"""
Run a test ROM headless in Mesen 2 with a generated Lua script and get back what happened.

    from mesen_verify import Run
    run = Run(level=8, x=7560, frames=1800, seed=0x1234, infinite_hp=True)
    run.track(0x02)                          # one line per frame for enemy id 2 (Chill Penguin)
    run.on_exec(0x81C019, "choose")          # log each call of a routine (A, X, Y, D = object)
    run.on_write(0x1F0C, "boss_defeated")    # log each write to an address (value, code address)
    run.action_replay(NO_DAMAGE)             # X takes no damage and walks through enemies
    run.input("return {right = r16(0x0BAD) < 7720}")   # Lua deciding the buttons each frame
    events = run.go()                        # list of dicts: {"f": frame, "tag": ..., ...}

Mesen runs at about 64 frames/s on the Pi (CPU-bound), so `run_all` runs several at once (one per core).
Needs Mesen 2 (../emulator/mesen.sh sets DOTNET_ROOT) and the project ROM work/hack.sfc.
"""
import collections
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mmx1 import MMX1, save_rom
from testwarp import make_test_rom

HERE = Path(__file__).parent
MESEN = HERE.parent / "emulator" / "mesen.sh"
NO_DAMAGE = "7E0BD808"           # Action Replay: X's hurt lock (X + $30) held at 8
ENEMIES = (0x0E68, 0x1228)       # alloc_enemy list (0x40 bytes per object)
LISTS = {"enemy": (0x0E68, 0x1228), "shot": (0x1428, 0x1628), "misc": (0x1628, 0x1928), "effect": (0x1928, 0x1D28)}
# fields printed every frame for tracked objects: (name, offset, size); vx/vy signed
TRACK_FIELDS = [("state", 0x01, 1), ("step", 0x02, 1), ("sub", 0x03, 1), ("hp", 0x27, 1), ("dmg", 0x28, 1),
                ("anim", 0x0F, 1), ("attr", 0x11, 1), ("air", 0x2F, 1), ("f30", 0x30, 1), ("f33", 0x33, 1),
                ("f34", 0x34, 1), ("f35", 0x35, 1), ("f36", 0x36, 1), ("f37", 0x37, 1), ("f38", 0x38, 1),
                ("f39", 0x39, 1), ("touch", 0x2B, 1), ("f3A", 0x3A, 1), ("f3B", 0x3B, 1), ("f3C", 0x3C, 1),
                ("f31", 0x31, 1), ("f32", 0x32, 1), ("f3D", 0x3D, 1), ("f3E", 0x3E, 1),
                ("x", 0x05, 2), ("y", 0x08, 2), ("vx", 0x1A, 2), ("vy", 0x1C, 2), ("grav", 0x1E, 1),
                ("key", 0x17, 1), ("parent", 0x0C, 2)]

LUA_HEAD = r"""
local mt = emu.memType.snesMemory
local frame = 0
local function r8(a) return emu.read(a, mt) end
local function r16(a) return emu.read(a, mt) + emu.read(a + 1, mt) * 256 end
local function s16(a) local v = r16(a); if v >= 0x8000 then v = v - 0x10000 end; return v end
local function w8(a, v) emu.write(a, v & 0xFF, mt) end
local function w16(a, v) w8(a, v); w8(a + 1, v >> 8) end
local function out(tag, s) print(string.format("@%d|%s|%s", frame, tag, s or "")) end
local function find(lo, hi, id)
  for a = lo, hi - 0x40, 0x40 do if r8(a) ~= 0 and r8(a + 0x0A) == id then return a end end
end
local function count(lo, hi, id)
  local n = 0
  for a = lo, hi - 0x40, 0x40 do if r8(a) ~= 0 and r8(a + 0x0A) == id then n = n + 1 end end
  return n
end
"""


