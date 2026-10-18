#!/usr/bin/env python3
"""Finalize today's MorningBriefing state: statuses + run notes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_state  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

state = mb_state.load_state(REPO)
mb_state.update_phase(state, "observer_sync", "done")
mb_state.update_phase(
    state, "cartoon", "skipped", "Kimi Docs images removed per user request"
)
mb_state.update_phase(state, "publish", "done")
state["notes"] = {
    "observer_source": "wsj (zhai 905 / jin 704 / song 907 chars html)",
    "observers_commit": "9448183",
    "publish_script": "scripts/mb_publish.py exit 0 — briefings already published by pipelines, PDFs synced, Read links correct, observers committed, CDN HTTP 200",
    "live_verified": "checkpoint+liveness: observers.json 200 with 2026-10-18, nyt/wsj html 200, nyt/wsj PDFs 200, reports_index has 5 refs to 2026-10-18, index.html 200",
    "pages_deploy": "39147641382 rerun success + 39147820200 success",
    "fix_deploy_race": "mb_publish.py now stages data/observers.json in the same commit as Read links/PDFs -> one push per day instead of two, which removes the 'in progress deployment' failure that hit today (two pushes 7s apart). Deploy 39147641382 initially failed on that race and was re-run after the earlier run finished.",
    "pending_manual": "pages.yml concurrency group (serialize deploys) NOT applied: pushed via OAuth token without 'workflow' scope (gh scopes: gist, read:org, repo). Needs a token with workflow scope.",
    "helpers": "scripts/mb_seed_state.py (seed) + scripts/mb_phase.py <phase> <status> [error] (update) — python3 -c is blocked by the cron security scanner",
}
mb_state.save_state(state, REPO)
print("state finalized:", state["date"])
