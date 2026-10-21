"""
Enemy graphics sets ("object sets") for Mega Man X1.

  $86ACEE + stage*2          -> offset of the stage's set list (offsets are from $86ACEE)
  list[n]                    -> offset of set n
  set                        -> 6-byte entries, terminated by $FF:
                                  graphics#, VRAM word address (2), palette pointer (2), palette slot
Loading a set ($80:B071) uploads each graphics block to VRAM, loads its palette into the slot,
and records tile base / palette in $7F:8200+gfx and $7F:8300+gfx, which enemy code reads.

Which set is active:
  * checkpoint `objLoad` = set loaded at stage start / respawn
  * type-2 trigger 15 (X position) / 18 (Y position): sub-id low digit = set loaded when X
    crosses it moving right (or down), high digit = moving left (or up)

Sets that grow are moved to free space at the end of bank $86 ($86FA44–$86FFEF).
"""
from collections import Counter
from dataclasses import dataclass

from mmx1 import MMX1, snes2pc
from sprites import sprite_ids, GFX_LIST

TABLE = 0x86ACEE
FREE_START, FREE_END = 0x86FA44, 0x86FFEF
SLOTS = (0x40, 0x50, 0x60, 0x70)
VRAM_LIMIT = 0x2000            # sprite VRAM ends at word $1FFF


@dataclass
class Entry:
    gfx: int
    vram: int      # VRAM word address; 0 = no tile upload (palette only) (?)
    pal: int       # palette pointer (offset into the $868133 palette table)
    slot: int      # sprite palette slot: $40/$50/$60/$70

    def bytes(self):
        return bytes([self.gfx, self.vram & 0xFF, self.vram >> 8, self.pal & 0xFF, self.pal >> 8, self.slot])


def _base(g):
    return snes2pc(TABLE)


def stage_list_offsets(g):
    b = _base(g)
    return [g.w(b + L * 2) for L in range(13)]


