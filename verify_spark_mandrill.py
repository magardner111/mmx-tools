"""
Re-checks everything we claim about Spark Mandrill by running the game in Mesen (see mesen_verify.py).

    python3 verify_spark_mandrill.py          # about 15 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_spark_mandrill.py --cached # re-check the last run's saved output

His boss checkpoint (2, x=7296) is between his two doors; X walks right through the second door and stops at
x=7480. The suite plays that once and saves a state at the first frame of the fight
(work/states/spark_mandrill_fight.mss); most runs start from it. Runs that check the intro or max HP play it
in full. Once he fights, the no-damage AR code is on unless a test needs X hurtable (the punch stun).
Hooks on his instructions (Run.at_exec) set things up exactly: his choice ($88:A362, $88:A36F) gets a chosen
row and 0-31 roll, stepping through every weight boundary of all six rows (rows 4 and 5 follow a stagger and a
freeze); the Dash punch can be turned away from X so it ends at the far wall.
"""
import collections
import json
import sys

import params as P
from defs import SPARK_MANDRILL as SM, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state, countdown

ID, SPARK = 0x31, 0x28
CACHE = "work/spark_mandrill_runs.json"
STATE = "work/states/spark_mandrill_fight.mss"
PAR = {p.key: p for p in SM.params}
TABLE = SM.attack_tables[0].addr
ROWS = 6                            # 4 in the editor's table + after a stagger + after a freeze
FIELDS = {0x88A362: "choose", 0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze",
          0x84AADD: "beaten", 0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound",
          0x828358: "alloc_shot", 0x8282D3: "alloc_effect", 0x84A677: "defeat_seq", 0x849B43: "hit_check",
          0x849B03: "hurt_x", 0x84ACA5: "face_x", 0x8281E8: "move_grav", 0x8491BE: "terrain",
          0x84A338: "shake", 0x84A316: "quake", 0x84A00D: "x_stun", 0x8490A0: "probe"}
M = f"find(0x0E68, 0x1228, {ID})"
WALK_IN = "return {right = r16(0x0BAD) < 7480}"
HOLD = """local xx = r16(0x0BAD)
return {right = xx < 7474, left = xx > 7486, y = fire and frame % 16 < 8}"""
FIRE = "fire = true\n" + HOLD
NO_DAMAGE = f"do local m = {M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
SET_HP1 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); hpset = true end end"
ICE = "w16(0x1F95, 0xDC00); w8(0x0BDB, 16)"          # own Shotgun Ice with ammo, and select it
# charge the buster and let go when he starts dashing (a charged shot mid-dash staggers him)
CHARGE = f"""local m = {M}
local dash = m and r8(m + 2) == 4 and r8(m + 3) == 2
local xx = r16(0x0BAD)
if dash and not was_dash then let_go = 6 end
was_dash = dash
if let_go and let_go > 0 then let_go = let_go - 1; return {{}} end
return {{right = xx < 7474, left = xx > 7486, y = true}}"""
# X jumps against the left wall and slides down it during every other punch quake (standing against it doesn't
# keep the wall bits set) and stands on the floor 40 px from it during the others
# (he switches after each quake, so he is in place before the next one)
WALL = f"""local m = {M}
local q = m and r8(m + 2) == 4 and r8(m + 3) == 6
if was_q and not q then quakes = (quakes or 0) + 1 end
was_q = q
local xx = r16(0x0BAD)
if (quakes or 0) % 2 == 1 then return {{left = true, b = frame % 40 < 20}} end   -- jump at it: slide down
return {{right = xx < 7476, left = xx > 7484}}"""
SPARKS = (f'for a = 0x1428, 0x1600, 0x40 do if r8(a) ~= 0 and r8(a + 10) == {SPARK} then out("sh", "slot=" .. a .. '
          '" sub=" .. r8(a + 11) .. " state=" .. r8(a + 1) .. " x=" .. r16(a + 5) .. " y=" .. r16(a + 8) .. " vx=" .. '
          's16(a + 0x1A) .. " vy=" .. s16(a + 0x1C) .. " t=" .. r8(a + 0x37)) end end')
