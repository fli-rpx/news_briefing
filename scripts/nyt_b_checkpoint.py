#!/usr/bin/env python3
"""NYT Briefing checkpoint CLI (Steps 11-14).

Prints a JSON summary of which pipeline phases are already done for today.

Usage:
    python3 scripts/nyt_b_checkpoint.py
"""

import json
import os
import struct
import subprocess
import sys
import urllib.request
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.now().strftime("%Y-%m-%d")
PDF_PATH = os.path.expanduser(f"~/.hermes/nyt_briefing_{TODAY}.pdf")
CDN_BASE = "https://fli-rpx.github.io/news_briefing/"


def _error(msg):
    print(msg, file=sys.stderr)


def _file_is_today(path):
    """Check if file was modified today (YYYY-MM-DD)."""
    if not path or not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return mtime.strftime("%Y-%m-%d") == TODAY


def _is_valid_image(path):
    """Validate JPEG/PNG by magic bytes and return (width, height) or None."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
    except OSError:
        return None

    # JPEG: FF D8 FF
    if header.startswith(b"\xff\xd8\xff"):
        return _jpeg_dimensions(path)
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png_dimensions(path)
    return None


def _jpeg_dimensions(path):
    """Parse JPEG SOF markers for width/height."""
    try:
        with open(path, "rb") as f:
            f.read(2)  # SOI
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    return None
                if marker[0] != 0xFF:
                    continue
                code = marker[1]
                if code == 0xD9:  # EOI
                    return None
                if code in (0xD8, 0xD9, 0x00):
                    continue
                # Skip padding bytes
                if code == 0xFF:
                    continue
                # Read segment length
                length_bytes = f.read(2)
                if len(length_bytes) < 2:
                    return None
                length = struct.unpack(">H", length_bytes)[0]
                if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    # SOF markers: precision(1) height(2) width(2)
                    data = f.read(5)
                    if len(data) < 5:
                        return None
                    height, width = struct.unpack(">HH", data[1:5])
                    return width, height
                else:
                    f.seek(length - 2, 1)
    except (OSError, struct.error):
        return None


def _png_dimensions(path):
    """Parse PNG IHDR chunk for width/height."""
    try:
        with open(path, "rb") as f:
            f.read(8)  # signature
            # IHDR chunk: length(4) type(4) width(4) height(4)
            chunk = f.read(16)
            if len(chunk) < 16:
                return None
            width, height = struct.unpack(">II", chunk[8:16])
            return width, height
    except (OSError, struct.error):
        return None


def _image_meets_requirements(path):
    """True if path is a valid image >= 1000x500."""
    dims = _is_valid_image(path)
    if dims is None:
        return False
    width, height = dims
    return width >= 1000 and height >= 500


def check_hero_image():
    """True if /tmp/nyt_hero_bg.jpg exists, is from today, and is a valid >=1000x500 image."""
    path = "/tmp/nyt_hero_bg.jpg"
    if os.path.exists(path) and _file_is_today(path):
        return _image_meets_requirements(path)
    return False


def check_cartoon():
    """True if /tmp/nyt_cartoon.jpg exists, is from today, and is a valid >=1000x500 image."""
    path = "/tmp/nyt_cartoon.jpg"
    if os.path.exists(path) and _file_is_today(path):
        return _image_meets_requirements(path)
    return False


def check_webpage():
    """True if /tmp/nyt_briefing_TODAY.html exists and is >1000 bytes."""
    path = f"/tmp/nyt_briefing_{TODAY}.html"
    if not os.path.exists(path):
        return False
    if not _file_is_today(path):
        return False
    try:
        return os.path.getsize(path) > 1000
    except OSError:
        return False


def _read_index():
    """Load reports_index.json as a list, or None on failure."""
    path = os.path.join(REPO_ROOT, "reports_index.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _nyt_entry_ok(index):
    """True if index contains today's nyt entry with briefings/nyt_ prefix."""
    if not isinstance(index, list):
        return False
    for entry in index:
        if not isinstance(entry, dict):
            continue
        if entry.get("date") == TODAY and entry.get("type") == "nyt":
            url = entry.get("url", "")
            if isinstance(url, str) and url.startswith("briefings/nyt_"):
                return True
    return False


def _cdn_reachable():
    """True if the NYT briefing CDN URL returns HTTP 200."""
    url = f"{CDN_BASE}briefings/nyt_{TODAY}.html"
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "nyt-b-checkpoint/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_publish():
    """True if briefing file exists, index entry is correct, and CDN is live."""
    briefing_path = os.path.join(REPO_ROOT, "briefings", f"nyt_{TODAY}.html")
    if not os.path.exists(briefing_path):
        return False

    index = _read_index()
    if not _nyt_entry_ok(index):
        return False

    return _cdn_reachable()


def main():
    if not os.path.exists(PDF_PATH):
        _error(f"NYT Job A incomplete — no PDF for {TODAY}: {PDF_PATH}")
        return 1

    phases = {
        "hero_image": "done" if check_hero_image() else "pending",
        "cartoon": "done" if check_cartoon() else "pending",
        "webpage": "done" if check_webpage() else "pending",
        "publish": "done" if check_publish() else "pending",
    }

    next_phase = None
    for phase in ("hero_image", "cartoon", "webpage", "publish"):
        if phases[phase] == "pending":
            next_phase = phase
            break

    output = {"date": TODAY, "phases": phases, "next": next_phase}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
