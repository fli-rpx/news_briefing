#!/usr/bin/env python3
"""Morning Briefing checkpoint CLI.

Prints a JSON summary of which pipeline phases are already done for today.

Usage:
    python3 scripts/mb_checkpoint.py
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.now().strftime("%Y-%m-%d")
CDN_URL = "https://fli-rpx.github.io/news_briefing/"


def _today_bounds():
    """Return --since / --until strings for git log covering today."""
    return f"{TODAY}T00:00:00", f"{TODAY}T23:59:59"


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_observer_sync():
    """True if data/observers.json has today's date with zhai/jin/song."""
    path = os.path.join(REPO_ROOT, "data", "observers.json")
    if not os.path.exists(path):
        return False

    try:
        data = _read_json(path)
    except (json.JSONDecodeError, OSError):
        return False

    entry = data.get(TODAY)
    if not isinstance(entry, dict):
        return False

    return all(field in entry and entry[field] for field in ("zhai", "jin", "song"))


def _is_valid_image(path):
    """Validate JPEG/PNG by inspecting the magic bytes."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
    except OSError:
        return False

    # JPEG: FF D8 FF
    if header.startswith(b"\xff\xd8\xff"):
        return True
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    return False


def _file_is_today(path):
    """Check if file was modified today."""
    if not path or not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return mtime.strftime("%Y-%m-%d") == TODAY


def check_cartoon():
    """True if images/cartoon_TODAY.{jpg,png} exists, is from today, and is a valid image."""
    base_dir = os.path.join(REPO_ROOT, "images")
    candidates = [
        os.path.join(base_dir, f"cartoon_{TODAY}.jpg"),
        os.path.join(base_dir, f"cartoon_{TODAY}.png"),
    ]
    for path in candidates:
        if os.path.exists(path) and _file_is_today(path) and _is_valid_image(path):
            return True
    return False


def _git_has_commit_today():
    """True if git log shows any commit authored today."""
    since, until = _today_bounds()
    result = subprocess.run(
        ["git", "log", f"--since={since}", f"--until={until}", "--oneline"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _cdn_reachable():
    """True if the gallery CDN URL returns HTTP 200."""
    try:
        req = urllib.request.Request(
            CDN_URL, method="HEAD", headers={"User-Agent": "mb-checkpoint/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def _read_links_ok():
    """True if data/reports_index.json has source-prefixed Read links for today."""
    path = os.path.join(REPO_ROOT, "data", "reports_index.json")
    if not os.path.exists(path):
        return False

    try:
        data = _read_json(path)
    except (json.JSONDecodeError, OSError):
        return False

    entry = data.get(TODAY)
    if not isinstance(entry, dict):
        return False

    for source, prefix in (("nyt", "briefings/nyt_"), ("wsj", "briefings/wsj_")):
        source_entry = entry.get(source)
        if not isinstance(source_entry, dict):
            return False
        local = source_entry.get("local")
        if not isinstance(local, str) or not local.startswith(prefix):
            return False

    return True


def check_publish():
    """True if today's commit, CDN, and Read links are all good."""
    return _git_has_commit_today() and _cdn_reachable() and _read_links_ok()


def main():
    phases = {
        "observer_sync": "done" if check_observer_sync() else "pending",
        "cartoon": "done" if check_cartoon() else "pending",
        "publish": "done" if check_publish() else "pending",
    }

    # Determine next pending phase.
    next_phase = None
    for phase in ("observer_sync", "cartoon", "publish"):
        if phases[phase] == "pending":
            next_phase = phase
            break

    output = {"date": TODAY, "phases": phases, "next": next_phase}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
