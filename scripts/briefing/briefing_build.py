#!/usr/bin/env python3
"""Deterministic V3-markdown -> briefing HTML builder ("container-split rebuild").

Usage:
    briefing_build.py --pipeline {nyt,wsj} [--date ISO] [--out PATH] [--template PATH] [--json]

Exit codes: 0 = built and verified, 1 = build/verify failure, 3 = environment
(no template / bad template). Prints a compact JSON summary with --json.
"""
import argparse
import json
import os
import re
import sys
import tempfile

try:
    from .briefing_lib import (
        DATE_RX, HERMES, date_card, date_full, date_title, md_inline,
        md_table_to_html, newest_template, paths, resolve_repo,
        split_sentences_safe, strip_footer, today_iso, verify_html,
    )
except ImportError:  # run as a plain script
    from briefing_lib import (
        DATE_RX, HERMES, date_card, date_full, date_title, md_inline,
        md_table_to_html, newest_template, paths, resolve_repo,
        split_sentences_safe, strip_footer, today_iso, verify_html,
    )

FOOTER_MARKERS = ('<footer class="footer">', '<div class="footer">')


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- section parsing

def _sections(v3):
    """Split V3 on '^## ' into {heading: body lines}; preamble dropped."""
    sec_map = {}
    for s in [x for x in re.split(r"^## ", v3, flags=re.M) if x.strip()][1:]:
        lines = s.splitlines()
        sec_map[lines[0].strip().rstrip("#").strip()] = lines[1:]

    def get_sec(keyword):
        for k, v in sec_map.items():
            if k.lower().startswith(keyword.lower()):
                return k, v
        return None, []

    return sec_map, get_sec


def _tables_in(lines):
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            blocks.append("\n".join(block))
        else:
            i += 1
    return blocks


# ---------------------------------------------------------------- NYT rendering

# Observer identity table: V3 subsection name -> card class, icon glyph,
# English name, and credential line (em dash is a literal U+2014 in output).
NYT_OBSERVERS = (
    ("翟东升", "zhai", "翟", "Zhai Dongsheng", "CDP Fellow, Renmin University"),
    ("金灿荣", "jin", "金", "Jin Canrong", "Professor, Renmin University"),
    ("宋鸿兵", "song", "宋", "Song Hongbing", "Author, Currency Wars"),
)


