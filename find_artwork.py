#!/usr/bin/env python3
"""Find and apply album artwork for the current Music/iTunes selection."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from search_cache import load_cache, save_cache
from undo_history import save_artwork_undo_snapshot


ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/release"
USER_AGENT = "MusicArtworkFinder/1.0 (https://github.com/local/music-artwork-finder)"
ITUNES_SIZE_CANDIDATES = (600, 800, 1000, 1200, 1400, 1500, 1800, 2000, 2500, 3000, 4000, 5000)
MUSICBRAINZ_MIN_INTERVAL = 1.0
FIELD_SEP = "|||"
_last_musicbrainz_request = 0.0


@dataclass(frozen=True)
class AlbumInfo:
    artist: str
    album: str
    app_name: str


@dataclass(frozen=True)
class ArtworkMatch:
    source: str
    title: str
    artist: str
    url: str
    score: float


@dataclass(frozen=True)
class ArtworkCandidate:
    url: str
    source: str
    title: str
    artist: str
    width: int
    height: int
    size_bytes: int
    score: float

    @property
    def resolution_label(self) -> str:
        return f"{self.width}x{self.height}"


def run_osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "AppleScript failed"
        raise RuntimeError(message)
    return result.stdout.strip()


def music_app_name() -> str:
    for name in ("Music", "iTunes"):
        script = f'tell application "System Events" to return (name of processes) contains "{name}"'
        if run_osascript(script) == "true":
            return name
    raise RuntimeError("Music or iTunes is not running. Open the app and try again.")


def get_selected_album(app_name: str) -> AlbumInfo:
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

    set theItem to item 1 of selectedItems
    set itemClass to class of theItem as string
    set artistName to missing value
    set albumName to missing value

    if itemClass contains "track" then
        set artistName to artist of theItem
        set albumName to album of theItem
    else
        try
            set albumName to name of theItem
            set artistName to artist of theItem
        end try
        if artistName is missing value or albumName is missing value then
            try
                set albumName to album of theItem
                set artistName to artist of theItem
            end try
        end if
        if artistName is missing value or albumName is missing value then
            try
                set albumName to name of theItem
                set artistName to album artist of theItem
            end try
        end if
    end if

    if albumName is missing value or albumName is "" then
        error "Could not determine the album name from the current selection."
    end if
    if artistName is missing value or artistName is "" then
        error "Could not determine the artist name from the current selection."
    end if
    return artistName & "|||" & albumName
end tell
'''
    payload = run_osascript(script)
    artist, album = payload.split("|||", 1)
    return AlbumInfo(artist=artist, album=album, app_name=app_name)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_artist_name(artist: str) -> str:
    cleaned = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]", " ", artist)
    cleaned = re.sub(r"\s+(feat\.?|featuring|with)\s+.+$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip()
    return cleaned or artist.strip()


def clean_album_name(album: str) -> str:
    return re.sub(r"\s+", " ", album).strip()


def artist_search_variants(artist: str) -> list[str]:
    variants: list[str] = []
    for value in (clean_artist_name(artist), artist.strip()):
        if value and value not in variants:
            variants.append(value)
    return variants


def itunes_search_terms(album: AlbumInfo) -> list[str]:
    cleaned_album = clean_album_name(album.album)
    terms: list[str] = []

    for artist in artist_search_variants(album.artist):
        terms.append(f"{artist} {cleaned_album}")

    primary_artist = clean_artist_name(album.artist)
    if normalize(cleaned_album) == normalize(primary_artist):
        terms.append(primary_artist)

    if cleaned_album:
        terms.append(cleaned_album)

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = normalize(term)
        if key and key not in seen:
            seen.add(key)
            deduped.append(term)
    return deduped


def musicbrainz_search_queries(album: AlbumInfo) -> list[str]:
    cleaned_album = clean_album_name(album.album)
    queries: list[str] = []

    for artist in artist_search_variants(album.artist):
        queries.append(f'artist:"{artist}" AND release:"{cleaned_album}"')
        queries.append(f"artist:{artist} AND release:{cleaned_album}")

    queries.append(f'release:"{cleaned_album}"')

    tokens = album_significant_tokens(cleaned_album)
    if len(tokens) >= 2:
        queries.append(" AND ".join(f"release:{token}" for token in tokens[:5]))
    if tokens:
        queries.append(f"release:{tokens[0]}")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


MB_QUERY_STOPWORDS = frozenset(
    {"music", "from", "the", "and", "for", "with", "vol", "volume", "album", "edition"}
)


def album_significant_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in normalize(clean_album_name(text)).split():
        if len(token) <= 2 or token in MB_QUERY_STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def is_various_artists(artist_name: str) -> bool:
    return normalize(clean_artist_name(artist_name)) in {"various artists", "various", "va"}


def token_overlap(a: str, b: str) -> float:
    a_tokens = set(normalize(a).split())
    b_tokens = set(normalize(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def is_likely_single_or_ep(title: str) -> bool:
    lowered = title.casefold()
    return any(
        marker in lowered
        for marker in (" - single", " - ep", " - maxi-single", " - remix", " - live")
    )


def live_album_mismatch_penalty(album_title: str, candidate_title: str) -> float:
    album_norm = normalize(album_title)
    candidate_norm = normalize(candidate_title)
    if album_norm == candidate_norm:
        return 1.0
    if "live" not in album_norm or "live" not in candidate_norm:
        return 1.0
    if album_norm.startswith("live") and candidate_norm.startswith("live"):
        return 0.25
    return 1.0


def score_result(album: AlbumInfo, collection_name: str, artist_name: str) -> float:
    album_score = token_overlap(album.album, collection_name)
    artist_score = token_overlap(album.artist, artist_name)

    if normalize(album.album) == normalize(collection_name):
        album_score = max(album_score, 1.0)
    if normalize(clean_artist_name(album.artist)) == normalize(clean_artist_name(artist_name)):
        artist_score = max(artist_score, 1.0)

    score = (album_score * 0.65) + (artist_score * 0.35)
    score *= live_album_mismatch_penalty(album.album, collection_name)

    if album_score >= 0.4 and is_various_artists(artist_name):
        score = max(score, (album_score * 0.92) + 0.05)
    elif album_score >= 0.4 and any(
        marker in normalize(album.album)
        for marker in ("music from", "soundtrack", "sampler", "original cast", " motion picture")
    ):
        score = max(score, album_score * 0.85)

    if is_likely_single_or_ep(collection_name) and not is_likely_single_or_ep(album.album):
        score *= 0.5

    return score


def choose_best_candidate(candidates: list[ArtworkCandidate]) -> ArtworkCandidate:
    if not candidates:
        raise RuntimeError("No artwork candidates to choose from.")

    best_score = max(candidate.score for candidate in candidates)
    if best_score >= 0.95:
        tier = [candidate for candidate in candidates if candidate.score >= best_score - 0.05]
    else:
        tier = [candidate for candidate in candidates if candidate.score >= best_score - 0.12]

    return max(
        tier,
        key=lambda candidate: (
            candidate.score,
            candidate.width * candidate.height,
            candidate.size_bytes,
        ),
    )


def itunes_artwork_base(url: str) -> str:
    if not url:
        return url
    return re.sub(r"/\d+x\d+bb\.(?:jpg|png)$", "", url)


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height

    if not data.startswith(b"\xff\xd8"):
        return None

    index = 2
    while index < len(data) - 9:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            height = (data[index + 5] << 8) + data[index + 6]
            width = (data[index + 7] << 8) + data[index + 8]
            return width, height
        if marker in (0xD8, 0xD9):
            index += 2
            continue
        segment_length = (data[index + 2] << 8) + data[index + 3]
        index += 2 + segment_length
    return None


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def musicbrainz_throttle() -> None:
    global _last_musicbrainz_request
    elapsed = time.monotonic() - _last_musicbrainz_request
    if elapsed < MUSICBRAINZ_MIN_INTERVAL:
        time.sleep(MUSICBRAINZ_MIN_INTERVAL - elapsed)
    _last_musicbrainz_request = time.monotonic()


def fetch_musicbrainz_json(url: str) -> dict:
    musicbrainz_throttle()
    return fetch_json(url)


def fetch_json(url: str) -> dict:
    return json.loads(fetch_bytes(url, timeout=20).decode("utf-8"))


def probe_itunes_artwork(base_url: str) -> ArtworkCandidate | None:
    sizes = ITUNES_SIZE_CANDIDATES
    cache: dict[int, ArtworkCandidate | None] = {}

    def candidate_at(index: int) -> ArtworkCandidate | None:
        if index in cache:
            return cache[index]
        size = sizes[index]
        url = f"{base_url}/{size}x{size}bb.jpg"
        try:
            data = fetch_bytes(url, timeout=15)
        except OSError:
            cache[index] = None
            return None

        dimensions = image_dimensions(data)
        if not dimensions:
            cache[index] = None
            return None

        width, height = dimensions
        candidate = ArtworkCandidate(
            url=url,
            source="iTunes",
            title="",
            artist="",
            width=width,
            height=height,
            size_bytes=len(data),
            score=0.0,
        )
        cache[index] = candidate
        return candidate

    if candidate_at(0) is None:
        return None

    lo, hi = 0, len(sizes) - 1
    best_index = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        current = candidate_at(mid)
        best = candidate_at(best_index)
        if current is None or best is None:
            hi = mid - 1
            continue
        if current.width * current.height >= best.width * best.height:
            best_index = mid
            lo = mid + 1
        else:
            hi = mid - 1

    result = candidate_at(best_index)
    if result is None:
        return None

    for index in range(best_index, len(sizes)):
        current = candidate_at(index)
        if current is None:
            break
        if current.width * current.height > result.width * result.height:
            result = current
        elif (
            current.width * current.height == result.width * result.height
            and current.size_bytes > result.size_bytes
        ):
            result = current
        elif current.width * current.height < result.width * result.height:
            break

    return result


def search_cover_art_archive(album: AlbumInfo, limit: int = 8) -> list[ArtworkMatch]:
    matches: list[ArtworkMatch] = []
    seen_release_ids: set[str] = set()

    for query in musicbrainz_search_queries(album):
        params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": limit})
        try:
            payload = fetch_musicbrainz_json(f"{MUSICBRAINZ_SEARCH_URL}?{params}")
        except OSError:
            continue

        for release in payload.get("releases", []):
            release_id = release.get("id")
            if not release_id or release_id in seen_release_ids:
                continue
            seen_release_ids.add(release_id)

            release_title = release.get("title", "")
            artist_name = ""
            artist_credit = release.get("artist-credit") or []
            if artist_credit:
                artist_name = artist_credit[0].get("name") or artist_credit[0].get("artist", {}).get("name", "")

            score = score_result(album, release_title, artist_name)
            if score < 0.35:
                continue

            try:
                cover_payload = fetch_musicbrainz_json(f"https://coverartarchive.org/release/{release_id}")
            except OSError:
                continue

            for image in cover_payload.get("images", []):
                if not image.get("front"):
                    continue
                urls = [image.get("image")]
                thumbnails = image.get("thumbnails") or {}
                for key in ("2500", "1200", "large", "500", "250"):
                    thumb_url = thumbnails.get(key)
                    if thumb_url:
                        urls.append(thumb_url)
                artwork_url = next((url for url in urls if url), None)
                if not artwork_url:
                    continue
                matches.append(
                    ArtworkMatch(
                        source="Cover Art Archive",
                        title=release_title,
                        artist=artist_name,
                        url=artwork_url,
                        score=score,
                    )
                )
                break

    return sorted(matches, key=lambda match: match.score, reverse=True)


def resolve_artwork_candidate(match: ArtworkMatch) -> ArtworkCandidate | None:
    if match.source == "iTunes":
        base_url = itunes_artwork_base(match.url)
        candidate = probe_itunes_artwork(base_url)
        if candidate is None:
            return None
        return ArtworkCandidate(
            url=candidate.url,
            source=candidate.source,
            title=match.title,
            artist=match.artist,
            width=candidate.width,
            height=candidate.height,
            size_bytes=candidate.size_bytes,
            score=match.score,
        )

    try:
        data = fetch_bytes(match.url)
    except OSError:
        return None

    dimensions = image_dimensions(data)
    if not dimensions:
        return None

    width, height = dimensions
    return ArtworkCandidate(
        url=match.url,
        source=match.source,
        title=match.title,
        artist=match.artist,
        width=width,
        height=height,
        size_bytes=len(data),
        score=match.score,
    )


def gather_artwork_metadata_matches(album: AlbumInfo) -> list[ArtworkMatch]:
    from search_providers import deep_search_artwork

    matches: list[ArtworkMatch] = []
    matches.extend(search_itunes(album))
    matches.extend(search_cover_art_archive(album))
    matches.extend(deep_search_artwork(album))
    return sorted(matches, key=lambda match: match.score, reverse=True)


def find_highest_quality_artwork(album: AlbumInfo, min_score: float) -> ArtworkCandidate:
    metadata_matches = gather_artwork_metadata_matches(album)

    if not metadata_matches:
        raise RuntimeError(f"No artwork found online for “{album.album}” by {album.artist}.")

    top_matches = [
        match
        for match in metadata_matches
        if match.score >= min_score
    ][:8]

    if not top_matches:
        best_meta = metadata_matches[0]
        raise RuntimeError(
            "Found possible matches, but none were close enough. "
            f"Best guess: “{best_meta.title}” by {best_meta.artist} (score {best_meta.score:.2f})."
        )

    candidates: list[ArtworkCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for match in top_matches:
        key = (match.source, match.artist, match.title)
        if key in seen:
            continue
        seen.add(key)

        candidate = resolve_artwork_candidate(match)
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        best_meta = top_matches[0]
        raise RuntimeError(
            "Found likely matches, but artwork could not be downloaded. "
            f"Best guess: “{best_meta.title}” by {best_meta.artist}."
        )

    return choose_best_candidate(candidates)


def search_itunes(album: AlbumInfo, limit: int = 12) -> list[ArtworkMatch]:
    matches: list[ArtworkMatch] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for term in itunes_search_terms(album):
        params = urllib.parse.urlencode(
            {
                "term": term,
                "entity": "album",
                "limit": limit,
                "media": "music",
            }
        )
        try:
            payload = fetch_json(f"{ITUNES_SEARCH_URL}?{params}")
        except OSError:
            continue

        for item in payload.get("results", []):
            artwork_url = item.get("artworkUrl100") or item.get("artworkUrl60")
            if not artwork_url:
                continue

            title = item.get("collectionName", "")
            artist = item.get("artistName", "")
            key = (artist, title, artwork_url)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            matches.append(
                ArtworkMatch(
                    source="iTunes",
                    title=title,
                    artist=artist,
                    url=artwork_url,
                    score=score_result(album, title, artist),
                )
            )

    return sorted(matches, key=lambda match: match.score, reverse=True)


def make_square_artwork(image_path: Path) -> None:
    dimensions = image_dimensions(image_path.read_bytes())
    if not dimensions:
        return

    width, height = dimensions
    if width == height:
        return

    side = min(width, height)
    temp_path = image_path.with_name(f"{image_path.stem}.square{image_path.suffix}")
    result = subprocess.run(
        [
            "sips",
            "--cropToHeightWidth",
            str(side),
            str(side),
            str(image_path),
            "--out",
            str(temp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not temp_path.exists():
        message = result.stderr.strip() or result.stdout.strip() or "Could not crop artwork to a square."
        raise RuntimeError(message)
    temp_path.replace(image_path)


def download_artwork(url: str, destination: Path) -> None:
    destination.write_bytes(fetch_bytes(url))
    make_square_artwork(destination)


def list_match_candidates(album: AlbumInfo, min_score: float) -> list[ArtworkCandidate]:
    metadata_matches = gather_artwork_metadata_matches(album)

    top_matches = [match for match in metadata_matches if match.score >= min_score][:5]

    candidates: list[ArtworkCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for match in top_matches:
        key = (match.source, match.artist, match.title)
        if key in seen:
            continue
        seen.add(key)
        candidate = resolve_artwork_candidate(match)
        if candidate is not None:
            candidates.append(candidate)

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.score,
            candidate.width * candidate.height,
            candidate.size_bytes,
        ),
        reverse=True,
    )


def apply_artwork(
    app_name: str,
    album: AlbumInfo,
    image_path: Path,
    entire_album: bool,
    skip_existing: bool = False,
) -> int:
    image_posix = str(image_path.resolve())
    script = f'''
set imageFile to POSIX file "{image_posix}"
set artworkData to read imageFile as picture

tell application "{app_name}"
    set targetTracks to {{}}
    if {str(entire_album).lower()} is true then
        set selectedItems to selection
        if (count of selectedItems) is 0 then
            try
                tell front browser window
                    set selectedItems to selection
                end tell
            end try
        end if
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
    else
        set targetTracks to selection
        if (count of targetTracks) is 0 then
            try
                tell front browser window
                    set targetTracks to selection
                end tell
            end try
        end if
    end if

    if (count of targetTracks) is 0 then
        error "No tracks found to update."
    end if

    set updatedCount to 0
    set skippedCount to 0
    repeat with aTrack in targetTracks
        if {str(skip_existing).lower()} is true then
            try
                if (count of artwork of aTrack) > 0 then
                    set skippedCount to skippedCount + 1
                else
                    set data of artwork 1 of aTrack to artworkData
                    set updatedCount to updatedCount + 1
                end if
            on error
                try
                    set data of artwork of aTrack to artworkData
                    set updatedCount to updatedCount + 1
                end try
            end try
        else
            try
                set data of artwork 1 of aTrack to artworkData
                set updatedCount to updatedCount + 1
            on error
                try
                    set data of artwork of aTrack to artworkData
                    set updatedCount to updatedCount + 1
                end try
            end try
        end if
    end repeat

    return (updatedCount as string) & "|" & (skippedCount as string)
end tell
'''
    payload = run_osascript(script)
    updated, _skipped = payload.split("|", 1)
    return int(updated)


def apply_artwork_to_track_ids(
    app_name: str,
    image_path: Path,
    track_ids: list[int],
) -> int:
    if not track_ids:
        return 0

    image_posix = str(image_path.resolve())
    id_list = ", ".join(str(track_id) for track_id in track_ids)
    script = f'''
set imageFile to POSIX file "{image_posix}"
set artworkData to read imageFile as picture

tell application "{app_name}"
    set updatedCount to 0
    repeat with trackId in {{{id_list}}}
        try
            set aTrack to (first track of library playlist 1 whose id is trackId)
            try
                set data of artwork 1 of aTrack to artworkData
            on error
                set data of artwork of aTrack to artworkData
            end try
            set updatedCount to updatedCount + 1
        end try
    end repeat
    return updatedCount as string
end tell
'''
    return int(run_osascript(script))


def save_artwork_undo(
    app_name: str,
    entire_album: bool,
    skip_existing: bool = False,
) -> None:
    undo_dir = Path(tempfile.mkdtemp(prefix="music-artwork-undo-"))
    undo_posix = str(undo_dir.resolve())
    script = f'''
tell application "{app_name}"
    set targetTracks to {{}}
    if {str(entire_album).lower()} is true then
        set selectedItems to selection
        if (count of selectedItems) is 0 then
            try
                tell front browser window
                    set selectedItems to selection
                end tell
            end try
        end if
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
    else
        set targetTracks to selection
        if (count of targetTracks) is 0 then
            try
                tell front browser window
                    set targetTracks to selection
                end tell
            end try
        end if
    end if

    set output to {{}}
    repeat with aTrack in targetTracks
        try
            if not {str(skip_existing).lower()} or (count of artwork of aTrack) is 0 then
                if (count of artwork of aTrack) > 0 then
                    set trackId to id of aTrack as string
                    set artworkPath to "{undo_posix}/" & trackId & ".pct"
                    set artworkFile to open for access (POSIX file artworkPath) with write permission
                    set eof artworkFile to 0
                    write (data of artwork 1 of aTrack) to artworkFile
                    close access artworkFile
                    set albumArtistName to album artist of aTrack
                    if albumArtistName is missing value then
                        set albumArtistName to ""
                    end if
                    set lineText to trackId & "{FIELD_SEP}" & (name of aTrack) & "{FIELD_SEP}" & (artist of aTrack) & "{FIELD_SEP}" & (album of aTrack) & "{FIELD_SEP}" & albumArtistName & "{FIELD_SEP}" & artworkPath
                    set end of output to lineText
                end if
            end if
        on error
            try
                close access artworkFile
            end try
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    tracks: list[dict[str, str]] = []
    for line in payload.splitlines():
        parts = line.split(FIELD_SEP)
        if len(parts) != 6:
            continue
        track_id, title, artist, album_name, album_artist, artwork_path = parts
        tracks.append(
            {
                "track_id": track_id,
                "title": title,
                "artist": artist,
                "album": album_name,
                "album_artist": album_artist,
                "artwork_path": artwork_path,
            }
        )
    save_artwork_undo_snapshot(tracks, undo_dir)


def save_artwork_undo_for_track_ids(
    app_name: str,
    track_ids: list[int],
    group_id: str | None = None,
) -> None:
    if not track_ids:
        return

    undo_dir = Path(tempfile.mkdtemp(prefix="music-artwork-undo-"))
    undo_posix = str(undo_dir.resolve())
    id_list = ", ".join(str(track_id) for track_id in track_ids)
    script = f'''
tell application "{app_name}"
    set output to {{}}
    repeat with trackId in {{{id_list}}}
        try
            set aTrack to (first track of library playlist 1 whose id is trackId)
            if (count of artwork of aTrack) > 0 then
                set trackIdText to id of aTrack as string
                set artworkPath to "{undo_posix}/" & trackIdText & ".pct"
                set artworkFile to open for access (POSIX file artworkPath) with write permission
                set eof artworkFile to 0
                write (data of artwork 1 of aTrack) to artworkFile
                close access artworkFile
                set albumArtistName to album artist of aTrack
                if albumArtistName is missing value then
                    set albumArtistName to ""
                end if
                set lineText to trackIdText & "{FIELD_SEP}" & (name of aTrack) & "{FIELD_SEP}" & (artist of aTrack) & "{FIELD_SEP}" & (album of aTrack) & "{FIELD_SEP}" & albumArtistName & "{FIELD_SEP}" & artworkPath
                set end of output to lineText
            end if
        on error
            try
                close access artworkFile
            end try
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    payload = run_osascript(script).strip()
    tracks: list[dict[str, str]] = []
    for line in payload.splitlines():
        parts = line.split(FIELD_SEP)
        if len(parts) != 6:
            continue
        track_id, title, artist, album_name, album_artist, artwork_path = parts
        tracks.append(
            {
                "track_id": track_id,
                "title": title,
                "artist": artist,
                "album": album_name,
                "album_artist": album_artist,
                "artwork_path": artwork_path,
            }
        )
    save_artwork_undo_snapshot(tracks, undo_dir, group_id=group_id)


def get_albums_missing_artwork(app_name: str) -> list[AlbumInfo]:
    script = f'''
tell application "{app_name}"
    set seen to {{}}
    set result to {{}}
    repeat with t in (every track of library playlist 1)
        try
            if (count of artwork of t) is 0 then
                set albumName to album of t
                set artistName to artist of t
                if albumName is not missing value and albumName is not "" and artistName is not missing value and artistName is not "" then
                    set recordKey to artistName & "|||" & albumName
                    if seen does not contain recordKey then
                        set end of seen to recordKey
                        set end of result to recordKey
                    end if
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


def candidate_label(candidate: ArtworkCandidate, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    return (
        f"{prefix}{candidate.resolution_label} | "
        f"{candidate.artist} — {candidate.title} ({candidate.source})"
    )


def choose_match_interactive(candidates: list[ArtworkCandidate]) -> ArtworkCandidate | None:
    if not candidates:
        return None

    options: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        label = candidate_label(candidate, index).replace('"', '\\"')
        options.append(label)

    list_literal = "{" + ", ".join(f'"{option}"' for option in options) + "}"
    script = f'''
set choices to {list_literal}
set picked to choose from list choices with prompt "Choose artwork to apply:" default items {{item 1 of choices}}
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
    return candidates[chosen_index]


def apply_candidate(
    app_name: str,
    album: AlbumInfo,
    candidate: ArtworkCandidate,
    entire_album: bool,
    skip_existing: bool,
    reembed: bool = True,
    image_path: Path | None = None,
) -> int:
    if image_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="music-artwork-")
        temp_dir_path = Path(temp_dir.name)
        image_path = temp_dir_path / "artwork.jpg"
        download_artwork(candidate.url, image_path)
        save_artwork_undo(app_name, entire_album=entire_album, skip_existing=skip_existing)
        updated = apply_artwork(
            app_name,
            album,
            image_path,
            entire_album=entire_album,
            skip_existing=skip_existing,
        )
        if reembed and updated > 0:
            reembed_artwork(app_name, album, entire_album=entire_album)
        temp_dir.cleanup()
        return updated

    save_artwork_undo(app_name, entire_album=entire_album, skip_existing=skip_existing)
    updated = apply_artwork(
        app_name,
        album,
        image_path,
        entire_album=entire_album,
        skip_existing=skip_existing,
    )
    if reembed and updated > 0:
        reembed_artwork(app_name, album, entire_album=entire_album)
    return updated


def artwork_from_release(release_match: ReleaseMatch, album: AlbumInfo) -> ArtworkCandidate | None:
    cache_key = f"{release_match.release_id}|{album.artist}|{album.album}"
    cached = load_cache("release-artwork", cache_key)
    if cached is not None:
        return ArtworkCandidate(**cached) if cached else None

    try:
        cover_payload = fetch_musicbrainz_json(
            f"https://coverartarchive.org/release/{release_match.release_id}"
        )
    except OSError:
        cover_payload = {"images": []}

    best: ArtworkCandidate | None = None
    for image in cover_payload.get("images", []):
        if not image.get("front"):
            continue
        urls: list[str] = []
        thumbnails = image.get("thumbnails") or {}
        for key in ("2500", "1200", "large", "500", "250"):
            thumb_url = thumbnails.get(key)
            if thumb_url:
                urls.append(thumb_url)
        full_url = image.get("image")
        if full_url:
            urls.append(full_url)

        for url in urls:
            if not url:
                continue
            try:
                data = fetch_bytes(url)
            except OSError:
                continue
            dimensions = image_dimensions(data)
            if not dimensions:
                continue
            width, height = dimensions
            candidate = ArtworkCandidate(
                url=url,
                source="Cover Art Archive",
                title=release_match.title,
                artist=release_match.artist,
                width=width,
                height=height,
                size_bytes=len(data),
                score=release_match.score,
            )
            if best is None or width * height > best.width * best.height:
                best = candidate
        if best is not None:
            save_cache("release-artwork", cache_key, best.__dict__)
            return best

    probe_album = AlbumInfo(
        artist=release_match.artist,
        album=release_match.title,
        app_name=album.app_name,
    )
    for match in search_itunes(probe_album, limit=5):
        if score_result(album, match.title, match.artist) < 0.45:
            continue
        candidate = resolve_artwork_candidate(match)
        if candidate is not None:
            result = ArtworkCandidate(
                url=candidate.url,
                source=candidate.source,
                title=release_match.title,
                artist=release_match.artist,
                width=candidate.width,
                height=candidate.height,
                size_bytes=candidate.size_bytes,
                score=release_match.score,
            )
            save_cache("release-artwork", cache_key, result.__dict__)
            return result

    from search_providers import deep_search_artwork

    for match in deep_search_artwork(probe_album):
        if score_result(album, match.title, match.artist) < 0.45:
            continue
        candidate = resolve_artwork_candidate(match)
        if candidate is not None:
            result = ArtworkCandidate(
                url=candidate.url,
                source=candidate.source,
                title=release_match.title,
                artist=release_match.artist,
                width=candidate.width,
                height=candidate.height,
                size_bytes=candidate.size_bytes,
                score=release_match.score,
            )
            save_cache("release-artwork", cache_key, result.__dict__)
            return result
    save_cache("release-artwork", cache_key, None)
    return None


def reembed_artwork(app_name: str, album: AlbumInfo, entire_album: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="music-artwork-reembed-") as temp_dir:
        temp_posix = str(Path(temp_dir).resolve())
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

    set reembeddedCount to 0
    repeat with aTrack in targetTracks
        try
            if (count of artwork of aTrack) > 0 then
                set tempFile to POSIX file ("{temp_posix}/art-" & (id of aTrack as string) & ".jpg")
                set artData to data of artwork 1 of aTrack
                set fileRef to open for access tempFile with write permission
                set eof of fileRef to 0
                write artData to fileRef
                close access fileRef
                set refreshedArt to read tempFile as picture
                set data of artwork 1 of aTrack to refreshedArt
                set reembeddedCount to reembeddedCount + 1
            end if
        end try
    end repeat
    return reembeddedCount as string
end tell
'''
        return int(run_osascript(script))


def process_album(
    app_name: str,
    album: AlbumInfo,
    min_score: float,
    entire_album: bool,
    skip_existing: bool,
    apply_index: int | None,
    pick_interactive: bool,
    dry_run: bool,
    preview: bool = False,
    reembed: bool = True,
    release_match: object | None = None,
) -> tuple[int, ArtworkCandidate | None]:
    if release_match is not None:
        chosen = artwork_from_release(release_match, album)
        if chosen is None:
            title = getattr(release_match, "title", "release")
            raise RuntimeError(f"No artwork found for release “{title}”.")
    else:
        candidates = list_match_candidates(album, min_score)
        if not candidates:
            raise RuntimeError(f"No artwork found online for “{album.album}” by {album.artist}.")

        if apply_index is not None:
            if apply_index < 1 or apply_index > len(candidates):
                raise RuntimeError(f"Match index must be between 1 and {len(candidates)}.")
            chosen = candidates[apply_index - 1]
        elif pick_interactive:
            chosen = choose_match_interactive(candidates)
            if chosen is None:
                raise RuntimeError("Artwork selection cancelled.")
        else:
            chosen = choose_best_candidate(candidates)

    if dry_run:
        return 0, chosen

    with tempfile.TemporaryDirectory(prefix="music-artwork-") as temp_dir:
        image_path = Path(temp_dir) / "artwork.jpg"
        download_artwork(chosen.url, image_path)
        if preview:
            from music_common import confirm_apply

            message = (
                f"Apply {chosen.resolution_label} artwork?\n"
                f"{chosen.artist} — {chosen.title}\n"
                f"Source: {chosen.source}\n"
                f"Score: {chosen.score:.2f}"
            )
            if not confirm_apply("Preview artwork", message, image_path):
                raise RuntimeError("Artwork apply cancelled.")

        updated = apply_candidate(
            app_name,
            album,
            chosen,
            entire_album=entire_album,
            skip_existing=skip_existing,
            reembed=reembed,
            image_path=image_path,
        )
    if updated == 0 and skip_existing:
        raise RuntimeError(f"All tracks already had artwork for “{album.album}”.")
    return updated, chosen


def run_batch_missing(
    app_name: str,
    min_score: float,
    skip_existing: bool,
    limit: int,
    dry_run: bool,
) -> int:
    albums = get_albums_missing_artwork(app_name)
    if not albums:
        print("No albums with missing artwork were found.")
        return 0

    if limit > 0:
        albums = albums[:limit]

    print(f"Processing {len(albums)} album(s) with missing artwork...\n")
    successes = 0
    failures = 0

    for index, album in enumerate(albums, start=1):
        print(f"[{index}/{len(albums)}] {album.artist} — {album.album}")
        try:
            updated, chosen = process_album(
                app_name,
                album,
                min_score=min_score,
                entire_album=True,
                skip_existing=skip_existing,
                apply_index=None,
                pick_interactive=False,
                dry_run=dry_run,
            )
            if dry_run and chosen:
                print(
                    f"  Would apply: {chosen.resolution_label} "
                    f"({chosen.source}) {chosen.artist} — {chosen.title}"
                )
            elif chosen:
                print(f"  Applied {chosen.resolution_label} to {updated} track(s).")
            successes += 1
        except Exception as exc:  # noqa: BLE001 - batch reporting
            failures += 1
            print(f"  Skipped: {exc}")

    summary = f"Finished batch: {successes} succeeded, {failures} failed."
    print(f"\n{summary}")
    notify("Album artwork batch", summary)
    return 0 if failures == 0 else 1


def notify(title: str, message: str) -> None:
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    run_osascript(
        f'display notification "{escaped_message}" with title "{escaped_title}" sound name "Glass"'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find album artwork online and apply it to the selected album(s) in Music."
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="Apply artwork only to selected song(s) instead of every song in the album(s).",
    )
    parser.add_argument(
        "--skip-if-artwork-exists",
        action="store_true",
        help="Skip tracks that already have artwork instead of overwriting them.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.45,
        help="Minimum match score required before applying artwork (default: 0.45).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and report the best match without changing anything in Music.",
    )
    parser.add_argument(
        "--list-matches",
        action="store_true",
        help="Print the top artwork matches with resolution and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="With --list-matches, print machine-readable JSON.",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Show a dialog to choose which artwork match to apply.",
    )
    parser.add_argument(
        "--apply-index",
        type=int,
        default=None,
        help="Apply a specific match from --list-matches (1-based index).",
    )
    parser.add_argument(
        "--batch-missing",
        action="store_true",
        help="Find artwork for albums in your library that are missing cover art.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="With --batch-missing, process at most this many albums (0 = all).",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview artwork in Preview.app and confirm before applying.",
    )
    parser.add_argument(
        "--no-reembed",
        action="store_true",
        help="Skip re-embedding artwork into track files after applying.",
    )
    args = parser.parse_args(argv)

    try:
        app_name = music_app_name()

        if args.batch_missing:
            return run_batch_missing(
                app_name,
                min_score=args.min_score,
                skip_existing=args.skip_if_artwork_exists,
                limit=args.limit,
                dry_run=args.dry_run,
            )

        album = get_selected_album(app_name)
        candidates = list_match_candidates(album, args.min_score)

        if args.list_matches:
            if not candidates:
                print("No matches found.")
                return 1
            if args.json:
                payload = [
                    {
                        "index": index,
                        "score": candidate.score,
                        "resolution": candidate.resolution_label,
                        "source": candidate.source,
                        "artist": candidate.artist,
                        "title": candidate.title,
                        "url": candidate.url,
                        "label": candidate_label(candidate, index),
                    }
                    for index, candidate in enumerate(candidates, start=1)
                ]
                print(json.dumps(payload, indent=2))
                return 0

            print(f"Searching for: {album.artist} — {album.album}\n")
            for index, candidate in enumerate(candidates, start=1):
                print(f"[{candidate.score:.2f}] {candidate_label(candidate, index)}")
            return 0

        updated, chosen = process_album(
            app_name,
            album,
            min_score=args.min_score,
            entire_album=not args.selection_only,
            skip_existing=args.skip_if_artwork_exists,
            apply_index=args.apply_index,
            pick_interactive=args.pick,
            dry_run=args.dry_run,
            preview=args.preview,
            reembed=not args.no_reembed,
        )

        if chosen is None:
            raise RuntimeError("No artwork match was selected.")

        if args.dry_run:
            print(
                f"Would apply: {chosen.artist} — {chosen.title}\n"
                f"Source: {chosen.source}\n"
                f"Resolution: {chosen.resolution_label}\n"
                f"File size: {chosen.size_bytes // 1024} KB\n"
                f"Score: {chosen.score:.2f}\n"
                f"URL: {chosen.url}"
            )
            return 0

        message = (
            f"Applied {chosen.resolution_label} artwork to {updated} track(s).\n"
            f"Match: {chosen.artist} — {chosen.title} ({chosen.source})"
        )
        if not args.no_reembed:
            message += "\nArtwork re-embedded into track files."
        print(message)
        notify(
            "Album artwork updated",
            f"{chosen.resolution_label} art applied to {updated} track(s)",
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Album artwork failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
