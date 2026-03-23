# -*- coding: utf-8 -*-
"""
EigrutelIndexDocumentation.py
Index Documentation — Version initiale
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import random
import sqlite3
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, ImageFilter


from ui_common import (
    UI,
    apply_style,
    apply_app_icon,
    app_dir,
    load_json,
    save_json,
    open_with_default_app,
    strip_accents,
)

Image.MAX_IMAGE_PIXELS = None

# =========================
# CONFIG
# =========================
APP_TITLE = "Index Documentation - Eigrutel tools"
DOC_RENAMER_WINDOW_TITLE = "Documentation - Eigrutel tools"

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")

DB_FILE = os.path.join(app_dir(), "index_documentation.db")
SETTINGS_FILE = os.path.join(app_dir(), "index_documentation_settings.json")
THUMBS_DIR = os.path.join(app_dir(), "index_documentation_thumbs")

THUMB_SIZE = (130 , 130)
RESULT_LIMIT = 500
SEARCH_DELAY_MS = 280

db_lock = threading.Lock()


# =========================
# HELPERS
# =========================
def ensure_thumb_dir() -> None:
    os.makedirs(THUMBS_DIR, exist_ok=True)


def center_window(root: tk.Tk, width: int = 1400, height: int = 860) -> None:
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2 - 20)
    root.geometry(f"{width}x{height}+{x}+{y}")


def center_on_parent(win, parent):
    win.update_idletasks()
    w = win.winfo_width()
    h = win.winfo_height()
    x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
    y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


def normalize_search_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = strip_accents(s)
    return s

def normalize_library_root(path: str) -> str:
    return os.path.abspath(path or "").rstrip("\\/")

def safe_image_size(path: str) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def make_thumb_name(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8", errors="ignore")).hexdigest() + ".jpg"


def get_thumb_path(image_path: str) -> str:
    ensure_thumb_dir()
    return os.path.join(THUMBS_DIR, make_thumb_name(image_path))


def get_or_create_thumb(image_path: str) -> str | None:
    thumb_path = get_thumb_path(image_path)

    try:
        src_mtime = os.path.getmtime(image_path)
    except Exception:
        return None

    if os.path.exists(thumb_path):
        try:
            thumb_mtime = os.path.getmtime(thumb_path)
            if thumb_mtime >= src_mtime:
                return thumb_path
        except Exception:
            pass

    try:
        with Image.open(image_path) as im:
            im = im.convert("RGB")
            im.thumbnail(THUMB_SIZE, Image.LANCZOS)
            im.save(thumb_path, "JPEG", quality=90)
        return thumb_path
    except Exception:
        return None


def open_folder(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    open_with_default_app(path)


def parse_search_query(query: str) -> tuple[list[str], list[str]]:
    includes: list[str] = []
    excludes: list[str] = []

    for raw in (query or "").split():
        token = normalize_search_text(raw)
        if not token:
            continue

        if token.startswith("-") and len(token) > 1:
            token = token[1:].strip()
            if token:
                excludes.append(token)
        else:
            includes.append(token)

    return includes, excludes


def bring_window_to_front(window_title: str) -> bool:
    """
    Windows uniquement.
    Cherche une fenêtre par son titre exact, la restaure si minimisée
    et la place au premier plan.
    Retourne True si trouvée, sinon False.
    """
    if not sys.platform.startswith("win"):
        return False

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, window_title)
        if not hwnd:
            return False

        SW_MAXIMIZE = 3
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def format_seconds(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"

def truncate_end(text: str, max_chars: int) -> str:
    text = str(text or "")
    if max_chars <= 3 or len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."

def format_file_size(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes)))
    for unit in ("octets", "Ko", "Mo", "Go", "To"):
        if value < 1024 or unit == "To":
            if unit == "octets":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return "0 octet"
# =========================
# DATABASE
# =========================
def db_connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_FILE, timeout=10)


def init_db() -> None:
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_root TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL,
                filename TEXT NOT NULL,
                folder TEXT NOT NULL,
                norm_filename TEXT NOT NULL,
                norm_folder TEXT NOT NULL,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                UNIQUE(library_root, path)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_flags (
                library_root TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL,
                favorite INTEGER DEFAULT 0,
                collected INTEGER DEFAULT 0,
                PRIMARY KEY (library_root, path)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_flags_library_path ON user_flags(library_root, path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_flags_favorite ON user_flags(library_root, favorite)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_flags_collected ON user_flags(library_root, collected)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_library_path ON images(library_root, path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_img_norm_filename ON images(library_root, norm_filename)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_img_norm_folder ON images(library_root, norm_folder)")
        
        # migration douce si la base existe déjà
        try:
            cur.execute("ALTER TABLE images ADD COLUMN library_root TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        try:
            cur.execute("ALTER TABLE user_flags ADD COLUMN library_root TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        cur.execute("UPDATE images SET library_root = '' WHERE library_root IS NULL")
        cur.execute("UPDATE user_flags SET library_root = '' WHERE library_root IS NULL")
        
        conn.commit()
        conn.close()


def clear_index(library_root: str) -> None:
    library_root = normalize_library_root(library_root)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM images WHERE library_root = ?", (library_root,))
        conn.commit()
        conn.close()


def insert_record(library_root: str, path: str, filename: str, folder: str, width: int, height: int) -> None:
    library_root = normalize_library_root(library_root)
    norm_filename = normalize_search_text(filename)
    norm_folder = normalize_search_text(folder)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO images
            (library_root, path, filename, folder, norm_filename, norm_folder, width, height)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (library_root, path, filename, folder, norm_filename, norm_folder, width, height))
        conn.commit()
        conn.close()


def count_indexed_images(library_root: str | None = None) -> int:
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        if library_root:
            library_root = normalize_library_root(library_root)
            n = cur.execute(
                "SELECT COUNT(*) FROM images WHERE library_root = ?",
                (library_root,)
            ).fetchone()[0]
        else:
            n = cur.execute("SELECT COUNT(*) FROM images").fetchone()[0]

        conn.close()
        return int(n)

def ensure_user_flag_row(library_root: str, path: str) -> None:
    library_root = normalize_library_root(library_root)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO user_flags (library_root, path, favorite, collected)
            VALUES (?, ?, 0, 0)
        """, (library_root, path))
        conn.commit()
        conn.close()


def set_favorite(library_root: str, path: str, value: bool) -> None:
    library_root = normalize_library_root(library_root)
    ensure_user_flag_row(library_root, path)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_flags
            SET favorite = ?
            WHERE library_root = ? AND path = ?
        """, (1 if value else 0, library_root, path))
        conn.commit()
        conn.close()


def toggle_favorite(library_root: str, path: str) -> int:
    library_root = normalize_library_root(library_root)
    ensure_user_flag_row(library_root, path)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        row = cur.execute("""
            SELECT favorite FROM user_flags
            WHERE library_root = ? AND path = ?
        """, (library_root, path)).fetchone()
        old_value = int(row[0]) if row else 0
        new_value = 0 if old_value else 1
        cur.execute("""
            UPDATE user_flags
            SET favorite = ?
            WHERE library_root = ? AND path = ?
        """, (new_value, library_root, path))
        conn.commit()
        conn.close()
        return new_value


def set_collected(library_root: str, path: str, value: bool) -> None:
    library_root = normalize_library_root(library_root)
    ensure_user_flag_row(library_root, path)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_flags
            SET collected = ?
            WHERE library_root = ? AND path = ?
        """, (1 if value else 0, library_root, path))
        conn.commit()
        conn.close()


def toggle_collected(library_root: str, path: str) -> int:
    library_root = normalize_library_root(library_root)
    ensure_user_flag_row(library_root, path)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        row = cur.execute("""
            SELECT collected FROM user_flags
            WHERE library_root = ? AND path = ?
        """, (library_root, path)).fetchone()
        old_value = int(row[0]) if row else 0
        new_value = 0 if old_value else 1
        cur.execute("""
            UPDATE user_flags
            SET collected = ?
            WHERE library_root = ? AND path = ?
        """, (new_value, library_root, path))
        conn.commit()
        conn.close()
        return new_value


def get_flags_map(paths: list[str]) -> dict[str, dict]:
    if not paths:
        return {}

    placeholders = ",".join("?" for _ in paths)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        rows = cur.execute(f"""
            SELECT path, favorite, collected
            FROM user_flags
            WHERE path IN ({placeholders})
        """, paths).fetchall()
        conn.close()

    out: dict[str, dict] = {}
    for path, favorite, collected in rows:
        out[path] = {
            "favorite": int(favorite),
            "collected": int(collected),
        }
    return out


def count_collected_items(library_root: str | None = None) -> int:
    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        if library_root:
            library_root = normalize_library_root(library_root)
            n = cur.execute("""
                SELECT COUNT(*) FROM user_flags
                WHERE library_root = ? AND collected = 1
            """, (library_root,)).fetchone()[0]
        else:
            n = cur.execute("""
                SELECT COUNT(*) FROM user_flags WHERE collected = 1
            """).fetchone()[0]

        conn.close()
        return int(n)


def clear_collected_items(library_root: str) -> None:
    library_root = normalize_library_root(library_root)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_flags
            SET collected = 0
            WHERE library_root = ? AND collected = 1
        """, (library_root,))
        conn.commit()
        conn.close()

def collect_paths(library_root: str, paths: list[str]) -> int:
    if not paths:
        return 0

    library_root = normalize_library_root(library_root)
    unique_paths = list(dict.fromkeys(paths))

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        for path in unique_paths:
            cur.execute("""
                INSERT OR IGNORE INTO user_flags (library_root, path, favorite, collected)
                VALUES (?, ?, 0, 0)
            """, (library_root, path))

        placeholders = ",".join("?" for _ in unique_paths)
        cur.execute(f"""
            UPDATE user_flags
            SET collected = 1
            WHERE library_root = ?
              AND path IN ({placeholders})
        """, [library_root, *unique_paths])

        conn.commit()
        conn.close()

    return len(unique_paths)

def cleanup_user_flags(library_root: str) -> None:
    library_root = normalize_library_root(library_root)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM user_flags
            WHERE library_root = ?
              AND path NOT IN (
                  SELECT path FROM images WHERE library_root = ?
              )
        """, (library_root, library_root))
        conn.commit()
        conn.close()
        
def rename_image_record(library_root: str, old_path: str, new_path: str) -> None:
    library_root = normalize_library_root(library_root)
    new_filename = os.path.basename(new_path)
    new_folder = os.path.dirname(new_path)
    norm_filename = normalize_search_text(new_filename)
    norm_folder = normalize_search_text(new_folder)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        cur.execute("""
            UPDATE images
            SET path = ?, filename = ?, folder = ?, norm_filename = ?, norm_folder = ?
            WHERE library_root = ? AND path = ?
        """, (new_path, new_filename, new_folder, norm_filename, norm_folder, library_root, old_path))

        cur.execute("""
            UPDATE user_flags
            SET path = ?
            WHERE library_root = ? AND path = ?
        """, (new_path, library_root, old_path))

        conn.commit()
        conn.close()

def search_images(
    
    library_root: str,
    query: str,
    limit: int = RESULT_LIMIT,
    favorites_only: bool = False
) -> list[dict]:
    
    library_root = normalize_library_root(library_root)
    includes, excludes = parse_search_query(query)

    with db_lock:
        conn = db_connect()
        cur = conn.cursor()

        params: list[object] = []
        wheres: list[str] = ["images.library_root = ?"]
        params.append(library_root)

        if favorites_only:
            wheres.append("COALESCE(user_flags.favorite, 0) = 1")

        for token in includes:
            like = f"%{token}%"
            wheres.append("(norm_filename LIKE ? OR norm_folder LIKE ?)")
            params.extend([like, like])

        for token in excludes:
            like = f"%{token}%"
            wheres.append("NOT (norm_filename LIKE ? OR norm_folder LIKE ?)")
            params.extend([like, like])

        if wheres:
            sql = f"""
                SELECT
                    images.path,
                    images.filename,
                    images.folder,
                    images.width,
                    images.height,
                    COALESCE(user_flags.favorite, 0) AS favorite,
                    COALESCE(user_flags.collected, 0) AS collected
                FROM images
                LEFT JOIN user_flags
                    ON user_flags.library_root = images.library_root
                   AND user_flags.path = images.path

                WHERE {' AND '.join(wheres)}
                ORDER BY folder COLLATE NOCASE, filename COLLATE NOCASE
                LIMIT ?
            """
            params.append(limit)
            rows = cur.execute(sql, params).fetchall()
        else:
            rows = cur.execute("""
                SELECT
                    images.path,
                    images.filename,
                    images.folder,
                    images.width,
                    images.height,
                    COALESCE(user_flags.favorite, 0) AS favorite,
                    COALESCE(user_flags.collected, 0) AS collected
                FROM images
                LEFT JOIN user_flags
                    ON user_flags.library_root = images.library_root
                   AND user_flags.path = images.path
                ORDER BY folder COLLATE NOCASE, filename COLLATE NOCASE
                LIMIT ?
            """, (limit,)).fetchall()
        conn.close()

    out = []
    for row in rows:
        out.append({
            "path": row[0],
            "filename": row[1],
            "folder": row[2],
            "width": row[3],
            "height": row[4],
            "favorite": int(row[5]),
            "collected": int(row[6]),
        })
    return out


# =========================
# INDEXATION
# =========================
def iter_images(root_dir: str):
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            if not name.startswith("DOCUMENTATION_"):
                continue
            if name.lower().endswith(IMG_EXTS):
                yield os.path.join(base, name)


def count_supported_images(root_dir: str) -> int:
    total = 0
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            if not name.startswith("DOCUMENTATION_"):
                continue
            if name.lower().endswith(IMG_EXTS):
                total += 1
    return total

def iter_any_images(root_dir: str):
    for base, _dirs, files in os.walk(root_dir):
        for name in files:
            if name.lower().endswith(IMG_EXTS):
                yield os.path.join(base, name)


