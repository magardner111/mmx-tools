"""
Literal 65816 -> pseudo-C translation of a traced routine, for reading.

Each instruction becomes one C-like statement (or merges into a branch condition).
Control flow is kept as-is (labels + goto), so it matches the assembly line for
line. Names come from what we've decoded: object fields, RAM, engine helpers.
Anything marked (?) is a guess. This is pseudo-C: it explains, it doesn't compile.

usage: python3 lift.py <snes_addr_hex>
"""
import sys
from mmx1 import MMX1, RAM
from trace import trace

ROM = "../Mega Man X (USA) (Rev 1).sfc"

# direct page = the current object's slot
FIELDS = {
    0x00: "active", 0x01: "state", 0x02: "step", 0x03: "substep", 0x05: "x", 0x08: "y",
    0x0A: "id", 0x0B: "sub_id", 0x0C: "parent", 0x0F: "anim_status", 0x11: "attr",
    0x17: "keyframe", 0x1A: "vx", 0x1C: "vy", 0x1E: "gravity", 0x20: "box_ptr",   # collision box (verified for X: $86:A552)
    0x04: "x_sub", 0x07: "y_sub", 0x0E: "visible",   # visible: cleared by obj_draw when off screen (?)
    0x16: "gfx", 0x18: "tile_base",                  # set by obj_start from the graphics tables (?)
    0x1B: "vx_hi", 0x1D: "vy_hi",                    # sign bytes: vx_hi & 0x80 = moving left, vy_hi & 0x80 = falling
    0x1F: "friction", 0x22: "prev_x", 0x24: "prev_y",   # prev_x/y: last frame's position (platforms) (?)
    0x27: "hp", 0x28: "damage_class", 0x29: "probe_x", 0x2A: "probe_y", 0x2B: "touch",
}
# anim_status bit 7 = the current animation has finished; hp bit 7 = ask the HUD to redraw the boss bar

TAKES_A = {0x848F07, 0x8088A2, 0x8087A2, 0x84A338, 0x84A316}

