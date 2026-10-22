"""
Re-checks everything we claim about Launch Octopus by running the game in Mesen (see mesen_verify.py).

    python3 verify_launch_octopus.py          # about 15 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_launch_octopus.py --cached # re-check the last run's saved output

His boss checkpoint (2) is the flooded corridor between his doors (x 7160 and 7416, floor y 703). Tests start X at
(7296, 640) so the camera sits at y 512 as it does there (the warp centres the camera on X; lower down, his spawn
point at y 512 never comes into range). X walks right through the door into the room (x 7424-7680). The suite
plays that once and saves a state at the first frame of the fight (work/states/launch_octopus_fight.mss); most
runs start from it. X takes no damage (AR code) unless a test needs him caught by the whirlpool.
His choice is checked exhaustively in one frame: a hook at the end of choose_next_attack ($81:CA42) sends him
back to its start 192 times, each time with a chosen distance ($81:CA15), tentacle state ($81:CA2A) and roll
($81:CA37), and logs what it picked.
"""
import collections
import json
import sys

import params as P
from defs import LAUNCH_OCTOPUS as LO, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state, countdown, shot_log, X_LOG, Fight, report

ID, TORPEDO, WHIRL, PIRANHA = 0x07, 0x1E, 0x1D, 0x08
CACHE = "work/launch_octopus_runs.json"
STATE = "work/states/launch_octopus_fight.mss"
PAR = {p.key: p for p in LO.params}
TABLE = LO.attack_tables[0].addr               # 6 rows of 32 at $86:C625: close, far, mid, then the same cut
HOP_VY = 0x86C6F5
PIRANHA_OFS = 0x86C6E5
EXECS = {0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze", 0x84AADD: "beaten",
         0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound", 0x828358: "alloc_shot",
         0x828321: "alloc_enemy", 0x8282D3: "alloc_effect", 0x84A677: "defeat_seq", 0x849B43: "hit_check",
         0x849B03: "hurt_x", 0x84ACA5: "face_x", 0x849F19: "x_grabbed", 0x849F7E: "x_drop",
         0x849F2F: "x_take_damage", 0x81CA37: "r_pick", 0x81C604: "r_hop", 0x81CA55: "fire_torpedoes",
         0x81CAB7: "tentacle_hit", 0x81C88D: "whirlpool_end"}
M = f"find(0x0E68, 0x1228, {ID})"
START = dict(level=1, x=7296, y=640)
LEFT, MID, NEAR = 7450, 7530, 7570
WALK_IN = f"return {{right = r16(0x0BAD) < {MID}}}"


def hold(x, fire=False, extra=""):
    return (("fire = true\n" if fire else "") + extra + f"""local xx = r16(0x0BAD)
return {{right = xx < {x - 3}, left = xx > {x + 3}, y = fire and frame % 16 < 8}}""")


HOLD = hold(MID)
FIRE = hold(LEFT, True)
NO_DAMAGE = f"do local m = {M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
# hurtable (so the whirlpool can catch X) only while he does the whirlpool; X's HP topped up to 16 otherwise
CATCHABLE = f"""do local m = {M}
if m and r8(m + 1) == 4 then
  if r8(m + 2) ~= 2 then w8(0x0BD8, 8); w8(0x0BCF, 0x90) else w8(0x0BD8, 0) end
  if not hpset then w8(m + 0x27, 0x80 | 20); hpset = true end
end end"""
SET_HP1 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); hpset = true end end"
CUTTER = "w16(0x1F93, 0xDC00); w8(0x0BDB, 14)"     # own Boomerang Cutter with ammo, and select it
SHIELD = "w16(0x1F8B, 0xDC00); w8(0x0BDB, 6)"      # Rolling Shield
DISTS = {0: (40, 79), 32: (128, 200), 64: (80, 127)}  # row offset -> (distances tried)


def table(g):
    b = snes2pc(TABLE)
    return list(g.rom[b:b + 192])


