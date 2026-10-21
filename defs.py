"""
Named, editable values in the Mega Man X1 (USA Rev 1) ROM.

Each Param points at an operand inside game code (or a data table). `prev` is the
opcode byte that must sit right before a code operand: params.py refuses to write
if it doesn't match, so we never patch the wrong place in an unexpected ROM.

Speeds are 16-bit fixed point, 1/256 px per frame (0x0600 = 6 px/frame) (?).
Frames are 1/60 s.
"""
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
    copies: tuple = ()        # other operand addresses that must hold the same value


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
    fields={0x2F: "f2F", 0x30: "f30", 0x33: "palette_bits", 0x34: "timer", 0x35: "invuln_timer",
            0x36: "shots", 0x38: "can_flinch", 0x39: "sliding"},
    attack_handlers=["ice_shot", "blizzard", "belly_slide", "jump_at_x", "ice_breath", "flinch"],
    func_names={0x81C019: "choose_next_attack", 0x81BF16: "breath_spawn_particle",
                0x81BF5C: "spawn_ice_statue"},
    attacks_doc={
        "Ice Shot": "Turns to X, fires the ice shots on animation keyframes, then idles.",
        "Blizzard": "Leaps to the room's centre, grabs the ceiling hook and starts the wind, hangs, drops.",
        "Belly Slide": "Turns to X, slides, bounces off walls, slows to a stop. No recovery pause (BEQ quirk).",
        "Jump at X": "Jumps with horizontal speed = (X.x − his x) × 4, lands, pauses 30 frames.",
        "Ice Breath": "Breathes ice, then makes two statues. Replaced by Ice Shot while a statue still stands.",
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
        rows=DIST + [f"{r}, tentacles cut" for r in DIST],
        desc="Rows = X's distance (and whether his tentacles are cut); 32 random picks per row.")],
    attacks_doc={
        "Torpedo hop": "Hops toward X (random height) firing homing torpedoes on the way up and down.",
        "Whirlpool & drain": "Jumps to X's position and spins (shots deflected). If X is caught, holds him and "
                             "drains 1 HP per interval while healing himself; mashing buttons escapes faster.",
        "Piranha swarm": "Releases four piranhas (enemy object 08) around himself.",
        "Torpedo volley": "Turns to X and fires torpedoes on animation keyframes.",
    },
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
        "Leap": "1 in 4: high leap toward the room's side; otherwise a jump across.",
        "Cloak": "Turns invisible (can't be hit), drifts to a new spot, reappears.",
        "Wall hop": "Hops up to the ceiling or along the wall, dropping toward X up to 3 times.",
        "Ceiling shake": "Hangs from the ceiling and shakes it so spikes fall (object 11).",
        "Chameleon Sting": "Turns to X and fires the 3-way shot; repeats with a 3-in-4 chance, up to 3 volleys.",
        "Tongue": "Lashes his tongue toward X up to 3 times, then jumps or cloaks (50/50).",
    },
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
        attacks={0: "Stomp jump", 2: "Trunk shot (oil?)", 4: "Volley (fire?)", 6: "Conveyor stomp"},
        rows=DIST + [f"{r}, trunk cut" for r in DIST],
        desc="Rows = X's distance (and whether his trunk is cut); 16 random picks. Ignored when X is high up.")],
    attacks_doc={
        "Stomp jump": "Jumps at X (speed = distance × 4); the landing shakes the screen and stuns a grounded X.",
        "Trunk shot (oil?)": "Fires object 21 that lands and slides on the belt; at most 2 at a time.",
        "Volley (fire?)": "Fires 3–5 shots (object 20).",
        "Conveyor stomp": "Stomps to reverse the conveyor belt.",
    },
)

STORM_EAGLE = Boss(
    key="storm_eagle", name="Storm Eagle", object_id=0x52, level=5, routine=0x87D85C,
    weakness="Chameleon Sting",
    summary=("Not placed directly: trigger object 20 (type 2) locks the camera and spawns him (enemy 52). "
             "Picks attacks from per-attack weights (out of 32). No special weapon reaction."),
    damage_class=7,
    params=[max_hp(0x87D95F), invuln(0x87D9F7)],
    attack_tables=[AttackTable(
        addr=0x86D41B, fmt="weights", row_len=4, total=32,
        attacks={0: "Fly up / hover (?)", 2: "Dive", 4: "Storm Tornado", 6: "Gust / birds (?)"},
        rows=["after Fly up", "after Dive", "after Storm Tornado", "after Gust"],
        desc="Rows = the attack he just finished; weights out of 32.")],
    attacks_doc={
        "Fly up / hover (?)": "Flies up for a random 120, 240 or 360 frames.",
        "Dive": "Swoops across the deck at X from one side (speed 0x400).",
        "Storm Tornado": "Fires tornado projectile (object 24).",
        "Gust / birds (?)": "Not traced in detail yet.",
    },
)

