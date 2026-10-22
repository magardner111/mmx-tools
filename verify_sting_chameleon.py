"""
Re-checks everything we claim about Sting Chameleon by running the game in Mesen (see mesen_verify.py).

    python3 verify_sting_chameleon.py          # about 15 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_sting_chameleon.py --cached # re-check the last run's saved output

His boss checkpoint (2) is the corridor between his doors (x 7672 and 7928, floor y 431) with the camera fixed at
y 256. Tests start X at (7808, 384), which gives that camera, and walk right through the door into the room
(x 7936-8192, ceiling y 272, floor y 432); his intro starts by itself. The suite plays that once and saves a state
at the first frame of the fight (work/states/sting_chameleon_fight.mss); most runs start from it. He has no attack
table: each attack ends with its own random rolls, which are logged where he reads them and checked against what he
does next.
"""
import collections
import json
import sys

import params as P
from defs import STING_CHAMELEON as SC, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state, countdown, shot_log, X_LOG, Fight, report

ID, SHOT = 0x0A, 0x11
CACHE = "work/sting_chameleon_runs.json"
STATE = "work/states/sting_chameleon_fight.mss"
PAR = {p.key: p for p in SC.params}
EXECS = {0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze", 0x84AADD: "beaten",
         0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound", 0x828358: "alloc_shot",
         0x84A677: "defeat_seq", 0x849B43: "hit_check", 0x849B03: "hurt_x", 0x84ACA5: "face_x",
         0x88880B: "r_leap", 0x88897E: "r_glide", 0x888B0B: "r_shake", 0x888BA2: "r_again", 0x888BC6: "r_leap_after",
         0x888C35: "r_tongue_after", 0x888EB9: "fire_sting", 0x888E4F: "x_in_tongue_reach"}
M = f"find(0x0E68, 0x1228, {ID})"
START = dict(level=2, x=7808, y=384)
LEFT, MID, RIGHT = 7980, 8064, 8150
WALK_IN = f"return {{right = r16(0x0BAD) < {MID}}}"


def hold(x, fire=False, extra=""):
    return (("fire = true\n" if fire else "") + extra + f"""local xx = r16(0x0BAD)
return {{right = xx < {x - 3}, left = xx > {x + 3}, y = fire and frame % 16 < 8}}""")


NO_DAMAGE = f"do local m = {M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
SET_HP1 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); hpset = true end end"
CUTTER = "w16(0x1F93, 0xDC00); w8(0x0BDB, 14)"     # own Boomerang Cutter with ammo, and select it
# X jumps and fires so shots reach him on the walls and ceiling too
JUMP_FIRE = f"""local xx = r16(0x0BAD)
return {{right = xx < {MID - 3}, left = xx > {MID + 3}, b = frame % 40 < 20, y = frame % 16 < 8}}"""


def values(**v):
    return lambda g: [P.put(g, PAR[k], x) for k, x in v.items()]


def run(frames, inp=None, seed=None, inf=True, ar=True, patch=None, extra=(), full=False):
    r = Run(**START, frames=frames, seed=seed, infinite_hp=inf, patch=patch, savestate=None if full else STATE)
    r.track(ID, tag="sc")
    for a, t in EXECS.items():
        r.on_exec(a, t)
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.on_write(0x1F0E, "hud_boss")
    r.input(inp or hold(MID))
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame(X_LOG)
    r.each_frame(shot_log("sh", [SHOT]))
    r.each_frame('out("cam", "l=" .. r16(0x1E4D) .. " t=" .. r16(0x1E50))')
    for lua in extra:
        r.each_frame(lua)
    return r


