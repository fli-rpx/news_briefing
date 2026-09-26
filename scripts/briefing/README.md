# Briefing tooling

Consolidated, deterministic tooling for the MorningBriefing publish pipelines.
Replaces the ~10 scattered scripts at the repo root of `scripts/`. Python 3.9+,
stdlib only (`curl_cffi` is optional and import-guarded in
`briefing_research.py`). Everything is run by unattended cron jobs, so failures
are loud and exit codes are a contract.

## Repo / site facts (canonical)

- Repo: `/Users/fudongli/Projects/MorningBriefing` (override with
  `BRIEFING_REPO`), remote `git@github.com:fli-rpx/news_briefing.git`, branch
  `main`. `/Users/fudongli/Projects/news_briefing` is a **legacy** clone — the
  tooling only warns about it, never touches it.
- Site: GitHub Pages `https://fli-rpx.github.io/news_briefing/` (branch
  `gh-pages` via workflow). `briefings/<name>` is served at
  `https://fli-rpx.github.io/news_briefing/briefings/<name>`.
- Artifacts (inside `briefings/`):
  | pipeline | HTML | PDF |
  |---|---|---|
  | nyt | `nyt_{date}.html` | `nyt_briefing_{date}.pdf` |
  | wsj | `wsj_briefing_{date}.html` | `reports/wsj_briefing_{date}.pdf` |
- V3 markdown sources: `~/.hermes/nyt_briefing_v3.md`,
  `~/.hermes/wsj_briefing_v3.md`. WSJ observer commentary is NOT in the V3 —
  it is read from `~/.hermes/wsj_observer{,2,3}.md`.
- Run log (all stages of every tool append here):
  `~/.hermes/state/briefing_runs.jsonl` (one JSON object per line with `ts`,
  `pipeline`, `date`, `stage`, `ok`, `detail`).

## Modules

### `briefing_lib.py` — shared helpers

`resolve_repo`, `assert_repo_fresh` / `require_fresh` (stale repo → exit 3 with
`STALE_REPO: <repo> is N commits behind origin/main — refusing to publish`),
`date_full` / `date_card` / `date_title`, `paths`, `newest_template`,
`strip_footer`, `md_inline`, `md_table_to_html`, `split_sentences_safe`,
`verify_html`, `gallery_upsert`, `gallery_transform`, `index_upsert`,
`root_index_apply`, `data_index_apply`, `git_commit_push`, `cdn_verify`,
`run_log`. No side effects at import.

### `briefing_build.py` — V3 markdown → briefing HTML

```
python3 scripts/briefing/briefing_build.py --pipeline {nyt,wsj} [--date ISO] \
    [--out PATH] [--template PATH] [--json]
```

Proven "container-split rebuild": split V3 on `^## `, render the body, splice
into the newest existing page template (`<div class="container">` split, footer
marker `<footer class="footer">`/`<div class="footer">`), fix the `<title>`
(the live NYT bug: stale `August 2` title on a September page), replace
weekday-date literals in head+tail with today's date, replace the footer ISO
date, remove escaped `&lt;!-- PHASE COMPLETE --&gt;` artifacts, then place
exactly one real `<!-- PHASE COMPLETE -->` immediately before `</body>`.
Asserts text-only output (no `<img` / `assets/images` / `url(`) and runs
`verify_html`. Default output is `/tmp/<html name>` — it never writes into the
repo on its own.

### `briefing_publish.py` — end-to-end publish

```
python3 scripts/briefing/briefing_publish.py --pipeline {nyt,wsj} [--date ISO] \
    [--html PATH] [--pdf PATH] [--make-pdf] [--hero TEXT] [--desc TEXT] \
    [--dry-run] [--no-push] [--skip-state] [--json]
```

