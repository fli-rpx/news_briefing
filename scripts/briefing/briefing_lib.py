#!/usr/bin/env python3
"""Shared helpers for the MorningBriefing briefing tooling.

Stdlib only. No side effects at import time.

Ports of proven code:
  - md_inline / md_table_to_html / split_sentences_safe / strip_footer are
    ported from watchdog-wsj-html-from-v3-FIXED.py (proven 2026-09-25).
  - verify_html keeps its two documented bug fixes:
      * >= 3 DISTINCT percentage values (not a hardcoded whitelist)
      * div balance counts "<div " + "<div>" (bare <div> bug fix)
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from html import escape as html_escape

CANONICAL_REPO = "/Users/fudongli/Projects/MorningBriefing"
LEGACY_REPO = "/Users/fudongli/Projects/news_briefing"
SITE_BASE = "https://fli-rpx.github.io/news_briefing/"
HERMES = os.path.expanduser("~/.hermes")
STATE_LOG = os.path.join(HERMES, "state", "briefing_runs.jsonl")
PIPELINE_STATE = "/Users/fudongli/Projects/nytimes_briefing/scripts/pipeline_state.py"

MONTHS = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)

DATE_RX = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
    r"[A-Z][a-z]+ \d{1,2}, \d{4}"
)

# Proven abbreviation list from the FIXED watchdog script: sentence splitting
# must never cut after one of these.
ABBREV = [
    "U.S.", "U.K.", "U.N.", "E.U.", "Inc.", "Corp.", "Co.", "Ltd.", "Mr.", "Ms.",
    "Mrs.", "Dr.", "Sen.", "Gov.", "Rep.", "Gen.", "Lt.", "Col.", "Sgt.", "St.",
    "vs.", "No.", "Jr.", "Sr.", "Ave.", "Blvd.", "Sept.", "Oct.", "Nov.", "Dec.",
    "Jan.", "Feb.", "Mar.", "Apr.", "Aug.", "Jun.", "Jul.",
]

OBSERVER_NAMES = ("翟东升", "金灿荣", "宋鸿兵")

BADGE_SPAN = ' <span class="badge badge-new">NEW</span>'


# ---------------------------------------------------------------- dates

def _dt(iso):
    return datetime.strptime(iso, "%Y-%m-%d")


def today_iso():
    return datetime.now().strftime("%Y-%m-%d")


def date_full(iso):
    """'2026-09-25' -> 'Friday, September 25, 2026'"""
    d = _dt(iso)
    return "%s, %s %d, %d" % (d.strftime("%A"), d.strftime("%B"), d.day, d.year)


def date_card(iso):
    """'2026-09-25' -> 'September 25, 2026' (no leading zero)"""
    d = _dt(iso)
    return "%s %d, %d" % (d.strftime("%B"), d.day, d.year)


def date_title(iso):
    """'2026-09-25' -> 'September 25, 2026 (Friday)'"""
    d = _dt(iso)
    return "%s %d, %d (%s)" % (d.strftime("%B"), d.day, d.year, d.strftime("%A"))


# ---------------------------------------------------------------- repo

def resolve_repo():
    """Env override, else canonical path. sys.exit(3) if not a git repo."""
    repo = os.environ.get("BRIEFING_REPO", CANONICAL_REPO)
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.stderr.write("NOT_A_GIT_REPO: %s\n" % repo)
        sys.exit(3)
    return repo


def _git(repo, args, timeout=60):
    return subprocess.run(
        ["git"] + args, cwd=repo, capture_output=True, text=True, timeout=timeout,
    )


def _warn_legacy_clone():
    """Warn (never fail) if the legacy clone exists and its HEAD is not origin/main."""
    if not os.path.isdir(os.path.join(LEGACY_REPO, ".git")):
        return
    try:
        head = _git(LEGACY_REPO, ["rev-parse", "HEAD"]).stdout.strip()
        origin = _git(LEGACY_REPO, ["rev-parse", "origin/main"]).stdout.strip()
        if head and origin and head != origin:
            sys.stderr.write(
                "WARN: legacy clone %s HEAD differs from origin/main "
                "(unpushed local work?)\n" % LEGACY_REPO
            )
    except Exception:
        pass


def assert_repo_fresh(repo, fetch=True):
    """git fetch origin, compare HEAD with origin/main.

    Returns {"head", "origin_main", "behind", "ahead", "fresh"}.
    A caller must treat behind > 0 as a hard environment error (exit 3).
    """
    if fetch:
        r = _git(repo, ["fetch", "origin"], timeout=180)
        if r.returncode != 0:
            sys.stderr.write(
                "FETCH_FAILED: git fetch origin failed in %s: %s\n"
                % (repo, r.stderr.strip())
            )
            sys.exit(3)
    head = _git(repo, ["rev-parse", "HEAD"]).stdout.strip() or None
    origin_main = _git(repo, ["rev-parse", "origin/main"]).stdout.strip() or None
    if not head:
        sys.stderr.write("NOT_A_GIT_REPO: %s\n" % repo)
        sys.exit(3)
    ahead = behind = 0
    if origin_main:
        r = _git(repo, ["rev-list", "--left-right", "--count", "HEAD...origin/main"])
        if r.returncode == 0:
            parts = r.stdout.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])
    _warn_legacy_clone()
    return {
        "head": head,
        "origin_main": origin_main,
        "behind": behind,
        "ahead": ahead,
        "fresh": origin_main is not None and behind == 0,
    }


def require_fresh(repo, fetch=True):
    """assert_repo_fresh + the mandated STALE_REPO exit(3) behaviour."""
    info = assert_repo_fresh(repo, fetch=fetch)
    if info["behind"] > 0:
        sys.stderr.write(
            "STALE_REPO: %s is %d commits behind origin/main — refusing to publish\n"
            % (repo, info["behind"])
        )
        sys.exit(3)
    if info["origin_main"] is None:
        sys.stderr.write("NO_ORIGIN_MAIN: %s has no origin/main ref\n" % repo)
        sys.exit(3)
    return info


# ---------------------------------------------------------------- artifact paths

def paths(pipeline, iso, repo=None):
    """Repo-relative artifact paths and display names for one pipeline/day.

    Keys: html, pdf, pdf_dir, template_glob, card_title, index_title.
    """
    if pipeline == "nyt":
        return {
            "html": "briefings/nyt_%s.html" % iso,
            "pdf": "briefings/nyt_briefing_%s.pdf" % iso,
            "pdf_dir": "briefings",
            "template_glob": "nyt_*.html",
            "card_title": "NYT A-Grade Briefing",
            "index_title": "NYT Briefing - %s" % date_card(iso),
        }
    if pipeline == "wsj":
        return {
            "html": "briefings/wsj_briefing_%s.html" % iso,
            "pdf": "briefings/reports/wsj_briefing_%s.pdf" % iso,
            "pdf_dir": "briefings/reports",
            "template_glob": "wsj_briefing_*.html",
            "card_title": "WSJ Daily Briefing",
            "index_title": "WSJ Briefing - %s" % date_card(iso),
        }
    raise ValueError("unknown pipeline: %r" % pipeline)


def newest_template(repo, pipeline, iso):
    """Newest briefings/<pipeline glob>*.html excluding today's file.

    sys.exit(3) if none. Never hardcodes a date.
    """
    p = paths(pipeline, iso, repo)
    cands = sorted(glob.glob(os.path.join(repo, "briefings", p["template_glob"])))
    today_name = os.path.basename(p["html"])
    cands = [c for c in cands if os.path.basename(c) != today_name]
    if not cands:
        sys.stderr.write(
            "NO_TEMPLATE: no %s under %s/briefings/ (excluding %s)\n"
            % (p["template_glob"], repo, today_name)
        )
        sys.exit(3)
    return cands[-1]


# ---------------------------------------------------------------- markdown ports

def strip_footer(text):
    """Strip a single trailing '<!-- PHASE COMPLETE -->' (proven port)."""
    t = text.rstrip()
    if t.endswith("<!-- PHASE COMPLETE -->"):
        t = t[: -len("<!-- PHASE COMPLETE -->")].rstrip()
    return t


def md_inline(text):
    """Markdown inline -> HTML (port of md_to_html_para).

    **bold** -> <strong>, *italic* -> <em>, HTML-escape the rest but NOT the
    tags just made; '—' -> '&mdash;'; '$' left untouched.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = text.replace("<strong>", "\x00S\x00").replace("</strong>", "\x00/S\x00")
    text = text.replace("<em>", "\x00E\x00").replace("</em>", "\x00/E\x00")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\x00S\x00", "<strong>").replace("\x00/S\x00", "</strong>")
    text = text.replace("\x00E\x00", "<em>").replace("\x00/E\x00", "</em>")
    text = text.replace("—", "&mdash;")
    return text