def build_item_from_path(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    if not path.lower().endswith(IMG_EXTS):
        return None

    filename = os.path.basename(path)
    folder = os.path.dirname(path)
    w, h = safe_image_size(path)

    return {
        "path": path,
        "filename": filename,
        "folder": folder,
        "width": w,
        "height": h,
        "favorite": 0,
        "collected": 0,
    }
# =========================
# SESSION ATELIER
# =========================
class AtelierSessionWindow:
    def __init__(self, app: "IndexDocumentationApp", items: list[dict], duration_s: int, image_bg: str = "#000000"):
        self.app = app
        self.items = items[:]
        self.duration_s = max(1, int(duration_s))

        self.win = tk.Toplevel(app.root)
        self.win.title("Atelier - Session croquis")
        try:
            self.win.iconbitmap(default=os.path.join(app_dir(), "Renamer.ico"))
        except Exception:
            pass

        self.win.minsize(900, 650)
        center_window(self.win, 1200, 820)
        self.win.configure(bg="#111111")

        self.current_idx = 0
        self.remaining_s = self.duration_s
        self.paused = False
        self.after_id = None
        self.fullscreen = False
        self.ending_screen = False
        self.image_ref: ImageTk.PhotoImage | None = None
        self.current_path: str | None = None
        self.display_mode = "normal"
        self.image_bg = image_bg or "#000000"

        self.display_modes = [
            ("normal", "Normal"),
            ("gray", "Gris"),
            ("bw", "Noir et blanc"),
            ("three_values", "3 valeurs"),
            ("five_values", "5 valeurs"),
            ("blur", "Flou"),
        ]

        # transformations géométriques
        self.flip_h = False
        self.flip_v = False
        self.rotation = 0   # 0 / 90 / 180 / 270
        self.mode_var = tk.StringVar(value="normal")

        self.grid_enabled = tk.BooleanVar(value=False)
        self.grid_size = tk.IntVar(value=80)
        self.grid_offset_x = tk.IntVar(value=0)
        self.grid_offset_y = tk.IntVar(value=0)

        self.grid_win: tk.Toplevel | None = None
        self.composition_enabled = tk.BooleanVar(value=False)
        self.thirds_color = "#E9B44C"
        self.diagonals_color = "#D85C63"



        self.title_var = tk.StringVar(value="")
        self.counter_var = tk.StringVar(value="")
        self.timer_var = tk.StringVar(value=format_seconds(self.remaining_s))
        self.index_var = tk.StringVar(value="1/1")
        self._build_ui()
        self._bind_events()
        self._create_context_menu()

        try:
            self.win.attributes("-fullscreen", True)
            self.fullscreen = True
        except Exception:
            self.fullscreen = False

        self.show_item(0)

        # focus clavier renforcé pour que les flèches marchent sans clic
        self.win.lift()
        self.win.focus_force()
        self.win.after(50, self._force_session_focus)
        self.win.after(150, self._force_session_focus)
        self.win.after(300, self._force_session_focus)


    def _build_ui(self) -> None:
        
        # image zone
        self.image_area = tk.Frame(self.win, bg=self.image_bg)
        self.image_area.pack(fill="both", expand=True)

        self.image_canvas = tk.Canvas(
            self.image_area,
            bg=self.image_bg,
            highlightthickness=0,
            bd=0,
            takefocus=1,
        )
        self.image_canvas.pack(fill="both", expand=True)
        

        # bottom controls
        bottom = tk.Frame(self.win, bg="#111111", height=86)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        # zone gauche = outils visuels (section 1)
        controls_left = tk.Frame(bottom, bg="#111111")
        controls_left.place(x=48, rely=0.55, anchor="w")

        self.btn_mode = ttk.Button(
            controls_left,
            textvariable=self.mode_var,
            command=self.cycle_display_mode,
            style="AtelierCtrl.TButton",
            width=14,
        )
        self.btn_mode.pack(side="left", padx=(0, 8))

        self.btn_composition = ttk.Button(
            controls_left,
            text="Composition",
            style="AtelierCtrl.TButton",
            command=self.toggle_composition,
            width=12,
        )
        self.btn_composition.pack(side="left", padx=(0, 8))

        if self.composition_enabled.get():
            self.btn_composition.config(style="AtelierCtrlOn.TButton")
        else:
            self.btn_composition.config(style="AtelierCtrl.TButton")

        self.chk_grid = ttk.Checkbutton(
            controls_left,
            text="",
            variable=self.grid_enabled,
            command=self.on_grid_toggle_from_checkbox,
            style="AtelierGrid.TCheckbutton",
            takefocus=0,
        )
        self.chk_grid.pack(side="left", padx=(0, 8))

        self.btn_flip_v = ttk.Button(
            controls_left,
            text="↕",
            command=self.toggle_flip_vertical,
            width=3,
            style="AtelierCtrl2.TButton",
        )
        self.btn_flip_v.pack(side="left", padx=(0, 6))

        self.btn_flip_h = ttk.Button(
            controls_left,
            text="↔",
            command=self.toggle_flip_horizontal,
            width=3,
            style="AtelierCtrl2.TButton",
        )
        self.btn_flip_h.pack(side="left", padx=(0, 6))

        self.btn_rotate = ttk.Button(
            controls_left,
            text="↻",
            command=self.rotate_image,
            width=3,
            style="AtelierCtrl2.TButton",
        )
        self.btn_rotate.pack(side="left", padx=(0, 0))

        # zone centrale = commandes session
        controls_center = tk.Frame(bottom, bg="#111111")
        controls_center.place(relx=0.50, rely=0.55, anchor="center")

        self.btn_prev = ttk.Button(
            controls_center,
            text="◁",
            command=self.previous_image,
            width=4,
            style="AtelierMain.TButton",
        )
        self.btn_prev.pack(side="left", padx=6)

        self.btn_pause = ttk.Button(
            controls_center,
            text="Pause",
            command=self.toggle_pause,
            width=8,
            style="AtelierMain.TButton",
        )
        self.btn_pause.pack(side="left", padx=6)

        self.btn_next = ttk.Button(
            controls_center,
            text="▷",
            command=self.next_image,
            width=4,
            style="AtelierMain.TButton",
        )
        self.btn_next.pack(side="left", padx=6)

        # zone droite = quitter + compteur + timer
        controls_right = tk.Frame(bottom, bg="#111111")
        controls_right.place(relx=0.985, rely=0.55, anchor="e")

        self.btn_quit = ttk.Button(
            controls_right,
            text="Quitter",
            command=self.return_to_atelier,
            width=8,
            style="AtelierCtrl.TButton",
        )
        self.btn_quit.pack(side="left", padx=(0,12))

        self.index_badge = tk.Label(
            controls_right,
            textvariable=self.index_var,
            bg="#0F1114",
            fg="#C8D0DA",
            font=("Segoe UI", 11, "bold"),
            padx=10,
            pady=1,
        )
        self.index_badge.pack(side="left", padx=(0,12))

        self.timer_badge = tk.Label(
            controls_right,
            textvariable=self.timer_var,
            bg="#0F1114",
            fg="#C8D0DA",
            font=("Segoe UI", 16, "bold"),
            padx=16,
            pady=8,
        )
        self.timer_badge.pack(side="left")


    def _bind_events(self) -> None:
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        # clic droit
        self.win.bind("<Button-3>", self._show_context_menu)
        self.image_canvas.bind("<Button-3>", self._show_context_menu)
        self.image_area.bind("<Button-3>", self._show_context_menu)

        self.win.bind("<Button-2>", self._show_context_menu)
        self.image_canvas.bind("<Button-2>", self._show_context_menu)
        self.image_area.bind("<Button-2>", self._show_context_menu)

        self.image_area.bind("<Configure>", self._on_resize)

        # raccourcis globaux pendant la session
        
        self.win.bind_all("<Left>", self._on_left_key)
        self.win.bind_all("<Right>", self._on_right_key)
        self.win.bind_all("<Escape>", self._on_escape_key)

        # modes d'affichage : clavier principal + pavé numérique
        self.win.bind_all("1", lambda e: self._set_mode_and_break("normal"))
        self.win.bind_all("2", lambda e: self._set_mode_and_break("gray"))
        self.win.bind_all("3", lambda e: self._set_mode_and_break("bw"))
        self.win.bind_all("4", lambda e: self._set_mode_and_break("three_values"))
        self.win.bind_all("5", lambda e: self._set_mode_and_break("five_values"))
        self.win.bind_all("6", lambda e: self._set_mode_and_break("blur"))
        #self.win.bind_all("7", lambda e: self._set_mode_and_break("simple_colors"))
        self.win.bind_all("7", lambda e: self._toggle_composition_and_break())
        self.win.bind_all("8", lambda e: self._cycle_grid_color_and_break())
        self.win.bind_all("9", lambda e: self._toggle_grid_and_break())
        self.win.bind_all("<KP_1>", lambda e: self._set_mode_and_break("normal"))
        self.win.bind_all("<KP_2>", lambda e: self._set_mode_and_break("gray"))
        self.win.bind_all("<KP_3>", lambda e: self._set_mode_and_break("bw"))
        self.win.bind_all("<KP_4>", lambda e: self._set_mode_and_break("three_values"))
        self.win.bind_all("<KP_5>", lambda e: self._set_mode_and_break("five_values"))
        self.win.bind_all("<KP_6>", lambda e: self._set_mode_and_break("blur"))
        self.win.bind_all("<KP_7>", lambda e: self._toggle_composition_and_break())
        self.win.bind_all("<KP_8>", lambda e: self._cycle_grid_color_and_break())
        self.win.bind_all("<KP_9>", lambda e: self._toggle_grid_and_break())
        self.win.bind_all("m", lambda e: self._toggle_flip_horizontal_and_break())
        self.win.bind_all("p", lambda e: self._toggle_flip_vertical_and_break())
        self.win.bind_all("r", lambda e: self._rotate_and_break())
        self.win.bind_all("<space>", lambda e: self._pause_and_break())
               
        
        
        self.grid_color = "#FFFFFF"
        self.grid_color_index = 0
        self.grid_colors = ["#FFFFFF", "#000000", "#FF4040", "#00FFFF"]
        
        self.image_canvas.focus_set()

    def _force_session_focus(self) -> None:
        try:
            self.win.focus_force()
            self.image_canvas.focus_set()
        except Exception:
            pass
    def _on_space_key(self, _event=None):
        self.toggle_pause()
        return "break"

    def _on_left_key(self, _event=None):
        self.previous_image()
        return "break"

    def _on_right_key(self, _event=None):
        self.next_image()
        return "break"

    def _on_escape_key(self, _event=None):
        if self.grid_win is not None and self.grid_win.winfo_exists():
            try:
                self.grid_win.destroy()
            except Exception:
                pass
            self.grid_win = None
            self._force_session_focus()
            return "break"

        self.close()
        return "break"

    def _set_mode_and_break(self, mode: str):
        self.set_display_mode(mode)
        return "break"

    def _toggle_grid_and_break(self):
        self.grid_enabled.set(not self.grid_enabled.get())
        self.on_grid_toggle_from_checkbox()
        return "break"
    
    def _toggle_flip_horizontal_and_break(self):
        self.toggle_flip_horizontal()
        return "break"

    def _toggle_flip_vertical_and_break(self):
        self.toggle_flip_vertical()
        return "break"

    def _rotate_and_break(self):
        self.rotate_image()
        return "break"

    def _pause_and_break(self):
        self.toggle_pause()
        return "break"

    def _quit_to_index_and_break(self):
        self.close()
        return "break"

    def _toggle_composition_and_break(self):
        self.toggle_composition()
        return "break"

    def _cycle_grid_color_and_break(self):
        self.cycle_grid_color()
        return "break"
    
    def toggle_composition(self) -> None:
        self.composition_enabled.set(not self.composition_enabled.get())

        if self.composition_enabled.get():
            self.btn_composition.config(style="AtelierCtrlOn.TButton")
        else:
            self.btn_composition.config(style="AtelierCtrl.TButton")

        self.refresh_image()
        self._force_session_focus()

    def _create_context_menu(self) -> None:
        self.context_menu = tk.Menu(
            self.win,
            tearoff=0,
            bg=UI.STRUCT_30,
            fg="#E6EBF2",
            activebackground="#2B3444",
            activeforeground="#FFFFFF",
            borderwidth=0,
            relief="flat",
            activeborderwidth=0,
            font=("Segoe UI", 10),
        )

        self.context_menu.add_command(
            label="",
        )
        self.context_menu.add_command(
            label="1. Normal",
            command=lambda: self.set_display_mode("normal")
        )
        self.context_menu.add_command(
            label="2. Gris",
            command=lambda: self.set_display_mode("gray")
        )
        self.context_menu.add_command(
            label="3. Noir & Blanc",
            command=lambda: self.set_display_mode("bw")
        )
        self.context_menu.add_command(
            label="4. Trois valeurs",
            command=lambda: self.set_display_mode("three_values")
        )
        self.context_menu.add_command(
            label="5. Cinq valeurs",
            command=lambda: self.set_display_mode("five_values")
        )
        self.context_menu.add_command(
            label="6. Flou",
            command=lambda: self.set_display_mode("blur")
        )
        #self.context_menu.add_command(
            #label="7. Couleurs simplifiées",
            #command=lambda: self.set_display_mode("simple_colors")
        #)

        self.context_menu.add_separator()
        
        self.context_menu.add_command(
            label="7. Composition",
            command=self.toggle_composition
        )
        self.context_menu.add_command(
            label="8. Couleur grille",
            command=self.cycle_grid_color
        )

        self.context_menu.add_command(
            label="9. Grille",
            command=self.toggle_grid_from_menu
        )
        self.context_menu.add_separator()

        self.context_menu.add_command(
            label="m. Miroir horizontal",
            command=self.toggle_flip_horizontal
        )
        self.context_menu.add_command(
            label="p. Miroir vertical",
            command=self.toggle_flip_vertical
        )
        self.context_menu.add_command(
            label="r. Rotation",
            command=self.rotate_image
        )

        self.context_menu.add_separator()

        self.context_menu.add_command(
            label="○ Fond sombre",
            command=self.set_bg_dark
        )
        self.context_menu.add_command(
            label="⬤ Fond blanc",
            command=self.set_bg_white
        )
        self.context_menu.add_command(
            label="◐ Fond neutre",
            command=self.set_bg_neutral
        )

        self.context_menu.add_separator()

        self.context_menu.add_command(
            label="Esc. Quitter la session",
            command=self.return_to_atelier
        )
        
        
        self.context_menu.add_command(
            label="",
        )

    def _show_context_menu(self, event) -> None:
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.context_menu.grab_release()
            except Exception:
                pass

    def set_display_mode(self, mode: str) -> None:
        self.display_mode = mode

        labels = {
            "normal": "normal",
            "gray": "gris",
            "bw": "noir et blanc",
            "three_values": "3 valeurs",
            "five_values": "5 valeurs",
            "blur": "flou",
        }

        self.mode_var.set(labels.get(mode, mode))

        self.refresh_image()
        self._force_session_focus()

    def cycle_display_mode(self) -> None:
        modes = [m[0] for m in self.display_modes]

        try:
            current_index = modes.index(self.display_mode)
        except ValueError:
            current_index = 0

        next_index = (current_index + 1) % len(modes)
        next_mode = modes[next_index]
        self.set_display_mode(next_mode)
    
    def on_grid_toggle_from_checkbox(self) -> None:
        if self.grid_enabled.get():
            self.refresh_image()
            self.open_grid_window()
        else:
            if self.grid_win is not None and self.grid_win.winfo_exists():
                try:
                    self.grid_win.destroy()
                except Exception:
                    pass
                self.grid_win = None

            self.refresh_image()

        self._force_session_focus()

    def toggle_grid_from_menu(self) -> None:
        self.grid_enabled.set(not self.grid_enabled.get())
        self.on_grid_toggle_from_checkbox()

    def open_grid_window(self) -> None:
        if self.grid_win is not None and self.grid_win.winfo_exists():
            self.grid_win.deiconify()
            self.grid_win.lift()
            self.grid_win.focus_force()
            return

        win = tk.Toplevel(self.win)
        self.grid_win = win

        win.configure(bg=UI.STRUCT_30)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.overrideredirect(True)

        panel = tk.Frame(win, bg=UI.STRUCT_30, padx=10, pady=10)
        panel.pack(fill="both", expand=True)

        header = tk.Frame(panel, bg=UI.STRUCT_30)
        header.pack(fill="x", pady=(0, 6))

        def on_close():
            try:
                win.destroy()
            finally:
                self.grid_win = None
                self._force_session_focus()

        tk.Label(
            header,
            text="Prise de mesure",
            bg=UI.STRUCT_30,
            fg="#E6EBF2",
            font=("Segoe UI", 9, "bold")
        ).pack(side="left")

        tk.Button(
            header,
            text="×",
            command=on_close,
            bg=UI.STRUCT_30,
            fg="#E6EBF2",
            activebackground="#2B3444",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            padx=6,
            pady=0,
            cursor="hand2",
        ).pack(side="right")

        
        def add_slider(icon_text: str, variable: tk.IntVar, from_, to_, color="#51627A"):
            block = tk.Frame(panel, bg=UI.STRUCT_30)
            block.pack(fill="x", pady=4)

            row = tk.Frame(block, bg=UI.STRUCT_30)
            row.pack(fill="x")

            tk.Label(
                row,
                text=icon_text,
                bg=UI.STRUCT_30,
                fg="#E6EBF2",
                font=("Segoe UI Symbol", 12),
                width=3,
                anchor="w",
            ).pack(side="left")

            scale = tk.Scale(
                row,
                from_=from_,
                to=to_,
                orient="horizontal",
                variable=variable,
                showvalue=False,
                resolution=1,
                length=180,
                width=14,
                sliderlength=20,
                bg=UI.STRUCT_30,
                fg="#E6EBF2",
                highlightthickness=0,
                troughcolor=color,
                activebackground="#7dbcf6",
                bd=0,
                relief="flat",
                command=lambda _v: self.on_grid_slider_change(),
            )
            scale.pack(side="left", fill="x", expand=True)
            

        add_slider("x", self.grid_offset_x, -300, 300)
        add_slider("y", self.grid_offset_y, -300, 300)
        add_slider("⇲", self.grid_size, 10, 300, "#6C8FBF")

        self.btn_grid_color = tk.Button(
            panel,
            text="◩",
            command=self.cycle_grid_color,
            bg=UI.STRUCT_30,
            fg=self.grid_color,
            activeforeground=self.grid_color,
            activebackground=UI.STRUCT_30,
            relief="flat",
            bd=0,
            font=("Segoe UI Symbol", 18),
            padx=4,
            pady=2,
            cursor="hand2"
        )
        self.btn_grid_color.pack(anchor="w", pady=(6,0))

        btns = tk.Frame(panel, bg=UI.STRUCT_30)

        
        
        self.grid_enabled.set(True)
        self.refresh_image()

        self.position_grid_window_bottom_left()

        def on_close():
            try:
                win.destroy()
            finally:
                self.grid_win = None
                self._force_session_focus()

        win.protocol("WM_DELETE_WINDOW", on_close)

    def position_grid_window_bottom_left(self) -> None:
        if self.grid_win is None or not self.grid_win.winfo_exists():
            return

        self.grid_win.update_idletasks()

        w = self.grid_win.winfo_width()
        h = self.grid_win.winfo_height()

        parent_x = self.win.winfo_rootx()
        parent_y = self.win.winfo_rooty()
        parent_h = self.win.winfo_height()

        x = parent_x + 24
        y = parent_y + parent_h - h - 110

        if y < 0:
            y = 20

        self.grid_win.geometry(f"{w}x{h}+{x}+{y}")
    def on_grid_slider_change(self) -> None:
        self.refresh_image()

    def toggle_grid(self) -> None:
        self.grid_enabled.set(not self.grid_enabled.get())
        self.refresh_image()
        self._force_session_focus()

    def increase_grid_size(self) -> None:
        self.grid_enabled.set(True)
        self.grid_size.set(min(400, int(self.grid_size.get()) + 10))
        self.refresh_image()
        self._force_session_focus()

    def decrease_grid_size(self) -> None:
        self.grid_enabled.set(True)
        self.grid_size.set(max(4, int(self.grid_size.get()) - 10))
        self.refresh_image()
        self._force_session_focus()

    def _on_resize(self, _event=None):
        self.refresh_image()

    def show_item(self, idx: int) -> None:
        if not self.items:
            self.return_to_atelier()
            return

        idx = max(0, min(idx, len(self.items) - 1))
        self.current_idx = idx
        item = self.items[idx]
        self.current_path = item["path"]
        self.title_var.set(item["filename"])
        self.counter_var.set(f"{idx + 1} / {len(self.items)}")
        self.remaining_s = self.duration_s
        self.timer_var.set(format_seconds(self.remaining_s))
        self.refresh_image()
        self._restart_timer()
        self._force_session_focus()
        self.win.after(50, self._force_session_focus)
        self._update_index_display()

    def _update_index_display(self):

        total = len(self.items)

        current = self.current_idx + 1

        self.index_var.set(f"{current}/{total}")
    def refresh_image(self) -> None:
        if not self.current_path:
            return

        try:
            self.image_area.update_idletasks()
            max_w = max(300, self.image_area.winfo_width() - 20)
            max_h = max(250, self.image_area.winfo_height() - 20)

            with Image.open(self.current_path) as im:
                im = im.convert("RGB")
                # -----------------
                # transformations géométriques
                # -----------------

                if self.flip_h:
                    im = im.transpose(Image.FLIP_LEFT_RIGHT)

                if self.flip_v:
                    im = im.transpose(Image.FLIP_TOP_BOTTOM)

                if self.rotation != 0:
                    im = im.rotate(self.rotation, expand=True)
                src_w, src_h = im.size

                if src_w <= 0 or src_h <= 0:
                    raise ValueError("Taille d'image invalide")

                # ---------
                # Modes d'affichage
                # ---------
                if self.display_mode == "gray":
                    im = im.convert("L").convert("RGB")

                elif self.display_mode == "bw":
                    gray = im.convert("L")
                    im = gray.point(lambda p: 255 if p > 128 else 0).convert("RGB")

                elif self.display_mode == "three_values":
                    gray = im.convert("L")

                    def map_three(p):
                        if p < 85:
                            return 0
                        elif p < 170:
                            return 127
                        return 255

                    im = gray.point(map_three).convert("RGB")

                elif self.display_mode == "five_values":
                    gray = im.convert("L")

                    def map_five(p):
                        if p < 51:
                            return 0
                        elif p < 102:
                            return 64
                        elif p < 153:
                            return 128
                        elif p < 204:
                            return 192
                        return 255

                    im = gray.point(map_five).convert("RGB")

                elif self.display_mode == "blur":
                    im = im.filter(ImageFilter.GaussianBlur(radius=6))

                #elif self.display_mode == "simple_colors":
                    #im = im.convert("P", palette=Image.ADAPTIVE, colors=12).convert("RGB")

                # ---------
                # Redimensionnement
                # ---------
                scale = min(max_w / src_w, max_h / src_h)
                new_w = max(1, int(src_w * scale))
                new_h = max(1, int(src_h * scale))

                im = im.resize((new_w, new_h), Image.LANCZOS)
                self.image_ref = ImageTk.PhotoImage(im)

            # ---------
            # Affichage canvas
            # ---------
            canvas_w = max(1, self.image_canvas.winfo_width())
            canvas_h = max(1, self.image_canvas.winfo_height())

            x0 = (canvas_w - new_w) // 2
            y0 = (canvas_h - new_h) // 2
            x1 = x0 + new_w
            y1 = y0 + new_h

            self.image_canvas.delete("all")
            self.image_canvas.create_image(x0, y0, anchor="nw", image=self.image_ref)

            # ---------
                        # Grille
            # ---------
            if self.grid_enabled.get() and int(self.grid_size.get()) > 2:
                step = int(self.grid_size.get())
                offset_x = int(self.grid_offset_x.get())
                offset_y = int(self.grid_offset_y.get())

                # verticales
                x = x0 + offset_x
                while x > x0:
                    x -= step
                while x <= x1:
                    self.image_canvas.create_line(
                        x, y0, x, y1,
                        fill=self.grid_color,
                        width=1
                    )
                    x += step

                # horizontales
                y = y0 + offset_y
                while y > y0:
                    y -= step
                while y <= y1:
                    self.image_canvas.create_line(
                        x0, y, x1, y,
                        fill=self.grid_color,
                        width=1
                    )
                    y += step

            # ---------
            # Composition : tiers + diagonales
            # ---------
            if self.composition_enabled.get():
                third_x1 = x0 + (new_w / 3)
                third_x2 = x0 + (2 * new_w / 3)
                third_y1 = y0 + (new_h / 3)
                third_y2 = y0 + (2 * new_h / 3)

                # tiers
                self.image_canvas.create_line(
                    third_x1, y0, third_x1, y1,
                    fill=self.thirds_color,
                    width=2
                )
                self.image_canvas.create_line(
                    third_x2, y0, third_x2, y1,
                    fill=self.thirds_color,
                    width=2
                )
                self.image_canvas.create_line(
                    x0, third_y1, x1, third_y1,
                    fill=self.thirds_color,
                    width=2
                )
                self.image_canvas.create_line(
                    x0, third_y2, x1, third_y2,
                    fill=self.thirds_color,
                    width=2
                )

                # diagonales du cadre
                self.image_canvas.create_line(
                    x0, y0, x1, y1,
                    fill=self.diagonals_color,
                    width=2
                )
                self.image_canvas.create_line(
                    x1, y0, x0, y1,
                    fill=self.diagonals_color,
                    width=2
                )

        except Exception:
            self.image_ref = None
            self.image_canvas.delete("all")
            self.image_canvas.create_text(
                self.image_canvas.winfo_width() // 2,
                self.image_canvas.winfo_height() // 2,
                text="Impossible d'afficher l'image",
                fill="#DDDDDD",
                font=("Segoe UI", 12),
            )

    def _restart_timer(self) -> None:
        self._cancel_timer()
        if not self.paused:
            self.after_id = self.win.after(1000, self._tick)

    def _cancel_timer(self) -> None:
        if self.after_id is not None:
            try:
                self.win.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _tick(self) -> None:
        self.after_id = None

        if self.paused or self.ending_screen:
            return

        self.remaining_s -= 1
        self.timer_var.set(format_seconds(self.remaining_s))

        if self.remaining_s <= 0:
            if self.current_idx >= len(self.items) - 1:
                self.show_session_end_screen()
            else:
                self.show_item(self.current_idx + 1)
        else:
            self.after_id = self.win.after(1000, self._tick)

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.btn_pause.config(text="▶" if self.paused else "Pause")

        if self.paused:
            self._cancel_timer()
        else:
            self._restart_timer()

        self._force_session_focus()

    def cycle_grid_color(self):
        self.grid_color_index = (self.grid_color_index + 1) % len(self.grid_colors)
        self.grid_color = self.grid_colors[self.grid_color_index]

        if hasattr(self, "btn_grid_color"):
            self.btn_grid_color.configure(fg=self.grid_color)

        self.refresh_image()

    def set_image_background(self, bg_value: str) -> None:
        self.image_bg = bg_value
        try:
            self.image_area.configure(bg=bg_value)
        except Exception:
            pass
        try:
            self.image_canvas.configure(bg=bg_value)
        except Exception:
            pass
        self.refresh_image()
        self._force_session_focus()

    def set_bg_dark(self) -> None:
        self.set_image_background("#000000")

    def set_bg_white(self) -> None:
        self.set_image_background("#FFFFFF")

    def set_bg_neutral(self) -> None:
        self.set_image_background("#808080")
        
    def next_image(self) -> None:
        if self.current_idx >= len(self.items) - 1:
            self.show_session_end_screen()
            return
        self.show_item(self.current_idx + 1)

    def previous_image(self) -> None:
        if self.current_idx <= 0:
            self.show_item(0)
            return
        self.show_item(self.current_idx - 1)

    def show_session_end_screen(self) -> None:
        self._cancel_timer()
        self.ending_screen = True

        try:
            self.image_canvas.delete("all")

            w = max(1, self.image_canvas.winfo_width())
            h = max(1, self.image_canvas.winfo_height())

            self.image_canvas.create_rectangle(
                0, 0, w, h,
                fill="#000000",
                outline=""
            )

            self.image_canvas.create_text(
                w // 2,
                h // 2 - 12,
                text="Fin de session",
                fill="#E6EBF2",
                font=("Segoe UI", 24, "bold"),
            )

            self.image_canvas.create_text(
                w // 2,
                h // 2 + 24,
                text="Retour à l'index…",
                fill="#AEB8C6",
                font=("Segoe UI", 11),
            )
        except Exception:
            pass

        self.win.after(1000, self.close)

    def return_to_atelier(self) -> None:
        self._cancel_timer()
        if self.grid_win is not None and self.grid_win.winfo_exists():
            try:
                self.grid_win.destroy()
            except Exception:
                pass
            self.grid_win = None

        # libérer les binds globaux
        try:
            self.win.unbind_all("<space>")
            self.win.unbind_all("<Left>")
            self.win.unbind_all("<Right>")
            self.win.unbind_all("<Escape>")

            self.win.unbind_all("1")
            self.win.unbind_all("2")
            self.win.unbind_all("3")
            self.win.unbind_all("4")
            self.win.unbind_all("5")
            self.win.unbind_all("6")
            self.win.unbind_all("7")

            self.win.unbind_all("<KP_1>")
            self.win.unbind_all("<KP_2>")
            self.win.unbind_all("<KP_3>")
            self.win.unbind_all("<KP_4>")
            self.win.unbind_all("<KP_5>")
            self.win.unbind_all("<KP_6>")
            self.win.unbind_all("<KP_7>")
        except Exception:
            pass

        try:
            self.win.destroy()
        except Exception:
            pass

        self.app.atelier_win = None
        
    

    def close(self) -> None:
        self._cancel_timer()
        if self.grid_win is not None and self.grid_win.winfo_exists():
            try:
                self.grid_win.destroy()
            except Exception:
                pass
            self.grid_win = None

        # libérer les binds globaux
        try:
            self.win.unbind_all("<space>")
            self.win.unbind_all("<Left>")
            self.win.unbind_all("<Right>")
            self.win.unbind_all("<Escape>")

            self.win.unbind_all("1")
            self.win.unbind_all("2")
            self.win.unbind_all("3")
            self.win.unbind_all("4")
            self.win.unbind_all("5")
            self.win.unbind_all("6")
            self.win.unbind_all("7")

            self.win.unbind_all("<KP_1>")
            self.win.unbind_all("<KP_2>")
            self.win.unbind_all("<KP_3>")
            self.win.unbind_all("<KP_4>")
            self.win.unbind_all("<KP_5>")
            self.win.unbind_all("<KP_6>")
            self.win.unbind_all("<KP_7>")
        except Exception:
            pass

        try:
            self.win.destroy()
        except Exception:
            pass
        self.app.atelier_win = None

    def toggle_flip_horizontal(self):
        self.flip_h = not self.flip_h
        self.refresh_image()
        self._force_session_focus()


    def toggle_flip_vertical(self):
        self.flip_v = not self.flip_v
        self.refresh_image()
        self._force_session_focus()


    def rotate_image(self):
        self.rotation = (self.rotation - 90) % 360
        self.refresh_image()
        self._force_session_focus()
        


# =========================
# UI
# =========================
class IndexDocumentationApp(ttk.Frame):
    LEFT_W = 400
    LEFT_W_MIN = 150

    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.root = master
        self.root.title(APP_TITLE)
        self.root.iconbitmap(os.path.join(app_dir(), "Renamer.ico"))
        try:
            self.root.state("zoomed")
        except Exception:
            center_window(self.root, 1400, 860)
        self.root.minsize(1180, 720)

        apply_style(self.root)
        self._create_local_styles()
        ensure_thumb_dir()
        init_db()

        self.settings = load_json(SETTINGS_FILE, {})
        self.folder: str = self.settings.get("folder", "") or ""
        self.results: list[dict] = []
        self.current_idx: int = -1
        self.current_item: dict | None = None
        self.indexing = False
        self.search_after_id = None
        self.info_win: tk.Toplevel | None = None
        self.favorites_only = False
        self.collected_only = False
        self.atelier_win: tk.Toplevel | None = None

        self.thumb_refs: list[ImageTk.PhotoImage] = []
        self.thumb_photo_cache: dict[str, ImageTk.PhotoImage | None] = {}
        self.results_signature: tuple = ()
        self.preview_ref: ImageTk.PhotoImage | None = None
        self.preview_source_path: str | None = None
        self.result_cards: list[tk.Frame] = []
        self.result_collected_badges: dict[str, tk.Label] = {}
        self.result_favorite_badges: dict[str, tk.Label] = {}
        self.results_columns = 2
        self.rendering_results = False
        self.pending_results_render = False
        self.preview_resize_after_id = None
        self.preserve_results_scroll = False

        self.search_var = tk.StringVar()
        self.results_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.path_var = tk.StringVar(value="")
        self.meta_var = tk.StringVar(value="")
        self.collected_var = tk.StringVar(value="")
        self.collect_feedback_var = tk.StringVar(value="")
        self.filename_edit_var = tk.StringVar(value="")
        self.search_history = self.settings.get("search_history", []) or []
        self.search_history_max = 25
        self.search_history_index = -1
        self.search_history_current_typed = ""
        self.search_from_history_nav = False

        self.filter_definitions = [
            {"key": "composition", "label": "Composition", "query": "composition"},
            {"key": "forme", "label": "Forme", "query": "forme"},
            {"key": "silhouette", "label": "Silhouette", "query": "silhouette"},
            {"key": "couleur", "label": "Couleur", "query": "couleur"},
            {"key": "lumiere", "label": "Lumière", "query": "lumiere"},
            {"key": "valeurs", "label": "Valeurs", "query": "valeurs"},
            {"key": "echelle", "label": "Échelle", "query": "echelle"},
        ]

        self.filter_vars = {
            item["key"]: tk.BooleanVar(value=False)
            for item in self.filter_definitions
        }
        self.filter_favorites_var = tk.BooleanVar(value=False)
        self.filter_collected_var = tk.BooleanVar(value=False)
        
        self.atelier_panel = None
        self.atelier_panel_visible = False
        self.atelier_panel_animating = False
        self.atelier_panel_height = 320
        self.atelier_panel_y_hidden = -320
        self.atelier_panel_y_shown = 0
        self.rb_atelier_source_results = None
        self.rb_atelier_source_favorites = None
        self.rb_atelier_source_collected = None
        self.atelier_external_file_path = self.settings.get("atelier_external_file_path", "") or ""
        self.atelier_external_folder_path = self.settings.get("atelier_external_folder_path", "") or ""

        
        self._build_ui()
        self._bind_events()
        self.refresh_collected_counter()
        self.refresh_indexed_counter()
        indexed_count = count_indexed_images(self.folder) if self.folder else 0

        if self.folder and os.path.isdir(self.folder):
            if indexed_count > 0:
                self.status_var.set(f"Index prêt — {indexed_count} image(s) indexée(s)")
                self.results_var.set("")
                self.run_search()
            else:
                self.status_var.set("Aucun index disponible. Cliquez sur Réindexer.")
                self.results_var.set("")
        else:
            if indexed_count > 0:
                self.status_var.set(f"Index disponible — {indexed_count} image(s) indexée(s)")
                self.results_var.set("")
                self.run_search()
            else:
                self.status_var.set("Choisissez un dossier Documentation.")
                self.results_var.set("")

    def _create_local_styles(self) -> None:
        style = ttk.Style()

        
        style.configure(
            "Fav.TButton",
            background=UI.ACCENT_10,
            foreground="#F2F2F2",
            padding=(8, 8),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )

        style.map(
            "Fav.TButton",
            background=[("active", UI.ACCENT_HOVER), ("pressed", UI.ACCENT_HOVER)],
            foreground=[("disabled", "#7B8794")],
        )

        style.configure(
            "SquareIcon.TButton",
            background=UI.STRUCT_30,
            foreground="#ECEFF4",
            padding=(8, 8),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )

        style.map(
            "SquareIcon.TButton",
            background=[("active", UI.STRUCT_30_2), ("pressed", UI.STRUCT_30_2)],
            foreground=[("disabled", "#7B8794")],
        )

        style.configure(
            "SquareIconOn.TButton",
            background=UI.ACCENT_10,
            foreground="#FFFFFF",
            padding=(8, 8),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )

        style.map(
            "SquareIconOn.TButton",
            background=[("active", UI.ACCENT_HOVER), ("pressed", UI.ACCENT_HOVER)],
            foreground=[("disabled", "#7B8794")],
        )

        style.configure(
            "Subtle.TButton",
            background="#E7EBF0",
            foreground=UI.TEXT_DARK,
            padding=(10, 6),
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        style.map(
            "Subtle.TButton",
            background=[("active", "#DCE3EA"), ("pressed", "#D6DDE5")],
            foreground=[("disabled", "#7B9487")],
        )

        style.configure(
            "SearchFilter.TCheckbutton",
            background=UI.PANEL,
            foreground=UI.TEXT_DARK,
            font=("Segoe UI", 8),
            padding=(1, 1),
        )
        style.map(
            "SearchFilter.TCheckbutton",
            background=[("active", UI.PANEL), ("selected", UI.PANEL)],
            foreground=[("active", UI.TEXT_DARK), ("selected", UI.TEXT_DARK)],
        )

        style.configure(
            "FavOn.TButton",
            background="#ffc862",
            foreground="#ffffff",
            padding=(8, 8),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )

        style.map(
            "FavOn.TButton",
            background=[("active", "#ffb18b"), ("pressed", "#f6a37d")],
        )

        style.configure(
            "FavFilter.TButton",
            background= "#2F3746",
            foreground="#FFFFFF",
            padding=(8, 4),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "FavFilter.TButton",
            background=[("active", "#2F3746"), ("pressed", "#2F3746")],
            foreground=[("disabled", "#7B8794")],
        )
        style.configure(
            "AtelierCtrl.TButton",
            background="#111111",
            foreground="#E6EBF2",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "AtelierCtrl.TButton",
            background=[("active", "#111111"), ("pressed", "#111111")],
            foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF"), ("disabled", "#7B8794")],
        )
        

        style.configure(
            "AtelierCtrlOn.TButton",
            background="#111111",
            foreground="#FFC862",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "AtelierCtrlOn.TButton",
            background=[("active", "#111111"), ("pressed", "#111111")],
            foreground=[("active", "#FFD27A"), ("pressed", "#FFD27A"), ("disabled", "#7B8794")],
        )
        style.configure(
            "AtelierCtrl2.TButton",
            background="#111111",
            foreground="#E6EBF2",
            padding=(12, 8),
            font=("Segoe UI", 12),
            borderwidth=0,
        )
        style.map(
            "AtelierCtrl2.TButton",
            background=[("active", "#111111"), ("pressed", "#111111")],
            foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF"), ("disabled", "#7B8794")],
        )
        

        style.configure(
            "AtelierCtrl2On.TButton",
            background="#111111",
            foreground="#FFC862",
            padding=(12, 8),
            font=("Segoe UI", 12),
            borderwidth=0,
        )
        style.map(
            "AtelierCtrl2On.TButton",
            background=[("active", "#111111"), ("pressed", "#111111")],
            foreground=[("active", "#FFD27A"), ("pressed", "#FFD27A"), ("disabled", "#7B8794")],
        )
        style.configure(
            "AtelierMain.TButton",
            background="#2F3746",
            foreground="#FFFFFF",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "AtelierMain.TButton",
            background=[("active", "#2F3746"), ("pressed", "#2F3746")],
            foreground=[("disabled", "#7B8794")],
        )

        style.configure(
            "AtelierGrid.TCheckbutton",
            background="#111111",
            foreground="#E6EBF2",
            indicatorbackground="#111111",
            indicatormargin=0,
            padding=(4, 8),
            font=("Segoe UI", 10),
        )
        style.map(
            "AtelierGrid.TCheckbutton",
            background=[("active", "#111111"), ("selected", "#111111")],
            foreground=[("active", "#E6EBF2"), ("selected", "#E6EBF2")],
            indicatorbackground=[("active", "#111111"), ("selected", "#111111")],
        )

        
        style.configure(
            "FavFilterOn.TButton",
            background="#2F3746",
            foreground="#ffc862",
            padding=(8, 4),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "FavFilterOn.TButton",
            background=[("active", UI.STRUCT_30), ("pressed", UI.STRUCT_30)],
            foreground=[("disabled", "#7B8794")],
        )
        style.configure(
            "SidePanel.TButton",
            background="#2F3746",
            foreground="#FFFFFF",
            padding=(10, 5),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "SidePanel.TButton",
            background=[("active", "#384255"), ("pressed", "#2A3240")],
            foreground=[("disabled", "#7B8794")],
        )

        style.configure(
            "SidePanelCollect.TButton",
            background="#2F3746",
            foreground="#FFFFFF",
            padding=(10, 5),
            font=style.lookup("Side.TButton", "font"),
            borderwidth=0,
        )

        style.map(
            "SidePanelCollect.TButton",
            background=[("active", "#384255"), ("pressed", "#2A3240")],
            foreground=[("disabled", "#7B8794")],
        )

        style.configure(
            "SidebarSection.TLabel",
            background=UI.PANEL,
            foreground=UI.TEXT_MUTED,
            font=("Segoe UI", 9, "bold"),
        )

        style.configure(
            "ResultsCount.TLabel",
            background=UI.PANEL,
            foreground=UI.TEXT_MUTED,
            font=("Segoe UI", 10, "bold"),
        )

        style.configure(
            "AtelierDark.TFrame",
            background=UI.STRUCT_30,
        )

        style.configure(
            "AtelierPanel.TFrame",
            background="#2B3444",
        )

        style.configure(
            "AtelierTitle.TLabel",
            background=UI.STRUCT_30,
            foreground="#F2F5F8",
            font=("Segoe UI", 12, "bold"),
        )

        style.configure(
            "AtelierTitle2.TLabel",
            background=UI.STRUCT_30,
            foreground="#F2F5F8",
            font=("Segoe UI", 10,),
        )

        style.configure(
            "AtelierHintDark.TLabel",
            background=UI.STRUCT_30,
            foreground="#AEB8C6",
            font=("Segoe UI", 9),
        )

        style.configure(
            "AtelierBox.TLabelframe",
            background="#2B3444",
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "AtelierBox.TLabelframe.Label",
            background="#2B3444",
            foreground="#F2F5F8",
            font=("Segoe UI", 10, "bold"),
        )

        style.configure(
            "Atelier.TRadiobutton",
            background="#2B3444",
            foreground="#E6EBF2",
            font=("Segoe UI", 10),
        )
        style.map(
            "Atelier.TRadiobutton",
            background=[("active", "#2B3444")],
            foreground=[("active", "#FFFFFF")],
        )

        style.configure(
            "Atelier.TEntry",
            fieldbackground="#1F2632",
            foreground="#F2F5F8",
            borderwidth=1,
            relief="solid",
            padding=4,
        )



    def launch_documentation_renamer(self) -> None:
        """
        Ouvre Documentation Renamer.
        Si le programme est déjà ouvert, le remet simplement au premier plan.
        Sinon, le lance.
        """
        if bring_window_to_front(DOC_RENAMER_WINDOW_TITLE):
            return

        base = app_dir()

        candidates = []

        if sys.platform.startswith("win"):
            candidates.extend([
                os.path.join(base, "EigrutelDocumentationRenamer.exe"),
                os.path.join(base, "DocumentationRenamer.exe"),
            ])

        candidates.extend([
            os.path.join(base, "EigrutelDocumentationRenamer.py"),
            os.path.join(base, "documentation.py"),
        ])

        target = next((p for p in candidates if os.path.exists(p)), None)

        if not target:
            messagebox.showerror(
                APP_TITLE,
                "Impossible de trouver EigrutelDocumentationRenamer dans le dossier du programme."
            )
            return

        try:
            if target.lower().endswith(".exe"):
                subprocess.Popen([target], cwd=os.path.dirname(target))
            elif target.lower().endswith(".py"):
                subprocess.Popen([sys.executable, target], cwd=os.path.dirname(target))
            else:
                open_with_default_app(target)
        except Exception as e:
            messagebox.showerror(
                APP_TITLE,
                f"Impossible d'ouvrir Documentation Renamer.\n\n{e}"
            )

    # -------------------------
    # Atelier settings
    # -------------------------
    
    def toggle_collected_only(self) -> None:
        self.collected_only = not self.collected_only
        self.filter_collected_var.set(self.collected_only)

        if self.collected_only:
            self.btn_collected_only.config(style="FavFilterOn.TButton")
        else:
            self.btn_collected_only.config(style="FavFilter.TButton")

        self.run_search()

    def _update_atelier_custom_state(self, duration_var: tk.StringVar, entry_widget):
        try:
            state = "normal" if duration_var.get() == "custom" else "disabled"
            entry_widget.configure(state=state)
        except Exception:
            pass

    def _update_atelier_limit_state(self, limit_mode_var: tk.StringVar, entry_widget):
        try:
            state = "normal" if limit_mode_var.get() == "limit" else "disabled"
            entry_widget.configure(state=state)
        except Exception:
            pass

    def choose_atelier_external_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choisir une image pour l'Atelier",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not path:
            return

        self.atelier_external_file_path = path
        self.settings["atelier_external_file_path"] = path
        save_json(SETTINGS_FILE, self.settings)

        if hasattr(self, "atelier_source_var"):
            self.atelier_source_var.set("external_file")


    def choose_atelier_external_folder(self) -> None:
        path = filedialog.askdirectory(title="Choisir un dossier d'images pour l'Atelier")
        if not path:
            return

        self.atelier_external_folder_path = path
        self.settings["atelier_external_folder_path"] = path
        save_json(SETTINGS_FILE, self.settings)

        if hasattr(self, "atelier_source_var"):
            self.atelier_source_var.set("external_folder")

    def start_atelier_from_panel(self) -> None:
        self._start_atelier_session_from_dialog(
            dlg=self.atelier_panel,
            source_var=self.atelier_source_var,
            duration_var=self.atelier_duration_var,
            custom_var=self.atelier_custom_var,
            order_var=self.atelier_order_var,
            limit_mode_var=self.atelier_limit_mode_var,
            limit_count_var=self.atelier_limit_count_var,
            bg_var=self.atelier_bg_var,
        )
        
    def _start_atelier_session_from_dialog(
        self,
        dlg,
        source_var: tk.StringVar,
        duration_var: tk.StringVar,
        custom_var: tk.StringVar,
        order_var: tk.StringVar,
        limit_mode_var: tk.StringVar,
        limit_count_var: tk.StringVar,
        bg_var: tk.StringVar,
    ) -> None:

        source = source_var.get().strip() or "results"
        bg_choice = bg_var.get().strip() or "dark"

        bg_map = {
            "dark": "#000000",
            "white": "#FFFFFF",
            "neutral": "#808080",
        }
        image_bg = bg_map.get(bg_choice, "#000000")

        if duration_var.get() == "custom":
            try:
                minutes = max(0.1, float(custom_var.get().strip().replace(",", ".")))
                duration_s = int(minutes * 60)
            except Exception:
                messagebox.showwarning(APP_TITLE, "Entrez un temps libre valide en minutes.")
                return
        else:
            try:
                duration_s = int(duration_var.get())
            except Exception:
                messagebox.showwarning(APP_TITLE, "Durée invalide.")
                return

        if duration_s <= 0:
            messagebox.showwarning(APP_TITLE, "La durée doit être supérieure à zéro.")
            return

        if source == "results":
            items = self.results[:]

        elif source == "favorites":
            items = search_images(self.folder, "", limit=RESULT_LIMIT, favorites_only=True)

        elif source == "collected":
            with db_lock:
                conn = db_connect()
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT
                        images.path,
                        images.filename,
                        images.folder,
                        images.width,
                        images.height,
                        COALESCE(user_flags.favorite, 0) AS favorite,
                        COALESCE(user_flags.collected, 0) AS collected
                    FROM images
                    INNER JOIN user_flags
                        ON user_flags.library_root = images.library_root
                       AND user_flags.path = images.path
                    WHERE images.library_root = ?
                      AND user_flags.collected = 1
                    ORDER BY images.folder COLLATE NOCASE, images.filename COLLATE NOCASE
                """, (normalize_library_root(self.folder),)).fetchall()
                conn.close()

            items = []
            for row in rows:
                items.append({
                    "path": row[0],
                    "filename": row[1],
                    "folder": row[2],
                    "width": row[3],
                    "height": row[4],
                    "favorite": int(row[5]),
                    "collected": int(row[6]),
                })

        elif source == "external_file":
            items = []
            item = build_item_from_path(self.atelier_external_file_path)
            if item is not None:
                items.append(item)

        elif source == "external_folder":
            items = []
            folder_path = self.atelier_external_folder_path
            if folder_path and os.path.isdir(folder_path):
                for img_path in iter_any_images(folder_path):
                    item = build_item_from_path(img_path)
                    if item is not None:
                        items.append(item)

        else:
            items = []

        if not items:
            messagebox.showinfo(APP_TITLE, "La source choisie ne contient aucune image.")
            return

        if order_var.get() == "random":
            random.shuffle(items)

        if limit_mode_var.get() == "limit":
            try:
                limit_n = int(limit_count_var.get().strip())
            except Exception:
                messagebox.showwarning(APP_TITLE, "Entrez un nombre d’images valide.")
                return

            if limit_n <= 0:
                messagebox.showwarning(APP_TITLE, "Le nombre d’images doit être supérieur à zéro.")
                return

            items = items[:limit_n]

        if not items:
            messagebox.showinfo(APP_TITLE, "La session ne contient aucune image.")
            return

        # save prefs
        self.settings["atelier_source"] = source_var.get()
        self.settings["atelier_duration_choice"] = duration_var.get()
        self.settings["atelier_custom_minutes"] = custom_var.get().strip()
        self.settings["atelier_order"] = order_var.get()
        self.settings["atelier_limit_mode"] = limit_mode_var.get()
        self.settings["atelier_limit_count"] = limit_count_var.get().strip()
        self.settings["atelier_bg"] = bg_choice
        save_json(SETTINGS_FILE, self.settings)

        # fermeture avant lancement session
        if dlg is self.atelier_panel:
            self.hide_atelier_panel()
        else:
            try:
                dlg.grab_release()
            except Exception:
                pass

            try:
                dlg.destroy()
            finally:
                self.atelier_win = None

        self.root.after(
            10,
            lambda: AtelierSessionWindow(
                self,
                items=items,
                duration_s=duration_s,
                image_bg=image_bg,
            )
        )

    def refresh_indexed_counter(self) -> None:
        n = count_indexed_images(self.folder) if self.folder else 0
        if n <= 0:
            self.index_count_var.set("0 image indexée")
        elif n == 1:
            self.index_count_var.set("1 image indexée")
        else:
            self.index_count_var.set(f"{n} images indexées")

    def refresh_collected_counter(self) -> None:
        n = count_collected_items(self.folder) if self.folder else 0
        if n <= 0:
            self.collected_var.set("0 image dans la collecte")
        elif n == 1:
            self.collected_var.set("1 image dans la collecte")
        else:
            self.collected_var.set(f"{n} iimages dans la collecte")

    def toggle_favorites_only(self) -> None:
        self.favorites_only = not self.favorites_only
        self.filter_favorites_var.set(self.favorites_only)

        if self.favorites_only:
            self.btn_favorites_only.config(style="FavFilterOn.TButton")
        else:
            self.btn_favorites_only.config(style="FavFilter.TButton")

        self.run_search()

    # -------------------------
    # UI
    # -------------------------
    def _build_ui(self) -> None:
        self.pack(fill="both", expand=True)

        # TOPBAR
        topbar = ttk.Frame(self, style="Topbar.TFrame", padding=(14, 10))
        topbar.pack(fill="x")

        ttk.Label(topbar, text="Index Documentation", style="TopbarTitle.TLabel").pack(side="left", padx=(0, 14))

        top_actions = ttk.Frame(topbar, style="Topbar.TFrame")
        top_actions.pack(side="right")

        

        self.btn_info = ttk.Button(
            top_actions,
            text="i",
            style="Side.TButton",
            command=self.open_info_window,
            width=3
        )
        self.btn_info.pack(side="right", padx=(8, 0))

        

        self.btn_bridge_doc = ttk.Button(
            top_actions,
            text="⤴ Documentation",
            style="Side.TButton",
            command=self.launch_documentation_renamer,
        )
        self.btn_bridge_doc.pack(side="right", padx=(8, 0))

        

        search_wrap = ttk.Frame(topbar, style="Topbar.TFrame")
        search_wrap.pack(side="left", fill="x", expand=True, padx=(0, 16))

        tk.Label(
            search_wrap,
            text="Recherche",
            bg=UI.STRUCT_30,
            fg="#ECEFF4",
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(0, 8))

        self.entry_search = tk.Entry(
            search_wrap,
            textvariable=self.search_var,
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            relief="solid",
            bd=1,
            highlightthickness=0,
            insertbackground=UI.TEXT_DARK,
            font=("Segoe UI", 11),
            width=70,
        )
        self.entry_search.pack(side="left", fill="x", expand=True, ipady=7)

        self.search_context_menu = tk.Menu(
            self,
            tearoff=0,
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            activebackground="#DCE3EA",
            activeforeground=UI.TEXT_DARK,
            relief="flat",
            bd=1,
            font=("Segoe UI", 10),
        )

        self.search_context_menu.add_command(
            label="Effacer historique",
            command=self.clear_search_history,
        )
        self.btn_favorites_only = ttk.Button(
            top_actions,
            text="=★",
            style="FavFilter.TButton",
            command=self.toggle_favorites_only,
            width=3,
        )
        self.btn_favorites_only.pack(side="right", padx=(8, 0))

        self.btn_collected_only = ttk.Button(
            top_actions,
            text="=☑",
            style="FavFilter.TButton",
            command=self.toggle_collected_only,
            width=3,
        )
        self.btn_collected_only.pack(side="right", padx=(8, 0))
        self._build_atelier_panel()
        

        # STATUS
        self.lbl_status = None

        # MAIN
        self.main_area = ttk.Frame(self, style="App.TFrame", padding=(12, 0, 12, 12))
        self.main_area.pack(fill="both", expand=True)

        
        # LEFT PANEL
        self.left_panel = ttk.Frame(self.main_area, style="Panel.TFrame")
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.configure(width=self.LEFT_W)
        self.left_panel.pack_propagate(False)

        left_header = ttk.Frame(self.left_panel, style="Panel.TFrame")
        left_header.pack(fill="x", padx=12, pady=(10, 2))

        left_title_row = ttk.Frame(left_header, style="Panel.TFrame")
        left_title_row.pack(fill="x")

        

        self.lbl_results_left = ttk.Label(
            left_title_row,
            textvariable=self.results_var,
            style="ResultsCount.TLabel",
        )
        self.lbl_results_left.pack(side="left", anchor="w")

        left_body = tk.Frame(self.left_panel, bg=UI.PANEL)
        left_body.pack(fill="both", expand=True)

        self.canvas_results = tk.Canvas(
            left_body,
            bg=UI.PANEL,
            highlightthickness=0,
            bd=0,
        )
        self.scroll_results = ttk.Scrollbar(left_body, orient="vertical", command=self.canvas_results.yview)
        self.canvas_results.configure(yscrollcommand=self.scroll_results.set)

        self.scroll_results.pack(side="right", fill="y")
        self.canvas_results.pack(side="left", fill="both", expand=True)

        self.results_container = tk.Frame(self.canvas_results, bg=UI.PANEL)
        self.results_container.grid_columnconfigure(0, weight=1)
        self.results_container.grid_columnconfigure(1, weight=0)
        self.results_columns = 2
        self.results_window = self.canvas_results.create_window((0, 0), window=self.results_container, anchor="nw")

        self.results_container.bind("<Configure>", self._on_results_configure)
        self.canvas_results.bind("<Configure>", self._on_canvas_results_configure)

        # RIGHT PANEL
        # RIGHT SIDE = aperçu + colonne commandes
        right_side = ttk.Frame(self.main_area, style="App.TFrame")
        right_side.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # panneau aperçu principal
        right = ttk.Frame(right_side, style="Panel.TFrame")
        right.pack(side="left", fill="both", expand=True)

        # colonne commandes
        commands = ttk.Frame(right_side, style="Panel.TFrame")
        commands.pack(side="left", fill="y", padx=(12, 0))
        commands.configure(width=220)
        commands.pack_propagate(False)

        cmd_wrap = ttk.Frame(commands, style="Panel.TFrame", padding=(12, 14, 12, 14))
        cmd_wrap.pack(fill="both", expand=True)

        

        self.btn_open_folder = ttk.Button(
            cmd_wrap,
            text="charger DOCUMENTATION",
            style="Accent.TButton",
            command=self.choose_folder,
        )
        self.btn_open_folder.pack(fill="x", pady=(0, 8))

        self.btn_reindex = ttk.Button(
            cmd_wrap,
            text="Indexer / Réindexer",
            style="Accent.TButton",
            command=lambda: self.start_indexing(auto=False),
        )
        self.btn_reindex.pack(fill="x", pady=(0, 10))

        self.index_count_var = tk.StringVar(value="0 image indexée")

        self.lbl_index_count = ttk.Label(
            cmd_wrap,
            textvariable=self.index_count_var,
            style="Muted.TLabel",
            justify="left",
        )
        self.lbl_index_count.pack(anchor="w", fill="x", pady=(0, 10))

       
        #ttk.Separator(cmd_wrap, orient="horizontal").pack(fill="x", pady=(2, 10))

        ttk.Label(
            cmd_wrap,
            text="Filtres de recherche",
            style="SidebarSection.TLabel",
        ).pack(anchor="w", pady=(0, 6))

        filters_box = ttk.Frame(cmd_wrap, style="Panel.TFrame")
        filters_box.pack(fill="x", pady=(0, 12))

        filters_inner = ttk.Frame(filters_box, style="Panel.TFrame")
        filters_inner.pack(fill="x", padx=(2, 0))

        for item in self.filter_definitions:
            ttk.Checkbutton(
                filters_inner,
                text=item["label"],
                variable=self.filter_vars[item["key"]],
                command=self.on_filter_toggle,
                style="SearchFilter.TCheckbutton",
            ).pack(anchor="w", pady=0)

        ttk.Checkbutton(
            filters_inner,
            text="Favoris",
            variable=self.filter_favorites_var,
            command=self.on_filter_flags_toggle,
            style="SearchFilter.TCheckbutton",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Checkbutton(
            filters_inner,
            text="Collecte",
            variable=self.filter_collected_var,
            command=self.on_filter_flags_toggle,
            style="SearchFilter.TCheckbutton",
        ).pack(anchor="w", pady=0)

        ttk.Button(
            filters_box,
            text="Reset recherche",
            style="SidePanelCollect.TButton",
            command=self.reset_search_filters,
        ).pack(fill="x", pady=(8, 0))


        #ttk.Separator(cmd_wrap, orient="horizontal").pack(fill="x", pady=(2, 10))


        self.lbl_collect_total = ttk.Label(
            cmd_wrap,
            textvariable=self.collected_var,
            style="Muted.TLabel",
            justify="left",
        )
        self.lbl_collect_total.pack(anchor="w", fill="x", pady=(0, 8))
        
        self.lbl_collect_feedback = ttk.Label(
            cmd_wrap,
            textvariable=self.collect_feedback_var,
            style="Muted.TLabel",
            justify="left",
        )
        self.lbl_collect_feedback.pack(anchor="w", fill="x", pady=(0, 2))

        
        self.btn_collect_side = ttk.Button(
            cmd_wrap,
            text="☐ image",
            style="SidePanelCollect.TButton",
            command=self.toggle_current_collected,
        )
        self.btn_collect_side.pack(fill="x", pady=(0, 6))

        self.btn_collect_results = ttk.Button(
            cmd_wrap,
            text="☐ tous les résultats",
            style="SidePanelCollect.TButton",
            command=self.collect_all_results,
        )
        self.btn_collect_results.pack(fill="x", pady=(0, 6))

        self.btn_show_collected = ttk.Button(
            cmd_wrap,
            text="Afficher collecte",
            style="SidePanelCollect.TButton",
            command=self.show_collected,
        )
        self.btn_show_collected.pack(fill="x", pady=(0, 8))

        
        self.btn_clear_collected = ttk.Button(
            cmd_wrap,
            text="Purger collecte",
            style="SidePanelCollect.TButton",
            command=self.clear_collected,
        )
        self.btn_clear_collected.pack(fill="x", pady=(0, 6))

        self.btn_export_collected = ttk.Button(
            cmd_wrap,
            text="Exporter collecte",
            style="SidePanelCollect.TButton",
            command=self.export_collected,
        )
        self.btn_export_collected.pack(fill="x", pady=(0, 10))
        
        #ttk.Separator(cmd_wrap, orient="horizontal").pack(fill="x", pady=(4, 10))


        self.btn_atelier = ttk.Button(
            cmd_wrap,
            text="Atelier",
            style="Accent.TButton",
            command=self.toggle_atelier_panel,
        )
        self.btn_atelier.pack(fill="x", pady=(0, 4))


        right_header = ttk.Frame(right, style="Panel.TFrame")
        right_header.pack(fill="x", padx=14, pady=(10, 2))

       

        self.preview_area = tk.Frame(right, bg=UI.PANEL)
        self.preview_area.pack(fill="both", expand=True, padx=14, pady=(14, 8))

        self.preview_label = tk.Label(
    self.preview_area,
        text=(
            "Pour démarrer :\n"
            "1. charger Documentation\n"
            "2. Indexer / réindexer\n\n"
            "Seuls les fichiers image dont le nom commence par\n"
            "DOCUMENTATION_\n"
            "seront indexés"
        ),
        bg=UI.PANEL,
        fg=UI.TEXT_MUTED,
        font=("Segoe UI", 12),
        justify="center",
        anchor="center",
        wraplength=700,
    )
        self.preview_label.pack(fill="both", expand=True)

        info_wrap = ttk.Frame(right, style="Panel.TFrame", padding=(14, 0, 14, 10))
        info_wrap.pack(fill="x")
        name_row = ttk.Frame(info_wrap, style="Panel.TFrame")
        name_row.pack(fill="x")

        self.entry_filename = tk.Entry(
            name_row,
            textvariable=self.filename_edit_var,
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            relief="solid",
            bd=1,
            highlightthickness=0,
            insertbackground=UI.TEXT_DARK,
            font=("Segoe UI", 11,),
        )
        self.entry_filename.pack(side="left", fill="x", expand=True)

        self.btn_rename = ttk.Button(
            name_row,
            text="Renommer",
            style="SidePanelCollect.TButton",
            command=self.rename_current_file,
        )
        self.btn_rename.pack(side="left", padx=(8, 0))

        self.lbl_meta = tk.Label(
            info_wrap,
            textvariable=self.meta_var,
            bg=UI.PANEL,
            fg=UI.TEXT_MUTED,
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
            wraplength=520,
        )
        self.lbl_meta.pack(fill="x", pady=(6, 0))

        info_wrap.bind("<Configure>", self._on_info_wrap_configure)

        btn_row = ttk.Frame(right, style="Panel.TFrame", padding=(14, 2, 14, 14))
        btn_row.pack(fill="x")

        btn_center = ttk.Frame(btn_row, style="Panel.TFrame")
        btn_center.pack(anchor="center")

        self.btn_open_image = ttk.Button(
            btn_center,
            text="Ouvrir image",
            style="SidePanelCollect.TButton",
            command=self.open_current_image,
        )
        self.btn_open_image.pack(side="left", padx=(20, 0))

        self.btn_open_parent = ttk.Button(
            btn_center,
            text="Ouvrir dossier",
            style="SidePanelCollect.TButton",
            command=self.open_current_folder,
        )
        self.btn_open_parent.pack(side="left", padx=(8, 20))

        self.btn_prev_image = ttk.Button(
            btn_center,
            text="← Précédent",
            style="Subtle.TButton",
            command=self.show_previous_image,
        )
        self.btn_prev_image.pack(side="left")

        self.btn_next_image = ttk.Button(
            btn_center,
            text="Suivant →",
            style="Subtle.TButton",
            command=self.show_next_image,
        )
        self.btn_next_image.pack(side="left", padx=(8, 20))

        self.btn_favorite = ttk.Button(
            btn_center,
            text="★",
            style="Fav.TButton",
            command=self.toggle_current_favorite,
            width=2,
        )
        self.btn_favorite.pack(side="left", padx=(0, 8), pady=(0, 6))

        self.btn_collect = ttk.Button(
            btn_center,
            text="☐",
            style="SquareIcon.TButton",
            command=self.toggle_current_collected,
            width=2,
        )
        self.btn_collect.pack(side="left", padx=(0, 8), pady=(0, 6))

        

    def _bind_events(self) -> None:
        self.entry_search.bind("<KeyRelease>", self.on_search_keyrelease)
        self.entry_search.bind("<Return>", self.on_search_enter)
        self.entry_filename.bind("<Control-Return>", self.on_filename_ctrl_return)
        self.entry_search.bind("<Up>", self.search_history_up)
        self.entry_search.bind("<Down>", self.search_history_down)
        self.entry_search.bind("<Button-3>", self._show_search_context_menu)
        self.entry_search.bind("<Button-2>", self._show_search_context_menu)
        self.entry_search.bind("<FocusIn>", self._on_search_focus_in)
        self.entry_search.bind("<Button-1>", self._on_search_focus_in)
        self.root.bind("<Control-o>", lambda _e: self.choose_folder())
        self.root.bind("<Control-F>", lambda _e: self._shortcut_open_image())
        self.root.bind("<Control-O>", lambda _e: self._shortcut_open_current_folder())
        self.root.bind("<Control-l>", self.shortcut_focus_search)
        self.root.bind("<Control-n>", self.shortcut_focus_filename)
        self.root.bind("<F1>", lambda _e: self.open_info_window())
        self.root.bind("<F6>", lambda _e: self.toggle_atelier_panel())
        self.root.bind("<Shift-F6>", self.shortcut_start_atelier_session)
        self.root.bind("<Return>", self.on_return_start_atelier_panel, add="+")
        self.root.bind("<Escape>", self.on_escape_close_atelier_panel)
        self.root.bind("<Left>", self.select_prev)
        self.root.bind("<Right>", self.select_next)
        # --- Raccourcis FAVORI / COLLECTE / ATELIER ---
        self.root.bind("<f>", self.shortcut_toggle_favorite)
        self.root.bind("<k>", self.shortcut_toggle_collected)
        self.root.bind("<K>", self.shortcut_collect_all_results)

        self.root.bind("<Control-k>", self.shortcut_show_collected)
        self.root.bind("<Control-K>", self.shortcut_clear_collected)

        self.root.bind("<Alt-k>", self.shortcut_export_collected)
        self.root.bind("<a>", self.shortcut_toggle_atelier)
        self.canvas_results.bind_all("<MouseWheel>", self._on_mousewheel)
        self.preview_area.bind("<Configure>", self.on_preview_resize)
        
        self.root.bind_all("<Button-1>", self._on_root_click_close_atelier, add="+")
        self.main_area.bind("<Configure>", self._update_left_panel_width)


    def _build_atelier_panel(self) -> None:
        self.atelier_panel = tk.Frame(
            self,
            bg=UI.STRUCT_30,
            bd=0,
            highlightthickness=1,
            highlightbackground="#2B3444",
        )

        self.atelier_panel.place(
            relx=0.14,
            y=self.atelier_panel_y_hidden,
            relwidth=0.72,
            height=self.atelier_panel_height,
        )
        self.atelier_panel.lift()

        outer = ttk.Frame(self.atelier_panel, style="AtelierDark.TFrame", padding=16)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="AtelierDark.TFrame")
        header.pack(fill="x", pady=(0, 8))

        ttk.Label(
            header,
            text="ATELIER",
            style="AtelierTitle.TLabel"
        ).pack(side="left", pady=(2, 3))

        ttk.Label(
            header,
            text=" s'exercer et analyser",
            style="AtelierTitle2.TLabel",
            
        ).pack(side="left")
        
        tk.Button(
            header,
            text="✕",
            command=self.hide_atelier_panel,
            bg=UI.STRUCT_30,
            fg="#E6EBF2",
            activebackground="#2B3444",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Segoe UI", 11, "bold"),
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side="right")


        body = ttk.Frame(outer, style="AtelierDark.TFrame")
        body.pack(fill="both", expand=True)

        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)
        body.columnconfigure(3, weight=1)

        # -------------------------
        # variables panneau atelier
        # -------------------------
        default_source = self.settings.get("atelier_source", "results")
        default_duration = str(self.settings.get("atelier_duration_choice", "120"))
        default_bg = self.settings.get("atelier_bg", "dark")

        if "atelier_custom_minutes" in self.settings:
            default_custom = str(self.settings.get("atelier_custom_minutes", "2"))
        else:
            old_seconds = self.settings.get("atelier_custom_seconds", "120")
            try:
                default_custom = str(max(1, round(float(old_seconds) / 60)))
            except Exception:
                default_custom = "2"

        default_order = self.settings.get("atelier_order", "normal")
        default_limit_mode = self.settings.get("atelier_limit_mode", "all")
        default_limit_count = str(self.settings.get("atelier_limit_count", "20"))

        self.atelier_source_var = tk.StringVar(value=default_source)
        self.atelier_duration_var = tk.StringVar(value=default_duration)
        self.atelier_custom_var = tk.StringVar(value=default_custom)
        self.atelier_order_var = tk.StringVar(value=default_order)
        self.atelier_limit_mode_var = tk.StringVar(value=default_limit_mode)
        self.atelier_limit_count_var = tk.StringVar(value=default_limit_count)
        self.atelier_bg_var = tk.StringVar(value=default_bg)

        # -------------------------
        # ligne 1 : Source + Durée
        # -------------------------
        

        src_box = ttk.LabelFrame(body, text="Source", style="AtelierBox.TLabelframe")
        src_box.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        dur_box = ttk.LabelFrame(body, text="Durée par image", style="AtelierBox.TLabelframe")
        dur_box.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)

        collected_n = count_collected_items()

        with db_lock:
            conn = db_connect()
            cur = conn.cursor()
            favorites_n = cur.execute("""
                SELECT COUNT(*)
                FROM images
                LEFT JOIN user_flags
                    ON user_flags.library_root = images.library_root
                   AND user_flags.path = images.path
                WHERE images.library_root = ?
                  AND COALESCE(user_flags.favorite, 0) = 1
            """, (normalize_library_root(self.folder),)).fetchone()[0]
            conn.close()

        src_wrap = ttk.Frame(src_box, style="AtelierPanel.TFrame")
        src_wrap.pack(fill="both", expand=True, padx=12, pady=10)

        self.rb_atelier_source_results = ttk.Radiobutton(
            src_wrap,
            text=f"Recherche actuelle ({len(self.results)} image(s))",
            value="results",
            variable=self.atelier_source_var,
            style="Atelier.TRadiobutton",
        )
        self.rb_atelier_source_results.pack(anchor="w", pady=1)

        self.rb_atelier_source_favorites = ttk.Radiobutton(
            src_wrap,
            text=f"Favoris ({favorites_n} image(s))",
            value="favorites",
            variable=self.atelier_source_var,
            style="Atelier.TRadiobutton",
        )
        self.rb_atelier_source_favorites.pack(anchor="w", pady=1)

        self.rb_atelier_source_collected = ttk.Radiobutton(
            src_wrap,
            text=f"Collecte ({collected_n} image(s))",
            value="collected",
            variable=self.atelier_source_var,
            style="Atelier.TRadiobutton",
        )
        self.rb_atelier_source_collected.pack(anchor="w", pady=1)

        
        src_actions = ttk.Frame(src_wrap, style="AtelierPanel.TFrame")
        src_actions.pack(fill="x", pady=(8, 0))

        ttk.Button(
            src_actions,
            text="Choisir fichier externe",
            style="SidePanel.TButton",
            command=self.choose_atelier_external_file,
        ).pack(fill="x", pady=(0, 6))

        ttk.Button(
            src_actions,
            text="Choisir dossier externe",
            style="SidePanel.TButton",
            command=self.choose_atelier_external_folder,
        ).pack(fill="x")

        dur_wrap = ttk.Frame(dur_box, style="AtelierPanel.TFrame")
        dur_wrap.pack(fill="both", expand=True, padx=12, pady=10)

        durations = [
            ("30 secondes", "30"),
            ("1 minute", "60"),
            ("2 minutes", "120"),
            ("5 minutes", "300"),
            ("10 minutes", "600"),
            ("30 minutes", "1800"),
        ]

        for i, (label, value) in enumerate(durations):
            ttk.Radiobutton(
                dur_wrap,
                text=label,
                value=value,
                variable=self.atelier_duration_var,
                style="Atelier.TRadiobutton",
                command=lambda: self._update_atelier_custom_state(
                    self.atelier_duration_var,
                    self.atelier_ent_custom
                ),
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 20), pady=2)

        ttk.Radiobutton(
            dur_wrap,
            text="Temps libre",
            value="custom",
            variable=self.atelier_duration_var,
            style="Atelier.TRadiobutton",
            command=lambda: self._update_atelier_custom_state(
                self.atelier_duration_var,
                self.atelier_ent_custom
            ),
        ).grid(row=3, column=0, sticky="w", padx=(0, 10), pady=(4, 2))

        self.atelier_ent_custom = ttk.Entry(
            dur_wrap,
            width=8,
            textvariable=self.atelier_custom_var,
            style="Atelier.TEntry"
        )
        self.atelier_ent_custom.grid(row=3, column=1, sticky="w", padx=(0, 6), pady=(4, 2))

        ttk.Label(
            dur_wrap,
            text="minutes",
            style="AtelierHintDark.TLabel"
        ).grid(row=3, column=1, sticky="w", padx=(86, 0), pady=(4, 2))
        

       

        order_box = ttk.LabelFrame(body, text="Ordre / Nombre d'images", style="AtelierBox.TLabelframe")
        order_box.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)

        bg_box = ttk.LabelFrame(body, text="Fond derrière l’image", style="AtelierBox.TLabelframe")
        bg_box.grid(row=0, column=3, sticky="nsew", padx=6, pady=6)

        

        order_wrap = ttk.Frame(order_box, style="AtelierPanel.TFrame")
        order_wrap.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Radiobutton(
            order_wrap,
            text="Normal",
            value="normal",
            variable=self.atelier_order_var,
            style="Atelier.TRadiobutton"
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            order_wrap,
            text="Aléatoire",
            value="random",
            variable=self.atelier_order_var,
            style="Atelier.TRadiobutton"
        ).pack(anchor="w", pady=(2, 10))

        ttk.Separator(order_wrap, orient="horizontal").pack(fill="x", pady=(2, 8))

        ttk.Label(
            order_wrap,
            text="Nombre d'images",
            style="AtelierHintDark.TLabel"
        ).pack(anchor="w", pady=(0, 4))

        ttk.Radiobutton(
            order_wrap,
            text="Toutes les images",
            value="all",
            variable=self.atelier_limit_mode_var,
            style="Atelier.TRadiobutton",
            command=lambda: self._update_atelier_limit_state(
                self.atelier_limit_mode_var,
                self.atelier_ent_limit
            ),
        ).pack(anchor="w", pady=2)

        limit_row = ttk.Frame(order_wrap, style="AtelierPanel.TFrame")
        limit_row.pack(fill="x", pady=(4, 0))

        ttk.Radiobutton(
            limit_row,
            text="Limiter à",
            value="limit",
            variable=self.atelier_limit_mode_var,
            style="Atelier.TRadiobutton",
            command=lambda: self._update_atelier_limit_state(
                self.atelier_limit_mode_var,
                self.atelier_ent_limit
            ),
        ).pack(side="left")

        self.atelier_ent_limit = ttk.Entry(
            limit_row,
            width=8,
            textvariable=self.atelier_limit_count_var,
            style="Atelier.TEntry"
        )
        self.atelier_ent_limit.pack(side="left", padx=(8, 6))

        ttk.Label(
            limit_row,
            text="images",
            style="AtelierHintDark.TLabel"
        ).pack(side="left")

        bg_wrap = ttk.Frame(bg_box, style="AtelierPanel.TFrame")
        bg_wrap.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Radiobutton(
            bg_wrap,
            text="Sombre",
            value="dark",
            variable=self.atelier_bg_var,
            style="Atelier.TRadiobutton"
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            bg_wrap,
            text="Blanc",
            value="white",
            variable=self.atelier_bg_var,
            style="Atelier.TRadiobutton"
        ).pack(anchor="w", pady=2)

        ttk.Radiobutton(
            bg_wrap,
            text="Neutre",
            value="neutral",
            variable=self.atelier_bg_var,
            style="Atelier.TRadiobutton"
        ).pack(anchor="w", pady=(2, 12))

        ttk.Separator(bg_wrap, orient="horizontal").pack(fill="x", pady=(2, 10))

        ttk.Button(
            bg_wrap,
            text="Démarrer",
            style="Accent.TButton",
            command=self.start_atelier_from_panel,
        ).pack(fill="x")

        
        self._update_atelier_custom_state(self.atelier_duration_var, self.atelier_ent_custom)
        self._update_atelier_limit_state(self.atelier_limit_mode_var, self.atelier_ent_limit)

    def refresh_atelier_panel_counts(self) -> None:
        results_n = len(self.results)
        collected_n = count_collected_items(self.folder)

        with db_lock:
            conn = db_connect()
            cur = conn.cursor()
            favorites_n = cur.execute("""
                SELECT COUNT(*)
                FROM images
                LEFT JOIN user_flags
                    ON user_flags.library_root = images.library_root
                AND user_flags.path = images.path
                WHERE images.library_root = ?
                AND COALESCE(user_flags.favorite, 0) = 1
            """, (normalize_library_root(self.folder),)).fetchone()[0]
            conn.close()

        if self.rb_atelier_source_results is not None:
            self.rb_atelier_source_results.config(
                text=f"Recherche actuelle ({results_n} image(s))"
            )

        if self.rb_atelier_source_favorites is not None:
            self.rb_atelier_source_favorites.config(
                text=f"Favoris ({favorites_n} image(s))"
            )

        if self.rb_atelier_source_collected is not None:
            self.rb_atelier_source_collected.config(
                text=f"Collecte ({collected_n} image(s))"
            )
        
    def toggle_atelier_panel(self) -> None:
        if self.atelier_panel_animating:
            return

        if self.atelier_panel_visible:
            self.hide_atelier_panel()
        else:
            self.show_atelier_panel()


    def show_atelier_panel(self) -> None:
        if self.atelier_panel is None or self.atelier_panel_animating:
            return
        if self.atelier_panel_visible:
            return

        self.refresh_atelier_panel_counts()
        self.atelier_panel.lift()
        self.atelier_panel_animating = True
        self._animate_atelier_panel(self.atelier_panel_y_hidden, self.atelier_panel_y_shown, 24)


    def hide_atelier_panel(self) -> None:
        if self.atelier_panel is None or self.atelier_panel_animating:
            return
        if not self.atelier_panel_visible:
            return

        self.atelier_panel_animating = True
        self._animate_atelier_panel(self.atelier_panel_y_shown, self.atelier_panel_y_hidden, -24)


    def _animate_atelier_panel(self, current_y: int, target_y: int, step: int) -> None:
        if self.atelier_panel is None:
            return

        done = (step > 0 and current_y >= target_y) or (step < 0 and current_y <= target_y)

        if done:
            self.atelier_panel.place_configure(y=target_y)
            self.atelier_panel_animating = False
            self.atelier_panel_visible = (target_y == self.atelier_panel_y_shown)
            return

        self.atelier_panel.place_configure(y=current_y)
        self.atelier_panel.lift()
        self.after(12, lambda: self._animate_atelier_panel(current_y + step, target_y, step))

    def _on_root_click_close_atelier(self, event) -> None:
        widget = event.widget

        # Ignorer tous les clics provenant d'une autre fenêtre Toplevel
        # (session Atelier, fenêtre de grille, boîte de dialogue, etc.)
        try:
            top = widget.winfo_toplevel()
            if top is not self.root:
                return
        except Exception:
            return

        # Sortie des champs texte uniquement dans la fenêtre principale
        if widget not in (self.entry_search, self.entry_filename):
            self.root.focus_set()

        if not self.atelier_panel_visible:
            return

        if self.atelier_panel_animating:
            return

        if self.atelier_panel is None or not self.atelier_panel.winfo_exists():
            return

        panel_x1 = self.atelier_panel.winfo_rootx()
        panel_y1 = self.atelier_panel.winfo_rooty()
        panel_x2 = panel_x1 + self.atelier_panel.winfo_width()
        panel_y2 = panel_y1 + self.atelier_panel.winfo_height()

        click_x = event.x_root
        click_y = event.y_root

        if panel_x1 <= click_x <= panel_x2 and panel_y1 <= click_y <= panel_y2:
            return

        self.hide_atelier_panel()
    def on_escape_close_atelier_panel(self, _event=None):
        if self.atelier_panel_visible and not self.atelier_panel_animating:
            self.hide_atelier_panel()
            return "break"
    # -------------------------
    # Layout helpers
    # -------------------------
    def _on_results_configure(self, _event=None) -> None:
        self.canvas_results.configure(scrollregion=self.canvas_results.bbox("all"))

    def _on_canvas_results_configure(self, event=None):
        if event is None:
            return

        if self.rendering_results:
            return

        sbw = self.scroll_results.winfo_width()
        if sbw <= 1:
            sbw = 18

        width = event.width - sbw - 6
        if width < 100:
            width = event.width

        self.canvas_results.itemconfigure(self.results_window, width=width)

        new_cols = 1 if width < 320 else 2
        if new_cols != self.results_columns:
            self.results_columns = new_cols
            self.root.after_idle(self.render_results)
            self.root.after_idle(self.update_result_highlight)
    def _update_left_panel_width(self, _event=None) -> None:
        if not hasattr(self, "left_panel") or not hasattr(self, "main_area"):
            return

        try:
            total_w = self.main_area.winfo_width()
            if total_w <= 1:
                return

            # garder de la place pour aperçu + colonne commandes
            target = int(total_w * 0.26)

            if target < self.LEFT_W_MIN:
                target = self.LEFT_W_MIN
            if target > self.LEFT_W:
                target = self.LEFT_W

            self.left_panel.configure(width=target)
        except Exception:
            pass

    def _on_mousewheel(self, event):
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if widget and self._is_descendant_of(widget, self.canvas_results):
                self.canvas_results.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _is_descendant_of(self, widget, ancestor) -> bool:
        w = widget
        while w is not None:
            if w == ancestor:
                return True
            try:
                w = w.master
            except Exception:
                return False
        return False

    def _results_signature_from_items(self, items: list[dict]) -> tuple:
        return tuple(
            (item["path"], int(item.get("favorite", 0)), int(item.get("collected", 0)))
            for item in items
        )

    def _get_thumb_photo_cached(self, path: str) -> ImageTk.PhotoImage | None:
        if path in self.thumb_photo_cache:
            return self.thumb_photo_cache[path]

        thumb_file = get_or_create_thumb(path)
        photo = None

        if thumb_file:
            try:
                with Image.open(thumb_file) as im:
                    photo = ImageTk.PhotoImage(im.copy())
            except Exception:
                photo = None

        if len(self.thumb_photo_cache) > 3000:
            self.thumb_photo_cache.clear()

        self.thumb_photo_cache[path] = photo
        return photo
    # -------------------------
    # Info window
    # -------------------------
    def open_info_window(self) -> None:
        if self.info_win is not None and self.info_win.winfo_exists():
            self.info_win.lift()
            self.info_win.focus_force()
            return

        dlg = tk.Toplevel(self.root)
        self.info_win = dlg
        dlg.title("Infos")
        try:
            dlg.iconbitmap(default=os.path.join(app_dir(), "Renamer.ico"))
        except Exception:
            pass
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.minsize(560, 580)

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)

        mid = ttk.Frame(outer)
        mid.pack(fill="both", expand=True)

        txt = tk.Text(
            mid,
            wrap="word",
            bg=getattr(UI, "PANEL", "#FFFFFF"),
            fg="#111111",
            relief="solid",
            bd=1,
            highlightthickness=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 10),
        )
        
        txt.tag_configure("title", font=("Segoe UI", 12, "bold"))
        txt.tag_configure("section", font=("Segoe UI", 11, "bold"))
        txt.tag_configure("subsection", font=("Segoe UI", 10, "bold"))
        txt.tag_configure("body", font=("Segoe UI", 10))
        txt.tag_configure("mono", font=("Consolas", 10))
        txt.tag_configure("link", foreground="#2BA3B8", underline=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        txt.insert("end", "INDEX DOCUMENTATION / aka LA MORGUE - INFOS\n", "title")
        txt.insert("end", "\n")

        txt.insert("end", "À quoi sert ce programme ?\n", "section")
        txt.insert("end", "Index Documentation est un outil de tri et d’exploitation de documentation graphique pour le dessin.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Spécificité\n", "section")
        txt.insert("end", "Index Documentation permet d’explorer rapidement une bibliothèque d’images de référence déjà renommées, organisées en sujets et en utilité graphique (composition, formes, silhouette, couleur, lumière, valeurs, échelle).\n", "body")
        txt.insert("end", "Il permet de les retrouver par mots-clés, de marquer des favoris, de constituer une collecte temporaire pour un projet donné, puis de lancer une session Atelier pour dessiner d’après documents.\n", "body")
        txt.insert("end", "Le programme s’appuie sur les noms de fichiers et les dossiers pour retrouver les images.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Instructions minimales\n", "section")
        txt.insert("end", "\n")

        txt.insert("end", "1. Charger DOCUMENTATION\n", "subsection")
        txt.insert("end", "Cliquez sur charger DOCUMENTATION puis choisissez le dossier que vous souhaitez explorer, avec tous ses sous-dossiers.\n", "body")
        txt.insert("end", "Idéalement, il s’agit du dossier DOCUMENTATION créé et alimenté avec le programme de renommage de documentation, afin de conserver une structure de noms cohérente.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "2. Indexer / Réindexer\n", "subsection")
        txt.insert("end", "Cliquez sur Indexer / Réindexer pour créer ou reconstruire l’index de recherche.\n", "body")
        txt.insert("end", "Le programme parcourt le dossier choisi et ses sous-dossiers, mais n’indexe que les fichiers image dont le nom commence par :\n", "body")
        txt.insert("end", "DOCUMENTATION_\n", "mono")
        txt.insert("end", "Les formats pris en compte sont les formats image usuels compatibles avec le programme.\n", "body")
        txt.insert("end", "L’index est conservé entre les lancements. Il n’est reconstruit que lorsque vous le demandez.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "3. Rechercher\n", "subsection")
        txt.insert("end", "Tapez vos mots dans le champ Recherche.\n", "body")
        txt.insert("end", "La recherche s’effectue sur :\n", "body")
        txt.insert("end", "- le nom du fichier\n", "body")
        txt.insert("end", "- le nom du dossier\n", "body")
        txt.insert("end", "- les mots partiels, sans obligation d’écrire un mot complet\n", "body")
        txt.insert("end", "Le système normalise aussi la recherche : minuscules, accents neutralisés, comparaison simplifiée.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Système de recherche\n", "section")
        txt.insert("end", "La recherche fonctionne avec une logique simple et rapide.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Inclure un ou plusieurs mots\n", "subsection")
        txt.insert("end", "Chaque mot saisi est considéré comme un mot à trouver.\n", "body")
        txt.insert("end", "Exemples :\n", "body")
        txt.insert("end", "- chat\n", "body")
        txt.insert("end", "- chat balle\n", "body")
        txt.insert("end", "- homme modele chapeau\n", "body")
        txt.insert("end", "Dans ce cas, le programme cherche les images contenant ces mots dans leur nom ou leur dossier.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Exclure un mot\n", "subsection")
        txt.insert("end", "Un mot précédé d’un tiret - est exclu.\n", "body")
        txt.insert("end", "Exemples :\n", "body")
        txt.insert("end", "- animal -chat\n", "body")
        txt.insert("end", "- femme velo -ville\n", "body")
        txt.insert("end", "Le programme affichera les résultats contenant les mots demandés, mais éliminera ceux contenant le mot exclu.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Termes partiels\n", "subsection")
        txt.insert("end", "Les fragments de mots sont acceptés.\n", "body")
        txt.insert("end", "Exemples :\n", "body")
        txt.insert("end", "- comp peut retrouver composition\n", "body")
        txt.insert("end", "- che peut retrouver cheval\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Limite utile\n", "subsection")
        txt.insert("end", "Le programme ignore les recherches trop pauvres :\n", "body")
        txt.insert("end", "- une recherche composée uniquement d’exclusions ne part pas\n", "body")
        txt.insert("end", "- les termes de moins de 2 caractères sont ignorés pour éviter le bruit\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Filtres rapides\n", "subsection")
        txt.insert("end", "Des cases permettent d’ajouter automatiquement certains groupes de mots à la recherche :\n", "body")
        txt.insert("end", "- Composition\n", "body")
        txt.insert("end", "- Forme\n", "body")
        txt.insert("end", "- Silhouette\n", "body")
        txt.insert("end", "- Couleur\n", "body")
        txt.insert("end", "- Lumière\n", "body")
        txt.insert("end", "- Valeurs\n", "body")
        txt.insert("end", "- Échelle\n", "body")
        txt.insert("end", "- Favoris\n", "body")
        txt.insert("end", "- Collecte\n", "body")
        txt.insert("end", "Ces filtres servent à orienter très vite la recherche dans une bibliothèque déjà nommée proprement.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Favoris\n", "section")
        txt.insert("end", "Les favoris servent à identifier les images les plus utiles. Ils peuvent être utilisés comme images totems.\n", "body")
        txt.insert("end", "Ils servent à réduire la documentation de façon pertinente.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Règle simple\n", "subsection")
        txt.insert("end", "50 images > 10 intéressantes > 3 utiles > 1 image maîtresse\n", "body")
        txt.insert("end", "Les favoris peuvent devenir ce niveau final : une image claire par idée.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Résultat\n", "subsection")
        txt.insert("end", "- bibliothèque plus petite\n", "body")
        txt.insert("end", "- plus lisible\n", "body")
        txt.insert("end", "- plus efficace\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Conseil\n", "subsection")
        txt.insert("end", "Ajouter un marqueur dans le nom : exemple ", "body")
        txt.insert("end", "_TOTEM\n", "mono")
        txt.insert("end", "\n")

        txt.insert("end", "Quelques usages typiques\n", "subsection")
        txt.insert("end", "- vos meilleures références anatomiques\n", "body")
        txt.insert("end", "- des images très lisibles pour l’étude\n", "body")
        txt.insert("end", "- des documents que vous aimez montrer\n", "body")
        txt.insert("end", "- des images que vous voulez revoir régulièrement\n", "body")
        txt.insert("end", "Les favoris sont mémorisés pour le dossier de documentation chargé. Ils peuvent ensuite servir de source directe pour l’Atelier.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Collecte\n", "section")
        txt.insert("end", "La collecte est une sélection de travail temporaire.\n", "body")
        txt.insert("end", "L’idée n’est pas seulement de mettre de côté une image, mais de constituer un petit ensemble cohérent de références pour un besoin précis.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "À quoi ça sert ?\n", "subsection")
        txt.insert("end", "- préparer la documentation d’un album ou d’une scène\n", "body")
        txt.insert("end", "- rassembler des images pour un personnage, un décor, une ambiance\n", "body")
        txt.insert("end", "- isoler des références pour une séance de croquis\n", "body")
        txt.insert("end", "- constituer un mini-dossier à partager avec un autre dessinateur\n", "body")
        txt.insert("end", "- extraire rapidement un lot d’images utiles pour un projet précis\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Logique de travail\n", "subsection")
        txt.insert("end", "La collecte permet de créer, à un moment donné, un panier documentaire de projet :\n", "body")
        txt.insert("end", "- soit en ajoutant les images une par une\n", "body")
        txt.insert("end", "- soit en ajoutant tous les résultats d’une recherche\n", "body")
        txt.insert("end", "Ensuite, on peut :\n", "body")
        txt.insert("end", "- afficher uniquement la collecte\n", "body")
        txt.insert("end", "- la purger\n", "body")
        txt.insert("end", "- l’exporter dans un dossier à part\n", "body")
        txt.insert("end", "Lors de l’export, les fichiers sont dupliqués dans un nouveau dossier.\n", "body")
        txt.insert("end", "Les images originales restent en place dans la documentation.\n", "body")
        txt.insert("end", "C’est donc un outil très pratique pour fabriquer rapidement un dossier spécifique à une mission, un album, une commande ou un échange entre collègues.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Atelier\n", "section")
        txt.insert("end", "L’Atelier est une visionneuse pensée pour le dessin d’observation et l’entraînement.\n", "body")
        txt.insert("end", "Elle permet d’afficher les images une par une, avec un temps fixe par image ou en temps libre, pour travailler vite et régulièrement d’après documents.\n", "body")
        txt.insert("end", "L’Atelier peut partir :\n", "body")
        txt.insert("end", "- de la recherche actuelle\n", "body")
        txt.insert("end", "- des favoris\n", "body")
        txt.insert("end", "- de la collecte\n", "body")
        txt.insert("end", "- d’un fichier externe\n", "body")
        txt.insert("end", "- d’un dossier externe\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Usages principaux\n", "subsection")
        txt.insert("end", "- s’exercer au dessin d’après documents\n", "body")
        txt.insert("end", "- faire des croquis chronométrés\n", "body")
        txt.insert("end", "- varier les références automatiquement\n", "body")
        txt.insert("end", "- prendre les proportions grâce à une grille ajustable\n", "body")
        txt.insert("end", "- analyser une image avec la grille de composition aux tiers\n", "body")
        txt.insert("end", "- basculer l’image en gris, noir et blanc, valeurs simplifiées ou flou pour mieux lire masses et structures\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "ATELIER — ANALYSE DES IMAGES\n", "section")
        txt.insert("end", "Au-delà du mode normal d’entraînement, l’Atelier permet d’étudier les images et de mieux comprendre leur construction.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Étude des valeurs\n", "subsection")
        txt.insert("end", "Différents modes permettent de simplifier l’image pour analyser les masses :\n", "body")
        txt.insert("end", "- Gris\n", "body")
        txt.insert("end", "- Noir & blanc\n", "body")
        txt.insert("end", "- 3 valeurs\n", "body")
        txt.insert("end", "- 5 valeurs\n", "body")
        txt.insert("end", "- Flou\n", "body")
        txt.insert("end", "Ces outils aident à lire :\n", "body")
        txt.insert("end", "- les contrastes\n", "body")
        txt.insert("end", "- la hiérarchie visuelle\n", "body")
        txt.insert("end", "- les masses principales\n", "body")
        txt.insert("end", "Le choix du fond (clair, sombre, neutre) permet d’adapter la lecture des valeurs.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Composition — étude d’image\n", "subsection")
        txt.insert("end", "Des outils permettent d’analyser la structure de l’image :\n", "body")
        txt.insert("end", "- Grille des tiers et diagonales\n", "body")
        txt.insert("end", "- Grille de proportionnalité\n", "body")
        txt.insert("end", "- Changement de couleur de grille\n", "body")
        txt.insert("end", "- Miroirs (horizontal / vertical)\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Raccourcis clavier — affichage principal\n", "section")
        txt.insert("end", "\n")

        txt.insert("end", "Recherche et navigation générale\n", "subsection")
        txt.insert("end", "- Entrée : lancer la recherche\n", "body")
        txt.insert("end", "- Ctrl + O : charger un dossier DOCUMENTATION\n", "body")
        txt.insert("end", "- Ctrl + L : placer le curseur dans le champ de recherche\n", "body")
        txt.insert("end", "- Ctrl + N : placer le curseur dans le champ de renommage du fichier courant\n", "body")
        txt.insert("end", "- F1 : ouvrir cette fenêtre d’infos\n", "body")
        txt.insert("end", "- F6 : ouvrir / fermer le panneau Atelier\n", "body")
        txt.insert("end", "  Si F6 ne fonctionne pas, utiliser Fn + F6 ou le raccourci alternatif.\n", "body")
        txt.insert("end", "- Maj + F6 : démarrer directement une session Atelier avec les réglages en cours\n", "body")
        txt.insert("end", "- Échap : fermer le panneau Atelier s’il est ouvert\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Navigation dans les résultats\n", "subsection")
        txt.insert("end", "- Flèche gauche : image précédente\n", "body")
        txt.insert("end", "- Flèche droite : image suivante\n", "body")
        txt.insert("end", "- Flèche haut / bas dans le champ de recherche : parcourir l’historique des recherches\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Ouverture des fichiers\n", "subsection")
        txt.insert("end", "- Ctrl + F : ouvrir l’image sélectionnée\n", "body")
        txt.insert("end", "- Ctrl + Maj + O : ouvrir le dossier de l’image sélectionnée\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Favoris, collecte, Atelier\n", "subsection")
        txt.insert("end", "Ces raccourcis ne s’activent pas quand le curseur est dans un champ texte.\n", "body")
        txt.insert("end", "- f : ajouter / retirer l’image courante des favoris\n", "body")
        txt.insert("end", "- k : ajouter / retirer l’image courante à la collecte\n", "body")
        txt.insert("end", "- Maj + K : ajouter tous les résultats actuels à la collecte\n", "body")
        txt.insert("end", "- Ctrl + K : afficher la collecte\n", "body")
        txt.insert("end", "- Ctrl + Maj + K : purger la collecte\n", "body")
        txt.insert("end", "- Alt + K : exporter la collecte\n", "body")
        txt.insert("end", "- a : ouvrir / fermer le panneau Atelier\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Souris\n", "subsection")
        txt.insert("end", "- Clic sur une vignette : sélectionner l’image\n", "body")
        txt.insert("end", "- Double-clic sur une vignette : ouvrir l’image\n", "body")
        txt.insert("end", "- Clic sur le petit carré de collecte d’une vignette : ajouter / retirer directement cette image de la collecte\n", "body")
        txt.insert("end", "- Molette : faire défiler les résultats\n", "body")
        txt.insert("end", "- Clic droit dans la zone recherche : menu contextuel avec effacement de l’historique\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Raccourcis — panneau Atelier\n", "section")
        txt.insert("end", "Le panneau Atelier est le panneau de réglage qui permet de préparer une session.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Depuis l’affichage principal\n", "subsection")
        txt.insert("end", "- F6 : ouvrir / fermer le panneau\n", "body")
        txt.insert("end", "  Si F6 ne fonctionne pas, utiliser Fn + F6 ou le raccourci alternatif.\n", "body")
        txt.insert("end", "- a : ouvrir / fermer le panneau\n", "body")
        txt.insert("end", "- Échap : fermer le panneau\n", "body")
        txt.insert("end", "- Entrée : démarrer la session Atelier si le panneau est ouvert\n", "body")
        txt.insert("end", "- Maj + F6 : démarrer directement la session Atelier\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Réglages disponibles\n", "subsection")
        txt.insert("end", "Dans le panneau Atelier, on peut choisir :\n", "body")
        txt.insert("end", "- la source des images\n", "body")
        txt.insert("end", "- la durée par image\n", "body")
        txt.insert("end", "- l’ordre normal ou aléatoire\n", "body")
        txt.insert("end", "- le nombre d’images\n", "body")
        txt.insert("end", "- le fond derrière l’image\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Raccourcis — dans l’Atelier\n", "section")
        txt.insert("end", "Une fois la session lancée :\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Déplacement dans la session\n", "subsection")
        txt.insert("end", "- Flèche gauche : image précédente\n", "body")
        txt.insert("end", "- Flèche droite : image suivante\n", "body")
        txt.insert("end", "- Espace : pause / reprise\n", "body")
        txt.insert("end", "- Échap : quitter la session\n", "body")
        txt.insert("end", "  Si la petite fenêtre de réglage de grille est ouverte, Échap la ferme d’abord.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Modes d’affichage\n", "subsection")
        txt.insert("end", "- 1 : normal\n", "body")
        txt.insert("end", "- 2 : gris\n", "body")
        txt.insert("end", "- 3 : noir et blanc\n", "body")
        txt.insert("end", "- 4 : 3 valeurs\n", "body")
        txt.insert("end", "- 5 : 5 valeurs\n", "body")
        txt.insert("end", "- 6 : flou\n", "body")
        txt.insert("end", "- 7 : composition\n", "body")
        txt.insert("end", "- 8 : changer la couleur de la grille\n", "body")
        txt.insert("end", "- 9 : afficher / masquer la grille\n", "body")
        txt.insert("end", "Les mêmes commandes existent aussi sur le pavé numérique.\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Transformations de l’image\n", "subsection")
        txt.insert("end", "- m : miroir horizontal\n", "body")
        txt.insert("end", "- p : miroir vertical\n", "body")
        txt.insert("end", "- r : rotation\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Menu contextuel dans l’Atelier\n", "subsection")
        txt.insert("end", "Un clic droit ouvre un menu donnant accès aux mêmes commandes :\n", "body")
        txt.insert("end", "- modes d’affichage\n", "body")
        txt.insert("end", "- composition\n", "body")
        txt.insert("end", "- couleur de grille\n", "body")
        txt.insert("end", "- grille\n", "body")
        txt.insert("end", "- miroirs\n", "body")
        txt.insert("end", "- rotation\n", "body")
        txt.insert("end", "- choix du fond\n", "body")
        txt.insert("end", "- quitter la session\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Renommage rapide dans l’index\n", "section")
        txt.insert("end", "Le programme permet aussi de renommer directement le fichier actuellement sélectionné, sans sortir de l’interface.\n", "body")
        txt.insert("end", "Le renommage :\n", "body")
        txt.insert("end", "- se fait dans le même dossier\n", "body")
        txt.insert("end", "- refuse les caractères interdits sous Windows\n", "body")
        txt.insert("end", "- conserve l’extension si elle n’est pas retapée\n", "body")
        txt.insert("end", "- met à jour l’index après changement de nom\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Fonctionnement général\n", "section")
        txt.insert("end", "- le dossier DOCUMENTATION est choisi une fois puis mémorisé\n", "body")
        txt.insert("end", "- l’index est conservé entre les lancements\n", "body")
        txt.insert("end", "- seules les images nommées selon la logique DOCUMENTATION_... sont indexées\n", "body")
        txt.insert("end", "- les favoris et la collecte sont mémorisés par bibliothèque chargée\n", "body")
        txt.insert("end", "- les miniatures sont générées pour accélérer l’affichage\n", "body")
        txt.insert("end", "- la recherche porte sur les noms de fichiers et de dossiers\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "Philosophie de l’outil\n", "section")
        txt.insert("end", "Index Documentation n’est pas seulement une visionneuse d’images.\n", "body")
        txt.insert("end", "C’est un outil de travail pour dessinateur :\n", "body")
        txt.insert("end", "- retrouver vite\n", "body")
        txt.insert("end", "- trier vite\n", "body")
        txt.insert("end", "- isoler un corpus utile\n", "body")
        txt.insert("end", "- préparer un projet\n", "body")
        txt.insert("end", "- partager une sélection\n", "body")
        txt.insert("end", "- puis passer immédiatement à la pratique grâce à l’Atelier\n", "body")
        txt.insert("end", "Il relie donc trois usages complémentaires :\n", "body")
        txt.insert("end", "1. archiver\n", "body")
        txt.insert("end", "2. retrouver\n", "body")
        txt.insert("end", "3. dessiner\n", "body")
        txt.insert("end", "\n")

        txt.insert("end", "—\n", "section")
        txt.insert("end", "Programme conçu, réalisé et offert par Simon Léturgie.\n", "body")
        txt.insert("end", "Eigrutel BD Academy - 2026\n", "body")
        txt.insert("end", "Site : stripmee.com\n", "link")
        def open_site(event):
            import webbrowser
            webbrowser.open("https://www.stripmee.com")
        txt.tag_bind("link", "<Button-1>", open_site)
        txt.configure(state="disabled")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Fermer", style="Side.TButton", command=dlg.destroy).pack(side="right")

        center_on_parent(dlg, self.root)

        def on_close():
            try:
                dlg.destroy()
            finally:
                self.info_win = None

        dlg.protocol("WM_DELETE_WINDOW", on_close)

    def remember_search(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        if text in self.search_history:
            self.search_history.remove(text)

        self.search_history.insert(0, text)
        self.search_history = self.search_history[:self.search_history_max]

        self.settings["search_history"] = self.search_history
        save_json(SETTINGS_FILE, self.settings)

        self.search_history_index = -1
        self.search_history_current_typed = ""

    def clear_search_history(self) -> None:
        self.search_history = []
        self.search_history_index = -1
        self.search_history_current_typed = ""
        self.search_from_history_nav = False
        self.settings["search_history"] = []
        save_json(SETTINGS_FILE, self.settings)
        self.collect_feedback_var.set("Historique de recherche effacé.")

    def _show_search_context_menu(self, event) -> None:
        try:
            self.search_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.search_context_menu.grab_release()
            except Exception:
                pass

    def on_filter_toggle(self) -> None:
        current_text = self.search_var.get().strip()
        parts = current_text.split() if current_text else []

        # enlever d'abord tous les mots injectés par les filtres
        words_to_remove = set()
        for item in self.filter_definitions:
            for word in item["query"].split():
                words_to_remove.add(normalize_search_text(word))

        kept_parts = [p for p in parts if normalize_search_text(p) not in words_to_remove]

        # réinjecter les groupes de mots correspondant aux cases cochées
        for item in self.filter_definitions:
            if self.filter_vars[item["key"]].get():
                kept_parts.extend(item["query"].split())

        new_text = " ".join(kept_parts).strip()
        self.search_var.set(new_text)

        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None

        self.run_search()

    def sync_filter_checkboxes_from_search(self) -> None:
        current_text = self.search_var.get().strip()
        parts = [normalize_search_text(p) for p in current_text.split()] if current_text else []

        for item in self.filter_definitions:
            query_words = [normalize_search_text(w) for w in item["query"].split()]
            is_present = all(word in parts for word in query_words)
            self.filter_vars[item["key"]].set(is_present)

    def sync_flag_filter_checkboxes(self) -> None:
        self.filter_favorites_var.set(bool(self.favorites_only))
        self.filter_collected_var.set(bool(self.collected_only))

    def reset_search_filters(self) -> None:
        self.search_var.set("")

        for item in self.filter_definitions:
            self.filter_vars[item["key"]].set(False)

        self.favorites_only = False
        self.collected_only = False
        self.filter_favorites_var.set(False)
        self.filter_collected_var.set(False)

        self.btn_favorites_only.config(style="FavFilter.TButton")
        self.btn_collected_only.config(style="FavFilter.TButton")

        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None

        self.collect_feedback_var.set("Recherche réinitialisée.")
        self.run_search()

    def on_filter_flags_toggle(self) -> None:
        self.favorites_only = bool(self.filter_favorites_var.get())
        self.collected_only = bool(self.filter_collected_var.get())

        if self.favorites_only:
            self.btn_favorites_only.config(style="FavFilterOn.TButton")
        else:
            self.btn_favorites_only.config(style="FavFilter.TButton")

        if self.collected_only:
            self.btn_collected_only.config(style="FavFilterOn.TButton")
        else:
            self.btn_collected_only.config(style="FavFilter.TButton")

        self.run_search()

    def _on_search_focus_in(self, _event=None) -> None:
        return

    def search_history_up(self, _event=None):
        if not self.search_history:
            return "break"

        current_text = self.search_var.get()

        if self.search_history_index == -1:
            self.search_history_current_typed = current_text
            if self.search_history and current_text == self.search_history[0]:
                self.search_history_index = 1 if len(self.search_history) > 1 else 0
            else:
                self.search_history_index = 0
        elif self.search_history_index < len(self.search_history) - 1:
            self.search_history_index += 1

        self.search_from_history_nav = True
        self.search_var.set(self.search_history[self.search_history_index])
        self.entry_search.icursor("end")

        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None

        self.run_search()
        return "break"


    def search_history_down(self, _event=None):
        if not self.search_history:
            return "break"

        if self.search_history_index == -1:
            return "break"

        if self.search_history_index > 0:
            self.search_history_index -= 1
            self.search_from_history_nav = True
            self.search_var.set(self.search_history[self.search_history_index])
        else:
            self.search_history_index = -1
            self.search_from_history_nav = True
            self.search_var.set(self.search_history_current_typed)

        self.entry_search.icursor("end")

        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None

        self.run_search()
        return "break"
        # -------------------------
        # Folder / indexing
        # -------------------------
    def choose_folder(self) -> None:
            folder = filedialog.askdirectory(title="Choisir le dossier Documentation")
            if not folder:
                return

            self.folder = folder
            self.settings["folder"] = folder
            save_json(SETTINGS_FILE, self.settings)

            indexed_count = count_indexed_images(self.folder)
            if indexed_count > 0:
                self.status_var.set(f"Dossier : {folder} — index existant chargé ({indexed_count} image(s))")
                self.run_search()
            else:
                self.status_var.set(f"Dossier : {folder} — cliquez sur Réindexer pour créer l'index")

    def start_indexing(self, auto: bool = False) -> None:
            if not self.folder or not os.path.isdir(self.folder):
                if not auto:
                    messagebox.showwarning(APP_TITLE, "Choisissez d'abord un dossier Documentation.")
                return

            if self.indexing:
                return

            self.indexing = True
            self.btn_reindex.state(["disabled"])
            self.btn_open_folder.state(["disabled"])

            def worker():
                try:
                    total = count_supported_images(self.folder)
                    total_bytes = 0
                    self.root.after(
                        0,
                        lambda t=total: self.show_indexing_preview(
                            "Indexation en cours",
                            f"0 / {t}"
                        )
                    )

                    clear_index(self.folder)
                    self.root.after(0, self.reset_collected_filter)
                    self.root.after(0, self.thumb_photo_cache.clear)

                    done = 0
                    for img_path in iter_images(self.folder):
                        filename = os.path.basename(img_path)
                        folder = os.path.dirname(img_path)

                        self.root.after(
                            0,
                            lambda d=done, t=total, p=img_path: self.show_indexing_preview(
                                "Indexation en cours",
                                f"{d} / {t}\n\n{p}"
                            )
                        )

                        try:
                            total_bytes += os.path.getsize(img_path)
                        except Exception:
                            pass

                        w, h = safe_image_size(img_path)
                        insert_record(self.folder, img_path, filename, folder, w, h)
                        done += 1

                        if done % 25 == 0 or done == total:
                            self.root.after(
                                0,
                                lambda d=done, t=total, p=img_path: self.show_indexing_preview(
                                    "Indexation en cours",
                                    f"{d} / {t}\n\n{p}"
                                )
                            )

                    cleanup_user_flags(self.folder)
                    indexed = count_indexed_images(self.folder)
                    total_size_text = format_file_size(total_bytes)

                    self.root.after(0, self.refresh_indexed_counter)
                    self.root.after(
                        0,
                        lambda i=indexed, s=total_size_text: self.show_indexing_preview(
                            "Indexation terminée",
                            f"{i} fichiers indexés\n{s}"
                        )
                    )
                    self.root.after(0, self.run_search)

                except Exception:
                    err = traceback.format_exc()
                    self.root.after(0, lambda: messagebox.showerror(APP_TITLE, f"Erreur pendant l'indexation.\n\n{err}"))
                    self.root.after(0, lambda: self.status_var.set("Erreur d'indexation."))
                finally:
                    self.indexing = False
                    self.root.after(0, lambda: self.btn_reindex.state(["!disabled"]))
                    self.root.after(0, lambda: self.btn_open_folder.state(["!disabled"]))
                    
            threading.Thread(target=worker, daemon=True).start()

        # -------------------------
        # Search
        # -------------------------
    def on_search_keyrelease(self, event=None) -> None:
        if event is not None and event.keysym in ("Up", "Down", "Left", "Right"):
            return

        if self.search_after_id:
            self.root.after_cancel(self.search_after_id)
            self.search_after_id = None

        self.search_history_index = -1

        text = self.search_var.get().strip()

        if text:
            includes, excludes = parse_search_query(text)
            if not includes and excludes:
                return
            short_tokens = [t for t in includes + excludes if len(t) < 2]
            if short_tokens:
                return

        self.search_after_id = self.root.after(SEARCH_DELAY_MS, self.run_search)
    def _focus_in_text_entry(self) -> bool:
        w = self.root.focus_get()
        return w in (self.entry_search, self.entry_filename)

    def shortcut_toggle_favorite(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.toggle_current_favorite()
        return "break"

    def shortcut_toggle_collected(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.toggle_current_collected()
        return "break"

    def shortcut_collect_all_results(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.collect_all_results()
        return "break"

    def shortcut_show_collected(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.show_collected()
        return "break"

    def shortcut_clear_collected(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.clear_collected()
        return "break"

    def shortcut_export_collected(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.export_collected()
        return "break"

    def shortcut_toggle_atelier(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.toggle_atelier_panel()
        return "break"
    
    def shortcut_start_atelier_session(self, _event=None):
        if self._focus_in_text_entry():
            return

        self.start_atelier_from_panel()
        return "break"

    def on_return_start_atelier_panel(self, _event=None):
        if not self.atelier_panel_visible or self.atelier_panel_animating:
            return

        self.start_atelier_from_panel()
        return "break"
    
    def shortcut_focus_search(self, _event=None):
        self.entry_search.focus_set()
        self.entry_search.icursor("end")
        return "break"

    def shortcut_focus_filename(self, _event=None):
        if not self.current_item:
            return "break"
        self.entry_filename.focus_set()
        self.entry_filename.icursor("end")
        return "break"
    def on_filename_ctrl_return(self, _event=None):
        self.rename_current_file()

        try:
            self.root.focus_set()
        except Exception:
            pass

        return "break"

    def on_search_enter(self, _event=None):
            if self.search_after_id:
                self.root.after_cancel(self.search_after_id)
                self.search_after_id = None
            self.run_search()
            return "break"

    def run_search(self) -> None:
        text = self.search_var.get().strip()
        self.sync_filter_checkboxes_from_search()
        self.sync_flag_filter_checkboxes()

        if text:
            if not self.search_from_history_nav:
                self.remember_search(text)
        else:
            self.search_history_index = -1
            self.search_history_current_typed = ""

        self.search_from_history_nav = False

        if text:
            includes, excludes = parse_search_query(text)
            if not includes and excludes:
                return
            short_tokens = [t for t in includes + excludes if len(t) < 2]
            if short_tokens:
                return

        includes, excludes = parse_search_query(text)

        with db_lock:
            conn = db_connect()
            cur = conn.cursor()

            params: list[object] = []
            where_text: list[str] = []

            library_root = normalize_library_root(self.folder) if self.folder else ""
            where_text.append("images.library_root = ?")
            params.append(library_root)

            for token in includes:
                like = f"%{token}%"
                where_text.append("(images.norm_filename LIKE ? OR images.norm_folder LIKE ?)")
                params.extend([like, like])

            for token in excludes:
                like = f"%{token}%"
                where_text.append("NOT (images.norm_filename LIKE ? OR images.norm_folder LIKE ?)")
                params.extend([like, like])

            filter_clause = ""
            if self.favorites_only and self.collected_only:
                filter_clause = "(COALESCE(user_flags.favorite, 0) = 1 OR COALESCE(user_flags.collected, 0) = 1)"
            elif self.favorites_only:
                filter_clause = "COALESCE(user_flags.favorite, 0) = 1"
            elif self.collected_only:
                filter_clause = "COALESCE(user_flags.collected, 0) = 1"

            wheres: list[str] = []
            if where_text:
                wheres.extend(where_text)
            if filter_clause:
                wheres.append(filter_clause)

            sql = """
                SELECT
                    images.path,
                    images.filename,
                    images.folder,
                    images.width,
                    images.height,
                    COALESCE(user_flags.favorite, 0) AS favorite,
                    COALESCE(user_flags.collected, 0) AS collected
                FROM images
                LEFT JOIN user_flags
                    ON user_flags.library_root = images.library_root
                   AND user_flags.path = images.path
            """

            if wheres:
                sql += "\nWHERE " + " AND ".join(wheres)

            sql += """
                ORDER BY images.folder COLLATE NOCASE, images.filename COLLATE NOCASE
                LIMIT ?
            """
            params.append(RESULT_LIMIT)

            rows = cur.execute(sql, params).fetchall()
            conn.close()

        new_results = []
        for row in rows:
            new_results.append({
                "path": row[0],
                "filename": row[1],
                "folder": row[2],
                "width": row[3],
                "height": row[4],
                "favorite": int(row[5]),
                "collected": int(row[6]),
            })

        new_signature = self._results_signature_from_items(new_results)
        results_changed = (new_signature != self.results_signature)

        old_path = self.current_item["path"] if self.current_item else None

        self.results = new_results
        self.results_signature = new_signature

        n = len(self.results)

        if n >= RESULT_LIMIT:
            base_label = f"plus de {RESULT_LIMIT} résultats"
        elif n == 0:
            base_label = "0 résultat"
        elif n == 1:
            base_label = "1 résultat"
        else:
            base_label = f"{n} résultats"

        if self.favorites_only and self.collected_only:
            self.results_var.set(f"{base_label} • fav/collecte")
        elif self.favorites_only:
            self.results_var.set(f"{base_label} • favoris")
        elif self.collected_only:
            self.results_var.set(f"{base_label} • collecte")
        else:
            self.results_var.set(base_label)

        if results_changed:
            previous_yview = self.canvas_results.yview()

            self.render_results()

            if self.preserve_results_scroll:
                if previous_yview:
                    self.canvas_results.yview_moveto(previous_yview[0])
                self.preserve_results_scroll = False
            else:
                self.canvas_results.yview_moveto(0.0)
                self.root.after(10, lambda: self.canvas_results.yview_moveto(0.0))
        if self.results:
            idx = 0
            if old_path:
                for i, item in enumerate(self.results):
                    if item["path"] == old_path:
                        idx = i
                        break

            if (
                results_changed
                or self.current_idx != idx
                or self.current_item is None
                or self.current_item["path"] != self.results[idx]["path"]
            ):
                self.show_item(idx)
            else:
                self.current_item = self.results[idx]
                self.preview_source_path = self.current_item["path"]
                self.filename_edit_var.set(self.current_item["filename"])

                folder_only = self.current_item["folder"]
                short_filename = truncate_end(self.current_item["filename"], 120)
                self.meta_var.set(f"{folder_only}\n{short_filename}")

                self._refresh_current_buttons()
                self.update_result_highlight()
        else:
            self.clear_preview()
        self.refresh_atelier_panel_counts()

        # -------------------------
        # Results
        # -------------------------
    def render_results(self) -> None:
        if self.rendering_results:
            self.pending_results_render = True
            return

        self.rendering_results = True
        try:
            for child in self.results_container.winfo_children():
                child.destroy()

            self.thumb_refs = []
            self.result_cards = []
            self.result_collected_badges = {}
            self.result_favorite_badges = {}

            for c in range(2):
                self.results_container.grid_columnconfigure(c, weight=0)

            for c in range(self.results_columns):
                self.results_container.grid_columnconfigure(c, weight=1)

            if not self.results:
                tk.Label(
                    self.results_container,
                    text="Aucun résultat",
                    bg=UI.PANEL,
                    fg=UI.TEXT_MUTED,
                    font=("Segoe UI", 10),
                    pady=20
                ).grid(row=0, column=0, columnspan=self.results_columns, sticky="ew")
                return

            for idx, item in enumerate(self.results):
                self._make_result_thumb(idx, item)

        finally:
            self.rendering_results = False

            if self.pending_results_render:
                self.pending_results_render = False
                self.root.after_idle(self.render_results)
    def _make_result_thumb(self, idx: int, item: dict) -> None:
        col = idx % self.results_columns
        row = idx // self.results_columns

        outer = tk.Frame(
            self.results_container,
            bg=UI.PANEL,
            bd=1,
            highlightthickness=1,
            highlightbackground=UI.BORDER,
            cursor="hand2",
        )
        self.result_cards.append(outer)
        self.results_container.grid_columnconfigure(col, weight=1)
        outer.grid(row=row, column=col, padx=8, pady=8, sticky="ew")

        if self.results_columns == 2 and col == 1:
            outer.grid_configure(padx=(8, 24))
        else:
            outer.grid_configure(padx=8)

        photo = self._get_thumb_photo_cached(item["path"])

        if photo is not None:
            self.thumb_refs.append(photo)
            lbl = tk.Label(
                outer,
                image=photo,
                bg=UI.PANEL,
                cursor="hand2",
                width=THUMB_SIZE[0],
                height=THUMB_SIZE[1],
            )
        else:
            lbl = tk.Label(
                outer,
                text="[image]",
                width=20,
                height=10,
                bg=UI.BG_60,
                fg=UI.TEXT_MUTED,
                cursor="hand2",
            )

        lbl.pack(padx=6, pady=6)

        lbl_favorite = tk.Label(
            outer,
            text="★",
            bg=outer["bg"],
            fg="#ffc862",
            font=("Segoe UI", 11, "bold"),
            padx=3,
            pady=0,
        )

        if int(item.get("favorite", 0)):
            lbl_favorite.place(x=8, y=6)

        self.result_favorite_badges[item["path"]] = lbl_favorite

        collected_text = "☑" if int(item.get("collected", 0)) else "☐"
        lbl_collected = tk.Label(
            outer,
            text=collected_text,
            bg=outer["bg"],
            fg="#000000",
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
        )
        lbl_collected.place(x=30, y=8)
        lbl_collected.bind("<Button-1>", lambda e, i=idx: (self.toggle_collected_from_result_thumb(i), "break")[1])

        self.result_collected_badges[item["path"]] = lbl_collected
        outer.bind("<Button-1>", lambda _e, i=idx: self.show_item(i))
        lbl.bind("<Button-1>", lambda _e, i=idx: self.show_item(i))
        outer.bind("<Double-Button-1>", lambda _e, p=item["path"]: self.open_image_path(p))
        lbl.bind("<Double-Button-1>", lambda _e, p=item["path"]: self.open_image_path(p))
    def update_result_highlight(self) -> None:
            for i, card in enumerate(self.result_cards):
                try:
                    if i == self.current_idx:
                        card.config(
                            highlightbackground=UI.ACCENT_10,
                            highlightcolor=UI.ACCENT_10,
                            highlightthickness=2,
                            bd=1,
                        )
                    else:
                        card.config(
                            highlightbackground=UI.BORDER,
                            highlightcolor=UI.BORDER,
                            highlightthickness=1,
                            bd=1,
                        )
                except Exception:
                    pass

    def refresh_results_view_only(self) -> None:
        self.render_results()
        self.update_result_highlight()
        
    def update_single_result_collected_badge(self, path: str, collected_value: int) -> None:
        badge = self.result_collected_badges.get(path)
        if badge is None:
            return

        try:
            badge.config(text="☑" if int(collected_value) else "☐")
        except Exception:
            pass

    def update_single_result_favorite_badge(self, path: str, favorite_value: int) -> None:
        badge = self.result_favorite_badges.get(path)
        if badge is None:
            return

        try:
            if int(favorite_value):
                badge.place(x=8, y=6)
            else:
                badge.place_forget()
        except Exception:
            pass

    def scroll_selected_thumb_into_view(self) -> None:
            if self.current_idx < 0 or self.current_idx >= len(self.result_cards):
                return

            try:
                self.root.update_idletasks()

                card = self.result_cards[self.current_idx]
                card_y = card.winfo_y()
                card_h = card.winfo_height()

                canvas_h = self.canvas_results.winfo_height()
                top_frac, bottom_frac = self.canvas_results.yview()

                total_h = max(1, self.results_container.winfo_height())
                visible_top = top_frac * total_h
                visible_bottom = bottom_frac * total_h

                if card_y < visible_top:
                    self.canvas_results.yview_moveto(card_y / total_h)
                elif card_y + card_h > visible_bottom:
                    target = (card_y + card_h - canvas_h) / total_h
                    if target < 0:
                        target = 0
                    self.canvas_results.yview_moveto(target)
            except Exception:
                pass

        # -------------------------
        # Preview
        # -------------------------

    def show_indexing_preview(self, text: str, subtext: str = "") -> None:
            self.current_idx = -1
            self.current_item = None
            self.preview_ref = None
            self.preview_source_path = None
            self.filename_edit_var.set("")
            self.meta_var.set("")
            self._refresh_current_buttons()

            display_text = text
            if subtext:
                display_text += f"\n\n{subtext}"

            self.preview_label.config(
                image="",
                text=display_text,
                justify="center",
                anchor="center",
                wraplength=max(300, self.preview_area.winfo_width() - 40),
            )

    def clear_preview(self) -> None:
        self.current_idx = -1
        self.current_item = None
        self.preview_ref = None
        self.preview_source_path = None

        text = "Aucun résultat"

        has_folder = bool(self.folder and os.path.isdir(self.folder))
        indexed_count = count_indexed_images(self.folder) if has_folder else 0
        search_text = self.search_var.get().strip()

        if not has_folder or indexed_count <= 0:
            text = (
                "Pour démarrer :\n"
                "1. charger Documentation\n"
                "2. Indexer / réindexer\n\n"
                "Seuls les fichiers image dont le nom commence par\n"
                "DOCUMENTATION_\n"
                "seront indexés"
            )
        elif not self.results and search_text:
            text = "Aucun résultat"

        self.preview_label.config(
            image="",
            text=text
        )

        self.filename_edit_var.set("")
        self.meta_var.set("")
        self.update_result_highlight()
        self._refresh_current_buttons()

    def show_item(self, idx: int) -> None:
            if idx < 0 or idx >= len(self.results):
                self.clear_preview()
                return

            self.current_idx = idx
            self.ending_screen = False
            self.current_item = self.results[idx]
            self.preview_source_path = self.current_item["path"]

            self.filename_edit_var.set(self.current_item["filename"])

            folder_only = self.current_item["folder"]
            short_filename = truncate_end(self.current_item["filename"], 120)
            self.meta_var.set(f"{folder_only}\n{short_filename}")
            self.refresh_preview_image()
            self._refresh_current_buttons()
            self.update_result_highlight()
            self.scroll_selected_thumb_into_view()

    def refresh_preview_image(self) -> None:
            if not self.preview_source_path:
                return

            try:
                self.preview_area.update_idletasks()
                max_w = max(200, self.preview_area.winfo_width() - 20)
                max_h = max(200, self.preview_area.winfo_height() - 20)

                with Image.open(self.preview_source_path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((max_w, max_h), Image.LANCZOS)
                    self.preview_ref = ImageTk.PhotoImage(im.copy())

                self.preview_label.config(image=self.preview_ref, text="")
            except Exception:
                self.preview_ref = None
                self.preview_label.config(image="", text="Impossible d'afficher l'image")

    def on_preview_resize(self, _event=None) -> None:
        if not self.current_item:
            return

        if self.preview_resize_after_id:
            try:
                self.root.after_cancel(self.preview_resize_after_id)
            except Exception:
                pass
            self.preview_resize_after_id = None

        self.preview_resize_after_id = self.root.after(80, self._refresh_preview_after_resize)
    
    def _refresh_preview_after_resize(self) -> None:
        self.preview_resize_after_id = None
        if self.current_item:
            self.refresh_preview_image()
        # -------------------------
        # Actions
        # -------------------------
        
    def _on_info_wrap_configure(self, event=None) -> None:
        if not hasattr(self, "lbl_meta"):
            return
        try:
            wrap = max(180, int(event.width) - 4)
            self.lbl_meta.config(wraplength=wrap)
        except Exception:
            pass
    def rename_current_file(self) -> None:
            if not self.current_item:
                return

            old_path = self.current_item["path"]
            old_folder = self.current_item["folder"]
            old_filename = self.current_item["filename"]

            new_filename = self.filename_edit_var.get().strip()
            if not new_filename:
                messagebox.showwarning(APP_TITLE, "Le nom du fichier ne peut pas être vide.")
                return

            invalid_chars = '<>:"/\\|?*'
            if any(c in new_filename for c in invalid_chars):
                messagebox.showwarning(APP_TITLE, "Le nom contient des caractères interdits pour Windows.")
                return

            old_ext = os.path.splitext(old_filename)[1]
            new_ext = os.path.splitext(new_filename)[1]

            if not new_ext:
                new_filename += old_ext

            if new_filename == old_filename:
                return

            new_path = os.path.join(old_folder, new_filename)

            if os.path.exists(new_path):
                messagebox.showwarning(APP_TITLE, "Un fichier portant ce nom existe déjà dans ce dossier.")
                return

            try:
                os.rename(old_path, new_path)
                self.thumb_photo_cache.pop(old_path, None)
                rename_image_record(self.folder, old_path, new_path)

                self.current_item["path"] = new_path
                self.current_item["filename"] = os.path.basename(new_path)
                self.current_item["folder"] = os.path.dirname(new_path)
                self.preview_source_path = new_path
                self.filename_edit_var.set(os.path.basename(new_path))

                folder_only = os.path.dirname(new_path)
                short_filename = truncate_end(os.path.basename(new_path), 50)
                self.meta_var.set(f"{folder_only}\n{short_filename}")

                short_name = truncate_end(os.path.basename(new_path), 100)
                self.status_var.set(f"Fichier renommé : {short_name}")
                current_path = new_path
                self.preserve_results_scroll = True
                self.run_search()

                for i, item in enumerate(self.results):
                    if item["path"] == current_path:
                        self.show_item(i)
                        break

            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Impossible de renommer le fichier.\n\n{e}")

    def toggle_collected_from_result_thumb(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.results):
            return

        item = self.results[idx]
        path = item["path"]
        old_value = int(item.get("collected", 0))

        new_value = toggle_collected(self.folder, path)
        item["collected"] = int(new_value)

        if self.current_item and self.current_item["path"] == path:
            self.current_item["collected"] = int(new_value)

        if int(new_value):
            self.collect_feedback_var.set("1 image ajoutée à la collecte.")
        else:
            self.collect_feedback_var.set("1 image retirée de la collecte.")

        self.refresh_collected_counter()
        self._refresh_current_buttons()
        self.refresh_atelier_panel_counts()

        if self.collected_only and old_value == 1 and int(new_value) == 0:
            self.run_search()
            return

        self.update_single_result_collected_badge(path, int(new_value))
    def toggle_current_favorite(self) -> None:
        if not self.current_item:
            return

        path = self.current_item["path"]
        new_value = toggle_favorite(self.folder, path)
        self.current_item["favorite"] = int(new_value)

        for item in self.results:
            if item["path"] == path:
                item["favorite"] = int(new_value)
                break

        self._refresh_current_buttons()
        self.refresh_atelier_panel_counts()

        if self.favorites_only and int(new_value) == 0:
            self.run_search()
            return

        self.update_single_result_favorite_badge(path, int(new_value))

    def toggle_current_collected(self) -> None:
        if not self.current_item:
            return

        path = self.current_item["path"]
        old_value = int(self.current_item.get("collected", 0))

        new_value = toggle_collected(self.folder, path)
        self.current_item["collected"] = int(new_value)

        # synchroniser aussi l'item dans self.results
        target_idx = -1
        for i, item in enumerate(self.results):
            if item["path"] == path:
                item["collected"] = int(new_value)
                target_idx = i
                break

        if int(new_value):
            self.collect_feedback_var.set("1 image ajoutée à la collecte.")
        else:
            self.collect_feedback_var.set("1 image retirée de la collecte.")

        self._refresh_current_buttons()
        self.refresh_collected_counter()
        self.refresh_atelier_panel_counts()

        # si on est en mode collecte et qu'on retire l'image, elle doit disparaître
        if self.collected_only and old_value == 1 and int(new_value) == 0:
            self.run_search()
            return

        # sinon, on met juste à jour le badge de la miniature concernée
        self.update_single_result_collected_badge(path, int(new_value))
    def collect_all_results(self) -> None:
            
            if not self.results:
                messagebox.showinfo(APP_TITLE, "Aucun résultat à collecter.")
                return

            paths = [item["path"] for item in self.results]
            added = collect_paths(self.folder, paths)

            if added <= 0:
                self.collect_feedback_var.set("Aucun ajout à la collecte.")
            elif added == 1:
                self.collect_feedback_var.set("1 image ajoutée à la collecte.")
            else:
                self.collect_feedback_var.set(f"{added} images ajoutées à la collecte.")

            self.refresh_collected_counter()
            self.run_search()

    def show_collected(self) -> None:
            self.search_var.set("")

            self.favorites_only = False
            self.collected_only = True

            self.btn_favorites_only.config(style="FavFilter.TButton")
            self.btn_collected_only.config(style="FavFilterOn.TButton")

            self.collect_feedback_var.set("Affichage de la collecte.")
            self.run_search()
    
    def reset_collected_filter(self) -> None:
        self.collected_only = False
        self.filter_collected_var.set(False)
        self.btn_collected_only.config(style="FavFilter.TButton")
        self.collect_feedback_var.set("")

    def _refresh_current_buttons(self) -> None:
            if not self.current_item:
                self.btn_favorite.config(text="☆")
                self.btn_collect.config(text="☐")
                if hasattr(self, "btn_collect_side"):
                    self.btn_collect_side.config(text="☐ Image")
                return

            if int(self.current_item.get("favorite", 0)):
                self.btn_favorite.config(style="FavOn.TButton")
            else:
                self.btn_favorite.config(style="Fav.TButton")

            if int(self.current_item.get("collected", 0)):
                self.btn_collect.config(text="☑")
                if hasattr(self, "btn_collect_side"):
                    self.btn_collect_side.config(text="☑ Image")
            else:
                self.btn_collect.config(text="☐")
                if hasattr(self, "btn_collect_side"):
                    self.btn_collect_side.config(text="☐ Image")
    def clear_collected(self) -> None:
            n = count_collected_items(self.folder)
            if n <= 0:
                messagebox.showinfo(APP_TITLE, "La collecte est déjà vide.")
                return

            if not messagebox.askyesno(APP_TITLE, f"Vider la collecte ({n} image(s)) ?"):
                return

            clear_collected_items(self.folder)
            self.collect_feedback_var.set("Collecte purgée.")
            self.refresh_collected_counter()
            self.reset_collected_filter()
            self.run_search()
    def export_collected(self) -> None:
            with db_lock:
                conn = db_connect()
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT images.path, images.filename
                    FROM images
                    INNER JOIN user_flags ON user_flags.path = images.path
                    WHERE user_flags.collected = 1
                    ORDER BY images.folder COLLATE NOCASE, images.filename COLLATE NOCASE
                """).fetchall()
                conn.close()

            if not rows:
                messagebox.showinfo(APP_TITLE, "Aucune image dans la collecte.")
                return

            dest = filedialog.askdirectory(title="Choisir le dossier d'export de la collecte")
            if not dest:
                return

            copied = 0
            errors = []

            import shutil

            for src_path, filename in rows:
                try:
                    target_path = os.path.join(dest, filename)

                    if os.path.exists(target_path):
                        base, ext = os.path.splitext(filename)
                        i = 2
                        while True:
                            candidate = os.path.join(dest, f"{base}_{i}{ext}")
                            if not os.path.exists(candidate):
                                target_path = candidate
                                break
                            i += 1

                    shutil.copy2(src_path, target_path)
                    copied += 1
                except Exception as e:
                    errors.append(f"{filename} : {e}")

            if errors:
                messagebox.showwarning(
                    APP_TITLE,
                    f"{copied} image(s) copiée(s).\n\nCertaines copies ont échoué :\n\n" + "\n".join(errors[:15])
                )
            else:
                messagebox.showinfo(APP_TITLE, f"{copied} image(s) copiée(s) dans :\n{dest}")

    def open_image_path(self, path: str) -> None:
            try:
                open_with_default_app(path)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Impossible d'ouvrir l'image.\n\n{e}")

    def open_current_image(self) -> None:
            if not self.current_item:
                return
            self.open_image_path(self.current_item["path"])

    def open_current_folder(self) -> None:
            if not self.current_item:
                return
            try:
                open_folder(self.current_item["folder"])
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Impossible d'ouvrir le dossier.\n\n{e}")

    def show_previous_image(self) -> None:
            if not self.results:
                return
            if self.current_idx <= 0:
                self.show_item(0)
            else:
                self.show_item(self.current_idx - 1)

    def show_next_image(self) -> None:
            if not self.results:
                return
            if self.current_idx < 0:
                self.show_item(0)
            else:
                self.show_item(min(len(self.results) - 1, self.current_idx + 1))

    def _shortcut_open_image(self):
            self.open_current_image()
            return "break"

    def _shortcut_open_current_folder(self):
            self.open_current_folder()
            return "break"

        # -------------------------
        # Keyboard nav
        # -------------------------
    def select_prev(self, _event=None):
        if self._focus_in_text_entry():
            return
        self.show_previous_image()
        return "break"

    def select_next(self, _event=None):
            if self._focus_in_text_entry():
                return
            self.show_next_image()
            return "break"


# =========================
# MAIN
# =========================
def main() -> None:
    root = tk.Tk()
    IndexDocumentationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
