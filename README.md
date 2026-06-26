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

**[Download MusicFix-1.1.4.pkg](https://github.com/IcelandicX/music-artwork-finder/releases/download/v1.1.4/MusicFix-1.1.4.pkg)** — open it and follow the prompts.

For other versions, see [GitHub Releases](https://github.com/IcelandicX/music-artwork-finder/releases).

The installer:

- Installs files to `/usr/local/share/music-artwork-finder`
- Adds CLI commands to `/usr/local/bin` (`music-ai`, `music-artwork`, `music-tags`, `music-fix`, `music-splits`, `music-combine`, `music-undo`, `music-cache`, `music-prefs`, `music-doctor`)
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

- Adds CLI commands to `~/.local/bin` (`music-ai`, `music-artwork`, `music-tags`, `music-fix`, `music-splits`, `music-combine`, `music-undo`, `music-cache`, `music-prefs`, `music-doctor`)
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
| **AI All-in-One Fix** | Deep-resolve split album(s), fix tags, find artwork, show per-album progress, auto-apply confident matches, and save undo metadata |
| **AI All-in-One Preview First** | Run the all-in-one workflow with a confirmation preview before applying |
| **AI All-in-One Dry Run** | Show what would happen without changing Music |
| **Fix Tags and Artwork** | One MusicBrainz match for both tags and cover art; auto-applies |
| **Find Artwork for Selected Album(s)** | Best artwork match; auto-applies |
| **Choose Artwork...** | Pick from multiple artwork candidates |
| **Preview Artwork Matches** | List top matches without applying |
| **Fix Tags for Selected Album(s)** | Apply MusicBrainz tags automatically |
| **Choose Tags...** | Pick which release metadata to use |
| **Preview Tag Matches** | List tag matches without applying |
| **Resolve Split Album(s)** | Find and combine split album(s) or song(s) under one album; auto-applies |
| **AI Deep Dive Resolve** | Use song-title, track-count, album-variant, and deep-search evidence to pick the best merge; auto-applies |
| **Smart Combine Main + Remix Album** | Combine selected related albums into one multi-disc album, e.g. main album as disc 1 and remixes as disc 2 |
| **Smart Combine: Choose Main...** | Pick which selected album becomes disc 1 before combining |
| **Smart Combine with Main Artwork** | Combine and copy the main album artwork to moved remix/bonus tracks |
| **Undo Last Metadata Change** | Restore the previous tags or artwork; grouped all-in-one runs undo together |
| **Open Last Fix Report** | Open the latest text report from an all-in-one run |
| **Clear AI Search Cache** | Remove cached release, artwork, and tracklist search results |
| **Fix Missing Artwork** | Batch: up to 20 albums missing artwork |
| **Fix Tags in Library** | Batch: up to 20 albums with incorrect tags |
| **Preferences** | Show saved defaults such as run mode and confidence threshold |
| **Run Setup Check** | Check CLI links, menu bar LaunchAgent, Music automation, internet, API keys, cache, and preferences |

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
music-ai --confirm-below 0.7
music-ai --auto-apply
```

AI All-in-One prints progress for each selected album and writes a text report to `~/.music-artwork-finder/reports`. If a release or artwork match is below the confidence threshold, it asks before applying even though auto-apply is the default.

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

### `music-combine`

Combine selected related albums into one multi-disc album. For example, select `Fever Ray` and `Remixes`; the tool keeps `Fever Ray` as disc 1 and moves the remix album to disc 2 under the same album title.

```bash
music-combine              # preview first, then confirm
music-combine --dry-run
music-combine --yes        # apply without confirmation
music-combine --pick-main
music-combine --main-album "Fever Ray"
music-combine --album "Fever Ray"
music-combine --name-mode deluxe
music-combine --name-mode plus
music-combine --inherit-artwork
music-combine --renumber   # optional: renumber each disc from 1
```

Smart Combine warns about duplicate-looking track titles before applying and writes the latest combine report to `~/.music-artwork-finder/reports/latest-smart-combine.txt`.

### `music-undo`

Undo the last Music Fix metadata or artwork change. This restores tags saved before `music-tags`, `music-fix`, or `music-splits` wrote changes, and restores previous artwork saved before cover art updates.

```bash
music-undo
music-undo --dry-run
```

Undo history is stored in `~/.music-artwork-finder/undo`. Multi-album all-in-one runs are grouped so one undo restores the latest run together.

### `music-cache`

Inspect or clear cached AI search results.

```bash
music-cache status
music-cache clear
music-cache clear --namespace release-tags
```

### `music-prefs`

Inspect or change saved defaults used by `music-ai`.

```bash
music-prefs show
music-prefs set run_mode preview
music-prefs set confirm_below 0.7
music-prefs set selection_only true
music-prefs reset
```

Valid run modes are `auto`, `preview`, and `dry-run`.

### `music-doctor`

Run first-use diagnostics.

```bash
music-doctor
```

Legacy alias: `find-album-artwork` → same as `music-artwork`.

## How matching works

- **Deep search** queries multiple services, deduplicates results, ranks them with the same album/artist scoring rules, and caches release/artwork/tracklist results for faster repeat runs.
- **Split album resolve** finds song(s) tagged under different album or artist names that belong together, looks up the correct release online, and merges them under one album.
- **Smart Combine** turns related selected albums into one multi-disc album while preserving track titles and artists, warning about duplicate-looking titles and optionally copying the main album artwork.
- **Fast AI mode** only fetches related album candidates around the current selection instead of scanning every track in the library.
- **Low-confidence safety** asks for confirmation before auto-applying weaker all-in-one matches.
- **Preferences** store saved defaults in `~/.music-artwork-finder/preferences.json`.
- **Fix reports** summarize all-in-one runs and include retry/undo hints.
- **AI Deep Dive Resolve** scores candidates using selected song titles, local vs. release track counts, album-title variants, artist and album-artist clues, plus deep-search release matches before choosing a merge target.
- **Artist names** are normalized (parenthetical credits like `Fever Ray (Karin Dreijer Andersson)` are stripped for search).
- **Live albums** are scored carefully so a different venue or city does not win over the correct release.
- **Artwork** prefers metadata match quality over raw pixel size—a high-res wrong cover loses to a correct lower-res match.
- **Artwork is always square**: non-square covers are center-cropped before previewing or applying to Music.
- **Preview** opens the chosen artwork in Preview.app (or shows a confirmation dialog for tags) before anything is written to Music.
- **Undo** saves previous metadata and artwork before writes, then `music-undo` can restore the latest snapshot or grouped all-in-one run.
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
rm -f /usr/local/bin/music-ai /usr/local/bin/music-splits /usr/local/bin/music-combine /usr/local/bin/music-undo /usr/local/bin/music-cache
rm -f /usr/local/bin/music-prefs /usr/local/bin/music-doctor
sudo rm -rf /usr/local/share/music-artwork-finder
rm -f ~/.local/bin/music-artwork ~/.local/bin/find-album-artwork
rm -f ~/.local/bin/music-tags ~/.local/bin/music-fix
rm -f ~/.local/bin/music-ai ~/.local/bin/music-splits ~/.local/bin/music-combine ~/.local/bin/music-undo ~/.local/bin/music-cache
rm -f ~/.local/bin/music-prefs ~/.local/bin/music-doctor
```

Remove the `PATH` line from `~/.zprofile` if you no longer need it.

## Development

```bash
./install.sh                 # re-run after code changes
./packaging/build-pkg.sh     # build dist/MusicFix-<version>.pkg
./scripts/tag-release.sh     # tag v<VERSION> and trigger release packaging
python3 assets/generate-icons.py  # rebuild icons from assets/icon-source.png
python3 menu_bar.py          # run menu bar app in foreground for debugging
```

Pushing a `v*` tag creates a GitHub release and uploads the matching `.pkg`.

## Contributing

Issues and pull requests are welcome on [GitHub](https://github.com/IcelandicX/music-artwork-finder).