HELPERS = {
    0x848F07: "anim_start",          # A = animation number
    0x848EEA: "anim_tick",
    0x849086: "random",
    0x82FC48: "x_in_range",          # X = range index, Y = also check vertical; 0 = in range
    0x84A081: "angle_to_x",
    0x84ACA5: "face_x",              # turn toward X (Mesen-verified on Chill Penguin)
    0x8491BE: "check_terrain",       # sets touch ($2B); bit 2 = standing on floor, bits 0/1 = walls (verified)
    0x82C715: "carry_x",             # move X by how far this object moved (x - prev_x, y - prev_y)
    0x82D7D7: "x_overlaps_self",     # (?) X alive and inside this object's box
    0x80E018: "bg_boss_load",        # (?) switch BG to the boss layer mode, start its tile load ($1F27)
    0x80E008: "bg_boss_ready",       # (?)
    0x849C0E: "obj_overlaps",        # carry set if the object at X (slot) overlaps this one's box_ptr box; X = $0BA8 tests X (grabs, tongue, oil) (seen in Mesen: Flame Mammoth's oil vs X and vs fireballs; probe.py on Mammoth with X = $0BA8: carry clear 127 px apart, set when touching)
    0x8490A0: "probe_terrain",       # collision value at (x + probe_x, y + probe_y); >= $34 is solid (verified)
    0x849B43: "hit_check",           # nonzero when a shot hit this object this frame (verified)
    0x849B03: "hurt_x_on_contact",   # damages X on touch (via $84:9D5C, not x_take_damage) (verified)
    0x8281E8: "move_with_gravity",   # vy -= gravity, then move (verified: only while airborne)
    0x82820A: "move",                # (?)
    0x828321: "alloc_enemy",
    0x82833E: "alloc_x_shot",
    0x828358: "alloc_enemy_shot",
    0x8282B9: "alloc_misc_1628",
    0x8282D3: "alloc_effect_1928",
    0x8088A2: "play_sound",          # A = sound id, panned by the object's distance from X
    0x8088CD: "play_sound_centered", # A = sound id, no panning
    0x80887F: "queue_sound",         # A = sound/command id, Y = its parameter byte (sound queue $0B72)
    0x8087A2: "play_music",          # A = track ($2E boss jingle, $1E boss fight) (verified)
    0x8280B4: "obj_draw",            # common tail: draw, unless more than 32 px outside the screen
    0x828011: "load_palette",        # Y = palette set ($86:8133 list), into its own slots
    0x828000: "load_palette_to",     # same, X = destination slot
    0x828174: "move_brake_right",    # vy -= gravity, vx -= field $1F, then move
    0x828195: "move_brake_left",     # vy -= gravity, vx += field $1F, then move
    0x82806E: "obj_far_offscreen",   # carry set when more than 64 px outside the screen
    0x82823E: "move_x",              # x += vx (x is 16.8 at $04-$06, vx 8.8)
    0x82825D: "move_y",              # y -= vy (y is 16.8 at $07-$09; positive vy = up)
    0x8283A3: "obj_despawn_shot",    # like obj_despawn and also clears $2C-$2D; enemy shots use it (seen with probe.py: on an oil puddle)
    0x828398: "obj_despawn",         # (verified: a defeated boss disappears through it)
    0x84A338: "screen_shake",        # A = length -> $1E7A, strengths $1E83/$1E7F/$1E81/$1E85, $1E78 = 2 (seen with probe.py; Flame Mammoth's landing uses 75)
    0x84AADD: "boss_already_beaten",  # 1 if this stage's boss is beaten (weapon_flags bit 6; stages < 9 only)
    0x849FEB: "x_freeze_for_boss",   # X step = $1E: X is held still during a boss intro
    0x84A003: "x_unfreeze",          # X step = 0 (ends x_freeze_for_boss)
    0x848000: "load_stage_tiles",    # (seen in Mesen: Flame Mammoth's belt flip and death; probe.py: A = 3 writes his belt's tile entries at $7E:F062-F097 x-flipped, 2 and 4 unflipped) A = entry of this stage's animated-tile list ($84:B8AC), e.g. conveyor
    0x80B071: "load_object_set",     # A = this stage's enemy graphics set (see gfxsets.py)
    0x83F74A: "show_dialogue",       # (?) text box (effect 0x2A); dialogue_active bit 7 while it's up
    0x84A046: "x_step_3A",           # X step $3A (Sigma 4 cutscenes) (?)
    0x84A019: "x_step_34",           # X step $34 (Sigma 4 ending) (?)
    0x849F8A: "x_hold",              # X step $18, previous step saved in $0C12 (boss defeated, cutscenes)
    0x849FB2: "x_resume",            # X step = the one saved by x_hold
    0x84A00D: "x_stun",              # X step $36 (step_stunned), X_stun_timer = A; X is stunned A + 32 frames (verified)
    0x84A316: "screen_quake",        # A = length -> $1E79, strengths $1E82/$1E7E/$1E80/$1E84, $1E78 = 1 (seen with probe.py); $84A31F takes X/Y strength too
    0x84A09C: "angle_between",       # (?) from ($0000,$0002) to ($0004,$0006)
    0x849F19: "x_grabbed",           # X step = $16: held by an enemy (Kuwanger's Dead Lift, Octopus's drain) (verified)
    0x849F7E: "x_drop",              # X step = 8: let go of a held X
    0x81812E: "x_update",
    0x8499AF: "x_wall_check",        # (?) carry set = wall in the facing direction (stops a walk)
    0x80E54D: "x_read_buttons",      # pad_held -> X_dpad / X buttons via the button setup (verified)            # X's per-frame update (see PLAYER.md)
    0x849D07: "x_contact_damage",    # hurt_x_on_contact's hit path: hurt_lock += 1, step $0E, HP -= damage
    0x849F2F: "x_take_damage",       # X step = $0E (hurt); X_hp -= X_pending_damage, ceil(d/2) with the
                                     # body (upgrades $04) (verified); at 0 HP X step = $0C (dying)
    # upgrades (verify_upgrades.py, see PLAYER.md "Upgrades")
    0x84A9EF: "grant_boss_weapon",   # boss_defeated_sequence step $16: level < 9 -> weapon_flags of that level |= $40 (verified)
    0x809FEB: "bosses_beaten_mask",  # A = bit per beaten main boss from the weapon words ($FF = all 8) (verified)
    0x809EF9: "refill_weapons",      # stage start: every owned weapon word (and the 9th, $1F97) = $DC00 (verified)
    0x809EEB: "clear_weapons",       # all weapon words = 0 (?)
    0x8199D3: "switch_weapon",       # L/R: next owned weapon (wraps buster <-> $10), L+R = buster, not while a shot is out;
                                     # sets the shots-on-screen limit X+$67 from $86:BAB8 (verified)
    0x8194AF: "weapon_ammo_cost",    # ammo per shot $86:BA92[w], full charge + $86:BAA4[w] and projectile + 9 (verified)
    0x81E11A: "give_weapon_energy",  # weapon energy pickup: current weapon, else first owned non-full; never clears its
                                     # overflow flag $0002, so the remainder reaches every later non-full weapon (verified)
    0x81A062: "hadouken_input",      # Down, Down+forward, forward (X_hadouken_stage 2/4/6, 20-frame X_hadouken_timer), then
                                     # shoot pressed or released (verified)
    0x81A0EA: "hadouken_check",      # HP exactly 32, hadouken bit 7, X step 0/2/4/$0A -> step $42 (verified)
    0x81A114: "hadouken_fire",       # X-shot 4 at X+25 px, 4 px a frame, sound $AF (verified)
    0x819EA1: "helmet_break_block",  # jump/wall-jump ceiling hit: with the helmet a $3C tile is broken (tile + 1, sound $23) (verified)
    0x8198FC: "legs_break_wall",     # wall kick with the legs breaks a $3C wall tile (verified)
    0x819731: "double_tap_dash",     # with the legs: second forward press within 12 frames dashes (step $14) (verified)
    0x80F1E0: "password_decode",     # 4 bytes -> upgrades, hearts (max_hp = $10 + 2 each), bosses, hadouken, intro_cleared (?)
    0x80C6C6: "subtank_menu_start",  # pause menu, Y on a sub tank (not at full HP) (verified)
    0x80C723: "subtank_menu_tick",   # every 4 frames: HP +1 (+2 if slot X_hp-10 is full: game bug), tank -1 down to $80 (verified)
    0x80CDA1: "subtank_compact",     # an emptied tank moves behind the non-empty owned ones (verified)
    0x82E4E2: "life_energy_give",    # +8 HP large / +2 small, 1 every 4 frames; at full HP +2/+1 units into the first
                                     # owned non-full sub tank, no spill (verified)
    0x84A677: "boss_defeated_sequence",  # called every frame of a boss's death state (verified); freezes
                                         # objects, palette flash to white, explosions, freezes X
                                         # for the stage clear; negative once finished
    0x84A4B5: "explode",             # one explosion at self + sound $23 (normal enemy death)
    0x84A4D0: "random_explosion",    # every (frame & $0008)==0: explosion at self + $0000/$0002 + random
                                     # (& $0004 / & $0006), random sound $93-$96
    0x84A467: "spawn_explosion",     # explosion effect (effect object 2) at ($0000, $0002)
    0x82827D: "obj_start",           # state = 2, damage class 3, tile/palette base for this id (verified)
    0x80DA0E: "hud_boss_bar",        # draws the boss HP bar for hud_boss
    0x80D56F: "hud_update",          # (?)
}

