"""
Re-checks everything we claim about Chill Penguin by running the game in Mesen (see mesen_verify.py).

    python3 verify_chill_penguin.py          # about 12 minutes on a Raspberry Pi 400 (runs 4 at a time)

Every test starts in his stage at checkpoint 2 (x=7560), walks X through the boss door and stops at
x=7720 (inside the room, left side). X has infinite HP unless a test needs him to die. Tests that need a
specific attack overwrite the attack table so he only does that attack; tests of editable values change
the value in the test ROM and check that the behaviour follows.
"""
import collections
import math
import sys

import params as P
from defs import CHILL_PENGUIN as CP, DAMAGE_TABLE
from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all

ID, ROOM_X = 0x02, 7720
WALK = f"return {{right = r16(0x0BAD) < {ROOM_X}}}"
FIRE = f"return {{right = r16(0x0BAD) < {ROOM_X}, y = r16(0x0BAD) >= {ROOM_X} and (frame % 16) < 8}}"
FIRE_WAVE = "w16(0x1F8D, 0xDC00); w8(0x0BDB, 8)"       # own Fire Wave with ammo, and select it
SET_HP1 = ('do local a = find(0x0E68, 0x1228, 2); if a and r8(a + 1) == 4 and not hpset then '
           'w8(a + 0x27, 0x81); hpset = true end end')
PAR = {p.key: p for p in CP.params}
TABLE = CP.attack_tables[0].addr
NAMES = ["Ice Shot", "Blizzard", "Belly Slide", "Jump at X", "Ice Breath"]
FIELDS = {0x81C019: "choose", 0x8087A2: "music", 0x849FEB: "x_freeze", 0x84A003: "x_unfreeze",
          0x82827D: "obj_start", 0x848F07: "anim", 0x8088CD: "sound_c", 0x8088A2: "sound",
          0x828358: "alloc_shot", 0x8282B9: "alloc_misc", 0x84A677: "defeat_seq", 0x81BF16: "breath_particle",
          0x81BF5C: "statue", 0x849B43: "hit_check", 0x849B03: "hurt_x", 0x84ACA5: "face_x",
          0x8281E8: "move_grav", 0x8491BE: "terrain", 0x828174: "brake_r", 0x828195: "brake_l"}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def only(attack, **values):
    """ROM patch: every table entry = `attack`, plus changed editable values."""
    def f(g):
        t = snes2pc(TABLE)
        g.rom[t:t + 80] = bytes([attack]) * 80
        for k, v in values.items():
            P.put(g, PAR[k], v)
    return f


def run(frames, inp=WALK, seed=None, inf=True, patch=None, extra=(), watch_all=True):
    r = Run(level=8, x=7560, frames=frames, seed=seed, infinite_hp=inf, patch=patch)
    r.track(ID, tag="peng").track(0x12, "misc", tag="hook")
    for a, t in (FIELDS.items() if watch_all else []):
        r.on_exec(a, t)
    r.on_write(0x1F0C, "boss_defeated").on_write(0x0BD8, "X_hurt_lock").on_write(0x1F1D, "last_hit")
    r.input(inp)
    r.each_frame('if r16(0x0BAD) ~= lastx then out("X", "x=" .. r16(0x0BAD)); lastx = r16(0x0BAD) end')
    for lua in extra:
        r.each_frame(lua)
    return r


class T:
    """Helpers over one run's events."""
    def __init__(self, ev):
        self.ev = ev
        self.p = [e for e in ev if e["tag"] == "peng" and "slot" in e]
        self.slot = self.p[0]["slot"] if self.p else None
        self.at = {e["f"]: e for e in self.p}
        self.hook = {e["f"]: e for e in ev if e["tag"] == "hook" and "slot" in e}

    def calls(self, tag):
        return [e for e in self.ev if e["tag"] == tag and e.get("d") == self.slot]

    def starts(self, cond):
        return [e for i, e in enumerate(self.p) if cond(e) and (i == 0 or not cond(self.p[i - 1]))]

    def next_call(self, tag, after):
        return next((e["f"] for e in self.calls(tag) if e["f"] > after), None)


