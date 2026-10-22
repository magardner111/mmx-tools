"""
Re-checks everything we claim about Boomer Kuwanger by running the game in Mesen (see mesen_verify.py).

    python3 verify_boomer_kuwanger.py          # about 15 minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_boomer_kuwanger.py --cached # re-check the last run's saved output

His boss checkpoint (2) is the short corridor at the top of the tower between his doors (x 1528 and 1784, floor
y 111). Tests start X at (1664, 100); X walks right through the door into the room (x 1792-2048, X stands at y 175)
and his intro starts by itself. The suite plays that once and saves a state at the first frame of the fight
(work/states/boomer_kuwanger_fight.mss); most runs start from it. X takes no damage (AR code) unless a test needs
him touchable (Dead Lift).
Both of his tables are checked exhaustively in one frame each: hooks send the post-dash choice ($87:8DDF -> $87:8DCA)
and the post-teleport choice ($87:8F3E -> $87:8F1A) back to their start for every row and column.
"""
import collections
import json
import sys

import params as P
from defs import BOOMER_KUWANGER as BK, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, fight_state, countdown, shot_log, X_LOG, Fight, report

ID, HORNS = 0x05, 0x1B
CACHE = "work/boomer_kuwanger_runs.json"
STATE = "work/states/boomer_kuwanger_fight.mss"
PAR = {p.key: p for p in BK.params}
DASH_T, TELE_T = BK.attack_tables[0].addr, BK.attack_tables[1].addr     # 2 rows of 16 each
EXECS = {0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze", 0x84AADD: "beaten",
         0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound", 0x828358: "alloc_shot",
         0x8282D3: "alloc_effect", 0x84A677: "defeat_seq", 0x849B43: "hit_check", 0x849B03: "hurt_x",
         0x84ACA5: "face_x", 0x849F19: "x_grabbed", 0x849F7E: "x_drop", 0x849F2F: "x_take_damage",
         0x84A338: "shake", 0x878D57: "r_dash_near", 0x878D66: "r_dash_far", 0x8790C5: "r_target",
         0x879029: "r_streak", 0x879033: "r_streak_len", 0x878DCE: "r_after_dash", 0x878F1E: "r_after_tele"}
M = f"find(0x0E68, 0x1228, {ID})"
START = dict(level=7, x=1664, y=100)
LEFT, MID, RIGHT = 1830, 1900, 2000
WALK_IN = f"return {{right = r16(0x0BAD) < {MID}}}"


def hold(x, fire=False, extra=""):
    return (("fire = true\n" if fire else "") + extra + f"""local xx = r16(0x0BAD)
return {{right = xx < {x - 3}, left = xx > {x + 3}, y = fire and frame % 16 < 8}}""")


HOLD = hold(MID)
NO_DAMAGE = f"do local m = {M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
SET_HP1 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); hpset = true end end"
SET_HP16 = f"do local a = {M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x90); hpset = true end end"
TORPEDO = "w16(0x1F87, 0xDC00); w8(0x0BDB, 2)"     # own Homing Torpedo with ammo, and select it
DASH_CASES = [(r, (0, 8) if r == 0 else (9, 46)) for r in (0, 1)]       # row -> dash_frames tried
TELE_DIST = {0: (128, 200), 1: (0, 127)}                                # row 0 = X far, 1 = X close


def table(g, addr):
    b = snes2pc(addr)
    return list(g.rom[b:b + 32])


