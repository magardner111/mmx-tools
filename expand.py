"""
Mega Man X1 ROM expansion: a line-by-line port of MegaEdX MMXCore::ExpandROM()
(type 0 / X1 only), producing a ROM MegaEdX itself would recognize (version 4).

usage: python3 expand.py <in.sfc> <out.sfc>

What it does (1.5MB -> 2.5MB):
  PC 0x180000 bank $B0  FG layouts, 0x800 per level
  PC 0x188000 bank $B1  BG layouts, 0x800 per level      (+ expansion header at $B0:FFC0)
  PC 0x190000 bank $B2  events, 0x800 per level; level ptr table at $B2:FFE0
  PC 0x198000 $B3-$BA   scenes, 0x40 scenes (0x4000 bytes) per level
  PC 0x1D8000 bank $BB  camera locks, flattened: 0x800/level, 0x20/lock
  $93:B000              checkpoint records (copied), with a new pointer table at $86:A780
  plus 65816 patches so the game's loaders read from the new banks.
"""
import struct
import sys
from pathlib import Path

from mmx1 import (P_LAYOUT, P_BLAYOUT, P_SCENES, P_EVENTS, P_CHECKP, P_BORDERS,
                  P_LOCKS, NUM_LEVELS, ORIG_SIZE, snes2pc, pc2snes, save_rom, MMX1)

VERSION = 4
HEADER_SIZE = 0x40
MARKER = b"EXPANDED ROM \x00"  # 13 chars + NUL, as strcpy_s writes it


class Patcher:
    def __init__(self, rom: bytearray):
        self.rom = rom

    def b(self, a, v=None):
        o = snes2pc(a)
        if v is None: return self.rom[o]
        self.rom[o] = v & 0xFF

    def w(self, a, v=None):
        o = snes2pc(a)
        if v is None: return struct.unpack_from("<H", self.rom, o)[0]
        struct.pack_into("<H", self.rom, o, v & 0xFFFF)

    def d(self, a, v):
        struct.pack_into("<I", self.rom, snes2pc(a), v & 0xFFFFFFFF)

    def l(self, a):
        o = snes2pc(a)
        return self.rom[o] | self.rom[o + 1] << 8 | self.rom[o + 2] << 16

    def put3(self, a, v):
        o = snes2pc(a)
        self.rom[o:o + 3] = struct.pack("<I", v)[:3]


def _event_stream_len(rom, p):
    count = 1
    block, nxt = 0xFF, rom[p]; p += 1
    while block != nxt and block < 0x100:
        block = nxt
        while True:
            done = rom[p + 6] & 0x80
            p += 7; count += 7
            if done: break
        nxt = rom[p]; p += 1; count += 1
    return count