class Run:
    def __init__(self, level, x, y=None, frames=1200, seed=None, infinite_hp=False, rom=None, patch=None,
                 savestate=None):
        """patch: optional function(MMX1) applied to the test ROM (e.g. change a boss value).
        savestate: a Mesen .mss file to load on frame 1 instead of using the warp (made in the Mesen window
        with Shift+F1; same ROM build). Test Lua has no file access, so its bytes go into the script."""
        self.level, self.x, self.y, self.frames = level, x, y, frames
        self.seed, self.infinite_hp = seed, infinite_hp
        self.rom = Path(rom or HERE / "work" / "hack.sfc")
        self.patch = patch
        self.savestate = savestate
        self.tracked, self.execs, self.writes, self.reads, self.counts = [], [], [], [], []
        self.shots, self.pokes, self.ar_codes, self.input_lua, self.every_frame_lua = [], [], [], None, []
        self.hooks, self.calls, self.state_out = [], [], None

    # --- what to observe -----------------------------------------------------------------
    def track(self, obj_id, lst="enemy", tag=None):
        self.tracked.append((obj_id, lst, tag or f"obj{obj_id:02X}"))
        return self

    def on_exec(self, addr, tag):
        self.execs.append((addr, tag))
        return self

    def on_write(self, addr, tag):
        self.writes.append((addr, tag))
        return self

    def on_read(self, addr, tag):
        """Log each read of an address (value, code address)."""
        self.reads.append((addr, tag))
        return self

    def count_objects(self, obj_id, lst, tag):
        """Print how many objects with this id are in a list whenever the number changes."""
        self.counts.append((obj_id, lst, tag))
        return self

    # --- what to change ------------------------------------------------------------------
    def poke(self, frame, addr, value, size=1):
        self.pokes.append((frame, addr, value, size))
        return self

    def action_replay(self, code):
        """Pro Action Replay code AAAAAAVV: write VV to $AAAAAA every frame, as the cheat device does.
        NO_DAMAGE (7E0BD808) keeps X's hurt lock at 8: no damage, no knockback, enemies pass through."""
        self.ar_codes.append((int(code[:6], 16), int(code[6:8], 16)))
        return self

    def screenshot(self, frame, path):
        """Save a PNG of this frame (sent over stdout as hex, so it works without Lua file access)."""
        self.shots.append((frame, str(path)))
        return self

    def hold(self, addr, value, size=1, when="true"):
        """Write `value` (a number or a Lua expression) to `addr` at the end of every frame while `when` holds,
        e.g. pin X's x: hold(0x0BAD, 7800, 2, "find(0x0E68, 0x1228, 0x0C)")."""
        self.every_frame_lua.append(f"if {when} then w{8 * size}(0x{addr:04X}, {value}) end")
        return self

    def at_exec(self, addr, lua):
        """Raw Lua run each time the instruction at `addr` is about to execute. It has `s` (emu.getState()) and
        setreg(name, v) to change a CPU register before the instruction runs ("cpu.a", "cpu.x", "cpu.y", ...),
        e.g. force random's result: at_exec(0x8796B8, 'setreg("cpu.a", 5)')."""
        self.hooks.append((addr, lua))
        return self

    def save_state(self, when, path):
        """Save a Mesen state (bytes, for Run(savestate=...)) the first frame `when` (Lua) is true."""
        self.state_out = (when, str(path))
        return self

    def call(self, at, target, when="true", a=None, x=None, y=None, d=None, db=None, m8=True, x8=True,
             rts=False, tag="call", watch=True, timeout=600, pre=""):
        """Call the routine `target` once, from the instruction at `at` (which must run in a context the
        routine expects, e.g. a boss's update so D = his slot), the first time `when` (Lua) is true there.
        A fake JSL: the return address is pushed and PC set to `target`; when it returns to `at`, the CPU
        registers are restored and the game carries on. `rts`: the routine ends in RTS, so it is entered
        through an RTL found in its own bank. Logs "<tag>" start/return (registers on return), every RAM
        write during the call ("<tag>_w": addr, value, pc) if `watch`, and "<tag>_timeout" if it never
        returns within `timeout` frames (crashed or stuck). a/x/y/d/db may be numbers or Lua expressions;
        `pre` is Lua run just before the call (e.g. to write the routine's inputs to RAM)."""
        self.calls.append(dict(at=at, target=target, when=when, a=a, x=x, y=y, d=d, db=db, m8=m8, x8=x8,
                               rts=rts, tag=tag, watch=watch, timeout=timeout, pre=pre))
        return self

    def input(self, lua_body):
        """Lua function body returning the button table for this frame (has frame, r8, r16, s16)."""
        self.input_lua = lua_body
        return self

    def each_frame(self, lua):
        """Raw Lua run at the end of every frame (has frame, r8, r16, w8, w16, out, find, count)."""
        self.every_frame_lua.append(lua)
        return self

    # --- running ---------------------------------------------------------------------------
    def lua(self):
        L = [LUA_HEAD]
        if self.savestate:
            # emu.loadSavestate only works from inside a memory callback, not a frame event
            data = Path(self.savestate).read_bytes()
            L.append('local state = "' + "".join(f"\\{b}" for b in data) + '"')
            L.append("""local loaded = false
emu.addMemoryCallback(function()
  if frame >= 1 and not loaded then loaded = true; emu.loadSavestate(state) end
end, emu.callbackType.exec, 0x808000, 0x80FFFF)""")
        for addr, lua in self.hooks:
            L.append(f"""emu.addMemoryCallback(function()
  local s = emu.getState()
  local function setreg(k, v) s[k] = v; emu.setState(s) end
  {lua}
end, emu.callbackType.exec, 0x{addr:06X})""")
        if self.state_out:
            L.append(f"""local state_saved = false
emu.addMemoryCallback(function()
  if not state_saved and ({self.state_out[0]}) then
    state_saved = true
    local st = emu.createSavestate()
    print("#S|" .. (st:gsub(".", function(c) return string.format("%02x", c:byte()) end)))
  end
end, emu.callbackType.exec, 0x808000, 0x80FFFF)""")
        for i, c in enumerate(self.calls):
            L.append(self._call_lua(i, c))
        for addr, tag in self.execs:
            L.append(f"""emu.addMemoryCallback(function()
  local s = emu.getState()
  out("{tag}", string.format("a=%d x=%d y=%d d=%d", s["cpu.a"], s["cpu.x"], s["cpu.y"], s["cpu.d"]))
end, emu.callbackType.exec, 0x{addr:06X})""")
        for kind, lst in (("write", self.writes), ("read", self.reads)):
            for addr, tag in lst:
                # low RAM is reachable through many banks ($00:, $7E:, $86: with DB=$86...): watch the RAM itself
                space, off = ("snesWorkRam", addr & 0x1FFFF) if addr < 0x2000 or addr >> 17 == 0x3F else ("snesMemory", addr)
                L.append(f"""emu.addMemoryCallback(function(a, v)
  local s = emu.getState()
  out("{tag}", string.format("v=%d pc=%d", v, s["cpu.k"] * 65536 + s["cpu.pc"]))
end, emu.callbackType.{kind}, 0x{off:04X}, 0x{off:04X}, emu.cpuType.snes, emu.memType.{space})""")
        if self.input_lua:
            L.append(f"""local function buttons() {self.input_lua} end
emu.addEventCallback(function() emu.setInput(buttons() or {{}}, 0) end, emu.eventType.inputPolled)""")
        body = []
        if self.seed is not None:
            # after the reset code has set its own seed ($0D37 at $80:8077, done by frame 2)
            body.append(f"if frame == 60 then w16(0x0BA6, {self.seed}) end")
        for f, a, v, size in self.pokes:
            body.append(f"if frame == {f} then w{8 * size}(0x{a:04X}, {v}) end")
        for a, v in self.ar_codes:
            body.append(f"w8(0x{a:06X}, {v})")
        if self.infinite_hp:
            body.append("if r8(0x0BCF) & 0x7F > 0 and r8(0x0BCF) & 0x7F < 16 then w8(0x0BCF, 0x80 | 16) end")
        for i, (obj_id, lst, tag) in enumerate(self.tracked):
            lo, hi = LISTS[lst]
            vals = " .. ".join(f'"|{n}=" .. ' + (f"s16(a + 0x{o:02X})" if n in ("vx", "vy") else f"r{8 * s}(a + 0x{o:02X})")
                               for n, o, s in TRACK_FIELDS)
            body.append(f"""do local a = find(0x{lo:04X}, 0x{hi:04X}, {obj_id})
  if a then out("{tag}", "slot=" .. a .. {vals}); seen{i} = true
  elseif seen{i} then out("{tag}", "gone"); seen{i} = false end end""")
            L.append(f"local seen{i} = false")
        for i, (obj_id, lst, tag) in enumerate(self.counts):
            lo, hi = LISTS[lst]
            L.append(f"local cnt{i} = 0")
            body.append(f"""do local n = count(0x{lo:04X}, 0x{hi:04X}, {obj_id})
  if n ~= cnt{i} then out("{tag}", "n=" .. n); cnt{i} = n end end""")
        for i, (f, _) in enumerate(self.shots):
            body.append(f'if frame == {f} then local p = emu.takeScreenshot(); '
                        f'print("#{i}|" .. (p:gsub(".", function(c) return string.format("%02x", c:byte()) end))) end')
        body += self.every_frame_lua
        body.append(f"if frame >= {self.frames} then out('end', '') emu.stop(0) end")
        L.append("emu.addEventCallback(function()\n  frame = frame + 1\n  "
                 + "\n  ".join(body) + "\nend, emu.eventType.endFrame)")
        return "\n".join(L)

    def _call_lua(self, i, c):
        rom = make_test_rom(MMX1(self.rom), self.level, self.x, self.y).rom
        ps = (0x20 if c["m8"] else 0) | (0x10 if c["x8"] else 0)
        bank, tgt = c["target"] >> 16, c["target"] & 0xFFFF
        rtl = None
        if c["rts"]:                     # an RTL byte in the routine's bank, to come back through
            from mmx1 import snes2pc
            base = snes2pc(bank << 16 | 0x8000)
            rtl = (bank << 16 | 0x8000) + rom[base:base + 0x8000].index(0x6B)
        regs = "".join(f'st["cpu.{r}"] = {v}; ' for r, v in (("a", c["a"]), ("x", c["x"]), ("y", c["y"]),
                                                          ("d", c["d"]), ("dbr", c["db"])) if v is not None)
        push_rts = (f'push(0x{(rtl - 1) >> 8 & 0xFF:02X}); push(0x{(rtl - 1) & 0xFF:02X}); ' if rtl else "")
        t = c["tag"]
        return f"""local call{i} = {{state = 0}}
local function call{i}_w(a, v)
  if call{i}.state == 1 then local s = emu.getState(); out("{t}_w", string.format("addr=%d v=%d pc=%d", a & 0x1FFFF, v, s["cpu.k"] * 65536 + s["cpu.pc"])) end
end
emu.addMemoryCallback(function()
  local c = call{i}
  if c.state == 0 and ({c["when"]}) then
    {c["pre"]}
    local st = emu.getState()
    c.saved = emu.getState(); c.state = 1; c.frame = frame
    local sp = st["cpu.sp"]
    local function push(v) emu.write(sp, v, emu.memType.snesWorkRam); sp = sp - 1 end
    local ret = 0x{c["at"] & 0xFFFF:04X} - 1
    push(0x{c["at"] >> 16:02X}); push(ret >> 8); push(ret & 0xFF)
    {push_rts}st["cpu.sp"] = sp
    st["cpu.pc"] = 0x{tgt:04X}; st["cpu.k"] = 0x{bank:02X}
    st["cpu.ps"] = (st["cpu.ps"] & 0xCF) | 0x{ps:02X}
    {regs}
    emu.setState(st)
    out("{t}", string.format("start=1 a=%d x=%d y=%d d=%d sp=%d", st["cpu.a"], st["cpu.x"], st["cpu.y"], st["cpu.d"], sp))
  elseif c.state == 1 then
    local s = emu.getState()
    out("{t}", string.format("ret=1 a=%d x=%d y=%d d=%d ps=%d sp=%d frames=%d", s["cpu.a"], s["cpu.x"], s["cpu.y"],
        s["cpu.d"], s["cpu.ps"], s["cpu.sp"], frame - c.frame))
    c.state = 2
    for k, v in pairs(c.saved) do if k:sub(1, 4) == "cpu." then s[k] = v end end
    emu.setState(s)
  end
end, emu.callbackType.exec, 0x{c["at"]:06X})
{"" if not c["watch"] else f'emu.addMemoryCallback(call{i}_w, emu.callbackType.write, 0x0000, 0x1FFFF, emu.cpuType.snes, emu.memType.snesWorkRam)'}
emu.addEventCallback(function()
  if call{i}.state == 1 and frame - call{i}.frame > {c["timeout"]} then out("{t}_timeout", ""); call{i}.state = 3 end
end, emu.eventType.endFrame)"""

    def go(self, keep=None):
        g = make_test_rom(MMX1(self.rom), self.level, self.x, self.y)
        if self.patch:
            self.patch(g)
        with tempfile.TemporaryDirectory() as tmp:
            rom, script = Path(tmp) / "t.sfc", Path(tmp) / "t.lua"
            save_rom(g, rom)
            script.write_text(self.lua())
            if keep:
                Path(keep).write_text(script.read_text())
            p = subprocess.run([str(MESEN), "--testrunner", str(rom), str(script)], capture_output=True,
                               text=True, timeout=self.frames / 8 + 180)
        for line in p.stdout.splitlines():
            if line.startswith("#S|"):
                Path(self.state_out[1]).write_bytes(bytes.fromhex(line[3:]))
            elif line.startswith("#"):
                i, _, data = line[1:].partition("|")
                Path(self.shots[int(i)][1]).write_bytes(bytes.fromhex(data))
        return parse(p.stdout)


