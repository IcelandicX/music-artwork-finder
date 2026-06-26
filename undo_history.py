#!/usr/bin/env python3
"""Undo journal helpers for Music Fix metadata changes."""

from __future__ import annotations

import json
import shutil
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


def _new_snapshot_path() -> Path:
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return UNDO_DIR / f"{timestamp}.json"


def save_undo_snapshot(changes: list[Any], action: str, group_id: str | None = None) -> Path | None:
    """Persist previous metadata for changes about to be applied."""
    if not changes:
        return None

    path = _new_snapshot_path()
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "kind": "metadata",
        "tracks": [_track_snapshot_payload(change.before) for change in changes],
    }
    if group_id:
        payload["group_id"] = group_id
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_artwork_undo_snapshot(
    tracks: list[dict[str, Any]],
    artwork_dir: Path,
    action: str = "artwork update",
    group_id: str | None = None,
) -> Path | None:
    if not tracks:
        shutil.rmtree(artwork_dir, ignore_errors=True)
        return None

    path = _new_snapshot_path()
    snapshot_dir = UNDO_DIR / path.stem
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    shutil.move(str(artwork_dir), str(snapshot_dir))

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "kind": "artwork",
        "artwork_dir": str(snapshot_dir),
        "tracks": tracks,
    }
    if group_id:
        payload["group_id"] = group_id
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def undo_snapshots_for_group(group_id: str) -> list[Path]:
    snapshots: list[Path] = []
    for path in UNDO_DIR.glob("*.json"):
        if path.name.endswith(".undone.json"):
            continue
        try:
            payload = load_undo_snapshot(path)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("group_id") == group_id:
            snapshots.append(path)
    return sorted(snapshots)


def latest_undo_snapshot() -> Path | None:
    snapshots = sorted(
        path for path in UNDO_DIR.glob("*.json") if not path.name.endswith(".undone.json")
    )
    return snapshots[-1] if snapshots else None


def load_undo_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def mark_undo_snapshot_used(path: Path) -> Path:
    destination = path.with_suffix(".undone.json")
    path.rename(destination)
    return destination
