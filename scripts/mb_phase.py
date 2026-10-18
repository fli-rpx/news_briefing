#!/usr/bin/env python3
"""CLI: mark a MorningBriefing phase status in mb_state.json.

Usage:
    python3 scripts/mb_phase.py <phase> <status> [error message]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mb_state  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    phase, status = argv[1], argv[2]
    error = argv[3] if len(argv) > 3 else None
    state = mb_state.load_state(REPO)
    mb_state.update_phase(state, phase, status, error)
    mb_state.save_state(state, REPO)
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
