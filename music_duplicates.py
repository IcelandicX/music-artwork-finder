#!/usr/bin/env python3
"""Detect and remove duplicate tracks from Music."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from find_artwork import music_app_name, normalize, notify, run_osascript
from find_tags import (
    FIELD_SEP,
    TagChange,
    TrackSnapshot,
    TrackTags,
    applescript_string,
    apply_tag_changes,
    format_change,
    get_target_tracks,
    get_tracks_for_album_title,
)
from music_common import confirm_apply
from resolve_splits import get_all_library_tracks
from run_report import REPORT_DIR


@dataclass(frozen=True)
class DuplicateGroup:
    key: tuple[str, ...]
    keeper: TrackSnapshot
    duplicates: tuple[TrackSnapshot, ...]
    match_mode: str


@dataclass(frozen=True)
class RenameGroup:
    key: tuple[str, ...]
    tracks: tuple[TrackSnapshot, ...]
    changes: tuple[TagChange, ...]


FINGERPRINT_MARKERS = {
    "album version",
    "clean",
    "digital remaster",
    "edit",
    "explicit",
    "mono",
    "radio edit",
    "remaster",
    "remastered",
    "remix",
    "single version",
    "stereo",
    "version",
}


def strip_marker_groups(title: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        content = normalize(match.group(1))
        if any(marker in content for marker in FINGERPRINT_MARKERS):
            return " "
        return f" {match.group(1)} "

    title = re.sub(r"\(([^)]*)\)", replacement, title)
    title = re.sub(r"\[([^]]*)\]", replacement, title)
    title = re.sub(r"\{([^}]*)\}", replacement, title)
    return title


def fingerprint_title(title: str) -> str:
    text = strip_marker_groups(title)
    text = re.sub(r"\b(19|20)\d{2}\s+(remaster|remastered)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(remaster|remastered|version|edit|mix)\b", " ", text, flags=re.IGNORECASE)
    return normalize(text)


def duplicate_key(
    track: TrackSnapshot,
    ignore_album: bool,
    fingerprint: bool,
    ignore_position: bool,
) -> tuple[str, ...]:
    artist = normalize(track.album_artist or track.artist)
    title = fingerprint_title(track.title) if fingerprint else normalize(track.title)
    position: tuple[str, ...] = ()
    if not ignore_position:
        position = (str(track.disc_number or 1), str(track.track_number or 0))
    if ignore_album:
        return (title, artist, *position)
    return (title, artist, normalize(track.album), *position)


def keeper_score(track: TrackSnapshot) -> tuple[int, int, int, int, int]:
    return (
        1 if track.album_artist else 0,
        1 if track.track_number else 0,
        1 if track.disc_number else 0,
        1 if track.year else 0,
        len(track.genre or ""),
    )


def title_collision_key(track: TrackSnapshot, ignore_album: bool) -> tuple[str, ...]:
    artist = normalize(track.album_artist or track.artist)
    title = normalize(track.title)
    if ignore_album:
        return (title, artist)
    return (title, artist, normalize(track.album))


def tracks_look_identical(left: TrackSnapshot, right: TrackSnapshot, ignore_album: bool) -> bool:
    if normalize(left.title) != normalize(right.title):
        return False
    if normalize(left.album_artist or left.artist) != normalize(right.album_artist or right.artist):
        return False
    if not ignore_album and normalize(left.album) != normalize(right.album):
        return False
    return (left.disc_number or 1) == (right.disc_number or 1) and (
        left.track_number or 0
    ) == (right.track_number or 0)


def context_suffix(track: TrackSnapshot, same_album: bool) -> str:
    parts: list[str] = []
    if not same_album and track.album:
        parts.append(track.album)
    if track.disc_number and track.disc_number > 1:
        parts.append(f"Disc {track.disc_number}")
    if track.track_number:
        parts.append(f"Track {track.track_number}")
    if not parts and track.genre:
        parts.append(track.genre)
    if not parts and track.year:
        parts.append(str(track.year))
    return ", ".join(parts) if parts else f"ID {track.track_id}"


def disambiguated_title(track: TrackSnapshot, suffix: str) -> str:
    normalized_title = normalize(track.title)
    normalized_suffix = normalize(suffix)
    if normalized_suffix and normalized_suffix in normalized_title:
        return track.title
    return f"{track.title} ({suffix})"


def build_rename_groups(
    tracks: list[TrackSnapshot],
    duplicate_groups: list[DuplicateGroup],
    ignore_album: bool,
) -> list[RenameGroup]:
    duplicate_ids = {
        track.track_id
        for group in duplicate_groups
        for track in (group.keeper, *group.duplicates)
    }
    grouped: dict[tuple[str, ...], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        key = title_collision_key(track, ignore_album=ignore_album)
        if not all(key):
            continue
        grouped[key].append(track)

    rename_groups: list[RenameGroup] = []
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        if all(tracks_look_identical(items[0], item, ignore_album=ignore_album) for item in items[1:]):
            continue

        rename_candidates = [item for item in items if item.track_id not in duplicate_ids]
        if len(rename_candidates) < 2:
            continue
        same_album = len({normalize(item.album) for item in rename_candidates}) == 1
        changes: list[TagChange] = []
        used_titles = {normalize(item.title) for item in rename_candidates}
        for item in sorted(rename_candidates, key=lambda track: (track.disc_number or 1, track.track_number or 0, track.track_id)):
            suffix = context_suffix(item, same_album=same_album)
            new_title = disambiguated_title(item, suffix)
            if normalize(new_title) in used_titles and normalize(new_title) != normalize(item.title):
                suffix = f"{suffix}, ID {item.track_id}"
                new_title = disambiguated_title(item, suffix)
            if normalize(new_title) == normalize(item.title):
                continue
            used_titles.add(normalize(new_title))
            changes.append(
                TagChange(
                    track_id=item.track_id,
                    before=item,
                    after=TrackTags(
                        title=new_title,
                        artist=item.artist,
                        album=item.album,
                        album_artist=item.album_artist or item.artist,
                        track_number=item.track_number,
                        disc_number=item.disc_number,
                        year=item.year,
                        genre=item.genre,
                    ),
                )
            )
        if changes:
            rename_groups.append(RenameGroup(key=key, tracks=tuple(rename_candidates), changes=tuple(changes)))

    return sorted(rename_groups, key=lambda group: (group.tracks[0].artist, group.tracks[0].album, group.tracks[0].title))


def find_duplicate_groups(
    tracks: list[TrackSnapshot],
    ignore_album: bool,
    fingerprint: bool,
    ignore_position: bool = False,
) -> list[DuplicateGroup]:
    grouped: dict[tuple[str, ...], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        key = duplicate_key(track, ignore_album, fingerprint, ignore_position)
        if not all(key):
            continue
        grouped[key].append(track)

    groups: list[DuplicateGroup] = []
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=keeper_score, reverse=True)
        groups.append(
            DuplicateGroup(
                key=key,
                keeper=ordered[0],
                duplicates=tuple(ordered[1:]),
                match_mode="fingerprint" if fingerprint else "exact",
            )
        )
    return sorted(groups, key=lambda group: (group.keeper.artist, group.keeper.album, group.keeper.title))


def selected_scope_tracks(app_name: str) -> list[TrackSnapshot]:
    selected = get_target_tracks(app_name, entire_album=False)
    album_titles: list[str] = []
    seen_albums: set[str] = set()
    for track in selected:
        key = normalize(track.album)
        if key and key not in seen_albums:
            seen_albums.add(key)
            album_titles.append(track.album)

    tracks: list[TrackSnapshot] = []
    seen_ids: set[int] = set()
    for album in album_titles:
        for track in get_tracks_for_album_title(app_name, album):
            if track.track_id in seen_ids:
                continue
            seen_ids.add(track.track_id)
            tracks.append(track)
    return tracks or selected


def format_track(track: TrackSnapshot) -> str:
    return (
        f"{track.artist} - {track.album} - {track.title} "
        f"(id {track.track_id}, disc {track.disc_number or 1}, track {track.track_number or '?'})"
    )


def format_plan(groups: list[DuplicateGroup], rename_groups: list[RenameGroup]) -> str:
    duplicate_count = sum(len(group.duplicates) for group in groups)
    rename_count = sum(len(group.changes) for group in rename_groups)
    lines = [
        "Duplicate cleanup plan",
        f"Duplicate groups: {len(groups)}",
        f"Tracks to remove: {duplicate_count}",
        f"Title groups to rename: {len(rename_groups)}",
        f"Tracks to rename: {rename_count}",
        "",
        "This removes identical-looking duplicate tracks and renames non-identical tracks that share the same displayed title.",
        "Fingerprint mode normalizes casing, punctuation, spacing, and common parenthetical/version markers.",
        "By default it also requires the same disc/track position to avoid removing alternate takes across discs.",
        "",
    ]
    for group in groups[:20]:
        lines.append(f"Keep [{group.match_mode}]: {format_track(group.keeper)}")
        for duplicate in group.duplicates:
            lines.append(f"  Remove: {format_track(duplicate)}")
        lines.append("")
    if len(groups) > 20:
        lines.append(f"... and {len(groups) - 20} more duplicate group(s)")

    if rename_groups:
        lines.extend(["", "Rename non-identical same-title tracks:"])
        for group in rename_groups[:20]:
            lines.append(f"Title collision: {group.tracks[0].title}")
            for change in group.changes:
                lines.append(f"  Rename: {format_change(change)}")
            lines.append("")
        if len(rename_groups) > 20:
            lines.append(f"... and {len(rename_groups) - 20} more rename group(s)")
    return "\n".join(lines).strip()


def save_duplicate_report(plan: str, summary: str | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "latest-duplicates.txt"
    lines = [plan]
    if summary:
        lines.extend(["", summary])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def remove_duplicate_tracks(app_name: str, duplicates: list[TrackSnapshot]) -> int:
    records = [
        FIELD_SEP.join(
            [
                str(track.track_id),
                track.title,
                track.artist,
                track.album,
                track.album_artist or "",
            ]
        )
        for track in duplicates
    ]
    if not records:
        return 0
    record_literal = "{" + ", ".join(f'"{applescript_string(record)}"' for record in records) + "}"
    script = f'''
tell application "{app_name}"
    set removedCount to 0
    repeat with recordLine in {record_literal}
        set AppleScript's text item delimiters to "{FIELD_SEP}"
        set parts to text items of recordLine
        set AppleScript's text item delimiters to ""
        set trackId to item 1 of parts as integer
        set oldTitle to item 2 of parts
        set oldArtist to item 3 of parts
        set oldAlbum to item 4 of parts
        set oldAlbumArtist to item 5 of parts
        try
            set theTrack to (first track of library playlist 1 whose id is trackId)
        on error
            set matchingTracks to (every track of library playlist 1 whose name is oldTitle and artist is oldArtist and album is oldAlbum)
            if (count of matchingTracks) is 0 and oldAlbumArtist is not "" then
                set matchingTracks to (every track of library playlist 1 whose name is oldTitle and album is oldAlbum and album artist is oldAlbumArtist)
            end if
            if (count of matchingTracks) is 0 then
                error "Could not find duplicate to remove: " & oldArtist & " - " & oldAlbum & " - " & oldTitle
            end if
            set theTrack to item 1 of matchingTracks
        end try
        delete theTrack
        set removedCount to removedCount + 1
    end repeat
    return removedCount as string
end tell
'''
    return int(run_osascript(script))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect and remove duplicate tracks from Music.")
    parser.add_argument("--library", action="store_true", help="Scan the whole library instead of selected albums.")
    parser.add_argument("--ignore-album", action="store_true", help="Treat same title+artist across albums as duplicates.")
    parser.add_argument(
        "--ignore-position",
        action="store_true",
        help="Allow duplicates across different disc/track numbers. Use with care.",
    )
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="Use conservative fuzzy fingerprints for title casing, punctuation, whitespace, and common version/remix markers.",
    )
    parser.add_argument("--yes", action="store_true", help="Remove duplicates without confirmation.")
    parser.add_argument("--dry-run", action="store_true", help="Print duplicate plan without changing Music.")
    args = parser.parse_args(argv)

    try:
        app_name = music_app_name()
        tracks = get_all_library_tracks(app_name) if args.library else selected_scope_tracks(app_name)
        groups = find_duplicate_groups(
            tracks,
            ignore_album=args.ignore_album,
            fingerprint=args.fingerprint,
            ignore_position=args.ignore_position,
        )
        rename_groups = build_rename_groups(tracks, groups, ignore_album=args.ignore_album)
        if not groups and not rename_groups:
            print("No duplicate tracks or same-title rename candidates found.")
            return 0

        plan = format_plan(groups, rename_groups)
        if args.dry_run:
            print(plan)
            report_path = save_duplicate_report(plan)
            print(f"\nReport: {report_path}")
            return 0

        if not args.yes and not confirm_apply("Clean Up Duplicate Tracks", plan):
            raise RuntimeError("Duplicate cleanup cancelled.")

        duplicates = [track for group in groups for track in group.duplicates]
        rename_changes = [change for group in rename_groups for change in group.changes]
        renamed = apply_tag_changes(
            app_name,
            rename_changes,
            undo_action="duplicate title rename",
            undo_group_id=None,
        )
        removed = remove_duplicate_tracks(app_name, duplicates)
        summary = (
            f"Removed {removed} duplicate track(s) from {len(groups)} group(s); "
            f"renamed {renamed} non-identical same-title track(s)."
        )
        report_path = save_duplicate_report(plan, summary)
        summary += f" Report: {report_path}"
        print(summary)
        notify("Duplicate removal complete", summary)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Duplicate removal failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