RAM_NAMES = {v & 0xFFFF: k for k, v in RAM.items() if v & 0xFF0000 == 0x7E0000 and v & 0xFFFF < 0x2000}
RAM_NAMES.update({0x0BAD: "X_x", 0x0BB0: "X_y", 0x0BCF: "X_hp", 0x0BDB: "X_weapon",
                  0x0B9C: "frame_counter", 0x1F1D: "last_hit_projectile", 0x1F7A: "level",
                  0x1F1B: "hit_direction", 0x1F1E: "last_hit_object", 0x1F26: "music_enabled",
                  0x0BAA: "X_step",
                  0x0BCE: "X_pending_damage", 0x0BD3: "X_touch",
                  0x0BB6: "X_visible",
                  0x00A7: "pad_held", 0x00AB: "pad_pressed",   # player 1, SNES bit order (verified)
                  0x0BDF: "X_dpad",         # X+$37: bit 0 R, 1 L, 2 D, 3 U (verified)
                  0x0B92: "collision_table_ptr",  # 24-bit; probe_terrain reads [ptr + map] (verified)
                  0x0BD8: "X_hurt_lock",    # X+$30: nonzero = can't be hurt (hit, grabbed, boss dying);
                                            # AR code 7E0BD808 holds it at 8 (see PLAYER.md)
                  0x0C13: "X_flash_timer",  # X+$6B: post-hit blinking; at 0 hurt_lock is cleared
                  0x0C32: "X_untouchable",  # X+$8A = boss_defeated | hurt_lock | X+$89, every frame
                  0x0C12: "X_saved_step",   # x_hold keeps the step to go back to here
                  0x1E50: "screen_top",
                  0x0BCA: "X_prev_x",       # X+$22: X's x before this frame's move (Flame Mammoth's oil averages with it) (verified)
                  0x0C2F: "X_status_flags", # X+$87: bit 7 set while stunned (step $36); Spark Mandrill's quake won't stun again while it's set (seen in Mesen: one stun per quake)
                  0x0C2D: "X_stun_timer",   # X+$85: set by x_stun, counted down in step $36 (verified)
                  0x1F99: "upgrades",       # armor $01 helmet, $02 arm, $04 body, $08 legs; sub tanks collected $10 Eagle,
                                            # $20 Armadillo, $40 Mandrill, $80 Mammoth (verified, PLAYER.md "Upgrades")
                  0x1F9C: "hearts",         # heart tanks, bit per stage: $01 Penguin $02 Armadillo $04 Eagle $08 Chameleon
                                            # $10 Mammoth $20 Kuwanger $40 Mandrill $80 Octopus (verified)
                  0x1F9A: "max_hp",         # $10 + 2 per heart, cap $20 (verified)
                  0x1F83: "sub_tanks",      # 4 slots $1F83-$1F86: bit 7 owned, energy = value - $80, full $8E (verified)
                  0x1F7E: "hadouken",       # bit 7 owned; low bits = Armadillo capsule spawns, capped at 5 (verified)
                  0x1F7C: "fortress_open",  # bit 6: all 8 main bosses beaten (set at $80:9C13) (verified); bit 7 (?)
                  0x1F80: "lives",          # (?) 2 at a new game, 1-up +1 (max 9), death -1
                  0x1F9B: "intro_cleared",  # (?) 0 = a new game starts in the intro stage; password byte 3 bit 4
                  0x0C27: "X_hadouken_stage",  # X+$7F: motion stage 0/2/4/6 (verified)
                  0x0C28: "X_hadouken_timer",  # X+$80: 20 frames to the next input (verified)
                  0x0BBE: "X_gfx",          # X+$16: sprite set, $18 with the helmet (verified)
                  0x0C38: "x_arm_part", 0x0C58: "x_body_part", 0x0C78: "x_legs_part",  # X's armor sprite objects
                                            # ($20 bytes each; nonzero = drawn), made from upgrades by X's init (verified)
                  0x1F3F: "part1_status", 0x1F40: "part2_status", 0x1F41: "part3_status",  # fortress bosses' parts;
                  0x1F42: "boss_signal",    # bit 7 = destroyed; boss_signal: part -> boss handshakes (?)
                  0x1F23: "boss_cleared",   # set when a boss is finished (also by boss_already_beaten)
                  0x1F7B: "fortress_cleared",  # (?) 1 after Bosspider, 2 after Rangda Bangda
                  0x00CA: "color_math", 0x00CB: "fixed_color_r", 0x00CC: "fixed_color_g",
                  0x00CD: "fixed_color_b",  # (?) screen fades
                  0x1F2C: "dialogue_active",  # (?) bit 7 while a text box is open
                  0x1F27: "bg_load_pending",  # (?) cleared once bg_boss_load's graphics are in
                  0x1F15: "freeze_enemies",  # (?) one of the boss-defeated freeze counters ($1F13-$1F18)
                  0x1F0C: "boss_defeated",  # set at boss HP 0: enemies stop hurting X, X's own update reads it
                  0x1F0E: "hud_boss",       # object whose HP the boss bar shows (0 = no bar)
                  0x1F10: "hud_boss_bar_state",  # 0 set up, 2 redraw when hp bit 7 set, 4 remove, 6 hide, 8 idle
                  0x1F86: "weapon_flags",   # [stage*2]: high byte of weapon w's word $1F85+2w (w = the boss's level):
                                            # bits 0-5 ammo (max $1C), bit 6 owned = boss beaten, bit 7 redraw the HUD bar (verified)
                  0x1E4D: "screen_left"})   # bosses place themselves at screen_left + $10/$20/$E0
