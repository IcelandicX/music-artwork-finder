#!/usr/bin/env python3
"""Undo the last Music Fix metadata change."""

from __future__ import annotations

import argparse
import sys

from find_artwork import music_app_name, notify
from find_tags import TagChange, TrackSnapshot, TrackTags, apply_tag_changes
from undo_history import latest_undo_snapshot, load_undo_snapshot, mark_undo_snapshot_used


def track_from_payload(payload: dict) -> TrackSnapshot:
    return TrackSnapshot(
        track_id=int(payload["track_id"]),
        title=payload.get("title") or "",
        artist=payload.get("artist") or "",
        album=payload.get("album") or "",
        album_artist=payload.get("album_artist") or "",
        track_number=payload.get("track_number"),
        disc_number=payload.get("disc_number"),
        year=payload.get("year"),
        genre=payload.get("genre") or "",
    )


def tags_from_snapshot(track: TrackSnapshot) -> TrackTags:
    return TrackTags(
        title=track.title,
        artist=track.artist,
        album=track.album,
        album_artist=track.album_artist,
        track_number=track.track_number,
        disc_number=track.disc_number,
        year=track.year,
        genre=track.genre,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Undo the last Music Fix metadata change.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the latest undo snapshot without changing Music.",
    )
    args = parser.parse_args(argv)

    try:
        snapshot_path = latest_undo_snapshot()
        if snapshot_path is None:
            raise RuntimeError("No undo history found.")

        snapshot = load_undo_snapshot(snapshot_path)
        tracks = [track_from_payload(item) for item in snapshot.get("tracks", [])]
        if not tracks:
            raise RuntimeError("Latest undo snapshot has no tracks to restore.")

        action = snapshot.get("action") or "metadata update"
        created_at = snapshot.get("created_at") or "unknown time"
        if args.dry_run:
            print(f"Would undo {action} from {created_at}:")
            for track in tracks[:12]:
                print(f"  {track.artist} — {track.album} — {track.title}")
            if len(tracks) > 12:
                print(f"  ... and {len(tracks) - 12} more track(s)")
            return 0

        app_name = music_app_name()
        changes = [
            TagChange(
                track_id=track.track_id,
                before=track,
                after=tags_from_snapshot(track),
            )
            for track in tracks
        ]
        updated = apply_tag_changes(app_name, changes, save_undo=False)
        mark_undo_snapshot_used(snapshot_path)
        summary = f"Undid {action}: restored {updated} track(s)."
        print(summary)
        notify("Music Fix undo complete", summary)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Music Fix undo failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