def _nyt_inline(text):
    """md_inline variant for the NYT pipeline: converts **bold**/<em>italic</em>
    and HTML-escapes, but keeps em dashes literal (published pages do not
    render &mdash; in body text)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = text.replace("<strong>", "\x00S\x00").replace("</strong>", "\x00/S\x00")
    text = text.replace("<em>", "\x00E\x00").replace("</em>", "\x00/E\x00")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\x00S\x00", "<strong>").replace("\x00/S\x00", "</strong>")
    text = text.replace("\x00E\x00", "<em>").replace("\x00/E\x00", "</em>")
    return text


def _render_nyt_cluster(lines):
    """One <div class="cluster"> per item, each wrapping <h3> + <p>.

    '**Label:** TEXT' becomes the h3 label (with 'Thematic hook' title-cased)
    and TEXT the paragraph; '**Articles:**' lines are dropped entirely.
    """
    html = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
        elif line.startswith("### "):
            html += "<h3>%s</h3>\n" % _nyt_inline(line[4:].strip())
            i += 1
        elif line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            html += _nyt_table_to_html(block) + "\n"
        elif re.fullmatch(r"-{3,}", line):
            i += 1
        else:
            m = re.match(r"^\*\*(.+?):\*\*\s*(.*)$", line)
            if m:
                label = m.group(1).strip()
                rest = m.group(2).strip()
                if label.lower() == "articles":
                    i += 1
                    continue
                if label.lower() == "thematic hook":
                    label = "Thematic Hook"
                html += '<div class="cluster">\n<h3>%s</h3>\n' % _nyt_inline(label)
                if rest:
                    html += "<p>%s</p>\n" % _nyt_inline(rest)
                html += "</div>\n"
            else:
                html += "<p>%s</p>\n" % _nyt_inline(line)
            i += 1
    return html


def _nyt_table_to_html(lines):
    """NYT pipe table -> the published multi-line <table> markup."""
    rows = []
    for line in lines:
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
    h = ("<table>\n<thead>\n<tr>"
         + "".join("<th>%s</th>" % _nyt_inline(c) for c in thead)
         + "</tr>\n</thead>\n<tbody>\n")
    for r in body:
        h += "<tr>" + "".join("<td>%s</td>" % _nyt_inline(c) for c in r) + "</tr>\n"
    return h + "</tbody>\n</table>"


def _render_nyt_observer_cards(lines):
    """Published observer-card markup: no section heading, one card per
    '### name' subsection with header row + icon + per-paragraph body."""
    text = "\n".join(lines)
    parts = re.split(r"^### ", text, flags=re.M)
    html = ""
    for part in parts[1:]:
        plines = [l.strip() for l in part.splitlines() if l.strip()]
        if not plines:
            continue
        name = plines[0]
        paras = [
            l for l in plines[1:]
            if not re.fullmatch(r"-{3,}", l) and not l.startswith("<!--")
        ]
        meta = next((o for o in NYT_OBSERVERS if o[0] == name), None)
        if meta:
            _, cls, icon, english, role = meta
        else:
            cls, icon, english, role = "", name[:1], "", ""
        header = "<strong>%s</strong>" % name
        if english:
            header += " (%s)" % english
        if role:
            header += " — %s" % role
        card = '<div class="observer-card %s">\n' % cls
        card += '<div class="observer-header">\n'
        card += '<div class="observer-icon">%s</div>\n' % icon
        card += "<div>%s</div>\n" % header
        card += "</div>\n"
        card += '<div class="observer-body">\n'
        for para in paras:
            card += "<p>%s</p>\n" % _nyt_inline(para)
        card += "</div>\n</div>\n"
        html += card
    return html


def _render_nyt(v3):
    _, get_sec = _sections(v3)
    blocks = []
    for n in range(1, 6):
        k, v = get_sec("Cluster %d" % n)
        if not k:
            sys.stderr.write("WARN missing section: Cluster %d\n" % n)
            continue
        sec = '<h2 class="section-title">%s</h2>\n' % _nyt_inline(k)
        sec += _render_nyt_cluster(v)
        blocks.append(sec.rstrip("\n"))
    k, v = get_sec("Prediction Summary")
    if k:
        sec = '<h2 class="section-title">Predictions</h2>\n'
        for block in _tables_in(v):
            sec += _nyt_table_to_html(block.splitlines()) + "\n"
        blocks.append(sec.rstrip("\n"))
    k, v = get_sec("Observer Commentary")
    if k:
        blocks.append(_render_nyt_observer_cards(v).rstrip("\n"))
    # content sits between '<div class="container">\n' and '\n' + tail; the
    # leading '\n' reproduces the blank line after the container open tag and
    # the trailing '\n' the blank line before the footer.
    return "\n" + "\n".join(blocks) + "\n"


def _derive_hero(v3):
    """Fallback hero line: first 5 Cluster 1 article titles (V3 order, '(#N)'
    suffixes stripped) joined with ' · '."""
    m = re.search(r"^## Cluster 1\b.*?(?=^## |\Z)", v3, flags=re.M | re.S)
    if not m:
        return ""
    titles = []
    for line in m.group(0).splitlines():
        lm = re.match(r"^\*\*(.+?):\*\*", line.strip())
        if not lm:
            continue
        label = lm.group(1).strip()
        if label.lower() in ("thematic hook", "articles", "prediction"):
            continue
        titles.append(re.sub(r"\s*\(#\d+\)", "", label).strip())
        if len(titles) == 5:
            break
    return " · ".join(titles)


def _nyt_footer_prose(v3):
    """Trailing '*Prepared from ...*' italic line, with ISO dates rewritten
    to the 'Month D, YYYY' display form (followed by the house-style comma,
    e.g. 'the September 25, 2026, New York Times print edition')."""
    m = re.search(r"^\*(Prepared from\b.+?)\*\s*$", v3, flags=re.M)
    if not m:
        return None
    prose = m.group(1).strip()

    def _iso(mm):
        return date_card("%s-%s-%s" % (mm.group(1), mm.group(2), mm.group(3))) + ","

    return re.sub(r"\b(20\d{2})-(\d{2})-(\d{2})\b", _iso, prose)


# ---------------------------------------------------------------- WSJ rendering

def _render_section(title, body):
    """Section renderer ported from the FIXED watchdog script."""
    html = '<h2 class="section-title">%s</h2>\n<div class="cluster">\n' % md_inline(title)
    i = 0
    while i < len(body):
        line = body[i].strip()
        if not line:
            i += 1
        elif line.startswith("### "):
            html += "<h3>%s</h3>\n" % md_inline(line[4:])
            i += 1
        elif line.startswith("|"):
            block = []
            while i < len(body) and body[i].strip().startswith("|"):
                block.append(body[i])
                i += 1
            html += md_table_to_html("\n".join(block)) + "\n"
        elif re.fullmatch(r"-{3,}", line):
            i += 1
        else:
            para = []
            while (i < len(body) and body[i].strip()
                   and not body[i].strip().startswith("### ")
                   and not body[i].strip().startswith("|")
                   and not re.fullmatch(r"-{3,}", body[i].strip())):
                para.append(body[i].strip())
                i += 1
            if para:
                html += "<p>%s</p>\n" % md_inline(" ".join(para))
    return html + "</div>\n"


def _render_wsj(v3):
    _, get_sec = _sections(v3)
    content = ""
    _, ex = get_sec("Executive")
    if ex:
        content += ('<h2 class="section-title">Executive Summary</h2>\n'
                    '<div class="cluster">\n<ul>\n')
        paras = [l.strip() for l in ex if l.strip() and not re.fullmatch(r"-{3,}", l.strip())]
        for sent in split_sentences_safe(paras[0] if paras else ""):
            conv = md_inline(sent)
            content += "<li>%s</li>\n" % conv if "<strong>" in conv \
                else "<li><strong>%s</strong></li>\n" % conv
        content += "</ul>\n"
        for p in paras[1:]:
            content += "<p>%s</p>\n" % md_inline(p)
        content += "</div>\n"
    for key in ("Cluster 1", "Cluster 2", "Cluster 3", "Cluster 4", "Confirmations"):
        k, v = get_sec(key)
        if k:
            content += _render_section(k, v)
        else:
            sys.stderr.write("WARN missing section: %s\n" % key)
    content += '<h2 class="section-title">观察者评论</h2>\n'
    for label, fn in [
        ("翟东升——体系/结构视角", "wsj_observer.md"),
        ("金灿荣——美国政治/战略相持视角", "wsj_observer2.md"),
        ("宋鸿兵——货币/债务/周期视角", "wsj_observer3.md"),
    ]:
        path = os.path.join(HERMES, fn)
        if not os.path.exists(path):
            sys.stderr.write("WARN missing observer: %s\n" % fn)
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        paras = [l.strip() for l in strip_footer(raw).splitlines()
                 if l.strip() and not re.fullmatch(r"-{3,}", l.strip())]
        body_html = "".join("<p>%s</p>\n" % md_inline(p) for p in paras)
        content += '<div class="observer-card"><h4>%s</h4>%s</div>\n' % (label, body_html)
    return content


# ---------------------------------------------------------------- template splice

def _splice(pipeline, iso, template, content, hero=None, footer_prose=None):
    with open(template, encoding="utf-8") as f:
        tpl = f.read()
    if '<div class="container">' not in tpl:
        sys.stderr.write("TEMPLATE_INVALID: no <div class=\"container\"> in %s\n" % template)
        sys.exit(3)
    head = tpl[:tpl.index('<div class="container">')]
    marker = next((m for m in FOOTER_MARKERS if m in tpl), None)
    if marker is None:
        sys.stderr.write(
            "TEMPLATE_INVALID: neither %r nor %r found in %s\n"
            % (FOOTER_MARKERS[0], FOOTER_MARKERS[1], template)
        )
        sys.exit(3)
    tail = tpl[tpl.index(marker):]

    # weekday-date literals -> today's full date (head AND tail)
    head = DATE_RX.sub(date_full(iso), head)
    tail = DATE_RX.sub(date_full(iso), tail)
    # footer ISO date -> today's
    tail = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", iso, tail)
    # fix the <title> (the live NYT bug: stale August title on a September page)
    if pipeline == "nyt":
        new_title = "<title>NYT Briefing — %s</title>" % date_title(iso)
    else:
        new_title = "<title>WSJ Daily Briefing &mdash; %s</title>" % date_full(iso)
    head = re.sub(r"<title>[^<]*</title>", new_title, head, count=1)

    # NYT: rebuild the hero block in the head region with today's hero line
    # and date (the template's hero advertises the template day's headlines).
    if pipeline == "nyt" and hero is not None:
        hero_block = (
            '<section class="hero">\n<div class="hero-content">\n'
            '<h1>NYT Daily Briefing</h1>\n'
            '<p class="hero-subtitle">%s</p>\n'
            '<p class="hero-meta">%s</p>\n</div>\n</section>'
            % (hero, date_full(iso))
        )
        head = re.sub(r'<section class="hero">.*?</section>',
                      lambda m: hero_block, head, count=1, flags=re.S)
        head = head.replace('<body>\n\n<section class="hero">',
                            '<body>\n<section class="hero">')
    # NYT: the footer's 'Prepared from ...' prose comes from the V3, not the
    # template (the template line describes the template day's edition).
    if pipeline == "nyt" and footer_prose is not None:
        tail = re.sub(r"<p>Prepared from [^<]*</p>",
                      lambda m: "<p>%s</p>" % footer_prose, tail, count=1)

    html = head + '<div class="container">\n' + content + "\n" + tail

    # remove escaped PHASE COMPLETE artifacts (with or without wrapping <p>)
    html = html.replace("<p>&lt;!-- PHASE COMPLETE --&gt;</p>\n", "")
    html = html.replace("<p>&lt;!-- PHASE COMPLETE --&gt;</p>", "")
    html = html.replace("&lt;!-- PHASE COMPLETE --&gt;", "")
    # exactly one real marker: NYT keeps the published pages' end-of-file
    # placement (after </html>); WSJ keeps it immediately before </body>.
    html = html.replace("<!-- PHASE COMPLETE -->", "")
    if pipeline == "nyt":
        return html.rstrip() + "\n<!-- PHASE COMPLETE -->\n"
    html = html.replace("</body>", "<!-- PHASE COMPLETE -->\n</body>")
    return html.rstrip() + "\n"


# ---------------------------------------------------------------- public API

def build_html(pipeline, iso, template=None, out=None, hero=None, desc=None):
    """Build the briefing page. Returns {"html", "template", "out", "bytes",
    "hero", "desc"}.

    Raises BuildError on missing input / text-only invariant violations.
    sys.exit(3) on missing/broken template (environment error).
    """
    v3_path = os.path.join(HERMES, "%s_briefing_v3.md" % pipeline)
    if not os.path.exists(v3_path):
        raise BuildError("V3_MISSING: %s" % v3_path)
    with open(v3_path, encoding="utf-8") as f:
        v3 = f.read()
    footer_prose = None
    if pipeline == "nyt":
        if hero is None:
            hero = _derive_hero(v3)
        if desc is None:
            desc = hero
        footer_prose = _nyt_footer_prose(v3)
        content = _render_nyt(v3)
    else:
        content = _render_wsj(v3)
    if template is None:
        template = newest_template(resolve_repo(), pipeline, iso)
    html = _splice(pipeline, iso, template, content, hero=hero,
                   footer_prose=footer_prose)
    leaks = []
    for lit, msg in (("<img", "image tag leaked into output"),
                     ("assets/images", "image path leaked into output"),
                     ("url(", "css url() leaked into output")):
        if lit in html:
            leaks.append(msg)
    if leaks:
        raise BuildError("; ".join(leaks))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
    return {"html": html, "template": template, "out": out, "bytes": len(html),
            "hero": hero, "desc": desc}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build briefing HTML from V3 markdown")
    ap.add_argument("--pipeline", required=True, choices=["nyt", "wsj"])
    ap.add_argument("--date", default=None, help="ISO date (default: today)")
    ap.add_argument("--out", default=None, help="output path (default: /tmp/<html name>)")
    ap.add_argument("--template", default=None, help="template HTML (default: newest in repo)")
    ap.add_argument("--hero", default=None,
                    help="NYT hero line (default: derived from V3 Cluster 1 titles)")
    ap.add_argument("--desc", default=None,
                    help="gallery card description (default: the hero line)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    iso = args.date or today_iso()
    out = args.out or os.path.join(
        tempfile.gettempdir(), os.path.basename(paths(args.pipeline, iso)["html"]))
    try:
        result = build_html(args.pipeline, iso, template=args.template, out=out,
                            hero=args.hero, desc=args.desc)
    except SystemExit:
        raise
    except BuildError as exc:
        summary = {"out": out, "bytes": 0, "template": args.template,
                   "checks_passed": False, "errors": [str(exc)]}
        _emit(summary, args.json)
        return 1
    ok, errors = verify_html(out, args.pipeline, iso, text_only=True)
    summary = {"out": out, "bytes": result["bytes"], "template": result["template"],
               "checks_passed": ok, "errors": errors}
    if args.pipeline == "nyt":
        summary["hero"] = result["hero"]
        summary["desc"] = result["desc"] if result["desc"] is not None else result["hero"]
    _emit(summary, args.json)
    return 0 if ok else 1


def _emit(summary, as_json):
    if as_json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print("out: %s (%d bytes)" % (summary["out"], summary["bytes"]))
        print("template: %s" % summary["template"])
        if summary["checks_passed"]:
            print("checks: PASS")
        else:
            print("checks: FAIL")
            for e in summary["errors"]:
                print("  ERROR: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