def parse(text):
    events = []
    for line in text.splitlines():
        if not line.startswith("@"):
            continue
        f, tag, rest = line[1:].split("|", 2)
        e = {"f": int(f), "tag": tag}
        for kv in rest.replace("|", " ").split():
            k, _, v = kv.partition("=")
            e[k] = int(v) if v.lstrip("-").isdigit() else v
        events.append(e)
    return events


def run_all(runs, workers=None):
    """Run several Runs at once (Mesen is single-threaded; the Pi has 4 cores)."""
    with ThreadPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        return list(ex.map(lambda r: r.go(), runs))


def fight_state(path, level, x, inp, when, frames=2000, **kw):
    """Play up to the start of a fight once and save a Mesen state there (Run(savestate=path) then starts
    from it). `when` is Lua that is true on the first frame of the fight. ROM patches given to later Runs
    still apply (a state holds RAM, not ROM), except for values the game already copied into RAM."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).unlink(missing_ok=True)
    Run(level=level, x=x, frames=frames, infinite_hp=True, **kw).input(inp).save_state(when, path).go()
    if not Path(path).exists():
        raise RuntimeError(f"fight never started: no state saved to {path}")
    return str(path)


def countdown(recs, field, start):
    """True if a timer field counts down from `start` to 1 over these per-frame records (one phase), allowing
    repeated values: on busy frames the game skips object updates, so frame counts run long but the timer
    doesn't. Returns (ok, first value, last value)."""
    v = [r[field] for r in recs]
    ok = bool(v) and v[0] == start and v[-1] == 1 and all(a - b in (0, 1) for a, b in zip(v, v[1:]))
    return ok, (v[0] if v else None), (v[-1] if v else None)


