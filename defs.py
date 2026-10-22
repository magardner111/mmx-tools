"""
Named, editable values in the Mega Man X1 (USA Rev 1) ROM.

Each Param points at an operand inside game code (or a data table). `prev` is the
opcode byte that must sit right before a code operand: params.py refuses to write
if it doesn't match, so we never patch the wrong place in an unexpected ROM.

Speeds are 16-bit fixed point, 1/256 px per frame (0x0600 = 6 px/frame) (?).
Frames are 1/60 s.
"""
from types import SimpleNamespace
from dataclasses import dataclass, field


@dataclass
class Param:
    key: str
    label: str
    addr: int                 # SNES address of the value
    kind: str                 # u8 | u16 | s16
    stock: int
    unit: str = "raw"         # frames | speed | hp | px | id | count | raw
    desc: str = ""
    prev: int | None = None   # expected opcode byte before the operand
    mirror: int | None = None  # address of a negated copy (e.g. leftward speed)
    min: int = 0
    max: int | None = None
    noun: str = ""            # word shown after counts/ids, e.g. "shots"
    copies: tuple = ()        # other operands that must hold the same value: address, or (address, opcode)


# --- weapons -----------------------------------------------------------------------
# X's selected weapon is $0BDB (= weapon * 2); ammo/ownership is $1F85 + weapon*2.
# Beating the boss of stage N gives weapon N. Firing ($81:952E) creates projectile
#   id = weapon + 6        (uncharged)      id = weapon + 15   (fully charged)
WEAPONS = [  # index: (game name, boss that gives it)
    ("X-Buster", None),
    ("Homing Torpedo", "Launch Octopus"),
    ("Chameleon Sting", "Sting Chameleon"),
    ("Rolling Shield", "Armored Armadillo"),
    ("Fire Wave", "Flame Mammoth"),
    ("Storm Tornado", "Storm Eagle"),
    ("Electric Spark", "Spark Mandrill"),
    ("Boomerang Cutter", "Boomer Kuwanger"),
    ("Shotgun Ice", "Chill Penguin"),
]

# Projectile id (what the damage routine stores in $1F1D) -> name. "(?)" = not confirmed.
PROJECTILES = {
    0x00: "X-Buster",
    0x01: "X-Buster half charge",
    0x02: "X-Buster charge, arm upgrade",
    0x03: "X-Buster full charge",
    0x04: "Hadouken",
    0x05: "X-Buster variant (?)",
    0x06: "X-Buster variant (?)",
    **{w + 6: WEAPONS[w][0] for w in range(1, 9)},
    0x0F: "unused (weapon 9)",
    **{w + 15: f"{WEAPONS[w][0]} (charged)" for w in range(1, 9)},
    0x18: "unused (weapon 9 charged)",
    0x19: "unknown 19",
    0x1A: "unknown 1A",
    0x1B: "unknown 1B",
    0x1C: "unknown 1C",
    0x1D: "X-Buster full charge, 2nd shot",
}
NUM_PROJECTILES = 0x1E

# Damage table: object field $28 is its "damage class" (a row); the hitting projectile
# id is the column. Row pointers are words at $86:EF37 (offsets from $86:EF37), 30 bytes
# per row. A value with bit 7 set calls a special handler instead of subtracting HP.
DAMAGE_TABLE = 0x86EF37


@dataclass
class AttackTable:
    """
    How a boss picks its next attack. Two layouts exist in the ROM:
      entries: each row is `row_len` attack values; the game picks row[random 0..row_len-1]
      weights: each row is one weight per attack (index i -> attack value 2*i); the game rolls
               0-31 and walks the weights from the last attack down, so attack 0 gets the
               remainder (its own byte is unused but kept equal to it here)
    """
    addr: int
    attacks: dict             # attack value -> name
    rows: list                # row labels, in ROM order
    fmt: str = "entries"      # entries | weights
    row_len: int = 16         # bytes per row
    total: int = 16           # what a row must total
    title: str = "Attack pattern"
    desc: str = ""
    # rows (indices) with a repeat limit: the boss refuses a 4th repeat and re-picks, so these rows need two
    # different attacks (besides needs_other_than) or the game freezes
    single_attack_freezes: tuple = ()
    # attacks the boss sometimes refuses (re-picks): every row needs another attack besides these
    needs_other_than: tuple = ()


@dataclass
class Boss:
    key: str
    name: str
    object_id: int
    level: int
    routine: int
    summary: str
    weakness: str = ""
    params: list = field(default_factory=list)
    attack_tables: list = field(default_factory=list)
    attacks_doc: dict = field(default_factory=dict)   # attack name -> description
    damage_class: int | None = None                   # row in the damage table ($28)
    damage_shared_with: str = ""
    notes: list = field(default_factory=list)
    object_list: str = "enemy"                        # which dispatch table the id is in
    # names used by the C decompiler (decomp.py)
    fields: dict = field(default_factory=dict)        # direct-page offset -> field name
    state_names: list = field(default_factory=list)   # top-level states, default init/intro/fight/death
    attack_handlers: list = field(default_factory=list)  # entries of the fight state's table
    func_names: dict = field(default_factory=dict)    # SNES address -> function name


LDA_IMM, LDX_IMM, CMP_IMM, ADC_IMM, SBC_IMM = 0xA9, 0xA2, 0xC9, 0x69, 0xE9


# compact constructors -------------------------------------------------------------------
def max_hp(addr):
    return Param("max_hp", "Max HP", addr, "u8", 0x20, "hp",
                 "Health bar fills up to this during the intro (bar holds 32).", prev=CMP_IMM, min=1, max=0x7F)


def frames(key, label, addr, stock, desc="", prev=LDA_IMM, copies=()):
    return Param(key, label, addr, "u8", stock, "frames", desc, prev=prev, min=1, max=0xFF, copies=copies)


def frames16(key, label, addr, stock, desc="", prev=LDA_IMM):
    return Param(key, label, addr, "u16", stock, "frames", desc, prev=prev, min=1, max=0x7FFF)


def speed(key, label, addr, stock, desc="", mirror=None, prev=LDA_IMM):
    return Param(key, label, addr, "s16" if mirror else "u16", stock, "speed", desc, prev=prev,
                 mirror=mirror, min=0, max=0x7FFF)


def count(key, label, addr, stock, noun, desc="", prev=LDA_IMM, lo=1, hi=0x20, copies=()):
    return Param(key, label, addr, "u8", stock, "count", desc, prev=prev, min=lo, max=hi, noun=noun, copies=copies)


def proj(key, label, addr, stock, desc=""):
    return Param(key, label, addr, "u8", stock, "projectile", desc, prev=CMP_IMM, max=NUM_PROJECTILES - 1)


def invuln(addr, stock=0x3C):
    return frames("invuln_time", "Invulnerability after hit", addr, stock, "Flashing / can't be hurt again for this long.")


DIST = ["X close (< 80 px)", "X mid (80–127 px)", "X far (≥ 128 px)"]


