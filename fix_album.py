#!/usr/bin/env python3
"""Fix tags and artwork using one shared MusicBrainz album match."""

from __future__ import annotations

import argparse
import sys
import tempfile
import uuid
from pathlib import Path

from find_artwork import (
    AlbumInfo,
    apply_artwork_to_track_ids,
    artwork_from_release,
    download_artwork,
    music_app_name,
    notify,
    run_osascript,
    save_artwork_undo_for_track_ids,
)
from find_tags import (
    format_change,
    get_target_tracks,
    get_target_tracks_for_album,
    process_tags,
)
from music_common import choose_release_match, confirm_apply, get_all_library_albums
from run_report import save_run_report
from resolve_splits import auto_resolve_for_selection


def build_preview_message(
    release_label: str,
    tag_changes: list,
    artwork_label: str | None,
) -> str:
    lines = [f"Use this album match for everything:", release_label, ""]
    if tag_changes:
        lines.append(f"Tags: update {len(tag_changes)} track(s)")
        for change in tag_changes[:5]:
            lines.append(format_change(change))
        if len(tag_changes) > 5:
            lines.append(f"... and {len(tag_changes) - 5} more track(s)")
    else:
        lines.append("Tags: already correct")

    lines.append("")
    if artwork_label:
        lines.append(f"Artwork: {artwork_label}")
    else:
        lines.append("Artwork: none found for this release")
    return "\n".join(lines)


def choose_album_from_library(app_name: str) -> tuple[AlbumInfo, list]:
    albums = sorted(
        get_all_library_albums(app_name),
        key=lambda item: (item.artist.casefold(), item.album.casefold()),
    )
    if not albums:
        raise RuntimeError("No albums found in your Music library.")

    options = [
        f"{index}. {album.artist} — {album.album}".replace('"', '\\"')
        for index, album in enumerate(albums, start=1)
    ]
    list_literal = "{" + ", ".join(f'"{option}"' for option in options) + "}"
    script = f'''
set choices to {list_literal}
set picked to choose from list choices with prompt "No Music selection found. Choose album/albums to fix:" default items {{item 1 of choices}}
if picked is false then
    return "CANCEL"
else
    return item 1 of picked
end if
'''
    result = run_osascript(script)
    if result == "CANCEL":
        raise RuntimeError("Album selection cancelled.")

    chosen_index = int(result.split(".", 1)[0]) - 1
    album = albums[chosen_index]
    return album, get_target_tracks_for_album(app_name, album)


def selected_album_jobs(app_name: str, selection_only: bool) -> list[tuple[AlbumInfo, list]]:
    try:
        selected_tracks = get_target_tracks(app_name, entire_album=False)
    except RuntimeError as exc:
        if "No album(s) or song(s) selected" not in str(exc):
            raise
        return [choose_album_from_library(app_name)]

    if not selected_tracks:
        return [choose_album_from_library(app_name)]

    if selection_only:
        first = selected_tracks[0]
        album = AlbumInfo(
            artist=first.album_artist or first.artist,
            album=first.album,
            app_name=app_name,
        )
        return [(album, selected_tracks)]

    jobs: list[tuple[AlbumInfo, list]] = []
    seen: set[tuple[str, str]] = set()
    for track in selected_tracks:
        key = (track.artist, track.album)
        if key in seen:
            continue
        seen.add(key)
        album = AlbumInfo(artist=track.artist, album=track.album, app_name=app_name)
        try:
            tracks = get_target_tracks_for_album(app_name, album)
        except RuntimeError:
            tracks = [item for item in selected_tracks if item.artist == track.artist and item.album == track.album]
        jobs.append((album, tracks))
    return jobs


