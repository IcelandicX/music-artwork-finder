# Music Fix

Menu bar app and command-line tools for **Apple Music** on macOS. Search online for album artwork and metadata, preview matches, and apply fixes to your library.

![Music Fix icon](assets/app-icon-256.png)

Artwork is fetched from the **iTunes Search API**, **MusicBrainz / Cover Art Archive**, **Deezer**, **Discogs**, **DuckDuckGo image search**, and optional **Google Images**, **Last.fm** when API keys are set. Tags come from **MusicBrainz**, enriched with matches discovered on Deezer and Discogs.

## Requirements

- macOS with **Apple Music** (or legacy iTunes)
- **Python 3** (included with macOS)
- Internet access for metadata and artwork lookups

## Install

### macOS installer (recommended)

**[Download MusicFix-1.1.0.pkg](https://github.com/IcelandicX/music-artwork-finder/releases/download/v1.1.0/MusicFix-1.1.0.pkg)** — open it and follow the prompts.

For other versions, see [GitHub Releases](https://github.com/IcelandicX/music-artwork-finder/releases).

The installer:

- Installs files to `/usr/local/share/music-artwork-finder`
- Adds CLI commands to `/usr/local/bin` (`music-artwork`, `music-tags`, `music-fix`)
- Installs Python dependencies for your user account (`rumps` for the menu bar app)
- Registers a **LaunchAgent** so the **Music Fix** menu bar app starts at login

If macOS warns that the package is from an unidentified developer, open **System Settings → Privacy & Security** and choose **Open Anyway**, or Control-click the `.pkg` and choose **Open**.

To build the installer yourself:

```bash
./packaging/build-pkg.sh
open dist/MusicFix-*.pkg
```

### Install from source

```bash
git clone https://github.com/IcelandicX/music-artwork-finder.git
cd music-artwork-finder
./install.sh
```

The source installer:

- Adds CLI commands to `~/.local/bin` (`music-artwork`, `music-tags`, `music-fix`)
- Installs Python dependencies (`rumps` for the menu bar app)
- Registers a **LaunchAgent** so the **Music Fix** menu bar app starts at login

Open a new terminal (or run `source ~/.zprofile`) so `music-artwork` and related commands are on your `PATH`.

## Permissions

The scripts control Apple Music through AppleScript. The first time you run a command, macOS should prompt for **Automation** access:

1. Open **System Settings → Privacy & Security → Automation**
2. Find **Terminal** (or **Cursor**, if you run commands from there) and enable **Music**

If no prompt appears, run any command once with Music open and selected tracks, then check Automation settings manually.

Music must be **running** when you use these tools. Select album/albums or songs in Music before running a command.

## Menu bar app

After install, look for **Music Fix** in the menu bar (near the clock). If it is missing:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.music-artwork-finder.plist
```

| Menu item | What it does |
| --- | --- |
| **AI All-in-One Fix** | Deep-resolve split album(s), fix tags, find artwork, auto-apply, and save undo metadata |
| **Fix Tags and Artwork** | One MusicBrainz match for both tags and cover art; auto-applies |
| **Find Artwork for Selected Album(s)** | Best artwork match; auto-applies |
| **Choose Artwork...** | Pick from multiple artwork candidates |
| **Preview Artwork Matches** | List top matches without applying |
| **Fix Tags for Selected Album(s)** | Apply MusicBrainz tags automatically |
| **Choose Tags...** | Pick which release metadata to use |
| **Preview Tag Matches** | List tag matches without applying |
| **Resolve Split Album(s)** | Find and combine split album(s) or song(s) under one album; auto-applies |
| **AI Deep Dive Resolve** | Use song-title, track-count, album-variant, and deep-search evidence to pick the best merge; auto-applies |
| **Undo Last Metadata Change** | Restore the previous tags saved before the last tag or split-album change |
| **Fix Missing Artwork** | Batch: up to 20 albums missing artwork |
| **Fix Tags in Library** | Batch: up to 20 albums with incorrect tags |

## Command-line usage

All commands read the current selection in Music unless you use batch modes.

### `music-ai`

Recommended all-in-one workflow. It uses AI-style deep evidence scoring to resolve split album(s), then fixes tags and artwork automatically with undo support.

```bash
music-ai
music-ai --dry-run
music-ai --preview
music-ai --selection-only
music-ai --pick
```

### `music-artwork`

Find and apply album artwork.

```bash
music-artwork                    # apply best match
music-artwork --preview          # open preview, confirm before apply
music-artwork --pick             # choose from a list of matches
music-artwork --list-matches     # print candidates (scores + resolution)
music-artwork --dry-run          # search only, no changes
music-artwork --skip-if-artwork-exists
music-artwork --selection-only   # selected song(s) only, not whole album(s)
music-artwork --batch-missing --limit 20
music-artwork --min-score 0.6    # require stronger title/artist match
```

Use `--no-reembed` to skip writing artwork back into track files after applying it in Music.

### `music-tags`

Fix album metadata (artist, album, year, track numbers, etc.) from MusicBrainz.

```bash
music-tags
music-tags --preview
music-tags --pick
music-tags --list-matches
music-tags --dry-run
music-tags --batch --limit 20
music-tags --selection-only
```

### `music-fix`

Fix **tags and artwork together** using a single MusicBrainz release match (avoids mismatched cover + metadata).

```bash
music-fix
music-fix --preview
music-fix --resolve-splits   # combine split album(s) first, then fix
music-fix --resolve-splits --ai-deep-dive
music-fix --pick
music-fix --tags-only
music-fix --artwork-only
music-fix --dry-run
```

### `music-splits`

Detect and combine split album(s) or song(s) that belong together but have mismatched album or artist tags.

```bash
music-splits
music-splits --preview
music-splits --ai-deep-dive --preview
music-splits --library --limit 20
music-splits --library --ai-deep-dive --limit 20
music-splits --dry-run
music-splits --pick
```

### `music-undo`

Undo the last Music Fix metadata or artwork change. This restores tags saved before `music-tags`, `music-fix`, or `music-splits` wrote changes, and restores previous artwork saved before cover art updates.

```bash
music-undo
music-undo --dry-run
```

Undo history is stored in `~/.music-artwork-finder/undo`.

Legacy alias: `find-album-artwork` → same as `music-artwork`.

## How matching works

- **Deep search** queries multiple services, deduplicates results, ranks them with the same album/artist scoring rules, and caches release/artwork search results for faster repeat runs.
- **Split album resolve** finds song(s) tagged under different album or artist names that belong together, looks up the correct release online, and merges them under one album.
- **AI Deep Dive Resolve** scores candidates using selected song titles, local vs. release track counts, album-title variants, artist and album-artist clues, plus deep-search release matches before choosing a merge target.
- **Artist names** are normalized (parenthetical credits like `Fever Ray (Karin Dreijer Andersson)` are stripped for search).
- **Live albums** are scored carefully so a different venue or city does not win over the correct release.
- **Artwork** prefers metadata match quality over raw pixel size—a high-res wrong cover loses to a correct lower-res match.
- **Artwork is always square**: non-square covers are center-cropped before previewing or applying to Music.
- **Preview** opens the chosen artwork in Preview.app (or shows a confirmation dialog for tags) before anything is written to Music.
- **Undo** saves previous metadata and artwork before writes, then `music-undo` can restore the latest snapshot.
- After applying artwork, tracks are **re-embedded** so cover art is stored in the files, not only in Music’s library database.

### Optional API keys

Deep search works without configuration. For higher rate limits or extra sources, set environment variables before running the tools:

| Variable | Service |
| --- | --- |
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | Google Custom Search (Images) |
| `DISCOGS_TOKEN` | Discogs |
| `LASTFM_API_KEY` | Last.fm |

## Uninstall

```bash
launchctl bootout "gui/$(id -u)/com.music-artwork-finder" 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.music-artwork-finder.plist
rm -f /usr/local/bin/music-artwork /usr/local/bin/find-album-artwork
rm -f /usr/local/bin/music-tags /usr/local/bin/music-fix
sudo rm -rf /usr/local/share/music-artwork-finder
rm -f ~/.local/bin/music-artwork ~/.local/bin/find-album-artwork
rm -f ~/.local/bin/music-tags ~/.local/bin/music-fix
```

Remove the `PATH` line from `~/.zprofile` if you no longer need it.

## Development

```bash
./install.sh                 # re-run after code changes
./packaging/build-pkg.sh     # build dist/MusicFix-<version>.pkg
python3 assets/generate-icons.py  # rebuild icons from assets/icon-source.png
python3 menu_bar.py          # run menu bar app in foreground for debugging
```

## Contributing

Issues and pull requests are welcome on [GitHub](https://github.com/IcelandicX/music-artwork-finder).
