#!/usr/bin/env python3
"""Menu bar helper for music-artwork-finder."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from preferences import CONFIG_DIR, load_preferences

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
MUSIC_ANALYZE = SCRIPT_DIR / "music_analyze.py"
MUSIC_DOCTOR = SCRIPT_DIR / "music_doctor.py"
MUSIC_PREFS = SCRIPT_DIR / "music_prefs.py"
MUSIC_COMBINE = SCRIPT_DIR / "music_combine.py"
MUSIC_RESPLIT = SCRIPT_DIR / "music_resplit.py"
MUSIC_DUPLICATES = SCRIPT_DIR / "music_duplicates.py"
FIX_ALBUM = SCRIPT_DIR / "fix_album.py"
RESOLVE_SPLITS = SCRIPT_DIR / "resolve_splits.py"
UNDO_LAST = SCRIPT_DIR / "undo_last.py"
MUSIC_CACHE = SCRIPT_DIR / "music_cache.py"
MENUBAR_ICON = SCRIPT_DIR / "assets" / "menubar-template@2x.png"

COMMAND_HELP = {
    "AI All-in-One Fix": "Deep-resolve split albums, fix tags, find artwork, and apply confident changes with undo support.",
    "AI All-in-One Preview First": "Run the all-in-one workflow but ask before applying changes.",
    "AI All-in-One Dry Run": "Show what the all-in-one workflow would change without touching Music.",
    "Fix Tags and Artwork": "Use one MusicBrainz release match for both metadata and artwork.",
    "Find Artwork for Selected Album(s)": "Find and apply the best artwork match for selected album(s).",
    "Choose Artwork...": "Pick artwork manually from candidate matches.",
    "Preview Artwork Matches": "List artwork candidates without applying anything.",
    "Fix Tags for Selected Album(s)": "Apply MusicBrainz metadata to selected album(s).",
    "Choose Tags...": "Pick which release metadata to use.",
    "Preview Tag Matches": "List metadata candidates without applying anything.",
    "Resolve Split Album(s)": "Combine songs split across inconsistent album or artist tags.",
    "AI Deep Dive Resolve": "Resolve split albums with deeper track-title and release evidence.",
    "Smart Combine Main + Remix Album": "Combine related selected albums into a clean multi-disc album.",
    "Smart Combine: Choose Main...": "Choose which selected album becomes disc 1 before combining.",
    "Smart Combine with Main Artwork": "Combine and copy the main album artwork to moved tracks.",
    "Analyze and Resplit Album(s)": "Suggest splitting remix, bonus, or disc groups back into separate albums.",
    "Detect and Remove Duplicates": "Preview duplicate-looking tracks and same-title rename suggestions.",
    "Undo Last Metadata Change": "Restore the latest saved metadata or artwork snapshot.",
    "Open Last Fix Report": "Open the latest action report.",
    "Clear AI Search Cache": "Remove cached online lookup results.",
    "Fix Missing Artwork": "Batch-fix albums with missing artwork.",
    "Fix Tags in Library": "Batch-check metadata differences across the library.",
    "Analyze Library Now": "Run a full local, non-destructive library polish scan.",
    "Auto-Resolve Analysis Suggestions": "Apply only safe local analysis fixes after confirmation.",
    "Open Library Analysis Report": "Open the latest library analysis HTML report.",
    "Open Analysis Ignore List": "Open the file of analysis finding keys that should be hidden.",
    "Enable Background Analysis": "Allow periodic suggestions-only library scans.",
    "Disable Background Analysis": "Stop periodic library scans.",
    "Enable Auto-Resolve Suggestions": "Allow periodic safe local auto-resolve actions using saved categories.",
    "Disable Auto-Resolve Suggestions": "Stop periodic auto-resolve actions; analysis remains suggestions-only.",
    "Enable Analysis Notifications": "Allow background analysis to show suggestion notifications.",
    "Disable Analysis Notifications": "Suppress background analysis notifications.",
    "Preferences": "Show saved Music Fix defaults and background analysis settings.",
    "Run Setup Check": "Check installation, permissions, network, cache, and preferences.",
}


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
        self._analysis_running = False
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
            "Detect and Remove Duplicates",
            None,
            "Undo Last Metadata Change",
            "Open Last Fix Report",
            "Clear AI Search Cache",
            None,
            "Fix Missing Artwork",
            "Fix Tags in Library",
            None,
            "Analyze Library Now",
            "Auto-Resolve Analysis Suggestions",
            "Open Library Analysis Report",
            "Open Analysis Ignore List",
            "Enable Background Analysis",
            "Disable Background Analysis",
            "Enable Auto-Resolve Suggestions",
            "Disable Auto-Resolve Suggestions",
            "Enable Analysis Notifications",
            "Disable Analysis Notifications",
            None,
            "Preferences",
            "Run Setup Check",
            "Command Guide",
            "About",
        ]
        self.analysis_timer = rumps.Timer(self._background_analysis_tick, 900)
        self.analysis_timer.start()

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

    @rumps.clicked("Detect and Remove Duplicates")
    def detect_and_remove_duplicates(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_DUPLICATES, ["--fingerprint"], title="Duplicate removal")

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

    @rumps.clicked("Analyze Library Now")
    def analyze_library_now(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_ANALYZE, [], title="Library analysis")

    @rumps.clicked("Auto-Resolve Analysis Suggestions")
    def auto_resolve_analysis_suggestions(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_ANALYZE,
            ["--auto-resolve", "--apply"],
            title="Analysis auto-resolve",
        )

    @rumps.clicked("Open Library Analysis Report")
    def open_library_analysis_report(self, _: rumps.MenuItem) -> None:
        report_dir = Path.home() / ".music-artwork-finder" / "reports"
        report_path = report_dir / "latest-library-analysis.html"
        if not report_path.exists():
            report_path = report_dir / "latest-library-analysis.txt"
        if not report_path.exists():
            rumps.alert(title="Library Analysis", message="No library analysis report found.", ok="OK")
            return
        subprocess.run(["open", str(report_path)], check=False)

    @rumps.clicked("Open Analysis Ignore List")
    def open_analysis_ignore_list(self, _: rumps.MenuItem) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ignore_path = CONFIG_DIR / "analysis-ignore.txt"
        if not ignore_path.exists():
            ignore_path.write_text("", encoding="utf-8")
        subprocess.run(["open", str(ignore_path)], check=False)

    @rumps.clicked("Enable Background Analysis")
    def enable_background_analysis(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_PREFS,
            ["set", "background_analysis_enabled", "true"],
            title="Background analysis",
        )

    @rumps.clicked("Disable Background Analysis")
    def disable_background_analysis(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_PREFS,
            ["set", "background_analysis_enabled", "false"],
            title="Background analysis",
        )

    @rumps.clicked("Enable Auto-Resolve Suggestions")
    def enable_auto_resolve_suggestions(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_PREFS,
            ["set", "analysis_auto_resolve_enabled", "true"],
            title="Analysis auto-resolve",
        )

    @rumps.clicked("Disable Auto-Resolve Suggestions")
    def disable_auto_resolve_suggestions(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_PREFS,
            ["set", "analysis_auto_resolve_enabled", "false"],
            title="Analysis auto-resolve",
        )

    @rumps.clicked("Enable Analysis Notifications")
    def enable_analysis_notifications(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_PREFS,
            ["set", "background_analysis_notifications", "true"],
            title="Analysis notifications",
        )

    @rumps.clicked("Disable Analysis Notifications")
    def disable_analysis_notifications(self, _: rumps.MenuItem) -> None:
        self._run_script(
            MUSIC_PREFS,
            ["set", "background_analysis_notifications", "false"],
            title="Analysis notifications",
        )

    @rumps.clicked("Preferences")
    def preferences(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_PREFS, ["show"], title="Music Fix preferences")

    @rumps.clicked("Run Setup Check")
    def run_setup_check(self, _: rumps.MenuItem) -> None:
        self._run_script(MUSIC_DOCTOR, [], title="Music Fix setup check")

    @rumps.clicked("Command Guide")
    def command_guide(self, _: rumps.MenuItem) -> None:
        lines = ["Menu command guide", ""]
        for name, detail in COMMAND_HELP.items():
            lines.append(f"{name}: {detail}")
            lines.append("")
        rumps.alert(title="Music Fix Command Guide", message="\n".join(lines).strip(), ok="OK")

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

    def _background_analysis_tick(self, _: rumps.Timer) -> None:
        if self._analysis_running:
            return
        prefs = load_preferences()
        if not prefs.get("background_analysis_enabled", True):
            return
        interval_seconds = max(1, int(prefs.get("background_analysis_interval_hours", 24))) * 60 * 60
        last_run = float(prefs.get("background_analysis_last_run", 0.0))
        if time.time() - last_run < interval_seconds:
            return

        self._analysis_running = True
        thread = threading.Thread(target=self._run_background_analysis, daemon=True)
        thread.start()

    def _run_background_analysis(self) -> None:
        try:
            result = subprocess.run(
                [sys.executable, str(MUSIC_ANALYZE), "--background"],
                capture_output=True,
                text=True,
                check=False,
            )
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode != 0:
                return
            if output and not output.startswith("No Music Fix suggestions") and self._analysis_notifications_allowed():
                rumps.notification(
                    title="Music Fix suggestions",
                    subtitle="Library analysis",
                    message=output,
                )
        finally:
            self._analysis_running = False

    def _analysis_notifications_allowed(self) -> bool:
        prefs = load_preferences()
        if not prefs.get("background_analysis_notifications", True):
            return False
        start = int(prefs.get("background_analysis_quiet_start", 22)) % 24
        end = int(prefs.get("background_analysis_quiet_end", 8)) % 24
        hour = time.localtime().tm_hour
        if start == end:
            return True
        if start < end:
            return not (start <= hour < end)
        return not (hour >= start or hour < end)


if __name__ == "__main__":
    ArtworkMenuBarApp().run()
