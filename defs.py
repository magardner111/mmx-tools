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
    0x01: "X-Buster half charge (?)",
    0x02: "X-Buster full charge",
    0x03: "X-Buster charge, arm upgrade (?)",
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


def count(key, label, addr, stock, noun, desc="", prev=LDA_IMM, lo=1, hi=0x20):
    return Param(key, label, addr, "u8", stock, "count", desc, prev=prev, min=lo, max=hi, noun=noun)


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
    summary=("Chooses attacks by how far away X is (three distance bands, 32 random picks each). "
             "Boomerang Cutter hits (3) sever his tentacles, which switches him to a second set of rows "
             "with only the torpedo attacks. Normal hits interrupt him briefly, then he resumes."),
    damage_class=0x0C,
    params=[
        max_hp(0x81C50E),
        invuln(0x81C560),
        proj("cut_a", "Tentacle-cut weapon A", 0x81C58E, 0x0D),
        proj("cut_b", "Tentacle-cut weapon B", 0x81C592, 0x16),
        count("cut_hits", "Hits to sever tentacles", 0x81C485, 3, "hits"),
        speed("hop_jump", "Jump-at-X launch speed", 0x81C6D8, 0x0720),
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
        "Torpedo hop": "Hops toward X (random height) firing homing torpedoes on the way up and down.",
        "Whirlpool & drain": "Jumps to X's position and spins (shots deflected). If X is caught, holds him and "
                             "drains 1 HP per interval while healing himself; mashing buttons escapes faster.",
        "Piranha swarm": "Releases four piranhas (enemy object 08) around himself.",
        "Torpedo volley": "Turns to X and fires torpedoes on animation keyframes.",
    },
    fields={0x0C: "cut_hits_left", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x36: "tentacles_cut",
            0x37: "row", 0x39: "spinning", 0x3A: "deflecting", 0x3B: "drain_tick", 0x3C: "invuln_timer",
            0x3D: "resume_attack"},
    attack_handlers=["torpedo_hop", "whirlpool", "piranha_swarm", "torpedo_volley", "flinch", "fall"],
    func_names={0x81CA07: "choose_next_attack", 0x81CA45: "set_pose", 0x81CA55: "fire_torpedoes",
                0x81CAB7: "tentacle_hit", 0x81C88D: "whirlpool_end"},
)

STING_CHAMELEON = Boss(
    key="sting_chameleon", name="Sting Chameleon", object_id=0x0A, level=2, routine=0x88853E,
    weakness="Boomerang Cutter",
    summary=("No single table: each attack ends with its own random rolls. He turns invisible to reposition "
             "and can't be hit at all while cloaked. Boomerang Cutter knocks him back."),
    damage_class=6,
    params=[
        max_hp(0x8886C9),
        invuln(0x888786),
        proj("knock_a", "Knockback weapon A", 0x88878D, 0x0D),
        proj("knock_b", "Knockback weapon B", 0x888791, 0x16),
        frames("cloak_move", "Invisible movement time", 0x88892E, 0x20, "Moves every other frame for this long."),
        frames("cloak_wait", "Wait before reappearing", 0x888944, 0x3C),
        frames("spike_wait", "Ceiling shake: minimum time", 0x888B0F, 0x3C,
               "Plus a random 0–127 frames.", prev=ADC_IMM),
        count("sting_volleys", "Chameleon Sting volleys (max)", 0x888BAE, 3, "volleys", prev=CMP_IMM),
        count("tongue_lashes", "Tongue lashes (max)", 0x888C19, 3, "lashes", prev=CMP_IMM),
    ],
    attacks_doc={
        "Leap": "1 in 4: high leap toward a side (48 px from the screen edge) that turns into Chameleon Sting "
                "at the top; otherwise a lower jump (64 px from the edge) that turns into Ceiling shake.",
        "Cloak": "Fades his palette out (can't be hit or hurt X while cloaked), waits, then glides invisibly "
                 "toward a high corner of the screen.",
        "Wall hop": "Still cloaked: up to 3 hops toward mid-height; after each he checks 4 tongue lengths and, "
                    "if X is in reach, reappears straight into a tongue lash. Otherwise fades back in.",
        "Ceiling shake": "Hangs from the ceiling and shakes it so spikes fall (object 11).",
        "Chameleon Sting": "Turns to X and fires the 3-way shot aimed with angle_between; repeats with a 3-in-4 "
                           "chance, up to 3 volleys.",
        "Tongue": "Lashes his tongue toward X up to 3 times, then jumps or cloaks (50/50).",
    },
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "invuln_timer", 0x34: "timer", 0x35: "effect_slot",
            0x37: "cloaked", 0x38: "count", 0x39: "tongue_length", 0x3A: "palette_bits"},
    attack_handlers=["leap", "cloak", "cloaked_move", "ceiling_shake", "chameleon_sting", "tongue", "knockback"],
    func_names={0x88879A: "flash_hurt_draw", 0x8887F7: "start_leap", 0x8889E1: "cloaked_hop",
                0x888D2F: "set_cloak_palette", 0x888D79: "claim_effect_slot", 0x888DAB: "fade_in_step",
                0x888E0F: "fade_out_step", 0x888E4F: "x_in_tongue_reach", 0x888EB9: "fire_sting"},
)

