#!/usr/bin/env python3
"""User preferences for Music Fix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".music-artwork-finder"
PREFS_PATH = CONFIG_DIR / "preferences.json"

DEFAULT_PREFS: dict[str, Any] = {
    "run_mode": "auto",
    "confirm_below": 0.60,
    "selection_only": False,
    "cache_ttl_hours": 24,
}

RUN_MODES = {"auto", "preview", "dry-run"}


def load_preferences() -> dict[str, Any]:
    if not PREFS_PATH.exists():
        return DEFAULT_PREFS.copy()
    try:
        loaded = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PREFS.copy()
    prefs = DEFAULT_PREFS.copy()
    prefs.update({key: value for key, value in loaded.items() if key in DEFAULT_PREFS})
    if prefs["run_mode"] not in RUN_MODES:
        prefs["run_mode"] = DEFAULT_PREFS["run_mode"]
    return prefs


def save_preferences(prefs: dict[str, Any]) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    sanitized = DEFAULT_PREFS.copy()
    sanitized.update({key: value for key, value in prefs.items() if key in DEFAULT_PREFS})
    if sanitized["run_mode"] not in RUN_MODES:
        raise ValueError(f"run_mode must be one of: {', '.join(sorted(RUN_MODES))}")
    sanitized["confirm_below"] = float(sanitized["confirm_below"])
    sanitized["selection_only"] = bool(sanitized["selection_only"])
    sanitized["cache_ttl_hours"] = int(sanitized["cache_ttl_hours"])
    PREFS_PATH.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
    return PREFS_PATH


def reset_preferences() -> Path:
    return save_preferences(DEFAULT_PREFS.copy())


def format_preferences(prefs: dict[str, Any] | None = None) -> str:
    prefs = prefs or load_preferences()
    return "\n".join(
        [
            f"run_mode: {prefs['run_mode']}",
            f"confirm_below: {prefs['confirm_below']}",
            f"selection_only: {prefs['selection_only']}",
            f"cache_ttl_hours: {prefs['cache_ttl_hours']}",
            f"path: {PREFS_PATH}",
        ]
    )
