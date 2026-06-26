#!/usr/bin/env python3
"""Manage Music Fix local search cache."""

from __future__ import annotations

import argparse
import sys

from find_artwork import notify
from search_cache import cache_file_count, clear_cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the Music Fix search cache.")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show the number of cached search files.")
    clear_parser = subparsers.add_parser("clear", help="Clear cached search results.")
    clear_parser.add_argument(
        "--namespace",
        default=None,
        help="Clear only one cache namespace, such as release-tags or all-releases.",
    )

    args = parser.parse_args(argv)
    command = args.command or "status"

    try:
        if command == "clear":
            deleted = clear_cache(args.namespace)
            summary = f"Cleared {deleted} cached search file(s)."
            print(summary)
            notify("Music Fix cache cleared", summary)
            return 0

        count = cache_file_count()
        print(f"Music Fix cache contains {count} file(s).")
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Music Fix cache failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
