#!/usr/bin/env python3
"""
UltraStar Deluxe Playlist Manager
A GUI tool for creating and managing UltraStar Deluxe playlists.

Songs folder:    ~/.var/app/eu.usdx.UltraStarDeluxe/.ultrastardx/songs
Playlist folder: ~/.var/app/eu.usdx.UltraStarDeluxe/.ultrastardx/playlists
"""

import os
import sys
import re
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt, QSortFilterProxyModel, QAbstractListModel, QModelIndex, Signal
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QListView, QLineEdit, QPushButton, QLabel, QMessageBox, QInputDialog,
    QFileDialog, QStatusBar, QToolBar, QComboBox, QStyle, QAbstractItemView,
    QDialog, QDialogButtonBox, QFormLayout,
)


# -------- Paths --------------------------------------------------------------
HOME = Path.home()
USDX_BASE = HOME / ".var/app/eu.usdx.UltraStarDeluxe/.ultrastardx"
DEFAULT_SONGS_DIR = USDX_BASE / "songs"
DEFAULT_PLAYLISTS_DIR = USDX_BASE / "playlists"

# Config file — follow XDG; fall back to ~/.config
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "usdx-playlist-manager"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """Load saved paths (or defaults if no config exists / it's broken)."""
    cfg = {
        "songs_dir": str(DEFAULT_SONGS_DIR),
        "playlists_dir": str(DEFAULT_PLAYLISTS_DIR),
    }
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if isinstance(data.get("songs_dir"), str):
                    cfg["songs_dir"] = data["songs_dir"]
                if isinstance(data.get("playlists_dir"), str):
                    cfg["playlists_dir"] = data["playlists_dir"]
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    """Persist paths. Best-effort — never crashes the app."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


# -------- Data model ---------------------------------------------------------
@dataclass
class Song:
    """One UltraStar song parsed from a .txt header."""
    artist: str
    title: str
    language: str = ""
    genre: str = ""
    edition: str = ""
    txt_path: Path = field(default_factory=Path)

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def playlist_line(self) -> str:
        """Format used inside .upl files: 'Artist : Title'."""
        return f"{self.artist} : {self.title}"

    @property
    def search_blob(self) -> str:
        return f"{self.artist} {self.title} {self.language} {self.genre} {self.edition}".lower()


# -------- Song scanner -------------------------------------------------------
HEADER_RE = re.compile(r"^#([A-Z0-9_]+)\s*:\s*(.*?)\s*$")

# Tags that indicate the header section has ended.
NOTE_PREFIXES = (":", "*", "F", "R", "G", "-", "P", "E")


def parse_song_txt(path: Path) -> Optional[Song]:
    """Parse just the header of an UltraStar .txt file."""
    # USDX files are usually UTF-8 (sometimes with BOM) but legacy ones may be
    # CP1252 / latin-1. Try in order, fall back to latin-1 which never fails.
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=enc) as f:
                lines = []
                for line in f:
                    if not line.startswith("#"):
                        # First non-header line ends the header
                        if line and line[0] in NOTE_PREFIXES:
                            break
                        # Blank lines inside header are tolerated
                        if line.strip() == "":
                            continue
                        break
                    lines.append(line)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    tags = {}
    for line in lines:
        m = HEADER_RE.match(line)
        if m:
            tags[m.group(1).upper()] = m.group(2)

    artist = tags.get("ARTIST", "").strip()
    title = tags.get("TITLE", "").strip()
    if not artist or not title:
        return None

    return Song(
        artist=artist,
        title=title,
        language=tags.get("LANGUAGE", "").strip(),
        genre=tags.get("GENRE", "").strip(),
        edition=tags.get("EDITION", "").strip(),
        txt_path=path,
    )


def scan_songs(songs_dir: Path) -> list[Song]:
    """Walk songs_dir recursively and parse every .txt file."""
    songs: list[Song] = []
    if not songs_dir.exists():
        return songs

    for txt in songs_dir.rglob("*.txt"):
        # Skip duet alternate files only if there's a base file too?
        # USDX treats every .txt as its own entry, so we do the same.
        try:
            song = parse_song_txt(txt)
            if song:
                songs.append(song)
        except Exception:
            # Bad file — just skip it, don't crash the whole scan
            continue

    songs.sort(key=lambda s: (s.artist.lower(), s.title.lower()))
    return songs


# -------- Playlist I/O -------------------------------------------------------
def read_playlist(path: Path) -> tuple[str, list[tuple[str, str]]]:
    """
    Read a .upl file. Returns (display_name, [(artist, title), ...]).
    UltraStar .upl format:
        #Name: Playlist Display Name
        #Songs:
        Artist : Title
        Artist : Title
        ...
    """
    name = path.stem
    entries: list[tuple[str, str]] = []
    if not path.exists():
        return name, entries

    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            content = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return name, entries

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("#name:"):
            name = line.split(":", 1)[1].strip() or name
            continue
        if line.startswith("#"):
            # Other headers like #Songs: — skip
            continue
        if ":" in line:
            artist, title = line.split(":", 1)
            entries.append((artist.strip(), title.strip()))

    return name, entries


def write_playlist(path: Path, display_name: str, songs: list[Song]) -> None:
    """Write a .upl file in UltraStar Deluxe format (UTF-8, no BOM)."""
    lines = [f"#Name: {display_name}", "#Songs:"]
    for s in songs:
        lines.append(s.playlist_line)
    # No BOM, Unix line endings — what USDX expects
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_filename(name: str) -> str:
    """Make a filename safe for the filesystem."""
    cleaned = re.sub(r"[^\w\-. ()]", "_", name).strip()
    return cleaned or "playlist"


# -------- Qt models ----------------------------------------------------------
class SongListModel(QAbstractListModel):
    """Model holding the master song library."""

    def __init__(self, songs: list[Song] | None = None):
        super().__init__()
        self._songs: list[Song] = songs or []

    def set_songs(self, songs: list[Song]):
        self.beginResetModel()
        self._songs = songs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._songs)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        s = self._songs[index.row()]
        if role == Qt.DisplayRole:
            extra = f"  [{s.language}]" if s.language else ""
            return f"{s.display}{extra}"
        if role == Qt.UserRole:
            return s
        if role == Qt.ToolTipRole:
            return f"{s.artist}\n{s.title}\n{s.txt_path}"
        return None


class SongFilterProxy(QSortFilterProxyModel):
    """Case-insensitive substring filter across artist/title/language/genre."""

    def __init__(self):
        super().__init__()
        self._needle = ""

    def set_needle(self, text: str):
        self._needle = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._needle:
            return True
        idx = self.sourceModel().index(source_row, 0, source_parent)
        song: Song = self.sourceModel().data(idx, Qt.UserRole)
        if song is None:
            return True
        # AND across whitespace-separated terms — easier filtering
        terms = self._needle.split()
        return all(t in song.search_blob for t in terms)


class PlaylistModel(QAbstractListModel):
    """Ordered list of Songs in the current playlist (right pane)."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self._items: list[Song] = []

    def items(self) -> list[Song]:
        return list(self._items)

    def set_items(self, songs: list[Song]):
        self.beginResetModel()
        self._items = list(songs)
        self.endResetModel()
        self.changed.emit()

    def add_song(self, song: Song, allow_duplicates: bool = False):
        if not allow_duplicates and any(
            s.txt_path == song.txt_path for s in self._items
        ):
            return False
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items))
        self._items.append(song)
        self.endInsertRows()
        self.changed.emit()
        return True

    def remove_rows(self, rows: list[int]):
        for r in sorted(rows, reverse=True):
            self.beginRemoveRows(QModelIndex(), r, r)
            del self._items[r]
            self.endRemoveRows()
        self.changed.emit()

    def move_rows(self, rows: list[int], delta: int):
        if not rows or delta == 0:
            return
        rows = sorted(rows, reverse=(delta > 0))
        for r in rows:
            new_r = r + delta
            if 0 <= new_r < len(self._items):
                self._items[r], self._items[new_r] = self._items[new_r], self._items[r]
        self.layoutChanged.emit()
        self.changed.emit()

    def clear(self):
        if not self._items:
            return
        self.beginResetModel()
        self._items = []
        self.endResetModel()
        self.changed.emit()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        s = self._items[index.row()]
        if role == Qt.DisplayRole:
            return f"{index.row() + 1:>3}. {s.display}"
        if role == Qt.UserRole:
            return s
        if role == Qt.ToolTipRole:
            return str(s.txt_path)
        return None