def shot_log(tag, ids, lo=0x1428, hi=0x1628):
    """Lua for each_frame: one line per live object in a list whose id is in `ids` (default: enemy shots)."""
    cond = " or ".join(f"r8(a + 10) == {i}" for i in ids)
    return (f'for a = 0x{lo:04X}, 0x{hi - 0x40:04X}, 0x40 do if r8(a) ~= 0 and ({cond}) then out("{tag}", "slot=" .. a .. '
            '" id=" .. r8(a + 10) .. " sub=" .. r8(a + 11) .. " state=" .. r8(a + 1) .. " x=" .. r16(a + 5) .. " y=" .. '
            'r16(a + 8) .. " vx=" .. s16(a + 0x1A) .. " vy=" .. s16(a + 0x1C) .. " attr=" .. r8(a + 0x11) .. " f2C=" .. '
            'r8(a + 0x2C)) end end')


X_LOG = ('if r16(0x0BAD) ~= lastx or r16(0x0BB0) ~= lasty or r8(0x0BAA) ~= laststep or r8(0x0C06) ~= lastt '
         'or r8(0x0C32) ~= lastu or r8(0x0BCF) ~= lasthp then out("X", "x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0) .. '
         '" step=" .. r8(0x0BAA) .. " touch=" .. r8(0x0C06) .. " untouchable=" .. r8(0x0C32) .. " stun=" .. r8(0x0C2D) .. '
         '" hp=" .. r8(0x0BCF)); lastx = r16(0x0BAD); lasty = r16(0x0BB0); laststep = r8(0x0BAA); lastt = r8(0x0C06); '
         'lastu = r8(0x0C32); lasthp = r8(0x0BCF) end')
