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
- Each suite now plays to the fight once and saves a fight-start state; runs start from it (NOTES.md).
- Hooks on a boss's own instructions (`Run.at_exec`) replace chance with exact setups: forced attack-table
  entries and rolls, X moved at the moment the boss reads his position. Phase lengths are checked by the
  boss's timer counting down, because on busy frames the game skips object updates.
- A routine can be called in the running game (`Run.call`, `probe.py`) and its RAM writes logged.

## Chill Penguin — all confirmed (`verify_chill_penguin.py`, 44/44 on 2026-10-21, starting from a fight-start state; 43/43 twice before)

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, jingle $2E, 60-frame wait, `obj_start` (state 2, damage class 3) | calls logged with D = his slot; timer $34 = 60 |
| `palette_bits` ($33) = attr & $0E | 8 with attr $29 |
| intro: falls to the floor, spawns the hook (object $12 in the $1628 list via `alloc_misc_1628`) | hook object appears |
| HP fill: +1 every 2 frames to 32 with `play_sound_centered($0C)`, then music $1E, then `x_unfreeze` | 32 ticks, 2 frames apart |
| fight damage class 9; 5 while invulnerable; 0 while sliding | field $28 |
| attack choice: one row per previous attack at `$86:C45B` | all 80 entries forced (hooks set the row at `choose_next_attack` (`$81:C019`) and replace `random` & 15 at `$81:C025`): 95/95 picks give that entry's attack; unforced 79 picks χ² 21.2 / 20 (earlier 422 picks: 19.5 / 20) |
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

## Storm Eagle — all confirmed (`verify_storm_eagle.py`, 35/35 on 2026-10-21, starting from a fight-start state; 34/34 before)

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
| attack choice: weights at `$86:D41B`, row = last attack; Birds, Tornado, Dive tested in that order, Gust gets the rest | every weight boundary of every row forced (row set at `choose_next_attack` (`$87:DE1F`), roll replaced at `$87:DE2C`): 30/30 cases, 51/51 picks right; unforced 65 picks χ² 7.8 / 11 |
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

## Flame Mammoth — all confirmed (`verify_flame_mammoth.py`, 64/64 on 2026-10-21)

