# MMX Lab: Mega Man X1 ROM tools

Tools for reading and editing *Mega Man X (USA) (Rev 1)*. Everything here was worked out by studying
MegaEdX and the game's own code; see the docs below for how.

## Setup

- Python 3 with Tk and Pillow (`pip install pillow`).
- Your own *Mega Man X (USA) (Rev 1)* ROM, placed **next to this folder** as
  `../Mega Man X (USA) (Rev 1).sfc`. No ROM data is included in this repository.
  `work/` and `out/` are created locally and ignored by git.
- Optional: an emulator for **Save & Run**. MMX Lab looks for Mesen 2 at
  `../emulator/Mesen.app`, or you can pick one with **Emulator…**.
- `expand.py` and `reference/` are derived from MegaEdX (GPLv3, Xeeynamo / RedGuyyyy / rbrummett).

## Start here

```bash
python3 ui.py                # opens work/hack.sfc (copied from the stock ROM on first run)
python3 ui.py some/other.sfc
```

| Tab | What you can do |
|---|---|
| **Bosses** | Read how a boss behaves; edit its parameters (HP, timings, speeds, weakness) and its attack-choice odds |
| **Enemies** | All 107 enemy object types with their sprite, HP (editable where found), code address, which stages use them. Double-click to name them |
| **Levels** | Stage map with camera-lock / collision overlays and an **editable event list**: change type, object, sub-id, X/Y; add, delete, revert; double-click the map to move the selected event. Click a marker to select it |
| **Code** | Any routine as Assembly, decompiled C, literal C, or Assembly + C side by side (click a line to find its counterpart) |

Edits are made in memory; **Save** (⌘S) writes the project ROM and fixes the checksum.
**Expand ROM…** (toolbar) grows the project to 2.5 MB so stages can hold more events (2 KB each instead of the stock size).
The original ROM can't be overwritten.

## Command line equivalents

```bash
python3 params.py show chill_penguin
python3 params.py set chill_penguin ice_shots=8 slide_speed=0x900 --rom work/hack.sfc --out work/hack.sfc
python3 params.py weights chill_penguin "Ice Shot" 0,0,16,0,0 --rom work/hack.sfc --out work/hack.sfc
python3 params.py export chill_penguin cp.json --rom work/hack.sfc
python3 params.py enemies
python3 render_level.py 8 --events --locks --collision
python3 expand.py "../Mega Man X (USA) (Rev 1).sfc" work/expanded.sfc
python3 trace.py 81B516
```

## Files

| File | Role |
|---|---|
| `ui.py` | The Tk app |
| `params.py` | Named values: read, write, safety checks, export/import, CLI |
| `defs.py` | **Definitions of editable values.** Add new bosses/params here |
| `mmx1.py` | ROM reader/writer: levels, events, checkpoints, camera locks, collision, palettes, tiles, checksum |
| `render_level.py` | Draws a stage to PNG |
| `expand.py` | ROM expansion (port of MegaEdX, with a Sigma 3 checkpoint fix) |
| `disasm.py`, `trace.py` | 65816 disassembler / control-flow tracer |
| `decomp.py` | Structured decompiler: functions per state, if/else, named fields (`python3 decomp.py chill_penguin`) |
| `lift.py` | Literal assembly → pseudo-C, one statement per instruction; also the shared name tables |
| `enemies.py` | Enemy dispatch table and HP finder |
| `sprites.py` | Draws an enemy's sprite (first frame) from the ROM |
| `collision_survey.py` | Builds the collision contact sheet |
| `reference/` | MegaEdX's C++ `ExpandROM` compiled on macOS, for byte-for-byte comparison |
| `labels.json` | Your names for enemy ids (created when you name one) |
| `work/` | Your project ROMs |
| `out/` | Generated images, listings, catalogues |

## Docs

- `NOTES.md`: ROM format: addressing, level data, events, checkpoints, camera locks, collision, expansion, RAM map, MegaEdX bugs.
- `ENEMY_AI.md`: how enemy code works (object fields, state machines, helpers), Batton Bone, and the full Chill Penguin breakdown.

## Safety

- Code values are only written if the expected opcode sits right before them (`prev` in `defs.py`),
  so a different ROM version or a moved routine is refused rather than corrupted.
- Values are range-checked; attack-odds rows must total 16.
- Edits to the in-place values (everything in Bosses/Enemies) work on both stock and expanded ROMs.

## Not done yet

- Nothing has been play-tested in an emulator.
- Only Chill Penguin is defined as a boss; the other bosses need tracing the same way.
- Level editing (moving enemies etc.) exists in `mmx1.py` but isn't in the UI yet.
