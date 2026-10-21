"""
Literal 65816 -> pseudo-C translation of a traced routine, for reading.

Each instruction becomes one C-like statement (or merges into a branch condition).
Control flow is kept as-is (labels + goto), so it matches the assembly line for
line. Names come from what we've decoded: object fields, RAM, engine helpers.
Anything marked (?) is a guess. This is pseudo-C: it explains, it doesn't compile.

usage: python3 lift.py <snes_addr_hex>
"""
import sys
from mmx1 import MMX1, RAM
from trace import trace

ROM = "../Mega Man X (USA) (Rev 1).sfc"

# direct page = the current object's slot
FIELDS = {
    0x00: "active", 0x01: "state", 0x02: "step", 0x03: "substep", 0x05: "x", 0x08: "y",
    0x0A: "id", 0x0B: "sub_id", 0x0C: "parent", 0x0F: "anim_status", 0x11: "attr",
    0x17: "keyframe", 0x1A: "vx", 0x1C: "vy", 0x1E: "gravity", 0x20: "anim_ptr",
    0x27: "hp", 0x28: "damage_class", 0x2B: "touch",
}

TAKES_A = {0x848F07, 0x8088A2, 0x8087A2, 0x84A338}

HELPERS = {
    0x848F07: "anim_start",          # A = animation number
    0x848EEA: "anim_tick",
    0x849086: "random",
    0x82FC48: "x_in_range",          # X = range index, Y = also check vertical; 0 = in range
    0x84A081: "angle_to_x",
    0x84ACA5: "face_x",              # (?)
    0x8491BE: "check_terrain",       # sets touch ($2B) (?)
    0x849B43: "hit_check",           # (?)
    0x849B03: "hurt_x_on_contact",   # (?)
    0x8281E8: "move_with_gravity",   # (?)
    0x82820A: "move",                # (?)
    0x828321: "alloc_enemy",
    0x82833E: "alloc_x_shot",
    0x828358: "alloc_enemy_shot",
    0x8282B9: "alloc_misc_1628",
    0x8282D3: "alloc_effect_1928",
    0x8088A2: "play_sound",          # A = sound id
    0x8087A2: "play_music",          # (?)
    0x8280B4: "obj_draw",            # common tail: draw / finish frame (?)
    0x828398: "obj_despawn",         # (?)
    0x84A338: "screen_shake",        # (?)
    0x84AADD: "boss_already_beaten",  # (?)
}

RAM_NAMES = {v & 0xFFFF: k for k, v in RAM.items() if v & 0xFF0000 == 0x7E0000 and v & 0xFFFF < 0x2000}
RAM_NAMES.update({0x0BAD: "X_x", 0x0BB0: "X_y", 0x0BCF: "X_hp", 0x0BDB: "X_weapon",
                  0x0B9C: "frame_counter", 0x1F1D: "last_hit_projectile", 0x1F7A: "level",
                  0x1F1B: "hit_direction", 0x1F1E: "last_hit_object", 0x1F26: "music_enabled"})
BRANCH = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ", "BRA", "BRL"}


def field(n):
    return f"self->{FIELDS[n]}" if n in FIELDS else f"self->f{n:02X}"