def process_one_album(
    app_name: str,
    album: AlbumInfo,
    local_tracks: list,
    args: argparse.Namespace,
    fix_tags: bool,
    fix_artwork: bool,
    undo_group_id: str | None = None,
) -> str:
    release = choose_release_match(
        album,
        min_score=args.min_score,
        pick_interactive=args.pick,
    )

    tag_result = (0, release, [])
    artwork_candidate = None
    if fix_tags:
        tag_result = process_tags(
            app_name,
            album,
            local_tracks,
            min_score=args.min_score,
            pick_interactive=False,
            apply_index=None,
            dry_run=True,
            release_match=release,
            skip_if_correct=True,
        )

    if fix_artwork:
        artwork_candidate = artwork_from_release(release, album)
        if artwork_candidate is None and fix_artwork and not fix_tags:
            raise RuntimeError(f"No artwork found for release “{release.title}”.")

    _, _, tag_changes = tag_result
    artwork_label = None
    if artwork_candidate is not None:
        artwork_label = (
            f"{artwork_candidate.resolution_label} "
            f"({artwork_candidate.source}) {artwork_candidate.artist} — {artwork_candidate.title}"
        )

    if args.dry_run:
        return build_preview_message(release.label, tag_changes, artwork_label)

    if not args.preview and not args.pick:
        weak_reasons: list[str] = []
        if release.score < args.confirm_below:
            weak_reasons.append(f"release score {release.score:.2f}")
        if artwork_candidate is not None and artwork_candidate.score < args.confirm_below:
            weak_reasons.append(f"artwork score {artwork_candidate.score:.2f}")
        if weak_reasons:
            message = (
                build_preview_message(release.label, tag_changes, artwork_label)
                + "\n\nThis match is below the auto-apply confidence threshold: "
                + ", ".join(weak_reasons)
            )
            if not confirm_apply("Confirm low-confidence album fix", message):
                raise RuntimeError("Low-confidence album fix cancelled.")

    preview_image: Path | None = None
    temp_dir_ctx = None
    if args.preview:
        if artwork_candidate is not None:
            temp_dir_ctx = tempfile.TemporaryDirectory(prefix="music-fix-preview-")
            preview_image = Path(temp_dir_ctx.name) / "artwork.jpg"
            download_artwork(artwork_candidate.url, preview_image)

        message = build_preview_message(release.label, tag_changes, artwork_label)
        if not confirm_apply("Preview album fix", message, preview_image):
            raise RuntimeError("Album fix cancelled.")

    updated_tags = 0
    updated_artwork = 0

    if fix_tags and tag_changes:
        updated_tags, _, _ = process_tags(
            app_name,
            album,
            local_tracks,
            min_score=args.min_score,
            pick_interactive=False,
            apply_index=None,
            dry_run=False,
            release_match=release,
            preview=False,
            undo_group_id=undo_group_id,
        )

    if fix_artwork and artwork_candidate is not None:
        with tempfile.TemporaryDirectory(prefix="music-fix-artwork-") as temp_dir:
            image_path = Path(temp_dir) / "artwork.jpg"
            download_artwork(artwork_candidate.url, image_path)
            track_ids = [track.track_id for track in local_tracks]
            save_artwork_undo_for_track_ids(app_name, track_ids, group_id=undo_group_id)
            updated_artwork = apply_artwork_to_track_ids(app_name, image_path, track_ids)

    if temp_dir_ctx is not None:
        temp_dir_ctx.cleanup()

    parts: list[str] = []
    if fix_tags:
        if tag_changes:
            parts.append(f"tags updated on {updated_tags} track(s)")
        else:
            parts.append("tags already correct")
    if fix_artwork and artwork_candidate is not None:
        parts.append(f"{artwork_candidate.resolution_label} artwork applied to {updated_artwork} track(s)")

    return f"Fixed {album.album} using {release.title}: " + ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix tags and artwork for the selected album(s) using one shared online match."
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Only update the selected song(s) instead of the whole album(s).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.45,
        help="Minimum album match score required (default: 0.45).",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Choose which online album match to use.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Confirm changes before applying.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying Music.",
    )
    parser.add_argument(
        "--tags-only",
        action="store_true",
        help="Fix tags only.",
    )
    parser.add_argument(
        "--artwork-only",
        action="store_true",
        help="Fix artwork only.",
    )
    parser.add_argument(
        "--no-reembed",
        action="store_true",
        help="Skip re-embedding artwork after applying it.",
    )
    parser.add_argument(
        "--resolve-splits",
        action="store_true",
        help="Detect and combine split album(s) or song(s) before fixing tags and artwork.",
    )
    parser.add_argument(
        "--ai-deep-dive",
        action="store_true",
        help="Use deeper song-title and release-evidence scoring when resolving split album(s).",
    )
    parser.add_argument(
        "--confirm-below",
        type=float,
        default=0.60,
        help="Ask before applying matches below this confidence score (default: 0.60).",
    )
    parser.add_argument(
        "--run-mode",
        choices=["auto", "preview", "dry-run"],
        default="auto",
        help="Label the current run mode in reports.",
    )
    args = parser.parse_args(argv)

    fix_tags = not args.artwork_only
    fix_artwork = not args.tags_only

    try:
        app_name = music_app_name()
        if args.resolve_splits:
            auto_resolve_for_selection(
                app_name,
                min_score=args.min_score,
                preview=args.preview,
                dry_run=args.dry_run,
                ai_deep_dive=args.ai_deep_dive,
            )

        jobs = selected_album_jobs(app_name, selection_only=args.selection_only)
        if not jobs:
            raise RuntimeError("No tracks found to update.")

        summaries: list[str] = []
        failures: list[str] = []
        undo_group_id = f"all-in-one-{uuid.uuid4()}" if not args.dry_run else None
        for index, (album, local_tracks) in enumerate(jobs, start=1):
            if not local_tracks:
                continue
            progress = f"[{index}/{len(jobs)}] Processing {album.artist} — {album.album}"
            print(progress)
            sys.stdout.flush()
            try:
                summaries.append(
                    process_one_album(
                        app_name,
                        album,
                        local_tracks,
                        args,
                        fix_tags=fix_tags,
                        fix_artwork=fix_artwork,
                        undo_group_id=undo_group_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - report per album
                failures.append(f"{album.artist} — {album.album}: {exc}")

        if args.dry_run:
            report_path = save_run_report(
                "AI All-in-One Fix",
                args.run_mode,
                summaries,
                failures,
                undo_group_id=undo_group_id,
            )
            print("\n\n".join(summaries + [f"Skipped: {item}" for item in failures]))
            print(f"\nReport: {report_path}")
            return 0 if not failures else 1

        if summaries:
            print("\n".join(summaries))
        if failures:
            for failure in failures:
                print(f"Skipped: {failure}", file=sys.stderr)

        summary = f"All-in-one finished: {len(summaries)} album(s) fixed, {len(failures)} failed."
        report_path = save_run_report(
            "AI All-in-One Fix",
            args.run_mode,
            summaries,
            failures,
            undo_group_id=undo_group_id,
        )
        print(f"Report: {report_path}")
        notify("Album fix complete", summary)
        if failures and not summaries:
            raise RuntimeError("; ".join(failures))
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Album fix failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