def exhaust():
    """Hooks: on the first choice, re-run choose_next_attack 192 times in that frame (every row and column)."""
    cases = [(off + 96 * cut, DISTS[off][c % 2], cut, c) for cut in (0, 1) for off in (0, 32, 64) for c in range(32)]
    lua = "{" + ", ".join(f"{{{d}, {cut}, {c}}}" for _, d, cut, c in cases) + "}"
    # (the exec hook at $81CA07 doesn't fire again when the PC is set back to it, so the loop hook advances)
    return [(0x81CA07, f'if not lo_done and not lo_cur then lo_c = {lua}; lo_n = 1; lo_cur = lo_c[1] end'),
            (0x81CA15, 'if lo_cur then setreg("cpu.a", lo_cur[1]) end'),
            (0x81CA2A, 'if lo_cur then w8(s["cpu.d"] + 0x36, lo_cur[2]) end'),
            (0x81CA37, 'if lo_cur then setreg("cpu.a", (s["cpu.a"] & 0xFF00) | lo_cur[3]) end'),
            (0x81CA42, 'if lo_cur then out("pick", "dist=" .. lo_cur[1] .. " cut=" .. lo_cur[2] .. " col=" .. lo_cur[3] .. '
                       '" row=" .. r8(s["cpu.d"] + 0x37) .. " step=" .. (s["cpu.a"] & 0xFF)); '
                       'if lo_n < #lo_c then lo_n = lo_n + 1; lo_cur = lo_c[lo_n]; setreg("cpu.pc", 0xCA07) '
                       'else lo_done = true; lo_cur = nil; w8(s["cpu.d"] + 0x36, 0) end end')], cases


def only(attack, **values):
    def f(g):
        b = snes2pc(TABLE)
        for i in range(192):
            g.rom[b + i] = attack
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def values(**v):
    return lambda g: [P.put(g, PAR[k], x) for k, x in v.items()]


def run(frames, inp=HOLD, seed=None, inf=True, ar=True, patch=None, extra=(), hooks=(), full=False):
    r = Run(**START, frames=frames, seed=seed, infinite_hp=inf, patch=patch, savestate=None if full else STATE)
    r.track(ID, tag="lo")
    r.track(PIRANHA, tag="pir")
    for a, t in EXECS.items():
        r.on_exec(a, t)
    for a, lua in hooks:
        r.at_exec(a, lua)
    r.at_exec(0x81CAF1, 'out("piece", "sub=" .. (s["cpu.a"] & 0xFF))')       # tentacle piece's sub-id as it is written
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.on_write(0x1F0E, "hud_boss")
    r.input(inp)
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame(X_LOG)
    r.each_frame(shot_log("sh", [TORPEDO, WHIRL]))
    r.each_frame(shot_log("pirs", [PIRANHA], 0x0E68, 0x1228))
    r.each_frame(shot_log("fx", [0x07], 0x1928, 0x1D28))
    for lua in extra:
        r.each_frame(lua)
    return r


def timer(e):
    return e["f34"] + 256 * e["f35"]


