#!/usr/bin/env python3
"""Analyze and split combined album(s) back into related albums."""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from find_artwork import music_app_name, normalize, notify
from find_tags import (
    TagChange,
    TrackSnapshot,
    TrackTags,
    apply_tag_changes,
    format_change,
    get_target_tracks,
    get_tracks_for_album_title,
)
from music_common import confirm_apply
from run_report import REPORT_DIR

REMIX_WORDS = {
    "remix",
    "remixes",
    "remixed",
    "mix",
    "mixes",
    "version",
    "versions",
    "edit",
    "dub",
    "rework",
}
BONUS_WORDS = {"bonus", "demo", "demos", "b-side", "b-sides", "bside", "bsides", "rarity", "rarities"}


@dataclass(frozen=True)
class ResplitGroup:
    source_album: str
    target_album: str
    reason: str
    tracks: tuple[TrackSnapshot, ...]


def tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", normalize(value)) if token}


def has_any_word(value: str, words: set[str]) -> bool:
    return bool(tokens(value) & words)


def default_remix_album_name(album: str) -> str:
    normalized = normalize(album)
    if "remix" in normalized:
        return album
    return "Remixes"


def default_bonus_album_name(album: str) -> str:
    normalized = normalize(album)
    if "bonus" in normalized:
        return album
    return "Bonus Tracks"


def selected_album_tracks(app_name: str) -> list[TrackSnapshot]:
    selected = get_target_tracks(app_name, entire_album=False)
    album_titles = []
    seen: set[str] = set()
    for track in selected:
        key = normalize(track.album)
        if key and key not in seen:
            seen.add(key)
            album_titles.append(track.album)

    tracks: list[TrackSnapshot] = []
    seen_ids: set[int] = set()
    for album in album_titles:
        for track in get_tracks_for_album_title(app_name, album):
            if track.track_id in seen_ids:
                continue
            seen_ids.add(track.track_id)
            tracks.append(track)
    return sorted(tracks, key=lambda item: (item.album, item.disc_number or 1, item.track_number or 9999, normalize(item.title)))


