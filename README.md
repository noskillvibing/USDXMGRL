# USDXMGRL
# UltraStar Playlist Manager

A simple graphical tool for creating and managing playlists for [UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX) on Linux.

## Disclaimer

This software was created with AI tools and without proper understanding what it does. It is provided "as is", without warranty of any kind, express or implied. Use it at your own risk. The author accepts no responsibility or liability for any loss of data, damage to files (including UltraStar song folders or playlist files), or any other consequences arising from the use of this software. Back up your important playlists before using new tools on them.

## Purpose & Context

UltraStar Deluxe is a free, open-source karaoke game. It uses plain-text playlist files (`.upl`) that list songs by `Artist : Title`. 

This tool lets you browse your song library and build, edit, and save UltraStar `.upl` playlists in a desktop UI.

It was originally built for an UltraStar Deluxe installation from the Flatpak (`eu.usdx.UltraStarDeluxe`), but works with any UltraStar setup — the songs and playlists folders are configurable from the Settings dialog.

### Features

- **Library scanner** — recursively reads `.txt` song files and parses `#ARTIST`, `#TITLE`, `#LANGUAGE`, `#GENRE`, `#EDITION` headers.
- **Search/filter** — fast substring search across all parsed fields, with space-separated terms acting as AND (e.g. `queen rock` matches Queen rock songs only).
- **Two-pane editor** — library on the left, current playlist on the right. Add, remove, reorder, clear.
- **Playlist management** — new, open (via dropdown of existing playlists), save, save-as, rename, delete.
- **Configurable paths** — Settings dialog lets you change the songs and playlists folders; values persist across sessions.
- **Encoding-safe** — reads `.txt` files in UTF-8 (with or without BOM), CP1252, or Latin-1; writes `.upl` files as UTF-8 without BOM and Unix line endings (the format UltraStar Deluxe expects, and which avoids the historical bug where playlists silently dropped songs containing `ä ö ü` or apostrophes).
- **Unsaved-changes protection** — prompts before discarding edits.

## Requirements

- **Python 3.10 or newer** (uses modern type hint syntax)
- **PySide6** (Qt 6 bindings for Python)
- A working UltraStar Deluxe installation (or at least a folder of UltraStar-format `.txt` song files)

Tested on Ubuntu 24.04 with the UltraStar Deluxe Flatpak (`eu.usdx.UltraStarDeluxe`). Should work on any Linux distro, and likely on macOS/Windows too, though those aren't tested.

## Installation

### 1. Install dependencies

```bash
sudo apt install python3 python3-pip
pip install --user PySide6
```
(You may need `pip install --break-system-packages PySide6` or set up a virtual environment — see "Using a virtual environment" below.)

### 2. Download the script

download the .py file:

usdx_playlist_manager.py

### 3. Run it

```bash
python3 usdx_playlist_manager.py
```

On first launch, the tool will look for the UltraStar Deluxe Flatpak default paths:

- Songs: `~/.var/app/eu.usdx.UltraStarDeluxe/.ultrastardx/songs`
- Playlists: `~/.var/app/eu.usdx.UltraStarDeluxe/.ultrastardx/playlists`

If your installation is different (non-Flatpak USDX, custom songs location, etc.), open **File → Settings…** and point it at the right folders. Your choices are saved to `~/.config/usdx-playlist-manager/config.json` and remembered next time.

### Using a virtual environment (recommended for system-package-protected Pythons)

```bash
python3 -m venv ~/.venvs/usdx-playlist-manager
~/.venvs/usdx-playlist-manager/bin/pip install PySide6
~/.venvs/usdx-playlist-manager/bin/python /path/to/usdx_playlist_manager.py
```

## Accessibility from desktop. Add it to the Ubuntu/GNOME application menu

To launch the tool from your Activities/Applications menu like a normal app:

### 1. Put the script somewhere stable

Create bin directory to your home directory, copy the file in to it and make it executable.

```bash
mkdir -p ~/bin
cp usdx_playlist_manager.py ~/bin/
chmod +x ~/bin/usdx_playlist_manager.py
```

### 2. (Optional) Add an icon

Download and save PNG icon as `~/.local/share/icons/usdx-playlist-manager.png`.

### 3. Create a `.desktop` launcher

Create `~/.local/share/applications/usdx-playlist-manager.desktop` with the following content (replace `YOUR_USERNAME` with your actual username):

```ini
[Desktop Entry]
Type=Application
Name=UltraStar Playlist Manager
Comment=Create and manage UltraStar Deluxe playlists
Exec=python3 /home/YOUR_USERNAME/bin/usdx_playlist_manager.py
Icon=/home/YOUR_USERNAME/.local/share/icons/usdx-playlist-manager.png
Terminal=false
Categories=AudioVideo;Music;
StartupNotify=true
Keywords=ultrastar;karaoke;playlist;
```

Then:

```bash
chmod +x ~/.local/share/applications/usdx-playlist-manager.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null
```

The app should now appear in your application menu (search for "ultrastar" or "playlist").

If you installed PySide6 in a virtual environment, replace the `Exec=` line with:

```ini
Exec=/home/YOUR_USERNAME/.venvs/usdx-playlist-manager/bin/python /home/YOUR_USERNAME/bin/usdx_playlist_manager.py
```

## File format notes

UltraStar `.upl` playlist files are plain UTF-8 text:

```
#Name: My Awesome Playlist
#Songs:
Queen : Bohemian Rhapsody
ABBA : Dancing Queen
```

The script always writes them this way (UTF-8 without BOM, Unix line endings). When loading, it tries multiple encodings to handle older or hand-edited files.

## Troubleshooting

**The app launches but the library is empty.**
Open **File → Settings…** and check that the Songs folder is set correctly. Click **Rescan library** (or press F5).

**Some songs from an existing playlist don't show up after loading.**
The tool matches playlist entries to the library by exact `Artist` + `Title` (case-insensitive). If a song's tags have been changed since the playlist was made, it won't match. The warning dialog lists the unmatched entries.

**ImportError: No module named PySide6.**
PySide6 isn't installed for the Python interpreter the script is running with. See the installation steps above; if using a venv, make sure the `.desktop` `Exec=` line points at the venv's Python.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contributing

Issues and pull requests are welcome. The script is intentionally kept as a single file for ease of distribution; please keep that in mind for larger changes.

## Acknowledgements

- The [UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX) project and community for the karaoke game itself.
- The [UltraStar Manager](https://github.com/UltraStar-Deluxe/UltraStar-Manager) and [Yass Reloaded](https://github.com/DoubleDee73/Yass-Reloaded) projects, whose feature sets and format handling were useful references.
