"""
Test ROMs that start straight in a stage at a chosen X position.

    python3 testwarp.py LEVEL [X [Y]] [--rom work/hack.sfc] [--out work/test.sfc] [--run]

Without Y, X lands on the first floor in that column. The beam starts LEAD + telDwn frames (8 px each)
above that spot, so terrain is already being checked when he reaches the floor.

Writes a separate test ROM (the project ROM is never touched):
  * no logos / attract mode / title: the logo task still does its setup (options from SRAM etc.) but
    with 1-frame pauses, and then jumps to the game-mode loop ($80:94D1, as the title does) instead
    of fading the logo in ($80:8620); the loop's new-game setup (mode 0, $80:94E7) sets the level to LEVEL instead of
    clearing it, and hands over to "load the stage" ($D2 = 2) instead of the title ($D2 = 0),
  * no boss intro card ($80:95AC: always take the "skip the card" path the intro stage uses),
  * GAME START (after a game over) also loads LEVEL instead of the intro stage ($80:9562),
  * that stage's checkpoint 0 is moved to (X, Y): spawn point, camera (centred on X, kept inside the
    stage), camera bounds widened just enough to allow it, and the enemy graphics / tile / palette
    sets that apply there (tile/palette sets and camera bounds from the nearest checkpoint).
"""
import argparse
import subprocess
import sys
from pathlib import Path

import gfxsets as G
from mmx1 import MMX1, LEVEL_NAMES, snes2pc, save_rom

HERE = Path(__file__).parent
GAME_START = 0x809562
GAME_START_STOCK = bytes([0xAD, 0x9B, 0x1F, 0xD0, 0x0F, 0x9C, 0x7A, 0x1F])
NEW_GAME = 0x8094E7            # mode 0: STZ $1F7A / STZ $1F7B
NEW_GAME_STOCK = bytes([0x9C, 0x7A, 0x1F, 0x9C, 0x7B, 0x1F])
LOGO_END = 0x808620            # logo task: LDA #$0F / STA $B3 (fade the logo in), then attract/title
LOGO_END_STOCK = bytes([0xA9, 0x0F, 0x85])
LOGO_WAITS = (0x808596, 0x8085C6, 0x808603, 0x80861C)   # LDA #n / JSR $810C (wait n frames): 120, 30, 30, 30
BOSS_CARD = 0x8095AC           # stage start: LDX $1F7A / BNE (show the boss card unless intro/fortress/beaten)
BOSS_CARD_STOCK = bytes([0xD0, 0x08])
TO_TITLE = 0x809525            # mode 0: (LDA #$02 / STA $D1 /) STZ $D2
TO_TITLE_STOCK = bytes([0x64, 0xD2])
LEAD = 60                      # up to this many frames of beam (8 px each) in open air before landing


def _patch(t: MMX1, addr: int, stock: bytes, new: bytes):
    p = snes2pc(addr)
    if t.rom[p:p + len(stock)] != stock:
        raise ValueError(f"unexpected code at ${addr:06X}: not the ROM revision this patch is for")
    t.rom[p:p + len(new)] = new
SCREEN_W, SCREEN_H = 256, 224


