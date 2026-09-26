#!/usr/bin/env python3
"""curl_cffi story discovery (index level: headline + summary only).

Usage:
    briefing_research.py --pipeline {nyt,wsj} [--date ISO] [--out PATH] [--limit N] [--json]

Optional dependency: curl_cffi. If missing, the script re-execs itself once
into <repo>/.venv-briefing/bin/python3 (when that venv exists); otherwise it
prints FALLBACK_REQUIRED and exits 4.
Exit 0 on success; exit 4 if HTTP != 200 or zero stories parsed (the caller then
falls back to the existing Tavily/CDP path).

NOTE: this is a DISCOVERY source only. It provides headline + summary level
data — it is NOT a replacement for article bodies (NYT article URLs return
403; WSJ returns only the ~100-word lede).
"""
import argparse
import json
import os
import re
import sys
import tempfile

try:
    from curl_cffi import requests as cffi_requests
    HAVE_CURL_CFFI = True
except ImportError:
    HAVE_CURL_CFFI = False
    if os.environ.get("BRIEFING_RESEARCH_REEXEC") != "1":
        # one-shot re-exec into the tool venv (which has curl_cffi) before
        # falling back; without the venv, keep the FALLBACK_REQUIRED contract
        try:
            from .briefing_lib import resolve_repo
        except ImportError:  # run as a plain script
            from briefing_lib import resolve_repo
        repo = resolve_repo()
        venv_py = os.path.join(repo, ".venv-briefing", "bin", "python3")
        if os.path.isfile(venv_py) and os.access(venv_py, os.X_OK):
            env = dict(os.environ)
            env["BRIEFING_RESEARCH_REEXEC"] = "1"
            os.execve(venv_py, [venv_py] + sys.argv, env)
        print("FALLBACK_REQUIRED: curl_cffi not installed "
              "(no .venv-briefing at %s)" % venv_py)
        sys.exit(4)

try:
    from .briefing_lib import run_log, today_iso
except ImportError:  # run as a plain script
    from briefing_lib import run_log, today_iso

SOURCES = {
    "nyt": "https://www.nytimes.com/section/todayspaper",
    "wsj": "https://www.wsj.com/",
}
# /print-edition and /front-page return 403/404 — the homepage is the working source.


def _extract_braced(text, start_idx):
    """Extract a balanced {...} object starting at/after start_idx.

    Brace-matching scanner (string/escape aware) — a regex fails on the ~550KB
    preloadedData payload.
    """
    i = text.index("{", start_idx)
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[i:j + 1]
    raise ValueError("unbalanced braces while scanning JSON payload")


def _parse_payload(pipeline, html_text):
    if pipeline == "nyt":
        marker = "window.__preloadedData"
        idx = html_text.find(marker)
        if idx < 0:
            raise ValueError("%s not found in page" % marker)
        payload = _extract_braced(html_text, idx)
        # the payload contains raw JS `undefined` — normalise before json.loads
        payload = re.sub(r":undefined(\s*[,}])", r":null\1", payload)
        return json.loads(payload)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                  html_text, flags=re.S)
    if not m:
        raise ValueError("__NEXT_DATA__ script tag not found in page")
    return json.loads(m.group(1))


def _section_name(node):
    sec = node.get("section")
    if isinstance(sec, dict):
        return sec.get("name") or sec.get("displayName") or ""
    if isinstance(sec, str):
        return sec
    return ""


def _walk(node, out):
    if isinstance(node, dict):
        headline = node.get("headline")
        if isinstance(headline, dict):
            headline = headline.get("default")
        summary = node.get("summary") or node.get("abstract") or node.get("description")
        url = node.get("url") or node.get("webUrl") or node.get("link")
        if isinstance(headline, str) and headline.strip() and (summary or url):
            out.append({
                "headline": headline.strip(),
                "summary": summary.strip() if isinstance(summary, str) else "",
                "url": url if isinstance(url, str) else "",
                "section": _section_name(node),
            })
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def discover(pipeline):
    """Returns (http_status, stories). Raises on network/parse errors."""
    url = SOURCES[pipeline]
    resp = cffi_requests.get(url, impersonate="chrome", timeout=30)
    status = resp.status_code
    if status != 200:
        return status, []
    tree = _parse_payload(pipeline, resp.text)
    stories = []
    _walk(tree, stories)
    # dedupe by url, else by headline
    seen = set()
    unique = []
    for s in stories:
        key = s["url"] or s["headline"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return status, unique


def _write_markdown(out_path, pipeline, iso, stories):
    lines = [
        "# %s Stories — %s" % ("NYT" if pipeline == "nyt" else "WSJ", iso),
        "<!-- SOURCE: curl_cffi index discovery "
        "(headline + summary only; bodies not fetched) -->",
        "",
        "## %s" % ("Today's Paper" if pipeline == "nyt" else "Homepage"),
    ]
    for i, s in enumerate(stories, 1):
        lines.append("### %d. %s" % (i, s["headline"]))
        if s["section"]:
            lines.append("- Section: %s" % s["section"])
        if s["url"]:
            lines.append("- URL: %s" % s["url"])
        if s["summary"]:
            lines.append("- Summary: %s" % s["summary"])
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="curl_cffi story discovery (headline + summary only)")
    ap.add_argument("--pipeline", required=True, choices=["nyt", "wsj"])
    ap.add_argument("--date", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not HAVE_CURL_CFFI:
        print("FALLBACK_REQUIRED: curl_cffi not installed")
        run_log({"pipeline": args.pipeline, "date": args.date or today_iso(),
                 "stage": "research", "ok": False,
                 "detail": "curl_cffi not installed"})
        return 4

    iso = args.date or today_iso()
    pipeline = args.pipeline
    try:
        status, stories = discover(pipeline)
    except Exception as exc:  # noqa: BLE001 - any failure => fallback
        print("FALLBACK_REQUIRED: discovery error: %s" % exc)
        run_log({"pipeline": pipeline, "date": iso, "stage": "research",
                 "ok": False, "detail": str(exc)})
        return 4
    if status != 200 or not stories:
        print("FALLBACK_REQUIRED: http=%d stories=%d" % (status, len(stories)))
        run_log({"pipeline": pipeline, "date": iso, "stage": "research",
                 "ok": False, "detail": {"http": status, "stories": len(stories)}})
        return 4

    stories = stories[:args.limit]
    out = args.out or os.path.join(
        tempfile.gettempdir(), "%s_stories_%s.md" % (pipeline, iso))
    _write_markdown(out, pipeline, iso, stories)

    summary = {"pipeline": pipeline, "source": "curl_cffi", "http": status,
               "stories": len(stories), "out": out, "level": "index"}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print("%d %s stories (headline + summary only) -> %s"
              % (len(stories), pipeline.upper(), out))
        print("NOTE: discovery source only — NOT a replacement for article bodies.")
    sys.stderr.write(
        "NOTE: index-level discovery — headline + summary only; "
        "bodies were not fetched (NYT article URLs 403; WSJ gives ~100-word lede).\n")
    run_log({"pipeline": pipeline, "date": iso, "stage": "research",
             "ok": True, "detail": summary})
    return 0


if __name__ == "__main__":
    sys.exit(main())