def operand(txt, m8, x8):
    """Assembly operand -> C lvalue/rvalue."""
    t = txt
    if t.endswith(",S"):                                         # stack relative
        return f"stack[0x{t[1:3]}]"
    if t.startswith("($") and t.endswith(",S),Y"):
        return f"(stack_ptr(0x{t[2:4]}))[Y]"
    if t.startswith("#$"):
        return f"0x{t[2:]}"
    if t.startswith("($") and t.endswith("),Y"):                 # ($dp),Y
        return f"(({field(int(t[2:4], 16))}))[Y]"
    if t.startswith("[$"):
        return f"far_ptr({field(int(t[2:4], 16))})" + ("[Y]" if t.endswith(",Y") else "[0]")
    idx = ""
    if t.endswith(",X") or t.endswith(",Y"):
        t, idx = t[:-2], t[-1]
    if t.startswith("$"):
        h = t[1:]
        v = int(h, 16)
        if len(h) == 2:                                          # direct page
            return f"self_dp[0x{v:02X} + {idx}]" if idx else field(v)
        if len(h) == 4:
            if idx and v < 0x40:                                 # other object's field via X
                name = FIELDS.get(v, f"f{v:02X}")
                return f"OBJ({idx})->{name}"
            if v < 0x2000:
                base = RAM_NAMES.get(v, f"ram[0x{v:04X}]")
                return f"{base}[{idx}]" if idx and not base.startswith("ram[") else \
                       (f"ram[0x{v:04X} + {idx}]" if idx else base)
            if v < 0x6000:
                return f"io[0x{v:04X}]" + (f"[{idx}]" if idx else "")
            return f"rom86[0x{v:04X}" + (f" + {idx}]" if idx else "]")   # data bank $86
        if len(h) == 6:
            bank = v >> 16
            area = "ram7e" if bank == 0x7E else "ram7f" if bank == 0x7F else "rom"
            off = v & 0xFFFF if area != "rom" else v
            return f"{area}[0x{off:04X}" + (f" + {idx}]" if idx else "]")
    if t == "A":
        return "A"
    return f"/* {txt} */"