def expand(rom: bytearray, faithful=False) -> bytearray:
    """faithful=True reproduces MegaEdX byte-for-byte, including its Sigma 3 checkpoint bug."""
    if rom[0x7FD7] != 0xB or len(rom) != ORIG_SIZE:
        raise ValueError("expects an unexpanded 1.5MB Mega Man X1 ROM")
    # checkpoints each level's events refer to, read before anything moves
    g = MMX1.__new__(MMX1); g.rom = bytearray(rom); g.expanded = False
    g.event_bank = P_EVENTS >> 16; g.checkpoint_bank = P_CHECKP >> 16
    needed_checkpoints = [g.num_checkpoints(i) for i in range(NUM_LEVELS)]

    rom = bytearray(rom) + b"\xFF" * 0x100000
    P = Patcher(rom)
    romSize = ORIG_SIZE
    numLevels = NUM_LEVELS
    eventBank = P_EVENTS >> 16

    # --- header -----------------------------------------------------------
    h = romSize + 0x8000 - HEADER_SIZE
    rom[h:h + len(MARKER)] = MARKER
    struct.pack_into("<HHHH", rom, h + 0xE, VERSION, 0x800, 0x800, 0x10)

    cur = romSize

    def layout_len(off):
        n = 3
        while rom[off + n] != 0xFF: n += 1
        return n + 1

    # --- copy FG and BG layouts -------------------------------------------
    for table in (P_LAYOUT, P_BLAYOUT):
        for i in range(numLevels):
            src = snes2pc(P.l(table + i * 3))
            n = layout_len(src)
            assert n <= 0x800
            rom[cur + i * 0x800:cur + i * 0x800 + n] = rom[src:src + n]
        cur += 0x10 * 0x800

    # --- copy events --------------------------------------------------------
    for i in range(numLevels):
        src = snes2pc(P.w(P_EVENTS + i * 2) | eventBank << 16)
        n = _event_stream_len(rom, src)
        assert n <= 0x800
        rom[cur + i * 0x800:cur + i * 0x800 + n] = rom[src:src + n]
    cur += 0x10 * 0x800

    # --- copy scenes ----------------------------------------------------------
    for i in range(numLevels):
        src = snes2pc(P.l(P_SCENES + i * 3))
        s = rom[snes2pc(P.l(P_LAYOUT + i * 3)) + 2]
        base = cur + i * 0x80 * 0x80
        rom[base:base + s * 0x80] = rom[src:src + s * 0x80]
        rom[base + s * 0x80:base + 0x80 * 0x80] = bytes(0x80 * 0x80 - s * 0x80)
    cur += 0x10 * 0x80 * 0x80

    # --- sanity: event-bank loader instructions (LDA #$85) are where we expect
    rev0 = all(P.w(a) == 0x85A9 for a in (0x80DB92, 0x80DBD9, 0x80DD4C))
    rev1 = all(P.w(a) == 0x85A9 for a in (0x80DB7C, 0x80DBC3, 0x80DD36))
    # (MegaEdX's check is looser: ANY one match per revision.)
    if not (rev0 or rev1):
        raise ValueError("event loader code not recognized (unknown revision or already patched)")
    if any(b != 0xFF for b in rom[snes2pc(0x80FF00):snes2pc(0x80FF00) + 0x90]):
        raise ValueError("free space at $80:FF00 is not empty")

    # --- remove copy-protection side effects (X1) ----------------------------
    P.b(0x81824E, 0x00)  # reset upgrades
    P.b(0x849FC7, 0x00)  # reset checkpoint
    P.b(0x84A41F, 0x00)  # 1UP drop resets stage

    # --- blank old events -------------------------------------------------------
    for i in range(numLevels):
        p = snes2pc(P.w(P_EVENTS + i * 2) | eventBank << 16)
        n = _event_stream_len(rom, p)
        rom[p:p + n] = b"\xFF" * n

    # --- repoint FG/BG layouts, blank old ---------------------------------------
    for table, base in ((P_LAYOUT, romSize), (P_BLAYOUT, romSize + 0x8000)):
        for i in range(numLevels):
            addr = pc2snes(base + i * 0x800)
            old = snes2pc(P.l(table + i * 3))
            q = old + 3
            while rom[q] != 0xFF:
                rom[q] = 0xFF; q += 1
            P.put3(table + i * 3, addr)

    # --- patch event loader to new bank + pointer table at $xx:FFE0 ------------
    eventBank = pc2snes(romSize + 2 * 0x8000) >> 16
    offsetAddr = pc2snes(romSize + 3 * 0x8000 - 2 * 0x10)
    if rev0:
        for a in (0x80DB92, 0x80DBD9, 0x80DD4C): P.w(a, 0xA9 | eventBank << 8)
        P.w(0x80DB9E, offsetAddr)
    else:
        for a in (0x80DB7C, 0x80DBC3, 0x80DD36): P.w(a, 0xA9 | eventBank << 8)
        P.w(0x80DB88, offsetAddr)
    for i in range(numLevels):
        P.w(offsetAddr + i * 2, pc2snes(romSize + 3 * 0x8000 + i * 0x800))

    # --- repoint scenes, blank old, sceneUsed = 0x40 ---------------------------
    for i in range(numLevels):
        old = snes2pc(P.l(P_SCENES + i * 3))
        lay = snes2pc(P.l(P_LAYOUT + i * 3))
        s = rom[lay + 2]
        rom[old:old + s * 0x80] = b"\xFF" * (s * 0x80)
        P.put3(P_SCENES + i * 3, pc2snes(romSize + 3 * 0x8000 + i * 0x80 * 0x80))
        rom[lay + 2] = 0x40

    # --- checkpoints: copy records to $93:B000, rebuild pointer table ----------
    checkpointBank = 0x93
    newBase = snes2pc(0x93AD00 + 0x300)
    pointers = bytearray(0x10 * 2 + 0x10 * 0x20)
    for j in range(0x10):
        struct.pack_into("<H", pointers, j * 2, (0x10 + j * 0x10) * 2)
    cbo = (0xAD00 + 0x300 - (P_CHECKP & 0xFFFF)) & 0xFFFF
    for i in range(numLevels):
        lv = P.w(P_CHECKP + i * 2)
        end = 0x0072
        for j in range(numLevels):
            t = P.w(P_CHECKP + j * 2)
            if lv < t < end: end = t
        p, pend = snes2pc(P_CHECKP + lv), snes2pc(P_CHECKP + end)
        if not faithful:
            # FIX: events may reference checkpoint slots past this level's list; the
            # original game then reads the next level's entries (Sigma 3 cp 6 is
            # Sigma 4 cp 0). MegaEdX drops those -> garbage. Keep them.
            pend = max(pend, p + 2 * needed_checkpoints[i])
        count = 0
        while p < pend and count < 0x10:
            v = struct.unpack_from("<H", rom, p)[0]; p += 2
            struct.pack_into("<H", pointers, (0x10 + i * 0x10 + count) * 2, (cbo + v) & 0xFFFF)
            count += 1
        o = (0x10 + i * 0x10 + count) * 2
        pointers[o:o + (0x10 - count) * 2] = b"\xFF" * ((0x10 - count) * 2)
    src = snes2pc(P_CHECKP)
    rom[newBase:newBase + 0x56E] = rom[src:src + 0x56E]
    rom[src:src + len(pointers)] = pointers

    # move the checkpoint base routine to $80:FF00 and wrap bank switches
    a, b = snes2pc(0x80FF00), snes2pc(0x80E68E)
    rom[a:a + 0x22] = rom[b:b + 0x22]
    rom[b:b + 0x22] = b"\xFF" * 0x22
    P.w(0x80FF22, 0xA9 | checkpointBank << 8); P.b(0x80FF24, 0x48); P.b(0x80FF25, 0xAB)  # LDA #$93 PHA PLB
    P.b(0x80FF26, 0x60)                                                                 # RTS
    for x in (0x809DA4, 0x80E602, 0x80E679): P.w(x, 0xFF00)
    # 1: restore bank $86, JSR $B117, RTS
    P.w(0x80FF27, 0xA9 | 0x06 << 8); P.b(0x80FF29, 0x48); P.b(0x80FF2A, 0xAB)
    P.b(0x80FF2B, 0x20); P.w(0x80FF2C, 0xB117); P.b(0x80FF2E, 0x60)
    P.w(0x809DD1, 0xFF27)
    # 2: SEP #$20, restore bank, REP #$20, JSL $80E301?, RTS
    P.b(0x80FF2F, 0xE2); P.b(0x80FF30, 0x20)
    P.w(0x80FF31, 0xA9 | 0x06 << 8); P.b(0x80FF33, 0x48); P.b(0x80FF34, 0xAB)
    P.b(0x80FF35, 0xC2); P.b(0x80FF36, 0x20)
    P.d(0x80FF37, 0x0180E322); P.b(0x80FF3B, 0x60)
    P.d(0x80E66D, 0xEAFF2F20)
    # 3: original routine tail restores bank then PLP RTL
    P.b(0x80E68C, 0xE2); P.b(0x80E68D, 0x20)
    P.w(0x80E68E, 0xA9 | 0x06 << 8); P.b(0x80E690, 0x48); P.b(0x80E691, 0xAB)
    P.b(0x80E692, 0xC2); P.b(0x80E693, 0x20)
    P.b(0x80E694, 0x28); P.b(0x80E695, 0x6B)

    # --- camera locks: flatten to bank $BB ---------------------------------------
    lockBank = pc2snes(cur) >> 16
    rom[cur:cur + 0x8000] = bytes(0x8000)
    pLocks = snes2pc(P_LOCKS)
    bank = P_BORDERS & 0xFF0000
    nextAddress = {}
    for i in range(numLevels):
        pB = P.w(P_BORDERS + i * 2) | bank
        pBNext = P.w(P_BORDERS + (i + 1) * 2) | bank
        if pB in nextAddress:
            pBNext = nextAddress[pB]
        elif pBNext in nextAddress:
            pBNext = pB
        nextAddress[pB] = pBNext
        for j in range((pBNext - pB) // 2 if pBNext > pB else 0):
            bo = snes2pc(P.w(pB + j * 2) | bank)
            dst = cur + i * 0x800 + j * 0x20
            rom[dst:dst + 8] = rom[bo:bo + 8]
            bo += 8
            k = 0
            while rom[bo]:
                off = (rom[bo] - 1) << 2
                rom[dst + 8 + k:dst + 8 + k + 4] = rom[pLocks + off:pLocks + off + 4]
                k += 4; bo += 1
            # MegaEdX zero-fills up to 0x18 with WORD writes (may write past 0x20 when k>0x18)
            while k < 0x18:
                rom[dst + 8 + k:dst + 10 + k] = b"\0\0"; k += 2
    cur += 0x8000

    # new lock-check routine (replaces the original index walk)
    P.w(0x81F6B6, P.w(0x81F6B6) - 2)
    code = bytearray()
    code += b"\x0A\x0A\x0A\x0A"                     # ASL x4
    code += b"\x8D\x00\x00"                         # STA $0000
    code += b"\xAD" + struct.pack("<H", 0x1F7A)     # LDA level
    code += b"\x29\xFF\x00\xEB\x0A\x0A\x0A"         # AND #$FF, XBA, ASL x3
    code += b"\x6D\x00\x00\x85\x04"                 # ADC $0000, STA $04
    code += b"\xC2\x30\xA6\x04"                     # REP #$30, LDX $04
    code += b"\xAD" + struct.pack("<H", 0x0BAD)     # LDA X pos
    code += bytes([0xDF, 0x00, 0x80, lockBank, 0xB0, 0x2F])  # CMP right, BCS
    code += bytes([0xDF, 0x02, 0x80, lockBank, 0x90, 0x29])  # CMP left,  BCC
    code += b"\xAD" + struct.pack("<H", 0x0BB0)     # LDA Y pos
    code += bytes([0xDF, 0x04, 0x80, lockBank, 0xB0, 0x20])  # CMP bottom, BCS
    code += bytes([0xDF, 0x06, 0x80, lockBank, 0x90, 0x1A])  # CMP top, BCC
    code += b"\xA9\x02\x00"                         # LDA #2
    code += b"\x8D" + struct.pack("<H", 0x1E52)     # STA $1E52
    code += bytes([0xBF, 0x08, 0x80, lockBank, 0xF0, 0x0E])  # loop: LDA addr,X; BEQ done
    code += b"\xA8\xE8\xE8"                         # TAY INX INX
    code += bytes([0xBF, 0x08, 0x80, lockBank])     # LDA value,X
    code += b"\xE8\xE8\x99\x00\x00\x80\xEC"         # INX INX STA $0000,Y BRA loop
    code += b"\xE2\x30\x60"                         # SEP #$30, RTS
    o = snes2pc(0x81F6C4)
    rom[o:o + len(code)] = code

    # event-ending routine: shift code down 4 bytes and turn 3-byte loads into long loads
    P.w(0x81F6B1, P.w(0x81F6B1) - 4)
    a = 0x81F722
    for shift, n in ((1, 0x41), (2, 0x36), (3, 0x20), (4, 0x15)):
        s_ = snes2pc(a - shift + 1); d_ = snes2pc(a - shift)
        rom[d_:d_ + n] = rom[s_:s_ + n]
    a += 0x0F
    for gap, lo in ((0, 0x00), (0x08, 0x02), (0x13, 0x04), (0x08, 0x06)):
        a += gap
        o = snes2pc(a)
        rom[o:o + 4] = bytes([0xBF, lo, 0x80, lockBank])
        a += 4
    for back, inc in ((0x2C, 3), (0x28, 1), (0x20, 2), (0x09, 1), (0x05, 1)):
        P.b(a - back, P.b(a - back) + inc)

    rom[0x7FD7] += 1   # header ROM size 0xB -> 0xC
    return rom


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    rom = bytearray(Path(src).read_bytes())
    out = expand(rom, faithful="--faithful" in sys.argv)

    class _G: pass
    g = _G(); g.rom = out
    c = save_rom(g, dst)
    print(f"wrote {dst} ({len(out):#x} bytes, checksum {c:04X})")
    MMX1(dst)  # re-open to confirm it's detected as expanded
