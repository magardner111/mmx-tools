"""
Re-checks what we claim about X's upgrades by running the game in Mesen (see mesen_verify.py): special weapons from
bosses, Zero's buster, the Hadouken, the armor parts, sub tanks, heart tanks and Dr. Light's capsules.

    python3 verify_upgrades.py          # about a minute on the M4 Max (runs 10 at a time, headless)
    python3 verify_upgrades.py --cached # re-check the last run's saved output

RAM: `upgrades` $1F99 (low nibble armor: $01 helmet, $02 arm, $04 body, $08 legs; high nibble sub tanks collected:
$10 Eagle, $20 Armadillo, $40 Mandrill, $80 Mammoth), sub tank slots $1F83-$1F86 (bit 7 owned, energy - $80, full
$8E), hearts $1F9C (bit per stage), max HP $1F9A ($10 + 2 per heart), weapons $1F85+2w (w = boss's level), Hadouken
$1F7E (bit 7 owned, low bits = capsule visits, capped at 5), all 8 bosses beaten $1F7C bit 6.
Most runs start from Armored Armadillo's fight-start state (work/states/armored_armadillo_fight.mss, made by
verify_armored_armadillo.py); the others warp X next to an item, a capsule or Zero.
"""
import json
import sys
import zlib
from pathlib import Path

import params
from mmx1 import MMX1, snes2pc
from mesen_verify import NO_DAMAGE, Run, countdown, report, run_all, shot_log


# ====================================================================================================================
# Special weapons
#
# Special weapons (bosses' weapons): RAM layout, grant on boss defeat, fortress flag, switching, ammo, charge, pickups.
#
# All runs start from Armored Armadillo's fight-start state (work/states/armored_armadillo_fight.mss, level 3).
# Weapon w (1..8) = the level of the boss who gives it; its word is $1F85+2w (low byte: fraction of a unit; high byte:
# bits 0-5 ammo, max $1C; bit 6 owned; bit 7 HUD bar redraw), X_weapon $0BDB = 2w (0 = buster).
# ====================================================================================================================

WEAPONS_STATE = "work/states/armored_armadillo_fight.mss"
WEAPONS_DIR = "work/upgrades"
WEAPONS_NAMES = ["X-Buster", "Homing Torpedo", "Chameleon Sting", "Rolling Shield", "Fire Wave", "Storm Tornado",
                 "Electric Spark", "Boomerang Cutter", "Shotgun Ice"]
_weapons_M = "find(0x0E68, 0x1228, 0x14)"
_weapons_NO_DAMAGE = f"do local m = {_weapons_M}; if m and r8(m + 1) == 4 then w8(0x0BD8, 8) end end"
_weapons_SET_HP1 = (f"do local a = {_weapons_M}; if a and r8(a + 1) == 4 and not hpset then w8(a + 0x27, 0x81); "
                    "hpset = true end end")
# one line whenever a weapon word, the selection, $1F7C, the level or $1F98 changes
_weapons_DUMP = ('local s = "" for w = 1, 9 do s = s .. string.format(" w%d=%d", w, r16(0x1F85 + 2 * w)) end '
                 's = s .. " sel=" .. r8(0x0BDB) .. " f7c=" .. r8(0x1F7C) .. " lvl=" .. r8(0x1F7A) '
                 'if s ~= lastdump then out("dump", s); lastdump = s end')
_weapons_FIRE = "local xx = r16(0x0BAD)\nreturn {right = xx < 5167, left = xx > 5173, y = frame % 16 < 8}"
WEAPONS_NORMAL = [0x80, 0x80, 0x100, 0x10, 0x100, 0x100, 0x100, 0x100]        # per shot (1 unit = $100)
WEAPONS_CHARGED = [0x300, 0x400, 0x200, 0x300, 0x200, 0x200, 0x200, 0x180]     # normal + charged extra
WEAPONS_LIMITS = [3, 2, 1, 1, 6, 1, 3, 3, 1]                                   # $86:BAB8[w]: shots on screen
WEAPONS_OWN_SWITCH = (1, 3, 5, 8)
# pickups: (name, sub-id, selected 2w, words {w: value}), the pickup spawned on X at frame 60
WEAPONS_PICKUPS = [
    ("big", 0, 6, {1: 0xDC00, 3: 0xC400}),
    ("small", 1, 6, {1: 0xDC00, 3: 0xC400}),
    ("full_current", 1, 6, {1: 0xDA00, 3: 0xDC00, 5: 0xC000}),
    ("buster", 1, 0, {1: 0xDC00, 2: 0x0000, 3: 0xC400, 5: 0xC000}),
    ("overflow", 0, 6, {1: 0xDB00, 2: 0xC000, 3: 0xDA00, 4: 0xC000, 5: 0x0000, 6: 0xC800, 7: 0xDC00, 8: 0xDC00}),
]
WEAPONS_F98 = [("full", 0x5C), ("ten", 0x4A), ("unowned", 0x1C)]


def _weapons_run(frames, inp, extra=(), execs=(), writes=(), reads=(), hooks=(), dump=True):
    r = Run(level=3, x=4992, frames=frames, infinite_hp=True, savestate=WEAPONS_STATE)
    for a, t in execs:
        r.on_exec(a, t)
    for a in writes:
        r.on_write(a, f"w{a:04X}")
    for a in reads:
        r.on_read(a, f"r{a:04X}")
    for a, lua in hooks:
        r.at_exec(a, lua)
    r.each_frame(_weapons_NO_DAMAGE)
    for lua in extra:
        r.each_frame(lua)
    if dump:
        r.each_frame(_weapons_DUMP)
    r.input(inp)
    return r


def _weapons_set(words, sel=None, arm=None):
    s = "if frame == 12 then " + " ".join(f"w16(0x{0x1F85 + 2 * w:04X}, {v})" for w, v in words.items())
    if sel is not None:
        s += f" w8(0x0BDB, {sel})"
    if arm is True:
        s += " w8(0x1F99, r8(0x1F99) | 2)"
    elif arm is False:
        s += " w8(0x1F99, r8(0x1F99) & 0xFD)"
    return s + " end"


_weapons_ALL_FULL = {w: 0xDC00 for w in range(1, 9)}
# shot accounting hooks: word before the normal subtraction, after it, after the charged one; projectile id
_weapons_AMMO_HOOKS = [
    (0x8194E0, 'out("pre", "x=" .. (s["cpu.x"] & 0xFF) .. " v=" .. r16(0x1F85 + (s["cpu.x"] & 0xFF)))'),
    (0x8194FA, 'out("post_n", "v=" .. r16(0x1F85 + r8(0x0BDB)))'),
    (0x81951C, 'out("post_c", "v=" .. r16(0x1F85 + r8(0x0BDB)))'),
    (0x819536, 'out("proj", "id=" .. (s["cpu.a"] & 0xFF))'),
]


def runs_weapons():
    runs = {}
    execs = [(0x84AA10, "grant"), (0x809BF3, "all8_check"), (0x809C13, "fortress_tsb"), (0x809EF9, "refill_fn")]
    own7 = "if frame == 12 then for _, a in ipairs({0x1F88, 0x1F8A, 0x1F8E, 0x1F90, 0x1F92, 0x1F94, 0x1F96}) do w8(a, 0x40) end end"
    words = list(range(0x1F87, 0x1F99)) + [0x1F7C, 0x1F7A]
    runs["weapons_kill"] = _weapons_run(1000, _weapons_FIRE, [_weapons_SET_HP1], execs, words)
    runs["weapons_kill_all8"] = _weapons_run(1000, _weapons_FIRE, [_weapons_SET_HP1, own7], execs, words)
    # switching: own 1, 3, 5, 8; R every 20 frames 12 times, then L 12 times
    inp = ("if frame < 40 then return {} end\nlocal k = (frame - 40) // 20; local p = (frame - 40) % 20 < 2\n"
           "if k < 12 then return {r = p} elseif k < 24 then return {l = p} end return {}")
    runs["weapons_switch"] = _weapons_run(540, inp, [_weapons_set({w: 0xDC00 for w in WEAPONS_OWN_SWITCH})],
                                          writes=[0x0BDB, 0x1F88])
    runs["weapons_lr"] = _weapons_run(100, "return {l = frame >= 40 and frame < 42, r = frame >= 40 and frame < 42}",
                                      [_weapons_set(_weapons_ALL_FULL, 6)], [(0x819A14, "sw_buster")], [0x0BDB])
    runs["weapons_blocked"] = _weapons_run(
        260, "return {y = frame >= 30 and frame < 32, r = (frame >= 34 and frame < 36) or (frame >= 200 and frame < 202)}",
        [_weapons_set(_weapons_ALL_FULL, 14), shot_log("xs", range(0x30), 0x1228, 0x1428)], writes=[0x0BDB])
    # ammo: arm owned, Y held frames 30-229 (the press fires a normal shot, the release a charged one)
    for w in range(1, 9):
        runs[f"weapons_ammo{w}"] = _weapons_run(
            260, "return {y = frame >= 30 and frame < 230}",
            [_weapons_set(_weapons_ALL_FULL, 2 * w, arm=True), shot_log("xs", range(0x30), 0x1228, 0x1428)],
            hooks=_weapons_AMMO_HOOKS)
    runs["weapons_firewave"] = _weapons_run(120, "return {y = frame >= 30 and frame < 90}",
                                            [_weapons_set(_weapons_ALL_FULL, 8, arm=False)], hooks=_weapons_AMMO_HOOKS)
    # negative controls: no ammo -> no shot; no arm -> no charged shot
    runs["weapons_empty"] = _weapons_run(100, "return {y = frame >= 30 and frame < 32}",
                                         [_weapons_set({**_weapons_ALL_FULL, 3: 0xC000}, 6),
                                          shot_log("xs", range(0x30), 0x1228, 0x1428)], hooks=_weapons_AMMO_HOOKS)
    runs["weapons_noarm"] = _weapons_run(260, "return {y = frame >= 30 and frame < 230}",
                                         [_weapons_set(_weapons_ALL_FULL, 6, arm=False),
                                          shot_log("xs", range(0x30), 0x1228, 0x1428)],
                                         [(0x8197DA, "arm_test")], hooks=_weapons_AMMO_HOOKS)
    # shots on screen: select weapon w with R (w presses from the buster: the switch sets the limit $67), then mash
    # Y (Fire Wave: hold), no arm; log X's shot counter ($35 = $0BDD) and shots of that id
    for w in range(9):
        sel = f"if frame >= 16 and frame < {16 + 6 * w} then return {{r = frame % 6 < 2}} end\n"
        inp = sel + ("return {y = frame >= 80}" if w == 4 else "return {y = frame >= 80 and frame % 4 < 2}")
        cnt = (f'local n = count(0x1228, 0x1428, {0 if w == 0 else w + 6}) local c = r8(0x0BDD) '
               'if n ~= lastn or c ~= lastc then out("cnt", "n=" .. n .. " c=" .. c); lastn = n; lastc = c end')
        r = _weapons_run(260, inp, [_weapons_set(_weapons_ALL_FULL, 0, arm=False), cnt], writes=[0x0BDB],
                         dump=False)
        r.on_write(0x0BDB + 0x67 - 0x33, "limit")
        r.at_exec(0x819449, 'out("gate", "c=" .. (s["cpu.a"] & 0xFF) .. " lim=" .. r8(0x0C0F))')   # CMP $67
        r.at_exec(0x819480, 'out("fired", "c=" .. r8(0x0BDD))')                                    # INC $35
        runs[f"weapons_limit{w}"] = r
    # weapon energy pickups: a $1628-list id 1 object put on X at frame 60
    for name, sub, sel, wd in WEAPONS_PICKUPS:
        spawn = ("if frame == 60 then for a = 0x1628, 0x1928 - 0x30, 0x30 do if r8(a) == 0 then "
                 "for i = 0, 0x2F do w8(a + i, 0) end w8(a, 1) w8(a + 0x0A, 1) "
                 f"w8(a + 0x0B, {sub}) w16(a + 5, r16(0x0BAD)) w16(a + 8, r16(0x0BB0) - 8) out('spawn', 'slot=' .. a) "
                 "break end end end")
        runs[f"weapons_pick_{name}"] = _weapons_run(
            150, "return {}", [_weapons_set(wd, sel), spawn],
            [(0x81E062, "pick_cur"), (0x81E0A9, "pick_tick"), (0x81E11A, "pick_spill")])
    # 9th word $1F97/$1F98 in the pause menu (Start at 30, screenshot at 150)
    for name, v in WEAPONS_F98:
        r = _weapons_run(160, "if frame >= 30 and frame < 32 then return {start = true} end return {}",
                         [f"if frame == 12 then w8(0x1F98, {v}) end"], reads=[0x1F98])
        r.screenshot(150, f"{WEAPONS_DIR}/part_f98_{name}.png")
        runs[f"weapons_f98_{name}"] = r
    return runs


def _weapons_png_rows(path):
    """Decode an 8-bit RGB/RGBA PNG (stdlib only) -> (width, rows of (r, g, b))."""
    data = open(path, "rb").read()
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n = int.from_bytes(data[pos:pos + 4], "big")
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, ctype = int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big"), body[9]
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    bpp = 4 if ctype == 6 else 3
    raw, stride, rows, prev = zlib.decompress(idat), w * bpp, [], bytearray(w * bpp)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1:
                line[i] = (line[i] + a) & 0xFF
            elif f == 2:
                line[i] = (line[i] + b) & 0xFF
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        rows.append([tuple(line[x * bpp:x * bpp + 3]) for x in range(w)])
        prev = line
    return w, rows


def _weapons_by(ev, tag):
    return [e for e in ev if e["tag"] == tag]


def _weapons_dumps(ev):
    return [e for e in ev if e["tag"] == "dump" and e["f"] >= 10]


def _weapons_last(ev, f=None):
    d = [e for e in _weapons_dumps(ev) if f is None or e["f"] <= f]
    return d[-1] if d else {}


