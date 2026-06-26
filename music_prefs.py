#!/usr/bin/env python3
"""Inspect and update Music Fix preferences."""

from __future__ import annotations

import argparse
import sys

from find_artwork import notify
from preferences import DEFAULT_PREFS, RUN_MODES, format_preferences, load_preferences, reset_preferences, save_preferences


def parse_bool(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true/false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect and update Music Fix preferences.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("show", help="Show current preferences.")
    subparsers.add_parser("reset", help="Reset preferences to defaults.")

    set_parser = subparsers.add_parser("set", help="Set one preference.")
    set_parser.add_argument("key", choices=sorted(DEFAULT_PREFS))
    set_parser.add_argument("value")

    args = parser.parse_args(argv)
    command = args.command or "show"

    try:
        if command == "reset":
            reset_preferences()
            summary = "Reset Music Fix preferences."
            print(summary)
            notify("Music Fix preferences", summary)
            return 0

        if command == "set":
            prefs = load_preferences()
            if args.key == "run_mode":
                value = args.value.casefold()
                if value not in RUN_MODES:
                    raise RuntimeError(f"run_mode must be one of: {', '.join(sorted(RUN_MODES))}")
            elif args.key == "confirm_below":
                value = float(args.value)
            elif args.key == "selection_only":
                value = parse_bool(args.value)
            elif args.key == "cache_ttl_hours":
                value = int(args.value)
            else:
                value = args.value
            prefs[args.key] = value
            save_preferences(prefs)
            summary = f"Set {args.key} to {value}."
            print(summary)
            notify("Music Fix preferences", summary)
            return 0

        print(format_preferences())
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Music Fix preferences failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
