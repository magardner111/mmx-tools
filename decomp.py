"""
Structured 65816 -> C decompiler for object routines (enemies / bosses).

Builds on trace.py:
  * splits the routine into functions (entry, every jump-table handler, local subroutines),
  * tracks A/X/Y symbolically so register traffic disappears into expressions,
  * rebuilds if/else from branches using post-dominators (goto only as a fallback),
  * recognises "allocate object, then fill its fields" and facing-based ?: idioms,
  * names fields / functions from defs.py (per-boss) and lift.py (engine helpers, RAM).

Output is readable C that follows the original logic exactly; it is not compiled.

usage: python3 decomp.py <snes_addr_hex | boss_key | x>
"""
import re
import sys

from mmx1 import MMX1
from trace import trace
from lift import FIELDS, HELPERS, RAM_NAMES, TAKES_A
from defs import ENEMY_SHOTS, KNOWN_OBJECT_NAMES

ROM = "../Mega Man X (USA) (Rev 1).sfc"
COND = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"}
ALLOCATORS = {0x828321: "alloc_enemy", 0x82833E: "alloc_x_shot", 0x828358: "alloc_enemy_shot",
              0x8282B9: "alloc_misc", 0x8282D3: "alloc_effect"}
# id -> name for what each allocator spawns, so `s->id = 33;` reads as the object it is
SPAWN_NAMES = {0x828321: KNOWN_OBJECT_NAMES,
               0x828358: {i: f"{n} {'' if m == 'verified' else '(?)'}".strip() for i, (n, _, m) in ENEMY_SHOTS.items()}}
TAIL = {0x8280B4, 0x828398}       # common "finish frame" / "despawn" tails
MASK_OPS = {"AND", "ORA", "EOR", "BIT", "TSB", "TRB"}


# ----------------------------------------------------------------------------------------
# expressions

def par(e):
    e = str(e)
    if re.fullmatch(r"(OBJ\(\w+\))?[\w\->\[\]\.]+", e) or (e.startswith("(") and e.endswith(")") and balanced(e[1:-1])):
        return e
    return f"({e})"


def balanced(s):
    d = 0
    for ch in s:
        d += ch == "("
        d -= ch == ")"
        if d < 0:
            return False
    return d == 0


def top_level(c, op):
    """Index of a top-level (depth 0) occurrence of op in c, or -1."""
    d = 0
    for i in range(len(c)):
        ch = c[i]
        d += ch == "("
        d -= ch == ")"
        if d == 0 and c.startswith(op, i):
            return i
    return -1


def split_top(c, op):
    parts, d, start, i = [], 0, 0, 0
    while i < len(c):
        ch = c[i]
        d += ch == "("
        d -= ch == ")"
        if d == 0 and c.startswith(op, i):
            parts.append(c[start:i])
            i += len(op)
            start = i
            continue
        i += 1
    parts.append(c[start:])
    return parts


def unwrap(c):
    c = c.strip()
    while c.startswith("(") and c.endswith(")") and balanced(c[1:-1]):
        c = c[1:-1].strip()
    return c


def neg(c):
    c = unwrap(c)
    if top_level(c, " || ") >= 0:
        return " && ".join(par(neg(p)) if top_level(neg(p), " ") >= 0 else neg(p) for p in split_top(c, " || "))
    if top_level(c, " && ") >= 0:
        return " || ".join(par(neg(p)) for p in split_top(c, " && "))
    if top_level(c, " ? ") < 0 and top_level(c, " && ") < 0 and top_level(c, " || ") < 0:
        for a, b in ((" == ", " != "), (" != ", " == "), (" >= ", " < "), (" < ", " >= ")):
            i = top_level(c, a)
            if i >= 0:
                return c[:i] + b + c[i + len(a):]
    if c.startswith("!(") and c.endswith(")") and balanced(c[2:-1]):
        return c[2:-1]
    if c.startswith("!") and re.fullmatch(r"![\w\->\[\]\.]+(\(\))?", c):
        return c[1:]
    return f"!{par(c)}"


def num(v, width, ctx=""):
    """Format a constant: masks in hex, small numbers in decimal, 16-bit negatives signed."""
    if ctx == "mask":
        return f"0x{v:02X}" if v < 0x100 else f"0x{v:04X}"
    if width == 16 and v >= 0x8000 and 0x10000 - v < 0x1000:
        return str(v - 0x10000)
    if v < 0x100:
        return str(v)
    return f"0x{v:04X}"


# ----------------------------------------------------------------------------------------

