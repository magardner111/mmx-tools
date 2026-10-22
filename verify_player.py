"""
Re-checks what we claim about X's movement, shots and damage by running the game in Mesen (see mesen_verify.py).

    python3 verify_player.py          # a few minutes on a Raspberry Pi 400 (runs 4 at a time)
    python3 verify_player.py --cached # re-check the last run's saved output

Test room: Armored Armadillo's room, from his fight-start state (work/states/armored_armadillo_fight.mss, made by
verify_armored_armadillo.py), with his object cleared every frame: a flat floor (X at y 2719, starting at x 5147)
between walls at x 5120 and 5376. (Setting his beaten flag instead makes entering the room end the stage: X goes
step $1E -> $1A -> $18 and leaves.) X's per-frame fields are logged (tag "xp"), and his shots ($1228 list, tag "xs").
"""
import collections
import json
import sys

from pathlib import Path

from mmx1 import MMX1, snes2pc
from mesen_verify import Run, run_all, shot_log, report

CACHE = "work/player_runs.json"
STATE = "work/states/armored_armadillo_fight.mss"
SPEEDS = 0x86B9B1                      # per step: vx word, vy word, gravity byte (index = step × 3)
NO_BOSS = "do local m = find(0x0E68, 0x1228, 0x14); if m then w8(m, 0) end end"
XF = [("step", 0x02, 1), ("sub", 0x03, 1), ("x", 0x05, 2), ("y", 0x08, 2), ("vx", 0x1A, -2), ("vy", 0x1C, -2),
      ("grav", 0x1E, 1), ("touch", 0x2B, 1), ("ta", 0x5E, 1), ("hp", 0x27, 1), ("lock", 0x30, 1),
      ("flash", 0x6B, 1), ("facing", 0x69, 1), ("spd", 0x5C, 2), ("t4E", 0x4E, 1), ("t52", 0x52, 1),
      ("dashj", 0x55, 1), ("t77", 0x77, 1), ("charge", 0x58, 1), ("anim", 0x0F, 1)]
X_TRACK = ('out("xp", ' + ' .. " " .. '.join(
    f'"{n}=" .. ' + (f"s16(0x{0x0BA8 + o:04X})" if s == -2 else f"r{8 * s}(0x{0x0BA8 + o:04X})") for n, o, s in XF) + ")")


def speeds():
    g = MMX1("work/hack.sfc")
    b = snes2pc(SPEEDS)
    s16 = lambda v: v - 0x10000 if v >= 0x8000 else v
    return {st: (s16(g.w(b + st * 3)), s16(g.w(b + st * 3 + 2)), g.rom[b + st * 3 + 4]) for st in range(0, 0x48, 2)}


def run(frames, inp, extra=(), seed=0x1234):
    r = Run(level=3, x=4992, frames=frames, seed=seed, infinite_hp=False, savestate=STATE)
    r.input(inp)
    r.each_frame(NO_BOSS)
    r.each_frame(X_TRACK)
    r.each_frame(shot_log("xs", range(0x20), 0x1228, 0x1428))
    for lua in extra:
        r.each_frame(lua)
    r.on_exec(0x8088CD, "sound_c").on_exec(0x84A338, "shake")
    return r


def press(button, at, length):
    """Lua input: hold `button` from frame `at` for `length` frames (frames counted from the state)."""
    return f"return {{{button} = frame >= {at} and frame < {at + length}}}"


class P:
    def __init__(self, ev):
        self.ev = ev
        self.x = [e for e in ev if e["tag"] == "xp" and e["f"] > 4]
        self.at = {e["f"]: e for e in self.x}
        self.shots = collections.defaultdict(list)
        for e in ev:
            if e["tag"] == "xs":
                self.shots[e["slot"]].append(e)

    def starts(self, step):
        return [e for a, e in zip(self.x, self.x[1:]) if e["step"] == step and a["step"] != step]

    def phase(self, s, key=("step",)):
        out = []
        for e in self.x:
            if e["f"] < s["f"]:
                continue
            if any(e[k] != s[k] for k in key):
                break
            out.append(e)
        return out

    def lives(self):
        out = []
        for recs in self.shots.values():
            cur = [recs[0]]
            for a, b in zip(recs, recs[1:]):
                if b["f"] != a["f"] + 1 or b["id"] != a["id"]:
                    out.append(cur)
                    cur = []
                cur.append(b)
            out.append(cur)
        return sorted(out, key=lambda l: l[0]["f"])


