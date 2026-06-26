#!/usr/bin/env python3
"""Undo journal helpers for Music Fix metadata changes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


UNDO_DIR = Path.home() / ".music-artwork-finder" / "undo"


def _track_snapshot_payload(track: Any) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "album_artist": track.album_artist,
        "track_number": track.track_number,
        "disc_number": track.disc_number,
        "year": track.year,
        "genre": track.genre,
    }


def save_undo_snapshot(changes: list[Any], action: str) -> Path | None:
    """Persist previous metadata for changes about to be applied."""
    if not changes:
        return None

    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = UNDO_DIR / f"{timestamp}.json"
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "tracks": [_track_snapshot_payload(change.before) for change in changes],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def latest_undo_snapshot() -> Path | None:
    snapshots = sorted(UNDO_DIR.glob("*.json"))
    return snapshots[-1] if snapshots else None


def load_undo_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def mark_undo_snapshot_used(path: Path) -> Path:
    destination = path.with_suffix(".undone.json")
    path.rename(destination)
    return destination