def split_sentences_safe(text):
    """Sentence split that never cuts inside a **bold** span or an abbreviation."""
    spans = []

    def mask_bold(m):
        spans.append(m.group(0))
        return "\x01%d\x02" % (len(spans) - 1)

    masked = re.sub(r"\*\*.+?\*\*", mask_bold, text)
    for a in ABBREV:
        masked = masked.replace(a, a.replace(".", "\x03"))
    out = []
    for p in re.split(r"(?<=[.!?])\s+", masked):
        p = p.replace("\x03", ".")
        p = re.sub(r"\x01(\d+)\x02", lambda m: spans[int(m.group(1))], p)
        if p.strip():
            out.append(p.strip())
    return out


def md_table_to_html(block):
    """Pipe table (header + --- separator + rows) -> <table> (proven port)."""
    rows = []
    for line in block.strip().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    thead, body = rows[0], rows[1:]
    h = ("<table><thead><tr>"
         + "".join("<th>%s</th>" % md_inline(c) for c in thead)
         + "</tr></thead><tbody>")
    for r in body:
        h += "<tr>" + "".join("<td>%s</td>" % md_inline(c) for c in r) + "</tr>"
    return h + "</tbody></table>"


# ---------------------------------------------------------------- verification

def expected_title(pipeline, iso):
    if pipeline == "nyt":
        return "<title>NYT Briefing — %s</title>" % date_title(iso)
    return "<title>WSJ Daily Briefing &mdash; %s</title>" % date_full(iso)


