# gadoc-trim levers

Prefer the lowest lever that fixes the finding. Every lever is reversible through `snapshot.py`. Nothing here deletes files.

## grok

| Goal | Lever | Journal | Verify |
|---|---|---|---|
| Hide a skill folder from grok | Add its folder to `[skills].ignore` in `~/.grok/config.toml` | `backup <id> ~/.grok/config.toml` | skill gone from `grok inspect --json` `.skills` |
| Hide a whole plugin (incl. Claude Code plugins grok inherits) | Add the plugin ID to `[plugins].disabled` in `~/.grok/config.toml` | `backup` config.toml | plugin `enabled: false` or absent in `inspect.plugins`; if unchanged, roll back and report the ID format as unknown |
| Turn off an MCP server for grok | `grok mcp disable <name>` | `record --do "grok mcp disable <name>" --undo "grok mcp enable <name>"` | `grok mcp list` / `inspect.mcpServers` |
| Fix a truncated or conflicting grok rule | Edit the rule file (show the exact diff first) | `backup <rule file>` | `inspect.projectInstructions` size |
| Remove an auto-approve alias | Comment the line out in the shell rc file | `backup ~/.zshrc` | `grep` the line; new shell |

Grok reads Claude Code's `~/.claude/skills`, `~/.claude/plugins`, `CLAUDE.md` and `~/.claude.json`. Do not edit or park anything under `~/.claude` or `~/.claude.json` for a grok finding - that would change Claude Code too. Use the grok-side `ignore`/`disabled` settings. If the user wants a shared file changed, say both tools are affected and get approval for that explicitly.

TOML edits: keep other tables intact; if `[skills]` or `[plugins]` exists, extend its array instead of adding a second table. After editing, run `grok inspect --json` - a parse error means roll back immediately.

## agy

| Goal | Lever | Journal | Verify |
|---|---|---|---|
| Hide a user skill (global or workspace folder) | Park the folder | `park <id> <skill dir>` | skill gone from a fresh collector run |
| Hide a skill that came in via `skills.json` | Add a pattern to that entry's `exclude` | `backup <skills.json>` | collector shows `excluded: true` |
| Disable a plugin | `agy plugin disable <name>` | `record --do "agy plugin disable <name>" --undo "agy plugin enable <name>"` | `agy plugin list` |
| Disable an MCP server | `agy mcp disable <name>` | `record --do "agy mcp disable <name>" --undo "agy mcp enable <name>"` | `agy mcp list` |
| Fix hooks | Edit `hooks.json` | `backup <hooks.json>` | JSON parses; collector shows no `AGY-HOOKS-CONFIG` |
| Fix a truncated or conflicting rule | Edit the rule file | `backup <rule file>` | collector rule size / budget findings |
| Remove an auto-approve alias | Comment the line out | `backup ~/.zshrc` | `grep` the line |

Built-in agy skills (`~/.gemini/antigravity-cli/builtin/`) are part of the app; never park or edit them - an update would restore them anyway. Report them as `info` only.

If a skill folder is a symlink, parking moves only the link; the target stays where it was.
