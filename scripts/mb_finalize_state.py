#!/usr/bin/env python3
"""Finalize today's MorningBriefing state: statuses + run notes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_state  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _head_commit():
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "-C", REPO, "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return None


def _observer_lens(date_str):
    import json

    path = os.path.join(REPO, "data", "observers.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f).get(date_str, {})
    except Exception:
        return {}
    return {k: len(v) for k, v in entry.items()}


state = mb_state.load_state(REPO)
date_str = state["date"]
mb_state.update_phase(state, "observer_sync", "done")
mb_state.update_phase(
    state, "cartoon", "skipped", "Kimi Docs images removed per user request"
)
mb_state.update_phase(state, "publish", "done")
lens = _observer_lens(date_str)
state["notes"] = {
    "observer_source": "wsj ("
    + " / ".join(f"{k} {v}" for k, v in sorted(lens.items()))
    + " chars html)"
    if lens
    else "none",
    "observers_commit": _head_commit(),
    "publish_script": "scripts/mb_publish.py — see run output for CDN status",
    "helpers": "scripts/mb_seed_state.py (seed) + scripts/mb_phase.py <phase> <status> [error] (update)",
}
mb_state.save_state(state, REPO)
print("state finalized:", state["date"])
