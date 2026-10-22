# How enemy behavior works in Mega Man X1

Everything here comes from reading the code with `trace.py` / `enemies.py`.
Items marked **(?)** are inferred but haven't been seen running in an emulator.

## The object system

- Every enemy, projectile and item is an **object**: a block of RAM used as the CPU's
  "direct page" while that object's code runs, so its fields are addressed `$00`–`$3F`.
- Once per frame the engine runs each live object. At `$80:D530` it saves the old
  position, then:
  ```
  LDA $0A      ; object id  (= the event id placed in the level)
  ASL : TAX
  JMP ($F8DD,X)  ; per-id table -> stub "JSL routine; RTS"
  ```
  So **the event id selects the code**. The table has 107 entries; see `out/enemy_catalogue.txt`.
- While object code runs, the data bank is **$86**. That's where its lookup tables
  (ranges, speeds, sine tables) live.

### Object fields found so far

| field | meaning |
|---|---|
| `$00` | active |
| `$01` | **state** (0, 2, 4, …: an index into a jump table) |
| `$02` | **substate** |
| `$03` | sub-substate / flag |
| `$05`, `$08` | X, Y position (16-bit) |
| `$0A` | object id |
| `$0B` | sub-id from the event. Picks the variant: bit 0, low nibble, etc. |
| `$0F` | animation status (bit 7 = animation finished) **(?)** |
| `$11` | sprite attributes (bit 6 = facing / h-flip) |
| `$1A`, `$1C` | X and Y velocity (16-bit, signed) |
| `$20` | `box_ptr`: pointer to the collision box (verified for X: the wall check reads his box at `$86:A552` through it; bosses set it with `$31`) |
| `$27` | **HP** (bit 7 used as a flag; `HP & 0x7F` = 0 means dead) |
| `$28` | **damage class**: which row of the damage table ($86:EF37) applies when X's shots hit it. Class 5 = all zeros (invulnerable) |
| `$2B` | `touch`: terrain contact bits; bit 2 = standing on a floor (verified), bits 0/1 = walls |
| `$33`–`$3F` | free scratch space for each enemy: timers, home position, counters |

### Engine helpers enemies call

| routine | what it does |
|---|---|
| `x_in_range` (`$82:FC48`) | **proximity check**: is X within `range[X]` horizontally (and vertically if Y≠0)? Ranges are in table `$86:E47B`. Returns 0 if in range |
| `angle_to_x` (`$84:A081`) | **angle from enemy to X**, used to aim |
| `$84:9086` | `random` (seed word `$0BA6`; verified by seeding tests) |
| `$84:8F07` | `anim_start`: start animation N |
| `$84:8EEA` | `anim_tick`: advance the current animation |
| `$82:820A` | `move`: apply velocity to position **(?)** |
| `$84:90A0` | `probe_terrain`: collision value at an offset (verified: lookup in `PLAYER.md`) |
| `$84:9B43` | `hit_check`: nonzero when a shot hit the object this frame (verified) |
| `alloc_effect_1928` (`$82:82D3`) | allocate a new object (spawn a projectile / child) **(?)** |

## Worked example: Batton Bone (id 0x2D, the bats in Chill Penguin's cave)

Code is at `$87:A07F`; run `python3 enemies.py 2D` for the full listing.

```
state 0  INIT    HP=2, remember home x/y, pick animation by sub-id,
                 set re-aim interval = 20 + (frame counter & 3) frames
   v
state 2  HANG    each frame: is X within 128 px horizontally?  (`x_in_range` ($82:FC48), range 0x80)
   v   yes
state 4  SWOOP   sub 0: play the "drop" animation until it finishes
                 sub 2: chase for up to 600 frames ($33 = 0x258):
                        every 20–23 frames ($37, reloaded from $38):
                            angle = direction to X  (`angle_to_x` ($84:A081))
                            velocity = sine/cosine table [angle]  ($86:EE37)
                        left its leash box around home (0x128 x 0xC0)? -> state 6
                        variant (sub-id bit 0): every 8 frames spawn object 0x10
   v   timer ran out / leash / got hit
state 6  RETURN  sub 0: fly straight up (vy = 0x280) until all 4 ceiling probes hit
                 sub 2: play the "land" animation
                 sub 4: wait 60 frames  -> back to state 2 (HANG)

every frame (after the state handler):
  got hit?  HP -> 0: death explosion; else -> state 6 (flee to the ceiling)
```