# Dash punch: turn him away from X right after face_x, so he dashes to the far wall
AWAY = [(0x88A06C, 'w8(s["cpu.d"] + 0x11, r8(s["cpu.d"] + 0x11) ~ 0x40)')]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def weights(g):
    b = snes2pc(TABLE)
    return [list(g.rom[b + r * 4:b + r * 4 + 4]) for r in range(ROWS)]


def pick_value(w, row, v):
    """The attack (0-3) a roll v (0-31) gives in this row: from Jump at X down, v -= weight; the first one
    below 0; Electric Spark if none."""
    for y in (3, 2, 1):
        v -= w[row][y]
        if v < 0:
            return y
    return 0


def boundary_cases(w):
    out = []
    for r in range(ROWS):
        c = [w[r][3], w[r][3] + w[r][2], w[r][3] + w[r][2] + w[r][1]]
        out += [(r, v) for v in sorted({0, 31, *[b - 1 for b in c], *c}) if 0 <= v <= 31]
    return out


def force_weights(cases, start):
    lua = "{" + ", ".join(f"{{{r}, {v}}}" for r, v in cases) + "}"
    return [(0x88A362, f'sm_c = sm_c or {lua}; sm_n = (sm_n or {start - 1}) + 1; local c = sm_c[sm_n % #sm_c + 1]; '
                       'sm_v = c[2]; w8(s["cpu.d"] + 2, c[1] * 2); out("force", "row=" .. c[1] .. " v=" .. c[2])'),
            (0x88A36F, 'setreg("cpu.a", (s["cpu.a"] & 0xFF00) | sm_v)')]


def only(attack, **values):
    """ROM patch: every row picks `attack` (weights out of 32; attack 0 gets the remainder), plus values."""
    def f(g):
        b = snes2pc(TABLE)
        for r in range(ROWS):
            for j in range(4):
                g.rom[b + r * 4 + j] = 32 if j == attack else 0
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def values(**v):
    return lambda g: [P.put(g, PAR[k], x) for k, x in v.items()]


def run(frames, inp=HOLD, seed=None, inf=True, ar=True, patch=None, extra=(), hooks=(), full=False, watch_all=True):
    r = Run(level=6, x=7296, frames=frames, seed=seed, infinite_hp=inf, patch=patch, savestate=None if full else STATE)
    r.track(ID, tag="sm")
    for a, t in (FIELDS.items() if watch_all else [(0x88A362, "choose")]):
        r.on_exec(a, t)
    for a, lua in hooks:
        r.at_exec(a, lua)
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.on_write(0x1F0E, "hud_boss")
    r.input(inp)
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame('if r16(0x0BAD) ~= lastx or r16(0x0BB0) ~= lasty or r8(0x0BAA) ~= laststep or r8(0x0C06) ~= lastt '
                 'or r8(0x0C32) ~= lastu then out("X", "x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0) .. " step=" .. '
                 'r8(0x0BAA) .. " touch=" .. r8(0x0C06) .. " untouchable=" .. r8(0x0C32) .. " stun=" .. r8(0x0C2D)); '
                 'lastx = r16(0x0BAD); lasty = r16(0x0BB0); laststep = r8(0x0BAA); lastt = r8(0x0C06); '
                 'lastu = r8(0x0C32) end')
    r.each_frame('out("cam", "l=" .. r16(0x1E4D) .. " t=" .. r16(0x1E50) .. " fc=" .. r8(0x00CB) .. " cm=" .. r8(0x00CA))'
                 if watch_all else "")
    r.each_frame(SPARKS)
    for lua in extra:
        r.each_frame(lua)
    return r


