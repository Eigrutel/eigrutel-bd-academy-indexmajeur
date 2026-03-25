# -*- coding: utf-8 -*-
"""
Détection de doublons d'images – Eigrutel Tools
"""

from __future__ import annotations

import os
import sqlite3
import hashlib
import subprocess
import threading
from pathlib import Path


import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk

from ui_common import UI, apply_style, apply_app_icon, app_dir

SUPPORTED = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif")
DB_NAME = os.path.join(app_dir(), "doublons_index.db")


# ----------------------------
# OUTILS
# ----------------------------

def format_size(num_bytes: int) -> str:
    if num_bytes is None:
        return "?"
    value = float(num_bytes)
    for unit in ["octets", "Ko", "Mo", "Go", "To"]:
        if value < 1024 or unit == "To":
            if unit == "octets":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} octets"


def get_dup_folder_for_source(source_folder: str) -> str:
    source_folder = os.path.abspath(source_folder)
    drive = os.path.splitdrive(source_folder)[0].upper()

    if drive == "C:":
        home = Path.home()
        docs = home / "Documents"
        if not docs.exists():
            docs = home
        target = docs / "Doublons"
    else:
        target = Path(drive + os.sep) / "Doublons"

    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def normpath_abs(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


# ----------------------------
# HASH EXACT
# ----------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ----------------------------
# DHASH VISUEL
# ----------------------------

def dhash(image, size=8):
    image = image.convert("L").resize((size + 1, size), Image.LANCZOS)

    diff = []
    for y in range(size):
        for x in range(size):
            left = image.getpixel((x, y))
            right = image.getpixel((x + 1, y))
            diff.append(left > right)

    value = 0
    for i, v in enumerate(diff):
        if v:
            value |= 1 << i

    return value


def hamming(a, b):
    return bin(a ^ b).count("1")


# ----------------------------
# BASE SQLITE
# ----------------------------

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS images(
        path TEXT PRIMARY KEY,
        name TEXT,
        size INTEGER,
        width INTEGER,
        height INTEGER,
        sha256 TEXT,
        dhash TEXT
    )
    """)

    conn.commit()
    return conn


def clear_db(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM images")
    conn.commit()


def get_image_info(conn, path: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT path, name, size, width, height, sha256, dhash
        FROM images
        WHERE path=?
    """, (normpath_abs(path),))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "path": row[0],
        "name": row[1],
        "size": row[2],
        "width": row[3],
        "height": row[4],
        "sha256": row[5],
        "dhash": row[6],
    }


# ----------------------------
# SCAN DOSSIER
# ----------------------------
def count_supported_images(folder, ignore_names=None, recursive=True):
    ignore_names = set(ignore_names or [])
    total = 0

    if recursive:
        walker = os.walk(folder)
    else:
        try:
            files = os.listdir(folder)
        except Exception:
            files = []
        walker = [(folder, [], files)]

    for root, dirs, files in walker:
        dirs[:] = [d for d in dirs if d not in ignore_names]
        for f in files:
            if f.lower().endswith(SUPPORTED):
                total += 1

    return total