# --- the eight Mavericks -----------------------------------------------------------------
CHILL_PENGUIN = Boss(
    key="chill_penguin", name="Chill Penguin", object_id=0x02, level=8, routine=0x81B516,
    weakness="Fire Wave",
    summary=("Picks attacks from a weighted table (one row per previous attack): he rarely repeats and "
             "tends to cycle Ice Shot → Slide → Breath → Blizzard → Jump. Turns to face X before most "
             "attacks. Normal hits only interrupt him at certain moments; Fire Wave always makes him flinch."),
    damage_class=9, damage_shared_with="object 2C (Armored Armadillo's stage)",
    params=[
        max_hp(0x81B605),
        count("ice_shots", "Ice shots per volley", 0x81B715, 4, "shots",
              "Fired one per animation keyframe; more than 4 may need a longer animation (?)."),
        frames("ice_shot_pause", "Pause after Ice Shot", 0x81B782, 0x78),
        speed("slide_speed", "Belly slide speed", 0x81B8BA, 0x0600, mirror=0x81B8BF),
        speed("jump_speed", "Jump-at-X launch speed", 0x81B96D, 0x087E),
        speed("blizzard_jump_speed", "Blizzard jump launch speed", 0x81B7B8, 0x07DE),
        frames("blizzard_hang", "Blizzard hang time", 0x81B842, 0x1E),
        frames("breath_time", "Ice breath duration", 0x81BA61, 0x3C),
        Param("statue1_dist", "Statue 1 distance", 0x81BA77, "u8", 0x30, "px", prev=LDA_IMM, max=0xFF),
        Param("statue2_dist", "Statue 2 distance", 0x81BA82, "u8", 0x50, "px", prev=LDA_IMM, max=0xFF),
        invuln(0x81B66D, 0x46),
        proj("weakness_a", "Big-flinch weapon A", 0x81B687, 0x0A),
        proj("weakness_b", "Big-flinch weapon B", 0x81B68B, 0x13),
        speed("flinch_x", "Flinch knockback X speed", 0x81BAF1, 0x0100),
        speed("flinch_y", "Flinch knockback Y speed", 0x81BAFB, 0x0221),
    ],
    attack_tables=[AttackTable(
        addr=0x86C45B, attacks={0: "Ice Shot", 2: "Blizzard", 4: "Belly Slide", 6: "Jump at X", 8: "Ice Breath"},
        rows=["after Ice Shot", "after Blizzard", "after Belly Slide", "after Jump at X", "after Ice Breath"],
        desc="Rows = the attack he just finished; 16 random picks per row. A flinch uses the 'after Ice Shot' row.")],
    # every name, value and attack below is checked in the running game by verify_chill_penguin.py
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x35: "invuln_timer",
            0x37: "flinch_timer",
            0x36: "shots", 0x38: "can_flinch", 0x39: "sliding"},
    attack_handlers=["ice_shot", "blizzard", "belly_slide", "jump_at_x", "ice_breath", "flinch"],
    func_names={0x81C019: "choose_next_attack", 0x81BF16: "breath_spawn_particle",
                0x81BF5C: "spawn_ice_statue"},
    attacks_doc={
        "Ice Shot": "Turns to X before each shot and fires the ice shots (enemy shot 6) one per keyframe, 55 frames "
                    "apart, then idles 120 frames. Fire Wave destroys the shots in flight.",
        "Blizzard": "Jumps (vy $7DE) to 10 px short of the room's centre (camera limit + 128), grabs the ceiling "
                    "hook, signals it (hook byte $1B = 1 → hook state 6, wind for about 150 frames), hangs 30 "
                    "frames, drops, lands, waits 30.",
        "Belly Slide": "Turns to X and slides at $600 (damage class 0: hits deflected; can't flinch), braking each "
                       "frame and bouncing off walls; picks the next attack the same frame it stops (BEQ quirk).",
        "Jump at X": "Jumps with horizontal speed = (X.x − his x) × 4, vy $87E; lands, pauses 30 frames.",
        "Ice Breath": "Breathes for 60 frames (a particle every 8), then makes two statues $30 and $50 in front, "
                      "waits 60 + 30. Picked while a statue still stands, it turns into Ice Shot.",
    },
)

LAUNCH_OCTOPUS = Boss(
    key="launch_octopus", name="Launch Octopus", object_id=0x07, level=1, routine=0x81C433,
    weakness="Rolling Shield",
    summary=("Opens with the Torpedo hop, then picks by X's distance (three bands, 32 random picks each; row order "
             "close, far, mid). Three Boomerang Cutter hits cut his tentacles off, after which he only uses the two "
             "torpedo attacks. Other hits make him flinch for one animation and then carry on where he was. "
             "His whirlpool catches X and drains 1 HP every 32 frames into his own bar."),
    damage_class=0x0C,
    params=[
        max_hp(0x81C50E),
        invuln(0x81C560),
        proj("cut_a", "Tentacle-cut weapon A", 0x81C58E, 0x0D),
        proj("cut_b", "Tentacle-cut weapon B", 0x81C592, 0x16),
        count("cut_hits", "Hits to sever tentacles", 0x81C485, 3, "hits"),
        speed("whirlpool_jump", "Whirlpool jump launch speed", 0x81C6D8, 0x0720,
              "The jump toward X before the whirlpool (the Torpedo hop's height comes from a table at $86C6F5)."),
        frames16("drain_time", "Energy drain max duration", 0x81C7AE, 0x01E1,
                 "How long he holds X in the whirlpool (button mashing shortens it)."),
        frames("drain_tick", "Energy drain interval", 0x81C7B5, 0x20,
               "Every this many frames X loses 1 HP and the Octopus gains 1.", copies=(0x81C825,)),
        Param("mash_cut", "Time removed per button press", 0x81C7E1, "u16", 0x10, "frames",
              prev=SBC_IMM, min=0, max=0x7FFF),
    ],
    attack_tables=[AttackTable(
        addr=0x86C625, row_len=32, total=32,
        attacks={0: "Torpedo hop", 2: "Whirlpool & drain", 4: "Piranha swarm", 6: "Torpedo volley"},
        # $81:CA07 picks the row as 0 = close, $20 = far, $40 = mid (+$60 once the tentacles are cut)
        rows=(lambda d: d + [f"{r}, tentacles cut" for r in d])([DIST[0], DIST[2], DIST[1]]),
        desc="Rows = X's distance (and whether his tentacles are cut); 32 random picks per row.")],
    attacks_doc={
        "Torpedo hop": "Hops toward X (vx $180, vy from $86:C6F5: $4C6/$555/$5D5/$64B, gravity 44), firing 3 homing "
                       "torpedoes (enemy shot 0x1E, sub-ids 2/1/0 aimed up/level/down) on the way up and down; "
                       "30 frames after landing.",
        "Whirlpool & drain": "Jumps (vy $720) with vx = distance × 256 / 42 so he comes down on X, then spins at the top "
                             "(shots bounce off) and sinks 1 px/frame inside a whirlpool (enemy shot 0x1D). If X is "
                             "caught he holds him for up to $1E1 frames, taking 1 HP every 32 frames and healing 1 "
                             "(max 32); each new button press cuts 16 frames. Then he rises to the ceiling and drops.",
        "Piranha swarm": "Releases four piranhas (enemy 0x08, sub-ids 0–3) at offsets from $86:C6E5.",
        "Torpedo volley": "Turns to X and fires 3 torpedoes on each of two animation keyframes; 30 frames.",
    },
    fields={0x0C: "cut_hits_left", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x36: "tentacles_cut",
            0x37: "row", 0x39: "spinning", 0x3A: "deflecting", 0x3B: "drain_tick", 0x3C: "invuln_timer",
            0x3D: "resume_attack"},
    attack_handlers=["torpedo_hop", "whirlpool", "piranha_swarm", "torpedo_volley", "flinch", "fall"],
    func_names={0x81CA07: "choose_next_attack", 0x81CA45: "set_pose", 0x81CA55: "fire_torpedoes",
                0x81CAB7: "tentacle_hit", 0x81C88D: "whirlpool_end",
                0x81C4A9: "intro_start", 0x81C4C8: "intro_sink", 0x81C4F5: "intro_fill_hp", 0x81C51A: "intro_end",
                0x81C5FC: "hop_start", 0x81C629: "hop_crouch", 0x81C643: "hop_rise", 0x81C66E: "hop_fall",
                0x81C68E: "hop_land",
                0x81C6AF: "whirl_jump_start", 0x81C6F3: "whirl_jump", 0x81C750: "whirl_spin", 0x81C7BB: "whirl_drain",
                0x81C87B: "whirl_rise", 0x81C8AC: "whirl_fall",
                0x81C8D1: "piranha_start", 0x81C8DC: "piranha_release", 0x81C932: "piranha_wait",
                0x81C949: "volley_start", 0x81C957: "volley_fire", 0x81C97A: "volley_wait"},
)

