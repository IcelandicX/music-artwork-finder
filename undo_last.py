#!/usr/bin/env python3
"""Undo the last Music Fix metadata change."""

from __future__ import annotations

import argparse
import sys

from find_artwork import music_app_name, notify
from find_tags import applescript_string
from find_tags import TagChange, TrackSnapshot, TrackTags, apply_tag_changes
from undo_history import (
    latest_undo_snapshot,
    load_undo_snapshot,
    mark_undo_snapshot_used,
    undo_snapshots_for_group,
)

FIELD_SEP = "|||"


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


def restore_artwork(app_name: str, tracks: list[dict]) -> int:
    records: list[str] = []
    for track in tracks:
        artwork_path = track.get("artwork_path")
        if not artwork_path:
            continue
        records.append(
            FIELD_SEP.join(
                [
                    str(track.get("track_id") or ""),
                    track.get("title") or "",
                    track.get("artist") or "",
                    track.get("album") or "",
                    artwork_path,
                ]
            )
        )

    if not records:
        return 0

    record_literal = "{" + ", ".join(f'"{applescript_string(record)}"' for record in records) + "}"
    script = f'''
tell application "{app_name}"
    set restoredCount to 0
    repeat with recordLine in {record_literal}
        set AppleScript's text item delimiters to "{FIELD_SEP}"
        set parts to text items of recordLine
        set AppleScript's text item delimiters to ""
        set trackId to item 1 of parts as integer
        set artworkPath to item 5 of parts
        try
            set theTrack to (first track of library playlist 1 whose id is trackId)
            set artworkFile to POSIX file artworkPath
            set artworkData to read artworkFile as picture
            try
                set data of artwork 1 of theTrack to artworkData
            on error
                set data of artwork of theTrack to artworkData
            end try
            set restoredCount to restoredCount + 1
        end try
    end repeat
    return restoredCount as string
end tell
'''
    from find_artwork import run_osascript

    return int(run_osascript(script))


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
        group_id = snapshot.get("group_id")
        snapshot_paths = undo_snapshots_for_group(group_id) if group_id else [snapshot_path]
        snapshots = [load_undo_snapshot(path) for path in reversed(snapshot_paths)]

        if args.dry_run and len(snapshots) > 1:
            total_tracks = sum(len(item.get("tracks", [])) for item in snapshots)
            print(f"Would undo grouped all-in-one run with {len(snapshots)} snapshot(s), {total_tracks} track record(s).")
            for item in snapshots:
                action = item.get("action") or "metadata update"
                created_at = item.get("created_at") or "unknown time"
                print(f"\n{action} from {created_at}:")
                for track in item.get("tracks", [])[:6]:
                    print(
                        "  "
                        f"{track.get('artist', '')} — {track.get('album', '')} — {track.get('title', '')}"
                    )
            return 0

        kind = snapshot.get("kind") or "metadata"
        raw_tracks = snapshot.get("tracks", [])
        if not raw_tracks:
            raise RuntimeError("Latest undo snapshot has no tracks to restore.")

        action = snapshot.get("action") or "metadata update"
        created_at = snapshot.get("created_at") or "unknown time"
        if args.dry_run:
            print(f"Would undo {action} from {created_at}:")
            for item in raw_tracks[:12]:
                print(
                    "  "
                    f"{item.get('artist', '')} — {item.get('album', '')} — {item.get('title', '')}"
                )
            if len(raw_tracks) > 12:
                print(f"  ... and {len(raw_tracks) - 12} more track(s)")
            return 0

        app_name = music_app_name()
        updated = 0
        for item in snapshots:
            item_kind = item.get("kind") or "metadata"
            item_tracks = item.get("tracks", [])
            if item_kind == "artwork":
                updated += restore_artwork(app_name, item_tracks)
            else:
                tracks = [track_from_payload(track) for track in item_tracks]
                changes = [
                    TagChange(
                        track_id=track.track_id,
                        before=track,
                        after=tags_from_snapshot(track),
                    )
                    for track in tracks
                ]
                updated += apply_tag_changes(app_name, changes, save_undo=False)
        for path in snapshot_paths:
            mark_undo_snapshot_used(path)
        if len(snapshots) > 1:
            summary = f"Undid grouped all-in-one run: restored {updated} track record(s)."
        else:
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