def checks_weapons(out, check):
    g = MMX1(str(params.STOCK_ROM))
    hx = lambda v: f"${v:04X}"

    # --- boss defeat grants the weapon; stage start refills; fortress flag ---------------------------------------
    k = out["weapons_kill"]
    gr = _weapons_by(k, "grant")
    w8c = [e for e in _weapons_by(k, "w1F8C") if e["f"] >= 10]
    first = w8c[0] if w8c else {}
    pre_d = [e for e in k if e["tag"] == "dump" and gr and 2 <= e["f"] < gr[0]["f"]]
    before = pre_d[-1] if pre_d else {}
    after = _weapons_last(k, gr[0]["f"] + 1) if gr else {}
    check("weapons: beating Armored Armadillo (level 3) sets $40 in $1F88+2*(3-1) = $1F8C (STA at $84:AA1F, logged "
          "pc $84:AA22), weapon 3 word $0000 -> $4000 (owned, 0 ammo)",
          gr and first.get("v") == 0x40 and first.get("pc") == 0x84AA22 and before.get("w3") == 0
          and after.get("w3") == 0x4000,
          f"grant exec f={gr[0]['f'] if gr else None}; w1F8C v={first.get('v')} pc={hx(first.get('pc', 0))}; "
          f"w3 {hx(before.get('w3', 0))} -> {hx(after.get('w3', 0))}")
    others = [hx(after.get(f"w{w}", -1)) for w in range(1, 9) if w != 3]
    check("weapons: the grant touches only the beaten boss's weapon (others stay $0000)",
          gr and all(after.get(f"w{w}") == 0 for w in range(1, 9) if w != 3), f"w1,2,4-8 after: {others}")
    rf = _weapons_by(k, "refill_fn")
    rw = [e for e in k if e["tag"] == "w1F8C" and e["v"] == 0xDC]
    end = _weapons_last(k)
    check("weapons: at the next stage start $80:9EF9 refills every owned word to $DC00 (owned + 28 units + redraw "
          "bit); ammo max = $1C; unowned words stay 0; $1F97/$1F98 (9th slot) refilled too",
          rf and rw and rw[0]["pc"] == 0x809F08 and end.get("w3") == 0xDC00 and end.get("w9") == 0xDC00
          and all(end.get(f"w{w}") == 0 for w in (1, 2, 4, 5, 6, 7, 8)),
          f"refill f={rf[0]['f'] if rf else None}, w1F8C v=$DC pc={hx(rw[0]['pc']) if rw else None}; "
          f"end w3={hx(end.get('w3', 0))} w9={hx(end.get('w9', 0))}, others 0")
    ft = _weapons_by(k, "fortress_tsb")
    check("weapons: control — with only one boss beaten the stage end checks all 8 ($80:9BF3) but does not set "
          "$1F7C bit 6", _weapons_by(k, "all8_check") and not ft and end.get("f7c") == 0,
          f"all8_check {len(_weapons_by(k, 'all8_check'))}x, fortress_tsb {len(ft)}x, $1F7C={end.get('f7c')}")
    a8 = out["weapons_kill_all8"]
    ft = _weapons_by(a8, "fortress_tsb")
    w7c = [e for e in _weapons_by(a8, "w1F7C") if e["f"] >= 10]
    d = _weapons_last(a8, ft[0]["f"] + 1) if ft else {}
    check("weapons: with the other 7 beaten, beating the 8th: TSB $1F7C #$40 at $80:9C13 (logged pc $80:9C16), "
          "level $1F7A = 9", ft and w7c and w7c[0]["v"] == 0x40 and w7c[0]["pc"] == 0x809C16 and d.get("lvl") == 9,
          f"fortress_tsb f={ft[0]['f'] if ft else None}; w1F7C v={w7c[0]['v'] if w7c else None} "
          f"pc={hx(w7c[0]['pc']) if w7c else None}; then $1F7C={d.get('f7c')} level={d.get('lvl')}")

    # --- switching ------------------------------------------------------------------------------------------------
    sw = out["weapons_switch"]
    owned = [0] + [2 * w for w in WEAPONS_OWN_SWITCH]
    exp, cur = [], 0
    for i in range(24):
        j = owned.index(cur)
        cur = owned[(j + 1) % len(owned)] if i < 12 else owned[(j - 1) % len(owned)]
        exp.append(cur)
    got = [_weapons_last(sw, 40 + 20 * i + 15).get("sel") for i in range(24)]
    check("weapons: R/L step X_weapon $0BDB by 2 through owned weapons only, wrapping $10 <-> 0 (buster); owned "
          "{1,3,5,8}", got == exp, f"R x12 then L x12: {got}")
    check("weapons: control — unowned weapons (2, 4, 6, 7) and the 9th slot ($12) are never selected",
          not any(v in (4, 8, 12, 14) or v > 16 for v in got if v is not None), f"selections seen {sorted(set(got))}")
    w88 = [e for e in _weapons_by(sw, "w1F88") if e["f"] >= 10]
    pre = _weapons_last(sw, 39).get("w1")
    check("weapons: bit 7 of the high byte is the HUD bar redraw flag: selecting weapon 1 (word $DC00) -> bar open "
          "writes $DC (pc $80:D920), bar drawn writes $5C (pc $80:D961); word $5C00 after",
          pre == 0xDC00 and [(e["v"], e["pc"]) for e in w88[:2]] == [(0xDC, 0x80D920), (0x5C, 0x80D961)]
          and _weapons_last(sw, 45).get("w1") == 0x5C00,
          f"w1 {hx(pre or 0)}; writes {[(hex(e['v']), hx(e['pc'])) for e in w88[:3]]}; then "
          f"{hx(_weapons_last(sw, 45).get('w1', 0))}")
    lr = out["weapons_lr"]
    lrw = [e for e in _weapons_by(lr, "w0BDB") if e["f"] >= 10]
    check("weapons: L+R together selects the buster ($81:9A14) from weapon 3",
          _weapons_by(lr, "sw_buster") and lrw and lrw[0]["v"] == 0 and _weapons_last(lr).get("sel") == 0,
          f"sw_buster f={[e['f'] for e in _weapons_by(lr, 'sw_buster')]}, $0BDB 6 -> {[e['v'] for e in lrw]}")
    bl = out["weapons_blocked"]
    blw = [(e["f"], e["v"]) for e in _weapons_by(bl, "w0BDB") if e["f"] >= 10]
    cut = [e["f"] for e in _weapons_by(bl, "xs") if e["id"] == 13]
    check("weapons: no switching while a shot is out: R at frame 34 (Boomerang Cutter out) ignored, R at 200 "
          "(no shot) moves 14 -> 16", cut and min(cut) <= 34 and max(cut) < 200 and blw and blw[0][0] >= 199
          and blw[-1][1] == 16, f"cutter on screen f {min(cut) if cut else None}-{max(cut) if cut else None}; "
                                f"$0BDB writes {blw}")

    # --- shots on screen ------------------------------------------------------------------------------------------
    rom_lim = [g.sb(0x86BAB8 + w) for w in range(9)]
    for w in range(9):
        ev = out[f"weapons_limit{w}"]
        cs = [e["c"] for e in _weapons_by(ev, "cnt") if e["f"] >= 80]
        sel = [e["v"] for e in _weapons_by(ev, "w0BDB") if e["f"] >= 10]
        lim = [e["v"] for e in _weapons_by(ev, "limit") if e["f"] >= 10]
        ns = [e["n"] for e in _weapons_by(ev, "cnt") if e["f"] >= 80]
        gates = [e for e in _weapons_by(ev, "gate") if e["f"] >= 80]
        fired = [e["c"] for e in _weapons_by(ev, "fired") if e["f"] >= 80]
        blocked = [e for e in gates if e["c"] >= e["lim"]]
        L = WEAPONS_LIMITS[w]
        check(f"weapons: {WEAPONS_NAMES[w]}: fires only while X's shot counter $35 < $67 = {L} ($86:BAB8[{w}], set "
              f"by the switch; $81:9447)", rom_lim[w] == L and fired and max(fired) == L - 1
              and all(e["lim"] == L for e in gates) and (w == 0 or (sel and sel[-1] == 2 * w and lim and lim[-1] == L)),
              f"ROM {rom_lim[w]}; $0BDB -> {sel[-1] if sel else 0}, $67 <- {lim[-1] if lim else None}; fired at $35 = "
              f"{sorted(set(fired))}, blocked {len(blocked)}x at $35 = {sorted({e['c'] for e in blocked})}; max $35 = {max(cs) if cs else None}; max shots id {0 if w == 0 else w + 6} = "
              f"{max(ns) if ns else None}")

    # --- ammo per shot, charged shots ------------------------------------------------------------------------------
    rn = [g.sw(0x86BA92 + 2 * w) for w in range(1, 9)]
    rc = [g.sw(0x86BAA4 + 2 * w) for w in range(1, 9)]
    for w in range(1, 9):
        ev = [e for e in out[f"weapons_ammo{w}"] if e["tag"] in ("pre", "post_n", "post_c", "proj")]
        shots, cur = [], None
        for e in ev:
            if e["tag"] == "pre":
                cur = {"f": e["f"], "pre": e["v"]}
                shots.append(cur)
            elif cur is not None:
                cur[e["tag"]] = e.get("v", e.get("id"))
        n = shots[0] if shots else {}
        c = [s for s in shots if "post_c" in s]
        c = c[0] if c else {}
        ids = {e["id"] for e in out[f"weapons_ammo{w}"] if e["tag"] == "xs"}
        ok = (n.get("pre", 0) - n.get("post_n", 0) == WEAPONS_NORMAL[w - 1] == rn[w - 1] and n.get("proj") == w + 6
              and c.get("pre", 0) - c.get("post_c", 0) == WEAPONS_CHARGED[w - 1] == rn[w - 1] + rc[w - 1]
              and c.get("proj") == w + 15 and {w + 6, w + 15} <= ids)
        check(f"weapons: {WEAPONS_NAMES[w]}: shot costs {hx(WEAPONS_NORMAL[w - 1])} (projectile {w + 6}); full arm "
              f"charge costs {hx(WEAPONS_CHARGED[w - 1])} in all (projectile {w + 15})", ok,
              f"normal f={n.get('f')} {hx(n.get('pre', 0))} -> {hx(n.get('post_n', 0))} id {n.get('proj')}; charged "
              f"f={c.get('f')} {hx(c.get('pre', 0))} -> {hx(c.get('post_c', 0))} id {c.get('proj')}; "
              f"ROM $86:BA92 {hx(rn[w - 1])} + $86:BAA4 {hx(rc[w - 1])}")
    fw = out["weapons_firewave"]
    pres = _weapons_by(fw, "pre")
    posts = _weapons_by(fw, "post_n")
    check("weapons: Fire Wave held 60 frames: 16 flames at $10 each = 1 unit",
          len(pres) == 16 and pres[0]["v"] - posts[-1]["v"] == 0x100,
          f"{len(pres)} flames, {hx(pres[0]['v']) if pres else None} -> {hx(posts[-1]['v']) if posts else None}")
    em = out["weapons_empty"]
    check("weapons: control — no ammo (word $C000): pressing Y fires nothing ($81:94E3 BIT #$3F00)",
          _weapons_by(em, "pre") and not _weapons_by(em, "post_n") and not _weapons_by(em, "proj")
          and not any(e["id"] == 9 for e in _weapons_by(em, "xs")) and _weapons_last(em).get("w3") == 0xC000,
          f"pre {len(_weapons_by(em, 'pre'))}x, post {len(_weapons_by(em, 'post_n'))}, shots id 9: "
          f"{sum(e['id'] == 9 for e in _weapons_by(em, 'xs'))}; w3 {hx(_weapons_last(em).get('w3', 0))}")
    na = out["weapons_noarm"]
    nids = sorted({e["id"] for e in _weapons_by(na, "xs")})
    check("weapons: charging a special weapon needs the arm ($81:97DA BIT #$02): Rolling Shield held 200 frames "
          "without it -> one normal shot only, no charged projectile 18, 1 unit used",
          _weapons_by(na, "arm_test") and [e["id"] for e in _weapons_by(na, "proj")] == [9] and nids == [9]
          and not _weapons_by(na, "post_c") and _weapons_last(na).get("w3") == 0xDB00,
          f"arm_test {len(_weapons_by(na, 'arm_test'))}x; projectiles {[e['id'] for e in _weapons_by(na, 'proj')]}; "
          f"shot ids {nids}; w3 {hx(_weapons_last(na).get('w3', 0))}")

    # --- weapon energy pickups -------------------------------------------------------------------------------------
    def pick(name):
        ev = out[f"weapons_pick_{name}"]
        return ev, _weapons_last(ev, 59), _weapons_last(ev)

    ev, b, e = pick("big")
    ticks = [x["f"] for x in _weapons_by(ev, "pick_tick")]
    seq = [x["w3"] for x in _weapons_dumps(ev) if x["f"] >= 60]
    check("weapons: big pickup (sub-id 0) = 8 units into the current weapon, 1 unit ($100) every 4 frames",
          b.get("w3") == 0xC400 and e.get("w3") == 0xCC00 and len(ticks) == 8
          and all(y - x == 4 for x, y in zip(ticks, ticks[1:])) and seq == list(range(0xC500, 0xCD00, 0x100)),
          f"w3 {hx(b.get('w3', 0))} -> {[hx(v) for v in seq]}, ticks f={ticks}")
    ev, b, e = pick("small")
    check("weapons: small pickup (sub-id != 0) = 2 units", b.get("w3") == 0xC400 and e.get("w3") == 0xC600
          and len(_weapons_by(ev, "pick_tick")) == 2, f"w3 {hx(b.get('w3', 0))} -> {hx(e.get('w3', 0))}")
    ev, b, e = pick("full_current")
    check("weapons: current weapon full -> the energy goes to the first owned non-full weapon ($81:E11A)",
          _weapons_by(ev, "pick_spill") and e.get("w3") == 0xDC00 and e.get("w1") == 0xDC00 and e.get("w5") == 0xC000,
          f"w1 {hx(b.get('w1', 0))} -> {hx(e.get('w1', 0))}, w3 stays {hx(e.get('w3', 0))}, "
          f"w5 stays {hx(e.get('w5', 0))}")
    ev, b, e = pick("buster")
    check("weapons: buster selected -> first owned non-full weapon from w1 up (w1 full and w2 unowned skipped)",
          _weapons_by(ev, "pick_spill") and not _weapons_by(ev, "pick_cur") and e.get("w1") == 0xDC00
          and e.get("w2") == 0 and e.get("w3") == 0xC600 and e.get("w5") == 0xC000,
          f"w1 {hx(e.get('w1', 0))} w2 {hx(e.get('w2', 0))} w3 {hx(b.get('w3', 0))} -> {hx(e.get('w3', 0))} "
          f"w5 {hx(e.get('w5', 0))}")
    ev, b, e = pick("overflow")
    check("weapons: overflow passes on: big pickup on weapon 3 at 26 -> w3 28 (2 units), then 6 spill: w1 27 -> 28, "
          "the 5 left go to w2 (0 -> 5)",
          e.get("w3") == 0xDC00 and e.get("w1") == 0xDC00 and e.get("w2") == 0xC500,
          " ".join(f"w{w} {hx(b.get(f'w{w}', 0))}->{hx(e.get(f'w{w}', 0))}" for w in range(1, 9)))
    check("weapons: game quirk: $81:E11A never clears its overflow flag $0002, and runs before the current "
          "weapon's final $1C00 store, so after an overflow every later owned non-full weapon gets the current "
          "remainder: w3 (still 27) +5 -> 28 leaving 4, then w4 0 -> 4 and w6 8 -> 12 (8 units picked up, 17 given); "
          "unowned w5 and full w7/w8 untouched",
          e.get("w4") == 0xC400 and e.get("w6") == 0xCC00 and e.get("w5") == 0 and e.get("w7") == 0xDC00
          and e.get("w8") == 0xDC00, f"w4 {hx(e.get('w4', 0))} w5 {hx(e.get('w5', 0))} w6 {hx(e.get('w6', 0))}")

    # --- 9th slot $1F97/$1F98 in the pause menu -----------------------------------------------------------------
    dots, reads = {}, {}
    for name, v in WEAPONS_F98:
        try:
            _, rows = _weapons_png_rows(f"{WEAPONS_DIR}/part_f98_{name}.png")
            dots[name] = sum(1 for x in range(158, 218) if rows[114][x][0] > 150 and rows[114][x][2] < 200)
        except (OSError, IndexError):
            dots[name] = None
        reads[name] = sorted({e["pc"] for e in _weapons_by(out[f"weapons_f98_{name}"], "r1F98")})
    check("weapons: $1F98 is the 9th bar, drawn under ESCAPE.U in the pause menu (read by LDA $1F88,X at $80:CA91, "
          "X = $10): $5C -> 28 segments, $4A -> 10; control: bit 6 clear ($1C) -> no bar",
          dots == {"full": 28, "ten": 10, "unowned": 0} and 0x80CA94 in reads["full"],
          f"segments on row 114: {dots}; read pcs {[hx(p) for p in reads['full']]}")


