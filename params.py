"""
Read and edit named game values (boss AI, enemy HP) in a Mega Man X1 ROM.

    python3 params.py list
    python3 params.py show chill_penguin [--rom path]
    python3 params.py set chill_penguin ice_shots=8 slide_speed=0x900 --rom in.sfc --out out.sfc
    python3 params.py weights chill_penguin "after Ice Shot" 0,0,16,0,0 [--table 0] --rom in.sfc --out out.sfc
    python3 params.py export chill_penguin cp.json [--rom path]
    python3 params.py import cp.json --rom in.sfc --out out.sfc
    python3 params.py enemies [--rom path]
    python3 params.py enemy-hp 2D=4 51=8 --rom in.sfc --out out.sfc

Never writes to the input ROM unless --out is the same path.
"""
import json
import struct
import sys
from functools import lru_cache
from pathlib import Path

from defs import (BOSSES, KNOWN_OBJECT_NAMES, Param, LDA_IMM, PROJECTILES, NUM_PROJECTILES,
                  DAMAGE_TABLE)
from mmx1 import MMX1, snes2pc, save_rom, LEVEL_NAMES

HERE = Path(__file__).parent
STOCK_ROM = HERE.parent / "Mega Man X (USA) (Rev 1).sfc"
LABELS = HERE / "labels.json"


class ParamError(Exception):
    pass


# --- raw param access ---------------------------------------------------------

def _size(p: Param):
    return 1 if p.kind == "u8" else 2


def check(g: MMX1, p: Param):
    """Make sure the bytes around the operand look like what we expect."""
    o = snes2pc(p.addr)
    if p.prev is not None and g.rom[o - 1] != p.prev:
        raise ParamError(f"{p.key}: expected opcode {p.prev:02X} before {p.addr:06X}, "
                         f"found {g.rom[o - 1]:02X} - not the ROM/version these defs are for")
    for extra in ([p.mirror] if p.mirror is not None else []) + list(p.copies):
        if p.prev is not None and g.rom[snes2pc(extra) - 1] != p.prev:
            raise ParamError(f"{p.key}: opcode mismatch at {extra:06X}")


def get(g: MMX1, p: Param) -> int:
    check(g, p)
    o = snes2pc(p.addr)
    v = int.from_bytes(g.rom[o:o + _size(p)], "little")
    if p.kind == "s16" and v & 0x8000:
        v -= 0x10000
    return v


def put(g: MMX1, p: Param, v: int):
    check(g, p)
    lo, hi = limits(p)
    if not (lo <= v <= hi):
        raise ParamError(f"{p.key}: {v:#x} outside allowed range {p.min:#x}..{hi:#x}")
    o = snes2pc(p.addr)
    g.rom[o:o + _size(p)] = (v & (0xFF if p.kind == "u8" else 0xFFFF)).to_bytes(_size(p), "little")
    if p.mirror is not None:
        struct.pack_into("<H", g.rom, snes2pc(p.mirror), (-v) & 0xFFFF)
    for c in p.copies:
        oc = snes2pc(c)
        g.rom[oc:oc + _size(p)] = (v & (0xFF if p.kind == "u8" else 0xFFFF)).to_bytes(_size(p), "little")


def parse_value(s: str) -> int:
    return int(s, 0)


def limits(p: Param) -> tuple[int, int]:
    hi = p.max if p.max is not None else (0xFF if p.kind == "u8" else 0xFFFF)
    return p.min, hi


def clamp(p: Param, v: int) -> int:
    lo, hi = limits(p)
    return max(lo, min(hi, v))


def hexstr(p: Param, v: int) -> str:
    return f"0x{v & 0xFF:02X}" if p.kind == "u8" else f"0x{v & 0xFFFF:04X}"


def describe(p: Param, v: int) -> str:
    """Short human reading of a value, with the raw hex in parentheses."""
    h = hexstr(p, v)
    if p.unit == "frames":
        return f"{v / 60:.2f} sec ({h})"
    if p.unit == "speed":
        return f"{v / 256:.2f} px/frame ({h})"
    if p.unit == "hp":
        return f"{v} HP ({h})"
    if p.unit == "px":
        return f"{v} px ({h})"
    if p.unit == "projectile":
        return f"{PROJECTILES.get(v, 'unknown')} ({h})"
    if p.unit in ("count", "id"):
        return f"{p.noun} {v} ({h})".strip() if p.unit == "id" else f"{v} {p.noun} ({h})".replace("  ", " ")
    return h


