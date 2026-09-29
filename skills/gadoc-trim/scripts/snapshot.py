#!/usr/bin/env python3
"""gadoc-trim snapshots: back up before changing, restore in one command, never clobber later edits.

Layout:
  ~/.gadoc/snapshots/<id>/manifest.json      what changed and its previous values
  ~/.gadoc/snapshots/<id>/files/             copies of files taken before editing
  ~/.gadoc/held/<id>/<scope>/<name>          items moved out of a load path (kept OUTSIDE the
                                             snapshot, so deleting a snapshot never deletes them)

Commands (run in this order during an apply):
  begin  --label TEXT                        -> prints <id>
  backup <id> FILE...                        copy each file before you edit it (absent files are recorded)
  hold   <id> PATH --scope SCOPE             move a skill folder / agent / hook file to the holding dir
  record <id> --do CMD --undo CMD            log a CLI toggle you ran (e.g. agy plugin disable x)
  commit <id>                                after editing: store post-change hashes (enables conflict checks)
  show <id> | list
  restore <id> [--run-undo]                  put everything back; a file edited after commit is reported, not overwritten
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

GADOC = os.path.join(os.path.expanduser("~"), ".gadoc")
SNAPS = os.path.join(GADOC, "snapshots")
HELD = os.path.join(GADOC, "held")
FORBIDDEN = ("/.claude/", "/.claude.json", "/.grok/bundled/", "/antigravity-cli/builtin/", "/.grok/auth.json")


def digest(path):
    if not os.path.lexists(path):
        return None
    if os.path.islink(path):
        return "link:" + os.readlink(path)
    if os.path.isdir(path):
        return "dir"
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def mpath(cid):
    return os.path.join(SNAPS, cid, "manifest.json")


def migrate_legacy(cid):
    """Snapshots made by gadoc 0.1 lived in ~/.gadoc/backups/<id> with a different manifest."""
    old_dir = os.path.join(GADOC, "backups", cid)
    old = os.path.join(old_dir, "manifest.json")
    if not os.path.isfile(old) or os.path.exists(os.path.join(SNAPS, cid)):
        return
    with open(old, encoding="utf-8") as f:
        o = json.load(f)
    os.makedirs(SNAPS, exist_ok=True)
    shutil.move(old_dir, os.path.join(SNAPS, cid))
    new_root = os.path.join(SNAPS, cid)
    m = {"id": cid, "label": o.get("label", ""), "created": o.get("created"), "committed": False,
         "restored": bool(o.get("rolled_back")), "commands": o.get("commands", []),
         "files": [{"path": e["orig"], "existed": e["existed"],
                    "copy": e["backup"].replace(old_dir, new_root) if e.get("backup") else None}
                   for e in o.get("files", [])],
         "held": [{"path": p["orig"], "held_at": p["parked"].replace(old_dir, new_root), "scope": "legacy"}
                  for p in o.get("parked", [])]}
    save(cid, m)


def load(cid):
    migrate_legacy(cid)
    if not os.path.isfile(mpath(cid)):
        sys.exit("unknown snapshot: %s" % cid)
    with open(mpath(cid), encoding="utf-8") as f:
        return json.load(f)


def save(cid, m):
    with open(mpath(cid), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def guard(path):
    p = path + ("/" if os.path.isdir(path) else "")
    for bad in FORBIDDEN:
        if bad in p:
            sys.exit("refusing to touch %s (owned by another runtime or bundled with the app)" % path)


def cmd_begin(a):
    cid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(os.path.join(SNAPS, cid, "files"), exist_ok=False)
    save(cid, {"id": cid, "label": a.label, "created": datetime.datetime.now().isoformat(timespec="seconds"),
               "files": [], "held": [], "commands": [], "committed": False, "restored": False})
    print(cid)


def cmd_backup(a):
    m = load(a.id)
    for f in a.files:
        src = os.path.abspath(os.path.expanduser(f))
        guard(src)
        if any(x["path"] == src for x in m["files"]):
            continue
        if os.path.isdir(src) and not os.path.islink(src):
            sys.exit("backup takes files; use hold for folders: %s" % src)
        e = {"path": src, "existed": os.path.lexists(src), "pre_hash": digest(src)}
        if e["existed"]:
            dst = os.path.join(SNAPS, a.id, "files", "%03d-%s" % (len(m["files"]), os.path.basename(src)))
            shutil.copy2(src, dst, follow_symlinks=False)
            e["copy"] = dst
        m["files"].append(e)
        print("backed up" if e["existed"] else "recorded absent", src)
    save(a.id, m)


def cmd_hold(a):
    m = load(a.id)
    src = os.path.abspath(os.path.expanduser(a.path))
    guard(src)
    if not os.path.lexists(src):
        sys.exit("not found: %s" % src)
    dst = os.path.join(HELD, a.id, a.scope, os.path.basename(src))
    if os.path.lexists(dst):
        sys.exit("collision: %s already exists; nothing moved" % dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    m["held"].append({"path": src, "held_at": dst, "scope": a.scope})
    save(a.id, m)
    print("held", src, "->", dst)


def cmd_record(a):
    m = load(a.id)
    m["commands"].append({"do": a.do, "undo": a.undo, "at": datetime.datetime.now().isoformat(timespec="seconds")})
    save(a.id, m)
    print("recorded:", a.do, "| undo:", a.undo)


def cmd_commit(a):
    m = load(a.id)
    for e in m["files"]:
        e["post_hash"] = digest(e["path"])
    m["committed"] = True
    save(a.id, m)
    print("committed", a.id)


def cmd_show(a):
    print(json.dumps(load(a.id), ensure_ascii=False, indent=2))


def cmd_list(_a):
    if not os.path.isdir(SNAPS):
        return
    for cid in sorted(os.listdir(SNAPS)):
        if not os.path.isfile(mpath(cid)):
            continue
        m = load(cid)
        print("%s  %-40s files=%d held=%d commands=%d%s" % (
            cid, m["label"][:40], len(m["files"]), len(m["held"]), len(m["commands"]),
            "  (restored)" if m.get("restored") else ""))


def cmd_restore(a):
    m = load(a.id)
    conflicts = []
    for e in reversed(m["files"]):
        now = digest(e["path"])
        if "post_hash" in e and now != e["post_hash"]:
            conflicts.append(e["path"])
            print("CONFLICT (changed after the snapshot; left alone):", e["path"])
            continue
        if e["existed"]:
            shutil.copy2(e["copy"], e["path"], follow_symlinks=False)
            print("restored", e["path"])
        elif os.path.lexists(e["path"]):
            os.remove(e["path"])
            print("removed (did not exist before)", e["path"])
    for h in reversed(m["held"]):
        if os.path.lexists(h["path"]):
            conflicts.append(h["path"])
            print("CONFLICT (path occupied again; held copy kept at %s):" % h["held_at"], h["path"])
            continue
        os.makedirs(os.path.dirname(h["path"]), exist_ok=True)
        shutil.move(h["held_at"], h["path"])
        print("moved back", h["path"])
    for c in reversed(m["commands"]):
        if a.run_undo:
            r = subprocess.run(c["undo"], shell=True)
            print("undo %s: %s" % ("ok" if r.returncode == 0 else "rc=%d" % r.returncode, c["undo"]))
        else:
            print("run to undo:", c["undo"])
    m["restored"] = not conflicts
    m["restore_conflicts"] = conflicts
    save(a.id, m)
    if conflicts:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("begin"); s.add_argument("--label", required=True); s.set_defaults(fn=cmd_begin)
    s = sub.add_parser("backup"); s.add_argument("id"); s.add_argument("files", nargs="+"); s.set_defaults(fn=cmd_backup)
    for name in ("hold", "park"):
        s = sub.add_parser(name); s.add_argument("id"); s.add_argument("path")
        s.add_argument("--scope", default="user"); s.set_defaults(fn=cmd_hold)
    s = sub.add_parser("record"); s.add_argument("id"); s.add_argument("--do", required=True)
    s.add_argument("--undo", required=True); s.set_defaults(fn=cmd_record)
    s = sub.add_parser("commit"); s.add_argument("id"); s.set_defaults(fn=cmd_commit)
    s = sub.add_parser("show"); s.add_argument("id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("list"); s.set_defaults(fn=cmd_list)
    for name in ("restore", "rollback"):
        s = sub.add_parser(name); s.add_argument("id"); s.add_argument("--run-undo", action="store_true")
        s.set_defaults(fn=cmd_restore)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