class Decompiler:
    def __init__(self, rom, entry, boss=None):
        self.rom, self.entry, self.boss = rom, entry, boss
        self.seen, self.labels, self.calls, self.tables = trace(rom, entry)
        self.fields = dict(FIELDS)
        if boss and getattr(boss, "fields", None):
            self.fields.update(boss.fields)
        self.struct = "".join(w.title() for w in boss.key.split("_")) if boss else "Obj"
        self._build_blocks()
        self._find_functions()
        self._name_functions()

    # --- CFG -----------------------------------------------------------------------------
    def _build_blocks(self):
        addrs = sorted(self.seen)
        self.addrs = addrs
        nxt = {a: b for a, b in zip(addrs, addrs[1:])}
        self.next_addr = nxt
        leaders = {self.entry} | {e for es in self.tables.values() for e in es}
        for a in addrs:
            raw, txt, info = self.seen[a]
            mn = txt.split()[0]
            t = info.get("target")
            if mn in COND or mn in ("BRA", "BRL"):
                if t in self.seen:
                    leaders.add(t)
                if a in nxt:
                    leaders.add(nxt[a])
            if mn in ("JSR", "JMP") and t in self.seen:
                leaders.add(t)
            if mn in ("RTS", "RTL", "JML", "JMP", "BRA", "BRL") and a in nxt:
                leaders.add(nxt[a])
            end = (a & 0xFF0000) | ((a + len(raw)) & 0xFFFF)
            if a in nxt and nxt[a] != end:          # gap in the listing
                leaders.add(nxt[a])
        self.blocks = {}
        cur = None
        for a in addrs:
            if a in leaders:
                cur = a
                self.blocks[cur] = []
            self.blocks[cur].append(a)
        self.succ = {}
        for b, ins in self.blocks.items():
            last = ins[-1]
            raw, txt, info = self.seen[last]
            mn = txt.split()[0]
            t = info.get("target")
            fall = self.next_addr.get(last)
            end = (last & 0xFF0000) | ((last + len(raw)) & 0xFFFF)
            if fall != end:
                fall = None
            if mn in COND:
                self.succ[b] = [x for x in (t, fall) if x in self.blocks]
            elif mn in ("BRA", "BRL"):
                self.succ[b] = [t] if t in self.blocks else []
            elif mn in ("RTS", "RTL", "RTI", "JML") or (mn == "JMP"):
                self.succ[b] = []
            else:
                self.succ[b] = [fall] if fall in self.blocks else []

    def _find_functions(self):
        starts = {self.entry} | {e for es in self.tables.values() for e in es}
        for a in self.addrs:
            raw, txt, info = self.seen[a]
            mn = txt.split()[0]
            t = info.get("target")
            if mn in ("JSR", "JMP") and "table" not in info and t in self.blocks:
                starts.add(t)
        self.func_starts = starts

    def _name_functions(self):
        b = self.boss
        names = {}
        state_names = getattr(b, "state_names", None) or ["init", "intro", "fight", "death"]
        attack_names = getattr(b, "attack_handlers", None) or []
        names[self.entry] = f"{b.key}_update" if b else f"obj_{self.entry:06X}_update"
        owner = {}
        for tb, ents in self.tables.items():
            jump = next((a for a in self.addrs if self.seen[a][2].get("table") == tb), None)
            owner[tb] = self._func_of(jump)
        order = sorted(self.tables, key=lambda t: (t != self._first_table(), t))
        for tb in order:
            ents = self.tables[tb]
            own = owner[tb]
            own_name = names.get(own, f"sub_{own:06X}" if own else "sub")
            for k, e in enumerate(ents):
                if e in names:
                    continue
                if own == self.entry and tb == self._first_table():
                    nm = state_names[k] if k < len(state_names) else f"state_{k * 2}"
                elif own_name == "fight" and attack_names:
                    nm = attack_names[k] if k < len(attack_names) else f"attack_{k * 2}"
                else:
                    nm = f"{own_name}_{k}"
                names[e] = nm
        extra = getattr(b, "func_names", None) or {}
        for s in sorted(self.func_starts):
            if s in extra:
                names[s] = extra[s]
            elif s not in names:
                names[s] = f"sub_{s & 0xFFFF:04X}"
        # de-duplicate (a handler listed twice in one table keeps its first name)
        self.fname = names

    def _first_table(self):
        for a in self.addrs:
            if "table" in self.seen[a][2]:
                return self.seen[a][2]["table"]
        return None

    def _func_of(self, addr):
        if addr is None:
            return None
        best = None
        for s in self.func_starts:
            if s <= addr and (best is None or s > best):
                if addr in self._reach(s):
                    best = s
        return best

    def _reach(self, start):
        seen, stack = set(), [start]
        while stack:
            b = stack.pop()
            if b in seen:
                continue
            seen.add(b)
            for s in self.succ.get(b, []):
                if s not in self.func_starts or s == start:
                    stack.append(s)
        out = set()
        for b in seen:
            out.update(self.blocks[b])
        return out

    def _func_blocks(self, start):
        seen, stack = [], [start]
        while stack:
            b = stack.pop()
            if b in seen:
                continue
            seen.append(b)
            for s in self.succ.get(b, []):
                if s not in self.func_starts or s == start:
                    stack.append(s)
        return seen

    def _ipdom(self, blocks):
        """Immediate post-dominators within one function (EXIT = None)."""
        bs = set(blocks)
        succ = {b: [s for s in self.succ[b] if s in bs and s not in self.func_starts or s == blocks[0]]
                for b in blocks}
        for b in blocks:   # edges into other functions count as exits
            succ[b] = [s for s in self.succ[b] if s in bs and (s not in self.func_starts)]
        EXIT = "EXIT"
        pd = {b: set(blocks) | {EXIT} for b in blocks}
        pd[EXIT] = {EXIT}
        changed = True
        while changed:
            changed = False
            for b in blocks:
                ss = succ[b] or [EXIT]
                new = {b} | set.intersection(*(pd[s] for s in ss))
                if new != pd[b]:
                    pd[b] = new
                    changed = True
        ip = {}
        for b in blocks:
            cands = pd[b] - {b}
            # the closest post-dominator is the one post-dominated by all others
            best = None
            for c in cands:
                if all(c == o or o in pd.get(c, {EXIT}) for o in cands):
                    best = c
                    break
            ip[b] = None if best in (EXIT, None) else best
        return ip

    # --- operands ------------------------------------------------------------------------
    def fld(self, n, obj="self"):
        # per-boss names describe the boss's own slot; other objects (spawned shots etc.) get the generic ones
        name = (self.fields if obj == "self" else FIELDS).get(n, f"f{n:02X}")
        return f"{obj}->{name}"

    def mem(self, arg, st):
        t = arg
        if t.endswith(",S"):
            return f"stack[{t[1:3]}]"
        if t.startswith("($") and t.endswith("),Y"):
            return f"((uint8_t *){self.fld(int(t[2:4], 16))})[{st.get('Y')}]"
        if t.startswith("($") and t.endswith(",X)"):
            return f"*(uint8_t *)self_dp[{int(t[2:4], 16)} + {par(st.get('X'))}]"
        if t.startswith("($") and t.endswith(")"):
            return f"*(uint8_t *){self.fld(int(t[2:4], 16))}"
        if t.startswith("[$"):
            return f"far_ptr({self.fld(int(t[2:4], 16))})[{st.get('Y') if t.endswith(',Y') else 0}]"
        idx = None
        if t.endswith(",X") or t.endswith(",Y"):
            idx, t = t[-1], t[:-2]
        h = t[1:]
        v = int(h, 16)
        iv = par(st.get(idx)) if idx else None
        if len(h) == 2:
            return f"self_dp[{v} + {iv}]" if idx else self.fld(v)
        if len(h) == 4:
            if idx and v < 0x40:
                plain = re.fullmatch(r"[A-Za-z_]\w*", iv) and iv not in ("X", "Y")
                return self.fld(v, obj=iv if plain else f"OBJ({iv})")
            if v < 0x2000:
                base = RAM_NAMES.get(v)
                if base:
                    return f"{base}[{iv}]" if idx else base
                return f"ram[0x{v:04X}{' + ' + iv if idx else ''}]"
            if v < 0x6000:
                return f"io[0x{v:04X}]"
            return f"rom86[0x{v:04X}{' + ' + iv if idx else ''}]"
        bank = v >> 16
        area = {0x7E: "ram7e", 0x7F: "ram7f"}.get(bank, "rom")
        off = (v & 0xFFFF) if area != "rom" else v
        return f"{area}[0x{off:04X}{' + ' + iv if idx else ''}]"

    # --- emission ------------------------------------------------------------------------
    def decompile(self):
        out = [f"// {self.boss.name if self.boss else 'object'} — decompiled from ${self.entry:06X}",
               "// Structured C that follows the original code exactly (not compiled). Names marked (?)",
               "// in lift.py/defs.py are guesses; unnamed fields are fNN (= direct-page offset $NN).", ""]
        out += self.struct_decl() + [""]
        for s in sorted(self.func_starts, key=lambda s: (s != self.entry, s)):
            out += self.function(s) + [""]
        return "\n".join(out)

    def struct_decl(self):
        used = set()
        for a in self.addrs:
            for m in re.finditer(r"\$([0-9A-F]{2})\b(?!,S)", self.seen[a][1]):
                used.add(int(m.group(1), 16))
        lines = [f"typedef struct {{   // one object slot = direct page $00–$3F"]
        for n in sorted(x for x in used if x < 0x40):
            nm = self.fields.get(n, f"f{n:02X}")
            ty = "int16_t" if n in (0x05, 0x08, 0x1A, 0x1C) else "uint8_t"
            lines.append(f"    /* ${n:02X} */ {ty} {nm};")
        lines.append(f"}} {self.struct};")
        return lines

    def function(self, start):
        name = self.fname[start]
        blocks = self._func_blocks(start)
        self.cur_blocks = set(blocks)
        self.ipdom = self._ipdom(blocks)
        self.emitted = set()
        self.goto_targets = set()
        self.loop_heads = {t for x in blocks for t in self.succ.get(x, []) if t in self.cur_blocks and t <= x}
        body, _ = self.region(start, None, {"A": "A", "X": "X", "Y": "Y", "m8": True, "x8": True}, 1)
        lines = [f"static void {name}({self.struct} *self)  // ${start:06X}\t@@{start:06X}", "{"]
        for ln in body:
            m = re.match(r"\s*@label (\w+)", ln)
            if m:
                if m.group(1) in self.goto_targets:
                    lines.append(f"{m.group(1)}:")
                continue
            lines.append(ln)
        while len(lines) > 2 and lines[-1].strip() == "return;" and lines[-1].startswith("    return"):
            lines.pop()
        lines.append("}")
        return lines

    def label(self, b):
        return f"L_{b & 0xFFFF:04X}"

    def region(self, b, stop, st, depth):
        ind = "    " * depth
        lines = []
        while b is not None and b != stop:
            if b not in self.cur_blocks or (b in self.func_starts and b != min(self.cur_blocks, key=lambda x: x not in self.func_starts)):
                pass
            if b in self.func_starts and lines is not None and b != self._current_start(b):
                lines.append(f"{ind}{self.fname[b]}(self);")
                lines.append(f"{ind}return;")
                return lines, st
            if b in self.emitted:
                for r in ("A", "X", "Y"):
                    if st.get(r) != r and b in self.loop_heads and self.head_reads(b, r):
                        lines.append(f"{ind}{r} = {st[r]};")
                self.goto_targets.add(self.label(b))
                lines.append(f"{ind}goto {self.label(b)};")
                return lines, st
            if b in self.loop_heads:
                st = dict(st)
                for r in ("A", "X", "Y"):
                    if st.get(r) != r:
                        if self.head_reads(b, r):
                            lines.append(f"{ind}{r} = {st[r]};")
                        st[r] = r
            self.emitted.add(b)
            lines.append(f"@label {self.label(b)}")
            st = dict(st)
            stmts, term = self.block(b, st, ind)
            lines += stmts
            kind = term[0]
            if kind == "cond":
                _, cond, taken, fall = term
                cond, taken, fall = self.merge_conditions(cond, taken, fall, st)
                j = self.ipdom.get(b)
                if j is None:
                    j = self.common_join(taken, fall)
                if j is None or (stop is not None and j > stop and stop in self.cur_blocks):
                    j = stop
                if taken not in self.cur_blocks:
                    j = fall
                t_lines, t_st = self.region(taken, j, dict(st), depth + 1) if taken != j else ([], st)
                f_lines, f_st = self.region(fall, j, dict(st), depth + 1) if fall != j else ([], st)
                t_lines = [l for l in t_lines if not l.strip().startswith("@label") or True]
                tern = self.ternary(cond, t_lines, f_lines, t_st, f_st, st)
                if tern:
                    st = tern
                elif self.empty(t_lines) and self.empty(f_lines):
                    pass
                elif self.empty(t_lines):
                    lines.append(f"{ind}if ({neg(cond)}) {{")
                    lines += f_lines
                    lines.append(f"{ind}}}")
                    st = self.merge(t_st, f_st, lines, ind)
                elif self.empty(f_lines):
                    lines.append(f"{ind}if ({cond}) {{")
                    lines += t_lines
                    lines.append(f"{ind}}}")
                    st = self.merge(t_st, f_st, lines, ind)
                else:
                    lines.append(f"{ind}if ({cond}) {{")
                    lines += t_lines
                    lines.append(f"{ind}}} else {{")
                    lines += f_lines
                    lines.append(f"{ind}}}")
                    st = self.merge(t_st, f_st, lines, ind)
                b = j
            elif kind == "goto":
                b = term[1]
            elif kind == "next":
                b = term[1]
            else:   # exit
                return lines, st
        return lines, st

    def head_reads(self, b, r):
        reads = {"A": {"STA", "AND", "ORA", "EOR", "ADC", "SBC", "CMP", "TAX", "TAY", "PHA", "TSB", "TRB", "XBA"},
                 "X": {"STX", "CPX", "TXA", "TXY", "PHX", "INX", "DEX"},
                 "Y": {"STY", "CPY", "TYA", "TYX", "PHY", "INY", "DEY"}}[r]
        writes = {"A": {"LDA", "TXA", "TYA", "PLA", "TDC"}, "X": {"LDX", "TAX", "TYX", "PLX"},
                  "Y": {"LDY", "TAY", "TXY", "PLY"}}[r]
        for a in self.blocks[b]:
            m_, a_ = (self.seen[a][1].split(None, 1) + [""])[:2]
            if m_ in reads or (r != "A" and f",{r}" in a_):
                return True
            if m_ in writes:
                return False
        return True

    def preds(self, x):
        return [b for b in self.cur_blocks if x in self.succ.get(b, [])]

    def pure_cond_block(self, x):
        """A block that only loads/compares and then branches (safe to fold into a condition)."""
        if x not in self.cur_blocks or x in self.emitted or x in self.func_starts or len(self.preds(x)) != 1:
            return False
        ins = self.blocks[x]
        last = self.seen[ins[-1]][1].split()[0]
        if last not in COND:
            return False
        ok = {"LDA", "LDX", "LDY", "CMP", "CPX", "CPY", "AND", "BIT", "REP", "SEP"}
        return all(self.seen[a][1].split()[0] in ok for a in ins[:-1])

    def merge_conditions(self, cond, taken, fall, st):
        """if c1 goto T; [F: if c2 goto T]  ->  if (c1 || c2) goto T   (and the !c2 variant)."""
        while fall is not None and self.pure_cond_block(fall):
            st2 = dict(st)
            _, term2 = self.block(fall, st2, "")
            if term2[0] != "cond":
                break
            _, c2, t2, f2 = term2
            if t2 == taken:
                cond, fall = f"{par(cond)} || {par(c2)}", f2
            elif f2 == taken:
                cond, fall = f"{par(cond)} || {par(neg(c2))}", t2
            else:
                break
            self.emitted.add(fall if False else self.blocks_key(term2))
        return cond, taken, fall

    def blocks_key(self, term):
        return None

    def common_join(self, a, b):
        """Earliest block reachable from both arms (used when one arm returns early)."""
        def reach(x):
            seen, stack = set(), [x]
            while stack:
                y = stack.pop()
                if y in seen or y not in self.cur_blocks:
                    continue
                seen.add(y)
                stack += [s for s in self.succ.get(y, []) if s not in self.func_starts]
            return seen
        if a is None or b is None:
            return None
        both = reach(a) & reach(b)
        return min(both) if both else None

    def _current_start(self, b):
        # the function currently being emitted is the smallest-address start whose blocks include b
        return min((s for s in self.func_starts if s in self.cur_blocks), default=b)

    def empty(self, lines):
        return all(l.strip().startswith("@label") for l in lines)

    def ternary(self, cond, tl, fl, tst, fst, base):
        """Both arms only changed registers -> fold into ?: (e.g. facing-based offsets)."""
        if not (self.empty(tl) and self.empty(fl)):
            return None
        out = dict(base)
        changed = False
        for r in ("A", "X", "Y"):
            if tst.get(r) != fst.get(r):
                out[r] = f"{par(cond)} ? {tst[r]} : {fst[r]}"
                changed = True
        for k in ("m8", "x8"):
            out[k] = tst.get(k, base.get(k))
        return out if changed else None

    def merge(self, a, b, lines, ind):
        out = dict(a)
        for r in ("A", "X", "Y"):
            if a.get(r) != b.get(r):
                out[r] = r          # value differs per path: fall back to the register name
        return out

    # --- one basic block -------------------------------------------------------------------
    def block(self, b, st, ind):
        lines = []
        ins = self.blocks[b]
        flags = None     # ("val", e) | ("cmp", l, r) | ("bit", m) | ("res", name)
        carry = None
        shift = None     # (orig_expr, n, dir) for ASL/LSR chains
        stack = []

        def w():
            return 8 if st["m8"] else 16

        def emit(s):
            lines.append(f"{ind}{s}\t@@{cur_a[0]:06X}")

        def live(r, i0):
            """Is register r read before being overwritten after instruction i0?"""
            for k in range(i0 + 1, len(ins)):
                m_, a_ = (self.seen[ins[k]][1].split(None, 1) + [""])[:2]
                reads = {"A": {"STA", "AND", "ORA", "EOR", "ADC", "SBC", "CMP", "TAX", "TAY", "PHA",
                               "TSB", "TRB", "BIT", "XBA"},
                         "X": {"STX", "CPX", "TXA", "TXY", "PHX", "INX", "DEX"},
                         "Y": {"STY", "CPY", "TYA", "TYX", "PHY", "INY", "DEY"}}[r]
                if m_ in reads or (r == "A" and m_ in ("ASL", "LSR", "ROL", "ROR", "INC", "DEC") and a_ in ("", "A")) \
                        or (r != "A" and (f",{r}" in a_)):
                    return True
                writes = {"A": {"LDA", "TXA", "TYA", "PLA", "TDC"}, "X": {"LDX", "TAX", "TYX", "PLX"},
                          "Y": {"LDY", "TAY", "TXY", "PLY"}}[r]
                if m_ in writes:
                    return False
                if m_ in ("RTS", "RTL", "JML") or (m_ in ("JSL", "JSR") and not (r == "A" and
                                                                                     self.seen[ins[k]][2].get("target") in TAKES_A)):
                    return False
            return True

        def invalidate(target):
            for r in ("A", "X", "Y"):
                if target in str(st[r]) and st[r] != r:
                    if live(r, cur_i[0]):
                        emit(f"{r} = {st[r]};")
                    st[r] = r

        cur_i = [0]
        cur_a = [b]
        for i, a in enumerate(ins):
            cur_i[0] = i
            cur_a[0] = a
            raw, txt, info = self.seen[a]
            parts = txt.split(None, 1)
            mn, arg = parts[0], (parts[1] if len(parts) > 1 else "")
            t = info.get("target")
            nxt_txt = self.seen[ins[i + 1]][1] if i + 1 < len(ins) else ""
            nxt_mn = nxt_txt.split()[0] if nxt_txt else ""

            def val(a_=arg, ctx=""):
                if a_.startswith("#$"):
                    v = int(a_[2:], 16)
                    return num(v, w() if mn not in ("LDX", "LDY", "CPX", "CPY") else (8 if st["x8"] else 16), ctx)
                return self.mem(a_, st)

            if mn in ("LDA", "LDX", "LDY"):
                r = mn[2]
                st[r] = val(ctx="mask" if nxt_mn in ("TSB", "TRB") else "")
                flags = ("val", st[r])
                shift = None
            elif mn in ("STA", "STX", "STY", "STZ"):
                dst = self.mem(arg, st)
                src = "0" if mn == "STZ" else st[mn[2]]
                m = re.fullmatch(re.escape(dst) + r" ([&|^+\-]) (.+)", str(src)) or \
                    re.fullmatch(r"\(" + re.escape(dst) + r"\) ([&|^+\-]) (.+)", str(src))
                if m and m.group(1) in "+-" and m.group(2) == "1":
                    emit(f"{dst}{m.group(1) * 2};")
                elif m:
                    emit(f"{dst} {m.group(1)}= {m.group(2)};")
                else:
                    spawned = None
                    if dst == "s->id" and st.get("alloc") in SPAWN_NAMES:
                        try:
                            spawned = SPAWN_NAMES[st["alloc"]].get(int(str(src), 0))
                        except ValueError:
                            pass
                    emit(f"{dst} = {src};" + (f"  // {spawned}" if spawned else ""))
                r_ = None if mn == "STZ" else mn[2]
                for r in ("A", "X", "Y"):
                    if r != r_ and dst in str(st[r]) and st[r] != r:
                        if live(r, i):
                            emit(f"{r} = {st[r]};")
                        st[r] = r
                if r_ and not re.fullmatch(r"-?\d+|0x[0-9A-F]+|[A-Za-z_]\w*", str(src)):
                    st[r_] = dst
            elif mn in ("AND", "ORA", "EOR"):
                op = {"AND": "&", "ORA": "|", "EOR": "^"}[mn]
                st["A"] = f"{par(st['A'])} {op} {val(ctx='mask')}"
                flags = ("val", st["A"])
            elif mn == "ADC":
                prev = self.seen[ins[i - 1]][1] if i else ""
                v = val()
                if v.startswith("-"):
                    st["A"] = f"{par(st['A'])} - {v[1:]}"
                elif prev == "CLC" and (" ? " in str(st["A"]) or re.fullmatch(r"-?\d+|0x[0-9A-F]+", str(st["A"]))):
                    st["A"] = f"{v} + {par(st['A'])}"
                else:
                    st["A"] = f"{par(st['A'])} + {v}" + ("" if prev == "CLC" else " + carry")
                flags = ("val", st["A"])
            elif mn == "SBC":
                prev = self.seen[ins[i - 1]][1] if i else ""
                st["A"] = f"{par(st['A'])} - {val()}" + ("" if prev == "SEC" else " - !carry")
                flags = ("val", st["A"])
            elif mn in ("CMP", "CPX", "CPY"):
                r = {"CMP": "A", "CPX": "X", "CPY": "Y"}[mn]
                flags = ("cmp", st[r], val())
            elif mn in ("INC", "DEC"):
                if arg in ("", "A"):
                    st["A"] = f"{par(st['A'])} {'+' if mn == 'INC' else '-'} 1"
                    flags = ("val", st["A"])
                else:
                    d = self.mem(arg, st)
                    invalidate(d)
                    emit(f"{d}{'++' if mn == 'INC' else '--'};")
                    flags = ("val", d)
            elif mn in ("INX", "INY", "DEX", "DEY"):
                r = mn[2]
                st[r] = f"{par(st[r])} {'+' if mn.startswith('IN') else '-'} 1"
                flags = ("val", st[r])
            elif mn in ("ASL", "LSR") and arg in ("", "A"):
                top = 0x80 if w() == 8 else 0x8000
                if shift and shift[2] == mn:
                    orig, n = shift[0], shift[1] + 1
                else:
                    orig, n = st["A"], 1
                shift = (orig, n, mn)
                bit = (top >> (n - 1)) if mn == "ASL" else (1 << (n - 1))
                mk = num(bit, 16, 'mask')
                carry = orig if str(orig).endswith(f"& {mk}") else f"{par(orig)} & {mk}"
                st["A"] = f"{par(orig)} {'<<' if mn == 'ASL' else '>>'} {n}"
                flags = ("val", st["A"])
                continue
            elif mn in ("ASL", "LSR", "ROL", "ROR"):
                d = self.mem(arg, st) if arg not in ("", "A") else "A"
                emit(f"{d} = {mn.lower()}({d});")
                flags = ("val", d)
            elif mn in ("TSB", "TRB"):
                d = self.mem(arg, st)
                emit(f"{d} |= {st['A']};" if mn == "TSB" else f"{d} &= ~{par(st['A'])};")
                invalidate(d)
            elif mn == "BIT":
                if arg.startswith("#"):
                    flags = ("val", f"{par(st['A'])} & {val(ctx='mask')}")
                else:
                    flags = ("bit", self.mem(arg, st))
            elif mn in ("TAX", "TAY", "TXA", "TYA", "TXY", "TYX"):
                st[mn[2]] = st[mn[1]]
                flags = ("val", st[mn[2]])
            elif mn == "TDC":
                st["A"] = "self"
            elif mn == "TCD":
                emit(f"self = (void *){st['A']};")
            elif mn == "XBA":
                st["A"] = f"swap_bytes({st['A']})"
            elif mn in ("PHA", "PHX", "PHY"):
                stack.append(st[mn[2]])
            elif mn in ("PLA", "PLX", "PLY"):
                st[mn[2]] = stack.pop() if stack else "pop()"
                flags = ("val", st[mn[2]])
            elif mn in ("PHP", "PLP", "PHB", "PLB", "PHD", "PLD", "PHK", "CLC", "SEC", "NOP", "CLV", "SEI", "CLI"):
                if mn == "PLD":
                    pass
            elif mn == "REP":
                bits = int(arg[2:], 16)
                if bits & 0x20: st["m8"] = False
                if bits & 0x10: st["x8"] = False
                if bits & 0x01: carry = "0"
            elif mn == "SEP":
                bits = int(arg[2:], 16)
                if bits & 0x20: st["m8"] = True
                if bits & 0x10: st["x8"] = True
            elif mn in ("JSR", "JSL"):
                if "table" in info:
                    ents = self.tables.get(info["table"], [])
                    emit(f"switch ({self.switch_index(st['X'])}) {{")
                    for k, e in enumerate(ents):
                        emit(f"    case {k * 2}: {self.fname.get(e, hex(e))}(self); break;")
                    emit("}")
                    st.update(A="A", X="X", Y="Y")
                    flags = None
                    continue
                if t in ALLOCATORS:
                    var = "s"
                    emit(f"Obj *{var} = {ALLOCATORS[t]}();")
                    st["X"] = var
                    st["alloc"] = t
                    flags = ("alloc", var)
                    continue
                name = HELPERS.get(t) or (self.fname.get(t) if t in self.func_starts else None) or f"sub_{t:06X}"
                args = []
                if t in TAKES_A:
                    args.append(str(st["A"]))
                if t == 0x82FC48:
                    args += [str(st["X"]), str(st["Y"])]
                local = t in self.func_starts
                call = f"{name}({'self' if local else ', '.join(args)})"
                # result used by the following branch(es)?
                uses = 0
                for k in range(i + 1, len(ins) + 1):
                    if k < len(ins):
                        mm = self.seen[ins[k]][1].split()[0]
                    else:
                        mm = self.seen[ins[-1]][1].split()[0]
                    break
                if nxt_mn in COND:
                    flags = ("res", call)
                    if t == 0x849086:   # random(): value in A
                        st["A"] = "r"
                        emit(f"r = {call};")
                        flags = ("val", "r")
                else:
                    if t == 0x849086 or (t == 0x84A081):
                        var = "r" if t == 0x849086 else "angle"
                        emit(f"{var} = {call};")
                        st["A"] = var
                    else:
                        emit(f"{call};")
                        st["A"] = "A"
                    flags = None
                st["X"], st["Y"] = ("X", "Y") if t not in ALLOCATORS else (st["X"], st["Y"])
            elif mn in ("JMP", "JML"):
                if "table" in info:
                    ents = self.tables.get(info["table"], [])
                    emit(f"switch ({self.switch_index(st['X'])}) {{")
                    for k, e in enumerate(ents):
                        emit(f"    case {k * 2}: {self.fname.get(e, hex(e))}(self); return;")
                    emit("}")
                    return lines, ("exit",)
                if t in HELPERS:
                    emit(f"{HELPERS[t]}();")
                    emit("return;")
                    return lines, ("exit",)
                if t in self.func_starts:
                    emit(f"{self.fname[t]}(self);")
                    emit("return;")
                    return lines, ("exit",)
                emit(f"goto sub_{t:06X};")
                return lines, ("exit",)
            elif mn in ("RTS", "RTL", "RTI"):
                emit("return;")
                return lines, ("exit",)
            elif mn in ("BRA", "BRL"):
                if t in self.func_starts:
                    emit(f"{self.fname[t]}(self);")
                    emit("return;")
                    return lines, ("exit",)
                return lines, ("goto", t)
            elif mn in COND:
                cond = self.cond(mn, flags, carry)
                fall = self.next_addr.get(a)
                return lines, ("cond", cond, t, fall if fall in self.blocks else None)
            else:
                emit(f"/* {txt} */")
            if mn not in ("ASL", "LSR"):
                shift = None
        fall = self.next_addr.get(ins[-1])
        return lines, ("next", fall if fall in self.blocks else None)

    def switch_index(self, x):
        return x

    def cond(self, mn, flags, carry):
        """Condition under which the branch is TAKEN."""
        if mn in ("BCC", "BCS") and (flags is None or flags[0] != "cmp"):
            c = carry or "carry"
            return c if mn == "BCS" else neg(c)
        if flags is None:
            return {"BEQ": "zero", "BNE": "!zero", "BMI": "negative", "BPL": "!negative",
                    "BVC": "!overflow", "BVS": "overflow"}.get(mn, mn)
        kind = flags[0]
        if kind == "alloc":
            v = flags[1]
            return {"BNE": f"!{v}", "BEQ": v}.get(mn, f"/*{mn}*/ {v}")
        if kind == "res":
            c = flags[1]
            return {"BEQ": f"!{c}", "BNE": c, "BMI": f"{c} < 0", "BPL": f"{c} >= 0",
                    "BVS": f"{c} /* overflow */", "BVC": f"!{c} /* overflow */"}.get(mn, c)
        if kind == "cmp":
            _, l, r = flags
            return {"BEQ": f"{l} == {r}", "BNE": f"{l} != {r}", "BCC": f"{l} < {r}", "BCS": f"{l} >= {r}",
                    "BMI": f"(int8_t)({l} - {r}) < 0", "BPL": f"(int8_t)({l} - {r}) >= 0"}.get(mn, mn)
        if kind == "bit":
            m = flags[1]
            return {"BMI": f"{m} & 0x80", "BPL": f"!({m} & 0x80)", "BVS": f"{m} & 0x40", "BVC": f"!({m} & 0x40)",
                    "BEQ": f"!(A & {m})", "BNE": f"A & {m}"}.get(mn, mn)
        e = par(flags[1])
        return {"BEQ": f"{e} == 0", "BNE": f"{e} != 0", "BMI": f"{par(e)} & 0x80", "BPL": f"!({par(e)} & 0x80)",
                "BVS": "overflow", "BVC": "!overflow"}.get(mn, mn)


