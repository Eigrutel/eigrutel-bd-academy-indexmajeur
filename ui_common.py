# -*- coding: utf-8 -*-
"""ui_common.py

Socle UI commun (Tkinter/ttk) basé sur le design de texte.py.
- Palette 60-30-10
- Styles ttk
- Tooltip simple
- Helpers (sanitize, open default app, persistance JSON)

Conçu pour être importé par texte/pdf/photo/audio/video.
"""

from __future__ import annotations

import json
import datetime
import random
import string
import os
import re
import subprocess
import sys
import unicodedata
import tkinter as tk
from tkinter import ttk

# =========================
# UI / Styles
# =========================
class UI:
    BG_60 = "#F4F5F7"
    PANEL = "#FFFFFF"
    STRUCT_30 = "#2E3440"
    STRUCT_30_2 = "#4C566A"
    TEXT_DARK = "#1F232B"
    TEXT_MUTED = "#5A6676"
    ACCENT_10 = "#1F9BA6"
    ACCENT_HOVER = "#2DB6C3"
    BORDER = "#D7DCE3"

def apply_style(root: tk.Tk) -> ttk.Style:
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=UI.BG_60)

    style.configure("App.TFrame", background=UI.BG_60)
    style.configure("Panel.TFrame", background=UI.PANEL)

    style.configure("Topbar.TFrame", background=UI.STRUCT_30)
    style.configure("Topbar.TLabel", background=UI.STRUCT_30, foreground="#ECEFF4", font=("Segoe UI", 10))
    style.configure("TopbarTitle.TLabel", background=UI.STRUCT_30, foreground="#ECEFF4",
                    font=("Segoe UI", 11, "bold"))

    style.configure("Topbar.TCheckbutton", background=UI.STRUCT_30, foreground="#ECEFF4", font=("Segoe UI", 9))
    style.map("Topbar.TCheckbutton", background=[("active", UI.STRUCT_30)])

    style.configure("Title.TLabel", background=UI.PANEL, foreground=UI.TEXT_DARK, font=("Segoe UI", 11, "bold"))
    style.configure("Muted.TLabel", background=UI.PANEL, foreground=UI.TEXT_MUTED, font=("Segoe UI", 9))

    style.configure("SideTitle.TLabel", background=UI.STRUCT_30, foreground="#ECEFF4", font=("Segoe UI", 10, "bold"))
    style.configure("Side.TFrame", background=UI.STRUCT_30)
    style.configure("SideInfo.TLabel", background=UI.STRUCT_30, foreground="#D8DEE9", font=("Segoe UI", 9))
    style.configure("SideSmall.TLabel", background=UI.STRUCT_30, foreground="#AEB8C5", font=("Segoe UI", 9))

    style.configure("TButton", font=("Segoe UI", 10), padding=8)

    style.configure("Accent.TButton",
                    background=UI.ACCENT_10,
                    foreground="#FFFFFF",
                    font=("Segoe UI", 10, "bold"),
                    padding=10,
                    borderwidth=0,
                    focusthickness=0)
    style.map("Accent.TButton", background=[("active", UI.ACCENT_HOVER), ("pressed", UI.ACCENT_HOVER)])

    style.configure("Side.TButton",
                    background=UI.STRUCT_30,
                    foreground="#ECEFF4",
                    padding=9,
                    borderwidth=0)
    style.map("Side.TButton", background=[("active", UI.STRUCT_30_2), ("pressed", UI.STRUCT_30_2)])

    style.configure("Tag.TCheckbutton",
                    background=UI.PANEL,
                    foreground=UI.TEXT_DARK,
                    font=("Segoe UI", 10),
                    padding=6)
    style.map("Tag.TCheckbutton", background=[("active", "#EEF1F5")])

    style.configure("Small.TLabel", background=UI.PANEL, foreground=UI.TEXT_MUTED, font=("Segoe UI", 9))

    return style


def apply_app_icon(root: tk.Tk, icon_name: str = "Renamer.png"):
    """
    Applique l'icône de l'application à la fenêtre Tk.
    """
    try:
        icon_path = os.path.join(app_dir(), icon_name)
        if os.path.exists(icon_path):
            icon = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, icon)
            root._app_icon = icon  # évite le garbage collection
    except Exception:
        pass
def digits_only_validator(new_value: str) -> bool:
    """
    Autorise uniquement une chaîne vide ou des chiffres.
    Compatible validatecommand Tkinter.
    """
    return new_value == "" or new_value.isdigit()


def bind_digits_only(entry: ttk.Entry, root: tk.Misc) -> None:
    """
    Applique une validation 'chiffres uniquement' à un Entry ttk.
    """
    vcmd = (root.register(digits_only_validator), "%P")
    entry.configure(validate="key", validatecommand=vcmd)


def set_default_counter(entry: ttk.Entry, value: str = "1") -> None:
    """
    Initialise un champ compteur avec une valeur par défaut
    seulement s'il est vide.
    """
    if not entry.get().strip():
        entry.delete(0, "end")
        entry.insert(0, value)

