#!/usr/bin/env python3
"""Combine selected related albums into one multi-disc album."""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass

from find_artwork import clean_artist_name, music_app_name, normalize, notify, token_overlap
from find_tags import TagChange, TrackSnapshot, TrackTags, apply_tag_changes, format_change, get_target_tracks
from music_common import confirm_apply

REMIX_WORDS = {
    "remix",
    "remixes",
    "remixed",
    "mixes",
    "mix",
    "versions",
    "version",
    "bonus",
    "b-sides",
    "bsides",
    "rarities",
    "extras",
}


@dataclass(frozen=True)
class CombineBucket:
    artist: str
    album: str
    album_artist: str
    tracks: tuple[TrackSnapshot, ...]

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.album} ({len(self.tracks)} track(s))"


def album_tokens(album: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", normalize(album)) if token}


def remix_score(album: str) -> int:
    tokens = album_tokens(album)
    return sum(1 for token in tokens if token in REMIX_WORDS)


def artist_related(left: str, right: str) -> bool:
    left_norm = normalize(clean_artist_name(left))
    right_norm = normalize(clean_artist_name(right))
    if not left_norm or not right_norm:
        return True
    if left_norm == right_norm:
        return True
    return token_overlap(left, right) >= 0.45


def build_buckets(tracks: list[TrackSnapshot]) -> list[CombineBucket]:
    grouped: dict[tuple[str, str], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        grouped[(track.artist, track.album)].append(track)

    buckets: list[CombineBucket] = []
    for (artist, album), bucket_tracks in grouped.items():
        album_artist = next((track.album_artist for track in bucket_tracks if track.album_artist), artist)
        buckets.append(
            CombineBucket(
                artist=artist,
                album=album,
                album_artist=album_artist,
                tracks=tuple(sorted(bucket_tracks, key=track_sort_key)),
            )
        )
    return buckets


def track_sort_key(track: TrackSnapshot) -> tuple[int, int, str]:
    return (track.disc_number or 1, track.track_number or 9999, normalize(track.title))


def choose_main_bucket(buckets: list[CombineBucket]) -> CombineBucket:
    return sorted(
        buckets,
        key=lambda bucket: (
            remix_score(bucket.album),
            -len(bucket.tracks),
            normalize(bucket.album),
        ),
    )[0]


def relatedness_warnings(main: CombineBucket, others: list[CombineBucket]) -> list[str]:
    warnings: list[str] = []
    main_tokens = album_tokens(main.album)
    main_artist = main.album_artist or main.artist
    for bucket in others:
        bucket_artist = bucket.album_artist or bucket.artist
        shared = main_tokens & album_tokens(bucket.album)
        if not artist_related(main_artist, bucket_artist):
            warnings.append(f"Artist differs: {bucket.label}")
        if remix_score(bucket.album) == 0 and not shared:
            warnings.append(f"Album title does not obviously look related: {bucket.label}")
    return warnings


def build_changes(
    main: CombineBucket,
    bonus_buckets: list[CombineBucket],
    combined_album: str,
    combined_album_artist: str,
    preserve_main_numbers: bool,
) -> list[TagChange]:
    changes: list[TagChange] = []
    ordered_buckets = [main, *bonus_buckets]
    for disc_index, bucket in enumerate(ordered_buckets, start=1):
        for track_index, track in enumerate(bucket.tracks, start=1):
            track_number = track.track_number if preserve_main_numbers and disc_index == 1 else track_index
            after = TrackTags(
                title=track.title,
                artist=track.artist,
                album=combined_album,
                album_artist=combined_album_artist,
                track_number=track_number,
                disc_number=disc_index,
                year=track.year,
                genre=track.genre,
            )
            if (
                normalize(track.album) == normalize(after.album)
                and normalize(track.album_artist or track.artist) == normalize(after.album_artist)
                and (track.disc_number or 1) == (after.disc_number or 1)
                and track.track_number == after.track_number
            ):
                continue
            changes.append(TagChange(track_id=track.track_id, before=track, after=after))
    return changes


def format_plan(
    main: CombineBucket,
    bonus_buckets: list[CombineBucket],
    combined_album: str,
    combined_album_artist: str,
    changes: list[TagChange],
    warnings: list[str],
) -> str:
    lines = [
        "Smart Combine plan",
        f"Combined album: {combined_album}",
        f"Album artist: {combined_album_artist}",
        "",
        f"Disc 1 (main): {main.label}",
    ]
    for index, bucket in enumerate(bonus_buckets, start=2):
        lines.append(f"Disc {index}: {bucket.label}")
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", f"Changes: {len(changes)} track(s)"])
    for change in changes[:10]:
        lines.append(format_change(change))
    if len(changes) > 10:
        lines.append(f"... and {len(changes) - 10} more track(s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Combine selected related albums into one multi-disc album."
    )
    parser.add_argument("--main-album", help="Album title to use as disc 1.")
    parser.add_argument("--album", help="Combined album title. Defaults to the main album title.")
    parser.add_argument("--album-artist", help="Combined album artist. Defaults to the main album artist.")
    parser.add_argument("--yes", action="store_true", help="Apply without confirmation.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without changing Music.")
    parser.add_argument(
        "--preserve-main-numbers",
        action="store_true",
        help="Keep existing track numbers on the main album.",
    )
    args = parser.parse_args(argv)

    try:
        app_name = music_app_name()
        selected_tracks = get_target_tracks(app_name, entire_album=False)
        buckets = build_buckets(selected_tracks)
        if len(buckets) < 2:
            raise RuntimeError("Select at least two albums or groups of songs to combine.")

        if args.main_album:
            matches = [bucket for bucket in buckets if normalize(bucket.album) == normalize(args.main_album)]
            if not matches:
                raise RuntimeError(f"Selected tracks do not include album {args.main_album!r}.")
            main_bucket = matches[0]
        else:
            main_bucket = choose_main_bucket(buckets)

        bonus_buckets = [bucket for bucket in buckets if bucket is not main_bucket]
        bonus_buckets.sort(key=lambda bucket: (remix_score(bucket.album) == 0, normalize(bucket.album)))

        combined_album = args.album or main_bucket.album
        combined_album_artist = args.album_artist or main_bucket.album_artist or main_bucket.artist
        warnings = relatedness_warnings(main_bucket, bonus_buckets)
        changes = build_changes(
            main_bucket,
            bonus_buckets,
            combined_album,
            combined_album_artist,
            preserve_main_numbers=args.preserve_main_numbers,
        )
        if not changes:
            print("Selected albums already match the smart combine plan.")
            return 0

        plan = format_plan(
            main_bucket,
            bonus_buckets,
            combined_album,
            combined_album_artist,
            changes,
            warnings,
        )
        if args.dry_run:
            print(plan)
            return 0
        if not args.yes and not confirm_apply("Smart Combine Albums", plan):
            raise RuntimeError("Smart combine cancelled.")

        group_id = f"smart-combine-{uuid.uuid4()}"
        updated = apply_tag_changes(
            app_name,
            changes,
            undo_action="smart album combine",
            undo_group_id=group_id,
        )
        summary = f"Smart combined {len(buckets)} album(s) into {combined_album}: updated {updated} track(s)."
        print(summary)
        notify("Smart combine complete", summary)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Smart combine failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
