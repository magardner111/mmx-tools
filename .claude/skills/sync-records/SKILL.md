---
name: sync-records
description: Bring every record of the game's code up to date and consistent after a completed run — a verify_*.py suite, an exploratory Mesen session (headless or in the window), or a reading of disassembly/decomp. Use whenever a run finishes (verify scripts print a reminder), whenever a name or fact about a routine, RAM address, object field or X/boss step is confirmed, corrected or renamed, and before reporting results to the user.
---

# Sync records

The project keeps the same facts in several places. After every completed run, update all of them in one pass and
finish with `python3 check_records.py` reporting **records consistent**.

## Where each kind of fact lives

| fact | primary (source of truth) | also appears in |
|---|---|---|
| engine routine name | `lift.py` `HELPERS` (comment: what it does, `(verified)` or `(?)`) | ENEMY_AI.md helper table, NOTES.md, PLAYER.md |
| RAM address name | `lift.py` `RAM_NAMES` | NOTES.md, PLAYER.md (X's slot `$0BA8`+), VERIFIED.md |
| generic object field | `lift.py` `FIELDS` | ENEMY_AI.md "object fields" table |
| a boss's fields / functions / attack names | `defs.py` boss entry (`fields`, `func_names`, `attack_handlers`, `state_names`, `params`, `attacks_doc`) | ENEMY_AI.md boss section, VERIFIED.md |
| X's fields / steps / routines | `defs.py` `PLAYER` | PLAYER.md (field table, step table with the same names, routines) |
| what was confirmed in the game and how | VERIFIED.md (one table per boss, plus side findings) | the `check(...)` text in verify_*.py |
| how to reach a boss / test setup | NOTES.md, the verify script's docstring | `work/states/*.mss` save states |
| enemy-shot id (the `$1428` list) | `defs.py` `ENEMY_SHOTS` (name, update routine, marking; checked against the ROM's dispatch table `$80:F77D`) | boss `attacks_doc` ("enemy shot 0xNN"), ENEMY_AI.md, the C (`decomp.py` comments `s->id = …;`) |
| enemy / object id | `defs.py` `KNOWN_OBJECT_NAMES` | ENEMY_AI.md, boss docs, the C (`decomp.py` comments `s->id = …;`) |

`decomp.py` (C output) and `lift.py` (pseudo-C) read their names from these, so a name fixed in the primary place
shows up in the C automatically. Re-run `python3 -c "from mmx1 import MMX1; from decomp import decompile; ..."`
for the affected boss (or `decomp.py x` for X) to check the new names appear and no `fNN`/`sub_` remains for
something now understood.

## Steps

1. **List what the run established.** From the run's output (PASS/FAIL lines, logs, screenshots): each fact
   confirmed, each claim proven wrong, each new name. A FAIL caused by the test (wrong frame count, sampling
   offset, bad input) is not a fact about the game; fix the test, don't record it.
2. **Update the primary place first** (table above): add or rename the symbol, set its marking.
3. **Propagate** to every other place in the table. Before finishing a rename, grep the whole project for the old
   name and the raw address: `grep -rn "old_name\|0BD8\|\$84:9D07" --include=*.py --include=*.md .`
   Add the old name to `RENAMED` in `check_records.py` so it can't come back.
4. **VERIFIED.md**: add a row per confirmed claim with its evidence (numbers from the run), and update the
   section header with the pass count (e.g. "31/31, run twice"). Remove "(?)" from those names everywhere.
5. **Run `python3 check_records.py`** and fix everything it reports. For a boss field that genuinely reuses a
   generic offset for something else, add it to `FIELD_OVERRIDES` there (after checking the code).
6. **Report** to the user: what was confirmed, what was renamed, what is still unconfirmed.

## New kinds of records

`check_records.py` covers every boss in `defs.BOSSES`, `PLAYER`, every `*.md` and every `verify_*.py`
automatically, so a new boss, doc or test needs nothing extra. A **new kind** of record (projectile/shot ids,
enemy ids, sound or music ids, stage data...) does: when you start keeping one, add its source of truth to the
table above and add a `@check` function in `check_records.py` that compares it with every place it's repeated.
Prove the check works by breaking a record in memory and seeing it reported (as done for the existing checks).

## Conventions (keep them identical everywhere)

- Markings: `(verified)` = checked by a verify suite; `seen in Mesen` = observed in a run but not a suite check;
  `(?)` = from reading code only. Never leave a name `(?)` in one file and verified in another.
- In docs, write the symbol next to every address: `` `X_hurt_lock` (`$0BD8`) ``, `` `face_x` (`$84:ACA5`) ``.
- Routine addresses as `$BB:AAAA`, RAM as `$AAAA`, object fields as `$NN`; X's fields are offsets from `$0BA8`.
- Names: snake_case; X's RAM names start with `X_` in `lift.py` and drop it in `defs.PLAYER.fields`
  (`X_hurt_lock` ↔ `hurt_lock`). Boss attack handlers are named after the attack (`gust`, `dive`, ...).
- Test event tags in verify_*.py use the current symbol name (e.g. `on_write(0x0BD8, "X_hurt_lock")`).
- Facts about X found while testing a boss go in PLAYER.md, not only in the boss's section.
