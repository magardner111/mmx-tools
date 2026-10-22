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
