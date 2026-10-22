"""
Checks the boss room data (rooms.py) against the game: loads each boss's fight-start state in Mesen and reads the
camera, the camera borders, X's and the boss's positions, and every 16x16 collision cell of the screen through the
game's own lookup (scene grid $7E:E800, map $7E:2000, table at collision_table_ptr $0B92). The ROM's grid
(testwarp.collision_at) must match cell for cell.

    python3 verify_rooms.py          # under a minute; needs every boss's fight-start state (run their suites first)
    python3 verify_rooms.py --cached
"""
import json
import sys
from pathlib import Path

from mmx1 import MMX1
from mesen_verify import Run, run_all, report
from rooms import ROOMS, MEASURED, collision_grid, SCREEN_W, SCREEN_H

CACHE = "work/rooms_runs.json"
# at frame 20: camera, borders, X, boss, then the collision rows of the screen (hex bytes)
LUA = """if frame == 20 then
  local l, t = r16(0x1E4D), r16(0x1E50)
  out("room", "l=" .. l .. " t=" .. t .. " bl=" .. r16(0x1E5E) .. " br=" .. r16(0x1E60) .. " bt=" .. r16(0x1E68) ..
      " bb=" .. r16(0x1E6E) .. " xx=" .. r16(0x0BAD) .. " xy=" .. r16(0x0BB0))
  local b = find(0x0E68, 0x1228, BOSS)
  if b then out("boss", "x=" .. r16(b + 5) .. " y=" .. r16(b + 8)) end
  local ptr = r16(0x0B92) + r8(0x0B94) * 65536
  local x0, y0 = l - l % 16, t - t % 16
  local row = 0
  for y = y0, t + 223, 16 do
    local s = ""
    for x = x0, l + 255, 16 do
      local scene = r8(0x7EE800 + (y >> 8) * 32 + (x >> 8))
      local map = r16(0x7E2000 + scene * 0x200 + ((y & 0xF0) << 1) + (((x & 0xFF) >> 3) & 0xFE))
      s = s .. string.format("%02x", r8(ptr + map))
    end
    out("coll", "row=" .. row .. " hex=h" .. s)        -- (h: keeps an all-digit row a string)
    row = row + 1
  end
end"""


def main():
    missing = [r["state"] for r in ROOMS.values() if not Path(r["state"]).exists()]
    if missing and "--cached" not in sys.argv:
        sys.exit(f"missing fight-start states (run those bosses' suites): {missing}")
    if "--cached" in sys.argv:
        out = json.load(open(CACHE))
    else:
        runs = {}
        for key, r in ROOMS.items():
            run = Run(level=r["level"], frames=30, infinite_hp=True, savestate=r["state"], **r["run"])
            run.each_frame(LUA.replace("BOSS", str(r["boss_id"])))
            Path("work/rooms").mkdir(parents=True, exist_ok=True)
            run.screenshot(20, f"work/rooms/{key}_game.png")        # the room as the game draws it (with sprites)
            runs[key] = run
        out = dict(zip(runs, run_all(list(runs.values()))))
        json.dump(out, open(CACHE, "w"))
    g = MMX1("work/hack.sfc")
    results, measured = [], {}

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    for key, ev in out.items():
        r = ROOMS[key]
        room = next((e for e in ev if e["tag"] == "room"), None)
        boss = next((e for e in ev if e["tag"] == "boss"), None)
        rows = sorted((e for e in ev if e["tag"] == "coll"), key=lambda e: e["row"])
        if not room:
            check(f"{key}: fight state loads", False)
            continue
        cam = [room["l"], room["t"]]
        game = [[int(e["hex"][1:][i:i + 2], 16) for i in range(0, len(e["hex"]) - 1, 2)] for e in rows]
        rom = collision_grid(g, r["level"], *cam)
        cells = sum(len(row) for row in rom)
        diff = [(y, x) for y, row in enumerate(rom) for x, v in enumerate(row)
                if y >= len(game) or x >= len(game[y]) or game[y][x] != v]
        if r.get("runtime_collision"):
            check(f"{key}: collision differs from the ROM's layout (map rewritten while the stage runs); the game's "
                  "grid is used", diff, f"camera {cam}, {len(diff)} cells differ")
        else:
            check(f"{key}: collision of the screen from the ROM = the game's lookup ({cells} cells)", not diff,
                  f"camera {cam}, {len(diff)} differences {diff[:4]}")
        locked = room["bl"] == room["br"] == cam[0] or (room["bl"] <= cam[0] <= room["br"])
        check(f"{key}: camera inside its borders", locked, f"borders x {room['bl']}..{room['br']}, y {room['bt']}..{room['bb']}")
        check(f"{key}: boss present on the first fight frame", boss is not None,
              f"boss {boss and (boss['x'], boss['y'])}, X {(room['xx'], room['xy'])}")
        measured[key] = dict(camera=cam, borders=[room["bl"], room["br"], room["bt"], room["bb"]],
                             x=[room["xx"], room["xy"]], boss=[boss["x"], boss["y"]] if boss else None, collision=game)
    MEASURED.parent.mkdir(parents=True, exist_ok=True)
    MEASURED.write_text(json.dumps(measured, indent=1))
    report(results)


if __name__ == "__main__":
    main()
