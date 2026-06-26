#!/usr/bin/env python3
"""Detect and combine split album(s) or song(s) in Apple Music."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

from find_artwork import (
    AlbumInfo,
    album_significant_tokens,
    clean_artist_name,
    music_app_name,
    normalize,
    notify,
    run_osascript,
    token_overlap,
)
from find_tags import (
    TrackSnapshot,
    TagChange,
    TrackTags,
    apply_tag_changes,
    build_tag_changes,
    fetch_release_tags,
    format_change,
    get_target_tracks,
    match_tracks,
    parse_track_line,
)
from music_common import ReleaseMatch, choose_release_match, confirm_apply, search_all_releases

FIELD_SEP = "|||"


@dataclass(frozen=True)
class AlbumBucket:
    artist: str
    album: str
    album_artist: str
    tracks: tuple[TrackSnapshot, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.artist, self.album)

    @property
    def label(self) -> str:
        return f"{self.artist} — {self.album} ({len(self.tracks)} song(s))"


@dataclass(frozen=True)
class SplitAlbumGroup:
    base_key: str
    buckets: tuple[AlbumBucket, ...]

    @property
    def all_tracks(self) -> list[TrackSnapshot]:
        return [track for bucket in self.buckets for track in bucket.tracks]

    @property
    def label(self) -> str:
        return " | ".join(bucket.label for bucket in self.buckets)

    def representative_album(self, app_name: str) -> AlbumInfo:
        bucket = max(self.buckets, key=lambda item: len(item.tracks))
        return AlbumInfo(
            artist=bucket.album_artist or bucket.artist,
            album=bucket.album,
            app_name=app_name,
        )


@dataclass(frozen=True)
class DeepDiveRelease:
    release: ReleaseMatch
    confidence: float
    matched_tracks: int
    local_track_count: int
    remote_track_count: int
    evidence: tuple[str, ...]


def normalize_album_base(album: str) -> str:
    text = normalize(album)
    text = re.sub(r"\b(disc|cd|disk|vol|volume|part|side)\s*\d+\b", " ", text)
    text = re.sub(r"\b\d+\s*(cd|disc|disk|lp)\b", " ", text)
    text = re.sub(r"\((deluxe|expanded|bonus|remaster[^)]*)\)", " ", text)
    text = re.sub(r"\[(deluxe|expanded|bonus|remaster[^\]]*)\]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def artists_compatible(left: str, right: str) -> bool:
    left_norm = normalize(clean_artist_name(left))
    right_norm = normalize(clean_artist_name(right))
    if not left_norm or not right_norm:
        return True
    if left_norm == right_norm:
        return True
    if left_norm in {"various artists", "various", "va"} or right_norm in {"various artists", "various", "va"}:
        return True
    return token_overlap(left, right) >= 0.45


def albums_related(left: str, right: str) -> bool:
    left_base = normalize_album_base(left)
    right_base = normalize_album_base(right)
    if left_base and left_base == right_base:
        return True
    if normalize(left) == normalize(right):
        return True
    left_tokens = set(album_significant_tokens(left_base or left))
    right_tokens = set(album_significant_tokens(right_base or right))
    if left_tokens and right_tokens:
        overlap = left_tokens & right_tokens
        if overlap and (overlap == left_tokens or overlap == right_tokens):
            return True
        if len(overlap) / len(left_tokens | right_tokens) >= 0.67:
            return True
    return token_overlap(left, right) >= 0.72


def parse_track_lines(payload: str) -> list[TrackSnapshot]:
    if not payload.strip():
        return []
    return [parse_track_line(line) for line in payload.splitlines() if line.strip()]


def get_all_library_tracks(app_name: str) -> list[TrackSnapshot]:
    script = f'''
tell application "{app_name}"
    set targetTracks to every track of library playlist 1
    if (count of targetTracks) is 0 then
        error "No tracks found in your Music library."
    end if
    set output to {{}}
    repeat with t in targetTracks
        try
            set albumName to album of t
            set artistName to artist of t
            if albumName is missing value or albumName is "" or artistName is missing value or artistName is "" then
                -- skip incomplete rows
            else
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
            end if
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to output as string
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    return parse_track_lines(run_osascript(script))


def get_selected_tracks_only(app_name: str) -> list[TrackSnapshot]:
    return get_target_tracks(app_name, entire_album=False)


def build_album_buckets(tracks: list[TrackSnapshot]) -> list[AlbumBucket]:
    grouped: dict[tuple[str, str], list[TrackSnapshot]] = defaultdict(list)
    for track in tracks:
        grouped[(track.artist, track.album)].append(track)

    buckets: list[AlbumBucket] = []
    for (artist, album), bucket_tracks in grouped.items():
        album_artist = next((track.album_artist for track in bucket_tracks if track.album_artist), artist)
        buckets.append(
            AlbumBucket(
                artist=artist,
                album=album,
                album_artist=album_artist,
                tracks=tuple(bucket_tracks),
            )
        )
    return buckets


def cluster_buckets(buckets: list[AlbumBucket]) -> list[list[AlbumBucket]]:
    clusters: list[list[AlbumBucket]] = []

    for bucket in buckets:
        placed = False
        for cluster in clusters:
            if any(
                albums_related(bucket.album, other.album) and artists_compatible(bucket.artist, other.artist)
                for other in cluster
            ):
                cluster.append(bucket)
                placed = True
                break
        if not placed:
            clusters.append([bucket])

    merged: list[list[AlbumBucket]] = []
    for cluster in clusters:
        absorbed = False
        for existing in merged:
            if any(
                albums_related(left.album, right.album) and artists_compatible(left.artist, right.artist)
                for left in cluster
                for right in existing
            ):
                existing.extend(cluster)
                absorbed = True
                break
        if not absorbed:
            merged.append(cluster)
    return merged


def find_split_groups(tracks: list[TrackSnapshot]) -> list[SplitAlbumGroup]:
    buckets = build_album_buckets(tracks)
    by_base: dict[str, list[AlbumBucket]] = defaultdict(list)
    for bucket in buckets:
        base = normalize_album_base(bucket.album) or normalize(bucket.album)
        if base:
            by_base[base].append(bucket)

    groups: list[SplitAlbumGroup] = []
    seen_group_keys: set[tuple[tuple[str, str], ...]] = set()

    for base, base_buckets in by_base.items():
        clusters = cluster_buckets(base_buckets)
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            cluster_key = tuple(sorted(bucket.key for bucket in cluster))
            if cluster_key in seen_group_keys:
                continue
            seen_group_keys.add(cluster_key)
            groups.append(
                SplitAlbumGroup(
                    base_key=base,
                    buckets=tuple(cluster),
                )
            )

    same_title_groups: dict[str, list[AlbumBucket]] = defaultdict(list)
    for bucket in buckets:
        same_title_groups[normalize(bucket.album)].append(bucket)

    for album_norm, album_buckets in same_title_groups.items():
        if len(album_buckets) < 2:
            continue
        artist_norms = {normalize(clean_artist_name(bucket.artist)) for bucket in album_buckets}
        if len(artist_norms) < 2:
            continue
        cluster_key = tuple(sorted(bucket.key for bucket in album_buckets))
        if cluster_key in seen_group_keys:
            continue
        seen_group_keys.add(cluster_key)
        groups.append(
            SplitAlbumGroup(
                base_key=album_norm,
                buckets=tuple(album_buckets),
            )
        )

    for cluster in cluster_buckets(buckets):
        if len(cluster) < 2:
            continue
        cluster_key = tuple(sorted(bucket.key for bucket in cluster))
        if cluster_key in seen_group_keys:
            continue
        seen_group_keys.add(cluster_key)
        groups.append(
            SplitAlbumGroup(
                base_key=normalize_album_base(cluster[0].album) or normalize(cluster[0].album),
                buckets=tuple(cluster),
            )
        )

    return sorted(groups, key=lambda group: sum(len(bucket.tracks) for bucket in group.buckets), reverse=True)


def groups_for_selection(groups: list[SplitAlbumGroup], selected_tracks: list[TrackSnapshot]) -> list[SplitAlbumGroup]:
    if not selected_tracks:
        return groups

    selected_ids = {track.track_id for track in selected_tracks}
    selected_signatures = {
        (
            normalize(track.title),
            normalize(track.album),
            normalize(clean_artist_name(track.artist)),
        )
        for track in selected_tracks
    }
    matched = []
    for group in groups:
        group_ids = {track.track_id for track in group.all_tracks}
        group_signatures = {
            (
                normalize(track.title),
                normalize(track.album),
                normalize(clean_artist_name(track.artist)),
            )
            for track in group.all_tracks
        }
        if selected_ids & group_ids or selected_signatures & group_signatures:
            matched.append(group)
    return matched


def album_probe_candidates(group: SplitAlbumGroup, app_name: str) -> list[AlbumInfo]:
    probes: list[AlbumInfo] = []
    seen: set[tuple[str, str]] = set()

    def add_probe(artist: str, album: str) -> None:
        key = (normalize(clean_artist_name(artist)), normalize(album))
        if not key[1] or key in seen:
            return
        seen.add(key)
        probes.append(AlbumInfo(artist=artist or "Various Artists", album=album, app_name=app_name))

    representative = group.representative_album(app_name)
    add_probe(representative.artist, representative.album)

    for bucket in group.buckets:
        add_probe(bucket.album_artist or bucket.artist, bucket.album)
        add_probe(bucket.artist, bucket.album)
        add_probe("Various Artists", bucket.album)

        base_album = normalize_album_base(bucket.album)
        if base_album and base_album != normalize(bucket.album):
            add_probe(bucket.album_artist or bucket.artist, base_album)
            add_probe("Various Artists", base_album)

    return probes


def score_release_with_tracks(
    group: SplitAlbumGroup,
    release: ReleaseMatch,
    remote_tracks: list[TrackTags],
) -> DeepDiveRelease:
    local_tracks = group.all_tracks
    pairs = match_tracks(local_tracks, remote_tracks)
    matched_tracks = len(pairs)

    local_count = len(local_tracks)
    remote_count = len(remote_tracks)
    coverage = matched_tracks / max(1, min(local_count, remote_count))
    count_fit = 1.0 - min(abs(remote_count - local_count), max(remote_count, local_count)) / max(
        1,
        max(remote_count, local_count),
    )

    title_scores = []
    for local_track, remote_track in pairs:
        title_scores.append(token_overlap(local_track.title, remote_track.title))
    title_fit = sum(title_scores) / len(title_scores) if title_scores else 0.0

    album_fit = max(token_overlap(bucket.album, release.title) for bucket in group.buckets)
    artist_fit = max(
        token_overlap(bucket.album_artist or bucket.artist, release.artist)
        for bucket in group.buckets
    )
    if normalize(clean_artist_name(release.artist)) in {"various artists", "various", "va"}:
        artist_fit = max(artist_fit, 0.8)

    confidence = (
        release.score * 0.25
        + coverage * 0.32
        + title_fit * 0.2
        + count_fit * 0.13
        + album_fit * 0.07
        + artist_fit * 0.03
    )

    evidence = (
        f"{matched_tracks}/{local_count} selected song(s) matched release tracks",
        f"local/release track count: {local_count}/{remote_count}",
        f"title fit {title_fit:.2f}, album fit {album_fit:.2f}, artist fit {artist_fit:.2f}",
        f"source match score {release.score:.2f} via {release.source}",
    )
    return DeepDiveRelease(
        release=release,
        confidence=min(1.0, confidence),
        matched_tracks=matched_tracks,
        local_track_count=local_count,
        remote_track_count=remote_count,
        evidence=evidence,
    )


def ai_deep_dive_release_match(
    app_name: str,
    group: SplitAlbumGroup,
    min_score: float,
) -> DeepDiveRelease:
    release_candidates: list[ReleaseMatch] = []
    seen_release_ids: set[str] = set()

    for probe in album_probe_candidates(group, app_name):
        for release in search_all_releases(probe, limit=8):
            if release.release_id in seen_release_ids:
                continue
            seen_release_ids.add(release.release_id)
            release_candidates.append(release)

    if not release_candidates:
        raise RuntimeError("Deep dive found no online release candidates for this split album.")

    scored: list[DeepDiveRelease] = []
    for release in release_candidates:
        try:
            remote_tracks = fetch_release_tags(release.release_id)
        except OSError:
            continue
        if not remote_tracks:
            continue
        scored.append(score_release_with_tracks(group, release, remote_tracks))

    if not scored:
        raise RuntimeError("Deep dive found release candidates, but no usable track metadata.")

    best = max(
        scored,
        key=lambda candidate: (
            candidate.confidence,
            candidate.matched_tracks,
            candidate.release.score,
        ),
    )
    if best.confidence < min_score:
        raise RuntimeError(
            "Deep dive found possible matches, but none were confident enough. "
            f"Best guess: {best.release.label} (confidence {best.confidence:.2f})."
        )
    return best


def build_split_resolution_changes(
    group: SplitAlbumGroup,
    release: ReleaseMatch,
) -> list:
    remote_tracks = fetch_release_tags(release.release_id)
    if not remote_tracks:
        raise RuntimeError(f"No track metadata returned for release “{release.title}”.")

    pairs = match_tracks(group.all_tracks, remote_tracks)
    if not pairs:
        raise RuntimeError("Could not match split album song(s) to online metadata.")

    changes = build_tag_changes(pairs)
    if not changes:
        canonical_album = release.title
        canonical_artist = release.artist
        manual_changes = []
        for track in group.all_tracks:
            if track.album == canonical_album and (track.album_artist or track.artist) == canonical_artist:
                continue
            manual_changes.append(
                TagChange(
                    track_id=track.track_id,
                    before=track,
                    after=TrackTags(
                        title=track.title,
                        artist=track.artist,
                        album=canonical_album,
                        album_artist=canonical_artist,
                        track_number=track.track_number,
                        disc_number=track.disc_number,
                        year=track.year,
                        genre=track.genre or None,
                    ),
                )
            )
        return manual_changes
    return changes


def resolve_split_group(
    app_name: str,
    group: SplitAlbumGroup,
    min_score: float,
    pick_interactive: bool,
    dry_run: bool,
    preview: bool,
    release_match: ReleaseMatch | None = None,
    ai_deep_dive: bool = False,
) -> tuple[int, ReleaseMatch, list]:
    deep_dive: DeepDiveRelease | None = None
    if release_match is not None:
        release = release_match
    elif ai_deep_dive:
        deep_dive = ai_deep_dive_release_match(app_name, group, min_score=min_score)
        release = deep_dive.release
    else:
        album = group.representative_album(app_name)
        release = choose_release_match(
            album,
            min_score=min_score,
            pick_interactive=pick_interactive,
        )

    changes = build_split_resolution_changes(group, release)
    if not changes:
        return 0, release, []

    if dry_run:
        return 0, release, changes

    if preview:
        preview_lines = [
            f"Combine split album(s) into {release.artist} — {release.title}:",
            group.label,
            "",
        ]
        if deep_dive is not None:
            preview_lines.append(f"AI deep dive confidence: {deep_dive.confidence:.2f}")
            preview_lines.extend(deep_dive.evidence)
            preview_lines.append("")
        preview_lines.extend([
            f"Update {len(changes)} song(s):",
        ])
        for change in changes[:8]:
            preview_lines.append(format_change(change))
        if len(changes) > 8:
            preview_lines.append(f"... and {len(changes) - 8} more song(s)")
        if not confirm_apply("Preview split album merge", "\n".join(preview_lines)):
            raise RuntimeError("Split album merge cancelled.")

    updated = apply_tag_changes(app_name, changes)
    return updated, release, changes


def resolve_splits(
    app_name: str,
    groups: list[SplitAlbumGroup],
    min_score: float,
    pick_interactive: bool,
    dry_run: bool,
    preview: bool,
    limit: int = 0,
    ai_deep_dive: bool = False,
) -> int:
    if not groups:
        print("No split album(s) found.")
        return 0

    if limit > 0:
        groups = groups[:limit]

    successes = 0
    failures = 0
    for index, group in enumerate(groups, start=1):
        print(f"[{index}/{len(groups)}] {group.label}")
        try:
            updated, release, changes = resolve_split_group(
                app_name,
                group,
                min_score=min_score,
                pick_interactive=pick_interactive,
                dry_run=dry_run,
                preview=preview,
                ai_deep_dive=ai_deep_dive,
            )
            if dry_run:
                if changes:
                    mode = "AI deep dive would combine" if ai_deep_dive else "Would combine"
                    print(f"  {mode} {len(changes)} song(s) into {release.artist} — {release.title}")
                else:
                    print("  Already combined.")
            elif changes:
                mode = "AI deep dive combined" if ai_deep_dive else "Combined"
                print(f"  {mode} {updated} song(s) into {release.artist} — {release.title}")
            else:
                print("  Already combined.")
            successes += 1
        except Exception as exc:  # noqa: BLE001 - batch reporting
            failures += 1
            print(f"  Skipped: {exc}")

    summary = f"Split album resolve finished: {successes} processed, {failures} failed."
    print(f"\n{summary}")
    notify("Split album resolve", summary)
    return 0 if failures == 0 else 1


def auto_resolve_for_selection(
    app_name: str,
    min_score: float = 0.45,
    preview: bool = False,
    dry_run: bool = False,
    ai_deep_dive: bool = False,
) -> bool:
    """Resolve split album(s) touching the current selection. Returns True if anything changed."""
    selected = get_selected_tracks_only(app_name)
    if not selected:
        return False

    library_tracks = get_all_library_tracks(app_name)
    groups = groups_for_selection(find_split_groups(library_tracks), selected)
    if not groups:
        return False

    changed = False
    for group in groups:
        _, _, changes = resolve_split_group(
            app_name,
            group,
            min_score=min_score,
            pick_interactive=False,
            dry_run=dry_run,
            preview=preview,
            ai_deep_dive=ai_deep_dive,
        )
        if changes:
            changed = True
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect and combine split album(s) or song(s) using online metadata."
    )
    parser.add_argument(
        "--library",
        action="store_true",
        help="Scan the Music library for split album(s) instead of using the current selection.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.45,
        help="Minimum album match score required (default: 0.45).",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Choose which online album match to use.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Confirm each merge before applying.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying Music.",
    )
    parser.add_argument(
        "--ai-deep-dive",
        action="store_true",
        help="Use selected song titles, track counts, album variants, and deep search to choose the best merge target.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most this many split album groups (0 = all).",
    )
    args = parser.parse_args(argv)

    try:
        app_name = music_app_name()

        if args.library:
            groups = find_split_groups(get_all_library_tracks(app_name))
        else:
            selected = get_selected_tracks_only(app_name)
            if not selected:
                raise RuntimeError(
                    "No album(s) or song(s) selected. Select album/albums or songs in Music, then run this again."
                )
            groups = groups_for_selection(find_split_groups(get_all_library_tracks(app_name)), selected)

        return resolve_splits(
            app_name,
            groups,
            min_score=args.min_score,
            pick_interactive=args.pick,
            dry_run=args.dry_run,
            preview=args.preview,
            limit=args.limit,
            ai_deep_dive=args.ai_deep_dive,
        )
    except Exception as exc:  # noqa: BLE001 - user-facing CLI tool
        print(f"Error: {exc}", file=sys.stderr)
        notify("Split album resolve failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