def scan_folder(folder, conn, ignore_names=None, recursive=True, progress_cb=None):
    ignore_names = set(ignore_names or [])
    cur = conn.cursor()
    done = 0

    if recursive:
        walker = os.walk(folder)
    else:
        try:
            files = os.listdir(folder)
        except Exception:
            files = []
        walker = [(folder, [], files)]

    for root, dirs, files in walker:
        dirs[:] = [d for d in dirs if d not in ignore_names]

        for f in files:
            if not f.lower().endswith(SUPPORTED):
                continue

            path = normpath_abs(os.path.join(root, f))

            try:
                size = os.path.getsize(path)

                with Image.open(path) as img:
                    width, height = img.size
                    sha = sha256_file(path)
                    dh = format(dhash(img), "016x")

                cur.execute("""
                INSERT OR REPLACE INTO images
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    path,
                    f,
                    size,
                    width,
                    height,
                    sha,
                    dh
                ))

            except Exception as e:
                print("Erreur :", path, e)

            done += 1
            if progress_cb and (done % 10 == 0 or done == 1):
                progress_cb(done, f)

    conn.commit()

    if progress_cb:
        progress_cb(done, "")

# ----------------------------
# DOUBLONS EXACTS
# ----------------------------

def find_exact(conn):
    cur = conn.cursor()

    cur.execute("""
    SELECT sha256, COUNT(*)
    FROM images
    GROUP BY sha256
    HAVING COUNT(*) > 1
    """)

    groups = []

    for sha, _count in cur.fetchall():
        cur.execute("""
        SELECT path FROM images
        WHERE sha256=?
        ORDER BY path
        """, (sha,))

        files = [r[0] for r in cur.fetchall() if os.path.exists(r[0])]

        if len(files) > 1:
            groups.append({
                "type": "exact",
                "paths": files,
            })

    groups.sort(key=lambda g: len(g["paths"]), reverse=True)
    return groups


# ----------------------------
# DOUBLONS VISUELS
# ----------------------------

def find_visual(conn, threshold=5):
    cur = conn.cursor()

    cur.execute("""
        SELECT path, dhash, width, height
        FROM images
        ORDER BY path
    """)
    rows = []
    for (p, h, w, hh) in cur.fetchall():
        if not os.path.exists(p):
            continue
        try:
            h_int = int(h, 16)
        except Exception:
            continue
        rows.append((p, h_int, w, hh))

    groups = []
    used = set()

    for i in range(len(rows)):
        p1, h1, w1, hh1 = rows[i]

        if p1 in used:
            continue

        group = [p1]

        for j in range(i + 1, len(rows)):
            p2, h2, w2, hh2 = rows[j]

            if p2 in used:
                continue

            if (w1, hh1) != (w2, hh2):
                continue

            if hamming(h1, h2) <= threshold:
                group.append(p2)
                used.add(p2)

        if len(group) > 1:
            groups.append({
                "type": "visual",
                "paths": group,
            })
            used.add(p1)

    groups.sort(key=lambda g: len(g["paths"]), reverse=True)
    return groups


# ----------------------------
# UI
# ----------------------------
def center_on_parent(win, parent):
    win.update_idletasks()

    w = win.winfo_width()
    h = win.winfo_height()

    x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
    y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)

    win.geometry(f"{w}x{h}+{x}+{y}")

class App:

    def __init__(self, root):
        self.root = root
        self.root.title("Twins - Eigrutel Tools")
        self.root.geometry("1550x900")
        self.root.minsize(1280, 760)

        apply_style(self.root)
        apply_app_icon(self.root, "Renamer.png")
        style = ttk.Style(self.root)

        style.configure(
            "Detect.TButton",
            background="#f4b183",
            foreground="#000000"
        )

        style.map(
            "Detect.TButton",
            background=[
                ("active", "#e7a06a"),
                ("pressed", "#d99055"),
            ],
            foreground=[
                ("active", "#000000"),
                ("pressed", "#000000"),
            ]
        )

        self.conn = init_db()

        self.folder = ""
        self.dup_folder = get_dup_folder_for_source("C:\\")
        self.groups = []
        self.current_group = 0
        self.left_index = 0
        self.right_index = 1
        self.current_mode = ""
        self.visual_threshold = tk.IntVar(value=5)
        self.include_subfolders = tk.BooleanVar(value=True)
        self.summary_exact_groups = 0
        self.summary_exact_files = 0
        self.summary_visual_groups = 0
        self.summary_visual_files = 0
        self.scan_in_progress = False
        self.scan_button = None
        self.build_ui()
        self.bind_keys()
        self.refresh_summary_labels()
        self.refresh_group_list()

    # ---------------------

    def bind_keys(self):
        self.root.bind("<Left>", lambda event: self.prev_group())
        self.root.bind("<Right>", lambda event: self.next_group())
        self.root.bind("<Up>", lambda event: self.prev_right_image())
        self.root.bind("<Down>", lambda event: self.next_right_image())
        self.root.bind("<Delete>", lambda event: self.mark_right())
        self.root.bind("<Shift-Delete>", lambda event: self.mark_left())
        self.root.bind("<Return>", lambda event: self.promote_right_to_left())
        self.root.bind("1", lambda event: self.mark_left())
        self.root.bind("3", lambda event: self.mark_right())
    # ---------------------

    def build_ui(self):
        main = ttk.Frame(self.root, style="App.TFrame")
        main.pack(fill="both", expand=True)

        # ---------- TOPBAR ----------
        topbar = ttk.Frame(main, style="Topbar.TFrame")
        topbar.pack(fill="x")

        ttk.Label(topbar, text="TWINS", style="TopbarTitle.TLabel").pack(
            side="left", padx=12, pady=8
        )
        ttk.Button(
            topbar,
            text="Choisir dossier",
            command=self.choose,
            style="Accent.TButton"
        ).pack(side="left", padx=(20, 6))

        ttk.Checkbutton(
            topbar,
            text="Inclure sous-dossiers",
            variable=self.include_subfolders,
            style="Topbar.TCheckbutton"
        ).pack(side="left", padx=(0, 10))

        self.scan_button = ttk.Button(
            topbar,
            text="Scanner",
            command=self.scan,
            style="Accent.TButton"
        )
        self.scan_button.pack(side="left")

        btn_info = tk.Button(
            topbar,
            text="i",
            command=self.open_info_dialog,
            bg="#3c4F5F",
            fg="#FFFFFF",
            activebackground="#3c4F5F",
            activeforeground="#FFFFFF",
            bd=0,
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 11, "bold"),
            padx=10,
            pady=4,
        )
        btn_info.pack(side="right", padx=(0, 10), pady=8)

        self.lbl_scan = ttk.Label(
            topbar,
            text="",
            style="Topbar.TLabel"
        )
        self.lbl_scan.pack(side="left", padx=6)

        self.lbl_compare_status = ttk.Label(topbar, text="Comparaison : -", style="Topbar.TLabel")
        self.lbl_compare_status.pack(side="right", padx=12)

        self.lbl_group_status = ttk.Label(topbar, text="Groupe", style="Topbar.TLabel")
        self.lbl_group_status.pack(side="right", padx=12)

        self.lbl_mode = ttk.Label(topbar, text="Mode", style="Topbar.TLabel")
        self.lbl_mode.pack(side="right", padx=12)

        body = ttk.Frame(main, style="App.TFrame", padding=10)
        body.pack(fill="both", expand=True)

        # ---------- SIDEBAR ----------
        left = ttk.Frame(body, style="Side.TFrame", width=320)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        ttk.Label(left, text="Dossier", style="SideTitle.TLabel").pack(anchor="w", padx=10, pady=(8, 4))
        self.lbl_folder = ttk.Label(left, text="Aucun dossier", wraplength=290, justify="left", style="SideInfo.TLabel")
        self.lbl_folder.pack(fill="x", padx=10, pady=(0, 8))

        # ttk.Separator(left).pack(fill="x", padx=10, pady=8)
        ttk.Label(
            left,
            text="Détection",
            style="SideTitle.TLabel"
        ).pack(anchor="w", padx=10, pady=(0, 4))

       
        ttk.Button(left, text="Doublons ", command=self.exact, style="Detect.TButton").pack(fill="x", padx=10, pady=3)
        ttk.Button(left, text="Images proches", command=self.visual, style="Detect.TButton").pack(fill="x", padx=10, pady=3)

        self.lbl_left_status = ttk.Label(
            left,
            text="Mode \nGroupe ",
            justify="left",
            style="SideInfo.TLabel"
        )
        self.lbl_left_status.pack(fill="x", padx=10, pady=(8, 4))

        thresh_row = ttk.Frame(left, style="Side.TFrame")
        thresh_row.pack(fill="x", padx=10, pady=(4, 4))
        ttk.Label(thresh_row, text="Niveau de ressemblance", style="SideInfo.TLabel").pack(side="left")
        ttk.Spinbox(
            thresh_row,
            from_=0, to=20,
            textvariable=self.visual_threshold,
            width=5
        ).pack(side="right")

        # ttk.Separator(left).pack(fill="x", padx=10, pady=10)


        self.lbl_dup_title = ttk.Label(
            left,
            text="Dossier doublons",
            justify="left",
            style="SideTitle.TLabel"
        )
        self.lbl_dup_title.pack(fill="x", padx=10, pady=(0, 2))

        self.lbl_dup_path = tk.Label(
            left,
            text="",
            justify="left",
            anchor="w",
            bg=UI.SIDE if hasattr(UI, "SIDE") else "#2f3948",
            fg="#dbe7ff",
            cursor="hand2",
            font=("Segoe UI", 10, "underline"),
            wraplength=290
        )
        self.lbl_dup_path.pack(fill="x", padx=10, pady=(0, 8))
        self.lbl_dup_path.bind("<Button-1>", lambda e: self.open_duplicates_folder())

        ttk.Label(left, text="Groupes", style="SideTitle.TLabel").pack(anchor="w", padx=10, pady=(0, 4))
        self.list_groups = tk.Listbox(
            left,
            height=8,
            exportselection=False,
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            selectbackground=UI.ACCENT_10,
            selectforeground="#FFFFFF",
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI.BORDER,
            font=("Segoe UI", 10),
        )
        self.list_groups.pack(fill="x", padx=10)
        self.list_groups.bind("<<ListboxSelect>>", self.on_group_selected)

        # ttk.Separator(left).pack(fill="x", padx=10, pady=10)

        ttk.Label(left, text="Images du groupe", style="SideTitle.TLabel").pack(anchor="w", padx=10, pady=(0, 4))
        self.list_group_items = tk.Listbox(
            left,
            height=8,
            exportselection=False,
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            selectbackground=UI.ACCENT_10,
            selectforeground="#FFFFFF",
            relief="flat",
            highlightthickness=1,
            highlightbackground=UI.BORDER,
            font=("Segoe UI", 10),
        )
        self.list_group_items.pack(fill="both", expand=True, padx=10)
        self.list_group_items.bind("<<ListboxSelect>>", self.on_group_item_selected)

        nav_group = ttk.Frame(left, style="Side.TFrame")
        nav_group.pack(fill="x", padx=10, pady=(8, 0))

        ttk.Button(
            nav_group,
            text="◀ Précédent",
            command=self.prev_group,
            style="Side.TButton"
        ).pack(side="left", fill="x", expand=True, padx=(0,4))

        ttk.Button(
            nav_group,
            text="Suivant ▶",
            command=self.next_group,
            style="Side.TButton"
        ).pack(side="left", fill="x", expand=True)

        # ttk.Separator(left).pack(fill="x", padx=10, pady=10)

        
        # ---------- CENTRAL PANEL ----------
        center = ttk.Frame(body, style="Panel.TFrame")
        center.pack(side="left", fill="both", expand=True)

        nav_bar = ttk.Frame(center, style="Panel.TFrame")
        nav_bar.pack(fill="x", padx=12, pady=(12, 8))

        

        preview_wrap = ttk.Frame(center, style="Panel.TFrame")
        preview_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        left_preview = ttk.Frame(preview_wrap, style="Panel.TFrame")
        left_preview.pack(side="left", fill="both", expand=True, padx=(0, 4))

        left_top = ttk.Frame(left_preview, style="Panel.TFrame")
        left_top.pack(fill="x", pady=(0, 6))

        self.lbl_similar_count = ttk.Label(
            left_top,
            text="",
            style="Title.TLabel"
        )
        self.lbl_similar_count.pack(side="left")

        ttk.Button(
            left_top,
            text="◀ ▶",
            command=self.promote_right_to_left,
            style="Accent.TButton",
            width=5
        ).pack(side="left", padx=(10, 0))

        ttk.Button(
            left_top,
            text="garder les meilleurs",
            command=self.open_merge_dialog,
            style="Side.TButton"
        ).pack(side="left", padx=(10, 0))
        right_preview = ttk.Frame(preview_wrap, style="Panel.TFrame")
        right_preview.pack(side="left", fill="both", expand=True, padx=(6, 0))

        right_nav = ttk.Frame(right_preview, style="Panel.TFrame")
        right_nav.pack(fill="x", pady=(0, 6))

        ttk.Button(
            right_nav,
            text="▲ Similaire précédent",
            command=self.prev_right_image,
            style="Side.TButton"
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        ttk.Button(
            right_nav,
            text="▼ Similaire suivant",
            command=self.next_right_image,
            style="Side.TButton"
        ).pack(side="left", fill="x", expand=True)


        self.canvas1 = tk.Canvas(
            left_preview,
            bg="#111827",
            height=480,
            highlightthickness=1,
            highlightbackground=UI.BORDER,
            relief="flat"
        )
        self.canvas1.pack(fill="both", expand=True, pady=(0, 8))
        self.canvas1.bind("<Double-1>", lambda e: self.open_left())

        self.left_info = tk.Text(
            left_preview,
            height=4,
            wrap="word",
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            relief="solid",
            bd=1,
            highlightthickness=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 10),
        )
        self.left_info.pack(fill="x", pady=(8, 0))
        self.left_info.configure(state="disabled")

        left_actions = ttk.Frame(left_preview, style="Panel.TFrame", height=44)
        left_actions.pack(fill="x", pady=(8, 0))
        left_actions.pack_propagate(False)
        ttk.Button(left_actions, text="📁 Dossier", command=self.open_left, style="Side.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(left_actions, text="➡ DOUBLONS     ", command=self.mark_left, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.canvas2 = tk.Canvas(
            right_preview,
            bg="#111827",
            height=480,
            highlightthickness=1,
            highlightbackground=UI.BORDER,
            relief="flat"
        )
        self.canvas2.pack(fill="both", expand=True, pady=(0, 8))
        self.canvas2.bind("<Double-1>", lambda e: self.open_right())

        self.right_info = tk.Text(
            right_preview,
            height=4,
            wrap="word",
            bg=UI.PANEL,
            fg=UI.TEXT_DARK,
            relief="solid",
            bd=1,
            highlightthickness=0,
            padx=10,
            pady=8,
            font=("Segoe UI", 10),
        )
        self.right_info.pack(fill="x", pady=(8, 0))
        self.right_info.configure(state="disabled")

        right_actions = ttk.Frame(right_preview, style="Panel.TFrame", height=44)
        right_actions.pack(fill="x", pady=(8, 0))
        right_actions.pack_propagate(False)
        ttk.Button(right_actions, text="📁 Dossier", command=self.open_right, style="Side.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(right_actions, text="➡ DOUBLONS     ", command=self.mark_right, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(4, 0))

    # ---------------------

    def choose(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder = folder
            self.dup_folder = get_dup_folder_for_source(self.folder)
            self.lbl_folder.config(text=self.folder)
            self.lbl_dup_path.config(text=self.dup_folder)

    # ---------------------

    def scan(self):
        if self.scan_in_progress:
            return

        if not self.folder:
            self.lbl_scan.config(text="")
            self.root.config(cursor="")
            messagebox.showwarning("Dossier", "Choisis d'abord un dossier.")
            return

        total = count_supported_images(
            self.folder,
            ignore_names={"_Doublons", "Doublons"},
            recursive=self.include_subfolders.get()
        )

        self.scan_in_progress = True

        if self.scan_button is not None:
            self.scan_button.config(state="disabled")

        self.lbl_scan.config(text=f"Scan en cours... 0 / {total}")
        self.root.config(cursor="watch")
        self.root.update_idletasks()

        folder = self.folder
        recursive = self.include_subfolders.get()

        worker = threading.Thread(
            target=self._scan_worker,
            args=(folder, recursive, total),
            daemon=True
        )
        worker.start()

    def _scan_worker(self, folder, recursive, total):
        try:
            conn = init_db()
            clear_db(conn)

            def progress_cb(done, filename):
                self.root.after(0, self._update_scan_progress, done, total, filename)

            scan_folder(
                folder,
                conn,
                ignore_names={"_Doublons", "Doublons"},
                recursive=recursive,
                progress_cb=progress_cb
            )

            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM images")
            indexed_count = cur.fetchone()[0]

            cur.execute("""
                SELECT sha256, COUNT(*)
                FROM images
                GROUP BY sha256
                HAVING COUNT(*) > 1
            """)
            sql_groups = cur.fetchall()

            print("IMAGES INDEXÉES :", indexed_count)
            print("GROUPES EXACTS SQL :", len(sql_groups))
            print("DETAIL GROUPES EXACTS SQL :", sql_groups[:10])

            conn.close()

            self.root.after(0, self._scan_finished_success)

        except Exception as e:
            self.root.after(0, self._scan_finished_error, str(e))

    def _update_scan_progress(self, done, total, filename):
        if filename:
            self.lbl_scan.config(
                text=f"Scan en cours... {done} / {total} — {filename}"
            )
        else:
            self.lbl_scan.config(
                text=f"Scan en cours... {done} / {total}"
            )

    def exact(self):
        self.current_mode = "exact"
        self.groups = find_exact(self.conn)
        self.current_group = 0
        self.reset_view_indices()
        self.refresh_summary_labels()
        self.refresh_group_list()
        self.show_group()

    def _scan_finished_success(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass

        self.conn = init_db()

        exact = find_exact(self.conn)
        visual = find_visual(self.conn, threshold=self.visual_threshold.get())

        self.summary_exact_groups = len(exact)
        self.summary_exact_files = sum(len(g["paths"]) for g in exact)
        self.summary_visual_groups = len(visual)
        self.summary_visual_files = sum(len(g["paths"]) for g in visual)

        self.current_mode = "exact"
        self.groups = exact
        self.current_group = 0
        self.reset_view_indices()
        self.refresh_summary_labels()
        self.refresh_group_list()

        if self.groups:
            self.show_group()
            messagebox.showinfo(
                "Scan",
                "Indexation terminée.\nDes doublons exacts ont été détectés."
            )
        else:
            self.lbl_mode.config(text="Doublons")
            self.lbl_left_status.config(text="Doublons\nGroupe  0 / 0")
            self.lbl_left_status.config(text="Mode : Doublons\nGroupe : 0 / 0")
            self.lbl_compare_status.config(text="")
            self.show_canvas_message(self.canvas1, "Pas de doublon exact\ndétecté")
            self.show_canvas_message(self.canvas2, "Pas de doublon exact\ndétecté")
            self.set_info_text(self.left_info, "")
            self.set_info_text(self.right_info, "")
            messagebox.showinfo(
                "Scan",
                "Indexation terminée.\nPas de doublon exact détecté."
            )

        self._end_scan_ui()

    def _scan_finished_error(self, error_message):
        self._end_scan_ui()
        messagebox.showerror("Erreur", f"Le scan a échoué.\n\n{error_message}")

    def _end_scan_ui(self):
        self.scan_in_progress = False
        self.lbl_scan.config(text="")
        self.root.config(cursor="")

        if self.scan_button is not None:
            self.scan_button.config(state="normal")
    # ---------------------

    def visual(self):
        self.current_mode = "visual"
        self.groups = find_visual(self.conn, threshold=self.visual_threshold.get())
        self.current_group = 0
        self.reset_view_indices()
        self.refresh_summary_labels()
        self.refresh_group_list()
        self.show_group()

    # ---------------------

    def reset_view_indices(self):
        self.left_index = 0
        self.right_index = 1

    # ---------------------

    def refresh_summary_labels(self):
        self.lbl_dup_path.config(text=self.dup_folder)
    # ---------------------

    def refresh_group_list(self):
        self.list_groups.delete(0, "end")

        if not self.groups:
            self.list_groups.insert("end", "Aucun groupe")
            return

        for idx, group in enumerate(self.groups, start=1):
            kind = "EXACT" if group["type"] == "exact" else "VISUEL"
            self.list_groups.insert("end", f"{idx:03d} | {kind} | {len(group['paths'])} image(s)")

        if self.groups:
            self.list_groups.selection_clear(0, "end")
            self.list_groups.selection_set(self.current_group)
            self.list_groups.see(self.current_group)

    # ---------------------

    def refresh_group_items_list(self):
        self.list_group_items.delete(0, "end")

        group = self.get_current_group()
        if not group:
            return

        for idx, path in enumerate(group["paths"]):
            info = get_image_info(self.conn, path)
            name = os.path.basename(path)
            size_txt = format_size(info["size"]) if info else "?"
            dims = f"{info['width']}x{info['height']}" if info else "?"
            side = ""
            if idx == self.left_index:
                side = " [G]"
            elif idx == self.right_index:
                side = " [D]"
            self.list_group_items.insert(
                "end",
                f"{idx+1}. {name} — {size_txt} — {dims}{side}"
            )

    # ---------------------

    def get_current_group(self):
        if not self.groups:
            return None
        if not (0 <= self.current_group < len(self.groups)):
            return None
        return self.groups[self.current_group]

    # ---------------------

    def get_left_path(self):
        group = self.get_current_group()
        if not group:
            return None
        if not (0 <= self.left_index < len(group["paths"])):
            return None
        return group["paths"][self.left_index]

    # ---------------------

    def get_right_path(self):
        group = self.get_current_group()
        if not group:
            return None
        if not (0 <= self.right_index < len(group["paths"])):
            return None
        return group["paths"][self.right_index]

    # ---------------------

    def ensure_valid_indices(self):
        group = self.get_current_group()
        if not group:
            self.left_index = 0
            self.right_index = 1
            return

        paths = group["paths"]
        if len(paths) < 2:
            self.left_index = 0
            self.right_index = 0
            return

        if self.left_index >= len(paths):
            self.left_index = 0

        if self.right_index >= len(paths) or self.right_index == self.left_index:
            self.right_index = self.find_next_index(self.left_index, forward=True)

    # ---------------------

    def find_next_index(self, start_idx, forward=True):
        group = self.get_current_group()
        if not group or len(group["paths"]) < 2:
            return 0

        n = len(group["paths"])
        if n == 2:
            return 1 - start_idx

        idx = start_idx
        for _ in range(n):
            idx = (idx + 1) % n if forward else (idx - 1) % n
            if idx != self.left_index:
                return idx
        return start_idx

    # ---------------------

    def show_group(self):
        if not self.groups:
            self.lbl_mode.config(text="-")
            self.lbl_group_status.config(text="Groupe ")
            self.lbl_left_status.config(text="-\nGroupe ")
            self.lbl_compare_status.config(text="Comparaison : -")
            self.lbl_similar_count.config(text="")
            self.show_canvas_message(self.canvas1, "Aucun doublon")
            self.show_canvas_message(self.canvas2, "Aucun doublon")
            self.set_info_text(self.left_info, "")
            self.set_info_text(self.right_info, "")
            self.refresh_group_list()
            self.refresh_group_items_list()
            self.refresh_summary_labels()
            return

        self.ensure_valid_indices()

        group = self.get_current_group()
        if not group:
            return

        left_path = self.get_left_path()
        right_path = self.get_right_path()
        count = len(group["paths"])
        if count > 1:
            self.lbl_similar_count.config(text=f"{count} images similaires")
        else:
            self.lbl_similar_count.config(text="1 image")

        kind = "Doublons" if group["type"] == "exact" else "Images proches"
        group_text = f"Groupe  {self.current_group + 1} / {len(self.groups)} — {len(group['paths'])} image(s)"

        self.lbl_mode.config(text=kind)
        self.lbl_group_status.config(text=group_text)
        self.lbl_left_status.config(text=f"{kind}\n{group_text}")
        self.lbl_compare_status.config(text="")

        if left_path and os.path.exists(left_path):
            self.display(self.canvas1, left_path)
            self.set_info_text(self.left_info, self.build_info_text(left_path))
        else:
            self.show_canvas_message(self.canvas1, "Image gauche indisponible")
            self.set_info_text(self.left_info, "")

        if right_path and os.path.exists(right_path):
            self.display(self.canvas2, right_path)
            self.set_info_text(self.right_info, self.build_info_text(right_path))
        else:
            self.show_canvas_message(self.canvas2, "Image droite indisponible")
            self.set_info_text(self.right_info, "")

        self.refresh_group_list()
        self.refresh_group_items_list()

    # ---------------------

    def display(self, canvas, path):
        canvas.delete("all")
        canvas.update_idletasks()

        try:
            with Image.open(path) as img:
                img = img.copy()
        except Exception:
            self.show_canvas_message(canvas, "Impossible d'ouvrir l'image")
            return

        w = max(canvas.winfo_width(), 300)
        h = max(canvas.winfo_height(), 300)

        margin = 20
        img.thumbnail((w - margin, h - margin), Image.LANCZOS)

        tkimg = ImageTk.PhotoImage(img)
        canvas.image = tkimg

        canvas.create_image(
            w // 2,
            h // 2,
            image=tkimg
        )

    # ---------------------

    def show_canvas_message(self, canvas, text):
        canvas.delete("all")
        canvas.update_idletasks()

        w = max(canvas.winfo_width(), 300)
        h = max(canvas.winfo_height(), 300)

        canvas.create_text(
            w // 2,
            h // 2,
            text=text,
            fill="#FFFFFF",
            font=("Segoe UI", 14, "bold"),
            justify="center"
        )

    # ---------------------

    def set_info_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ---------------------

    def build_info_text(self, path):
        info = get_image_info(self.conn, path)
        if not info:
            return path

        return (
            f"Nom : {info['name']}\n"
            f"Chemin : {info['path']}\n"
            f"Poids : {format_size(info['size'])}\n"
            f"Dimensions : {info['width']} x {info['height']}"
        )

    # ---------------------

    def prev_group(self):
        if not self.groups:
            return
        if self.current_group > 0:
            self.current_group -= 1
            self.reset_view_indices()
            self.show_group()

    # ---------------------

    def next_group(self):
        if not self.groups:
            return
        if self.current_group < len(self.groups) - 1:
            self.current_group += 1
            self.reset_view_indices()
            self.show_group()

    # ---------------------

    def prev_right_image(self):
        group = self.get_current_group()
        if not group or len(group["paths"]) < 2:
            return

        if self.right_index == self.left_index:
            self.right_index = self.find_next_index(self.left_index, forward=False)
        else:
            idx = self.right_index
            n = len(group["paths"])
            for _ in range(n):
                idx = (idx - 1) % n
                if idx != self.left_index:
                    self.right_index = idx
                    break

        self.show_group()

    # ---------------------

    def next_right_image(self):
        group = self.get_current_group()
        if not group or len(group["paths"]) < 2:
            return

        if self.right_index == self.left_index:
            self.right_index = self.find_next_index(self.left_index, forward=True)
        else:
            idx = self.right_index
            n = len(group["paths"])
            for _ in range(n):
                idx = (idx + 1) % n
                if idx != self.left_index:
                    self.right_index = idx
                    break

        self.show_group()

    # ---------------------

    def promote_right_to_left(self):
        group = self.get_current_group()
        if not group or len(group["paths"]) < 2:
            return

        if self.right_index == self.left_index:
            return

        old_left = self.left_index
        self.left_index = self.right_index

        if old_left != self.left_index:
            self.right_index = old_left
        else:
            self.right_index = self.find_next_index(self.left_index, forward=True)

        self.show_group()

    def open_merge_dialog(self):
        exact_groups = find_exact(self.conn)

        if not exact_groups:
            messagebox.showinfo(
                "Garder les meilleurs",
                "Aucun doublon exact à fusionner."
            )
            return

        total_groups = len(exact_groups)
        total_files = sum(len(g["paths"]) for g in exact_groups)

        dlg = tk.Toplevel(self.root)
        dlg.title("Fusion doublons exacts")
        apply_app_icon(dlg, "Renamer.png")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.configure(bg=UI.STRUCT_30 if hasattr(UI, "STRUCT_30") else "#1f2430")

        choice = tk.StringVar(value="recent")

        outer = tk.Frame(
            dlg,
            bg=UI.STRUCT_30 if hasattr(UI, "STRUCT_30") else "#1f2430",
            padx=16,
            pady=16
        )
        outer.pack(fill="both", expand=True)

        title_lbl = tk.Label(
            outer,
            text="Fusionner les doublons exacts",
            bg=outer.cget("bg"),
            fg="#FFFFFF",
            font=("Segoe UI", 12, "bold"),
            anchor="w"
        )
        title_lbl.pack(fill="x", pady=(0, 12))

        rule_box = tk.Frame(
            outer,
            bg=UI.STRUCT_20 if hasattr(UI, "STRUCT_20") else "#2a3140",
            bd=1,
            relief="solid"
        )
        rule_box.pack(fill="x", pady=(0, 12))

        rule_title = tk.Label(
            rule_box,
            text="Choisir la règle pour conserver le bon fichier",
            bg=rule_box.cget("bg"),
            fg="#FFFFFF",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=12,
            pady=10
        )
        rule_title.pack(fill="x")

        radio_wrap = tk.Frame(
            rule_box,
            bg=rule_box.cget("bg"),
            padx=12,
            pady=4
        )
        radio_wrap.pack(fill="x")

        rb_style = dict(
            bg=rule_box.cget("bg"),
            fg="#FFFFFF",
            activebackground=rule_box.cget("bg"),
            activeforeground="#FFFFFF",
            selectcolor=rule_box.cget("bg"),
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            highlightthickness=0,
            bd=0
        )

        tk.Radiobutton(
            radio_wrap,
            text="Garder le plus récent",
            variable=choice,
            value="recent",
            **rb_style
        ).pack(anchor="w", pady=2)

        tk.Radiobutton(
            radio_wrap,
            text="Garder le nom le plus court",
            variable=choice,
            value="shortest",
            **rb_style
        ).pack(anchor="w", pady=2)

        tk.Radiobutton(
            radio_wrap,
            text="Garder le nom le plus long",
            variable=choice,
            value="longest",
            **rb_style
        ).pack(anchor="w", pady=2)

        info_box = tk.Frame(
            outer,
            bg=UI.STRUCT_20 if hasattr(UI, "STRUCT_20") else "#2a3140",
            bd=1,
            relief="solid",
            padx=12,
            pady=10
        )
        info_box.pack(fill="x", pady=(0, 14))

        info_txt = (
            "Cette action traitera tous les doublons exacts d'un coup :\n"
            f"- {total_groups} groupe(s)\n"
            f"- {total_files} fichier(s) concernés\n\n"
            "Dans chaque groupe, un seul fichier sera conservé.\n"
            "Les autres seront déplacés dans le dossier Doublons."
        )

        tk.Label(
            info_box,
            text=info_txt,
            bg=info_box.cget("bg"),
            fg="#FFFFFF",
            font=("Segoe UI", 10),
            justify="left",
            anchor="w"
        ).pack(fill="x")

        actions = tk.Frame(
            outer,
            bg=outer.cget("bg")
        )
        actions.pack(fill="x")

        def do_merge():
            rule = choice.get()
            dlg.destroy()
            self.merge_all_exact_groups(rule)

        btn_cancel = tk.Button(
            actions,
            text="Annuler",
            command=dlg.destroy,
            bg=UI.STRUCT_20 if hasattr(UI, "STRUCT_20") else "#2a3140",
            fg="#FFFFFF",
            activebackground=UI.STRUCT_40 if hasattr(UI, "STRUCT_40") else "#394257",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10),
            padx=18,
            pady=10,
            cursor="hand2"
        )
        btn_cancel.pack(side="right")

        btn_merge = tk.Button(
            actions,
            text="Garder les meilleurs",
            command=do_merge,
            bg=UI.ACCENT_10 if hasattr(UI, "ACCENT_10") else "#2BA3B8",
            fg="#FFFFFF",
            activebackground=UI.ACCENT_20 if hasattr(UI, "ACCENT_20") else "#22879a",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            padx=18,
            pady=10,
            cursor="hand2"
        )
        btn_merge.pack(side="right", padx=(0, 8))

        center_on_parent(dlg, self.root)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        
    def choose_keep_path(self, paths, rule):
        existing = [p for p in paths if os.path.exists(p)]
        if not existing:
            return None

        if rule == "recent":
            return max(existing, key=lambda p: os.path.getmtime(p))

        if rule == "shortest":
            return min(existing, key=lambda p: (len(os.path.basename(p)), os.path.basename(p).lower()))

        if rule == "longest":
            return max(existing, key=lambda p: (len(os.path.basename(p)), os.path.basename(p).lower()))

        return existing[0]
        
    def merge_all_exact_groups(self, rule):
        exact_groups = find_exact(self.conn)

        if not exact_groups:
            messagebox.showinfo("Fusionner", "Aucun doublon exact à fusionner.")
            return

        kept_count = 0
        moved_count = 0
        group_count = 0
        errors = []

        for group in exact_groups:
            paths = list(group["paths"])
            if len(paths) < 2:
                continue

            keep_path = self.choose_keep_path(paths, rule)
            if not keep_path:
                errors.append("Impossible de déterminer le fichier à conserver pour un groupe.")
                continue

            group_count += 1
            kept_count += 1

            for path in paths:
                if path == keep_path:
                    continue
                if not os.path.exists(path):
                    continue
                try:
                    self.move_path_to_duplicates(path)
                    moved_count += 1
                except Exception as e:
                    errors.append(f"{os.path.basename(path)} : {e}")
        self.purge_missing_files_from_db()
        # recharge l'affichage après traitement
        if self.current_mode == "exact":
            self.groups = find_exact(self.conn)
        elif self.current_mode == "visual":
            self.groups = find_visual(self.conn, threshold=self.visual_threshold.get())
        else:
            self.groups = []

        self.current_group = 0
        self.reset_view_indices()
        self.refresh_summary_labels()
        self.refresh_group_list()
        self.show_group()

        msg = (
            f"Fusion terminée.\n\n"
            f"Groupes traités : {group_count}\n"
            f"Fichiers conservés : {kept_count}\n"
            f"Fichiers déplacés : {moved_count}"
        )

        if errors:
            msg += "\n\nCertaines images n'ont pas pu être déplacées :\n- " + "\n- ".join(errors[:10])

        messagebox.showinfo("garder les meilleurs", msg)
    # ---------------------
    def open_duplicates_folder(self):
        path = self.dup_folder
        if os.path.exists(path):
            subprocess.Popen(["explorer", os.path.normpath(path)])

    def open_left(self):
        path = self.get_left_path()
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    # ---------------------


    def open_right(self):
        path = self.get_right_path()
        if path and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    # ---------------------

    def move_path_to_duplicates(self, path):
        dst = self.dup_folder
        name = os.path.basename(path)
        target = os.path.join(dst, name)

        base, ext = os.path.splitext(name)
        n = 1
        while os.path.exists(target):
            target = os.path.join(dst, f"{base}_{n}{ext}")
            n += 1

        os.rename(path, target)
        return target
    
    def delete_path_from_db(self, path):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM images WHERE path=?", (normpath_abs(path),))
        self.conn.commit()

    def purge_missing_files_from_db(self):
        cur = self.conn.cursor()
        cur.execute("SELECT path FROM images")
        rows = cur.fetchall()

        missing = [row[0] for row in rows if not os.path.exists(row[0])]
        if missing:
            cur.executemany("DELETE FROM images WHERE path=?", [(p,) for p in missing])
            self.conn.commit()
    # ---------------------

    def remove_path_from_current_group(self, remove_index):
        group = self.get_current_group()
        if not group:
            return

        if not (0 <= remove_index < len(group["paths"])):
            return

        del group["paths"][remove_index]

        if len(group["paths"]) < 2:
            del self.groups[self.current_group]
            if self.current_group >= len(self.groups):
                self.current_group = max(0, len(self.groups) - 1)
            self.reset_view_indices()
            
            self.refresh_group_list()
            self.show_group()
            return

        if remove_index == self.left_index:
            self.left_index = 0
            self.right_index = self.find_next_index(self.left_index, forward=True)
        else:
            if remove_index < self.left_index:
                self.left_index -= 1

            if remove_index < self.right_index:
                self.right_index -= 1

            if self.right_index == self.left_index or self.right_index >= len(group["paths"]):
                self.right_index = self.find_next_index(self.left_index, forward=True)

        
        self.refresh_group_list()
        self.show_group()

    # ---------------------

    def mark_left(self):
        group = self.get_current_group()
        if not group:
            return

        path = self.get_left_path()
        if not path or not os.path.exists(path):
            return

        try:
            self.move_path_to_duplicates(path)
            self.delete_path_from_db(path)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de déplacer le fichier.\n\n{e}")
            return

        self.remove_path_from_current_group(self.left_index)

    # ---------------------

    def mark_right(self):
        group = self.get_current_group()
        if not group:
            return

        path = self.get_right_path()
        if not path or not os.path.exists(path):
            return

        try:
            self.move_path_to_duplicates(path)
            self.delete_path_from_db(path)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de déplacer le fichier.\n\n{e}")
            return

        self.remove_path_from_current_group(self.right_index)
    # ---------------------

    def on_group_selected(self, _event=None):
        if not self.groups:
            return
        sel = self.list_groups.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.groups):
            self.current_group = idx
            self.reset_view_indices()
            self.show_group()

    # ---------------------

    def on_group_item_selected(self, _event=None):
        group = self.get_current_group()
        if not group:
            return

        sel = self.list_group_items.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx == self.left_index:
            return
        if 0 <= idx < len(group["paths"]):
            self.right_index = idx
            self.show_group()

    # ---------------------

    def selected_to_left(self):
        group = self.get_current_group()
        if not group:
            return

        sel = self.list_group_items.curselection()
        if not sel:
            return
        idx = sel[0]
        if not (0 <= idx < len(group["paths"])):
            return
        if idx == self.left_index:
            return

        old_left = self.left_index
        self.left_index = idx
        if old_left != self.left_index:
            self.right_index = old_left
        else:
            self.right_index = self.find_next_index(self.left_index, forward=True)

        self.show_group()

    # ---------------------

    def selected_to_right(self):
        group = self.get_current_group()
        if not group:
            return

        sel = self.list_group_items.curselection()
        if not sel:
            return
        idx = sel[0]
        if not (0 <= idx < len(group["paths"])):
            return
        if idx == self.left_index:
            return

        self.right_index = idx
        self.show_group()

    def open_info_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Infos")
        apply_app_icon(dlg, "Renamer.png")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.minsize(560, 560)

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="TWINS - Manuel").pack(anchor="w")

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
        txt.tag_configure("title", font=("Segoe UI", 14, "bold"))
        txt.tag_configure("section", font=("Segoe UI", 11, "bold"))
        txt.tag_configure("bold", font=("Segoe UI", 10, "bold"))

        sb = ttk.Scrollbar(mid, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)

        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        txt.insert("end", "TWINS — Détection de doublons d'images\n", "title")
        txt.insert("end", "\n")

        txt.insert("end", "Principe général\n", "section")
        txt.insert("end", "TWINS sert à repérer des images en double ou très proches dans un dossier. ")
        txt.insert("end", "L'outil compare les fichiers puis affiche les résultats par groupes pour permettre une vérification visuelle rapide.\n\n")

        txt.insert("end", "Deux modes de détection\n", "section")
        txt.insert("end", "Doublons\n", "bold")
        txt.insert("end", " : fichiers strictement identiques.\n")
        txt.insert("end", "Images proches\n", "bold")
        txt.insert("end", " : images visuellement ressemblantes, même si elles ne sont pas exactement le même fichier.\n\n")

        txt.insert("end", "Tolérance\n", "section")
        txt.insert("end", "Le niveau de ressemblance règle la souplesse de la détection visuelle.\n")
        txt.insert("end", "- valeur basse : détection prudente, moins de faux positifs\n")
        txt.insert("end", "- valeur haute : détection plus large, mais plus risquée\n\n")

        txt.insert("end", "Lecture de l'interface\n", "section")
        txt.insert("end", "- Colonne gauche : dossier, type de détection, groupes trouvés, images du groupe.\n")
        txt.insert("end", "- Centre : image de référence à gauche, image comparée à droite.\n")
        txt.insert("end", "- Sous chaque image : informations du fichier et actions.\n\n")

        txt.insert("end", "Navigation dans un groupe\n", "section")
        txt.insert("end", "- L'image de gauche sert de référence.\n")
        txt.insert("end", "- L'image de droite est l'image actuellement comparée.\n")
        txt.insert("end", "- ")
        txt.insert("end", "Similaire précédent", "bold")
        txt.insert("end", " et ")
        txt.insert("end", "Similaire suivant", "bold")
        txt.insert("end", " permettent de faire défiler les autres images du groupe.\n")
        txt.insert("end", "- Le bouton ")
        txt.insert("end", "◀ ▶", "bold")
        txt.insert("end", " inverse la référence et l'image comparée.\n\n")

        txt.insert("end", "Boutons principaux\n", "section")
        txt.insert("end", "- ")
        txt.insert("end", "Choisir dossier", "bold")
        txt.insert("end", " : sélectionne le dossier à analyser.\n")
        txt.insert("end", "- ")
        txt.insert("end", "Inclure sous-dossiers", "bold")
        txt.insert("end", " : étend le scan à toute l'arborescence.\n")
        txt.insert("end", "- ")
        txt.insert("end", "Scanner", "bold")
        txt.insert("end", " : indexe les images puis affiche automatiquement les doublons exacts s'il y en a.\n")
        txt.insert("end", "- ")
        txt.insert("end", "📁 Dossier", "bold")
        txt.insert("end", " : ouvre l'emplacement du fichier.\n")
        txt.insert("end", "- ")
        txt.insert("end", "➜ DOUBLONS", "bold")
        txt.insert("end", " : déplace l'image dans le dossier Documents/Doublons.\n\n")

        txt.insert("end", "Dossier Doublons\n", "section")
        txt.insert("end", "Les fichiers écartés sont déplacés dans :\n")
        txt.insert("end", "Sur C: : Documents\\Doublons\n", "bold")
        txt.insert("end", "Sur un autre disque : racine_du_disque\\Doublons\n\n", "bold")

        txt.insert("end", "Raccourcis clavier\n", "section")
        txt.insert("end", "- Flèche gauche / droite : groupe précédent / suivant\n")
        txt.insert("end", "- Flèche haut / bas : image similaire précédente / suivante\n")
        txt.insert("end", "- Suppr : envoyer l'image de droite dans Doublons\n")
        txt.insert("end", "- Maj + Suppr : envoyer l'image de gauche dans Doublons\n")
        txt.insert("end", "- Entrée : basculer droite ↔ gauche\n")
        txt.insert("end", "\n")
        txt.insert("end", "—\n", "section")


        txt.insert(
            "end",
            "Programme conçu, réalisé et offert par Simon Léturgie.\n",
        )
    
        txt.insert(
            "end",
            "Eigrutel BD Academy - 2026\n"
        )

        txt.insert(
            "end",
            "Site : stripmee.com\n",
            "link"
        )
        def open_site(event):
            import webbrowser
            webbrowser.open("https://www.stripmee.com")

        txt.tag_bind("link", "<Button-1>", open_site)

        txt.tag_configure("link", foreground="#2BA3B8", underline=True)


        txt.configure(state="disabled")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))

        ttk.Button(actions, text="Fermer", style="Side.TButton", command=dlg.destroy).pack(side="right")

        center_on_parent(dlg, self.root)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
# ----------------------------
# MAIN
# ----------------------------

if __name__ == "__main__":
    root = tk.Tk()

    # plein écran maximisé Windows
    root.state("zoomed")

    app = App(root)

    root.mainloop()