STING_CHAMELEON = Boss(
    key="sting_chameleon", name="Sting Chameleon", object_id=0x0A, level=2, routine=0x88853E,
    weakness="Boomerang Cutter",
    summary=("No attack table: each attack ends with its own random rolls. He opens with a leap, turns invisible "
             "to reposition (no hit check and no contact damage while cloaked) and lashes his tongue when X is in "
             "reach. Boomerang Cutter knocks him back. His high leap has a bug: the gravity store lands on vy's low "
             "byte, so it launches at vy $740 with whatever gravity he had."),
    damage_class=6,
    params=[
        max_hp(0x8886C9),
        invuln(0x888786),
        proj("knock_a", "Knockback weapon A", 0x88878D, 0x0D),
        proj("knock_b", "Knockback weapon B", 0x888791, 0x16),
        frames("cloak_fade", "Cloak fade-out length", 0x88892E, 0x20, "Fade steps, one every other frame (32 = 64 frames)."),
        frames("cloak_wait", "Invisible wait before moving", 0x888944, 0x3C),
        frames("spike_wait", "Ceiling shake: minimum time", 0x888B0F, 0x3C,
               "Plus a random 0–127 frames.", prev=ADC_IMM),
        count("sting_volleys", "Chameleon Sting volleys (max)", 0x888BAE, 3, "volleys", prev=CMP_IMM),
        count("tongue_lashes", "Tongue lashes (max)", 0x888C19, 3, "lashes", "From a wall and on the floor.",
              prev=CMP_IMM, copies=((0x888C67, CMP_IMM),)),
    ],
    attacks_doc={
        "Leap": "1 in 4: high leap to the other half of the room (screen left + 48 / 208; vy $740 from the bug, "
                "gravity unchanged) that turns into Chameleon Sting at the top; otherwise a lower jump (+ 64 / 192, "
                "vy $593, gravity 48) that turns into Ceiling shake. vx = (target − x) × 8.",
        "Cloak": "Fades his palette out (can't be hit or hurt X while cloaked), waits, then glides invisibly "
                 "toward a high corner of the screen.",
        "Wall hop": "Still cloaked: up to 3 hops toward mid-height; after each he checks 4 tongue lengths and, "
                    "if X is in reach, reappears straight into a tongue lash. Otherwise fades back in.",
        "Ceiling shake": "Hangs from the ceiling for 32 frames, then shakes it for (random & 127) + 60 frames, a spike "
                         "(enemy shot 0x11, sub-id 0) per animation keyframe; 32 frames, then cloaks.",
        "Chameleon Sting": "Turns to X and fires 3 enemy shots 0x11 (sub-ids k..k+2 of 9 directions at $400, k from "
                           "angle_between) from y + 48; after 32 frames another volley 12 in 16 (up to 3), else leap "
                           "3 in 16 or cloak.",
        "Tongue": "Lashes his tongue toward X up to 3 times while X stays in reach (sound $7C); from a wall then "
                  "cloaks or leaps (50/50), on the floor leaps.",
    },
    fields={0x2F: "airborne", 0x30: "cloak_copy", 0x33: "invuln_timer", 0x34: "timer", 0x35: "effect_slot",
            0x37: "cloaked", 0x38: "count", 0x39: "tongue_length", 0x3A: "palette_bits"},
    attack_handlers=["leap", "cloak", "cloaked_move", "ceiling_shake", "chameleon_sting", "tongue", "knockback"],
    func_names={0x88879A: "flash_hurt_draw", 0x8887F7: "start_leap", 0x8889E1: "cloaked_hop",
                0x888D2F: "set_cloak_palette", 0x888D79: "claim_effect_slot", 0x888DAB: "fade_in_step",
                0x888E0F: "fade_out_step", 0x888E4F: "x_in_tongue_reach", 0x888EB9: "fire_sting",
                0x888EA4: "x_in_floor_tongue_reach",
                0x88860C: "intro_wait", 0x888622: "intro_lower", 0x88863D: "intro_fade_in", 0x888669: "intro_fall",
                0x888694: "intro_land", 0x8886A7: "intro_pose", 0x8886B4: "intro_fill_hp", 0x8886D5: "intro_end",
                0x8887DC: "leap_start", 0x888879: "leap_fall", 0x88889D: "leap_land", 0x8888B4: "low_leap_rise",
                0x8888D0: "high_leap_rise", 0x8888F0: "high_leap_turn",
                0x88890F: "cloak_start", 0x888925: "cloak_pause", 0x888932: "cloak_fade_out", 0x888948: "cloak_hold",
                0x888972: "cloaked_choose", 0x888A18: "cloaked_glide", 0x888A44: "cloaked_fade_in",
                0x888A57: "cloaked_reveal_sting", 0x888A6A: "cloaked_hop_wait", 0x888A77: "cloaked_hop_move",
                0x888AC0: "cloaked_reveal_tongue", 0x888ADD: "cloaked_reveal_leap",
                0x888AF4: "shake_start", 0x888B03: "shake_hang", 0x888B17: "shake_spikes", 0x888B54: "shake_end",
                0x888B6A: "sting_start", 0x888B7B: "sting_fire", 0x888B9A: "sting_wait",
                0x888BDA: "tongue_start", 0x888C09: "tongue_wall", 0x888C57: "tongue_floor",
                0x888C9A: "knockback_start", 0x888CC4: "knockback_fall", 0x888CE6: "knockback_land"},
)