def main():
    g0 = MMX1("work/hack.sfc")
    tab = table(g0)
    hop_vy = [g0.w(snes2pc(HOP_VY) + 2 * i) for i in range(4)]
    pofs = [((g0.w(snes2pc(PIRANHA_OFS) + 4 * i) + 0x8000) % 0x10000 - 0x8000,
             (g0.w(snes2pc(PIRANHA_OFS) + 4 * i + 2) + 0x8000) % 0x10000 - 0x8000) for i in range(4)]
    hooks, cases = exhaust()
    natural = [("n0", 0x1111, hold(LEFT)), ("n1", 0x2345, hold(MID)), ("n2", 0x3C3C, hold(NEAR)),
               ("n3", 0x4A21, hold(LEFT, True))]
    runs = {k: run(5000, inp, seed=s) for k, s, inp in natural}
    runs.update({
        "intro": run(1500, WALK_IN, seed=0x1234, full=True),
        "table": run(600, seed=0x1001, hooks=hooks),
        "hop": run(4000, seed=0x2001, patch=only(0)),
        "whirl": run(4000, seed=0x2002, patch=only(2)),
        "piranha": run(3000, seed=0x2003, patch=only(4)),
        "volley": run(3000, seed=0x2004, patch=only(6)),
        "drain": run(4000, hold(NEAR), seed=0x2005, inf=False, ar=False, patch=only(2), extra=[CATCHABLE]),
        "mash": run(4000, "return {right = r16(0x0BAD) < 7567, left = r16(0x0BAD) > 7573, b = frame % 4 == 0}",
                    seed=0x2006, inf=False, ar=False, patch=only(2), extra=[CATCHABLE]),
        "buster": run(3000, hold(MID, True), seed=0x2007),
        "cutter": run(4000, hold(MID, True, CUTTER + "\n"), seed=0x2008),
        "shield": run(3000, hold(MID, True, SHIELD + "\n"), seed=0x2009),
        "death": run(1500, FIRE, seed=0x200A, extra=[SET_HP1]),
        "x_dies": run(3000, hold(NEAR), seed=0x200B, inf=False, ar=False),
        "v_hit": run(2600, FIRE, seed=0x3001, full=True, patch=values(max_hp=20, invuln_time=0x20)),
        "v_hop": run(3000, seed=0x3002, patch=only(2, whirlpool_jump=0x500)),
        "v_cut": run(3000, hold(MID, True, CUTTER + "\n"), seed=0x3003, full=True, patch=values(cut_hits=1)),
        "v_drain": run(4000, hold(NEAR), seed=0x3004, inf=False, ar=False, extra=[CATCHABLE],
                       patch=only(2, drain_time=0x0100, drain_tick=0x10)),
    })
    if "--cached" in sys.argv:
        out = json.load(open(CACHE))
    else:
        print("playing to the start of the fight...", flush=True)
        fight_state(STATE, START["level"], START["x"], WALK_IN,
                    f"(function() local m = {M}; return m and r8(m + 1) == 4 end)()", y=START["y"])
        print(f"running {len(runs)} emulator sessions...", flush=True)
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    t = {k: Fight(v, "lo") for k, v in out.items()}
    nat = [t[k] for k, _, _ in natural]
    alls = [x for k, x in t.items() if not k.startswith("v_") and k != "x_dies"]
    dt = snes2pc(DAMAGE_TABLE)
    row = g0.rom[dt + g0.w(dt + 2 * LO.damage_class):][:32]
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # --- intro -------------------------------------------------------------------------------
    n = t["intro"]
    init = n.starts(lambda e: e["state"] == 0 and e["step"] == 1)[0]
    check("init: boss_already_beaten, x_freeze_for_boss, jingle $2E",
          n.calls("beaten") and n.calls("x_freeze", False) and any(c["a"] & 0xFF == 0x2E for c in n.calls("music", False)))
    ok, a, b = countdown(n.phase(init), "f34", 59)
    ok2, a2, b2 = countdown(n.phase(init), "f34", 60)
    check("init: 60-frame wait (timer $34)", ok or ok2, f"{a}..{b}")
    st2 = n.starts(lambda e: e["state"] == 2)[0]
    check("obj_start: palette_bits ($33) = attr & $0E, cut_hits_left ($0C) = 3, tentacles_cut 0",
          st2["f33"] == st2["attr"] & 0x0E and st2["parent"] & 0xFF == 3 and st2["f36"] == 0)
    sink = n.starts(lambda e: e["state"] == 2 and e["step"] == 2)
    land = n.starts(lambda e: e["state"] == 2 and e["step"] == 4)
    check("intro: starts 16 px higher and sinks at 1 px a frame (vy −$100) for at least 40 frames until he lands",
          sink and land and sink[0]["vy"] == -0x100 and sink[0]["y"] == st2["y"] - 16
          and land[0]["f"] - sink[0]["f"] >= 40, f"y {sink and sink[0]['y']} -> {land and land[0]['y']}, "
                                                 f"{land[0]['f'] - sink[0]['f'] if land and sink else None} frames")
    ticks = [c["f"] for c in n.calls("sound_c") if n.at.get(c["f"] + 1, {}).get("state") == 2]
    check("landing: boss bar (hud_boss); HP +1 every 2 frames to 32", len(ticks) == 32 and n.by_tag["hud_boss"]
          and set(b - a for a, b in zip(ticks, ticks[1:])) == {2}, f"{len(ticks)} ticks")
    e6 = n.starts(lambda e: e["state"] == 2 and e["step"] == 6)[0]
    nx = n.after(e6)
    check("end of intro: when the pose ends, x_unfreeze, music $1E, state 4 starting with the Torpedo hop",
          nx and (nx["state"], nx["step"]) == (4, 0) and n.calls("x_unfreeze", False)
          and any(c["a"] & 0xFF == 0x1E for c in n.calls("music", False)))
    # (set before this frame's hit check and timer step: compare with the timer as the frame began)
    dm = collections.Counter((e["f3A"] != 0, x.at[e["f"] - 1]["f3C"] != 0, e["dmg"]) for x in alls for e in x.p
                             if e["state"] == 4 and x.at.get(e["f"] - 1, {}).get("state") == 4 and e["dmg"] != 3
                             and not (e["f3C"] and e["f3C"] == x.at[e["f"] - 1]["f3C"]))   # (busy frames: no update)
    check("damage class 12; 5 while invulnerable (invuln_timer $3C as the frame starts); 0 (shots bounce off) "
          "while spinning (deflecting $3A)",
          dm and all(d == (0 if de else 5 if inv else 12) for (de, inv, d) in dm), f"{dict(dm)}")

    # --- choice ------------------------------------------------------------------------------
    x = t["table"]
    picks = x.by_tag["pick"]
    want = [(0 if p["dist"] < 80 else 32 if p["dist"] >= 128 else 64) + 96 * p["cut"] for p in picks]
    good = [p["row"] == r_ and p["step"] == tab[r_ + p["col"]] for p, r_ in zip(picks, want)]
    tried = {(r_, p["col"]) for p, r_ in zip(picks, want)}
    check("attack choice (all 192 entries, re-run within one frame): row = distance (< 80 -> 0, ≥ 128 -> $20, "
          "else $40; tried at 40/79, 128/200, 80/127) + $60 once the tentacles are cut, column = random & 31, "
          "attack = entry at $86:C625", len(picks) == 192 and all(good) and len(tried) == 192,
          f"{sum(good)}/{len(picks)}, {len(tried)} entries")
    after = x.at.get(picks[-1]["f"] + 2) if picks else None
    check("after the 192 re-runs the game carries on normally", after and after["state"] == 4 and x.p[-1]["f"] >= 590)
    un = []
    for k, x in t.items():
        if k in ("table", "hop", "whirl", "piranha", "volley", "drain", "mash") or k.startswith("v_"):
            continue                                          # (forced or patched tables)
        for c in x.calls("r_pick"):
            a = x.at.get(c["f"] + 1)
            if a and a["state"] == 4:
                un.append(a["step"] == tab[a["f37"] + (c["a"] & 0x1F)] or a["step"] == 8)
    check("unforced choices agree with the table", un and all(un), f"{sum(un)}/{len(un)}")

    # --- Torpedo hop -------------------------------------------------------------------------
    ho = [t["hop"], *nat]
    hv = []
    for x in ho:
        for c in x.calls("r_hop"):
            a = x.at.get(c["f"] + 1)
            if a and a["step"] == 0:
                hv.append(a["vy"] == hop_vy[c["a"] & 3] and abs(a["vx"]) == 0x180 and a["grav"] == 44)
    check(f"Torpedo hop: vy = $86:C6F5[random & 3] ({', '.join(f'${v:X}' for v in hop_vy)}), vx ±$180, gravity 44",
          hv and all(hv), f"{sum(hv)}/{len(hv)}")
    vols = []
    for x in [t["hop"], t["volley"], *nat]:
        for c in x.calls("fire_torpedoes", True):
            m = x.at.get(c["f"] + 1)                       # (his position after this frame's move, when he fires)
            ls = [l for l in x.lives("sh") if l[0]["f"] == c["f"] + 1 and l[0]["id"] == TORPEDO]
            if m:
                fr = bool(m["attr"] & 0x40)
                vols.append((sorted(l[0]["sub"] for l in ls), all(l[0]["y"] == m["y"] - 7 and
                             abs(l[0]["x"] - m["x"]) in (6, 11) for l in ls), x.called("sound", c["f"] + 1, 0x1E)))
    check("fire_torpedoes: 3 enemy shots $1E (sub-ids 2, 1, 0) at his x ± 6 or 11 (by pose), y − 7, sound $1E",
          vols and all(v == ([0, 1, 2], True, True) for v in vols), f"{len(vols)} volleys")
    tv = {}
    for x in [t["hop"], t["volley"]]:
        for l in x.lives("sh"):
            if l[0]["id"] == TORPEDO and len(l) > 3:
                tv.setdefault(l[0]["sub"], set()).add((abs(l[1]["vx"]), l[1]["vy"] * (1 if l[1]["vx"] < 0 else -1)))
    speedup = [abs(l[-1]["vx"]) + abs(l[-1]["vy"]) > abs(l[1]["vx"]) + abs(l[1]["vy"]) for x in [t["volley"]]
               for l in x.lives("sh") if l[0]["id"] == TORPEDO and len(l) > 10]
    check("torpedo: sub-id 2 starts angled up, 1 straight-ish, 0 down (≈ $200 px), and speeds up as it flies",
          tv and speedup and sum(speedup) > len(speedup) * 0.8, f"first velocities {dict((k, sorted(v)[:2]) for k, v in tv.items())}")
    lands = [countdown(x.phase(s), "f34", 30) for x in ho for s in x.starts(x.fight(0, 8))
             if x.phase(s) and x.after(s) and x.after(s)["step"] != 8
             and x.at.get(s["f"] - 1, {}).get("sub") == 6]          # (not resumed after a flinch)
    check("Torpedo hop: lands, 30 frames (timer $34), then chooses again", lands and all(o for o, _, _ in lands),
          f"{len(lands)}")

    # --- Torpedo volley ----------------------------------------------------------------------
    v = t["volley"]
    st = v.starts(v.fight(6, 2))
    per = [len([c for c in v.calls("fire_torpedoes", True) if p[0]["f"] - 1 <= c["f"] <= p[-1]["f"]])
           for s in st for p in [v.phase(s)] if p]
    check("Torpedo volley: faces X, fires torpedoes on keyframes until the animation ends, 30 frames, chooses",
          per and all(k >= 1 for k in per) and all(o for o, _, _ in v.timers(6, 4, "f34", 30)),
          f"volleys per attack {collections.Counter(per)}")

    # --- Piranha swarm -----------------------------------------------------------------------
    p = t["piranha"]
    sw = []
    for s in p.starts(p.fight(4, 4)):
        m = p.at.get(s["f"] - 1)
        ls = [l for l in p.lives("pirs") if s["f"] - 1 <= l[0]["f"] <= s["f"]]
        offs = sorted((l[0]["sub"], l[0]["x"] - s["x"], l[0]["y"] - s["y"]) for l in ls)
        sw.append((offs, p.called("sound", s["f"], 0x1E)))
    want = [(i, pofs[i][0], pofs[i][1]) for i in range(4)]
    check("Piranha swarm: when the pose ends, 4 piranhas (enemy $08, sub-ids 0-3) at his position + "
          f"$86:C6E5 {pofs}, sound $1E; chooses when the animation ends",
          sw and all(o == want and snd for o, snd in sw), f"{len(sw)} swarms, {sw[:1]}")

    # --- Whirlpool ---------------------------------------------------------------------------
    w = t["whirl"]
    jv = []
    for s in w.starts(w.fight(2, 2)):
        b = w.at.get(s["f"] - 1)
        xx = w.x.get(s["f"] - 1)
        if b and xx:
            d = abs(xx["x"] - b["x"])
            jv.append((abs(s["vx"]), d * 256 // 42, s["vy"], s["grav"]))
    check("Whirlpool: jumps with vy $720 (whirlpool_jump), gravity 44, vx = |X.x − his x| × 256 / 42 toward X",
          jv and all(abs(a - b) <= 8 and vy == 0x720 and gr == 44 for a, b, vy, gr in jv), f"{jv[:3]}")
    sp = w.starts(w.fight(2, 4))
    wl = []
    for s in sp:
        ls = [l for l in w.lives("sh") if l[0]["id"] == WHIRL and s["f"] - 1 <= l[0]["f"] <= s["f"]]
        wl.append((s["vy"], s["vx"], s["f39"], s["f3A"], len(ls), ls and ls[0][0]["x"] == s["x"]))
    check("Whirlpool: at the top of the jump he spins (vy −$100, vx 0, spinning, deflecting) and makes the "
          "whirlpool (enemy shot $1D) at his x", wl and all(o == (-0x100, 0, 1, 1, 1, True) for o in wl), f"{wl[:2]}")
    nog = []
    for s in sp:
        a = w.after(s)
        if a:
            nog.append((a["sub"], a["vy"]))
    rise = [w.after(s) for s in w.starts(w.fight(2, 8))]
    check("Whirlpool (X not caught): lands, rises at vy $200 to the ceiling, then falls (gravity 44) and chooses",
          nog and all(o == (8, 0x200) for o in nog) and rise and all(r and r["sub"] == 10 and r["f39"] == 0
                                                                     and r["f3A"] == 0 for r in rise), f"{nog[:3]}")
    dr = t["drain"]
    gr = dr.starts(dr.fight(2, 6))
    check("Whirlpool: X overlapping him (and not above him) -> x_grabbed, drain timer $1E1, drain_tick 32",
          gr and all(timer(s) in (0x1E1, 0x1E0) and s["f3B"] in (31, 32) for s in gr)
          and all(dr.called("x_grabbed", s["f"]) for s in gr), f"{len(gr)} catches")
    held = collections.Counter()
    for s in gr:
        for e in dr.phase(s)[1:]:
            xx = dr.x.get(e["f"])
            if xx:
                held[(xx["x"] - e["x"], xx["y"] - e["y"])] += 1
    check("draining: X held at his x, y + 32 (+31 once X's own update has run that frame)",
          held and set(held) == {(0, 31)}, f"{dict(held)}")
    ticks = []
    for s in gr:
        ph = dr.phase(s)
        hpup = [(a["f"], (c["hp"] & 0x7F) - (a["hp"] & 0x7F)) for a, c in zip(ph, ph[1:]) if c["hp"] != a["hp"]]
        ticks.append([b[0] - a[0] for a, b in zip(hpup, hpup[1:])])
    xd = [(a["hp"] & 0x7F) - (b["hp"] & 0x7F) for a, b in zip(dr.by_tag["X"], dr.by_tag["X"][1:])
          if any(s["f"] < b["f"] < s["f"] + 600 for s in gr) and b["hp"] != a["hp"] and b["hp"] & 0x7F != 16]
    check("draining: every 32 frames X loses 1 HP and he gains 1 (sound $4F)", ticks and all(set(k) <= {32, 33} for k in ticks if k)
          and any(ticks) and any(c["a"] & 0xFF == 0x4F for c in dr.calls("sound_c", False)),
          f"intervals {[collections.Counter(k) for k in ticks][:3]}, X HP steps {collections.Counter(xd)}")
    ends = []
    for s in gr:
        ph = dr.phase(s)
        a = dr.after(s)
        if ph and a:
            ends.append((len(ph), a["sub"], a["y"] - ph[-1]["y"], dr.called("x_drop", a["f"])))
    check("draining: when the timer runs out, x_drop, he moves up 8 px and rises (vy $200)",
          ends and all(sub == 8 and dy == -8 and drop for _, sub, dy, drop in ends), f"{ends}")
    ma = t["mash"]
    mg = ma.starts(ma.fight(2, 6))
    lens = [len(ma.phase(s)) for s in mg if ma.phase(s)]
    cuts = [a["f34"] + 256 * a["f35"] - timer(c) for s in mg for a, c in zip(ma.phase(s), ma.phase(s)[1:])
            if timer(a) - timer(c) > 1]
    check("mashing: each new button press takes 16 more frames off the drain timer", lens and cuts
          and all(k == 17 for k in cuts if k < 100) and max(lens) < 481, f"drains {lens} frames, cuts {collections.Counter(cuts)}")

    # --- getting hit --------------------------------------------------------------------------
    bu = [t["buster"], t["n3"]]
    lhb = [{e["f"]: e["v"] for e in x.by_tag["last_hit"]} for x in bu]
    hits = [(x, a, c) for x in bu for a, c in zip(x.p, x.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: −1 HP (damage row 12), sound $13, invuln_timer ($3C) = 60", hits and all(
        (a["hp"] - c["hp"]) & 0x7F == row[0] and c["f3C"] in (59, 60) and x.called("sound", c["f"], 0x13)
        for x, a, c in hits), f"{len(hits)} hits")
    fl = []
    for x, a, c in hits:
        if c["step"] == 8:
            ph = x.phase(c, ("state", "step"))
            nx = x.after(ph[-1]) if ph else None
            nxt = x.at.get(ph[-1]["f"] + 1) if ph else None
            if nxt is not None and nxt["state"] == 4:     # (resume_attack = the step as he was hit; he may have just chosen)
                fl.append(nxt["step"] == c["f3D"] and c["f3D"] in (a["step"], 0, 2, 4, 6))
    check("hit: flinch (step 8) saving his step and animation, then resumes the same step where it left off",
          fl and all(fl), f"{sum(fl)}/{len(fl)}")
    inv = [c for x in bu for a, c in zip(x.p, x.p[1:]) if 0 < c["f3C"] == a["f3C"] - 1 and c["f3C"] & 3 == 0]
    rest = [(a, c) for x in bu for a, c in zip(x.p, x.p[1:]) if a["f3C"] > 1 and c["hp"] & 0x7F < a["hp"] & 0x7F]
    check("invulnerable: no HP lost; he flashes (palette bits cleared when the timer is a multiple of 4)",
          not rest and inv and all(c["attr"] & 0x0E == 0 for c in inv), f"{len(inv)} flash frames")
    spin_hits = [(a, c) for x in alls for a, c in zip(x.p, x.p[1:]) if a["f3A"] and c["hp"] & 0x7F < a["hp"] & 0x7F]
    check("spinning: shots bounce off (no HP lost)", not spin_hits)

    # --- tentacles / weakness -----------------------------------------------------------------
    cu = t["cutter"]
    lh = {e["f"]: e["v"] for e in cu.by_tag["last_hit"]}
    cuts = [(c["f"], (cu.at.get(c["f"] + 1) or {}).get("parent", 0) & 0xFF) for c in cu.calls("tentacle_hit")]
    cut = cu.starts(lambda e: e["f36"] == 1)
    fx = [e["sub"] for e in cu.by_tag["piece"] if cut and cut[0]["f"] - 2 <= e["f"] <= cut[0]["f"]]
    check("Boomerang Cutter (projectile $0D) hits count cut_hits_left 3 -> 0; at 0 tentacles_cut = 1, 4 tentacle "
          "pieces (effect $07, sub-ids 3-0)", cut and [k for _, k in cuts][:3] == [2, 1, 0] and fx == [3, 2, 1, 0],
          f"left after each {[k for _, k in cuts][:4]}, pieces {fx}, shots {sorted({v for v in lh.values() if v})}")
    fa = cu.starts(cu.fight(10))
    check("tentacles cut: he falls (step 10: vx 0, vy 0, gravity 44) and chooses on landing",
          fa and all(cu.at.get(s["f"] + 1, s)["grav"] == 44 for s in fa)
          and all(cu.at.get(ph[-1]["f"] + 1, {}).get("step") in (0, 2, 4, 6, 8)
                  for s in fa for ph in [cu.phase(s, ("state", "step"))] if ph))
    post = [cu.at.get(c["f"] + 1)["step"] for c in cu.calls("r_pick") if cut and c["f"] > cut[0]["f"]
            and cu.at.get(c["f"] + 1)]
    check("tentacles cut: rows +$60 hold only the torpedo attacks (hop, volley)",
          set(tab[96:]) == {0, 6} and post and set(post) <= {0, 6, 8}, f"{collections.Counter(post)}")
    sh = t["shield"]
    lhs = {e["f"]: e["v"] for e in sh.by_tag["last_hit"]}
    shh = [(a, c) for a, c in zip(sh.p, sh.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("Rolling Shield (his weakness, projectile $09): damage from row 12", shh and all(
        (a["hp"] - c["hp"]) & 0x7F == row[0x09] or c["hp"] & 0x7F == 0 for a, c in shh),
          f"{collections.Counter((a['hp'] - c['hp']) & 0x7F for a, c in shh)}, row12[$09] = {row[9]}, "
          f"shots {sorted({v for v in lhs.values() if v})}")

    # --- death / X ----------------------------------------------------------------------------
    de = t["death"]
    six = de.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, X_hurt_lock |= 1, boss_defeated |= 1, sound $13, boss_defeated_sequence, despawn",
          six and de.by_tag["boss_defeated"] and de.called("sound", six[0]["f"], 0x13)
          and len(de.calls("defeat_seq")) > 300 and any("gone" in e for e in de.by_tag["lo"]))
    xd = t["x_dies"]
    died = [e for e in xd.by_tag["X"] if e["hp"] & 0x7F == 0 and e["f"] > 10]
    check("x_dead ($30) = 1 once X's HP is 0", died and any(e["f30"] == 1 for e in xd.p if e["f"] >= died[0]["f"]),
          f"X at 0 HP from frame {died[0]['f'] if died else None}")
    noh = [c for c in dr.calls("hurt_x") if dr.at.get(c["f"] + 1, {}).get("f3B")]       # (drain_tick after that frame)
    check("hurt_x_on_contact is skipped while he drains X", dr.calls("hurt_x") and not noh)

    # --- values -------------------------------------------------------------------------------
    v = t["v_hit"]
    check("value max_hp = 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f3C"] for e in v.p) in (31, 32))
    v = t["v_hop"]
    check("value whirlpool_jump = $500", any(s["vy"] == 0x500 for s in v.starts(v.fight(2, 2))))
    v = t["v_cut"]
    check("value cut_hits = 1 -> one Boomerang Cutter hit cuts the tentacles", v.starts(lambda e: e["f36"] == 1)
          and len(v.calls("tentacle_hit")) >= 1 and v.starts(lambda e: e["f36"] == 1)[0]["f"] <= v.calls("tentacle_hit")[0]["f"] + 2)
    v = t["v_drain"]
    vg = v.starts(v.fight(2, 6))
    vt = []
    for s in vg:
        ph = v.phase(s)
        ups = [c["f"] for a, c in zip(ph, ph[1:]) if c["hp"] != a["hp"]]
        vt += [b - a for a, b in zip(ups, ups[1:])]
    check("values drain_time = $100, drain_tick = $10", vg and all(timer(s) in (0xFF, 0x100) for s in vg)
          and vt and set(vt) <= {16, 17}, f"{len(vg)} catches, intervals {collections.Counter(vt)}")

    report(results)


if __name__ == "__main__":
    main()
