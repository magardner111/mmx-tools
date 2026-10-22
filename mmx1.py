"""
Mega Man X1 (SNES, USA) ROM reader.

A clean-room Python re-statement of what MegaEdX's MMXCore.cpp knows about the
X1 ROM format, so we can poke at the data directly. Only X1 (type 0) for now.

Level graphics hierarchy (smallest -> largest):
  tile   8x8 px, 4bpp SNES planar, lives in VRAM
  map    16x16 px = 2x2 tiles (4 SNES BG tilemap words)
  block  32x32 px = 2x2 maps  (4 map indices)
  scene  256x256 px = 8x8 blocks (64 block indices)
  layout W x H scenes, RLE-compressed list of scene indices
"""
import struct
from pathlib import Path

HERE = Path(__file__).parent

# SNES (LoROM, FastROM bank $80+) addresses of the per-level pointer tables.
P_LAYOUT   = 0x868D24  # 3-byte long pointers, one per level
P_SCENES   = 0x868D93
P_BLOCKS   = 0x868E02
P_MAPS     = 0x868E71
P_COLLIS   = 0x868EE0
P_BLAYOUT  = 0x868F4F  # background (BG2) versions
P_BSCENES  = 0x868FBE
P_BBLOCKS  = 0x86902D
P_CHECKP   = 0x86A780
P_PALETT   = 0x868133
P_FONT     = 0x86F744
P_GFXCFG   = 0x86F56F
P_GFXPOS   = 0x86F6F7
P_EVENTS   = 0x8582C2
P_BORDERS  = 0x86E4E2
P_LOCKS    = 0x86ECD0

# PC (file) offsets used directly by MegaEdX
DYN_TILE_TABLE    = 0x321D5   # per-checkpoint tile uploads
DYN_PALETTE_TABLE = 0x32260   # per-checkpoint palette uploads

NUM_LEVELS = 13

# ROM expansion (see expand.py)
ORIG_SIZE = 0x180000
EXPANDED_HEADER_PC = ORIG_SIZE + 0x8000 - 0x40
EXPANDED_MARKER = b"EXPANDED ROM \x00"
EXPANDED_EVENT_TABLE = 0xFFE0          # word ptrs in the event bank, one per level

LEVEL_NAMES = [
    "Intro Highway", "Launch Octopus", "Sting Chameleon", "Armored Armadillo",
    "Flame Mammoth", "Storm Eagle", "Spark Mandrill", "Boomer Kuwanger",
    "Chill Penguin", "Sigma 1", "Sigma 2", "Sigma 3", "Sigma 4",
]

# Collision byte per 16x16 map. Inferred by grouping every placed map by its
# collision value and eyeballing them (collision_survey.py); confidence noted.
COLLISION = {
    0x00: "air",
    **{v: "slope" for v in range(0x01, 0x0D)},  # 01-04 steep pairs, 05-0C 4-step gentle slopes (high)
    0x0D: "water (submerged)",                   # high: only in Launch Octopus water
    0x0E: "water surface",                       # high
    0x12: "ladder?",                             # medium: horizontal rung strips
    0x13: "ladder top?",                         # medium
    0x33: "conveyor?",                           # medium: Flame Mammoth belts
    0x3B: "solid",                               # high: ~65k placements, generic ground/walls
    0x3F: "spikes (instant death)",              # high: spike tiles in Armadillo/Mandrill/Sigma
}
# 0x34-0x3E are also solid (ground, walls, pipes); the low nibble probably picks
# a surface variant (sound, dust, wall-slide). 0x41+ appear only 1-4 times and
# look like unused or mismatched maps.


def collision_name(v):
    if v in COLLISION:
        return COLLISION[v]
    if 0x34 <= v <= 0x3E:
        return f"solid (variant {v:02X})"
    return f"unknown {v:02X}"


