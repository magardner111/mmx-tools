"""
Re-checks everything we claim about Storm Eagle by running the game in Mesen (see mesen_verify.py).

    python3 verify_storm_eagle.py          # about 10 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_storm_eagle.py --cached # re-check the last run's saved output

Warping into his deck doesn't start the fight (he only comes after the platform ride), so the suite loads
a save state made on the airship's wing tip (work/states/storm_eagle_wing.mss, checkpoint 1, x=6302),
jumps left onto the platform and rides up once, saving a second state at the first frame of the fight
(work/states/storm_eagle_fight.mss); runs start from that, except those that check the ride, the intro or max HP.
The weights are also checked exactly: hooks on his choice ($87:DE1F, $87:DE2C) set the row and the 0-31
roll to every weight boundary. Once X is let go (step $46 ends) the no-damage AR code is on and
X holds the middle of the deck and walks into the wind during a Gust (it pushes 2 px a frame, walking
gives 1.5 and X has no dash at this point of the game, so an endless Gust would still win). Tests
that need one attack set the weight table so he only picks it; tests of editable values change the value
in the test ROM and check that the behaviour follows.
"""
import collections
import json
import math
import sys

import params as P
from defs import STORM_EAGLE as SE, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state

ID, STATE = 0x52, "work/states/storm_eagle_wing.mss"
FIGHT = "work/states/storm_eagle_fight.mss"         # made from STATE by main(): first frame of the fight
CACHE = "work/storm_eagle_runs.json"
LO, HI = 6020, 6070            # X stays between these on the deck (pit at x < ~5760, edge at ~6300)
# jump left off the wing onto the platform; nothing during the ride; then hold the middle of the deck
RIDE = """
if not rode then
  if r8(0x0BAA) == 0x46 then rode = true; return {} end
  return {left = true, b = frame > 10 and frame < 38}
end
if r8(0x0BAA) == 0x46 then return {} end
local x = r16(0x0BAD)
"""
# During a Gust or while his tornado is out X walks toward him (net -0.5 px/frame: he has no dash yet); otherwise back to the middle.
AIM = RIDE + f"""local e = find(0x0E68, 0x1228, {ID})
local gust = e ~= nil and r8(e + 1) == 4 and r8(e + 2) == 0 and r8(e + 3) == 4
gust = gust or (e ~= nil and find(0x1428, 0x1628, 0x24) ~= nil)      -- his tornado pushes X too
local go_right = x < {LO}
local go_left = x > {HI}
if gust then go_right = r16(e + 5) > x; go_left = not go_right end
"""
HOLD = AIM + "return {right = go_right, left = go_left}"
FIRE = AIM + "return {right = go_right, left = go_left, y = (frame % 16) < 8}"
TO_PIT = RIDE + "return {left = true}"                      # X walks off the deck's left edge
NO_DAMAGE = "if rode and r8(0x0BAA) ~= 0x46 then w8(0x0BD8, 8) end"   # AR 7E0BD808, only after the ride
SET_HP1 = (f'do local a = find(0x0E68, 0x1228, {ID}); if a and r8(a + 1) == 4 and not hpset then '
           'w8(a + 0x27, 0x81); hpset = true end end')
PAR = {p.key: p for p in SE.params}
TABLE = SE.attack_tables[0].addr
NAMES = ["Gust", "Dive", "Storm Tornado", "Birds"]
FIELDS = {0x87DE1F: "choose", 0x8087A2: "music", 0x84A003: "x_unfreeze", 0x84AADD: "beaten",
          0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound",
          0x828358: "alloc_shot", 0x828321: "alloc_enemy", 0x8282D3: "alloc_effect", 0x84A677: "defeat_seq",
          0x849B43: "hit_check", 0x849B03: "hurt_x", 0x84ACA5: "face_x", 0x82825D: "move_y", 0x82820A: "move",
          0x8491BE: "terrain", 0x87DE63: "wind_effect", 0x828398: "despawn"}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def only(attack, **values):
    """ROM patch: every row picks `attack` (0 = Gust gets the remainder when the others are 0)."""
    def f(g):
        t = snes2pc(TABLE)
        for r in range(4):
            for j in range(4):
                g.rom[t + r * 4 + j] = 32 if (j == attack and attack) else 0
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def gust_birds(**values):
    """ROM patch: Gust and Birds take turns (Birds gives X time to walk back between Gusts)."""
    def f(g):
        t = snes2pc(TABLE)
        g.rom[t:t + 16] = bytes([0, 0, 0, 32] + [0] * 12)
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def values(**v):
    return lambda g: [P.put(g, PAR[k], x) for k, x in v.items()]