# --- damage table ----------------------------------------------------------------

def damage_row_addr(g: MMX1, damage_class: int) -> int:
    """SNES address of a damage-class row (30 bytes, one per projectile id)."""
    return DAMAGE_TABLE + g.sw(DAMAGE_TABLE + damage_class * 2)


def get_damage(g: MMX1, damage_class: int) -> list[int]:
    o = snes2pc(damage_row_addr(g, damage_class))
    return list(g.rom[o:o + NUM_PROJECTILES])


def set_damage(g: MMX1, damage_class: int, projectile: int, v: int):
    if not 0 <= projectile < NUM_PROJECTILES:
        raise ParamError(f"projectile {projectile:#x} out of range")
    o = snes2pc(damage_row_addr(g, damage_class)) + projectile
    if g.rom[o] & 0x80:
        raise ParamError(f"{PROJECTILES.get(projectile)}: this entry calls a special handler; not editable")
    g.rom[o] = max(0, min(0x7F, v))


# --- attack tables --------------------------------------------------------------

def _row_bytes(g: MMX1, t, r: int) -> list[int]:
    base = snes2pc(t.addr) + t.row_len * r
    return list(g.rom[base:base + t.row_len])


def table_weights(g: MMX1, t) -> dict:
    """{row label: {attack name: weight}} for one AttackTable (weights total t.total)."""
    out = {}
    names = list(t.attacks.values())
    for r, label in enumerate(t.rows):
        row = _row_bytes(g, t, r)
        w = {n: 0 for n in names}
        if t.fmt == "entries":
            for v in row:
                n = t.attacks.get(v, f"?{v:02X}")
                w[n] = w.get(n, 0) + 1
        else:  # weights: index i -> attack value 2*i; attack 0 gets the remainder
            for i in range(1, t.row_len):
                w[t.attacks[2 * i]] = row[i]
            w[t.attacks[0]] = t.total - sum(row[1:])
        out[label] = w
    return out


def set_weights(g: MMX1, t, row_label: str, weights: dict):
    """weights: {attack name: weight}; must total t.total."""
    by_name = {n: v for v, n in t.attacks.items()}
    if row_label not in t.rows:
        raise ParamError(f"unknown row {row_label!r}; choose from {t.rows}")
    for name, n in weights.items():
        if name not in by_name:
            raise ParamError(f"unknown attack {name!r}")
        if n < 0:
            raise ParamError("weights can't be negative")
    if sum(weights.values()) != t.total:
        raise ParamError(f"'{row_label}' totals {sum(weights.values())}, must be {t.total}")
    if t.fmt == "entries":
        if table_weights(g, t)[row_label] == {**{n: 0 for n in by_name}, **weights}:
            return  # same odds: keep the ROM's own byte order
        row = sorted(v for name, n in weights.items() for v in [by_name[name]] * n)
    else:
        row = [weights.get(t.attacks[2 * i], 0) for i in range(t.row_len)]
    base = snes2pc(t.addr) + t.row_len * t.rows.index(row_label)
    g.rom[base:base + t.row_len] = bytes(row)


# --- enemies ---------------------------------------------------------------------

@lru_cache(maxsize=1)
def enemy_catalogue():
    """[(id, routine, n_states, hp_param | None, levels)] derived from the stock ROM."""
    from enemies import routine, init_constants, NUM_IDS
    g = MMX1(STOCK_ROM)
    used = {}
    for L in range(13):
        for e in g.events(L):
            if e.type == 3:
                used.setdefault(e.id, set()).add(L)
    out = []
    for i in range(1, NUM_IDS + 1):
        r = routine(g, i)
        if r is None:
            continue
        try:
            consts, n = init_constants(g, r)
        except Exception:
            consts, n = {}, 0
        hp = None
        if "$27" in consts:
            val, addr = consts["$27"]
            if g.rom[snes2pc(addr) - 1] == LDA_IMM:
                hp = Param(f"hp_{i:02x}", "HP", addr, "u8", val, "hp", prev=LDA_IMM, min=1, max=0x7F)
        out.append((i, r, n, hp, sorted(used.get(i, []))))
    return out


def load_labels() -> dict:
    labels = {f"{k:02X}": v for k, v in KNOWN_OBJECT_NAMES.items()}
    if LABELS.exists():
        labels.update(json.loads(LABELS.read_text()))
    return labels