def tidy(text):
    """Small readability rewrites on the final text."""
    text = text.replace("->attr & 0x40", "->attr & FLIP_X")
    text = re.sub(r"\((\w+->attr & FLIP_X)\) \?", r"(\1) ?", text)
    text = re.sub(r"(\w[\w\->\[\]\.]*) != 0\)", r"\1)", text)               # x != 0  ->  x
    text = re.sub(r"\(([\w\->\[\]\.]+) == 0\)", r"(!\1)", text)               # (x == 0) -> (!x)
    text = re.sub(r"if \(\((.+?)\) != 0\)", r"if (\1)", text)
    return text


def decompile_with_map(rom, entry, boss=None):
    """(text, {line number (1-based): SNES address}) — the map drives side-by-side sync."""
    raw = tidy(Decompiler(rom, entry, boss).decompile())
    lines, amap = [], {}
    for n, line in enumerate(raw.splitlines(), 1):
        code, sep, addr = line.partition("\t@@")
        lines.append(code.rstrip())
        if sep:
            amap[n] = int(addr, 16)
    return "\n".join(lines), amap


def decompile(rom, entry, boss=None):
    return decompile_with_map(rom, entry, boss)[0]


if __name__ == "__main__":
    from defs import BOSSES, PLAYER
    g = MMX1(ROM)
    arg = sys.argv[1]
    boss = PLAYER if arg == PLAYER.key else BOSSES.get(arg)
    entry = boss.routine if boss else int(arg, 16)
    if not boss:
        boss = next((b for b in BOSSES.values() if b.routine == entry), None)
    print(decompile(g.rom, entry, boss))
