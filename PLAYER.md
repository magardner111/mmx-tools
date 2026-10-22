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
| `$16` | `$0BBE` | gfx | sprite set: $18 with the helmet (`upgrades` $01), set by init and by the helmet's capsule (verified) |
| `$7F` | `$0C27` | hadouken_stage | Hadouken motion: 2 after Down, 4 after Down+forward, 6 after forward (verified) |
| `$80` | `$0C28` | hadouken_timer | 20 at each stage: the next input must come within 20 frames (verified) |
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
| `$38` | `$81:92F3` | `step_capsule_pose` | X's pose after a capsule gives a part, about 60 frames, then step 0 (verified) |
| `$42` | `$81:9017` | `step_hadouken` | Hadouken: 42 frames; projectile 4 spawned 17 frames in (`hadouken_fire` (`$81:A114`)) (verified) |
| `$34`, `$3A` | | | Sigma 4 ending, Sigma 4 cutscenes (?) |

`python3 decomp.py x` prints X's whole update as C with these names (symbols: `PLAYER` in `defs.py`).
The hurt step itself (`$0E`) sets hurt_lock = 8 and flash_timer = 60, so the AR value 8 is the same value
a normal hit uses.

## Routines

| address | name | |
|---|---|---|
| `$81:812E` | `x_update` | X's per-frame update: rebuilds `untouchable`, runs the state/step handler |
| `$84:9B03` | `hurt_x_on_contact` | enemies call it; skips X while `untouchable` / `boss_defeated` |
| `$84:9D07` | `x_contact_damage` | `hurt_lock += 1`, step `$0E`, HP −= pending (ceil(d/2) with the body, `upgrades` $04) (verified) |
| `$84:9F2F` | `x_take_damage` | same, from projectiles / scripted damage (verified) |
| `$84:9F19` | `x_grabbed` | step `$16`, hurt_lock = 8 |
| `$84:9F7E` | `x_drop` | step 8, hurt_lock = 0 |
| `$84:9F8A` / `$84:9FB2` | `x_hold` / `x_resume` | |
| `$84:9FEB` / `$84:A003` | `x_freeze_for_boss` / `x_unfreeze` | |
| `$81:95EC` | `x_start_jump` | step 6 with the jump speeds; keeps the dash speed if `dash_jump` is set (verified) |
| `$81:9934` | `x_step_speeds` | vx (by facing), vy, gravity for the current step from the table at `$86:B9B1` (step × 3: vx word, vy word, gravity byte) (verified for steps 2, 4, 6, $0E, $10, $12, $14) |
| `$81:9662` / `$81:95D6` | `x_start_fall` / `x_to_normal` | step 8 / step 0 |
| `$81:984A` / `$81:9859` / `$81:988A` | `charge_idle` / `charge_start` / `charge_hold` | the charge state machine (`charge_state` 0/2/4); on release `shot_request` = `$86:BA71`[`charge_level`] (verified) |
| `$84:A00D` | `x_stun` | step `$36`, `stun_timer` (`$0C2D`) = A: X is stunned A + 32 frames (verified) |
| `$81:99D3` | `switch_weapon` | L/R weapon switching (verified, see Upgrades) |
| `$81:94AF` | `weapon_ammo_cost` | ammo per shot and the charged projectile id (verified) |
| `$81:A062` / `$81:A0EA` / `$81:A114` | `hadouken_input` / `hadouken_check` / `hadouken_fire` | the Hadouken (verified) |
| `$81:9731` | `double_tap_dash` | dash on a double tap of forward, with the legs (verified) |
| `$81:9EA1` / `$81:98FC` | `helmet_break_block` / `legs_break_wall` | breaking `$3C` blocks with the helmet / legs (verified) |

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