def verify_html(path, pipeline, iso, text_only=True):
    """Structural checks. Returns (ok, errors)."""
    if not os.path.exists(path):
        return False, ["file not found: %s" % path]
    raw = open(path, encoding="utf-8").read()
    h = raw.strip()
    errs = []

    # 1. termination
    if h.count("</html>") != 1:
        errs.append("</html> count: %d (expected 1)" % h.count("</html>"))
    if h.count("</body>") != 1:
        errs.append("</body> count: %d (expected 1)" % h.count("</body>"))

    # 2. PHASE COMPLETE exactly once
    n_phase = h.count("<!-- PHASE COMPLETE -->")
    if n_phase != 1:
        errs.append("<!-- PHASE COMPLETE --> count: %d (expected 1)" % n_phase)

    # 3. observer names
    for name in OBSERVER_NAMES:
        if name not in h:
            errs.append("missing observer %s" % name)

    # 4. >= 3 distinct percentages (bug fix: not a hardcoded whitelist)
    pct = set(re.findall(r"\b(\d{1,3})%", h))
    if len(pct) < 3:
        errs.append(
            "too few distinct percentages: %d (%s)"
            % (len(pct), sorted(pct))
        )
    tr_count = len(re.findall(r"<tr>", h))
    if tr_count < 3:
        errs.append("too few <tr> rows: %d (expected 3+)" % tr_count)

    # 5. correct <title> for iso + a date string
    if expected_title(pipeline, iso) not in h:
        errs.append("missing expected %s" % expected_title(pipeline, iso))
    if date_card(iso) not in h:
        if not re.search(
            r"(%s)\s+\d{1,2},\s+\d{4}" % "|".join(MONTHS), h
        ):
            errs.append("no 'Month D, YYYY' date string found")

    # 6. footer present and inside body
    body_start = h.find("<body")
    body_end = h.find("</body>")
    footer_at = h.find('class="footer"')
    if footer_at < 0:
        errs.append('missing class="footer"')
    elif body_start >= 0 and body_end > 0 and not (body_start < footer_at < body_end):
        errs.append("footer not inside <body>")

    # 7. size
    sz = len(h)
    if sz < 5000:
        errs.append("file too small: %d bytes (expected >5000)" % sz)
    elif sz > 500000:
        errs.append("file suspiciously large: %d bytes" % sz)

    # 8. text-only
    if text_only:
        refs = re.findall(
            r"(img src|background-image|hero_bg|cartoon\.jpg|\./assets/images/)", h
        )
        if refs:
            errs.append("text-only mode but found image references: %s" % refs)
        for lit in ("assets/images", "url("):
            if lit in h:
                errs.append("text-only violation: found %r" % lit)

    # 9. balanced divs (bug fix: count "<div " + "<div>")
    open_divs = h.count("<div ") + h.count("<div>")
    close_divs = h.count("</div>")
    if open_divs != close_divs:
        errs.append("unbalanced <div>: %d open, %d closed" % (open_divs, close_divs))

    return (not errs), errs