ARMORED_ARMADILLO = Boss(
    key="armored_armadillo", name="Armored Armadillo", object_id=0x14, level=3, routine=0x83B144,
    weakness="Electric Spark",
    summary=("Waits facing X and raises his guard when shot at (shots deflected while guarding or rolling). "
             "A charged buster shot into his guard triggers a counter-attack. Electric Spark knocks his armor "
             "off. Picks attacks by X's distance and never does the same one more than twice in a row."),
    damage_class=0x0B,
    params=[
        max_hp(0x83B2B5),
        invuln(0x83B367),
        proj("armor_a", "Armor-break weapon A", 0x83B38B, 0x0C),
        proj("armor_b", "Armor-break weapon B", 0x83B38F, 0x15),
        frames("armor_stun", "Armor-break stagger time", 0x83B397, 0xB4),
        proj("counter_a", "Counter-trigger shot A", 0x83B347, 0x02),
        proj("counter_b", "Counter-trigger shot B", 0x83B34B, 0x03),
        proj("counter_c", "Counter-trigger shot C", 0x83B34F, 0x01),
        speed("roll_speed", "Roll speed", 0x83B485, 0x0600, mirror=0x83B48A),
        speed("roll_jump", "Roll jump launch speed", 0x83B409, 0x0506),
        frames("think_time", "Pause before choosing", 0x83B605, 0x1E),
        frames("guard_time", "Guard time", 0x83B620, 0x1E),
    ],
    attack_tables=[AttackTable(
        addr=0x86C980, attacks={0: "Rolling attack", 2: "Energy shots"}, rows=DIST,
        desc="Rows = X's distance; 16 random picks. Energy shots fire 3–5 shots (table $86C970).")],
    attacks_doc={
        "Rolling attack": "Jumps, curls up and rolls at high speed, bouncing off walls (shots deflected).",
        "Energy shots": "Fires 3–5 energy shots at X.",
        "Guard": "Between attacks he faces X; incoming shots make him raise his armor for the guard time.",
        "Counter": "If a charged buster shot hits his guard he absorbs it and fires back.",
    },
    fields={0x30: "x_dead", 0x31: "last_attack", 0x32: "repeats", 0x33: "armor_off", 0x35: "palette_bits",
            0x36: "shots_left", 0x37: "guard", 0x38: "invuln_timer", 0x39: "hp_before_hit", 0x3B: "guard_timer",
            0x3C: "pushback", 0x3D: "piece"},
    attack_handlers=["rolling_attack", "energy_shots", "guard_and_choose", "counter", "hit"],
    func_names={0x83B3C7: "hurt_and_draw", 0x83B9C8: "set_pose", 0x83B9FE: "roll_bounce",
                0x83BA20: "incoming_shot", 0x83BAAA: "deflect_pushback", 0x83BACA: "spawn_armor_piece",
                0x83BB38: "spawn_debris"},
)