## How this compares with your mental model

| your idea | what the code does |
|---|---|
| "an attack happens at an interval" | **Yes, but as countdown timers in the object's own fields.** Batton Bone re-aims every 20–23 frames and has a 600-frame chase limit; others count down to their next shot. Intervals are usually a constant `LDA #n / STA $3x`, sometimes plus a little randomness, so **they're easy to patch**. |
| "behavior is in a stack" | **Not a stack: a state machine**, two or three levels deep (`$01` state → `$02` substate → `$03`). Each state handler chooses the next state by writing `$01`/`$02` directly. There's no queue of pending behaviors; the only "stack" is the CPU's call stack. |
| "player behavior affects states" | **Yes, through specific checks:** distance to X (wake-up/attack ranges), angle to X (aiming), getting hit (flee/stagger), and a few reads of X's own state (e.g. `X_hp` (`$0BCF`), possibly X's charge/weapon **(?)**). Each check is a branch you can retune or redirect. |

## What's easy to change now

- **HP:** 1 byte, location listed per enemy in `out/enemy_catalogue.txt` (e.g. Batton Bone `0x3A13D`).
- **Timers and intervals:** the `LDA #n` before `STA $33`/`$37`/`$38`/`$3A`.
- **Speeds:** the velocity constants (`LDA #$0280 / STA $1C`) and the shared speed tables in bank $86. Note that shared tables affect every enemy that uses them.
- **Detection ranges:** the index passed in X to `x_in_range` (`$82:FC48`), or the range table at `$86:E47B` (shared).
- **Behavior variants:** many enemies check sub-id bits, so a different sub-id in the level events can switch behavior without touching code.

## Harder (needs new code in the expanded ROM's free space)

- Adding new states: for example, give Batton Bone a projectile attack while hanging.
- Changing how an enemy reacts to X, e.g. dodging when X charges a shot.
- Mixing behaviors from two enemies.

## Boss: Chill Penguin (id 0x02, `$81:B516`)

Full listing: `out/chill_penguin.asm` (`python3 trace.py 81B516`).

### Top-level states (`$01`)
| state | handler | what happens |
|---|---|---|
| 0 | `$B523` | wait ~60 frames after the room loads, start the boss music |
| 2 | `$B581` | **intro**: drop from the ceiling, land, spawn the ceiling hook (object 0x12), fill the HP bar to 32, one point every 2 frames |
| 4 | `$B629` | **fight**: run the current attack (`$02`), then the shared hit-handling code |
| 6 | `$BB57` | **death**: explosion, then hand off to the stage-clear sequence |

### Attacks (`$02` inside state 4; each has its own steps in `$03`)
| `$02` | attack | sequence |
|---|---|---|
| 0 | **Ice Shot** | turn to face X, fire 4 ice projectiles (object 0x06), one per animation keyframe, then idle 120 frames |
| 2 | **Blizzard** | jump to the middle of the room, grab the ceiling hook, signal it (sets byte `$1B` of the hook object to 1, which starts the wind), hang 30 frames, drop, land, idle 30 frames |
| 4 | **Belly Slide** | face X, slide at speed 0x600, bounce off walls (reversing direction), slow down to a stop, then pick the next attack immediately (see quirks) |
| 6 | **Jump at X** | face X, horizontal speed = (X.x − boss.x) × 4, vertical speed 0x87E, land, idle 30 frames |
| 8 | **Ice Breath** | if an ice statue already exists, **do Ice Shot instead**. Otherwise breathe for 60 frames (breath particles = object 0x1A sub 0, sound 0x72), then make two statues (object 0x1A sub 1) at 0x30 and 0x50 px in front, wait 60 + 30 frames |
| A | **Flinch** (on hit) | hop backwards (x 0x100, y 0x221); a small hop of 20 frames, or a big one of 60 frames when hit by his weakness; then choose an attack as if he had just done Ice Shot |

