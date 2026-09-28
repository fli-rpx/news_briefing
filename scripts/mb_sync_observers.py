#!/usr/bin/env python3
"""Sync observer commentaries into data/observers.json for a given date.

Prefers WSJ observer files (wsj_observer.md / 2 / 3) and falls back to the
NYT observer files (nyt_observer_{zhai,jin,song}.md) when the WSJ set is
missing or stale.

Usage:
    python3 scripts/mb_sync_observers.py [YYYY-MM-DD] [--source wsj|nyt|auto]
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERMES = os.path.expanduser("~/.hermes")

SOURCES = {
    "wsj": {
        "zhai": os.path.join(HERMES, "wsj_observer.md"),
        "jin": os.path.join(HERMES, "wsj_observer2.md"),
        "song": os.path.join(HERMES, "wsj_observer3.md"),
    },
    "nyt": {
        "zhai": os.path.join(HERMES, "nyt_observer_zhai.md"),
        "jin": os.path.join(HERMES, "nyt_observer_jin.md"),
        "song": os.path.join(HERMES, "nyt_observer_song.md"),
    },
}


def _is_today(path, date):
    """True when the file was last modified on *date*."""
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
    return mtime == date


def extract_text(path):
    """Return the commentary body: drop the leading heading and markers."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    body = "".join(lines[1:]) if lines and lines[0].lstrip().startswith("#") else "".join(lines)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return body.strip()


def to_html(text):
    escaped = html.escape(text)
    html_text = escaped.replace("\n\n", "<br><br>").replace("\n", "<br>")
    return '<h2>Observer</h2><div style="white-space:pre-wrap">%s</div>' % html_text


def pick_source(date, requested):
    """Return (source_name, {key: path}) for files that exist for *date*."""
    order = [requested] if requested in ("wsj", "nyt") else ["wsj", "nyt"]
    fallback = None
    for name in order:
        files = SOURCES[name]
        existing = {k: p for k, p in files.items() if os.path.exists(p)}
        if len(existing) < 3:
            continue
        if all(_is_today(p, date) for p in existing.values()):
            return name, existing
        if fallback is None:
            fallback = (name, existing)
    return fallback if fallback else (None, {})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--source", default="auto", choices=["auto", "wsj", "nyt"])
    args = parser.parse_args()

    date = args.date
    source, files = pick_source(date, args.source)
    if not source:
        print("ERROR: no complete observer file set found")
        return 1

    print("source: %s" % source)
    entry = {}
    for key in ("zhai", "jin", "song"):
        text = extract_text(files[key])
        entry[key] = to_html(text)
        print("  ok %s: %d chars (%s)" % (key, len(text), os.path.basename(files[key])))

    obs_path = os.path.join(REPO_ROOT, "data", "observers.json")
    with open(obs_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault(date, {}).update(entry)
    with open(obs_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("observers.json updated for %s (keys: %s)" % (date, sorted(entry.keys())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