# ---------------------------------------------------------------- gallery

def _div_balance(html):
    return html.count("<div ") + html.count("<div>"), html.count("</div>")


def _matching_div_close(html, start):
    """Index just past the </div> matching the <div at start."""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", html[start:]):
        if m.group(0).startswith("<div"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start + m.end()
    raise ValueError("unbalanced <div> while scanning gallery card")


def _gallery_fallback_card(pipeline, iso, desc):
    """Literal card template from the domain spec (used when no prior card exists)."""
    p = paths(pipeline, iso)
    return (
        '      <div class="briefing-card">\n'
        '        <div class="briefing-date">%s</div>\n'
        '        <h3 class="briefing-title">%s</h3>\n'
        '        <p class="briefing-desc">%s</p>\n'
        '        <div class="briefing-links">\n'
        '          <a href="%s" class="btn btn-primary">Read</a>\n'
        '          <a href="%s" class="btn btn-secondary">PDF</a>\n'
        '        </div>\n'
        '      </div>'
        % (date_card(iso), p["card_title"], html_escape(desc, quote=False),
           os.path.basename(p["html"]), os.path.basename(p["pdf"]) if pipeline == "nyt"
           else "reports/" + os.path.basename(p["pdf"]))
    )


def gallery_transform(html, pipeline, iso, desc, badges=True):
    """Pure gallery transform. Returns the new gallery HTML string."""
    p = paths(pipeline, iso)
    prefix = "nyt" if pipeline == "nyt" else "wsj_briefing"
    target_name = os.path.basename(p["html"])
    pdf_href = (os.path.basename(p["pdf"]) if pipeline == "nyt"
                else "reports/" + os.path.basename(p["pdf"]))

    # strip ALL existing badge spans globally (safe: the CSS rule has no <span>)
    html = html.replace(BADGE_SPAN, "")

    target_idx = html.find('href="%s"' % target_name)
    if target_idx >= 0:
        # upsert: today's card already exists — rewrite the date text, the
        # desc, and both hrefs IN PLACE; the card stays at its position and
        # nothing is inserted
        start = html.rfind('<div class="briefing-card">', 0, target_idx)
        if start < 0:
            sys.stderr.write("GALLERY_INVALID: card open not found above %s\n" % target_name)
            sys.exit(1)
        end = _matching_div_close(html, start)
        card = html[start:end]
        card = re.sub(r'href="[^"]*?\.html"', 'href="%s"' % target_name, card, count=1)
        card = re.sub(r'href="[^"]*?\.pdf"', 'href="%s"' % pdf_href, card, count=1)
        card = re.sub(
            r'<div class="briefing-date">.*?</div>',
            '<div class="briefing-date">%s</div>' % date_card(iso),
            card, count=1, flags=re.S,
        )
        card = re.sub(
            r'<p class="briefing-desc">.*?</p>',
            '<p class="briefing-desc">%s</p>' % html_escape(desc, quote=False),
            card, count=1, flags=re.S,
        )
        html = html[:start] + card + html[end:]
    else:
        card = None
        insert_pos = -1
        dates = re.findall(r'href="%s_(\d{4}-\d{2}-\d{2})\.html"' % re.escape(prefix), html)
        if dates:
            # clone the most recent existing card of the SAME pipeline and
            # insert it directly above the same-pipeline card whose date is
            # the greatest date strictly less than the target
            older = [d for d in dates if d < iso]
            prev_iso = max(older) if older else min(dates)
            prev_html_name = "%s_%s.html" % (prefix, prev_iso)
            idx = html.find('href="%s"' % prev_html_name)
            start = html.rfind('<div class="briefing-card">', 0, idx)
            if start < 0:
                sys.stderr.write("GALLERY_INVALID: card open not found above %s\n" % prev_html_name)
                sys.exit(1)
            end = _matching_div_close(html, start)
            card = html[start:end]
            # substitute only the date string, the desc, and the two hrefs
            card = card.replace('href="%s"' % prev_html_name,
                                'href="%s"' % target_name)
            card = re.sub(r'href="[^"]*?\.pdf"', 'href="%s"' % pdf_href, card, count=1)
            card = re.sub(
                r'<div class="briefing-date">.*?</div>',
                '<div class="briefing-date">%s</div>' % date_card(iso),
                card, count=1, flags=re.S,
            )
            card = re.sub(
                r'<p class="briefing-desc">.*?</p>',
                '<p class="briefing-desc">%s</p>' % html_escape(desc, quote=False),
                card, count=1, flags=re.S,
            )
            insert_pos = start
        else:
            # cold start: no card of this pipeline exists at all. Inserting at
            # the top of the grid is only acceptable on this cold-start path —
            # it is not exercised while any same-pipeline card exists.
            card = _gallery_fallback_card(pipeline, iso, desc)
            grid = html.find('<div class="briefing-grid">')
            if grid < 0:
                sys.stderr.write("GALLERY_INVALID: no briefing-grid found\n")
                sys.exit(1)
            insert_pos = grid + len('<div class="briefing-grid">')

        # insert the new card directly above the anchor card
        html = html[:insert_pos] + card + "\n\n" + html[insert_pos:]

    # re-add exactly one badge to every card whose date == today
    if badges:
        d = date_card(iso)
        html = html.replace(
            '<div class="briefing-date">%s</div>' % d,
            '<div class="briefing-date">%s%s</div>' % (d, BADGE_SPAN),
        )
    return html


def gallery_upsert(repo, pipeline, iso, desc, badges=True):
    """Insert/update today's card in briefings/gallery.html. Returns the path."""
    path = os.path.join(repo, "briefings", "gallery.html")
    html = open(path, encoding="utf-8").read()
    new_html = gallery_transform(html, pipeline, iso, desc, badges=badges)
    opens, closes = _div_balance(new_html)
    if opens != closes:
        sys.stderr.write(
            "GALLERY_UNBALANCED: %d open vs %d closed divs — refusing to write\n"
            % (opens, closes)
        )
        sys.exit(1)
    if not new_html.rstrip().endswith("</html>"):
        sys.stderr.write("GALLERY_INVALID: file does not end with </html>\n")
        sys.exit(1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_html)
    return path


# ---------------------------------------------------------------- indexes

def root_index_apply(data, pipeline, iso):
    """Upsert this pipeline's entry in the root reports_index.json (a list)."""
    p = paths(pipeline, iso)
    entry = {"date": iso, "type": pipeline, "title": p["index_title"], "url": p["html"]}
    for i, e in enumerate(data):
        if isinstance(e, dict) and e.get("date") == iso and e.get("type") == pipeline:
            data[i] = entry
            return data
    data.append(entry)
    return data


def data_index_apply(d, pipeline, iso):
    """Upsert only this pipeline's key under data/reports_index.json (date -> obj)."""
    p = paths(pipeline, iso)
    day = d.get(iso)
    if not isinstance(day, dict):
        day = {}
        d[iso] = day
    day[pipeline] = {"pdf": os.path.basename(p["pdf"]), "local": p["html"]}
    return d


def _write_json_proven(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    try:
        with open(path, encoding="utf-8") as f:
            json.load(f)
    except Exception as exc:
        sys.stderr.write("INDEX_INVALID: %s failed to re-parse: %s\n" % (path, exc))
        sys.exit(1)


def index_upsert(repo, pipeline, iso):
    """Upsert both index files, preserving every other key and key order."""
    root = os.path.join(repo, "reports_index.json")
    with open(root, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        sys.stderr.write("INDEX_INVALID: %s must contain a JSON list\n" % root)
        sys.exit(1)
    _write_json_proven(root, root_index_apply(data, pipeline, iso))

    dpath = os.path.join(repo, "data", "reports_index.json")
    with open(dpath, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        sys.stderr.write("INDEX_INVALID: %s must contain a JSON object\n" % dpath)
        sys.exit(1)
    _write_json_proven(dpath, data_index_apply(d, pipeline, iso))
    return None


# ---------------------------------------------------------------- git / cdn / log

def git_commit_push(repo, files, message, push=True):
    """Stage exactly `files`, commit, push (with one rebase-retry). Never 'git add -A'.

    On rebase conflict: abort cleanly and sys.exit(5).
    Returns {"committed": bool, "commit": sha|None, "pushed": bool}.
    """
    files = [f for f in files if f]
    r = _git(repo, ["add", "--"] + files)
    if r.returncode != 0:
        sys.stderr.write("GIT_ADD_FAILED: %s\n" % r.stderr.strip())
        sys.exit(1)
    staged = _git(repo, ["diff", "--cached", "--name-only"]).stdout.split()
    if not staged:
        return {"committed": False, "commit": None, "pushed": False}
    r = _git(repo, ["commit", "-m", message])
    if r.returncode != 0:
        sys.stderr.write("GIT_COMMIT_FAILED: %s\n" % r.stderr.strip())
        sys.exit(1)
    commit = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    if not push:
        return {"committed": True, "commit": commit, "pushed": False}
    r = _git(repo, ["push", "origin", "main"], timeout=180)
    if r.returncode == 0:
        return {"committed": True, "commit": commit, "pushed": True}
    # push rejected: rebase onto origin and retry once
    sys.stderr.write("PUSH_REJECTED: attempting git pull --rebase --autostash\n")
    r2 = _git(repo, ["pull", "--rebase", "--autostash"], timeout=180)
    if r2.returncode != 0:
        _git(repo, ["rebase", "--abort"])
        sys.stderr.write(
            "GIT_CONFLICT: pull --rebase failed; rebase aborted, tree restored.\n"
            "Resolve manually: git -C %s status; then re-run briefing_publish.\n" % repo
        )
        sys.exit(5)
    r3 = _git(repo, ["push", "origin", "main"], timeout=180)
    if r3.returncode != 0:
        sys.stderr.write(
            "GIT_PUSH_FAILED after rebase: %s\n" % r3.stderr.strip()
        )
        sys.exit(5)
    return {"committed": True, "commit": commit, "pushed": True}


def _sha256_file(path):
    """sha256 hex of a local file, or None when it is missing/unreadable."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def cdn_verify(urls, attempts=6, delay=15, expect=None):
    """GET each URL with a ?cb=<epoch> cache-buster and verify the SERVED CONTENT.

    `expect` maps url -> {"local": path, "needle": str}. A URL passes only when the
    response is HTTP 200 AND the served bytes match the local file's sha256 (or, when
    no local file is available, contain `needle`). The sha256 comparison is the point:
    a 200 alone cannot tell a fresh publish from a stale CDN entry or a push that
    silently failed, so a URL with no expectation is reported as unchecked rather
    than ok. Retries cover the GitHub Pages rebuild lag after a push.

    Returns {url: {"ok", "status", "attempts", "checked", "sha_match",
                   "needle_match", "served_sha256", "local_sha256", "error"}}.
    """
    expect = expect or {}
    results = {}
    for url in urls:
        spec = expect.get(url) or {}
        local = spec.get("local")
        needle = spec.get("needle")
        want = _sha256_file(local) if local else None
        ok = False
        status = None
        err = None
        sha_match = None
        needle_match = None
        served_sha = None
        attempt = 0
        for attempt in range(1, attempts + 1):
            cb = "%s%scb=%d" % (url, "&" if "?" in url else "?", int(time.time()))
            try:
                req = urllib.request.Request(
                    cb, headers={"User-Agent": "briefing-publish/1.0",
                                 "Cache-Control": "no-cache"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    status = resp.status
                    body = resp.read()
                served_sha = hashlib.sha256(body).hexdigest()
                sha_match = (served_sha == want) if want else None
                if needle is not None:
                    needle_match = needle in body.decode("utf-8", "replace")
                if status != 200:
                    ok = False
                elif want is not None:
                    ok = bool(sha_match)
                elif needle is not None:
                    ok = bool(needle_match)
                else:
                    ok = False  # no expectation supplied: unverifiable, not ok
            except Exception as exc:  # noqa: BLE001 - report any network failure
                err = str(exc)
                ok = False
            if ok:
                break
            if attempt < attempts:
                time.sleep(delay)
        results[url] = {
            "ok": ok,
            "status": status,
            "attempts": attempt,
            "checked": bool(want is not None or needle is not None),
            "sha_match": sha_match,
            "needle_match": needle_match,
            "served_sha256": (served_sha or "")[:12] or None,
            "local_sha256": (want or "")[:12] or None,
            "error": err,
        }
    return results
def run_log(entry):
    """Append one JSON line to ~/.hermes/state/briefing_runs.jsonl."""
    os.makedirs(os.path.dirname(STATE_LOG), exist_ok=True)
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "pipeline": entry.get("pipeline"),
        "date": entry.get("date"),
        "stage": entry.get("stage"),
        "ok": entry.get("ok"),
        "detail": entry.get("detail"),
    }
    for k, v in entry.items():
        if k not in rec:
            rec[k] = v
    with open(STATE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return STATE_LOG
