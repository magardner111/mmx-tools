"""
Re-checks everything we claim about Armored Armadillo by running the game in Mesen (see mesen_verify.py).

    python3 verify_armored_armadillo.py          # about 15 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_armored_armadillo.py --cached # re-check the last run's saved output

His boss checkpoint (2, x=4992) is left of his door; X walks right through it and drops into the room
(x 5120-5376) at x 5147, and his intro starts without waiting for X. The suite plays that once and saves a state
at the first frame of the fight (work/states/armored_armadillo_fight.mss); most runs start from it. Runs that
check the intro or max HP play it in full. X takes no damage (AR code) unless a test needs him hurt.
Hooks on his instructions (Run.at_exec) set things up exactly: his first choice is re-run 48 times within one
frame (back to $83B630 from $83B670), each time with the repeat counter cleared ($83B632) and a chosen roll and
distance ($83B647, $83B658), so every table entry is tried; the random rolls deciding wall bounces, guards and
shot counts are logged where he reads them.
"""
import collections
import json
import sys

import params as P
from defs import ARMORED_ARMADILLO as AA, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state, countdown, shot_log, X_LOG, Fight, report

ID, SHOT = 0x14, 0x04
CACHE = "work/armored_armadillo_runs.json"
STATE = "work/states/armored_armadillo_fight.mss"
PAR = {p.key: p for p in AA.params}
TABLE = AA.attack_tables[0].addr            # 3 rows of 16 at $86:C980 (< 80, 80-127, >= 128 px)
SHOTS_TABLE = 0x86C970                      # energy shot counts, 16 entries
EXECS = {0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze", 0x84AADD: "beaten",
         0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound", 0x828358: "alloc_shot",
         0x8282D3: "alloc_effect", 0x84A677: "defeat_seq", 0x849B43: "hit_check", 0x849B03: "hurt_x",
         0x84ACA5: "face_x", 0x8281E8: "move_grav", 0x8491BE: "terrain", 0x84A338: "shake", 0x84A316: "quake",
         0x83B647: "r_pick", 0x83B6B0: "r_shots", 0x83B4CD: "r_wall", 0x83B524: "r_floor", 0x83BA9F: "r_guard",
         0x83BACA: "spawn_armor_piece", 0x83BB38: "spawn_debris"}
M = f"find(0x0E68, 0x1228, {ID})"
LEFT, MID, NEAR = 5170, 5240, 5290
WALK_IN = f"return {{right = r16(0x0BAD) < {LEFT}}}"


def hold(x, fire=False, extra=""):
    return (("fire = true\n" if fire else "") + extra + f"""local xx = r16(0x0BAD)
return {{right = xx < {x - 3}, left = xx > {x + 3}, y = fire and frame % 16 < 8}}""")


HOLD = hold(LEFT)
FIRE = hold(LEFT, True)
NO_DAMAGE = f"do local m = {M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
SET_HP1 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); hpset = true end end"
SPARK = "w16(0x1F91, 0xDC00); w8(0x0BDB, 12)"     # own Electric Spark with ammo, and select it
# charge the buster and let go when he is choosing (the charged shot makes him guard, then hits the guard)
CHARGE = f"""local m = {M}
local g = m and r8(m + 1) == 4 and r8(m + 2) == 4 and r8(m + 3) == 2
if g and not was then let_go = 3 end
was = g
local xx = r16(0x0BAD)
if let_go and let_go > 0 then let_go = let_go - 1; return {{right = xx < {MID - 3}, left = xx > {MID + 3}}} end
return {{right = xx < {MID - 3}, left = xx > {MID + 3}, y = true}}"""
ROWS = [(40, 0), (79, 0), (80, 1), (127, 1), (128, 2), (160, 2)]     # (distance given, row it must use)


def table(g, addr, n):
    b = snes2pc(addr)
    return list(g.rom[b:b + n])