FLAME_MAMMOTH = Boss(
    key="flame_mammoth", name="Flame Mammoth", object_id=0x0C, level=4, routine=0x8791A7,
    weakness="Storm Tornado",
    summary=("If X is high up he always does the stomp jump; otherwise he picks by X's distance. "
             "Boomerang Cutter (3 hits) cuts his trunk, leaving only the jump and the volley. "
             "He stomps to reverse the conveyor when a puddle nears its edge, and won't do the same attack "
             "more than 3 times in a row while his trunk is intact."),
    damage_class=8,
    params=[
        max_hp(0x8792BD),
        invuln(0x879355),
        proj("trunk_a", "Trunk-cut weapon A", 0x879362, 0x0D),
        proj("trunk_b", "Trunk-cut weapon B", 0x879366, 0x16),
        count("trunk_hits", "Hits to cut trunk", 0x8791CD, 3, "hits"),
        speed("stomp_jump", "Stomp jump launch speed", 0x8793CC, 0x0593),
        frames("quake_time", "Landing quake time", 0x879438, 0x1E),
        frames("spit_pause", "Pause after trunk shot", 0x8794E7, 0x3C),
        count("volley_shots", "Volley shots (base)", 0x879521, 4, "shots", "Then randomly −1 or +1."),
        frames("volley_pause", "Pause after volley", 0x879590, 0x5A),
        frames("conveyor_wait", "Conveyor stomp time", 0x8795E5, 0x3C),
    ],
    attack_tables=[AttackTable(
        addr=0x86C843,
        attacks={0: "Stomp jump", 2: "Oil shot", 4: "Fire volley", 6: "Conveyor stomp"},
        rows=DIST + [f"{r}, trunk cut" for r in DIST],
        desc="Rows = X's distance (and whether his trunk is cut); 16 random picks. Ignored when X is high up.")],
    attacks_doc={
        "Stomp jump": "Jumps at X (speed = distance × 4); the landing shakes the screen for 75 frames and "
                      "stuns X if he is on the ground within 30 frames of it.",
        "Oil shot": "Spits enemy shot 0x21 from his trunk; it lands as a puddle that rides the conveyor. At most "
                    "2 at a time (otherwise he re-rolls).",
        "Fire volley": "Fires 3–5 shots (enemy shot 0x20, count 4 ± 1 at random) one per animation keyframe.",
        "Conveyor stomp": "Stomps, waits 60 frames, flips the belt direction and swaps the conveyor tiles "
                          "(load_stage_tiles). Forced whenever an oil puddle comes within 64 px of the edge; "
                          "resumes an unfinished volley afterwards.",
    },
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x35: "shots_left",
            0x36: "trunk_hp", 0x37: "pose", 0x38: "belt_direction", 0x39: "invuln_timer",
            0x3A: "stun_window", 0x3B: "last_attack", 0x3C: "repeats"},
    attack_handlers=["stomp_jump", "oil_shot", "fire_volley", "conveyor_stomp"],
    func_names={0x879663: "choose_next_attack", 0x879687: "pick_from_table", 0x87971B: "landing_stun",
                0x87973C: "check_oil_near_edge"},
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
    summary=("Picks attacks from per-attack weights (out of 32): Electric Spark, Ceiling drop, Dash punch "
             "(its quake stuns a grounded X) and Jump at X. Normal hits never interrupt him; Shotgun Ice "
             "freezes him, and a charged buster shot during the dash staggers him."),
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
        rows=["after Electric Spark", "after Ceiling drop", "after Dash punch", "after Jump at X"],
        desc="Rows = the attack he just finished; weights out of 32.")],
    attacks_doc={
        "Electric Spark": "Punches the floor: two sparks (enemy shot 0x28, sub-ids 0 and $28) run along the "
                          "ground; small screen shake.",
        "Ceiling drop": "Jumps to the ceiling, hand-walks toward X 28 px per swing, drops once he passes X "
                        "(or meets a wall); heavy landing with a screen shake.",
        "Dash punch": "Probes 34/50/56 px ahead: if clear, charges at 0x400 into the wall, otherwise punches "
                      "on the spot. The punch quakes the screen for 30 frames and stuns X if X is on the ground. "
                      "A charged buster shot mid-dash staggers him into a sliding knockback.",
        "Jump at X": "Jumps with horizontal speed = (X.x − his x) × 4 (like Chill Penguin), lands with a shake.",
        "Frozen": "Shotgun Ice (either level) drops him to the floor and freezes him for 60 frames; he breaks "
                  "out in 16 ice shards. Other hits don't interrupt him.",
    },
    fields={0x2F: "airborne", 0x30: "x_dead", 0x33: "palette_bits", 0x34: "timer", 0x35: "invuln_timer",
            0x36: "frozen"},
    attack_handlers=["electric_spark", "ceiling_drop", "dash_punch", "jump_at_x", "stagger", "frozen"],
    func_names={0x88A362: "choose_next_attack", 0x889E11: "flash_hurt_draw"},
)

