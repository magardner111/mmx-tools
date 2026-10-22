# The player (X)

X is an object like any other, but with a bigger slot: it starts at `$0BA8` and its fields run past `$40`
(up to at least `$8C`). His code runs with the direct page = `$0BA8`, so field `$30` is RAM `X_hurt_lock` (`$0BD8`).
Names marked (?) come from reading the code only; the rest were seen in Mesen (see `VERIFIED.md`).

## Fields (offset from `$0BA8`)

| field | RAM | name | what it does |
|---|---|---|---|
| `$01` | `$0BA9` | state | 0 = init, 2 = alive (table at `$81:819F`) |
| `$02` | `$0BAA` | step | what X is doing (table at `$81:82A6`, below) |
| `$05` | `$0BAD` | x | |
| `$08` | `$0BB0` | y | |
| `$22` | `$0BCA` | prev_x | X's x before this frame's move (verified: Flame Mammoth's oil puddle sets X's x to the average of this and the new x) |
| `$0E` | `$0BB6` | visible | toggled every frame by the flash timer, so X blinks |
| `$26` | `$0BCE` | pending_damage | taken off HP by `x_take_damage` / the contact path |
| `$27` | `$0BCF` | hp | bit 7 = redraw the HUD bar |
| `$2B` | `$0BD3` | touch | terrain contact bits |
| `$30` | `$0BD8` | **hurt_lock** | nonzero = can't be hurt. Raised by a hit (INC at `$84:9D2E`, `$84:9F32`), set to 8 by `x_grabbed`, 1 by a dying boss, cleared by `x_drop` and when the flash timer runs out (`$81:828A`) |
| `$6B` | `$0C13` | flash_timer | post-hit blinking; at 0, X is visible again and hurt_lock is cleared |
| `$85` | `$0C2D` | stun_timer | set by `x_stun`, counted down in step `$36` (verified) |
| `$87` | `$0C2F` | status_flags | bit 7 set while stunned (step `$36` sets and clears it); Spark Mandrill's punch quake doesn't stun X again while it's set (seen in Mesen: one stun per 30-frame quake) |
| `$89` | `$0C31` | (?) | a second "can't be hurt" source, ORed into `$8A` |
| `$4E` | `$0BF6` | step_timer | per-step frame count: walk start 5, landing 4, wall-jump pose 4 then push 8 (verified) |
| `$52` | `$0BFA` | dash_timer | 32 at the start of a dash, counted down (verified) |
| `$55` | `$0BFD` | dash_jump | set during a dash: a jump out of it keeps `move_speed` $375 (verified) |
| `$57` | `$0BFF` | charge_timer | 180 when the shoot button is pressed, counted down while held (verified) |
| `$58` | `$0C00` | charge_state | 0 idle, 2 held, 4 charged |
| `$59` | `$0C01` | shot_request | shot to fire, from `$86:BA71`[`charge_level`]: 2 half, 8 full, 4 arm level |
| `$5B` | `$0C03` | charge_level | 3 after 31 frames, 2 after 101, 1 after 180 with the arm upgrade (verified) |
| `$5C` | `$0C04` | move_speed | horizontal speed: $178 walking/jumping, $375 dashing (verified) |
| `$5F` | `$0C07` | fall_cap | −$580, set by init; the fall step clamps vy to it before gravity (verified: −$5C0 at full speed) |
| `$77` | `$0C1F` | wall_stick | 8 when a wall slide starts: vy held at 0 meanwhile (verified) |
| `$8A` | `$0C32` | **untouchable** | rebuilt every frame by X's update (`$81:8142`): `boss_defeated \| hurt_lock \| $89`. `hurt_x_on_contact` skips X while it's nonzero |

## The Action Replay code `7E0BD808` (no damage, walk through enemies)

It writes 8 to `hurt_lock` every frame. With `hurt_lock` stuck on and no flash timer running, X is in the
"just got hit" state without blinking: `untouchable` stays nonzero, so contact damage is skipped, and
`hurt_lock` without a flash timer also stops grabs (`$81:E70D`, `$81:ECA4` grab X only when
`hurt_lock = 0` or `flash_timer ≠ 0`). Falling into a pit still kills X (step `$0C`): that path doesn't
check any of these. `mesen_verify.Run.action_replay(NO_DAMAGE)` applies it in tests.

**It also stops boss doors from opening** (verified: Chill Penguin's door opens without the code, X goes
step `$1C` → `$1E` and the boss appears; with it, X stands at the door forever). Tests must turn it on only
after X is through the door.

## Steps (`$02`, jump table at `$81:82A6`, $00–$46)