### How the next attack is chosen (`choose_next_attack` (`$81:C019`))
`next = table[$86:C45B + current*8 + random(0..15)]`, i.e. one 16-entry row per attack.
Odds out of 16:

| after ↓ / next → | Ice Shot | Blizzard | Slide | Jump | Breath |
|---|---|---|---|---|---|
| Ice Shot | 1 | 2 | **7** | 2 | 4 |
| Blizzard | 2 | 1 | 2 | **7** | 4 |
| Slide | 4 | 2 | 1 | 2 | **7** |
| Jump | **7** | 4 | 2 | 1 | 2 |
| Breath | 4 | **7** | 2 | 2 | 1 |

Each row is the previous one rotated, so he rarely repeats an attack and *tends* to cycle
Ice Shot → Slide → Breath → Blizzard → Jump → Ice Shot. Edit these 80 bytes (PC `0x3445B`) to change his pattern.

### How X affects him
- **Aiming**: Ice Shot, Slide, Jump and Breath all turn to face X first (`face_x`, `$84:ACA5`, verified). Jump aims its arc at X's X position.
- **Getting hit**: 70 frames of invulnerability (flashing). He flinches only when flag `$38` is set, Ice Shot and Jump set it as they start. Slide and Breath clear it as they start and set it again when they finish; Blizzard leaves it as it was. He always flinches when hit by his weakness. So mid-slide and mid-breath, normal shots hurt him but don't interrupt him.
- **Weakness**: `last_hit_projectile` (`$1F1D`) is the id of the projectile that just hit (set by the damage routine `$84:9E15`). 0x0A (Fire Wave) or 0x13 (charged Fire Wave) forces the big flinch and a different hit sound.
- **Ice statues** block Ice Breath until they're destroyed, so breaking statues changes which attacks he can use.
- He doesn't react to X's position before choosing; the choice is purely random from the table above.

### Values worth editing
| value | SNES | PC | stock |
|---|---|---|---|
| max HP (bar fill target) | `$81B605` | `0x0B605` | 0x20 (32) |
| ice shots per volley | `$81B715` | `0x0B715` | 4 |
| idle after ice shots | `$81B782` | `0x0B782` | 0x78 (120 f) |
| slide speed → / ← | `$81B8BA` / `$81B8BF` | `0x0B8BA` / `0x0B8BF` | 0x0600 / 0xFA00 |
| jump-at-X vertical speed | `$81B96D` | `0x0B96D` | 0x087E |
| blizzard jump vertical speed | `$81B7B8` | `0x0B7B8` | 0x07DE |
| blizzard hang time | `$81B842` | `0x0B842` | 0x1E (30 f) |
| ice breath duration | `$81BA61` | `0x0BA61` | 0x3C (60 f) |
| statue distances | `$81BA77` / `$81BA82` | `0x0BA77` / `0x0BA82` | 0x30 / 0x50 |
| invulnerability after hit | `$81B66D` | `0x0B66D` | 0x46 (70 f) |
| weakness weapon ids | `$81B687` / `$81B68B` | `0x0B687` / `0x0B68B` | 0x0A / 0x13 |
| flinch knockback x / y | `$81BAF1` / `$81BAFB` | `0x0BAF1` / `0x0BAFB` | 0x0100 / 0x0221 |
| attack selection table | `$86C45B` | `0x3445B` | 5 rows × 16 bytes |

### Note on spawned objects
The ice shot (0x06), hook (0x12) and breath/statue (0x1A) ids are **not** enemy ids. They're
created through other allocators (`alloc_enemy_shot` (`$82:8358`), `alloc_misc_1628` (`$82:82B9`)) into a separate object list
(`$1428–$1628`) that has its own dispatch table (not yet located). Enemy id 0x06, for example, is an
unrelated enemy placed in Sting Chameleon's stage.

