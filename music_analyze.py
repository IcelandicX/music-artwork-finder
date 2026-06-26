#!/usr/bin/env python3
"""Local background analysis for Music Fix suggestions."""

from __future__ import annotations

import argparse
import html
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from find_artwork import get_albums_missing_artwork, music_app_name, normalize, notify, run_osascript
from find_tags import FIELD_SEP, TagChange, TrackSnapshot, TrackTags, apply_tag_changes
from music_common import confirm_apply
from music_duplicates import build_rename_groups, find_duplicate_groups, remove_duplicate_tracks
from music_resplit import infer_groups
from preferences import CONFIG_DIR, load_preferences, save_preferences
from resolve_splits import find_split_groups, get_all_library_tracks
from run_report import REPORT_DIR

IGNORE_PATH = CONFIG_DIR / "analysis-ignore.txt"
CATEGORIES = ("Artwork", "Duplicates", "Split Albums", "Metadata", "Organization")


@dataclass(frozen=True)
class Issue:
    category: str
    title: str
    detail: str
    action: str
    key: str


def album_key(track: TrackSnapshot) -> tuple[str, str]:
    return (normalize(track.album_artist or track.artist), normalize(track.album))


def issue_key(category: str, title: str) -> str:
    return f"{normalize(category).replace(' ', '-')}/{normalize(title).replace(' ', '-')}"


def make_issue(category: str, title: str, detail: str, action: str) -> Issue:
    return Issue(category, title, detail, action, issue_key(category, title))