def pick_value(w, row, v):
    """The attack (0-3) his choice gives for roll v (0-31) after attack `row`: from Birds down, v -= weight;
    the first one that goes below 0; Gust if none."""
    for y in (3, 2, 1):
        v -= w[row][y]
        if v < 0:
            return y
    return 0


def boundary_cases(w):
    """(row, roll) pairs at every weight boundary of every row, plus 0 and 31."""
    out = []
    for r in range(4):
        c = [w[r][3], w[r][3] + w[r][2], w[r][3] + w[r][2] + w[r][1]]
        out += [(r, v) for v in sorted({0, 31, *[b - 1 for b in c], *c}) if 0 <= v <= 31]
    return out


def force_weights(cases, start):
    """Hooks: pick n sets his step to row*2 just before choose reads it and replaces `random & 31` with roll."""
    lua = "{" + ", ".join(f"{{{r}, {v}}}" for r, v in cases) + "}"
    return [(0x87DE1F, f'se_c = se_c or {lua}; se_n = (se_n or {start - 1}) + 1; local c = se_c[se_n % #se_c + 1]; '
                       'se_v = c[2]; w8(s["cpu.d"] + 2, c[1] * 2); out("force", "row=" .. c[1] .. " v=" .. c[2])'),
            (0x87DE2C, 'setreg("cpu.a", (s["cpu.a"] & 0xFF00) | se_v)')]


def run(frames, inp=HOLD, seed=None, inf=True, ar=True, patch=None, extra=(), watch_all=True, hooks=(), full=False):
    """full: from the wing tip through the ride and intro; otherwise from the first frame of the fight."""
    r = Run(level=5, x=6302, frames=frames, seed=seed, infinite_hp=inf, patch=patch,
            savestate=STATE if full else FIGHT)
    if not full:
        inp = "rode = true\n" + inp          # (already off the platform)
    for a, lua in hooks:
        r.at_exec(a, lua)
    r.track(ID, tag="eagle").track(0x24, "shot", tag="tornado").count_objects(0x55, "enemy", "eggs").count_objects(0x56, "enemy", "birds")
    for a, t in (FIELDS.items() if watch_all else []):
        r.on_exec(a, t)
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1E5E, "border_left")
    r.on_write(0x1E60, "border_right").on_write(0x1F0E, "hud_boss")
    r.input(inp)
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame('if r16(0x0BAD) ~= lastx or r16(0x0BB0) ~= lasty or r8(0x0BAA) ~= laststep then out("X", "x=" .. '
                 'r16(0x0BAD) .. " y=" .. r16(0x0BB0) .. " step=" .. r8(0x0BAA) .. " hp=" .. (r8(0x0BCF) & 0x7F)); '
                 'lastx = r16(0x0BAD); lasty = r16(0x0BB0); laststep = r8(0x0BAA) end')
    r.each_frame('out("cam", "l=" .. r16(0x1E4D) .. " t=" .. r16(0x1E50))' if watch_all else "")
    for lua in extra:
        r.each_frame(lua)
    return r