### Quirks and open questions
- **Slide has no recovery pause.** The end-of-slide timer uses `BEQ` where the other attacks use `BNE`, so he picks the next attack on the very next frame instead of waiting 30 frames. It could be a bug or intentional.
- `$28` (damage class) is 9 normally, 5 while flashing (class 5 = takes no damage) and 0 while sliding (class 0 = every entry is a special handler, i.e. shots are deflected (?)).
- The flinch path reuses the "after Ice Shot" row because `$02` is cleared before choosing.


## Weapons, projectiles and damage

- X's selected weapon is `$0BDB` (= weapon × 2). Ammo/ownership is a word at `$1F85 + weapon×2`.
  Beating the boss of stage N gives weapon N (`$80:C947`, `$84:AAE6` read `$1F86 + 2×level`).
- Firing (`$81:94AF`): X-Buster shots come from a charge-level table at `$86:BA76`. For special weapons,
  **projectile id = weapon + 6** (uncharged) or **weapon + 15** (fully charged).
- Hadouken is projectile 0x04, created by `$81:A114` only with the buster selected, **full health**,
  the flag in `$1F7E` set and the input sequence done.
- Damage (`$84:9E15`): `damage = table[row = target's $28][column = projectile id]`. Rows are at
  `$86:EF37 + word[$86:EF37 + 2×row]`, 30 bytes each. Bit 7 set → special handler.

| weapon # | weapon | from | uncharged id | charged id |
|---|---|---|---|---|
| 0 | X-Buster | — | 00 / 01 / 02 (+1D) | — |
| 1 | Homing Torpedo | Launch Octopus | 07 | 10 |
| 2 | Chameleon Sting | Sting Chameleon | 08 | 11 |
| 3 | Rolling Shield | Armored Armadillo | 09 | 12 |
| 4 | Fire Wave | Flame Mammoth | 0A | 13 |
| 5 | Storm Tornado | Storm Eagle | 0B | 14 |
| 6 | Electric Spark | Spark Mandrill | 0C | 15 |
| 7 | Boomerang Cutter | Boomer Kuwanger | 0D | 16 |
| 8 | Shotgun Ice | Chill Penguin | 0E | 17 |

Projectile 0x04 is Hadouken, and 0x1D is the second shot of a full charge. Ids 01, 03, 05, 06 and 19–1C
aren't confirmed yet.

## All bosses (summary)

Every editable value below is defined in `defs.py` and checked against the stock ROM
(the opcode before it and the stock value). Full listings are in `out/bosses/*.asm`.

