---
name: gadoc
description: Use when the grok (Grok Build) or Antigravity CLI (agy) harness needs a checkup - the wrong skill keeps getting picked, two skills look alike, sessions feel slow or bloated after adding skills, plugins or MCP servers, rule files (AGENTS.md, GEMINI.md, CLAUDE.md) may contradict each other, or the user asks to audit, diagnose or review their grok or agy setup. Read-only. Not for Claude Code or Codex, and not for applying changes (use gadoc-trim).
---

# gadoc - grok / agy harness checkup

Read-only diagnosis of what grok and agy load into every session. Evidence comes from the collector script and the harness's own listing commands, never from memory.

**Never modify anything in this skill.** Changes go through `gadoc-trim` after the user approves.

## Procedure

1. **Scope.** Target harness (`grok`, `agy`, or both; default both) and project directory (default: current directory). Name both in the report.
2. **Collect.** Run the collector from this skill's folder:
   ```bash
   python3 <this-skill-dir>/scripts/collect.py --project <dir> --harness <grok|agy|both> \
     --out ~/.gadoc/reports/inventory-$(date +%Y%m%d-%H%M%S).json --summary
   ```
   It runs `grok inspect --json`, `grok mcp doctor --json`, `agy plugin list`, `agy mcp list`, scans skill/rule/plugin/MCP/hook locations, and emits mechanical `findings`. Secrets are redacted.
3. **Judge.** Read the JSON, then work through [references/checks.md](references/checks.md). Mechanical findings are already in `findings`; add the judgment checks (overlapping skills, conflicting rules, unneeded exposure) by reading the actual files the inventory points to.
4. **Report** in the user's language, using the format below.

## Report format

```
## gadoc report - <harness> - <project> - <date>
Scope: <harness versions>, inventory: <json path>

### Summary
<3 lines: biggest problem, estimated per-request listing cost, count by severity>

### Findings
| # | Sev | Harness | What | Evidence (path:line or command) | Suggested fix (gadoc-trim lever) |

### Could not verify
<items marked unknown and why>
```

Rules for the report:
- Every finding cites a path or command output from this run.
- Severity: `high` = broken, truncated or unsafe now; `medium` = shadowing, overlap, contradiction; `low` = hygiene; `info` = cost and context.
- Something the collector could not read is `unknown`, never "OK" or zero.
- Grok also loads Claude Code skills, plugins, rules and MCP servers. Say where an item really lives (for example `~/.claude/plugins/...`), and propose grok-side levers so Claude Code is left untouched.
- End with: "To apply fixes, run gadoc-trim with this report."

## Quick reference

| Need | grok | agy |
|---|---|---|
| Full inventory | `grok inspect --json` | collector scan (no listing command) |
| MCP health | `grok mcp doctor --json` | `agy mcp list` + command check |
| Plugins | `inspect.plugins` | `agy plugin list`, `~/.gemini/config/plugins/` |
| Rule caps | 10,000 chars per file | 24,000 bytes per file, 20,000-token rules budget |
