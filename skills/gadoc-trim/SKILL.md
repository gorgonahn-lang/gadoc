---
name: gadoc-trim
description: "Approval-gated cleanup for a grok (Grok Build) or Antigravity CLI (agy) harness, with a one-command rollback. Use when the user wants to act on a gadoc diagnosis - lower the exposure of skills, plugins or MCP servers they do not need, fix truncated or conflicting rules - or wants to preview such a change (--dry-run) or restore a previous snapshot. Not for diagnosis alone (use gadoc), and not for Claude Code or Codex (use HarDoc trim)."
---

# gadoc-trim

gadoc has two surfaces. `gadoc` collects evidence and stops. `gadoc-trim` turns that evidence into a change a person approved, and keeps a way back.

The goal is not a smaller item count. It is a harness where the assistant sees what this person actually works on.

## Usage

- grok: `/gadoc-trim`, `/gadoc-trim --dry-run`, `/gadoc-trim restore <snapshot-id>`
- agy: "gadoc-trim", "gadoc-trim --dry-run", "gadoc-trim restore <snapshot-id>"

| Flag | Effect |
| --- | --- |
| `--dry-run` | Preview only. Write nothing at all, including the stored profile. |
| `--reprofile` | Ask the profile questions again and overwrite the stored answers. Combined with `--dry-run`, ask them but store nothing. |
| `--include-hooks` | Allow hook and agent candidates, which require destructive edits. Off by default. |
| `--level off` | Raise the default prescription from `user-invocable-only` to `off` for role-unrelated items. |
| `restore <id>` | Roll a snapshot back. |

## The core move: lower exposure instead of deleting

grok and agy have no settings-level per-skill override. The levels available, verified on grok 1.0.41 and agy 1.2.13:

| Level | grok | agy | Use for |
| --- | --- | --- | --- |
| `on` | default | default | Keep |
| `user-invocable-only` | `disable-model-invocation: true` in the skill's own `SKILL.md` frontmatter. Verified: removed from the model's skill listing, `/name` still works | Same frontmatter. Verified: removed from the model's skill listing. Direct invocation by name is **unverified** - check it after applying | **Default prescription for a skill from a skills directory the person owns.** The skill survives; only its standing cost drops |
| `name-only` | Not available | Not available | - |
| `off` | Add the folder to `[skills].ignore` in `~/.grok/config.toml` | Move the folder to the holding directory (`snapshot.py hold`), or add an `exclude` pattern to the `skills.json` entry that declared it | Confirmed unused, or items grok inherits from Claude Code |

Start at `user-invocable-only`. A wrong guess there costs almost nothing: the capability survives and a person can still invoke it. Reserve `off` for items the person names, for `--level off` runs, and for sources where the frontmatter lever is not allowed (below).

### Classify every candidate by source before prescribing anything

| Source | Available lever |
| --- | --- |
| grok user/project skills directory (`~/.grok/skills`, `.grok/skills`) | The levels above, per skill. The frontmatter edit changes the skill's source file; if the folder is a link into a repository, say so |
| agy global/workspace skills directory (`~/.gemini/config/skills`, `.agents/skills`) | The levels above, per skill |
| Skill grok inherits from Claude Code (`~/.claude/skills/...`, synced skills) | Only `off` via grok's `[skills].ignore`. Editing its frontmatter would change Claude Code too, so it is not allowed |
| A plugin (grok native, a Claude Code plugin grok inherits, or an agy plugin) | Only the plugin as a whole: grok `[plugins].disabled = ["<name>"]` (or `grok plugin disable` for plugins installed with `grok plugin install`); agy `agy plugin disable <name>`. There is no per-skill lever |
| Bundled with the runtime (`~/.grok/bundled`, agy built-ins) | No supported lever. Report only |
| Anything else, or a source that could not be resolved | No prescription. Report it as `unknown` and leave it alone |

A skipped candidate costs a little standing context; a confidently wrong prescription costs trust in every other row of the table.

When a plugin's skills are the expensive part, the honest proposal is "disable this plugin" with its full cost, not a per-skill edit that cannot reach it. If the person wants to keep part of a plugin, say that the runtime does not support it.

Confirm the behavior against the installed version rather than assuming it. An observation from grok is not evidence about agy, and the other way round; say which runtime an observation came from.

The same preference for reversible form applies elsewhere. Plugins are disabled, not uninstalled. agy rules in `.agents/rules/*.md` can be demoted from `always_on` to `trigger: model_decision` instead of being removed.

## Steps

### 1. Profile

Ask at most four questions, then stop asking. Read [references/profile.md](references/profile.md) for the question set and the matching rules. Store answers in `~/.gadoc/profile.json` and reuse them on later runs unless `--reprofile` is given. Under `--dry-run`, keep the answers in memory for that run and write nothing, so the flag's promise holds literally.