| boss | object | code | damage class | weakness (damage table) | weapon with a special reaction | how attacks are picked |
|---|---|---|---|---|---|---|
| Launch Octopus (verified) | enemy 07 | `$81:C433` | 0C (0 while spinning) | Rolling Shield | Boomerang Cutter ×3 cuts tentacles (then torpedo attacks only); other hits: one-animation flinch, then resumes | Torpedo hop first; X distance band (+ tentacles cut), 32 entries/row at `$86:C625`; **row order close, far, mid** |
| Sting Chameleon (verified) | enemy 0A | `$88:853E` | 06 | Boomerang Cutter | Boomerang Cutter → knockback; can't be hit while cloaked | inline random rolls after each attack (leap first); while cloaked he hops up to 3 times and lashes if X is in tongue reach; high leap bug: vy $740, gravity unchanged |
| Armored Armadillo (verified) | enemy 14 | `$83:B144` | 0B (0 while guarding or curled with armour) | Electric Spark | Electric Spark breaks armour (then no guard, hurtable curled); charged buster into guard → 8-shot counter | Rolling first; X distance band, 16/row at `$86:C980`; never 3 in a row (the other attack is forced, so a one-attack row doesn't freeze) |
| Flame Mammoth (verified) | enemy 0C, trunk enemy 0E | `$87:91A7` | 08 | Storm Tornado | Boomerang Cutter ×3 knocks the trunk off | X high → stomp; else distance band (+ trunk cut), 16/row at `$86:C843`; max 3 repeats while the trunk is on (a one-attack row freezes the game) |
| Storm Eagle | enemy 52 (appears during the platform ride; type-2 trigger 20 (?)) | `$87:D85C` | 07 | Chameleon Sting | — | per-attack weights /32 at `$86:D41B` (Gust, Dive, Storm Tornado, Birds) |
| Spark Mandrill (verified) | enemy 31 | `$88:9BE1` | 0A | Shotgun Ice | Shotgun Ice freezes (other hits never interrupt him); charged buster staggers dash | random first attack; then per-attack weights /32 at `$86:CFDB` (Electric Spark, Ceiling drop, Dash punch, Jump at X), 6 rows: after each attack, after a stagger, after a freeze |
| Boomer Kuwanger (verified) | enemy 05 | `$87:8A7E` | 0D | Homing Torpedo | while teleporting, hittable only with Homing Torpedo selected (or on the frame he reappears); Homing Torpedo hits flinch longer (24 vs 16 frames) | after a dash: 16/row at `$86:C5A3` (row = dash ≥ 9 frames); after a teleport: 16/row at `$86:C5C3` (row = X within 128 px); Dead Lift whenever X is within 32 px in front |
| Chill Penguin | enemy 02 | `$81:B516` | 09 | Fire Wave | Fire Wave → big flinch | previous attack, 16/row at `$86:C45B` |

Common to all eight: the HP bar fills to 32 in the intro (`CMP #$20`), there are 60 frames of
invulnerability after a hit (70 for Chill Penguin), and damage class 5 (no damage) applies while flashing.

Fortress bosses (details in `defs.py`):

- **Bosspider** (object 63, Sigma 1): rides a web drawn into the stage's collision (values $14/$15/$16 =
  turn right / go down / turn left), shows a random path, walks it, climbs back. Hurtable only for 24 frames
  at the bottom (damage class $0A; class 0 = deflect elsewhere (?)). Babies (enemy shot 0x2B) when X is level.
- **Rangda Bangda** (object 5D, Sigma 2): a controller: two eyes (5E), nose (5F), closing walls (60); the bar
  is the sum of the parts' HP. Parts report through `part1-3_status` ($1F3F-$1F41, bit 7 = destroyed).
- **D-Rex (?)** (object 62, Sigma 3): drawn on a background layer, a platform X can ride (`carry_x`); rams
  the walls (quake + stun) and crushes a pinned X for 6. Works with a part (61) through the same status bytes.
- **Sigma** (object 65, Sigma 4): the whole finale in one object: sends Velguarder (26 (?)), fights as Sigma
  (dash/slash, jump dash + wall kick, two shots, guard), then Wolf Sigma (hands 6B, head shots 0x31/0x32).

68 = Sigma 4 helper. Vile is object 69, never placed in a stage (spawned by a script). The Mavericks'
rematches reuse the same objects.

### Boomer Kuwanger compared with Chill Penguin

Both are built on the same skeleton; the differences are in the attacks.

