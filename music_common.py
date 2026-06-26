#!/usr/bin/env python3
"""Shared helpers for Music library fixing tools."""

from __future__ import annotations

import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from find_artwork import (
    AlbumInfo,
    fetch_musicbrainz_json,
    musicbrainz_search_queries,
    notify,
    run_osascript,
    score_result,
)
from search_cache import load_cache, save_cache


MUSICBRAINZ_RELEASE_URL = "https://musicbrainz.org/ws/2/release"


@dataclass(frozen=True)
class ReleaseMatch:
    release_id: str
    title: str
    artist: str
    date: str
    score: float
    track_count: int
    source: str = "MusicBrainz"

    @property
    def label(self) -> str:
        suffix = f" via {self.source}" if self.source != "MusicBrainz" else ""
        return (
            f"{self.artist} — {self.title} "
            f"({self.date or 'unknown date'}, {self.track_count} tracks){suffix}"
        )


def release_artist_name(release: dict) -> str:
    credits = release.get("artist-credit") or []
    if not credits:
        return ""
    return credits[0].get("name") or credits[0].get("artist", {}).get("name", "")


def search_musicbrainz_releases(album: AlbumInfo, limit: int = 8) -> list[ReleaseMatch]:
    matches: list[ReleaseMatch] = []
    seen_release_ids: set[str] = set()

    for query in musicbrainz_search_queries(album):
        params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": limit})
        try:
            payload = fetch_musicbrainz_json(f"{MUSICBRAINZ_RELEASE_URL}?{params}")
        except OSError:
            continue

        for release in payload.get("releases", []):
            release_id = release.get("id")
            if not release_id or release_id in seen_release_ids:
                continue
            seen_release_ids.add(release_id)

            title = release.get("title", "")
            artist = release_artist_name(release)
            score = score_result(album, title, artist)
            if score < 0.35:
                continue

            matches.append(
                ReleaseMatch(
                    release_id=release_id,
                    title=title,
                    artist=artist,
                    date=release.get("date") or "",
                    score=score,
                    track_count=int(release.get("track-count") or 0),
                    source="MusicBrainz",
                )
            )

    return sorted(matches, key=lambda match: (match.score, match.track_count), reverse=True)


def search_all_releases(album: AlbumInfo, limit: int = 8) -> list[ReleaseMatch]:
    from search_providers import deep_search_release_hints, lookup_musicbrainz_release

    cache_key = f"{album.artist}|{album.album}|{limit}"
    cached = load_cache("releases", cache_key)
    if cached is not None:
        return [ReleaseMatch(**item) for item in cached]

    matches = search_musicbrainz_releases(album, limit=limit)
    seen_release_ids = {match.release_id for match in matches}

    for hint in deep_search_release_hints(album):
        if hint.score < 0.4:
            continue

        release = lookup_musicbrainz_release(
            hint.artist,
            hint.title,
            album,
            track_count=hint.track_count,
        )
        if release is None:
            continue

        release_id = release.get("id")
        if not release_id or release_id in seen_release_ids:
            continue
        seen_release_ids.add(release_id)

        title = release.get("title", hint.title)
        artist = release_artist_name(release) or hint.artist
        score = max(score_result(album, title, artist), hint.score * 0.98)
        matches.append(
            ReleaseMatch(
                release_id=release_id,
                title=title,
                artist=artist,
                date=release.get("date") or hint.date,
                score=score,
                track_count=int(release.get("track-count") or hint.track_count or 0),
                source=hint.source,
            )
        )

    result = sorted(matches, key=lambda match: (match.score, match.track_count), reverse=True)
    save_cache("releases", cache_key, [match.__dict__ for match in result])
    return result


def choose_release_interactive(matches: list[ReleaseMatch]) -> ReleaseMatch | None:
    if not matches:
        return None

    options: list[str] = []
    for index, match in enumerate(matches[:8], start=1):
        label = (
            f"{index}. [{match.score:.2f}] {match.artist} — {match.title} "
            f"({match.date or 'unknown date'}, {match.track_count} tracks)"
        )
        options.append(label.replace('"', '\\"'))

    list_literal = "{" + ", ".join(f'"{option}"' for option in options) + "}"
    script = f'''
set choices to {list_literal}
set picked to choose from list choices with prompt "Choose the correct album:" default items {{item 1 of choices}}
if picked is false then
    return "CANCEL"
else
    return item 1 of picked
end if
'''
    result = run_osascript(script)
    if result == "CANCEL":
        return None
    chosen_index = int(result.split(".", 1)[0]) - 1
    return matches[chosen_index]


def choose_release_match(
    album: AlbumInfo,
    min_score: float,
    pick_interactive: bool = False,
    apply_index: int | None = None,
) -> ReleaseMatch:
    matches = [match for match in search_all_releases(album) if match.score >= min_score]
    if not matches:
        all_matches = search_all_releases(album)
        if all_matches:
            best = all_matches[0]
            raise RuntimeError(
                "Found possible album matches, but none were close enough. "
                f"Best guess: {best.label} (score {best.score:.2f})."
            )
        raise RuntimeError(f"No matching album metadata found for “{album.album}” by {album.artist}.")

    if apply_index is not None:
        if apply_index < 1 or apply_index > len(matches):
            raise RuntimeError(f"Release index must be between 1 and {len(matches)}.")
        return matches[apply_index - 1]

    if pick_interactive:
        chosen = choose_release_interactive(matches)
        if chosen is None:
            raise RuntimeError("Album selection cancelled.")
        return chosen

    return matches[0]


def confirm_apply(title: str, message: str, image_path: Path | None = None) -> bool:
    if image_path is not None and image_path.exists():
        subprocess.run(["open", str(image_path.resolve())], check=False)

    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'''
display dialog "{escaped_message}" with title "{escaped_title}" buttons {{"Cancel", "Apply"}} default button "Apply"
return button returned of result
'''
    return run_osascript(script) == "Apply"


def get_all_library_albums(app_name: str) -> list[AlbumInfo]:
    script = f'''
tell application "{app_name}"
    set seen to {{}}
    set result to {{}}
    repeat with t in (every track of library playlist 1)
        try
            set albumName to album of t
            set artistName to artist of t
            if albumName is not missing value and albumName is not "" and artistName is not missing value and artistName is not "" then
                set recordKey to artistName & "|||" & albumName
                if seen does not contain recordKey then
                    set end of seen to recordKey
                    set end of result to recordKey
                end if
            end if
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to result as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    if not payload:
        return []

    albums: list[AlbumInfo] = []
    for line in payload.splitlines():
        if "|||" not in line:
            continue
        artist, album_name = line.split("|||", 1)
        albums.append(AlbumInfo(artist=artist, album=album_name, app_name=app_name))
    return albums