def save_label(obj_id: int, name: str):
    data = json.loads(LABELS.read_text()) if LABELS.exists() else {}
    if name:
        data[f"{obj_id:02X}"] = name
    else:
        data.pop(f"{obj_id:02X}", None)
    LABELS.write_text(json.dumps(data, indent=2, sort_keys=True))


# --- export / import ---------------------------------------------------------------

def export_boss(g: MMX1, boss) -> dict:
    return {
        "boss": boss.key,
        "params": {p.key: get(g, p) for p in boss.params},
        "attack_tables": [table_weights(g, t) for t in boss.attack_tables],
    }


def import_boss(g: MMX1, data: dict):
    boss = BOSSES[data["boss"]]
    params = {p.key: p for p in boss.params}
    for k, v in data.get("params", {}).items():
        put(g, params[k], v if isinstance(v, int) else parse_value(v))
    for t, rows in zip(boss.attack_tables, data.get("attack_tables") or []):
        for label, w in rows.items():
            set_weights(g, t, label, w)


# --- CLI ------------------------------------------------------------------------------

def _opt(name, default=None):
    for a in sys.argv:
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
    if f"--{name}" in sys.argv:
        i = sys.argv.index(f"--{name}")
        return sys.argv[i + 1]
    return default


def _positional():
    out, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False; continue
        if a in ("--rom", "--out", "--table"):
            skip = True; continue
        if a.startswith("--"):
            continue
        out.append(a)
    return out


def _write(g):
    out = _opt("out")
    if not out:
        raise SystemExit("refusing to write: pass --out <file> (use the same path as --rom to overwrite)")
    c = save_rom(g, out)
    print(f"wrote {out} (checksum {c:04X})")


def main():
    args = _positional()
    if not args:
        print(__doc__); return
    cmd = args[0]
    g = MMX1(_opt("rom", STOCK_ROM))

    if cmd == "list":
        for b in BOSSES.values():
            print(f"{b.key:16} {b.name} (object {b.object_id:02X}, {LEVEL_NAMES[b.level]}), "
                  f"{len(b.params)} params, {len(b.attack_tables)} attack table(s)")
    elif cmd == "show":
        b = BOSSES[args[1]]
        print(f"{b.name}\n{b.summary}\n")
        for p in b.params:
            v = get(g, p)
            mark = "" if v == p.stock else f"   (stock {describe(p, p.stock)})"
            print(f"  {p.key:20} {v:>6}  {describe(p, v):26}{mark}")
        for t in b.attack_tables:
            names = list(t.attacks.values())
            print(f"\n  {t.title} (out of {t.total})\n  {'':26}" + "".join(f"{n[:12]:>14}" for n in names))
            for label, row in table_weights(g, t).items():
                print(f"  {label:26}" + "".join(f"{row.get(n, 0):>14}" for n in names))
    elif cmd == "set":
        b = BOSSES[args[1]]
        params = {p.key: p for p in b.params}
        for kv in args[2:]:
            k, v = kv.split("=", 1)
            if k not in params:
                raise SystemExit(f"unknown param {k}; choose from {list(params)}")
            put(g, params[k], parse_value(v))
        _write(g)
    elif cmd == "weights":
        b = BOSSES[args[1]]
        t = b.attack_tables[int(_opt("table", "0"))]
        counts = [int(x) for x in args[3].split(",")]
        set_weights(g, t, args[2], dict(zip(t.attacks.values(), counts)))
        _write(g)
    elif cmd == "export":
        b = BOSSES[args[1]]
        Path(args[2]).write_text(json.dumps(export_boss(g, b), indent=2))
        print(f"wrote {args[2]}")
    elif cmd == "import":
        import_boss(g, json.loads(Path(args[1]).read_text()))
        _write(g)
    elif cmd == "enemies":
        labels = load_labels()
        print(f"{'id':>3}  {'name':28} {'HP':>4}  {'routine':>7}  levels")
        for i, r, n, hp, lv in enemy_catalogue():
            print(f"{i:02X}   {labels.get(f'{i:02X}', ''):28} {get(g, hp) if hp else '':>4}  {r:06X}  "
                  + ", ".join(LEVEL_NAMES[x] for x in lv))
    elif cmd == "enemy-hp":
        cat = {i: hp for i, r, n, hp, lv in enemy_catalogue()}
        for kv in args[1:]:
            k, v = kv.split("=", 1)
            hp = cat.get(int(k, 16))
            if not hp:
                raise SystemExit(f"no known HP location for object {k}")
            put(g, hp, parse_value(v))
        _write(g)
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        main()
    except ParamError as e:
        raise SystemExit(f"error: {e}")
