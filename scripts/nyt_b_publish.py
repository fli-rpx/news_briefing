#!/usr/bin/env python3
"""NYT Briefing publishing wrapper (Steps 11-14).

Copies generated images and webpage into the repo, updates the reports index,
commits/pushes, and verifies CDN availability.

Usage:
    python3 scripts/nyt_b_publish.py
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.now().strftime("%Y-%m-%d")
PDF_PATH = os.path.expanduser(f"~/.hermes/nyt_briefing_{TODAY}.pdf")
CDN_BASE = "https://fli-rpx.github.io/news_briefing/"
CDN_POLL_RETRIES = 3
CDN_POLL_INTERVAL = 15

SRC_HERO = "/tmp/nyt_hero_bg.jpg"
SRC_CARTOON = "/tmp/nyt_cartoon.jpg"
SRC_WEBPAGE = f"/tmp/nyt_briefing_{TODAY}.html"

DST_IMAGE_DIR = os.path.join(REPO_ROOT, "briefings", "assets", "images")
DST_HERO = os.path.join(DST_IMAGE_DIR, "nyt_hero_bg.jpg")
DST_CARTOON = os.path.join(DST_IMAGE_DIR, "nyt_cartoon.jpg")
DST_WEBPAGE = os.path.join(REPO_ROOT, "briefings", f"nyt_{TODAY}.html")
INDEX_PATH = os.path.join(REPO_ROOT, "reports_index.json")


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


def preflight():
    """Ensure Job A PDF exists before proceeding."""
    if not os.path.exists(PDF_PATH):
        _error(f"NYT Job A incomplete — no PDF for {TODAY}: {PDF_PATH}")
        sys.exit(1)


def copy_images():
    """Copy hero and cartoon images into briefings/assets/images/."""
    os.makedirs(DST_IMAGE_DIR, exist_ok=True)
    if not os.path.exists(SRC_HERO):
        raise FileNotFoundError(f"Hero image not found: {SRC_HERO}")
    if not os.path.exists(SRC_CARTOON):
        raise FileNotFoundError(f"Cartoon image not found: {SRC_CARTOON}")
    shutil.copy2(SRC_HERO, DST_HERO)
    shutil.copy2(SRC_CARTOON, DST_CARTOON)


def copy_webpage():
    """Copy today's NYT briefing HTML into briefings/nyt_TODAY.html."""
    if not os.path.exists(SRC_WEBPAGE):
        raise FileNotFoundError(f"Webpage not found: {SRC_WEBPAGE}")
    shutil.copy2(SRC_WEBPAGE, DST_WEBPAGE)


def update_reports_index():
    """Ensure reports_index.json has today's nyt entry with a source-prefixed URL."""
    if not os.path.exists(INDEX_PATH):
        raise FileNotFoundError(f"Index file not found: {INDEX_PATH}")

    data = _read_json(INDEX_PATH)
    if not isinstance(data, list):
        raise ValueError(f"{INDEX_PATH} must contain a JSON list")

    expected_url = f"briefings/nyt_{TODAY}.html"
    now = datetime.now()
    expected_title = f"NYT Briefing - {now.strftime('%B')} {now.day}, {now.year}"

    # Update existing entry if present
    changed = False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("date") == TODAY and entry.get("type") == "nyt":
            if entry.get("url") != expected_url:
                entry["url"] = expected_url
                changed = True
            if not entry.get("title"):
                entry["title"] = expected_title
                changed = True
            break
    else:
        # Add new entry
        data.append({
            "date": TODAY,
            "type": "nyt",
            "title": expected_title,
            "url": expected_url,
        })
        changed = True

    if changed:
        _write_json(INDEX_PATH, data)

    return changed


def _has_changes_to_commit():
    result = _run(["git", "status", "--porcelain"], check=False)
    return bool(result.stdout.strip())


def git_commit_and_push():
    """Stage, commit, and push all changes."""
    if not _has_changes_to_commit():
        return False

    # Add only the files this pipeline touches.
    rel_hero = os.path.relpath(DST_HERO, REPO_ROOT)
    rel_cartoon = os.path.relpath(DST_CARTOON, REPO_ROOT)
    rel_webpage = os.path.relpath(DST_WEBPAGE, REPO_ROOT)
    rel_index = os.path.relpath(INDEX_PATH, REPO_ROOT)
    _run(["git", "add", rel_hero, rel_cartoon, rel_webpage, rel_index])
    _run(["git", "commit", "-m", f"NYT briefing {TODAY} — static HTML page"])
    _run(["git", "push", "origin", "main"])
    return True


def verify_cdn():
    """Poll the NYT briefing CDN URL until HTTP 200 or retries exhausted."""
    url = f"{CDN_BASE}briefings/nyt_{TODAY}.html"
    for attempt in range(1, CDN_POLL_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url, method="HEAD", headers={"User-Agent": "nyt-b-publish/1.0"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:
            _error(f"CDN check attempt {attempt} failed: {exc}")

        if attempt < CDN_POLL_RETRIES:
            time.sleep(CDN_POLL_INTERVAL)

    return False


def verify_read_links():
    """True if reports_index.json has the correct nyt entry for today."""
    data = _read_json(INDEX_PATH)
    if not isinstance(data, list):
        return False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("date") == TODAY and entry.get("type") == "nyt":
            url = entry.get("url", "")
            return isinstance(url, str) and url.startswith("briefings/nyt_")
    return False


def main():
    preflight()

    try:
        print(f"=== NYT Briefing Publish for {TODAY} ===")

        print("Step 1: Copying images...")
        copy_images()
        print("  Images copied.")

        print("Step 2: Copying webpage...")
        copy_webpage()
        print("  Webpage copied.")

        print("Step 3: Updating reports index...")
        updated = update_reports_index()
        print("  Index updated." if updated else "  Index already correct.")

        print("Step 4: Committing and pushing...")
        pushed = git_commit_and_push()
        print("  Pushed." if pushed else "  Nothing to commit.")

        print("Step 5: Verifying CDN...")
        if not verify_cdn():
            _error(f"CDN did not return HTTP 200 after {CDN_POLL_RETRIES} attempts")
            return 1
        print("  CDN is live (HTTP 200).")

        print("Step 6: Verifying Read links...")
        if not verify_read_links():
            _error("Read links verification failed")
            return 1
        print("  Read links verified.")

        print("=== Publish complete ===")
        return 0

    except Exception as exc:
        _error(f"Publish failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
