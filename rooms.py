"""
Boss room data for all eight main bosses: where each fight happens, read from the ROM and checked against the game
by verify_rooms.py (camera, borders, starting positions, and every collision cell through the game's own lookup).

    python3 rooms.py            # writes work/rooms/<boss>.json and <boss>.png (the room, cropped from the level;
                                # Storm Eagle's from the game's screenshot, since his deck isn't the ROM's layout)

ROOMS holds how each fight is reached in tests (the same start the boss's verify suite uses) and the room facts
verify_rooms.py confirmed in Mesen. room_data() adds the ROM's collision grid for the camera rectangle.
"""
import json
import sys
from pathlib import Path

from mmx1 import MMX1
from testwarp import collision_at

SCREEN_W, SCREEN_H = 256, 224

# boss key -> how its suite reaches the fight (Run args + fight-start state) and the fight's room, as measured on the
# first fight frame (camera left/top = $1E4D/$1E50; borders = $1E5E/$1E60/$1E68/$1E6E; X and boss positions).
# Filled from verify_rooms.py's output; every value there is checked against the game.
ROOMS = {
    "chill_penguin": dict(level=8, run=dict(x=7560), state="work/states/chill_penguin_fight.mss", boss_id=0x02),
    # the deck he fights on isn't the ROM's layout: by the fight the level map in RAM has a flat deck at y 224
    # (seen in Mesen), so this room's collision is taken from the game
    "storm_eagle": dict(level=5, run=dict(x=6302), state="work/states/storm_eagle_fight.mss", boss_id=0x52,
                        runtime_collision=True),
    "flame_mammoth": dict(level=4, run=dict(x=7552), state="work/states/flame_mammoth_fight.mss", boss_id=0x0C),
    "spark_mandrill": dict(level=6, run=dict(x=7296), state="work/states/spark_mandrill_fight.mss", boss_id=0x31),
    "armored_armadillo": dict(level=3, run=dict(x=4992), state="work/states/armored_armadillo_fight.mss", boss_id=0x14),
    "launch_octopus": dict(level=1, run=dict(x=7296, y=640), state="work/states/launch_octopus_fight.mss", boss_id=0x07),
    "boomer_kuwanger": dict(level=7, run=dict(x=1664, y=100), state="work/states/boomer_kuwanger_fight.mss", boss_id=0x05),
    "sting_chameleon": dict(level=2, run=dict(x=7808, y=384), state="work/states/sting_chameleon_fight.mss", boss_id=0x0A),
}
MEASURED = Path("work/rooms/measured.json")      # written by verify_rooms.py


def collision_grid(g, level, left, top, w=SCREEN_W, h=SCREEN_H):
    """Collision bytes of the 16x16 cells covering the rectangle (rows of columns), from the ROM."""
    x0, y0 = left - left % 16, top - top % 16
    return [[collision_at(g, level, x, y) for x in range(x0, left + w, 16)] for y in range(y0, top + h, 16)]


def room_data(g, key):
    r = ROOMS[key]
    m = json.loads(MEASURED.read_text())[key]
    out = dict(boss=key, level=r["level"], camera=m["camera"], borders=m["borders"], x_start=m["x"],
               boss_start=m["boss"], cell_origin=[m["camera"][0] - m["camera"][0] % 16, m["camera"][1] - m["camera"][1] % 16])
    if r.get("runtime_collision"):
        out["collision"], out["collision_source"] = m["collision"], "game RAM on the first fight frame"
    else:
        out["collision"], out["collision_source"] = collision_grid(g, r["level"], *m["camera"]), "ROM (= the game's lookup)"
    return out


def main():
    if not MEASURED.exists():
        sys.exit("run verify_rooms.py first (it measures each room in the game)")
    from render_level import render
    g = MMX1("work/hack.sfc")
    Path("work/rooms").mkdir(parents=True, exist_ok=True)
    images = {}
    for key in ROOMS:
        d = room_data(g, key)
        Path(f"work/rooms/{key}.json").write_text(json.dumps(d, indent=1))
        lvl = d["level"]
        if lvl not in images:
            images[lvl] = render(g, lvl)
        l, t = d["camera"]
        if ROOMS[key].get("runtime_collision"):          # the ROM's layout isn't what's on screen: use the game's picture
            Path(f"work/rooms/{key}.png").write_bytes(Path(f"work/rooms/{key}_game.png").read_bytes())
        else:
            images[lvl].crop((l, t, l + SCREEN_W, t + SCREEN_H)).save(f"work/rooms/{key}.png")
        print(f"{key:18} level {lvl}  camera {d['camera']}  X {d['x_start']}  boss {d['boss_start']}")


if __name__ == "__main__":
    main()