Steps (each recorded in the run log): freshness gate → build/verify HTML →
PDF (`--make-pdf` renders the repo HTML via headless Chrome,
`/Applications/Google Chrome.app/... --headless --disable-gpu
--no-pdf-header-footer --print-to-pdf=<out> --virtual-time-budget=8000
file://<abs html>`, polls up to 30 s, asserts > 50 KB, Chrome stderr ignored;
otherwise copies `--pdf` or `~/.hermes/<pdf name>`) → copy HTML+PDF into the
repo → `gallery_upsert` + `index_upsert` (badges on) → `git_commit_push` with
an explicit file list (HTML, PDF, `briefings/gallery.html`, both
`reports_index.json` files — **never** `git add -A`/`git add .`; on push
rejection: `git pull --rebase --autostash`, retry once, on conflict abort the
rebase and exit 5 with instructions) → `cdn_verify` of gallery + HTML + PDF
with `?cb=<epoch>` cache-busters (failure → exit 6, commit NOT rolled back) →
unless `--skip-state`, mark the pipeline state published via
`/Users/fudongli/Projects/nytimes_briefing/scripts/pipeline_state.py`.

The gallery description defaults to a deterministic derivation from the V3
(NYT: `**tl;dr:**` sentences; WSJ: exec-summary lead + bold headlines);
pass `--desc` for the curated card text. `--hero` overrides the NYT hero line
at build time (default: derived from the V3 Cluster 1 titles).

`--dry-run` performs steps 1–5 in memory/temp only (no repo writes, no git
mutations, no network — the freshness check uses local refs) and prints the
planned actions. The gallery upsert is idempotent: a re-run for the same
(pipeline, date) rewrites the existing card in place (date, description, both
hrefs) instead of inserting a duplicate.

### `briefing_preflight.py` — readiness gate

```
python3 scripts/briefing/briefing_preflight.py [--pipeline {nyt,wsj,both}] \
    [--date ISO] [--clean] [--json]
```

Checks: repo resolves and is fresh (stale → 3); V3 exists and its mtime is
today (else → 2); WSJ: the three `wsj_observer*.md` exist and are dated today
— NYT: the three `nyt_observer_*.md` sidecars exist (else → 2);
`pipeline_state.py --action can_publish` is true (else → 2). Reports `/tmp`
artifacts from previous days matching `nyt_briefing_*.html`,
`wsj_briefing_*.html`, `kimi_prompt.md`, `wsj_webpage_prompt.md`
(informational); `--clean` removes only files whose date is not today.

Cron wiring: exit 0 = ready; exit 2 = upstream not ready → report `[SILENT]`;
exit 3 = environment error → alert.

### `briefing_research.py` — curl_cffi story discovery

```
python3 scripts/briefing/briefing_research.py --pipeline {nyt,wsj} [--date ISO] \
    [--out PATH] [--limit N] [--json]
```

Optional dependency: if `curl_cffi` is missing, prints
`FALLBACK_REQUIRED: curl_cffi not installed` and exits 4. NYT fetches
`https://www.nytimes.com/section/todayspaper`, extracts
`window.__preloadedData` with a string-aware brace-matching scanner, applies
`re.sub(r':undefined(\s*[,}]', r':null\1', ...)` before `json.loads`. WSJ
fetches `https://www.wsj.com/` and parses the `__NEXT_DATA__` script tag
(`/print-edition` and `/front-page` return 403/404 — do not use them).
Stories = dicts with a `headline` (possibly `{default: ...}`) plus
`summary`/`abstract` and `url`/`webUrl`. Writes a markdown stories file and
prints `{"pipeline", "source": "curl_cffi", "http", "stories", "out",
"level": "index"}`. Exit 4 on non-200 HTTP or zero stories — the caller then
falls back to the existing Tavily/CDP path.

**This is a discovery source only: headline + summary level data. It is NOT a
replacement for article bodies** (NYT article URLs return 403; WSJ returns
only the ~100-word lede).

## Exit codes

| code | meaning |
|---|---|
| 0 | success |
| 1 | build/verify failure, invalid index, missing PDF/HTML input |
| 2 | preflight: upstream not ready (cron reports `[SILENT]`) |
| 3 | environment error: not a git repo, fetch failed, stale repo (`STALE_REPO`), no template |
| 4 | research: `curl_cffi` missing / HTTP != 200 / zero stories → fallback required |
| 5 | publish: git sync conflict — rebase aborted cleanly, tree restored |
| 6 | publish: CDN verification failed (commit is NOT rolled back) |
| 7 | publish: pipeline-state update failed |

## Cron example

```bash
python3 scripts/briefing/briefing_preflight.py --pipeline both --clean --json
python3 scripts/briefing/briefing_publish.py --pipeline nyt --make-pdf --json
python3 scripts/briefing/briefing_publish.py --pipeline wsj --make-pdf --json
```