The suite plays once from checkpoint 2 through his door and saves a state at the first frame of the fight; most
runs start there. X has the no-damage AR code on (except the stun and death runs). Hooks on his own instructions
set things up exactly: X moved to a chosen distance and `random`'s result replaced at the pick, X's y set at
`choose_next_attack`, X's x read when he aims the jump.

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, jingle $2E, `x_freeze_for_boss`; `trunk_hp` = 3, `belt_direction` = 2; spawns his trunk (enemy $0E, parent = him); 60-frame wait | timer 60 → 1 |
| `intro_move_in`: x += 64, `border_right` += 112; `intro_wait_for_x`: waits until X is within 128 px (the belt carries X, held in step `$1E`), then `hud_boss` and pose 19 | x 7935 → 7999; switch at 128 → 127 px; X 7772 → 7885 |
| `intro_fill_hp` +1 every 2 frames to 32; `intro_wait` counts the fill's timer (63) down, then `x_unfreeze`, music $1E, state 4 | 32 ticks, 63 → 1 |
| fight damage class 8 (5 while invulnerable); the trunk has his x, y, state, step, substep every frame | 16130/16130 frames |
| Stomp jump: vx = (X.x − his x) × 4, vy $593, gravity 48; landing = sound $4D, `screen_shake`(75), stun window 30; 60-frame pause | 209 jumps, 65 landings, 32 pauses |
| landing stun: X standing and hurtable when he lands → `x_stun(30)` that frame; X landing later in the window → `x_stun`(frames left); never with X untouchable (AR code) | 12 + 11 stuns (30 and 14) |
| `x_stun(A)`: X step `$36` (`step_stunned`) for A + 32 frames | 30 → 62, 14 → 46; also `x_stun(40)` called with `probe.py` → 72 |
| Oil shot: enemy shot $21 at x ± 46, y − 6; vx $280–$2FF right / −$300–−$281 left, vy $200; 60-frame pause | 54 shots, 53 pauses |
| Oil shot picked while 2 puddles are out → `choose_next_attack` again (a new pick); fewer → he spits | 11 re-choices, 9 spits |
| oil puddle: X touching it → X.x = average of `X_prev_x` (`$0BCA`, his x before this frame's move) and his x now, rounded toward now; the belt's push afterwards isn't halved | exact on 336/336 frames |
| a fireball touching a puddle sets it alight: sound $5C, states 6, 8, then burns 180 frames | 7/7 |
| the belt moves puddles, Mammoth and X 0.5 px a frame (1 px every other frame): right while `belt_direction` bit 0 = 0, left while 1 | puddles 0.494 / −0.497, him 0.499 / −0.500, X 0.498 |
| Fire volley: 3–5 shots (4; half the time +1 at 13/16, −1 at 3/16), one per keyframe, enemy shot $20 at x ± 42, y − 7; 90-frame pause | {3: 3, 4: 15, 5: 13}, χ² 0.0 / 2; 82 shots |
| fireball vx $440 if X is 80 px or more away, else $260 | 67 × $260, 11 × $440 |
| Conveyor stomp: 60 frames, `belt_direction` ^= 1 + `load_stage_tiles`, 60 more; resumes an unfinished volley | 43 stomps, 6 resumes |
| forced Conveyor stomp when a puddle is < 64 px from the edge the belt moves it to (after each pick and every volley frame) | 20 forced, 0 missed |
| pick: row = X's distance (< 80, 80–127, ≥ 128) + 48 once the trunk is cut, column = `random` & 15; the attack is that entry of `$86:C843` | all 96 entries forced (distances 40/79, 80/127, 128/160): 186/186 rows, 141/141 attacks; unforced columns χ² 11.1 / 15 |
| repeat limit: with the trunk on, a 4th repeat is re-picked; none once the trunk is cut | re-pick exactly at repeats = 3; 18 Stomp jumps in a row with the trunk cut |
| a table with only one attack freezes the game (endless re-pick) | 349 picks in one frame, game stuck (`params.py` now refuses such rows) |
| X high up (X.y − screen_top < 112) → always the Stomp jump, without the table | y 110/111 → jump without a pick; 112/113 → pick |
| buster −1 (damage row 8), Boomerang Cutter (projectile $0D) −1, Storm Tornado ($0B, weakness) −3; invulnerability 60 frames, sound $13 | 20, 9 and 11 hits |
| each Boomerang Cutter hit takes 1 trunk HP; at 0 the trunk falls off (state 10) and despawns; then only the Stomp jump and the Fire volley | 3 hits |
| HP 0: state 6, death pose 21, `boss_defeated` = 1, `X_hurt_lock` = 1, `load_stage_tiles`; `boss_defeated_sequence` every frame, despawn; his oil and fireballs vanish | |
| `x_dead` ($30) = 1 when X's HP reaches 0 | |
| editable values: max HP, invulnerability, trunk hits, stomp jump speed, stun window, spit pause, volley shots, volley pause, conveyor wait | 20 → fill to 20; $20 → 32 frames; 1 → one Cutter hit; $400; $50 → 80; $20 → 32 frames each; 6 → 5–7 shots |
| `move_with_gravity` only in the Stomp jump; `hit_check` / `hurt_x_on_contact` in every attack | |

Side findings:
- Pinned at x 7700 (the left edge of the floor) X sinks to y 703 and can't jump; from 7740 on he's fine.
- `obj_overlaps` (`$84:9C0E`) tests any object's box, not just X's: the oil uses it on X and on fireballs.
- Still unchecked: the second trunk-cut weapon ($16 — the charged Cutter?); the intro's writes to `$1E74`, `$1E76`, `$1E54`; a puddle vanishing at a wall; the burning puddle's growing hitbox; the rematch branch (level ≥ 9).

## Spark Mandrill — all confirmed (`verify_spark_mandrill.py`, 41/41 on 2026-10-21)

Runs start from a fight-start state (checkpoint 2, through the door, X at x 7480); the intro and max-HP runs
play it in full. Hooks force his choice: the row is set at `choose_next_attack` (`$88:A362`) and the 0–31 roll
replaced at `$88:A36F`. For the stun test a hook turns his Dash punch away from X, so it ends at the far wall.

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, jingle $2E; 60-frame wait while the screen fades to white (fixed colour +1 a frame to 31, colour math $AF) | timer 60 → 1 |
| intro: falls (gravity 64), lands with sound $4D and `screen_shake`(30); boss bar; HP +1 every 2 frames to 32; 30 frames; `x_unfreeze`, music $1E | 32 ticks |
| first attack = (`random` & 3) × 2 | roll $FE → step 4 |
| fight damage class 10; 5 while invulnerable (60 frames, sound $13); buster −1 (row 10) and no flinch; Shotgun Ice −3 | 19 buster hits, 11 Ice hits |
| Electric Spark: `screen_shake`(10), sound $44, two sparks (enemy shot $28, sub-id 0 left, $28 right) at x ± 26, y + 24; 32-frame pause | 24 attacks, 48 sparks |
| spark: 4 px a frame, turns to climb a wall and back at the ceiling/floor (crawls around the room), lives 120 frames | 68 turns, all 120 (+ the spawn frame) |
| Ceiling drop: vy $6C3, gravity 64; grabs the ceiling as he starts to fall (`screen_shake` 10); hand-walks 28 px a swing; lets go once X is behind him (tested right after each swing) or at a wall; landing sound $4D, shake 30; 32-frame pause | 11 drops |
| Dash punch: probes 34/50/56 px ahead; clear → charges at $400 to the wall, otherwise punches on the spot; `screen_quake`, 30 frames, 32-frame pause | 2 dashes, 74 on the spot |
| punch quake: X on a wall (sliding down it) → `x_stun(32)`, once per quake; X on the floor, even pressed against the wall, isn't stunned | 5 + 5 quakes |
| a charged buster shot (projectile 1 or 3) mid-dash → stagger: slides back at $400, friction 32, 32 frames | 2 staggers |
| Jump at X: vx = (X.x − his x) × 4, vy $70D, gravity 64; lands with sound $4D, shake 30; 32-frame pause | |
| Shotgun Ice (projectile $0E) → frozen: `frozen` = 1, 60 frames; breaks out in 16 ice shards (effect $06), sound $4C, 30 more frames | 5 freezes |
| attack choice: weights at `$86:CFDB`, 6 rows (after each attack, after a stagger, after a freeze — rows 5 and 6 are 8/8/8/8); Jump at X, Dash punch, Ceiling drop tested in that order, Electric Spark gets the rest | every boundary of all 6 rows forced: 48/48 cases, 102/102 picks right |
| HP 0: state 6, death anim 17, `boss_defeated`, `boss_defeated_sequence`, despawn; his beaten flag is `$1F92` bit 6 | |
| field `$30` (`x_dead` in other bosses) is cleared at the fight's start and never set, even when X dies | X died from frame 587 |
| editable values: max HP, invulnerability, dash speed, both jump speeds | 20; $20 → 32 frames; $300; $600 |

Side findings:
- The old note "the quake stuns a grounded X" was wrong: the test is X's wall bits (`$0C06` & 3), so only X on a wall is
  stunned, and X's `status_flags` (`$0C2F`) bit 7 (set while stunned) keeps it to once per quake.
- `probe.py` results: `screen_shake`(A) and `screen_quake`(A) fill two shake channels (`$1E7A…` and `$1E79…`, mode `$1E78`
  = 2 / 1); `load_stage_tiles`(3) rewrites Flame Mammoth's belt tiles x-flipped, (2) and (4) unflipped;
  `obj_despawn_shot` (`$82:83A3`) clears an object like `obj_despawn` plus `$2C`; `obj_overlaps` sets carry only when X
  touches him.
- Still unchecked: charged Shotgun Ice ($17) and projectile 2 for the stagger; that more Ice hits while frozen don't restart
  the freeze (the code says so); falling while frozen; the spark's damage.


## Armored Armadillo — all confirmed (`verify_armored_armadillo.py`, 48/48 on 2026-10-21)

Runs start from a fight-start state (checkpoint 2, through the door, X dropped in at x 5147); the intro and max-HP
runs play it in full. His first choice is re-run 48 times within one frame (a hook at `$83:B670` sends him back to
`$83:B630`), each time with repeats cleared (`$83:B632`), the 0–15 roll replaced (`$83:B647`) and X's distance
replaced (`$83:B658`), so all 48 entries are tried at both edges of each distance band. The random rolls for wall bounces (`$83:B4CD`, `$83:B524`), guards (`$83:BA9F`) and shot counts
(`$83:B6B0`) are logged where he reads them, and each outcome is checked against its roll.

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, `screen_shake`(60), jingle $2E; 60 frames (`timer` `$34`) | 60 → 1 |
| intro: `palette_bits` = attr & $0E, gravity 64, `spawn_debris` ×4; falls in, bounces at half speed (vy −2176 → 1120), second landing `screen_shake`(8); boss bar, HP +1 every 2 frames to 32; 10 frames, `x_unfreeze`, music $1E; first attack always the Rolling attack (`last_attack` 0, `repeats` 1) | 32 ticks |
| damage class 11; 0 (shots bounce off) while guarding (`guard` bit 0) or curled (bit 7) with the armor on; 11 curled once it's off | 40 000 fight frames |
| Rolling: vy $506; curls when the jump animation ends; bounces once (vy = −vy); rolls at ±$600 the way he faces | 31 rolls |
| Rolling at a wall (sound $48, rocks): `random` & 15 ≥ 6 → `screen_quake`(8) and ricochets at $43B both ways; else hops off (vx $100 away, vy $506) and uncurls | 31/31 (20 ricochets) |
| ricocheting: floor touch with `random` & 15 < 6 → hops off; walls flip vx (`screen_quake` 8), floor/ceiling flip vy (`screen_shake` 8); lands, uncurls, back to choosing | 38/38 floor rolls, 44 wall bounces |
| choosing: 30 frames facing X (unless he guards); row = X's distance (< 80, 80–127, ≥ 128), column = `random` & 15, attack = entry at `$86:C980` | all 48 entries forced in one frame: 48/48 right |
| repeat limit: after the same attack twice (`repeats` = 2) he does the other without a roll; a one-attack table gives RRE RRE… / EER EER… (no freeze) | 25 forced switches |
| Energy shots: `shots_left` = `$86:C970`[`random` & 15] (3/4/5); each = enemy shot $04 (sub 0) at x ± 15, y − 14, vx ±$300, sound $33; fires them all, then back to choosing | 38/38 counts, 154 shots |
| guard: an X shot within 80 px (front edge) and 36 px up/down is noticed once (shot field `$2C`); `random` & 15 ≥ 4 → guards (12 in 16) | 306/306 rolls |
| guard: `guard_timer` 30 frames, dropped the frame after a shot bounces off it (`guard_timer` = 1); each deflection pushes him 2 px (`pushback` += 2); a guard mid-volley then finishes the volley | 79 full, 168 cut short |
| counter: charged buster (projectile 1, 2 or 3) into his guard → sound $4E, `guard` = $80, then 8 enemy shots $04 (sub-ids 1–8: up, up-right, right… at $800, diagonals $5A4) from his position, sound $02, 30 frames | 16 counters |
| hit: buster −1 (row 11), sound $13, `invuln_timer` 60 (flashing; hits meanwhile take no HP); knocked back (vx $100 away, vy $100) for 20 frames (`hit_timer` `$3A`) unless mid-roll; then an unfinished volley resumes | 35 hits, 31 knockbacks |
| Electric Spark (projectile $0C) with the armor on → `invuln_timer` 180, staggers 90 frames, falls, 20 frames, armor pieces (effect $2B, sub-ids 34…30, `piece` `$3D`), `armor_off` = 1; after that he never guards and can be hurt curled up; Electric Spark −3 (row 11) | 1 break |
| HP 0: state 6, `X_hurt_lock`, `boss_defeated`, `boss_defeated_sequence`, despawn; `x_dead` = 1 once X's HP is 0 | |
| editable values: max HP, invulnerability, think and guard time (both guards), roll speed and jump, counter shots | 20; $20 → 32; $10 / $0C; $400; counter_c = 0 → plain buster counters |

Side findings:
- `armor_invuln` (renamed from the old "stagger time" value) is the invulnerability after the armor-break hit, not the stagger (fixed at 90 frames).
  Set below 90 with the buster as an armor-break weapon, each hit restarts the stagger and the armor never comes off
  (30 staggers in a row in the test).
- The guard during the Energy shots reads its own 30 (`$83:B758`); the editor's Guard time now writes both.
- His first 6 fight frames don't run his update (damage class stays obj_start's 3).
- `screen_quake` takes its length in A like `screen_shake`; the C now shows it.
- `decomp.py` shows his damage class as `damage_class = A`; the assembly picks 0 / $0B as above (decompiler gap).


## Launch Octopus — all confirmed (`verify_launch_octopus.py`, 40/40 on 2026-10-21)