# ====================================================================================================================
# Zero's buster and the Hadouken
#
# Section of verify_upgrades.py: Zero's buster (Sigma stage 1) and the Hadouken (Armored Armadillo's stage).
#
# Zero (object $66, $88:D1B8): after Vile ($1F7D = 2) he waits for X at x >= $0BB8, talks (text $1C if X has the arm,
# $1D if not) and, only without the arm, gives it: TSB $1F99 #$02 ($88:D7D5), INC $0C38. Runs start X in level 9 at
# x $0A40 with $1F7D held at 2, walk right, poke X past the locked Vile-room edge at frame 900 and press Y while the
# text box is open.
#
# Hadouken: motion detector $81:A062 (stage X+$7F = $0C27, timer X+$80 = $0C28; Down, Down+forward, forward, each
# within 20 frames, then shoot pressed or released), conditions $81:A0EA (HP == 32, $1F7E bit 7, step 0/2/4/$0A),
# step $42 ($81:9017) fires projectile 4 ($81:A114). Runs: Armadillo's fight-start state (X on the floor), his object
# cleared every frame except in the damage runs; $1F7E = $80, max HP and HP = 32 poked every frame.
#
# Capsule counter $1F7E ($87:CA86, level 3): +1 per capsule spawn, capped at 5; the capsule stays only at 5 with
# $1F99 & $1F9C == $FF, $1F7C bit 6 and HP 32. Runs warp X onto the capsule ledge (x $12D0, floor y 2415).
# ====================================================================================================================

_zero_hadouken_STATE = "work/states/armored_armadillo_fight.mss"
_zero_hadouken_NO_BOSS = "do local m = find(0x0E68, 0x1228, 0x14); if m then w8(m, 0) end end"
_zero_hadouken_XLOG = ('out("xp", "step=" .. r8(0x0BAA) .. " sub=" .. r8(0x0BAB) .. " m=" .. r8(0x0C27) .. " t=" .. '
                       'r8(0x0C28) .. " dpad=" .. r8(0x0BDF) .. " hp=" .. r8(0x0BCF) .. " face=" .. r8(0x0C11) .. '
                       '" x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0))')
_zero_hadouken_BOSS = ('do local m = find(0x0E68, 0x1228, 0x14); if m then out("boss", "hp=" .. r8(m + 0x27) .. '
                       '" cls=" .. r8(m + 0x28) .. " st=" .. r8(m + 1)) end end')
_zero_hadouken_LEDGE = (0x12D0, 2407)
_zero_hadouken_GIVE = ("if frame < 420 then w8(0x1F99, 0xFF); w8(0x1F9C, 0xFF); w8(0x1F7C, 0x40); w8(0x1F9A, 0x20); "
                       "w8(0x0BCF, 0x20) end")
ZERO_HADOUKEN_MOTION = [("down", 2), ("down+right", 2), ("right", 2)]      # X faces right in the state


def _zero_hadouken_seq(steps, start=20):
    """Lua input body: steps = [(buttons joined by '+', or None), frames], from frame `start`."""
    conds, f = [], start
    for btns, n in steps:
        if btns:
            t = ", ".join(f"{b} = true" for b in btns.split("+"))
            conds.append(f"if frame >= {f} and frame < {f + n} then return {{{t}}} end")
        f += n
    return "\n".join(conds) + "\nreturn {}"


def _zero_hadouken_had(inp, flag=0x80, hp=0x20, boss=False, frames=200):
    r = Run(level=3, x=4992, frames=frames, seed=0x1234, infinite_hp=boss, savestate=_zero_hadouken_STATE)
    r.input(inp)
    if boss:
        r.action_replay(NO_DAMAGE)
        r.each_frame(_zero_hadouken_BOSS)
    else:
        r.each_frame(_zero_hadouken_NO_BOSS)
    r.each_frame(f"if frame >= 10 then w8(0x1F7E, {flag}); w8(0x1F9A, 0x20); w8(0x0BCF, {hp}) end")
    r.each_frame(_zero_hadouken_XLOG)
    r.each_frame(shot_log("xs", range(0x20), 0x1228, 0x1428))
    r.at_exec(0x81A0E1, 'out("go", "step=" .. r8(0x0BAA))')          # conditions passed (step still the old one)
    r.on_exec(0x81A114, "spawn").on_exec(0x8088CD, "sound")
    if boss:
        r.on_write(0x1F1D, "last_hit")
    return r


def _zero_hadouken_zero(arm):
    r = Run(level=9, x=0x0A40, y=0x0590, frames=2400, seed=0x1234, infinite_hp=True)
    r.action_replay(NO_DAMAGE)
    r.each_frame("if frame < 400 then w8(0x1F7D, 2) end")
    r.each_frame(f"if frame >= 300 and frame < 400 then w8(0x1F99, {'r8(0x1F99) | 2' if arm else 'r8(0x1F99) & 0xFD'}) end")
    r.each_frame("if frame == 900 then w16(0x0BAD, 0x0BC0) end")      # past the locked Vile-room edge
    r.input("""if r8(0x1F2C) >= 0x80 then return {y = frame % 16 < 2} end
return {right = frame >= 420 and r16(0x0BAD) < 0x0BD0}""")
    r.track(0x66, tag="zero")
    for a, t in ((0x1F99, "w1F99"), (0x1F9B, "w1F9B"), (0x1F7D, "w1F7D"), (0x0C38, "w0C38"), (0x1F81, "w1F81")):
        r.on_write(a, t)
    r.at_exec(0x83F74A, 'out("text", "id=" .. r8(0x0008))')
    r.each_frame('if frame == 2399 then out("end_ram", "up=" .. r8(0x1F99) .. " p7D=" .. r8(0x1F7D) .. " p9B=" .. r8(0x1F9B)) end')
    return r


def _zero_hadouken_cap(frames, lua=(), inp="return {}", hp=True):
    r = Run(level=3, x=_zero_hadouken_LEDGE[0], y=_zero_hadouken_LEDGE[1], frames=frames, seed=0x1234, infinite_hp=hp)
    r.input(inp)
    for l in lua:
        r.each_frame(l)
    r.on_write(0x1F7E, "w1F7E")
    r.on_exec(0x87CA86, "cap_init")
    r.count_objects(0x4D, "enemy", "n4D")
    r.each_frame('if frame % 20 == 0 then out("cp", "x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0) .. " hp=" .. '
                 'r8(0x0BCF) .. " camy=" .. r16(0x00B6) .. " fl=" .. r8(0x1F7E)) end')
    return r


def runs_zero_hadouken():
    s, M = _zero_hadouken_seq, ZERO_HADOUKEN_MOTION
    h = _zero_hadouken_had
    tp = "if frame >= {f} and frame < {g} then w16(0x0BAD, {x}); w16(0x0BB0, {y}) end"
    lx = _zero_hadouken_LEDGE[0]
    return {
        "zero_hadouken_zero_noarm": _zero_hadouken_zero(False),
        "zero_hadouken_zero_arm": _zero_hadouken_zero(True),
        "zero_hadouken_basic": h(s([*M, ("y", 2)])),
        "zero_hadouken_release": h(s([("y", 4), ("y+down", 2), ("y+down+right", 2), ("y+right", 2)])),
        "zero_hadouken_backward": h(s([("down", 2), ("down+left", 2), ("left", 2), ("y", 2)])),
        "zero_hadouken_no_down": h(s([("down+right", 2), ("right", 2), ("y", 2)])),
        "zero_hadouken_gap20": h(s([("down", 1), (None, 19), ("down+right", 1), ("right", 1), ("y", 2)])),
        "zero_hadouken_gap21": h(s([("down", 1), (None, 20), ("down+right", 1), ("right", 1), ("y", 2)])),
        "zero_hadouken_last20": h(s([*M, (None, 18), ("y", 2)])),      # Y 20 frames after the first Right frame
        "zero_hadouken_last21": h(s([*M, (None, 19), ("y", 2)])),
        "zero_hadouken_walk": h(s([("right", 6), ("down", 2), ("down+right", 2), ("right", 2), ("right+y", 2), ("right", 10)])),
        "zero_hadouken_jump": h(s([("b", 10), ("b+down", 2), ("b+down+right", 2), ("b+right", 2), ("b+right+y", 2)])),
        # short hop with the motion in the air, Y on the first landing frame (step $0A)
        "zero_hadouken_land": h("""if frame >= 20 and frame < 26 then return {b = true} end
if frame >= 26 and frame < 28 then return {down = true} end
if frame >= 28 and frame < 30 then return {down = true, right = true} end
if frame >= 30 and frame < 32 then return {right = true} end
if frame >= 32 and frame < 60 and r8(0x0BAA) == 0x0A then return {y = true} end
return {}"""),
        "zero_hadouken_no_flag": h(s([*M, ("y", 2)]), flag=0),
        "zero_hadouken_hp31": h(s([*M, ("y", 2)]), hp=0x1F),
        # into Armadillo: at frame 40 he guards (class 0), at 200 he doesn't (class $0B)
        **{f"zero_hadouken_boss{t}": h(s([*M, ("y", 2)], start=t), boss=True, frames=t + 120) for t in (40, 200)},
        # capsule counter
        "zero_hadouken_cap_stay": _zero_hadouken_cap(600),
        "zero_hadouken_cap_scroll": _zero_hadouken_cap(1500, [tp.format(f=500, g=503, x=0x12A8, y=2670),
                                                              tp.format(f=800, g=803, x=lx, y=2400),
                                                              tp.format(f=1000, g=1003, x=0x12A8, y=2670),
                                                              tp.format(f=1300, g=1303, x=lx, y=2400)]),
        "zero_hadouken_cap_die": _zero_hadouken_cap(1300, inp="return {left = frame >= 500 and frame < 600}", hp=False),
        "zero_hadouken_cap_fifth": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 4) end", _zero_hadouken_GIVE]),
        "zero_hadouken_cap_hp31": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 4) end",
                                                           _zero_hadouken_GIVE.replace("w8(0x0BCF, 0x20)", "w8(0x0BCF, 0x1F)")]),
        "zero_hadouken_cap_heart": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 4) end",
                                                            _zero_hadouken_GIVE.replace("w8(0x1F9C, 0xFF)", "w8(0x1F9C, 0x7F)")]),
        "zero_hadouken_cap_upg": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 4) end",
                                                          _zero_hadouken_GIVE.replace("w8(0x1F99, 0xFF)", "w8(0x1F99, 0xFD)")]),
        "zero_hadouken_cap_7C": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 4) end",
                                                         _zero_hadouken_GIVE.replace("w8(0x1F7C, 0x40)", "w8(0x1F7C, 0x00)")]),
        "zero_hadouken_cap_owned": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 0x80) end", _zero_hadouken_GIVE]),
        "zero_hadouken_cap_ninth": _zero_hadouken_cap(600, ["if frame < 300 then w8(0x1F7E, 9) end"]),
    }


class _zero_hadouken_H:
    """One Hadouken run: X records, go/spawn/sound events, shot lives."""
    def __init__(self, ev):
        self.ev = ev
        self.x = [e for e in ev if e["tag"] == "xp" and e["f"] > 4]
        self.at = {e["f"]: e for e in self.x}
        self.go = [e for e in ev if e["tag"] == "go"]
        self.spawn = [e["f"] for e in ev if e["tag"] == "spawn"]
        self.shots = [e for e in ev if e["tag"] == "xs"]
        self.ids = sorted({e["id"] for e in self.shots})
        self.sounds = [e["a"] & 0xFF for e in ev if e["tag"] == "sound"]
        self.s42 = [e for e in self.x if e["step"] == 0x42]

    def fired(self):
        return bool(self.go) and 4 in self.ids


def _zero_hadouken_writes(ev, tag, bank=None):
    return [e for e in ev if e["tag"] == tag and e["f"] > 10 and (bank is None or e["pc"] >> 16 == bank)]


