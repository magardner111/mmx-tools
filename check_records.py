"""
Checks that our records of the game's code agree with each other.

    python3 check_records.py        # prints problems; exit code 1 if there are any

Sources of names: lift.py (HELPERS = routines, RAM_NAMES = RAM, FIELDS = object fields), defs.py (every boss in
BOSSES, PLAYER for X, KNOWN_OBJECT_NAMES). Docs: every *.md in the project. Tests: every verify_*.py.
Each kind of record has one check function below, registered with @check; when we start recording a new kind of
thing (projectile ids, sounds, music, enemies...), add its check here. How to fix what this reports:
.claude/skills/sync-records/SKILL.md.
"""
import glob
import re
import sys

import defs
import lift

DOCS = sorted(glob.glob("*.md"))
TESTS = sorted(glob.glob("verify_*.py"))
CODE = ["lift.py", "defs.py", "decomp.py", "mesen_verify.py", "testwarp.py"]
OBJECTS = list(defs.BOSSES.values()) + [defs.PLAYER]          # everything with fields / func_names
X_BASE = 0x0BA8
STOCK_ROM = "Mega Man X (USA) (Rev 1).sfc"
# reviewed: these objects really use a generic field's slot for something else
FIELD_OVERRIDES = {("launch_octopus", 0x0C), ("bosspider", 0x1F)}
RENAMED = {"X_f30": "X_hurt_lock", "anim_ptr": "box_ptr", "quake_time": "stun_window", "x_in_attack_box": "obj_overlaps",
           "armor_stun": "armor_invuln", "hop_jump": "whirlpool_jump",
           "cloak_move": "cloak_fade"}     # old -> new; add to this when renaming

CHECKS = []
problems = []


def check(fn):
    CHECKS.append(fn)
    return fn


def problem(kind, msg):
    problems.append((kind, msg))


def snes(a):
    return f"${a >> 16:02X}:{a & 0xFFFF:04X}"


def routine_names():
    r = {}
    for a, n in lift.HELPERS.items():
        r.setdefault(a, {})["lift.HELPERS"] = n
    for b in OBJECTS:
        for a, n in (getattr(b, "func_names", None) or {}).items():
            r.setdefault(a, {})[f"defs.{b.key}"] = n
    return r


def doc_lines():
    for path in DOCS:
        for i, line in enumerate(open(path).read().splitlines(), 1):
            yield path, i, line


