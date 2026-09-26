#!/usr/bin/env python3
"""Readiness/freshness gate for the morning pipelines.

Usage:
    briefing_preflight.py [--pipeline {nyt,wsj,both}] [--date ISO] [--clean] [--json]

Exit codes: 0 = ready, 2 = upstream not ready (cron reports [SILENT]),
3 = environment error (cron alerts).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime

try:
    from .briefing_lib import (
        HERMES, PIPELINE_STATE, require_fresh, resolve_repo, run_log, today_iso,
    )
except ImportError:  # run as a plain script
    from briefing_lib import (
        HERMES, PIPELINE_STATE, require_fresh, resolve_repo, run_log, today_iso,
    )

TMP_PATTERNS = ("nyt_briefing_*.html", "wsj_briefing_*.html",
                "kimi_prompt.md", "wsj_webpage_prompt.md")
NYT_OBSERVERS = ("nyt_observer_zhai.md", "nyt_observer_jin.md", "nyt_observer_song.md")
WSJ_OBSERVERS = ("wsj_observer.md", "wsj_observer2.md", "wsj_observer3.md")


def _mtime_date(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def _can_publish(pipeline):
    """Run pipeline_state.py can_publish. Returns (ok, detail)."""
    if not os.path.exists(PIPELINE_STATE):
        return False, "missing %s" % PIPELINE_STATE
    try:
        r = subprocess.run(
            ["python3", PIPELINE_STATE, "--pipeline", pipeline,
             "--action", "can_publish"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return False, "can_publish error: %s" % exc
    if r.returncode != 0:
        return False, "can_publish rc=%d: %s" % (r.returncode, r.stderr.strip())
    try:
        out = json.loads(r.stdout)
    except ValueError as exc:
        return False, "can_publish unparseable output: %s" % exc
    return bool(out.get("can_publish")), out


def _check_pipeline(pipeline, target):
    checks = {}

    v3 = os.path.join(HERMES, "%s_briefing_v3.md" % pipeline)
    v3_exists = os.path.exists(v3)
    v3_mtime = _mtime_date(v3) if v3_exists else None
    v3_ok = v3_exists and v3_mtime == target
    checks["v3"] = {"path": v3, "exists": v3_exists,
                    "mtime_date": v3_mtime, "ok": v3_ok}

    if pipeline == "wsj":
        obs = []
        for fn in WSJ_OBSERVERS:
            path = os.path.join(HERMES, fn)
            exists = os.path.exists(path)
            mdate = _mtime_date(path) if exists else None
            obs.append({"path": path, "exists": exists, "mtime_date": mdate,
                        "ok": exists and mdate == target})
        checks["observers"] = obs
    else:
        # NYT observers are inline in the V3; only check the sidecar files exist.
        obs = []
        for fn in NYT_OBSERVERS:
            path = os.path.join(HERMES, fn)
            exists = os.path.exists(path)
            obs.append({"path": path, "exists": exists, "ok": exists})
        checks["observers"] = obs

    cp_ok, cp_detail = _can_publish(pipeline)
    checks["can_publish"] = {"ok": cp_ok, "detail": cp_detail}

    ready = (v3_ok
             and all(o["ok"] for o in checks["observers"])
             and cp_ok)
    return ready, checks


def _tmp_artifacts(target, clean):
    tmpdir = tempfile.gettempdir()
    found, cleaned = [], []
    for pat in TMP_PATTERNS:
        for path in sorted(glob.glob(os.path.join(tmpdir, pat))):
            name = os.path.basename(path)
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", name)
            art_date = m.group(1) if m else _mtime_date(path)
            old = art_date != target
            entry = {"path": path, "date": art_date, "old": old}
            found.append(entry)
            if clean and old:
                try:
                    os.remove(path)
                    cleaned.append(path)
                except OSError as exc:
                    entry["clean_error"] = str(exc)
    return found, cleaned


def main(argv=None):
    ap = argparse.ArgumentParser(description="Preflight gate for briefing pipelines")
    ap.add_argument("--pipeline", choices=["nyt", "wsj", "both"], default="both")
    ap.add_argument("--date", default=None, help="ISO date (default: today)")
    ap.add_argument("--clean", action="store_true",
                    help="remove /tmp artifacts from previous days")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    target = args.date or today_iso()
    repo = resolve_repo()
    info = require_fresh(repo, fetch=True)

    pipelines = ["nyt", "wsj"] if args.pipeline == "both" else [args.pipeline]
    report = {
        "repo": repo,
        "date": target,
        "fresh": {"head": info["head"], "origin_main": info["origin_main"],
                  "behind": info["behind"], "ahead": info["ahead"],
                  "fresh": info["fresh"]},
        "pipelines": {},
        "tmp_artifacts": [],
        "cleaned": [],
    }
    exit_code = 0
    for pl in pipelines:
        ready, checks = _check_pipeline(pl, target)
        report["pipelines"][pl] = dict(ready=ready, checks=checks)
        if not ready and exit_code < 2:
            exit_code = 2
        run_log({"pipeline": pl, "date": target, "stage": "preflight",
                 "ok": ready, "detail": checks})

    artifacts, cleaned = _tmp_artifacts(target, args.clean)
    report["tmp_artifacts"] = artifacts
    report["cleaned"] = cleaned
    report["ready"] = exit_code == 0

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print("repo: %s (behind=%d ahead=%d)" % (repo, info["behind"], info["ahead"]))
        for pl in pipelines:
            st = report["pipelines"][pl]
            print("%s: %s" % (pl, "READY" if st["ready"] else "NOT READY"))
            c = st["checks"]
            print("  v3: %s" % ("ok" if c["v3"]["ok"]
                                else "missing/stale (%s mtime=%s)"
                                % (c["v3"]["path"], c["v3"]["mtime_date"])))
            for o in c["observers"]:
                print("  observer: %s %s" % ("ok" if o["ok"] else "MISSING",
                                             o["path"]))
            print("  can_publish: %s" % c["can_publish"]["ok"])
        if artifacts:
            print("tmp artifacts: %d (old: %d)" % (len(artifacts),
                                                   sum(1 for a in artifacts if a["old"])))
        if cleaned:
            print("cleaned: %d" % len(cleaned))
        print("exit: %d" % exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