def main():
    sp = speeds()
    # inputs (frame numbers are frames since the state loaded; X is standing at x 5200)
    hold_y = lambda n: f"return {{y = frame >= 20 and frame < {20 + n}}}"
    runs = {
        "walk": run(200, "return {right = frame >= 20 and frame < 120}"),
        "walk_left": run(200, "return {left = frame >= 20 and frame < 120}"),
        "jump": run(200, press("b", 20, 80)),
        "jump_short": run(200, press("b", 20, 6)),
        # hold right into the right wall; jump there (held while rising), slide down it, press jump 4 frames into the
        # slide and hold it through the wall jump (steps $10 and 6)
        "slide": run(400, """local st = r8(0x0BAA)
return {right = frame >= 20, b = (st == 0 and frame >= 150 and frame % 30 < 5) or st == 6}"""),
        "wall": run(500, """local st = r8(0x0BAA)
if st == 0x12 then slide = (slide or 0) + 1 else slide = 0 end
return {right = frame >= 20, b = (st == 0 and frame >= 150 and frame % 30 < 5) or st == 6 or st == 0x10
        or slide >= 4}"""),
        "dash": run(200, "return {a = frame >= 20 and frame < 80}", extra=["w8(0x1F99, r8(0x1F99) | 0x08)"]),
        "no_dash": run(200, "return {a = frame >= 20 and frame < 80}", extra=["w8(0x1F99, r8(0x1F99) & 0xF7)"]),
        "dash_jump": run(200, "return {a = frame >= 20 and frame < 80, b = frame >= 30 and frame < 80}",
                         extra=["w8(0x1F99, r8(0x1F99) | 0x08)"]),
        "shots": run(300, "return {y = frame >= 20 and frame % 8 < 2}"),
        **{f"charge{n}": run(260, hold_y(n)) for n in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120)},
        "hurt": run(200, "return {}", extra=["if frame == 30 then w8(0x0BCE, 2); w8(0x0BAA, 0x0E); w8(0x0BAB, 0) end"]),
        "hurt_armor": run(200, "return {}", extra=["w8(0x1F99, r8(0x1F99) | 0x04)",
                                                   "if frame == 30 then w8(0x0BCE, 2); w8(0x0BAA, 0x0E); w8(0x0BAB, 0) end"]),
    }
    if "--cached" in sys.argv:
        out = json.load(open(CACHE))
    else:
        if not Path(STATE).exists():
            sys.exit("run verify_armored_armadillo.py first (it makes the fight-start state)")
        print(f"running {len(runs)} emulator sessions, 4 at a time...", flush=True)
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    t = {k: P(v) for k, v in out.items()}
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # --- walking ------------------------------------------------------------------------------
    w = t["walk"]
    ws = w.starts(2)
    ph = w.phase(ws[0]) if ws else []
    st4 = w.starts(4)
    xs = [e["x"] for e in w.x if e["step"] == 4]
    steps = collections.Counter(b - a for a, b in zip(xs, xs[1:]))
    check("walk: Left/Right starts step 2 (vx $100) for 5 frames, then step 4 at speed $178 (1 or 2 px a frame)",
          ws and len(ph) in (4, 5) and st4 and abs(w.at[st4[0]["f"] + 1]["vx"]) == sp[4][0] and set(steps) <= {1, 2},
          f"step 2 for {len(ph)} frames, vx {st4 and w.at[st4[0]['f'] + 1]['vx']}, x steps {dict(steps)}")
    rate = (xs[-1] - xs[0]) / (len(xs) - 1) if len(xs) > 1 else 0
    check("walk: 376/256 = 1.47 px a frame on average", abs(rate - 0x178 / 256) < 0.03, f"{rate:.3f} px/frame")
    wl = t["walk_left"]
    l4 = wl.starts(4)
    l4b = wl.at.get(l4[0]["f"] + 1) if l4 else None      # (the first step-4 frame still has step 2's vx)
    check("walk left: vx −$178, facing 0", l4b and l4b["vx"] == -sp[4][0] and l4b["facing"] == 0,
          f"{l4b and (l4b['vx'], l4b['facing'])}")
    stop = [e for a, e in zip(w.x, w.x[1:]) if a["step"] == 4 and e["step"] == 0]
    check("walk: letting go returns to step 0 at once", stop, f"{len(stop)}")

    # --- jumping ------------------------------------------------------------------------------
    j = t["jump"]
    js = j.starts(6)
    up = j.phase(js[0]) if js else []
    vys = [e["vy"] for e in up]
    dv = collections.Counter(a - b for a, b in zip(vys, vys[1:]))
    check(f"jump: step 6 with vy ${sp[6][1]:X} and gravity {sp[6][2]} (vy −{sp[6][2]} a frame)",
          js and up and up[0]["grav"] == sp[6][2] and vys[0] in (sp[6][1], sp[6][1] - sp[6][2]) and set(dv) <= {sp[6][2], 0},
          f"vy {vys[:3]}, steps {dict(dv)}")
    top = min(e["y"] for e in j.x) if j.x else 0
    base = j.x[0]["y"] if j.x else 0
    check("jump: rises about 56 px (vy² / 2g), then falls (step 8) and lands (step $0A, sound)",
          j.starts(8) and j.starts(10) and 50 <= base - top <= 62, f"height {base - top}")
    land = j.starts(10)
    lp = j.phase(land[0]) if land else []
    check("landing: step $0A for 4 frames, then step 0", lp and len(lp) in (3, 4) and j.at.get(lp[-1]["f"] + 1, {}).get("step") == 0,
          f"{len(lp)} frames")
    sj = t["jump_short"]
    rel = [e for a, e in zip(sj.x, sj.x[1:]) if a["step"] == 6 and e["step"] == 8]
    ht = (sj.x[0]["y"] - min(e["y"] for e in sj.x)) if sj.x else 0
    check("jump released early: next frame step 8 with vy reset to 0 (a short hop)", rel and rel[0]["vy"] <= 0
          and ht < 25, f"vy after release {rel and rel[0]['vy']}, height {ht}")

    # --- walls --------------------------------------------------------------------------------
    wa = t["wall"]
    so = t["slide"]
    sl = so.starts(0x12)
    slp = so.phase(sl[0]) if sl else []
    vy_sl = [e["vy"] for e in slp]
    check("wall slide (step $12): touching a wall in the air while pressing toward it; vy 0 for the first 8 frames, "
          f"then vy {sp[0x12][1]} (2 px a frame down)", sl and vy_sl[:8].count(0) >= 6 and sp[0x12][1] in vy_sl,
          f"{len(slp)} frames, vy {vy_sl[:10]}")
    wj = wa.starts(0x10)
    wjp = wa.phase(wj[0]) if wj else []
    push = [e for e in wjp if e["sub"] == 4]
    check("wall jump (step $10): jump on a wall -> 4 frames, then vx $178 away from it for 8 frames, then a jump "
          "(still held) or a fall", wj and push and abs(push[0]["vx"]) == sp[0x10][0] and
          (push[0]["vx"] < 0) and len(push) in (7, 8, 9), f"{len(wjp)} frames, push {[e['vx'] for e in push][:3]} "
                                                          f"for {len(push)}")

    # --- dash ---------------------------------------------------------------------------------
    d = t["dash"]
    ds = d.starts(0x14)
    dp = d.phase(ds[0]) if ds else []
    check(f"dash (step $14, needs upgrades bit 3 = $08): vx ${sp[0x14][0]:X} for 32 frames (t52 counts down)",
          ds and dp and abs(dp[1]["vx"] if len(dp) > 1 else 0) == sp[0x14][0] and len(dp) in range(30, 36)
          and not t["no_dash"].starts(0x14), f"{len(dp)} frames, vx {dp and dp[min(1, len(dp) - 1)]['vx']}")
    dj = t["dash_jump"]
    djs = dj.starts(6)
    check("dash jump: jumping out of a dash keeps the dash speed in the air (spd $375)",
          djs and djs[0]["spd"] == sp[0x14][0], f"{djs and djs[0]['spd']}")

    # --- shots --------------------------------------------------------------------------------
    s = t["shots"]
    ls = s.lives()
    vx = collections.Counter(next((e["vx"] for e in l[1:] if e["vx"]), 0) for l in ls)
    alive = collections.Counter()
    for e in s.ev:
        if e["tag"] == "xs":
            alive[e["f"]] += 1
    check("buster: each press fires a shot (X shot list $1228, id 0), at most 3 on screen", ls and all(l[0]["id"] == 0
          for l in ls) and max(alive.values()) <= 3, f"{len(ls)} shots, speeds {dict(vx)}, max on screen {max(alive.values()) if alive else 0}")
    ch = {}
    for n in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120):
        x = t[f"charge{n}"]
        l = x.lives()
        ch[n] = sorted({k[0]["id"] for k in l})
    check("charging: holding the shoot button and letting go fires a bigger shot after long enough (ids by hold time)",
          ch[10] == [0] and any(v != [0] for v in ch.values()), f"{ch}")

    # --- hurt ---------------------------------------------------------------------------------
    h = t["hurt"]
    hs = h.starts(0x0E)
    hp = h.phase(hs[0]) if hs else []
    first = hp[1] if len(hp) > 1 else (hp[0] if hp else {})
    check(f"hurt (step $0E): hurt_lock 8, knocked back (vx {sp[0x0E][0]} against his facing), vy {sp[0x0E][1]}, gravity 64",
          hs and first.get("lock") == 8 and abs(first.get("vx", 0)) == abs(sp[0x0E][0]),
          f"{first and (first['lock'], first['vx'], first['vy'], first['facing'])}")
    after = h.at.get(hp[-1]["f"] + 1) if hp else None
    check("hurt: when the animation ends, flash_timer 60 and back to step 0 (on the floor)", after and after["step"] == 0
          and after["flash"] in (59, 60), f"{after and (after['step'], after['flash'])}")
    fl = [e for e in h.x if e["flash"]]
    unlock = next((e for a, e in zip(h.x, h.x[1:]) if a["flash"] == 1 and e["flash"] == 0), None)
    check("flash_timer counts down 60 frames; at 0 hurt_lock is cleared", fl and unlock and unlock["lock"] == 0,
          f"{len(fl)} flashing frames")
    ha = t["hurt_armor"]
    has = ha.starts(0x0E)
    hap = ha.phase(has[0]) if has else []
    a1 = hap[1] if len(hap) > 1 else {}
    check("armor (upgrades bit 2 = $04) halves the knockback's vy", a1 and first and abs(a1.get("vy", 0) - first.get("vy", 0) // 2) <= 64,
          f"vy {first.get('vy') if first else None} -> {a1.get('vy')}")

    report(results)


if __name__ == "__main__":
    main()