Runs start from a fight-start state: X starts at (7296, 640) in the flooded corridor between his doors (camera at
y 512, as at checkpoint 2) and walks into the room (x 7424–7680); the intro and max-HP runs play it in full. His
choice is checked exhaustively in one frame: a hook at the end of `choose_next_attack` (`$81:CA42`) sends him back to
its start 192 times with a chosen distance (`$81:CA15`), tentacle state (`$81:CA2A`) and roll (`$81:CA37`).

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, jingle $2E; 60 frames; `palette_bits` = attr & $0E, `cut_hits_left` (`$0C`) = 3 | 60 → 1 |
| intro: starts 16 px up and sinks at vy −$100 (≥ 40 frames) until he lands; boss bar; HP +1 every 2 frames to 32; when the pose ends `x_unfreeze`, music $1E, first attack the Torpedo hop | y 496 → 677, 32 ticks |
| damage class 12; 5 while invulnerable; 0 (shots bounce off) while spinning (`deflecting`) | 31 000 fight frames |
| choice: row = distance (< 80 → 0, ≥ 128 → $20, else $40) + $60 with the tentacles cut, column = `random` & 31, attack = entry at `$86:C625` | all 192 entries in one frame; 152/152 unforced picks agree |
| Torpedo hop: vx ±$180, vy = `$86:C6F5`[`random` & 3] ($4C6/$555/$5D5/$64B), gravity 44; 30 frames after landing | 43/43 |
| `fire_torpedoes`: 3 enemy shots $1E (sub-ids 2/1/0: up, level, down, ≈ $200) at x ± 6 or 11, y − 7, sound $1E; they speed up as they home | 172 volleys |
| Torpedo volley: 2 volleys on animation keyframes, 30 frames | 24 attacks |
| Piranha swarm: 4 piranhas (enemy $08, sub-ids 0–3) at (−54, −2), (53, −2), (−34, 13), (35, 13) from `$86:C6E5`, sound $1E | 31 swarms |
| Whirlpool: vy $720, gravity 44, vx = distance × 256 / 42; at the top spins (vy −$100, `spinning`, `deflecting`) with the whirlpool (enemy shot $1D); not caught → lands, rises at vy $200 to the ceiling, falls, chooses | |
| drain: X overlapping (and not above him) → `x_grabbed`, timer $1E1, `drain_tick` 32; X held at his x, y + 32; every 32 frames X −1 HP and he +1 (sound $4F); timer out → `x_drop`, he moves up 8 and rises; each new button press −16 frames; `hurt_x_on_contact` skipped meanwhile | 11 drains of 32 frames; mashing: drain over in 97 frames |
| hit: buster −1 (row 12), sound $13, `invuln_timer` 60 (flashing every 4); flinch for one animation, then the same step resumes where it left off | 41 hits, 40/40 resumes |
| Boomerang Cutter (projectile $0D): `cut_hits_left` 3 → 0, then `tentacles_cut`, 4 pieces (effect $07, sub-ids 3–0), falls (step 10), and rows +$60 (torpedo attacks only) | |
| Rolling Shield (weakness) −3 (row 12) | 11 hits |
| HP 0: state 6, `X_hurt_lock`, `boss_defeated`, sound $13, `boss_defeated_sequence`, despawn; `x_dead` = 1 once X's HP is 0 | |
| editable values: max HP, invulnerability, whirlpool jump, cut hits, drain time and interval | 20; $20 → 32; $500; 1 hit; $100 / 16 frames |

Side findings:
- `whirlpool_jump` (was labelled "Jump-at-X launch speed") is the whirlpool's jump; the Torpedo hop's heights come from
  the table at `$86:C6F5`.
- Exec hooks in Mesen don't fire again for the instruction the PC is set back to; the one-frame re-run loop advances
  its counter in the loop hook instead.


## Boomer Kuwanger — all confirmed (`verify_boomer_kuwanger.py`, 30/30 on 2026-10-21)

Runs start from a fight-start state: X starts at (1664, 100) in the corridor at the top of the tower and walks into
the room (x 1792–2048); the intro and max-HP runs play it in full. Both tables are checked exhaustively in one frame
each: hooks send the post-dash choice (`$87:8DDF` → `$87:8DCA`) and the post-teleport choice (`$87:8F3E` → `$87:8F1A`)
back to their start for every row and column.

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, jingle $2E; 60 frames; `palette_bits` = attr & $0E | 60 → 1 |
| intro: beams in from screen left + 16 along a right/down/right zig-zag (vx $1000), boss bar, HP +1 every 2 frames to 32, 30 frames, `x_unfreeze`, music $1E, first attack a Dash | (1808, 40) → (2000, 168) |
| damage class 13; 5 while invulnerable | 27 700 fight frames |
| after a dash: row = `dash_frames` ≥ 9, column = `random` & 15, entry at `$86:C5A3`; after a teleport: row = X within 128 px, entry at `$86:C5C3` | all 32 + 32 entries in one frame each; 85/85 unforced |
| Dash: faces X, sound $53, vx ±$400; X < 128 px: `random` & 15 < 6 → all the way to X (timer distance / 4 + 1) else 8 frames; X farther: the reverse; stops at a wall; 20 frames | 177/177 |
| Boomerang: horns (enemy shot $1B) at x, y − 24, `boomerang_out` while away; cleared when they return; 8 frames, then a dash; a dash ending with the horns out dashes again | 14 throws |
| Teleport: `random` & 3 = 0/1/2 → X ± 28/48/80 on the side toward the screen's middle (X − d when X ≥ screen left + 128), 3 → screen left + 32 (he is right of X) or + 224; vx ±$800 toward it (right when the target ≥ his x), sound $50; blinks 20, moves until within 5 px (snaps) or a wall, blinks 20, 8 frames | 80/80 targets, 65 arrivals |
| teleporting: only a hit with Homing Torpedo selected (`X_weapon` = 2) counts; the buster can hit him on the frame he reappears (the flag clears before the hit check) | buster 0 mid-teleport / 10 on reappearing; torpedo 10 |
| Dead Lift: X within 32 px in front (touchable, horns in) → step 6; within 40 px when the pose ends → `x_grabbed`, X held 32 px in front; at the ceiling 4 damage (`x_take_damage`, X HP 16 → 12) and `screen_shake`(32) | 18 tries, 13 grabs, 12 throws |
| hit: buster −1 (row 13), sound $13, `invuln_timer` 60 (flashing), flinch 16 frames; Homing Torpedo (projectile 7) flinch 24, −3 | 69 + 11 hits |
| below 17 HP: after a flinch `random` & 15 < 6 → a streak of (`random` & 7) + 6 teleports | 8/8 |
| HP 0: state 6, `boss_defeated`, `X_hurt_lock`, `boss_defeated_sequence`, despawn; `x_dead` = 1 once X's HP is 0 | |
| editable values: max HP, invulnerability, teleport and dash speed | 20; $20 → 32; $600 / $300 both ways |

Side findings:
- `teleport_speed` and `dash_speed` only changed rightward movement: the leftward speeds are separate constants
  (`$87:8E7D`, `$87:8D2A`). They are now mirrors, so the editor writes both (the test saw −$800 / −$400 before).


## Sting Chameleon — all confirmed (`verify_sting_chameleon.py`, 28/28 on 2026-10-21)

Runs start from a fight-start state: X starts at (7808, 384) in the corridor between his doors (camera at y 256, as at
checkpoint 2) and walks into the room (x 7936–8192); the intro and max-HP runs play it in full. He has no attack
table; every random roll is logged where he reads it (`$88:880B`, `$88:897E`, `$88:8B0B`, `$88:8BA2`, `$88:8BC6`,
`$88:8C35`) and checked against what he does next.

| claim | evidence |
|---|---|
| init: `boss_already_beaten`, `x_freeze_for_boss`, jingle $2E; 60 frames; attr $2B (`palette_bits` $0A), 30 frames | 60 → 1 |
| intro: lowers at vy −$80 for 60 frames, fades in for 90 (sound $76), falls to the floor; boss bar, HP +1 every 2 frames to 32; music $1E, `x_unfreeze`, first attack a leap | y 320 → 350, 32 ticks |
| damage class 6, 5 while invulnerable; cloaked: no `hit_check` and no contact damage; field `$30` (`cloak_copy`) = `cloaked` every frame | 24 000 fight frames |
| leap: `random` & 15 < 4 → high leap to screen left + 48 / 208, else low leap to + 64 / 192 (the other half of the room); vx = (target − x) × 8; low vy $593, gravity 48; at the top low → Ceiling shake, high → Sting | 31/31 (7 high), 20/20 turns |
| high leap (game bug): vy $070D then `LDA #$40 / STA $1C` (meant for gravity `$1E`) → vy $0740, gravity unchanged | 7 high leaps, gravity stayed 64 |
| Chameleon Sting: 3 enemy shots $11 (sub-ids k..k+2, k = 1–7 from the angle to X) from x, y + 48, sound $79; sub-ids 1–9 = 9 directions at $400 (right … left in 22.5° steps); 32 frames, then `random` & 15 < 12 → another (up to 3), else `random` & 15 < 3 → leap, otherwise cloak | 57 volleys, 53/53 follow-ups |
| Ceiling shake: 32 frames, then (`random` & 127) + 60 frames with a spike (enemy shot $11, sub-id 0) per keyframe; 32 frames, cloak | 19/19, 274 spikes |
| cloak: sound $76, `cloaked` = 1, 32 frames, fade-out over 64 frames (one step every 2), 60 frames; then `random` & 15 ≥ 6 → hops (vx ±$200, up to 3) else glides to a high corner | 49/49 rolls, 36 hops |
| after a hop with X in tongue reach: fades in (32 frames) straight into the Tongue; Tongue: sound $7C, up to 3 lashes while X stays in reach; from a wall then `random` & 15 ≥ 8 → cloak else leap; on the floor, leap | 23/23 |
| hit: buster −1 (row 6), sound $13, `invuln_timer` 60 (flashing), no knockback; Boomerang Cutter (projectile $0D) −3 and knockback (vx $100, vy $200, gravity 64), then a leap | 3 + 8 hits |
| HP 0: state 6, death anim 21, uncloaked, sound $13, `boss_defeated`, `boss_defeated_sequence`, despawn; with X at 0 HP he stops checking for hits | |
| editable values: max HP, invulnerability, cloak fade length and wait, spike time, sting volleys and tongue lashes | 20; $20 → 32; $10 → 32 frames, $20; base $14; 1 / 1 |