ARMORED_ARMADILLO = Boss(
    key="armored_armadillo", name="Armored Armadillo", object_id=0x14, level=3, routine=0x83B144,
    weakness="Electric Spark",
    summary=("Opens with the Rolling attack, then picks by X's distance and never does the same attack 3 times "
             "in a row (a table of only one attack alternates two of it with one of the other). While he waits, "
             "each X shot that comes within 80 px makes him raise his guard 12 times in 16 (shots bounce off; the "
             "guard drops the frame after one does). A charged buster shot into his guard makes him absorb it and "
             "fire 8 shots in a ring. Electric Spark staggers him and knocks his armor off: after that he never "
             "guards and can be hurt while rolling."),
    damage_class=0x0B,
    params=[
        max_hp(0x83B2B5),
        invuln(0x83B367),
        proj("armor_a", "Armor-break weapon A", 0x83B38B, 0x0C),
        proj("armor_b", "Armor-break weapon B", 0x83B38F, 0x15),
        frames("armor_invuln", "Invulnerability after the armor-break hit", 0x83B397, 0xB4,
               "The stagger itself lasts 90 frames; below that, each new hit restarts it and the armor never "
               "comes off."),
        proj("counter_a", "Counter-trigger shot A", 0x83B347, 0x02),
        proj("counter_b", "Counter-trigger shot B", 0x83B34B, 0x03),
        proj("counter_c", "Counter-trigger shot C", 0x83B34F, 0x01),
        speed("roll_speed", "Roll speed", 0x83B485, 0x0600, mirror=0x83B48A),
        speed("roll_jump", "Roll jump launch speed", 0x83B409, 0x0506),
        frames("think_time", "Pause before choosing", 0x83B605, 0x1E),
        frames("guard_time", "Guard time", 0x83B620, 0x1E, "Also used by the guard during the Energy shots.",
               copies=(0x83B758,)),
    ],
    attack_tables=[AttackTable(
        addr=0x86C980, attacks={0: "Rolling attack", 2: "Energy shots"}, rows=DIST,
        desc="Rows = X's distance; 16 random picks. Energy shots fire 3–5 shots (table $86C970).")],
    attacks_doc={
        "Rolling attack": "Jumps (vy $506), curls up, bounces once and rolls at $600. At a wall, 10 times in 16 he "
                          "ricochets around the room at $43B both ways (screen quakes at walls), otherwise he hops "
                          "off it; while ricocheting, each floor touch has a 6 in 16 chance to end it. Curled up "
                          "with his armor on, shots bounce off.",
        "Energy shots": "Fires 3–5 energy shots (enemy shot 0x04) at x ± 15, y − 14, 3 px/frame; a guard or a hit "
                        "pauses the volley, which then carries on.",
        "Guard": "While choosing (30 frames) or firing, an X shot within 80 px (front edge) and 36 px up/down is "
                 "noticed once; 12 times in 16 he guards for 30 frames, dropping it the frame after a shot bounces "
                 "off (each pushes him back 2 px).",
        "Counter": "A charged buster shot (projectile 1, 2 or 3) hitting his guard: absorbs it, then fires 8 enemy "
                   "shots 0x04 in a ring (sub-ids 1–8, $800 straight / $5A4 diagonal) and waits 30 frames.",
        "Hit": "60 frames invulnerable (flashing). Knocked back ($100) for 20 frames unless mid-roll, then resumes "
               "an unfinished volley. Electric Spark with the armor on: invulnerable 180 frames, staggers 90, "
               "falls, and the armor comes off in 5 pieces (effect 0x2B).",
    },
    fields={0x30: "x_dead", 0x31: "last_attack", 0x32: "repeats", 0x33: "armor_off", 0x34: "timer",
            0x35: "palette_bits", 0x36: "shots_left", 0x37: "guard", 0x38: "invuln_timer", 0x39: "hp_before_hit",
            0x3A: "hit_timer", 0x3B: "guard_timer", 0x3C: "pushback", 0x3D: "piece"},
    attack_handlers=["rolling_attack", "energy_shots", "guard_and_choose", "counter", "hit"],
    func_names={0x83B3C7: "hurt_and_draw", 0x83B9C8: "set_pose", 0x83B9FE: "roll_bounce",
                0x83BA20: "incoming_shot", 0x83BAAA: "deflect_pushback", 0x83BACA: "spawn_armor_piece",
                0x83BB38: "spawn_debris",
                0x83B20F: "intro_fall", 0x83B23D: "intro_bounce", 0x83B277: "intro_land_pose",
                0x83B294: "intro_fill_hp", 0x83B2C6: "intro_end",
                0x83B3F9: "roll_jump_start", 0x83B416: "roll_jump", 0x83B441: "roll_curl_fall",
                0x83B468: "roll_land_bounce", 0x83B493: "roll_along_floor", 0x83B4FE: "roll_ricochet",
                0x83B5A9: "roll_hop_off", 0x83B5E2: "roll_uncurl",
                0x83B600: "choose_start", 0x83B60E: "choose_wait", 0x83B682: "guarding",
                0x83B6A8: "energy_start", 0x83B6BE: "energy_fire", 0x83B75C: "energy_guard",
                0x83B78F: "counter_start", 0x83B7A5: "counter_absorb", 0x83B816: "counter_pause",
                0x83B839: "knockback_start", 0x83B848: "stagger_start", 0x83B878: "hit_fall",
                0x83B897: "knockback_slide", 0x83B8E3: "stagger", 0x83B8C0: "armor_break"},
)

FLAME_MAMMOTH = Boss(
    key="flame_mammoth", name="Flame Mammoth", object_id=0x0C, level=4, routine=0x8791A7,
    weakness="Storm Tornado",
    summary=("Fought on a conveyor belt that carries X, him and his oil 0.5 px a frame. If X is high up he "
             "always does the Stomp jump; otherwise he picks by X's distance. Boomerang Cutter (3 hits) knocks "
             "his trunk off (a separate object, enemy 0x0E), leaving only the jump and the volley. He stomps to "
             "reverse the belt when a puddle nears the edge, and won't do the same attack more than 3 times in a "
             "row while his trunk is on (a table with only one attack therefore freezes the game)."),
    damage_class=8,
    params=[
        max_hp(0x8792BD),
        invuln(0x879355),
        proj("trunk_a", "Trunk-cut weapon A", 0x879362, 0x0D),
        proj("trunk_b", "Trunk-cut weapon B", 0x879366, 0x16),
        count("trunk_hits", "Hits to cut trunk", 0x8791CD, 3, "hits"),
        speed("stomp_jump", "Stomp jump launch speed", 0x8793CC, 0x0593),
        frames("stun_window", "Landing stun window", 0x879438, 0x1E,
               "Frames after a Stomp jump landing in which X standing on the ground gets stunned (for the frames "
               "left). The landing's screen shake (75 frames) is separate."),
        frames("spit_pause", "Pause after trunk shot", 0x8794E7, 0x3C),
        count("volley_shots", "Volley shots (base)", 0x879521, 4, "shots", "Then randomly −1 or +1."),
        frames("volley_pause", "Pause after volley", 0x879590, 0x5A),
        frames("conveyor_wait", "Conveyor stomp time", 0x8795E5, 0x3C),
    ],
    attack_tables=[AttackTable(
        addr=0x86C843,
        attacks={0: "Stomp jump", 2: "Oil shot", 4: "Fire volley", 6: "Conveyor stomp"},
        rows=DIST + [f"{r}, trunk cut" for r in DIST],
        desc="Rows = X's distance (and whether his trunk is cut); 16 random picks. Ignored when X is high up. "
             "He refuses a 4th repeat (trunk on) and Oil shot while 2 puddles are out, and re-picks until he "
             "accepts: so a trunk row needs two different attacks besides Oil shot, a cut-trunk row one, or "
             "the game freezes.",
        single_attack_freezes=(0, 1, 2), needs_other_than=("Oil shot",))],
    # every value and attack below is checked in the running game by verify_flame_mammoth.py
    attacks_doc={
        "Stomp jump": "Jumps at X (vx = (X.x − his x) × 4, vy $593, gravity 48); the landing plays sound $4D and "
                      "shakes the screen (75), then a 60-frame pause. For 30 frames after landing (stun window) "
                      "X standing on the ground and hurtable is stunned for the frames left (X step $36 for that "
                      "+ 32 frames); never with X untouchable.",
        "Oil shot": "Spits enemy shot 0x21 from his trunk (x ± 46, y − 6; vx $280–$2FF right or −$300–−$281 "
                    "left, vy $200); it lands as a puddle that rides the belt. X touching a puddle is slowed: "
                    "his x is averaged with where he was before this frame's move (a 2 px step becomes 1). A "
                    "fireball touching it sets it alight (sound $5C, burns 180 frames). Then a 60-frame pause. "
                    "Picked while 2 puddles are out, he chooses again.",
        "Fire volley": "Fires 3–5 fireballs (enemy shot 0x20 at x ± 42, y − 7), one per animation keyframe: 4, "
                       "then half the time +1 (13 in 16) or −1 (3 in 16). A fireball flies at $440 if X is 80 px "
                       "or more away, else $260. Then a 90-frame pause.",
        "Conveyor stomp": "Stomps, waits 60 frames, flips the belt direction and swaps the conveyor tiles "
                          "(load_stage_tiles), then 60 more. Forced whenever an oil puddle is less than 64 px "
                          "from the edge the belt moves it to (checked after each pick and every frame of a "
                          "Fire volley); resumes an unfinished volley afterwards.",
    },
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x35: "shots_left",
            0x36: "trunk_hp", 0x37: "pose", 0x38: "belt_direction", 0x39: "invuln_timer",
            0x3A: "stun_window", 0x3B: "last_attack", 0x3C: "repeats"},
    attack_handlers=["stomp_jump", "oil_shot", "fire_volley", "conveyor_stomp"],
    # every name below is checked in the running game by verify_flame_mammoth.py
    func_names={0x879663: "choose_next_attack", 0x879687: "pick_from_table", 0x87971B: "landing_stun",
                0x87973C: "check_oil_near_edge",
                0x87923C: "intro_move_in", 0x879270: "intro_wait_for_x", 0x87929B: "intro_stomp",
                0x8792A8: "intro_fill_hp", 0x8792DC: "intro_wait",
                0x8793AD: "stomp_jump_aim", 0x8793D7: "stomp_jump_takeoff", 0x8793F0: "stomp_jump_rise",
                0x87940F: "stomp_jump_fall", 0x879442: "stomp_jump_land", 0x879461: "stomp_jump_pause",
                0x879480: "oil_shot_start", 0x879497: "oil_shot_spit", 0x8794EF: "oil_shot_pause",
                0x87950E: "fire_volley_start", 0x87953C: "fire_volley_fire", 0x8795A0: "fire_volley_pause",
                0x8795C1: "conveyor_stomp_start", 0x8795D8: "conveyor_stomp_raise", 0x8795F3: "conveyor_stomp_flip",
                0x879618: "conveyor_stomp_pause"},
)

