"""
Recursive-descent 65816 disassembly of one routine (and the jump tables /
local subroutines it reaches). Prints a listing in address order with labels.

usage: python3 trace.py <snes_addr_hex> [--m16] [--x16] [--follow-jsr] [--follow-jsl]
"""
import sys
from mmx1 import MMX1, snes2pc
from disasm import disasm

ROM = "../Mega Man X (USA) (Rev 1).sfc"
BRANCHES = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"}


def read_table(rom, table, bank):
    """Jump-table entries: stop at a non-code pointer or when we run into code."""
    out, a = [], table
    lowest = 0xFFFF
    while (a & 0xFFFF) < lowest and len(out) < 64:
        v = rom[snes2pc(a)] | rom[snes2pc(a) + 1] << 8
        if v < 0x8000:
            break
        out.append(bank | v)
        lowest = min(lowest, v)
        a += 2
    return out


def trace(rom, entry, m8=True, x8=True, follow_jsr=True, follow_jsl=False):
    seen = {}          # addr -> (raw, text, info)
    labels = {entry: "entry"}
    calls = set()
    tables = {}
    work = [(entry, m8, x8)]
    visited = set()
    while work:
        a, m, x = work.pop()
        if (a, m, x) in visited:
            continue
        visited.add((a, m, x))
        for addr, raw, txt, info in disasm(rom, a, 400, m, x, stop=False):
            if addr in seen and addr != a:
                break
            seen[addr] = (raw, txt, info)
            mn = txt.split()[0]
            m, x = info["m8"], info["x8"]
            t = info.get("target")
            if mn in BRANCHES or mn in ("BRA", "BRL"):
                labels.setdefault(t, f"L{t & 0xFFFF:04X}")
                work.append((t, m, x))
                if mn in ("BRA", "BRL"):
                    break
            elif mn in ("JSR", "JSL"):
                if "table" in info:   # JSR (tbl,X)
                    ents = read_table(rom, info["table"], addr & 0xFF0000)
                    tables[info["table"]] = ents
                    for i, e in enumerate(ents):
                        labels.setdefault(e, f"S{e & 0xFFFF:04X}")
                        work.append((e, m, x))
                elif t is not None:
                    calls.add(t)
                    local = (mn == "JSR" and follow_jsr) or (mn == "JSL" and follow_jsl)
                    if local:
                        labels.setdefault(t, f"F{t & 0xFFFF:04X}")
                        work.append((t, m, x))
            elif mn in ("JMP", "JML"):
                if "table" in info:
                    ents = read_table(rom, info["table"], addr & 0xFF0000)
                    tables[info["table"]] = ents
                    for e in ents:
                        labels.setdefault(e, f"S{e & 0xFFFF:04X}")
                        work.append((e, m, x))
                elif t is not None and (t & 0xFF0000) == (entry & 0xFF0000) and mn == "JMP":
                    labels.setdefault(t, f"J{t & 0xFFFF:04X}")
                    work.append((t, m, x))
                break
            elif mn in ("RTS", "RTL", "RTI", "STP"):
                break
    return seen, labels, calls, tables


def listing(rom, entry, notes=None, **kw):
    seen, labels, calls, tables = trace(rom, entry, **kw)
    notes = notes or {}
    lines = []
    prev_end = None
    for a in sorted(seen):
        raw, txt, info = seen[a]
        if prev_end is not None and a != prev_end:
            lines.append("")
        if a in labels:
            lines.append(f"{labels[a]}:")
        t = info.get("target")
        if t in labels:
            txt = txt.rsplit(" ", 1)[0] + " " + labels[t]
        note = notes.get(a) or annotate(txt)
        lines.append(f"  {a:06X}  {raw.hex(' '):<12} {txt:<22}{('; ' + note) if note else ''}")
        prev_end = (a & 0xFF0000) | ((a + len(raw)) & 0xFFFF)
    for tb, ents in tables.items():
        lines.append(f"\ntable {tb:06X}: " + ", ".join(labels.get(e, f'{e:06X}') for e in ents))
    ext = sorted(c for c in calls if c not in labels)
    if ext:
        lines.append("external calls: " + ", ".join(f"{c:06X}" for c in ext))
    return "\n".join(lines)


# What we know (or strongly suspect) about the enemy object's direct-page slot
# and a few globals. Refined as we trace; '?' = unconfirmed.
DP = {
    "$00": "active", "$01": "state", "$02": "substate", "$03": "substate2?",
    "$05": "x.lo?", "$27": "HP", "$28": "dmg/contact?",
}
GLOBAL = {
    "$0BAD": "X.xpos", "$0BB0": "X.ypos", "$0B9C": "?", "$0BAA": "X.step",
    "$1F7A": "level", "$1F86": "weapon flags (bit 6 = stage boss beaten)", "$1E4D": "screen left",
    "$1F0C": "boss defeated", "$1F0E": "HUD boss", "$1F10": "HUD boss bar state",
}


def annotate(txt):
    parts = txt.split()
    if len(parts) < 2:
        return ""
    op = parts[1].split(",")[0]
    if op in DP:
        return DP[op]
    if op in GLOBAL:
        return GLOBAL[op]
    return ""


if __name__ == "__main__":
    g = MMX1(ROM)
    a = int(sys.argv[1], 16)
    print(listing(g.rom, a, m8="--m16" not in sys.argv, x8="--x16" not in sys.argv,
                  follow_jsr="--no-jsr" not in sys.argv, follow_jsl="--follow-jsl" in sys.argv))
