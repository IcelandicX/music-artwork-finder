#!/usr/bin/env python3
"""Search for correct Music tags and apply them to the current selection."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from dataclasses import dataclass

from find_artwork import (
    AlbumInfo,
    get_selected_album,
    music_app_name,
    normalize,
    notify,
    run_osascript,
    search_itunes,
    token_overlap,
)
from music_common import (
    ReleaseMatch,
    choose_release_match,
    confirm_apply,
    get_all_library_albums,
    release_artist_name,
    search_all_releases,
)
from search_cache import load_cache, save_cache
from undo_history import save_undo_snapshot


from find_artwork import fetch_musicbrainz_json

MUSICBRAINZ_RELEASE_URL = "https://musicbrainz.org/ws/2/release"
FIELD_SEP = "|||"
RECORD_SEP = "\n"


@dataclass(frozen=True)
class TrackSnapshot:
    track_id: int
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str


@dataclass(frozen=True)
class TrackTags:
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None


@dataclass(frozen=True)
class TagChange:
    track_id: int
    before: TrackSnapshot
    after: TrackTags


def applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_optional_int(value: str) -> int | None:
    value = value.strip()
    if not value or value.lower() in {"missing value", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_track_line(line: str) -> TrackSnapshot:
    parts = line.split(FIELD_SEP)
    if len(parts) != 9:
        raise RuntimeError(f"Unexpected track metadata format: {line!r}")
    return TrackSnapshot(
        track_id=int(parts[0]),
        title=parts[1],
        artist=parts[2],
        album=parts[3],
        album_artist=parts[4],
        track_number=parse_optional_int(parts[5]),
        disc_number=parse_optional_int(parts[6]),
        year=parse_optional_int(parts[7]),
        genre=parts[8],
    )


def serialize_track_line(track: TrackSnapshot) -> str:
    def field(value: int | None) -> str:
        return "" if value is None else str(value)

    return FIELD_SEP.join(
        [
            str(track.track_id),
            track.title,
            track.artist,
            track.album,
            track.album_artist,
            field(track.track_number),
            field(track.disc_number),
            field(track.year),
            track.genre,
        ]
    )


def get_target_tracks(app_name: str, entire_album: bool) -> list[TrackSnapshot]:
    script = f'''
tell application "{app_name}"
    set selectedItems to selection
    if (count of selectedItems) is 0 then
        try
            tell front browser window
                set selectedItems to selection
            end tell
        end try
    end if
    if (count of selectedItems) is 0 then
        try
            set selectedItems to {{current track}}
        end try
    end if
    if (count of selectedItems) is 0 then
        error "No album(s) or song(s) selected. Select album/albums or songs in Music, or start playing a song, then run this again."
    end if

    set targetTracks to selectedItems
    if {str(entire_album).lower()} is true then
        set firstItem to item 1 of selectedItems
        set itemClass to class of firstItem as string
        set albumName to missing value
        set artistName to missing value
        if itemClass contains "track" then
            set albumName to album of firstItem
            set artistName to artist of firstItem
        else
            try
                set albumName to name of firstItem
                set artistName to artist of firstItem
            end try
            if albumName is missing value or artistName is missing value then
                set albumName to album of firstItem
                set artistName to artist of firstItem
            end if
        end if
        set targetTracks to (every track of library playlist 1 whose album is albumName and artist is artistName)
    end if

    if (count of targetTracks) is 0 then
        error "No tracks found to update."
    end if

    set output to {{}}
    repeat with t in targetTracks
        set albumArtistName to album artist of t
        if albumArtistName is missing value then
            set albumArtistName to ""
        end if
        set genreName to genre of t
        if genreName is missing value then
            set genreName to ""
        end if
        set lineText to (id of t as string) & "{FIELD_SEP}" & (name of t) & "{FIELD_SEP}" & (artist of t) & "{FIELD_SEP}" & (album of t) & "{FIELD_SEP}" & albumArtistName & "{FIELD_SEP}" & (track number of t as string) & "{FIELD_SEP}" & (disc number of t as string) & "{FIELD_SEP}" & (year of t as string) & "{FIELD_SEP}" & genreName
        set end of output to lineText
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    if not payload:
        return []
    return [parse_track_line(line) for line in payload.splitlines() if line.strip()]


def get_tracks_by_ids(app_name: str, track_ids: list[int]) -> list[TrackSnapshot]:
    if not track_ids:
        return []

    id_list = ", ".join(str(track_id) for track_id in track_ids)
    script = f'''
tell application "{app_name}"
    set targetTracks to {{}}
    repeat with trackId in {{{id_list}}}
        try
            set end of targetTracks to (first track of library playlist 1 whose id is trackId)
        end try
    end repeat
    if (count of targetTracks) is 0 then
        error "No tracks found to update."
    end if
    set output to {{}}
    repeat with t in targetTracks
        set albumArtistName to album artist of t
        if albumArtistName is missing value then
            set albumArtistName to ""
        end if
        set genreName to genre of t
        if genreName is missing value then
            set genreName to ""
        end if
        set lineText to (id of t as string) & "{FIELD_SEP}" & (name of t) & "{FIELD_SEP}" & (artist of t) & "{FIELD_SEP}" & (album of t) & "{FIELD_SEP}" & albumArtistName & "{FIELD_SEP}" & (track number of t as string) & "{FIELD_SEP}" & (disc number of t as string) & "{FIELD_SEP}" & (year of t as string) & "{FIELD_SEP}" & genreName
        set end of output to lineText
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    if not payload:
        return []
    return [parse_track_line(line) for line in payload.splitlines() if line.strip()]


def clean_track_title(title: str) -> str:
    cleaned = re.sub(
        r"\s*[\(\[\{][^\)\]\}]*(live|remix|mix|version|edit|mono|stereo|acoustic)[^\)\]\}]*[\)\]\}]",
        "",
        title,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*-\s*(live|remix|mix|edit|version)$", "", cleaned, flags=re.IGNORECASE)
    return normalize(cleaned)


def title_match_score(left: str, right: str) -> float:
    direct = token_overlap(left, right)
    cleaned = token_overlap(clean_track_title(left), clean_track_title(right))
    return max(direct, cleaned)


def release_year(date_value: str) -> int | None:
    if not date_value:
        return None
    match = re.match(r"(\d{4})", date_value)
    if not match:
        return None
    return int(match.group(1))


def lookup_itunes_genre(artist: str, album: str) -> str | None:
    probe = AlbumInfo(artist=artist, album=album, app_name="Music")
    matches = search_itunes(probe, limit=5)
    if not matches:
        return None
    params = urllib.parse.urlencode(
        {
            "term": f"{artist} {album}",
            "entity": "album",
            "limit": 5,
            "media": "music",
        }
    )
    try:
        from find_artwork import fetch_json

        payload = fetch_json(f"https://itunes.apple.com/search?{params}")
    except OSError:
        return None

    for item in payload.get("results", []):
        genre = item.get("primaryGenreName")
        if genre:
            return genre
    return None


def fetch_release_tags(release_id: str, fallback_genre: str | None = None) -> list[TrackTags]:
    cache_key = f"{release_id}|{fallback_genre or ''}"
    cached = load_cache("release-tags", cache_key)
    if cached is not None:
        return [TrackTags(**item) for item in cached]

    params = urllib.parse.urlencode(
        {
            "inc": "artist-credits+recordings",
            "fmt": "json",
        }
    )
    payload = fetch_musicbrainz_json(f"{MUSICBRAINZ_RELEASE_URL}/{release_id}?{params}")
    album_title = payload.get("title", "")
    album_artist = release_artist_name(payload)
    year = release_year(payload.get("date") or "")
    genre = fallback_genre or lookup_itunes_genre(album_artist, album_title)

    tags: list[TrackTags] = []
    for medium in payload.get("media", []):
        disc_number = medium.get("position") or 1
        for track in medium.get("tracks", []):
            track_number = track.get("number")
            if track_number is not None:
                try:
                    track_number = int(str(track_number).split("-")[0])
                except ValueError:
                    track_number = None
            tags.append(
                TrackTags(
                    title=track.get("title") or track.get("recording", {}).get("title", ""),
                    artist=album_artist,
                    album=album_title,
                    album_artist=album_artist,
                    track_number=track_number,
                    disc_number=int(disc_number),
                    year=year,
                    genre=genre,
                )
            )
    save_cache("release-tags", cache_key, [tag.__dict__ for tag in tags])
    return tags


def match_tracks(
    local_tracks: list[TrackSnapshot],
    remote_tracks: list[TrackTags],
) -> list[tuple[TrackSnapshot, TrackTags]]:
    pairs: list[tuple[TrackSnapshot, TrackTags]] = []
    used_remote: set[int] = set()

    for local_track in local_tracks:
        best_index: int | None = None
        best_score = 0.0
        for index, remote_track in enumerate(remote_tracks):
            if index in used_remote:
                continue
            score = title_match_score(local_track.title, remote_track.title)
            if local_track.track_number and remote_track.track_number:
                if local_track.track_number == remote_track.track_number:
                    score += 0.35
            if local_track.disc_number and remote_track.disc_number:
                if local_track.disc_number == remote_track.disc_number:
                    score += 0.15
            if score > best_score:
                best_score = score
                best_index = index

        if best_index is not None and best_score >= 0.45:
            used_remote.add(best_index)
            pairs.append((local_track, remote_tracks[best_index]))

    return pairs


def build_tag_changes(pairs: list[tuple[TrackSnapshot, TrackTags]]) -> list[TagChange]:
    changes: list[TagChange] = []
    for local_track, remote_tags in pairs:
        if (
            normalize(local_track.title) == normalize(remote_tags.title)
            and normalize(local_track.artist) == normalize(remote_tags.artist)
            and normalize(local_track.album) == normalize(remote_tags.album)
            and normalize(local_track.album_artist or local_track.artist)
            == normalize(remote_tags.album_artist or remote_tags.artist)
            and local_track.track_number == remote_tags.track_number
            and (local_track.disc_number or 1) == (remote_tags.disc_number or 1)
            and local_track.year == remote_tags.year
            and (
                not remote_tags.genre
                or normalize(local_track.genre) == normalize(remote_tags.genre)
            )
        ):
            continue
        changes.append(TagChange(track_id=local_track.track_id, before=local_track, after=remote_tags))
    return changes


def format_change(change: TagChange) -> str:
    lines = [f"Track ID {change.track_id}: {change.before.title}"]
    fields = [
        ("Title", change.before.title, change.after.title),
        ("Artist", change.before.artist, change.after.artist),
        ("Album", change.before.album, change.after.album),
        ("Album Artist", change.before.album_artist or change.before.artist, change.after.album_artist),
        ("Track #", change.before.track_number, change.after.track_number),
        ("Disc #", change.before.disc_number or 1, change.after.disc_number or 1),
        ("Year", change.before.year, change.after.year),
        ("Genre", change.before.genre, change.after.genre or change.before.genre),
    ]
    for label, old, new in fields:
        if old != new and new not in (None, ""):
            lines.append(f"  {label}: {old!r} -> {new!r}")
    return "\n".join(lines)


def apply_tag_changes(
    app_name: str,
    changes: list[TagChange],
    save_undo: bool = True,
    undo_action: str = "metadata update",
    undo_group_id: str | None = None,
) -> int:
    if not changes:
        return 0

    if save_undo:
        save_undo_snapshot(changes, undo_action, group_id=undo_group_id)

    records: list[str] = []
    for change in changes:
        after = change.after
        records.append(
            FIELD_SEP.join(
                [
                    str(change.track_id),
                    after.title,
                    after.artist,
                    after.album,
                    after.album_artist,
                    "" if after.track_number is None else str(after.track_number),
                    "" if after.disc_number is None else str(after.disc_number),
                    "" if after.year is None else str(after.year),
                    after.genre or "",
                ]
            )
        )

    record_literal = "{" + ", ".join(f'"{applescript_string(record)}"' for record in records) + "}"
    script = f'''
tell application "{app_name}"
    set updatedCount to 0
    repeat with recordLine in {record_literal}
        set AppleScript's text item delimiters to "{FIELD_SEP}"
        set parts to text items of recordLine
        set AppleScript's text item delimiters to ""
        set trackId to item 1 of parts as integer
        set newTitle to item 2 of parts
        set newArtist to item 3 of parts
        set newAlbum to item 4 of parts
        set newAlbumArtist to item 5 of parts
        set newTrackNumber to item 6 of parts
        set newDiscNumber to item 7 of parts
        set newYear to item 8 of parts
        set newGenre to item 9 of parts
        set theTrack to (first track of library playlist 1 whose id is trackId)
        set name of theTrack to newTitle
        set artist of theTrack to newArtist
        set album of theTrack to newAlbum
        if newAlbumArtist is not "" then
            set album artist of theTrack to newAlbumArtist
        end if
        if newTrackNumber is not "" then
            set track number of theTrack to newTrackNumber as integer
        end if
        if newDiscNumber is not "" then
            set disc number of theTrack to newDiscNumber as integer
        end if
        if newYear is not "" then
            set year of theTrack to newYear as integer
        end if
        if newGenre is not "" then
            set genre of theTrack to newGenre
        end if
        set updatedCount to updatedCount + 1
    end repeat
    return updatedCount as string
end tell
'''
    return int(run_osascript(script))


def process_tags(
    app_name: str,
    album: AlbumInfo,
    local_tracks: list[TrackSnapshot],
    min_score: float,
    pick_interactive: bool,
    apply_index: int | None,
    dry_run: bool,
    release_match: ReleaseMatch | None = None,
    preview: bool = False,
    skip_if_correct: bool = False,
    undo_group_id: str | None = None,
) -> tuple[int, ReleaseMatch, list[TagChange]]:
    if release_match is None:
        release = choose_release_match(
            album,
            min_score=min_score,
            pick_interactive=pick_interactive,
            apply_index=apply_index,
        )
    else:
        release = release_match

    remote_tracks = fetch_release_tags(release.release_id)
    if not remote_tracks:
        raise RuntimeError(f"No track metadata returned for release “{release.title}”.")

    pairs = match_tracks(local_tracks, remote_tracks)
    if not pairs:
        raise RuntimeError("Could not match any selected tracks to online metadata.")

    changes = build_tag_changes(pairs)
    if not changes:
        if skip_if_correct:
            return 0, release, []
        raise RuntimeError("Tags already match the best online metadata.")

    if dry_run:
        return 0, release, changes

    if preview:
        preview_lines = [
            f"Update {len(changes)} track(s) using:",
            release.label,
            "",
        ]
        for change in changes[:8]:
            preview_lines.append(format_change(change))
        if len(changes) > 8:
            preview_lines.append(f"... and {len(changes) - 8} more track(s)")
        if not confirm_apply("Preview tag changes", "\n".join(preview_lines)):
            raise RuntimeError("Tag update cancelled.")

    updated = apply_tag_changes(app_name, changes, undo_group_id=undo_group_id)
    return updated, release, changes


def run_batch_tags(
    app_name: str,
    min_score: float,
    limit: int,
    dry_run: bool,
    preview: bool,
) -> int:
    albums = get_all_library_albums(app_name)
    if not albums:
        print("No albums found in your Music library.")
        return 0

    if limit > 0:
        albums = albums[:limit]

    print(f"Checking tags for {len(albums)} album(s)...\n")
    successes = 0
    skipped = 0
    failures = 0

    for index, album in enumerate(albums, start=1):
        print(f"[{index}/{len(albums)}] {album.artist} — {album.album}")
        try:
            local_tracks = get_target_tracks_for_album(app_name, album)
            updated, release, changes = process_tags(
                app_name,
                album,
                local_tracks,
                min_score=min_score,
                pick_interactive=False,
                apply_index=None,
                dry_run=dry_run,
                preview=False,
                skip_if_correct=True,
            )
            if not changes:
                print("  Already correct.")
                skipped += 1
                continue
            if dry_run:
                print(f"  Would update {len(changes)} track(s) using {release.title}")
            else:
                print(f"  Updated {updated} track(s) using {release.title}")
            successes += 1
        except Exception as exc:  # noqa: BLE001 - batch reporting
            failures += 1
            print(f"  Skipped: {exc}")

    summary = f"Batch tags finished: {successes} updated, {skipped} already correct, {failures} failed."
    print(f"\n{summary}")
    notify("Music tag batch", summary)
    return 0 if failures == 0 else 1


def get_tracks_for_album_title(app_name: str, album_title: str) -> list[TrackSnapshot]:
    script = f'''
tell application "{app_name}"
    set targetTracks to (every track of library playlist 1 whose album is "{applescript_string(album_title)}")
    if (count of targetTracks) is 0 then
        error "No tracks found for album."
    end if
    set output to {{}}
    repeat with t in targetTracks
        set albumArtistName to album artist of t
        if albumArtistName is missing value then
            set albumArtistName to ""
        end if
        set genreName to genre of t
        if genreName is missing value then
            set genreName to ""
        end if
        set lineText to (id of t as string) & "{FIELD_SEP}" & (name of t) & "{FIELD_SEP}" & (artist of t) & "{FIELD_SEP}" & (album of t) & "{FIELD_SEP}" & albumArtistName & "{FIELD_SEP}" & (track number of t as string) & "{FIELD_SEP}" & (disc number of t as string) & "{FIELD_SEP}" & (year of t as string) & "{FIELD_SEP}" & genreName
        set end of output to lineText
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    if not payload:
        return []
    return [parse_track_line(line) for line in payload.splitlines() if line.strip()]


def get_target_tracks_for_album(app_name: str, album: AlbumInfo) -> list[TrackSnapshot]:
    script = f'''
tell application "{app_name}"
    set targetTracks to (every track of library playlist 1 whose album is "{applescript_string(album.album)}" and artist is "{applescript_string(album.artist)}")
    if (count of targetTracks) is 0 then
        error "No tracks found for album."
    end if
    set output to {{}}
    repeat with t in targetTracks
        set albumArtistName to album artist of t
        if albumArtistName is missing value then
            set albumArtistName to ""
        end if
        set genreName to genre of t
        if genreName is missing value then
            set genreName to ""
        end if
        set lineText to (id of t as string) & "{FIELD_SEP}" & (name of t) & "{FIELD_SEP}" & (artist of t) & "{FIELD_SEP}" & (album of t) & "{FIELD_SEP}" & albumArtistName & "{FIELD_SEP}" & (track number of t as string) & "{FIELD_SEP}" & (disc number of t as string) & "{FIELD_SEP}" & (year of t as string) & "{FIELD_SEP}" & genreName
        set end of output to lineText
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    return [parse_track_line(line) for line in payload.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search for correct album tags and apply them in Music."
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Update only the selected song(s) instead of the whole album(s).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.45,
        help="Minimum album match score required (default: 0.45).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show tag changes without modifying Music.",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Choose which online album match to use.",
    )
    parser.add_argument(
        "--apply-index",
        type=int,
        default=None,
        help="Apply a specific release match by index (1-based).",
    )
    parser.add_argument(
        "--list-matches",
        action="store_true",
        help="List possible online album metadata matches.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show a confirmation dialog before applying tag changes.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Scan the library and fix tags for albums that differ from online metadata.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="With --batch, process at most this many albums (0 = all).",
    )
    args = parser.parse_args(argv)

    try:
        app_name = music_app_name()

        if args.batch:
            return run_batch_tags(
                app_name,
                min_score=args.min_score,
                limit=args.limit,
                dry_run=args.dry_run,
                preview=args.preview,
            )

        album = get_selected_album(app_name)
        local_tracks = get_target_tracks(app_name, entire_album=not args.selection_only)
        if not local_tracks:
            raise RuntimeError("No tracks found to update.")

        if args.list_matches:
            matches = [match for match in search_all_releases(album) if match.score >= args.min_score]
            if not matches:
                print("No matches found.")
                return 1
            print(f"Searching tags for: {album.artist} — {album.album}\n")
            for index, match in enumerate(matches[:8], start=1):
                print(
                    f"{index}. [{match.score:.2f}] {match.artist} — {match.title} "
                    f"({match.date or 'unknown date'}, {match.track_count} tracks)"
                )
            return 0

        updated, release, changes = process_tags(
            app_name,
            album,
            local_tracks,
            min_score=args.min_score,
            pick_interactive=args.pick,
            apply_index=args.apply_index,
            dry_run=args.dry_run,
            preview=args.preview,
        )

        if args.dry_run:
            print(f"Would update {len(changes)} track(s) using {release.artist} — {release.title}\n")
            for change in changes:
                print(format_change(change))
                print()
            return 0

        summary = f"Updated tags on {updated} track(s) using {release.artist} — {release.title}"
        print(summary)
        for change in changes[:5]:
            print(format_change(change))
        if len(changes) > 5:
            print(f"... and {len(changes) - 5} more track(s)")
        notify("Music tags updated", summary)
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Music tag update failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