def set_count(g, L):
    los = stage_list_offsets(g)
    if L < 12:
        return (los[L + 1] - los[L]) // 2
    first = min(g.w(_base(g) + los[s] + n * 2) for s in range(12) for n in range((los[s + 1] - los[s]) // 2))
    return (first - los[12]) // 2


def set_pointer_addr(g, L, n):
    """PC offset of the word that points at set n of stage L."""
    return _base(g) + stage_list_offsets(g)[L] + n * 2


def read_set(g, L, n):
    k = _base(g) + g.w(set_pointer_addr(g, L, n))
    out = []
    while g.rom[k] != 0xFF and len(out) < 32:
        e = g.rom[k:k + 6]
        out.append(Entry(e[0], e[1] | e[2] << 8, e[3] | e[4] << 8, e[5]))
        k += 6
    return out


def gfx_words(g, gfx):
    return g.w(snes2pc(GFX_LIST) + gfx * 5) // 2


def write_set(g, L, n, entries):
    """Write set n of stage L: in place if it fits, otherwise relocate to free space in bank $86."""
    data = b"".join(e.bytes() for e in entries) + b"\xFF"
    ptr = set_pointer_addr(g, L, n)
    cur = _base(g) + g.w(ptr)
    old_len = len(read_set(g, L, n)) * 6 + 1
    if len(data) <= old_len:
        g.rom[cur:cur + len(data)] = data
        return "in place"
    start = allocate(g, len(data))
    if start is None:
        raise ValueError(f"no free space in bank $86 for a {len(entries)}-entry set")
    g.rom[start:start + len(data)] = data
    g.rom[ptr:ptr + 2] = (start - _base(g)).to_bytes(2, "little")
    if snes2pc(FREE_START) <= cur <= snes2pc(FREE_END):     # an earlier relocation: give its space back
        g.rom[cur:cur + old_len] = b"\xFF" * old_len
    return "moved"


def allocate(g, size):
    """First run of $FF in the free area big enough for `size` bytes (never touching a set's terminator)."""
    lo, hi = snes2pc(FREE_START), snes2pc(FREE_END)
    i = lo
    while i < hi:
        if g.rom[i] != 0xFF:
            i += 1
            continue
        j = i
        while j <= hi and g.rom[j] == 0xFF:
            j += 1
        # the first $FF after other data may be that data's terminator: never reuse it
        start = i + 1 if g.rom[i - 1] != 0xFF else i
        if j - start >= size:
            return start
        i = j
    return None


def free_bytes(g):
    lo, hi = snes2pc(FREE_START), snes2pc(FREE_END)
    return sum(1 for k in range(lo, hi + 1) if g.rom[k] == 0xFF)


# --- what's active where ----------------------------------------------------------------
def set_sources(g, L):
    """{set#: [descriptions]} — where each set gets loaded."""
    out = {}
    for c in range(g.num_checkpoints(L)):
        out.setdefault(g.checkpoint(L, c)["objLoad"], []).append(f"checkpoint {c}")
    for e in g.events(L):
        if e.type == 2 and e.id in (0x15, 0x18):
            axis = "X" if e.id == 0x15 else "Y"
            fwd, back = ("→", "←") if e.id == 0x15 else ("↓", "↑")
            out.setdefault(e.sub & 0xF, []).append(f"{fwd} trigger {axis}={e.x if e.id == 0x15 else e.y}")
            out.setdefault(e.sub >> 4, []).append(f"{back} trigger {axis}={e.x if e.id == 0x15 else e.y}")
    return out


def active_set_at(g, L, x, events=None):
    """Set active at X when playing left-to-right from the start (horizontal triggers only)."""
    cur = g.checkpoint(L, 0)["objLoad"]
    src = "stage start (checkpoint 0)"
    for c in range(1, g.num_checkpoints(L)):
        cp = g.checkpoint(L, c)
        if cp["chX"] <= x:
            cur, src = cp["objLoad"], f"checkpoint {c}"
    evs = events if events is not None else g.events(L)
    trig = sorted((e for e in evs if e.type == 2 and e.id == 0x15 and e.x < x), key=lambda e: e.x)
    for t in trig:
        cur, src = t.sub & 0xF, f"trigger at X={t.x}"
    return cur, src


# --- helpers for choosing entries --------------------------------------------------------
def gfx_users(g):
    users = {}
    for i in range(1, 0x6C):
        users.setdefault(sprite_ids(g, i)[1], []).append(i)
    return users


def known_palettes(g):
    """gfx -> most common (palette pointer, slot) across all stages' sets."""
    seen = {}
    for L in range(13):
        for n in range(set_count(g, L)):
            for e in read_set(g, L, n):
                seen.setdefault(e.gfx, Counter())[(e.pal, e.slot)] += 1
    return {gf: c.most_common(1)[0][0] for gf, c in seen.items()}


def ranges(g, entries):
    return [(e, e.vram, e.vram + gfx_words(g, e.gfx)) for e in entries if e.vram]


def problems(g, entries):
    out = []
    rs = ranges(g, entries)
    for i, (a, s1, e1) in enumerate(rs):
        if e1 > VRAM_LIMIT:
            out.append(f"graphics {a.gfx:02X} runs past VRAM ${VRAM_LIMIT:04X} (ends ${e1:04X})")
        for b, s2, e2 in rs[i + 1:]:
            if s1 < e2 and s2 < e1:
                out.append(f"graphics {a.gfx:02X} and {b.gfx:02X} overlap in VRAM (${max(s1, s2):04X}–${min(e1, e2) - 1:04X})")
    slots = Counter(e.slot for e in entries)
    for s, c in slots.items():
        if c > 1:
            gf = ", ".join(f"{e.gfx:02X}" for e in entries if e.slot == s)
            out.append(f"palette slot ${s:02X} used by {c} entries ({gf}) — the last one loaded wins")
    return out


def free_vram(g, entries, words, skip=None):
    """Lowest tile-aligned VRAM word address with room for `words`: $1000–$1FFF first, then $0400–$0FFF."""
    used = sorted((s_, e_) for x, s_, e_ in ranges(g, entries) if x is not skip)
    for lo, hi in ((0x1000, VRAM_LIMIT), (0x0400, 0x1000)):
        pos = lo
        for s_, e_ in used:
            if e_ <= pos or s_ >= hi:
                continue
            if s_ - pos >= words:
                return pos
            pos = (max(pos, e_) + 0xF) & ~0xF
        if hi - pos >= words:
            return pos
    return None


def free_slot(entries, skip=None):
    used = {e.slot for e in entries if e is not skip}
    return next((s for s in SLOTS if s not in used), None)


# --- the simple, user-facing model: sections along the stage ------------------------------
@dataclass
class Section:
    start: int          # X where it begins (inclusive)
    end: int            # X where it ends (exclusive)
    set_no: int
    how: str            # what loads it


def sections(g, L, events=None):
    """Horizontal sections of the stage, in order, as seen playing left to right."""
    evs = events if events is not None else g.events(L)
    width = g.layout(L)[0] * 256
    trig = sorted((e for e in evs if e.type == 2 and e.id == 0x15), key=lambda e: e.x)
    out = []
    cur, how, x0 = g.checkpoint(L, 0)["objLoad"], "stage start", 0
    for t in trig:
        if t.x > x0:
            out.append(Section(x0, t.x, cur, how))
        cur, how, x0 = t.sub & 0xF, f"trigger at X={t.x}", t.x
    out.append(Section(x0, width, cur, how))
    return out


def other_sets(g, L, events=None):
    """Sets not reached by walking left-to-right (vertical triggers, respawns, going back)."""
    reached = {s.set_no for s in sections(g, L, events)}
    srcs = set_sources(g, L)
    return [(n, "; ".join(srcs.get(n, [])) or "not used by any trigger")
            for n in range(set_count(g, L)) if n not in reached]


def vram_use(g, entries):
    """(words used, words available) in the enemy-graphics VRAM areas ($0400–$1FFF)."""
    used = sum(min(b, VRAM_LIMIT) - a for _, a, b in ranges(g, entries))
    return used, VRAM_LIMIT - 0x0400


def add_graphics(g, L, n, gfx, known_pal):
    """Add graphics block `gfx` to set n with automatic VRAM / palette / slot. Returns a message."""
    entries = read_set(g, L, n)
    if any(e.gfx == gfx for e in entries):
        return f"graphics {gfx:02X} are already loaded in set {n}"
    words = gfx_words(g, gfx)
    vram = free_vram(g, entries, words)
    if vram is None:
        biggest = sorted(ranges(g, entries), key=lambda r: r[1] - r[2])[:3]
        hogs = ", ".join(f"graphics {e.gfx:02X} ({b - a} words)" for e, a, b in biggest)
        raise ValueError(f"Not enough free graphics space: graphics {gfx:02X} need {words} words. "
                         f"Remove something first — largest here: {hogs}.")
    pal, slot = known_pal.get(gfx, (0, None))
    if slot is None or any(e.slot == slot for e in entries):
        slot = free_slot(entries)
    if slot is None:
        raise ValueError("All 4 sprite palette slots are in use in this section. Remove an enemy first "
                         "(two different palettes can't share a slot).")
    write_set(g, L, n, entries + [Entry(gfx, vram, pal, slot)])
    return f"loaded graphics {gfx:02X} into set {n} (VRAM ${vram:04X}, palette slot ${slot:02X})"
