#!/usr/bin/env python3
"""Menu bar helper for music-artwork-finder."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    import rumps
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: rumps\n"
        "Install with: python3 -m pip install -r requirements.txt"
    ) from exc

SCRIPT_DIR = Path(__file__).resolve().parent
FIND_ARTWORK = SCRIPT_DIR / "find_artwork.py"
FIND_TAGS = SCRIPT_DIR / "find_tags.py"
FIX_ALBUM = SCRIPT_DIR / "fix_album.py"


class ArtworkMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Music Fix", quit_button="Quit")
        self.menu = [
            "Fix Tags and Artwork",
            None,
            "Find Artwork for Selected Album",
            "Choose Artwork...",
            "Preview Artwork Matches",
            None,
            "Fix Tags for Selected Album",
            "Choose Tags...",
            "Preview Tag Matches",
            None,
            "Fix Missing Artwork",
            "Fix Tags in Library",
            None,
            "About",
        ]

    @rumps.clicked("Fix Tags and Artwork")
    def fix_tags_and_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(FIX_ALBUM, ["--preview"], title="Album fix")

    @rumps.clicked("Find Artwork for Selected Album")
    def find_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_ARTWORK, ["--preview"], title="Album artwork")

    @rumps.clicked("Choose Artwork...")
    def choose_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_ARTWORK, ["--pick"], title="Album artwork")

    @rumps.clicked("Preview Artwork Matches")
    def preview_artwork_matches(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_ARTWORK, ["--list-matches"], title="Artwork matches")

    @rumps.clicked("Fix Tags for Selected Album")
    def fix_tags(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_TAGS, ["--preview"], title="Music tags")

    @rumps.clicked("Choose Tags...")
    def choose_tags(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_TAGS, ["--pick"], title="Music tags")

    @rumps.clicked("Preview Tag Matches")
    def preview_tag_matches(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_TAGS, ["--list-matches"], title="Tag matches")

    @rumps.clicked("Fix Missing Artwork")
    def fix_missing(self, _: rumps.MenuItem) -> None:
        response = rumps.alert(
            title="Fix Missing Artwork",
            message=(
                "Search your Music library for albums missing artwork and "
                "apply the best match to each one.\n\n"
                "This run processes up to 20 albums and skips tracks that "
                "already have artwork."
            ),
            ok="Start",
            cancel="Cancel",
        )
        if response == 1:
            self._run_script(
                FIND_ARTWORK,
                ["--batch-missing", "--skip-if-artwork-exists", "--limit", "20"],
                title="Batch artwork update",
            )

    @rumps.clicked("Fix Tags in Library")
    def fix_tags_batch(self, _: rumps.MenuItem) -> None:
        response = rumps.alert(
            title="Fix Tags in Library",
            message=(
                "Scan your Music library and fix tags for albums that differ "
                "from online metadata.\n\n"
                "This run processes up to 20 albums and skips albums that are "
                "already correct."
            ),
            ok="Start",
            cancel="Cancel",
        )
        if response == 1:
            self._run_script(
                FIND_TAGS,
                ["--batch", "--limit", "20"],
                title="Batch tag update",
            )

    @rumps.clicked("About")
    def about(self, _: rumps.MenuItem) -> None:
        rumps.alert(
            title="Music Fix",
            message=(
                "Select an album or tracks in Music, then choose an action.\n\n"
                "Fix Tags and Artwork uses one MusicBrainz match for both steps, "
                "shows a preview before applying, and re-embeds artwork into files."
            ),
            ok="OK",
        )

    def _run_script(
        self,
        script_path: Path,
        extra_args: list[str],
        title: str,
    ) -> None:
        rumps.notification(title=title, subtitle="Working", message="Processing selection...")
        result = subprocess.run(
            [sys.executable, str(script_path), *extra_args],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            summary = output.splitlines()[0] if output else "Done"
            rumps.notification(title=title, subtitle="Success", message=summary)
            if len(output.splitlines()) > 1:
                rumps.alert(title=title, message=output, ok="OK")
        else:
            rumps.alert(title=f"{title} failed", message=output or "Unknown error", ok="OK")


if __name__ == "__main__":
    ArtworkMenuBarApp().run()
