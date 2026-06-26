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
MUSIC_AI = SCRIPT_DIR / "music_ai.py"
MUSIC_DOCTOR = SCRIPT_DIR / "music_doctor.py"
MUSIC_PREFS = SCRIPT_DIR / "music_prefs.py"
MUSIC_COMBINE = SCRIPT_DIR / "music_combine.py"
MUSIC_RESPLIT = SCRIPT_DIR / "music_resplit.py"
FIX_ALBUM = SCRIPT_DIR / "fix_album.py"
RESOLVE_SPLITS = SCRIPT_DIR / "resolve_splits.py"
UNDO_LAST = SCRIPT_DIR / "undo_last.py"
MUSIC_CACHE = SCRIPT_DIR / "music_cache.py"
MENUBAR_ICON = SCRIPT_DIR / "assets" / "menubar-template@2x.png"


class ArtworkMenuBarApp(rumps.App):
    def __init__(self) -> None:
        icon = str(MENUBAR_ICON) if MENUBAR_ICON.exists() else None
        super().__init__(
            "Music Fix",
            title=None if icon else "Music Fix",
            icon=icon,
            template=True,
            quit_button="Quit",
        )
        self.menu = [
            "AI All-in-One Fix",
            "AI All-in-One Preview First",
            "AI All-in-One Dry Run",
            None,
            "Fix Tags and Artwork",
            None,
            "Find Artwork for Selected Album(s)",
            "Choose Artwork...",
            "Preview Artwork Matches",
            None,
            "Fix Tags for Selected Album(s)",
            "Choose Tags...",
            "Preview Tag Matches",
            None,
            "Resolve Split Album(s)",
            "AI Deep Dive Resolve",
            "Smart Combine Main + Remix Album",
            "Smart Combine: Choose Main...",
            "Smart Combine with Main Artwork",
            "Analyze and Resplit Album(s)",
            None,
            "Undo Last Metadata Change",
            "Open Last Fix Report",
            "Clear AI Search Cache",
            None,
            "Fix Missing Artwork",
            "Fix Tags in Library",
            None,
            "Preferences",
            "Run Setup Check",
            "About",
        ]

    @rumps.clicked("AI All-in-One Fix")
    def ai_all_in_one_fix(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_AI, ["--auto-apply"], title="AI all-in-one fix")

    @rumps.clicked("AI All-in-One Preview First")
    def ai_all_in_one_preview(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_AI, ["--preview"], title="AI all-in-one preview")

    @rumps.clicked("AI All-in-One Dry Run")
    def ai_all_in_one_dry_run(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_AI, ["--dry-run"], title="AI all-in-one dry run")

    @rumps.clicked("Fix Tags and Artwork")
    def fix_tags_and_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(
            FIX_ALBUM,
            ["--resolve-splits", "--ai-deep-dive"],
            title="Album fix",
        )

    @rumps.clicked("Find Artwork for Selected Album(s)")
    def find_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_ARTWORK, [], title="Album artwork")

    @rumps.clicked("Choose Artwork...")
    def choose_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_ARTWORK, ["--pick"], title="Album artwork")

    @rumps.clicked("Preview Artwork Matches")
    def preview_artwork_matches(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_ARTWORK, ["--list-matches"], title="Artwork matches")

    @rumps.clicked("Fix Tags for Selected Album(s)")
    def fix_tags(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_TAGS, [], title="Music tags")

    @rumps.clicked("Choose Tags...")
    def choose_tags(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_TAGS, ["--pick"], title="Music tags")

    @rumps.clicked("Preview Tag Matches")
    def preview_tag_matches(self, _: rumps.MenuItem) -> None:
        self._run_script(FIND_TAGS, ["--list-matches"], title="Tag matches")

    @rumps.clicked("Resolve Split Album(s)")
    def resolve_splits(self, _: rumps.MenuItem) -> None:
        self._run_script(RESOLVE_SPLITS, [], title="Split album resolve")

    @rumps.clicked("AI Deep Dive Resolve")
    def ai_deep_dive_resolve(self, _: rumps.MenuItem) -> None:
        self._run_script(
            RESOLVE_SPLITS,
            ["--ai-deep-dive"],
            title="AI deep dive resolve",
        )

    @rumps.clicked("Smart Combine Main + Remix Album")
    def smart_combine_main_remix(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_COMBINE, [], title="Smart album combine")

    @rumps.clicked("Smart Combine: Choose Main...")
    def smart_combine_choose_main(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_COMBINE, ["--pick-main"], title="Smart album combine")

    @rumps.clicked("Smart Combine with Main Artwork")
    def smart_combine_with_artwork(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_COMBINE, ["--inherit-artwork"], title="Smart album combine")

    @rumps.clicked("Analyze and Resplit Album(s)")
    def analyze_and_resplit(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_RESPLIT, [], title="Album resplit")

    @rumps.clicked("Undo Last Metadata Change")
    def undo_last_change(self, _: rumps.MenuItem) -> None:
        preview = subprocess.run(
            [sys.executable, str(UNDO_LAST), "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        preview_text = (preview.stdout or preview.stderr or "").strip()
        response = rumps.alert(
            title="Undo Last Metadata Change",
            message=preview_text or "Restore the latest saved tags or artwork?",
            ok="Undo",
            cancel="Cancel",
        )
        if response == 1:
            self._run_script(UNDO_LAST, [], title="Music Fix undo")

    @rumps.clicked("Open Last Fix Report")
    def open_last_fix_report(self, _: rumps.MenuItem) -> None:
        report_dir = Path.home() / ".music-artwork-finder" / "reports"
        reports = sorted(report_dir.glob("*.txt")) if report_dir.exists() else []
        if not reports:
            rumps.alert(title="Fix Reports", message="No fix reports found.", ok="OK")
            return
        subprocess.run(["open", str(reports[-1])], check=False)

    @rumps.clicked("Clear AI Search Cache")
    def clear_ai_search_cache(self, _: rumps.MenuItem) -> None:
        response = rumps.alert(
            title="Clear AI Search Cache",
            message="Remove cached release, artwork, and tracklist search results?",
            ok="Clear Cache",
            cancel="Cancel",
        )
        if response == 1:
            self._run_script(MUSIC_CACHE, ["clear"], title="Music Fix cache")

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

    @rumps.clicked("Preferences")
    def preferences(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_PREFS, ["show"], title="Music Fix preferences")

    @rumps.clicked("Run Setup Check")
    def run_setup_check(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_DOCTOR, [], title="Music Fix setup check")

    @rumps.clicked("About")
    def about(self, _: rumps.MenuItem) -> None:
        rumps.alert(
            title="Music Fix",
            message=(
                "Select album/albums or songs in Music, then choose an action.\n\n"
                "Fix Tags and Artwork can auto-resolve split album(s) with AI-style "
                "deep evidence scoring, uses one MusicBrainz match for both steps, "
                "auto-applies confident changes, saves undo history, and re-embeds artwork into files."
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
