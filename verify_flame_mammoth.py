"""
Re-checks everything we claim about Flame Mammoth by running the game in Mesen (see mesen_verify.py).

    python3 verify_flame_mammoth.py          # about 15 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_flame_mammoth.py --cached # re-check the last run's saved output

His boss checkpoint (2, x=7552) is between his two doors, so X walks right through the second door; the
belt then carries X toward him until he is within 128 px and the intro runs. The suite plays that once and
saves a state at the first frame of the fight (work/states/flame_mammoth_fight.mss); most runs start from it.
Runs that check the intro or values the intro copies into RAM (max HP, trunk HP) play it in full.

Once he fights, the no-damage AR code is on (unless a test needs X hurt or stunned). Instead of relying on
chance, tests set things up exactly with hooks on his own instructions (Run.at_exec):
  - the attack pick: X is put at a chosen distance and `random`'s result is replaced, stepping through every
    row and column of the table at $86:C843;
  - choose_next_attack: X's y is set just above / at the "X is high" line;
  - the Stomp jump's aim: X's x is read exactly when he reads it.
A table that holds only one attack freezes the game (after 3 repeats he re-picks forever; checked below), so
single-attack runs also raise the repeat limit ($87:970A, 3 -> $FF) in the test ROM.
"""
import collections
import json
import sys

import params as P
from defs import FLAME_MAMMOTH as FM, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state, countdown

ID, TRUNK, FIRE_ID, OIL_ID = 0x0C, 0x0E, 0x20, 0x21
CACHE = "work/flame_mammoth_runs.json"
STATE = "work/states/flame_mammoth_fight.mss"
LEFT = 7690                         # leftmost spot X can stand in his room
PAR = {p.key: p for p in FM.params}
TABLE = FM.attack_tables[0].addr
REPEAT_LIMIT = 0x87970A             # operand of CMP #$03 in pick_from_table
FIELDS = {0x879663: "choose", 0x8796BF: "pick", 0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze",
          0x84AADD: "beaten", 0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound",
          0x828358: "alloc_shot", 0x828321: "alloc_enemy", 0x84A677: "defeat_seq", 0x849B43: "hit_check",
          0x849B03: "hurt_x", 0x84ACA5: "face_x", 0x8281E8: "move_grav", 0x8491BE: "terrain",
          0x84A338: "shake", 0x848000: "stage_tiles", 0x84A00D: "x_stun", 0x828398: "despawn",
          0x879773: "oil_edge", 0x87976E: "oil_dist", 0x878891: "oil_slow", 0x8787AA: "ignite"}
M = f"find(0x0E68, 0x1228, {ID})"


def hold(tgt):
    """X walks to `tgt` and stays there (against the belt); every 16 frames he turns to face Mammoth."""
    return f"""local m = {M}
local xx = r16(0x0BAD)
local inp = {{}}
if xx < {tgt} - 6 then inp.right = true elseif xx > {tgt} + 6 then inp.left = true
elseif m and r8(m + 1) == 4 and frame % 16 == 0 then
  if r16(m + 5) > xx then inp.right = true else inp.left = true end end
if fire and frame % 16 < 8 then inp.y = true end
return inp"""


HOLD = hold(7700)
# X jumps while he comes down on every other Stomp jump, so some landings find X in the air
STUN_JUMPS = f"""local m = {M}
if m and r8(m + 2) == 0 and r8(m + 3) == 6 then
  if not falling then falling = true; stomps = (stomps or 0) + 1 end
else falling = false end
return {{b = falling and stomps % 2 == 0}}"""
FIRE = "fire = true\n" + HOLD
PACE = """local xx = r16(0x0BAD)
if xx < 7710 then goright = true elseif xx > 7960 then goright = false end
return {right = goright, left = not goright}"""
WALK_IN = "return {right = r16(0x0BAD) < 7700}"
NO_DAMAGE = f"do local m = {M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
SET_HP1 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); hpset = true end end"
CUTTER = "w16(0x1F93, 0xDC00); w8(0x0BDB, 14)"      # own Boomerang Cutter with ammo, and select it
TORNADO = "w16(0x1F8F, 0xDC00); w8(0x0BDB, 10)"     # Storm Tornado
SHOTS = (f'for a = 0x1428, 0x1600, 0x40 do local i = r8(a + 10); if r8(a) ~= 0 and (i == {FIRE_ID} or i == {OIL_ID}) '
         'then out("sh", "slot=" .. a .. " id=" .. i .. " state=" .. r8(a + 1) .. " x=" .. r16(a + 5) .. " y=" .. '
         'r16(a + 8) .. " vx=" .. s16(a + 0x1A) .. " vy=" .. s16(a + 0x1C) .. " attr=" .. r8(a + 0x11) .. '
         '" t=" .. r8(a + 0x37)) end end')
# hooks (Lua run before an instruction; `s` = CPU state, D = his slot)
AIM_LOG = (0x8793C1, 'out("aim", "xx=" .. r16(0x0BAD) .. " mx=" .. r16(s["cpu.d"] + 5))')   # stomp: LDA X_x
PICK_LOG = (0x879689, 'out("pickpos", "xx=" .. r16(0x0BAD) .. " mx=" .. r16(s["cpu.d"] + 5) .. " trunk=" .. '
                      'r8(s["cpu.d"] + 0x36) .. " last=" .. r8(s["cpu.d"] + 0x3B) .. " rep=" .. r8(s["cpu.d"] + 0x3C) .. '
                      '" oils=" .. count(0x1428, 0x1628, 0x21))')


def place_x(d):
    """Lua: put X `d` px from him (left of him if there's room)."""
    return (f'do local mx = r16(s["cpu.d"] + 5); local d = {d}; '
            f'if mx - d >= {LEFT} then w16(0x0BAD, mx - d) else w16(0x0BAD, mx + d) end end')