# =========================
# Tooltip
# =========================
class HoverTooltip:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.tip = None

    def bind(self, widget: tk.Widget, text_func):
        widget.bind("<Enter>", lambda e: self._show(widget, text_func()))
        widget.bind("<Leave>", lambda e: self._hide())

    def _show(self, widget: tk.Widget, text: str):
        self._hide()
        if not text:
            return
        try:
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 8
        except Exception:
            x, y = 50, 50
        self.tip = tk.Toplevel(self.root)
        self.tip.overrideredirect(True)
        self.tip.configure(bg="#111827")
        lbl = tk.Label(self.tip, text=text, bg="#111827", fg="#F9FAFB",
                       font=("Segoe UI", 9), justify="left", padx=8, pady=6)
        lbl.pack()
        self.tip.geometry(f"+{x}+{y}")

    def _hide(self):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


# =========================
# Helpers
# =========================
def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return default


def save_json(path: str, data) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def sanitize_token(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = strip_accents(s)
    s = s.replace(" ", "_")
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    s = re.sub(r"[\t\r\n]+", "_", s)
    s = re.sub(r"[^\w\-\.]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def open_with_default_app(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def format_pos(idx: int, total: int) -> str:
    """Formate un indicateur de position '(2/34)'.

    - idx: index 0-based (comme self.idx)
    - total: len(self.files)
    """
    try:
        total_i = int(total)
        idx_i = int(idx)
    except Exception:
        return "(0/0)"
    if total_i <= 0:
        return "(0/0)"
    return f"({idx_i + 1}/{total_i})"
def format_counter(value: int | str, pad: int = 3) -> str:
    """
    Formate un compteur en suffixe standard (_001)
    """
    try:
        n = int(str(value).strip())
    except Exception:
        n = 1
    return str(max(0, n)).zfill(pad)
def next_free_counter_in_dir(dir_path: str, base_stem: str, ext: str, width: int = 3) -> int:
    """
    Cherche le prochain compteur libre pour des fichiers du type:
    {base_stem}_{NNN}{ext}
    dans le dossier dir_path uniquement.

    - base_stem : nom SANS compteur (ex: "AUDIO_Podcast_Titre")
    - ext : extension avec point (ex: ".mp3")
    - width : largeur du padding (3 -> 001)

    Retourne un entier (ex: 1, 2, 15...)
    """
    try:
        names = os.listdir(dir_path)
    except Exception:
        return 1

    ext = (ext or "").lower()
    base = (base_stem or "").strip()
    if not base:
        return 1

    # pattern: base_001.ext
    # on accepte underscore multiples dans base
    # on ne matche que si c'est exactement base + "_" + chiffres + ext
    nums = set()
    prefix = base + "_"
    for fn in names:
        try:
            if not fn.lower().endswith(ext):
                continue
            if not fn.startswith(prefix):
                continue
            core = fn[len(prefix):]
            core_no_ext = core[: -len(ext)] if ext else core
            if not core_no_ext.isdigit():
                continue
            nums.add(int(core_no_ext))
        except Exception:
            continue

    n = 1
    while n in nums:
        n += 1
    return n


# =========================
# LOGS (mensuels) + UNDO
# =========================

def _now_iso() -> str:
    # ISO 8601 local time with offset if possible (fallback naive)
    try:
        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception:
        return datetime.datetime.now().isoformat(timespec="seconds")


def new_session_id(prefix: str = "") -> str:
    """Session id stable pendant la session. À créer une fois au lancement d'un outil."""
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rand = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"{prefix}{ts}-{rand}" if prefix else f"{ts}-{rand}"


def logs_dir(base_dir: str | None = None) -> str:
    root = base_dir or app_dir()
    p = os.path.join(root, "logs")
    os.makedirs(p, exist_ok=True)
    return p


def monthly_log_path(dt: datetime.datetime | None = None, base_dir: str | None = None) -> str:
    d = dt or datetime.datetime.now()
    ym = d.strftime("%Y-%m")
    return os.path.join(logs_dir(base_dir=base_dir), f"rename_log_{ym}.jsonl")


def append_log_line(obj: dict, base_dir: str | None = None) -> None:
    """Écrit une ligne JSON dans le log mensuel courant (JSONL)."""
    path = monthly_log_path(base_dir=base_dir)
    line = json.dumps(obj, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_rename(
    *,
    tool: str,
    session_id: str,
    folder: str,
    old_path: str,
    new_path: str,
    old_name: str,
    new_name: str,
    status: str = "ok",
    error: str | None = None,
    user_target_mode: str | None = None,
    conflict_resolution: str | None = None,
    base_dir: str | None = None,
) -> dict:
    obj = {
        "ts": _now_iso(),
        "session_id": session_id,
        "tool": tool,
        "folder": folder,
        "old_path": old_path,
        "new_path": new_path,
        "old_name": old_name,
        "new_name": new_name,
        "status": status,
    }
    if error:
        obj["error"] = error
    if user_target_mode:
        obj["user_target_mode"] = user_target_mode
    if conflict_resolution:
        obj["conflict_resolution"] = conflict_resolution

    append_log_line(obj, base_dir=base_dir)
    return obj


def log_undo(
    *,
    session_id: str,
    undo_of_ts: str,
    old_path: str,
    new_path: str,
    base_dir: str | None = None,
) -> dict:
    """Log d'une action d'annulation (undo)."""
    obj = {
        "ts": _now_iso(),
        "session_id": session_id,
        "tool": "undo",
        "undo_of_ts": undo_of_ts,
        "old_path": old_path,
        "new_path": new_path,
        "old_name": os.path.basename(old_path),
        "new_name": os.path.basename(new_path),
        "status": "ok",
    }
    append_log_line(obj, base_dir=base_dir)
    return obj


def _iter_month_files_backwards(max_months: int = 24, base_dir: str | None = None) -> list[str]:
    """Retourne une liste de fichiers de logs (mois courant vers le passé)."""
    files = []
    d = datetime.datetime.now().replace(day=15)  # safe mid-month
    for _ in range(max_months):
        p = monthly_log_path(dt=d, base_dir=base_dir)
        if os.path.exists(p):
            files.append(p)
        # recule d'un mois
        year = d.year
        month = d.month - 1
        if month == 0:
            month = 12
            year -= 1
        d = d.replace(year=year, month=month)
    return files


def _read_jsonl_reversed(path: str, max_lines: int | None = None) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if max_lines:
            lines = lines[-max_lines:]
        out = []
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


def find_last_undoable_action(
    *,
    max_scan_lines: int = 5000,
    max_months: int = 24,
    base_dir: str | None = None,
) -> dict | None:
    """
    Retourne la dernière action 'ok' non annulée.
    On considère qu'une action est annulée si un log 'undo' existe avec undo_of_ts == action.ts
    """
    undone = set()
    for lf in _iter_month_files_backwards(max_months=max_months, base_dir=base_dir):
        entries = _read_jsonl_reversed(lf, max_lines=max_scan_lines)
        for e in entries:
            if e.get("tool") == "undo" and e.get("status") == "ok":
                uts = e.get("undo_of_ts")
                if uts:
                    undone.add(uts)
        for e in entries:
            if e.get("status") != "ok":
                continue
            if e.get("tool") == "undo":
                continue
            ts = e.get("ts")
            if ts and ts in undone:
                continue
            # action candidate
            if e.get("old_path") and e.get("new_path"):
                return e
    return None


def _make_undo_suffix_path(target_path: str, prefix: str = "_UNDO") -> str:
    folder = os.path.dirname(target_path)
    name = os.path.basename(target_path)
    stem, ext = os.path.splitext(name)
    # find next free
    n = 1
    while True:
        cand = os.path.join(folder, f"{stem}{prefix}{n:03d}{ext}")
        if not os.path.exists(cand):
            return cand
        n += 1


def perform_undo(
    *,
    action: dict,
    session_id: str,
    suffix_prefix: str = "_UNDO",
    base_dir: str | None = None,
) -> tuple[bool, str]:
    """
    Tente d'annuler une action de renommage.
    Retourne (ok, message).
    """
    old_path = action.get("old_path", "")
    new_path = action.get("new_path", "")
    if not old_path or not new_path:
        return False, "Action invalide (chemins manquants)."

    if not os.path.exists(new_path):
        return False, "Impossible d’annuler : le fichier à restaurer est introuvable."

    restore_path = old_path
    if os.path.exists(restore_path):
        restore_path = _make_undo_suffix_path(old_path, prefix=suffix_prefix)

    try:
        os.rename(new_path, restore_path)
    except Exception as e:
        return False, f"Impossible d’annuler : {e}"

    try:
        log_undo(
            session_id=session_id,
            undo_of_ts=action.get("ts", ""),
            old_path=new_path,
            new_path=restore_path,
            base_dir=base_dir,
        )
    except Exception:
        # Undo effectué, même si log échoue
        pass

    if restore_path != old_path:
        return True, f"Restauré avec suffixe : {os.path.basename(restore_path)}"
    return True, "Renommage annulé."



# =========================
# ScrollableFrame (utile pour Tags)
# =========================

class ScrollableFrame(ttk.Frame):
    """
    Frame scrollable verticalement (Canvas + scrollbar).
    Usage:
        sf = ScrollableFrame(parent)
        container = sf.inner  # mettre widgets dedans
    """
    def __init__(self, master, *args, height: int | None = None, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, background=UI.PANEL)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.inner = ttk.Frame(self.canvas, style="Panel.TFrame")
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        if height is not None:
            self.canvas.config(height=height)

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mousewheel support (Windows)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_frame_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # Make inner width match canvas width
        try:
            self.canvas.itemconfig(self._win, width=event.width)
        except Exception:
            pass

    def _on_mousewheel(self, event):
        # Only scroll when mouse is over canvas
        try:
            if self.winfo_containing(event.x_root, event.y_root) == self.canvas:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
