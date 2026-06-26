#!/usr/bin/env python3
"""Small JSON cache for slow online search results."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from preferences import load_preferences


CACHE_DIR = Path.home() / ".music-artwork-finder" / "cache"
DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _cache_path(namespace: str, key: str) -> Path:
    safe_key = "".join(ch if ch.isalnum() else "_" for ch in key.casefold())[:180]
    return CACHE_DIR / namespace / f"{safe_key}.json"


def load_cache(namespace: str, key: str, ttl_seconds: int | None = None) -> Any | None:
    if ttl_seconds is None:
        ttl_seconds = int(load_preferences().get("cache_ttl_hours", 24)) * 60 * 60
    path = _cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(payload.get("created_at", 0)) > ttl_seconds:
        return None
    return payload.get("value")


def save_cache(namespace: str, key: str, value: Any) -> None:
    path = _cache_path(namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": time.time(),
        "value": value,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def clear_cache(namespace: str | None = None) -> int:
    """Remove cached search files and return the number of files deleted."""
    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if not target.exists():
        return 0

    deleted = sum(1 for path in target.rglob("*.json") if path.is_file())
    shutil.rmtree(target)
    return deleted


def cache_file_count() -> int:
    if not CACHE_DIR.exists():
        return 0
    return sum(1 for path in CACHE_DIR.rglob("*.json") if path.is_file())
