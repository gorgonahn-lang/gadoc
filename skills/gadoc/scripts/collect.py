#!/usr/bin/env python3
"""gadoc inventory collector for grok (Grok Build) and Antigravity CLI (agy).

Read-only. Verifies the target directory, records the runtime environment,
runs the doctor/listing surfaces each installed CLI actually supports, and
collects skills, plugins, MCP servers, hooks, rule files, shell aliases and
recent-use evidence. Secrets are masked. Nothing on disk is modified except
the --out file.

Usage:
  python3 collect.py [--project DIR] [--harness grok|agy|both] [--out FILE]
                     [--summary] [--no-connect] [--usage-days N]
Exit codes: 0 ok, 2 target path invalid (nothing was run).
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
GROK_HOME = os.environ.get("GROK_HOME", os.path.join(HOME, ".grok"))
AGY_CONFIG = os.path.join(HOME, ".gemini", "config")
AGY_CLI_HOME = os.path.join(HOME, ".gemini", "antigravity-cli")
AGY_WORKSPACE_ROOTS = (".agents", ".agent", "_agents", "_agent")
SECRET_KEY = re.compile(r"(key|token|secret|passw|auth|cookie|credential|bearer)", re.I)
URL_QUERY = re.compile(r"(https?://[^\s\"'?#]+)\?[^\s\"']*")
AUTO_APPROVE = re.compile(
    r"--always-approve|--dangerously-skip-permissions|--permission-mode[ =]+(bypassPermissions|dontAsk)"
)

GROK_RULE_CHAR_CAP = 10000          # per AGENTS.md-style file, truncated beyond this
AGY_RULE_BYTE_CAP = 24000           # per rule file
AGY_RULES_TOKEN_BUDGET = 20000      # always-on + global rules, shared budget
DESCRIPTION_CHAR_WARN = 1024


# ---------------------------------------------------------------- helpers

def run(cmd, cwd=None, timeout=90):
    """Run a command; return command, exit code, doctor-style status and output."""
    rec = {"command": " ".join(cmd), "cwd": cwd}
    try:
        p = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        rec.update(rc=p.returncode, status="COMPLETED" if p.returncode == 0 else "ERROR",
                   out=p.stdout, err=mask_text(p.stderr[-2000:]))
    except FileNotFoundError:
        rec.update(rc=None, status="NOT_RUN", out="", err="not installed")
    except subprocess.TimeoutExpired:
        rec.update(rc=None, status="TIMEOUT", out="", err="timeout after %ss" % timeout)
    return rec


def mask_text(text):
    text = URL_QUERY.sub(r"\1?***", text or "")
    return re.sub(r"(?i)((?:api[_-]?key|token|secret|password|bearer)[\"'=: ]+)[^\s\"',]+", r"\1***", text)


def binary_info(name, env_var):
    """Real executable (skipping shell-script shims) plus any shim that shadows it on PATH."""
    forced = os.environ.get(env_var)
    shims, real = [], None
    for d in os.environ.get("PATH", "").split(os.pathsep) + ["/opt/homebrew/bin", "/usr/local/bin"]:
        cand = os.path.join(d, name)
        if not (os.path.isfile(cand) and os.access(cand, os.X_OK)):
            continue
        try:
            with open(os.path.realpath(cand), "rb") as f:
                is_script = f.read(2) == b"#!"
        except OSError:
            continue
        if is_script:
            if cand not in shims and real is None:
                shims.append(cand)
        elif real is None:
            real = cand
    real = forced or real or shutil.which(name)
    if not real:
        return None
    return {"path": real, "realpath": os.path.realpath(real), "shadowing_shims": shims}


def approx_tokens(n_chars):
    return (n_chars + 3) // 4


def read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit) if limit else f.read()
    except OSError:
        return None


def sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


RUBY_YAML = ('require "yaml"; require "json"; require "date"; '
             'd = YAML.safe_load(STDIN.read, permitted_classes: [Date, Time, Symbol]); '
             'puts JSON.generate(d.is_a?(Hash) ? d : {"__not_a_mapping__" => true})')
YAML_PARSER = None  # "pyyaml" | "ruby-psych" | "builtin-subset"; set on first use


def _yaml_load(block):
    """Parse a YAML block with a real YAML parser. Returns (dict or None on parse failure)."""
    global YAML_PARSER
    try:
        import yaml  # PyYAML, if installed
        YAML_PARSER = "pyyaml"
        try:
            d = yaml.safe_load(block)
            return d if isinstance(d, dict) else None
        except yaml.YAMLError:
            return None
    except ImportError:
        pass
    ruby = shutil.which("ruby")
    if ruby:
        YAML_PARSER = "ruby-psych"
        try:
            p = subprocess.run([ruby, "-e", RUBY_YAML], input=block, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True, timeout=20)
            if p.returncode == 0:
                d = json.loads(p.stdout)
                return None if d.get("__not_a_mapping__") else d
            return None
        except (subprocess.TimeoutExpired, ValueError, OSError):
            return None
    YAML_PARSER = "builtin-subset"
    return _subset_load(block)


def frontmatter(path):
    """YAML frontmatter of a SKILL.md / rule / command file, read with a real YAML parser so
    multi-line values and escapes survive. Returns None if the file is unreadable, {} if it has
    no frontmatter, and {"__parse_error__": True} if the block does not parse - a failure is
    recorded as unknown, never reconstructed."""
    text = read_text(path, 20000)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
    except StopIteration:
        return {"__parse_error__": True}
    d = _yaml_load("\n".join(lines[1:end]) + "\n")
    if d is None:
        return {"__parse_error__": True}
    return {str(k): ("" if v is None else v if isinstance(v, (bool, int, float)) else str(v).strip())
            for k, v in d.items()}


def _subset_load(block):
    """Fallback when no YAML library exists: top-level scalars and >- / | blocks only.
    Anything else (flow maps, anchors, lists) makes the block unparseable -> unknown."""
    lines = block.splitlines()
    if any(re.match(r"^\s*[&*!\[{]", l.split(":", 1)[-1].strip() or "x") for l in lines if ":" in l and not l.startswith(" ")):
        return None
    data, key, block = {}, None, []
    for line in lines:
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


def truthy(v):
    return str(v).strip().lower() in ("true", "yes", "1")


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in ("env", "headers") and isinstance(v, dict):
                out[k] = {ek: "***" for ek in v}
            elif k == "args" and isinstance(v, list):
                out[k] = ["***" if SECRET_KEY.search(str(a)) else a for a in v]
            elif SECRET_KEY.search(str(k)) and not isinstance(v, (dict, list)):
                out[k] = "***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return URL_QUERY.sub(r"\1?***", obj)
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
    fm = fm or {}
    rec["parse"] = "error" if fm.get("__parse_error__") else ("ok" if fm else ("unknown" if rec["exists"] else "missing"))
    rec["name"] = fm.get("name") or rec["dir_name"]
    rec["description"] = fm.get("description", "")
    rec["frontmatter_ok"] = bool(fm.get("name") and fm.get("description"))
    # A frontmatter that does not parse is unknown: never reconstruct its description or cost.
    rec["description_chars"] = "unknown" if rec["parse"] == "error" else len(rec["description"])
    rec["hash"] = sha256(skill_md) if rec["exists"] else None
    rec["invocation_policy"] = {
        "disable_model_invocation": truthy(fm.get("disable-model-invocation", "false")),
        "user_invocable": not (str(fm.get("user-invocable", "true")).strip().lower() == "false"),
    }
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


def scan_md_dir(base, scope, harness, extra=None):
    """Command / workflow files (*.md) directly inside `base`."""
    out = []
    for f in sorted(glob.glob(os.path.join(base, "*.md"))):
        fm = frontmatter(f) or {}
        parse = "error" if fm.get("__parse_error__") else "ok"
        desc = fm.get("description", "")
        rec = {"harness": harness, "scope": scope, "name": os.path.splitext(os.path.basename(f))[0],
               "path": f, "realpath": os.path.realpath(f), "hash": sha256(f), "parse": parse,
               "description_chars": "unknown" if parse == "error" else len(desc)}
        if extra:
            rec.update(extra)
        out.append(rec)
    return out


def rule_record(path, scope, harness):
    text = read_text(path) or ""
    fm = frontmatter(path) or {}
    return {
        "harness": harness, "scope": scope, "path": path, "realpath": os.path.realpath(path),
        "bytes": len(text.encode("utf-8")), "chars": len(text), "approx_tokens": approx_tokens(len(text)),
        "trigger": fm.get("trigger"), "hash": sha256(path),
    }


GADOC_SKILLS = ("gadoc", "gadoc-trim")


def _grok_loads(line):
    """SKILL.md paths loaded by a grok read_file tool call in one updates.jsonl line."""
    try:
        u = json.loads(line).get("params", {}).get("update", {})
    except ValueError:
        return []
    if u.get("sessionUpdate") != "tool_call" or u.get("title") != "read_file":
        return []
    p = str((u.get("rawInput") or {}).get("target_file", ""))
    return [p] if p.endswith("/SKILL.md") else []


def _agy_loads(line):
    """SKILL.md paths loaded by an agy view_file tool call in one transcript.jsonl line."""
    try:
        calls = json.loads(line).get("tool_calls") or []
    except ValueError:
        return []
    out = []
    for c in calls:
        if c.get("name") == "view_file":
            p = str((c.get("args") or {}).get("AbsolutePath", "")).strip("\"'")
            if p.endswith("/SKILL.md"):
                out.append(p)
    return out


def usage_from_logs(paths_glob, window_days, parser):
    """Map SKILL.md realpath -> {count, sessions, last} from sessions modified within the window.

    Counts only real skill loads (the agent reading a SKILL.md with its file-view tool).
    Sessions that loaded gadoc itself are audits that read other skills on purpose, so
    only the gadoc skills are counted from them."""
    cutoff = time.time() - window_days * 86400
    hits, files_read = {}, 0
    for f in glob.glob(paths_glob):
        try:
            if os.path.getmtime(f) < cutoff:
                continue
            files_read += 1
            loads = []
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "SKILL.md" in line:
                        loads += parser(line)
        except OSError:
            continue
        real = [os.path.realpath(p) for p in loads]
        audit = any(os.path.basename(os.path.dirname(p)) in GADOC_SKILLS for p in real)
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(f)).isoformat(timespec="seconds")
        for rp in set(real):
            if audit and os.path.basename(os.path.dirname(rp)) not in GADOC_SKILLS:
                continue
            h = hits.setdefault(rp, {"count": 0, "sessions": 0, "last": None})
            h["count"] += real.count(rp)
            h["sessions"] += 1
            h["last"] = max(h["last"] or mt, mt)
    return hits, files_read


def item(installed, enabled, exposed, invoked, usage, cost_chars, evidence, dependency="unknown"):
    return {"installed": installed, "enabled": enabled, "exposed": exposed, "invoked": invoked,
            "usage_window": usage.get("window"), "usage_source": usage.get("source"),
            "dependency": dependency, "always_cost_chars": cost_chars,
            "always_cost_tokens": approx_tokens(cost_chars) if isinstance(cost_chars, int) else "unknown",
            "evidence": evidence}


# ---------------------------------------------------------------- grok

def collect_grok(project, no_connect, usage_days):
    g = {"installed": False}
    info = binary_info("grok", "GADOC_GROK_BIN")
    if not info:
        return g
    binary = info["path"]
    g.update(installed=True, binary=info, home=GROK_HOME)
    g["version"] = run([binary, "--version"], timeout=20)["out"].strip()
    help_text = run([binary, "--help"], timeout=20)["out"]

    r = run([binary, "inspect", "--json"], cwd=project, timeout=120)
    try:
        g["inspect"] = redact(json.loads(r["out"]))
        g["inspect_status"] = "COMPLETED"
    except ValueError:
        g["inspect"] = None
        g["inspect_status"] = r["status"] if r["status"] != "COMPLETED" else "ERROR"
        g["inspect_error"] = (r["err"] or r["out"])[:500]
    ins = g["inspect"] or {}

    # Doctors. `grok doctor fix` applies changes, so only the read-only forms are run.
    doctors = []
    if re.search(r"^\s+doctor\b", help_text, re.M):
        d = run([binary, "doctor"], cwd=project, timeout=60)
        d["scope"] = "terminal, clipboard, color and input support only (not skills/plugins/rules)"
        d["out"] = mask_text(d["out"][-3000:])
        doctors.append(d)
    else:
        doctors.append({"command": "grok doctor", "status": "UNSUPPORTED"})
    project_mcp = any(os.path.isfile(os.path.join(dd, n)) for dd in dirs_root_to_cwd(project)
                      for n in (os.path.join(".grok", "config.toml"), ".mcp.json"))
    if no_connect:
        doctors.append({"command": "grok mcp doctor --json", "status": "NOT_RUN", "reason": "--no-connect"})
    elif project_mcp and not ins.get("projectTrusted"):
        doctors.append({"command": "grok mcp doctor --json", "status": "NOT_RUN",
                        "reason": "project defines MCP servers and is not trusted; connection state unknown"})
    else:
        d = run([binary, "mcp", "doctor", "--json"], cwd=project, timeout=180)
        d["scope"] = "MCP server configuration and connectivity (starts configured servers)"
        try:
            d["result"] = redact(json.loads(d["out"]))
        except ValueError:
            d["result"] = None
        d["out"] = mask_text(d["out"][-3000:])
        doctors.append(d)
    g["doctors"] = doctors

    cfg = os.path.join(GROK_HOME, "config.toml")
    text = read_text(cfg)
    g["config_toml"] = {"path": cfg, "exists": text is not None}
    if text is not None:
        g["config_toml"]["tables"] = re.findall(r"^\s*\[\[?([^\]]+)\]\]?\s*$", text, re.M)
        for section in ("skills", "plugins"):
            m = re.search(r"^\s*\[%s\]\s*$(.*?)(?=^\s*\[|\Z)" % section, text, re.M | re.S)
            if m:
                g["config_toml"][section] = m.group(1).strip()

    disk = []
    for d in dirs_root_to_cwd(project):
        disk += scan_skill_dir(os.path.join(d, ".grok", "skills"), "project", "grok")
        disk += scan_skill_dir(os.path.join(d, ".claude", "skills"), "project-claude-compat", "grok")
    disk += scan_skill_dir(os.path.join(GROK_HOME, "skills"), "user", "grok")
    disk += scan_skill_dir(os.path.join(HOME, ".claude", "skills"), "user-claude-compat", "grok")
    disk += scan_skill_dir(os.path.join(HOME, ".agents", "skills"), "user-agents-compat", "grok")
    g["skill_dirs_on_disk"] = disk

    # Commands: grok loads Claude Code plugin `commands/` and command folders alongside skills.
    m = re.search(r"disabled\s*=\s*\[([^\]]*)\]", g["config_toml"].get("plugins", ""))
    disabled = set(re.findall(r"\"([^\"]+)\"", m.group(1))) if m else set()
    commands = []
    for p in ins.get("plugins", []):
        if p.get("path"):
            commands += scan_md_dir(os.path.join(p["path"], "commands"), "plugin:" + str(p.get("name")), "grok",
                                    {"plugin": p.get("name"), "enabled": p.get("name") not in disabled})
    for d in dirs_root_to_cwd(project):
        commands += scan_md_dir(os.path.join(d, ".grok", "commands"), "project", "grok")
        commands += scan_md_dir(os.path.join(d, ".claude", "commands"), "project-claude-compat", "grok")
    commands += scan_md_dir(os.path.join(GROK_HOME, "commands"), "user", "grok")
    commands += scan_md_dir(os.path.join(HOME, ".claude", "commands"), "user-claude-compat", "grok")
    g["commands"] = commands

    usage, files_read = usage_from_logs(os.path.join(GROK_HOME, "sessions", "*", "*", "updates.jsonl"), usage_days, _grok_loads)
    usage_meta = {"window": "%dd" % usage_days,
                  "source": "grok session logs on this host (%d sessions; read_file of SKILL.md; gadoc audit sessions excluded)" % files_read}
    g["usage_meta"] = usage_meta

    items = []
    for s in ins.get("skills", []):
        path = (s.get("source") or {}).get("path")
        rec = skill_record(path, (s.get("source") or {}).get("type", "unknown"), "grok") if path else {}
        u = usage.get(os.path.realpath(path)) if path else None
        policy = rec.get("invocation_policy", {})
        exposed = "listed" if not policy.get("disable_model_invocation") else "user-invocable only"
        items.append(dict(kind="skill", name=s.get("name"), source=s.get("source"), hash=rec.get("hash"),
                          invocation_policy=policy, description_chars=len(s.get("description", "")),
                          recent_use=u,
                          **item(True, True, exposed, (u or {}).get("count", "unknown") if files_read else "unknown",
                                 usage_meta, len(s.get("description", "")) if exposed == "listed" else 0,
                                 "grok inspect --json")))
    for p in ins.get("plugins", []):
        items.append(dict(kind="plugin", name=p.get("name"), source={"type": p.get("scope"), "path": p.get("path")},
                          provides=p.get("provides"),
                          **item(True, p.get("enabled"), "see provided skills", "unknown", usage_meta, "sum of provided items",
                                 "grok inspect --json")))
    for m in ins.get("mcpServers", []):
        items.append(dict(kind="mcp", name=m.get("name"), detail=m,
                          **item(True, m.get("enabled", "unknown"), "unknown", "unknown", usage_meta, "unknown",
                                 "grok inspect --json")))
    for h in ins.get("hooks", []):
        items.append(dict(kind="hook", name=h.get("event"), source=h.get("source"),
                          **item(True, "unknown", "registered", "unknown", usage_meta, 0, "grok inspect --json")))
    for pi in ins.get("projectInstructions", []):
        items.append(dict(kind="rule", name=pi.get("path"), detail=pi,
                          **item(True, True, "always", "n/a", usage_meta, pi.get("sizeBytes", 0), "grok inspect --json")))
    for c in commands:
        items.append(dict(kind="command", name=c["name"], source={"type": c["scope"], "path": c["path"]},
                          hash=c["hash"], description_chars=c["description_chars"],
                          **item(True, c.get("enabled", True), "unknown (grok inspect does not list commands)",
                                 "unknown", usage_meta, "unknown", "filesystem scan")))
    g["items"] = items
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


def collect_agy(project, usage_days):
    a = {"installed": False}
    info = binary_info("agy", "GADOC_AGY_BIN")
    if not info:
        return a
    binary = info["path"]
    a.update(installed=True, binary=info, config_root=AGY_CONFIG)
    a["version"] = run([binary, "--version"], cwd=HOME, timeout=20)["out"].strip()
    help_text = run([binary, "--help"], cwd=HOME, timeout=20)["out"]
    a["doctors"] = [{"command": "agy doctor", "status": "UNSUPPORTED",
                     "reason": "agy --help lists no doctor/diagnose subcommand"}] \
        if not re.search(r"^\s+doctor\b", help_text, re.M) else [run([binary, "doctor"], cwd=project, timeout=60)]
    pl = run([binary, "plugin", "list"], cwd=project, timeout=60)
    ml = run([binary, "mcp", "list"], cwd=project, timeout=60)
    a["listings"] = [{"command": x["command"], "status": x["status"], "out": mask_text(x["out"].strip()[:3000])} for x in (pl, ml)]

    walk = dirs_root_to_cwd(project)
    workspace_roots = [os.path.join(d, r) for d in walk for r in AGY_WORKSPACE_ROOTS
                       if os.path.isdir(os.path.join(d, r))]

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
            pref = enabled_map.get(dname)
            user_pref = pref.get("enabled") if isinstance(pref, dict) else None
            enabled = user_pref if user_pref is not None else not declared_off
            plugins.append({"dir": pdir, "dir_name": dname, "scope": scope, "manifest_state": state,
                            "name": (data or {}).get("name", dname) if isinstance(data, dict) else dname,
                            "enabled": enabled})
            if enabled:
                for p in sorted(glob.glob(os.path.join(pdir, "rules", "*.md"))):
                    rules.append(rule_record(p, "plugin:" + dname, "agy"))

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

    mcp = []
    mcp_files = [(os.path.join(AGY_CONFIG, "mcp_config.json"), "global")]
    mcp_files += [(os.path.join(p["dir"], "mcp_config.json"), "plugin:" + p["dir_name"]) for p in plugins if p["enabled"]]
    for path, scope in mcp_files:
        data, state = load_json(path)
        if state != "ok":
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
                rec["serverUrl"] = URL_QUERY.sub(r"\1?***", srv["serverUrl"])
            mcp.append(rec)

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

    usage, files_read = usage_from_logs(
        os.path.join(AGY_CLI_HOME, "brain", "*", ".system_generated", "logs", "transcript.jsonl"), usage_days, _agy_loads)
    usage_meta = {"window": "%dd" % usage_days,
                  "source": "agy transcripts on this host (%d conversations; view_file of SKILL.md; gadoc audit sessions excluded)" % files_read}

    items = []
    for s in skills:
        u = usage.get(s["realpath"])
        listed = not s.get("excluded") and not s["invocation_policy"]["disable_model_invocation"]
        s["recent_use"] = u
        items.append(dict(kind="skill", name=s["name"], source={"type": s["scope"], "path": s["path"]},
                          hash=s["hash"], invocation_policy=s["invocation_policy"], recent_use=u,
                          **item(s["exists"], not s.get("excluded"), "listed" if listed else "not listed",
                                 (u or {}).get("count", 0 if files_read else "unknown"), usage_meta,
                                 s["description_chars"] if listed else 0, "filesystem scan")))
    for p in plugins:
        items.append(dict(kind="plugin", name=p["name"], source={"type": p["scope"], "path": p["dir"]},
                          **item(True, p["enabled"], "see provided items", "unknown", usage_meta,
                                 "sum of provided items", "filesystem scan + agy plugin list")))
    for m in mcp:
        if m.get("name"):
            items.append(dict(kind="mcp", name=m["name"], detail=m,
                              **item(True, not m.get("disabled"), "unknown", "unknown", usage_meta, "unknown",
                                     "mcp_config.json + agy mcp list")))
    seen = set()
    for r in rules:
        if r["realpath"] in seen:
            continue
        seen.add(r["realpath"])
        always = r["trigger"] in (None, "always_on")
        items.append(dict(kind="rule", name=r["path"], detail=r,
                          **item(True, True, "always" if always else r["trigger"], "n/a", usage_meta,
                                 r["chars"] if always else 0, "filesystem scan")))
    for h in hooks:
        items.append(dict(kind="hook", name=h["path"], source={"type": h["scope"]},
                          **item(True, "unknown", "registered", "unknown", usage_meta, 0, "filesystem scan")))

    # Workflows: agy's slash-command equivalent (deprecated in favour of skills; built-in
    # `migrate-workflows` converts them).
    workflows = []
    for base, scope in [(os.path.join(AGY_CONFIG, "global_workflows"), "global"),
                        (os.path.join(AGY_CONFIG, "workflows"), "global")] + \
                       [(os.path.join(r, "workflows"), "workspace") for r in workspace_roots]:
        workflows += scan_md_dir(base, scope, "agy")
    for cfg in [os.path.join(AGY_CONFIG, "workflows.json")] + [os.path.join(r, "workflows.json") for r in workspace_roots]:
        for e in json_entries(cfg):
            workflows += scan_md_dir(e["path"], "declared", "agy")
    for w in workflows:
        items.append(dict(kind="command", name=w["name"], source={"type": w["scope"], "path": w["path"]},
                          hash=w["hash"], description_chars=w["description_chars"],
                          **item(True, True, "workflow (slash command)", "unknown", usage_meta, "unknown",
                                 "filesystem scan")))
    a["workflows"] = workflows

    settings, _ = load_json(os.path.join(AGY_CLI_HOME, "settings.json"))
    a.update(project_dirs=walk, workspace_roots=workspace_roots, rules=rules, plugins=plugins,
             skills=skills, mcp_servers=mcp, hooks=hooks, usage_meta=usage_meta, items=items,
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

def add(findings, fid, harness, severity, cls, title, evidence, fix=None):
    findings.append({"id": fid, "harness": harness, "severity": severity, "class": cls, "title": title,
                     "evidence": evidence, "suggested_fix": fix})


def find_issues(data):
    f = []
    grok, agy = data.get("grok", {}), data.get("agy", {})
    FIX, CAND, OBS = "fix candidate", "cleanup candidate", "insufficient observation"

    if grok.get("installed"):
        ins = grok.get("inspect") or {}
        if not ins:
            add(f, "GROK-INSPECT", "grok", "high", FIX, "`grok inspect --json` did not complete", grok.get("inspect_error"))
        if grok["binary"].get("shadowing_shims"):
            add(f, "GROK-WRAPPER", "grok", "info", OBS, "a shell wrapper precedes the grok binary on PATH",
                grok["binary"]["shadowing_shims"], "diagnosis used the real binary; check the wrapper separately if runs differ")
        by_name = {}
        for rec in grok.get("skill_dirs_on_disk", []):
            by_name.setdefault(rec["name"], []).append(rec)
        for name, recs in sorted(by_name.items()):
            if len(recs) > 1 and len(set(r["realpath"] for r in recs)) > 1:
                add(f, "GROK-SHADOW", "grok", "medium", CAND,
                    "skill name `%s` exists in %d grok skill folders; only one wins" % (name, len(recs)),
                    [r["path"] for r in recs], "keep one copy or ignore the others via [skills].ignore")
        for rec in grok.get("skill_dirs_on_disk", []):
            if rec["symlink"] and not rec["exists"]:
                add(f, "GROK-BROKEN-SKILL", "grok", "medium", FIX, "broken skill symlink", rec["dir"])
            elif rec["parse"] == "error":
                add(f, "GROK-SKILL-PARSE", "grok", "medium", FIX, "SKILL.md frontmatter does not parse", rec["path"])
            elif rec["exists"] and not rec["frontmatter_ok"]:
                add(f, "GROK-SKILL-FRONTMATTER", "grok", "low", FIX, "SKILL.md missing name/description", rec["path"])
        loaded = ins.get("skills", [])
        compat = [s for s in loaded if "/.claude/" in (s.get("source") or {}).get("path", "")]
        if compat:
            add(f, "GROK-CLAUDE-COMPAT", "grok", "info", OBS,
                "%d of %d grok skills come from Claude Code folders/plugins" % (len(compat), len(loaded)),
                sorted(set((s.get("source") or {}).get("plugin_name") or "~/.claude/skills" for s in compat)),
                "grok-side [plugins].disabled / [skills].ignore; never edit ~/.claude")
        listed = [i for i in grok.get("items", []) if i["kind"] == "skill" and i["exposed"] == "listed"]
        total = sum(i["always_cost_chars"] for i in listed if isinstance(i["always_cost_chars"], int))
        add(f, "GROK-LISTING-COST", "grok", "info", OBS,
            "%d of %d skills listed to the model; descriptions total %d chars (~%d tokens per request)" % (
                len(listed), len(loaded), total, approx_tokens(total)), None)
        for s in loaded:
            if len(s.get("description", "")) > DESCRIPTION_CHAR_WARN:
                add(f, "GROK-LONG-DESC", "grok", "low", CAND, "skill `%s` description is %d chars" % (
                    s["name"], len(s["description"])), (s.get("source") or {}).get("path"))
        for pi in ins.get("projectInstructions", []):
            if pi.get("sizeBytes", 0) > GROK_RULE_CHAR_CAP:
                add(f, "GROK-RULE-TRUNCATED", "grok", "high", FIX,
                    "rule file over grok's 10,000-char cap is truncated", pi.get("path"), "shorten or split the file")
        for d in grok.get("doctors", []):
            if d["status"] != "COMPLETED":
                add(f, "GROK-DOCTOR-" + d["status"], "grok", "info", OBS,
                    "`%s` %s; that check is UNVERIFIED" % (d["command"], d["status"]), d.get("reason") or d.get("err"))
            res = d.get("result")
            if isinstance(res, dict) and (res.get("failing") or 0) > 0:
                add(f, "GROK-MCP-FAILING", "grok", "high", FIX, "`grok mcp doctor` reports failing servers",
                    res.get("servers") or res)

    if grok.get("installed") and grok.get("commands"):
        cmds = grok["commands"]
        on = [c for c in cmds if c.get("enabled", True)]
        add(f, "GROK-COMMANDS", "grok", "info", OBS,
            "%d command files found (%d from enabled sources); grok inspect does not list them, so exposure is unknown" % (
                len(cmds), len(on)),
            sorted(set("%s:%s" % (c["scope"], c["name"]) for c in cmds)),
            "treat like skills of the same source; a plugin's commands go away with the plugin")
        for c in cmds:
            if c["parse"] == "error":
                add(f, "GROK-COMMAND-PARSE", "grok", "low", FIX, "command frontmatter does not parse", c["path"])

    if agy.get("installed"):
        active = [s for s in agy.get("skills", []) if not s.get("excluded")]
        by_name = {}
        for s in active:
            by_name.setdefault(s["name"], []).append(s)
        for name, recs in sorted(by_name.items()):
            if len(recs) > 1 and len(set(r["realpath"] for r in recs)) > 1:
                add(f, "AGY-SHADOW", "agy", "medium", CAND,
                    "skill name `%s` defined in %d places; higher-priority scope wins" % (name, len(recs)),
                    ["%s (%s)" % (r["path"], r["scope"]) for r in recs], "keep one copy or exclude via skills.json")
        for s in agy.get("skills", []):
            if s["symlink"] and not s["exists"]:
                add(f, "AGY-BROKEN-SKILL", "agy", "medium", FIX, "broken skill symlink", s["dir"])
            elif s["parse"] == "error":
                add(f, "AGY-SKILL-PARSE", "agy", "medium", FIX, "SKILL.md frontmatter does not parse", s["path"])
            elif s["exists"] and not s["frontmatter_ok"]:
                add(f, "AGY-SKILL-FRONTMATTER", "agy", "medium", FIX, "SKILL.md missing name/description", s["path"])
            if isinstance(s["description_chars"], int) and s["description_chars"] > DESCRIPTION_CHAR_WARN:
                add(f, "AGY-LONG-DESC", "agy", "low", CAND, "skill `%s` description is %d chars" % (
                    s["name"], s["description_chars"]), s["path"])
        listed = [i for i in agy.get("items", []) if i["kind"] == "skill" and i["exposed"] == "listed"]
        total = sum(i["always_cost_chars"] for i in listed if isinstance(i["always_cost_chars"], int))
        add(f, "AGY-LISTING-COST", "agy", "info", OBS,
            "%d skills listed to the model; descriptions total %d chars (~%d tokens per request)" % (
                len(listed), total, approx_tokens(total)), None)
        seen, rule_tokens = set(), 0
        for r in agy.get("rules", []):
            if r["realpath"] in seen:
                continue
            seen.add(r["realpath"])
            if r["trigger"] in (None, "always_on"):
                rule_tokens += r["approx_tokens"]
            if r["bytes"] > AGY_RULE_BYTE_CAP:
                add(f, "AGY-RULE-TRUNCATED", "agy", "high", FIX, "rule file over agy's 24,000-byte cap is truncated", r["path"])
        if rule_tokens > AGY_RULES_TOKEN_BUDGET:
            add(f, "AGY-RULES-BUDGET", "agy", "high", FIX,
                "always-on rules ~%d tokens, over agy's 20,000-token rules budget" % rule_tokens, None)
        for m in agy.get("mcp_servers", []):
            if m.get("error"):
                add(f, "AGY-MCP-CONFIG", "agy", "high", FIX, "mcp_config.json cannot be parsed", "%s: %s" % (m["path"], m["error"]))
            elif m.get("command") and not m.get("command_found"):
                add(f, "AGY-MCP-MISSING-CMD", "agy", "high", FIX, "MCP server `%s` command not found" % m["name"], m["command"])
        for h in agy.get("hooks", []):
            if h.get("error"):
                add(f, "AGY-HOOKS-CONFIG", "agy", "high", FIX, "hooks.json cannot be parsed", "%s: %s" % (h["path"], h["error"]))
        if agy.get("workflows"):
            add(f, "AGY-WORKFLOWS", "agy", "low", CAND,
                "%d legacy workflow files; agy treats workflows as deprecated in favour of skills" % len(agy["workflows"]),
                [w["path"] for w in agy["workflows"]], "convert with the built-in migrate-workflows skill (it archives the originals)")
        if str(agy.get("config_json_state", "")).startswith("invalid"):
            add(f, "AGY-CONFIG-JSON", "agy", "high", FIX, "~/.gemini/config/config.json cannot be parsed", agy["config_json_state"])
        for d in agy.get("doctors", []):
            if d["status"] != "COMPLETED":
                add(f, "AGY-DOCTOR-" + d["status"], "agy", "info", OBS,
                    "`%s` %s; doctor verification is UNVERIFIED" % (d["command"], d["status"]), d.get("reason"))

    if grok.get("installed") and agy.get("installed"):
        gl = {os.path.realpath((s.get("source") or {}).get("path")): s["name"]
              for s in (grok.get("inspect") or {}).get("skills", []) if (s.get("source") or {}).get("path")}
        both = sorted(set(s["name"] for s in agy.get("skills", []) if s["realpath"] in gl))
        if both:
            add(f, "CROSS-SHARED-SKILL", "both", "info", OBS, "same skill file exposed to both grok and agy", both)

    for a in data.get("shell_aliases", []):
        harness = "grok" if re.search(r"\bgrok\b", a["text"]) else "agy"
        if a["auto_approve"] and harness in data:
            add(f, "SHELL-AUTO-APPROVE", harness, "high", OBS,
                "shell alias makes every session auto-approve all tool calls",
                "%s:%d  %s" % (a["file"], a["line"], a["text"]),
                "keep only if intended; use `command %s` for a prompting session" % harness)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    f.sort(key=lambda x: (order.get(x["severity"], 9), x["harness"], x["id"]))
    return f


# ---------------------------------------------------------------- main

def summary(data):
    lines = ["# gadoc inventory %s" % data["collected_at"], "project: %s  host: %s" % (data["project"], data["host"]), ""]
    for h in ("grok", "agy"):
        x = data.get(h, {})
        if not x.get("installed"):
            continue
        kinds = {}
        for i in x.get("items", []):
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
        docs = ", ".join("%s=%s" % (d["command"], d["status"]) for d in x.get("doctors", []))
        lines.append("%s %s: %s" % (h, x.get("version", "?"), ", ".join("%s %d" % kv for kv in sorted(kinds.items()))))
        lines.append("  doctor: %s" % docs)
        lines.append("  usage evidence: %s, %s" % (x["usage_meta"]["window"], x["usage_meta"]["source"]))
    lines.append("")
    for x in data["findings"]:
        lines.append("[%s] %s %s (%s): %s" % (x["severity"], x["harness"], x["id"], x["class"], x["title"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--harness", choices=("grok", "agy", "both"), default="both")
    ap.add_argument("--out")
    ap.add_argument("--summary", action="store_true", help="print a short text summary to stdout")
    ap.add_argument("--no-connect", action="store_true", help="do not run checks that start MCP servers")
    ap.add_argument("--usage-days", type=int, default=30, help="recent-use window in days (default 30)")
    args = ap.parse_args()
    project = os.path.abspath(os.path.expanduser(args.project))

    base = {"tool": "gadoc", "collected_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "host": socket.gethostname(), "os": platform.platform(), "project": project}
    if not os.path.exists(project) or not os.path.isdir(project):
        base.update(status="error", state="UNVERIFIED",
                    reason="target path does not exist" if not os.path.exists(project) else "target path is a file, not a directory")
        print(json.dumps(base, ensure_ascii=False, indent=2))
        return 2

    data = dict(base, status="ok", git_root=git_root(project))
    if args.harness in ("grok", "both"):
        data["grok"] = collect_grok(project, args.no_connect, args.usage_days)
    if args.harness in ("agy", "both"):
        data["agy"] = collect_agy(project, args.usage_days)
    data["shell_aliases"] = collect_shell()
    data["yaml_parser"] = YAML_PARSER or "not needed"
    data["findings"] = find_issues(data)

    blob = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        out = os.path.abspath(os.path.expanduser(args.out))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(blob)
    if args.summary or not args.out:
        print(summary(data) if args.summary else blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
