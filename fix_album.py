#!/usr/bin/env python3
"""Fix tags and artwork using one shared MusicBrainz album match."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from find_artwork import (
    artwork_from_release,
    download_artwork,
    get_selected_album,
    music_app_name,
    notify,
    process_album,
)
from find_tags import format_change, get_target_tracks, process_tags
from music_common import choose_release_match, confirm_apply


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fix tags and artwork for the selected album using one shared online match."
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Only update the selected tracks instead of the whole album.",
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
    args = parser.parse_args(argv)

    fix_tags = not args.artwork_only
    fix_artwork = not args.tags_only

    try:
        app_name = music_app_name()
        album = get_selected_album(app_name)
        local_tracks = get_target_tracks(app_name, entire_album=not args.selection_only)
        if not local_tracks:
            raise RuntimeError("No tracks found to update.")

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
            print(build_preview_message(release.label, tag_changes, artwork_label))
            return 0

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
            )

        if fix_artwork and artwork_candidate is not None:
            updated_artwork, _ = process_album(
                app_name,
                album,
                min_score=args.min_score,
                entire_album=not args.selection_only,
                skip_existing=False,
                apply_index=None,
                pick_interactive=False,
                dry_run=False,
                preview=False,
                reembed=not args.no_reembed,
                release_match=release,
            )

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

        summary = f"Fixed {album.album} using {release.title}: " + ", ".join(parts)
        print(summary)
        notify("Album fix complete", summary)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Album fix failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