def exhaust():
    """Hooks: on his first choice, re-run it 48 times in that frame (repeats cleared, each row at both edges of its
    distance band, every column), logging each pick at $83B670 (A = the entry read)."""
    lua = "{" + ", ".join(f"{{{ROWS[2 * r + c % 2][0]}, {c}}}" for r in range(3) for c in range(16)) + "}"
    # (the exec hook at $83B630 doesn't fire again when the PC is set back to it, so the loop hook advances)
    return [(0x83B630, f'if not aa_done and not aa_cur then aa_c = {lua}; aa_n = 1; aa_cur = aa_c[1] end'),
            (0x83B632, 'if aa_cur then w8(s["cpu.d"] + 0x32, 0) end'),
            (0x83B647, 'if aa_cur then setreg("cpu.a", (s["cpu.a"] & 0xFF00) | aa_cur[2]) end'),
            (0x83B658, 'if aa_cur then setreg("cpu.a", aa_cur[1]) end'),
            (0x83B670, 'if aa_cur then out("force", "dist=" .. aa_cur[1] .. " col=" .. aa_cur[2] .. " step=" .. '
                       '(s["cpu.a"] & 0xFF)); if aa_n < #aa_c then aa_n = aa_n + 1; aa_cur = aa_c[aa_n]; '
                       'setreg("cpu.pc", 0xB630) else aa_done = true; '
                       'aa_cur = nil end end')]


def only(attack, **values):
    """ROM patch: every table entry = attack (0 Rolling, 2 Energy shots), plus values."""
    def f(g):
        b = snes2pc(TABLE)
        for i in range(48):
            g.rom[b + i] = attack
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def values(**v):
    return lambda g: [P.put(g, PAR[k], x) for k, x in v.items()]


def run(frames, inp=HOLD, seed=None, inf=True, ar=True, patch=None, extra=(), hooks=(), full=False):
    r = Run(level=3, x=4992, frames=frames, seed=seed, infinite_hp=inf, patch=patch, savestate=None if full else STATE)
    r.track(ID, tag="aa")
    for a, t in EXECS.items():
        r.on_exec(a, t)
    for a, lua in hooks:
        r.at_exec(a, lua)
    r.at_exec(0x83BAE1, 'out("piece", "sub=" .. (s["cpu.a"] & 0xFF))')       # armor piece's sub-id as it is written
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.on_write(0x1F0E, "hud_boss")
    r.input(inp)
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame(X_LOG)
    r.each_frame(shot_log("sh", [SHOT]))
    r.each_frame(shot_log("xs", range(0x30), 0x1228, 0x1428))
    r.each_frame(shot_log("fx", [0x10, 0x22, 0x2B], 0x1928, 0x1D28))
    for lua in extra:
        r.each_frame(lua)
    return r


