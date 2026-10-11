#!/usr/bin/env python3
"""Audio retention: keep only the newest N briefings per pipeline.

Deletes older mp3s under briefings/audio and strips the player from their pages,
so a published page never offers a control pointing at a file that is gone.
It also prunes the rolling 'briefing-audio' GitHub release: any mp3 asset
whose embedded date is outside the keep window is deleted, so the release
mirrors the local keep policy (audio is hosted as a release asset, not in git).

Note: this keeps the WORKING TREE and the release small. It does not reclaim
git history - each mp3 committed before the move to release assets stays in
the object store forever.

Usage:
    briefing_audio_prune.py [--keep-days N] [--dry-run] [--json]

Exit codes: 0 ok, 1 error, 3 environment
"""
import argparse
import json
import os
import re
import subprocess
import sys

try:
    from .briefing_lib import resolve_repo
except ImportError:  # run as a plain script
    from briefing_lib import resolve_repo

try:
    from .briefing_build import _strip_audio_bars
except ImportError:
    try:
        from briefing_build import _strip_audio_bars
    except ImportError:  # keep working standalone if the builder moves
        _strip_audio_bars = None

AUDIO_RX = re.compile(r"^(nyt|wsj)_briefing_(\d{4}-\d{2}-\d{2})\.mp3$")
BAR_RX = re.compile(r'<div class="audio-bar"[^>]*>', re.S)
AUDIO_RELEASE_TAG = "briefing-audio"


def _depth_strip(html):
    """Fallback bar stripper (the bar wraps a nested div, so count depth)."""
    out, pos = [], 0
    while True:
        m = BAR_RX.search(html, pos)
        if m is None:
            out.append(html[pos:])
            return "".join(out)
        out.append(html[pos:m.start()])
        depth, end = 1, None
        for tag in re.finditer(r"<div\b[^>]*>|</div>", html[m.end():], re.S):
            depth += -1 if tag.group(0).startswith("</") else 1
            if depth == 0:
                end = m.end() + tag.end()
                break
        end = end if end is not None else m.end()
        if html[end:end + 1] == "\n":
            end += 1
        pos = end


def page_rel(pipeline, iso):
    return ("nyt_%s.html" % iso) if pipeline == "nyt" else ("wsj_briefing_%s.html" % iso)


def _prune_release_assets(kept_pairs, dry_run):
    """Best-effort pruning of the rolling 'briefing-audio' GitHub release:
    every mp3 asset whose embedded (pipeline, date) is outside the local keep
    window is deleted. Failures are reported on stderr and never fail the
    prune run. Returns the list of deleted — or, in dry-run, would-delete —
    asset names."""
    deleted = []
    try:
        r = subprocess.run(["gh", "release", "view", AUDIO_RELEASE_TAG,
                            "--json", "assets"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError("gh release view failed: %s"
                               % (r.stderr.strip() or "unknown error"))
        assets = json.loads(r.stdout or "{}").get("assets", [])
    except Exception as exc:  # noqa: BLE001 - release pruning is best effort
        sys.stderr.write("AUDIO_WARN: release asset listing failed: %s\n" % exc)
        return deleted
    for asset in assets:
        name = asset.get("name", "")
        m = AUDIO_RX.match(name)
        if not m or (m.group(1), m.group(2)) in kept_pairs:
            continue
        if dry_run:
            deleted.append(name)
            continue
        try:
            r = subprocess.run(["gh", "release", "delete-asset",
                                AUDIO_RELEASE_TAG, name, "--yes"],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "unknown error")
            deleted.append(name)
        except Exception as exc:  # noqa: BLE001 - best effort per asset
            sys.stderr.write("AUDIO_WARN: release asset %s not deleted: %s\n"
                             % (name, exc))
    return deleted


def prune(repo, keep_days, dry_run=False):
    adir = os.path.join(repo, "briefings", "audio")
    if not os.path.isdir(adir):
        return {"ok": False, "error": "NO_AUDIO_DIR: %s" % adir}
    by_pipe = {}
    for name in sorted(os.listdir(adir)):
        m = AUDIO_RX.match(name)
        if m:
            by_pipe.setdefault(m.group(1), []).append((m.group(2), name))
    pruned, kept = [], []
    kept_pairs = set()
    for pipeline in sorted(by_pipe):
        entries = sorted(by_pipe[pipeline], reverse=True)      # newest first
        keep = entries[:keep_days]
        drop = entries[keep_days:]
        kept.extend([n for _, n in keep])
        kept_pairs.update((pipeline, iso) for iso, _ in keep)
        for iso, name in drop:
            page = page_rel(pipeline, iso)
            page_path = os.path.join(repo, "briefings", page)
            bars_removed = 0
            if os.path.exists(page_path):
                with open(page_path, encoding="utf-8") as f:
                    html = f.read()
                stripped = (_strip_audio_bars(html) if _strip_audio_bars
                            else _depth_strip(html))
                if stripped != html:
                    bars_removed = len(BAR_RX.findall(html)) - len(BAR_RX.findall(stripped))
                    if not dry_run:
                        with open(page_path, "w", encoding="utf-8") as f:
                            f.write(stripped)
            if not dry_run:
                os.remove(os.path.join(adir, name))
            pruned.append({"file": "briefings/audio/%s" % name,
                           "page": page if bars_removed else None,
                           "page_changed": bool(bars_removed)})
    deleted_assets = _prune_release_assets(kept_pairs, dry_run)
    return {"ok": True, "kept": sorted(kept), "pruned": pruned,
            "kept_count": len(kept), "pruned_count": len(pruned),
            "deleted_assets": deleted_assets,
            "dry_run": dry_run, "repo": repo}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Keep only the newest N audio files per pipeline")
    ap.add_argument("--keep-days", type=int, default=3,
                    help="how many of the newest briefings keep their audio (default 3)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.keep_days < 1:
        sys.stderr.write("BAD_ARG: --keep-days must be >= 1\n")
        return 3
    try:
        res = prune(resolve_repo(), args.keep_days, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("PRUNE_FAILED: %s\n" % exc)
        return 1
    if not res.get("ok"):
        sys.stderr.write("%s\n" % res.get("error"))
        return 3
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        verb = "would prune" if args.dry_run else "pruned"
        print("repo: %s" % res["repo"])
        print("keeping %d file(s): %s" % (res["kept_count"], ", ".join(res["kept"]) or "-"))
        print("%s %d file(s):" % (verb, res["pruned_count"]))
        for p in res["pruned"]:
            extra = "  (+player removed from %s)" % p["page"] if p["page_changed"] else ""
            print("  %s%s" % (p["file"], extra))
        if res["deleted_assets"]:
            verb = "would delete" if res["dry_run"] else "deleted"
            print("%s %d release asset(s): %s"
                  % (verb, len(res["deleted_assets"]), ", ".join(res["deleted_assets"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
