#!/usr/bin/env python3
"""Morning Briefing pipeline state management.

Reads/writes a JSON state file that tracks the daily progress of the
observer_sync -> cartoon -> publish phases.
"""

import json
import os
from datetime import datetime

DEFAULT_PHASES = ["observer_sync", "cartoon", "publish"]
DEFAULT_CONFIG = {"max_retries": 2}


def _state_path(path):
    """Resolve a project root or file path to the state file path."""
    if os.path.isdir(path):
        return os.path.join(path, "mb_state.json")
    return path


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _fresh_state():
    return {
        "date": _today(),
        "phases": {
            phase: {"status": "pending", "retries": 0, "error": None}
            for phase in DEFAULT_PHASES
        },
        "config": DEFAULT_CONFIG.copy(),
    }


def load_state(path):
    """Load state from *path* (project root or direct file path).

    If the file does not exist or is malformed, a fresh state for today is
    returned and NOT automatically written to disk.
    """
    state_file = _state_path(path)
    if not os.path.exists(state_file):
        return _fresh_state()

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _fresh_state()

    if not isinstance(state, dict):
        return _fresh_state()

    # Ensure required structure.
    if "date" not in state:
        state["date"] = _today()
    if "phases" not in state or not isinstance(state["phases"], dict):
        state["phases"] = {}

    for phase in DEFAULT_PHASES:
        if phase not in state["phases"]:
            state["phases"][phase] = {
                "status": "pending",
                "retries": 0,
                "error": None,
            }
        else:
            entry = state["phases"][phase]
            if not isinstance(entry, dict):
                entry = {"status": str(entry), "retries": 0, "error": None}
                state["phases"][phase] = entry
            entry.setdefault("status", "pending")
            entry.setdefault("retries", 0)
            entry.setdefault("error", None)

    if "config" not in state or not isinstance(state["config"], dict):
        state["config"] = DEFAULT_CONFIG.copy()
    else:
        state["config"].setdefault("max_retries", DEFAULT_CONFIG["max_retries"])

    return state


def save_state(state, path):
    """Persist *state* to *path* (project root or direct file path)."""
    state_file = _state_path(path)
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_next_phase(state):
    """Return the first phase still marked pending, or None if all done."""
    for phase in DEFAULT_PHASES:
        if state.get("phases", {}).get(phase, {}).get("status") == "pending":
            return phase
    return None


def update_phase(state, phase_name, status, error=None):
    """Update *phase_name* to *status* and increment retries on failure.

    Returns the updated state dict (same object, mutated in place).
    """
    if phase_name not in state.get("phases", {}):
        state["phases"][phase_name] = {
            "status": "pending",
            "retries": 0,
            "error": None,
        }

    entry = state["phases"][phase_name]
    entry["status"] = status
    entry["error"] = error

    if status == "failed":
        entry["retries"] = entry.get("retries", 0) + 1

    return state
