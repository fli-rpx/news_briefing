#!/usr/bin/env python3
"""Daily Morning Briefing update script for GitHub Pages.

Copies new PDFs from ~/.hermes into the repository, updates the reports
index, generates a local dark-themed HTML briefing from the current
index.html or a Kimi webpage URL, and commits/pushes the changes.

Usage:
    python scripts/daily_update.py
    python scripts/daily_update.py --date 2026-06-05
    python scripts/daily_update.py --date 2026-06-05 --kimi-url https://7hxicwoa45hze.kimi.page
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

# Repository paths -----------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = "/Users/fudongli/.hermes"
REPORTS_DIR = os.path.join(REPO_ROOT, "reports")
BRIEFINGS_DIR = os.path.join(REPO_ROOT, "briefings")
DATA_DIR = os.path.join(REPO_ROOT, "data")
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")
INDEX_JSON = os.path.join(DATA_DIR, "reports_index.json")
OBSERVERS_JSON = os.path.join(DATA_DIR, "observers.json")

SOURCES = ["nyt", "wsj"]


# Argument parsing -----------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Update Morning Briefing for GitHub Pages"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date to process in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--kimi-url",
        default=None,
        help='URL of a Kimi webpage. Prefix with "source:" e.g. "nyt:https://..." or "wsj:https://..."',
    )
    parser.add_argument(
        "--bundle-assets",
        action="store_true",
        default=True,
        help="Download JS/CSS assets for Kimi SPA pages so they work offline (default: True)",
    )
    return parser.parse_args()


def validate_date(date_str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD.")
    datetime.strptime(date_str, "%Y-%m-%d")
    return date_str


# Step 1: Copy PDFs ----------------------------------------------------------------
def copy_pdfs_for_date(date_str):
    """Copy PDFs for the given date from SOURCE_DIR to REPORTS_DIR.

    Returns a list of (source, filename) tuples for newly copied files.
    """
    copied = []
    for source in SOURCES:
        filename = f"{source}_briefing_{date_str}.pdf"
        src = os.path.join(SOURCE_DIR, filename)
        dst = os.path.join(REPORTS_DIR, filename)

        if not os.path.exists(src):
            print(f"  {source.upper()} PDF not found: {src}")
            continue

        if os.path.exists(dst):
            print(f"  {filename} already exists in reports/, skipping")
            continue

        shutil.copy2(src, dst)
        print(f"  Copied {filename}")
        copied.append((source, filename))

    if not copied:
        print("  No new PDFs copied for this date.")
    return copied


# Step 2: Update reports_index.json ------------------------------------------------
def update_index(date_str, copied_pdfs, kimi_source=None, kimi_local_path=None, skip_fallback=False):
    """Add PDF entries and local HTML links to data/reports_index.json.

    If kimi_source and kimi_local_path are provided, only update that source's
    local entry. Otherwise fall back to shared briefings/{date_str}.html for all.
    """
    print(f"Updating index: {INDEX_JSON}")

    with open(INDEX_JSON, "r", encoding="utf-8") as f:
        index = json.load(f)

    if date_str not in index:
        index[date_str] = {}
    entry = index[date_str]

    changed = False

    # Add PDF entries for newly copied files
    for source, filename in copied_pdfs:
        if source not in entry:
            entry[source] = {}
        if entry[source].get("pdf") != filename:
            entry[source]["pdf"] = filename
            changed = True
            print(f"  Added {source.upper()} PDF entry: {filename}")

    # If a Kimi page was saved for a specific source, set that source's local path
    if kimi_source and kimi_local_path:
        if kimi_source not in entry:
            entry[kimi_source] = {}
        if entry[kimi_source].get("local") != kimi_local_path:
            entry[kimi_source]["local"] = kimi_local_path
            changed = True
            print(f"  Set {kimi_source.upper()} local entry: {kimi_local_path}")
    elif not skip_fallback:
        # Fallback: shared local path for all sources
        local_path = f"briefings/{date_str}.html"
        for source in SOURCES:
            if source not in entry:
                entry[source] = {}
            if entry[source].get("local") != local_path:
                entry[source]["local"] = local_path
                changed = True
                print(f"  Added {source.upper()} local entry: {local_path}")

    if changed:
        sorted_index = dict(sorted(index.items()))
        with open(INDEX_JSON, "w", encoding="utf-8") as f:
            json.dump(sorted_index, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("  Index updated.")
    else:
        print("  No index changes needed.")

    return changed


# Step 3: Save local HTML briefing ------------------------------------------------
def extract_observer_divs(html):
    """Extract all top-level <div class="observer"> blocks from the HTML."""
    marker = '<div class="observer">'
    positions = []
    start = 0
    while True:
        idx = html.find(marker, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + len(marker)

    divs = []
    for pos in positions:
        depth = 0
        i = pos
        n = len(html)
        while i < n:
            open_idx = html.find("<div", i)
            close_idx = html.find("</div>", i)

            if open_idx == -1 and close_idx == -1:
                break

            if open_idx != -1 and (close_idx == -1 or open_idx < close_idx):
                depth += 1
                i = open_idx + 4
            else:
                depth -= 1
                i = close_idx + 6
                if depth == 0:
                    divs.append(html[pos:i])
                    break

    return divs


def format_date_long(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%A, %B ") + str(dt.day) + ", " + str(dt.year)


def format_date_title(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%B ") + str(dt.day) + ", " + str(dt.year)


def save_local_briefing(date_str, kimi_url=None):
    """Save briefings/{source}_{date_str}.html from a Kimi URL or the current index.html.

    Kimi URL can be prefixed with "source:" e.g. "nyt:https://..." or "wsj:https://...".
    Without prefix, saves to briefings/{date_str}.html (shared fallback).
    Returns (bool, str) — (success, local_path) where local_path is relative to REPO_ROOT.
    """
    os.makedirs(BRIEFINGS_DIR, exist_ok=True)

    source = None
    clean_url = kimi_url
    if kimi_url and ":" in kimi_url and kimi_url.split(":")[0] in ("nyt", "wsj"):
        source = kimi_url.split(":")[0]
        clean_url = kimi_url[len(source) + 1:]

    if source:
        out_path = os.path.join(BRIEFINGS_DIR, f"{source}_{date_str}.html")
    else:
        out_path = os.path.join(BRIEFINGS_DIR, f"{date_str}.html")
    local_rel = os.path.relpath(out_path, REPO_ROOT)

    if clean_url:
        print(f"  Fetching {clean_url} with curl...")
        result = subprocess.run(
            ["curl", "-s", "-L", clean_url],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  ERROR: curl failed: {result.stderr.strip()}")
            return (False, None)
        if not result.stdout.strip():
            print(f"  ERROR: fetched empty content from {clean_url}")
            return (False, None)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)
        print(f"  Saved Kimi page to {out_path}")
        return (True, local_rel)

    # Fallback: extract from index.html
    print(f"  Generating from {INDEX_HTML}...")

    if not os.path.exists(INDEX_HTML):
        print(f"  ERROR: {INDEX_HTML} not found. Cannot generate local briefing.")
        return (False, None)

    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    observers = extract_observer_divs(html)
    if len(observers) != 3:
        # New index.html is a gallery SPA without hardcoded observers.
        # This is OK when --kimi-url is used (the primary workflow).
        return (True, None)

    observers_html = "\n\n".join(observers)
    long_date = format_date_long(date_str)
    title_date = format_date_title(date_str)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Morning Briefing — {title_date}</title>
    <link rel="stylesheet" href="../style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>Morning Briefing</h1>
            <p class="date">{long_date}</p>
            <a class="past-reports-link" href="../archive.html">📋 Past Reports</a>
        </header>

        <section>
{observers_html}
        </section>

        <footer>
            <p>Powered by Hermes Agent Pipeline · Observer Commentary</p>
            <p style="margin-top:0.3rem;">Full briefing generated daily at 6:30 AM</p>
        </footer>
    </div>
</body>
</html>
"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"  Saved local briefing to {out_path}")
    return (True, local_rel)


# Step 3.75: Save observer text for gallery ----------------------------------------
def save_observers_for_date(date_str):
    """Extract observer inner HTML from index.html and save to observers.json.

    Expects exactly 3 <div class="observer"> blocks in index.html:
    first = zhai (翟东升), second = jin (金灿荣), third = song (宋鸿兵).
    """
    if not os.path.exists(INDEX_HTML):
        print(f"  WARNING: {INDEX_HTML} not found. Cannot save observers.")
        return

    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    divs = extract_observer_divs(html)
    if len(divs) != 3:
        # New index.html is a gallery SPA — observers come from the pipeline separately.
        # The primary workflow uses --kimi-url, which doesn't need observer extraction.
        return

    # Strip outer <div class="observer">...</div> to get inner HTML
    inner_htmls = []
    prefix = '<div class="observer">'
    suffix = "</div>"
    for div in divs:
        inner = div[len(prefix) : -len(suffix)].strip()
        inner_htmls.append(inner)

    observers = {"zhai": inner_htmls[0], "jin": inner_htmls[1], "song": inner_htmls[2]}

    data = {}
    if os.path.exists(OBSERVERS_JSON):
        with open(OBSERVERS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

    data[date_str] = observers
    sorted_data = dict(sorted(data.items()))

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OBSERVERS_JSON, "w", encoding="utf-8") as f:
        json.dump(sorted_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Saved observers for {date_str}")


# Step 3.5: Bundle Kimi SPA assets --------------------------------------------------
def bundle_kimi_assets(date_str, kimi_url):
    """Download JS/CSS assets referenced by a Kimi SPA page so it works offline on GH Pages.

    Parses briefings/{source}_YYYY-MM-DD.html for relative asset references (./assets/...),
    downloads them from the Kimi server.
    """
    # Parse source from URL prefix like "nyt:https://..." or "wsj:https://..."
    source = None
    clean_url = kimi_url
    if kimi_url and ":" in kimi_url and kimi_url.split(":")[0] in ("nyt", "wsj"):
        source = kimi_url.split(":")[0]
        clean_url = kimi_url[len(source) + 1:]

    if source:
        html_path = os.path.join(BRIEFINGS_DIR, f"{source}_{date_str}.html")
    else:
        html_path = os.path.join(BRIEFINGS_DIR, f"{date_str}.html")
    if not os.path.exists(html_path):
        print(f"  Skipping asset bundle: {html_path} not found")
        return False

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Check if this is an SPA (has <div id="root"> and ./assets/ references)
    if '<div id="root">' not in html or "./assets/" not in html:
        print("  Not a Kimi SPA page — no asset bundle needed")
        return True  # not an error, just nothing to do

    # Determine base URL for resolving relative paths
    base_url = clean_url.rstrip("/")
    assets_dir = os.path.join(BRIEFINGS_DIR, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # Find all local asset references: src="./assets/..." or href="./assets/..."
    patterns = re.findall(r'(?:src|href)="(\./assets/[^"]+)"', html)
    if not patterns:
        print("  No local assets found in HTML")
        return True

    downloaded = []
    for rel_path in patterns:
        # Build remote URL
        remote = f"{base_url}/{rel_path.lstrip('./')}"
        local_name = rel_path.replace("./assets/", "")
        local_path = os.path.join(assets_dir, local_name)

        print(f"  Downloading {rel_path} -> assets/{local_name}...")
        result = subprocess.run(
            ["curl", "-s", "-L", remote],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0 or len(result.stdout) == 0:
            print(f"    WARNING: failed to download {remote}")
            continue

        with open(local_path, "wb") as f:
            f.write(result.stdout)
        size_kb = len(result.stdout) / 1024
        print(f"    Saved {size_kb:.0f} KB")
        downloaded.append(local_name)

    # Also handle remote kimi.com SDK script
    sdk_remote = "https://www.kimi.com/sdk-seed.js"
    sdk_local = os.path.join(assets_dir, "sdk-seed.js")
    if "kimi.com/sdk-seed" in html and not os.path.exists(sdk_local):
        print("  Downloading sdk-seed.js...")
        result = subprocess.run(
            ["curl", "-s", "-L", sdk_remote],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and len(result.stdout) > 0:
            with open(sdk_local, "wb") as f:
                f.write(result.stdout)
            print(f"    Saved {len(result.stdout)/1024:.0f} KB")
            downloaded.append("sdk-seed.js")

    # Rewrite remote kimi CDN refs to local
    if "sdk-seed.js" in downloaded:
        html = html.replace(
            "https://www.kimi.com/sdk-seed.js",
            "./assets/sdk-seed.js",
        )

    # Rewrite relative asset paths to always point to ./assets/
    # (they already use ./assets/X from Kimi's build, so this is a no-op
    #  when briefings/2026-06-05.html references ./assets/X.js which resolves
    #  to briefings/assets/X.js — exactly right for GH Pages)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Bundled {len(downloaded)} assets for SPA")
    return True


# Step 4: Git commit and push ------------------------------------------------------
def git_commit_and_push(date_str):
    """Stage, commit, and push repository changes."""
    print("Staging changes for git...")

    paths_to_stage = ["reports/", "data/reports_index.json", "briefings/", "index.html"]
    for item in paths_to_stage:
        path = os.path.join(REPO_ROOT, item)
        if os.path.exists(path):
            subprocess.run(
                ["git", "add", item],
                cwd=REPO_ROOT,
                timeout=60,
                check=False,
            )

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    if diff.returncode == 0:
        print("  No changes to commit.")
        return False

    message = f"Daily briefing update for {date_str}"
    print(f"Committing: {message}")
    commit = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=REPO_ROOT,
        timeout=60,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        print(f"  ERROR: git commit failed: {commit.stderr.strip()}")
        return False
    print("  Committed.")

    print("Pushing to origin main...")
    push = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=REPO_ROOT,
        timeout=60,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        print(f"  ERROR: git push failed: {push.stderr.strip()}")
        return False
    print("  Pushed.")
    return True


# Main ---------------------------------------------------------------------------
def main():
    args = parse_args()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    try:
        validate_date(date_str)
    except ValueError as e:
        print(e)
        sys.exit(1)

    print(f"=== Morning Briefing Update for {date_str} ===")

    print("Step 1: Copying PDFs...")
    copied = copy_pdfs_for_date(date_str)

    # Parse source prefix from kimi_url (e.g. "nyt:https://..." or "wsj:https://...")
    kimi_source = None
    if args.kimi_url and ":" in args.kimi_url and args.kimi_url.split(":")[0] in ("nyt", "wsj"):
        kimi_source = args.kimi_url.split(":")[0]

    print("Step 2: Updating reports index...")
    # When a Kimi URL is provided, skip the fallback shared-path logic
    # (the source-specific path is set in Step 2b below)
    index_changed = update_index(date_str, copied, skip_fallback=bool(args.kimi_url))

    if args.kimi_url:
        print("Step 3: Fetching Kimi page...")
    else:
        print("Step 3: Saving local HTML briefing...")
    html_ok, local_path = save_local_briefing(date_str, args.kimi_url)

    # Update index with the correct per-source local path if a Kimi page was saved
    if html_ok and local_path and kimi_source:
        print("Step 2b: Updating index with per-source local path...")
        update_index(date_str, [], kimi_source=kimi_source, kimi_local_path=local_path)

    if args.kimi_url and args.bundle_assets and html_ok:
        print("Step 3.5: Bundling Kimi SPA assets for offline use...")
        bundle_kimi_assets(date_str, args.kimi_url)

    print("Step 3.75: Saving observer text for gallery...")
    save_observers_for_date(date_str)

    print("Step 4: Git commit and push...")
    git_ok = git_commit_and_push(date_str)

    print("=== Update complete ===")

    # Worthwhile if at least one of PDF copy, local briefing, or Kimi download succeeded
    if not (copied or html_ok or git_ok):
        print("Nothing changed today.")

    sys.exit(0)


if __name__ == "__main__":
    main()
