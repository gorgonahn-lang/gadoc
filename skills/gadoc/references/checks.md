# gadoc checks

Work through each check for every harness in scope. For each, record a finding, "none", or "unknown (reason)".

## Where each harness looks

### grok (Grok Build)
| Kind | Locations (highest priority first) |
|---|---|
| Skills | `./.grok/skills/`, `<repo>/.grok/skills/`, `~/.grok/skills/`, `~/.claude/skills/`, `~/.agents/skills/`, plugin `skills/`, `[skills].paths` |
| Plugins | `.grok/plugins/`, `~/.grok/plugins/`, Claude Code `~/.claude/plugins/installed_plugins.json`, `[plugins].paths` |
| Rules | `~/.grok/`, then repo root to cwd: `Agents.md`, `Claude.md`, `AGENT.md`, `AGENTS.md` (10,000-char cap each; deeper wins) |
| MCP | `~/.grok/config.toml [mcp_servers.*]`, `.grok/config.toml`, `~/.claude.json`, `.mcp.json` |
| Hooks | `.grok/hooks/`, `[[hooks.*]]` in config layers, plugin hooks |
| Permissions | TOML config, else `.claude/settings*.json` |

`grok inspect --json` is the source of truth for what actually loaded; the collector's `skill_dirs_on_disk` shows copies that lost to a higher-priority copy.

### agy (Antigravity CLI)
| Kind | Locations (highest priority first) |
|---|---|
| Skills | workspace `.agents/skills/` (walks cwd to repo root), `skills.json` entries, `~/.gemini/config/skills/`, plugin `skills/`, built-ins `~/.gemini/antigravity-cli/builtin/skills/` |
| Plugins | `.agents/plugins/`, `~/.gemini/config/plugins/`, `plugins.json`; on/off in `~/.gemini/config/config.json` |
| Rules | `~/.gemini/config/AGENTS.md`/`GEMINI.md`, `AGENTS.md`/`GEMINI.md` from repo root to cwd, `.agents/rules/*.md`, plugin `rules/` |
| MCP | `~/.gemini/config/mcp_config.json`, plugin `mcp_config.json` |
| Hooks | `~/.gemini/config/hooks.json`, `~/.gemini/antigravity-cli/hooks.json`, workspace/plugin `hooks.json` |

## Checks

1. **Broken or unreadable (high).** Broken skill symlinks, `SKILL.md` without `name`/`description`, unparsable JSON/TOML, MCP commands not on PATH, `grok mcp doctor` failures, `grok inspect` errors.
2. **Truncated rules (high).** grok rule file over 10,000 chars; agy rule file over 24,000 bytes; agy always-on + global rules over ~20,000 tokens (overflow becomes a file pointer the model may not read).
3. **Unsafe defaults (high).** Shell aliases or wrappers adding `--always-approve`, `--dangerously-skip-permissions` or `--permission-mode bypassPermissions`; hooks that download and run remote code (`curl ... | sh`); secrets written inline in MCP `env`/`headers` (the collector shows key names only - check the file). Report; the user decides whether it is intended.
4. **Shadowing (medium).** Same skill name in more than one location. Say which copy wins and whether the copies differ (`diff` the two `SKILL.md`).
5. **Overlap (medium).** Different names, same job: descriptions that would trigger on the same request (for example two browser skills, two PDF skills, a grok bundled skill plus a Claude plugin skill). Read both descriptions; state the request that would be ambiguous.
6. **Rule conflicts (medium).** Read every rule file listed for the harness (global, project, plugin, and for grok also `CLAUDE.md`). Quote contradicting lines side by side with paths and line numbers (language, permission, formatting, tool choice). Do not report mere repetition as conflict; report it as duplication (low).
   - agy deduplicates rules by resolved file path: two paths (or a symlink) pointing to the same file load once. Compare `realpath` in the inventory before calling it a duplicate load.
   - grok does not merge files: the same text in `AGENTS.md` and `CLAUDE.md` is sent twice; that is duplication (low).
7. **Unneeded exposure (info/low).** Skills, plugins and MCP servers loaded into every session that the user's work does not need: for grok especially Claude Code plugins and synced skills it inherits. Give the per-request listing cost from `GROK-LISTING-COST` / `AGY-LISTING-COST` and which groups dominate it. Ask the user about their work before calling something unneeded.
8. **Hygiene (low).** Descriptions over 1,024 chars, name/folder mismatch, empty skill bodies, stale disabled entries.

## Unknowns

Mark `unknown` instead of guessing when: a command timed out, a file was unreadable, agy loads something only at runtime (declared entries with patterns the collector could not evaluate), or login is required for a listing.