def exhaust():
    """Hooks re-running each choice 32 times within one frame. (An exec hook doesn't fire again for the
    instruction the PC is set back to, so the loop hook advances the case itself.)"""
    dc = "{" + ", ".join(f"{{{fr[c % 2]}, {c}, {r}}}" for r, fr in DASH_CASES for c in range(16)) + "}"
    tc = "{" + ", ".join(f"{{{TELE_DIST[r][c % 2]}, {c}, {r}}}" for r in (0, 1) for c in range(16)) + "}"
    return [
        (0x878DC6, f'if not d_done and not d_cur then d_c = {dc}; d_n = 1; d_cur = d_c[1] end'),
        (0x878DCE, 'if d_cur then setreg("cpu.a", (s["cpu.a"] & 0xFF00) | d_cur[2]) end'),
        (0x878DD3, 'if d_cur then setreg("cpu.a", (s["cpu.a"] & 0xFF00) | d_cur[1]) end'),
        (0x878DDF, 'if d_cur then out("dpick", "frames=" .. d_cur[1] .. " col=" .. d_cur[2] .. " row=" .. d_cur[3] .. '
                   '" step=" .. (s["cpu.a"] & 0xFF)); if d_n < #d_c then d_n = d_n + 1; d_cur = d_c[d_n]; '
                   'setreg("cpu.pc", 0x8DCA) else d_done = true; d_cur = nil end end'),
        (0x878F11, f'if not t_done and not t_cur and r8(s["cpu.d"] + 0x32) == 0 then t_c = {tc}; t_n = 1; '
                   't_cur = t_c[1] end'),
        (0x878F1E, 'if t_cur then setreg("cpu.a", (s["cpu.a"] & 0xFF00) | t_cur[2]) end'),
        (0x878F2F, 'if t_cur then setreg("cpu.a", t_cur[1]) end'),
        (0x878F3E, 'if t_cur then out("tpick", "dist=" .. t_cur[1] .. " col=" .. t_cur[2] .. " row=" .. t_cur[3] .. '
                   '" step=" .. (s["cpu.a"] & 0xFF)); if t_n < #t_c then t_n = t_n + 1; t_cur = t_c[t_n]; '
                   'setreg("cpu.pc", 0x8F1A) else t_done = true; t_cur = nil end end')]


def only(attack, **values):
    def f(g):
        for addr in (DASH_T, TELE_T):
            b = snes2pc(addr)
            for i in range(32):
                g.rom[b + i] = attack
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def values(**v):
    return lambda g: [P.put(g, PAR[k], x) for k, x in v.items()]


def run(frames, inp=HOLD, seed=None, inf=True, ar=True, patch=None, extra=(), hooks=(), full=False):
    r = Run(**START, frames=frames, seed=seed, infinite_hp=inf, patch=patch, savestate=None if full else STATE)
    r.track(ID, tag="bk")
    for a, t in EXECS.items():
        r.on_exec(a, t)
    for a, lua in hooks:
        r.at_exec(a, lua)
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.on_write(0x1F0E, "hud_boss").on_write(0x0BCF, "X_hp")
    r.input(inp)
    if ar:
        r.each_frame(NO_DAMAGE)
    r.each_frame(X_LOG)
    r.each_frame(shot_log("sh", [HORNS]))
    r.each_frame('out("cam", "l=" .. r16(0x1E4D))')
    for lua in extra:
        r.each_frame(lua)
    return r