A profile is a hypothesis about what this person does, not a fact about what they need. It ranks candidates; it never decides alone.

### 2. Inventory and cost

Reuse the `gadoc` collector (`<gadoc-skill-dir>/scripts/collect.py`). Do not write a second inventory implementation. Its items already carry:

- `source`: where the item is loaded from. This decides which lever exists at all; an item whose source is unknown gets no prescription.
- `always_cost_chars` / `always_cost_tokens`: what the item injects into every session regardless of the request (listed skill description, always-on rule bytes).
- `recent_use` and `invoked`: skill loads seen in this host's session logs within the window. Absence of evidence is `unknown`, never zero.

Add `role_match`: `related`, `unclear`, or `unrelated` against the profile. Rank candidates by standing cost descending within `role_match = unrelated`. An item with a large standing cost and no relation to the person's work is the best candidate. A cheap item is rarely worth touching even when unused.

### 3. Preview

Read [references/levers.md](references/levers.md) before proposing anything. It fixes which files may be edited, which must never be touched, the reversible form for each target, and how standing cost is measured.

Print one table: item, runtime, source, current state, proposed level, estimated saving, evidence, and how to undo it. Put the total saving on top. Name every item that was considered and kept, with the reason.

Write nothing in this step. A person must be able to run the preview on a whim. Under `--dry-run` run the collector without `--out` so it prints the inventory to stdout and no file is created anywhere, including `/tmp`; analyze it in the same command (for example `python3 collect.py ... | python3 -c '...'`).

### 4. Apply

1. Snapshot first, with `scripts/snapshot.py`:
   ```bash
   S=<this-skill-dir>/scripts/snapshot.py
   ID=$(python3 $S begin --label "<short label>")
   python3 $S backup $ID <every file about to change>        # config.toml, SKILL.md, skills.json, hooks.json, rc file
   python3 $S hold   $ID <folder or file to move> --scope <grok-user|agy-global|...>   # instead of deleting
   python3 $S record $ID --do "<cli toggle>" --undo "<reverse>"                     # right after running it
   ```
   Moved items go to `~/.gadoc/held/<id>/<scope>/`, outside the snapshot, so deleting a settled snapshot never deletes them. `hold` refuses to move onto an occupied path; report the collision.
2. Apply the approved subset only. If the person approved part of the list, do not apply the rest. Read each file immediately before writing it and merge into what is actually there.
3. Re-parse every edited file (TOML via `grok inspect --json`; JSON via `python3 -m json.tool`). If a file no longer parses, restore the snapshot immediately and report the failure.
4. Confirm the change took effect by re-observing what the runtime exposes: re-run the collector (and for grok `grok inspect --json`). A file that parses is not a change that applied - a lever the runtime ignores leaves a perfectly valid file behind. Report anything that did not take effect as failed, and do not count its saving.
5. `python3 $S commit $ID` to store post-change hashes, then print the rollback command: `/gadoc-trim restore <id>` (or `python3 $S restore <id> --run-undo`).

`restore` compares the current value against the snapshot. When a file changed after the snapshot was committed, it reports the conflict and leaves it alone rather than overwriting somebody's later edit.

## Safety

- **Hooks and agents are opt-in.** grok's `disabled-hooks` file is undocumented and agy has no hook switch, so turning one off means cutting an entry out of a settings file or moving a file. They stay out of the applied set unless `--include-hooks` is given, and they always require a snapshot.
- **Zero observed calls is not a reason to remove anything.** This rule is inherited from `gadoc` and is not relaxed here. An item may be exposed only on another machine, invoked directly by a project file, or needed rarely.
- **Dependencies win over counts.** Language servers, security hooks and verification hooks stay even at zero skill invocations.
- **Recent use is a veto.** Any item with recent-use evidence leaves the candidate list regardless of role match.
- **Never write another runtime's or a derived file.** Nothing under `~/.claude` or `~/.claude.json` (grok only reads them), no bundled or built-in skill, no plugin cache, no marketplace registry (owned by `grok plugin marketplace`), no managed policy, no `~/.grok/auth.json`.
- **Read the version from the binary that actually runs.** A terminal wrapper or stale CLI earlier on `PATH` may predate the settings keys this skill relies on. The collector records the real binary and any shadowing wrapper.
- Never install, update, log in, or change a managed policy file to make a change succeed.

## Reporting

Report in the user's language, in this order: what changed, what was kept and why, anything that was attempted and did not take effect, the total saving from confirmed changes only, snapshot id, rollback command.

Count a saving only for a change that step 4 confirmed. An unsupported lever produces no saving no matter how clean the edit looked.

State savings as estimates. Standing token cost is measurable; task accuracy is not measured by this skill. When a person asks whether the harness got better, hand them back to `gadoc evaluate`, which compares real tasks. A smaller context is not by itself an improvement.