BRANCH = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ", "BRA", "BRL"}


def field(n):
    return f"self->{FIELDS[n]}" if n in FIELDS else f"self->f{n:02X}"


def operand(txt, m8, x8):
    """Assembly operand -> C lvalue/rvalue."""
    t = txt
    if t.endswith(",S"):                                         # stack relative
        return f"stack[0x{t[1:3]}]"
    if t.startswith("($") and t.endswith(",S),Y"):
        return f"(stack_ptr(0x{t[2:4]}))[Y]"
    if t.startswith("#$"):
        return f"0x{t[2:]}"
    if t.startswith("($") and t.endswith("),Y"):                 # ($dp),Y
        return f"(({field(int(t[2:4], 16))}))[Y]"
    if t.startswith("[$"):
        return f"far_ptr({field(int(t[2:4], 16))})" + ("[Y]" if t.endswith(",Y") else "[0]")
    idx = ""
    if t.endswith(",X") or t.endswith(",Y"):
        t, idx = t[:-2], t[-1]
    if t.startswith("$"):
        h = t[1:]
        v = int(h, 16)
        if len(h) == 2:                                          # direct page
            return f"self_dp[0x{v:02X} + {idx}]" if idx else field(v)
        if len(h) == 4:
            if idx and v < 0x40:                                 # other object's field via X
                name = FIELDS.get(v, f"f{v:02X}")
                return f"OBJ({idx})->{name}"
            if v < 0x2000:
                base = RAM_NAMES.get(v, f"ram[0x{v:04X}]")
                return f"{base}[{idx}]" if idx and not base.startswith("ram[") else \
                       (f"ram[0x{v:04X} + {idx}]" if idx else base)
            if v < 0x6000:
                return f"io[0x{v:04X}]" + (f"[{idx}]" if idx else "")
            return f"rom86[0x{v:04X}" + (f" + {idx}]" if idx else "]")   # data bank $86
        if len(h) == 6:
            bank = v >> 16
            area = "ram7e" if bank == 0x7E else "ram7f" if bank == 0x7F else "rom"
            off = v & 0xFFFF if area != "rom" else v
            return f"{area}[0x{off:04X}" + (f" + {idx}]" if idx else "]")
    if t == "A":
        return "A"
    return f"/* {txt} */"


