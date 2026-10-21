"""
Catalogue of X1 object/enemy routines.

The per-frame object update ($80:D530) does:
    LDA $0A ; ASL ; TAX ; JMP ($F8DD,X)
so object id N (the event id) dispatches through word[$80F8DD + 2N], which points
at a 'JSL routine / RTS' stub. Each routine is normally a state machine:
    LDX $01 ; JSR/JMP (table,X)       ; $01 = state (0,2,4,...)
with nested substate tables on $02 (and sometimes $03).

usage: python3 enemies.py            # table of all ids
       python3 enemies.py 2D         # full traced listing of one id
"""
import sys
from mmx1 import MMX1, snes2pc
from disasm import disasm
from trace import trace, listing

ROM = "../Mega Man X (USA) (Rev 1).sfc"
DISPATCH = 0x80F8DD     # + 2*id
NUM_IDS = 0x6B          # 107 entries, ids 1..0x6B
DATA_BANK = 0x86        # DB while object code runs: absolute,X tables live in bank $86

# Names confirmed by tracing + where they're placed (see ENEMY_AI.md)
NAMES = {
    0x2D: "Batton Bone (bat)",
}


def routine(g, i):
    stub = snes2pc(0x800000 | g.sw(DISPATCH + i * 2))
    if g.rom[stub] != 0x22:
        return None
    return g.l(stub + 1)


def init_constants(g, entry):
    """Follow the state-0 handler and report constants stored to object fields."""
    seen, labels, calls, tables = trace(g.rom, entry)
    # the first state table reached from the entry is the main one
    main = None
    for a in sorted(seen):
        raw, txt, info = seen[a]
        if "table" in info:
            main = tables.get(info["table"])
            break
    if not main:
        return {}, 0
    init = main[0]
    iseen, _, _, _ = trace(g.rom, init)
    out = {}
    imm = None
    for a in sorted(iseen):
        raw, txt, info = iseen[a]
        parts = txt.split()
        mn = parts[0]
        if mn == "LDA" and len(parts) > 1 and parts[1].startswith("#"):
            imm = (int(parts[1][2:], 16), a + 1)
        elif mn == "STA" and imm and len(parts[1]) == 3:   # STA $dp
            out.setdefault(parts[1], imm)
        else:
            imm = None
    return out, len(main)


def users(g):
    """Which levels place each id as an event (type 3 = enemy)."""
    from mmx1 import LEVEL_NAMES
    u = {}
    for L in range(13):
        for e in g.events(L):
            u.setdefault(e.id if e.type == 3 else None, set()).add(L)
    u.pop(None, None)
    return u


if __name__ == "__main__":
    g = MMX1(ROM)
    if len(sys.argv) > 1:
        i = int(sys.argv[1], 16)
        r = routine(g, i)
        print(f"; object {i:02X} {NAMES.get(i, '')} -> {r:06X}\n")
        print(listing(g.rom, r))
        sys.exit()
    u = users(g)
    print(f"{'id':>3}  {'routine':>7}  {'states':>6}  {'HP':>4}  {'HP@snes':>8}  levels")
    for i in range(1, NUM_IDS + 1):
        r = routine(g, i)
        if r is None:
            continue
        try:
            consts, nstates = init_constants(g, r)
        except Exception:
            consts, nstates = {}, 0
        hp = consts.get("$27")
        lv = ",".join(str(x) for x in sorted(u.get(i, [])))
        print(f"{i:02X}   {r:06X}  {nstates:>6}  {hp[0] if hp else '':>4}  "
              f"{(hex(hp[1]) if hp else ''):>8}  {lv:<14} {NAMES.get(i, '')}")
