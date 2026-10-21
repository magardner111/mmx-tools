# Mega Man X1 ROM format notes

Learned by reading MegaEdX (`megaedx_v1.3/.../MMXCore.cpp`, `CompressionCore.cpp`,
`SNESCore.cpp`, `RenderED.cpp`), then checked against
`Mega Man X (USA) (Rev 1).sfc` by rendering every level with `render_level.py`.

ROM: `MEGAMAN X`, version 1, 1.5 MB (0x180000), LoROM, no copier header.
SHA-1 `c65216760ba99178100a10d98457cf11496c2097`.

## Addressing

- **LoROM.** Each bank maps 32 KB of ROM at `$8000-$FFFF`.
  - `pc = ((snes & 0x7F0000) >> 1) | (snes & 0x7FFF)`
  - `snes = 0x800000 | ((pc << 1) & 0x7F0000) | 0x8000 | (pc & 0x7FFF)`
- MegaEdX writes most pointers as FastROM addresses (`$86xxxx`). Bit 23 doesn't matter for the file offset.
- Pointer tables come in two kinds:
  - 3-byte long pointers, indexed `level*3`.
  - 2-byte pointers within the bank, indexed `level*2`, with the bank implied by the table's own address.
- **Header** at PC `0x7FC0`: title(21), map mode, cart type, ROM size, RAM size, country, license, version, then the checksum complement at `0x7FDC` and the checksum at `0x7FDE`.
- **Checksum** is the 16-bit sum of every byte. The ROM is mirrored up to a power of two, so for X1 the last 0.5 MB counts twice. `snes_checksum()` reproduces the stock value 0x4CC2.

## Level IDs (verified visually)

| id | stage | id | stage |
|---|---|---|---|
| 0 | Intro highway | 7 | Boomer Kuwanger (tower, vertical) |
| 1 | Launch Octopus | 8 | Chill Penguin |
| 2 | Sting Chameleon | 9 | Sigma 1 |
| 3 | Armored Armadillo | 10 | Sigma 2 |
| 4 | Flame Mammoth | 11 | Sigma 3 |
| 5 | Storm Eagle | 12 | Sigma 4 (vertical shaft) |
| 6 | Spark Mandrill | | |

## Pointer tables (X1, SNES addresses)

| what | table | entry |
|---|---|---|
| layout (FG) | `$868D24` | long ptr, `level*3` |
| scenes (FG) | `$868D93` | long ptr |
| blocks (FG) | `$868E02` | long ptr |
| maps | `$868E71` | long ptr |
| collision | `$868EE0` | long ptr (1 byte per map) |
| layout/scenes/blocks (BG) | `$868F4F` / `$868FBE` / `$86902D` | long ptr |
| events | `$8582C2` | word ptr in bank `$85`, `level*2` |
| checkpoints | `$86A780` | 2-level word table, see below |
| level palette config | `$868133 + 0x60` | word ptr in bank `$86`, `level*2` |
| tileset config | `$86F56F + 4` | word ptr in bank `$86`, `level*2` |
| compressed gfx list | `$86F6F7` | 5-byte entries; long ptr at +2 |
| font | `$86F744` | |
| camera borders / locks | `$86E4E2` / `$86ECD0` | |
| sprite assembly | `$8D8000` | |
| object gfx / object palettes | `$86ACEE` / `$86ACF1` | |

There are also tables that MegaEdX addresses by raw PC offset:
- dynamic tile uploads at `0x321D5`
- dynamic palette uploads at `0x32260`
- the sprite palette bank at `0x2A000`

## Graphics hierarchy

```
tile   8x8    4bpp planar (32 bytes) in VRAM
map    16x16  4 words: SNES BG tilemap entries, order TL TR BL BR
              word = v h o ppp cccccccccc  (vflip, hflip, priority, palette 0-7, tile 0-1023)
block  32x32  4 words: map indices, TL TR BL BR
scene  256x256  64 words: block indices, 8x8, row-major (0x80 bytes per scene)
layout W x H scenes
```

- **Collision** is 1 byte per *map* (16x16), at `collision + mapIndex`.
- **Layout encoding:**
  - The header is `width, height, scenesUsed`.
  - Then come `(ctrl, scene)` pairs until `ctrl == 0xFF`.
  - The run length is `ctrl & 0x7F`.
  - If bit 7 is **clear**, the scene number goes up by 1 with each cell. If it is set, the same scene repeats.
- Map, block and scene data are **uncompressed and stored back to back per level**. MegaEdX guesses each count from the gap to the next level's pointer. **Growing any of them overwrites the next level** unless you relocate the data (that's what "ROM expansion" does).

## Tiles and palettes for a level