def main():
    g0 = MMX1("work/hack.sfc")
    tab = table(g0, TABLE, 48)
    counts = table(g0, SHOTS_TABLE, 16)
    natural = [("n0", 0x1111, hold(LEFT)), ("n1", 0x2345, hold(MID)), ("n2", 0x3C3C, hold(NEAR)),
               ("n3", 0x4A21, hold(LEFT, True))]
    runs = {k: run(5000, inp, seed=s) for k, s, inp in natural}
    runs.update({
        "intro": run(1300, WALK_IN, seed=0x1234, full=True),
        "table": run(900, seed=0x1001, hooks=exhaust()),
        "rolling": run(5000, seed=0x2001, patch=only(0)),
        "energy": run(3000, seed=0x2002, patch=only(2)),
        "guard": run(4000, FIRE, seed=0x2003, patch=only(2)),
        "counter": run(4000, CHARGE, seed=0x2004),
        "spark": run(5000, hold(LEFT, True, SPARK + "\n"), seed=0x2005),
        "buster": run(3000, hold(MID, True), seed=0x2006),
        "death": run(1500, FIRE, seed=0x2007, extra=[SET_HP1]),
        "x_dies": run(3000, hold(MID), seed=0x2008, inf=False, ar=False),
        "v_hit": run(2600, FIRE, seed=0x3001, full=True, patch=values(max_hp=20, invuln_time=0x20)),
        "v_times": run(3000, FIRE, seed=0x3002, patch=values(think_time=0x10, guard_time=0x0C)),
        "v_roll": run(3000, seed=0x3003, patch=only(0, roll_speed=0x400, roll_jump=0x400)),
        "v_armor": run(3000, FIRE, seed=0x3004, patch=values(armor_a=0x00, armor_invuln=0x40)),
        "v_counter": run(3000, FIRE, seed=0x3005, patch=values(counter_c=0x00)),
    })
    if "--cached" in sys.argv:
        out = json.load(open(CACHE))
    else:
        print("playing to the start of the fight...", flush=True)
        fight_state(STATE, 3, 4992, WALK_IN, f"(function() local m = {M}; return m and r8(m + 1) == 4 end)()")
        print(f"running {len(runs)} emulator sessions...", flush=True)
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    t = {k: Fight(v, "aa") for k, v in out.items()}
    nat = [t[k] for k, _, _ in natural]
    alls = [x for k, x in t.items() if not k.startswith("v_")]
    unforced = [x for k, x in t.items() if not k.startswith(("v_", "table"))]
    dt = snes2pc(DAMAGE_TABLE)
    row = g0.rom[dt + g0.w(dt + 2 * AA.damage_class):][:32]
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # --- intro -------------------------------------------------------------------------------
    n = t["intro"]
    init = n.starts(lambda e: e["state"] == 0 and e["step"] == 1)[0]
    check("init: boss_already_beaten, x_freeze_for_boss, screen_shake(60), jingle $2E",
          n.calls("beaten") and n.calls("x_freeze", False) and n.called("shake", init["f"], 60)
          and any(c["a"] & 0xFF == 0x2E for c in n.calls("music", False)))
    ok, a, b = countdown(n.phase(init), "f34", 60)
    check("init: 60-frame wait (timer $34, 60..1)", ok, f"{a}..{b}")
    st2 = n.starts(lambda e: e["state"] == 2)[0]
    rocks = [l for l in n.lives("fx") if st2["f"] - 1 <= l[0]["f"] <= st2["f"]]
    check("obj_start: palette_bits ($35) = attr & $0E, gravity 64; spawn_debris 4 times at his x ± 8, y / y + 8",
          st2["f35"] == st2["attr"] & 0x0E and st2["grav"] == 64 and len(n.calls("spawn_debris")) >= 4,
          f"{len(n.calls('spawn_debris'))} calls, {collections.Counter(l[0]['id'] for l in rocks)} effects")
    b1 = n.starts(lambda e: e["state"] == 2 and e["step"] == 2)
    pre = n.at.get(b1[0]["f"] - 1) if b1 else None
    check("intro: falls in, and the first landing bounces him up at half the speed (vy = −vy / 2)",
          b1 and pre and abs(b1[0]["vy"] - (-(pre["vy"] - 64)) // 2) <= 40, f"{pre and pre['vy']} -> {b1 and b1[0]['vy']}")
    b2 = n.starts(lambda e: e["state"] == 2 and e["step"] == 4)
    check("intro: second landing -> screen_shake(8)", b2 and n.called("shake", b2[0]["f"], 8))
    ticks = [c["f"] for c in n.calls("sound_c") if n.at.get(c["f"] + 1, {}).get("state") == 2]
    check("HP fill: +1 every 2 frames to 32, boss bar (hud_boss) set", len(ticks) == 32
          and set(b - a for a, b in zip(ticks, ticks[1:])) == {2} and n.by_tag["hud_boss"], f"{len(ticks)} ticks")
    s8 = n.starts(lambda e: e["state"] == 2 and e["step"] == 8)[0]
    ok, a, b = countdown(n.phase(s8), "f34", 10)
    nx = n.after(s8)
    check("end of intro: 10 frames, x_unfreeze, music $1E, state 4 starting with the Rolling attack "
          "(last_attack 0, repeats 1)", ok and nx and (nx["state"], nx["step"], nx["f31"], nx["f32"]) == (4, 0, 0, 1)
          and n.calls("x_unfreeze", False) and any(c["a"] & 0xFF == 0x1E for c in n.calls("music", False)), f"{a}..{b}")
    live = [x for k, x in t.items() if not k.startswith("v_") and k != "x_dies"]     # (X dying restarts the stage)
    first = {id(x): next((e["f"] for e in x.p if e["state"] == 4 and e["dmg"] != 3), 0) for x in live}
    dm = collections.Counter((e["f37"] & 0x81 != 0, e["f33"] != 0, e["dmg"]) for x in live for e in x.p
                             if e["state"] == 4 and e["f"] >= first[id(x)])
    check("damage class: 11, but 0 (shots bounce off) while guarding (guard bit 0) or curled up (bit 7) with "
          "his armor on", dm and all(d == (0 if g and not off else 11) for (g, off, d) in dm), f"{dict(dm)}")

    # --- Rolling attack -----------------------------------------------------------------------
    ro = [t["rolling"], *nat]
    jumps = [s for x in ro for s in x.starts(x.fight(0, 2))]
    check("Rolling: jumps with vy $506 (vx 0)", jumps and all(s["vy"] == 0x506 and s["vx"] == 0 for s in jumps),
          f"{len(jumps)} jumps")
    curls = [s for x in ro for s in x.starts(x.fight(0, 4))]
    check("Rolling: curls up when the jump animation ends (guard bit 7)", curls and all(s["f37"] & 0x80 for s in curls))
    bnc = []
    for x in ro:
        for s in x.starts(x.fight(0, 6)):
            b = x.at.get(s["f"] - 1)
            if b:
                bnc.append(s["vy"] == -(b["vy"] - 64))
    check("Rolling: bounces once on landing (vy = −vy)", bnc and all(bnc), f"{sum(bnc)}/{len(bnc)}")
    rolls = [(s, x.x.get(s["f"])) for x in ro for s in x.starts(x.fight(0, 8))]
    check("Rolling: lands again and rolls at ±$600 toward the side he faces", rolls and all(
        abs(s["vx"]) == 0x600 and (s["vx"] > 0) == bool(s["attr"] & 0x40) for s, _ in rolls), f"{len(rolls)} rolls")
    wall, wq = [], []
    for x in ro:
        rw = {c["f"]: c["a"] & 0x0F for c in x.calls("r_wall")}
        for f, v in rw.items():
            a = x.at.get(f + 1)
            b = x.at.get(f)
            if a and b:
                if v >= 6:
                    wall.append(a["sub"] == 10 and abs(a["vx"]) == 0x43B and a["vy"] == 0x43B
                                and (a["vx"] > 0) != (b["vx"] > 0) and x.called("quake", f + 1, 8)
                                and x.called("sound", f + 1, 0x48))
                else:
                    wall.append(a["sub"] == 12 and abs(a["vx"]) == 0x100 and (a["vx"] > 0) != (b["vx"] > 0)
                                and a["vy"] == 0x506 and not a["f37"] & 0x80)
                wq.append(v >= 6)
    check("Rolling: at a wall (sound $48, rocks): random & 15 ≥ 6 -> screen_quake(8) and bounces away at $43B "
          "both ways; else hops off it (vx $100 away, vy $506) and uncurls", wall and all(wall) and any(wq)
          and not all(wq), f"{sum(wall)}/{len(wall)}, {sum(wq)} bounces")
    fl = []
    for x in ro:
        for c in x.calls("r_floor"):
            a = x.at.get(c["f"] + 1)
            if a:
                fl.append((c["a"] & 0x0F < 6) == (a["sub"] == 12))
    walls = sum(1 for x in ro for a, b in zip(x.p, x.p[1:]) if a["step"] == 0 and a["sub"] == b["sub"] == 10
                and (a["vx"] > 0) != (b["vx"] > 0))
    check("Rolling (bouncing): touching the floor with random & 15 < 6 -> hops (as above); walls flip vx "
          "(screen_quake(8)), floor and ceiling flip vy (screen_shake(8))", fl and all(fl) and walls,
          f"{sum(fl)}/{len(fl)} floor rolls, {walls} wall bounces")
    ends = [s for x in ro for s in x.starts(x.fight(0, 14))]
    after = [x.after(s) for x in ro for s in x.starts(x.fight(0, 14))]
    check("Rolling: lands (pose), then back to choosing (step 4)", ends and all(a and a["step"] == 4 for a in after if a))

    # --- choosing -----------------------------------------------------------------------------
    th = [countdown(x.phase(s), "f34", 30) for x in unforced for s in x.starts(x.fight(4, 2))
          if s["f34"] == 30 and x.phase(s) and x.after(s) and x.after(s)["state"] == 4
          and x.after(s)["step"] in (0, 2)]
    check("choosing: waits 30 frames (timer $34) facing X, unless he guards", th and all(o for o, _, _ in th),
          f"{len(th)} waits")
    done, ok = set(), []
    x = t["table"]
    for fo in x.by_tag["force"]:
        r_ = next(r for d, r in ROWS if d == fo["dist"])
        ok.append(fo["step"] == tab[r_ * 16 + fo["col"]])
        done.add((r_, fo["col"]))
    last = x.by_tag["force"][-1] if x.by_tag["force"] else None
    nx = x.at.get(last["f"] + 1) if last else None
    check("attack choice (all 48 entries, re-run within one frame): row = X's distance (< 80, 80-127, ≥ 128; tried "
          "at 40/79, 80/127, 128/160), column = random & 15; the attack is the entry at $86:C980",
          ok and all(ok) and len(done) == 48 and len({fo["f"] for fo in x.by_tag["force"]}) == 1
          and nx and nx["state"] == 4 and nx["step"] == last["step"], f"{sum(ok)}/{len(ok)}, {len(done)}/48 entries")
    seq_ok, forced = [], 0
    for x in unforced:
        for c in x.calls("r_pick"):
            b = x.at.get(c["f"])
            a = x.at.get(c["f"] + 1)
            if a and b:
                seq_ok.append(b["f32"] < 2)
        for s in x.starts(x.fight(4, 2)):
            a = x.after(s)
            if a and a["state"] == 4 and s["f32"] >= 2 and a["step"] not in (4, 6, 8):
                forced += 1
                seq_ok.append(a["step"] == s["f31"] ^ 2 and a["f32"] == s["f32"] - 1)
    check("repeat limit: after the same attack twice (repeats = 2) he does the other one (no roll)",
          seq_ok and all(seq_ok) and forced, f"{forced} forced switches")
    pats = []
    for k in ("rolling", "energy"):
        x = t[k]
        seq = [x.after(s)["step"] for s in x.starts(x.fight(4, 2)) if x.after(s) and x.after(s)["state"] == 4]
        pats.append((k, "".join("RE"[v // 2] for v in seq)))
    check("a table of only one attack: that attack twice, then the other once (no freeze)",
          pats[0][1] and "RRR" not in pats[0][1] and "RRE" in pats[0][1] and "EEE" not in pats[1][1] and "EER" in pats[1][1],
          f"{pats}")
    cols = collections.Counter(c["a"] & 0x0F for x in unforced for c in x.calls("r_pick"))

    # --- Energy shots -------------------------------------------------------------------------
    en = [t["energy"], t["n0"], t["n1"], t["n2"]]       # (X not shooting: no guards in between)
    sl = []
    for x in en:
        for c in x.calls("r_shots"):
            a = x.at.get(c["f"] + 1)
            if a:
                sl.append(a["f36"] == counts[c["a"] & 0x0F])
    check("Energy shots: shots_left ($36) = $86:C970[random & 15] (3, 4 or 5)", sl and all(sl), f"{sum(sl)}/{len(sl)}")
    sp = []
    for x in en:
        for l in x.lives("sh"):
            if l[0]["sub"] != 0:
                continue
            m = x.at.get(l[0]["f"])
            v = next((s["vx"] for s in l[1:] if s["vx"]), None)
            if m:
                sp.append((l[0]["x"] - m["x"], l[0]["y"] - m["y"], bool(m["attr"] & 0x40), v,
                           x.called("sound", l[0]["f"], 0x33)))
    check("Energy shots: each shot = enemy shot $04 (sub 0) at his x ± 15 (facing), y − 14, vx ±$300, sound $33",
          sp and all(abs(dx) == 15 and (dx > 0) == fr and dy == -14 and v == (0x300 if fr else -0x300) and snd
                     for dx, dy, fr, v, snd in sp), f"{len(sp)} shots, {sp[:2]}")
    fired = []
    for x in en:
        for s in x.starts(x.fight(2, 2)):
            ph = x.phase(s, ("state", "step"))
            if ph and s["f36"] and x.at.get(s["f"] - 1, {}).get("sub") == 0:
                nshots = len([l for l in x.lives("sh") if ph[0]["f"] <= l[0]["f"] <= ph[-1]["f"] + 1 and l[0]["sub"] == 0])
                fired.append((s["f36"], nshots, x.after(ph[-1]) and x.at.get(ph[-1]["f"] + 1, {}).get("step")))
    full = [f_ for f_ in fired if f_[0] in (3, 4, 5)]
    check("Energy shots: fires until shots_left = 0, then back to choosing", full and all(k == m and nx_ == 4
          for k, m, nx_ in full if nx_ is not None), f"{collections.Counter((a, b) for a, b, _ in full)}")

    # --- guard --------------------------------------------------------------------------------
    gu = [t["guard"], t["n3"], t["buster"]]
    gd = []
    for x in gu:
        for c in x.calls("r_guard"):
            a = x.at.get(c["f"] + 1)
            if a and a["state"] == 4:
                gd.append((c["a"] & 0x0F >= 4) == bool(a["f37"] & 1))
    marks = []
    for x in gu:
        for l in x.lives("xs"):
            m = next((s for s in l if s["f2C"]), None)
            if m:
                b = x.at.get(m["f"])
                if b:
                    marks.append((abs(m["x"] - b["x"]) < 96 and abs(m["y"] - b["y"]) < 36))
    check("guard: an X shot within 80 px (its front edge) and 36 px up/down is noticed once (shot field $2C); "
          "random & 15 ≥ 4 -> he guards (12 in 16)", gd and all(gd) and marks and all(marks),
          f"{sum(gd)}/{len(gd)} rolls, {sum(marks)}/{len(marks)} shots in range")
    gp = []
    for x in gu:
        for s in x.starts(lambda e: e["state"] == 4 and e["f37"] & 1 and e["step"] in (2, 4)):
            ph = x.phase(s, ("state", "step", "sub"))
            nx = x.after(s)
            if ph and nx and nx["step"] in (6, 8):
                gp.append("hit")
            elif ph:
                v = [p["f3B"] for p in ph]
                cut = any(a - b > 1 and b == 1 for a, b in zip(v, v[1:]))
                steady = all(a - b in (0, 1) for a, b in zip(v, v[1:]))
                gp.append("?" if v[0] != 30 or v[-1] != 1 else "deflect" if cut else "full" if steady else "?")
    check("guard: guard_timer ($3B) 30 frames, cut short (to 1) by a shot bouncing off it (or a hit / counter)",
          gp and "?" not in gp and "full" in gp and "deflect" in gp, f"{collections.Counter(gp)}")
    hd = [(a, c) for x in gu for a, c in zip(x.p, x.p[1:]) if a["state"] == 4 and a["dmg"] == 0
          and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    defl = sum(1 for x in gu for a, c in zip(x.p, x.p[1:]) if c["f3C"] > a["f3C"])
    check("guarding / curled: buster shots bounce off (no HP lost), each pushing him back 2 px ($3C += 2)",
          not hd and defl, f"{defl} deflections")
    eg = [s for x in gu for s in x.starts(x.fight(2, 4))]
    res = [x.after(s) for x in gu for s in x.starts(x.fight(2, 4))]
    check("guard during Energy shots: step 2/4, then the remaining shots (or back to choosing if none)", eg and all(
        a is None or (a["step"], a["sub"]) in ((2, 2), (4, 0), (8, 0), (6, 0)) for a in res), f"{len(eg)} guards")

    # --- counter -------------------------------------------------------------------------------
    co = t["counter"]
    cs = co.starts(co.fight(6, 2))
    lh = {e["f"]: e["v"] for e in co.by_tag["last_hit"]}
    check("charged buster (projectile 1, 2 or 3) into his guard -> counter: sound $4E, guard = $80",
          cs and all(s["f37"] == 0x80 and co.called("sound", s["f"], 0x4E) for s in cs),
          f"{len(cs)} counters, shots {sorted({v for v in lh.values() if v})}")
    vol = []
    for s in cs:
        ph = co.phase(s)
        if ph:
            ls = [l for l in co.lives("sh") if ph[-1]["f"] <= l[0]["f"] <= ph[-1]["f"] + 1]
            vol.append((sorted(l[0]["sub"] for l in ls), all(l[0]["x"] == ph[-1]["x"] and l[0]["y"] == ph[-1]["y"]
                                                              for l in ls)))
    vel = sorted({(l[0]["sub"], next((s["vx"] for s in l[1:] if s["vx"] or s["vy"]), 0),
                   next((s["vy"] for s in l[1:] if s["vx"] or s["vy"]), 0)) for l in co.lives("sh") if l[0]["sub"]})
    check("counter: when the animation ends, 8 enemy shots $04 (sub-ids 1-8) from his position, sound $02",
          vol and all(v == (list(range(1, 9)), True) for v in vol), f"{vol[:2]}; velocities {vel[:8]}")
    tm = co.timers(6, 4, "f34", 30)
    check("counter: then 30 frames and back to choosing", tm and all(o for o, _, _ in tm), f"{len(tm)}")

    # --- getting hit --------------------------------------------------------------------------
    hb = [t["buster"], t["n3"], t["guard"]]
    hits = [(x, a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: −1 HP (damage row 11), sound $13, invuln_timer ($38) = 60", hits and all(
        (a["hp"] - c["hp"]) & 0x7F == row[0] and c["f38"] in (59, 60) and x.called("sound", c["f"], 0x13)
        for x, a, c in hits), f"{len(hits)} hits")
    kb, kb_roll = [], []
    for x, a, c in hits:
        if (a["step"], a["sub"] >= 12) != (0, False):
            kb.append(c["step"] == 8 and abs(x.at.get(c["f"] + 1, c)["vx"]) == 0x100)
        else:
            kb_roll.append(c["step"] == 0)
    check("hit: knocked back (step 8: vx $100 away, vy $100) unless mid-roll (rolling substeps below 12)",
          kb and all(kb) and all(kb_roll), f"{sum(kb)}/{len(kb)} knockbacks, {len(kb_roll)} mid-roll hits")
    rs = []
    for x in hb:
        for s in x.starts(x.fight(8, 6)):
            ph = x.phase(s)
            a = x.after(s)
            if ph and a:
                rs.append((s["f36"] > 0) == ((a["step"], a["sub"]) == (2, 2)))
    check("knockback: slides 20 frames (timer $3A), then resumes the energy shots if any are left, else choosing",
          rs and all(rs), f"{sum(rs)}/{len(rs)}")
    inv = [(a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if 0 < c["f38"] == a["f38"] - 1 and c["f38"] & 4
           and c["step"] != 8]
    rest = [(a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if a["f38"] > 1 and c["hp"] & 0x7F < a["hp"] & 0x7F]
    check("invulnerable: hits while invuln_timer runs don't take HP; he flashes (palette bits cleared when bit 2 is set)",
          not rest and inv and all(c["attr"] & 0x0E == 0 for a, c in inv), f"{len(inv)} flash frames")

    # --- Electric Spark / armor ---------------------------------------------------------------
    sx = t["spark"]
    lhs = {e["f"]: e["v"] for e in sx.by_tag["last_hit"]}
    br = sx.starts(sx.fight(8, 8))
    check("Electric Spark (projectile $0C) with his armor on -> stagger: invuln_timer 180",
          br and all(sx.at.get(s["f"] - 1, {}).get("f38") in (179, 180) for s in br),
          f"{len(br)} breaks, shots {sorted({v for v in lhs.values() if v})}")
    st = [[p["f3A"] for p in sx.phase(s)] for s in br]
    s12 = sx.starts(sx.fight(8, 12))
    fallw = [[p["f3A"] for p in sx.phase(s) + sx.phase(sx.after(s) or s)] for s in sx.starts(sx.fight(8, 10))]
    check("stagger: 90 frames (timer $3A 90..0), then falls; the pieces come off when the timer, reset to 20, "
          "reaches 0 (it keeps counting while he falls)",
          st and all(v[0] == 90 and v[-1] == 0 and all(a - b in (0, 1) for a, b in zip(v, v[1:])) for v in st)
          and fallw and all(v[0] == 19 and v[-1] == 0 and all(a - b in (0, 1) for a, b in zip(v, v[1:])) for v in fallw),
          f"{[(v[0], v[-1], len(v)) for v in st]}, fall + wait {[(v[0], v[-1]) for v in fallw]}")
    pieces = []
    for s in s12:
        a = sx.after(s)
        if a:
            subs = [e["sub"] for e in sx.by_tag["piece"] if e["f"] == a["f"] - 1]
            pieces.append((subs, a["f33"], a["step"]))
    check("armor off: armor pieces (effect $2B, sub-ids 34 down to 30, as many as there are free effect slots), "
          "armor_off ($33) = 1, back to choosing", pieces and all(p[0] and p[0] == list(range(34, 34 - len(p[0]), -1))
                                                                  and p[1:] == (1, 4) for p in pieces), f"{pieces}")
    off = [e for e in sx.p if e["f33"]]
    check("armor off: he never guards again (incoming_shot returns 0)", off and not any(e["f37"] & 1 for e in off),
          f"{len(off)} frames")
    curled = [e for e in off if e["f37"] & 0x80]
    check("armor off: curled up he can be hurt (damage class 11)", curled and all(e["dmg"] == 11 for e in curled
                                                                                 if sx.at.get(e["f"] - 1, {}).get("f37", 0) & 0x80),
          f"{len(curled)} frames")
    sh = [(a, c) for a, c in zip(sx.p, sx.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    ids = collections.Counter(lhs.get(c["f"] - 1, lhs.get(c["f"])) for a, c in sh)
    check("Electric Spark (his weakness): damage from row 11", sh and all((a["hp"] - c["hp"]) & 0x7F == row[0x0C]
          or c["hp"] & 0x7F == 0 for a, c in sh), f"{collections.Counter((a['hp'] - c['hp']) & 0x7F for a, c in sh)}, "
                                                   f"row11[$0C] = {row[0x0C]}")

    # --- death / X ----------------------------------------------------------------------------
    de = t["death"]
    six = de.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, X_hurt_lock = 1, boss_defeated = 1, boss_defeated_sequence, then he despawns",
          six and de.by_tag["boss_defeated"] and any(e["v"] == 1 for e in de.by_tag["X_hurt_lock"])
          and len(de.calls("defeat_seq")) > 300 and any("gone" in e for e in de.by_tag["aa"]))
    xd = t["x_dies"]
    died = [e for e in xd.by_tag["X"] if e["hp"] & 0x7F == 0 and e["f"] > 10]      # (frame 1: before the state loads)
    check("x_dead ($30) = 1 once X's HP is 0", died and any(e["f30"] == 1 for e in xd.p if e["f"] >= died[0]["f"]),
          f"X at 0 HP from frame {died[0]['f'] if died else None}")
    check("hit_check and hurt_x_on_contact run in every attack",
          all(x.calls("hit_check") for x in nat) and all(x.calls("hurt_x") for x in nat))

    # --- values -------------------------------------------------------------------------------
    v = t["v_hit"]
    check("value max_hp = 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f38"] for e in v.p) in (31, 32))
    v = t["v_times"]
    th = v.timers(4, 2, "f34", 0x10)
    gv = [(s["step"], p["f3B"]) for s in v.starts(lambda e: e["state"] == 4 and e["step"] in (2, 4) and e["sub"] == 4)
          for p in v.phase(s)[:1]]
    check("values think_time = $10, guard_time = $0C (both guards: choosing and Energy shots)",
          th and any(o for o, _, _ in th) and {g for _, g in gv} == {0x0C} and {st for st, _ in gv} == {2, 4},
          f"{th[:3]}, guard {collections.Counter(gv)}")
    v = t["v_roll"]
    check("values roll_speed = $400, roll_jump = $400", any(abs(s["vx"]) == 0x400 for s in v.starts(v.fight(0, 8)))
          and all(s["vy"] == 0x400 for s in v.starts(v.fight(0, 2))))
    v = t["v_armor"]
    vb = v.starts(v.fight(8, 2)) + v.starts(v.fight(8, 8))
    check("values armor_a = 0 (X-Buster), armor_invuln = $40 -> buster hits stagger him with invuln 64; shorter than "
          "the 90-frame stagger, so each new hit restarts it and the armor never comes off",
          vb and all(e["f38"] in (63, 64) for e in vb if e["sub"] == 2) and not any(e["f33"] for e in v.p),
          f"{len(v.starts(v.fight(8, 2)))} staggers")
    v = t["v_counter"]
    check("value counter_c = 0 -> a plain buster shot into his guard makes him counter", v.starts(v.fight(6, 2)))

    report(results)


if __name__ == "__main__":
    main()
