#!/usr/bin/env python3
"""All-in-one AI-assisted Music Fix workflow."""

from __future__ import annotations

import argparse
import sys

from fix_album import main as fix_album_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "AI all-in-one fix: deep-resolve split album(s), fix tags, "
            "find artwork, auto-apply, and save undo metadata."
        )
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show a confirmation preview before applying.",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying Music.",
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Only update selected song(s), not the whole resolved album.",
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
        help="Choose which online album match to use after AI split resolution.",
    )
    parser.add_argument(
        "--no-reembed",
        action="store_true",
        help="Skip re-embedding artwork after applying it.",
    )
    args = parser.parse_args(argv)

    fix_args = [
        "--resolve-splits",
        "--ai-deep-dive",
        "--min-score",
        str(args.min_score),
    ]
    if args.preview and not args.dry_run:
        fix_args.append("--preview")
    if args.dry_run:
        fix_args.append("--dry-run")
    if args.selection_only:
        fix_args.append("--selection-only")
    if args.pick:
        fix_args.append("--pick")
    if args.no_reembed:
        fix_args.append("--no-reembed")

    return fix_album_main(fix_args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