def checks_zero_hadouken(out, check):
    # --- Zero's buster ----------------------------------------------------------------------------
    for k, arm in (("noarm", False), ("arm", True)):
        ev = out[f"zero_hadouken_zero_{k}"]
        zs = [e for e in ev if e["tag"] == "zero"]
        st0E = [e for e in zs if e.get("step") == 0x0E]
        texts = [e["id"] for e in ev if e["tag"] == "text"]
        w99 = _zero_hadouken_writes(ev, "w1F99", 0x88)
        w38 = _zero_hadouken_writes(ev, "w0C38", 0x88)
        w9B = [e for e in ev if e["tag"] == "w1F9B" and e["f"] > 200]     # (new-game init clears it at f151)
        w7D = [e["v"] for e in _zero_hadouken_writes(ev, "w1F7D", 0x88)]
        w81 = [(e["v"], e["pc"]) for e in _zero_hadouken_writes(ev, "w1F81", 0x88)]  # (Vile's $88:DB1A writes 1 first)
        end = next((e for e in ev if e["tag"] == "end_ram"), {})
        pos = st0E and (st0E[-1]["x"], st0E[-1]["y"])
        if not arm:
            check("Zero ($66) after Vile ($1F7D = 2), X without the arm: text $1D, then TSB $1F99 #$02 ($88:D7D5) and "
                  "INC $0C38 ($88:D7D8); $1F7D -> 3, $1F81 -> 2; $1F9B untouched",
                  st0E and texts == [0x1D] and [e["v"] for e in w99] == [2] and w99[0]["pc"] in (0x88D7D5, 0x88D7D8)
                  and [e["v"] for e in w38] == [1] and w7D == [3] and w81[-1:] == [(2, 0x88D809)] and not w9B and end.get("up", 0) & 2,
                  f"Zero step $0E at {pos}; text ids {texts}; $1F99 writes "
                  f"{[(e['f'], e['v'], hex(e['pc'])) for e in w99]}; $0C38 {[(e['v'], hex(e['pc'])) for e in w38]}; "
                  f"$1F7D {w7D}, $1F81 {[(v, hex(a)) for v, a in w81]}; $1F9B writes after f200: {len(w9B)}; at the end $1F99 = ${end.get('up', 0):02X}")
        else:
            check("Zero with the arm already owned: text $1C, no write to $1F99 or $0C38 (no gift); $1F7D -> 3; "
                  "$1F9B untouched", st0E and texts == [0x1C] and not w99 and not w38 and w7D == [3] and not w9B,
                  f"text ids {texts}; $1F99 writes {len(w99)}, $0C38 writes {len(w38)}; $1F7D {w7D}; $1F9B writes after f200: {len(w9B)}")

    # --- Hadouken: motion ----------------------------------------------------------------------------
    t = {k[len("zero_hadouken_"):]: _zero_hadouken_H(v) for k, v in out.items() if k.startswith("zero_hadouken_")
         and not k.startswith(("zero_hadouken_cap", "zero_hadouken_zero"))}
    b = t["basic"]
    stages = []
    for e in b.x:
        if e["m"] and (not stages or stages[-1][0] != e["m"]):
            stages.append((e["m"], e["t"], e["dpad"]))
    check("Hadouken motion: Down alone -> stage 2, Down+forward -> 4, forward alone -> 6 (X+$7F), each setting the "
          "timer X+$80 to 20; then shoot -> step $42",
          [s[:2] for s in stages] == [(2, 20), (4, 20), (6, 20)] and b.s42 and b.fired(),
          f"(stage, timer, dpad) {stages}; go at f{[e['f'] for e in b.go]}, shot ids {b.ids}")
    bw = t["backward"]
    turn = next((e for a, e in zip(bw.x, bw.x[1:]) if a["face"] == 0x40 and e["face"] == 0), None)
    st4 = next((e for e in bw.x if e["m"] == 4), None)
    check("forward is X's facing: Down, Down+Left, Left works too (Down+Left turns X left, then matches $06)",
          bw.fired() and turn and turn["dpad"] == 6 and st4 and st4["f"] >= turn["f"],
          f"facing $40 -> 0 at f{turn and turn['f']} (dpad {turn and turn['dpad']}), stage 4 at f{st4 and st4['f']}; "
          f"go {[e['f'] for e in bw.go]}, ids {bw.ids}")
    check("exact match: without a Down-alone frame (Down+Right first) no Hadouken", not t["no_down"].go,
          f"go {t['no_down'].go}, ids {t['no_down'].ids}")
    r = t["release"]
    check("shoot released also triggers it (Y held through the motion: the press fires a buster shot, the release "
          "the Hadouken)", r.fired() and 0 in r.ids, f"go at f{[e['f'] for e in r.go]}, ids {r.ids}")
    check("window: Down+forward 20 frames after Down still counts, 21 frames is too late",
          t["gap20"].fired() and not t["gap21"].go, f"20: go {[e['f'] for e in t['gap20'].go]}; 21: go {t['gap21'].go}")
    check("window: shoot 20 frames after the first forward frame still counts, 21 is too late",
          t["last20"].fired() and not t["last21"].go, f"20: go {[e['f'] for e in t['last20'].go]}; 21: go {t['last21'].go}")

    # --- Hadouken: conditions --------------------------------------------------------------------------
    gs = {k: [e["step"] for e in t[k].go] for k in ("last20", "basic", "walk", "land")}
    check("allowed steps: standing (0), walking (2 and 4), landing ($0A)",
          gs["last20"] == [0] and gs["basic"] == [2] and gs["walk"] == [4] and gs["land"] == [0x0A]
          and all(t[k].fired() for k in gs), f"step when it fired: {gs}")
    j = t["jump"]
    check("in the air (jump steps 6/8) no Hadouken", not j.go and 0x42 not in {e['step'] for e in j.x},
          f"steps {sorted({hex(e['step']) for e in j.x})}, ids {j.ids}")
    check("needs $1F7E bit 7 (no Hadouken with $1F7E = 0)", not t["no_flag"].go, f"go {t['no_flag'].go}, ids {t['no_flag'].ids}")
    check("needs HP exactly 32 (none at 31)", not t["hp31"].go and b.x[-1]["hp"] == 32,
          f"hp31: go {t['hp31'].go}, ids {t['hp31'].ids}")

    # --- Hadouken: step $42 and the projectile -----------------------------------------------------------
    s42 = b.s42
    first = s42[0]["f"] if s42 else 0
    sh = [e for e in b.shots if e["id"] == 4]
    xat = b.at.get(sh[0]["f"], {}) if sh else {}
    # (the first frame still has vx 0: the shot moves from its second frame on)
    dx = sorted({q["x"] - p["x"] for p, q in zip(sh[1:], sh[2:]) if q["f"] == p["f"] + 1}) if sh else []
    check("step $42 lasts 42 frames, then step 0", len(s42) == 42 and b.at.get(s42[-1]["f"] + 1, {}).get("step") == 0,
          f"step $42 f{first}..f{s42 and s42[-1]['f']} ({len(s42)} frames)")
    check("projectile 4 ($81:A114) spawned 17 frames after step $42 starts, at X+25 px, X-3 px, moving 4 px a frame "
          "(vx $400, from its 2nd frame); sound $AF", b.spawn and b.spawn[0] - first == 16 and sh and sh[0]["x"] - xat.get("x", 0) == 25
          and sh[0]["y"] - xat.get("y", 0) == -3 and dx == [4] and any(e["vx"] == 0x400 for e in sh) and 0xAF in b.sounds,
          f"spawn exec f{b.spawn} (exec f = frame - 1; step $42 from f{first}), shot at ({sh and sh[0]['x']}, "
          f"{sh and sh[0]['y']}) vs X ({xat.get('x')}, {xat.get('y')}), dx {dx}, vx {sorted({e['vx'] for e in sh})}, "
          f"sounds {[hex(v) for v in b.sounds]}")

    # --- Hadouken: damage ----------------------------------------------------------------------------
    for k, kill in (("boss200", True), ("boss40", False)):
        ev = out[f"zero_hadouken_{k}"]
        hit = [e["f"] for e in ev if e["tag"] == "last_hit" and e["v"] == 4]
        bs = {e["f"]: e for e in ev if e["tag"] == "boss"}
        before = bs.get(hit[0], {}) if hit else {}
        after = bs.get(hit[0] + 1, {}) if hit else {}
        if kill:
            check("Hadouken on Armadillo (class $0B): 32 damage, HP 32 -> 0 in one hit (state 6)",
                  hit and before.get("hp") == 32 and before.get("cls") == 0x0B and after.get("hp") == 0 and after.get("st") == 6,
                  f"hit ($1F1D = 4) at f{hit}; boss before {before}, after {after}")
        else:
            later = [e["hp"] for f, e in bs.items() if hit and f > hit[0]]
            check("Armadillo's guard (class 0) blocks it: the hit registers ($1F1D = 4), no damage",
                  hit and before.get("cls") == 0 and later and min(later) == 32,
                  f"hit at f{hit}; boss class {before.get('cls')}, HP after {sorted(set(later))}")

    # --- capsule counter $1F7E ----------------------------------------------------------------------------
    def cap(k):
        ev = out[f"zero_hadouken_cap_{k}"]
        inits = [e["f"] for e in ev if e["tag"] == "cap_init"]
        w = [e["v"] for e in ev if e["tag"] == "w1F7E" and e["pc"] >> 16 == 0x87]
        n = [(e["f"], e["n"]) for e in ev if e["tag"] == "n4D"]
        stays = bool(n) and n[-1][1] == 1 and bool(inits)
        return ev, inits, w, n, stays

    _, i, w, n, st = cap("stay")
    check("capsule $4D init ($87:CA86) on level 3: $1F7E += 1 (0 -> 1); below 5 it deletes itself",
          len(i) == 1 and w == [1] and not st, f"inits f{i}, $1F7E writes {w}, objects {n}")
    _, i, w, n, st = cap("ninth")
    check("cap: the count is stored as 5 once it reaches 5 (preset 9 -> 10 -> 5)", w == [10, 5] and not st,
          f"writes {w}, objects {n}")
    _, i, w, n, st = cap("fifth")
    check("5th spawn with every upgrade ($1F99 & $1F9C == $FF), $1F7C bit 6 and HP 32: the capsule stays",
          w == [5, 5] and st, f"writes {w}, objects {n}")
    neg = {}
    for k in ("hp31", "heart", "upg", "7C"):
        _, i, w, n, st = cap(k)
        neg[k] = (w, st)
    check("5th spawn, one condition missing (HP 31 / a heart $1F9C = $7F / the arm $1F99 = $FD / $1F7C = 0): deleted",
          all(w == [5, 5] and not st for w, st in neg.values()), f"(writes, stays) {neg}")
    _, i, w, n, st = cap("owned")
    check("Hadouken owned ($1F7E bit 7): no count, the capsule deletes itself", i and not w and not st,
          f"inits {i}, writes {w}, objects {n}")
    ev, i, w, n, st = cap("die")
    cp = [e for e in ev if e["tag"] == "cp"]
    fell = max((e["y"] for e in cp), default=0)
    check("dying and respawning spawns the capsule again and counts again (1 -> 2): the counter survives death",
          len(i) == 2 and w == [1, 2] and fell > 2700, f"inits f{i}, writes {w}, X fell to y {fell}")
    ev, i, w, n, st = cap("scroll")
    cy = [e["camy"] for e in ev if e["tag"] == "cp" and e["f"] > 300]
    check("scrolling the camera away (264 px down) and back, twice: no new spawn, no count",
          len(i) == 1 and w == [1] and cy and max(cy) - min(cy) >= 200,
          f"inits f{i}, writes {w}, camera y {min(cy) if cy else None}..{max(cy) if cy else None}")


# ====================================================================================================================
# Armor parts
#
# Armor upgrades (`upgrades` = $1F99 low nibble: $01 helmet, $02 arm, $04 body, $08 legs): what each bit does to X.
#
# Section of the future verify_upgrades.py (run alone: python3 work/scratch/part_harness.py armor [--cached]).
# `upgrades` is forced every frame in each run (w8, so also before X's init in warped runs).
#
# - Armadillo's fight-start state (work/states/armored_armadillo_fight.mss, made by verify_armored_armadillo.py):
#   damage (x_take_damage called from X's update with HP 12; HP above the max 16 is clamped, so 12), contact damage
#   (Armadillo left alive, X walks into him), double-tap dash (boss cleared every frame), charging a special weapon.
# - Warped starts (X beams in, ~470 frames): Storm Eagle's $3C block (x 3952-4015, bottom y 623, floor 672) for the
#   headbutt and X's gfx; Sting Chameleon's $3C wall (x 1392-1407, y 832-959; X starts at 1416 on the floor at 960)
#   for wall kicks; Chameleon's cave at x 1560 (floor 736) for the falling rocks (enemy $18: X's buster shots make
#   them fall, `$83:BD6A`).
# Breaking a $3C tile = `$84:9129` (tile number + 1 in the map at $7E:2000) followed by sound $23.
# ====================================================================================================================

_ARMOR_STATE = "work/states/armored_armadillo_fight.mss"
_ARMOR_NO_BOSS = "do local m = find(0x0E68, 0x1228, 0x14); if m then w8(m, 0) end end"
_ARMOR_XLOG = ('out("ax", "step=" .. r8(0x0BAA) .. " x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0) .. " hp=" .. '
               '(r8(0x0BCF) & 0x7F) .. " charge=" .. r8(0x0C00) .. " lvl=" .. r8(0x0C03) .. " gfx=" .. r8(0x0BBE) .. '
               '" vx=" .. s16(0x0BC2))')
_ARMOR_SHOTS = ('for a = 0x1228, 0x13E8, 0x40 do if r8(a) ~= 0 then out("ashot", "id=" .. r8(a + 10)) end end')
ARMOR_STING = "w16(0x1F89, 0xDC00); w8(0x0BDB, 4)"          # own Chameleon Sting (weapon 2) and select it
ARMOR_DMG = (1, 2, 3, 5, 8)
ARMOR_GAPS = (1, 4, 10, 11, 12, 13)


def _armor_force(v):
    return f"w8(0x1F99, {v})"


def _armor_state_run(frames, up, inp="return {}", boss=False):
    r = Run(level=3, x=4992, frames=frames, seed=0x1234, infinite_hp=False, savestate=_ARMOR_STATE)
    r.input(inp)
    if not boss:
        r.each_frame(_ARMOR_NO_BOSS)
    return r.each_frame(_armor_force(up)).each_frame(_ARMOR_XLOG)


def _armor_warp(level, x, y, frames, up, inp):
    """Warped start; `inp` is Lua using t = frames since X first stood in step 0 (no input before)."""
    r = Run(level=level, x=x, y=y, frames=frames, seed=0x1234, infinite_hp=False)
    r.input("local st = r8(0x0BAA)\nif st == 0 and not t0 and frame > 30 then t0 = frame end\n"
            "local t = t0 and frame - t0\nif not t then return {} end\n" + inp)
    r.each_frame(_armor_force(up)).each_frame(_ARMOR_XLOG)
    for a, tag in ((0x849129, "tile_inc"), (0x819EA1, "headbutt"), (0x819EAC, "helmet_br"), (0x8198FC, "wallbrk"),
                   (0x819903, "legs_br")):
        r.on_exec(a, tag)
    r.at_exec(0x8088CD, 'out("snd", "id=" .. (s["cpu.a"] & 0xFF))')
    return r


def runs_armor():
    runs = {}
    for d in ARMOR_DMG:
        for up in (0, 4):
            r = _armor_state_run(60, up)
            r.call(0x81812E, 0x849F2F, when="frame == 30", d=0x0BA8, db=0x86, watch=False,
                   pre=f"w8(0x0BCF, 0x80 | 12); w8(0x0BCE, {d})", tag="dmg")
            r.at_exec(0x849F59, 'out("td", "dmg=" .. r8(0x0000))')
            runs[f"armor_dmg{d}_{up}"] = r
    for up in (0, 4):
        r = _armor_state_run(360, up, "return {right = frame >= 20}", boss=True)
        r.at_exec(0x849D50, 'out("cd", "dmg=" .. r8(0x0000) .. " hp=" .. (r8(0x0BCF) & 0x7F))')
        runs[f"armor_contact_{up}"] = r
    tap = "return {{{k} = frame == 20 or (frame >= {a} and frame < {b})}}"
    for gap in ARMOR_GAPS:
        runs[f"armor_tap{gap}_8"] = _armor_state_run(110, 8, tap.format(k="right", a=21 + gap, b=51 + gap))
    for gap in (1, 4, 11):
        runs[f"armor_tap{gap}_0"] = _armor_state_run(110, 0, tap.format(k="right", a=21 + gap, b=51 + gap))
    # tap left from x 5200 (the state's X position is 5147 + a few px; walk right first to have room)
    left = ("return {right = frame >= 15 and frame < 45, left = frame == 60 or (frame >= 64 and frame < 90)}")
    for up in (0, 8):
        runs[f"armor_tapL_{up}"] = _armor_state_run(130, up, left)
    for up in (0, 2):
        r = _armor_state_run(260, up, "return {y = frame >= 20 and frame < 220}")
        r.each_frame(ARMOR_STING).each_frame(_ARMOR_SHOTS)
        runs[f"armor_sting_{up}"] = r
    for up in (0, 1):
        runs[f"armor_headbutt_{up}"] = _armor_warp(5, 3976, 655, 700, up, "return {b = t >= 10 and t % 40 < 25}")
    for up in (0, 1, 8):
        runs[f"armor_wall_{up}"] = _armor_warp(2, 1416, 943, 640, up, "return {left = true, b = t >= 10 and t % 8 < 3}")
    for up in (0, 1):
        r = _armor_warp(2, 1560, 719, 720, up, "return {y = t >= 10 and t % 20 < 2}")
        r.at_exec(0x83BD2C, 'out("rock_hit", "")')          # rock touches X with X below it
        r.at_exec(0x83BD38, 'out("rock_dmg", "")')          # ...and calls x_take_damage(1)
        runs[f"armor_rock_{up}"] = r
    return runs


def _armor_x(ev):
    return [e for e in ev if e["tag"] == "ax" and e["f"] > 10]


def _armor_tags(ev, tag):
    return [e for e in ev if e["tag"] == tag]