def main():
    g0 = MMX1("work/hack.sfc")
    natural = [("n0", 0x1111, hold(LEFT)), ("n1", 0x2345, hold(MID)), ("n2", 0x3C3C, hold(RIGHT)),
               ("n3", 0x4A21, JUMP_FIRE), ("n4", 0x5B5B, hold(LEFT)), ("n5", 0x6C6C, hold(RIGHT))]
    runs = {k: run(6000, inp, seed=s) for k, s, inp in natural}
    runs.update({
        "intro": run(1600, WALK_IN, seed=0x1234, full=True),
        "cutter": run(5000, JUMP_FIRE.replace("local xx", CUTTER + "\nlocal xx"), seed=0x2001),
        "death": run(2000, JUMP_FIRE, seed=0x2002, extra=[SET_HP1]),
        "x_dies": run(4000, hold(MID), seed=0x2003, inf=False, ar=False),
        "v_hit": run(3000, JUMP_FIRE, seed=0x3001, full=True, patch=values(max_hp=20, invuln_time=0x20)),
        "v_times": run(5000, seed=0x3002, patch=values(cloak_fade=0x10, cloak_wait=0x20, spike_wait=0x14)),
        "v_counts": run(5000, seed=0x3003, patch=values(sting_volleys=1, tongue_lashes=1)),
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
    t = {k: Fight(v, "sc") for k, v in out.items()}
    nat = [t[k] for k, _, _ in natural]
    alls = [x for k, x in t.items() if not k.startswith("v_") and k != "x_dies"]
    dt = snes2pc(DAMAGE_TABLE)
    row = g0.rom[dt + g0.w(dt + 2 * SC.damage_class):][:32]
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    def cam(x, f):
        return next((e for e in x.by_tag["cam"] if e["f"] == f), {"l": 0, "t": 0})

    # --- intro -------------------------------------------------------------------------------
    n = t["intro"]
    init = n.starts(lambda e: e["state"] == 0 and e["step"] == 1)[0]
    check("init: boss_already_beaten, x_freeze_for_boss, jingle $2E",
          n.calls("beaten") and n.calls("x_freeze", False) and any(c["a"] & 0xFF == 0x2E for c in n.calls("music", False)))
    ok, a, b = countdown(n.phase(init), "f34", 59)
    ok2, a2, b2 = countdown(n.phase(init), "f34", 60)
    check("init: 60-frame wait (timer $34)", ok or ok2, f"{a}..{b}")
    st2 = n.starts(lambda e: e["state"] == 2)[0]
    check("obj_start: attr = $2B, palette_bits ($3A) = $0A, then 30 frames", st2["attr"] & 0xFF == 0x2B
          and countdown(n.phase(st2), "f34", 30)[0], f"attr {st2['attr']:#x}")
    d = n.starts(lambda e: e["state"] == 2 and e["step"] == 2)
    fi = n.starts(lambda e: e["state"] == 2 and e["step"] == 4)
    check("intro: lowers at vy −$80 (0.5 px a frame) for 60 frames, then fades in for 90 frames (sound $76)",
          d and fi and d[0]["vy"] == -0x80 and fi[0]["y"] - d[0]["y"] in (29, 30, 31) and countdown(n.phase(d[0]), "f34", 60)[0]
          and countdown(n.phase(fi[0]), "f34", 90)[0] and n.called("sound", fi[0]["f"], 0x76),
          f"y {d and d[0]['y']} -> {fi and fi[0]['y']}")
    land = n.starts(lambda e: e["state"] == 2 and e["step"] == 8)
    ticks = [c["f"] for c in n.calls("sound_c") if n.at.get(c["f"] + 1, {}).get("state") == 2]
    check("intro: falls (gravity 64) to the floor -> boss bar; HP +1 every 2 frames to 32", land and n.by_tag["hud_boss"]
          and len(ticks) == 32 and set(b - a for a, b in zip(ticks, ticks[1:])) == {2}, f"{len(ticks)} ticks")
    s4 = n.starts(lambda e: e["state"] == 4)
    check("end of intro: music $1E, x_unfreeze, state 4 starting with a leap", s4 and s4[0]["step"] == 0
          and n.calls("x_unfreeze", False) and any(c["a"] & 0xFF == 0x1E for c in n.calls("music", False)))
    dm = collections.Counter((e["f37"] != 0, x.at[e["f"] - 1]["f33"] != 0, e["dmg"]) for x in alls for e in x.p
                             if e["state"] == 4 and x.at.get(e["f"] - 1, {}).get("state") == 4 and e["dmg"] != 3
                             and not (e["f33"] and e["f33"] == x.at[e["f"] - 1]["f33"]))
    check("damage class 6; 5 while invulnerable (unchanged while cloaked)",
          dm and all(d == (5 if inv else 6) for (cl, inv, d) in dm if not cl), f"{dict(dm)}")
    clk = [c for x in alls for c in x.calls("hit_check") if x.at.get(c["f"], {}).get("f37") and x.at.get(c["f"] + 1, {}).get("f37")]
    clh = [(a, c) for x in alls for a, c in zip(x.p, x.p[1:]) if a["f37"] and c["f37"] and c["hp"] & 0x7F < a["hp"] & 0x7F]
    check("cloaked: no hit check (can't be hurt) and no contact damage", not clk and not clh)
    f30 = [(e["f30"], e["f37"]) for x in alls for e in x.p if e["state"] == 4]
    check("field $30 cloak_copy (x_dead in other bosses) is a copy of cloaked ($37), set every frame", f30 and all(a == b for a, b in f30),
          f"{collections.Counter(f30)}")

    # --- leaps --------------------------------------------------------------------------------
    lp = []
    for x in alls:
        for c in x.calls("r_leap"):
            a, b = x.at.get(c["f"] + 1), x.at.get(c["f"])
            if not (a and b) or a["state"] != 4:
                continue
            left = cam(x, c["f"])["l"]
            high = c["a"] & 0x0F < 4
            right = left + 128 >= b["x"]                    # he is left of the middle -> leaps right
            tgt = left + ((208 if right else 48) if high else (192 if right else 64))
            vx = ((tgt - b["x"]) * 8 + 0x8000) % 0x10000 - 0x8000
            lp.append((high, a["sub"] == (8 if high else 6), a["vx"] == vx, a["vy"] == (0x740 if high else 0x593),
                       high or a["grav"] == 48))
    check("leap: random & 15 < 4 -> high leap to screen left + 48 / 208, else low leap to + 64 / 192 (to the other "
          "half of the room); vx = (target − x) × 8; low: vy $593, gravity 48", lp and all(all(o[1:]) for o in lp)
          and any(o[0] for o in lp) and not all(o[0] for o in lp), f"{sum(all(o[1:]) for o in lp)}/{len(lp)}, "
                                                                 f"{sum(o[0] for o in lp)} high")
    hg = [a["grav"] for x in alls for c in x.calls("r_leap") if c["a"] & 0x0F < 4
          for a in [x.at.get(c["f"] + 1)] if a and a["state"] == 4]
    check("high leap (game bug): vy is written $070D, then the gravity store hits vy's low byte -> vy $0740, gravity "
          "left as it was", hg and lp and all(o[3] for o in lp if o[0]), f"gravity on high leaps {collections.Counter(hg)}")
    ap = []
    for x in alls:
        for sub, nxt in ((6, (6, 0)), (10, (8, 0))):
            for s in x.starts(x.fight(0, 6 if sub == 6 else 8)):
                if s["f"] < 10:                             # (before the save state loads)
                    continue
                ph = x.phase(s)
                a = x.after(s)
                if ph and a and a["step"] != 12:
                    ap.append((sub, (a["step"], a["sub"]) == (nxt if sub == 6 else (0, 10)) and a["vy"] < 0))
    check("leap: at the top of the jump (vy < 0) the low leap turns into Ceiling shake, the high leap into the Sting pose",
          ap and all(o for _, o in ap), f"{sum(o for _, o in ap)}/{len(ap)}")

    # --- Chameleon Sting ----------------------------------------------------------------------
    vo = []
    for x in alls:
        for c in x.calls("fire_sting", True):
            m = x.at.get(c["f"] + 1)
            ls = [l for l in x.lives("sh") if l[0]["f"] == c["f"] + 1 and l[0]["sub"]]
            subs = sorted(l[0]["sub"] for l in ls)
            if m:
                vo.append((subs, len(subs) == 3 and subs == list(range(subs[0], subs[0] + 3)) and 1 <= subs[0] <= 7
                           and all(l[0]["x"] == m["x"] and l[0]["y"] == m["y"] + 48 for l in ls)
                           and x.called("sound", c["f"] + 1, 0x79)))
    vel = collections.defaultdict(set)
    for x in alls:
        for l in x.lives("sh"):
            if l[0]["sub"] and len(l) > 2:
                vel[l[0]["sub"]].add((l[1]["vx"], l[1]["vy"]))
    check("Chameleon Sting: 3 enemy shots $11 with consecutive sub-ids (k..k+2, k = 1-7 from the angle to X) from his "
          "x, y + 48, sound $79; sub-ids 1-9 are 9 fixed directions at $400 (right, then 22.5° steps down to left)", vo and all(o for _, o in vo)
          and all(len(v) == 1 for v in vel.values()) and all(abs(abs(complex(*sorted(v)[0])) - 0x400) < 3
                                                             for v in vel.values()), f"{len(vo)} volleys, {collections.Counter(s[0] for s, _ in vo if s)}, "
                                                      f"velocities {dict((k, sorted(v)[0]) for k, v in sorted(vel.items()))}")
    ag = []
    for x in alls:
        for c in x.calls("r_again"):
            b, a = x.at.get(c["f"]), x.at.get(c["f"] + 1)
            if a and b and a["state"] == 4 and a["step"] != 12:
                again = c["a"] & 0x0F < 12 and b["f38"] + 1 < 3
                follow = [c2 for c2 in x.calls("r_leap_after") if c2["f"] == c["f"]]
                if again:
                    ag.append((a["step"], a["sub"]) == (8, 2) and not follow)
                else:
                    ag.append(bool(follow) and a["step"] == (0 if follow[0]["a"] & 0x0F < 3 else 2))
    check("Sting: after each volley 32 frames, then random & 15 < 12 -> another (up to 3 volleys, count $38); else "
          "random & 15 < 3 -> leap, otherwise cloak", ag and all(ag), f"{sum(ag)}/{len(ag)}")

    # --- Ceiling shake ------------------------------------------------------------------------
    sh = []
    for x in alls:
        for c in x.calls("r_shake"):
            a = x.at.get(c["f"] + 1)
            if a and a["step"] == 6:
                sh.append(a["f34"] in ((c["a"] & 0x7F) + 60, (c["a"] & 0x7F) + 59))
    spikes = [l for x in alls for l in x.lives("sh") if l[0]["sub"] == 0]
    during = all(x.at.get(l[0]["f"], {}).get("step") in (6, 12) for x in alls for l in x.lives("sh") if l[0]["sub"] == 0)
    check("Ceiling shake: 32 frames, then shakes for (random & 127) + 60 frames, a spike (enemy shot $11, sub-id 0) per "
          "animation keyframe; then 32 frames and cloak", sh and all(sh) and spikes and during
          and all((x.after(s) or {}).get("step") in (2, 12, None) for x in alls for s in x.starts(x.fight(6, 6))),
          f"{sum(sh)}/{len(sh)} shakes, {len(spikes)} spikes")

    # --- cloak --------------------------------------------------------------------------------
    cl = []
    for x in alls:
        for s in x.starts(x.fight(2, 2)):
            ph2 = x.phase(s)
            a = x.after(s)
            if ph2 and a and a["step"] == 2:
                ph4 = x.phase(a)
                if not ph4:                                 # (still fading when the run ended)
                    continue
                b = x.after(a)
                ph6 = x.phase(b) if b else []
                cl.append((countdown(ph2, "f34", 32)[0], len(ph4) in (63, 64, 65), countdown(ph6, "f34", 60)[0] if ph6 else None,
                           s["f37"] == 1 and x.called("sound", s["f"], 0x76)))
    check("cloak: sound $76, cloaked = 1; 32 frames, fades out over 64 frames (one step every other frame), "
          "60 frames, then moves", cl and all(o[0] and o[1] and o[2] is not False and o[3] for o in cl), f"{cl[:3]}")
    gl = []
    for x in alls:
        for c in x.calls("r_glide"):
            a = x.at.get(c["f"] + 1)
            if a and a["step"] == 4:
                gl.append((c["a"] & 0x0F >= 6) == (a["sub"] == 18))
    hops = [s for x in alls for s in x.starts(x.fight(4, 18))]
    check("cloaked: random & 15 ≥ 6 -> hops (vx ±$200, vy = (y − screen top − 128) × 8; up to 3), else glides to a high "
          "corner (screen left + 48 / 208, top + 48)", gl and all(gl) and hops and all(abs(s["vx"]) == 0x200 for s in hops),
          f"{sum(gl)}/{len(gl)}, {len(hops)} hops")
    reach = [x.after(s) for x in alls for s in x.starts(x.fight(4, 12))]
    check("after a hop, X in tongue reach (one of 4 tongue boxes) -> fades in (32 frames) straight into the Tongue",
          reach and all(a is None or a["step"] in (10, 12) for a in reach), f"{len(reach)}")

    # --- Tongue -------------------------------------------------------------------------------
    tg = []
    for x in alls:
        for c in x.calls("r_tongue_after"):
            a = x.at.get(c["f"] + 1)
            if a and a["state"] == 4 and a["step"] != 12:
                tg.append(a["step"] == (2 if c["a"] & 0x0F >= 8 else 0))
    snd = [s for x in alls for s in x.starts(x.fight(10, 2)) + x.starts(x.fight(10, 4)) if x.called("sound", s["f"], 0x7C)]
    # (count $38 is shared with the cloaked hops: the attack's first frame still holds the old value)
    lashes = [max(p["f38"] for p in x.phase(s, ("state", "step"))[1:]) for x in alls for s in x.starts(x.fight(10))
              if len(x.phase(s, ("state", "step"))) > 1]
    check("Tongue: sound $7C, up to 3 lashes while X stays in reach (count $38); from a wall, then random & 15 ≥ 8 -> "
          "cloak, else leap; on the floor, leap", tg and all(tg) and snd and lashes and max(lashes) <= 3,
          f"{sum(tg)}/{len(tg)}, lashes {collections.Counter(lashes)}")

    # --- hits ---------------------------------------------------------------------------------
    hb = [t["n3"], t["cutter"]]
    lhs = {}
    for x in hb:
        lhs[id(x)] = {e["f"]: e["v"] for e in x.by_tag["last_hit"]}
    hits = [(x, a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if a["state"] == c["state"] == 4
            and (c["hp"] & 0x7F) < (a["hp"] & 0x7F) and c["f"] > 10]
    bh = [(x, a, c) for x, a, c in hits if x is t["n3"]]
    check("buster hit: −1 HP (row 6), sound $13, invuln_timer ($33) 60; no knockback", bh and all(
        (a["hp"] - c["hp"]) & 0x7F == row[0] and c["f33"] in (59, 60) and x.called("sound", c["f"], 0x13)
        and c["step"] != 12 for x, a, c in bh), f"{len(bh)} hits")
    ch = [(x, a, c) for x, a, c in hits if x is t["cutter"]]
    kb = [x.at.get(c["f"] + 1, c) for x, a, c in ch if c["step"] == 12]
    check("Boomerang Cutter (projectile $0D, his weakness): damage from row 6 and knockback (step 12: vx $100 away, "
          "vy $200, gravity 64), then a leap when he lands", ch and all((a["hp"] - c["hp"]) & 0x7F == row[0x0D] or
                                                                         c["hp"] & 0x7F == 0 for x, a, c in ch)
          and kb and all(abs(k["vx"]) == 0x100 and k["grav"] == 64 for k in kb),
          f"{len(ch)} hits, row6[$0D] = {row[0x0D]}, {len(kb)} knockbacks")
    inv = [c for x in hb for a, c in zip(x.p, x.p[1:]) if 0 < c["f33"] == a["f33"] - 1 and c["f33"] & 3 == 0 and not c["f37"]]
    rest = [(a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if a["f33"] > 1 and c["hp"] & 0x7F < a["hp"] & 0x7F]
    check("invulnerable: no HP lost; he flashes (palette bits cleared when the timer is a multiple of 4)",
          not rest and inv and all(c["attr"] & 0x0E == 0 for c in inv), f"{len(inv)} flash frames")

    # --- death --------------------------------------------------------------------------------
    de = t["death"]
    six = de.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, death anim 21, uncloaked, sound $13, boss_defeated, boss_defeated_sequence, despawn",
          six and de.called("anim", six[0]["f"], 21) and six[0]["f37"] == 0 and de.by_tag["boss_defeated"]
          and len(de.calls("defeat_seq")) > 300 and any("gone" in e for e in de.by_tag["sc"]))
    xd = t["x_dies"]
    died = [e for e in xd.by_tag["X"] if e["hp"] & 0x7F == 0 and e["f"] > 10]
    back = next((e["f"] for e in xd.by_tag["X"] if died and e["f"] > died[0]["f"] and e["hp"] & 0x7F), 10 ** 9)
    nohit = [c for c in xd.calls("hit_check") if died and died[0]["f"] + 1 < c["f"] < back]   # (until the stage restarts)
    check("X at 0 HP: he stops checking for hits", died and not nohit, f"X at 0 HP from frame {died[0]['f'] if died else None}")

    # --- values -------------------------------------------------------------------------------
    v = t["v_hit"]
    check("value max_hp = 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f33"] for e in v.p) in (31, 32))
    v = t["v_times"]
    fo = [len(v.phase(s)) for s in v.starts(v.fight(2, 4)) if v.phase(s)]
    w6 = [countdown(v.phase(s), "f34", 0x20)[0] for s in v.starts(v.fight(2, 6)) if v.phase(s)]
    sk = [a["f34"] - (c["a"] & 0x7F) for c in v.calls("r_shake") for a in [v.at.get(c["f"] + 1)] if a]
    check("values cloak_fade = $10 (32 frames), cloak_wait = $20, spike_wait = $14", fo and all(k in (31, 32, 33) for k in fo)
          and w6 and all(w6) and sk and set(sk) <= {0x14, 0x13}, f"fade {collections.Counter(fo)}, shake base {collections.Counter(sk)}")
    v = t["v_counts"]
    vol = [max(p["f38"] for p in v.phase(s, ("state", "step"))[1:]) for s in v.starts(v.fight(8))
           if len(v.phase(s, ("state", "step"))) > 1]
    tl = [max(p["f38"] for p in v.phase(s, ("state", "step"))[1:]) for s in v.starts(v.fight(10))
          if len(v.phase(s, ("state", "step"))) > 1]
    check("values sting_volleys = 1, tongue_lashes = 1 -> one volley, one lash", vol and max(vol) <= 1
          and (not tl or max(tl) <= 1), f"volleys {collections.Counter(vol)}, lashes {collections.Counter(tl)}")

    report(results)


if __name__ == "__main__":
    main()