STORM_EAGLE = Boss(
    key="storm_eagle", name="Storm Eagle", object_id=0x52, level=5, routine=0x87D85C,
    weakness="Chameleon Sting",
    summary=("Fought on top of the airship after a platform ride (his object appears during the ride; trigger "
             "object 20 (type 2) may be what spawns him (?)). Picks attacks from per-attack weights (out of 32): "
             "Gust (blows X toward the edge), Dive (often a chain of 6-9), Storm Tornado (also pushes X), or "
             "Birds (an egg that hatches into 4 birds). No special weapon reaction."),
    damage_class=7,
    params=[max_hp(0x87D95F), invuln(0x87D9F7),
            Param("gust_push", "Gust push on X", 0x87DAE5, "u16", 0x0200, "speed",
                  "Added to X's position every frame while X is on the side he faces and less than 16 px below "
                  "him (8.8: $0200 = 2 px; X walks at 1.5).",
                  prev=SBC_IMM, max=0x7FFF, copies=((0x87DAFF, ADC_IMM),))],
    attack_tables=[AttackTable(
        addr=0x86D41B, fmt="weights", row_len=4, total=32,
        attacks={0: "Gust", 2: "Dive", 4: "Storm Tornado", 6: "Birds"},
        rows=["after Gust", "after Dive", "after Storm Tornado", "after Birds"],
        desc="Rows = the attack he just finished; weights out of 32 (Birds, Tornado and Dive are tested in "
             "that order; Gust gets what's left).")],
    # every value and attack below is checked in the running game by verify_storm_eagle.py
    attacks_doc={
        "Gust": "Lands if airborne, then flaps (pose 1) for a random 120, 240 or 360 frames: X on the side he "
                "faces and less than 16 px below him is pushed 2 px/frame away, more than X's walking speed "
                "(1.5); wind effect every 3 frames; then a 40-frame pause.",
        "Dive": "Flies above the screen, then dives at 4 px/frame on both axes from X.x ± (X.y − his y), i.e. "
                "on a 45° line through X, and exits below; waits 40 frames and comes back from the top. "
                "One dive, or (12 in 16) a chain of 6-9.",
        "Storm Tornado": "Lands if airborne, then fires one tornado (enemy shot 0x24, speed 4 then 2 px/frame) "
                         "from his beak (pose 3). It carries X along: walking into it X still loses 1.5 px/frame.",
        "Birds": "Flies up (vy $100) for 90 frames, then drops eggs (enemy 0x55) on animation keyframes; each "
                 "egg hatches after 30 frames into 4 birds (enemy 0x56, sub-ids 0-3); then a 20-frame pause.",
    },
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x36: "dives_left",
            0x37: "invuln_timer", 0x38: "pose", 0x39: "wind_timer"},
    state_names=["init", "intro", "fight", "death"],
    attack_handlers=["gust", "dive", "storm_tornado", "birds"],
    func_names={0x87DE1F: "choose_next_attack", 0x87DE3F: "wing_sounds", 0x87DE63: "gust_wind_effect",
                0x87D8D1: "intro_appear", 0x87D902: "intro_fall", 0x87D93D: "intro_land",
                0x87D94A: "intro_fill_hp", 0x87D992: "intro_wait",
                0x87DA37: "gust_start", 0x87DA98: "gust_land", 0x87DABD: "gust_blow", 0x87DB27: "gust_pause",
                0x87DB44: "dive_rise", 0x87DB7D: "dive_aim", 0x87DBEC: "dive_down", 0x87DC10: "dive_offscreen",
                0x87DC46: "dive_return", 0x87DC6C: "dive_pause",
                0x87DC89: "tornado_start", 0x87DCCD: "tornado_land", 0x87DCE4: "tornado_fire",
                0x87DD25: "tornado_end",
                0x87DD3E: "birds_start", 0x87DD71: "birds_rise", 0x87DD82: "birds_drop_eggs",
                0x87DDD0: "birds_pause"},
)

