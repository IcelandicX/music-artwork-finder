#!/usr/bin/env python3
"""Small JSON cache for slow online search results."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


CACHE_DIR = Path.home() / ".music-artwork-finder" / "cache"
DEFAULT_TTL_SECONDS = 24 * 60 * 60


def _cache_path(namespace: str, key: str) -> Path:
    safe_key = "".join(ch if ch.isalnum() else "_" for ch in key.casefold())[:180]
    return CACHE_DIR / namespace / f"{safe_key}.json"


def load_cache(namespace: str, key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Any | None:
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