Side findings:
- `cloak_fade` (was "Invisible movement time") is the fade-out length in steps of 2 frames; `cloak_wait` is the invisible
  wait before he moves.
- The floor tongue has its own lash limit (`CMP #$03` at `$88:8C67`); the editor's Tongue lashes now writes both.
- The high-leap bug above is in the original game.


## X: movement, shots, damage — confirmed (`verify_player.py`, 23/23 on 2026-10-21)

Test room: Armored Armadillo's room from his fight-start state, with his object cleared every frame (a flat floor
between two walls). X's fields are logged every frame; inputs are scripted (some react to X's step, e.g. jump four
frames into a wall slide).

| claim | evidence |
|---|---|
| walk: `step_walk_start` (vx $100) for 5 frames, then `step_walk` at `move_speed` $178 (1.47 px a frame, steps of 1 and 2); facing from Left/Right (`x_face_dpad`) | 1.468 px/frame |
| jump: vy $553, gravity 64 (−64 a frame), about 56 px high; letting go ends it: step 8 with vy reset; `step_land` (sound, `step_timer` 4) | height 54; short hop 23 |
| fall: vy clamped to −$580 (`fall_cap`) before gravity → −$5C0 (5.75 px a frame) at full speed | 7 frames at −$5C0 |
| wall slide: vy 0 for 8 frames (`wall_stick`), then −$200; wall jump: 4 frames, then vx $178 away for 8, then a jump (held) or a fall | 34-frame slide; 13-frame wall jump |
| dash: needs `upgrades` bit $08 (no dash without it); vx $375 for 32 frames (`dash_timer`), then `step_dash_end` for 8 frames; a jump out of it keeps $375 (`dash_jump`) | 32 + 8 frames |
| buster: shot id 0 in X's shot list at $440, at most 3 on screen | 18 shots |
| charge: `charge_timer` 180 counted down while held; held 31 frames → projectile 1, 101 frames → projectile 3; with `upgrades` bit $02, 180 frames → projectile 2 plus X-shot object $1D (`$86:BA71` → `shot_request`) | boundaries 30/31 and 100/101 exact |
| hurt: hurt_lock 8, vx −$8A, vy $200, gravity 64; flash_timer 60 after the animation, hurt_lock cleared when it runs out; armor (bit $04) halves the vy | 448 → 192 on the first frame |
| `x_take_damage`: HP −= pending damage (10 → 7), step $0E; at 1 HP → HP 0 and step $0C | called with `Run.call` from X's update |

Side findings:
- Projectile ids: 1 = half charge, 3 = full charge, 2 = the arm upgrade's charge (the labels had 2 and 3 swapped).
- Setting a boss's beaten flag before his room makes entering it end the stage (X: step $1E → $1A → $18, then gone);
  to get an empty room, clear his object every frame.

## X's upgrades — confirmed (`verify_upgrades.py`, 149/149 on 2026-10-21)

131 headless runs (about 35 s on the M4 Max, 10 at a time). Most start from Armored Armadillo's fight-start state with
his object cleared; items, capsules and Zero are reached by warping X next to them (`Run(level, x, y)`), with
`upgrades`, `hearts`, HP and weapon words poked after the new-game init (frame 151) where a case needs them.
Summary in PLAYER.md "Upgrades". Evidence frames: per-frame records `f` = frame, hook events `f` = frame − 1.

### Special weapons (37)