def collision_at(g: MMX1, level: int, x: int, y: int) -> int:
    """Collision byte of the 16x16 map at stage pixel (x, y)."""
    ptr = g.level_ptrs(level)
    width, height, _, cells = g.layout(level)
    if not (0 <= x < width * 256 and 0 <= y < height * 256):
        return 0
    scene = cells[(y // 256) * width + x // 256]
    block = g.w(ptr["scenes"] + scene * 0x80 + ((y % 256) // 32 * 8 + (x % 256) // 32) * 2)
    m = g.w(ptr["blocks"] + block * 8 + ((y % 32) // 16 * 2 + (x % 32) // 16) * 2)
    return g.rom[ptr["collision"] + m]


def floor_y(g: MMX1, level: int, x: int, start: int = 0) -> int | None:
    """Y just above the first floor at or below `start` that has at least 48 px of air over it."""
    height = g.layout(level)[1] * 256
    air = 0
    for y in range(start - start % 16, height, 16):
        if collision_at(g, level, x, y) == 0:
            air += 16
        elif air >= 48:
            return y - 1
        else:
            air = 0
    return None


def make_stage_rom(g: MMX1, level: int) -> MMX1:
    """A copy of `g` that boots straight into `level` at its normal start (checkpoints untouched)."""
    t = MMX1(bytes(g.rom))
    for w in LOGO_WAITS:                                                # copyright/logo pauses: 1 frame
        _patch(t, w - 1, bytes([0xA9, t.rom[snes2pc(w)], 0x20, 0x0C, 0x81]), bytes([0xA9, 0x01]))
    _patch(t, LOGO_END, LOGO_END_STOCK, bytes([0x4C, 0xD1, 0x94]))      # JMP $94D1: the game-mode loop
    _patch(t, NEW_GAME, NEW_GAME_STOCK, bytes([0xA9, level, 0x8D, 0x7A, 0x1F, 0xEA]))  # LDA #L / STA $1F7A / NOP
    _patch(t, TO_TITLE, TO_TITLE_STOCK, bytes([0x85, 0xD2]))                         # STA $D2 (A = 2)
    _patch(t, BOSS_CARD, BOSS_CARD_STOCK, bytes([0xEA, 0xEA]))          # never show the boss card
    _patch(t, GAME_START, GAME_START_STOCK, bytes([0xA9, level, 0x8D, 0x7A, 0x1F, 0xEA, 0xEA, 0xEA]))
    return t


def make_test_rom(g: MMX1, level: int, x: int, y: int | None = None) -> MMX1:
    """A copy of `g` that starts in `level` with X at (x, y)."""
    t = make_stage_rom(g, level)

    width, height = t.layout(level)[:2]
    cp0 = t.checkpoint(level, 0)
    if y is None:
        # search from the top of the playable area around x (the camera of the checkpoint nearest in x)
        cps = [t.checkpoint(level, c) for c in range(t.num_checkpoints(level))]
        top = min(cps, key=lambda c: abs(c["chX"] - x))
        y = floor_y(t, level, x, min(top["minY"], top["camY"]))
        if y is None:
            raise ValueError(f"no floor with room above it at x={x}; give a y")
    # tile / palette sets and camera bounds: from the checkpoint nearest to (x, y) (vertical stages too)
    near = min((t.checkpoint(level, c) for c in range(t.num_checkpoints(level))),
               key=lambda c: (c["chX"] - x) ** 2 + (c["chY"] - y) ** 2)
    cam_x = min(max(x - SCREEN_W // 2, 0), width * 256 - SCREEN_W)
    cam_y = min(max(y - SCREEN_H // 2 - 16, 0), height * 256 - SCREEN_H)
    # X's beam (step $22) falls 8 px a frame and ignores terrain for the first telDwn frames. Started right
    # above the floor he sinks into it and gets stuck, so release the beam LEAD frames earlier: terrain is
    # already being checked when he reaches the floor and he lands on it the normal way.
    # The early part has to be open air, or he lands on whatever is above (a ledge over Chill Penguin's room).
    air = 0
    while y - air - 16 >= 0 and collision_at(t, level, x, y - air - 16) == 0:
        air += 16
    lead = max(1, min(LEAD, (air - 32) // 8))
    tel = near["telDwn"]
    start = max(y - 8 * (tel - 1) - 8 * lead, 0)
    t.write_checkpoint(
        level, 0,
        objLoad=G.active_set_at(t, level, x)[0], tileLoad=near["tileLoad"], palLoad=near["palLoad"],
        chX=x, chY=start, camX=cam_x, camY=cam_y, bkgX=cam_x, bkgY=cam_y,
        minX=min(near["minX"], cam_x), maxX=max(near["maxX"], cam_x),
        minY=min(near["minY"], cam_y), maxY=max(near["maxY"], cam_y),
        forceX=near["forceX"], forceY=near["forceY"], scroll=near["scroll"], telDwn=tel)
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("level", type=int, help="0-12: " + ", ".join(f"{i} {n}" for i, n in enumerate(LEVEL_NAMES)))
    ap.add_argument("x", type=int, nargs="?", help="omit to start at the stage's normal start")
    ap.add_argument("y", type=int, nargs="?", help="default: just above the first floor at x")
    ap.add_argument("--rom", default=str(HERE / "work" / "hack.sfc"))
    ap.add_argument("--out", default=str(HERE / "work" / "test.sfc"))
    ap.add_argument("--run", action="store_true", help="open it in the emulator MMX Lab uses")
    a = ap.parse_args()
    if a.x is None:
        t = make_stage_rom(MMX1(a.rom), a.level)
        save_rom(t, Path(a.out))
        print(f"wrote {a.out}: {LEVEL_NAMES[a.level]} from its normal start")
    else:
        t = make_test_rom(MMX1(a.rom), a.level, a.x, a.y)
        save_rom(t, Path(a.out))
        print(f"wrote {a.out}: {LEVEL_NAMES[a.level]}, X beams down at x={a.x} from y={t.checkpoint(a.level, 0)['chY']}")
    if a.run:
        from ui import load_settings, DEFAULT_EMULATOR
        emu = load_settings().get("emulator") or DEFAULT_EMULATOR
        if not emu:
            sys.exit("no emulator found (set one with Emulator… in MMX Lab)")
        subprocess.Popen([str(emu), str(Path(a.out).resolve())])


if __name__ == "__main__":
    main()