SPARK_MANDRILL = Boss(
    key="spark_mandrill", name="Spark Mandrill", object_id=0x31, level=6, routine=0x889BE1,
    weakness="Shotgun Ice",
    summary=("Starts with a random attack, then picks from per-attack weights (out of 32): Electric Spark, "
             "Ceiling drop, Dash punch (its quake stuns X if he is on a wall) and Jump at X. Normal hits never "
             "interrupt him; Shotgun Ice freezes him, and a charged buster shot during the dash staggers him. "
             "After a stagger or a freeze he picks from two extra rows of the table (all four attacks equally)."),
    damage_class=0x0A, damage_shared_with="Vile, outside his ride armour (Sigma 1)",
    params=[
        max_hp(0x889D29),
        invuln(0x889DCE),
        proj("freeze_a", "Freeze weapon A", 0x889DFE, 0x0E),
        proj("freeze_b", "Freeze weapon B", 0x889E02, 0x17),
        proj("stagger_a", "Dash-stagger shot A", 0x889DE7, 0x01),
        proj("stagger_b", "Dash-stagger shot B", 0x889DEB, 0x02),
        proj("stagger_c", "Dash-stagger shot C", 0x889DEF, 0x03),
        speed("dash_speed", "Dash punch speed", 0x88A0B3, 0x0400, mirror=0x88A0B8),
        speed("jump_speed", "Ceiling-drop jump launch speed", 0x889F48, 0x06C3),
        speed("leap_speed", "Jump-at-X launch speed", 0x88A198, 0x070D),
    ],
    attack_tables=[AttackTable(
        addr=0x86CFDB, fmt="weights", row_len=4, total=32,
        attacks={0: "Electric Spark", 2: "Ceiling drop", 4: "Dash punch", 6: "Jump at X"},
        rows=["after Electric Spark", "after Ceiling drop", "after Dash punch", "after Jump at X",
              "after a stagger", "after being frozen"],
        desc="Rows = what he just finished (rows 5 and 6: a stagger, a freeze); weights out of 32 (Jump at X, "
             "Dash punch and Ceiling drop are tested in that order; Electric Spark gets what's left).")],
    # every value and attack below is checked in the running game by verify_spark_mandrill.py
    attacks_doc={
        "Electric Spark": "Punches the floor (screen_shake 10, sound $44): two sparks (enemy shot 0x28, sub-id 0 "
                          "runs left, $28 right) start at his x ± 26, y + 24 and crawl around the room's edges at "
                          "4 px a frame (up a wall, along the ceiling...) for 120 frames. Then a 32-frame pause.",
        "Ceiling drop": "Jumps (vy $6C3, gravity 64), catches the ceiling as he starts to fall (screen_shake 10), "
                        "hand-walks toward X 28 px a swing and lets go once X is behind him (or he meets a wall); "
                        "heavy landing (sound $4D, screen_shake 30), then a 32-frame pause.",
        "Dash punch": "Probes 34/50/56 px ahead: if clear, charges at $400 into the wall, otherwise punches on the "
                      "spot. The punch quakes the screen for 30 frames; X on a wall (sliding down it) is stunned "
                      "(x_stun(32), once per quake), X on the floor isn't. Then a 32-frame pause. A charged buster "
                      "shot mid-dash staggers him: slides back at $400 (friction 32) for 32 frames.",
        "Jump at X": "Jumps with vx = (X.x − his x) × 4 (like Chill Penguin), vy $70D, gravity 64; lands with "
                     "sound $4D and screen_shake 30; then a 32-frame pause.",
        "Frozen": "Shotgun Ice drops him to the floor and freezes him for 60 frames (more hits don't restart it); "
                  "he breaks out in 16 ice shards (effect $06, sound $4C) and waits 30 frames. Other hits don't "
                  "interrupt him.",
    },
    # $30 is cleared when the fight starts but never set (no x_dead bookkeeping, verified)
    fields={0x2F: "airborne", 0x33: "palette_bits", 0x34: "timer", 0x35: "invuln_timer", 0x36: "frozen"},
    attack_handlers=["electric_spark", "ceiling_drop", "dash_punch", "jump_at_x", "stagger", "frozen"],
    func_names={0x88A362: "choose_next_attack", 0x889E11: "flash_hurt_draw",
                0x889C6F: "intro_appear", 0x889C84: "intro_fade_out", 0x889CB7: "intro_fall", 0x889CE5: "intro_land",
                0x889D05: "intro_pose", 0x889D15: "intro_fill_hp", 0x889D3C: "intro_wait",
                0x889E45: "spark_start", 0x889E72: "spark_punch", 0x889EF6: "spark_end", 0x889F14: "spark_pause",
                0x889F37: "ceiling_jump", 0x889F59: "ceiling_rise", 0x889F7A: "ceiling_grab",
                0x889F8D: "ceiling_swing", 0x88A002: "ceiling_fall", 0x88A032: "ceiling_land",
                0x88A049: "ceiling_pause",
                0x88A068: "dash_probe", 0x88A0CE: "dash_charge", 0x88A10D: "dash_punch_here",
                0x88A122: "dash_quake", 0x88A15E: "dash_pause",
                0x88A17D: "jump_start", 0x88A1A3: "jump_crouch", 0x88A1B4: "jump_air", 0x88A1E4: "jump_land",
                0x88A1FB: "jump_pause",
                0x88A275: "frozen_start", 0x88A29D: "frozen_fall", 0x88A2CD: "frozen_wait",
                0x88A2DF: "frozen_break", 0x88A322: "frozen_after"},
)

BOOMER_KUWANGER = Boss(
    key="boomer_kuwanger", name="Boomer Kuwanger", object_id=0x05, level=7, routine=0x878A7E,
    weakness="Homing Torpedo",
    summary=("Opens with a Dash. Dashes at X, throws his horns as a boomerang, or teleports next to X (blinking; "
             "only hittable with Homing Torpedo selected, or on the frame he reappears). Whenever X is within 32 px "
             "in front of him he uses Dead Lift: grabs X and throws him up into the ceiling for 4 damage. Below 17 HP "
             "a hit can send him into a streak of 6-13 teleports."),
    damage_class=0x0D,
    params=[
        max_hp(0x878BE8),
        invuln(0x878C59),
        speed("teleport_speed", "Teleport speed", 0x878E78, 0x0800, mirror=0x878E7D),
        speed("dash_speed", "Dash speed", 0x878D25, 0x0400, mirror=0x878D2A),
    ],
    attack_tables=[
        AttackTable(addr=0x86C5A3, attacks={0: "Dash", 2: "Boomerang", 4: "Teleport"},
                    rows=["after a short dash (< 9 frames)", "after a long dash (≥ 9 frames)"],
                    title="After a dash",
                    desc="Used when a dash ends; row picked by how long he ran (field $31)."),
        AttackTable(addr=0x86C5C3, attacks={0: "Dash", 2: "Boomerang", 4: "Teleport"},
                    rows=["X far (≥ 128 px)", "X close (< 128 px)"], title="After a teleport",
                    desc="Used when he reappears; row picked by X's distance."),
    ],
    attacks_doc={
        "Dash": "Faces X (sound $53) and runs at 4 px/frame, either all the way to X (distance / 4 + 1 frames) or an "
                "8-frame burst: X under 128 px away → all the way 6 times in 16, farther → 10 in 16. Stops at a wall; "
                "20 frames, then the after-a-dash table (or another dash while his horns are out). Dead Lift if X "
                "ends up within 32 px in front.",
        "Boomerang": "Throws his horns (enemy shot 0x1B) from x, y − 24; uses hornless poses until they come back; "
                     "8 frames later he dashes.",
        "Teleport": "Vanishes (sound $50, blinking 20 frames; only Homing Torpedo can hit him) and moves at 8 px/frame "
                    "to X ± 28/48/80 px (on the side of X toward the screen's middle) or (1 in 4) to the screen "
                    "edge past X (screen left + 32 / + 224); snaps to the target within 5 px, blinks 20 more, "
                    "reappears, 8 frames, then the after-a-teleport table.",
        "Dead Lift": "Not in the tables: used whenever X is within 32 px in front. Grabs X, holds him 32 px "
                     "in front, then lifts him 8 px/frame until X hits the ceiling: 4 damage and a screen shake. "
                     "Hitting him before the throw drops X.",
    },
    fields={0x30: "x_dead", 0x31: "dash_frames", 0x32: "teleport_streak", 0x33: "palette_bits",
            0x34: "timer", 0x35: "boomerang_out", 0x36: "scratch", 0x37: "boomerang_caught",
            0x38: "teleporting", 0x39: "blink", 0x3A: "target_x", 0x3C: "lift", 0x3D: "invuln_timer",
            0x3E: "resume_attack"},
    attack_handlers=["dash", "boomerang", "teleport", "dead_lift", "flinch"],
    func_names={0x8790B1: "set_pose", 0x8790C1: "pick_teleport_target", 0x879113: "try_dead_lift",
                0x879129: "x_in_lift_range", 0x879131: "x_in_front_within", 0x879170: "dead_lift_throw",
                0x8790D6: "target_x_28", 0x8790DB: "target_x_48", 0x8790E0: "target_x_80",
                0x8790FE: "target_screen_edge",
                0x878AE7: "beam_in_start", 0x878B1A: "beam_in_right", 0x878B59: "beam_in_down",
                0x878B94: "beam_in_right_2", 0x878BCB: "fill_hp", 0x878BF8: "intro_end",
                0x879050: "resume_dash", 0x879059: "resume_boomerang", 0x87906A: "resume_teleport",
                0x879077: "resume_dead_lift",
                0x878D09: "dash_start", 0x878D6D: "dash_windup", 0x878D94: "dash_run", 0x878DBA: "dash_end",
                0x878DF1: "boomerang_start", 0x878DFF: "boomerang_throw", 0x878E4D: "boomerang_wait",
                0x878E69: "teleport_start", 0x878E8F: "teleport_vanish", 0x878EB1: "teleport_move",
                0x878EEC: "teleport_appear", 0x878F05: "teleport_wait",
                0x878F55: "lift_start", 0x878F63: "lift_reach", 0x878FA2: "lift_hold", 0x878FD0: "lift_throw",
                0x878FE7: "lift_recover"},
)

