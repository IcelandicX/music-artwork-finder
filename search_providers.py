#!/usr/bin/env python3
"""Deep multi-source search for album artwork and release metadata."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from find_artwork import (
    AlbumInfo,
    ArtworkMatch,
    MUSICBRAINZ_SEARCH_URL,
    USER_AGENT,
    clean_album_name,
    fetch_bytes,
    fetch_json,
    fetch_musicbrainz_json,
    itunes_search_terms,
    musicbrainz_search_queries,
    score_result,
)
from search_cache import load_cache, save_cache


def _release_artist_name(release: dict) -> str:
    credits = release.get("artist-credit") or []
    if not credits:
        return ""
    return credits[0].get("name") or credits[0].get("artist", {}).get("name", "")


DEEZER_SEARCH_URL = "https://api.deezer.com/search/album"
DISCOGS_SEARCH_URL = "https://api.discogs.com/database/search"
LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
GOOGLE_IMAGE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


@dataclass(frozen=True)
class ExternalReleaseHint:
    title: str
    artist: str
    date: str
    track_count: int
    score: float
    source: str


def _request_json(url: str, headers: dict[str, str] | None = None) -> dict:
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)
    request = urllib.request.Request(url, headers=merged_headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _album_search_terms(album: AlbumInfo) -> list[str]:
    terms = list(itunes_search_terms(album))
    cleaned_album = clean_album_name(album.album)
    terms.append(f"{cleaned_album} album cover")
    terms.append(f"{cleaned_album} cover art")

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.casefold()
        if key and key not in seen:
            seen.add(key)
            deduped.append(term)
    return deduped


def search_deezer_artwork(album: AlbumInfo, limit: int = 8) -> list[ArtworkMatch]:
    matches: list[ArtworkMatch] = []
    seen_urls: set[str] = set()

    for term in _album_search_terms(album)[:6]:
        params = urllib.parse.urlencode({"q": term, "limit": limit})
        try:
            payload = _request_json(f"{DEEZER_SEARCH_URL}?{params}")
        except OSError:
            continue

        for item in payload.get("data", []):
            url = item.get("cover_xl") or item.get("cover_big") or item.get("cover_medium")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = item.get("title") or ""
            artist = (item.get("artist") or {}).get("name") or ""
            matches.append(
                ArtworkMatch(
                    source="Deezer",
                    title=title,
                    artist=artist,
                    url=url,
                    score=score_result(album, title, artist),
                )
            )

    return matches


def search_discogs_artwork(album: AlbumInfo, limit: int = 8) -> list[ArtworkMatch]:
    token = os.environ.get("DISCOGS_TOKEN", "").strip()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    matches: list[ArtworkMatch] = []
    seen_urls: set[str] = set()

    for term in _album_search_terms(album)[:5]:
        params = urllib.parse.urlencode(
            {
                "q": term,
                "type": "release",
                "per_page": limit,
            }
        )
        try:
            payload = _request_json(f"{DISCOGS_SEARCH_URL}?{params}", headers=headers)
        except OSError:
            continue

        for item in payload.get("results", []):
            thumb = item.get("cover_image") or item.get("thumb")
            if not thumb or thumb in seen_urls:
                continue
            seen_urls.add(thumb)

            title = item.get("title") or ""
            artist = item.get("artist") or ""
            if " - " in title and not artist:
                artist, title = title.split(" - ", 1)

            matches.append(
                ArtworkMatch(
                    source="Discogs",
                    title=title.strip(),
                    artist=artist.strip(),
                    url=thumb,
                    score=score_result(album, title, artist),
                )
            )

    return matches


def search_lastfm_artwork(album: AlbumInfo, limit: int = 6) -> list[ArtworkMatch]:
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        return []

    matches: list[ArtworkMatch] = []
    seen_urls: set[str] = set()

    for term in _album_search_terms(album)[:4]:
        params = urllib.parse.urlencode(
            {
                "method": "album.search",
                "album": term,
                "api_key": api_key,
                "format": "json",
                "limit": limit,
            }
        )
        try:
            payload = _request_json(f"{LASTFM_API_URL}?{params}")
        except OSError:
            continue

        albums = payload.get("results", {}).get("albummatches", {}).get("album", [])
        if isinstance(albums, dict):
            albums = [albums]

        for item in albums:
            images = item.get("image") or []
            url = ""
            for image in reversed(images):
                if image.get("#text"):
                    url = image["#text"]
                    break
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = item.get("name") or ""
            artist = item.get("artist") or ""
            matches.append(
                ArtworkMatch(
                    source="Last.fm",
                    title=title,
                    artist=artist,
                    url=url,
                    score=score_result(album, title, artist),
                )
            )

    return matches


def _duckduckgo_vqd(query: str) -> str | None:
    params = urllib.parse.urlencode({"q": query, "iax": "images", "ia": "images"})
    try:
        html = fetch_bytes(f"https://duckduckgo.com/?{params}", timeout=20).decode(
            "utf-8", errors="ignore"
        )
    except OSError:
        return None

    match = re.search(r"vqd=['\"]([^'\"]+)['\"]", html)
    if match:
        return match.group(1)
    match = re.search(r"vqd=([\d-]+)&", html)
    return match.group(1) if match else None


def search_duckduckgo_images(album: AlbumInfo, limit: int = 10) -> list[ArtworkMatch]:
    matches: list[ArtworkMatch] = []
    seen_urls: set[str] = set()

    for term in _album_search_terms(album)[:4]:
        vqd = _duckduckgo_vqd(term)
        if not vqd:
            continue

        params = urllib.parse.urlencode(
            {
                "l": "us-en",
                "o": "json",
                "q": term,
                "vqd": vqd,
                "f": ",,,",
                "p": "1",
            }
        )
        try:
            payload = _request_json(f"https://duckduckgo.com/i.js?{params}")
        except OSError:
            continue

        for item in payload.get("results", [])[:limit]:
            url = item.get("image")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = item.get("title") or album.album
            source_label = item.get("source") or "Web"
            matches.append(
                ArtworkMatch(
                    source=f"DuckDuckGo ({source_label})",
                    title=title,
                    artist=album.artist,
                    url=url,
                    score=score_result(album, title, album.artist) * 0.92,
                )
            )

    return matches


def search_google_images(album: AlbumInfo, limit: int = 8) -> list[ArtworkMatch]:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    search_engine_id = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if not api_key or not search_engine_id:
        return []

    matches: list[ArtworkMatch] = []
    seen_urls: set[str] = set()

    for term in _album_search_terms(album)[:4]:
        params = urllib.parse.urlencode(
            {
                "key": api_key,
                "cx": search_engine_id,
                "q": term,
                "searchType": "image",
                "num": min(limit, 10),
                "safe": "active",
            }
        )
        try:
            payload = _request_json(f"{GOOGLE_IMAGE_SEARCH_URL}?{params}")
        except OSError:
            continue

        for item in payload.get("items", []):
            url = item.get("link")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = item.get("title") or album.album
            matches.append(
                ArtworkMatch(
                    source="Google Images",
                    title=title,
                    artist=album.artist,
                    url=url,
                    score=score_result(album, title, album.artist) * 0.9,
                )
            )

    return matches


def search_deezer_release_hints(album: AlbumInfo, limit: int = 8) -> list[ExternalReleaseHint]:
    hints: list[ExternalReleaseHint] = []
    seen: set[tuple[str, str]] = set()

    for term in _album_search_terms(album)[:6]:
        params = urllib.parse.urlencode({"q": term, "limit": limit})
        try:
            payload = _request_json(f"{DEEZER_SEARCH_URL}?{params}")
        except OSError:
            continue

        for item in payload.get("data", []):
            title = item.get("title") or ""
            artist = (item.get("artist") or {}).get("name") or ""
            key = (artist.casefold(), title.casefold())
            if not title or key in seen:
                continue
            seen.add(key)

            hints.append(
                ExternalReleaseHint(
                    title=title,
                    artist=artist,
                    date=(item.get("release_date") or "")[:10],
                    track_count=int(item.get("nb_tracks") or 0),
                    score=score_result(album, title, artist),
                    source="Deezer",
                )
            )

    return hints


def search_discogs_release_hints(album: AlbumInfo, limit: int = 8) -> list[ExternalReleaseHint]:
    token = os.environ.get("DISCOGS_TOKEN", "").strip()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    hints: list[ExternalReleaseHint] = []
    seen: set[tuple[str, str]] = set()

    for term in _album_search_terms(album)[:5]:
        params = urllib.parse.urlencode(
            {
                "q": term,
                "type": "release",
                "per_page": limit,
            }
        )
        try:
            payload = _request_json(f"{DISCOGS_SEARCH_URL}?{params}", headers=headers)
        except OSError:
            continue

        for item in payload.get("results", []):
            title = item.get("title") or ""
            artist = item.get("artist") or ""
            if " - " in title and not artist:
                artist, title = title.split(" - ", 1)
            key = (artist.casefold(), title.casefold())
            if not title or key in seen:
                continue
            seen.add(key)

            year = str(item.get("year") or "")
            hints.append(
                ExternalReleaseHint(
                    title=title.strip(),
                    artist=artist.strip(),
                    date=year,
                    track_count=0,
                    score=score_result(album, title, artist),
                    source="Discogs",
                )
            )

    return hints


def lookup_musicbrainz_release(
    artist: str,
    title: str,
    local_album: AlbumInfo,
    track_count: int = 0,
) -> dict | None:
    probe = AlbumInfo(artist=artist, album=title, app_name=local_album.app_name)
    queries: list[str] = []
    seen_queries: set[str] = set()
    for source_album in (probe, local_album):
        for query in musicbrainz_search_queries(source_album):
            if query not in seen_queries:
                seen_queries.add(query)
                queries.append(query)

    best: dict | None = None
    best_score = 0.0

    for query in queries:
        params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 8})
        try:
            payload = fetch_musicbrainz_json(f"{MUSICBRAINZ_SEARCH_URL}?{params}")
        except OSError:
            continue

        for release in payload.get("releases", []):
            release_title = release.get("title", "")
            release_artist = _release_artist_name(release)
            score = score_result(local_album, release_title, release_artist)
            if track_count:
                remote_count = int(release.get("track-count") or 0)
                if remote_count and abs(remote_count - track_count) <= 1:
                    score = min(1.0, score + 0.08)
                elif remote_count and abs(remote_count - track_count) > 3:
                    score *= 0.85

            if score > best_score:
                best = release
                best_score = score

    if best is None or best_score < 0.4:
        return None
    return best


def dedupe_artwork_matches(matches: list[ArtworkMatch]) -> list[ArtworkMatch]:
    deduped: list[ArtworkMatch] = []
    seen_urls: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()

    for match in sorted(matches, key=lambda item: item.score, reverse=True):
        url_key = match.url.split("?", 1)[0].casefold()
        meta_key = (match.source.casefold(), match.artist.casefold(), match.title.casefold())
        if url_key in seen_urls or meta_key in seen_keys:
            continue
        seen_urls.add(url_key)
        seen_keys.add(meta_key)
        deduped.append(match)

    return deduped


def deep_search_artwork(album: AlbumInfo) -> list[ArtworkMatch]:
    cache_key = f"{album.artist}|{album.album}"
    cached = load_cache("artwork-matches", cache_key)
    if cached is not None:
        return [ArtworkMatch(**item) for item in cached]

    matches: list[ArtworkMatch] = []
    providers = (
        search_deezer_artwork,
        search_discogs_artwork,
        search_lastfm_artwork,
        search_google_images,
        search_duckduckgo_images,
    )
    for provider in providers:
        try:
            matches.extend(provider(album))
        except OSError:
            continue
    result = dedupe_artwork_matches(matches)
    save_cache("artwork-matches", cache_key, [match.__dict__ for match in result])
    return result


def deep_search_release_hints(album: AlbumInfo) -> list[ExternalReleaseHint]:
    hints: list[ExternalReleaseHint] = []
    for provider in (search_deezer_release_hints, search_discogs_release_hints):
        try:
            hints.extend(provider(album))
        except OSError:
            continue

    deduped: list[ExternalReleaseHint] = []
    seen: set[tuple[str, str]] = set()
    for hint in sorted(hints, key=lambda item: item.score, reverse=True):
        key = (hint.artist.casefold(), hint.title.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hint)
    return deduped