SPARK_MANDRILL = Boss(
    key="spark_mandrill", name="Spark Mandrill", object_id=0x31, level=6, routine=0x889BE1,
    weakness="Shotgun Ice",
    summary=("Picks attacks from per-attack weights (out of 32), cycling like Chill Penguin. Shotgun Ice "
             "freezes him; a charged buster shot at the right moment of his dash punch staggers him."),
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
        speed("jump_speed", "Jump launch speed", 0x889F48, 0x06C3),
        speed("leap_speed", "Leap-at-X launch speed", 0x88A198, 0x070D),
    ],
    attack_tables=[AttackTable(
        addr=0x86CFDB, fmt="weights", row_len=4, total=32,
        attacks={0: "Electric Spark", 2: "Jump & quake (?)", 4: "Dash punch", 6: "Leap at X (?)"},
        rows=["after Electric Spark", "after Jump", "after Dash punch", "after Leap"],
        desc="Rows = the attack he just finished; weights out of 32.")],
    attacks_doc={
        "Electric Spark": "Strikes the floor, sending sparks (object 28) along the ground.",
        "Jump & quake (?)": "High jump; the landing shakes the screen.",
        "Dash punch": "Charges across the floor (0x400). A charged buster shot mid-dash staggers him.",
        "Leap at X (?)": "Leaps toward X's position.",
    },
)

BOOMER_KUWANGER = Boss(
    key="boomer_kuwanger", name="Boomer Kuwanger", object_id=0x05, level=7, routine=0x878A7E,
    weakness="Homing Torpedo",
    summary=("Teleports around and picks attacks from two tables. While teleporting he can only be hit if X "
             "has Homing Torpedo selected. His Dead Lift grabs X and throws him to the ceiling."),
    damage_class=0x0D,
    params=[
        max_hp(0x878BE8),
        invuln(0x878C59),
        speed("dash_speed", "Dash speed", 0x878E78, 0x0800),
        speed("move_speed", "Teleport-move speed", 0x878D25, 0x0400),
    ],
    attack_tables=[
        AttackTable(addr=0x86C5A3, attacks={0: "Teleport (?)", 2: "Boomerang", 4: "Dash"},
                    rows=["after teleport (state < 9)", "after teleport (state ≥ 9)"],
                    title="Attack pattern A",
                    desc="Used after he reappears; row picked by object field $31 (meaning unconfirmed)."),
        AttackTable(addr=0x86C5C3, attacks={0: "Teleport (?)", 2: "Boomerang", 4: "Dash"},
                    rows=["X far (≥ 128 px)", "X close (< 128 px)"], title="Attack pattern B",
                    desc="Used after other attacks; row picked by X's distance."),
    ],
    attacks_doc={
        "Teleport (?)": "Vanishes and reappears near X.",
        "Boomerang": "Throws his boomerang horns (enemy projectile).",
        "Dash": "Charges across the room at 0x800.",
        "Dead Lift": "Grabs X (sets X's position) and throws him upward with a screen shake.",
    },
)

# --- fortress bosses (identified by placement + sprite; behaviour not traced yet) ----------
FORTRESS_NOTE = "Identified by stage placement and sprite; attacks not traced yet."

BOSSPIDER = Boss(
    key="bosspider", name="Bosspider (Sigma 1)", object_id=0x63, level=9, routine=0x82DB7D,
    summary="End boss of Sigma stage 1 (its sprite is the spider). " + FORTRESS_NOTE,
    damage_class=0x0A, damage_shared_with="Spark Mandrill",
    params=[max_hp(0x82DC15)],
    notes=["Uses damage class 13 (or 18) in one phase and class 0A in another.",
           "Vile is object 69: never placed in a stage, so he's spawned by a script."],
)
RANGDA_BANGDA = Boss(
    key="rangda_bangda", name="Rangda Bangda (Sigma 2) (?)", object_id=0x5D, level=10, routine=0x88A985,
    summary="End boss of Sigma stage 2 (sprite: eye orb). " + FORTRESS_NOTE,
    params=[max_hp(0x88AA38)],
    notes=["Its damage class is set elsewhere (probably by its parts)."],
)
D_REX = Boss(
    key="d_rex", name="D-Rex (Sigma 3) (?)", object_id=0x62, level=11, routine=0x88BF48,
    summary="End boss of Sigma stage 3 (sprite: dragon-headed tank). " + FORTRESS_NOTE,
    params=[max_hp(0x88C0FD)],
    notes=["Its damage class is set elsewhere (probably by its parts)."],
)
SIGMA = Boss(
    key="sigma", name="Sigma (Sigma 4)", object_id=0x65, level=12, routine=0x88C3B2,
    summary="Final stage, 10 top-level states with two HP fills (two fights in one object). " + FORTRESS_NOTE,
    params=[max_hp(0x88C67B),
            Param("max_hp_2", "Max HP (second fight)", 0x88CB78, "u8", 0x20, "hp", prev=CMP_IMM, min=1, max=0x7F)],
    notes=["Damage classes 12 and 13 are used in its two phases.", "Object 68 (also in Sigma 4) is a small helper."],
)

BOSSES = {b.key: b for b in [LAUNCH_OCTOPUS, STING_CHAMELEON, ARMORED_ARMADILLO, FLAME_MAMMOTH,
                             STORM_EAGLE, SPARK_MANDRILL, BOOMER_KUWANGER, CHILL_PENGUIN,
                             BOSSPIDER, RANGDA_BANGDA, D_REX, SIGMA]}

# Names we're confident about (id -> name) in the *enemy* object table ($80F8DD).
# Projectiles/effects a boss spawns use other allocators/lists with their own ids:
#   $82:8321 -> enemies ($0E68)   $82:833E -> X's shots ($1228)   $82:8358 -> enemy shots ($1428)
#   $82:82B9 -> $1628 list        $82:82D3 -> $1928 list
KNOWN_OBJECT_NAMES = {
    **{b.object_id: b.name for b in BOSSES.values()},
    0x08: "Launch Octopus (copy / piranhas?)",
    0x69: "Vile",
    0x2D: "Batton Bone",
    0x4D: "Dr. Light capsule",
}
