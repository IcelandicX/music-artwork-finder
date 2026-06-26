#!/usr/bin/env python3
"""First-run diagnostics for Music Fix."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from find_artwork import music_app_name, notify, run_osascript
from preferences import format_preferences
from search_cache import cache_file_count


def check(label: str, ok: bool, detail: str) -> str:
    status = "OK" if ok else "WARN"
    return f"[{status}] {label}: {detail}"


def command_path(command: str) -> str:
    return shutil.which(command) or "not found"


def music_access_check() -> tuple[bool, str]:
    try:
        app_name = music_app_name()
        result = run_osascript(f'tell application "{app_name}" to return name')
        return True, f"Automation can talk to {result or app_name}"
    except Exception as exc:  # noqa: BLE001 - diagnostic output
        return False, str(exc)


def internet_check() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("https://musicbrainz.org", timeout=5) as response:
            return response.status < 500, "musicbrainz.org reachable"
    except Exception as exc:  # noqa: BLE001 - diagnostic output
        return False, str(exc)


def launch_agent_check() -> tuple[bool, str]:
    plist = Path.home() / "Library" / "LaunchAgents" / "com.music-artwork-finder.plist"
    if not plist.exists():
        return False, f"missing {plist}"
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/com.music-artwork-finder"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, "LaunchAgent is loaded"
    return False, "plist exists but LaunchAgent is not loaded"


def main(argv: list[str] | None = None) -> int:
    _ = argv
    lines: list[str] = ["Music Fix Doctor", ""]

    for command in [
        "music-ai",
        "music-analyze",
        "music-artwork",
        "music-tags",
        "music-duplicates",
        "music-cache",
        "music-prefs",
    ]:
        path = command_path(command)
        lines.append(check(command, path != "not found", path))

    ok, detail = launch_agent_check()
    lines.append(check("Menu bar LaunchAgent", ok, detail))

    ok, detail = music_access_check()
    lines.append(check("Music automation", ok, detail))

    ok, detail = internet_check()
    lines.append(check("Internet", ok, detail))

    api_keys = [
        key
        for key in ["GOOGLE_API_KEY", "GOOGLE_CSE_ID", "DISCOGS_TOKEN", "LASTFM_API_KEY"]
        if os.environ.get(key)
    ]
    lines.append(check("Optional API keys", bool(api_keys), ", ".join(api_keys) if api_keys else "none set"))
    lines.append(check("Search cache", True, f"{cache_file_count()} file(s)"))
    lines.extend(["", "Preferences:", format_preferences()])

    output = "\n".join(lines)
    print(output)
    notify("Music Fix Doctor", "Diagnostics complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