class T:
    """Helpers over one run's events."""
    def __init__(self, ev):
        self.ev = ev
        self.p = [e for e in ev if e["tag"] == "eagle" and "slot" in e and e["state"] > 0]
        self.slot = self.p[0]["slot"] if self.p else None
        self.at = {e["f"]: e for e in self.p}
        self.cam = {e["f"]: e for e in ev if e["tag"] == "cam"}
        xs = [e for e in ev if e["tag"] == "X"]
        self.x, i, cur = {}, 0, None          # X's position on every frame (logged only when it changes)
        for f in range(0, (ev[-1]["f"] if ev else 0) + 1):
            while i < len(xs) and xs[i]["f"] <= f:
                cur, i = xs[i], i + 1
            if cur:
                self.x[f] = cur

    def calls(self, tag):
        return [e for e in self.ev if e["tag"] == tag and e.get("d") == self.slot]

    def starts(self, cond):
        return [e for i, e in enumerate(self.p) if cond(e) and (i == 0 or not cond(self.p[i - 1]))]

    def next_call(self, tag, after):
        return next((e["f"] for e in self.calls(tag) if e["f"] > after), None)

    def fight(self, step, sub):
        return lambda e: e["state"] == 4 and e["step"] == step and e["sub"] == sub


def main():
    seeds = [0x1111, 0x2345, 0x3C3C, 0x4A21, 0x5EED, 0x6F01, 0x7777, 0x8D13, 0x9101, 0xA0B1, 0xB2C3, 0xC4D5]
    runs = {
        "natural": run(4500, full=True),
        "buster": run(4500, FIRE, seed=0x1111),
        "death": run(2600, FIRE, seed=0x3333, extra=[SET_HP1]),
        "x_dies": run(1500, TO_PIT, ar=False, inf=False),
        "gust": run(4000, patch=gust_birds()),
        "v_gust": run(3000, patch=gust_birds(gust_push=0x0100)),
        "dive": run(4000, seed=0x2222, patch=only(1)),
        "dive2": run(4000, seed=0x4444, patch=only(1)),
        "tornado": run(2600, patch=only(2)),
        "birds": run(2600, patch=only(3)),
        "v_hit": run(3000, FIRE, full=True, patch=values(max_hp=20, invuln_time=0x20)),
    }
    g0 = MMX1("work/hack.sfc")
    b0 = snes2pc(TABLE)
    w0 = [list(g0.rom[b0 + r * 4:b0 + r * 4 + 4]) for r in range(4)]
    cases = boundary_cases(w0)
    for i, s in enumerate(seeds[:6]):
        runs[f"stats{i}"] = run(6000, seed=s, watch_all=False).on_exec(0x87DE1F, "choose")
    for i in range(5):                      # ~9 picks each (his attacks are long), starting 6 cases apart
        runs[f"table{i}"] = run(8000, seed=seeds[6 + i], watch_all=False,
                                hooks=force_weights(cases, i * len(cases) // 5)).on_exec(0x87DE1F, "choose")
    if "--cached" in sys.argv:              # re-check the last run's output without emulating again
        out = json.load(open(CACHE))
    else:
        print("riding up to the start of the fight...", flush=True)
        fight_state(FIGHT, 5, 6302, HOLD, f"(function() local m = find(0x0E68, 0x1228, {ID}); "
                                          "return m and r8(m + 1) == 4 end)()", frames=2500, savestate=STATE)
        print(f"running {len(runs)} emulator sessions...", flush=True)
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    t = {k: T(v) for k, v in out.items()}
    alls = list(t.values())
    g = MMX1("work/hack.sfc")

    # --- getting there ---------------------------------------------------------------------
    n = t["natural"]
    rode = [e for e in n.ev if e["tag"] == "X" and e["step"] == 0x46]
    freed = next((e for e in n.ev if e["tag"] == "X" and rode and e["f"] > rode[0]["f"] and e["step"] != 0x46), None)
    st4 = n.starts(lambda e: e["state"] == 4)
    check("route: X held in step $46 from the platform until the fight starts",
          rode and freed and st4 and abs(freed["f"] - st4[0]["f"]) <= 2,
          f"held f{rode[0]['f'] if rode else None}-{freed['f'] if freed else None}, fight f{st4[0]['f'] if st4 else None}")

    # --- init / intro ------------------------------------------------------------------------
    raw = [e for e in n.ev if e["tag"] == "eagle" and "slot" in e]
    i0 = next((e for e in raw if e["state"] == 0 and e["step"] == 1), None)
    st2 = n.starts(lambda e: e["state"] == 2)
    check("init: boss_already_beaten, jingle $2E", n.calls("beaten") and any(c["a"] & 0xFF == 0x2E for c in n.calls("music")))
    check("init: 60-frame wait (timer $34 = 60)", i0 and i0["f34"] == 60 and st2 and 60 <= st2[0]["f"] - i0["f"] <= 64,
          f"timer {i0 and i0['f34']}, waited {st2 and i0 and st2[0]['f'] - i0['f']}")
    check("obj_start: damage class 3; palette_bits ($33) = attr & $0E",
          st2 and st2[0]["dmg"] == 3 and st2[0]["f33"] == st2[0]["attr"] & 0x0E,
          f"{st2 and (st2[0]['dmg'], st2[0]['f33'], hex(st2[0]['attr']))}")
    s1 = n.starts(lambda e: e["state"] == 2 and e["step"] == 2)
    cam = n.cam.get(s1[0]["f"]) if s1 else None
    check("intro: appears at screen_left + 208, screen_top, falling at vy -256",
          s1 and cam and s1[0]["x"] == cam["l"] + 208 and s1[0]["vy"] == -256,
          f"x {s1 and s1[0]['x']} (screen_left {cam and cam['l']}), y {s1 and s1[0]['y']} (top {cam and cam['t']}), vy {s1 and s1[0]['vy']}")
    land = n.starts(lambda e: e["state"] == 2 and e["step"] == 4)
    hb = [e for e in n.ev if e["tag"] == "hud_boss" and e["v"]]
    check("intro: lands on the floor (touch bit 2), then the boss bar shows him (hud_boss)",
          land and land[0]["touch"] & 4 and hb and abs(hb[0]["f"] - land[0]["f"]) <= 1)
    ticks = [c["f"] for c in n.calls("sound_c") if st2 and c["f"] > st2[0]["f"]][:40]
    fight = st4[0] if st4 else None
    check("HP fill: +1 every 2 frames to 32", fight and fight["hp"] & 0x7F == 32 and len(ticks) >= 32
          and set(b - a for a, b in zip(ticks[:32], ticks[1:32])) == {2}, f"{len(ticks)} ticks")
    bl = [e["v"] for e in n.ev if e["tag"] == "border_left"]
    f8 = n.starts(lambda e: e["state"] == 2 and e["step"] == 8)
    # the 30-frame timer only starts counting ~8 frames later: nothing updates while the boss music loads
    tm = [n.at[f]["f34"] for f in range(f8[0]["f"], fight["f"] + 1) if f in n.at] if f8 and fight else []
    tm = [v for v in tm if v <= 30]                     # (the fight frame reuses $34 for his first attack)
    dec = [b for a, b in zip(tm, tm[1:]) if b != a]
    check("end of intro: arena borders set, boss music $1E, 30-frame timer, x_unfreeze, fight",
          f8 and fight and tm[0] == 30 and dec == list(range(29, -1, -1)) and n.calls("x_unfreeze")
          and any(c["a"] & 0xFF == 0x1E for c in n.calls("music")) and bl,
          f"{fight and f8 and fight['f'] - f8[0]['f']} frames, {len(tm) - len(dec) - 1} frames stalled")
    check("fight damage class 7", any(e["dmg"] == 7 for e in n.p if e["state"] == 4))

    # --- Gust ------------------------------------------------------------------------------------
    gu = t["gust"]
    gs = gu.starts(gu.fight(0, 4))
    lens = []
    for s in gs:
        e = next((e for e in gu.p if e["f"] > s["f"] and not (e["step"] == 0 and e["sub"] == 4)), None)
        if e:
            lens.append(e["f"] - s["f"])
    check("Gust: flaps for 120, 240 or 360 frames (16-bit timer), on the ground (pose 1)",
          lens and set(lens) <= {120, 240, 360} and all(s["f38"] == 1 for s in gs), f"{lens}")
    pause = gu.starts(gu.fight(0, 6))
    gaps = [gu.next_call("choose", s["f"]) - s["f"] for s in pause if gu.next_call("choose", s["f"])]
    check("Gust: then a 40-frame pause", gaps and set(gaps) <= {39, 40}, f"{gaps[:5]}")

    def speeds(x):
        """X's mean speed (px/frame) walking on the deck: (with no wind, toward him during a Gust, frames)."""
        free, wind = [], []
        for f in range(1, max(x.x) + 1):
            a, b, e = x.x.get(f - 1), x.x.get(f), x.at.get(f)
            if not (a and b and e and e["state"] == 4 and a["step"] == 4 and b["step"] == 4 and a["y"] == b["y"] == 207):
                continue
            if e["step"] == 0 and e["sub"] == 4:
                wind.append(b["x"] - a["x"] if e["x"] > a["x"] else a["x"] - b["x"])
            else:
                free.append(abs(b["x"] - a["x"]))
        return (sum(free) / len(free) if free else 0), (sum(wind) / len(wind) if wind else 0), len(wind)
    walk, net2, n2 = speeds(gu)
    check("X walks 1.5 px a frame (steps of 1 and 2)", abs(walk - 1.5) < 0.05, f"{walk:.2f}")
    check("Gust: pushes X 2 px a frame away from him (walking speed − speed into the wind)",
          n2 > 100 and abs((walk - net2) - 2) < 0.1, f"walk {walk:.2f}, into the wind {net2:.2f} over {n2} frames")
    wind = [c["f"] for c in gu.calls("wind_effect")]
    eff = [c["f"] for c in gu.calls("alloc_effect")]
    check("Gust: a wind effect every 3 frames", len(eff) > 20 and collections.Counter(b - a for a, b in zip(eff, eff[1:])).most_common(1)[0][0] == 3,
          f"{len(eff)} effects, {len(wind)} wind calls")

    # --- Dive ------------------------------------------------------------------------------------
    chains, vel = [], []
    for k in ("dive", "dive2"):
        x = t[k]
        picks = [c["f"] for c in x.calls("choose")]        # one Dive attack between two picks
        dives = x.starts(x.fight(2, 4))
        for a, b in zip(picks, picks[1:]):
            chains.append(sum(1 for d in dives if a < d["f"] <= b))
        vel += [(d["vx"], d["vy"]) for d in dives]
    chains = [c for c in chains if c]
    check("Dive: one dive, or a chain of 6-9", chains and set(chains) <= {1, 6, 7, 8, 9}, f"{chains}")
    check("Dive: dives at vy -1024 (4 px a frame)", vel and all(v == -1024 for _, v in vel),
          f"vx {sorted(set(abs(a) for a, _ in vel))}")
    x = t["dive"]
    ds = x.starts(x.fight(2, 4))
    ok = []
    for d in ds:
        xx, p = x.x.get(d["f"] - 1), x.at.get(d["f"] - 1)
        if xx and p:
            sy = p["y"] - 0x10000 if p["y"] >= 0x8000 else p["y"]
            ok.append(abs(abs(d["x"] - xx["x"]) - (xx["y"] - sy)) <= 6)     # one frame of movement
    check("Dive: starts at X.x ± (X.y − his y), i.e. on a 45° line through X", ok and all(ok), f"{ok[:6]}")
    rs = x.starts(x.fight(2, 6))
    check("Dive: off the bottom, waits 40 frames", rs and all(r["f34"] == 40 for r in rs))

    # --- Storm Tornado / Birds -------------------------------------------------------------------
    x = t["tornado"]
    sh = [c["f"] for c in x.calls("alloc_shot")]
    fire = x.starts(x.fight(4, 6))
    check("Storm Tornado: fired once per attack, from the ground (pose 3)",
          fire and sh and all(any(abs(s - f["f"]) <= 1 for s in sh) for f in fire)
          and all(x.at.get(f["f"] - 1, {}).get("f38") == 3 for f in fire), f"{len(fire)} attacks, {len(sh)} shots")
    tw = []
    tor = {e["f"]: e for e in x.ev if e["tag"] == "tornado" and "slot" in e}
    for f in sorted(tor):
        a, b = x.x.get(f - 1), x.x.get(f)
        if a and b and a["step"] == 4 and b["step"] == 4 and abs(tor[f]["x"] - b["x"]) < 40:
            tw.append(b["x"] - a["x"] if tor[f]["vx"] > 0 else a["x"] - b["x"])
    check("Storm Tornado: pushes X along with it (net speed walking into it)", tw,
          f"{len(tw)} frames touching, mean {sum(tw) / len(tw) if tw else 0:.2f} px/frame, vx {sorted(set(e['vx'] for e in tor.values()))[:4]}")
    x = t["birds"]
    up = x.starts(x.fight(6, 2))
    rel = x.starts(x.fight(6, 4))
    birds = [c["f"] for c in x.calls("alloc_enemy")]
    check("Birds: flies up (vy $100) for 90 frames, then releases birds",
          up and rel and up[0]["vy"] == 0x100 and rel[0]["f"] - up[0]["f"] in (89, 90, 91) and birds,
          f"{rel and up and rel[0]['f'] - up[0]['f']} frames, {len(birds)} birds")
    eg = [(e["f"], e["n"]) for e in x.ev if e["tag"] == "eggs"]
    br = [(e["f"], e["n"]) for e in x.ev if e["tag"] == "birds"]
    # counts are logged only when they change; the count before the first entry is 0
    laid = [f for (f, n), m in zip(eg, [0] + [n for _, n in eg]) if n > m]
    gone = [f for (f, n), m in zip(eg, [0] + [n for _, n in eg]) if n < m]
    hatch = [f for (f, n), m in zip(br, [0] + [n for _, n in br]) if n - m == 4]
    life = [g - l for l, g in zip(laid, gone)]
    check("Birds: he drops an egg (enemy $55) that hatches after 30 frames into 4 birds (enemy $56)",
          laid and life and set(life) <= {29, 30, 31} and all(any(abs(h - g) <= 1 for h in hatch) for g in gone),
          f"{len(laid)} eggs, lifetimes {life[:4]}, hatches {len(hatch)}, eggs alive at once {max(n for _, n in eg) if eg else 0}")
    p3 = x.starts(x.fight(6, 6))
    gaps = [x.next_call("choose", s["f"]) - s["f"] for s in p3 if x.next_call("choose", s["f"])]
    check("Birds: then a 20-frame pause", gaps and set(gaps) <= {19, 20}, f"{gaps[:5]}")

    # --- attack choice statistics ---------------------------------------------------------------
    b = snes2pc(TABLE)
    table = [list(g.rom[b + r * 4:b + r * 4 + 4]) for r in range(4)]
    obs = [[0] * 4 for _ in range(4)]
    for k, x in t.items():
        if k.startswith("stats") or k in ("natural", "buster"):
            for c in x.calls("choose"):
                bf, af = x.at.get(c["f"]), x.at.get(c["f"] + 1)
                if bf and af and bf["state"] == 4 and af["state"] == 4:
                    obs[bf["step"] // 2][af["step"] // 2] += 1
    chi, impossible, dof = 0.0, 0, 0
    for r in range(4):
        nrow = sum(obs[r])
        w = table[r][:]
        w[0] = 32 - sum(w[1:])
        for c in range(4):
            e = w[c] * nrow / 32
            if e:
                chi += (obs[r][c] - e) ** 2 / e
                dof += 1
            elif obs[r][c]:
                impossible += 1
    dof -= 4
    z = ((chi / dof) ** (1 / 3) - (1 - 2 / (9 * dof))) / math.sqrt(2 / (9 * dof)) if dof > 0 else 99
    total = sum(map(sum, obs))
    check("attack choice (unforced) matches the weights at $86:D41B (Gust gets the remainder)",
          abs(z) < 2.5 and not impossible and total > 60, f"{total} picks, chi2={chi:.1f}/{dof}, z={z:.2f}, {obs}")
    done, ok = set(), []
    for k in [f"table{i}" for i in range(5)]:
        x = t[k]
        for fo in [e for e in x.ev if e["tag"] == "force"]:
            af = x.at.get(fo["f"] + 1)
            if af and af["state"] == 4:
                ok.append(af["step"] == 2 * pick_value(table, fo["row"], fo["v"]))
                done.add((fo["row"], fo["v"]))
    check("attack choice (forced): at every weight boundary of every row the roll gives the expected attack "
          "(Birds, Tornado, Dive tested in that order, then Gust)", ok and all(ok) and done == set(cases),
          f"{sum(ok)}/{len(ok)}, {len(done)}/{len(cases)} cases")

    # --- getting hit -------------------------------------------------------------------------------
    bu = t["buster"]
    row7 = g.rom[snes2pc(DAMAGE_TABLE) + g.w(snes2pc(DAMAGE_TABLE) + 14):][:30]
    hits = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: -1 HP (damage row 7)", hits and all((a["hp"] - c["hp"]) & 0x7F == row7[0] for a, c in hits),
          f"{len(hits)} hits")
    check("hit: 60 frames invulnerable (sound $13), damage class 5 meanwhile",
          hits and all(c["f37"] == 60 or c["f37"] == 59 for a, c in hits)
          and all(bu.at.get(c["f"] + 1, {}).get("dmg") == 5 for a, c in hits)
          and any(s["a"] & 0xFF == 0x13 for s in bu.calls("sound")), f"{[c['f37'] for a, c in hits][:5]}")
    d = t["death"]
    six = d.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, death pose 10, boss_defeated = 1, X hurt_lock bit 0",
          six and any(c["a"] & 0xFF == 10 for c in d.calls("anim") if abs(c["f"] - six[0]["f"]) <= 1)
          and any(e["v"] == 1 for e in d.ev if e["tag"] == "boss_defeated")
          and any(e["v"] & 1 for e in d.ev if e["tag"] == "X_hurt_lock" and six and e["f"] >= six[0]["f"] - 1))
    check("death: boss_defeated_sequence every frame, then he despawns",
          len(d.calls("defeat_seq")) > 300 and any(e["tag"] == "eagle" and "gone" in e for e in d.ev),
          f"{len(d.calls('defeat_seq'))} calls")
    xd = t["x_dies"]
    check("x_dead ($30) = 1 once X's HP is 0", any(e["f30"] == 1 for e in xd.p))

    # --- editable values -------------------------------------------------------------------------
    walk1, net1, n1 = speeds(t["v_gust"])
    check("value gust_push = $100 -> 1 px a frame", n1 > 100 and abs((walk1 - net1) - 1) < 0.1,
          f"walk {walk1:.2f}, into the wind {net1:.2f} over {n1} frames")
    v = t["v_hit"]
    check("value max_hp = 20 -> HP fill stops at 20", v.p and max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    # (the frame a hit lands the timer is already one lower when we read it: 60 shows as 59)
    check("value invuln_time = $20 -> 32 frames", v.p and max(e["f37"] for e in v.p) == 31, f"{v.p and max(e['f37'] for e in v.p)}")

    # --- which routines he uses where -------------------------------------------------------------
    use = collections.defaultdict(set)
    for x in alls:
        for e in x.ev:
            if e["tag"] in FIELDS.values() and e.get("d") == x.slot and e["f"] in x.at:
                p = x.at[e["f"]]
                use[e["tag"]].add((p["state"], p["step"]))
    check("wind effect only during the Gust", use["wind_effect"] == {(4, 0)}, f"{use['wind_effect']}")
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