def snake(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@check
def one_name_per_routine():
    """The same routine address has the same name everywhere (lift.HELPERS, every boss, PLAYER)."""
    for a, where in routine_names().items():
        if len(set(where.values())) > 1:
            problem("name clash", f"{snes(a)} has different names: {where}")


@check
def x_fields_match_ram_names():
    """X's fields in defs.PLAYER agree with lift.RAM_NAMES at $0BA8 + offset (X_ prefix in lift)."""
    for off, n in defs.PLAYER.fields.items():
        ram = lift.RAM_NAMES.get(X_BASE + off)
        if ram and ram.lower() != f"x_{n}".lower():
            problem("name clash", f"X field ${off:02X} is '{n}' in defs.PLAYER but RAM ${X_BASE + off:04X} is "
                                  f"'{ram}' in lift.py")


@check
def boss_fields_vs_generic():
    """A boss field at a generic offset uses the generic name, unless reviewed in FIELD_OVERRIDES."""
    for b in defs.BOSSES.values():
        for off, n in (b.fields or {}).items():
            g = lift.FIELDS.get(off)
            if g and g != n and (b.key, off) not in FIELD_OVERRIDES:
                problem("name clash", f"{b.key} field ${off:02X} = '{n}' but lift.FIELDS calls it '{g}'")


@check
def boss_attack_names():
    """Each boss: every attack in its table is described in attacks_doc, and the fight-table handler for that
    step is named after it (attack_handlers[step / 2])."""
    for b in defs.BOSSES.values():
        for t in b.attack_tables:
            for step, name in t.attacks.items():
                if name not in b.attacks_doc:
                    problem("boss record", f"{b.key}: attack '{name}' (table {snes(t.addr)}) has no attacks_doc entry")
                hs = b.attack_handlers
                if hs and step // 2 < len(hs) and hs[step // 2] not in snake(name) and snake(name) not in hs[step // 2]:
                    problem("boss record", f"{b.key}: step {step} is '{name}' in the table but handler "
                                           f"'{hs[step // 2]}' in attack_handlers")


@check
def boss_identity_in_docs():
    """A doc line naming a boss together with a boss routine address uses that boss's own routine."""
    routines = {snes(b.routine): b for b in defs.BOSSES.values()}
    for path, i, line in doc_lines():
        for tag in re.findall(r"\$[0-9A-F]{2}:[0-9A-F]{4}", line):
            b = routines.get(tag)
            if not b:
                continue
            others = [o for o in defs.BOSSES.values() if o is not b and o.name in line and b.name not in line]
            if others:
                problem("boss record", f"{path}:{i}: {tag} is {b.name}'s routine but the line names {others[0].name}")


@check
def object_names():
    """Boss object ids in KNOWN_OBJECT_NAMES match defs.BOSSES."""
    for b in defs.BOSSES.values():
        n = defs.KNOWN_OBJECT_NAMES.get(b.object_id, "")
        if b.name not in n:
            problem("object name", f"object ${b.object_id:02X} is {b.name} in BOSSES but '{n}' in KNOWN_OBJECT_NAMES")


@check
def docs_name_their_addresses():
    """In every doc, a routine or RAM address we have a name for carries that name on the same line."""
    names_by_tag = {snes(a): set(w.values()) for a, w in routine_names().items()}
    ram_by_tag = {f"${a:04X}": n for a, n in lift.RAM_NAMES.items()}
    for path, i, line in doc_lines():
        for tag in re.findall(r"\$[0-9A-F]{2}:[0-9A-F]{4}", line):
            nm = names_by_tag.get(tag)
            if nm and not any(n in line for n in nm):
                problem("doc missing name", f"{path}:{i}: {tag} is {sorted(nm)}")
        for tag in re.findall(r"`(\$[0-9A-F]{4})`", line):
            nm = ram_by_tag.get(tag)
            short = nm[2:] if nm and nm.startswith("X_") else nm      # PLAYER.md's field tables use the field name
            if nm and nm not in line and not re.search(rf"\b{re.escape(short or '')}\b", line):
                problem("doc missing name", f"{path}:{i}: RAM {tag} is '{nm}'")


@check
def verified_not_marked_guess():
    """A routine listed in VERIFIED.md isn't still marked (?) in lift.py."""
    verified = open("VERIFIED.md").read() if glob.glob("VERIFIED.md") else ""
    src = open("lift.py").read()
    for a, n in lift.HELPERS.items():
        m = re.search(rf'0x{a:06X}: "{re.escape(n)}",\s*#([^\n]*)', src)
        if m and "(?)" in m.group(1) and f"`{n}`" in verified:
            problem("marking", f"{n} ({snes(a)}) is in VERIFIED.md but marked (?) in lift.py")


@check
def player_step_table():
    """PLAYER.md's step table uses the same names as defs.PLAYER.func_names."""
    pm = open("PLAYER.md").read() if glob.glob("PLAYER.md") else ""
    for m in re.finditer(r"\| `\$[0-9A-F]{2}` \| `(\$81:[0-9A-F]{4})` \| `?(\w*)`? \|", pm):
        addr = int(m.group(1)[1:].replace(":", ""), 16)
        want = defs.PLAYER.func_names.get(addr)
        if want and m.group(2) != want:
            problem("name clash", f"PLAYER.md step row {m.group(1)} says '{m.group(2)}', defs.PLAYER says '{want}'")
        if not want:
            problem("missing symbol", f"PLAYER.md step handler {m.group(1)} has no name in defs.PLAYER.func_names")


@check
def enemy_shots():
    """defs.ENEMY_SHOTS matches the ROM's enemy-shot dispatch table, and every "enemy shot 0xNN" in a boss's
    attacks_doc is listed (and, if the shot's name names a boss, it's that boss's)."""
    from mmx1 import MMX1, snes2pc
    g = MMX1(STOCK_ROM)
    base = snes2pc(defs.ENEMY_SHOT_DISPATCH)
    for i, (name, routine, _) in defs.ENEMY_SHOTS.items():
        stub = snes2pc(0x800000 | g.w(base + 2 * i))
        if g.rom[stub] != 0x22 or g.l(stub + 1) != routine:
            problem("enemy shot", f"shot 0x{i:02X} ({name}): ROM dispatches to {snes(g.l(stub + 1))}, defs says {snes(routine)}")
    for b in defs.BOSSES.values():
        for attack, text in b.attacks_doc.items():
            for m in re.findall(r"enemy shots? (0x[0-9A-F]{2})", text):
                i = int(m, 16)
                if i not in defs.ENEMY_SHOTS:
                    problem("enemy shot", f"{b.name} '{attack}' mentions enemy shot {m}, not in defs.ENEMY_SHOTS")
                elif "'s " in defs.ENEMY_SHOTS[i][0] and not defs.ENEMY_SHOTS[i][0].startswith(b.name.split(" (")[0]):
                    problem("enemy shot", f"{b.name} '{attack}' uses enemy shot {m}, listed as {defs.ENEMY_SHOTS[i][0]}")


@check
def no_old_names():
    """Names in RENAMED don't come back anywhere (docs, tests, code)."""
    for path in TESTS + DOCS + CODE:
        for i, line in enumerate(open(path).read().splitlines(), 1):
            for old, new in RENAMED.items():
                if re.search(rf"\b{old}\b", line) and "RENAMED" not in line:
                    problem("old name", f"{path}:{i}: '{old}' was renamed to '{new}'")


@check
def tests_use_current_names():
    """A verify script that logs a routine under a tag doesn't use another routine's name for it."""
    rn = {a: set(w.values()) for a, w in routine_names().items()}
    allnames = {n for v in rn.values() for n in v}
    for path in TESTS:
        for m in re.finditer(r"0x([0-9A-F]{6}): \"(\w+)\"", open(path).read()):
            a, tag = int(m.group(1), 16), m.group(2)
            if tag in allnames and tag not in rn.get(a, set()):
                problem("test tag", f"{path}: tag '{tag}' on {snes(int(m.group(1), 16))}, but '{tag}' is another routine")


if __name__ == "__main__":
    for fn in CHECKS:
        fn()
    kinds = {}
    for k, m in problems:
        kinds.setdefault(k, []).append(m)
    for k, ms in kinds.items():
        print(f"== {k} ({len(ms)})")
        for m in ms:
            print("  " + m)
    print(f"\n{len(CHECKS)} checks over {len(defs.BOSSES)} bosses + X, {len(DOCS)} docs, {len(TESTS)} test scripts")
    print(f"{len(problems)} problem(s)" if problems else "records consistent")
    sys.exit(1 if problems else 0)
