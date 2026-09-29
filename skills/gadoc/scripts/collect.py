#!/usr/bin/env python3
"""gadoc inventory collector.

Read-only snapshot of the grok (Grok Build) and Antigravity CLI (agy) harness:
skills, plugins, MCP servers, hooks, rule files and shell aliases, plus the
findings that can be decided mechanically. Nothing on disk is modified.

Usage:
  python3 collect.py [--project DIR] [--harness grok|agy|both] [--out FILE] [--summary]
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
GROK_HOME = os.environ.get("GROK_HOME", os.path.join(HOME, ".grok"))
AGY_CONFIG = os.path.join(HOME, ".gemini", "config")
AGY_CLI_HOME = os.path.join(HOME, ".gemini", "antigravity-cli")
AGY_WORKSPACE_ROOTS = (".agents", ".agent", "_agents", "_agent")
SECRET_KEY = re.compile(r"(key|token|secret|passw|auth|cookie|credential|bearer)", re.I)
AUTO_APPROVE = re.compile(
    r"--always-approve|--dangerously-skip-permissions|--permission-mode[ =]+(bypassPermissions|dontAsk)"
)

# Limits documented by each harness.
GROK_RULE_CHAR_CAP = 10000          # per AGENTS.md-style file, truncated beyond this
AGY_RULE_BYTE_CAP = 24000           # per rule file
AGY_RULES_TOKEN_BUDGET = 20000      # always-on + global rules, shared budget
DESCRIPTION_CHAR_WARN = 1024


# ---------------------------------------------------------------- helpers

def run(cmd, cwd=None, timeout=90):
    try:
        p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        return {"rc": p.returncode, "out": p.stdout, "err": p.stderr[-2000:]}
    except FileNotFoundError:
        return {"rc": None, "out": "", "err": "not installed"}
    except subprocess.TimeoutExpired:
        return {"rc": None, "out": "", "err": "timeout after %ss" % timeout}


def real_binary(name, env_var):
    """Find the real executable, skipping shell-script wrappers (e.g. terminal shims)."""
    forced = os.environ.get(env_var)
    if forced:
        return forced
    for d in os.environ.get("PATH", "").split(os.pathsep) + ["/opt/homebrew/bin", "/usr/local/bin"]:
        cand = os.path.join(d, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            try:
                with open(os.path.realpath(cand), "rb") as f:
                    head = f.read(2)
            except OSError:
                continue
            if head != b"#!":
                return cand
    return shutil.which(name)


def approx_tokens(n_chars):
    return (n_chars + 3) // 4


def read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit) if limit else f.read()
    except OSError:
        return None


def frontmatter(path):
    """Minimal YAML frontmatter reader for name/description (handles >- and | blocks)."""
    text = read_text(path, 20000)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data, key, block = {}, None, []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            if key and block:
                data[key] = " ".join(s.strip() for s in block).strip()
            key, val = m.group(1), m.group(2).strip()
            block = []
            if val in (">", ">-", "|", "|-", ">+", "|+"):
                data[key] = ""
            else:
                data[key] = val.strip("\"'")
                key = None if val else key
        elif key is not None:
            block.append(line)
    if key and block:
        data[key] = " ".join(s.strip() for s in block).strip()
    return data


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("env", "headers") and isinstance(v, dict):
                out[k] = {ek: "***" for ek in v}
            elif SECRET_KEY.search(str(k)) and not isinstance(v, (dict, list)):
                out[k] = "***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def load_json(path):
    text = read_text(path)
    if text is None:
        return None, "missing"
    if not text.strip():
        return {}, "empty"
    try:
        return json.loads(text), "ok"
    except ValueError as e:
        return None, "invalid json: %s" % e


def git_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def dirs_root_to_cwd(cwd):
    root = git_root(cwd)
    if not root:
        return [os.path.abspath(cwd)]
    out, d = [], os.path.abspath(cwd)
    while True:
        out.append(d)
        if d == root:
            break
        d = os.path.dirname(d)
    return list(reversed(out))


def skill_record(skill_md, scope, harness, extra=None):
    d = os.path.dirname(skill_md)
    rec = {
        "harness": harness, "scope": scope, "dir": d, "dir_name": os.path.basename(d),
        "path": skill_md, "realpath": os.path.realpath(skill_md),
        "symlink": os.path.islink(d), "exists": os.path.isfile(skill_md),
    }
    fm = frontmatter(skill_md) if rec["exists"] else None
    rec["name"] = (fm or {}).get("name") or rec["dir_name"]
    rec["description"] = (fm or {}).get("description", "")
    rec["frontmatter_ok"] = bool(fm and fm.get("name") and fm.get("description"))
    rec["description_chars"] = len(rec["description"])
    if extra:
        rec.update(extra)
    return rec


def scan_skill_dir(base, scope, harness, extra=None):
    out = []
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        d = os.path.join(base, entry)
        if entry.startswith(".") or not (os.path.isdir(d) or os.path.islink(d)):
            continue
        out.append(skill_record(os.path.join(d, "SKILL.md"), scope, harness, extra))
    return out


def rule_record(path, scope, harness):
    text = read_text(path) or ""
    return {
        "harness": harness, "scope": scope, "path": path, "realpath": os.path.realpath(path),
        "bytes": len(text.encode("utf-8")), "chars": len(text), "approx_tokens": approx_tokens(len(text)),
    }


# ---------------------------------------------------------------- grok

def collect_grok(project):
    g = {"installed": False}
    binary = real_binary("grok", "GADOC_GROK_BIN")
    if not binary:
        return g
    g.update(installed=True, binary=binary, home=GROK_HOME)
    g["version"] = run([binary, "--version"], timeout=20)["out"].strip()

    r = run([binary, "inspect", "--json"], cwd=project, timeout=120)
    try:
        g["inspect"] = redact(json.loads(r["out"]))
    except ValueError:
        g["inspect"] = None
        g["inspect_error"] = (r["err"] or r["out"])[:500]

    r = run([binary, "mcp", "doctor", "--json"], cwd=project, timeout=180)
    try:
        g["mcp_doctor"] = redact(json.loads(r["out"]))
    except ValueError:
        g["mcp_doctor"] = {"rc": r["rc"], "text": (r["out"] or r["err"])[:2000]}

    cfg = os.path.join(GROK_HOME, "config.toml")
    text = read_text(cfg)
    g["config_toml"] = {"path": cfg, "exists": text is not None}
    if text is not None:
        tables = re.findall(r"^\s*\[\[?([^\]]+)\]\]?\s*$", text, re.M)
        g["config_toml"]["tables"] = tables
        for section in ("skills", "plugins"):
            m = re.search(r"^\s*\[%s\]\s*$(.*?)(?=^\s*\[|\Z)" % section, text, re.M | re.S)
            if m:
                g["config_toml"][section] = m.group(1).strip()

    # Skill folders on disk that grok scans, so shadowing can be seen even though
    # `grok inspect` only lists the winner of each name.
    disk = []
    for d in dirs_root_to_cwd(project):
        disk += scan_skill_dir(os.path.join(d, ".grok", "skills"), "project", "grok")
        disk += scan_skill_dir(os.path.join(d, ".claude", "skills"), "project-claude-compat", "grok")
    disk += scan_skill_dir(os.path.join(GROK_HOME, "skills"), "user", "grok")
    disk += scan_skill_dir(os.path.join(HOME, ".claude", "skills"), "user-claude-compat", "grok")
    disk += scan_skill_dir(os.path.join(HOME, ".agents", "skills"), "user-agents-compat", "grok")
    g["skill_dirs_on_disk"] = disk
    return g


# ---------------------------------------------------------------- agy

def json_entries(config_path):
    data, _ = load_json(config_path)
    out = []
    if isinstance(data, dict):
        for e in data.get("entries", []) or []:
            p = e.get("path", "")
            if p.startswith("~/"):
                p = os.path.join(HOME, p[2:])
            elif not p.startswith("/"):
                p = os.path.join(git_root(os.path.dirname(config_path)) or os.path.dirname(config_path), p)
            out.append({"path": p, "exclude": e.get("exclude", []), "include_only": e.get("include_only")})
    return out


def collect_agy(project):
    a = {"installed": False}
    binary = real_binary("agy", "GADOC_AGY_BIN")
    if not binary:
        return a
    a.update(installed=True, binary=binary, config_root=AGY_CONFIG)
    a["version"] = run([binary, "--version"], cwd=HOME, timeout=20)["out"].strip()
    a["plugin_list_text"] = run([binary, "plugin", "list"], cwd=project, timeout=60)["out"].strip()
    a["mcp_list_text"] = run([binary, "mcp", "list"], cwd=project, timeout=60)["out"].strip()

    walk = dirs_root_to_cwd(project)
    workspace_roots = [os.path.join(d, r) for d in walk for r in AGY_WORKSPACE_ROOTS
                       if os.path.isdir(os.path.join(d, r))]

    # Rules
    rules = []
    for name in ("AGENTS.md", "GEMINI.md"):
        p = os.path.join(AGY_CONFIG, name)
        if os.path.isfile(p):
            rules.append(rule_record(p, "global", "agy"))
    for d in walk:
        for name in ("AGENTS.md", "GEMINI.md"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                rules.append(rule_record(p, "project", "agy"))
    for root in workspace_roots:
        for p in sorted(glob.glob(os.path.join(root, "rules", "*.md"))):
            rules.append(rule_record(p, "workspace-rules", "agy"))

    # Plugins
    config_json, config_state = load_json(os.path.join(AGY_CONFIG, "config.json"))
    enabled_map = (config_json or {}).get("plugins", {}) if isinstance(config_json, dict) else {}
    plugin_dirs = [(os.path.join(AGY_CONFIG, "plugins"), "global")]
    plugin_dirs += [(os.path.join(r, "plugins"), "workspace") for r in workspace_roots]
    for cfg in [os.path.join(AGY_CONFIG, "plugins.json")] + [os.path.join(r, "plugins.json") for r in workspace_roots]:
        for e in json_entries(cfg):
            plugin_dirs.append((e["path"], "declared"))
    plugins = []
    for base, scope in plugin_dirs:
        for manifest in sorted(glob.glob(os.path.join(base, "*", "plugin.json"))):
            pdir = os.path.dirname(manifest)
            data, state = load_json(manifest)
            dname = os.path.basename(pdir)
            declared_off = bool(isinstance(data, dict) and data.get("disabled"))
            user_pref = enabled_map.get(dname, {}).get("enabled") if isinstance(enabled_map.get(dname), dict) else None
            enabled = user_pref if user_pref is not None else not declared_off
            plugins.append({"dir": pdir, "dir_name": dname, "scope": scope, "manifest_state": state,
                            "name": (data or {}).get("name", dname) if isinstance(data, dict) else dname,
                            "enabled": enabled})
            if enabled:
                for p in sorted(glob.glob(os.path.join(pdir, "rules", "*.md"))):
                    rules.append(rule_record(p, "plugin:" + dname, "agy"))

    # Skills (priority: workspace > declared > global > builtin)
    skills = []
    for root in workspace_roots:
        skills += scan_skill_dir(os.path.join(root, "skills"), "workspace", "agy")
    for cfg in [os.path.join(r, "skills.json") for r in workspace_roots] + [os.path.join(AGY_CONFIG, "skills.json")]:
        for e in json_entries(cfg):
            for rec in scan_skill_dir(e["path"], "declared", "agy"):
                if any(re.search(pat, rec["dir_name"]) for pat in e["exclude"]):
                    rec["excluded"] = True
                skills.append(rec)
    skills += scan_skill_dir(os.path.join(AGY_CONFIG, "skills"), "global", "agy")
    for p in plugins:
        if p["enabled"]:
            skills += scan_skill_dir(os.path.join(p["dir"], "skills"), "plugin:" + p["dir_name"], "agy")
    skills += scan_skill_dir(os.path.join(AGY_CLI_HOME, "builtin", "skills"), "builtin", "agy")

    # MCP servers
    mcp = []
    mcp_files = [(os.path.join(AGY_CONFIG, "mcp_config.json"), "global")]
    mcp_files += [(os.path.join(p["dir"], "mcp_config.json"), "plugin:" + p["dir_name"]) for p in plugins if p["enabled"]]
    for path, scope in mcp_files:
        data, state = load_json(path)
        if state not in ("ok",):
            if state not in ("missing", "empty"):
                mcp.append({"scope": scope, "path": path, "error": state})
            continue
        for name, srv in ((data or {}).get("mcpServers") or {}).items():
            srv = srv or {}
            rec = {"name": name, "scope": scope, "path": path,
                   "transport": "sse" if srv.get("serverUrl") else "stdio",
                   "disabled": bool(srv.get("disabled")), "env_keys": sorted((srv.get("env") or {}).keys())}
            if srv.get("command"):
                rec["command"] = srv["command"]
                rec["command_found"] = bool(shutil.which(srv["command"]) or os.path.isfile(srv["command"]))
            if srv.get("serverUrl"):
                rec["serverUrl"] = srv["serverUrl"]
            mcp.append(rec)

    # Hooks
    hooks = []
    hook_files = [(os.path.join(AGY_CONFIG, "hooks.json"), "global"),
                  (os.path.join(AGY_CLI_HOME, "hooks.json"), "cli")]
    hook_files += [(os.path.join(r, "hooks.json"), "workspace") for r in workspace_roots]
    hook_files += [(os.path.join(p["dir"], "hooks.json"), "plugin:" + p["dir_name"]) for p in plugins if p["enabled"]]
    for path, scope in hook_files:
        data, state = load_json(path)
        if state == "ok" and data:
            hooks.append({"scope": scope, "path": path, "hooks": redact(data)})
        elif state not in ("missing", "empty"):
            hooks.append({"scope": scope, "path": path, "error": state})

    settings, _ = load_json(os.path.join(AGY_CLI_HOME, "settings.json"))
    a.update(project_dirs=walk, workspace_roots=workspace_roots, rules=rules, plugins=plugins,
             skills=skills, mcp_servers=mcp, hooks=hooks,
             config_json_state=config_state, settings=redact(settings or {}))
    return a


# ---------------------------------------------------------------- shell

def collect_shell():
    out = []
    for rc in (".zshrc", ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile"):
        p = os.path.join(HOME, rc)
        text = read_text(p)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b(alias|function)\b.*\b(grok|agy)\b", line) or re.match(r"^\s*(grok|agy)\s*\(\)", line):
                out.append({"file": p, "line": i, "text": line.strip(),
                            "auto_approve": bool(AUTO_APPROVE.search(line))})
    return out


# ---------------------------------------------------------------- findings

def add(findings, fid, harness, severity, title, evidence, fix=None):
    findings.append({"id": fid, "harness": harness, "severity": severity, "title": title,
                     "evidence": evidence, "suggested_fix": fix})


def find_issues(data):
    f = []
    grok, agy = data.get("grok", {}), data.get("agy", {})

    # grok
    if grok.get("installed"):
        ins = grok.get("inspect") or {}
        if not ins:
            add(f, "GROK-INSPECT", "grok", "high", "`grok inspect --json` failed", grok.get("inspect_error"))
        loaded = ins.get("skills", [])
        by_name = {}
        for rec in grok.get("skill_dirs_on_disk", []):
            by_name.setdefault(rec["name"], []).append(rec)
        for name, recs in sorted(by_name.items()):
            paths = sorted(set(r["realpath"] for r in recs))
            if len(recs) > 1 and len(paths) > 1:
                add(f, "GROK-SHADOW", "grok", "medium",
                    "skill name `%s` exists in %d grok skill folders; only one wins" % (name, len(recs)),
                    [r["path"] for r in recs], "keep one copy or ignore the others via [skills].ignore")
        for rec in grok.get("skill_dirs_on_disk", []):
            if rec["symlink"] and not rec["exists"]:
                add(f, "GROK-BROKEN-SKILL", "grok", "medium", "broken skill symlink", rec["dir"], "remove or repoint the link")
            elif rec["exists"] and not rec["frontmatter_ok"]:
                add(f, "GROK-SKILL-FRONTMATTER", "grok", "low", "SKILL.md missing name/description", rec["path"])
        compat = [s for s in loaded if (s.get("source") or {}).get("type") in ("plugin", "user")
                  and "/.claude/" in (s.get("source") or {}).get("path", "")]
        if compat:
            add(f, "GROK-CLAUDE-COMPAT", "grok", "info",
                "%d of %d grok skills come from Claude Code folders/plugins" % (len(compat), len(loaded)),
                sorted(set((s.get("source") or {}).get("plugin_name") or "~/.claude/skills" for s in compat)),
                "if grok does not need them, use [plugins].disabled / [skills].ignore in ~/.grok/config.toml")
        total_desc = sum(len(s.get("description", "")) for s in loaded)
        add(f, "GROK-LISTING-COST", "grok", "info",
            "%d skills listed; descriptions total %d chars (~%d tokens per request)" % (len(loaded), total_desc, approx_tokens(total_desc)),
            None)
        for s in loaded:
            if len(s.get("description", "")) > DESCRIPTION_CHAR_WARN:
                add(f, "GROK-LONG-DESC", "grok", "low", "skill `%s` description is %d chars" % (s["name"], len(s["description"])),
                    (s.get("source") or {}).get("path"))
        for pi in ins.get("projectInstructions", []):
            if pi.get("sizeBytes", 0) > GROK_RULE_CHAR_CAP:
                add(f, "GROK-RULE-TRUNCATED", "grok", "high",
                    "rule file over grok's 10,000-char cap is truncated", pi.get("path"), "shorten or split the file")
        doc = grok.get("mcp_doctor")
        if isinstance(doc, dict) and doc.get("rc") not in (None, 0) and "text" in doc:
            add(f, "GROK-MCP-DOCTOR", "grok", "medium", "`grok mcp doctor` reported a problem", doc.get("text", "")[:400])

    # agy
    if agy.get("installed"):
        active = [s for s in agy.get("skills", []) if not s.get("excluded")]
        by_name = {}
        for s in active:
            by_name.setdefault(s["name"], []).append(s)
        for name, recs in sorted(by_name.items()):
            if len(recs) > 1 and len(set(r["realpath"] for r in recs)) > 1:
                add(f, "AGY-SHADOW", "agy", "medium",
                    "skill name `%s` defined in %d places; higher-priority scope wins" % (name, len(recs)),
                    ["%s (%s)" % (r["path"], r["scope"]) for r in recs], "keep one copy or exclude via skills.json")
        for s in agy.get("skills", []):
            if s["symlink"] and not s["exists"]:
                add(f, "AGY-BROKEN-SKILL", "agy", "medium", "broken skill symlink", s["dir"], "remove or repoint the link")
            elif s["exists"] and not s["frontmatter_ok"]:
                add(f, "AGY-SKILL-FRONTMATTER", "agy", "medium", "SKILL.md missing name/description", s["path"])
            if s["description_chars"] > DESCRIPTION_CHAR_WARN:
                add(f, "AGY-LONG-DESC", "agy", "low", "skill `%s` description is %d chars" % (s["name"], s["description_chars"]), s["path"])
        total_desc = sum(s["description_chars"] for s in active)
        add(f, "AGY-LISTING-COST", "agy", "info",
            "%d skills visible; descriptions total %d chars (~%d tokens per request)" % (len(active), total_desc, approx_tokens(total_desc)),
            None)
        seen, rule_tokens = set(), 0
        for r in agy.get("rules", []):
            if r["realpath"] in seen:
                continue
            seen.add(r["realpath"])
            rule_tokens += r["approx_tokens"]
            if r["bytes"] > AGY_RULE_BYTE_CAP:
                add(f, "AGY-RULE-TRUNCATED", "agy", "high", "rule file over agy's 24,000-byte cap is truncated", r["path"])
        if rule_tokens > AGY_RULES_TOKEN_BUDGET:
            add(f, "AGY-RULES-BUDGET", "agy", "high",
                "rules total ~%d tokens, over agy's 20,000-token rules budget (extras become file pointers)" % rule_tokens, None)
        for m in agy.get("mcp_servers", []):
            if m.get("error"):
                add(f, "AGY-MCP-CONFIG", "agy", "high", "mcp_config.json cannot be parsed", "%s: %s" % (m["path"], m["error"]))
            elif m.get("command") and not m.get("command_found"):
                add(f, "AGY-MCP-MISSING-CMD", "agy", "high", "MCP server `%s` command not found" % m["name"], m["command"])
        for h in agy.get("hooks", []):
            if h.get("error"):
                add(f, "AGY-HOOKS-CONFIG", "agy", "high", "hooks.json cannot be parsed", "%s: %s" % (h["path"], h["error"]))
        if agy.get("config_json_state", "").startswith("invalid"):
            add(f, "AGY-CONFIG-JSON", "agy", "high", "~/.gemini/config/config.json cannot be parsed", agy["config_json_state"])

    # cross-harness
    if grok.get("installed") and agy.get("installed"):
        gl = {(s.get("source") or {}).get("path") and os.path.realpath((s.get("source") or {}).get("path")): s["name"]
              for s in (grok.get("inspect") or {}).get("skills", [])}
        both = sorted(set(gl.values()) & set(s["name"] for s in agy.get("skills", []) if s["realpath"] in gl))
        if both:
            add(f, "CROSS-SHARED-SKILL", "both", "info", "same skill file exposed to both grok and agy", both)

    for a in data.get("shell_aliases", []):
        harness = "grok" if re.search(r"\bgrok\b", a["text"]) else "agy"
        if a["auto_approve"] and harness in data:
            add(f, "SHELL-AUTO-APPROVE", harness, "high",
                "shell alias makes every session auto-approve all tool calls",
                "%s:%d  %s" % (a["file"], a["line"], a["text"]),
                "keep only if intended; use `command %s` for a prompting session" % harness)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    f.sort(key=lambda x: (order.get(x["severity"], 9), x["harness"], x["id"]))
    return f


# ---------------------------------------------------------------- main

def summary(data):
    lines = ["# gadoc inventory %s" % data["collected_at"], "project: %s" % data["project"], ""]
    g, a = data.get("grok", {}), data.get("agy", {})
    if g.get("installed"):
        ins = g.get("inspect") or {}
        lines.append("grok %s: skills %d, plugins %d, mcp %d, hooks %d, rule files %d" % (
            g.get("version", "?"), len(ins.get("skills", [])), len(ins.get("plugins", [])),
            len(ins.get("mcpServers", [])), len(ins.get("hooks", [])), len(ins.get("projectInstructions", []))))
    if a.get("installed"):
        lines.append("agy %s: skills %d, plugins %d, mcp %d, hook files %d, rule files %d" % (
            a.get("version", "?"), len(a.get("skills", [])), len(a.get("plugins", [])),
            len(a.get("mcp_servers", [])), len(a.get("hooks", [])), len(a.get("rules", []))))
    lines.append("")
    for x in data["findings"]:
        lines.append("[%s] %s %s: %s" % (x["severity"], x["harness"], x["id"], x["title"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--harness", choices=("grok", "agy", "both"), default="both")
    ap.add_argument("--out")
    ap.add_argument("--summary", action="store_true", help="print a short text summary to stdout")
    args = ap.parse_args()
    project = os.path.abspath(os.path.expanduser(args.project))

    data = {"tool": "gadoc", "collected_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "project": project, "git_root": git_root(project)}
    if args.harness in ("grok", "both"):
        data["grok"] = collect_grok(project)
    if args.harness in ("agy", "both"):
        data["agy"] = collect_agy(project)
    data["shell_aliases"] = collect_shell()
    data["findings"] = find_issues(data)

    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(blob)
    if args.summary or not args.out:
        print(summary(data) if args.summary else blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
