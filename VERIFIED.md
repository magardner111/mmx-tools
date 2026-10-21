# Verification log

What has been confirmed in the running game, and how. Everything else in `defs.py`, `lift.py`, `NOTES.md`
and `ENEMY_AI.md` comes from reading the code; names still marked (?) are guesses.

## How tests run

- `testwarp.py` builds a test ROM that boots straight into a stage at a chosen spot.
- `mesen_verify.py` runs that ROM headless in Mesen 2 (`../emulator/mesen.sh --testrunner`) with a generated
  Lua script that can: follow objects every frame, log calls of a routine (A/X/Y and D = which object made the
  call), log writes to an address (and which code wrote it), press buttons, and write RAM (seed, infinite HP,
  boss HP, weapons...). Tests can also patch the ROM first (e.g. change one of a boss's values).
- Mesen runs at about 64 frames/s on the Pi 400 (one core), so suites run 4 sessions at a time.
- `verify_<boss>.py` re-runs every check for a boss and prints PASS/FAIL.

Things learned while building this:
- The random seed is the word at `$0BA6`; the reset code sets it to `$0D37` (by frame 2), and nothing uses it
  before the first enemy, so a test sets it at frame 60 to get a different run.
- Object code runs with data bank `$86`, so its writes to low RAM go to `$86:xxxx`; watch RAM (Mesen's
  work-RAM memory type), not one CPU address.
- Weapons: word at `$1F85 + weapon×2`, bits 15-14 = owned, bits 13-8 = ammo; `$0BDB` = selected weapon × 2.
- Starting X right above a floor sank him into it: X's beam ignores terrain for the checkpoint's `telDwn` frames
  (`PLAYER.md`). `testwarp.py` now releases the beam higher, over open air.
- The no-damage AR code (`7E0BD808`, `X_hurt_lock` held at 8) also stops boss doors from opening, so tests turn
  it on only after the door (or the ride).
- Some bosses can't be warped to (Storm Eagle comes after a platform ride): tests load a Mesen save state
  (`Run(savestate=...)`, NOTES.md has how to make one).

## Chill Penguin — all confirmed (`verify_chill_penguin.py`, 43/43, run twice; again 43/43 on 2026-10-21 with the new beam-in start)

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, jingle $2E, 60-frame wait, `obj_start` (state 2, damage class 3) | calls logged with D = his slot; timer $34 = 60 |
| `palette_bits` ($33) = attr & $0E | 8 with attr $29 |
| intro: falls to the floor, spawns the hook (object $12 in the $1628 list via `alloc_misc_1628`) | hook object appears |
| HP fill: +1 every 2 frames to 32 with `play_sound_centered($0C)`, then music $1E, then `x_unfreeze` | 32 ticks, 2 frames apart |
| fight damage class 9; 5 while invulnerable; 0 while sliding | field $28 |
| attack choice: one row per previous attack at `$86:C45B` | 422 picks over 24 seeds: chi² 19.5 / 20; another 208: 23.3 / 20 |
| Ice Shot: `shots` ($36) = 4, one per keyframe 55 frames apart, 120-frame pause, `face_x` between shots | |
| Belly Slide: $600, `sliding` ($39) = 1, `can_flinch` ($38) = 0, `move_brake_left/right` only here, no recovery pause | next attack picked the same frame (5 of 5) |
| Jump at X: vx = (X.x − x) × 4, vy $87E, 30-frame landing pause | vx −384 with X at 7721, him at 7817 |
| Blizzard: vy $7DE, lands 10 px from room centre, hook byte $1B = 1 → hook state 6, hang 30 | |
| Ice Breath: 60 frames (`breath_spawn_particle` every frame, a particle every 8), `spawn_ice_statue` ×2 at $30/$50; becomes Ice Shot while a statue stands | |
| hit: buster −1, Fire Wave −3 (damage row 9); 70 frames invulnerable | |
| flinch only when `can_flinch` = 1; small flinch `flinch_timer` ($37) = 20, speeds $100/$221; Fire Wave → big flinch 60, sound $4A | 3 flinchable hits flinched, 6 others didn't |
| HP 0: state 6, death pose 4, `X_hurt_lock` (`$0BD8`) = 1 (at `$81:B6B7`; X can't be hurt during the boss's death), `boss_defeated` = 1 (at `$81:B6BA`), `boss_defeated_sequence` every frame, then despawn | |
| `x_dead` ($30) = 1 when X's HP reaches 0 | |
| every editable value: max HP, ice shots, Ice Shot pause, slide speed, jump speed, Blizzard jump speed and hang, breath time, statue distances, invulnerability, both weakness ids, flinch speeds | each changed in the test ROM; the game followed the new value |
| shared routines: `hit_check`/`hurt_x_on_contact` every fight frame, `move_with_gravity` only while airborne, `check_terrain` touch bit 2 = floor, `face_x`, `play_music` ids, `obj_despawn` | |

Side findings:
- `$84:9E15` (damage) runs for any object a shot hits, including Penguin's ice shots (Fire Wave destroys them).
- Contact damage to X goes through `$84:9D5C`, not `x_take_damage` (X lost 2/4/6 HP on contact).
- Penguin's hook keeps the wind going for about 150 frames after the signal.

## Storm Eagle — all confirmed (`verify_storm_eagle.py`, 34/34 on 2026-10-21; the other 33 also passed in the run before)

Every test loads the wing-tip save state, jumps onto the platform and rides up; after the ride X has the no-damage
AR code on and holds the middle of the deck, walking into the Gust and the tornado.

| claim | evidence |
|---|---|
| route: X held in step `$46` from the platform until the fight starts | held frames 44–882, fight from 882 |
| init: `boss_already_beaten`, jingle $2E, 60-frame wait (timer $34), `obj_start` (damage class 3), `palette_bits` = attr & $0E | waited 63 frames (busy frames), 8 with attr $39 |
| intro: appears at screen_left + 208 and the top of the screen, falls at vy −256, lands (touch bit 2), then `hud_boss` = him | x 6192 with screen_left 5984 |
| HP fill +1 every 2 frames to 32; then arena borders, music $1E, a 30-frame timer, `x_unfreeze`, state 4 | timer counts 30→0 one per update, after a ~7-frame stall while the music loads |
| fight damage class 7; 5 while invulnerable | |
| buster hit −1 (damage row 7); 60 frames invulnerable, sound $13 | 8 hits |
| `gust_start`/`gust_blow`/`gust_pause`: 120, 240 or 360 frames (16-bit timer) on the ground (pose 1), then 40 frames | lengths 240, 120, 240 |
| Gust pushes X 2 px a frame away from him; `gust_wind_effect` every 3 frames, only during the Gust | X walks 1.45–1.47 px/frame, −0.53 into the wind |
| Dive: one dive or a chain of 6–9; 4 px a frame on both axes; starts at X.x ± (X.y − his y); 40 frames below the screen | chains 7, 1, 6 |
| Storm Tornado: one tornado (enemy shot $24, speed −1024 then −512) per attack, from the ground (pose 3); walking into it X loses 1.48 px/frame | 8 attacks, 8 shots |
| Birds: flies up (vy $100) for 90 frames; each egg (enemy $55) hatches after 30 frames into 4 birds (enemy $56, sub-ids 0–3); then 20 frames | 12 eggs, all 30 frames, 12 hatches |
| attack choice: weights at `$86:D41B`, row = last attack; Birds, Tornado, Dive tested in that order, Gust gets the rest | 110 picks over 14 runs: χ² 6.4 / 11; Tornado never follows Tornado |
| HP 0: state 6, death pose 10, `boss_defeated` = 1, `X_hurt_lock` bit 0; `boss_defeated_sequence` every frame, then despawn | |
| `x_dead` ($30) = 1 when X's HP reaches 0 | X walked into the pit |
| editable values: max HP, invulnerability, gust push | 20 → fill stops at 20; $20 → 32 frames; $100 → push 1 px/frame |
| `hit_check` / `hurt_x_on_contact` in every attack | |

Side findings:
- While X is dying (step `$0C`) enemies stop updating: Eagle's Gust timer froze for those 30 frames.
- X walks 1.5 px a frame (steps of 1 and 2); without the dash he can't out-walk a 2 px push.
- Still unchecked: the "land first if airborne" branches of Gust, Tornado and Birds; Gust/Tornado picking again
  when he's far from the room centre; `dive_return` / `dive_pause` (vy −256 down to 64 px, 24 frames); spawn offsets
  (tornado ±39, y−10; eggs ±18, y−6; wind y+26); `wing_sounds`; the egg's and birds' own code.
