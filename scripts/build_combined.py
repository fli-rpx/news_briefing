#!/usr/bin/env python3
"""Build a combined HTML page from the latest NYT + WSJ observer analysis files.

Looks for the latest observer HTML files in a configurable input directory,
merges them into a single dark-themed HTML page, and writes it to the
specified output path.

Usage:
    python3 scripts/build_combined.py [--input-dir DIR] [--output FILE]

Defaults:
    --input-dir  /Users/fudongli/.hermes
    --output     /Users/fudongli/.hermes/combined_latest.html
"""

import argparse
import glob
import os
import re
import sys
from datetime import datetime

DEFAULT_INPUT_DIR = "/Users/fudongli/.hermes"
DEFAULT_OUTPUT = "/Users/fudongli/.hermes/combined_latest.html"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg: #0a0a0a;
            --surface: #141414;
            --text: #e8e6e3;
            --muted: #888;
            --accent: #c41e3a;
            --border: #2a2a2a;
            --font-serif: 'Georgia', 'Noto Serif SC', serif;
            --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: var(--font-sans);
            line-height: 1.6;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem 1.5rem;
        }}
        header {{
            text-align: center;
            padding: 4rem 0 3rem;
            border-bottom: 1px solid var(--border);
        }}
        h1 {{
            font-family: var(--font-serif);
            font-size: 2.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }}
        .date {{
            color: var(--muted);
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }}
        .source-badge {{
            display: inline-block;
            margin-top: 1rem;
            padding: 0.35rem 1rem;
            background: var(--accent);
            color: white;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .source-section {{
            margin: 2rem 0;
            padding: 1.5rem;
            background: var(--surface);
            border-radius: 8px;
            border-left: 3px solid var(--accent);
        }}
        .source-section.nyt {{ border-left-color: #c41e3a; }}
        .source-section.wsj {{ border-left-color: #1a5fb4; }}
        .source-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
        }}
        .source-header h2 {{
            font-family: var(--font-serif);
            font-size: 1.3rem;
        }}
        .source-tag {{
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.25rem 0.6rem;
            border-radius: 4px;
            background: var(--accent);
            color: white;
            text-transform: uppercase;
        }}
        .source-tag.nyt {{ background: #c41e3a; }}
        .source-tag.wsj {{ background: #1a5fb4; }}
        .observer {{
            margin: 1.5rem 0;
            padding: 1.25rem;
            background: #1a1a1a;
            border-radius: 6px;
            border-left: 2px solid #444;
        }}
        .observer h3 {{
            font-family: var(--font-serif);
            font-size: 1.1rem;
            margin-bottom: 0.25rem;
        }}
        .observer .title {{
            color: var(--muted);
            font-size: 0.85rem;
            margin-bottom: 1rem;
        }}
        .observer p {{
            margin-bottom: 0.8rem;
            font-size: 0.95rem;
        }}
        .observer .quote {{
            font-style: italic;
            color: #bbb;
            border-left: 2px solid #444;
            padding-left: 1rem;
            margin: 1rem 0;
        }}
        footer {{
            text-align: center;
            color: var(--muted);
            font-size: 0.8rem;
            padding: 2rem 0;
            border-top: 1px solid var(--border);
            margin-top: 3rem;
        }}
        @media (max-width: 600px) {{
            h1 {{ font-size: 1.8rem; }}
            .container {{ padding: 1rem; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Morning Briefing</h1>
            <p class="date">{display_date}</p>
            <p style="color: var(--muted); font-size: 0.85rem; margin-top: 0.5rem;">Combined NYT + WSJ Analysis</p>
        </header>

        {content}

        <footer>
            <p>Powered by Hermes Agent Pipeline · Observer Commentary</p>
            <p style="margin-top:0.3rem;">Full briefing generated daily at 6:30 AM</p>
        </footer>
    </div>
</body>
</html>
"""


def extract_date_from_filename(filename):
    """Extract YYYY-MM-DD from a filename like nyt_briefing_2026-06-04.html"""
    match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(filename))
    if match:
        return match.group(1)
    return None


def find_latest_files(input_dir, source):
    """Find the latest observer HTML file for a given source."""
    pattern = os.path.join(input_dir, f"{source}_briefing_*.html")
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(reverse=True)
    return files[0]


def extract_observer_sections(html_content):
    """Extract observer divs from an HTML file."""
    # Try to find sections with class 'observer'
    pattern = re.compile(r'<div class="observer">(.*?)</div>\s*</div>', re.DOTALL)
    matches = pattern.findall(html_content)
    if matches:
        sections = []
        for m in matches:
            sections.append('<div class="observer">' + m + '</div>')
        return sections

    # Fallback: extract body content between <body> and </body>
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if body_match:
        return [body_match.group(1).strip()]

    return [html_content]


def build_combined(input_dir, output_path):
    sources = ["nyt", "wsj"]
    source_labels = {"nyt": "New York Times", "wsj": "Wall Street Journal"}
    content_parts = []
    latest_date = None

    for source in sources:
        filepath = find_latest_files(input_dir, source)
        if not filepath:
            print(f"Warning: no {source.upper()} briefing file found in {input_dir}")
            continue

        file_date = extract_date_from_filename(filepath)
        if file_date:
            if latest_date is None or file_date > latest_date:
                latest_date = file_date

        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        sections = extract_observer_sections(html)
        sections_html = "\n".join(sections)

        part = f'''<section class="source-section {source}">
    <div class="source-header">
        <h2>{source_labels[source]}</h2>
        <span class="source-tag {source}">{source.upper()}</span>
    </div>
    {sections_html}
</section>'''
        content_parts.append(part)
        print(f"Included: {filepath}")

    if not content_parts:
        print("Error: no source files found.", file=sys.stderr)
        sys.exit(1)

    if latest_date:
        try:
            dt = datetime.strptime(latest_date, "%Y-%m-%d")
            display_date = dt.strftime("%A, %B %d, %Y")
        except ValueError:
            display_date = latest_date
    else:
        display_date = datetime.now().strftime("%A, %B %d, %Y")

    title = f"Morning Briefing — {display_date}"
    full_html = HTML_TEMPLATE.format(
        title=title,
        display_date=display_date,
        content="\n\n".join(content_parts)
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"Combined HTML written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Build combined NYT + WSJ briefing HTML")
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="Directory containing source HTML files")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output HTML file path")
    args = parser.parse_args()

    build_combined(args.input_dir, args.output)


if __name__ == "__main__":
    main()