| part | Chill Penguin (`$81:B516`) | Boomer Kuwanger (`$87:8A7E`) | Storm Eagle (`$87:D85C`, verified) |
|---|---|---|---|
| states | init / intro / fight / death | same | same |
| init | `boss_already_beaten` → despawn; `x_freeze_for_boss`; 60 frames; jingle $2E; `obj_start` | identical | same but no `x_freeze_for_boss`: X is held by the platform ride (X step `$46`) |
| entrance | falls with gravity until he lands, then spawns the ceiling hook | beam-in: 16 px steps right, down, right (no gravity) | appears at screen_left + 208, top of the screen, falls at a steady vy −256 until he lands |
| HP fill | `hud_boss = self`, +1 every 2 frames to 32 with `play_sound_centered`, bit 7 set to redraw | identical | identical |
| end of intro | boss music $1E, then `x_unfreeze` straight away | waits 30 frames, then `x_unfreeze`, then boss music | sets the arena borders, boss music $1E, waits 30 frames (plus ~7 while the music loads), then `x_unfreeze` |
| every fight frame | restore `palette_bits`; run the attack; damage class 9 (5 while invulnerable, 0 while sliding) | restore `palette_bits`; run the attack; damage class 13 (5 while invulnerable) | restore `palette_bits`; run the attack; `wing_sounds`; damage class 7 (5 while invulnerable) |
| getting hit | 70 frames invulnerable; flinches only if `can_flinch`, or always to his weakness | 60 frames invulnerable; **always** flinches and remembers the attack (`resume_attack`); can't be hit while teleporting unless X has Homing Torpedo selected | 60 frames invulnerable, sound $13; never flinches |
| weakness reaction | Fire Wave → big flinch + sound $4A | Homing Torpedo → 24-frame flinch instead of 16 | none (Chameleon Sting only does more damage) |
| hurting X | `hurt_x_on_contact` every frame | only while visible and not teleporting | `hurt_x_on_contact` every frame; Gust and tornado push X instead of hurting |
| HP 0 | checked only on a hit | checked every frame | checked only on a hit |
| at HP 0 | state 6, `boss_defeated = 1`, `X_hurt_lock` (`$0BD8`) = 1, death pose | identical | identical (death pose 10), plus `boss_signal` bit 0 |
| death | `boss_defeated_sequence`, then `obj_despawn` (fortress rematch: music $1B) | identical (music $1A); also keeps animating unless `freeze_enemies` | identical |
| choosing an attack | one table, row = the attack he just did (`choose_next_attack`) | two tables: after a dash (row = dash length), after a teleport (row = X distance); Dead Lift by range, not by table | one weight table, row = the attack he just did (`choose_next_attack`, `$87:DE1F`) |
| low HP | no change | below 17 HP a hit can start a 6–13 teleport streak | no change |

Logically they match: same intro hand-off, same HP/HUD protocol, same hit → invulnerability → flash loop, same
`x_dead` bookkeeping and the same death hand-off. Boomer adds the "only Homing Torpedo while teleporting" gate,
a range-triggered grab that bypasses the tables, and an HP-dependent mode; Chill Penguin instead gates flinching
per attack. The one ordering difference is the end of the intro (Boomer waits 30 frames before freeing X).

### Object lists and allocators
| allocator | RAM list | dispatch table | contents |
|---|---|---|---|
| `alloc_enemy` (`$82:8321`) | `$0E68–$1228` | `$80:F8DD` | enemies (event type 3), Storm Eagle, Octopus piranhas |
| `alloc_x_shot` (`$82:833E`) | `$1228–$1428` | `$80:F68F` | X's projectiles (30 ids) |
| `alloc_enemy_shot` (`$82:8358`) | `$1428–$1628` | `$80:F77D` (each entry a `JSL` stub; ids in `defs.ENEMY_SHOTS`) | enemy projectiles (ice shots, oil, fireballs…) |
| `alloc_misc_1628` (`$82:82B9`) | `$1628–` | ? | misc (Chill Penguin's hook) |
| `alloc_effect_1928` (`$82:82D3`) | `$1928–` | ? | effects |
Event type 2 (triggers) dispatch through `$80:F59A` (35 ids).

## Enemy sprites (`sprites.py`)
`$86A5E4 + (id−1)×2` gives the sprite assembly and graphics number for each enemy id. The graphics are
X1-compressed 4bpp tiles from the `$86F6F7` list. Each graphics number's palette comes from the stages'
object-graphics sets (`$86ACEE`). The assemblies at `$8D8000` list each frame's pieces as x, y, tile, info
(bit 5 = 16×16, bit 6/7 = h/v flip). `python3 sprites.py` draws all of them to `out/enemy_sprites.png`.
