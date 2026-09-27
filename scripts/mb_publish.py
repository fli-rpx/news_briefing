#!/usr/bin/env python3
"""Morning Briefing publish orchestrator.

Wraps scripts/daily_update.py, fixes Read links in the reports index,
commits/pushes the fix, and verifies the CDN is live.

Usage:
    python3 scripts/mb_publish.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.now().strftime("%Y-%m-%d")
CDN_URL = "https://fli-rpx.github.io/news_briefing/"
CDN_POLL_RETRIES = 3
CDN_POLL_INTERVAL = 15


def _error(msg):
    print(msg, file=sys.stderr)


def _run(cmd, cwd=REPO_ROOT, timeout=120, check=True):
    """Run a subprocess and return its CompletedProcess result."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{err}")
    return result


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _find_cartoon_path():
    """Return the relative cartoon path for today, or None if not found."""
    for ext in ("jpg", "png"):
        rel = f"images/cartoon_{TODAY}.{ext}"
        full = os.path.join(REPO_ROOT, rel)
        if os.path.exists(full):
            return rel
    return None


def run_daily_update(cartoon_rel):
    """Run daily_update.py, passing today's cartoon path when one exists.

    The cartoon is optional: Kimi Docs image generation was removed, so the
    publish path must work without one.
    """
    cmd = ["python3", "scripts/daily_update.py"]
    if cartoon_rel:
        cmd += ["--cartoon-path", cartoon_rel]
    _run(cmd)


def fix_read_links():
    """Ensure today's entries in data/reports_index.json use source-prefixed paths.

    Returns True if the file was changed, False otherwise.
    """
    path = os.path.join(REPO_ROOT, "data", "reports_index.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Index file not found: {path}")

    data = _read_json(path)
    entry = data.get(TODAY)
    if not isinstance(entry, dict):
        raise ValueError(f"No entry for {TODAY} in {path}")

    changed = False
    for source in ("nyt", "wsj"):
        source_entry = entry.get(source)
        if not isinstance(source_entry, dict):
            continue

        local = source_entry.get("local", "")

        # Never break a link that already resolves to a file on disk: the WSJ
        # pipeline names its page briefings/wsj_briefing_<date>.html, not
        # briefings/wsj_<date>.html.
        if local and os.path.exists(os.path.join(REPO_ROOT, local)):
            continue

        expected = f"briefings/{source}_{TODAY}.html"

        # The WSJ pipeline writes briefings/wsj_briefing_<date>.html; prefer it
        # when the shorter name does not exist.
        if source == "wsj" and not os.path.exists(os.path.join(REPO_ROOT, expected)):
            alt = f"briefings/wsj_briefing_{TODAY}.html"
            if os.path.exists(os.path.join(REPO_ROOT, alt)):
                expected = alt

        if local != expected:
            source_entry["local"] = expected
            changed = True

    if changed:
        _write_json(path, data)

    return changed


def _has_changes_to_commit():
    result = _run(["git", "diff", "--cached", "--quiet"], check=False)
    return result.returncode != 0


def git_commit_and_push_fix():
    """Stage, commit, and push the Read-links fix if there are changes."""
    if not _has_changes_to_commit():
        return False

    _run(["git", "add", "data/reports_index.json"])
    _run(["git", "commit", "-m", f"Fix Read links for {TODAY}"])
    _run(["git", "push", "origin", "main"])
    return True


def verify_cdn():
    """Poll the gallery CDN until HTTP 200 or retries exhausted."""
    for attempt in range(1, CDN_POLL_RETRIES + 1):
        try:
            req = urllib.request.Request(
                CDN_URL, method="HEAD", headers={"User-Agent": "mb-publish/1.0"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:
            _error(f"CDN check attempt {attempt} failed: {exc}")

        if attempt < CDN_POLL_RETRIES:
            time.sleep(CDN_POLL_INTERVAL)

    return False


def _git_file_committed_today(rel_path):
    """True if *rel_path* appears in today's commits."""
    since = f"{TODAY}T00:00:00"
    until = f"{TODAY}T23:59:59"
    result = subprocess.run(
        ["git", "log", f"--since={since}", f"--until={until}", "--oneline", "--", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def verify_commit_artifacts(cartoon_rel):
    """Check that observers.json and (when present) the cartoon are committed today."""
    observers_ok = _git_file_committed_today("data/observers.json")
    cartoon_ok = _git_file_committed_today(cartoon_rel) if cartoon_rel else True
    return observers_ok, cartoon_ok


def _already_published():
    """True when today's per-source pages and index entries already exist on disk.

    The NYT/WSJ briefing pipelines publish their own HTML, PDFs, index entries
    and commits. Running daily_update.py after that would write a shared
    briefings/<date>.html fallback, so the legacy copy path must be skipped.
    """
    idx_path = os.path.join(REPO_ROOT, "data", "reports_index.json")
    if not os.path.exists(idx_path):
        return False

    try:
        entry = _read_json(idx_path).get(TODAY, {})
    except Exception:
        return False

    if not isinstance(entry, dict):
        return False

    for source in ("nyt", "wsj"):
        source_entry = entry.get(source)
        if not isinstance(source_entry, dict):
            return False
        local = source_entry.get("local", "")
        if not local or not os.path.exists(os.path.join(REPO_ROOT, local)):
            return False

    return True


def main():
    cartoon_rel = _find_cartoon_path()
    if not cartoon_rel:
        print(f"No cartoon for {TODAY} (Kimi Docs images removed) — publishing without one.")

    try:
        print(f"=== Morning Briefing Publish for {TODAY} ===")

        if _already_published():
            print("Step 1: Today's briefings were already published by the pipelines"
                  " — skipping daily_update.py.")
        else:
            print("Step 1: Running daily_update.py...")
            run_daily_update(cartoon_rel)

        print("Step 2: Fixing Read links...")
        fixed = fix_read_links()
        if fixed:
            print("  Read links fixed.")
        else:
            print("  Read links already correct.")

        print("Step 3: Committing/pushing Read-links fix...")
        pushed = git_commit_and_push_fix()
        print("  Pushed fix." if pushed else "  No fix to push.")

        print("Step 4: Verifying CDN...")
        if not verify_cdn():
            _error(f"CDN did not return HTTP 200 after {CDN_POLL_RETRIES} attempts")
            return 1
        print("  CDN is live (HTTP 200).")

        print("Step 5: Verifying committed artifacts...")
        observers_ok, cartoon_ok = verify_commit_artifacts(cartoon_rel)
        if not observers_ok:
            _error("data/observers.json was not committed today")
        if not cartoon_ok:
            _error(f"{cartoon_rel} was not committed today")
        if not (observers_ok and cartoon_ok):
            return 1
        print("  observers.json and cartoon image are committed." if cartoon_rel else "  observers.json is committed.")

        print("=== Publish complete ===")
        return 0

    except Exception as exc:
        _error(f"Publish failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
