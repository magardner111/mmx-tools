"""
Call a routine in the running game and report what it did (see mesen_verify.Run.call).

    python3 probe.py 84A00D --a 40                         # x_stun(40) during Flame Mammoth's fight
    python3 probe.py 849C0E --x 0x0BA8 --x16               # obj_overlaps with X's slot: carry = X touches him?
    python3 probe.py 84A09C --pre "w16(0,0) w16(2,0) w16(4,10) w16(6,0)" --a16 --x16
    python3 probe.py 879663 --rts                          # a routine ending in RTS (entered through an RTL)

By default it starts from Flame Mammoth's fight state (work/states/flame_mammoth_fight.mss, made by
verify_flame_mammoth.py) and calls from the start of his update ($87:91A7, direct page = his slot) on the
first frame `--when` holds (default: 60 frames in). Use --at/--state/--level/--xpos to call from elsewhere.
It prints whether it returned (or timed out: stuck or crashed), the registers and flags on return, every RAM
write during the call with its name where we have one, and saves screenshots of the first and last frame\n(work/probe/start.png, end.png).
"""
import argparse
import collections
from pathlib import Path

import lift
from mesen_verify import Run, LISTS

FLAGS = "CZIDXMVN"


def name_of(addr):
    if addr in lift.RAM_NAMES:
        return lift.RAM_NAMES[addr]
    if 0x0BA8 <= addr < 0x0C38:
        return f"X+${addr - 0x0BA8:02X}"
    for lst, (lo, hi) in LISTS.items():
        if lo <= addr < hi:
            off = (addr - lo) % 0x40
            return f"{lst}[{(addr - lo) // 0x40}]+${off:02X} {lift.FIELDS.get(off, '')}".rstrip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="routine address, e.g. 84A00D")
    ap.add_argument("--a"), ap.add_argument("--x"), ap.add_argument("--y"), ap.add_argument("--d")
    ap.add_argument("--db")
    ap.add_argument("--a16", action="store_true"), ap.add_argument("--x16", action="store_true")
    ap.add_argument("--rts", action="store_true", help="the routine ends in RTS")
    ap.add_argument("--pre", default="", help="Lua run just before the call (write inputs)")
    ap.add_argument("--at", default="8791A7", help="instruction to call from")
    ap.add_argument("--when", default="frame >= 60")
    ap.add_argument("--state", default="work/states/flame_mammoth_fight.mss")
    ap.add_argument("--level", type=int, default=4), ap.add_argument("--xpos", type=int, default=7552)
    ap.add_argument("--frames", type=int, default=240)
    ap.add_argument("--shots", default="work/probe")
    o = ap.parse_args()
    num = lambda v: None if v is None else (str(int(v, 0)) if v[:1].isdigit() else v)
    r = Run(level=o.level, x=o.xpos, frames=o.frames, infinite_hp=True,
            savestate=o.state if o.state and Path(o.state).exists() else None)
    r.call(int(o.at, 16), int(o.target, 16), when=o.when, a=num(o.a), x=num(o.x), y=num(o.y), d=num(o.d),
           db=num(o.db), m8=not o.a16, x8=not o.x16, rts=o.rts, pre=o.pre, timeout=o.frames)
    Path(o.shots).mkdir(parents=True, exist_ok=True)
    r.screenshot(2, Path(o.shots) / "start.png").screenshot(o.frames - 1, Path(o.shots) / "end.png")
    ev = r.go()
    st = [e for e in ev if e["tag"] == "call"]
    start = next((e for e in st if e.get("start")), None)
    ret = next((e for e in st if e.get("ret")), None)
    if not start:
        print("never called: --when didn't hold at --at (is that code running?)")
        return
    print(f"called on frame {start['f']}: a=${start['a']:04X} x=${start['x']:04X} y=${start['y']:04X} d=${start['d']:04X}")
    if ret:
        fl = " ".join(f for i, f in enumerate(FLAGS) if ret["ps"] >> i & 1)
        print(f"returned after {ret['frames']} frame(s): a=${ret['a']:04X} x=${ret['x']:04X} y=${ret['y']:04X} "
              f"d=${ret['d']:04X} flags [{fl}] stack {'balanced' if ret['sp'] == start['sp'] + (5 if o.rts else 3) else 'UNBALANCED'}")
    else:
        print("did NOT return (stuck or crashed)" + (" - timed out" if any(e["tag"] == "call_timeout" for e in ev) else ""))
    w = [e for e in ev if e["tag"] == "call_w"]
    by = collections.OrderedDict()
    for e in w:
        by.setdefault(e["addr"], []).append(e)
    print(f"{len(w)} RAM writes to {len(by)} addresses:")
    for a, es in by.items():
        vals = " ".join(f"{e['v']:02X}" for e in es[:8]) + (" ..." if len(es) > 8 else "")
        print(f"  ${a:05X}  {name_of(a):34} {vals}   (from ${es[0]['pc'] >> 16:02X}:{es[0]['pc'] & 0xFFFF:04X})")


if __name__ == "__main__":
    main()