def load_ignore_list() -> set[str]:
    if not IGNORE_PATH.exists():
        return set()
    return {
        line.strip()
        for line in IGNORE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def save_ignore_list(keys: set[str]) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    IGNORE_PATH.write_text("\n".join(sorted(keys)) + ("\n" if keys else ""), encoding="utf-8")
    return IGNORE_PATH


def add_ignore_key(key: str) -> Path:
    keys = load_ignore_list()
    keys.add(key)
    return save_ignore_list(keys)


def clear_ignore_list() -> Path:
    return save_ignore_list(set())


def count_missing_metadata(tracks: list[TrackSnapshot]) -> list[Issue]:
    missing_album_artist = sum(1 for track in tracks if not track.album_artist)
    missing_track_number = sum(1 for track in tracks if not track.track_number)
    missing_year = sum(1 for track in tracks if not track.year)
    issues: list[Issue] = []
    if missing_album_artist:
        issues.append(
            make_issue(
                "Metadata",
                "Album artist consistency",
                f"{missing_album_artist} track(s) are missing album artist, which can fragment polished album views.",
                "Run music-tags --preview on affected albums.",
            )
        )
    if missing_track_number:
        issues.append(
            make_issue(
                "Metadata",
                "Track order consistency",
                f"{missing_track_number} track(s) are missing track numbers, which can break intended album sequencing.",
                "Run music-tags --preview on affected albums.",
            )
        )
    if missing_year:
        issues.append(
            make_issue(
                "Metadata",
                "Release year consistency",
                f"{missing_year} track(s) are missing year metadata.",
                "Run music-tags --preview on affected albums.",
            )
        )
    return issues


def artwork_presence_issues(app_name: str) -> list[Issue]:
    script = f'''
tell application "{app_name}"
    set output to {{}}
    repeat with t in (every track of library playlist 1)
        try
            set albumName to album of t
            set artistName to album artist of t
            if artistName is missing value or artistName is "" then
                set artistName to artist of t
            end if
            if albumName is not missing value and albumName is not "" and artistName is not missing value and artistName is not "" then
                set hasArtwork to "0"
                if (count of artwork of t) > 0 then
                    set hasArtwork to "1"
                end if
                set end of output to artistName & "{FIELD_SEP}" & albumName & "{FIELD_SEP}" & hasArtwork
            end if
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    album_presence: dict[tuple[str, str], set[str]] = defaultdict(set)
    for line in payload.splitlines():
        parts = line.split(FIELD_SEP)
        if len(parts) != 3:
            continue
        artist, album, has_artwork = parts
        album_presence[(normalize(artist), normalize(album))].add(has_artwork)

    mixed_albums = sum(1 for states in album_presence.values() if states == {"0", "1"})
    if not mixed_albums:
        return []
    return [
        make_issue(
            "Artwork",
            "Artwork consistency",
            f"{mixed_albums} album(s) have a mix of tracks with and without artwork.",
            "Run music-artwork --preview on affected albums or use Fix Missing Artwork.",
        )
    ]


def analyze_tracks(
    tracks: list[TrackSnapshot],
    missing_artwork_count: int,
    artwork_issues: list[Issue],
) -> list[Issue]:
    issues: list[Issue] = []

    duplicate_groups = find_duplicate_groups(
        tracks,
        ignore_album=False,
        fingerprint=True,
        ignore_position=False,
    )
    if duplicate_groups:
        duplicate_count = sum(len(group.duplicates) for group in duplicate_groups)
        issues.append(
            make_issue(
                "Duplicates",
                "Duplicate-looking tracks",
                f"{duplicate_count} removable duplicate track(s) in {len(duplicate_groups)} group(s) may be cluttering the library.",
                "Run music-duplicates --library --fingerprint --dry-run.",
            )
        )

    rename_groups = build_rename_groups(tracks, duplicate_groups, ignore_album=False)
    if rename_groups:
        rename_count = sum(len(group.changes) for group in rename_groups)
        issues.append(
            make_issue(
                "Duplicates",
                "Same-name tracks need disambiguation",
                f"{rename_count} non-identical same-title track(s) can be renamed for clearer browsing.",
                "Run music-duplicates --library --fingerprint --dry-run.",
            )
        )

    split_groups = find_split_groups(tracks)
    if split_groups:
        issues.append(
            make_issue(
                "Split Albums",
                "Possible split albums",
                f"{len(split_groups)} group(s) look like albums split across inconsistent tags.",
                "Run music-splits --library --dry-run.",
            )
        )

    by_album: dict[tuple[str, str], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        by_album[album_key(track)].append(track)
    resplit_candidates = 0
    for album_tracks in by_album.values():
        if infer_groups(album_tracks, remix_album=None, bonus_album=None, include_disc_groups=False):
            resplit_candidates += 1
    if resplit_candidates:
        issues.append(
            make_issue(
                "Organization",
                "Possible combined albums to resplit",
                f"{resplit_candidates} album(s) contain remix, bonus, or disc groups worth reviewing.",
                "Run music-resplit --dry-run on selected albums.",
            )
        )

    if missing_artwork_count:
        issues.append(
            make_issue(
                "Artwork",
                "Artwork completeness",
                f"{missing_artwork_count} album(s) have at least one track missing artwork, which hurts the visual library experience.",
                "Run music-artwork --batch-missing --limit 20.",
            )
        )

    issues.extend(artwork_issues)
    issues.extend(count_missing_metadata(tracks))
    return issues


def health_scores(issues: list[Issue]) -> dict[str, int]:
    counts = Counter(issue.category for issue in issues)
    scores: dict[str, int] = {}
    for category in CATEGORIES:
        penalty = min(60, counts.get(category, 0) * 15)
        scores[category] = max(40, 100 - penalty)
    if not issues:
        overall = 100
    else:
        overall = round(sum(scores.values()) / len(scores))
    return {"Overall": overall, **scores}


def suggested_actions(issues: list[Issue]) -> list[str]:
    seen: set[str] = set()
    actions: list[str] = []
    for issue in issues:
        if issue.action in seen:
            continue
        seen.add(issue.action)
        actions.append(issue.action)
    return actions


def filter_ignored_issues(issues: list[Issue], ignored: set[str]) -> tuple[list[Issue], int]:
    kept = [issue for issue in issues if issue.key not in ignored]
    return kept, len(issues) - len(kept)


def format_report(
    issues: list[Issue],
    track_count: int,
    album_count: int,
    ignored_count: int,
) -> str:
    scores = health_scores(issues)
    lines = [
        "Music Fix Library Analysis",
        "Goal: keep Apple Music looking sleek, with high-quality artwork and artist-intended album organization.",
        f"Scanned: {track_count} track(s), {album_count} album(s)",
        f"Issues found: {len(issues)}",
        f"Ignored findings hidden: {ignored_count}",
        f"Library Health Score: {scores['Overall']}/100",
        "Mode: suggestions only; nothing was changed.",
        "",
        "Health categories:",
    ]
    for category in CATEGORIES:
        lines.append(f"- {category}: {scores[category]}/100")
    lines.append("")
    lines.extend(
        [
            "Artwork quality notes:",
            "- Missing and mixed artwork are checked locally.",
            "- Low-resolution and non-square artwork checks require exporting image data, so they are left to preview-first artwork tools.",
            "",
        ]
    )
    lines.append(f"Ignore list: {IGNORE_PATH}")
    lines.append("To ignore a finding: music-analyze --ignore <key>")
    lines.append("")
    if issues:
        lines.append("Suggested actions:")
        for action in suggested_actions(issues):
            lines.append(f"- {action}")
        lines.append("")
 
    if not issues:
        lines.append("No local metadata issues found. The library looks clean from this local scan.")
        return "\n".join(lines)

    category_counts = Counter(issue.category for issue in issues)
    lines.append("Summary:")
    for category, count in sorted(category_counts.items()):
        lines.append(f"- {category}: {count}")
    lines.append("")
    for issue in issues:
        lines.extend(
            [
                f"{issue.category}: {issue.title} [{issue.key}]",
                f"  {issue.detail}",
                f"  Preview-first suggestion: {issue.action}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def format_html_report(report: str, issues: list[Issue], track_count: int, album_count: int, ignored_count: int) -> str:
    scores = health_scores(issues)
    issue_items = "\n".join(
        f"<li><strong>{html.escape(issue.category)}: {html.escape(issue.title)}</strong> "
        f"<code>{html.escape(issue.key)}</code><br>{html.escape(issue.detail)}"
        f"<br><em>{html.escape(issue.action)}</em></li>"
        for issue in issues
    )
    action_items = "\n".join(f"<li>{html.escape(action)}</li>" for action in suggested_actions(issues))
    score_cards = "\n".join(
        f"<div class='card'><span>{html.escape(category)}</span><strong>{score}/100</strong></div>"
        for category, score in scores.items()
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Music Fix Library Analysis</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2933; background: #f7f8fb; }}
    h1 {{ margin-bottom: 0; }}
    .subtitle {{ color: #65758b; margin-top: 6px; }}
    .scores {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 24px 0; }}
    .card {{ background: white; border-radius: 14px; padding: 16px; box-shadow: 0 1px 8px rgba(15, 23, 42, .08); }}
    .card span {{ display: block; color: #65758b; font-size: 13px; }}
    .card strong {{ font-size: 26px; }}
    section {{ background: white; border-radius: 14px; padding: 18px 22px; margin: 18px 0; box-shadow: 0 1px 8px rgba(15, 23, 42, .08); }}
    code {{ background: #edf2f7; padding: 2px 5px; border-radius: 5px; }}
    li {{ margin: 10px 0; }}
    pre {{ white-space: pre-wrap; background: #111827; color: #f9fafb; padding: 18px; border-radius: 12px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Music Fix Library Analysis</h1>
  <p class="subtitle">A local, non-destructive polish scan for artwork, organization, duplicates, and metadata.</p>
  <p>Scanned {track_count} track(s), {album_count} album(s). Ignored findings hidden: {ignored_count}.</p>
  <div class="scores">{score_cards}</div>
  <section>
    <h2>Suggested Actions</h2>
    <ul>{action_items or "<li>No actions needed.</li>"}</ul>
  </section>
  <section>
    <h2>Findings</h2>
    <ul>{issue_items or "<li>No local metadata issues found.</li>"}</ul>
  </section>
  <section>
    <h2>Artwork Quality Notes</h2>
    <p>Missing and mixed artwork are checked locally. Low-resolution and non-square checks are intentionally left to preview-first artwork tools because checking those requires exporting image data.</p>
  </section>
  <section>
    <h2>Text Report</h2>
    <pre>{html.escape(report)}</pre>
  </section>
</body>
</html>
"""


def save_analysis_report(report: str, html_report: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text_path = REPORT_DIR / "latest-library-analysis.txt"
    html_path = REPORT_DIR / "latest-library-analysis.html"
    text_path.write_text(report + "\n", encoding="utf-8")
    html_path.write_text(html_report, encoding="utf-8")
    return text_path, html_path


def update_last_run() -> None:
    prefs = load_preferences()
    prefs["background_analysis_last_run"] = time.time()
    save_preferences(prefs)


def in_quiet_hours(prefs: dict) -> bool:
    start = int(prefs.get("background_analysis_quiet_start", 22)) % 24
    end = int(prefs.get("background_analysis_quiet_end", 8)) % 24
    hour = time.localtime().tm_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def should_notify(args: argparse.Namespace, prefs: dict) -> bool:
    if args.no_notify:
        return False
    if not prefs.get("background_analysis_notifications", True):
        return False
    if args.background and in_quiet_hours(prefs):
        return False
    return True


def configured_categories(prefs: dict) -> set[str]:
    raw = str(prefs.get("analysis_auto_resolve_categories", "")).casefold()
    return {item.strip() for item in raw.split(",") if item.strip()}


def auto_resolve_due(prefs: dict) -> bool:
    interval = max(1, int(prefs.get("analysis_auto_resolve_interval_hours", 24))) * 60 * 60
    last_run = float(prefs.get("analysis_auto_resolve_last_run", 0.0))
    return time.time() - last_run >= interval


def update_auto_resolve_last_run() -> None:
    prefs = load_preferences()
    prefs["analysis_auto_resolve_last_run"] = time.time()
    save_preferences(prefs)


def build_album_artist_changes(tracks: list[TrackSnapshot]) -> list[TagChange]:
    by_album: dict[tuple[str, str], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        by_album[album_key(track)].append(track)

    changes: list[TagChange] = []
    for album_tracks in by_album.values():
        album_artists = [track.album_artist for track in album_tracks if track.album_artist]
        if not album_artists:
            continue
        target_album_artist = Counter(album_artists).most_common(1)[0][0]
        for track in album_tracks:
            if track.album_artist:
                continue
            changes.append(
                TagChange(
                    track_id=track.track_id,
                    before=track,
                    after=TrackTags(
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        album_artist=target_album_artist,
                        track_number=track.track_number,
                        disc_number=track.disc_number,
                        year=track.year,
                        genre=track.genre,
                    ),
                )
            )
    return changes


def copy_existing_album_artwork_to_missing(app_name: str) -> int:
    script = f'''
tell application "{app_name}"
    set updatedCount to 0
    set seenAlbums to {{}}
    repeat with sourceTrack in (every track of library playlist 1)
        try
            if (count of artwork of sourceTrack) > 0 then
                set albumName to album of sourceTrack
                set artistName to album artist of sourceTrack
                if artistName is missing value or artistName is "" then
                    set artistName to artist of sourceTrack
                end if
                if albumName is not missing value and albumName is not "" and artistName is not missing value and artistName is not "" then
                    set albumKey to artistName & "{FIELD_SEP}" & albumName
                    if seenAlbums does not contain albumKey then
                        set end of seenAlbums to albumKey
                        set artworkData to data of artwork 1 of sourceTrack
                        set albumTracks to (every track of library playlist 1 whose album is albumName)
                        repeat with targetTrack in albumTracks
                            try
                                set targetArtist to album artist of targetTrack
                                if targetArtist is missing value or targetArtist is "" then
                                    set targetArtist to artist of targetTrack
                                end if
                                if targetArtist is artistName and (count of artwork of targetTrack) is 0 then
                                    try
                                        set data of artwork 1 of targetTrack to artworkData
                                    on error
                                        set data of artwork of targetTrack to artworkData
                                    end try
                                    set updatedCount to updatedCount + 1
                                end if
                            end try
                        end repeat
                    end if
                end if
            end if
        end try
    end repeat
    return updatedCount as string
end tell
'''
    return int(run_osascript(script))


def auto_resolve_plan(
    tracks: list[TrackSnapshot],
    categories: set[str],
) -> tuple[list[TagChange], list[object], list[str]]:
    messages: list[str] = []
    tag_changes: list[TagChange] = []
    duplicate_groups: list[object] = []

    if "metadata" in categories:
        metadata_changes = build_album_artist_changes(tracks)
        tag_changes.extend(metadata_changes)
        if metadata_changes:
            messages.append(f"Fill missing album artist on {len(metadata_changes)} track(s).")

    strict_duplicate_groups = find_duplicate_groups(
        tracks,
        ignore_album=False,
        fingerprint=True,
        ignore_position=False,
    )
    if "renames" in categories:
        rename_groups = build_rename_groups(tracks, strict_duplicate_groups, ignore_album=False)
        rename_changes = [change for group in rename_groups for change in group.changes]
        tag_changes.extend(rename_changes)
        if rename_changes:
            messages.append(f"Rename {len(rename_changes)} non-identical same-title track(s).")

    if "duplicates" in categories:
        duplicate_groups = strict_duplicate_groups
        duplicate_count = sum(len(group.duplicates) for group in duplicate_groups)
        if duplicate_count:
            messages.append(f"Remove {duplicate_count} strict fingerprint duplicate track(s).")

    if "artwork" in categories:
        messages.append("Copy existing album artwork to tracks missing artwork within the same album.")

    return tag_changes, duplicate_groups, messages


def format_auto_resolve_plan(messages: list[str], tag_changes: list[TagChange], duplicate_groups: list[object]) -> str:
    duplicate_count = sum(len(group.duplicates) for group in duplicate_groups)
    lines = [
        "Auto-Resolve Analysis Suggestions",
        "Only conservative local fixes are included. No online searches will run.",
        "",
        "Planned actions:",
    ]
    if messages:
        lines.extend(f"- {message}" for message in messages)
    else:
        lines.append("- No safe auto-resolve actions found.")
    lines.extend(["", f"Metadata/title changes: {len(tag_changes)}"])
    for change in tag_changes[:12]:
        lines.append(f"- {change.before.artist} - {change.before.album} - {change.before.title}")
    if len(tag_changes) > 12:
        lines.append(f"... and {len(tag_changes) - 12} more metadata/title change(s)")
    lines.extend(["", f"Duplicate removals: {duplicate_count}"])
    for group in duplicate_groups[:8]:
        lines.append(f"- Keep {group.keeper.title}; remove {len(group.duplicates)} duplicate(s)")
    if len(duplicate_groups) > 8:
        lines.append(f"... and {len(duplicate_groups) - 8} more duplicate group(s)")
    return "\n".join(lines)


def run_auto_resolve(
    app_name: str,
    tracks: list[TrackSnapshot],
    prefs: dict,
    apply: bool,
    assume_yes: bool,
    background: bool,
) -> tuple[str, int]:
    categories = configured_categories(prefs)
    tag_changes, duplicate_groups, messages = auto_resolve_plan(tracks, categories)
    plan = format_auto_resolve_plan(messages, tag_changes, duplicate_groups)
    if not apply:
        return plan, 0

    has_artwork = "artwork" in categories
    has_duplicates = bool(duplicate_groups)
    has_changes = bool(tag_changes) or has_duplicates or has_artwork
    if not has_changes:
        update_auto_resolve_last_run()
        return plan + "\n\nNo safe auto-resolve actions found.", 0

    if not background and not assume_yes and not confirm_apply("Auto-Resolve Analysis Suggestions", plan):
        raise RuntimeError("Auto-resolve cancelled.")

    group_id = f"analysis-auto-resolve-{uuid.uuid4()}"
    changed = 0
    if tag_changes:
        changed += apply_tag_changes(
            app_name,
            tag_changes,
            undo_action="analysis auto-resolve metadata",
            undo_group_id=group_id,
        )
    if duplicate_groups:
        duplicates = [track for group in duplicate_groups for track in group.duplicates]
        changed += remove_duplicate_tracks(app_name, duplicates)
    artwork_changed = 0
    if has_artwork:
        artwork_changed = copy_existing_album_artwork_to_missing(app_name)
        changed += artwork_changed
    update_auto_resolve_last_run()
    summary = f"Applied {changed} auto-resolve change(s)."
    if artwork_changed:
        summary += f" Artwork copied to {artwork_changed} track(s)."
    return plan + "\n\n" + summary, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze the Music library locally and suggest fixes.")
    parser.add_argument("--background", action="store_true", help="Background mode: concise output for menu bar checks.")
    parser.add_argument("--no-notify", action="store_true", help="Do not show a macOS notification.")
    parser.add_argument("--auto-resolve", action="store_true", help="Preview safe auto-resolve actions from analysis suggestions.")
    parser.add_argument("--apply", action="store_true", help="Apply safe auto-resolve actions. Requires confirmation unless --yes or background preference is enabled.")
    parser.add_argument("--yes", action="store_true", help="Apply auto-resolve without confirmation.")
    parser.add_argument("--ignore", metavar="KEY", help="Add an analysis finding key to the ignore list.")
    parser.add_argument("--list-ignored", action="store_true", help="List ignored analysis finding keys.")
    parser.add_argument("--clear-ignored", action="store_true", help="Clear ignored analysis finding keys.")
    args = parser.parse_args(argv)

    try:
        if args.ignore:
            path = add_ignore_key(args.ignore)
            print(f"Ignored analysis key {args.ignore}. Ignore list: {path}")
            return 0
        if args.list_ignored:
            ignored = sorted(load_ignore_list())
            if ignored:
                print("\n".join(ignored))
            else:
                print("No ignored analysis findings.")
            return 0
        if args.clear_ignored:
            path = clear_ignore_list()
            print(f"Cleared analysis ignore list: {path}")
            return 0

        prefs = load_preferences()
        app_name = music_app_name()
        tracks = get_all_library_tracks(app_name)
        album_count = len({album_key(track) for track in tracks})
        missing_artwork = len(get_albums_missing_artwork(app_name))
        issues = analyze_tracks(
            tracks,
            missing_artwork_count=missing_artwork,
            artwork_issues=artwork_presence_issues(app_name),
        )
        issues, ignored_count = filter_ignored_issues(issues, load_ignore_list())
        report = format_report(
            issues,
            track_count=len(tracks),
            album_count=album_count,
            ignored_count=ignored_count,
        )
        html_report = format_html_report(report, issues, len(tracks), album_count, ignored_count)
        report_path, html_path = save_analysis_report(report, html_report)
        update_last_run()

        auto_resolve_output = ""
        wants_manual_auto_resolve = args.auto_resolve or args.apply
        wants_background_auto_resolve = (
            args.background
            and bool(prefs.get("analysis_auto_resolve_enabled", False))
            and auto_resolve_due(prefs)
            and not in_quiet_hours(prefs)
        )
        if wants_manual_auto_resolve or wants_background_auto_resolve:
            auto_resolve_output, applied_count = run_auto_resolve(
                app_name,
                tracks,
                prefs,
                apply=args.apply or wants_background_auto_resolve,
                assume_yes=args.yes,
                background=wants_background_auto_resolve,
            )
            mode_line = (
                "Mode: analysis plus auto-resolve; safe local changes may have been applied."
                if applied_count
                else "Mode: analysis plus auto-resolve preview; nothing was changed."
            )
            report = report.replace("Mode: suggestions only; nothing was changed.", mode_line)
            report = report + "\n\n" + auto_resolve_output
            html_report = format_html_report(report, issues, len(tracks), album_count, ignored_count)
            report_path, html_path = save_analysis_report(report, html_report)
            if applied_count and should_notify(args, prefs):
                notify("Music Fix auto-resolve", f"Applied {applied_count} safe local change(s).")

        if issues:
            score = health_scores(issues)["Overall"]
            message = f"Health {score}/100. Found {len(issues)} suggestion(s). Report: {html_path}"
            if args.background:
                if auto_resolve_output:
                    print(message + " Auto-resolve checked.")
                else:
                    print(message)
            else:
                print(report)
                print(f"\nReport: {report_path}")
                print(f"HTML Report: {html_path}")
            if should_notify(args, prefs):
                notify("Music Fix suggestions", message)
        else:
            if args.background:
                if auto_resolve_output:
                    print("No Music Fix suggestions found. Auto-resolve checked.")
                else:
                    print("No Music Fix suggestions found.")
            else:
                print(report)
                print(f"\nReport: {report_path}")
                print(f"HTML Report: {html_path}")
            if should_notify(args, prefs):
                notify("Music Fix analysis", "No local metadata issues found.")
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        if not args.no_notify:
            notify("Music Fix analysis failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