class T:
    """Helpers over one run's events (exec/hook events have f = frame - 1, per-frame records f = frame)."""
    def __init__(self, ev):
        self.ev = ev
        self.by_tag = collections.defaultdict(list)
        for e in ev:
            self.by_tag[e["tag"]].append(e)
        self._calls = {}
        self.p = [e for e in self.by_tag["sm"] if "slot" in e]
        self.slot = self.p[0]["slot"] if self.p else None
        self.at = {e["f"]: e for e in self.p}
        self.cam = {e["f"]: e for e in self.by_tag["cam"]}
        self.sh = collections.defaultdict(list)
        for e in self.by_tag["sh"]:
            self.sh[e["slot"]].append(e)
        xs = self.by_tag["X"]
        self.x, i, cur = {}, 0, None
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

    def fight(self, step, sub):
        return lambda e: e["state"] == 4 and e["step"] == step and e["sub"] == sub

    def phase(self, s):
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
        ph = self.phase(s)
        return self.at.get(ph[-1]["f"] + 1) if ph else None

    def spark_lives(self):
        """Per slot, split into lives (a gap in frames starts a new one)."""
        lives = []
        for recs in self.sh.values():
            cur = [recs[0]]
            for a, b in zip(recs, recs[1:]):
                if b["f"] != a["f"] + 1:
                    lives.append(cur)
                    cur = []
                cur.append(b)
            lives.append(cur)
        return lives


def timers(xs, step, sub, field, start):
    res = []
    for x in xs:
        for s in x.starts(x.fight(step, sub)):
            ph = x.phase(s)
            if ph:
                res.append(countdown(ph, field, start))
    return res