def force_table(start, dists):
    """Hooks stepping through the table: pick n uses row (n // 16) % 6, column n % 16. The row's distance band
    comes from moving X (`dists` = one distance per band), the trunk rows from setting trunk_hp."""
    pick = (f'fm_n = (fm_n or {start - 1}) + 1; local row = (fm_n // 16) % 6; fm_col = fm_n % 16; '
            f'local d = ({{{", ".join(map(str, dists))}}})[row % 3 + 1]; '
            f'w8(s["cpu.d"] + 0x36, row >= 3 and 0 or 3); ' + place_x("d") +
            ' out("force", "n=" .. fm_n .. " row=" .. row .. " col=" .. fm_col .. " d=" .. d)')
    return [(0x879689, pick), (0x8796B8, 'setreg("cpu.a", (s["cpu.a"] & 0xFF00) | fm_col)')]


def first_then(col_first, col_again, trunk=3):
    """Hooks: the first pick of a frame takes column `col_first`, any re-pick that frame `col_again`; X stands
    40 px away (row 0); trunk_hp is held at `trunk`."""
    pick = (f'if fm_f ~= frame then fm_f = frame; fm_k = 0 end; fm_k = fm_k + 1; '
            f'fm_col = fm_k == 1 and {col_first} or {col_again}; w8(s["cpu.d"] + 0x36, {trunk}); ' + place_x(40))
    return [(0x879689, pick), (0x8796B8, 'setreg("cpu.a", (s["cpu.a"] & 0xFF00) | fm_col)')]


def oil_first():
    """Hooks: the first pick of a frame takes the Oil shot column of X's distance band, re-picks the Stomp jump."""
    pick = ('if fm_f ~= frame then fm_f = frame; fm_k = 0 end; fm_k = fm_k + 1; '
            'local d = math.abs(r16(s["cpu.d"] + 5) - r16(0x0BAD)); '
            'fm_col = fm_k > 1 and 0 or (d < 80 and 2 or (d < 128 and 5 or 12))')
    return [(0x879689, pick), (0x8796B8, 'setreg("cpu.a", (s["cpu.a"] & 0xFF00) | fm_col)')]


# the oil puddle's slowdown: new X.x it stores, X.x at the start of X's update ($0BCA) and X.x now
OIL_AVG = (0x8788AF, 'out("avg", "new=" .. s["cpu.a"] .. " prev=" .. r16(0x0BCA) .. " cur=" .. r16(0x0BAD))')
# choose_next_attack: X's y set to 110, 111, 112, 113 px below the screen top in turn ("high" means < 112)
HIGH = [(0x879663, 'fm_h = ((fm_h or -1) + 1) % 4; w16(0x0BB0, r16(0x1E50) + 110 + fm_h); '
                   'out("high", "dy=" .. (110 + fm_h))')]
# the Stomp jump aims straight up (X moved under him while he reads X's x, then put back): X is never hit
STRAIGHT_UP = [(0x8793C1, 'fm_keep = r16(0x0BAD); w16(0x0BAD, r16(s["cpu.d"] + 5))'),
               (0x8793C4, 'w16(0x0BAD, fm_keep)')]

DISTS = [(79, 127, 160), (40, 80, 128)]     # one distance per band, at and away from the band edges
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def patch(attack=None, **values):
    """ROM patch: optionally every table entry = `attack` (with the repeat limit raised so it can't freeze),
    plus changed editable values."""
    def f(g):
        if attack is not None:
            t = snes2pc(TABLE)
            g.rom[t:t + 96] = bytes([attack]) * 96
            g.rom[snes2pc(REPEAT_LIMIT)] = 0xFF
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


FAST = patch(spit_pause=1, volley_pause=1, conveyor_wait=1)   # table runs: shorter pauses, more picks


def freeze_patch(g):
    """Every table entry = Stomp jump, repeat limit left alone."""
    t = snes2pc(TABLE)
    g.rom[t:t + 96] = bytes(96)


def run(frames, inp=HOLD, seed=None, inf=True, ar=True, rom=None, extra=(), hooks=(), full=False, watch_all=True):
    r = Run(level=4, x=7552, frames=frames, seed=seed, infinite_hp=inf, patch=rom,
            savestate=None if full else STATE)
    r.track(ID, tag="fm").track(TRUNK, tag="trunk")
    for a, t in (FIELDS.items() if watch_all else [(0x879663, "choose"), (0x8796BF, "pick")]):
        r.on_exec(a, t)
    for a, lua in [AIM_LOG, PICK_LOG, *hooks]:
        r.at_exec(a, lua)
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.on_write(0x1F0E, "hud_boss")
    r.input(inp)
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame('if r16(0x0BAD) ~= lastx or r16(0x0BB0) ~= lasty or r8(0x0BAA) ~= laststep or r8(0x0C32) ~= lastu '
                 'or r8(0x0C06) ~= lastt then out("X", "x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0) .. " step=" .. '
                 'r8(0x0BAA) .. " hp=" .. (r8(0x0BCF) & 0x7F) .. " stun=" .. r8(0x0C2D) .. " touch=" .. r8(0x0C06) .. '
                 '" untouchable=" .. r8(0x0C32)); lastx = r16(0x0BAD); lasty = r16(0x0BB0); laststep = r8(0x0BAA); '
                 'lastu = r8(0x0C32); lastt = r8(0x0C06) end')
    r.each_frame('out("cam", "l=" .. r16(0x1E4D) .. " t=" .. r16(0x1E50) .. " bl=" .. r16(0x1E5E) .. " br=" .. r16(0x1E60))')
    r.each_frame(SHOTS)
    for lua in extra:
        r.each_frame(lua)
    return r