# --- fortress bosses (identified by placement + sprite; behaviour not traced yet) ----------
FORTRESS_NOTE = "Identified by stage placement and sprite; attacks not traced yet."

BOSSPIDER = Boss(
    key="bosspider", name="Bosspider (Sigma 1)", object_id=0x63, level=9, routine=0x82DB7D,
    summary=("Rides a web drawn into the stage's collision map. Drops in from one of 4 columns, shows a random "
             "path through the web, then walks it down (turning where the collision says so) and climbs back "
             "up. Drops baby spiders when X is level with him. Gets faster below 16 and 8 HP."),
    damage_class=0x0A, damage_shared_with="Spark Mandrill",
    params=[max_hp(0x82DC15)],
    attacks_doc={
        "Drop in": "Picks one of 4 x positions ($86:D65C) and descends; speed from $86:D6A2 by HP "
                   "(≥ 16, ≥ 8, below 8).",
        "Show path": "Picks a random route (up to 8 left/right choices) and lights it with marker effects "
                     "(effect 0x3C at $86:D68C/$86:D692), then waits 60 frames.",
        "Walk the web": "Follows the route: probes 16 px above him; collision $14 = turn right, $16 = turn left, "
                        "$15 = keep going down. Same HP-based speed.",
        "Babies": "When X is within 32 px of his height (and fewer than 8 exist), or 1 in 4 at the end of a "
                  "drop: releases 8 baby spiders (enemy shot 0x2B; offsets/speeds from $86:D664).",
        "At the bottom": "Damage class $0A (hurtable) for 24 frames, then climbs back to the top. Elsewhere his "
                         "class is 0 (every weapon a special $80 entry: deflected (?)).",
    },
    notes=["Hit: 24 frames of damage class 5 (no damage) and flashing.",
           "Death: freezes objects, flashes the web palette ($7F:D06C...), then removes the HUD bar "
           "(hud_boss_bar_state = 4) and sets $1F7B (stage exit (?)).",
           "Vile is object 69: never placed in a stage, so he's spawned by a script."],
    fields={0x0D: "dropped_babies", 0x1F: "landed", 0x2F: "step_sound", 0x34: "palette_bits", 0x35: "timer",
            0x36: "f36", 0x37: "baby_index", 0x3A: "path_choice", 0x3B: "path_left", 0x3C: "path_dir",
            0x3D: "web_tile", 0x3E: "speed_index", 0x3F: "invuln_timer"},
    attack_handlers=["pick_drop", "pick_path", "walk_down", "walk_across", "drop_in", "babies", "climb_up",
                     "show_path", "at_bottom"],
    func_names={0x82DC7F: "hit_and_draw", 0x82DCD7: "hurt_and_draw", 0x82DD0D: "start_drop",
                0x82DD52: "next_path_choice", 0x82DDA8: "path_done", 0x82E0B9: "maybe_drop_babies",
                0x82E0E7: "start_babies", 0x82E0F6: "follow_web", 0x82E114: "web_junction",
                0x82E184: "count_babies", 0x82E1B9: "spawn_path_marker"},
)
RANGDA_BANGDA = Boss(
    key="rangda_bangda", name="Rangda Bangda (Sigma 2)", object_id=0x5D, level=10, routine=0x88A985,
    summary=("A controller, not a body: it spawns two eyes (object 0x5E), the nose (0x5F) and closing walls "
             "(0x60), shows their combined HP in the boss bar, and tells the parts what to do. Each round: a "
             "random number of eye attacks, then the walls close in while the nose attacks. Ends when all "
             "three parts are destroyed."),
    params=[max_hp(0x88AA38)],
    attacks_doc={
        "Eyes": "Picks how many eye attacks this round ($86:D4F4), then which eye and which attack "
                "($86:D504 / $86:D524; both eyes at once once one is gone), each with 2-5 repeats (field $3A).",
        "Walls + nose": "Unless the nose is destroyed: spawns the two wall halves (0x60) and, when they signal "
                        "($1F42), starts the nose's attack.",
        "Death": "Freezes objects, 255 frames of explosions over a 128 x 128 area with screen shakes, then "
                 "the room fades out from white.",
    },
    notes=["Damage is handled by the parts; the boss bar is eye + eye + nose HP.",
           "Before the fight it locks the camera at x $1400 and fades the palette in 4 steps."],
    state_names=["setup", "fight", "death"],
    fields={0x30: "f30", 0x33: "left_eye", 0x35: "right_eye", 0x37: "nose", 0x39: "eye_attacks_left",
            0x3A: "repeats", 0x3B: "timer", 0x3D: "fade_level", 0x3E: "palette_step"},
    func_names={0x88ACDD: "spawn_eyes", 0x88AD1A: "spawn_nose", 0x88AD3B: "spawn_walls",
                0x88AD66: "total_hp", 0x88AD92: "fade_palette_1", 0x88ADB9: "fade_palette_all",
                0x88ADFC: "clear_fade_table"},
)
D_REX = Boss(
    key="d_rex", name="D-Rex (Sigma 3) (?)", object_id=0x62, level=11, routine=0x88BF48,
    summary=("A tank drawn on a background layer (it moves by scrolling that layer, $1E8D/$1E90) that X can "
             "stand on: it carries X along. It spawns a separate part (object 0x61) and coordinates with it "
             "through part1-3_status. Its own attack is ramming the walls; X gets crushed (6 damage) if "
             "pinned against one."),
    params=[max_hp(0x88C0FD)],
    attacks_doc={
        "Entrance": "Locks the camera at x $1100, loads its layer, drops in bouncing (quake + sound $20 per bounce), "
                    "fills its HP, waits 120 frames.",
        "Ram": "Drives at ±$200 (+$200 more once the part is below 16 HP; a random 12 in 16 uses another speed) "
               "until it hits a wall: screen quake for 40 frames, stuns X if he's on the ground.",
        "Follow the part": "Drives to the part's x and rides under it until part1_status is set.",
        "Back to centre": "Returns to x $11C0, signals part2 (bit 6), waits for it (192), 120 frames, then part3.",
        "Crush": "If X is pressed between it and a wall: 6 damage.",
        "Death": "48 frames, then 255 frames of explosions (64 x 32 area) with shakes; waits for part1, then "
                 "despawns.",
    },
    notes=["Its HP bar is its own HP; it ignores hits during the intro (field $34 bit 7)."],
    state_names=["setup", "fight", "death"],
    fields={0x2C: "x_on_top", 0x33: "timer", 0x34: "flags", 0x35: "part"},
    attack_handlers=["start_death", "explode", "wait_part", "pause"],
    func_names={0x88C2FB: "sync_layer", 0x88C310: "spawn_part", 0x88C333: "x_standing_check",
                0x88C38E: "crush_x", 0x88C3A6: "alive"},
)
SIGMA = Boss(
    key="sigma", name="Sigma (Sigma 4)", object_id=0x65, level=12, routine=0x88C3B2,
    summary=("The whole final sequence in one object: sends in his dog (enemy 0x26, Velguarder (?)), then "
             "fights as Sigma, then becomes Wolf Sigma (two hand objects 0x6B and his head) with a second HP "
             "fill. Talks through text boxes between phases."),
    params=[max_hp(0x88C67B),
            Param("max_hp_2", "Max HP (second fight)", 0x88CB78, "u8", 0x20, "hp", prev=CMP_IMM, min=1, max=0x7F)],
    attacks_doc={
        "Dash": "Runs at X at 4 px/frame for distance/4 frames; slashes if X enters his sword box.",
        "Jump dash": "Jumps at X at 6 px/frame until he hits a wall, then kicks off it.",
        "Shots": "Two kinds: enemy shot 0x2D, and 0x2C with sound $50 (slash wave (?)).",
        "Guard": "Damage class 0: shots are deflected (sound $47).",
        "Choosing": "After each move: guard or stand (50/50); standing picks the next move from weights out of "
                    "16 at $86:D7A9.",
        "Wolf Sigma": "Every 16-79 frames: half the time one hand attacks (part2/part3 status); otherwise the "
                      "head fires 9 slow shots (0x31, every 16 frames) or a 32-shot stream (0x32, every 3 frames).",
        "End": "Freezes everything, 240-frame quakes with explosions, a text box, then sets fortress_cleared = 4 "
               "and puts X in step $34.",
    },
    notes=["Damage classes: $12 as Sigma, $13 as Wolf Sigma (0 while invulnerable there, 5 as Sigma).",
           "Object 68 (also in Sigma 4) is a small helper."],
    state_names=["setup", "entrance", "send_dog", "wait_for_dog", "sigma_intro", "sigma_fight",
                 "sigma_defeated", "wolf_intro", "wolf_fight", "final_death"],
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "timer", 0x34: "palette_bits", 0x35: "invuln_timer",
            0x36: "pose", 0x38: "shots_left", 0x39: "quake_timer", 0x3D: "aim"},
    func_names={0x88C74D: "dash", 0x88C7E0: "jump_dash", 0x88C84F: "shot_2D", 0x88C89F: "slash_wave",
                0x88C8EA: "guard", 0x88C91F: "wall_kick", 0x88C9AE: "wall_kick_2", 0x88CA14: "stand",
                0x88CC48: "wolf_choose", 0x88CC93: "wolf_hand_attack", 0x88CCAA: "wolf_slow_shots",
                0x88CCF0: "wolf_stream", 0x88CEBB: "quake_tick", 0x88CEC8: "explosion_tick",
                0x88CEE8: "guard_or_stand", 0x88CEFB: "choose_next_move"},
)