def lift(rom, entry):
    seen, labels, calls, tables = trace(rom, entry)
    out = [f"// auto-translated from ${entry:06X} — literal pseudo-C, one statement per instruction",
           "// A, X, Y are the CPU registers; self = the object running this code (direct page)", ""]
    last = None          # what the next branch tests: ("val", expr, width) | ("cmp", lhs, rhs, width) | ("call", expr)
    carry_note = ""
    prev_end = None
    addrs = sorted(seen)
    for i, a in enumerate(addrs):
        raw, txt, info = seen[a]
        m8, x8 = info["m8"], info["x8"]
        parts = txt.split(None, 1)
        mn, arg = parts[0], (parts[1] if len(parts) > 1 else "")
        if prev_end is not None and a != prev_end:
            out.append("")
            last = None
        if a in labels:
            out.append(f"{labels[a]}:")
        prev_end = (a & 0xFF0000) | ((a + len(raw)) & 0xFFFF)
        wa = 8 if m8 else 16
        wx = 8 if x8 else 16
        reg_w = {"A": wa, "X": wx, "Y": wx}
        stmt = None
        tgt = info.get("target")
        lab = labels.get(tgt, f"L{tgt & 0xFFFF:04X}" if tgt else "")

        if mn in ("LDA", "LDX", "LDY"):
            r = mn[2]
            stmt = f"{r} = {operand(arg, m8, x8)};"
            last = ("val", r, reg_w[r])
        elif mn in ("STA", "STX", "STY", "STZ"):
            src = "0" if mn == "STZ" else mn[2]
            stmt = f"{operand(arg, m8, x8)} = {src};"
        elif mn in ("AND", "ORA", "EOR"):
            op = {"AND": "&", "ORA": "|", "EOR": "^"}[mn]
            stmt = f"A {op}= {operand(arg, m8, x8)};"
            last = ("val", "A", wa)
        elif mn == "ADC":
            prev = seen[addrs[i - 1]][1] if i else ""
            stmt = f"A += {operand(arg, m8, x8)};" if prev == "CLC" else f"A += {operand(arg, m8, x8)} + carry;"
            last = ("val", "A", wa)
        elif mn == "SBC":
            prev = seen[addrs[i - 1]][1] if i else ""
            stmt = f"A -= {operand(arg, m8, x8)};" if prev == "SEC" else f"A -= {operand(arg, m8, x8)} + !carry;"
            last = ("val", "A", wa)
        elif mn in ("CMP", "CPX", "CPY"):
            r = {"CMP": "A", "CPX": "X", "CPY": "Y"}[mn]
            stmt = None
            last = ("cmp", r, operand(arg, m8, x8), reg_w[r])
        elif mn in ("INC", "DEC"):
            tgt_ = "A" if arg in ("", "A") else operand(arg, m8, x8)
            stmt = f"{tgt_}{'++' if mn == 'INC' else '--'};"
            last = ("val", tgt_, wa)
        elif mn in ("INX", "INY", "DEX", "DEY"):
            r = mn[2]
            stmt = f"{r}{'++' if mn[:2] == 'IN' else '--'};"
            last = ("val", r, reg_w[r])
        elif mn in ("ASL", "LSR", "ROL", "ROR"):
            tgt_ = "A" if arg in ("", "A") else operand(arg, m8, x8)
            top = "0x80" if wa == 8 else "0x8000"
            stmt = {"ASL": f"carry = ({tgt_} & {top}) != 0; {tgt_} <<= 1;",
                    "LSR": f"carry = {tgt_} & 1; {tgt_} >>= 1;",
                    "ROL": f"{tgt_} = rol({tgt_}, &carry);",
                    "ROR": f"{tgt_} = ror({tgt_}, &carry);"}[mn]
            last = ("val", tgt_, wa)
        elif mn in ("TSB", "TRB"):
            o = operand(arg, m8, x8)
            stmt = f"{o} |= A;" if mn == "TSB" else f"{o} &= ~A;"
        elif mn == "BIT":
            if arg.startswith("#"):
                last = ("val", f"(A & {operand(arg, m8, x8)})", wa)
            else:
                last = ("bit", operand(arg, m8, x8), wa)
        elif mn in ("TAX", "TAY", "TXA", "TYA", "TXY", "TYX"):
            d, s_ = mn[2], mn[1]
            stmt = f"{d} = {s_};"
            last = ("val", d, reg_w[d])
        elif mn == "TDC":
            stmt = "A = (uint16_t)self;   // object's address"
        elif mn == "TCD":
            stmt = "self = (Obj *)A;"
        elif mn == "XBA":
            stmt = "A = swap_bytes(A);"
        elif mn in ("PHA", "PHX", "PHY", "PHP", "PHB", "PHD", "PHK"):
            stmt = f"push({ {'PHA': 'A', 'PHX': 'X', 'PHY': 'Y', 'PHP': 'flags', 'PHB': 'data_bank', 'PHD': 'self', 'PHK': 'code_bank'}[mn] });"
        elif mn in ("PLA", "PLX", "PLY", "PLP", "PLB", "PLD"):
            d = {"PLA": "A", "PLX": "X", "PLY": "Y", "PLP": "flags", "PLB": "data_bank", "PLD": "self"}[mn]
            stmt = f"{d} = pop();"
            if mn in ("PLA", "PLX", "PLY"):
                last = ("val", d, reg_w[d])
        elif mn == "CLC":
            stmt = None if i + 1 < len(addrs) and seen[addrs[i + 1]][1].startswith("ADC") else "carry = 0;"
        elif mn == "SEC":
            stmt = None if i + 1 < len(addrs) and seen[addrs[i + 1]][1].startswith("SBC") else "carry = 1;"
        elif mn == "REP":
            bits = int(arg[2:], 16)
            stmt = "// " + ", ".join(n for b, n in ((0x20, "A is 16-bit"), (0x10, "X/Y are 16-bit"), (0x01, "carry = 0")) if bits & b)
        elif mn == "SEP":
            bits = int(arg[2:], 16)
            stmt = "// " + ", ".join(n for b, n in ((0x20, "A is 8-bit"), (0x10, "X/Y are 8-bit"), (0x01, "carry = 1")) if bits & b)
        elif mn in ("JSR", "JSL"):
            if "table" in info:
                ents = tables.get(info["table"], [])
                cases = ", ".join(f"{k * 2:#04x}: {labels.get(e, hex(e))}" for k, e in enumerate(ents))
                stmt = f"switch_call(X, {{{cases}}});"
            else:
                name = HELPERS.get(tgt) or labels.get(tgt) or f"sub_{tgt:06X}"
                arg_ = "A" if tgt in TAKES_A else ""
                nxt = seen[addrs[i + 1]][1].split()[0] if i + 1 < len(addrs) else ""
                if nxt in BRANCH and nxt not in ("BRA", "BRL"):
                    stmt = f"res = {name}({arg_});"
                    last = ("val", "res", wa)
                else:
                    stmt = f"{name}({arg_});"
                    last = None
        elif mn in ("JMP", "JML"):
            if "table" in info:
                ents = tables.get(info["table"], [])
                cases = ", ".join(f"{k * 2:#04x}: {labels.get(e, hex(e))}" for k, e in enumerate(ents))
                stmt = f"switch_goto(X, {{{cases}}});"
            else:
                name = HELPERS.get(tgt)
                stmt = f"return {name}();" if name else f"goto {labels.get(tgt, f'sub_{tgt:06X}')};"
        elif mn in ("RTS", "RTL", "RTI"):
            stmt = "return;"
        elif mn == "NOP":
            stmt = None
        elif mn in BRANCH:
            if mn in ("BRA", "BRL"):
                stmt = f"goto {lab};"
            else:
                stmt = f"if ({condition(mn, last)}) goto {lab};"
        else:
            stmt = f"/* {txt} */"

        if stmt:
            out.append(f"    {stmt:<58}// {a:06X} {txt}")
        elif mn in ("CMP", "CPX", "CPY", "BIT", "CLC", "SEC", "NOP"):
            out.append(f"    {'':<58}// {a:06X} {txt}")
    out = fold(out)
    for tb, ents in tables.items():
        out.append(f"\n// jump table {tb:06X}: " + ", ".join(labels.get(e, hex(e)) for e in ents))
    return "\n".join(out)