# -------- Settings dialog ----------------------------------------------------
class SettingsDialog(QDialog):
    """Edit the songs and playlists folder locations."""

    def __init__(self, parent, songs_dir: Path, playlists_dir: Path):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)

        self._songs_edit = QLineEdit(str(songs_dir))
        self._playlists_edit = QLineEdit(str(playlists_dir))

        songs_row = self._path_row(self._songs_edit, "Choose songs folder")
        playlists_row = self._path_row(self._playlists_edit, "Choose playlists folder")

        form = QFormLayout()
        form.addRow("Songs folder:", songs_row)
        form.addRow("Playlists folder:", playlists_row)

        # Reset-to-defaults button
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._reset_defaults)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.addButton(reset_btn, QDialogButtonBox.ResetRole)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        hint = QLabel(
            "Defaults are the UltraStar Deluxe Flatpak folders.\n"
            "Changes take effect after you click OK; the library will be rescanned."
        )
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _path_row(self, edit: QLineEdit, dialog_title: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse(edit, dialog_title))
        h.addWidget(browse)
        return w

    def _browse(self, edit: QLineEdit, title: str):
        start = edit.text().strip() or str(HOME)
        chosen = QFileDialog.getExistingDirectory(self, title, start)
        if chosen:
            edit.setText(chosen)

    def _reset_defaults(self):
        self._songs_edit.setText(str(DEFAULT_SONGS_DIR))
        self._playlists_edit.setText(str(DEFAULT_PLAYLISTS_DIR))

    def values(self) -> tuple[Path, Path]:
        return (
            Path(self._songs_edit.text().strip()).expanduser(),
            Path(self._playlists_edit.text().strip()).expanduser(),
        )


