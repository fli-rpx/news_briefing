#!/usr/bin/env python3
"""End-to-end briefing publish orchestration.

Usage:
    briefing_publish.py --pipeline {nyt,wsj} [--date ISO] [--html PATH] [--pdf PATH]
        [--make-pdf] [--hero TEXT] [--desc TEXT] [--dry-run] [--no-push]
        [--skip-state] [--json]

Exit codes: 0 ok, 1 verify/pdf failure, 3 environment, 5 git sync conflict,
6 CDN verification failed (commit NOT rolled back), 7 pipeline-state update failed.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    from .briefing_lib import (
        HERMES, PIPELINE_STATE, SITE_BASE, STATE_LOG, data_index_apply,
        gallery_transform, gallery_upsert, git_commit_push, cdn_verify, index_upsert,
        paths, require_fresh, resolve_repo, root_index_apply, run_log,
        split_sentences_safe, today_iso, verify_html,
    )
    from .briefing_build import BuildError, build_html
except ImportError:  # run as plain scripts
    from briefing_lib import (
        HERMES, PIPELINE_STATE, SITE_BASE, STATE_LOG, data_index_apply,
        gallery_transform, gallery_upsert, git_commit_push, cdn_verify, index_upsert,
        paths, require_fresh, resolve_repo, root_index_apply, run_log,
        split_sentences_safe, today_iso, verify_html,
    )
    from briefing_build import BuildError, build_html

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PDF_MIN_BYTES = 50 * 1024
PDF_POLL_SECONDS = 30


def _clip(text, n=80):
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "…"


def derive_desc(pipeline, iso):
    """Deterministic gallery-card description from the V3 source.

    Override with --desc for curated text. NYT: tl;dr sentences. WSJ: first
    exec-summary sentence + first bold headlines.
    """
    v3_path = os.path.join(HERMES, "%s_briefing_v3.md" % pipeline)
    if not os.path.exists(v3_path):
        return "%s briefing %s" % (pipeline.upper(), iso)
    with open(v3_path, encoding="utf-8") as f:
        v3 = f.read()
    if pipeline == "nyt":
        m = re.search(r"^\*\*tl;dr:\*\*\s*(.+?)(?=\n\s*---|\Z)", v3, flags=re.M | re.S)
        if not m:
            return "NYT briefing %s" % iso
        text = re.sub(r"\s+", " ", m.group(1)).strip()
        parts = []
        for s in split_sentences_safe(text)[:5]:
            s = s.replace("**", "").strip().rstrip(".").strip()
            if s:
                parts.append(s[0].upper() + s[1:])
        return " · ".join(_clip(p) for p in parts) or "NYT briefing %s" % iso
    # wsj
    m = re.search(r"^## Executive Summary\s*\n(.+?)(?=\n\s*\n|\Z)", v3,
                  flags=re.M | re.S)
    if not m:
        return "WSJ briefing %s" % iso
    para = re.sub(r"\s+", " ", m.group(1)).strip()
    heads = re.findall(r"\*\*\"([^\"]+)\"\*\*", para)[:3]
    sents = split_sentences_safe(re.sub(r"\*\*.+?\*\*", lambda x: x.group(0).replace("**", ""), para))
    first = (sents[0].strip().rstrip(".") if sents else "")
    parts = ([first[0].upper() + first[1:]] if first else []) + heads
    parts = [p for p in parts if p]
    return " · ".join(_clip(p) for p in parts[:4]) or "WSJ briefing %s" % iso


def make_pdf(repo_html_path, repo_pdf_path):
    """Render the repo HTML to PDF via headless Chrome. sys.exit(1) on failure."""
    out_pdf = os.path.abspath(repo_pdf_path)
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    cmd = [
        CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        "--print-to-pdf=%s" % out_pdf,
        "--virtual-time-budget=8000",
        "file://%s" % os.path.abspath(repo_html_path),
    ]
    try:
        # Chrome prints noisy stderr; ignore it as long as the PDF appears.
        subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("PDF_FAILED: chrome render error: %s\n" % exc)
        sys.exit(1)
    deadline = time.time() + PDF_POLL_SECONDS
    while time.time() < deadline:
        if os.path.exists(out_pdf) and os.path.getsize(out_pdf) > PDF_MIN_BYTES:
            return out_pdf
        time.sleep(0.5)
    sys.stderr.write(
        "PDF_FAILED: %s did not appear within %ds or is <= %d bytes\n"
        % (out_pdf, PDF_POLL_SECONDS, PDF_MIN_BYTES)
    )
    sys.exit(1)


def _cdn_expect(repo, pipeline, iso):
    """CDN urls -> what the served bytes must match locally.

    The gallery is fingerprinted by its own file plus the day's href needle, so a
    gallery that is live but missing today's card still fails verification.
    """
    p = paths(pipeline, iso)
    html_local = os.path.join(repo, p["html"])
    return {
        SITE_BASE + "briefings/gallery.html": {
            "local": os.path.join(repo, "briefings/gallery.html"),
            "needle": os.path.basename(p["html"]),
        },
        SITE_BASE + p["html"]: {
            "local": html_local,
            "needle": "<!-- PHASE COMPLETE -->",
        },
        SITE_BASE + p["pdf"]: {
            "local": os.path.join(repo, p["pdf"]),
        },
    }
def main(argv=None):
    ap = argparse.ArgumentParser(description="Publish one briefing end to end")
    ap.add_argument("--pipeline", required=True, choices=["nyt", "wsj"])
    ap.add_argument("--date", default=None)
    ap.add_argument("--html", default=None, help="pre-built HTML (default: build now)")
    ap.add_argument("--pdf", default=None, help="pre-built PDF to copy in")
    ap.add_argument("--make-pdf", action="store_true",
                    help="render PDF from the repo HTML via headless Chrome")
    ap.add_argument("--hero", default=None,
                    help="hero line override (passed through to briefing_build)")
    ap.add_argument("--desc", default=None,
                    help="gallery card description override (also passed to briefing_build)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--skip-state", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    iso = args.date or today_iso()
    pipeline = args.pipeline
    p = paths(pipeline, iso)
    repo = resolve_repo()
    log_ctx = {"pipeline": pipeline, "date": iso}

    # -- 1. freshness gate -------------------------------------------------
    info = require_fresh(repo, fetch=not args.dry_run)
    run_log(dict(log_ctx, stage="fresh", ok=True,
                 detail={"head": info["head"], "behind": info["behind"]}))

    # -- 2. obtain + verify HTML -------------------------------------------
    tmp_html = None
    hero_resolved = args.hero
    if args.html:
        html_path = args.html
        if not os.path.exists(html_path):
            sys.stderr.write("HTML_MISSING: %s\n" % html_path)
            run_log(dict(log_ctx, stage="build", ok=False, detail="missing --html"))
            return 1
    else:
        fd, tmp_html = tempfile.mkstemp(suffix=".html", prefix="briefing_")
        os.close(fd)
        try:
            result = build_html(pipeline, iso, out=tmp_html,
                                hero=args.hero, desc=args.desc)
            hero_resolved = result.get("hero")
        except SystemExit:
            raise
        except BuildError as exc:
            sys.stderr.write("BUILD_FAILED: %s\n" % exc)
            run_log(dict(log_ctx, stage="build", ok=False, detail=str(exc)))
            return 1
        html_path = tmp_html
    vok, verrs = verify_html(html_path, pipeline, iso, text_only=True)
    if not vok:
        for e in verrs:
            sys.stderr.write("VERIFY: %s\n" % e)
        run_log(dict(log_ctx, stage="verify", ok=False, detail=verrs))
        return 1
    run_log(dict(log_ctx, stage="verify", ok=True,
                 detail={"bytes": os.path.getsize(html_path)}))

    repo_html = os.path.join(repo, p["html"])
    repo_pdf = os.path.join(repo, p["pdf"])
    desc = args.desc if args.desc is not None else derive_desc(pipeline, iso)
    files = [p["html"], p["pdf"], "briefings/gallery.html",
             "reports_index.json", "data/reports_index.json"]
    commit_msg = "%s briefing %s — publish" % (pipeline.upper(), iso)

    # -- dry run: steps 1-5 in memory only ---------------------------------
    if args.dry_run:
        planned = []
        planned.append("COPY %s -> %s" % (html_path, repo_html))
        if args.make_pdf:
            planned.append("CHROME %s --print-to-pdf=%s" % (repo_html, repo_pdf))
        elif args.pdf:
            planned.append("COPY %s -> %s" % (args.pdf, repo_pdf))
        else:
            local_pdf = os.path.join(HERMES, os.path.basename(p["pdf"]))
            planned.append("COPY %s -> %s (if present)" % (local_pdf, repo_pdf))
        with open(os.path.join(repo, "briefings", "gallery.html"), encoding="utf-8") as f:
            gal = f.read()
        new_gal = gallery_transform(gal, pipeline, iso, desc, badges=True)
        n_badges = new_gal.count('class="badge badge-new"')
        with open(os.path.join(repo, "reports_index.json"), encoding="utf-8") as f:
            root_idx = json.load(f)
        with open(os.path.join(repo, "data", "reports_index.json"), encoding="utf-8") as f:
            data_idx = json.load(f)
        root_idx = root_index_apply(root_idx, pipeline, iso)
        data_idx = data_index_apply(data_idx, pipeline, iso)
        planned.append("GALLERY upsert card for %s (%d badge(s) today)"
                       % (iso, n_badges))
        planned.append("INDEX upsert %s %s entry in both reports_index.json files"
                       % (iso, pipeline))
        planned.append("GIT add -- %s" % " ".join(files))
        planned.append("GIT commit -m %r" % commit_msg)
        planned.append("GIT push origin main" + (" (skipped: --no-push)" if args.no_push else ""))
        planned.append("CDN verify: " + ", ".join(_cdn_expect(repo, pipeline, iso)))
        if not args.skip_state:
            planned.append("STATE pipeline_state.py update --phase publish --status done")
        summary = {
            "dry_run": True, "repo": repo, "date": iso, "pipeline": pipeline,
            "head_sha": info["head"], "hero": hero_resolved, "desc": desc,
            "verify": {"ok": True, "errors": []},
            "planned": planned,
        }
        run_log(dict(log_ctx, stage="dry_run", ok=True,
                     detail={"planned": len(planned)}))
        _emit(summary, args.json)
        return 0

    # -- 3/4. place HTML + PDF in the repo ---------------------------------
    os.makedirs(os.path.dirname(repo_html), exist_ok=True)
    shutil.copy2(html_path, repo_html)
    run_log(dict(log_ctx, stage="copy_html", ok=True, detail=p["html"]))
    if args.make_pdf:
        make_pdf(repo_html, repo_pdf)
    else:
        src = args.pdf or os.path.join(HERMES, os.path.basename(p["pdf"]))
        if not os.path.exists(src):
            sys.stderr.write("PDF_MISSING: %s (use --make-pdf or --pdf)\n" % src)
            run_log(dict(log_ctx, stage="pdf", ok=False, detail="missing pdf"))
            return 1
        os.makedirs(os.path.dirname(repo_pdf), exist_ok=True)
        shutil.copy2(src, repo_pdf)
    pdf_bytes = os.path.getsize(repo_pdf)
    run_log(dict(log_ctx, stage="pdf", ok=True, detail={"bytes": pdf_bytes}))

    # -- 5. gallery + indexes ----------------------------------------------
    gallery_upsert(repo, pipeline, iso, desc, badges=True)
    index_upsert(repo, pipeline, iso)
    run_log(dict(log_ctx, stage="gallery_index", ok=True, detail=desc))

    # -- 6. commit + push ----------------------------------------------------
    res = git_commit_push(repo, files, commit_msg, push=not args.no_push)
    run_log(dict(log_ctx, stage="commit", ok=True, detail=res))

    # -- 7. CDN verify -------------------------------------------------------
    cdn = cdn_verify(list(_cdn_expect(repo, pipeline, iso)),
                     expect=_cdn_expect(repo, pipeline, iso))
    cdn_ok = all(r["ok"] for r in cdn.values())
    run_log(dict(log_ctx, stage="cdn", ok=cdn_ok, detail=cdn))
    if not cdn_ok:
        summary = _summary(repo, iso, pipeline, info, res, files, html_path,
                           repo_pdf, {"ok": True, "errors": []}, cdn,
                           hero=hero_resolved, desc=desc)
        _emit(summary, args.json)
        return 6

    # -- 8. pipeline state ----------------------------------------------------
    if not args.skip_state:
        r = subprocess.run(
            ["python3", PIPELINE_STATE, "--pipeline", pipeline,
             "--action", "update", "--phase", "publish", "--status", "done"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            sys.stderr.write("STATE_UPDATE_FAILED: %s\n" % r.stderr.strip())
            run_log(dict(log_ctx, stage="state", ok=False,
                         detail=r.stderr.strip()))
            summary = _summary(repo, iso, pipeline, info, res, files, html_path,
                               repo_pdf, {"ok": True, "errors": []}, cdn,
                               hero=hero_resolved, desc=desc)
            _emit(summary, args.json)
            return 7
        run_log(dict(log_ctx, stage="state", ok=True, detail="publish done"))

    # -- 9. summary ------------------------------------------------------------
    summary = _summary(repo, iso, pipeline, info, res, files, html_path,
                       repo_pdf, {"ok": True, "errors": []}, cdn,
                       hero=hero_resolved, desc=desc)
    _emit(summary, args.json)
    return 0


def _summary(repo, iso, pipeline, info, res, files, html_path, repo_pdf, verify,
             cdn, hero=None, desc=None):
    return {
        "dry_run": False,
        "repo": repo,
        "date": iso,
        "pipeline": pipeline,
        "head_sha": info["head"],
        "hero": hero,
        "desc": desc,
        "commit_sha": res.get("commit"),
        "pushed": res.get("pushed", False),
        "files": files,
        "bytes": {"html": os.path.getsize(html_path) if os.path.exists(html_path) else 0,
                  "pdf": os.path.getsize(repo_pdf) if os.path.exists(repo_pdf) else 0},
        "verify": verify,
        "cdn": cdn,
        "run_log": STATE_LOG,
    }


def _emit(summary, as_json):
    if as_json:
        print(json.dumps(summary, ensure_ascii=False))
        return
    print("repo: %s" % summary["repo"])
    print("pipeline/date: %s %s" % (summary["pipeline"], summary["date"]))
    print("head: %s" % summary.get("head_sha"))
    if summary.get("dry_run"):
        print("DRY RUN — planned actions:")
        for a in summary["planned"]:
            print("  %s" % a)
        return
    print("commit: %s (pushed=%s)" % (summary.get("commit_sha"), summary.get("pushed")))
    print("hero: %s" % summary.get("hero"))
    print("desc: %s" % summary.get("desc"))
    print("files: %s" % ", ".join(summary["files"]))
    print("bytes: %s" % summary["bytes"])
    print("verify: %s" % summary["verify"])
    for url, r in summary["cdn"].items():
        print("cdn %s: ok=%s status=%s attempts=%s" % (url, r["ok"], r["status"], r["attempts"]))
    print("run_log: %s" % summary["run_log"])


if __name__ == "__main__":
    sys.exit(main())