1. **Base VRAM.** The first 0x200 bytes are a fixed block of 16 tiles (`vram.cpp` → `vrambase.bin`).
2. **Main tileset.** The tileset config entry is `gfxId(1) size(2) vramWordDest(2)`. The source is the long pointer at `$86F6F7 + gfxId*5 + 2`.
   - The destination in our buffer is `(vramWordDest*2 - 0x2000) & 0xFFFF`.
   - The `& 0xFFFF` matters. The C++ relies on the silent wrap of a 16-bit `WORD`. Without it, the intro stage loads at 0x10200 instead of 0x0200.
3. **X1 decompression** ("RLE"). For every 8 output bytes there's a `control` byte and a `fill` byte. Each control bit, MSB first, says "1 = read a literal, 0 = write the fill byte". X2 and X3 use LZSS instead (the second branch of `GFXRLE`).
4. **Dynamic tile uploads**, chosen by the checkpoint's `tileLoad`: uncompressed copies made at checkpoints 0..N, from table `0x321D5`.
5. **Palette.**
   - The base config is `count(1) wordPtr(2)`, with colors in bank `$85`.
   - On top of that come dynamic palettes chosen by the checkpoint's `palLoad`, from table `0x32260`. That table is a list of `(colorPtr16, dstIndex8)` entries terminated by 0xFFFF, each copying 16 colors.
   - Colors are BGR555.

## Events (enemies, items, triggers)

- `events[level]` is a stream: `[columnId] record record ... [columnId] record ...`, ending when an id repeats.
- `columnId` is about `x >> 5`. The game streams events in by camera column.
- Each record is 7 bytes:

```
byte  type(2 low bits) | match(6 high bits)
word  y
byte  id
byte  subId
word  x (13 bits) | flags(3 bits); flag bit 2 (0x8000) = last record in this column
```

The types are:

| type | meaning |
|---|---|
| 0 | items, boss doors, some enemies |
| 1 | scripted events: cutscenes, dialogue |
| 2 | camera-lock regions (id 0x00, sub = lock index), checkpoints (id 0x02/0x0B, checkpoint number in `sub & 0xF`), camera scroll edges (ids 0x15–0x18) |
| 3 | enemies (id = enemy kind) |

Notes:
- **Event size is fixed per level.** Original byte sizes are in `GetOrigEventSize()`. Adding events needs free space or relocation.
- **Chill Penguin (level 8)** has 92 events, mostly type 3 enemies (ids 0x2D, 0x15, 0x36, 0x51…).

## Checkpoints

To find checkpoint `n` of a level:
`$86A780 + word[$86A780 + word[$86A780 + level*2] + n*2]`.

Each record is:

```
objLoad tileLoad palLoad      (bytes: which dynamic gfx/tile/palette set is active)
chX chY camX camY bkgX bkgY   (X spawn, camera, BG scroll)
minX maxX minY maxY           (camera bounds)
forceX forceY
scroll telDwn                 (bytes)
```

(X2 and X3 insert extra bytes; see `LoadCheckpoints()`.)

## Gotchas found in MegaEdX