def _armor_steps(ev):
    out = []
    for e in _armor_x(ev):
        if not out or out[-1][1] != e["step"]:
            out.append((e["f"], e["step"]))
    return out


def _armor_breaks(ev):
    """Frames with a tile change, and whether sound $23 played in each of them."""
    snd = {e["f"] for e in _armor_tags(ev, "snd") if e["id"] == 0x23}
    tiles = sorted({e["f"] for e in _armor_tags(ev, "tile_inc")})
    return tiles, all(f in snd for f in tiles), len(snd)


def checks_armor(out, check):
    # --- body ($04): damage halved, rounded up --------------------------------------------------------------
    got = {}
    for d in ARMOR_DMG:
        for up in (0, 4):
            xs = _armor_x(out[f"armor_dmg{d}_{up}"])
            td = _armor_tags(out[f"armor_dmg{d}_{up}"], "td")
            got[d, up] = (12 - xs[-1]["hp"] if xs else None, td[0]["dmg"] if td else None)
    want = {d: (d + 1) // 2 for d in ARMOR_DMG}
    check("body (upgrades $04): x_take_damage takes ceil(d/2) (1->1, 2->1, 3->2, 5->3, 8->4); full d without it",
          all(got[d, 0] == (d, d) and got[d, 4] == (want[d], want[d]) for d in ARMOR_DMG),
          "HP 12 minus: " + ", ".join(f"d {d}: {got[d, 0][0]} / body {got[d, 4][0]}" for d in ARMOR_DMG))
    cd = {up: [(e["dmg"], e["hp"]) for e in _armor_tags(out[f"armor_contact_{up}"], "cd")] for up in (0, 4)}
    hp = {up: (_armor_x(out[f"armor_contact_{up}"]) or [{"hp": None}])[-1]["hp"] for up in (0, 4)}
    check("body: x_contact_damage halves Armadillo's contact hits too (6->3, 4->2)",
          [d for d, _ in cd[0]][:2] == [6, 4] and [d for d, _ in cd[4]][:2] == [3, 2]
          and hp[0] == 16 - 10 and hp[4] == 16 - 5,
          f"hits (damage, HP before) no armor {cd[0]} -> HP {hp[0]}; body {cd[4]} -> HP {hp[4]}")

    # --- legs ($08): double-tap dash ---------------------------------------------------------------------------
    dash = {}
    for gap in ARMOR_GAPS:
        st = _armor_steps(out[f"armor_tap{gap}_8"])
        dash[gap] = next((f for f, s in st if s == 0x14), None)
    check("legs (upgrades $08): Right tapped twice dashes (step $14) if the second press comes <= 12 frames after "
          "the first (gaps 1, 4, 10, 11 released frames), not after 13-14 (gaps 12, 13: a walk)",
          all(dash[g] == 22 + g for g in (1, 4, 10, 11)) and dash[12] is None and dash[13] is None,
          "first press f20; dash starts at " + ", ".join(f"gap {g}: {dash[g]}" for g in ARMOR_GAPS))
    sp = [e["vx"] for e in _armor_x(out["armor_tap4_8"]) if e["step"] == 0x14]
    no = {g: sorted({s for _, s in _armor_steps(out[f"armor_tap{g}_0"])}) for g in (1, 4, 11)}
    check("legs: the double-tap dash runs at $375; without the legs the same taps only walk",
          sp and abs(sp[-1]) == 0x375 and all(0x14 not in s for s in no.values()),
          f"dash vx {sp[-1] if sp else None}; steps without legs {({g: [hex(x) for x in s] for g, s in no.items()})}")
    lt = {up: next((e for e in _armor_x(out[f"armor_tapL_{up}"]) if e["step"] == 0x14), None) for up in (0, 8)}
    check("legs: a Left double tap dashes left (none without the legs)",
          lt[8] and lt[8]["f"] == 65 and lt[0] is None,
          f"legs: step $14 at f{lt[8] and lt[8]['f']}; no legs: {lt[0]}")

    # --- arm ($02): charging special weapons ------------------------------------------------------------------
    s = {}
    for up in (0, 2):
        ev = out[f"armor_sting_{up}"]
        s[up] = (sorted({(e["charge"], e["lvl"]) for e in _armor_x(ev)}), sorted({e["id"] for e in _armor_tags(ev, "ashot")}))
    check("arm (upgrades $02): Chameleon Sting held 200 frames: no charge without the arm (shot 8 only); with it the "
          "charge reaches level 1 and the release fires the charged Sting (shot $11)",
          s[0][0] == [(0, 0)] and s[0][1] == [8] and (4, 1) in s[2][0] and 0x11 in s[2][1],
          f"(charge_state, level) seen / shot ids: no arm {s[0]}; arm {s[2]}")

    # --- helmet ($01): headbutt, falling rocks, gfx --------------------------------------------------------------
    hb = {up: out[f"armor_headbutt_{up}"] for up in (0, 1)}
    t1, snd1, _ = _armor_breaks(hb[1])
    t0, _, n0 = _armor_breaks(hb[0])
    calls = {up: len(_armor_tags(hb[up], "headbutt")) for up in (0, 1)}
    check("helmet (upgrades $01): jumping into Storm Eagle's $3C block breaks it (tile +1, sound $23); without it X "
          "hits the same ceiling and nothing breaks",
          t1 and snd1 and len(_armor_tags(hb[1], "helmet_br")) > 0 and calls[0] > 0 and not t0 and n0 == 0,
          f"helmet: {len(_armor_tags(hb[1], 'tile_inc'))} tile changes in frames {t1[:6]}, sound $23 each: {snd1}; "
          f"no helmet: {calls[0]} ceiling hits, {len(t0)} tile changes, {n0} sounds $23")
    j = {up: [b - a for (a, s), (b, _) in zip(_armor_steps(hb[up]), _armor_steps(hb[up])[1:]) if s == 6][:3]
         for up in (0, 1)}
    check("helmet: X keeps rising through the broken block (jump step lasts longer than the 4 frames to the ceiling)",
          j[0] and all(n <= 5 for n in j[0]) and j[1] and j[1][0] > 10,
          f"jump-step lengths: no helmet {j[0]}, helmet {j[1]}")
    g = {up: sorted({e["gfx"] for e in _armor_x(hb[up]) if e["f"] > 455 and e["step"] == 0}) for up in (0, 1)}
    check("helmet: X's own sprite set ($0BBE) is $18 with the helmet, 0 without", g[1] == [0x18] and g[0] == [0],
          f"$0BBE standing: no helmet {g[0]}, helmet {g[1]}")
    rk = {}
    for up in (0, 1):
        ev = out[f"armor_rock_{up}"]
        hit = _armor_tags(ev, "rock_hit")
        xs = _armor_x(ev)
        f = hit[0]["f"] if hit else None
        after = [e for e in xs if f is not None and f < e["f"] <= f + 20]
        rk[up] = (f, len(_armor_tags(ev, "rock_dmg")), xs[-1]["hp"] if xs else None,
                  any(e["step"] == 0x0E for e in after))
    check("helmet: a falling rock (enemy $18, Chameleon's cave) hitting X from above does nothing with the helmet; "
          "without it 1 damage and knockback (step $0E)",
          rk[0][0] and rk[0][1] == 1 and rk[0][2] == 15 and rk[0][3]
          and rk[1][0] and rk[1][1] == 0 and rk[1][2] == 16 and not rk[1][3],
          f"(hit frame, damage calls, final HP, knocked back): no helmet {rk[0]}, helmet {rk[1]}")

    # --- legs ($08): wall kicks break $3C walls --------------------------------------------------------------------
    w = {}
    for up in (0, 1, 8):
        ev = out[f"armor_wall_{up}"]
        tl, snd, _ = _armor_breaks(ev)
        w[up] = (len(_armor_tags(ev, "wallbrk")), len(_armor_tags(ev, "legs_br")), len(tl), snd)
    check("legs: kicking off Sting Chameleon's $3C wall (x 1392) breaks it (tile +1, sound $23); not with no armor "
          "or with the helmet alone",
          w[8][1] > 0 and w[8][2] > 0 and w[8][3] and w[0][0] > 0 and w[0][2] == 0 and w[1][0] > 0 and w[1][2] == 0,
          f"($3C-wall kicks, legs branch, tile changes, sound $23 each): legs {w[8]}, none {w[0]}, helmet {w[1]}")


# ====================================================================================================================
# Sub tanks, heart tanks, life energy
#
# Section 'tanks' of verify_upgrades.py: sub tanks, heart tanks, life energy -> sub tanks, sub tank use.
#
# Sub tank = $1628-list object 5 ($81:E4BB), heart tank = object $0B ($81:E992), life energy = object 2 ($82:E342);
# sub tank use = pause menu ($80:C6C6 start, $80:C723 tick, $80:CDA1 slot compaction).
# X lands on each item after the stage starts (touch ~f430-f512). Pokes of $1F99 / $1F9C go after the new-game init
# (f151 zeroes them) and before the item's state 0 runs (~f426).
# ====================================================================================================================

TANKS_HEART_ARM = (3, 0x04CA, 0x0937)    # Armadillo heart, sub-id $02
TANKS_HEART_PEN = (8, 0x148C, 0x02B4)    # Chill Penguin heart, $01
TANKS_HEART_EAGLE = (5, 0x0020, 0x0570)  # Storm Eagle heart, $04
TANKS_HEART_MAM = (4, 0x0FB8, 0x03D7)    # Flame Mammoth heart, $10
TANKS_SUB_MAM = (4, 0x0B3A, None)        # Flame Mammoth sub tank, $80
TANKS_LIFE_MAM = (4, 0x0870, None)       # Flame Mammoth placed (large) life energy, $0B = $80

TANKS_STATE = ('out("st", string.format("hp=%d max=%d hearts=%d upg=%d t0=%d t1=%d t2=%d t3=%d frz=%d f19=%d '
               'p0=%d p1=%d p6=%d", r8(0x0BCF) & 0x7F, r8(0x1F9A), r8(0x1F9C), r8(0x1F99), r8(0x1F83), r8(0x1F84), '
               'r8(0x1F85), r8(0x1F86), r8(0x1F13) + 2*r8(0x1F14) + 4*r8(0x1F15) + 8*r8(0x1F16) + 16*r8(0x1F17) + '
               '32*r8(0x1F18), r8(0x1F19), r8(0x0703), r8(0x0707), r8(0x071B)))')


def _tanks_run(where, frames, pokes=(), obj=None, small=False):
    r = Run(*where, frames=frames)
    for f, a, v in pokes:
        r.poke(f, a, v)
    r.each_frame(f"if frame >= 400 then {TANKS_STATE} end")
    if obj is not None:
        r.track(obj, "misc", "item")
    # sound requests ($80:88CD, A = id)
    r.at_exec(0x8088CD, 'out("snd", string.format("a=%d", s["cpu.a"] & 0xFF))')
    if small:   # life energy init: make it the other kind ($0B & $7F != 0)
        r.at_exec(0x82E34E, 'w8(s["cpu.d"] + 0x0B, 0x81)')
    return r


def _tanks_menu(tanks, hp, button="y", frames=705):
    pk = [(200, 0x1F99, 0x80)] + [(420, 0x1F83 + i, v) for i, v in enumerate(tanks)] + [(420, 0x0BCF, 0x80 | hp)]
    r = _tanks_run(TANKS_SUB_MAM, frames, pk)      # the Mammoth sub tank is pre-owned: it deletes itself
    r.input("if frame >= 480 and frame < 484 then return {start = true} end\n"
            "if frame >= 540 and frame < 544 then return {down = true} end\n"
            f"if frame >= 640 and frame < 644 then return {{{button} = true}} end\nreturn {{}}")
    r.on_exec(0x80C6E1, "use_start")    # X = X_hp - 10 here
    r.at_exec(0x80C6F8, 'out("use_step", string.format("step=%d cursor=%d", '
                        'emu.read(s["cpu.d"] + 0x11, emu.memType.snesMemory), emu.read(s["cpu.d"] + 0x0A, emu.memType.snesMemory)))')
    r.at_exec(0x80C754, 'out("tank_dec", string.format("x=%d", s["cpu.x"] & 0xFF))')
    return r


def runs_tanks():
    R = {}
    # hearts
    R["tanks_heart_arm"] = _tanks_run(TANKS_HEART_ARM, 530, obj=0x0B)
    R["tanks_heart_pen"] = _tanks_run(TANKS_HEART_PEN, 535, obj=0x0B)
    R["tanks_heart_eagle"] = _tanks_run(TANKS_HEART_EAGLE, 610, obj=0x0B)
    R["tanks_heart_mam"] = _tanks_run(TANKS_HEART_MAM, 530, obj=0x0B)
    R["tanks_heart_owned"] = _tanks_run(TANKS_HEART_ARM, 450, [(200, 0x1F9C, 0x02)], obj=0x0B)
    R["tanks_heart_other"] = _tanks_run(TANKS_HEART_ARM, 450, [(200, 0x1F9C, 0xFD)], obj=0x0B)
    R["tanks_heart_hp10"] = _tanks_run(TANKS_HEART_ARM, 530, [(420, 0x0BCF, 0x8A)], obj=0x0B)
    R["tanks_heart_max1f"] = _tanks_run(TANKS_HEART_ARM, 525, [(420, 0x1F9A, 0x1F), (420, 0x0BCF, 0x9F)], obj=0x0B)
    R["tanks_heart_max20"] = _tanks_run(TANKS_HEART_ARM, 445, [(420, 0x1F9A, 0x20), (420, 0x0BCF, 0xA0)], obj=0x0B)
    # sub tanks
    R["tanks_sub"] = _tanks_run(TANKS_SUB_MAM, 525, obj=5)
    R["tanks_sub_owned"] = _tanks_run(TANKS_SUB_MAM, 450, [(200, 0x1F99, 0x80)], obj=5)
    R["tanks_sub_other"] = _tanks_run(TANKS_SUB_MAM, 450, [(200, 0x1F99, 0x7F)], obj=5)
    R["tanks_sub_slot0"] = _tanks_run(TANKS_SUB_MAM, 450, [(420, 0x1F83, 0x85)], obj=5)
    R["tanks_sub_all"] = _tanks_run(TANKS_SUB_MAM, 450, [(420, a, 0x80) for a in range(0x1F83, 0x1F87)], obj=5)
    # life energy (X at full HP unless poked)
    for name, pk, small, frames in [
            ("t0", [(420, 0x1F83, 0x80)], False, 470),
            ("t0_small", [(420, 0x1F83, 0x80)], True, 470),
            ("t0_8d", [(420, 0x1F83, 0x8D)], False, 470),
            ("t0full_t1", [(420, 0x1F83, 0x8E), (420, 0x1F84, 0x80)], False, 470),
            ("t0none_t1", [(420, 0x1F83, 0x00), (420, 0x1F84, 0x85)], False, 470),
            ("t0full_only", [(420, 0x1F83, 0x8E)], False, 470),
            ("hp4", [(420, 0x1F83, 0x80), (420, 0x0BCF, 0x84)], False, 495),
            ("hp12", [(420, 0x1F83, 0x80), (420, 0x0BCF, 0x8C)], False, 480),
            ("hp10_small", [(420, 0x1F83, 0x80), (420, 0x0BCF, 0x8A)], True, 475),
            ("hp15_small", [(420, 0x1F83, 0x80), (420, 0x0BCF, 0x8F)], True, 470)]:
        R[f"tanks_fill_{name}"] = _tanks_run(TANKS_LIFE_MAM, frames, pk, obj=2, small=small)
    # sub tank use (Start f480, Down f540, button f640)
    R["tanks_menu_full_hp10"] = _tanks_menu([0x8E], 10)
    R["tanks_menu_full_hp11"] = _tanks_menu([0x8E], 11)
    R["tanks_menu_full_hp11_t1full"] = _tanks_menu([0x8E, 0x8E], 11)
    R["tanks_menu_part_hp10"] = _tanks_menu([0x85], 10, frames=670)
    R["tanks_menu_full_hp14"] = _tanks_menu([0x8E], 14)
    R["tanks_menu_hpfull"] = _tanks_menu([0x8E], 16, frames=680)
    R["tanks_menu_b"] = _tanks_menu([0x8E], 10, button="b", frames=680)
    return R


# ---- helpers ---------------------------------------------------------------------------------------------------
def _tanks_st(ev):
    return {e["f"]: e for e in ev if e["tag"] == "st"}


def _tanks_changes(ev, key, lo=400):
    """[(frame, value)] whenever st[key] changes (first record included)."""
    out, last = [], None
    for e in ev:
        if e["tag"] == "st" and e["f"] >= lo and e[key] != last:
            out.append((e["f"], e[key]))
            last = e[key]
    return out


def _tanks_item(ev):
    """[(frame, (state, step, sub) or None)] at each change of the tracked item."""
    out = []
    for e in ev:
        if e["tag"] != "item":
            continue
        k = None if e.get("state") is None else (e["state"], e["step"], e["sub"])
        if not out or out[-1][1] != k:
            out.append((e["f"], k))
    return out


def _tanks_first(items, key):
    return next((f for f, k in items if k == key), None)


def _tanks_sounds(ev, lo=400):
    return [(e["f"], e["a"]) for e in ev if e["tag"] == "snd" and e["f"] >= lo]


def _tanks_last(ev):
    return max((e for e in ev if e["tag"] == "st"), key=lambda e: e["f"])


def _tanks_h(v):
    return f"${v:02X}"


def checks_tanks(out, check):
    # ======== sub tank ========
    ev = out["tanks_sub"]
    it = _tanks_item(ev)
    s = _tanks_st(ev)
    got = _tanks_first(it, (2, 6, 2))
    wait_end = _tanks_first(it, (2, 6, 4))
    fin = s[got]
    snd = [f for f, a in _tanks_sounds(ev) if a == 0x29]
    check("sub tank: touch -> first free slot $1F83 = $80 (owned, empty), sub-id $80 into $1F99, all six freeze "
          "flags $1F13-$1F18 = 1, sound $29",
          s[got - 1]["t0"] == 0 and fin["t0"] == 0x80 and fin["upg"] == 0x80 and fin["frz"] == 63 and snd,
          f"f{got}: $1F83 {_tanks_h(s[got - 1]['t0'])}->{_tanks_h(fin['t0'])}, $1F99 = {_tanks_h(fin['upg'])}, "
          f"freeze bits {fin['frz']:06b}, sound $29 at f{snd}")
    unfrz = next(f for f in sorted(s) if f > got and s[f]["frz"] == 0)
    gone = _tanks_first(it, None)
    check("sub tank: freeze 80 frames ($27 = $50), then unfreeze and delete",
          wait_end - got == 80 and unfrz == wait_end + 1 and gone and gone > wait_end,
          f"wait step f{got}..f{wait_end - 1} ({wait_end - got} frames), freeze cleared f{unfrz}, deleted f{gone}")

    ev = out["tanks_sub_owned"]
    it = _tanks_item(ev)
    last = _tanks_last(ev)
    check("sub tank: state 0 deletes it if its own bit is already in $1F99",
          it[0][1] == (0, 0, 0) and it[1][1] is None and not any(k and k[0] == 2 for _, k in it)
          and last["t0"] == 0 and last["frz"] == 0,
          f"$1F99 = $80 at f200: item f{it[0][0]} state 0, gone f{it[1][0]}; $1F83 stays {_tanks_h(last['t0'])}")
    ev = out["tanks_sub_other"]
    last = _tanks_last(ev)
    check("sub tank: only its own bit counts ($1F99 = $7F -> still collected)",
          last["upg"] == 0xFF and last["t0"] == 0x80, f"$1F99 -> {_tanks_h(last['upg'])}, $1F83 = {_tanks_h(last['t0'])}")
    ev = out["tanks_sub_slot0"]
    last = _tanks_last(ev)
    check("sub tank: slot 0 already owned -> next slot $1F84 = $80",
          last["t0"] == 0x85 and last["t1"] == 0x80 and last["upg"] == 0x80,
          f"$1F83 = {_tanks_h(last['t0'])}, $1F84 = {_tanks_h(last['t1'])}, $1F99 = {_tanks_h(last['upg'])}")
    ev = out["tanks_sub_all"]
    it = _tanks_item(ev)
    last = _tanks_last(ev)
    touched = _tanks_first(it, (2, 6, 0))
    frz = any(e["frz"] for e in ev if e["tag"] == "st" and e["f"] > 425)
    check("sub tank: all 4 slots owned -> deleted (state 4) without its bit, no freeze",
          touched and _tanks_first(it, (4, 6, 0)) == touched + 1 and last["upg"] == 0 and not frz
          and [last[f"t{i}"] for i in range(4)] == [0x80] * 4,
          f"touch f{touched}, state 4 f{_tanks_first(it, (4, 6, 0))}, gone f{_tanks_first(it, None)}; "
          f"$1F99 = {_tanks_h(last['upg'])}, slots {[_tanks_h(last[f't{i}']) for i in range(4)]}, freeze seen: {frz}")

    # ======== life energy -> tanks ========
    def fill(name):
        ev = out[f"tanks_fill_{name}"]
        before = _tanks_st(ev)[425]
        last = _tanks_last(ev)
        return ev, before, last

    ev, b, l = fill("t0")
    ev2, b2, l2 = fill("t0_small")
    check("life energy at full HP: large ($0B & $7F = 0) +2 units, small +1 unit into the tank",
          b["t0"] == 0x80 and l["t0"] == 0x82 and l2["t0"] == 0x81 and l["hp"] == l2["hp"] == 16,
          f"large $80->{_tanks_h(l['t0'])}, small ($0B forced $81) $80->{_tanks_h(l2['t0'])}, HP stays {l['hp']}")
    ev, b, l = fill("t0_8d")
    snd = [f for f, a in _tanks_sounds(ev) if a == 0x2B]
    check("life energy: tank capped at $8E (14 units, no spill: $8D + large = $8E), sound $2B when it becomes full",
          l["t0"] == 0x8E and l["t1"] == 0 and snd, f"$8D -> {_tanks_h(l['t0'])}, $1F84 = {_tanks_h(l['t1'])}, $2B at f{snd}")
    ev, b, l = fill("t0full_t1")
    ev2, b2, l2 = fill("t0none_t1")
    ev3, b3, l3 = fill("t0full_only")
    nfill = [(e["f"], e["t0"]) for e in ev3 if e["tag"] == "st" and e["t0"] != 0x8E and e["f"] >= 420]
    check("life energy: fills only the first owned (bit 7) non-full slot, in order 0..3",
          l["t0"] == 0x8E and l["t1"] == 0x82 and l2["t0"] == 0 and l2["t1"] == 0x87 and l3["t0"] == 0x8E
          and l3["t1"] == 0 and not nfill,
          f"($8E,$80) -> ({_tanks_h(l['t0'])},{_tanks_h(l['t1'])}); unowned slot 0 ($00,$85) -> "
          f"({_tanks_h(l2['t0'])},{_tanks_h(l2['t1'])}); only a full tank ($8E,$00) -> ({_tanks_h(l3['t0'])},{_tanks_h(l3['t1'])})")

    ev, b, l = fill("hp4")
    hp = _tanks_changes(ev, "hp", 425)
    steps = [f for f, _ in hp[1:]]
    snd = [f for f, a in _tanks_sounds(ev) if a == 0x0C]
    frz = [(f, v) for f, v in _tanks_changes(ev, "f19", 425)]
    check("life energy below full HP: large +8 HP, +1 every 4 frames (sound $0C), objects frozen ($1F13-$1F19)",
          [v for _, v in hp] == list(range(4, 13)) and all(b - a == 4 for a, b in zip(steps, steps[1:]))
          and len(snd) == 8 and len(frz) == 3 and l["t0"] == 0x80,
          f"HP {hp[0][1]}->{hp[-1][1]} at f{steps}; $1F19 {frz}; tank stays {_tanks_h(l['t0'])}")
    ev, b, l = fill("hp10_small")
    hp = _tanks_changes(ev, "hp", 425)
    check("life energy: small +2 HP", [v for _, v in hp] == [10, 11, 12] and l["t0"] == 0x80, f"HP {hp}")
    ev, b, l = fill("hp12")
    ev2, b2, l2 = fill("hp15_small")
    hp = _tanks_changes(ev, "hp", 425)
    check("life energy: HP stops at max, the rest is lost (not put into a tank)",
          l["hp"] == 16 and l["t0"] == 0x80 and l2["hp"] == 16 and l2["t0"] == 0x80,
          f"large at HP 12: {hp}, tank {_tanks_h(l['t0'])}; small at HP 15: -> {l2['hp']}, tank {_tanks_h(l2['t0'])}")

    # ======== sub tank use (pause menu) ========
    def menu(name):
        ev = out[f"tanks_menu_{name}"]
        hp = _tanks_changes(ev, "hp", 630)
        t0 = _tanks_changes(ev, "t0", 630)
        step = [e for e in ev if e["tag"] == "use_step"]
        dec = [e["f"] for e in ev if e["tag"] == "tank_dec"]
        return ev, hp, t0, step, dec

    ev, hp, t0, step, dec = menu("part_hp10")
    check("menu: Start, Down, Y uses tank 0 (cursor $0A); +1 HP and -1 unit every 4 frames (tank $85, HP 10)",
          step and step[0]["cursor"] == 0x0A and step[0]["step"] == 1 and [v for _, v in hp] == list(range(10, 16))
          and [v for _, v in t0] == list(range(0x85, 0x7F, -1)) and all(b - a == 4 for a, b in zip(dec, dec[1:])),
          f"start f{step[0]['f'] if step else None} cursor {step[0]['cursor'] if step else None}; HP {[v for _, v in hp]}; "
          f"tank {[_tanks_h(v) for _, v in t0]}; ticks f{dec}")
    ev, hp, t0, step, dec = menu("hpfull")
    ev2, hp2, t02, step2, dec2 = menu("b")
    check("menu: nothing at full HP; B does nothing",
          not step and not dec and _tanks_last(ev)["t0"] == 0x8E and not step2 and _tanks_last(ev2)["t0"] == 0x8E,
          f"HP 16: tank {_tanks_h(_tanks_last(ev)['t0'])}, no use; B at HP 10: tank {_tanks_h(_tanks_last(ev2)['t0'])}, HP {_tanks_last(ev2)['hp']}")
    ev, hp, t0, step, dec = menu("full_hp14")
    full = hp[-1][0]
    after = [f for f, v in t0 if f > full]
    check("menu: the tank drains to $80 even after HP is full (excess wasted)",
          hp[-1][1] == 16 and t0[-1][1] == 0x80 and len(after) > 10 and len(dec) == 14,
          f"HP {[v for _, v in hp]} full at f{full}; tank keeps draining until {_tanks_h(t0[-1][1])} at f{t0[-1][0]} "
          f"({len(dec)} ticks)")
    ev, hp, t0, step, dec = menu("full_hp10")
    ev2, hp2, t02, step2, dec2 = menu("full_hp11")
    ev3, hp3, t03, step3, dec3 = menu("full_hp11_t1full")
    use = [e for e in ev3 if e["tag"] == "use_start"]
    check("menu (game bug): the +2-HP-a-tick check for a full tank reads slot X_hp-10, not the cursor's slot",
          step[0]["step"] == 2 and [v for _, v in hp] == [10, 12, 14, 16]
          and step2[0]["step"] == 1 and [v for _, v in hp2] == list(range(11, 17))
          and step3[0]["step"] == 2 and step3[0]["cursor"] == 0x0A and use and use[0]["x"] == 1
          and [v for _, v in hp3] == [11, 13, 15, 16],
          f"tank 0 $8E: HP 10 (index 0) step {step[0]['step']} HP {[v for _, v in hp]}; HP 11 (index 1, $1F84 = 0) "
          f"step {step2[0]['step']} HP {[v for _, v in hp2]}; HP 11 with $1F84 = $8E: X = {use[0]['x'] if use else None}, "
          f"step {step3[0]['step']}, cursor {_tanks_h(step3[0]['cursor'])}, HP {[v for _, v in hp3]}")
    l3 = _tanks_last(ev3)
    check("menu: an emptied tank is moved behind the remaining owned non-empty ones ($80:CDA1)",
          l3["t0"] == 0x8E and l3["t1"] == 0x80 and len(dec3) == 14,
          f"($8E,$8E), tank 0 used up after {len(dec3)} ticks -> ($1F83,$1F84) = ({_tanks_h(l3['t0'])},{_tanks_h(l3['t1'])})")

    # ======== heart tank ========
    for name, bit, lv in (("arm", 0x02, "Armadillo"), ("pen", 0x01, "Chill Penguin"), ("eagle", 0x04, "Storm Eagle"),
                          ("mam", 0x10, "Flame Mammoth")):
        ev = out[f"tanks_heart_{name}"]
        it = _tanks_item(ev)
        s = _tanks_st(ev)
        got = _tanks_first(it, (2, 6, 2))
        raise_ = _tanks_first(it, (2, 6, 4))
        done = _tanks_first(it, (2, 6, 6))
        # up to the end of the raise step (at Mammoth an enemy hits X a few frames after the unfreeze)
        mx = [(f, v) for f, v in _tanks_changes(ev, "max", 400)][1:]
        hpc = [(f, v) for f, v in _tanks_changes(ev, "hp", 400)[1:] if done and f <= done]
        flash = [f for f in sorted(s) if s[f]["p0"] == 0x30]
        pal_ok = all(s[f]["p0"] == s[f]["p1"] == s[f]["p6"] for f in s)
        snd29 = [f for f, a in _tanks_sounds(ev) if a == 0x29]
        snd0c = [f for f, a in _tanks_sounds(ev) if a == 0x0C]
        rel = [f - raise_ for f, _ in mx] if raise_ else []
        ok = (got and s[got]["hearts"] == bit and s[got]["frz"] == 63 and raise_ - got == 80 and done - raise_ == 8
              and [v for _, v in mx] == [17, 18] and hpc == mx and rel == [4, 8]
              and flash == [raise_ + 1, raise_ + 3, raise_ + 5, raise_ + 7] and pal_ok
              and all(s[f]["p0"] == 0x34 for f in s if f > done) and s[done + 1]["frz"] == 0
              and snd29 and len(snd0c) == 2)
        check(f"heart ({lv}, ${bit:02X}): bit into $1F9C, freeze 80 frames (sound $29), then 8 frames of palette "
              f"flash ($0703+4k ^= 4) with max HP +1 and HP +1 every 4 frames, 2 times (sound $0C), then unfreeze",
              ok, f"touch f{got} $1F9C = {_tanks_h(s[got]['hearts']) if got else None}; wait f{got}..f{raise_ - 1 if raise_ else None}; "
              f"max {mx}, HP {hpc} ({rel} frames into the raise step); $0703 = $30 at f{flash}, $34 otherwise; "
              f"unfreeze f{done + 1 if done else None}")

    ev = out["tanks_heart_owned"]
    it = _tanks_item(ev)
    last = _tanks_last(ev)
    check("heart: state 0 deletes it if its own bit is already in $1F9C",
          it[0][1] == (0, 0, 0) and it[1][1] is None and last["max"] == 16 and last["frz"] == 0,
          f"$1F9C = $02 at f200: state 0 f{it[0][0]}, gone f{it[1][0]}; max stays {last['max']}")
    last = _tanks_last(out["tanks_heart_other"])
    check("heart: only its own bit counts ($1F9C = $FD -> collected)", last["hearts"] == 0xFF and last["max"] == 16,
          f"$1F9C -> {_tanks_h(last['hearts'])} (max {last['max']} at f{last['f']}, still in the wait)")
    ev = out["tanks_heart_hp10"]
    mx = _tanks_changes(ev, "max", 425)
    hp = _tanks_changes(ev, "hp", 425)
    check("heart: HP is not refilled when not full, just +1 per step", [v for _, v in hp] == [10, 11, 12]
          and [v for _, v in mx] == [16, 17, 18], f"HP {hp}, max {mx}")
    ev = out["tanks_heart_max1f"]
    it = _tanks_item(ev)
    mx = _tanks_changes(ev, "max", 425)
    hp = _tanks_changes(ev, "hp", 425)
    r4, r6 = _tanks_first(it, (2, 6, 4)), _tanks_first(it, (2, 6, 6))
    check("heart: max $1F -> one step to $20, then it ends (cap $20)",
          [v for _, v in mx] == [0x1F, 0x20] and [v for _, v in hp] == [0x1F, 0x20] and r6 - r4 == 4,
          f"max {mx}, HP {hp}; raise step f{r4}..f{r6 - 1} ({r6 - r4} frames instead of 8)")
    ev = out["tanks_heart_max20"]
    it = _tanks_item(ev)
    last = _tanks_last(ev)
    frz = any(e["frz"] for e in ev if e["tag"] == "st" and e["f"] > 425)
    t = _tanks_first(it, (2, 2, 1))
    check("heart: max already $20 -> bit still set first, nothing else (no freeze), deleted",
          last["hearts"] == 0x02 and last["max"] == 0x20 and last["hp"] == 0x20 and not frz
          and _tanks_first(it, (4, 6, 0)) and _tanks_first(it, None),
          f"$1F9C = {_tanks_h(last['hearts'])}, max {_tanks_h(last['max'])}, freeze seen: {frz}; state 4 "
          f"f{_tanks_first(it, (4, 6, 0))}, gone f{_tanks_first(it, None)}")


# ====================================================================================================================
# Dr. Light capsules
#
# Section 'capsule': Dr. Light capsules (enemy $4D, $87:CA7B), the part light $4E ($87:D012), Dr. Light $5C and
# Sting Chameleon's hidden-area trigger ($1D08-list id $1D, $87:FB40).
# ====================================================================================================================

CAPSULE_G = MMX1(str(params.STOCK_ROM))


def _capsule_b(addr, n=1):
    p = snes2pc(addr)
    return list(CAPSULE_G.rom[p:p + n])


def _capsule_w(addr):
    lo, hi = _capsule_b(addr, 2)
    return lo | hi << 8


# walk toward the capsule (cx); press B every 8 frames while the text box is up ($1F3C); hands off while X is frozen
# (steps $1E/$38) or once the capsule has him (substate >= 8); jump toward it once Dr. Light is gone (it is solid)
CAPSULE_WALK = r"""
local cap = find(0x0E68, 0x1228, 0x4D)
local st = r8(0x0BAA)
if r8(0x1F3C) ~= 0 then return {b = frame % 8 == 0} end
if st == 0x1E or st == 0x38 then return {} end
if cap and r8(cap + 2) >= 8 then return {} end
local cx = CX
local x = r16(0x0BAD)
EXTRA
local jump = (find(0x0E68, 0x1228, 0x5C) == nil) and cap ~= nil and r8(cap + 2) == 6 and frame % 50 < 25
if x < cx - 2 then return {right = true, b = jump} elseif x > cx + 2 then return {left = true, b = jump} end
return {b = jump}
"""
# Chameleon: keep 64 px left of the capsule until it has risen (else it lifts X onto its roof); shoot enemy 9
CAPSULE_CHAM_EXTRA = """if not cap or r8(cap + 2) < 2 then cx = cx - 64 end
local e = find(0x0E68, 0x1228, 9)
if e then local ex = r16(e + 5); return {right = ex > x + 8 and frame % 40 == 0, left = ex < x - 8 and frame % 40 == 0, y = frame % 8 < 4} end"""
# test aid: enemy 9 has ~64 HP and the buster rarely hits it; hold its HP at 1 so one hit kills it (normal death path)
CAPSULE_HP1 = "do local e = find(0x0E68, 0x1228, 9); if e and (r8(e + 0x27) & 0x7F) > 1 then w8(e + 0x27, 1) end end"

CAPSULE_LOGS = [
    'local st = r8(0x0BAA) if st ~= _xs then out("xs", "step=" .. st .. " x=" .. r16(0x0BAD) .. " y=" .. r16(0x0BB0)); _xs = st end',
    'local p = r16(0x00A7) if p ~= _pad then out("pad", "held=" .. p .. " new=" .. r16(0x00AB)); _pad = p end',
    'local v = r8(0x1F48) * 256 + r8(0x0BD8) if v ~= _ram then out("ram", "f48=" .. r8(0x1F48) .. " hurt=" .. r8(0x0BD8)); _ram = v end',
    'local v = r16(0x1E5E) .. "," .. r16(0x1E60) .. "," .. r16(0x1E68) .. "," .. r16(0x1E6E) if v ~= _lock then '
    'out("lock", "x1=" .. r16(0x1E5E) .. " x2=" .. r16(0x1E60) .. " y1=" .. r16(0x1E68) .. " y2=" .. r16(0x1E6E)); _lock = v end',
]
CAPSULE_CHAM_LOGS = [
    'for a = 0x1D08, 0x1DF8, 0x10 do if r8(a) ~= 0 and r8(a + 10) == 0x1D then local k = r8(a + 1) '
    'if k ~= _o1d then out("o1D", "slot=" .. a .. " state=" .. k .. " x=" .. r16(a + 5) .. " y=" .. r16(a + 8)); _o1d = k end end end',
    'local n = 0 for a = 0x1628, 0x18F8, 0x30 do if r8(a) ~= 0 and r8(a + 10) == 0x11 then n = n + 1 end end '
    'if n ~= (_n11 or 0) then out("m11", "n=" .. n); _n11 = n end',
]
CAPSULE_HOOKS = {
    0x87D0B2: 'out("grant", "mask=" .. (s["cpu.a"] & 0xFF) .. " idx=" .. (s["cpu.x"] & 0xFF) .. " anim=" .. r8(s["cpu.d"] + 3))',
    0x87CECD: 'out("spawn4E", "a=" .. (s["cpu.a"] & 0xFF) .. " t33=" .. r8(s["cpu.d"] + 0x33))',
    0x83F74A: 'out("text", "id=" .. r8(0x0008))',
    0x87FC6A: 'out("brk", "x=" .. r16(s["cpu.d"] + 5) .. " y=" .. r16(s["cpu.d"] + 8))',
    0x828398: 'out("despawn", "d=" .. s["cpu.d"])',
}

# (level, x, y, capsule x) per capsule
CAPSULE_LEVELS = {"eagle": 5, "mammoth": 4, "chameleon": 2, "penguin": 8, "armadillo": 3}
CAPSULE_PART = {"eagle": "helmet $01", "mammoth": "arm $02", "chameleon": "body $04", "penguin": "legs $08",
                "armadillo": "Hadouken ($1F7E |= $80)"}
CAPSULE_HADOUKEN_POKES = [(200, 0x1F9A, 0x20), (200, 0x1F99, 0xFF), (200, 0x1F9C, 0xFF), (200, 0x1F7C, 0x40),
                          (200, 0x1F7E, 0x04)]


def _capsule_run(level, x, y, cx, frames, pokes=(), cham=False):
    r = Run(level, x=x, y=y, frames=frames, infinite_hp=True)
    r.input(CAPSULE_WALK.replace("CX", str(cx)).replace("EXTRA", CAPSULE_CHAM_EXTRA if cham else ""))
    r.track(0x4D, tag="cap").track(0x4E, tag="orb").track(0x5C, tag="light")
    for a in (0x1F99, 0x1F7E, 0x0C38, 0x0C58, 0x0C78, 0x0BBE):
        r.on_write(a, f"w{a:04X}")
    for a, lua in CAPSULE_HOOKS.items():
        r.at_exec(a, lua)
    for lua in CAPSULE_LOGS:
        r.each_frame(lua)
    if cham:
        r.track(0x09, tag="e09").each_frame(CAPSULE_HP1)
        for lua in CAPSULE_CHAM_LOGS:
            r.each_frame(lua)
    for f, a, v in pokes:
        r.poke(f, a, v)
    return r


def runs_capsule():
    hp = [(200, 0x0BCF, 0x20)]
    return {
        "capsule_eagle": _capsule_run(5, 0x0F60, 0x0280, 0x0FC8, 2100),
        "capsule_mammoth": _capsule_run(4, 0x0930, 0x0260, 0x093B, 2300),
        "capsule_penguin": _capsule_run(8, 0x09A0, 0x0240, 0x09E0, 4100),
        "capsule_armadillo": _capsule_run(3, 0x12C0, 0x0900, 0x12EC, 1700, CAPSULE_HADOUKEN_POKES + hp),
        "capsule_chameleon": _capsule_run(2, 0x05D0, 0x0180, 0x06D8, 3100, cham=True),
        "capsule_armadillo_lowhp": _capsule_run(3, 0x12C0, 0x0900, 0x12EC, 520,
                                                CAPSULE_HADOUKEN_POKES + [(200, 0x0BCF, 0x1F)]),
        "capsule_eagle_owned": _capsule_run(5, 0x0F60, 0x0280, 0x0FC8, 520, [(200, 0x1F99, 0x01)]),
        "capsule_chameleon_owned": _capsule_run(2, 0x05D0, 0x0180, 0x06D8, 1900, [(200, 0x1F99, 0x04)], cham=True),
    }


def _capsule_tag(ev, tag):
    return [e for e in ev if e["tag"] == tag]


def _capsule_changes(ev, tag, keys=("state", "step", "sub")):
    """First record of each (state, substate, sub2) of a tracked object, plus 'gone'."""
    out, last = [], None
    for e in ev:
        if e["tag"] != tag:
            continue
        k = tuple(e.get(n) for n in keys) if "state" in e else "gone"
        if k != last:
            out.append((e["f"], k, e))
            last = k
    return out


def _capsule_scene(ev):
    """{sub2: first frame} of the capsule's substate 8, and its per-frame records."""
    recs = [e for e in _capsule_tag(ev, "cap") if "state" in e]
    f = {}
    for e in recs:
        if e["state"] == 2 and e["step"] == 8 and e["sub"] not in f:
            f[e["sub"]] = e["f"]
    return f, recs


def _capsule_value_at(ev, tag, key, frame):
    v = None
    for e in _capsule_tag(ev, tag):
        if e["f"] > frame:
            break
        v = e[key]
    return v


def _capsule_script(level):
    off = _capsule_b(0x86D36B + level)[0]
    pairs, i = [], 0x86D36B + off
    while _capsule_b(i)[0] != 0xFF:
        pairs.append(tuple(_capsule_b(i, 2)))
        i += 2
    return pairs


def checks_capsule(out, check):
    D362 = _capsule_b(0x86D362, 13)
    D3D5 = _capsule_b(0x86D3D5, 4)
    D4E3 = _capsule_b(0x86D4E3, 13)

    for name, level in CAPSULE_LEVELS.items():
        ev = out[f"capsule_{name}"]
        part = CAPSULE_PART[name]
        idx = D362[level]
        tx, ty = _capsule_w(0x86D33E + 4 * level), _capsule_w(0x86D340 + 4 * level)
        lx, ly = _capsule_w(0x86D3A1 + 4 * level), _capsule_w(0x86D3A3 + 4 * level)
        ch = _capsule_changes(ev, "cap")
        st2 = next((e for f, k, e in ch if k != "gone" and k[0] == 2), None)
        sub0 = [e for e in _capsule_tag(ev, "cap") if "state" in e and e["state"] == 2 and e["step"] == 0]

        # position from $86:D33E (the event's own position is replaced); levels 2 and 5 rise out of the floor first
        ok = st2 is not None and st2["x"] == tx and st2["y"] == ty
        det = f"table ${tx:04X},${ty:04X}; first main-state record x=${st2['x']:04X} y=${st2['y']:04X}" if st2 else "no capsule"
        if level in (2, 5):
            s2 = next((e for e in _capsule_tag(ev, "cap") if "state" in e and e["state"] == 2 and e["step"] == 2), None)
            rise = sub0[0]["y"] - s2["y"] if sub0 and s2 else 0
            ok = ok and rise == 96 and s2["f"] - sub0[0]["f"] == 48
            det += f"; y {sub0[0]['y']} at f{sub0[0]['f']} -> {s2['y']} at f{s2['f']} (substate 2): {rise} px in {s2['f'] - sub0[0]['f']} frames"
        else:
            ok = ok and not sub0
        check(f"{name}: capsule at $86:D33E[{level}]" + (" and rises 96 px (2 px a frame)" if level in (2, 5) else ""), ok, det)

        # touching the capsule: X frozen, camera lock from $86:D3A1 (none for levels 2, 3)
        s4 = next((f for f, k, e in ch if k[:2] == (2, 4)), None)
        locks = _capsule_tag(ev, "lock")
        before = _capsule_value_at(ev, "lock", "x1", s4 - 1), _capsule_value_at(ev, "lock", "y1", s4 - 1)
        at = [l for l in locks if l["f"] == s4]
        xstep = _capsule_value_at(ev, "xs", "step", s4)
        if lx:
            ok = at and (at[0]["x1"], at[0]["x2"], at[0]["y1"], at[0]["y2"]) == (lx, lx, ly, ly) and xstep == 0x1E
            det = f"f{s4}: lock = {at[0]['x1']},{at[0]['x2']},{at[0]['y1']},{at[0]['y2']} (table ${lx:04X},${ly:04X}); X step ${xstep:02X}" if at else "no lock write"
        else:
            ok = not at and xstep == 0x1E
            det = f"f{s4}: table 0 -> camera bounds unchanged ({before}); X step ${xstep:02X}"
        check(f"{name}: X touches the capsule -> X step $1E, camera lock $86:D3A1[{level}]", ok, det)

        # Dr. Light: text id, needs presses (pressed here), leaves -> X step 0 and camera bounds restored
        texts = _capsule_tag(ev, "text")
        lch = _capsule_changes(ev, "light")
        gone = next((f for f, k, e in lch if k == "gone"), None)
        lock_after = _capsule_value_at(ev, "lock", "x1", gone), _capsule_value_at(ev, "lock", "y1", gone)
        step_gone = _capsule_value_at(ev, "xs", "step", gone - 1) if gone else None
        restored = lock_after != (lx, ly) if lx else True
        ok = len(texts) == 1 and texts[0]["id"] == D4E3[level] and gone and step_gone == 0 and restored
        check(f"{name}: Dr. Light ($5C) text id $86:D4E3[{level}] = ${D4E3[level]:02X}; leaving frees X and restores the camera",
              ok, f"text box f{texts[0]['f'] if texts else '-'} id ${texts[0]['id'] if texts else 0:02X}; light gone f{gone}, "
              f"X step {step_gone}, lock x/y after {lock_after}")

        # the scene: substate 8 timings ($33 countdowns)
        f8, recs = _capsule_scene(ev)
        want = [(0, 2, 1), (2, 4, 20), (4, 6, 255), (6, 8, 128), (8, 10, 30), (10, 12, 30), (12, 14, 60)]
        deltas = [(a, b, f8.get(b, 0) - f8.get(a, 0), n) for a, b, n in want]
        cds = []
        for a, b, n in want[1:]:
            ph = [e for e in recs if e["step"] == 8 and e["sub"] == a and f8[a] <= e["f"] < f8[b]]
            cds.append(countdown(ph, "f33", n)[0])
        ok = all(d == n for a, b, d, n in deltas) and all(cds)
        check(f"{name}: scene sub2 0/2/4/6/8/A/C last 1/20/255/128/30/30/60 frames ($33)", ok,
              " ".join(f"{a:X}->{b:X}:{d}" for a, b, d, n in deltas) + f"; countdowns {cds}")

        # X steps in the scene: $1E from sub2 0, $38 from sub2 C (~60 frames), then 0 before the demo
        xs = [e for e in _capsule_tag(ev, "xs") if f8[0] <= e["f"] <= f8[14]]
        seq = [(e["f"], e["step"]) for e in xs]
        ok = (seq and seq[0] == (f8[2], 0x1E) and (f8[12], 0x38) in seq and seq[-1][1] == 0
              and [s for f, s in seq] == [0x1E, 0x38, 0] and _capsule_value_at(ev, "xs", "x", f8[2]) == tx)
        check(f"{name}: X in the scene: x = capsule x, step $1E -> $38 (sub2 C) -> 0", ok,
              f"sub2 2 f{f8[2]}, C f{f8[12]}, E f{f8[14]}; X steps {[(f, hex(s)) for f, s in seq]}")

        # the orb: spawned at $33 = $14 with A = 0 (grants), then A = 1 after sub2 8 (grants nothing)
        sp = _capsule_tag(ev, "spawn4E")
        grants = _capsule_tag(ev, "grant")
        ok = ([(e["a"], e["t33"]) for e in sp][:1] == [(0, 0x14)] and len(sp) == 2 and sp[1]["a"] == 1
              and f8[8] <= sp[1]["f"] <= f8[10] and grants and all(g["anim"] == 0 and g["idx"] == idx
                                                                   and g["mask"] == D3D5[idx] for g in grants)
              and f8[6] <= grants[0]["f"] < f8[8])
        check(f"{name}: orb $4E (index {idx}) spawned at $33 = $14; TSB $1F99 with ${D3D5[idx]:02X} by the first orb "
              f"only ({len(grants)} events), second orb (A=1) grants nothing", ok,
              f"spawns {[(e['f'], e['a'], e['t33']) for e in sp]}; grants {[(e['f'], e['mask'], e['idx'], e['anim']) for e in grants]}")

        # the part's effect
        w = {a: [e for e in _capsule_tag(ev, f"w{a:04X}") if e["f"] >= f8[0]] for a in (0x1F99, 0x1F7E, 0x0C38, 0x0C58, 0x0C78, 0x0BBE)}
        hand = lambda a: [e["v"] for e in w[a] if 0x87D0C4 <= e["pc"] <= 0x87D118]
        if name == "armadillo":
            ok = hand(0x1F7E) and hand(0x1F7E)[-1] == 0x85 and not hand(0x0C38)
            det = f"$1F7E writes {[hex(v) for v in hand(0x1F7E)]}; $0C38 writes by the handler {hand(0x0C38)}"
        elif name == "eagle":
            ok = hand(0x0BBE) and set(hand(0x0BBE)) == {0x18} and [e["v"] for e in w[0x1F99]][-1:] == [1]
            det = f"$0BBE (X gfx) writes {[hex(v) for v in hand(0x0BBE)]}; $1F99 -> {[e['v'] for e in w[0x1F99]]}"
        else:
            slot = {"mammoth": 0x0C38, "chameleon": 0x0C58, "penguin": 0x0C78}[name]
            ok = hand(slot) == [1, 2] and [e["v"] for e in w[0x1F99]][-1:] == [D3D5[idx]]
            det = f"${slot:04X} (X part object) -> {hand(slot)} (INC twice: the event fires on 2 frames); $1F99 -> {[e['v'] for e in w[0x1F99]]}"
        check(f"{name}: {part} granted" + ("" if name in ("eagle", "armadillo") else " - X sprite-part slot switched on"), ok, det)

        # demo input: (frames, pad high byte) pairs from $86:D36B, played into $00A7 from sub2 E; then control returns
        script = _capsule_script(level)
        pads = _capsule_tag(ev, "pad")
        start = f8[14] + 1
        expect, f = {}, start
        for n, b in script:
            for i in range(n):
                expect[f + i] = b << 8
            f += n
        end = f
        got = {fr: _capsule_value_at(ev, "pad", "held", fr) for fr in expect}
        bad = [fr for fr in expect if got[fr] != expect[fr]]
        ram_end = [e for e in _capsule_tag(ev, "ram") if e["f"] == end]
        ok = not bad and f8.get(16) == end and ram_end and ram_end[0]["f48"] == 0 and ram_end[0]["hurt"] == 0
        check(f"{name}: demo pad script {[(n, hex(b)) for n, b in script]} played exactly into $00A7, then control "
              f"returns ($1F48 = 0, hurt lock 0)", ok,
              f"f{start}..{end - 1}: {len(expect) - len(bad)}/{len(expect)} frames match; sub2 $10 at f{f8.get(16)}, "
              f"ram at end {ram_end[0] if ram_end else None}")
        demo_steps = [(e["f"], e["step"]) for e in _capsule_tag(ev, "xs") if start <= e["f"] <= end]
        if name == "penguin":
            d = [f for f, s in demo_steps if s == 0x14]
            e20 = [f for f, s in demo_steps if s == 0x20]
            ok = d and e20 and e20[0] - d[0] == 32
            check("penguin: the demo's double tap of Right dashes (X step $14 for 32 frames, then $20)", ok,
                  f"X steps {[(f, hex(s)) for f, s in demo_steps]}")
        if name == "armadillo":
            ok = any(s == 0x42 for f, s in demo_steps)
            check("armadillo: the demo's Down, Down+Left, Left, Y puts X in step $42 (Hadouken)", ok,
                  f"X steps {[(f, hex(s)) for f, s in demo_steps]}")

    # X init creates the part objects from $1F99 (Armadillo run: $1F99 = $FF poked before X's init)
    ev = out["capsule_armadillo"]
    init = {a: [e["v"] for e in _capsule_tag(ev, f"w{a:04X}") if 0x819D88 <= e["pc"] <= 0x819DC8] for a in (0x0C38, 0x0C58, 0x0C78)}
    gfx = [e["v"] for e in _capsule_tag(ev, "w0BBE") if 0x819D88 <= e["pc"] <= 0x819DC8]
    check("X init ($81:9D88) creates part objects $0C38/$0C58/$0C78 from $1F99 bits $02/$04/$08 and sets gfx $0BBE = $18 "
          "for bit $01", all(v == [1] for v in init.values()) and 0x18 in gfx, f"slot writes {init}; gfx writes {gfx}")

    # already owned / conditions not met: the capsule deletes itself at init
    ev = out["capsule_eagle_owned"]
    ch = _capsule_changes(ev, "cap")
    check("eagle, helmet owned ($1F99 = $01): the capsule deletes itself at init",
          [k for f, k, e in ch] == [(0, 0, 0), "gone"] and _capsule_tag(ev, "despawn"),
          f"capsule records {[(f, k) for f, k, e in ch]}; despawn f{[e['f'] for e in _capsule_tag(ev, 'despawn')][:1]}")
    ev = out["capsule_armadillo_lowhp"]
    ch = _capsule_changes(ev, "cap")
    w7e = [e["v"] for e in _capsule_tag(ev, "w1F7E") if e["pc"] >> 16 == 0x87]
    check("armadillo: all conditions but X HP $1F -> $1F7E = 5, capsule deletes itself (no Hadouken)",
          [k for f, k, e in ch] == [(0, 0, 0), "gone"] and w7e and w7e[-1] == 5,
          f"capsule records {[(f, k) for f, k, e in ch]}; $1F7E writes {w7e}")
    ev = out["capsule_armadillo"]
    w7e = [e["v"] for e in _capsule_tag(ev, "w1F7E") if 0x87CA86 <= e["pc"] <= 0x87CAA0]
    check("armadillo: init counts $1F7E 4 -> 5 and the capsule appears (all upgrades, hearts, bosses, HP $20)",
          w7e and w7e[-1] == 5 and any(k != "gone" and k[0] == 2 for f, k, e in _capsule_changes(ev, "cap")), f"$1F7E writes {w7e}")

    # Chameleon's trigger ($87:FB40)
    ev = out["capsule_chameleon"]
    evs = [e for e in CAPSULE_G.events(2) if e.type == 2 and e.id == 0x1D]
    o1d = _capsule_tag(ev, "o1D")
    st = {e["state"]: e for e in o1d}
    check("chameleon: event type 2 id $1D at ($0600,$0140) -> $1D08-list object (code $87:FB40)",
          len(evs) == 1 and (evs[0].x, evs[0].y) == (0x600, 0x140) and o1d and 0x1D08 <= o1d[0]["slot"] < 0x1E08
          and (o1d[0]["x"], o1d[0]["y"]) == (0x600, 0x140),
          f"events {evs}; object slot ${o1d[0]['slot']:04X} at ${o1d[0]['x']:04X},${o1d[0]['y']:04X} f{o1d[0]['f']}" if o1d else "none")
    f2 = st[2]["f"] if 2 in st else None
    xprev = _capsule_value_at(ev, "xs", "x", f2 - 1) if f2 else None
    xat = [e for e in _capsule_tag(ev, "xs") if e["f"] == f2]
    lk = [l for l in _capsule_tag(ev, "lock") if l["f"] == f2]
    ok = xat and xat[0]["step"] == 0x1E and xat[0]["x"] >= 0x630 and xat[0]["x"] - 0x630 < 3 and lk and \
        (lk[0]["x1"], lk[0]["x2"], lk[0]["y1"], lk[0]["y2"]) == (0x600, 0x600, 0x100, 0x100)
    check("chameleon: X x >= $0630 -> X step $1E, camera lock x $0600 y $0100", ok,
          f"f{f2}: X {xat[0] if xat else None}; lock {lk[0] if lk else None}")
    rises = []
    last = 0
    for e in _capsule_tag(ev, "m11"):
        if e["n"] > last:
            rises.append(e["f"])
        last = e["n"]
    e9 = [e for e in _capsule_tag(ev, "e09") if "state" in e]
    f4 = st[4]["f"] if 4 in st else 0
    ok = len(rises) == 6 and rises[0] - f4 == 60 and all(b - a == 60 for a, b in zip(rises, rises[1:])) and e9 \
        and e9[0]["f"] == rises[-1] and (e9[0]["x"], e9[0]["y"]) == (0x6D0, 0xE0)
    check("chameleon: camera in place -> six $1628-list id $11 objects 60 frames apart, enemy 9 at ($06D0,$00E0) with the 6th",
          ok, f"state 4 f{f4}; id $11 spawns {rises}; enemy 9 first f{e9[0]['f'] if e9 else None} at "
          f"{(hex(e9[0]['x']), hex(e9[0]['y'])) if e9 else None}")
    gone9 = next((e["f"] for e in _capsule_tag(ev, "e09") if "state" not in e), None)
    cap0 = next((e["f"] for e in _capsule_tag(ev, "cap") if "state" in e), None)
    ok = gone9 and cap0 and cap0 - gone9 in (96, 97, 98) and st.get(8, {}).get("f") == gone9
    check("chameleon: enemy 9 gone -> 96 frames -> capsule $4D spawned (test aid: enemy 9's HP held at 1)", ok,
          f"enemy 9 gone f{gone9}, trigger state 8 f{st.get(8, {}).get('f')}, capsule f{cap0}")
    # exec events are logged with f = frame - 1
    grant = next((e["f"] + 1 for e in _capsule_tag(ev, "grant")), None)
    brk = [dict(b, f=b["f"] + 1) for b in _capsule_tag(ev, "brk")]
    ok = grant and st.get(12, {}).get("f") == grant and len(brk) == 6 and brk[0]["f"] - grant == 180 \
        and all(b["f"] - a["f"] == 20 for a, b in zip(brk, brk[1:])) and [b["y"] for b in brk] == list(range(0x110, 0x1B0 + 1, 0x20)) \
        and all(b["x"] == 0x610 for b in brk)
    check("chameleon: grant -> trigger state $0C the same frame; 180 frames, then 6 wall blocks at x $0610, y $0110..$01B0, "
          "20 frames apart", ok, f"grant f{grant}, state $0C f{st.get(12, {}).get('f')}; breaks {[(b['f'], hex(b['y'])) for b in brk]}")

    ev = out["capsule_chameleon_owned"]
    o1d = {e["state"]: e["f"] for e in _capsule_tag(ev, "o1D")}
    ch = _capsule_changes(ev, "cap")
    brk = _capsule_tag(ev, "brk")
    ok = [k for f, k, e in ch][:2] == [(0, 0, 0), "gone"] and 6 in o1d and o1d.get(12) == ch[1][0] and len(brk) == 6
    check("chameleon, body owned ($1F99 = $04): rocks and enemy 9 still come; the capsule deletes itself at init and the "
          "wall breaks anyway", ok, f"trigger states {o1d}; capsule {[(f, k) for f, k, e in ch]}; breaks {[b['f'] for b in brk]}")


CACHE = "work/upgrades_runs.json"
SECTIONS = [(runs_weapons, checks_weapons), (runs_zero_hadouken, checks_zero_hadouken), (runs_armor, checks_armor),
            (runs_tanks, checks_tanks), (runs_capsule, checks_capsule)]


def main():
    Path(WEAPONS_DIR).mkdir(parents=True, exist_ok=True)
    if "--cached" in sys.argv:
        out = json.loads(Path(CACHE).read_text())
    else:
        runs = {}
        for make, _ in SECTIONS:
            runs.update(make())
        print(f"running {len(runs)} emulator sessions...")
        out = dict(zip(runs, run_all(list(runs.values()))))
        Path(CACHE).write_text(json.dumps(out))
    results = []
    for _, checks in SECTIONS:
        checks(out, lambda name, ok, detail="": results.append((name, bool(ok), detail)))
    report(results)


if __name__ == "__main__":
    main()
