# Levers: what can be turned down, and how

Verify every key against the installed runtime version before using it. Keys and accepted values change between releases, and a terminal wrapper or stale CLI earlier on `PATH` may not know a key that the running build supports. Read the version from the binary that actually executes (the collector's `binary.realpath`), not from whatever `which` resolves.

## Files this skill may edit

| File | Holds |
| --- | --- |
| `~/.grok/config.toml` | grok `[skills]` paths/ignore, `[plugins]` paths/disabled, `[mcp_servers.*]`, `[[hooks.*]]` |
| `SKILL.md` frontmatter of a skill in `~/.grok/skills/`, `.grok/skills/`, `~/.gemini/config/skills/` or `.agents/skills/` | `disable-model-invocation: true` (the `user-invocable-only` level). Only the frontmatter line; never the body |
| `~/.gemini/config/skills.json`, `.agents/skills.json`, `plugins.json` | agy declared entries and their `exclude` patterns |
| `~/.gemini/config/config.json` | agy plugin on/off - prefer `agy plugin enable/disable`, which writes it |
| `~/.gemini/config/mcp_config.json` | agy MCP servers - prefer `agy mcp enable/disable` |
| `.agents/rules/*.md` frontmatter | agy rule `trigger` (`always_on` → `model_decision`) |
| `~/.gemini/config/hooks.json`, `.agents/hooks.json`, grok `.grok/hooks/` files | Hooks. Only under `--include-hooks` |
| `~/.grok/agents/`, `.grok/agents/` | Agent definitions written by a person. Only under `--include-hooks`, and only by moving a file to this run's holding directory, never by deleting or editing it |
| `~/.gadoc/held/<id>/<scope>/` | Where a moved skill folder, agent or hook file is held. One directory per run and per scope, so two items that share a name never land on the same path |
| Shell rc file (`~/.zshrc` ...) | An auto-approve alias for grok/agy - only when the person asks; comment the line out, never delete it |

The runtime writes to some of these files while it is running. Read each file immediately before writing it, merge into what is actually there, and write once. Never build an edit from a copy read minutes earlier, or a setting the person changed in between disappears. Where a CLI command exists for the change, prefer it over editing the file, because it handles this and keeps derived state consistent. In TOML, extend an existing `[skills]` or `[plugins]` table instead of adding a second one.

## Files this skill must not edit

| File | Why |
| --- | --- |
| Anything under `~/.claude/`, and `~/.claude.json` | Claude Code owns them; grok only reads them. Use grok-side levers |
| `~/.grok/bundled/`, `~/.gemini/antigravity-cli/builtin/` | Shipped with the app; an update restores them |
| Plugin caches, installed-plugin inventories, generated agent or command files | Generated, not the source. Editing them desynchronizes state. Change the source and let the existing sync produce them |
| Marketplace registry | Owned by `grok plugin marketplace` / `agy plugin` |
| Managed or policy settings (`/etc/grok/*`, `~/.grok/managed_config.toml`, `~/.grok/requirements.toml`) | Cannot be overridden, and must not be worked around |
| `~/.grok/auth.json`, `~/.gemini/antigravity-cli/cache/`, session logs | Credentials and runtime state |
| `~/.grok/disabled-hooks` | Undocumented format. Do not write it; use the TUI hooks modal if the person wants that |

## Reversible levers (preferred)

| Target | Edit | Undo | Verified |
| --- | --- | --- | --- |
| grok skill from a skills directory the person owns | `disable-model-invocation: true` in its `SKILL.md` frontmatter (`user-invocable-only`) | Remove the line (or `restore`) | grok 1.0.41: hidden from model listing, `/name` works |
| grok skill folder, including ones inherited from `~/.claude/skills` | `[skills] ignore = ["<folder or parent>"]` (`~` allowed) | Remove the entry | grok 1.0.41 |
| grok plugin, including Claude Code plugins grok inherits | `[plugins] disabled = ["<plugin name>"]` | Remove the entry | grok 1.0.41: its skills leave `inspect.skills`; `inspect.plugins[].enabled` and plugin hook entries may still show - judge by the skills list |
| grok plugin installed with `grok plugin install` | `grok plugin disable <name>` | `grok plugin enable <name>` | CLI |
| grok MCP server | `grok mcp disable <name>` | `grok mcp enable <name>` | CLI; confirm with `grok mcp list` |
| agy skill from a skills directory | `disable-model-invocation: true` in its frontmatter (`user-invocable-only`) | Remove the line | agy 1.2.13: hidden from model listing; direct invocation unverified |
| agy skill folder (`off`) | `snapshot.py hold` the folder | `restore` moves it back | filesystem |
| agy skill declared via `skills.json` | Add a pattern to that entry's `exclude` | Remove the pattern | documented |
| agy plugin | `agy plugin disable <name>` | `agy plugin enable <name>` | CLI |
| agy MCP server | `agy mcp disable <name>` | `agy mcp enable <name>` | CLI |
| agy rule in `.agents/rules/*.md` loaded every session | `trigger: model_decision` frontmatter | Restore `always_on` / remove the key | documented; standalone `AGENTS.md`/`GEMINI.md` take no frontmatter |

Prefer the CLI when one exists; hand-editing the same value does not keep derived state consistent.

## Destructive levers (opt-in only)

| Target | Why it is destructive | Requirement |
| --- | --- | --- |
| A single hook | No supported, documented disable flag. The entry has to be cut out of `config.toml` / `hooks.json`, or the hook file moved out of `.grok/hooks/` | Snapshot, plus `--include-hooks` |
| A single agent | No disable flag. The file has to be moved to `~/.gadoc/held/<id>/<scope>/`, so undo is a move back. If anything already occupies the destination path, do not move: report the collision and leave both files alone. A move that overwrites is a deletion wearing a different name | Snapshot, plus `--include-hooks` |
| A grok rule file (`AGENTS.md`, `CLAUDE.md` ...) | grok has no conditional loading; shortening or splitting changes text | Explicit approval of the exact diff; never for `CLAUDE.md` owned by Claude Code |

Commenting a hook command out is not a supported disable path and must not be proposed. A global switch that disables every hook usually disables the status line and terminal integrations with it (for example cmux hooks), so it is not a substitute for turning off one noisy hook.

## Estimating standing cost

| Target | Measure |
| --- | --- |
| Skill | Length of the description exposed in the skill listing (0 once `disable-model-invocation` is set) |
| Rule | Bytes of files that load unconditionally: grok every discovered rule file (cap 10,000 chars each); agy `always_on` and global rules (cap 24,000 bytes each, ~20,000-token shared budget) |
| MCP server | Size of the tool schemas exposed to the session. grok discovers MCP tools through `search_tool`, so do not count every installed schema as injected |
| Plugin | Sum of the skills, MCP servers and hooks it contributes |
| Hook | Registration count and, where observable, execution time |

Report cost as an estimate with the measure named. Do not convert it into a claim about task accuracy.