| step | handler | name | meaning |
|---|---|---|---|
| `$00` | `$81:82EE` | `step_normal` | standing, under control; walks when Left/Right is held (seen in Mesen; `x_unfreeze` sets it) |
| `$02` | `$81:839D` | `step_walk_start` | starting to walk: 5 frames, then step 4 (seen in Mesen) |
| `$04` | `$81:8408` | `step_walk` | walking at 1.5 px a frame (steps of 1 and 2) (verified) |
| `$06` | `$81:8486` | `step_jump` | jump: vy $553, gravity 64, sound; letting go of jump ends it (step 8, vy reset to 0); about 56 px high (verified) |
| `$08` | `$81:8522` | `step_fall` | falling: vy clamped to `fall_cap` (−$580) before gravity, so −$5C0 (5.75 px) a frame at full speed (verified); `x_drop` sets it |
| `$0A` | `$81:8600` | `step_land` | landing: sound, `step_timer` 4, then step 0 (verified) |
| `$0C` | `$81:8A4F` | `step_dying` | dying: HP 0 or fell into a pit (seen in Mesen); enemies stop updating meanwhile (seen in Mesen: Storm Eagle's timer froze) |
| `$0E` | `$81:865B` | `step_hurt` | hurt / knockback: hurt_lock = 8, vx −$8A (backwards), vy $200 (halved with the armor, `upgrades` bit $04), gravity 64; flash_timer = 60 when the animation ends, then step 0 (verified) |
| `$10` | `$81:8718` | `step_wall_jump` | jump on a wall: 4 frames, then vx $178 away from the wall for 8 frames, then step 6 if jump is held, else a fall (verified) |
| `$12` | `$81:883E` | `step_wall_slide` | in the air pressing into a wall: vy 0 for 8 frames (`wall_stick`), then −$200 (2 px a frame down) (verified) |
| `$14` | `$81:890E` | `step_dash` | dash (needs `upgrades` bit $08): vx $375 for 32 frames (`dash_timer`) (verified) |
| `$20` | `$81:89AA` | `step_dash_end` | after a dash: 8 frames (`step_timer`), then step 0; jump or Left/Right cut it short (verified: 8 frames) |
| `$16` | `$81:8B3B` | `step_grabbed` | held by an enemy (`x_grabbed`); verified in Launch Octopus's drain: the boss sets X's x, y + 32 each frame, then X's update leaves him at y + 31 |
| `$18` | `$81:8B4D` | `step_hold` | held still (`x_hold`, previous step kept in `X_saved_step` (`$0C12`)) (?) |
| `$1C` | `$81:8B4E` | `step_boss_door` | walking through a boss door, then `$1E` (seen in Mesen: Chill Penguin's door) |
| `$1E` | `$81:8B57` | `step_boss_freeze` | frozen for a boss intro (`x_freeze_for_boss`) (seen in Mesen) |
| `$22` | `$81:89FA` | `step_beam_in` | beaming in (verified, see below; init sets it, or `$44` if `$1F7F` ≠ 0) |
| `$46` | `$81:8B57` | `step_boss_freeze` | held during Storm Eagle's platform ride and intro, let go the frame he starts fighting (seen in Mesen) |
| `$36` | `$81:9249` | `step_stunned` | stunned (`x_stun`): a stagger animation, then `stun_timer` counts down; lasts `stun_timer` + 32 frames (verified with Flame Mammoth's landing: 30 → 62, 14 → 46; and `x_stun(40)` called directly → 72) |
| `$34`, `$3A` | | | Sigma 4 ending, Sigma 4 cutscenes (?) |

`python3 decomp.py x` prints X's whole update as C with these names (symbols: `PLAYER` in `defs.py`).
The hurt step itself (`$0E`) sets hurt_lock = 8 and flash_timer = 60, so the AR value 8 is the same value
a normal hit uses.

## Routines

| address | name | |
|---|---|---|
| `$81:812E` | `x_update` | X's per-frame update: rebuilds `untouchable`, runs the state/step handler |
| `$84:9B03` | `hurt_x_on_contact` | enemies call it; skips X while `untouchable` / `boss_defeated` |
| `$84:9D07` | `x_contact_damage` | `hurt_lock += 1`, step `$0E`, HP −= pending (halved by upgrade bit 2) |
| `$84:9F2F` | `x_take_damage` | same, from projectiles / scripted damage |
| `$84:9F19` | `x_grabbed` | step `$16`, hurt_lock = 8 |
| `$84:9F7E` | `x_drop` | step 8, hurt_lock = 0 |
| `$84:9F8A` / `$84:9FB2` | `x_hold` / `x_resume` | |
| `$84:9FEB` / `$84:A003` | `x_freeze_for_boss` / `x_unfreeze` | |
| `$81:95EC` | `x_start_jump` | step 6 with the jump speeds; keeps the dash speed if `dash_jump` is set (verified) |
| `$81:9934` | `x_step_speeds` | vx (by facing), vy, gravity for the current step from the table at `$86:B9B1` (step × 3: vx word, vy word, gravity byte) (verified for steps 2, 4, 6, $0E, $10, $12, $14) |
| `$81:9662` / `$81:95D6` | `x_start_fall` / `x_to_normal` | step 8 / step 0 |
| `$81:984A` / `$81:9859` / `$81:988A` | `charge_idle` / `charge_start` / `charge_hold` | the charge state machine (`charge_state` 0/2/4); on release `shot_request` = `$86:BA71`[`charge_level`] (verified) |
| `$84:A00D` | `x_stun` | step `$36`, `stun_timer` (`$0C2D`) = A: X is stunned A + 32 frames (verified) |

## Beaming in (step `$22`) — verified

`$81:8A05` sets vy = −$800 (8 px a frame down); `$81:8A25` moves X until the floor bit (`$5E` & 4) is set,
then the landing animation. X starts at the checkpoint's y, and **terrain is ignored for the checkpoint's
`telDwn` frames** (18 in Storm Eagle's stage), so the start point must be `8 × (telDwn − 1)` px above the
floor. Started right above the floor, X sinks 136 px into it and snaps to some tile edge inside it (stuck:
walk and jump checks fail), or falls out of the stage where the floor is thin. Checked by starting at
floor − 136 (lands on the floor) and by patching `telDwn` to 6 (lands 6 frames after the beam starts).
`testwarp.py` now starts the beam up to 60 frames higher still (`LEAD`), limited to the open air above
the landing spot (more and X lands on a ledge above, as over Chill Penguin's room), so terrain is
already being checked when he reaches the floor. This fixes the old "falls through the floor in boss rooms".

X's y is his middle, not his feet: standing on a floor whose top is at 224, y = 207 (box at `$86:A552`:
y offset −1, half height $11).

## Controls — verified

| RAM | name | |
|---|---|---|
| `$00A7` | pad_held | player 1 buttons, SNES order (Right = $0100, Left = $0200, B = $8000, A = $0080) |
| `$00AB` | pad_pressed | newly pressed this frame |
| `$0BDF` (X+`$37`) | dpad | bit 0 Right, 1 Left, 2 Down, 3 Up; copied from `pad_held` by `x_read_buttons` (`$80:E54D`) |
| `$0BDE`/`$0BE0`/`$0BE2` (X+`$36/$38/$3A`) | buttons / last frame / new (?) | the other buttons, remapped through the button setup at `$7E:FFC4` |

Step 0 starts a walk (step 2) when Left/Right is held and `x_wall_check` (`$84:99AF`) (wall check in the facing direction,
carry = blocked) (?) allows it; facing is `$69` = $40 for right, 0 for left, set from Left/Right by `x_face_dpad` (`$81:9580`).

## Terrain lookup — verified

`probe_terrain` (`$84:90A0`): scene = `$7E:E800[(y>>8)×32 + (x>>8)]` (the scene grid has a fixed row
width of 32), map = word at `$7E:2000 + scene×$200 + ((y & $F0) << 1) + ((x & $FF) >> 3 & ~1)` (scenes
expanded to 16×16 cells), collision = byte at [`collision_table_ptr` (`$0B92`)] + map. `testwarp.collision_at` (read from the ROM)
gives the same answer for all 51,968 cells of Storm Eagle's stage.

## Moving and being pushed — verified (verify_storm_eagle.py)

X walks 1.5 px a frame. Without the leg upgrade he can't dash (the test save has none; setting bit 0 of
`upgrades` (`$1F99`) did not give him one, so where the legs are recorded is still unknown), so a push of
2 px a frame (Storm Eagle's Gust) beats walking; walking into it he still loses 0.5 px a frame. Pushes are
written straight into his position, `X_x` (`$0BAD`, with its fraction at `$0BAC`), not his speed.

## Shots and charging — verified (verify_player.py)

- Each press of the shoot button fires a buster shot (X's shot list `$1228`, id 0) at $440 (4.25 px a frame); at most
  3 are on screen at once.
- Holding the button: `charge_timer` 180, counting down. Held 31 frames (timer 150): charged, sound, palette flash;
  letting go fires projectile 1 (half charge). Held 101 frames (timer 80): projectile 3 (full charge). With the arm
  upgrade (`upgrades` bit $02), held 180 frames (timer 1): projectile 2 plus a second X-shot object, id $1D.
  The X-shot object id is the projectile id the damage tables use (`last_hit_projectile` was 3 for full charges).

## Upgrades (`upgrades`, `$1F99`)

| bit | effect | |
|---|---|---|
| `$08` | dash (step $14 on the dash button) | verified |
| `$04` | body armor: the knockback's vy is halved (and damage is halved, from the code) | verified (knockback) |
| `$02` | arm: a third charge level (projectile 2); charging special weapons | verified (buster) |
| `$01` | armored sprite set (`gfx` 24) (?) | |

Copy protection touches X: init (`$81:81A3`) clears `upgrades` if a random byte of the ROM's two halves differs, an SRAM check
(`$70:0800`, `$70:0804`) nudges `$1F9E`, and the jump/speed code checks its own bytes (`$81:8545`, `$81:853D`): a
mismatch sets `$1F9E` bit 7, which the jump step then uses as X's gravity.