def infer_groups(
    tracks: list[TrackSnapshot],
    remix_album: str | None,
    bonus_album: str | None,
    include_disc_groups: bool,
) -> list[ResplitGroup]:
    grouped: dict[tuple[str, str, str], list[TrackSnapshot]] = defaultdict(list)
    by_disc: dict[tuple[str, int], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        disc = track.disc_number or 1
        by_disc[(track.album, disc)].append(track)

    title_groups: dict[tuple[str, str, str], list[TrackSnapshot]] = defaultdict(list)
    disc_candidates: dict[tuple[str, int], list[TrackSnapshot]] = {}
    all_disc_candidates: dict[tuple[str, int], list[TrackSnapshot]] = {}
    for key, disc_tracks in by_disc.items():
        album, disc = key
        if disc <= 1:
            continue
        all_disc_candidates[(album, disc)] = disc_tracks
        signal_count = sum(
            1
            for track in disc_tracks
            if has_any_word(track.title, REMIX_WORDS) or has_any_word(track.title, BONUS_WORDS)
        )
        if include_disc_groups or (disc_tracks and signal_count / len(disc_tracks) >= 0.60):
            disc_candidates[(album, disc)] = disc_tracks

    for track in tracks:
        disc = track.disc_number or 1
        title_is_remix = has_any_word(track.title, REMIX_WORDS)
        title_is_bonus = has_any_word(track.title, BONUS_WORDS)
        if title_is_remix:
            target = remix_album or default_remix_album_name(track.album)
            title_groups[(track.album, target, "remix-looking title")].append(track)
        elif title_is_bonus:
            target = bonus_album or default_bonus_album_name(track.album)
            title_groups[(track.album, target, "bonus-looking title")].append(track)

    if title_groups:
        grouped.update(title_groups)
    else:
        fallback_disc_candidates = disc_candidates or all_disc_candidates
        for (album, disc), disc_tracks in fallback_disc_candidates.items():
            target = remix_album or default_remix_album_name(album)
            grouped[(album, target, f"disc {disc}")].extend(disc_tracks)

    return [
        ResplitGroup(source_album=source, target_album=target, reason=reason, tracks=tuple(group_tracks))
        for (source, target, reason), group_tracks in sorted(grouped.items())
    ]


def build_changes(groups: list[ResplitGroup], renumber: bool) -> list[TagChange]:
    changes: list[TagChange] = []
    for group in groups:
        ordered = sorted(group.tracks, key=lambda item: (item.disc_number or 1, item.track_number or 9999, normalize(item.title)))
        for index, track in enumerate(ordered, start=1):
            after = TrackTags(
                title=track.title,
                artist=track.artist,
                album=group.target_album,
                album_artist=track.album_artist or track.artist,
                track_number=index if renumber else track.track_number or index,
                disc_number=1,
                year=track.year,
                genre=track.genre,
            )
            if (
                normalize(track.album) == normalize(after.album)
                and (track.disc_number or 1) == (after.disc_number or 1)
                and track.track_number == after.track_number
            ):
                continue
            changes.append(TagChange(track_id=track.track_id, before=track, after=after))
    return changes


def format_plan(groups: list[ResplitGroup], changes: list[TagChange]) -> str:
    lines = ["Analyze and Resplit plan", ""]
    for group in groups:
        lines.append(
            f"{group.source_album} -> {group.target_album}: {len(group.tracks)} track(s) ({group.reason})"
        )
    lines.extend(["", f"Changes: {len(changes)} track(s)"])
    for change in changes[:12]:
        lines.append(format_change(change))
    if len(changes) > 12:
        lines.append(f"... and {len(changes) - 12} more track(s)")
    return "\n".join(lines)


def save_resplit_report(plan: str, summary: str | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "latest-resplit.txt"
    lines = [plan]
    if summary:
        lines.extend(["", summary])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze and split combined album(s) back into related albums.")
    parser.add_argument("--remix-album", help="Album name for remix tracks (default: Remixes).")
    parser.add_argument("--bonus-album", help="Album name for bonus/demo tracks (default: Bonus Tracks).")
    parser.add_argument(
        "--disc-groups",
        action="store_true",
        help="Move all disc 2+ tracks, even if their titles do not look like remixes or bonus tracks.",
    )
    parser.add_argument("--renumber", action="store_true", help="Renumber each split album from 1.")
    parser.add_argument("--yes", action="store_true", help="Apply without confirmation.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without changing Music.")
    args = parser.parse_args(argv)

    try:
        app_name = music_app_name()
        tracks = selected_album_tracks(app_name)
        if not tracks:
            raise RuntimeError("No tracks found to analyze.")

        groups = infer_groups(
            tracks,
            remix_album=args.remix_album,
            bonus_album=args.bonus_album,
            include_disc_groups=args.disc_groups,
        )
        if not groups:
            raise RuntimeError("No remix, bonus, or disc 2+ tracks found to resplit.")

        changes = build_changes(groups, renumber=args.renumber)
        if not changes:
            print("Selected album(s) already match the resplit plan.")
            return 0

        plan = format_plan(groups, changes)
        if args.dry_run:
            print(plan)
            report_path = save_resplit_report(plan)
            print(f"\nReport: {report_path}")
            return 0

        if not args.yes and not confirm_apply("Analyze and Resplit Albums", plan):
            raise RuntimeError("Resplit cancelled.")

        group_id = f"resplit-{uuid.uuid4()}"
        updated = apply_tag_changes(
            app_name,
            changes,
            undo_action="album resplit",
            undo_group_id=group_id,
        )
        summary = f"Resplit {len(groups)} group(s): updated {updated} track(s)."
        report_path = save_resplit_report(plan, summary)
        summary += f" Report: {report_path}"
        print(summary)
        notify("Album resplit complete", summary)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Album resplit failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
