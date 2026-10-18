#!/usr/bin/env python3
"""Seed mb_state.json for today's MorningBriefing run."""
import datetime
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "mb_state.json")
today = datetime.date.today().isoformat()

state = {
    "date": today,
    "phases": {
        "observer_sync": {"status": "pending", "retries": 0, "error": None},
        "cartoon": {
            "status": "skipped",
            "retries": 0,
            "error": "Kimi Docs images removed per user request",
        },
        "publish": {"status": "pending", "retries": 0, "error": None},
    },
    "config": {"max_retries": 2},
}

with open(STATE, "w", encoding="utf-8") as fh:
    json.dump(state, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(json.dumps(state, ensure_ascii=False))