# Work-RAM addresses (X1) used by MegaEdX's emulator overlay and Docs/mmx1_Ram.txt.
RAM = {
    "camera_x": 0x7E1E6A, "camera_y": 0x7E1E6C,
    "border_left": 0x7E1E5E, "border_right": 0x7E1E60,
    "border_top": 0x7E1E68, "border_bottom": 0x7E1E6E,
    "x_pos": 0x7E0BAD, "y_pos": 0x7E0BB0,
    "object_set": 0x7E1F08, "tile_set": 0x7E1F09, "palette_set": 0x7E1F0A,
    "level": 0x7E1F7A, "checkpoint": 0x7E1F81,
    # alternate-stage flags (named after the stage they change): low bytes of the weapon words of Launch
    # Octopus, Storm Eagle and Chill Penguin, whose defeat changes that stage (?). Not those bosses' beaten flags.
    "flag_sting_chameleon": 0x7E1F87, "flag_spark_mandrill": 0x7E1F8F,
    "flag_flame_mammoth": 0x7E1F95,
    "palette_ram": 0x7E0300,
    "map_placing": 0x7E2000,        # ..7EA600
    "bg_map_placing": 0x7EA600,     # ..7EE800
    "level_layout": 0x7EE800,       # ..7EEC00 (decompressed scene grid)
    "bg_layout": 0x7EEC00,          # ..7EF000
}
# Camera-lock entries write to these RAM words (border registers):
LOCK_TARGETS = {0x1E5E: "left", 0x1E60: "right", 0x1E68: "top", 0x1E6E: "bottom"}


def snes2pc(addr: int) -> int:
    """LoROM: banks hold 32KB at $8000-$FFFF."""
    return ((addr & 0x7F0000) >> 1) | (addr & 0x7FFF)


def pc2snes(off: int) -> int:
    return 0x800000 | ((off & 0x3F8000) << 1) | 0x8000 | (off & 0x7FFF)


def snes_color(c: int):
    """15-bit BGR555 -> (r, g, b) 8-bit."""
    r, g, b = c & 0x1F, (c >> 5) & 0x1F, (c >> 10) & 0x1F
    return (r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2)


def decode_4bpp(tile: bytes):
    """32-byte SNES 4bpp planar tile -> 64 palette indices (row-major)."""
    out = []
    for y in range(8):
        p0, p1, p2, p3 = tile[y*2], tile[y*2+1], tile[y*2+16], tile[y*2+17]
        for x in range(8):
            s = 7 - x
            out.append(((p0 >> s) & 1) | ((p1 >> s) & 1) << 1 |
                       ((p2 >> s) & 1) << 2 | ((p3 >> s) & 1) << 3)
    return out


def x1_decompress(rom: bytes, pos: int, size: int) -> bytes:
    """
    X1's graphics 'RLE': for every 8 output bytes there's a control byte and a
    fill byte. Each control bit (MSB first) = 1 -> take a literal from the
    stream, 0 -> emit the fill byte.
    """
    out = bytearray()
    for _ in range(size >> 3):
        control, fill = rom[pos], rom[pos + 1]
        pos += 2
        for _ in range(8):
            if control & 0x80:
                out.append(rom[pos]); pos += 1
            else:
                out.append(fill)
            control = (control << 1) & 0xFF
    return bytes(out)


class Event:
    __slots__ = ("block", "match", "type", "x", "y", "id", "sub", "flag")

    def copy(self):
        e = Event()
        for k in self.__slots__:
            setattr(e, k, getattr(self, k))
        return e

    def __repr__(self):
        return (f"Event(blk={self.block:02X} type={self.type} id={self.id:02X} "
                f"sub={self.sub:02X} x={self.x:04X} y={self.y:04X} match={self.match:02X})")