def fold(lines):
    """A = 0x02; / x = A;  ->  x = A = 0x02;     A = 0x01; / f(A);  ->  f(A = 0x01);"""
    out = []
    for line in lines:
        code, _, cmt = line.partition("// ")
        prev = out[-1] if out else ""
        pcode, _, pcmt = prev.partition("// ")
        p, c = pcode.strip(), code.strip()
        if p.startswith("A = 0x") and p.endswith(";") and " " not in p[4:-1]:
            val = p[4:-1]
            if c.endswith(" = A;") and not c.startswith("A "):
                out[-1] = f"    {c[:-2] + 'A = ' + val + ';':<58}// {pcmt.strip()} / {cmt.strip()}"
                continue
            if c.endswith("(A);"):
                out[-1] = f"    {c[:-3] + 'A = ' + val + ');':<58}// {pcmt.strip()} / {cmt.strip()}"
                continue
        out.append(line)
    return out


def condition(mn, last):
    if last is None:
        return {"BEQ": "zero", "BNE": "!zero", "BMI": "negative", "BPL": "!negative",
                "BCC": "!carry", "BCS": "carry", "BVC": "!overflow", "BVS": "overflow"}[mn]
    kind = last[0]
    if kind == "cmp":
        _, r, v, w = last
        sign = f"(int{w}_t)({r} - {v})"
        return {"BEQ": f"{r} == {v}", "BNE": f"{r} != {v}", "BCC": f"{r} < {v}", "BCS": f"{r} >= {v}",
                "BMI": f"{sign} < 0", "BPL": f"{sign} >= 0",
                "BVC": "!overflow", "BVS": "overflow"}[mn]
    if kind == "bit":
        _, m, w = last
        top, nxt = ("0x80", "0x40") if w == 8 else ("0x8000", "0x4000")
        return {"BEQ": f"(A & {m}) == 0", "BNE": f"(A & {m}) != 0", "BMI": f"{m} & {top}",
                "BPL": f"!({m} & {top})", "BVS": f"{m} & {nxt}", "BVC": f"!({m} & {nxt})",
                "BCC": "!carry", "BCS": "carry"}[mn]
    _, e, w = last
    top = "0x80" if w == 8 else "0x8000"
    return {"BEQ": f"{e} == 0", "BNE": f"{e} != 0", "BMI": f"{e} & {top}", "BPL": f"!({e} & {top})",
            "BCC": "!carry", "BCS": "carry", "BVC": "!overflow", "BVS": "overflow"}[mn]


if __name__ == "__main__":
    g = MMX1(ROM)
    print(lift(g.rom, int(sys.argv[1], 16)))