"""each_frame Lua: a line whenever X's position, step, terrain bits, untouchable flag or HP changes (tag "X")."""


class Fight:
    """Helpers over one run's events for a boss tracked with Run.track(..., tag=tag) (exec/hook events have
    f = frame - 1, per-frame records f = frame). X's state comes from X_LOG lines, objects from shot_log."""
    def __init__(self, ev, tag):
        self.ev = ev
        self.by_tag = collections.defaultdict(list)
        for e in ev:
            self.by_tag[e["tag"]].append(e)
        self._calls = {}
        self.p = [e for e in self.by_tag[tag] if "slot" in e]
        self.slot = self.p[0]["slot"] if self.p else None
        self.at = {e["f"]: e for e in self.p}
        xs = self.by_tag["X"]
        self.x, i, cur = {}, 0, None
        for f in range(0, (ev[-1]["f"] if ev else 0) + 1):
            while i < len(xs) and xs[i]["f"] <= f:
                cur, i = xs[i], i + 1
            if cur:
                self.x[f] = cur

    def calls(self, tag, mine=True):
        """Exec events of `tag`; mine = only those made with D = the boss's slot."""
        k = (tag, mine)
        if k not in self._calls:
            self._calls[k] = [e for e in self.by_tag[tag] if not mine or e.get("d") == self.slot]
        return self._calls[k]

    def called(self, tag, f, a=None, mine=False):
        """True if `tag` ran on the frame before record f (with A's low byte = a)."""
        return any(c["f"] == f - 1 and (a is None or c["a"] & 0xFF == a) for c in self.calls(tag, mine))

    def starts(self, cond):
        return [e for i, e in enumerate(self.p) if cond(e) and (i == 0 or not cond(self.p[i - 1]))]

    @staticmethod
    def fight(step, sub=None):
        return lambda e: e["state"] == 4 and e["step"] == step and (sub is None or e["sub"] == sub)

    def phase(self, s, key=("state", "step", "sub")):
        """The records from s while the fields in key stay the same ([] if it never ends in the run)."""
        out, k0 = [], tuple(s[k] for k in key)
        for f in range(s["f"], s["f"] + 5000):
            e = self.at.get(f)
            if e is None:
                return []
            if tuple(e[k] for k in key) != k0:
                return out
            out.append(e)
        return []

    def after(self, s):
        ph = self.phase(s)
        return self.at.get(ph[-1]["f"] + 1) if ph else None

    def lives(self, tag):
        """Objects logged by shot_log(tag, ...): per slot, split into lives (a frame gap starts a new one)."""
        per = collections.defaultdict(list)
        for e in self.by_tag[tag]:
            per[e["slot"]].append(e)
        out = []
        for recs in per.values():
            cur = [recs[0]]
            for a, b in zip(recs, recs[1:]):
                if b["f"] != a["f"] + 1 or b["id"] != a["id"]:
                    out.append(cur)
                    cur = []
                cur.append(b)
            out.append(cur)
        return sorted(out, key=lambda l: l[0]["f"])

    def timers(self, step, sub, field, start):
        return [countdown(ph, field, start) for s in self.starts(self.fight(step, sub)) for ph in [self.phase(s)] if ph]


def report(results):
    """Print a suite's (name, ok, detail) results and exit 1 if any failed."""
    import sys
    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:{width}}  {detail}")
    bad = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - bad}/{len(results)} passed")
    print("Run complete: now run the sync-records skill (.claude/skills/sync-records) to update every record.")
    sys.exit(1 if bad else 0)