class T:
    """Helpers over one run's events. Event frames: an exec/hook event logged while frame k is emulated has
    f = k - 1; per-frame records (fm, X, cam, sh) for that frame have f = k."""
    def __init__(self, ev):
        self.ev = ev
        self.by_tag = collections.defaultdict(list)
        for e in ev:
            self.by_tag[e["tag"]].append(e)
        self._lives, self._calls = {}, {}
        self.p = [e for e in self.by_tag["fm"] if "slot" in e]
        self.slot = self.p[0]["slot"] if self.p else None
        self.at = {e["f"]: e for e in self.p}
        self.trunk = {e["f"]: e for e in self.by_tag["trunk"] if "slot" in e}
        self.cam = {e["f"]: e for e in self.by_tag["cam"]}
        self.sh = collections.defaultdict(list)
        for e in self.by_tag["sh"]:
            self.sh[e["f"]].append(e)
        xs = self.by_tag["X"]
        self.x, i, cur = {}, 0, None          # X on every frame (logged only when something changes)
        for f in range(0, (ev[-1]["f"] if ev else 0) + 1):
            while i < len(xs) and xs[i]["f"] <= f:
                cur, i = xs[i], i + 1
            if cur:
                self.x[f] = cur

    def calls(self, tag, mine=True):
        k = (tag, mine)
        if k not in self._calls:
            self._calls[k] = [e for e in self.by_tag[tag] if not mine or e.get("d") == self.slot]
        return self._calls[k]

    def starts(self, cond):
        return [e for i, e in enumerate(self.p) if cond(e) and (i == 0 or not cond(self.p[i - 1]))]

    def phase(self, s):
        """Records from `s` while his state/step/substep stay the same ([] if the run ends first)."""
        out, key = [], (s["state"], s["step"], s["sub"])
        for f in range(s["f"], s["f"] + 3000):
            e = self.at.get(f)
            if e is None:
                return []
            if (e["state"], e["step"], e["sub"]) != key:
                return out
            out.append(e)
        return []

    def after(self, s):
        """His first record after the phase starting at `s`."""
        ph = self.phase(s)
        return self.at.get(ph[-1]["f"] + 1) if ph else None

    def fight(self, step, sub):
        return lambda e: e["state"] == 4 and e["step"] == step and e["sub"] == sub

    def shot_lives(self, sid):
        """Each life of shot `sid`: its per-frame records."""
        if sid in self._lives:
            return self._lives[sid]
        lives, cur = [], {}
        for f in sorted(self.sh):
            seen = set()
            for s in self.sh[f]:
                if s["id"] != sid:
                    continue
                k = s["slot"]
                seen.add(k)
                if k not in cur:
                    cur[k] = []
                    lives.append(cur[k])
                cur[k].append(s)
            for k in [k for k in cur if k not in seen]:
                del cur[k]
        self._lives[sid] = lives
        return lives

    def pick_frames(self):
        """{frame: [pick-related events, in order]}."""
        byf = collections.defaultdict(list)
        for e in self.ev:
            if e["tag"] in ("pick", "pickpos", "force") or (e["tag"] == "choose" and e.get("d") == self.slot):
                byf[e["f"]].append(e)
        return byf


def timers(xs, step, sub, field, start):
    """countdown() over every complete phase (step, sub) in these runs."""
    res = []
    for x in xs:
        for s in x.starts(x.fight(step, sub)):
            ph = x.phase(s)
            if ph:
                res.append(countdown(ph, field, start))
    return res