class MMX1:
    def __init__(self, path):
        """path: a ROM file, or the ROM's bytes."""
        data = path if isinstance(path, (bytes, bytearray)) else Path(path).read_bytes()
        self.rom = bytearray(data)
        if len(self.rom) % 0x8000 == 0x200:   # strip copier header
            self.rom = self.rom[0x200:]
        title = self.rom[0x7FC0:0x7FD5].decode("ascii", "replace")
        if not title.startswith("MEGAMAN X "):
            raise ValueError(f"not Mega Man X1: {title!r}")
        self.title = title.strip()
        # MegaEdX-style expansion: +1MB, marker at the end of the first new bank
        hdr = EXPANDED_HEADER_PC
        self.expanded = (len(self.rom) == 0x280000 and self.rom[0x7FD7] == 0xC and
                         self.rom[hdr:hdr + 14] == EXPANDED_MARKER)
        self.expanded_version = self.w(hdr + 0xE) if self.expanded else 0
        self.event_bank = 0xB2 if self.expanded else P_EVENTS >> 16
        self.checkpoint_bank = 0x93 if self.expanded else P_CHECKP >> 16
        self.lock_bank = 0xBB if self.expanded else None

    # --- raw readers -----------------------------------------------------
    def b(self, off):  return self.rom[off]
    def w(self, off):  return struct.unpack_from("<H", self.rom, off)[0]
    def l(self, off):  return self.w(off) | self.rom[off + 2] << 16
    def sb(self, a):   return self.b(snes2pc(a))
    def sw(self, a):   return self.w(snes2pc(a))
    def sl(self, a):   return self.l(snes2pc(a))

    # --- per-level pointers ---------------------------------------------
    def level_ptrs(self, level, background=False):
        t = (P_BLAYOUT, P_BSCENES, P_BBLOCKS) if background else (P_LAYOUT, P_SCENES, P_BLOCKS)
        return dict(
            layout=snes2pc(self.sl(t[0] + level * 3)),
            scenes=snes2pc(self.sl(t[1] + level * 3)),
            blocks=snes2pc(self.sl(t[2] + level * 3)),
            maps=snes2pc(self.sl(P_MAPS + level * 3)),
            collision=snes2pc(self.sl(P_COLLIS + level * 3)),
        )

    # --- layout ----------------------------------------------------------
    def layout(self, level, background=False):
        """
        Format: width, height, scenesUsed, then (ctrl, scene) pairs until ctrl=0xFF.
        ctrl & 0x7F = run length. If bit 7 clear, scene index increments each step
        (a 'sequential' run); if set, the same scene repeats.
        """
        p = self.level_ptrs(level, background)["layout"]
        width, height, used = self.rom[p], self.rom[p + 1], self.rom[p + 2]
        p += 3
        cells = []
        while (ctrl := self.rom[p]) != 0xFF:
            scene = self.rom[p + 1]
            p += 2
            for _ in range(ctrl & 0x7F):
                cells.append(scene)
                if not ctrl & 0x80:
                    scene = (scene + 1) & 0xFF
        return width, height, used, cells

    # --- events ----------------------------------------------------------
    def events_offset(self, level):
        table = (self.event_bank << 16 | EXPANDED_EVENT_TABLE) if self.expanded else P_EVENTS
        return snes2pc(self.sw(table + level * 2) | self.event_bank << 16)

    def events_size(self, level):
        """Bytes currently used by this level's event stream (incl. terminator)."""
        p = start = self.events_offset(level)
        block, nxt = 0xFF, self.rom[p]; p += 1
        while block != nxt and block < 0x100:
            block = nxt
            while True:
                last = self.rom[p + 6] & 0x80
                p += 7
                if last:
                    break
            nxt = self.rom[p]; p += 1
        return p - start

    # original event-stream sizes per stage (= the space available on an unexpanded ROM)
    ORIG_EVENT_SIZE = [0x2C8, 0x211, 0x250, 0x4B3, 0x2EA, 0x32C, 0x2E2, 0x260, 0x2D2, 0x37F, 0x254, 0x2B2, 0x27]

    def events_capacity(self, level):
        """How many bytes we may write without clobbering something else."""
        return 0x800 if self.expanded else self.ORIG_EVENT_SIZE[level]

    def write_events(self, level, events):
        """
        Re-serialize a level's events (same encoding as MegaEdX SaveEvents):
        groups sorted by e.block, end bit on each group's last record, then the
        last block id repeated as terminator. Refuses to grow past capacity.
        """
        if not events:
            raise ValueError("a stage needs at least one event")
        groups = {}
        for e in events:
            groups.setdefault(e.block, []).append(e)
        out = bytearray()
        last = 0
        for blk in sorted(groups):
            out.append(blk); last = blk
            for i, e in enumerate(groups[blk]):
                end = 0x4 if i == len(groups[blk]) - 1 else 0
                flag = (e.flag & 0x3) | end
                out += struct.pack("<BHBBH", (e.match << 2) | e.type, e.y, e.id, e.sub,
                                   (flag << 13) | (e.x & 0x1FFF))
        out.append(last)
        cap = self.events_capacity(level)
        if len(out) > cap:
            raise ValueError(f"events need {len(out)} bytes, only {cap} available"
                             + ("" if self.expanded else " (expand the ROM first)"))
        p = self.events_offset(level)
        self.rom[p:p + len(out)] = out
        return len(out)

    def events(self, level):
        """
        Events are grouped by 'block id' (the column of the level, in 256px units
        roughly). Stream: [blockId] then 7-byte records until a record's flag has
        bit 2 set, then next [blockId]; stops when the id repeats.
          byte0: type (low 2 bits) | match (upper 6)
          word : y
          byte : id
          byte : subId
          word : x (low 13 bits) | flag (top 3 bits; 0x4 = last in group)
        """
        p = self.events_offset(level)
        out = []
        block, nxt = 0xFF, self.rom[p]; p += 1
        while block != nxt and block < 0x100:
            block = nxt
            while True:
                e = Event()
                t = self.rom[p]
                e.block, e.type, e.match = block, t & 3, t >> 2
                e.y = self.w(p + 1)
                e.id, e.sub = self.rom[p + 3], self.rom[p + 4]
                xw = self.w(p + 5)
                e.x, e.flag = xw & 0x1FFF, xw >> 13
                p += 7
                out.append(e)
                if e.flag & 4:
                    break
            nxt = self.rom[p]; p += 1
        return out

    # --- checkpoints -----------------------------------------------------
    CHECKPOINT_FIELDS = ["objLoad", "tileLoad", "palLoad"]
    CHECKPOINT_WORDS = ["chX", "chY", "camX", "camY", "bkgX", "bkgY",
                        "minX", "maxX", "minY", "maxY", "forceX", "forceY"]

    def checkpoint_offset(self, level, n):
        # NB the tables themselves always sit at $86A780; only the record bank moves
        base = self.sw(P_CHECKP + level * 2)
        return snes2pc(self.checkpoint_bank << 16 | ((P_CHECKP & 0xFFFF) + self.sw(P_CHECKP + base + n * 2)))

    def checkpoint(self, level, n):
        p = self.checkpoint_offset(level, n)
        cp = {"_pc": p}
        for f in self.CHECKPOINT_FIELDS:
            cp[f] = self.rom[p]; p += 1
        for f in self.CHECKPOINT_WORDS:
            cp[f] = self.w(p); p += 2
        cp["scroll"], cp["telDwn"] = self.rom[p], self.rom[p + 1]
        return cp

    def write_checkpoint(self, level, n, **fields):
        """In-place edit of a checkpoint record (fixed size, always safe)."""
        p = self.checkpoint_offset(level, n)
        layout = [(f, 1) for f in self.CHECKPOINT_FIELDS] + \
                 [(f, 2) for f in self.CHECKPOINT_WORDS] + [("scroll", 1), ("telDwn", 1)]
        for name, size in layout:
            if name in fields:
                v = fields.pop(name)
                if size == 1: self.rom[p] = v & 0xFF
                else: struct.pack_into("<H", self.rom, p, v & 0xFFFF)
            p += size
        if fields:
            raise KeyError(f"unknown checkpoint fields: {list(fields)}")

    # --- camera locks ----------------------------------------------------
    def lock_offset(self, level, index):
        if self.expanded and self.expanded_version >= 4:
            return snes2pc(self.lock_bank << 16 | (0x8000 + level * 0x800 + index * 0x20))
        borders = self.sw(P_BORDERS + level * 2) | (P_BORDERS & 0xFF0000)
        return snes2pc(self.sw(borders + index * 2) | (P_BORDERS & 0xFF0000))

    def camera_lock(self, level, index):
        """
        A camera-lock region, referenced by event type 2 / id 0x00 / sub = index.
        While X is inside [left,right] x [top,bottom] the listed RAM border
        registers are written (that's what stops the camera scrolling).
          original: 4 words, then 1-byte indices into $86ECD0 (4 bytes each:
                    RAM addr, value), 0-terminated
          expanded: 4 words, then up to 6 inline (RAM addr, value) pairs, 0-terminated
        """
        p = self.lock_offset(level, index)
        right, left, bottom, top = struct.unpack_from("<4H", self.rom, p)
        locks = []
        q = p + 8
        if self.expanded and self.expanded_version >= 4:
            while len(locks) < 6 and (addr := self.w(q)):
                locks.append((addr, self.w(q + 2))); q += 4
        else:
            pl = snes2pc(P_LOCKS)
            while (i := self.rom[q]):
                o = pl + (i - 1) * 4
                locks.append((self.w(o), self.w(o + 2))); q += 1
        return dict(index=index, _pc=p, left=left, right=right, top=top, bottom=bottom,
                    locks=[(a, v, LOCK_TARGETS.get(a, "?")) for a, v in locks])

    def camera_locks(self, level):
        idx = sorted({e.sub for e in self.events(level) if e.type == 2 and e.id == 0})
        return [self.camera_lock(level, i) for i in idx]

    def write_camera_lock_box(self, level, index, left=None, right=None, top=None, bottom=None):
        """Move/resize a lock's trigger box in place. (Lock values: original
        ROM shares them between levels via the index table, so not edited here.)"""
        p = self.lock_offset(level, index)
        cur = list(struct.unpack_from("<4H", self.rom, p))
        for i, v in enumerate((right, left, bottom, top)):
            if v is not None: cur[i] = v
        struct.pack_into("<4H", self.rom, p, *cur)

    # --- collision -------------------------------------------------------
    def collision(self, level, map_index):
        return self.rom[self.level_ptrs(level)["collision"] + map_index]

    def num_checkpoints(self, level):
        # MegaEdX counts them from checkpoint-trigger events (type 2, id 0x2/0xB)
        n = 1
        for e in self.events(level):
            if e.type == 2 and e.id in (0x2, 0xB):
                n = max(n, (e.sub & 0xF) + 1)
        return n

    # --- palettes --------------------------------------------------------
    def palette(self, level, checkpoint=0):
        pal = [0] * 256
        cfg = snes2pc(self.sw(P_PALETT + level * 2 + 0x60) | 0x860000)
        count = self.rom[cfg]
        base = snes2pc(self.w(cfg + 1) | 0x850000)
        for i in range(count):
            pal[i] = self.w(base + i * 2)
        # dynamic palettes chosen by checkpoint.palLoad
        sel = self.checkpoint(level, checkpoint)["palLoad"]
        T = DYN_PALETTE_TABLE
        for i in range(sel + 1):
            idx = self.w(T + self.w(T + level * 2) + i * 2)
            while (cp := self.w(T + idx)) != 0xFFFF:
                dst = self.w(T + idx + 2) & 0xFF
                src = snes2pc(0x850000 | cp)
                for j in range(16):
                    pal[dst + j] = self.w(src + j * 2)
                idx += 3
        return [snes_color(c) for c in pal]

    # --- VRAM / tiles ----------------------------------------------------
    def vram(self, level, checkpoint=0):
        vram = bytearray(0x10000)
        vram[:0x200] = (HERE / "vrambase.bin").read_bytes()
        # main compressed tileset
        cfg = snes2pc(self.sw(P_GFXCFG + level * 2 + 4) | 0x860000)
        gfx_id = self.rom[cfg]
        size = self.w(cfg + 1)
        dest = ((self.w(cfg + 3) << 1) - 0x2000) & 0xFFFF  # VRAM word addr -> byte offset; wraps like the C++ WORD
        src = snes2pc(self.sl(P_GFXPOS + gfx_id * 5 + 2))
        data = x1_decompress(self.rom, src, size)
        vram[dest:dest + len(data)] = data
        # uncompressed per-checkpoint tile uploads
        sel = self.checkpoint(level, checkpoint)["tileLoad"]
        T = DYN_TILE_TABLE
        for i in range(sel + 1):
            main = self.w(T + self.w(T + level * 2) + i * 2)
            sz = self.w(T + main)
            if not sz:
                continue
            d = ((self.w(T + main + 2) << 1) - 0x2000) & 0xFFFF
            a = self.l(T + main + 4)
            if a != 0x7F0000:
                s = snes2pc(a)
                vram[d:d + sz] = self.rom[s:s + sz]
        return vram


def snes_checksum(rom: bytes) -> int:
    """
    SNES internal checksum: 16-bit sum of all bytes, with the ROM mirrored up to
    the next power of two. X1 is 1.5MB = 1MB + 0.5MB, so the last 0.5MB counts twice.
    The checksum/complement bytes themselves are summed as FF FF 00 00.
    """
    rom = bytearray(rom)
    rom[0x7FDC:0x7FE0] = b"\xFF\xFF\x00\x00"
    size = len(rom)
    p2 = 1 << (size.bit_length() - 1)
    if p2 == size:
        return sum(rom) & 0xFFFF
    rest = rom[p2:]
    return (sum(rom[:p2]) + sum(rest) * (p2 // len(rest))) & 0xFFFF


def save_rom(g: "MMX1", path):
    """Write the (possibly edited) ROM with a corrected header checksum."""
    c = snes_checksum(g.rom)
    struct.pack_into("<HH", g.rom, 0x7FDC, c ^ 0xFFFF, c)
    Path(path).write_bytes(g.rom)
    return c