BOOMER_KUWANGER = Boss(
    key="boomer_kuwanger", name="Boomer Kuwanger", object_id=0x05, level=7, routine=0x878A7E,
    weakness="Homing Torpedo",
    summary=("Dashes at X, throws his horn as a boomerang, or teleports next to X (invisible; only hittable "
             "with Homing Torpedo selected). Whenever X is within 32 px in front of him he uses Dead Lift: "
             "grabs X and throws him up into the ceiling for 4 damage. Below 17 HP a hit can send him into "
             "a streak of 6-13 teleports."),
    damage_class=0x0D,
    params=[
        max_hp(0x878BE8),
        invuln(0x878C59),
        speed("teleport_speed", "Teleport speed", 0x878E78, 0x0800),
        speed("dash_speed", "Dash speed", 0x878D25, 0x0400),
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
        "Dash": "Faces X and runs at 4 px/frame, either all the way to X or a short 32 px burst; Dead Lift "
                "if X ends up within 32 px in front.",
        "Boomerang": "Throws his horns (enemy shot 0x1B); uses hornless poses until they come back.",
        "Teleport": "Vanishes (blinking, only Homing Torpedo can hit him) and moves at 8 px/frame to "
                    "X ± 28/48/80 px or near a screen edge, then reappears.",
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
                0x879077: "resume_dead_lift"},
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
            0x69: "facing",
            0x89: "untouchable_2", 0x8A: "untouchable"},
    state_names=["init", "alive"],
    attack_handlers=[],
    func_names={0x8181A3: "init", 0x81825D: "alive",
                0x8182EE: "step_normal", 0x81839D: "step_walk_start", 0x818408: "step_walk",
                0x818486: "step_jump", 0x818522: "step_fall", 0x81883E: "step_wall_slide",
                0x818A4F: "step_dying", 0x81865B: "step_hurt", 0x818B3B: "step_grabbed",
                0x818B4D: "step_hold", 0x818B57: "step_boss_freeze", 0x8189FA: "step_beam_in",
                0x818B4E: "step_boss_door"},   # step $46 also runs step_boss_freeze (Storm Eagle's ride)
)

# Names we're confident about (id -> name) in the *enemy* object table ($80F8DD).
# Projectiles/effects a boss spawns use other allocators/lists with their own ids:
#   $82:8321 -> enemies ($0E68)   $82:833E -> X's shots ($1228)   $82:8358 -> enemy shots ($1428)
#   $82:82B9 -> $1628 list        $82:82D3 -> $1928 list
KNOWN_OBJECT_NAMES = {
    **{b.object_id: b.name for b in BOSSES.values()},
    0x08: "Launch Octopus (copy / piranhas?)",
    0x26: "Velguarder (Sigma's dog) (?)",
    0x5E: "Rangda Bangda eye", 0x5F: "Rangda Bangda nose", 0x60: "Rangda Bangda wall",
    0x61: "D-Rex part (?)",
    0x6B: "Wolf Sigma hand (?)",
    0x69: "Vile",
    0x2D: "Batton Bone",
    0x4D: "Dr. Light capsule",
    0x55: "Storm Eagle's egg (hatches into 4 x 0x56)",
    0x56: "Storm Eagle's bird (sub-id 0-3)",
}