def lift(rom, entry):
    seen, labels, calls, tables = trace(rom, entry)
    out = [f"// auto-translated from ${entry:06X} — literal pseudo-C, one statement per instruction",
           "// A, X, Y are the CPU registers; self = the object running this code (direct page)", ""]
    last = None          # what the next branch tests: ("val", expr, width) | ("cmp", lhs, rhs, width) | ("call", expr)
    carry_note = ""
    prev_end = None
    addrs = sorted(seen)
    for i, a in enumerate(addrs):
        raw, txt, info = seen[a]
        m8, x8 = info["m8"], info["x8"]
        parts = txt.split(None, 1)
        mn, arg = parts[0], (parts[1] if len(parts) > 1 else "")
        if prev_end is not None and a != prev_end:
            out.append("")
            last = None
        if a in labels:
            out.append(f"{labels[a]}:")
        prev_end = (a & 0xFF0000) | ((a + len(raw)) & 0xFFFF)
        wa = 8 if m8 else 16
        wx = 8 if x8 else 16
        reg_w = {"A": wa, "X": wx, "Y": wx}
        stmt = None
        tgt = info.get("target")
        lab = labels.get(tgt, f"L{tgt & 0xFFFF:04X}" if tgt else "")

        if mn in ("LDA", "LDX", "LDY"):
            r = mn[2]
            stmt = f"{r} = {operand(arg, m8, x8)};"
            last = ("val", r, reg_w[r])
        elif mn in ("STA", "STX", "STY", "STZ"):
            src = "0" if mn == "STZ" else mn[2]
            stmt = f"{operand(arg, m8, x8)} = {src};"
        elif mn in ("AND", "ORA", "EOR"):
            op = {"AND": "&", "ORA": "|", "EOR": "^"}[mn]
            stmt = f"A {op}= {operand(arg, m8, x8)};"
            last = ("val", "A", wa)
        elif mn == "ADC":
            prev = seen[addrs[i - 1]][1] if i else ""
            stmt = f"A += {operand(arg, m8, x8)};" if prev == "CLC" else f"A += {operand(arg, m8, x8)} + carry;"
            last = ("val", "A", wa)
        elif mn == "SBC":
            prev = seen[addrs[i - 1]][1] if i else ""
            stmt = f"A -= {operand(arg, m8, x8)};" if prev == "SEC" else f"A -= {operand(arg, m8, x8)} + !carry;"
            last = ("val", "A", wa)
        elif mn in ("CMP", "CPX", "CPY"):
            r = {"CMP": "A", "CPX": "X", "CPY": "Y"}[mn]
            stmt = None
            last = ("cmp", r, operand(arg, m8, x8), reg_w[r])
        elif mn in ("INC", "DEC"):
            tgt_ = "A" if arg in ("", "A") else operand(arg, m8, x8)
            stmt = f"{tgt_}{'++' if mn == 'INC' else '--'};"
            last = ("val", tgt_, wa)
        elif mn in ("INX", "INY", "DEX", "DEY"):
            r = mn[2]
            stmt = f"{r}{'++' if mn[:2] == 'IN' else '--'};"
            last = ("val", r, reg_w[r])
        elif mn in ("ASL", "LSR", "ROL", "ROR"):
            tgt_ = "A" if arg in ("", "A") else operand(arg, m8, x8)
            top = "0x80" if wa == 8 else "0x8000"
            stmt = {"ASL": f"carry = ({tgt_} & {top}) != 0; {tgt_} <<= 1;",
                    "LSR": f"carry = {tgt_} & 1; {tgt_} >>= 1;",
                    "ROL": f"{tgt_} = rol({tgt_}, &carry);",
                    "ROR": f"{tgt_} = ror({tgt_}, &carry);"}[mn]
            last = ("val", tgt_, wa)
        elif mn in ("TSB", "TRB"):
            o = operand(arg, m8, x8)
            stmt = f"{o} |= A;" if mn == "TSB" else f"{o} &= ~A;"
        elif mn == "BIT":
            if arg.startswith("#"):
                last = ("val", f"(A & {operand(arg, m8, x8)})", wa)
            else:
                last = ("bit", operand(arg, m8, x8), wa)
        elif mn in ("TAX", "TAY", "TXA", "TYA", "TXY", "TYX"):
            d, s_ = mn[2], mn[1]
            stmt = f"{d} = {s_};"
            last = ("val", d, reg_w[d])
        elif mn == "TDC":
            stmt = "A = (uint16_t)self;   // object's address"
        elif mn == "TCD":
            stmt = "self = (Obj *)A;"
        elif mn == "XBA":
            stmt = "A = swap_bytes(A);"
        elif mn in ("PHA", "PHX", "PHY", "PHP", "PHB", "PHD", "PHK"):
            stmt = f"push({ {'PHA': 'A', 'PHX': 'X', 'PHY': 'Y', 'PHP': 'flags', 'PHB': 'data_bank', 'PHD': 'self', 'PHK': 'code_bank'}[mn] });"
        elif mn in ("PLA", "PLX", "PLY", "PLP", "PLB", "PLD"):
            d = {"PLA": "A", "PLX": "X", "PLY": "Y", "PLP": "flags", "PLB": "data_bank", "PLD": "self"}[mn]
            stmt = f"{d} = pop();"
            if mn in ("PLA", "PLX", "PLY"):
                last = ("val", d, reg_w[d])
        elif mn == "CLC":
            stmt = None if i + 1 < len(addrs) and seen[addrs[i + 1]][1].startswith("ADC") else "carry = 0;"
        elif mn == "SEC":
            stmt = None if i + 1 < len(addrs) and seen[addrs[i + 1]][1].startswith("SBC") else "carry = 1;"
        elif mn == "REP":
            bits = int(arg[2:], 16)
            stmt = "// " + ", ".join(n for b, n in ((0x20, "A is 16-bit"), (0x10, "X/Y are 16-bit"), (0x01, "carry = 0")) if bits & b)
        elif mn == "SEP":
            bits = int(arg[2:], 16)
            stmt = "// " + ", ".join(n for b, n in ((0x20, "A is 8-bit"), (0x10, "X/Y are 8-bit"), (0x01, "carry = 1")) if bits & b)
        elif mn in ("JSR", "JSL"):
            if "table" in info:
                ents = tables.get(info["table"], [])
                cases = ", ".join(f"{k * 2:#04x}: {labels.get(e, hex(e))}" for k, e in enumerate(ents))
                stmt = f"switch_call(X, {{{cases}}});"
            else:
                name = HELPERS.get(tgt) or labels.get(tgt) or f"sub_{tgt:06X}"
                arg_ = "A" if tgt in TAKES_A else ""
                nxt = seen[addrs[i + 1]][1].split()[0] if i + 1 < len(addrs) else ""
                if nxt in BRANCH and nxt not in ("BRA", "BRL"):
                    stmt = f"res = {name}({arg_});"
                    last = ("val", "res", wa)
                else:
                    stmt = f"{name}({arg_});"
                    last = None
        elif mn in ("JMP", "JML"):
            if "table" in info:
                ents = tables.get(info["table"], [])
                cases = ", ".join(f"{k * 2:#04x}: {labels.get(e, hex(e))}" for k, e in enumerate(ents))
                stmt = f"switch_goto(X, {{{cases}}});"
            else:
                name = HELPERS.get(tgt)
                stmt = f"return {name}();" if name else f"goto {labels.get(tgt, f'sub_{tgt:06X}')};"
        elif mn in ("RTS", "RTL", "RTI"):
            stmt = "return;"
        elif mn == "NOP":
            stmt = None
        elif mn in BRANCH:
            if mn in ("BRA", "BRL"):
                stmt = f"goto {lab};"
            else:
                stmt = f"if ({condition(mn, last)}) goto {lab};"
        else:
            stmt = f"/* {txt} */"

        if stmt:
            out.append(f"    {stmt:<58}// {a:06X} {txt}")
        elif mn in ("CMP", "CPX", "CPY", "BIT", "CLC", "SEC", "NOP"):
            out.append(f"    {'':<58}// {a:06X} {txt}")
    out = fold(out)
    for tb, ents in tables.items():
        out.append(f"\n// jump table {tb:06X}: " + ", ".join(labels.get(e, hex(e)) for e in ents))
    return "\n".join(out)