# -------- Main window --------------------------------------------------------
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("UltraStar Playlist Manager")
        self.resize(1200, 720)

        # Load configured paths
        cfg = load_config()
        self.songs_dir: Path = Path(cfg["songs_dir"]).expanduser()
        self.playlists_dir: Path = Path(cfg["playlists_dir"]).expanduser()

        self.songs: list[Song] = []
        self.song_index: dict[tuple[str, str], Song] = {}  # (artist_lower, title_lower) -> Song
        self.current_playlist_path: Optional[Path] = None
        self.current_playlist_name: str = ""
        self.dirty: bool = False

        self._build_ui()
        self._build_menu()
        self._refresh_playlist_combo()
        self.scan_library()

    # ---- UI construction ----
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # Top toolbar — playlist selector
        topbar = QHBoxLayout()
        topbar.addWidget(QLabel("Playlist:"))
        self.playlist_combo = QComboBox()
        self.playlist_combo.setMinimumWidth(260)
        self.playlist_combo.activated.connect(self._on_combo_activated)
        topbar.addWidget(self.playlist_combo)

        self.btn_new = QPushButton("New")
        self.btn_new.clicked.connect(self.new_playlist)
        topbar.addWidget(self.btn_new)

        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.save_playlist)
        topbar.addWidget(self.btn_save)

        self.btn_save_as = QPushButton("Save As…")
        self.btn_save_as.clicked.connect(self.save_playlist_as)
        topbar.addWidget(self.btn_save_as)

        self.btn_rename = QPushButton("Rename")
        self.btn_rename.clicked.connect(self.rename_playlist)
        topbar.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.delete_playlist)
        topbar.addWidget(self.btn_delete)

        topbar.addStretch(1)

        self.btn_rescan = QPushButton("Rescan library")
        self.btn_rescan.clicked.connect(self.scan_library)
        topbar.addWidget(self.btn_rescan)

        root.addLayout(topbar)

        # Splitter: library | playlist
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # ---- Left: library ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search artist, title, language… (space = AND)")
        self.search_edit.textChanged.connect(self._on_search_changed)
        left_layout.addWidget(self.search_edit)

        self.library_label = QLabel("Library")
        left_layout.addWidget(self.library_label)

        self.library_view = QListView()
        self.library_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.library_view.setUniformItemSizes(True)
        self.library_view.doubleClicked.connect(self._on_library_double_clicked)

        self.library_model = SongListModel()
        self.library_proxy = SongFilterProxy()
        self.library_proxy.setSourceModel(self.library_model)
        self.library_view.setModel(self.library_proxy)
        left_layout.addWidget(self.library_view, 1)

        # Add buttons
        add_row = QHBoxLayout()
        self.btn_add = QPushButton("Add to playlist  →")
        self.btn_add.clicked.connect(self.add_selected_to_playlist)
        add_row.addWidget(self.btn_add)
        left_layout.addLayout(add_row)

        splitter.addWidget(left)

        # ---- Right: playlist ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.playlist_label = QLabel("(unsaved playlist)")
        f = self.playlist_label.font()
        f.setBold(True)
        self.playlist_label.setFont(f)
        right_layout.addWidget(self.playlist_label)

        self.playlist_view = QListView()
        self.playlist_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.playlist_view.setUniformItemSizes(True)

        self.playlist_model = PlaylistModel()
        self.playlist_model.changed.connect(self._on_playlist_changed)
        self.playlist_view.setModel(self.playlist_model)
        right_layout.addWidget(self.playlist_view, 1)

        # Order / remove buttons
        ctrl_row = QHBoxLayout()
        self.btn_up = QPushButton("▲ Up")
        self.btn_up.clicked.connect(lambda: self._move_selected(-1))
        ctrl_row.addWidget(self.btn_up)

        self.btn_down = QPushButton("▼ Down")
        self.btn_down.clicked.connect(lambda: self._move_selected(+1))
        ctrl_row.addWidget(self.btn_down)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self.remove_selected_from_playlist)
        ctrl_row.addWidget(self.btn_remove)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear_playlist)
        ctrl_row.addWidget(self.btn_clear)

        right_layout.addLayout(ctrl_row)

        splitter.addWidget(right)
        splitter.setSizes([700, 500])

        # Status bar
        self.setStatusBar(QStatusBar())

    def _build_menu(self):
        m = self.menuBar()
        file_menu = m.addMenu("&File")

        a_new = QAction("&New playlist", self)
        a_new.setShortcut(QKeySequence.New)
        a_new.triggered.connect(self.new_playlist)
        file_menu.addAction(a_new)

        a_save = QAction("&Save playlist", self)
        a_save.setShortcut(QKeySequence.Save)
        a_save.triggered.connect(self.save_playlist)
        file_menu.addAction(a_save)

        a_save_as = QAction("Save &As…", self)
        a_save_as.setShortcut(QKeySequence.SaveAs)
        a_save_as.triggered.connect(self.save_playlist_as)
        file_menu.addAction(a_save_as)

        file_menu.addSeparator()

        a_rescan = QAction("&Rescan library", self)
        a_rescan.setShortcut("F5")
        a_rescan.triggered.connect(self.scan_library)
        file_menu.addAction(a_rescan)

        a_settings = QAction("&Settings…", self)
        a_settings.setShortcut("Ctrl+,")
        a_settings.triggered.connect(self.open_settings)
        file_menu.addAction(a_settings)

        file_menu.addSeparator()

        a_quit = QAction("&Quit", self)
        a_quit.setShortcut(QKeySequence.Quit)
        a_quit.triggered.connect(self.close)
        file_menu.addAction(a_quit)

        help_menu = m.addMenu("&Help")
        a_about = QAction("&About", self)
        a_about.triggered.connect(self._about)
        help_menu.addAction(a_about)

    # ---- Library scanning ----
    def scan_library(self):
        self.statusBar().showMessage("Scanning songs…")
        QApplication.processEvents()

        if not self.songs_dir.exists():
            QMessageBox.warning(
                self,
                "Songs folder not found",
                f"Could not find:\n{self.songs_dir}\n\n"
                "Open Settings (File → Settings) to choose the correct folder.",
            )
            self.statusBar().showMessage("Songs folder missing.")
            self.songs = []
            self.song_index = {}
            self.library_model.set_songs(self.songs)
            self.library_label.setText("Library — 0 songs")
            return

        self.songs = scan_songs(self.songs_dir)
        self.song_index = {
            (s.artist.lower(), s.title.lower()): s for s in self.songs
        }
        self.library_model.set_songs(self.songs)
        self.library_label.setText(f"Library — {len(self.songs)} songs")
        self.statusBar().showMessage(f"Found {len(self.songs)} songs in {self.songs_dir}")

    # ---- Playlist combo ----
    def _refresh_playlist_combo(self):
        self.playlist_combo.blockSignals(True)
        self.playlist_combo.clear()
        self.playlist_combo.addItem("— select a playlist —", userData=None)
        if self.playlists_dir.exists():
            for upl in sorted(self.playlists_dir.glob("*.upl")):
                self.playlist_combo.addItem(upl.stem, userData=upl)
        self.playlist_combo.blockSignals(False)

    def _on_combo_activated(self, idx: int):
        path = self.playlist_combo.itemData(idx)
        if path is None:
            return
        if not self._confirm_discard():
            # Reset combo to current selection
            self._select_combo_for_path(self.current_playlist_path)
            return
        self.load_playlist(Path(path))

    def _select_combo_for_path(self, path: Optional[Path]):
        self.playlist_combo.blockSignals(True)
        if path is None:
            self.playlist_combo.setCurrentIndex(0)
        else:
            for i in range(self.playlist_combo.count()):
                if self.playlist_combo.itemData(i) == path:
                    self.playlist_combo.setCurrentIndex(i)
                    break
        self.playlist_combo.blockSignals(False)

    # ---- Playlist actions ----
    def new_playlist(self):
        if not self._confirm_discard():
            return
        self.playlist_model.clear()
        self.current_playlist_path = None
        self.current_playlist_name = ""
        self.dirty = False
        self._update_playlist_label()
        self._select_combo_for_path(None)

    def load_playlist(self, path: Path):
        name, entries = read_playlist(path)
        resolved: list[Song] = []
        missing: list[str] = []
        for artist, title in entries:
            key = (artist.lower(), title.lower())
            song = self.song_index.get(key)
            if song:
                resolved.append(song)
            else:
                missing.append(f"{artist} : {title}")

        self.playlist_model.set_items(resolved)
        self.current_playlist_path = path
        self.current_playlist_name = name
        self.dirty = False
        self._update_playlist_label()
        self._select_combo_for_path(path)

        if missing:
            QMessageBox.warning(
                self,
                "Some songs not found",
                f"{len(missing)} entries in this playlist couldn't be matched "
                f"to songs in your library:\n\n" + "\n".join(missing[:20])
                + ("\n…" if len(missing) > 20 else "")
                + "\n\nThey will not be saved if you save this playlist.",
            )

    def save_playlist(self):
        if self.current_playlist_path is None:
            return self.save_playlist_as()
        self._do_save(self.current_playlist_path, self.current_playlist_name)

    def save_playlist_as(self):
        default = self.current_playlist_name or "New Playlist"
        name, ok = QInputDialog.getText(
            self, "Save playlist as", "Playlist name:", text=default
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        path = self.playlists_dir / f"{safe_filename(name)}.upl"
        if path.exists() and path != self.current_playlist_path:
            r = QMessageBox.question(
                self,
                "Overwrite?",
                f"A playlist file '{path.name}' already exists. Overwrite it?",
            )
            if r != QMessageBox.Yes:
                return
        self._do_save(path, name)
        self._refresh_playlist_combo()
        self._select_combo_for_path(path)

    def _do_save(self, path: Path, display_name: str):
        try:
            self.playlists_dir.mkdir(parents=True, exist_ok=True)
            write_playlist(path, display_name, self.playlist_model.items())
        except OSError as e:
            QMessageBox.critical(self, "Save failed", f"Could not save playlist:\n{e}")
            return
        self.current_playlist_path = path
        self.current_playlist_name = display_name
        self.dirty = False
        self._update_playlist_label()
        self.statusBar().showMessage(f"Saved {path}", 5000)

    def rename_playlist(self):
        if self.current_playlist_path is None:
            QMessageBox.information(
                self, "Rename", "Save the playlist first, then you can rename it."
            )
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename playlist", "New name:", text=self.current_playlist_name
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        new_path = self.playlists_dir / f"{safe_filename(new_name)}.upl"
        if new_path != self.current_playlist_path and new_path.exists():
            QMessageBox.warning(
                self, "Rename failed", f"A playlist '{new_path.name}' already exists."
            )
            return
        try:
            # Write under new name and remove old file
            write_playlist(new_path, new_name, self.playlist_model.items())
            if new_path != self.current_playlist_path:
                self.current_playlist_path.unlink(missing_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Rename failed", str(e))
            return
        self.current_playlist_path = new_path
        self.current_playlist_name = new_name
        self.dirty = False
        self._refresh_playlist_combo()
        self._select_combo_for_path(new_path)
        self._update_playlist_label()

    def delete_playlist(self):
        if self.current_playlist_path is None:
            return
        r = QMessageBox.question(
            self,
            "Delete playlist",
            f"Delete '{self.current_playlist_name}'?\n\nFile: {self.current_playlist_path}",
        )
        if r != QMessageBox.Yes:
            return
        try:
            self.current_playlist_path.unlink()
        except OSError as e:
            QMessageBox.critical(self, "Delete failed", str(e))
            return
        self.current_playlist_path = None
        self.current_playlist_name = ""
        self.playlist_model.clear()
        self.dirty = False
        self._refresh_playlist_combo()
        self._select_combo_for_path(None)
        self._update_playlist_label()

    # ---- Library/playlist interactions ----
    def _on_search_changed(self, text: str):
        self.library_proxy.set_needle(text)

    def _on_library_double_clicked(self, proxy_index):
        src = self.library_proxy.mapToSource(proxy_index)
        song: Song = self.library_model.data(src, Qt.UserRole)
        if song:
            self.playlist_model.add_song(song)

    def add_selected_to_playlist(self):
        added = 0
        skipped = 0
        for proxy_idx in self.library_view.selectionModel().selectedIndexes():
            src = self.library_proxy.mapToSource(proxy_idx)
            song: Song = self.library_model.data(src, Qt.UserRole)
            if song:
                if self.playlist_model.add_song(song):
                    added += 1
                else:
                    skipped += 1
        msg = f"Added {added} song(s)"
        if skipped:
            msg += f" — skipped {skipped} duplicate(s)"
        self.statusBar().showMessage(msg, 4000)

    def remove_selected_from_playlist(self):
        rows = sorted({i.row() for i in self.playlist_view.selectionModel().selectedIndexes()})
        if rows:
            self.playlist_model.remove_rows(rows)

    def clear_playlist(self):
        if self.playlist_model.rowCount() == 0:
            return
        r = QMessageBox.question(self, "Clear", "Remove all songs from this playlist?")
        if r == QMessageBox.Yes:
            self.playlist_model.clear()

    def _move_selected(self, delta: int):
        rows = sorted({i.row() for i in self.playlist_view.selectionModel().selectedIndexes()})
        if not rows:
            return
        self.playlist_model.move_rows(rows, delta)
        # Re-select moved rows so user can press the button again
        sm = self.playlist_view.selectionModel()
        sm.clearSelection()
        for r in rows:
            new_r = r + delta
            if 0 <= new_r < self.playlist_model.rowCount():
                idx = self.playlist_model.index(new_r, 0)
                sm.select(idx, sm.SelectionFlag.Select)

    # ---- Misc ----
    def _on_playlist_changed(self):
        self.dirty = True
        self._update_playlist_label()

    def _update_playlist_label(self):
        n = self.playlist_model.rowCount()
        if self.current_playlist_path is None:
            label = f"(unsaved playlist) — {n} songs"
        else:
            label = f"{self.current_playlist_name} — {n} songs"
        if self.dirty:
            label += "  •  modified"
        self.playlist_label.setText(label)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(
            self,
            "Unsaved changes",
            "The current playlist has unsaved changes. Discard them?",
            QMessageBox.Discard | QMessageBox.Save | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if r == QMessageBox.Save:
            self.save_playlist()
            return not self.dirty  # only proceed if save actually completed
        return r == QMessageBox.Discard

    def open_settings(self):
        """Open the Settings dialog and apply any changes."""
        if not self._confirm_discard():
            return
        dlg = SettingsDialog(self, self.songs_dir, self.playlists_dir)
        if dlg.exec() != QDialog.Accepted:
            return

        new_songs, new_playlists = dlg.values()

        # Basic sanity check — don't accept empty paths
        if not str(new_songs) or not str(new_playlists):
            QMessageBox.warning(self, "Invalid paths", "Both folders must be set.")
            return

        changed = (new_songs != self.songs_dir) or (new_playlists != self.playlists_dir)
        self.songs_dir = new_songs
        self.playlists_dir = new_playlists

        save_config({
            "songs_dir": str(self.songs_dir),
            "playlists_dir": str(self.playlists_dir),
        })

        if changed:
            # Reset current playlist — its songs reference the old library
            self.playlist_model.clear()
            self.current_playlist_path = None
            self.current_playlist_name = ""
            self.dirty = False
            self._update_playlist_label()
            self._refresh_playlist_combo()
            self.scan_library()
            self.statusBar().showMessage("Settings updated.", 4000)

    def _about(self):
        QMessageBox.about(
            self,
            "About",
            "<h3>UltraStar Playlist Manager</h3>"
            "<p>A simple GUI for creating and managing UltraStar Deluxe playlists.</p>"
            f"<p><b>Songs:</b> {self.songs_dir}<br>"
            f"<b>Playlists:</b> {self.playlists_dir}</p>",
        )

    def closeEvent(self, e):
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("UltraStar Playlist Manager")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
