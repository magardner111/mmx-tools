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
                               text=True, timeout=self.frames / 30 + 120)
        for line in p.stdout.splitlines():
            if line.startswith("#"):
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