def fold(lines):
    """A = 0x02; / x = A;  ->  x = A = 0x02;     A = 0x01; / f(A);  ->  f(A = 0x01);"""
    out = []
    for line in lines:
        code, _, cmt = line.partition("// ")
        prev = out[-1] if out else ""
        pcode, _, pcmt = prev.partition("// ")
        p, c = pcode.strip(), code.strip()
        if p.startswith("A = 0x") and p.endswith(";") and " " not in p[4:-1]:
            val = p[4:-1]
            if c.endswith(" = A;") and not c.startswith("A "):
                out[-1] = f"    {c[:-2] + 'A = ' + val + ';':<58}// {pcmt.strip()} / {cmt.strip()}"
                continue
            if c.endswith("(A);"):
                out[-1] = f"    {c[:-3] + 'A = ' + val + ');':<58}// {pcmt.strip()} / {cmt.strip()}"
                continue
        out.append(line)
    return out


def condition(mn, last):
    if last is None:
        return {"BEQ": "zero", "BNE": "!zero", "BMI": "negative", "BPL": "!negative",
                "BCC": "!carry", "BCS": "carry", "BVC": "!overflow", "BVS": "overflow"}[mn]
    kind = last[0]
    if kind == "cmp":
        _, r, v, w = last
        sign = f"(int{w}_t)({r} - {v})"
        return {"BEQ": f"{r} == {v}", "BNE": f"{r} != {v}", "BCC": f"{r} < {v}", "BCS": f"{r} >= {v}",
                "BMI": f"{sign} < 0", "BPL": f"{sign} >= 0",
                "BVC": "!overflow", "BVS": "overflow"}[mn]
    if kind == "bit":
        _, m, w = last
        top, nxt = ("0x80", "0x40") if w == 8 else ("0x8000", "0x4000")
        return {"BEQ": f"(A & {m}) == 0", "BNE": f"(A & {m}) != 0", "BMI": f"{m} & {top}",
                "BPL": f"!({m} & {top})", "BVS": f"{m} & {nxt}", "BVC": f"!({m} & {nxt})",
                "BCC": "!carry", "BCS": "carry"}[mn]
    _, e, w = last
    top = "0x80" if w == 8 else "0x8000"
    return {"BEQ": f"{e} == 0", "BNE": f"{e} != 0", "BMI": f"{e} & {top}", "BPL": f"!({e} & {top})",
            "BCC": "!carry", "BCS": "carry", "BVC": "!overflow", "BVS": "overflow"}[mn]


if __name__ == "__main__":
    g = MMX1(ROM)
    print(lift(g.rom, int(sys.argv[1], 16)))