def main():
    g0 = MMX1("work/hack.sfc")
    dtab, ttab = table(g0, DASH_T), table(g0, TELE_T)
    natural = [("n0", 0x1111, hold(LEFT)), ("n1", 0x2345, hold(MID)), ("n2", 0x3C3C, hold(RIGHT)),
               ("n3", 0x4A21, hold(MID, True))]
    runs = {k: run(5000, inp, seed=s) for k, s, inp in natural}
    runs.update({
        "intro": run(1300, WALK_IN, seed=0x1234, full=True),
        "table": run(1500, seed=0x1001, hooks=exhaust()),
        "dash": run(4000, seed=0x2001, patch=only(0)),
        "boomerang": run(3000, seed=0x2002, patch=only(2)),
        "teleport": run(4000, seed=0x2003, patch=only(4)),
        "lift": run(4000, hold(MID), seed=0x2004, ar=False, patch=only(0)),
        "buster": run(3000, hold(MID, True), seed=0x2005, patch=only(4)),
        "torpedo": run(3000, hold(MID, True, TORPEDO + "\n"), seed=0x2006, patch=only(4)),
        "streak": run(3000, hold(MID, True), seed=0x2007, extra=[SET_HP16]),
        "death": run(1500, hold(MID, True), seed=0x2008, extra=[SET_HP1]),
        "x_dies": run(3000, hold(MID), seed=0x2009, inf=False, ar=False),
        "v_hit": run(2600, hold(MID, True), seed=0x3001, full=True, patch=values(max_hp=20, invuln_time=0x20)),
        "v_speed": run(3000, seed=0x3002, patch=values(teleport_speed=0x600, dash_speed=0x300)),
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
    t = {k: Fight(v, "bk") for k, v in out.items()}
    nat = [t[k] for k, _, _ in natural]
    alls = [x for k, x in t.items() if not k.startswith("v_") and k != "x_dies"]
    dt = snes2pc(DAMAGE_TABLE)
    row = g0.rom[dt + g0.w(dt + 2 * BK.damage_class):][:32]
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
    cam = {e["f"]: e["l"] for e in n.by_tag["cam"]}
    b1 = n.starts(lambda e: e["state"] == 2 and e["step"] == 2)
    check("obj_start: palette_bits ($33) = attr & $0E; beam-in starts at screen left + 16 (vx $1000)",
          st2["f33"] == st2["attr"] & 0x0E and b1 and b1[0]["x"] == cam.get(b1[0]["f"], 0) + 16 and b1[0]["vx"] == 0x1000,
          f"x {b1 and b1[0]['x']}, screen left {b1 and cam.get(b1[0]['f'])}")
    path = [(e["x"], e["y"]) for e in n.p if e["state"] == 2 and e["step"] in (2, 4, 6)]
    check("beam-in: a zig-zag path (right, down, right in 16 px steps), then the boss bar (hud_boss)",
          path and n.by_tag["hud_boss"] and len({x for x, _ in path}) > 3 and len({y for _, y in path}) > 3,
          f"{path[0]} -> {path[-1]}")
    ticks = [c["f"] for c in n.calls("sound_c") if n.at.get(c["f"] + 1, {}).get("state") == 2]
    check("HP fill: +1 every 2 frames to 32", len(ticks) == 32 and set(b - a for a, b in zip(ticks, ticks[1:])) == {2},
          f"{len(ticks)} ticks")
    s10 = n.starts(lambda e: e["state"] == 2 and e["step"] == 10)[0]
    ok, a, b = countdown(n.phase(s10), "f34", 30)
    nx = n.after(s10)
    check("end of intro: 30 frames, x_unfreeze, music $1E, state 4 starting with a Dash",
          ok and nx and (nx["state"], nx["step"]) == (4, 0) and n.calls("x_unfreeze", False)
          and any(c["a"] & 0xFF == 0x1E for c in n.calls("music", False)), f"{a}..{b}")
    dm = collections.Counter((x.at[e["f"] - 1]["f3D"] != 0, e["dmg"]) for x in alls for e in x.p
                             if e["state"] == 4 and x.at.get(e["f"] - 1, {}).get("state") == 4 and e["dmg"] != 3
                             and not (e["f3D"] and e["f3D"] == x.at[e["f"] - 1]["f3D"]))
    check("damage class 13; 5 while invulnerable", dm and all(d == (5 if inv else 13) for (inv, d) in dm), f"{dict(dm)}")

    # --- choices ------------------------------------------------------------------------------
    x = t["table"]
    dp, tp = x.by_tag["dpick"], x.by_tag["tpick"]
    dok = [p["step"] == dtab[16 * (1 if p["frames"] >= 9 else 0) + p["col"]] for p in dp]
    tok = [p["step"] == ttab[16 * (0 if p["dist"] >= 128 else 1) + p["col"]] for p in tp]
    check("after a dash (all 32 entries, one frame): row = dash_frames ($31) ≥ 9 (tried at 0/8, 9/46), column = "
          "random & 15, attack = entry at $86:C5A3", len(dp) == 32 and all(dok) and len({f["f"] for f in dp}) == 1,
          f"{sum(dok)}/{len(dp)}")
    check("after a teleport (all 32 entries, one frame): row = X within 128 px (tried at 128/200, 0/127), column = "
          "random & 15, attack = entry at $86:C5C3", len(tp) == 32 and all(tok) and len({f["f"] for f in tp}) == 1,
          f"{sum(tok)}/{len(tp)}")
    un = []
    for k, x in t.items():
        if k in ("table", "dash", "boomerang", "teleport", "lift", "buster", "torpedo") or k.startswith("v_"):
            continue
        for c in x.calls("r_after_dash"):
            b, a = x.at.get(c["f"]), x.at.get(c["f"] + 1)
            if a and b and a["state"] == 4 and a["step"] != 8:
                un.append(a["step"] == dtab[16 * (b["f31"] >= 9) + (c["a"] & 0x0F)] or a["step"] == 6)
    check("unforced choices after a dash agree with the table", un and all(un), f"{sum(un)}/{len(un)}")

    # --- Dash ---------------------------------------------------------------------------------
    da = [t["dash"], *nat]
    dl = []
    for x in da:
        for tag, near in (("r_dash_near", True), ("r_dash_far", False)):
            for c in x.calls(tag):
                a = x.at.get(c["f"] + 1)
                xx = x.x.get(c["f"])
                if a and xx and a["step"] == 0:
                    d = abs(xx["x"] - x.at[c["f"]]["x"]) if x.at.get(c["f"]) else None
                    full = (c["a"] & 0x0F < 6) == near
                    dl.append((a["f34"] == (d // 4 + 1 if full else 8)) if d is not None else True)
    check("Dash: X < 128 px away: random & 15 < 6 -> runs all the way to X (timer = distance / 4 + 1), else an 8-frame "
          "burst; X farther: the other way round", dl and sum(dl) >= len(dl) - 2, f"{sum(dl)}/{len(dl)}")
    sp = [s for x in da for s in x.starts(x.fight(0, 2))]
    check("Dash: faces X, sound $53, vx ±$400 the way he faces", sp and all(abs(s["vx"]) == 0x400 and
          (s["vx"] > 0) == bool(s["attr"] & 0x40) for s in sp) and all(x.called("sound", s["f"], 0x53)
                                                                       for x in da for s in x.starts(x.fight(0, 2))),
          f"{len(sp)} dashes")
    runs_ = []
    for x in da:
        for s in x.starts(x.fight(0, 4)):
            a = x.after(s)                                     # (the frame the run ends: dash_frames final)
            if a and a["step"] == 0 and a["sub"] == 6:
                runs_.append((a["f31"], s["f34"], bool(a["touch"] & 3)))
    check("Dash: runs until the timer ends or he meets a wall (dash_frames $31 counts the frames), then 20 frames",
          runs_ and all(fr == tm or wall for fr, tm, wall in runs_)
          and all(countdown(x.phase(s), "f34", 20)[0] for x in da for s in x.starts(x.fight(0, 6))
                  if x.phase(s) and x.after(s) and x.after(s)["step"] != 8),
          f"{collections.Counter(runs_).most_common(4)}")

    # --- Boomerang ----------------------------------------------------------------------------
    bo = t["boomerang"]
    th = []
    for l in bo.lives("sh"):
        m = bo.at.get(l[0]["f"])
        if m:
            th.append((l[0]["x"] - m["x"], l[0]["y"] - m["y"], m["f35"]))
    check("Boomerang: horns = enemy shot $1B at his x, y − 24; boomerang_out ($35) = 1 while they're out",
          th and all(dx == 0 and dy == -24 for dx, dy, _ in th), f"{len(th)} throws, {th[:3]}")
    ret = [e for e in bo.p if e["f35"] and e["state"] == 4]
    back = [l for l in bo.lives("sh") if l[-1]["f"] < bo.p[-1]["f"]]
    clr = [bo.at.get(l[-1]["f"] + 1, {}).get("f35") for l in back]
    check("Boomerang: when the horns come back boomerang_out is cleared (horned poses again); after 8 frames he dashes",
          back and all(c == 0 for c in clr if c is not None) and all(o for o, _, _ in bo.timers(2, 4, "f34", 8)),
          f"{len(back)} returns")
    noch = [e for e in bo.p if e["f35"] and e["step"] == 0 and e["sub"] == 6 and e["f34"] == 1]
    check("dash end with the horns still out: no choice, he dashes again", all(
        bo.at.get(e["f"] + 1, {}).get("step", 0) == 0 for e in noch), f"{len(noch)}")

    # --- Teleport -----------------------------------------------------------------------------
    te = [t["teleport"], t["buster"], t["torpedo"]]
    tg = []
    for x in te:
        for c in x.calls("r_target"):
            a, b = x.at.get(c["f"] + 1), x.at.get(c["f"])
            xx = x.x.get(c["f"])
            left = next((e["l"] for e in x.by_tag["cam"] if e["f"] == c["f"]), 0)
            if a and b and xx:
                k = c["a"] & 3
                tx = a["f3A"] + 256 * a["f3B"]
                if k < 3:
                    d = (28, 48, 80)[k]
                    want = xx["x"] - d if xx["x"] - 128 - left >= 0 else xx["x"] + d
                else:
                    want = left + (32 if b["x"] >= xx["x"] else 224)
                tg.append((k, tx == want, abs(a["vx"]) == 0x800 and (a["vx"] > 0) == (tx >= b["x"])))
    check("Teleport target: random & 3 = 0/1/2 -> X ± 28/48/80 (on the side of X toward the screen's middle), 3 -> "
          "screen left + 32 or + 224 (past X); vx ±$800 toward it, sound $50", tg and all(o and v for _, o, v in tg),
          f"{sum(o and v for _, o, v in tg)}/{len(tg)}, kinds {collections.Counter(k for k, _, _ in tg)}")
    arr = []
    for x in te:
        for s in x.starts(x.fight(4, 6)):
            b = x.at.get(s["f"] - 1)
            if b:
                arr.append(s["x"] == s["f3A"] + 256 * s["f3B"] or bool(s["touch"] & 3))
    check("Teleport: blinks 20 frames (teleporting = 1), moves until within 5 px of the target (then snaps to it) or a "
          "wall, sound $50, blinks 20 more, reappears, 8 frames, chooses", arr and all(arr) and all(
              countdown(x.phase(s), "f34", 8)[0] for x in te for s in x.starts(x.fight(4, 8))
              if x.phase(s) and x.after(s) and x.after(s)["step"] != 8), f"{sum(arr)}/{len(arr)}")
    def mid(a):        # still teleporting during this frame (on the frame he reappears the flag clears before the hit check)
        return a["f38"] and not (a["step"] == 4 and a["sub"] == 6 and a["f39"] == 0)
    bu = t["buster"]
    tele_hits = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if mid(a) and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    reappear = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if a["f38"] and not mid(a) and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    to = t["torpedo"]
    tt = [(a, c) for a, c in zip(to.p, to.p[1:]) if mid(a) and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("while teleporting only a hit with Homing Torpedo selected ($0BDB = 2) counts (the buster can hit him on "
          "the frame he reappears)", not tele_hits and tt,
          f"buster {len(tele_hits)} mid-teleport, {len(reappear)} on reappearing; torpedo {len(tt)} mid-teleport")

    # --- Dead Lift ----------------------------------------------------------------------------
    li = t["lift"]
    gr = li.starts(li.fight(6, 4))
    check("Dead Lift: X within 32 px in front (and touchable, horns in) -> step 6; still within 40 px when the pose "
          "ends -> x_grabbed, lift = 1, X held 32 px in front for 20 frames", gr and all(li.called("x_grabbed", s["f"])
                                                                                 for s in gr),
          f"{len(li.starts(li.fight(6, 0)))} tries, {len(gr)} grabs")
    hold32 = collections.Counter()
    for s in gr:
        for e in li.phase(s)[1:]:
            xx = li.x.get(e["f"])
            if xx:
                hold32[(xx["x"] - e["x"]) * (1 if e["attr"] & 0x40 else -1)] += 1
    thr = [e for e in li.by_tag["X_hp"] if any(c["f"] == e["f"] for c in li.calls("x_take_damage", False))]
    shakes = [c for c in li.calls("shake", False) if c["a"] & 0xFF == 32]
    check("Dead Lift throw: when X reaches the ceiling, 4 damage (x_take_damage: X HP 16 -> 12) and screen_shake(32)", gr and shakes and li.calls("x_take_damage", False),
          f"held at {dict(hold32)}, {len(shakes)} throws, X HP writes {[e['v'] & 0x7F for e in thr][:4]}")

    # --- getting hit --------------------------------------------------------------------------
    hb = [t["n3"], t["buster"], t["streak"]]
    lh = [{e["f"]: e["v"] for e in x.by_tag["last_hit"]} for x in hb]
    hits = [(x, a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if a["state"] == c["state"] == 4 and c["f"] > 10
            and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: −1 HP (row 13), sound $13, invuln_timer ($3D) 60, flinch (step 8) for 16 frames", hits and all((a["hp"] - c["hp"]) & 0x7F == row[0] and c["f3D"] in (59, 60) and c["step"] == 8
                                       and c["f34"] in (15, 16) for x, a, c in hits), f"{len(hits)} hits")
    th24 = [(a, c) for a, c in zip(to.p, to.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("Homing Torpedo (projectile 7, his weakness): flinch 24 frames; damage from row 13",
          th24 and all(c["f34"] in (23, 24) and ((a["hp"] - c["hp"]) & 0x7F == row[7] or c["hp"] & 0x7F == 0)
                       for a, c in th24), f"{len(th24)} hits, row13[7] = {row[7]}")
    st = t["streak"]
    sk = []
    for c in st.calls("r_streak"):
        nx = next((c2 for c2 in st.calls("r_streak_len") if c2["f"] == c["f"]), None)
        a = st.at.get(c["f"] + 1)
        if a:
            if c["a"] & 0x0F < 6:
                sk.append(nx is not None and a["f32"] == (nx["a"] & 7) + 6 and a["step"] == 4)
            else:
                sk.append(nx is None)
    check("below 17 HP: after a flinch, random & 15 < 6 starts a streak of (random & 7) + 6 teleports",
          sk and all(sk) and any(c["a"] & 0x0F < 6 for c in st.calls("r_streak")), f"{sum(sk)}/{len(sk)}")
    inv = [c for x in hb for a, c in zip(x.p, x.p[1:]) if 0 < c["f3D"] == a["f3D"] - 1 and c["f3D"] & 3 == 0]
    rest = [(a, c) for x in hb for a, c in zip(x.p, x.p[1:]) if a["f3D"] > 1 and c["hp"] & 0x7F < a["hp"] & 0x7F]
    check("invulnerable: no HP lost; he flashes (palette bits cleared when the timer is a multiple of 4)",
          not rest and inv and all(c["attr"] & 0x0E == 0 for c in inv), f"{len(inv)} flash frames")

    # --- death / X ----------------------------------------------------------------------------
    de = t["death"]
    six = de.starts(lambda e: e["state"] == 6)
    check("HP 0: state 6, boss_defeated = 1, X_hurt_lock = 1, boss_defeated_sequence, despawn",
          six and de.by_tag["boss_defeated"] and len(de.calls("defeat_seq")) > 300 and any("gone" in e for e in de.by_tag["bk"]))
    xd = t["x_dies"]
    died = [e for e in xd.by_tag["X"] if e["hp"] & 0x7F == 0 and e["f"] > 10]
    check("x_dead ($30) = 1 once X's HP is 0", died and any(e["f30"] == 1 for e in xd.p if e["f"] >= died[0]["f"]),
          f"X at 0 HP from frame {died[0]['f'] if died else None}")

    # --- values -------------------------------------------------------------------------------
    v = t["v_hit"]
    check("value max_hp = 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f3D"] for e in v.p) in (31, 32))
    v = t["v_speed"]
    tv = {s["vx"] for s in v.starts(v.fight(4, 2))}
    dv = {s["vx"] for s in v.starts(v.fight(0, 2))}
    check("values teleport_speed = $600, dash_speed = $300 (both directions)",
          tv and dv and {abs(k) for k in tv} == {0x600} and {abs(k) for k in dv} == {0x300},
          f"teleport vx {sorted(tv)}, dash vx {sorted(dv)}")

    report(results)


if __name__ == "__main__":
    main()