| claim | evidence |
|---|---|
| weapons: beating Armored Armadillo (level 3) sets $40 in $1F88+2*(3-1) = $1F8C (STA at $84:AA1F, logged pc $84:AA22), weapon 3 word $0000 -> $4000 (owned, 0 ammo) | grant exec f=558; w1F8C v=64 pc=$84AA22; w3 $0000 -> $4000 |
| weapons: the grant touches only the beaten boss's weapon (others stay $0000) | w1,2,4-8 after: ['$0000', '$0000', '$0000', '$0000', '$0000', '$0000', '$0000'] |
| weapons: at the next stage start refill_weapons ($80:9EF9) refills every owned word to $DC00 (owned + 28 units + redraw bit); ammo max = $1C; unowned words stay 0; $1F97/$1F98 (9th slot) refilled too | refill f=901, w1F8C v=$DC pc=$809F08; end w3=$DC00 w9=$DC00, others 0 |
| weapons: control — with only one boss beaten the stage end checks all 8 ($80:9BF3) but does not set $1F7C bit 6 | all8_check 1x, fortress_tsb 0x, $1F7C=0 |
| weapons: with the other 7 beaten, beating the 8th: TSB $1F7C #$40 at $80:9C13 (logged pc $80:9C16), level $1F7A = 9 | fortress_tsb f=866; w1F7C v=64 pc=$809C16; then $1F7C=64 level=9 |
| weapons: R/L step X_weapon $0BDB by 2 through owned weapons only, wrapping $10 <-> 0 (buster); owned {1,3,5,8} | R x12 then L x12: [2, 6, 10, 16, 0, 2, 6, 10, 16, 0, 2, 6, 2, 0, 16, 10, 6, 2, 0, 16, 10, 6, 2, 0] |
| weapons: control — unowned weapons (2, 4, 6, 7) and the 9th slot ($12) are never selected | selections seen [0, 2, 6, 10, 16] |
| weapons: bit 7 of the high byte is the HUD bar redraw flag: selecting weapon 1 (word $DC00) -> bar open writes $DC (pc $80:D920), bar drawn writes $5C (pc $80:D961); word $5C00 after | w1 $DC00; writes [('0xdc', '$80D920'), ('0x5c', '$80D961'), ('0x5c', '$80D9AE')]; then $5C00 |
| weapons: L+R together selects the buster ($81:9A14) from weapon 3 | sw_buster f=[40, 41], $0BDB 6 -> [0, 0] |
| weapons: no switching while a shot is out: R at frame 34 (Boomerang Cutter out) ignored, R at 200 (no shot) moves 14 -> 16 | cutter on screen f 31-91; $0BDB writes [(200, 15), (200, 16)] |
| weapons: X-Buster: fires only while X's shot counter $35 < $67 = 3 ($86:BAB8[0], set by the switch; $81:9447) | ROM 3; $0BDB -> 0, $67 <- None; fired at $35 = [0, 1, 2], blocked 17x at $35 = [3]; max $35 = 3; max shots id 0 = 3 |
| weapons: Homing Torpedo: fires only while X's shot counter $35 < $67 = 2 ($86:BAB8[1], set by the switch; $81:9447) | ROM 2; $0BDB -> 2, $67 <- 2; fired at $35 = [0, 1], blocked 15x at $35 = [2]; max $35 = 2; max shots id 7 = 2 |
| weapons: Chameleon Sting: fires only while X's shot counter $35 < $67 = 1 ($86:BAB8[2], set by the switch; $81:9447) | ROM 1; $0BDB -> 4, $67 <- 1; fired at $35 = [0], blocked 9x at $35 = [1]; max $35 = 4; max shots id 8 = 4 |
| weapons: Rolling Shield: fires only while X's shot counter $35 < $67 = 1 ($86:BAB8[3], set by the switch; $81:9447) | ROM 1; $0BDB -> 6, $67 <- 1; fired at $35 = [0], blocked 26x at $35 = [1]; max $35 = 1; max shots id 9 = 1 |
| weapons: Fire Wave: fires only while X's shot counter $35 < $67 = 6 ($86:BAB8[4], set by the switch; $81:9447) | ROM 6; $0BDB -> 8, $67 <- 6; fired at $35 = [0, 1, 2, 3, 4, 5], blocked 0x at $35 = []; max $35 = 5; max shots id 10 = 5 |
| weapons: Storm Tornado: fires only while X's shot counter $35 < $67 = 1 ($86:BAB8[5], set by the switch; $81:9447) | ROM 1; $0BDB -> 10, $67 <- 1; fired at $35 = [0], blocked 43x at $35 = [1]; max $35 = 1; max shots id 11 = 1 |
| weapons: Electric Spark: fires only while X's shot counter $35 < $67 = 3 ($86:BAB8[6], set by the switch; $81:9447) | ROM 3; $0BDB -> 12, $67 <- 3; fired at $35 = [0, 1, 2], blocked 2x at $35 = [3, 4]; max $35 = 5; max shots id 12 = 5 |
| weapons: Boomerang Cutter: fires only while X's shot counter $35 < $67 = 3 ($86:BAB8[7], set by the switch; $81:9447) | ROM 3; $0BDB -> 14, $67 <- 3; fired at $35 = [0, 1, 2], blocked 0x at $35 = []; max $35 = 3; max shots id 13 = 3 |
| weapons: Shotgun Ice: fires only while X's shot counter $35 < $67 = 1 ($86:BAB8[8], set by the switch; $81:9447) | ROM 1; $0BDB -> 16, $67 <- 1; fired at $35 = [0], blocked 32x at $35 = [1, 2, 3]; max $35 = 5; max shots id 14 = 5 |
| weapons: Homing Torpedo: shot costs $0080 (projectile 7); full arm charge costs $0300 in all (projectile 16) | normal f=30 $DC00 -> $DB80 id 7; charged f=230 $DB80 -> $D880 id 16; ROM $86:BA92 $0080 + $86:BAA4 $0280 |
| weapons: Chameleon Sting: shot costs $0080 (projectile 8); full arm charge costs $0400 in all (projectile 17) | normal f=30 $DC00 -> $DB80 id 8; charged f=230 $DB80 -> $D780 id 17; ROM $86:BA92 $0080 + $86:BAA4 $0380 |
| weapons: Rolling Shield: shot costs $0100 (projectile 9); full arm charge costs $0200 in all (projectile 18) | normal f=30 $DC00 -> $DB00 id 9; charged f=230 $DB00 -> $D900 id 18; ROM $86:BA92 $0100 + $86:BAA4 $0100 |
| weapons: Fire Wave: shot costs $0010 (projectile 10); full arm charge costs $0300 in all (projectile 19) | normal f=30 $DC00 -> $DBF0 id 10; charged f=230 $D930 -> $D630 id 19; ROM $86:BA92 $0010 + $86:BAA4 $02F0 |
| weapons: Storm Tornado: shot costs $0100 (projectile 11); full arm charge costs $0200 in all (projectile 20) | normal f=30 $DC00 -> $DB00 id 11; charged f=230 $DB00 -> $D900 id 20; ROM $86:BA92 $0100 + $86:BAA4 $0100 |
| weapons: Electric Spark: shot costs $0100 (projectile 12); full arm charge costs $0200 in all (projectile 21) | normal f=30 $DC00 -> $DB00 id 12; charged f=230 $DB00 -> $D900 id 21; ROM $86:BA92 $0100 + $86:BAA4 $0100 |
| weapons: Boomerang Cutter: shot costs $0100 (projectile 13); full arm charge costs $0200 in all (projectile 22) | normal f=30 $DC00 -> $DB00 id 13; charged f=230 $DB00 -> $D900 id 22; ROM $86:BA92 $0100 + $86:BAA4 $0100 |
| weapons: Shotgun Ice: shot costs $0100 (projectile 14); full arm charge costs $0180 in all (projectile 23) | normal f=30 $DC00 -> $DB00 id 14; charged f=230 $DB00 -> $D980 id 23; ROM $86:BA92 $0100 + $86:BAA4 $0080 |
| weapons: Fire Wave held 60 frames: 16 flames at $10 each = 1 unit | 16 flames, $DC00 -> $DB00 |
| weapons: control — no ammo (word $C000): pressing Y fires nothing ($81:94E3 BIT #$3F00) | pre 1x, post 0, shots id 9: 0; w3 $C000 |
| weapons: charging a special weapon needs the arm ($81:97DA BIT #$02): Rolling Shield held 200 frames without it -> one normal shot only, no charged projectile 18, 1 unit used | arm_test 252x; projectiles [9]; shot ids [9]; w3 $DB00 |
| weapons: big pickup (sub-id 0) = 8 units into the current weapon, 1 unit ($100) every 4 frames | w3 $C400 -> ['$C500', '$C600', '$C700', '$C800', '$C900', '$CA00', '$CB00', '$CC00'], ticks f=[66, 70, 74, 78, 82, 86, 90, 94] |
| weapons: small pickup (sub-id != 0) = 2 units | w3 $C400 -> $C600 |
| weapons: current weapon full -> the energy goes to the first owned non-full weapon (give_weapon_energy ($81:E11A)) | w1 $DA00 -> $DC00, w3 stays $DC00, w5 stays $C000 |
| weapons: buster selected -> first owned non-full weapon from w1 up (w1 full and w2 unowned skipped) | w1 $DC00 w2 $0000 w3 $C400 -> $C600 w5 $C000 |
| weapons: overflow passes on: big pickup on weapon 3 at 26 -> w3 28 (2 units), then 6 spill: w1 27 -> 28, the 5 left go to w2 (0 -> 5) | w1 $DB00->$DC00 w2 $C000->$C500 w3 $DA00->$DC00 w4 $C000->$C400 w5 $0000->$0000 w6 $C800->$CC00 w7 $DC00->$DC00 w8 $DC00->$DC00 |
| weapons: game quirk: give_weapon_energy ($81:E11A) never clears its overflow flag $0002, and runs before the current weapon's final $1C00 store, so after an overflow every later owned non-full weapon gets the current remainder: w3 (still 27) +5 -> 28 leaving 4, then w4 0 -> 4 and w6 8 -> 12 (8 units picked up, 17 given); unowned w5 and full w7/w8 untouched | w4 $C400 w5 $0000 w6 $CC00 |
| weapons: $1F98 is the 9th bar, drawn under ESCAPE.U in the pause menu (read by LDA $1F88,X at $80:CA91, X = $10): $5C -> 28 segments, $4A -> 10; control: bit 6 clear ($1C) -> no bar | segments on row 114: {'full': 28, 'ten': 10, 'unowned': 0}; read pcs ['$80CA94', '$80CB77'] |

### Zero's buster and the Hadouken (23)

| claim | evidence |
|---|---|
| Zero ($66) after Vile ($1F7D = 2), X without the arm: text $1D, then TSB $1F99 #$02 ($88:D7D5) and INC $0C38 ($88:D7D8); $1F7D -> 3, $1F81 -> 2; $1F9B untouched | Zero step $0E at (3044, 1447); text ids [29]; $1F99 writes [(2317, 2, '0x88d7d8')]; $0C38 [(1, '0x88d7db')]; $1F7D [3], $1F81 [(1, '0x88db1a'), (2, '0x88d809')]; $1F9B writes after f200: 0; at the end $1F99 = $02 |
| Zero with the arm already owned: text $1C, no write to $1F99 or $0C38 (no gift); $1F7D -> 3; $1F9B untouched | text ids [28]; $1F99 writes 0, $0C38 writes 0; $1F7D [3]; $1F9B writes after f200: 0 |
| Hadouken motion: Down alone -> stage 2, Down+forward -> 4, forward alone -> 6 (X+$7F), each setting the timer X+$80 to 20; then shoot -> step $42 | (stage, timer, dpad) [(2, 20, 4), (4, 20, 5), (6, 20, 1)]; go at f[26], shot ids [4] |
| forward is X's facing: Down, Down+Left, Left works too (Down+Left turns X left, then matches $06) | facing $40 -> 0 at f23 (dpad 6), stage 4 at f24; go [26], ids [4] |
| exact match: without a Down-alone frame (Down+Right first) no Hadouken | go [], ids [0] |
| shoot released also triggers it (Y held through the motion: the press fires a buster shot, the release the Hadouken) | go at f[30], ids [0, 4] |
| window: Down+forward 20 frames after Down still counts, 21 frames is too late | 20: go [42]; 21: go [] |
| window: shoot 20 frames after the first forward frame still counts, 21 is too late | 20: go [44]; 21: go [] |
| allowed steps: standing (0), walking (2 and 4), landing ($0A) | step when it fired: {'last20': [0], 'basic': [2], 'walk': [4], 'land': [10]} |
| in the air (jump steps 6/8) no Hadouken | steps ['0x0', '0x6', '0x8', '0xa'], ids [0] |
| needs $1F7E bit 7 (no Hadouken with $1F7E = 0) | go [], ids [0] |
| needs HP exactly 32 (none at 31) | hp31: go [], ids [0] |
| step $42 lasts 42 frames, then step 0 | step $42 f27..f68 (42 frames) |
| projectile 4 (hadouken_fire ($81:A114)) spawned 17 frames after step $42 starts, at X+25 px, X-3 px, moving 4 px a frame (vx $400, from its 2nd frame); sound $AF | spawn exec f[43] (exec f = frame - 1; step $42 from f27), shot at (5175, 2716) vs X (5150, 2719), dx [4], vx [0, 1024], sounds ['0xaf'] |
| Hadouken on Armadillo (class $0B): 32 damage, HP 32 -> 0 in one hit (state 6) | hit ($1F1D = 4) at f[256]; boss before {'f': 256, 'tag': 'boss', 'hp': 32, 'cls': 11, 'st': 4}, after {'f': 257, 'tag': 'boss', 'hp': 0, 'cls': 11, 'st': 6} |
| Armadillo's guard (class 0) blocks it: the hit registers ($1F1D = 4), no damage | hit at f[70]; boss class 0, HP after [32] |
| capsule $4D init ($87:CA86) on level 3: $1F7E += 1 (0 -> 1); below 5 it deletes itself | inits f[431], $1F7E writes [1], objects [(251, 1), (432, 0)] |
| cap: the count is stored as 5 once it reaches 5 (preset 9 -> 10 -> 5) | writes [10, 5], objects [(251, 1), (432, 0)] |
| 5th spawn with every upgrade ($1F99 & $1F9C == $FF), $1F7C bit 6 and HP 32: the capsule stays | writes [5, 5], objects [(251, 1)] |
| 5th spawn, one condition missing (HP 31 / a heart $1F9C = $7F / the arm $1F99 = $FD / $1F7C = 0): deleted | (writes, stays) {'hp31': ([5, 5], False), 'heart': ([5, 5], False), 'upg': ([5, 5], False), '7C': ([5, 5], False)} |
| Hadouken owned ($1F7E bit 7): no count, the capsule deletes itself | inits [431], writes [], objects [(251, 1), (432, 0)] |
| dying and respawning spawns the capsule again and counts again (1 -> 2): the counter survives death | inits f[431, 1071], writes [1, 2], X fell to y 2818 |
| scrolling the camera away (264 px down) and back, twice: no new spawn, no count | inits f[431], writes [1], camera y 2279..2543 |

### Armor parts (11)

| claim | evidence |
|---|---|
| body (upgrades $04): x_take_damage takes ceil(d/2) (1->1, 2->1, 3->2, 5->3, 8->4); full d without it | HP 12 minus: d 1: 1 / body 1, d 2: 2 / body 1, d 3: 3 / body 2, d 5: 5 / body 3, d 8: 8 / body 4 |
| body: x_contact_damage halves Armadillo's contact hits too (6->3, 4->2) | hits (damage, HP before) no armor [(6, 16), (4, 10)] -> HP 6; body [(3, 16), (2, 13)] -> HP 11 |
| legs (upgrades $08): Right tapped twice dashes (step $14) if the second press comes <= 12 frames after the first (gaps 1, 4, 10, 11 released frames), not after 13-14 (gaps 12, 13: a walk) | first press f20; dash starts at gap 1: 23, gap 4: 26, gap 10: 32, gap 11: 33, gap 12: None, gap 13: None |
| legs: the double-tap dash runs at $375; without the legs the same taps only walk | dash vx 885; steps without legs {1: ['0x0', '0x2', '0x4'], 4: ['0x0', '0x2', '0x4'], 11: ['0x0', '0x2', '0x4']} |
| legs: a Left double tap dashes left (none without the legs) | legs: step $14 at f65; no legs: None |
| arm (upgrades $02): Chameleon Sting held 200 frames: no charge without the arm (shot 8 only); with it the charge reaches level 1 and the release fires the charged Sting (shot $11) | (charge_state, level) seen / shot ids: no arm ([(0, 0)], [8]); arm ([(0, 0), (2, 0), (4, 1), (4, 2), (4, 3)], [8, 17]) |
| helmet (upgrades $01): jumping into Storm Eagle's $3C block breaks it (tile +1, sound $23); without it X hits the same ceiling and nothing breaks | helmet: 12 tile changes in frames [475, 483, 494, 530, 569, 608], sound $23 each: True; no helmet: 6 ceiling hits, 0 tile changes, 0 sounds $23 |
| helmet: X keeps rising through the broken block (jump step lasts longer than the 4 frames to the ceiling) | jump-step lengths: no helmet [4, 4, 4], helmet [26, 12, 12] |
| helmet: X's own sprite set ($0BBE) is $18 with the helmet, 0 without | $0BBE standing: no helmet [0], helmet [24] |
| helmet: a falling rock (enemy $18, Chameleon's cave) hitting X from above does nothing with the helmet; without it 1 damage and knockback (step $0E) | (hit frame, damage calls, final HP, knocked back): no helmet (648, 1, 15, True), helmet (648, 0, 16, False) |
| legs: kicking off Sting Chameleon's $3C wall (x 1392) breaks it (tile +1, sound $23); not with no armor or with the helmet alone | ($3C-wall kicks, legs branch, tile changes, sound $23 each): legs (6, 6, 6, True), none (12, 0, 0, True), helmet (12, 0, 0, True) |

### Sub tanks, heart tanks, life energy (26)

| claim | evidence |
|---|---|
| sub tank: touch -> first free slot $1F83 = $80 (owned, empty), sub-id $80 into $1F99, all six freeze flags $1F13-$1F18 = 1, sound $29 | f435: $1F83 $00->$80, $1F99 = $80, freeze bits 111111, sound $29 at f[434] |
| sub tank: freeze 80 frames ($27 = $50), then unfreeze and delete | wait step f435..f514 (80 frames), freeze cleared f516, deleted f517 |
| sub tank: state 0 deletes it if its own bit is already in $1F99 | $1F99 = $80 at f200: item f237 state 0, gone f426; $1F83 stays $00 |
| sub tank: only its own bit counts ($1F99 = $7F -> still collected) | $1F99 -> $FF, $1F83 = $80 |
| sub tank: slot 0 already owned -> next slot $1F84 = $80 | $1F83 = $85, $1F84 = $80, $1F99 = $80 |
| sub tank: all 4 slots owned -> deleted (state 4) without its bit, no freeze | touch f434, state 4 f435, gone f436; $1F99 = $00, slots ['$80', '$80', '$80', '$80'], freeze seen: False |
| life energy at full HP: large ($0B & $7F = 0) +2 units, small +1 unit into the tank | large $80->$82, small ($0B forced $81) $80->$81, HP stays 16 |
| life energy: tank capped at $8E (14 units, no spill: $8D + large = $8E), sound $2B when it becomes full | $8D -> $8E, $1F84 = $00, $2B at f[453] |
| life energy: fills only the first owned (bit 7) non-full slot, in order 0..3 | ($8E,$80) -> ($8E,$82); unowned slot 0 ($00,$85) -> ($00,$87); only a full tank ($8E,$00) -> ($8E,$00) |
| life energy below full HP: large +8 HP, +1 every 4 frames (sound $0C), objects frozen ($1F13-$1F19) | HP 4->12 at f[458, 462, 466, 470, 474, 478, 482, 486]; $1F19 [(425, 0), (454, 1), (487, 0)]; tank stays $80 |
| life energy: small +2 HP | HP [(425, 10), (459, 11), (463, 12)] |
| life energy: HP stops at max, the rest is lost (not put into a tank) | large at HP 12: [(425, 12), (458, 13), (462, 14), (466, 15), (470, 16)], tank $80; small at HP 15: -> 16, tank $80 |
| menu: Start, Down, Y uses tank 0 (cursor $0A); +1 HP and -1 unit every 4 frames (tank $85, HP 10) | start f640 cursor 10; HP [10, 11, 12, 13, 14, 15]; tank ['$85', '$84', '$83', '$82', '$81', '$80']; ticks f[644, 648, 652, 656, 660] |
| menu: nothing at full HP; B does nothing | HP 16: tank $8E, no use; B at HP 10: tank $8E, HP 10 |
| menu: the tank drains to $80 even after HP is full (excess wasted) | HP [14, 15, 16] full at f649; tank keeps draining until $80 at f697 (14 ticks) |
| menu (game bug): the +2-HP-a-tick check for a full tank reads slot X_hp-10, not the cursor's slot | tank 0 $8E: HP 10 (index 0) step 2 HP [10, 12, 14, 16]; HP 11 (index 1, $1F84 = 0) step 1 HP [11, 12, 13, 14, 15, 16]; HP 11 with $1F84 = $8E: X = 1, step 2, cursor $0A, HP [11, 13, 15, 16] |
| menu: an emptied tank is moved behind the remaining owned non-empty ones (subtank_compact ($80:CDA1)) | ($8E,$8E), tank 0 used up after 14 ticks -> ($1F83,$1F84) = ($8E,$80) |
| heart (Armadillo, $02): bit into $1F9C, freeze 80 frames (sound $29), then 8 frames of palette flash ($0703+4k ^= 4) with max HP +1 and HP +1 every 4 frames, 2 times (sound $0C), then unfreeze | touch f432 $1F9C = $02; wait f432..f511; max [(516, 17), (520, 18)], HP [(516, 17), (520, 18)] ([4, 8] frames into the raise step); $0703 = $30 at f[513, 515, 517, 519], $34 otherwise; unfreeze f521 |
| heart (Chill Penguin, $01): bit into $1F9C, freeze 80 frames (sound $29), then 8 frames of palette flash ($0703+4k ^= 4) with max HP +1 and HP +1 every 4 frames, 2 times (sound $0C), then unfreeze | touch f437 $1F9C = $01; wait f437..f516; max [(521, 17), (525, 18)], HP [(521, 17), (525, 18)] ([4, 8] frames into the raise step); $0703 = $30 at f[518, 520, 522, 524], $34 otherwise; unfreeze f526 |
| heart (Storm Eagle, $04): bit into $1F9C, freeze 80 frames (sound $29), then 8 frames of palette flash ($0703+4k ^= 4) with max HP +1 and HP +1 every 4 frames, 2 times (sound $0C), then unfreeze | touch f513 $1F9C = $04; wait f513..f592; max [(597, 17), (601, 18)], HP [(597, 17), (601, 18)] ([4, 8] frames into the raise step); $0703 = $30 at f[594, 596, 598, 600], $34 otherwise; unfreeze f602 |
| heart (Flame Mammoth, $10): bit into $1F9C, freeze 80 frames (sound $29), then 8 frames of palette flash ($0703+4k ^= 4) with max HP +1 and HP +1 every 4 frames, 2 times (sound $0C), then unfreeze | touch f435 $1F9C = $10; wait f435..f514; max [(519, 17), (523, 18)], HP [(519, 17), (523, 18)] ([4, 8] frames into the raise step); $0703 = $30 at f[516, 518, 520, 522], $34 otherwise; unfreeze f524 |
| heart: state 0 deletes it if its own bit is already in $1F9C | $1F9C = $02 at f200: state 0 f249, gone f429; max stays 16 |
| heart: only its own bit counts ($1F9C = $FD -> collected) | $1F9C -> $FF (max 16 at f450, still in the wait) |
| heart: HP is not refilled when not full, just +1 per step | HP [(425, 10), (516, 11), (520, 12)], max [(425, 16), (516, 17), (520, 18)] |
| heart: max $1F -> one step to $20, then it ends (cap $20) | max [(425, 31), (516, 32)], HP [(425, 31), (516, 32)]; raise step f512..f515 (4 frames instead of 8) |
| heart: max already $20 -> bit still set first, nothing else (no freeze), deleted | $1F9C = $02, max $20, freeze seen: False; state 4 f432, gone f433 |

### Dr. Light's capsules (52)

| claim | evidence |
|---|---|
| eagle: capsule at $86:D33E[5] and rises 96 px (2 px a frame) | table $0FC8,$02D1; first main-state record x=$0FC8 y=$02D1; y 721 at f433 -> 625 at f481 (substate 2): 96 px in 48 frames |
| eagle: X touches the capsule -> X step $1E, camera lock $86:D3A1[5] | f510: lock = 3840,3840,496,496 (table $0F00,$01F0); X step $1E |
| eagle: Dr. Light ($5C) text id $86:D4E3[5] = $0C; leaving frees X and restores the camera | text box f571 id $0C; light gone f1327, X step 0, lock x/y after (0, 0) |
| eagle: scene sub2 0/2/4/6/8/A/C last 1/20/255/128/30/30/60 frames ($33) | 0->2:1 2->4:20 4->6:255 6->8:128 8->A:30 A->C:30 C->E:60; countdowns [True, True, True, True, True, True] |
| eagle: X in the scene: x = capsule x, step $1E -> $38 (sub2 C) -> 0 | sub2 2 f1365, C f1828, E f1888; X steps [(1365, '0x1e'), (1828, '0x38'), (1887, '0x0')] |
| eagle: orb $4E (index 0) spawned at $33 = $14; TSB $1F99 with $01 by the first orb only (2 events), second orb (A=1) grants nothing | spawns [(1619, 0, 20), (1797, 1, 30)]; grants [(1683, 1, 0, 0), (1684, 1, 0, 0)] |
| eagle: helmet $01 granted | $0BBE (X gfx) writes ['0x18', '0x18']; $1F99 -> [1, 1] |
| eagle: demo pad script [(16, '0x0'), (40, '0x2'), (64, '0x80')] played exactly into $00A7, then control returns ($1F48 = 0, hurt lock 0) | f1889..2008: 120/120 frames match; sub2 $10 at f2009, ram at end {'f': 2009, 'tag': 'ram', 'f48': 0, 'hurt': 0} |
| mammoth: capsule at $86:D33E[4] | table $093B,$0293; first main-state record x=$093B y=$0293 |
| mammoth: X touches the capsule -> X step $1E, camera lock $86:D3A1[4] | f439: lock = 2304,2304,512,512 (table $0900,$0200); X step $1E |
| mammoth: Dr. Light ($5C) text id $86:D4E3[4] = $0E; leaving frees X and restores the camera | text box f527 id $0E; light gone f1383, X step 0, lock x/y after (16, 256) |
| mammoth: scene sub2 0/2/4/6/8/A/C last 1/20/255/128/30/30/60 frames ($33) | 0->2:1 2->4:20 4->6:255 6->8:128 8->A:30 A->C:30 C->E:60; countdowns [True, True, True, True, True, True] |
| mammoth: X in the scene: x = capsule x, step $1E -> $38 (sub2 C) -> 0 | sub2 2 f1412, C f1875, E f1935; X steps [(1412, '0x1e'), (1875, '0x38'), (1934, '0x0')] |
| mammoth: orb $4E (index 1) spawned at $33 = $14; TSB $1F99 with $02 by the first orb only (2 events), second orb (A=1) grants nothing | spawns [(1666, 0, 20), (1844, 1, 30)]; grants [(1730, 2, 1, 0), (1731, 2, 1, 0)] |
| mammoth: arm $02 granted - X sprite-part slot switched on | $0C38 (X part object) -> [1, 2] (INC twice: the event fires on 2 frames); $1F99 -> [2, 2] |
| mammoth: demo pad script [(16, '0x0'), (40, '0x1'), (208, '0x40'), (32, '0x0')] played exactly into $00A7, then control returns ($1F48 = 0, hurt lock 0) | f1936..2231: 296/296 frames match; sub2 $10 at f2232, ram at end {'f': 2232, 'tag': 'ram', 'f48': 0, 'hurt': 0} |
| chameleon: capsule at $86:D33E[2] and rises 96 px (2 px a frame) | table $06D8,$01F0; first main-state record x=$06D8 y=$01F0; y 496 at f1580 -> 400 at f1628 (substate 2): 96 px in 48 frames |
| chameleon: X touches the capsule -> X step $1E, camera lock $86:D3A1[2] | f1649: table 0 -> camera bounds unchanged ((1536, 256)); X step $1E |
| chameleon: Dr. Light ($5C) text id $86:D4E3[2] = $0D; leaving frees X and restores the camera | text box f1693 id $0D; light gone f2407, X step 0, lock x/y after (1536, 256) |
| chameleon: scene sub2 0/2/4/6/8/A/C last 1/20/255/128/30/30/60 frames ($33) | 0->2:1 2->4:20 4->6:255 6->8:128 8->A:30 A->C:30 C->E:60; countdowns [True, True, True, True, True, True] |
| chameleon: X in the scene: x = capsule x, step $1E -> $38 (sub2 C) -> 0 | sub2 2 f2432, C f2895, E f2955; X steps [(2432, '0x1e'), (2895, '0x38'), (2954, '0x0')] |
| chameleon: orb $4E (index 2) spawned at $33 = $14; TSB $1F99 with $04 by the first orb only (2 events), second orb (A=1) grants nothing | spawns [(2686, 0, 20), (2864, 1, 30)]; grants [(2750, 4, 2, 0), (2751, 4, 2, 0)] |
| chameleon: body $04 granted - X sprite-part slot switched on | $0C58 (X part object) -> [1, 2] (INC twice: the event fires on 2 frames); $1F99 -> [4, 4] |
| chameleon: demo pad script [] played exactly into $00A7, then control returns ($1F48 = 0, hurt lock 0) | f2956..2955: 0/0 frames match; sub2 $10 at f2956, ram at end {'f': 2956, 'tag': 'ram', 'f48': 0, 'hurt': 0} |
| penguin: capsule at $86:D33E[8] | table $09E0,$0270; first main-state record x=$09E0 y=$0270 |
| penguin: X touches the capsule -> X step $1E, camera lock $86:D3A1[8] | f481: lock = 2480,2480,512,512 (table $09B0,$0200); X step $1E |
| penguin: Dr. Light ($5C) text id $86:D4E3[8] = $0B; leaving frees X and restores the camera | text box f586 id $0B; light gone f3279, X step 0, lock x/y after (2304, 256) |
| penguin: scene sub2 0/2/4/6/8/A/C last 1/20/255/128/30/30/60 frames ($33) | 0->2:1 2->4:20 4->6:255 6->8:128 8->A:30 A->C:30 C->E:60; countdowns [True, True, True, True, True, True] |
| penguin: X in the scene: x = capsule x, step $1E -> $38 (sub2 C) -> 0 | sub2 2 f3315, C f3778, E f3838; X steps [(3315, '0x1e'), (3778, '0x38'), (3837, '0x0')] |
| penguin: orb $4E (index 3) spawned at $33 = $14; TSB $1F99 with $08 by the first orb only (2 events), second orb (A=1) grants nothing | spawns [(3569, 0, 20), (3747, 1, 30)]; grants [(3633, 8, 3, 0), (3634, 8, 3, 0)] |
| penguin: legs $08 granted - X sprite-part slot switched on | $0C78 (X part object) -> [1, 2] (INC twice: the event fires on 2 frames); $1F99 -> [8, 8] |
| penguin: demo pad script [(16, '0x0'), (40, '0x1'), (16, '0x0'), (1, '0x1'), (1, '0x0'), (32, '0x1'), (32, '0x0')] played exactly into $00A7, then control returns ($1F48 = 0, hurt lock 0) | f3839..3976: 138/138 frames match; sub2 $10 at f3977, ram at end {'f': 3977, 'tag': 'ram', 'f48': 0, 'hurt': 0} |
| penguin: the demo's double tap of Right dashes (X step $14 for 32 frames, then $20) | X steps [(3856, '0x2'), (3861, '0x4'), (3876, '0x8'), (3888, '0x4'), (3896, '0x0'), (3912, '0x2'), (3913, '0x0'), (3914, '0x14'), (3946, '0x20'), (3954, '0x0')] |
| armadillo: capsule at $86:D33E[3] | table $12EC,$0943; first main-state record x=$12EC y=$0943 |
| armadillo: X touches the capsule -> X step $1E, camera lock $86:D3A1[3] | f469: table 0 -> camera bounds unchanged ((4672, 2176)); X step $1E |
| armadillo: Dr. Light ($5C) text id $86:D4E3[3] = $19; leaving frees X and restores the camera | text box f513 id $19; light gone f1008, X step 0, lock x/y after (4672, 2176) |
| armadillo: scene sub2 0/2/4/6/8/A/C last 1/20/255/128/30/30/60 frames ($33) | 0->2:1 2->4:20 4->6:255 6->8:128 8->A:30 A->C:30 C->E:60; countdowns [True, True, True, True, True, True] |
| armadillo: X in the scene: x = capsule x, step $1E -> $38 (sub2 C) -> 0 | sub2 2 f1033, C f1496, E f1556; X steps [(1033, '0x1e'), (1496, '0x38'), (1555, '0x0')] |
| armadillo: orb $4E (index 1) spawned at $33 = $14; TSB $1F99 with $02 by the first orb only (2 events), second orb (A=1) grants nothing | spawns [(1287, 0, 20), (1465, 1, 30)]; grants [(1351, 2, 1, 0), (1352, 2, 1, 0)] |
| armadillo: Hadouken ($1F7E \|= $80) granted | $1F7E writes ['0x85', '0x85']; $0C38 writes by the handler [] |
| armadillo: demo pad script [(2, '0x0'), (2, '0x4'), (2, '0x6'), (2, '0x2'), (1, '0x40'), (32, '0x0')] played exactly into $00A7, then control returns ($1F48 = 0, hurt lock 0) | f1557..1597: 41/41 frames match; sub2 $10 at f1598, ram at end {'f': 1598, 'tag': 'ram', 'f48': 0, 'hurt': 0} |
| armadillo: the demo's Down, Down+Left, Left, Y puts X in step $42 (Hadouken) | X steps [(1562, '0x4'), (1566, '0x42')] |
| X init ($81:9D88) creates part objects $0C38/$0C58/$0C78 from $1F99 bits $02/$04/$08 and sets gfx $0BBE = $18 for bit $01 | slot writes {3128: [1], 3160: [1], 3192: [1]}; gfx writes [0, 24] |
| eagle, helmet owned ($1F99 = $01): the capsule deletes itself at init | capsule records [(248, (0, 0, 0)), (433, 'gone')]; despawn f[431] |
| armadillo: all conditions but X HP $1F -> $1F7E = 5, capsule deletes itself (no Hadouken) | capsule records [(255, (0, 0, 0)), (432, 'gone')]; $1F7E writes [5, 5] |
| armadillo: init counts $1F7E 4 -> 5 and the capsule appears (all upgrades, hearts, bosses, HP $20) | $1F7E writes [5, 5] |
| chameleon: event type 2 id $1D at ($0600,$0140) -> $1D08-list object (code $87:FB40) | events [Event(blk=30 type=2 id=1D sub=00 x=0600 y=0140 match=00)]; object slot $1D08 at $0600,$0140 f251 |
| chameleon: X x >= $0630 -> X step $1E, camera lock x $0600 y $0100 | f569: X {'f': 569, 'tag': 'xs', 'step': 30, 'x': 1584, 'y': 431}; lock {'f': 569, 'tag': 'lock', 'x1': 1536, 'x2': 1536, 'y1': 256, 'y2': 256} |
| chameleon: camera in place -> six $1628-list id $11 objects 60 frames apart, enemy 9 at ($06D0,$00E0) with the 6th | state 4 f610; id $11 spawns [670, 730, 790, 850, 910, 970]; enemy 9 first f970 at ('0x6d0', '0xe0') |
| chameleon: enemy 9 gone -> 96 frames -> capsule $4D spawned (test aid: enemy 9's HP held at 1) | enemy 9 gone f1482, trigger state 8 f1482, capsule f1579 |
| chameleon: grant -> trigger state $0C the same frame; 180 frames, then 6 wall blocks at x $0610, y $0110..$01B0, 20 frames apart | grant f2751, state $0C f2751; breaks [(2931, '0x110'), (2951, '0x130'), (2971, '0x150'), (2991, '0x170'), (3011, '0x190'), (3031, '0x1b0')] |
| chameleon, body owned ($1F99 = $04): rocks and enemy 9 still come; the capsule deletes itself at init and the wall breaks anyway | trigger states {0: 251, 2: 570, 4: 611, 6: 971, 8: 1483, 10: 1580, 12: 1581, 14: 1861}; capsule [(1580, (0, 0, 0)), (1581, 'gone')]; breaks [1760, 1780, 1800, 1820, 1840, 1860] |

Side findings:
- Game quirk: weapon energy overflow reaches every later non-full weapon, because `give_weapon_energy` (`$81:E11A`)
  never clears its overflow flag (8 units picked up gave 17).
- Game bug: using a full sub tank gives +2 HP a tick only if slot X_hp − 10 is full (`subtank_menu_tick` (`$80:C723`)).
- Zero's buster is the arm upgrade (`upgrades` $02); `intro_cleared` (`$1F9B`) is never written by Zero.
- PLAYER.md's old note that the legs' bit was unknown is resolved: legs = `upgrades` $08.

## Boss rooms — confirmed (`verify_rooms.py`, 24/24 on 2026-10-21)

Each boss's fight-start state is loaded in Mesen; on its 20th frame the suite reads the camera (`screen_left` `$1E4D`,
`screen_top` `$1E50`), the camera borders (`border_left` `$1E5E`, `border_right` `$1E60`, `border_top` `$1E68`,
`border_bottom` `$1E6E`), X's and the boss's positions, and every 16×16 collision cell of the
screen through the game's own lookup (scene grid `$7E:E800`, map `$7E:2000`, table at `collision_table_ptr`).
`rooms.py` writes the result per room to `work/rooms/<boss>.json` (with the collision grid) and `<boss>.png`.

| room | camera (left, top) | camera borders | X | boss |
|---|---|---|---|---|
| Chill Penguin | 7680, 287 | x 7680–7680, y 256–287 | 7705, 431 | 7888, 428 |
| Storm Eagle | 5920, 47 | x 5632–6144, y 47–47 | 6047, 207 | 6192, 196 |
| Flame Mammoth | 7763, 543 | x 7680–7792, y 512–543 | 7891, 687 | 8012, 671 |
| Spark Mandrill | 7424, 768 | x 7424–7424, y 767–768 | 7451, 943 | 7632, 930 |
| Armored Armadillo | 5120, 2560 | x 5120–5120, y 2559–2560 | 5147, 2719 | 5328, 2678 |
| Launch Octopus | 7424, 512 | x 7424–7424, y 512–512 | 7451, 687 | 7607, 642 |
| Boomer Kuwanger | 1792, 0 | x 1792–1792, y 0–0 | 1819, 175 | 1980, 168 |
| Sting Chameleon | 7936, 256 | x 7936–7936, y 256–256 | 7963, 415 | 8067, 347 |

- In 7 rooms the ROM's collision (`testwarp.collision_at`) equals the game's lookup cell for cell (1,671 cells).
- **Storm Eagle's deck is not the ROM's layout**: on the first fight frame the level map in RAM has a flat deck at
  y 224 where the ROM's layout has a sloped one (38 of 240 cells differ), so his room's collision and picture are taken
  from the game.
- Flame Mammoth's camera can still scroll in the fight (x 7680–7792), and Chill Penguin's and Spark Mandrill's by a
  pixel or so vertically; the others are locked.