- **Silent 16-bit wraparound.** `tileCmpDest` and `tileDecDest` are `WORD`, and the code depends on the wrap.
- **Expanded-ROM check: two bugs that cancel out.** `CheckROM()` tests `&& strcmp("EXPANDED ROM  ", marker)`, which is true when the strings *differ*. But the expander writes `"EXPANDED ROM "` (one trailing space) and the check compares against two spaces, so for a MegaEdX-expanded ROM they always differ, and the test passes. In effect any 2.5 MB ROM with header size 0xC counts as "expanded", marker or not.
- **Expansion drops a Sigma 3 checkpoint (real bug).** Sigma 3's event at x=0xF68 references checkpoint 6. Its pointer list has only 6 entries, so the original game reads one slot past the end and gets Sigma 4's checkpoint 0. MegaEdX copies only each level's own entries, so after expansion slot 6 is `0xFFFF` and points at garbage. `expand.py` fixes this; `--faithful` reproduces the bug.
- **Expansion writes uninitialized memory.** The checkpoint pointer slots for levels 13–15 (which don't exist) are copied from an uninitialized stack array.
- **Save states crash.** `Emulator::UpdateSaveState` passes `sizeof(char*)` (8) as the buffer size to `_splitpath_s`/`strcat_s`.
- **"Run" in the emulator ignores the selected level.** The LOADLEVEL handler is just `// TODO` comments.
- **`raw2tile2bpp` writes 4bpp plane offsets** (0x08/0x09) into a 0x10-byte 2bpp tile.
- **Alternate stage states are hard-coded.** `SwitchLevelEvent()` copies layout cells by hand for levels 2, 4 and 6, e.g. Flame Mammoth's state after Chill Penguin is beaten.

## Collision (1 byte per map, `collision + mapIndex`)

Inferred by grouping every placed map by value (`collision_survey.py` → `out/collision_sheet.png`):

| value | meaning | confidence |
|---|---|---|
| 00 | air | high |
| 01–0C | slopes (01–04 steep pairs, 05–0C four-step gentle slopes) | high |
| 0D | underwater | high (only Launch Octopus) |
| 0E | water surface | high |
| 12 / 13 | ladder / ladder top? | medium |
| 33 | conveyor? (Flame Mammoth belts) | medium |
| 3B | solid (the default; ~65k placements) | high |
| 34–3E | solid; the low nibble is probably a surface variant (sound/dust/wall-slide) | medium |
| 3F | spikes (instant death) | high |
| 41+ | 1–4 placements each; probably unused or mismatched maps | — |

Nailing these down needs the game's collision handler disassembled, or testing in an emulator.

## Camera locks

- An event of **type 2, id 0x00** is a lock region. Its `sub` is the lock index.
- **Original format:**
  - The border list is a word table at `$86E4E2 + level*2` (bank $86).
  - Each lock record is `right, left, bottom, top` (4 words), then 1-byte indices into `$86ECD0`, 0-terminated.
  - Each `$86ECD0` entry is 4 bytes: a RAM word address and a value, written while X is inside the box.
  - The addresses are the camera border registers `border_left` (`$1E5E`) left, `border_right` (`$1E60`) right, `border_top` (`$1E68`) top, `border_bottom` (`$1E6E`) bottom.
  - Lock entries are **shared between levels by index**, so editing an entry's value in place affects other levels too.
- **Expanded (v4) format:** flattened into bank $BB. Each level gets 0x800 bytes and each lock 0x20: 4 border words, then up to 6 inline `(addr, value)` pairs, 0-terminated. A new 65816 routine at `$81F6C4` reads them.

## ROM expansion (`expand.py`, port of `MMXCore::ExpandROM`)

It grows the ROM from 1.5 MB to 2.5 MB (header size 0xB → 0xC) and writes a header at `$B0:FFC0`:
`"EXPANDED ROM \0"`, then version=4, layout=0x800, events=0x800, checkpoints=0x10.

| PC | bank | contents |
|---|---|---|
| 0x180000 | $B0 | FG layouts, 0x800/level (old ones blanked to FF, 3-byte pointers rewritten) |
| 0x188000 | $B1 | BG layouts, 0x800/level |
| 0x190000 | $B2 | events, 0x800/level; level pointer table at `$B2:FFE0` |
| 0x198000 | $B3–$BA | scenes, 0x40 per level (sceneUsed in each layout header set to 0x40) |
| 0x1D8000 | $BB | camera locks, flattened |
| 0x099000 | $93:B000 | copy of the checkpoint records; new pointer table at `$86A780` (0x10 levels × 0x10 slots) |

Code patches:
- `LDA #$85` → `LDA #$B2` in the event loaders. There are two code revisions; Rev 1 (yours) is at `$80DB7C/$80DBC3/$80DD36`.
- The checkpoint base routine moves to `$80:FF00` and switches to bank $93.
- New lock-check routine at `$81F6C4`, and long loads in the event-end routine at `$81F722`.
- Copy-protection resets are disabled at `$81824E`, `$849FC7` and `$84A41F`.

How it was verified:
- MegaEdX's real `ExpandROM()` is compiled unmodified on macOS (`reference/harness.cpp`). `--faithful` output matches it byte for byte, apart from the uninitialized slots.
- The expanded ROM reads back identically: all 13 levels' events, checkpoints, locks and layouts, plus pixel-identical renders.
- **Not yet tested in a running game.**

## RAM map (X1)

In `mmx1.RAM`:
- camera X/Y `$1E6A/$1E6C`
- borders L/R/T/B `$1E5E/$1E60/$1E68/$1E6E`
- X position `$0BAD/$0BB0`
- level `$1F7A`, checkpoint `$1F81`
- object/tile/palette set `$1F08/09/0A`
- boss-defeat flags for Chameleon `flag_sting_chameleon` (`$1F87`), Mandrill `flag_spark_mandrill` (`$1F8F`), Mammoth `flag_flame_mammoth` (`$1F95`)
- decompressed layouts at `$7EE800` (FG) and `$7EEC00` (BG)
- X's object is at `$0BA8`, so X's field `$33` = `$0BDB` is the selected weapon × 2; ammo/ownership at `$1F85 + weapon×2`
- `last_hit_projectile` (`$1F1D`) = id of the last projectile that hit an enemy; `last_hit_object` (`$1F1E`) = that projectile's object address
- `$1F86 + 2×stage` (high byte of that stage's weapon word): bit 6 = the stage's boss is beaten. `boss_already_beaten` (`$84:AADD`) tests it
  for stages < 9 and returns 1 (and increments `boss_cleared` (`$1F23`)) if set; bosses despawn on spawn when it does
- `$0BAA` = X's step (field `$02`); `x_freeze_for_boss` (`$84:9FEB`) sets it to `$1E` (frozen) when a boss spawns
- `screen_left` (`$1E4D`) = screen left edge used by boss positioning (Boomer Kuwanger appears at +$10, teleports to +$20 / +$E0)
- Boss HP bar: `hud_boss` (`$1F0E`) = the object it shows (0 = no bar; a boss sets it to itself at the end of its intro),
  `hud_boss_bar_state` (`$1F10`) = bar state for `hud_boss_bar` (`$80:DA0E`) (0 set up, 2 redraw whenever the object's hp has bit 7 set, 4 remove,
  6 hide during pause, 8 idle). Never setting `hud_boss` (`$1F0E`) means no bar at all.
- `boss_defeated` (`$1F0C`) = boss defeated: set at boss HP 0; enemies stop hurting X (`hurt_x_on_contact` (`$84:9B03`)) and X's own update reads it.
  The boss-defeated sequence (`boss_defeated_sequence` (`$84:A677`)) freezes objects (`$1F13`–`$1F18`), fades the palette to white and
  freezes X for the stage clear.
- Explosions: `explode` (`$84:A4B5`) one explosion at the object + sound $23; `random_explosion` (`$84:A4D0`) random explosions around it
  (offset `$0000`/`$0002`, random masks `$0004`/`$0006`, every frame where `frame & $0008 == 0`)

## Tooling here

- `mmx1.py`: reads and writes the ROM, both stock and expanded.
  - Reads layout, events, checkpoints, camera locks, collision, palette and VRAM.
  - Writes `write_events` (byte-identical round-trip; refuses to overflow), `write_checkpoint` and `write_camera_lock_box`.
  - Also has `save_rom` (fixes the checksum), `LEVEL_NAMES`, `COLLISION` and `RAM`.
- `render_level.py <level> [cp] [--bg] [--events] [--collision] [--locks] [--rom=path]`: writes `out/levelNN.png`.
- `expand.py <in> <out> [--faithful]`: ROM expansion.
- `collision_survey.py`: builds the collision contact sheet.
- `reference/`: the C++ harness that runs MegaEdX's own `ExpandROM` for differential testing.

## Open questions / next steps

- Test in an emulator: boot the expanded ROM, play each stage, check checkpoints and locks, and confirm the collision guesses.
- The BG layer (`--bg`) renders but hasn't been verified against the game.
- No mapping yet from enemy id to name and sprite.
- Growing maps, blocks or tiles still needs relocation work; expansion only covers layouts, scenes, events, checkpoints and locks.

## Getting to Storm Eagle in tests (verified by verify_storm_eagle.py)

Warping into his deck (checkpoint 2, x 6656–7168) doesn't start the fight: he only comes after the ride.
Route from checkpoint 1: on the airship's wing tip (x≈6302, y 351), jump left over the pit onto the
platform at x≈6250. Checkpoint becomes 2, X is held in step `$46` while the platform carries him up to the
deck (x≈6081, y 207) and Eagle flies in (his state 2: descends, lands, HP to 32); X is let go the frame Eagle
enters state 4. The deck runs from about x 5760 to 6300, with a pit on both sides. His Gust pushes X 2 px a
frame and X walks at 1.5 (no dash before Chill Penguin's leg upgrade), so tests walk into the wind and come
back to the middle between attacks; the tornado pushes too.

Tests load a save state made on the wing tip, `work/states/storm_eagle_wing.mss`, with `Run(savestate=...)`.
`work/` isn't in git (a save state holds the game's RAM and video memory), so make your own:

1. `python3 testwarp.py 5 --run` (boots straight into his stage at its normal start, opens the emulator;
   for Mesen: `../emulator/mesen.sh work/test.sfc`).
2. Play to the wing tip just before the platform (checkpoint 1, x≈6302) and save state slot 1 (Shift+F1).
3. `cp ~/.config/Mesen2/SaveStates/test_1.mss work/states/storm_eagle_wing.mss`

Mesen's Lua can only load a state from inside a memory callback (`emu.loadSavestate` does nothing from a
frame event), and test scripts have no file access, so `Run` writes the state's bytes into the script.
