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
| `$06` | `$81:8486` | `step_jump` | jump (?): sound, rises under gravity, brakes vx |
| `$08` | `$81:8522` | `step_fall` | falling (seen in Mesen); `x_drop` sets it |
| `$0C` | `$81:8A4F` | `step_dying` | dying: HP 0 or fell into a pit (seen in Mesen); enemies stop updating meanwhile (seen in Mesen: Storm Eagle's timer froze) |
| `$0E` | `$81:865B` | `step_hurt` | hurt / knockback: sets hurt_lock = 8, flash_timer = 60 (seen in Mesen) |
| `$12` | `$81:883E` | `step_wall_slide` | sliding down a wall (seen in Mesen: down the side of the pit in Storm Eagle's stage) |
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
carry = blocked) (?) allows it; facing is `$69` = $40 for right, 0 for left (`$81:9580`).

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
