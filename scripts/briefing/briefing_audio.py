#!/usr/bin/env python3
"""Synthesise one briefing page into a spoken MP3 (deterministic TTS).

Usage:
    briefing_audio.py --pipeline {nyt,wsj} --date ISO [--out DIR] [--json]

Reads briefings/<page>.html, strips markup to speakable sentences, and reads
the briefing verbatim (no AI summarisation) via edge-tts. Lines are chunked
at line boundaries (max CHUNK chars per request), stitched with ffmpeg
concat, then re-encoded to 32 kbps mono so the repo stays small.

Exit codes: 0 = mp3 written, 1 = synthesis/ffmpeg failure, 3 = environment
(missing source page / edge-tts / ffmpeg). Failures print one line on stderr;
--json prints {"ok", "path", "seconds", "chunks"} on success.
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser

try:
    from .briefing_lib import resolve_repo
except ImportError:  # run as a plain script
    from briefing_lib import resolve_repo

EDGE_TTS = os.environ.get(
    "EDGE_TTS",
    "/Users/fudongli/.hermes/installs/544e24d9950f205f/environments/"
    "720b66c5e093421c9c4aa73b27c4b09c/venv/bin/edge-tts",
)
VOICE = "en-US-AriaNeural"
VOICE_ZH = "zh-CN-XiaoxiaoNeural"   # CJK-dominant lines (observer sections)
CJK = re.compile(r"[\u4e00-\u9fff]")
CHUNK = 2500                        # chars per synthesis request
ATTEMPTS = 3
ENCODE_ARGS = ["-ac", "1", "-b:a", "32k"]   # mono, 32 kbps — keeps the repo small


class AudioError(Exception):
    pass


def _check_env():
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            sys.stderr.write("AUDIO_ENV: %s not found on PATH\n" % tool)
            sys.exit(3)
    if not os.path.exists(EDGE_TTS):
        sys.stderr.write("AUDIO_ENV: edge-tts not found at %s (set $EDGE_TTS)\n" % EDGE_TTS)
        sys.exit(3)


# ---------------------------------------------------------------- text extraction

class Extract(HTMLParser):
    SKIP = {"script", "style", "nav", "head", "svg", "noscript"}
    BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4",
             "tr", "br", "figcaption", "blockquote"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.out.append("\n## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def to_text(path):
    p = Extract()
    with open(path, encoding="utf-8", errors="ignore") as f:
        p.feed(f.read())
    t = html.unescape("".join(p.out))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return "\n".join(line.strip() for line in t.split("\n")).strip()


def spoken_lines(text):
    """Strip markdown, make every line a speakable sentence."""
    out = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)      # headings
        line = re.sub(r"^\*+\s*", "", line)         # bold bullets
        line = re.sub(r"^[-•·]\s*", "", line)       # dash bullets
        line = line.replace("**", "").replace("*", "")
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        # drop lines with nothing pronounceable (leftover bullets, dashes, symbols)
        if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", line):
            continue
        if not line.endswith((".", "!", "?", ":", ";", '"', "”", "’", ")”")):
            line += "."
        out.append(line)
    return out


def language_segments(lines):
    """Group consecutive lines into (lang, [lines]) runs; 'zh' for CJK-dominant lines."""
    runs, cur, lang = [], [], None
    for line in lines:
        cjk = len(CJK.findall(line))
        this = "zh" if cjk >= 6 and cjk / max(len(line), 1) > 0.15 else "en"
        if this != lang and cur:
            runs.append((lang, cur))
            cur = []
        lang = this
        cur.append(line)
    if cur:
        runs.append((lang, cur))
    return runs


def chunk(lines, target=CHUNK):
    parts, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > target:
            parts.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def plan_parts(src):
    """Briefing HTML -> ordered [(lang, text)] synthesis parts."""
    lines = spoken_lines(to_text(src))
    if not lines:
        raise AudioError("no speakable text in %s" % src)
    parts = []
    for lang, seg in language_segments(lines):
        parts += [(lang, p) for p in chunk(seg)]
    # fold tiny fragments into the previous part: edge-tts refuses near-empty input
    merged = []
    for lang, text in parts:
        if merged and (len(text) < 12 or len(merged[-1][1]) + len(text) <= CHUNK):
            if len(text) < 12:
                p_lang, p_text = merged[-1]
                merged[-1] = (p_lang, p_text + "\n" + text)
                continue
        merged.append((lang, text))
    return merged


# ---------------------------------------------------------------- synthesis

def _synth_part(work, i, lang, text, total):
    voice = VOICE_ZH if lang == "zh" else VOICE
    txt = os.path.join(work, "%02d.txt" % i)
    mp3 = os.path.join(work, "%02d.mp3" % i)
    with open(txt, "w", encoding="utf-8") as f:
        f.write(text)
    ok, err = False, ""
    for attempt in range(ATTEMPTS):
        r = subprocess.run([EDGE_TTS, "-v", voice, "-f", txt, "--write-media", mp3],
                           capture_output=True, text=True)
        ok = r.returncode == 0 and os.path.exists(mp3) and os.path.getsize(mp3) > 1000
        err = r.stderr.strip()
        if ok:
            break
        time.sleep(2 + 2 * attempt)
    sys.stderr.write("[%2d/%d] %s %5d chars -> %5d KB %s\n"
                     % (i + 1, total, lang, len(text),
                        os.path.getsize(mp3) // 1024 if os.path.exists(mp3) else 0,
                        "ok" if ok else "FAILED"))
    if not ok:
        if len(text) < 20:          # negligible residue: skip rather than fail
            sys.stderr.write("    skipping un-speakable %d-char fragment\n" % len(text))
            return None
        raise AudioError("chunk %d/%d failed after %d attempts: %s"
                         % (i + 1, total, ATTEMPTS, err[:200]))
    return mp3


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def synthesize(src, dest, work):
    """Synthesise briefing HTML -> dest mp3. Returns (seconds, chunks)."""
    parts = plan_parts(src)
    words = sum(len(p.split()) for _, p in parts)
    sys.stderr.write("%d words -> %d chunks [en %d / zh %d, %d CJK chars]\n" % (
        words, len(parts),
        sum(1 for l, _ in parts if l == "en"),
        sum(1 for l, _ in parts if l == "zh"),
        sum(len(CJK.findall(p)) for _, p in parts)))
    made = []
    for i, (lang, text) in enumerate(parts):
        mp3 = _synth_part(work, i, lang, text, len(parts))
        if mp3:
            made.append(mp3)
    if not made:
        raise AudioError("no chunks synthesised from %s" % src)

    listing = os.path.join(work, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.write("".join("file '%s'\n" % os.path.basename(m) for m in made))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", listing, "-c", "copy", dest],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AudioError("ffmpeg concat failed: %s" % r.stderr.strip()[:300])
    # re-encode to 32 kbps mono (edge-tts emits wideband stereo)
    tmp_dest = dest + ".reencode.mp3"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", dest] + ENCODE_ARGS
                       + [tmp_dest], capture_output=True, text=True)
    if r.returncode != 0:
        raise AudioError("ffmpeg re-encode failed: %s" % r.stderr.strip()[:300])
    os.replace(tmp_dest, dest)
    return duration(dest), len(made)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Synthesise a briefing page to MP3 via edge-tts (verbatim read)")
    ap.add_argument("--pipeline", required=True, choices=["nyt", "wsj"])
    ap.add_argument("--date", required=True, help="ISO date YYYY-MM-DD")
    ap.add_argument("--out", default=None,
                    help="output directory (default: <repo>/briefings/audio)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    _check_env()
    repo = resolve_repo()
    page = "nyt_%s.html" % args.date if args.pipeline == "nyt" \
        else "wsj_briefing_%s.html" % args.date
    src = os.path.join(repo, "briefings", page)
    if not os.path.exists(src):
        sys.stderr.write("AUDIO_SOURCE_MISSING: %s\n" % src)
        return 3
    out_dir = args.out or os.path.join(repo, "briefings", "audio")
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, "%s_briefing_%s.mp3" % (args.pipeline, args.date))

    work = tempfile.mkdtemp(prefix="briefing_audio_")
    try:
        seconds, chunks = synthesize(src, dest, work)
    except AudioError as exc:
        sys.stderr.write("AUDIO_FAILED: %s\n" % exc)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if args.json:
        print(json.dumps({"ok": True, "path": dest, "seconds": round(seconds, 1),
                          "chunks": chunks}, ensure_ascii=False))
    else:
        print("%s -> %s  %.1f MB  %dm %02ds (%d chunks)"
              % (os.path.basename(src), dest, os.path.getsize(dest) / 1048576.0,
                 int(seconds // 60), int(seconds % 60), chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