def main():
    g0 = MMX1("work/hack.sfc")
    w0 = weights(g0)
    cases = boundary_cases(w0)
    natural = [("n0", 0x1111), ("n1", 0x2345), ("n2", 0x3C3C), ("n3", 0x4A21)]
    runs = {k: run(5000, seed=s) for k, s in natural}
    runs.update({
        "intro": run(1500, WALK_IN, seed=0x1234, full=True).on_exec(0x889D4E, "first_roll"),
        **{f"table{i}": run(6000, seed=0x1001 + i, watch_all=False, hooks=force_weights(cases, i * len(cases) // 4))
           for i in range(4)},
        "spark": run(3000, seed=0x2001, patch=only(0)),
        "ceiling": run(3000, seed=0x2002, patch=only(1)),
        "dash": run(3000, seed=0x2003, patch=only(2)),
        "jump": run(3000, seed=0x2004, patch=only(3)),
        "wall": run(4000, WALL, seed=0x2005, ar=False, patch=only(2), hooks=AWAY),
        "stagger": run(4000, CHARGE, seed=0x2006, patch=only(2)),
        "ice": run(3000, FIRE, seed=0x2007, extra=[ICE]),
        "buster": run(3000, FIRE, seed=0x2008),
        "death": run(1500, FIRE, seed=0x2009, extra=[SET_HP1]),
        "x_dies": run(3000, f"return {{right = true}}", seed=0x200A, inf=False, ar=False),
        "v_hit": run(2600, FIRE, seed=0x3001, full=True, patch=values(max_hp=20, invuln_time=0x20)),
        "v_speed": run(3000, seed=0x3002, patch=lambda g: (only(2)(g), values(dash_speed=0x300)(g))),
        "v_jumps": run(3000, seed=0x3003, patch=values(jump_speed=0x600, leap_speed=0x600)),
    })
    if "--cached" in sys.argv:
        out = json.load(open(CACHE))
    else:
        print("playing to the start of the fight...", flush=True)
        fight_state(STATE, 6, 7296, WALK_IN, f"(function() local m = {M}; return m and r8(m + 1) == 4 end)()")
        print(f"running {len(runs)} emulator sessions...", flush=True)
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    t = {k: T(v) for k, v in out.items()}
    nat = [t[k] for k, _ in natural]
    alls = [x for k, x in t.items() if not k.startswith("v_")]
    g = MMX1("work/hack.sfc")
    dt = snes2pc(DAMAGE_TABLE)
    row10 = g.rom[dt + g.w(dt + 20):][:32]

    # --- intro -------------------------------------------------------------------------------
    n = t["intro"]
    init = n.starts(lambda e: e["state"] == 0 and e["step"] == 1)[0]
    check("init: boss_already_beaten, x_freeze_for_boss, jingle $2E", n.calls("beaten") and n.calls("x_freeze", False)
          and any(c["a"] & 0xFF == 0x2E for c in n.calls("music", False)))
    ok, a, b = countdown(n.phase(init), "f34", 59)
    ok2, a2, b2 = countdown(n.phase(init), "f34", 60)
    check("init: 60-frame wait (timer $34)", ok or ok2, f"{a}..{b}")
    fades = [n.cam[f]["fc"] for f in range(init["f"], init["f"] + 60) if f in n.cam]
    check("init: the screen fades to white meanwhile (fixed colour +1 a frame up to 31, colour math $AF)",
          fades and max(fades) & 0x1F == 31 and any(n.cam[f]["cm"] == 0xAF for f in range(init["f"], init["f"] + 60)
                                                     if f in n.cam), f"{fades[:5]}..{fades[-3:]}")
    st2 = n.starts(lambda e: e["state"] == 2)[0]
    check("obj_start: damage class 3; palette_bits ($33) = attr & $0E", st2["dmg"] == 3 and st2["f33"] == st2["attr"] & 0x0E)
    land = n.starts(lambda e: e["state"] == 2 and e["step"] == 6)[0]
    check("intro: falls (gravity 64) and lands with sound $4D and screen_shake(30)",
          any(c["a"] & 0xFF == 0x4D and c["f"] == land["f"] - 1 for c in n.calls("sound"))
          and any(c["a"] & 0xFF == 30 and c["f"] == land["f"] - 1 for c in n.calls("shake", False)))
    ticks = [c["f"] for c in n.calls("sound_c") if n.at.get(c["f"] + 1, {}).get("state") == 2]
    check("HP fill: +1 every 2 frames to 32 (boss bar from the pose before)", len(ticks) == 32
          and set(b - a for a, b in zip(ticks, ticks[1:])) == {2} and n.by_tag["hud_boss"], f"{len(ticks)} ticks")
    s12 = n.starts(lambda e: e["state"] == 2 and e["step"] == 12)[0]
    ok, a, b = countdown(n.phase(s12), "f34", 30)
    nx = n.after(s12)
    check("end of intro: 30 frames, x_unfreeze, music $1E, state 4 with a random first attack (random & 3)",
          ok and nx and nx["state"] == 4 and n.calls("x_unfreeze", False)
          and any(c["a"] & 0xFF == 0x1E for c in n.calls("music", False)), f"{a}..{b}")
    r0 = n.by_tag["first_roll"]
    check("first attack = (random & 3) × 2", r0 and nx and nx["step"] == (r0[0]["a"] & 3) * 2,
          f"roll {r0[0]['a'] & 0xFF if r0 else None}, step {nx and nx['step']}")
    check("fight damage class 10 (5 while invulnerable)",
          all(e["dmg"] in (10, 5) for x in nat for e in x.p if e["state"] == 4 and e["f"] > 60)
          and any(e["dmg"] == 10 for e in nat[0].p))

    # --- Electric Spark ------------------------------------------------------------------------
    sp = t["spark"]
    fire_f = [c["f"] for c in sp.calls("sound") if c["a"] & 0xFF == 68]
    lives = [l for l in sp.spark_lives() if l[0]["state"] in (0, 2)]
    pairs = collections.Counter(l[0]["f"] for l in lives)
    check("Electric Spark: two sparks (enemy shot $28, sub-ids 0 and $28) per attack, sound $44, screen_shake(10)",
          fire_f and pairs and set(pairs.values()) == {2} and {l[0]["sub"] for l in lives} == {0, 0x28}
          and any(c["a"] & 0xFF == 10 for c in sp.calls("shake", False)), f"{len(fire_f)} attacks, {len(lives)} sparks")
    sx = []
    for l in lives:
        m = sp.at.get(l[0]["f"])
        if m:
            sx.append((l[0]["x"] - m["x"], l[0]["y"] - m["y"], m["attr"] & 0x40))
    check("Electric Spark: sparks start at his x ± 26 (facing), y + 24", sx and all(abs(dx) == 26 and (dx > 0) == bool(fr)
          and dy == 24 for dx, dy, fr in sx), f"{sx[:3]}")
    spd = [(l[0]["sub"], next((s["vx"] for s in l if s["state"] == 2), 0)) for l in lives]   # (state 0: old values)
    check("spark: sub-id 0 runs left, $28 right, at 4 px a frame", spd and all(v == (0x400 if s else -0x400) for s, v in spd))
    turns = sum(1 for l in lives for a, b in zip(l, l[1:]) if a["state"] == 2 and b["state"] == 4)
    vert = [abs(s["vy"]) for l in lives for s in l if s["state"] == 4]
    check("spark: at a wall it turns to climb it (4 px a frame), and back to running at the ceiling or floor",
          turns > 0 and vert and set(vert) == {0x400}, f"{turns} turns")
    ln = [len(l) for l in lives if l[-1]["f"] < max(x["f"] for x in sp.p)]
    check("spark: lives 120 frames", ln and all(118 <= k <= 121 for k in ln), f"{collections.Counter(ln)}")
    tm = timers([sp], 0, 6, "f34", 32)
    check("Electric Spark: then a 32-frame pause", tm and all(o for o, _, _ in tm), f"{len(tm)} pauses")

    # --- Ceiling drop -------------------------------------------------------------------------
    c = t["ceiling"]
    up = c.starts(c.fight(2, 2))
    check("Ceiling drop: jumps with vy $6C3, gravity 64", up and all(s["vy"] == 0x6C3 and s["grav"] == 64 for s in up))
    hang = c.starts(c.fight(2, 4))
    check("Ceiling drop: catches the ceiling as he starts to fall (screen_shake(10))", hang and all(
        any(k["a"] & 0xFF == 10 and k["f"] == s["f"] - 1 for k in c.calls("shake", False)) for s in hang))
    steps = []
    for s in c.starts(c.fight(2, 6)):
        ph = c.phase(s)
        xs = [p["x"] for p in ph]
        steps += [b - a for a, b in zip(xs, xs[1:]) if b != a]
    check("Ceiling drop: hand-walks toward X 28 px a swing", steps and set(abs(k) for k in steps) == {28},
          f"{collections.Counter(steps)}")
    drops = []
    for s in c.starts(c.fight(2, 8)):
        prev = c.at.get(s["f"] - 1)
        xx = c.x.get(s["f"] - 1)
        if prev and xx:                     # (tested right after the swing moved him: his x this frame)
            fr = prev["attr"] & 0x40
            passed = (xx["x"] < s["x"]) if fr else (xx["x"] >= s["x"])
            drops.append(bool(passed or s["touch"] & 3))
    check("Ceiling drop: lets go once he has passed X (or meets a wall)", drops and all(drops), f"{len(drops)} drops")
    lands = c.starts(c.fight(2, 10))
    check("Ceiling drop: heavy landing (sound $4D, screen_shake(30)), then a 32-frame pause",
          lands and all(any(k["a"] & 0xFF == 0x4D and k["f"] == s["f"] - 1 for k in c.calls("sound")) for s in lands)
          and all(o for o, _, _ in timers([c], 2, 12, "f34", 32)))

    # --- Dash punch ---------------------------------------------------------------------------
    d = t["dash"]
    ds = d.starts(d.fight(4, 2))
    check("Dash punch: charges at $400 (facing X) when 34, 50 and 56 px ahead are clear",
          ds and all(abs(s["vx"]) == 0x400 for s in ds), f"{len(ds)} dashes")
    hitw = d.starts(d.fight(4, 6))
    check("Dash punch: stops at the wall, screen_quake, 30 frames, then a 32-frame pause",
          hitw and all(o for o, _, _ in timers([d], 4, 6, "f34", 30)) and all(o for o, _, _ in timers([d], 4, 8, "f34", 32))
          and d.calls("quake", False))
    spot = [s for x in alls for s in x.starts(x.fight(4, 4))]
    check("Dash punch: punches on the spot when a wall is that close", spot, f"{len(spot)} times")
    w = t["wall"]
    st = w.calls("x_stun", False)
    on_wall, mid = [], []
    for s in w.starts(w.fight(4, 6)):
        ph = w.phase(s)
        stuns = [k for k in st if ph and ph[0]["f"] - 1 <= k["f"] <= ph[-1]["f"]]
        xs = [w.x.get(p["f"]) for p in ph]
        touching = any(x_ and x_["touch"] & 3 and not x_["untouchable"] for x_ in xs)
        (on_wall if touching else mid).append((len(stuns), stuns[0]["a"] & 0xFF if stuns else None))
    check("punch quake: stuns X on a wall (wall bits set, e.g. sliding down it) with x_stun(32), once per quake", on_wall and all(n_ == 1 and a == 32
          for n_, a in on_wall), f"{on_wall[:5]}")
    check("punch quake: doesn't stun X standing away from the walls", mid and all(n_ == 0 for n_, a in mid), f"{mid[:5]}")
    stg = t["stagger"]
    sg = stg.starts(stg.fight(8, 1))
    lh = {e["f"]: e["v"] for e in stg.by_tag["last_hit"]}
    check("charged buster shot mid-dash -> stagger: vx $400 away from where he faces, friction 32, 32 frames",
          sg and all(abs(s["vx"]) <= 0x400 for s in sg) and all(o for o, _, _ in timers([stg], 8, 1, "f34", 31)),
          f"{len(sg)} staggers, shots {sorted({v for v in lh.values() if v})}")

    # --- Jump at X ----------------------------------------------------------------------------
    j = t["jump"]
    good = []
    for s in j.starts(j.fight(6, 2)):
        b = j.at.get(s["f"] - 1)
        xx = j.x.get(s["f"] - 1)
        if b and xx:
            good.append((s["vx"], ((xx["x"] - b["x"]) * 4 + 0x8000) % 0x10000 - 0x8000, s["vy"]))
    check("Jump at X: vx = (X.x − his x) × 4, vy $70D, gravity 64", good and all(abs(a - b) <= 8 and v == 0x70D
          for a, b, v in good), f"{good[:3]}")
    check("Jump at X: lands with sound $4D and screen_shake(30), then a 32-frame pause",
          all(o for o, _, _ in timers([j], 6, 8, "f34", 32)) and j.starts(j.fight(6, 6)))

    # --- Shotgun Ice --------------------------------------------------------------------------
    ic = t["ice"]
    fz = ic.starts(lambda e: e["state"] == 4 and e["step"] == 10)
    lhi = {e["f"]: e["v"] for e in ic.by_tag["last_hit"]}
    check("Shotgun Ice (projectile $0E) -> frozen (step 10): next frame frozen = 1, timer 60",
          fz and all(ic.at.get(s["f"] + 1, {}).get("f36") == 1 and ic.at.get(s["f"] + 1, {}).get("f34") in (59, 60)
                     for s in fz), f"{len(fz)} freezes, shots {sorted({v for v in lhi.values() if v})}")
    brk = ic.starts(ic.fight(10, 8))
    shards = [len([k for k in ic.calls("alloc_effect") if k["f"] == s["f"] - 1]) for s in brk]
    check("frozen: breaks out in 16 ice shards (effect $06), sound $4C, 30 more frames", shards and all(k == 16 for k in shards)
          and all(o for o, _, _ in timers([ic], 10, 8, "f34", 30)), f"{shards}")
    again = [s for s in ic.starts(ic.fight(10, 4))]
    check("frozen: more Shotgun Ice hits while frozen don't restart it", again, f"{len(again)}")

    # --- attack choice ------------------------------------------------------------------------
    done, ok = set(), []
    for i in range(4):
        x = t[f"table{i}"]
        for fo in x.by_tag["force"]:
            af = x.at.get(fo["f"] + 1)
            if af and af["state"] == 4:
                ok.append(af["step"] == 2 * pick_value(w0, fo["row"], fo["v"]))
                done.add((fo["row"], fo["v"]))
    check("attack choice (forced): weights at $86:CFDB, row = what he just did (rows 4 and 5: after a stagger, after "
          "a freeze), Jump/Dash/Ceiling tested in that order, Electric Spark gets the rest; every boundary tried",
          ok and all(ok) and done == set(cases), f"{sum(ok)}/{len(ok)}, {len(done)}/{len(cases)} cases")

    # --- getting hit ---------------------------------------------------------------------------
    bu = t["buster"]
    hits = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: -1 HP (damage row 10); no flinch", hits and all((a["hp"] - c["hp"]) & 0x7F == row10[0]
          and c["step"] == a["step"] for a, c in hits), f"{len(hits)} hits")
    inv = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if c["f35"] == a["f35"] - 1 > 0]
    check("hit: invuln_timer ($35) = 60, sound $13, damage class 5 while it runs", hits and all(c["f35"] == 59 for a, c in hits)
          and inv and all(c["dmg"] == 5 for a, c in inv))
    ich = [(a, c) for a, c in zip(ic.p, ic.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    lid = {lhi.get(c["f"] - 1) for a, c in ich}
    check("Shotgun Ice (weakness): damage from row 10", ich and all((a["hp"] - c["hp"]) & 0x7F == row10[lhi.get(c["f"] - 1, 0)]
          or c["hp"] & 0x7F == 0 for a, c in ich), f"{collections.Counter((a['hp'] - c['hp']) & 0x7F for a, c in ich)}, ids {lid}")
    de = t["death"]
    six = de.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, death anim 17, sound $13, boss_defeated, then despawn",
          six and any(c["a"] & 0xFF == 17 and c["f"] == six[0]["f"] - 1 for c in de.calls("anim"))
          and len(de.calls("defeat_seq")) > 300 and any("gone" in e for e in de.by_tag["sm"]))
    xd = t["x_dies"]
    died = [e for e in xd.by_tag["X"] if e["step"] == 0x0C]
    check("field $30 (x_dead in other bosses): cleared when the fight starts, never set, even when X dies",
          died and all(e["f30"] == 0 for e in xd.p), f"X dying from frame {died[0]['f'] if died else None}")

    # --- values -------------------------------------------------------------------------------
    v = t["v_hit"]
    check("value max_hp = 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f35"] for e in v.p) in (31, 32))
    v = t["v_speed"]
    check("value dash_speed = $300", any(abs(e["vx"]) == 0x300 for e in v.p if e["step"] == 4 and e["sub"] == 2))
    v = t["v_jumps"]
    check("values jump_speed / leap_speed = $600", any(s["vy"] == 0x600 for s in v.starts(v.fight(2, 2)))
          or any(s["vy"] == 0x600 for s in v.starts(v.fight(6, 2))))

    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:{width}}  {detail}")
    bad = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - bad}/{len(results)} passed")
    print("Run complete: now run the sync-records skill (.claude/skills/sync-records) to update every record.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
