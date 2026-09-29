---
name: gadoc-trim
description: Use when the user wants to act on a gadoc report for grok (Grok Build) or Antigravity CLI (agy) - hide or disable skills, plugins or MCP servers they do not need, fix truncated or conflicting rule files, remove an auto-approve alias - or wants to undo a previous gadoc-trim change. Not for Claude Code or Codex.
---

# gadoc-trim - approved, reversible cleanup for grok / agy

Changes happen only after the user approves an exact plan, and every change set can be rolled back with one command.

## Procedure

1. **Start from evidence.** Use the latest gadoc report and its inventory JSON (`~/.gadoc/reports/`). If there is none, or it is older than today, run the `gadoc` skill first.
2. **Ask about the work** (one short question): what the user does with this harness. Only call something unneeded after the answer.
3. **Plan.** For each change, one row:

   | # | Harness | Finding | Lever | Exact change (file/key/command, before -> after) | Effect | Undo |

   Pick levers from [references/levers.md](references/levers.md). Show the plan and ask for approval: all, by row number, or none.
4. **Journal, then change.** Only approved rows, in this order:
   ```bash
   S=<this-skill-dir>/scripts/snapshot.py
   ID=$(python3 $S begin --label "<short label>")
   python3 $S backup $ID <each file you will edit>      # before editing it
   python3 $S park   $ID <skill folder>                 # instead of deleting
   python3 $S record $ID --do "<cli toggle>" --undo "<reverse toggle>"   # right after running it
   ```
5. **Verify.** Re-run `python3 <gadoc-skill-dir>/scripts/collect.py ... --summary` and confirm each approved item changed as planned. If a check fails or a config no longer parses, roll back that change set immediately and report it.
6. **Report** in the user's language: each row with done / failed / skipped, the change-set ID, and the rollback command:
   `python3 <this-skill-dir>/scripts/snapshot.py rollback <ID> --run-undo`

## Rollback

`snapshot.py list` shows change sets. `rollback <ID> --run-undo` restores backed-up files, moves parked folders back, then runs the recorded undo commands in reverse order. Verify with the collector afterwards.

## Common mistakes

| Mistake | Instead |
|---|---|
| Editing `~/.claude/...` to fix something grok inherits | grok-side `[skills].ignore` / `[plugins].disabled` |
| Deleting a skill folder | `park` it |
| Running a toggle without `record` | Record immediately, with its reverse |
| Adding a second `[skills]` table to config.toml | Extend the existing array |
| Touching agy built-in skills | Report only |
| Applying rows the user did not approve | Apply exactly the approved rows |
