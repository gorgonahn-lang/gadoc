#!/usr/bin/env python3
"""gadoc-trim change journal: back up before changing, roll back in one command.

Every change set lives in ~/.gadoc/backups/<id>/ with a manifest.json.

  python3 snapshot.py begin --label "trim grok"          -> prints <id>
  python3 snapshot.py backup <id> FILE [FILE ...]         copy files (absent files are recorded too)
  python3 snapshot.py park <id> DIR                       move a skill folder out of the load path
  python3 snapshot.py record <id> --do CMD --undo CMD     log a CLI toggle you ran (e.g. agy plugin disable x)
  python3 snapshot.py show <id> | list
  python3 snapshot.py rollback <id> [--run-undo]          restore files, un-park folders, then undo CLI toggles
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.join(os.path.expanduser("~"), ".gadoc", "backups")


def manifest_path(cid):
    return os.path.join(ROOT, cid, "manifest.json")


def load(cid):
    p = manifest_path(cid)
    if not os.path.isfile(p):
        sys.exit("unknown change set: %s" % cid)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(cid, m):
    with open(manifest_path(cid), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def cmd_begin(a):
    cid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(os.path.join(ROOT, cid, "files"), exist_ok=False)
    save(cid, {"id": cid, "label": a.label, "created": datetime.datetime.now().isoformat(timespec="seconds"),
               "files": [], "parked": [], "commands": [], "rolled_back": False})
    print(cid)


def cmd_backup(a):
    m = load(a.id)
    for f in a.files:
        src = os.path.abspath(os.path.expanduser(f))
        if any(x["orig"] == src for x in m["files"]):
            continue
        entry = {"orig": src, "existed": os.path.exists(src)}
        if entry["existed"]:
            if os.path.isdir(src) and not os.path.islink(src):
                sys.exit("backup takes files; use park for folders: %s" % src)
            dst = os.path.join(ROOT, a.id, "files", "%03d-%s" % (len(m["files"]), os.path.basename(src)))
            shutil.copy2(src, dst, follow_symlinks=False)
            entry["backup"] = dst
        m["files"].append(entry)
        print("backed up" if entry["existed"] else "recorded absent", src)
    save(a.id, m)


def cmd_park(a):
    m = load(a.id)
    src = os.path.abspath(os.path.expanduser(a.dir))
    if not os.path.lexists(src):
        sys.exit("not found: %s" % src)
    if "/.claude/" in src + "/":
        sys.exit("refusing to park inside ~/.claude (shared with Claude Code); use a grok-side ignore instead")
    dst = os.path.join(ROOT, a.id, "parked", "%03d-%s" % (len(m["parked"]), os.path.basename(src)))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    m["parked"].append({"orig": src, "parked": dst})
    save(a.id, m)
    print("parked", src, "->", dst)


def cmd_record(a):
    m = load(a.id)
    m["commands"].append({"do": a.do, "undo": a.undo, "at": datetime.datetime.now().isoformat(timespec="seconds")})
    save(a.id, m)
    print("recorded:", a.do, "| undo:", a.undo)


def cmd_show(a):
    print(json.dumps(load(a.id), ensure_ascii=False, indent=2))


def cmd_list(_a):
    if not os.path.isdir(ROOT):
        return
    for cid in sorted(os.listdir(ROOT)):
        try:
            m = load(cid)
        except SystemExit:
            continue
        print("%s  %-30s files=%d parked=%d commands=%d%s" % (
            cid, m["label"], len(m["files"]), len(m["parked"]), len(m["commands"]),
            "  (rolled back)" if m.get("rolled_back") else ""))


def cmd_rollback(a):
    m = load(a.id)
    for e in reversed(m["files"]):
        if e["existed"]:
            shutil.copy2(e["backup"], e["orig"], follow_symlinks=False)
            print("restored", e["orig"])
        elif os.path.lexists(e["orig"]):
            os.remove(e["orig"])
            print("removed (did not exist before)", e["orig"])
    for p in reversed(m["parked"]):
        if os.path.lexists(p["orig"]):
            print("SKIP un-park, path is occupied again:", p["orig"])
            continue
        os.makedirs(os.path.dirname(p["orig"]), exist_ok=True)
        shutil.move(p["parked"], p["orig"])
        print("un-parked", p["orig"])
    for c in reversed(m["commands"]):
        if a.run_undo:
            r = subprocess.run(c["undo"], shell=True)
            print("undo (%s): %s" % ("ok" if r.returncode == 0 else "rc=%d" % r.returncode, c["undo"]))
        else:
            print("run to undo:", c["undo"])
    m["rolled_back"] = True
    save(a.id, m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("begin"); s.add_argument("--label", required=True); s.set_defaults(fn=cmd_begin)
    s = sub.add_parser("backup"); s.add_argument("id"); s.add_argument("files", nargs="+"); s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("park"); s.add_argument("id"); s.add_argument("dir"); s.set_defaults(fn=cmd_park)
    s = sub.add_parser("record"); s.add_argument("id"); s.add_argument("--do", required=True)
    s.add_argument("--undo", required=True); s.set_defaults(fn=cmd_record)
    s = sub.add_parser("show"); s.add_argument("id"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("list"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("rollback"); s.add_argument("id"); s.add_argument("--run-undo", action="store_true")
    s.set_defaults(fn=cmd_rollback)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