def main():
    seeds = [0x1111, 0x2345, 0x3C3C, 0x4A21, 0x5EED, 0x6F01, 0x7777, 0x8D13, 0x9101, 0xA0B1, 0xB2C3, 0xC4D5]
    runs = {
        "natural": run(3600),
        "buster": run(3600, FIRE, seed=0x1111),
        "firewave": run(3600, FIRE, seed=0x2222, extra=[FIRE_WAVE]),
        "death": run(2400, FIRE, seed=0x3333, extra=[SET_HP1]),
        "x_dies": run(2600, inf=False, seed=0x4444),
        "v_ice": run(2300, patch=only(0, ice_shots=6, ice_shot_pause=30)),
        "v_hit": run(2300, FIRE, patch=only(0, max_hp=20, invuln_time=0x20, weakness_a=0x00,
                                            flinch_x=0x180, flinch_y=0x300)),
        "v_weak_b": run(2300, FIRE, patch=only(0, weakness_a=0x1C, weakness_b=0x00)),
        "v_slide": run(2200, patch=only(4, slide_speed=0x300)),
        "v_jump": run(2200, patch=only(6, jump_speed=0x600)),
        "v_bliz": run(2400, patch=only(2, blizzard_jump_speed=0x700, blizzard_hang=0x50)),
        "v_breath": run(2400, patch=only(8, breath_time=0x20, statue1_dist=0x20, statue2_dist=0x60)),
    }
    for i, s in enumerate(seeds):
        runs[f"stats{i}"] = run(6000, seed=s, watch_all=False).on_exec(0x81C019, "choose")
    print(f"running {len(runs)} emulator sessions, 4 at a time...", flush=True)
    out = dict(zip(runs, run_all(list(runs.values()))))
    t = {k: T(v) for k, v in out.items()}
    g = MMX1("work/hack.sfc")

    # --- intro ---------------------------------------------------------------------------
    n = t["natural"]
    init = n.starts(lambda e: e["state"] == 0 and e["step"] == 1)[0]
    check("init: x_freeze_for_boss + jingle $2E when he starts",
          n.calls("x_freeze") and any(c["a"] & 0xFF == 0x2E for c in n.calls("music")))
    st2 = n.starts(lambda e: e["state"] == 2)[0]
    # (the game skips object updates on a few busy frames, so allow a little slack)
    check("init: 60-frame wait (timer $34 = 60)", init["f34"] == 60 and 60 <= st2["f"] - init["f"] <= 64,
          f"timer {init['f34']}, waited {st2['f'] - init['f']} frames")
    check("obj_start: state 2, damage class 3", st2["dmg"] == 3)
    check("palette_bits ($33) = attr & $0E", st2["f33"] == st2["attr"] & 0x0E, f"{st2['f33']} / attr {st2['attr']:02X}")
    check("intro spawns the ceiling hook (object $12, misc list)", n.hook)
    ticks = [c["f"] for c in n.calls("sound_c") if c["a"] & 0xFF == 0x0C]
    check("HP fill: 32 ticks, 2 frames apart", len(ticks) == 32 and set(b - a for a, b in zip(ticks, ticks[1:])) == {2},
          f"{len(ticks)} ticks")
    fight = n.starts(lambda e: e["state"] == 4)[0]
    check("max HP 32 after the fill", fight["hp"] & 0x7F == 32)
    check("end of intro: boss music $1E, then x_unfreeze", any(c["a"] & 0xFF == 0x1E for c in n.calls("music"))
          and n.calls("x_unfreeze"))
    check("fight damage class 9", any(e["dmg"] == 9 for e in n.p if e["state"] == 4))

    # --- attacks ---------------------------------------------------------------------------
    vol = n.starts(lambda e: e["state"] == 4 and e["step"] == 0 and e["sub"] == 2)[0]
    shots = [c["f"] for c in n.calls("alloc_shot") if vol["f"] <= c["f"] <= vol["f"] + 300]
    check("Ice Shot: 4 shots", vol["f36"] == 4 and len(shots) == 4, f"field {vol['f36']}, spawned {len(shots)}")
    pause = n.starts(lambda e: e["state"] == 4 and e["step"] == 0 and e["sub"] == 4)[0]
    nxt = n.next_call("choose", pause["f"])
    check("Ice Shot: 120-frame pause", pause["f34"] == 120 and nxt - pause["f"] == 119, f"{nxt - pause['f']}")
    alls = [x for x in t.values()]
    slide = next(s for x in alls for s in x.starts(lambda e: e["state"] == 4 and e["step"] == 4 and e["sub"] == 2))
    check("Belly Slide: speed $600, damage class 0, sliding=1, can_flinch=0",
          abs(slide["vx"]) == 0x600 and slide["dmg"] == 0 and slide["f39"] == 1 and slide["f38"] == 0)
    quirk = []
    for x in alls:
        for s in x.starts(lambda e: e["state"] == 4 and e["step"] == 4 and e["sub"] == 6):
            c = x.next_call("choose", s["f"] - 1)
            if c is not None:
                quirk.append(c - s["f"])
    check("Belly Slide: no recovery pause (next attack the same frame)", quirk and set(quirk) == {0}, f"{quirk[:5]}")
    jump = next((x, s) for x in alls for s in x.starts(lambda e: e["state"] == 4 and e["step"] == 6 and e["sub"] == 2))
    xj, sj = jump
    xx = max((e for e in xj.ev if e["tag"] == "X" and e["f"] <= sj["f"]), key=lambda e: e["f"])["x"]
    check("Jump at X: vx = (X.x - his x) x 4, vy $87E", sj["vx"] == (xx - xj.at[sj["f"] - 1]["x"]) * 4
          and sj["vy"] == 0x87E, f"vx {sj['vx']} (X {xx}, him {xj.at[sj['f'] - 1]['x']}), vy {sj['vy']}")
    bl = next((x, s) for x in alls for s in x.starts(lambda e: e["state"] == 4 and e["step"] == 2 and e["sub"] == 2))
    check("Blizzard: vy $7DE", bl[1]["vy"] == 0x7DE, f"{bl[1]['vy']}")
    xb = bl[0]
    sig = [f for f in sorted(xb.hook) if f > bl[1]["f"] and (xb.hook[f]["vx"] >> 8) & 0xFF == 1]
    drop = next((e["f"] for e in xb.p if sig and e["f"] > sig[0] and e["step"] == 2 and e["sub"] == 6), None)
    check("Blizzard: signals the hook ($1B = 1), hangs 30 frames", sig and drop - sig[0] == 30,
          f"hang {drop - sig[0] if sig and drop else None}")
    hstate = [xb.hook[f]["state"] for f in sorted(xb.hook) if sig and f in (sig[0], sig[0] + 1)]
    check("Blizzard: the hook switches to its wind state (6) on the signal", hstate[-1:] == [6], f"{hstate}")
    br = next((x, s) for x in alls for s in x.starts(lambda e: e["state"] == 4 and e["step"] == 8 and e["sub"] == 4))
    xr, sr = br
    end = next(e["f"] for e in xr.p if e["f"] > sr["f"] and not (e["step"] == 8 and e["sub"] == 4))
    st = [c["a"] & 0xFF for c in xr.calls("alloc_shot") if sr["f"] <= c["f"] <= end + 1 and c["a"] & 0xFF not in (0x80,)]
    check("Ice Breath: 60 frames, statues at $30 and $50", end - sr["f"] == 60 and st[:2] == [0x30, 0x50],
          f"{end - sr['f']} frames, {st[:2]}")
    sub = any(x.at.get(c["f"] + 1, {}).get("step") == 8 and x.at.get(c["f"] + 2, {}).get("step") == 0
              for x in alls for c in x.calls("choose"))
    check("Ice Breath becomes Ice Shot while a statue stands", sub)

    # --- table statistics ----------------------------------------------------------------
    b = snes2pc(TABLE)
    table = [list(g.rom[b + r * 16:b + r * 16 + 16]) for r in range(5)]
    obs = [[0] * 5 for _ in range(5)]
    for k, x in t.items():
        if k.startswith("stats"):
            for c in x.calls("choose"):
                bf, af = x.at.get(c["f"]), x.at.get(c["f"] + 1)
                if bf and af and bf["step"] < 10:
                    obs[bf["step"] // 2][af["step"] // 2] += 1
    chi, impossible = 0.0, 0
    for r in range(5):
        nrow = sum(obs[r])
        for c in range(5):
            e = table[r].count(c * 2) * nrow / 16
            if e:
                chi += (obs[r][c] - e) ** 2 / e
            elif obs[r][c]:
                impossible += 1
    dof = 20
    z = ((chi / dof) ** (1 / 3) - (1 - 2 / (9 * dof))) / math.sqrt(2 / (9 * dof))
    total = sum(map(sum, obs))
    check("attack choice matches the table at $86:C45B", abs(z) < 2.5 and not impossible and total > 150,
          f"{total} picks, chi2={chi:.1f}/{dof}, z={z:.2f}")

    # --- getting hit -------------------------------------------------------------------------
    bu = t["buster"]
    row9 = g.rom[snes2pc(DAMAGE_TABLE) + g.w(snes2pc(DAMAGE_TABLE) + 18):][:30]
    hits = [(a, c) for a, c in zip(bu.p, bu.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    check("buster hit: -1 HP (damage row 9)", hits and all((a["hp"] - c["hp"]) & 0x7F == row9[0] for a, c in hits),
          f"{len(hits)} hits")
    check("hit: 70 frames invulnerable, damage class 5 meanwhile",
          all(c["f35"] == 69 and bu.at.get(c["f"] + 1, {}).get("dmg") == 5 for a, c in hits))
    fl = [(a, c) for a, c in hits if a["f38"] == 1]
    nf = [(a, c) for a, c in hits if a["f38"] == 0]
    check("flinches only when can_flinch ($38) = 1", fl and all(c["step"] == 10 for a, c in fl)
          and all(c["step"] != 10 for a, c in nf), f"{len(fl)} flinchable, {len(nf)} not")
    s0 = bu.at.get(fl[0][1]["f"] + 1) if fl else None
    check("small flinch: timer $37 = 20, speeds $100 / $221",
          s0 and s0["f37"] == 20 and abs(s0["vx"]) == 0x100 and s0["vy"] == 0x221)
    fw = t["firewave"]
    fwh = [(a, c) for a, c in zip(fw.p, fw.p[1:]) if a["state"] == 4 and (c["hp"] & 0x7F) < (a["hp"] & 0x7F)]
    big = [c for a, c in fwh if c["step"] == 10 and c["sub"] == 2]
    f2 = fw.at.get(big[0]["f"] + 1) if big else None
    check("Fire Wave: -3 HP and the big flinch ($37 = 60, sound $4A)",
          fwh and (fwh[0][0]["hp"] - fwh[0][1]["hp"]) & 0x7F == row9[0x0A] and f2 and f2["f37"] == 60
          and any(c["a"] & 0xFF == 0x4A for c in fw.calls("sound")))
    d = t["death"]
    six = d.starts(lambda e: e["state"] == 6)
    bdw = [e for e in d.ev if e["tag"] == "boss_defeated" and e["v"] == 1]
    check("HP 0: state 6, death pose 4, boss_defeated = 1, X_hurt_lock = 1",
          six and any(c["a"] & 0xFF == 4 and c["f"] == six[0]["f"] - 1 for c in d.calls("anim")) and bdw
          and any(e["v"] == 1 for e in d.ev if e["tag"] == "X_hurt_lock"))
    check("death: boss_defeated_sequence every frame, then he despawns",
          len(d.calls("defeat_seq")) > 400 and any(e["tag"] == "peng" and "gone" in e for e in d.ev))
    xd = t["x_dies"]
    check("x_dead ($30) = 1 once X's HP is 0", any(e["f30"] == 1 for e in xd.p))

    # --- editable values ---------------------------------------------------------------------
    v = t["v_ice"]
    vs = v.starts(lambda e: e["step"] == 0 and e["sub"] == 2)
    ve = v.starts(lambda e: e["step"] == 0 and e["sub"] == 4)
    cnt = [sum(1 for c in v.calls("alloc_shot") if a["f"] <= c["f"] <= b["f"]) for a, b in zip(vs, ve)]
    check("value ice_shots = 6 -> 6 shots", cnt and set(cnt) == {6}, f"{cnt}")
    gaps = [v.next_call("choose", e["f"]) - e["f"] for e in ve]
    check("value ice_shot_pause = 30 -> 30-frame pause", gaps and set(gaps) == {29}, f"{gaps}")
    v = t["v_hit"]
    check("value max_hp = 20 -> HP fill stops at 20", max(e["hp"] & 0x7F for e in v.p if e["state"] == 2) == 20)
    check("value invuln_time = $20 -> 32 frames", max(e["f35"] for e in v.p) == 32)
    bigs = v.starts(lambda e: e["step"] == 10 and e["sub"] == 2)
    nx = v.at.get(bigs[0]["f"] + 1) if bigs else None
    check("value weakness_a = buster -> buster gives the big flinch", bigs)
    check("values flinch_x/y = $180/$300", nx and abs(nx["vx"]) == 0x180 and nx["vy"] == 0x300,
          f"{nx and (nx['vx'], nx['vy'])}")
    check("value weakness_b = buster -> buster gives the big flinch",
          t["v_weak_b"].starts(lambda e: e["step"] == 10 and e["sub"] == 2))
    v = t["v_slide"]
    check("value slide_speed = $300", any(abs(e["vx"]) == 0x300 for e in v.p if e["step"] == 4 and e["sub"] == 2))
    v = t["v_jump"]
    check("value jump_speed = $600", any(e["vy"] == 0x600 for e in v.p if e["step"] == 6 and e["sub"] == 2))
    v = t["v_bliz"]
    s = v.starts(lambda e: e["step"] == 2 and e["sub"] == 2)
    sig = [f for f in sorted(v.hook) if (v.hook[f]["vx"] >> 8) & 0xFF == 1]
    drop = next((e["f"] for e in v.p if sig and e["f"] > sig[0] and e["step"] == 2 and e["sub"] == 6), None)
    check("values blizzard_jump_speed = $700, blizzard_hang = $50", s and s[0]["vy"] == 0x700 and sig
          and drop - sig[0] == 0x50, f"vy {s and s[0]['vy']}, hang {sig and drop and drop - sig[0]}")
    v = t["v_breath"]
    s = v.starts(lambda e: e["step"] == 8 and e["sub"] == 4)
    e2 = next(e["f"] for e in v.p if s and e["f"] > s[0]["f"] and not (e["step"] == 8 and e["sub"] == 4))
    st = [c["a"] & 0xFF for c in v.calls("alloc_shot") if s and s[0]["f"] <= c["f"] <= e2 + 1 and c["a"] & 0xFF != 0x80]
    check("values breath_time = $20, statues $20/$60", s and e2 - s[0]["f"] == 0x20 and st[:2] == [0x20, 0x60],
          f"{e2 - s[0]['f'] if s else None}, {st[:2]}")

    # --- which routines he uses where -----------------------------------------------------------
    use = collections.defaultdict(set)
    for x in alls:
        for e in x.ev:
            if e["tag"] in FIELDS.values() and e.get("d") == x.slot and e["f"] in x.at:
                p = x.at[e["f"]]
                use[e["tag"]].add((p["state"], p["step"]))
    check("breath_spawn_particle / spawn_ice_statue only during Ice Breath",
          use["breath_particle"] == {(4, 8)} and use["statue"] == {(4, 8)})
    check("move_brake_left/right only during the slide", (use["brake_l"] | use["brake_r"]) == {(4, 4)})
    check("hit_check / hurt_x_on_contact every fight step",
          {s for s in use["hit_check"] if s[0] == 4} >= {(4, 0), (4, 2), (4, 4), (4, 6), (4, 8)})
    check("move_with_gravity only when airborne (intro fall, Blizzard, Jump)",
          use["move_grav"] <= {(2, 0), (4, 2), (4, 6), (4, 10)})

    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:{width}}  {detail}")
    bad = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - bad}/{len(results)} passed")
    print("Run complete: now run the sync-records skill (.claude/skills/sync-records) to update every record.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