def main():
    natural = [("n0", 0x1111, 7700), ("n1", 0x2345, 7800), ("n2", 0x3C3C, 7940), ("n3", 0x4A21, 7700),
               ("n4", 0x5EED, 7860), ("n5", 0x6F01, 7760)]
    runs = {k: run(5000, hold(tg), seed=s) for k, s, tg in natural}
    runs.update({
        "intro": run(1500, WALK_IN, seed=0x1234, full=True),
        **{f"table{i}": run(6000, seed=0x1001 + i, rom=FAST, hooks=force_table(12 * i, DISTS[i % 2]))
           for i in range(8)},
        "repeat": run(3000, seed=0x1005, hooks=first_then(0, 6)),
        "repeat_cut": run(3000, seed=0x1006, hooks=first_then(0, 6, trunk=0)),
        "oil": run(4000, PACE, seed=0x1007, hooks=oil_first() + [OIL_AVG]),
        "high": run(3000, seed=0x1008, hooks=HIGH),
        "stun": run(4000, STUN_JUMPS, seed=0x1009, ar=False, rom=patch(0),
                    hooks=STRAIGHT_UP, extra=["w16(0x0BAD, 7760)"]),     # (at 7700 X sinks into the floor's edge)
        "belt": run(2000, "return {}", seed=0x100A, rom=patch(4)),
        "volleys": run(6000, seed=0x100B, rom=patch(4)),
        "buster": run(3000, FIRE, seed=0x2001),
        "cutter": run(3000, FIRE, seed=0x2002, extra=[CUTTER]),
        "tornado": run(2400, FIRE, seed=0x2003, extra=[TORNADO]),
        "death": run(1500, FIRE, seed=0x2004, extra=[SET_HP1]),
        "x_dies": run(2500, seed=0x2005, inf=False, ar=False),
        "v_hit": run(2600, FIRE, seed=0x3001, full=True, rom=patch(max_hp=20, invuln_time=0x20)),
        "v_trunk": run(2600, FIRE, seed=0x3002, full=True, rom=patch(trunk_hits=1), extra=[CUTTER]),
        "v_jump": run(2000, seed=0x3003, rom=patch(0, stomp_jump=0x400, stun_window=0x50)),
        "v_oil": run(2000, seed=0x3004, rom=patch(spit_pause=0x20), hooks=oil_first()),
        "v_volley": run(2400, seed=0x3005, rom=patch(4, volley_shots=6, volley_pause=0x20)),
        "v_belt": run(2400, seed=0x3006, rom=patch(6, conveyor_wait=0x20)),
        "freeze": run(1500, seed=0x3007, rom=freeze_patch, watch_all=False),
    })
    if "--cached" in sys.argv:              # re-check the last run's output without emulating again
        out = json.load(open(CACHE))
    else:
        print("playing to the start of the fight...", flush=True)
        fight_state(STATE, 4, 7552, WALK_IN, f"(function() local m = {M}; return m and r8(m + 1) == 4 end)()")
        print(f"running {len(runs)} emulator sessions, 4 at a time...", flush=True)
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    t = {k: T(v) for k, v in out.items()}
    nat = [t[k] for k, _, _ in natural]
    alls = [x for k, x in t.items() if k != "freeze"]
    g = MMX1("work/hack.sfc")
    tbl = list(g.rom[snes2pc(TABLE):snes2pc(TABLE) + 96])
    dt = snes2pc(DAMAGE_TABLE)
    row8 = g.rom[dt + g.w(dt + 16):][:32]

    # --- intro -------------------------------------------------------------------------------
    n = t["intro"]
    init = n.starts(lambda e: e["state"] == 0 and e["step"] == 1)[0]
    check("init: boss_already_beaten, jingle $2E, x_freeze_for_boss",
          n.calls("beaten") and n.calls("x_freeze", False) and any(c["a"] & 0xFF == 0x2E for c in n.calls("music", False)))
    check("init: trunk_hp ($36) = 3, belt_direction ($38) = 2", init["f36"] == 3 and init["f38"] == 2)
    tr = [e for f, e in sorted(n.trunk.items())]
    check("init: spawns his trunk (enemy $0E) with parent = him", tr and tr[0]["parent"] == n.slot)
    ok, a, b = countdown(n.phase(init), "f34", 60)
    check("init: 60-frame wait (timer $34 = 60, counted down to 0)", ok, f"{a}..{b}")
    st2 = n.starts(lambda e: e["state"] == 2)[0]
    check("obj_start: damage class 3; palette_bits ($33) = attr & $0E",
          st2["dmg"] == 3 and st2["f33"] == st2["attr"] & 0x0E, f"{st2['dmg']}, {st2['f33']}, {st2['attr']:#x}")
    a1 = n.starts(lambda e: e["state"] == 2 and e["step"] == 2)[0]
    check("intro: x += 64, border_right += 112", a1["x"] - st2["x"] == 64
          and n.cam[a1["f"]]["br"] - n.cam[st2["f"]]["br"] == 112,
          f"x {st2['x']} -> {a1['x']}, border_right {n.cam[st2['f']]['br']} -> {n.cam[a1['f']]['br']}")
    a2 = n.starts(lambda e: e["state"] == 2 and e["step"] == 4)[0]
    gaps = [n.at[f]["x"] - n.x[f]["x"] for f in (a2["f"] - 2, a2["f"] - 1)]
    check("intro: waits until X is within 128 px, then the boss bar (hud_boss) and pose 19 (anim 12)",
          gaps[0] >= 128 > gaps[1] and any(abs(e["f"] - a2["f"]) <= 1 for e in n.by_tag["hud_boss"])
          and any(c["a"] & 0xFF == 12 and c["f"] == a2["f"] - 1 for c in n.calls("anim")) and a2["f37"] == 19,
          f"distance {gaps}")
    xs = [n.x[f]["x"] for f in range(a1["f"], a2["f"])]
    check("intro: the belt carries X toward him (X held by x_freeze_for_boss, step $1E)", xs and xs[-1] > xs[0]
          and all(n.x[f]["step"] == 0x1E for f in range(a1["f"] + 1, a2["f"])), f"X {xs[0]} -> {xs[-1]}")
    ticks = [c["f"] for c in n.calls("sound_c") if n.at.get(c["f"] + 1, {}).get("state") == 2]
    check("HP fill: +1 every 2 frames to 32", len(ticks) == 32 and set(b - a for a, b in zip(ticks, ticks[1:])) == {2}
          and max(e["hp"] & 0x7F for e in n.p if e["state"] == 2) == 32, f"{len(ticks)} ticks")
    s8 = n.starts(lambda e: e["state"] == 2 and e["step"] == 8)[0]
    ok, a, b = countdown(n.phase(s8), "f34", 63)
    check("end of intro: the HP fill's timer (63) counts down, then x_unfreeze, boss music $1E, state 4",
          ok and n.calls("x_unfreeze", False) and any(c["a"] & 0xFF == 0x1E for c in n.calls("music", False))
          and n.after(s8)["state"] == 4, f"{a}..{b}")
    check("fight damage class 8 (5 while invulnerable)", all(e["dmg"] in (8, 5) for x in nat for e in x.p
                                                              if e["state"] == 4 and e["f"] > 60)
          and any(e["dmg"] == 8 for e in nat[0].p))

    # --- trunk ---------------------------------------------------------------------------------
    same = ok = 0
    for x in nat:
        for f, e in x.trunk.items():
            m = x.at.get(f)
            if m and m["state"] == 4 and e["state"] == 4:
                same += 1
                ok += (e["x"], e["y"], e["step"], e["sub"]) == (m["x"], m["y"], m["step"], m["sub"])
    check("trunk: has his x, y, state, step and substep every frame", same > 1000 and ok == same, f"{ok}/{same} frames")

    # --- Stomp jump ----------------------------------------------------------------------------
    good = []
    for k, x in t.items():
        if k == "stun":                     # (aims straight up there)
            continue
        aims = {e["f"]: e for e in x.by_tag["aim"]}
        for s in x.starts(x.fight(0, 2)):
            a = aims.get(s["f"] - 1)
            if a and "stomp_jump" not in k and k != "v_jump":
                good.append(s["vx"] == ((a["xx"] - a["mx"]) * 4 + 0x8000) % 0x10000 - 0x8000
                            and s["vy"] == 0x593 and s["grav"] == 48)
    check("Stomp jump: vx = (X.x − his x) × 4, vy $593, gravity 48", good and all(good), f"{sum(good)}/{len(good)}")
    lok = []
    for x in nat + [t["repeat"], t["repeat_cut"]]:
        for s in x.starts(x.fight(0, 8)):
            lok.append(any(c["a"] & 0xFF == 77 and c["f"] == s["f"] - 1 for c in x.calls("sound"))
                       and any(c["a"] & 0xFF == 75 and c["f"] == s["f"] - 1 for c in x.calls("shake", False))
                       and s["f3A"] == 29 and s["air"] == 0)
    check("Stomp jump: landing = sound $4D, screen_shake(75), stun_window ($3A) = 30 (29 by the end of that frame: "
          "with X untouchable it counts down at once)",
          lok and all(lok), f"{sum(lok)}/{len(lok)}")
    tm = timers(nat, 0, 10, "f34", 60)
    check("Stomp jump: then a 60-frame pause (timer $34)", tm and all(o for o, _, _ in tm), f"{len(tm)} pauses")

    st = t["stun"]
    stuns = st.calls("x_stun", False)
    detail, ok_now, ok_later, extra_ = [], [], [], []
    for s in st.starts(st.fight(0, 8)):
        lf = s["f"]
        xr = st.x.get(lf - 1)
        c = next((c for c in stuns if lf - 1 <= c["f"] <= lf + 31), None)
        on_ground = bool(xr and xr["touch"] & 4 and xr["untouchable"] == 0)
        if on_ground:
            ok_now.append(c is not None and c["f"] == lf - 1 and c["a"] & 0xFF == 30)
        elif c is not None:
            xa = st.x.get(c["f"] + 1)
            ok_later.append(c["a"] & 0xFF == 30 - (c["f"] - (lf - 1)) and xa and xa["step"] == 0x36)
        if c is not None:
            k = 0
            while st.x.get(c["f"] + 1 + k, {}).get("step") == 0x36:
                k += 1
            extra_.append(k - (c["a"] & 0xFF))
        detail.append((lf, on_ground, c and c["a"] & 0xFF))
    check("landing stun: X standing (and hurtable) when he lands -> x_stun(30) that frame",
          ok_now and all(ok_now), f"{sum(ok_now)}/{len(ok_now)}")
    check("landing stun: X landing later within the 30 frames -> x_stun(frames left)", ok_later and all(ok_later),
          f"{sum(ok_later)}/{len(ok_later)}; {detail[:8]}")
    check("x_stun(A): X step $36 lasts A frames plus a fixed get-up time", extra_ and len(set(extra_)) == 1,
          f"extra {sorted(set(extra_))}")
    nst = sum(len(x.calls("x_stun", False)) for x in nat)
    check("landing stun: never with the AR code on (X untouchable)", nst == 0, f"{nst} stuns")

    # --- Oil shot ------------------------------------------------------------------------------
    sp = []
    for x in alls:
        for life in x.shot_lives(OIL_ID):
            m = x.at.get(life[0]["f"])
            if m and len(life) > 1 and life[1]["state"] == 2:
                fr = life[0]["attr"] & 0x40
                sp.append((life[0]["x"] - m["x"], life[0]["y"] - m["y"], fr, life[1]["vx"], life[1]["vy"]))
    oko = [abs(dx) == 46 and (dx > 0) == bool(fr) and dy == -6 and vy == 0x200
           and ((0x280 <= vx <= 0x2FF) if fr else (-0x300 <= vx <= -0x281)) for dx, dy, fr, vx, vy in sp]
    check("Oil shot: enemy shot $21 at his x ± 46 (facing), y − 6; vx $280 + r right / −$300 + r left (r < 128), "
          "vy $200", oko and all(oko) and {s[2] for s in sp} == {0, 0x40}, f"{sum(oko)}/{len(oko)}")
    tm = timers(alls, 2, 4, "f34", 60)
    tm = [x for x in tm] if tm else tm
    check("Oil shot: then a 60-frame pause", timers(nat + [t["oil"]], 2, 4, "f34", 60)
          and all(o for o, _, _ in timers(nat + [t["oil"]], 2, 4, "f34", 60)), f"{len(tm)} pauses")
    o = t["oil"]
    rer, used = [], []
    for f, evs in o.pick_frames().items():
        tags = [e["tag"] for e in evs]
        pos = [e for e in evs if e["tag"] == "pickpos"]
        if not pos:
            continue
        if tags.count("pick") >= 2:
            i = tags.index("pick")
            rer.append("choose" in tags[i:] and pos[0]["oils"] >= 2)
        elif tags.count("pick") == 1:
            used.append(pos[0]["oils"] < 2 and o.at.get(f + 1, {}).get("step") in (2, 6))
    check("Oil shot: with 2 puddles out he chooses again (choose_next_attack -> a new pick)", rer and all(rer),
          f"{sum(rer)}/{len(rer)}")
    check("Oil shot: with fewer than 2 out he spits", used and all(used), f"{sum(used)}/{len(used)}")
    av = o.by_tag["avg"]
    exact = [e["new"] == (e["prev"] + e["cur"]) // 2 + ((e["prev"] + e["cur"]) % 2 if e["prev"] < e["cur"] else 0)
             for e in av]
    moved = [e for e in av if abs(e["cur"] - e["prev"]) >= 2]
    check("oil puddle: X touching it -> X.x = average of his x before this frame's move ($0BCA) and now, "
          "rounded toward now (a 2 px step becomes 1, a 1 px step stays; later pushes like the belt aren't halved)",
          len(av) > 50 and all(exact) and moved and all(abs(e["new"] - e["prev"]) < abs(e["cur"] - e["prev"]) for e in moved),
          f"{sum(exact)}/{len(exact)} frames")
    seg = {0: [], 1: [], 2: [], 3: []}
    for x in nat + [o]:
        for life in x.shot_lives(OIL_ID):
            run_ = []
            for a, b in zip(life, life[1:]):
                m = x.at.get(b["f"])
                if a["state"] == b["state"] == 4 and m and b["f"] == a["f"] + 1 and 7710 < b["x"] < 7990:
                    seg[m["f38"] & 1].append(b["x"] - a["x"])          # (away from the walls)
    for x in nat:
        for e in x.p:
            a = x.at.get(e["f"] - 1)
            if a and e["state"] == 4 and (a["step"], a["sub"]) == (e["step"], e["sub"]) and e["air"] == 0 \
                    and e["sub"] in (4, 6, 10) and 7720 < e["x"] < 7990:     # standing still: pauses, stomps
                seg[e["f38"] & 1 | 2].append(e["x"] - a["x"])
    mv = {d: sum(v) / len(v) for d, v in seg.items() if v}
    check("belt: a puddle on it, and Mammoth, move 0.5 px a frame; right while belt_direction bit 0 = 0, left while 1",
          len(mv) == 4 and all(abs(mv[d] - (0.5 if d % 2 == 0 else -0.5)) < 0.02 for d in mv),
          f"puddle {mv.get(0, 0):.3f} / {mv.get(1, 0):.3f}, him {mv.get(2, 0):.3f} / {mv.get(3, 0):.3f}")
    b = t["belt"]
    xd = [b.x[f]["x"] - b.x[f - 1]["x"] for f in range(20, max(b.x)) if f - 1 in b.x and b.x[f]["step"] == 0
          and b.x[f - 1]["step"] == 0 and b.x[f]["x"] < 8010]
    check("belt: carries X too, standing still (0.5 px a frame)", len(xd) > 100 and abs(sum(xd) / len(xd) - 0.5) < 0.02,
          f"X {sum(xd) / max(len(xd), 1):.3f} over {len(xd)} frames")
    ign = [(x, c) for x in alls for c in x.calls("ignite", False)]
    burn = []
    for x, c in ign:
        life = next((l for l in x.shot_lives(OIL_ID) for s in l if s["slot"] == c["d"] and s["f"] == c["f"] + 1), None)
        if life and life[-1]["f"] < max(x.sh):
            st_ = [s["state"] for s in life]
            ten = [s for s in life if s["state"] == 10]
            burn.append(6 in st_ and 8 in st_ and bool(ten) and ten[0]["t"] in (179, 180) and len(ten) >= 179)
    check("oil puddle: a fireball touching it sets it alight (sound $5C; states 6, 8, then burns 180 frames)",
          burn and all(burn) and any(c["a"] & 0xFF == 0x5C for x, _ in ign for c in x.calls("sound", False)),
          f"{sum(burn)}/{len(burn)}")

    # --- Fire volley ---------------------------------------------------------------------------
    counts, vok = collections.Counter(), []
    for x in nat + [t["volleys"]]:
        for s in x.starts(x.fight(4, 2)):
            prev = x.at.get(s["f"] - 1)
            fresh = prev and prev["f35"] == 0 and prev["step"] == 4 and prev["sub"] == 0
            if fresh:
                counts[s["f35"]] += 1
            nx = x.after(s)
            if nx and nx["sub"] == 4 and fresh:
                k = sum(1 for c in x.calls("alloc_shot") if s["f"] - 1 <= c["f"] <= nx["f"])
                vok.append(k == s["f35"])
    tot = sum(counts.values())
    exp = {3: 3 / 32, 4: 16 / 32, 5: 13 / 32}
    chi = sum((counts[k] - tot * p) ** 2 / (tot * p) for k, p in exp.items()) if tot else 99
    check("Fire volley: 3, 4 or 5 shots (4; half the time then +1 at 13/16, −1 at 3/16)",
          set(counts) <= {3, 4, 5} and tot >= 30 and chi < 9.2, f"{dict(counts)}, chi2={chi:.1f}/2")
    check("Fire volley: one shot per animation keyframe until shots_left ($35) = 0", vok and all(vok),
          f"{sum(vok)}/{len(vok)}")
    fs = []
    for x in nat:
        for life in x.shot_lives(FIRE_ID):
            m, xx = x.at.get(life[0]["f"]), x.x.get(life[0]["f"])
            v = next((s["vx"] for s in life[1:3] if s["vx"]), None)
            if m and xx and v:
                fs.append((life[0]["x"] - m["x"], life[0]["y"] - m["y"], life[0]["attr"] & 0x40, v,
                           abs(life[0]["x"] - xx["x"])))
    check("Fire volley: shots spawn at his x ± 42 (facing), y − 7", fs and all(abs(a) == 42 and (a > 0) == bool(fr)
          and b == -7 for a, b, fr, v, d in fs), f"{len(fs)} shots")
    spd = [(abs(v), d) for a, b, fr, v, d in fs if abs(d - 80) > 3]
    check("fireball: vx $440 if X is 80 px or more away, else $260; toward the side he faces", spd
          and all((v == 0x440) == (d >= 80) and v in (0x440, 0x260) for v, d in spd)
          and all((v > 0) == bool(fr) for a, b, fr, v, d in fs), f"{collections.Counter(v for v, d in spd)}")
    tm = timers(nat, 4, 4, "f34", 90)
    check("Fire volley: then a 90-frame pause", tm and all(o for o, _, _ in tm), f"{len(tm)} pauses")

    # --- Conveyor stomp ------------------------------------------------------------------------
    cok = []
    fast = [t["v_belt"]] + [t[f"table{i}"] for i in range(8)]      # (conveyor_wait changed there)
    for x in alls:
        for s in x.starts(x.fight(6, 4)):
            ph, nx = x.phase(s), x.after(s)
            if ph and nx and x not in fast:
                cok.append(countdown(ph, "f34", 60)[0] and nx["sub"] == 6 and nx["f38"] == ph[-1]["f38"] ^ 1
                           and nx["f34"] == 60 and any(c["f"] == nx["f"] - 1 for c in x.calls("stage_tiles")))
    tm = timers(nat, 6, 6, "f34", 60)
    check("Conveyor stomp: 60 frames, then belt_direction ^= 1, load_stage_tiles, 60 more", cok and all(cok)
          and tm and all(o for o, _, _ in tm), f"{sum(cok)}/{len(cok)}")
    edge = [(x, c) for x in alls for c in x.calls("oil_edge", False)]
    eok = []
    for x, c in edge:
        d = [e["a"] & 0xFFFF for e in x.calls("oil_dist", False) if e["f"] == c["f"]]
        af = x.at.get(c["f"] + 1)
        eok.append(bool(d) and d[-1] < 64 and af and af["step"] == 6 and af["sub"] in (0, 2) and af["f3B"] == 6)
    near = []
    for x in alls:
        ef = {c["f"] for c in x.calls("oil_edge", False)}
        near += [e for e in x.calls("oil_dist", False) if (e["a"] & 0xFFFF) < 64 and e["f"] not in ef]
    check("forced Conveyor stomp: an oil puddle less than 64 px from the edge the belt moves it to "
          "(checked after each pick and during a Fire volley)", eok and all(eok) and not near,
          f"{sum(eok)}/{len(eok)}, {len(near)} missed")
    res = []
    for x in alls:
        for s in x.starts(x.fight(6, 6)):
            nx = x.after(s)
            if nx and s["f35"]:
                res.append(nx["step"] == 4 and nx["f3B"] == 4 and nx["f3C"] == 1)
    check("Conveyor stomp: resumes an unfinished Fire volley", res and all(res), f"{sum(res)}/{len(res)}")

    # --- attack choice -------------------------------------------------------------------------
    seen, rowok, mapok = set(), [], []
    for k in [f"table{i}" for i in range(8)]:
        x = t[k]
        for f, evs in x.pick_frames().items():
            picks = [e for e in evs if e["tag"] == "pick"]
            forced = [e for e in evs if e["tag"] == "force"]
            for pk, fo in zip(picks, forced):
                i = pk["x"] & 0xFF
                seen.add(i)
                rowok.append(i == fo["row"] * 16 + fo["col"])
            if picks:
                af = x.at.get(f + 1)
                if af and af["state"] == 4:
                    mapok.append(af["step"] == tbl[picks[-1]["x"] & 0xFF] or af["step"] == 6)
    check("pick: row = X's distance (< 80, 80-127, ≥ 128 px; tried at 40/79, 80/127, 128/160) + 48 once the "
          "trunk is cut; column = random & 15", rowok and all(rowok), f"{sum(rowok)}/{len(rowok)}")
    check("pick: every one of the 96 entries tried, and the attack is the entry at $86:C843",
          len(seen) == 96 and mapok and all(mapok), f"{len(seen)} entries, {sum(mapok)}/{len(mapok)}")
    nb = collections.Counter()
    for x in nat:
        for c in x.calls("pick"):
            nb[(c["x"] & 0xFF) % 16] += 1
    tot = sum(nb.values())
    chi = sum((nb[i] - tot / 16) ** 2 / (tot / 16) for i in range(16)) if tot else 99
    check("pick (unforced): the column (random & 15) is evenly spread", tot > 60 and chi < 30.6,
          f"{tot} picks, chi2={chi:.1f}/15")
    r = t["repeat"]
    rp = []
    for f, evs in r.pick_frames().items():
        pos = [e for e in evs if e["tag"] == "pickpos"]
        if pos:
            rp.append((pos[0]["last"], pos[0]["rep"], sum(e["tag"] == "pick" for e in evs)))
    good = [k == (2 if (last == 0 and rep >= 3) else 1) for last, rep, k in rp]
    check("repeat limit: a 4th Stomp jump in a row (repeats = 3) is re-picked", good and all(good)
          and any(k == 2 for _, _, k in rp), f"{rp[:8]}")
    rc = t["repeat_cut"]
    reps = [e["rep"] for e in rc.by_tag["pickpos"]]
    single = all(sum(e["tag"] == "pick" for e in evs) <= 1 for evs in rc.pick_frames().values())
    check("repeat limit: none once the trunk is cut (Stomp jump 5+ times in a row)",
          max(reps, default=0) >= 5 and single, f"repeats up to {max(reps, default=0)}")
    fz = t["freeze"]
    per = collections.Counter(c["f"] for c in fz.calls("pick"))
    check("a table of only one attack freezes the game (endless re-pick after 3 repeats)",
          per and max(per.values()) > 50, f"{max(per.values()) if per else 0} picks in one frame")
    h = t["high"]
    hok = []
    pf = {p["f"] for p in h.calls("pick")}
    for e in h.by_tag["high"]:
        af = h.at.get(e["f"] + 1)
        if af:
            hok.append((e["dy"], e["f"] in pf, af["step"]))
    check("X high up (X.y − screen_top < 112) -> always the Stomp jump, without the table",
          hok and all((dy < 112) == (not p) and (p or s == 0) for dy, p, s in hok)
          and {dy for dy, _, _ in hok} == {110, 111, 112, 113}, f"{collections.Counter((dy, p) for dy, p, s in hok)}")

    # --- getting hit ---------------------------------------------------------------------------
    bu = t["buster"]
    hits = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: -1 HP (damage row 8)", hits and all((a["hp"] - c["hp"]) & 0x7F == row8[0] for a, c in hits),
          f"{len(hits)} hits")
    inv = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if c["f39"] == a["f39"] - 1 > 0]     # counting down
    check("hit: invuln_timer ($39) = 60 (59 by the end of the frame; sound $13), damage class 5 while it runs",
          hits and all(c["f39"] == 59 for a, c in hits) and inv and all(c["dmg"] == 5 for a, c in inv)
          and any(c["a"] & 0xFF == 0x13 for c in bu.calls("sound")))
    cu = t["cutter"]
    lh = {e["f"]: e["v"] for e in cu.by_tag["last_hit"]}
    ch = {lh.get(c["f"] - 1) for a, c in zip(cu.p, cu.p[1:]) if c["f36"] < a["f36"]}
    tcut = [(a, c) for a, c in zip(cu.p, cu.p[1:]) if c["f36"] < a["f36"]]
    check("Boomerang Cutter (projectile $0D): each hit takes 1 trunk HP", ch == {0x0D} and len(tcut) == 3, f"{ch}")
    check("trunk_hp 0 -> the trunk falls off (state 10) and despawns",
          any(e["state"] == 10 for e in cu.trunk.values()) and any("gone" in e for e in cu.by_tag["trunk"]))
    cut_f = tcut[-1][1]["f"] if len(tcut) == 3 else 10 ** 9
    after = [cu.at[c["f"] + 1]["step"] for c in cu.calls("choose") if c["f"] > cut_f and c["f"] + 1 in cu.at]
    check("trunk cut: only the Stomp jump and the Fire volley afterwards", after and set(after) <= {0, 4},
          f"{collections.Counter(after)}")
    cuh = [(a, c) for a, c in zip(cu.p, cu.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("Boomerang Cutter: damage from row 8", cuh and all((a["hp"] - c["hp"]) & 0x7F == row8[0x0D] for a, c in cuh),
          f"{len(cuh)} hits, row8[$0D] = {row8[0x0D]}")
    to = t["tornado"]
    toh = [(a, c, (a["hp"] - c["hp"]) & 0x7F) for a, c in zip(to.p, to.p[1:])
           if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    lh = {e["f"]: e["v"] for e in to.by_tag["last_hit"]}
    tid = {lh.get(c["f"] - 1) for a, c, _ in toh}
    check("Storm Tornado (projectile $0B, his weakness): damage from row 8", tid == {0x0B} and toh
          and all(dmg == row8[0x0B] or c["hp"] & 0x7F == 0 for a, c, dmg in toh),
          f"{[d for _, _, d in toh]}, row8[$0B] = {row8[0x0B]}")
    d = t["death"]
    six = d.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, death pose 21 (anim 20), boss_defeated = 1, X_hurt_lock = 1, load_stage_tiles",
          six and six[0]["f37"] == 21 and any(c["a"] & 0xFF == 20 and c["f"] == six[0]["f"] - 1 for c in d.calls("anim"))
          and any(e["v"] == 1 for e in d.by_tag["boss_defeated"]) and any(e["v"] == 1 for e in d.by_tag["X_hurt_lock"])
          and any(c["f"] == six[0]["f"] - 1 for c in d.calls("stage_tiles")))
    check("death: boss_defeated_sequence every frame, then he despawns",
          len(d.calls("defeat_seq")) > 300 and any("gone" in e for e in d.by_tag["fm"]))
    late = [s for f, ss in d.sh.items() if six and f > six[0]["f"] + 2 for s in ss]
    check("death: his oil and fireballs vanish once his HP is 0", six and not late, f"{len(late)} shot-frames after")
    check("x_dead ($30) = 1 once X's HP is 0", any(e["f30"] == 1 for e in t["x_dies"].p))

    # --- editable values -----------------------------------------------------------------------
    v = t["v_hit"]
    check("value max_hp = 20 -> HP fill stops at 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f39"] for e in v.p) in (31, 32))
    v = t["v_trunk"]
    vt = [(a, c) for a, c in zip(v.p, v.p[1:]) if c["f36"] < a["f36"]]
    check("value trunk_hits = 1 -> one Boomerang Cutter hit cuts the trunk", v.p and v.p[-1]["f36"] == 0 and len(vt) == 1)
    v = t["v_jump"]
    sj, sl = v.starts(v.fight(0, 2)), v.starts(v.fight(0, 8))
    check("value stomp_jump = $400", sj and all(s["vy"] == 0x400 for s in sj))
    check("value stun_window = $50 -> stun_window 80 (79 by the end of the frame)", sl and all(s["f3A"] == 79 for s in sl), f"{[s['f3A'] for s in sl][:4]}")
    tm = timers([t["v_oil"]], 2, 4, "f34", 0x20)
    check("value spit_pause = $20", tm and all(o for o, _, _ in tm), f"{tm[:3]}")
    v = t["v_volley"]
    nn = collections.Counter(s["f35"] for s in v.starts(v.fight(4, 2)) if v.at.get(s["f"] - 1, {}).get("f35") == 0)
    check("value volley_shots = 6 -> 5, 6 or 7 shots", nn and set(nn) <= {5, 6, 7}, f"{dict(nn)}")
    tm = timers([v], 4, 4, "f34", 0x20)
    check("value volley_pause = $20", tm and all(o for o, _, _ in tm), f"{tm[:3]}")
    tm = timers([t["v_belt"]], 6, 4, "f34", 0x20)
    check("value conveyor_wait = $20", tm and all(o for o, _, _ in tm), f"{tm[:3]}")

    # --- which routines he uses where ----------------------------------------------------------
    use = collections.defaultdict(set)
    for x in nat:
        for e in x.ev:
            if e["tag"] in FIELDS.values() and e.get("d") == x.slot and e["f"] + 1 in x.at:
                p = x.at[e["f"] + 1]
                use[e["tag"]].add((p["state"], p["step"]))
    check("move_with_gravity only in the Stomp jump", {s for s in use["move_grav"] if s[0] == 4} == {(4, 0)},
          f"{use['move_grav']}")
    check("hit_check / hurt_x_on_contact in every attack",
          {s for s in use["hit_check"] if s[0] == 4} >= {(4, 0), (4, 2), (4, 4), (4, 6)}, f"{use['hit_check']}")

    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:{width}}  {detail}")
    bad = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - bad}/{len(results)} passed")
    print("Run complete: now run the sync-records skill (.claude/skills/sync-records) to update every record.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
