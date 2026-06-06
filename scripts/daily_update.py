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
        help="URL of a Kimi webpage to download as the local briefing",
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
def update_index(date_str, copied_pdfs):
    """Add PDF entries and local HTML links to data/reports_index.json."""
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

    # Ensure a local link is recorded for every source once the HTML exists
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
    """Save briefings/YYYY-MM-DD.html from a Kimi URL or the current index.html."""
    os.makedirs(BRIEFINGS_DIR, exist_ok=True)
    out_path = os.path.join(BRIEFINGS_DIR, f"{date_str}.html")

    if kimi_url:
        print(f"  Fetching {kimi_url} with curl...")
        result = subprocess.run(
            ["curl", "-s", "-L", kimi_url],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  ERROR: curl failed: {result.stderr.strip()}")
            return False
        if not result.stdout.strip():
            print(f"  ERROR: fetched empty content from {kimi_url}")
            return False

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)
        print(f"  Saved Kimi page to {out_path}")
        return True

    # Fallback: extract from index.html
    print(f"  Generating from {INDEX_HTML}...")

    if not os.path.exists(INDEX_HTML):
        print(f"  ERROR: {INDEX_HTML} not found. Cannot generate local briefing.")
        return False

    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    observers = extract_observer_divs(html)
    if len(observers) != 3:
        print(f"  ERROR: Expected 3 observer sections, found {len(observers)}.")
        return False

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
    return True


# Step 3.5: Bundle Kimi SPA assets --------------------------------------------------
def bundle_kimi_assets(date_str, kimi_url):
    """Download JS/CSS assets referenced by a Kimi SPA page so it works offline on GH Pages.

    Parses briefings/YYYY-MM-DD.html for relative asset references (./assets/...),
    downloads them from the Kimi server, and rewrites remote CDN refs to local.
    """
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
    base_url = kimi_url.rstrip("/")
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

    print("Step 2: Updating reports index...")
    index_changed = update_index(date_str, copied)

    if args.kimi_url:
        print("Step 3: Fetching Kimi page...")
    else:
        print("Step 3: Saving local HTML briefing...")
    html_ok = save_local_briefing(date_str, args.kimi_url)

    if args.kimi_url and args.bundle_assets and html_ok:
        print("Step 3.5: Bundling Kimi SPA assets for offline use...")
        bundle_kimi_assets(date_str, args.kimi_url)

    print("Step 4: Git commit and push...")
    git_ok = git_commit_and_push(date_str)

    print("=== Update complete ===")

    # Worthwhile if at least one of PDF copy, local briefing, or Kimi download succeeded
    if not (copied or html_ok or git_ok):
        print("Nothing changed today.")

    sys.exit(0)


if __name__ == "__main__":
    main()
