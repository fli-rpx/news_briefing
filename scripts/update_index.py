#!/usr/bin/env python3
"""Update reports_index.json with a new briefing entry.

Usage:
    python3 scripts/update_index.py --source nyt --date 2026-06-04 \\
        --pdf nyt_briefing_2026-06-04.pdf --web https://xxx.kimi.page
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(PROJECT_ROOT, "data", "reports_index.json")

VALID_SOURCES = {"nyt", "wsj"}


def load_index():
    if not os.path.exists(INDEX_PATH):
        return {}
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_index(index):
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")


def update_entry(source, date, pdf=None, local=None):
    source = source.lower().strip()
    if source not in VALID_SOURCES:
        print(f"Error: source must be one of {VALID_SOURCES}, got '{source}'", file=sys.stderr)
        sys.exit(1)

    index = load_index()
    if date not in index:
        index[date] = {}

    if source not in index[date]:
        index[date][source] = {}

    if pdf:
        index[date][source]["pdf"] = pdf
    if local:
        index[date][source]["local"] = local

    save_index(index)
    print(f"Updated {date} -> {source}: pdf={pdf}, local={local}")
    print(f"Index now contains {len(index)} date(s) with {sum(len(v) for v in index.values())} source entries.")


def main():
    parser = argparse.ArgumentParser(description="Update reports_index.json")
    parser.add_argument("--source", required=True, help="Source: nyt or wsj")
    parser.add_argument("--date", required=True, help="Date in YYYY-MM-DD format")
    parser.add_argument("--pdf", default=None, help="PDF filename")
    parser.add_argument("--local", default=None, help="Path to local HTML file")
    args = parser.parse_args()

    if not args.pdf and not args.local:
        print("Error: at least one of --pdf or --local must be provided", file=sys.stderr)
        sys.exit(1)

    update_entry(args.source, args.date, pdf=args.pdf, local=args.local)


if __name__ == "__main__":
    main()
