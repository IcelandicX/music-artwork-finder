# Music Fix

Menu bar app and command-line tools for **Apple Music** on macOS. Search online for album artwork and metadata, preview matches, and apply fixes to your library.

![Music Fix icon](assets/app-icon-256.png)

Artwork is fetched from the **iTunes Search API** (high-resolution covers) with a **MusicBrainz / Cover Art Archive** fallback. Tags come from **MusicBrainz**.

## Requirements

- macOS with **Apple Music** (or legacy iTunes)
- **Python 3** (included with macOS)
- Internet access for metadata and artwork lookups

## Install

### macOS installer (recommended)

Download the latest `MusicFix-*.pkg` from [GitHub Releases](https://github.com/Icelandick/music-artwork-finder/releases), open it, and follow the prompts.

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
git clone https://github.com/Icelandick/music-artwork-finder.git
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

Music must be **running** when you use these tools. Select one or more tracks from an album—or select an album in the Albums view—before running a command.

## Menu bar app

After install, look for **Music Fix** in the menu bar (near the clock). If it is missing:

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.music-artwork-finder.plist
```

| Menu item | What it does |
| --- | --- |
| **Fix Tags and Artwork** | One MusicBrainz match for both tags and cover art; preview before apply |
| **Find Artwork for Selected Album** | Best artwork match with preview |
| **Choose Artwork...** | Pick from multiple artwork candidates |
| **Preview Artwork Matches** | List top matches without applying |
| **Fix Tags for Selected Album** | Apply MusicBrainz tags with confirmation |
| **Choose Tags...** | Pick which release metadata to use |
| **Preview Tag Matches** | List tag matches without applying |
| **Fix Missing Artwork** | Batch: up to 20 albums missing artwork |
| **Fix Tags in Library** | Batch: up to 20 albums with incorrect tags |

## Command-line usage

All commands read the current selection in Music unless you use batch modes.

### `music-artwork`

Find and apply album artwork.

```bash
music-artwork                    # apply best match
music-artwork --preview          # open preview, confirm before apply
music-artwork --pick             # choose from a list of matches
music-artwork --list-matches     # print candidates (scores + resolution)
music-artwork --dry-run          # search only, no changes
music-artwork --skip-if-artwork-exists
music-artwork --selection-only   # selected tracks only, not whole album
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
music-fix --pick
music-fix --tags-only
music-fix --artwork-only
music-fix --dry-run
```

Legacy alias: `find-album-artwork` → same as `music-artwork`.

## How matching works

- **Artist names** are normalized (parenthetical credits like `Fever Ray (Karin Dreijer Andersson)` are stripped for search).
- **Live albums** are scored carefully so a different venue or city does not win over the correct release.
- **Artwork** prefers metadata match quality over raw pixel size—a high-res wrong cover loses to a correct lower-res match.
- **Preview** opens the chosen artwork in Preview.app (or shows a confirmation dialog for tags) before anything is written to Music.
- After applying artwork, tracks are **re-embedded** so cover art is stored in the files, not only in Music’s library database.

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

Issues and pull requests are welcome on [GitHub](https://github.com/Icelandick/music-artwork-finder).
