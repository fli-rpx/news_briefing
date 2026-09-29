#!/usr/bin/env python3
"""Sync today's observer commentaries into data/observers.json.

Source preference: WSJ observer files (they carry an explicit date heading),
falling back to NYT observer files when WSJ ones are missing or stale.

Refuses to write commentary that is not from today: the gallery must never
attribute stale commentary to the current date.

Usage:
    python3 scripts/mb_observer_sync.py [--date YYYY-MM-DD] [--dry-run]
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERMES = os.path.join(os.path.expanduser("~"), ".hermes")
OBSERVERS_JSON = os.path.join(REPO_ROOT, "data", "observers.json")

WSJ_FILES = {
    "zhai": "wsj_observer.md",
    "jin": "wsj_observer2.md",
    "song": "wsj_observer3.md",
}
NYT_FILES = {
    "zhai": "nyt_observer_zhai.md",
    "jin": "nyt_observer_jin.md",
    "song": "nyt_observer_song.md",
}

DATE_HEADING_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def _heading_date(text):
    """Return YYYY-MM-DD parsed from a Chinese date in the first 200 chars, else None."""
    m = DATE_HEADING_RE.search(text[:200])
    if not m:
        return None
    return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))


def _mtime_date(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def _load_set(mapping, date_str):
    """Return (entry_dict, problems) for one source's observer files."""
    entry, problems = {}, []
    for key, name in mapping.items():
        path = os.path.join(HERMES, name)
        if not os.path.exists(path):
            problems.append(f"{name}: missing")
            continue
        raw = open(path, "r", encoding="utf-8", errors="replace").read()
        hd = _heading_date(raw)
        if hd and hd != date_str:
            problems.append(f"{name}: heading date {hd} != {date_str}")
            continue
        if not hd and _mtime_date(path) != date_str:
            problems.append(f"{name}: no date heading and mtime {_mtime_date(path)} != {date_str}")
            continue
        body = _body(raw)
        if len(body) < 200:
            problems.append(f"{name}: body too short ({len(body)} chars)")
            continue
        entry[key] = to_html(body)
    return entry, problems


def _body(raw):
    """Drop the leading heading line(s) and phase markers; return plain text."""
    lines = raw.splitlines()
    # Skip leading blank lines and the first markdown heading / front matter block.
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith("#"):
        i += 1
    if i < len(lines) and lines[i].strip() == "---":
        i += 1
    body = "\n".join(lines[i:])
    body = re.sub(r"<!--\s*PHASE COMPLETE\s*-->", "", body)
    body = re.sub(r"<!--\s*.*?-->", "", body)
    return body.strip()


def to_html(text):
    escaped = html.escape(text).replace("\n", "<br>")
    return f'<h2>Observer</h2><div style="white-space:pre-wrap">{escaped}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    date_str = args.date

    entry, problems = _load_set(WSJ_FILES, date_str)
    source = "wsj"
    if not all(k in entry for k in ("zhai", "jin", "song")):
        print("WSJ observer set incomplete: " + "; ".join(problems), file=sys.stderr)
        nyt_entry, nyt_problems = _load_set(NYT_FILES, date_str)
        problems += nyt_problems
        source = "nyt"
        entry = nyt_entry
        if not all(k in entry for k in ("zhai", "jin", "song")):
            print("NO-USABLE-OBSERVERS: " + "; ".join(problems), file=sys.stderr)
            print("ERROR: no fresh observer set for %s — refusing to attribute stale commentary."
                  % date_str, file=sys.stderr)
            return 2

    print(f"Using {source.upper()} observer set for {date_str}")
    for k, v in entry.items():
        print(f"  {k}: {len(v)} chars html")

    if args.dry_run:
        print("(dry run — observers.json untouched)")
        return 0

    data = {}
    if os.path.exists(OBSERVERS_JSON):
        with open(OBSERVERS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault(date_str, {})
    data[date_str].update(entry)

    with open(OBSERVERS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"observers.json updated for {date_str} (source={source})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