BOSSES = {b.key: b for b in [LAUNCH_OCTOPUS, STING_CHAMELEON, ARMORED_ARMADILLO, FLAME_MAMMOTH,
                             STORM_EAGLE, SPARK_MANDRILL, BOOMER_KUWANGER, CHILL_PENGUIN,
                             BOSSPIDER, RANGDA_BANGDA, D_REX, SIGMA]}

# X himself (see PLAYER.md). Not a boss: kept out of BOSSES so the editor doesn't list it, but decomp.py
# uses it for `python3 decomp.py x` (X's update at $81:812E, direct page = his slot at $0BA8).
PLAYER = SimpleNamespace(
    key="x", name="X", routine=0x81812E,
    fields={0x0E: "visible", 0x26: "pending_damage", 0x30: "hurt_lock", 0x6B: "flash_timer",
            0x36: "buttons", 0x37: "dpad", 0x38: "buttons_prev", 0x3A: "buttons_new", 0x5E: "touch_any",
            0x69: "facing", 0x22: "prev_x", 0x85: "stun_timer", 0x87: "status_flags",
            0x89: "untouchable_2", 0x8A: "untouchable",
            0x4E: "step_timer", 0x52: "dash_timer", 0x55: "dash_jump", 0x57: "charge_timer", 0x58: "charge_state",
            0x59: "shot_request", 0x5B: "charge_level", 0x5C: "move_speed", 0x5F: "fall_cap", 0x77: "wall_stick"},
    state_names=["init", "alive"],
    attack_handlers=[],
    func_names={0x8181A3: "init", 0x81825D: "alive",
                0x8182EE: "step_normal", 0x81839D: "step_walk_start", 0x818408: "step_walk",
                0x818486: "step_jump", 0x818522: "step_fall", 0x81883E: "step_wall_slide",
                0x818A4F: "step_dying", 0x81865B: "step_hurt", 0x818B3B: "step_grabbed",
                0x818B4D: "step_hold", 0x818B57: "step_boss_freeze", 0x8189FA: "step_beam_in",
                0x818B4E: "step_boss_door", 0x819249: "step_stunned",
                0x818600: "step_land", 0x818718: "step_wall_jump", 0x81890E: "step_dash", 0x8189AA: "step_dash_end",
                0x8195EC: "x_start_jump", 0x819934: "x_step_speeds", 0x819662: "x_start_fall",
                0x8195D6: "x_to_normal", 0x819580: "x_face_dpad",
                0x81984A: "charge_idle", 0x819859: "charge_start", 0x81988A: "charge_hold"},
    # step $46 also runs step_boss_freeze (Storm Eagle's ride)
)

# Enemy shots (the $1428 list, alloc_enemy_shot $82:8358): id -> (name, update routine, marking).
# The update routine is what the enemy-shot dispatch table at $80:F77D jumps to (JSL in a 4-byte stub);
# check_records.py checks both against the ROM and that every "enemy shot 0xNN" in an attacks_doc is listed.
ENEMY_SHOT_DISPATCH = 0x80F77D
ENEMY_SHOTS = {
    0x04: ("Armored Armadillo's energy shot (sub-ids 1-8: his counter ring)", 0x83B93B, "verified"),
    0x1B: ("Boomer Kuwanger's horns", 0x83AB58, "verified"),
    0x11: ("Sting Chameleon's sting (sub-ids 1-9) / ceiling spike (sub-id 0)", 0x878328, "verified"),
    0x1D: ("Launch Octopus's whirlpool", 0x8783FF, "verified"),
    0x1E: ("Launch Octopus's homing torpedo", 0x8784D8, "verified"),
    0x20: ("Flame Mammoth's fireball", 0x878637, "verified"),
    0x21: ("Flame Mammoth's oil (puddle once it lands)", 0x8786E2, "verified"),
    0x24: ("Storm Eagle's tornado", 0x8789BF, "verified"),
    0x28: ("Spark Mandrill's spark", 0x88803C, "verified"),
    0x2B: ("Bosspider's baby spider", 0x888162, "(?)"),
    0x2C: ("Sigma's slash wave", 0x8882C4, "(?)"),
    0x2D: ("Sigma's shot", 0x88833C, "(?)"),
}

# Names we're confident about (id -> name) in the *enemy* object table ($80F8DD).
# Projectiles/effects a boss spawns use other allocators/lists with their own ids:
#   $82:8321 -> enemies ($0E68)   $82:833E -> X's shots ($1228)   $82:8358 -> enemy shots ($1428)
#   $82:82B9 -> $1628 list        $82:82D3 -> $1928 list
KNOWN_OBJECT_NAMES = {
    **{b.object_id: b.name for b in BOSSES.values()},
    0x08: "Launch Octopus's piranha",
    0x26: "Velguarder (Sigma's dog) (?)",
    0x5E: "Rangda Bangda eye", 0x5F: "Rangda Bangda nose", 0x60: "Rangda Bangda wall",
    0x61: "D-Rex part (?)",
    0x6B: "Wolf Sigma hand (?)",
    0x69: "Vile",
    0x2D: "Batton Bone",
    0x4D: "Dr. Light capsule",
    0x55: "Storm Eagle's egg (hatches into 4 x 0x56)",
    0x56: "Storm Eagle's bird (sub-id 0-3)",
    0x0E: "Flame Mammoth's trunk (follows him; falls off at trunk_hp 0)",
}