X walks 1.5 px a frame. Without the leg upgrade (`upgrades` (`$1F99`) bit $08) he can't dash, so a push of
2 px a frame (Storm Eagle's Gust) beats walking; walking into it he still loses 0.5 px a frame. Pushes are
written straight into his position, `X_x` (`$0BAD`, with its fraction at `$0BAC`), not his speed.

## Shots and charging — verified (verify_player.py)

- Each press of the shoot button fires a buster shot (X's shot list `$1228`, id 0) at $440 (4.25 px a frame); at most
  3 are on screen at once.
- Holding the button: `charge_timer` 180, counting down. Held 31 frames (timer 150): charged, sound, palette flash;
  letting go fires projectile 1 (half charge). Held 101 frames (timer 80): projectile 3 (full charge). With the arm
  upgrade (`upgrades` bit $02), held 180 frames (timer 1): projectile 2 plus a second X-shot object, id $1D.
  The X-shot object id is the projectile id the damage tables use (`last_hit_projectile` was 3 for full charges).

## Upgrades — verified (verify_upgrades.py, 149/149)

### Where they are kept

| RAM | name | contents |
|---|---|---|
| `$1F99` | `upgrades` | low nibble armor: `$01` helmet (Storm Eagle's capsule), `$02` arm (Flame Mammoth's, or Zero), `$04` body (Sting Chameleon's), `$08` legs (Chill Penguin's); high nibble sub tanks collected: `$10` Storm Eagle, `$20` Armored Armadillo, `$40` Spark Mandrill, `$80` Flame Mammoth |
| `$1F83` | `sub_tanks` | 4 slots `$1F83`-$1F86: bit 7 owned, energy = value − $80, full `$8E` (14 units) |
| `$1F9C` | `hearts` | bit per stage: `$01` Chill Penguin, `$02` Armored Armadillo, `$04` Storm Eagle, `$08` Sting Chameleon, `$10` Flame Mammoth, `$20` Boomer Kuwanger, `$40` Spark Mandrill, `$80` Launch Octopus |
| `$1F9A` | `max_hp` | $10 + 2 per heart, at most $20 |
| `$1F86` | `weapon_flags` | weapon w (1-8 = the level of the boss who gives it) is the word `$1F85+2w`: low byte a fraction of a unit; high byte bits 0-5 ammo (max $1C = 28), bit 6 owned (boss beaten), bit 7 redraw the HUD bar (cleared when it's drawn). `$1F97/$1F98` is a 9th bar, drawn under ESCAPE.U on the pause screen, never selectable |
| `$1F7E` | `hadouken` | bit 7 owned; low bits count spawns of Armored Armadillo's capsule, capped at 5 |
| `$1F7C` | `fortress_open` | bit 6 = all 8 main bosses beaten |

The item's sub-id (event data) is its bit: heart tanks are `$1628`-list object `$0B` (`$81:E992`), sub tanks object
5 (`$81:E4BB`), life energy object 2 (`$82:E342`). The password (`password_decode` (`$80:F1E0`), not run) packs
`upgrades`, `hearts`, the beaten bosses, the Hadouken and `intro_cleared` (`$1F9B`); it sets `max_hp` from the hearts.

### What each armor part does

| bit | part | effect |
|---|---|---|
| `$01` | helmet | jumping into a `$3C` block breaks it (`helmet_break_block` (`$81:9EA1`): tile + 1, sound $23) and X keeps rising; falling rocks (enemy $18, Sting Chameleon's cave) do no damage; X's sprite set `gfx` = $18 |
| `$02` | arm | third buster charge level (projectile 2 + X-shot $1D); special weapons can charge at all (`$81:97DA`): charged id = weapon + 15 |
| `$04` | body | damage ceil(d/2) (1→1, 2→1, 3→2, 5→3, 8→4; contact 6→3, 4→2); knockback vy halved |
| `$08` | legs | dash on the dash button (step $14) or a double tap of forward, second press within 12 frames (`double_tap_dash` (`$81:9731`)); wall kicks break `$3C` walls (`legs_break_wall` (`$81:98FC`)) |

The arm, body and legs are drawn by three $20-byte sprite objects after X's slot: `x_arm_part` (`$0C38`),
`x_body_part` (`$0C58`), `x_legs_part` (`$0C78`), made by X's init (`$81:9D88`) from `upgrades`.

### Dr. Light's capsules (enemy `$4D`, `$87:CA7B`)

- Which part: `$86:D362[level]` → mask `$86:D3D5[index]` (01 02 04 08); the capsule deletes itself if X has it.
  Position `$86:D33E[level]`; in Sting Chameleon's and Storm Eagle's stages it rises 96 px out of the floor first.
- X touches it → step $1E, camera lock `$86:D3A1[level]`; Dr. Light (`$5C`) talks (text `$86:D4E3[level]`: Chameleon
  $0D, Armadillo $19, Mammoth $0E, Eagle $0C, Penguin $0B; the box needs button presses); X jumps into the capsule.
- Scene timer `$33`: 1, 20, 255 (the light `$4E` spawned at 20), 128 (the part's bit set by the light's animation
  event: `TSB upgrades`, then the part's handler: helmet `gfx` = $18, arm/body/legs INC their sprite object), 30
  (a second light that grants nothing), 30, then X's pose (step $38) for 60, then the demo: a pad script from
  `$86:D36B` is played into the pad (Eagle: Left, jump; Mammoth: Right, a charged shot; Penguin: a double-tap dash;
  Armadillo: the Hadouken motion; Chameleon: nothing), then control returns.
- Sting Chameleon's capsule is not an event: event type 2 id $1D starts `$87:FB40` ($1D08 list); at X x $0630 the
  camera locks, six rocks (id $11) fall 60 frames apart, enemy 9 appears; 96 frames after it dies the capsule rises;
  after the grant, 180 frames, then six wall blocks at x $0610 break 20 frames apart.

### Zero's buster

Zero (`$66`, Sigma stage 1) after Vile: text $1C if X has the arm; otherwise text $1D and `TSB upgrades #$02`
(`$88:D7D5`) plus `x_arm_part` — exactly the arm capsule's gift. There is no separate flag; the charge code only
reads `upgrades` $02.

### Hadouken

- Armored Armadillo's capsule counts its spawns in `hadouken` (`$1F7E`) (dying and coming back counts, scrolling away
  doesn't); it stays only at the 5th spawn or later with `upgrades` & `hearts` = $FF, `fortress_open` bit 6 and HP
  exactly 32. Its light sets `hadouken` bit 7.
- Input (`hadouken_input` (`$81:A062`)): Down alone, Down+forward, forward alone, then shoot pressed or released; each
  within 20 frames (21 fails); exact pad matches. `hadouken_check` (`$81:A0EA`): HP exactly 32, bit 7, X standing,
  walking or landing (steps 0/2/4/$0A; not in the air).
- Step $42 (42 frames); projectile 4 at frame 17, X+25 px, 4 px a frame, sound $AF; 32 damage to every main boss
  (a one-hit kill; blocked by Armored Armadillo's guard).

### Weapons from bosses

- Beating a main boss: `grant_boss_weapon` (`$84:A9EF`) sets $40 in that level's weapon word; at the next stage start
  `refill_weapons` (`$80:9EF9`) fills every owned weapon to $DC00. The stage end after the 8th boss sets `fortress_open`
  bit 6 (`$80:9C13`, `bosses_beaten_mask` (`$80:9FEB`) = $FF) and goes to Sigma stage 1.
- `switch_weapon` (`$81:99D3`): R/L step through owned weapons only, wrapping buster ↔ Shotgun Ice; L+R = buster; not
  while a shot is out. Shots on screen (`$86:BAB8`): buster 3, Torpedo 2, Sting 1, Shield 1, Fire Wave 6, Tornado 1,
  Spark 3, Cutter 3, Ice 1.
- Ammo per shot (`weapon_ammo_cost` (`$81:94AF`), units of $100 of 28): Torpedo 0.5 (charged 3), Sting 0.5 (4), Shield
  1 (2), Fire Wave 1/16 a flame = 1 per second held (3), Tornado, Spark, Cutter 1 (2), Ice 1 (1.5); no ammo → no shot.
- Weapon energy (`$1628` object 1): big 8 units, small 2, 1 unit every 4 frames into the current weapon, else the first
  owned non-full one. Game quirk: `give_weapon_energy` (`$81:E11A`) never clears its overflow flag, so after an overflow
  every later non-full weapon gets the remainder (8 units picked up gave 17 in the test).

### Sub tanks, heart tanks, life energy

- Sub tank: first slot without bit 7 → $80, its bit into `upgrades`; 80 frames frozen (sound $29). All 4 slots owned:
  deleted without its bit.
- Life energy: large +8 HP / small +2, 1 every 4 frames (objects frozen); the rest is lost. At full HP: +2 / +1 units
  into the first owned non-full sub tank only (no spill; sound $2B when it fills).
- Using a tank (pause menu: Start, Down, Y; not at full HP): every 4 frames HP +1 and the tank −1, always down to $80
  even after HP is full; the emptied tank moves behind the non-empty ones (`subtank_compact` (`$80:CDA1`)). Game bug:
  the "+2 HP a tick for a full tank" test reads slot X_hp − 10 instead of the chosen one (`subtank_menu_tick` (`$80:C723`)).
- Heart tank: its bit into `hearts` first; if `max_hp` is already $20 nothing else. Otherwise 80 frames frozen, then 8
  frames of palette flash with `max_hp` +1 and HP +1 every 4 frames, twice (HP isn't refilled; at $1F only one step).

Copy protection touches X: init (`$81:81A3`) clears `upgrades` if a random byte of the ROM's two halves differs, an SRAM check
(`$70:0800`, `$70:0804`) nudges `$1F9E`, and the jump/speed code checks its own bytes (`$81:8545`, `$81:853D`): a
mismatch sets `$1F9E` bit 7, which the jump step then uses as X's gravity.
