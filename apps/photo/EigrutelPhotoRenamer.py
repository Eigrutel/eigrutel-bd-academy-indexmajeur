# -*- coding: utf-8 -*-
"""
EigrutelPhotoRenamer.py — Photo Renamer (version beta)

"""

from __future__ import annotations

import os
import re
import subprocess
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import ExifTags, Image, ImageTk

from ui_common import (
    UI,
    apply_style,
    app_dir,
    format_pos,
    load_json,
    log_rename,
    new_session_id,
    open_with_default_app,
    sanitize_token,
    save_json,

)
from ui_common import apply_app_icon
from ui_common import bind_digits_only, set_default_counter
Image.MAX_IMAGE_PIXELS = None

APP_KEY = "photo"
TOOL_CODE = "PHOTO"
APP_TITLE = "Photo - Eigrutel tools"
SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")

SETTINGS_PATH = os.path.join(app_dir(), "settings.json")
TAGS_PATH = os.path.join(app_dir(), "tags_config.json")
TAG_LISTS_PATH = os.path.join(app_dir(), "photo_tag_lists.json")

INVALID_WIN = r'[<>:"/\\|?*\n\r\t]'

DOC_TAG_LISTS = {
    "Documentation": {
        "tags": [
            "Animaux",
            "Arts_et_sciences",
            "Costume",
            "Dessinateurs",
            "Divers",
            "Divertissement",
            "Geographie",
            "Industrie",
            "Logement",
            "Nature",
            "Objets",
            "Peintres",
            "Personnes",
            "Photographes",
            "Sports",
            "Transports",
            "References",
        ],
    },

    "Dessin_BD": {
        "tags": [
        "Croquis",
        "Crayonne",
        "Encrage",
        "Couleur",
        "Storyboard",
        "Illustration",
        "Recherche",
        "HD",
        "WIP",
        "Personnage",
        "Decor",
        "Planche",
    ],
    }
}


# =========================
# Helpers
# =========================
def human_size(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "?"
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n // 1024} Ko"
    return f"{n // (1024 * 1024)} Mo"


def sanitize_free_name(s: str) -> str:
    """Nom libre (champ Nom cible). On enlève seulement les chars Windows invalides."""
    s = (s or "").strip()
    s = re.sub(INVALID_WIN, "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "SANS_TITRE"


def tok(s: str) -> str:
    """Token depuis UI (respecte la casse de l'utilisateur)."""
    return sanitize_token(s or "")


def tok_upper(s: str) -> str:
    return tok(s).upper()


def counter_3(s: str) -> str:
    """Compteur formaté sur 3 chiffres si numérique, sinon token upper."""
    t = tok_upper(s)
    if not t:
        return ""
    if t.isdigit():
        try:
            return f"{int(t):03d}"
        except Exception:
            return t
    return t


def open_folder_of_file(path: str) -> None:
    folder = os.path.dirname(path)
    try:
        os.startfile(folder)  # type: ignore[attr-defined]
        return
    except Exception:
        pass
    try:
        subprocess.Popen(["explorer", folder])
    except Exception:
        pass

def center_on_parent(win, parent):
    win.update_idletasks()

    w = win.winfo_width()
    h = win.winfo_height()

    x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
    y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)

    win.geometry(f"{w}x{h}+{x}+{y}")
# =========================
# App
# =========================
class PhotoRenamerApp:
    LEFT_W = 340
    RIGHT_W = 440

    TAG_COLS = 2
    TAGS_PER_COL = 9
    TAGS_MAX_MAIN = TAG_COLS * TAGS_PER_COL  # 18


    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        apply_app_icon(self.root)

        try:
            self.root.state("zoomed")
        except Exception:
            pass
        self.root.minsize(1200, 750)

        apply_style(self.root)

        # session (log)
        self.session_id = new_session_id("PHOTO-")

        # state
        self.folder = ""
        self.include_subdirs = tk.BooleanVar(value=False)  # défaut décoché
        self.files: list[str] = []
        self.idx = 0

        # image refs
        self._img_tk = None
        self._canvas_img_id = None
        self._src_img = None

        # settings/tags
        self.settings = load_json(SETTINGS_PATH, {})
        self.tag_lists_data = self._load_tag_lists_data()
        self.current_tag_list_name = self._get_last_tag_list_name()
        self.tags_all = self._load_active_tags()
        self.tags_selected: list[str] = []

        # naming
        self.manual_mode = False
        self.include_type_var = tk.BooleanVar(value=True)
        self.include_doc_var = tk.BooleanVar(value=False)
        self.append_to_current_var = tk.BooleanVar(value=False)
        # couleurs boutons secondaires
        self.SUBBTN_BG = "#3c4F5F"  # bleu foncé (mais moins sombre que le fond gauche)
        self.SUBBTN_BG_ACTIVE = "#3c4F5F"
        self.SUBBTN_FG = "#FFFFFF"

        self._build_ui()
        self._bind_keyboard()
        self._restore_settings()

    def open_info_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Infos")
        apply_app_icon(dlg)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.minsize(520, 520)  # comme tags

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)

        # (Optionnel) petit titre, discret
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="EigrutelPhotoRenamer - Manuel").pack(anchor="w")

        # Zone centrale + scrollbar (comme tags)
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
            font=("Segoe UI", 10)
        )
        txt.tag_configure("title", font=("Segoe UI", 14, "bold"))
        txt.tag_configure("section", font=("Segoe UI", 11, "bold"))
        txt.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)

        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        

        txt.insert("end", "Raccourcis clavier\n", "section")

        txt.insert("end", "Navigation :\n")
        txt.insert("end", "- Flèche gauche  : fichier précédent\n")
        txt.insert("end", "- Flèche droite  : fichier suivant\n\n")

        txt.insert("end", "Actions :\n")
        txt.insert("end", "- Entrée         : RENOMMER\n")
        txt.insert("end", "- Ctrl+O         : Ouvrir dossier\n")
        txt.insert("end", "- Ctrl+Shift+O   : Ouvrir fichier (appli par défaut)\n")
        txt.insert("end", "- Ctrl+Shift+F   : Ouvrir l’emplacement du fichier\n")
        txt.insert("end", "- Ctrl+R         : ↺ Nomenclature\n")
        txt.insert("end", "- Ctrl+I         : Injecter nom actuel\n")
        txt.insert("end", "- Ctrl+T         : Gestion des tags\n\n")
        txt.insert("end", "-------------------------------------\n")
        txt.insert("end", "Colonne gauche - Renommage\n", "section")

        txt.insert("end", "- Nom actuel : nom du fichier sélectionné.\n")
        txt.insert("end", "- Nom cible : nom final modifiable.\n")
        txt.insert("end", "- Nom actuel (bouton) : injecte le nom actuel.\n")
        txt.insert("end", "- ↺ Nomenclature : recalcule le nom cible.\n")
        txt.insert("end", "- Ajouter PHOTO : ajoute ou retire le préfixe.\n")
        txt.insert("end", "- RENOMMER : applique le nouveau nom.\n")
        txt.insert("end", "- Infos + Métadonnées : affiche des informations de fichier et les métadonnées/EXIF quand disponibles.\n")
        txt.insert("end", "- Ouvrir fichier : ouvre la photo avec l’application par défaut.\n")
        txt.insert("end", "- Dossier : ouvre l’emplacement du fichier.\n")
        txt.insert("end", "- Précédent / Suivant : navigue dans la liste des fichiers chargés.\n\n")

        txt.insert("end", "Colonne centrale - Aperçu\n", "section")
        txt.insert("end", "- Affiche l’image en cours (redimensionnée pour tenir dans l’espace).\n\n")

        txt.insert("end", "Colonne droite - Détails et Tags\n", "section")
        txt.insert("end", "Champs utilisés pour construire la nomenclature automatique :\n")

        txt.insert("end", "- Année, Mois, Lieu, Précision : segments textuels (sanitisés pour Windows).\n")

        txt.insert("end", "- Compteur : si vide → pas de suffixe ; si numérique → formaté en 3 chiffres ")
        txt.insert("end", "(001, 002…)", "bold")
        txt.insert("end", " lors du calcul.\n")
        txt.insert("end", "  Après un renommage, si le compteur est numérique, il est auto-incrémenté (+1).\n\n")

        txt.insert("end", "Tags :\n", "bold")
        txt.insert("end", "- Sélection multiple : chaque tag coché est ajouté au nom (dans l’ordre de la liste).\n")
        txt.insert("end", "- “–” supprime directement un tag de la liste (sans confirmation).\n")
        txt.insert("end", "- Champ + bouton “+” : ajoute un tag à la liste.\n")
        txt.insert("end", "- “Gestion des tags” : ouvre une fenêtre dédiée pour réorganiser (Monter/Descendre) et supprimer/ajouter des tags.\n\n")
        txt.insert("end", "-------------------------------------\n")
        txt.insert("end", "Nomenclature automatique (principe)\n", "section")
        

        txt.insert("end", "Le nom cible est construit en concaténant des éléments séparés par des underscores :\n")
        txt.insert("end", "PHOTO_ + Année + Mois + Lieu + Précision + Tags… + Compteur(3 chiffres)\n", "bold")
        txt.insert("end", "Seuls les champs non vides sont inclus.\n\n")

        txt.insert("end", "Mode automatique vs mode manuel\n", "section")

        txt.insert("end", "- Mode automatique : le champ “Nom cible” suit la nomenclature ")
        txt.insert("end", "(mise à jour quand tu modifies un champ/tag ou quand tu changes de fichier).\n")

        txt.insert("end", "- Mode manuel : tu modifies “Nom cible” librement ")
        txt.insert("end", "(après injection ou saisie). ")
        txt.insert("end", "Le programme n’écrase plus le nom cible automatiquement.\n")

        txt.insert("end", "- “↺ Nomenclature” force le retour au mode automatique.\n\n")

        txt.insert("end", "Chargement des fichiers\n", "section")

        txt.insert("end", "- “Ouvrir dossier” charge les images du dossier.\n")
        txt.insert("end", "- “Inclure sous-dossiers” inclut aussi les images dans l’arborescence.\n")
        txt.insert("end", "Formats pris en charge : ")
        txt.insert("end", ".jpg .jpeg .png .webp .tif .tiff\n", "bold")

        txt.insert("end", "\nSécurité Windows\n", "section")
        txt.insert("end", "- Les caractères interdits dans Windows sont remplacés ")
        txt.insert("end", "(ex : < > : \" / \\ | ? *)", "bold")
        txt.insert("end", ".\n")
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
        txt.insert("end", "- Les espaces sont convertis en underscores, underscores multiples réduits.\n\n")

        
        txt.configure(state="disabled")  # lecture seule

        # Actions bas (comme tags)
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))

        ttk.Button(actions, text="Fermer", style="Side.TButton", command=dlg.destroy).pack(side="right")

        center_on_parent(dlg, self.root)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    # ---------- UI helpers ----------
    def _sub_button(self, parent, text: str, command, *, small: bool = True) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.SUBBTN_BG,
            fg=self.SUBBTN_FG,
            activebackground=self.SUBBTN_BG_ACTIVE,
            activeforeground=self.SUBBTN_FG,
            bd=0,
            relief="flat",
            cursor="hand2",
        )
        if small:
            btn.configure(padx=8, pady=3)
        else:
            btn.configure(padx=10, pady=6)
        return btn
    
    def _clear_btn(self, parent, entry: ttk.Entry, *, padx_left: int = 8) -> tk.Button:
        """
        Petit bouton "–" qui vide un Entry + recalcule la nomenclature.
        Look calé sur le "–" des tags.
        """
        def _do_clear():
            entry.delete(0, "end")
            self.reset_nomenclature()

        btn = tk.Button(
            parent,
            text="✕",
            command=_do_clear,
            bd=0,
            padx=6,
            pady=2,
            fg=getattr(UI, "ACCENT_10", "#2BA3B8"),
            bg=getattr(UI, "PANEL", "#FFFFFF"),
            activeforeground=getattr(UI, "ACCENT_10", "#2BA3B8"),
            activebackground=getattr(UI, "PANEL", "#FFFFFF"),
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )
        return btn
    # ---------- image handle safety ----------
    def _release_current_image(self):
        try:
            if self._src_img is not None:
                self._src_img.close()
        except Exception:
            pass
        self._src_img = None
        self._img_tk = None
        self._canvas_img_id = None

    # ---------- tags / listes ----------
    def _default_tags(self) -> list[str]:
        return ["Famille", "Voyage", "Supprimer", "Papa", "Maman", "créé par Simon Léturgie"]


    def _clean_tag_list(self, tags) -> list[str]:
        if not isinstance(tags, list):
            return []
        out: list[str] = []
        seen = set()
        for t in tags:
            s = str(t).strip()
            if not s:
                continue
            key = s.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        return out


    def _load_tag_lists_data(self) -> dict:
        data = load_json(TAG_LISTS_PATH, {})
        if not isinstance(data, dict):
            data = {}

        saved_lists = data.get("saved_lists", {})
        if not isinstance(saved_lists, dict):
            saved_lists = {}

        cleaned_saved = {}
        for name, tags in saved_lists.items():
            name_s = str(name).strip()
            if not name_s:
                continue
            cleaned_saved[name_s] = self._clean_tag_list(tags)

        active_tags = self._clean_tag_list(data.get("active_tags", []))
        tags_actuels = self._clean_tag_list(data.get("tags_actuels", []))
        last_loaded = str(data.get("last_loaded_list", "")).strip()

        if not active_tags:
            active_tags = self._default_tags()

        data = {
            "active_tags": active_tags,
            "tags_actuels": tags_actuels,
            "saved_lists": cleaned_saved,
            "last_loaded_list": last_loaded,
        }

        # Ajoute la liste prédéfinie Documentation si elle n'existe pas déjà
        for list_name, payload in DOC_TAG_LISTS.items():
            if list_name not in data["saved_lists"]:
                data["saved_lists"][list_name] = self._clean_tag_list(payload.get("tags", []))

        save_json(TAG_LISTS_PATH, data)
        return data


    def _save_tag_lists_data(self) -> None:
        self.tag_lists_data["active_tags"] = self._clean_tag_list(self.tags_all)
        save_json(TAG_LISTS_PATH, self.tag_lists_data)


    def _load_active_tags(self) -> list[str]:
        tags = self._clean_tag_list(self.tag_lists_data.get("active_tags", []))
        if not tags:
            tags = self._default_tags()
        return tags


    def _get_saved_tag_list_names(self) -> list[str]:
        saved = self.tag_lists_data.get("saved_lists", {})
        if not isinstance(saved, dict):
            return []
        names = [str(k).strip() for k in saved.keys() if str(k).strip()]
        names.sort(key=lambda s: s.lower())
        return names


    def _get_available_tag_list_names(self) -> list[str]:
        names = ["Tags actuels"]
        names.extend(self._get_saved_tag_list_names())
        return names


    def _get_last_tag_list_name(self) -> str:
        name = str(self.tag_lists_data.get("last_loaded_list", "")).strip()
        if name == "Tags actuels":
            return name
        if name and name in self.tag_lists_data.get("saved_lists", {}):
            return name
        return "Tags actuels"


    def _remember_current_tags_as_backup(self) -> None:
        self.tag_lists_data["tags_actuels"] = self._clean_tag_list(self.tags_all)
        self._save_tag_lists_data()


    def _load_tag_list_by_name(self, name: str) -> None:
        name = (name or "").strip()
        if not name:
            return

        self._remember_current_tags_as_backup()

        if name == "Tags actuels":
            new_tags = self._clean_tag_list(self.tag_lists_data.get("tags_actuels", []))
            if not new_tags:
                new_tags = self._clean_tag_list(self.tag_lists_data.get("active_tags", []))
        else:
            saved = self.tag_lists_data.get("saved_lists", {})
            new_tags = self._clean_tag_list(saved.get(name, []))

        if not new_tags:
            new_tags = self._default_tags()

        self.tags_selected = [t for t in self.tags_selected if t in new_tags]
        self.tags_all = new_tags
        self.current_tag_list_name = name
        self.tag_lists_data["active_tags"] = self._clean_tag_list(self.tags_all)
        self.tag_lists_data["last_loaded_list"] = name
        self._save_tag_lists_data()

        if hasattr(self, "lbl_tag_list"):
            self.lbl_tag_list.config(text=f"Liste : {name}")

        self._rebuild_tags()
        self.reset_nomenclature()


    def _save_current_tags_as_named_list(self, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False

        if name == "Tags actuels":
            messagebox.showerror("Erreur", "Le nom « Tags actuels » est réservé.", parent=self.root)
            return False

        saved = self.tag_lists_data.setdefault("saved_lists", {})
        if name in saved:
            if not messagebox.askyesno(
                "Remplacer la liste",
                f"La liste « {name} » existe déjà.\nVoulez-vous la remplacer ?",
                parent=self.root,
            ):
                return False

        saved[name] = self._clean_tag_list(self.tags_all)
        self.current_tag_list_name = name
        self.tag_lists_data["active_tags"] = self._clean_tag_list(self.tags_all)
        self.tag_lists_data["last_loaded_list"] = name
        self._save_tag_lists_data()

        if hasattr(self, "lbl_tag_list"):
            self.lbl_tag_list.config(text=f"Liste : {name}")

        return True

    # ---------- keyboard ----------
    def _bind_keyboard(self):
        self.root.bind_all("<KeyPress-Left>", lambda _e: (self.prev_file(), "break")[1])
        self.root.bind_all("<KeyPress-Right>", lambda _e: (self.next_file(), "break")[1])
        self.root.bind_all("<KeyPress-KP_Left>", lambda _e: (self.prev_file(), "break")[1])
        self.root.bind_all("<KeyPress-KP_Right>", lambda _e: (self.next_file(), "break")[1])

        self.root.bind_all("<KeyPress-Return>", lambda _e: (self.rename_current(), "break")[1])
        self.root.bind_all("<KeyPress-KP_Enter>", lambda _e: (self.rename_current(), "break")[1])
        self.root.bind_all("<Control-t>", lambda e: self.open_manage_tags_dialog())
        self.root.bind_all("<Control-i>", lambda e: self.inject_current_name())

        # --- Raccourcis ---
        self.root.bind_all("<Control-o>", lambda _e: (self.choose_folder(), "break")[1])
        self.root.bind_all("<Control-O>", lambda _e: (self.choose_folder(), "break")[1])
        self.root.bind_all("<Control-r>", lambda e: (self.reset_nomenclature(), "break")[1])
        self.root.bind_all("<Control-R>", lambda e: (self.reset_nomenclature(), "break")[1])

        # Ouvrir fichier : Ctrl+Shift+O (binder sur O maj et o)
        self.root.bind_all("<Control-Shift-o>", lambda _e: (self.open_current(), "break")[1])
        self.root.bind_all("<Control-Shift-O>", lambda _e: (self.open_current(), "break")[1])

        # Ouvrir dossier (emplacement) : Ctrl+Shift+F
        self.root.bind_all("<Control-Shift-f>", lambda _e: (self.open_current_folder(), "break")[1])
        self.root.bind_all("<Control-Shift-F>", lambda _e: (self.open_current_folder(), "break")[1])
    # ---------- UI ----------
    def _build_ui(self):
        # Topbar
        top = ttk.Frame(self.root, style="Topbar.TFrame")
        top.pack(fill="x")

        ttk.Label(top, text=TOOL_CODE, style="TopbarTitle.TLabel").pack(side="left", padx=16, pady=10)

        ttk.Button(top, text="Ouvrir dossier", style="Accent.TButton", command=self.choose_folder).pack(
            side="left", padx=10
        )

        ttk.Checkbutton(
            top,
            text="Inclure sous-dossiers",
            variable=self.include_subdirs,
            style="Topbar.TCheckbutton",
            command=self._on_toggle_subdirs,
        ).pack(side="left", padx=10)
        btn_info = tk.Button(
            top,
            text="i",
            command=self.open_info_dialog,
            bg=self.SUBBTN_BG, fg=self.SUBBTN_FG,
            activebackground=self.SUBBTN_BG_ACTIVE, activeforeground=self.SUBBTN_FG,
            bd=0, relief="flat",
            cursor="hand2",
        )
        btn_info.configure(font=("Segoe UI", 11, "bold"), padx=10, pady=4)
        btn_info.pack(side="right", padx=(0, 10), pady=8)
        ttk.Label(top, text="Formats : .jpg .png .webp .tif …", style="Topbar.TLabel").pack(side="right", padx=16)

        # Main
        main = ttk.Frame(self.root, style="App.TFrame")
        main.pack(fill="both", expand=True, padx=10, pady=10)

        main.grid_columnconfigure(0, minsize=self.LEFT_W, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_columnconfigure(2, minsize=self.RIGHT_W, weight=0)
        main.grid_rowconfigure(0, weight=1)

        self.left = ttk.Frame(main, style="Side.TFrame", width=self.LEFT_W)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.left.grid_propagate(False)

        self.center = ttk.Frame(main, style="Panel.TFrame")
        self.center.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

        self.right = ttk.Frame(main, style="Panel.TFrame", width=self.RIGHT_W)
        self.right.grid(row=0, column=2, sticky="nsew")
        self.right.grid_propagate(False)

        self._build_left()
        self._build_center()
        self._build_right()

    def _build_left(self):
        padx = 14
              
        self.lbl_current = ttk.Label(
            self.left, text="Nom actuel : —", style="SideInfo.TLabel", wraplength=self.LEFT_W - 2 * padx
        )
        self.lbl_current.pack(anchor="w", padx=padx, pady=(18, 0))

        ttk.Label(self.left, text="Nom cible", style="SideInfo.TLabel").pack(anchor="w", padx=padx, pady=(10, 0))
        self.target_name_var = tk.StringVar(value="")
        self.ent_target = ttk.Entry(self.left, textvariable=self.target_name_var)
        self.ent_target.pack(fill="x", padx=padx, pady=(2, 0))
        self.ent_target.bind("<KeyRelease>", lambda _e: self._on_target_edited())

        # Toggle + actions (secondaires en bleu)
        opts = ttk.Frame(self.left, style="Side.TFrame")
        opts.pack(fill="x", padx=padx, pady=(10, 6))

        ttk.Checkbutton(
            opts,
            text=f"Ajouter \"{TOOL_CODE}\" en début de nom",
            variable=self.include_type_var,
            style="Topbar.TCheckbutton",
            command=self._on_toggle_type,
        ).pack(anchor="w")

        ttk.Checkbutton(
            opts,
            text="Ajouter \"DOCUMENTATION\" en début de nom",
            variable=self.include_doc_var,
            style="Topbar.TCheckbutton",
            command=self._on_toggle_doc,
        ).pack(anchor="w")

        ttk.Checkbutton(
            opts,
            text="Ajouter au nom actuel",
            variable=self.append_to_current_var,
            style="Topbar.TCheckbutton",
            command=self._on_toggle_append_mode,
        ).pack(anchor="w")
        btn_row = ttk.Frame(self.left, style="Side.TFrame")
        btn_row.pack(fill="x", padx=padx, pady=(6, 6))

        btn_row.grid_columnconfigure(0, weight=1, uniform="btn")
        btn_row.grid_columnconfigure(1, weight=1, uniform="btn")

        self.btn_inject = self._sub_button(btn_row, "Nom actuel", self.inject_current_name, small=True)
        self.btn_inject.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_reset = self._sub_button(btn_row, "↺ Nomenclature", self.reset_nomenclature, small=True)
        self.btn_reset.grid(row=0, column=1, sticky="ew")
        
        

        

        ttk.Button(self.left, text="RENOMMER (Entrée)", style="Accent.TButton", command=self.rename_current).pack(
            fill="x", padx=padx, pady=(50, 70)
        )
        # --- Bloc INFOS + MÉTADONNÉES (collés) ---
        info_block = ttk.Frame(self.left, style="Side.TFrame")
        info_block.pack(fill="both", expand=True, padx=padx, pady=(10, 12))

        self.lbl_info = ttk.Label(
            info_block,
            text="—",
            style="SideInfo.TLabel",
            wraplength=self.LEFT_W - 2 * padx
        )
        self.lbl_info.pack(anchor="w", pady=(0, 6))  # <= collé au bloc meta

        meta_card = ttk.Frame(info_block, style="Side.TFrame")
        meta_card.pack(fill="both", expand=True, pady=(0, 0))

        self.text_meta = tk.Text(
            meta_card,
            width=38,
            height=10,
            bg=UI.STRUCT_30,
            fg="#D8DEE9",
            insertbackground="#D8DEE9",
            relief="solid",
            bd=1,
            highlightthickness=0,
        )
        self.text_meta.pack(fill="both", expand=True)
        
        # Actions "ouvrir" en bleu (discrets, alignés à gauche)
        act = ttk.Frame(self.left, style="Side.TFrame")
        act.pack(fill="x", padx=padx, pady=(0, 8))

        # 2 boutons côte à côte, largeur équilibrée
        self.btn_open = self._sub_button(act, "📂 Ouvrir fichier", self.open_current, small=True)
        self.btn_open.pack(side="left", fill="x", expand=True)

        self.btn_open_folder = self._sub_button(act, "📁 Dossier", self.open_current_folder, small=True)
        self.btn_open_folder.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # Navigation placée juste avant les métadonnées
        nav = ttk.Frame(self.left, style="Side.TFrame")
        nav.pack(fill="x", padx=padx, pady=(0, 0))
        ttk.Button(nav, text="← Précédent", style="Side.TButton", command=self.prev_file).pack(side="left")
        ttk.Button(nav, text="Suivant →", style="Side.TButton", command=self.next_file).pack(side="right")

        
        

    def _build_center(self):
        

        self.canvas = tk.Canvas(self.center, bg="#ffffff", highlightthickness=0, highlightbackground=UI.BORDER)
        self.canvas.pack(fill="both", expand=True, padx=14, pady=(70, 70))
        self.canvas.bind("<Configure>", lambda _e: self._redraw_canvas())

    def _build_right(self):
        padx = 14
        

        form = ttk.Frame(self.right, style="Panel.TFrame")
        form.grid_columnconfigure(0, weight=0)  # labels
        form.grid_columnconfigure(1, weight=0)  # entries
        form.grid_columnconfigure(2, weight=0)  # mini boutons
        form.pack(anchor="w", padx=padx, pady=(18, 10))

        label_w = 10
        label_style = "FormLabel.TLabel"

        ttk.Label(form, text="Année", width=label_w, background="#4B5B6B", foreground="#ffffff").grid(row=0, column=0, sticky="w", pady=4)
        self.ent_year = ttk.Entry(form, width=18)
        self.ent_year.grid(row=0, column=1, sticky="w", pady=4, padx=(6, 0))
        self._clear_btn(form, self.ent_year).grid(row=0, column=2, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(form, text="Mois", width=label_w, background="#4B5B6B", foreground="#ffffff").grid(row=1, column=0, sticky="w", pady=4)
        self.ent_month = ttk.Entry(form, width=18)
        self.ent_month.grid(row=1, column=1, sticky="w", pady=4, padx=(6, 0))
        self._clear_btn(form, self.ent_month).grid(row=1, column=2, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(form, text="Lieu", width=label_w, background="#4B5B6B", foreground="#ffffff").grid(row=2, column=0, sticky="w", pady=4)
        self.ent_place = ttk.Entry(form, width=18)
        self.ent_place.grid(row=2, column=1, sticky="w", pady=4, padx=(6, 0))
        self._clear_btn(form, self.ent_place).grid(row=2, column=2, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(form, text="Précision", width=label_w, background="#4B5B6B", foreground="#ffffff").grid(row=3, column=0, sticky="w", pady=4)
        self.ent_detail = ttk.Entry(form, width=18)
        self.ent_detail.grid(row=3, column=1, sticky="w", pady=4, padx=(6, 0))
        self._clear_btn(form, self.ent_detail).grid(row=3, column=2, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(form, text="Compteur", width=label_w, background="#1F9BA6", foreground="#ffffff").grid(row=4, column=0, sticky="w", pady=4)
        self.ent_counter = ttk.Entry(form, width=18)
        self.ent_counter.grid(row=4, column=1, sticky="w", pady=(4, 4), padx=(6, 0))
        bind_digits_only(self.ent_counter, self.root)
        set_default_counter(self.ent_counter, "1")
        self._clear_btn(form, self.ent_counter).grid(row=4, column=2, sticky="w", pady=4, padx=(8, 0))


        ttk.Separator(self.right).pack(fill="x", padx=padx, pady=10)

        list_row = ttk.Frame(self.right, style="Panel.TFrame")
        list_row.pack(fill="x", padx=padx, pady=(4, 6))

        self.btn_load_tag_list = self._sub_button(list_row, "Charger liste", self.open_load_tag_list_dialog, small=True)
        self.btn_load_tag_list.pack(side="left")

        self.btn_save_tag_list = self._sub_button(list_row, "Sauvegarder liste", self.save_current_tag_list_dialog, small=True)
        self.btn_save_tag_list.pack(side="left", padx=(8, 0))

        self.lbl_tag_list = tk.Label(
            self.right,
            text=f"Liste : {self.current_tag_list_name}",
            font=("Segoe UI", 10),
            bg=getattr(UI, "PANEL", "#FFFFFF"),
            fg="#111111",
            anchor="w",
        )

        self.lbl_tag_list.pack(anchor="w", padx=padx, pady=(0, 6))

        row = ttk.Frame(self.right, style="Panel.TFrame")
        row.pack(anchor="w", padx=padx, pady=(8, 0))

        self.ent_add_tag = ttk.Entry(row, width=29)
        self.ent_add_tag.pack(side="left")

    
        
        btn_plus = tk.Button(row, text="+", command=self.add_tag, font=("Segoe UI", 11, "bold"), width=2, height=1, bg=UI.ACCENT_10, fg="white", activebackground=UI.ACCENT_10, activeforeground="white", bd=0, relief="flat", cursor="hand2", padx=3, pady=0)

        btn_plus.pack(side="left", padx=6, pady=0)

        # Gestion des tags : bouton bleu
        self.btn_manage_tags = self._sub_button(row, """☰""", self.open_manage_tags_dialog, small=True)
        self.btn_manage_tags.configure(font=("Segoe UI", 11))
        self.btn_manage_tags.configure(pady=0)
        self.btn_manage_tags.pack(side="left", padx=(0, 0))
        self.btn_manage_tags.configure(bg=self.SUBBTN_FG, fg=self.SUBBTN_BG, activebackground=self.SUBBTN_FG, activeforeground=self.SUBBTN_BG,)

        # zone tags sans scrollbar (principale)
        self.tags_main = ttk.Frame(self.right, style="Panel.TFrame")
        self.tags_main.pack(fill="x", padx=padx, pady=(0, 0))

        self.tag_vars: dict[str, tk.BooleanVar] = {}
        self._rebuild_tags()

        for w in (self.ent_year, self.ent_month, self.ent_place, self.ent_detail, self.ent_counter):
            w.bind("<KeyRelease>", lambda _e: self.reset_nomenclature())
            self.ent_add_tag.bind("<Return>", lambda e: "break")
            self.ent_add_tag.bind("<KP_Enter>", lambda e: "break")
    # =========================
    # Tags UI (main)
    # =========================
    def _rebuild_tags(self):
        for child in list(self.tags_main.winfo_children()):
            child.destroy()
        self.tag_vars.clear()

        show_tags = self.tags_all[: self.TAGS_MAX_MAIN]

        for col in range(self.TAG_COLS):
            self.tags_main.grid_columnconfigure(col, weight=1, uniform="tagcol")

        wrap = 170
        r = 0
        c = 0

        for tag in show_tags:
            var = tk.BooleanVar(value=False)
            self.tag_vars[tag] = var

            cell = ttk.Frame(self.tags_main, style="Panel.TFrame")
            cell.grid(row=r, column=c, sticky="ew", padx=(0, 10 if c == 0 else 0), pady=3)

            # 0: bouton "-"  / 1: checkbox
            cell.grid_columnconfigure(0, weight=0)
            cell.grid_columnconfigure(1, weight=1)

            # suppression DIRECTE (sans validation)
            minus = tk.Button(
                cell,
                text="–",
                bd=0,
                padx=6,
                pady=2,
                fg=getattr(UI, "ACCENT_10", "#2BA3B8"),
                bg=getattr(UI, "PANEL", "#FFFFFF"),
                activeforeground=getattr(UI, "ACCENT_10", "#2BA3B8"),
                activebackground=getattr(UI, "PANEL", "#FFFFFF"),
                command=lambda t=tag: self._delete_tag(t),
            )
            minus.configure(font=("Segoe UI", 10, "bold"))
            minus.grid(row=0, column=0, sticky="w")

            chk = ttk.Checkbutton(
                cell,
                text=tag,
                variable=var,
                style="Tag.TCheckbutton",
                command=self.reset_nomenclature,
            )
            try:
                chk.configure(wraplength=wrap, justify="left")
            except Exception:
                pass
            chk.grid(row=0, column=1, sticky="w")

            c += 1
            if c >= self.TAG_COLS:
                c = 0
                r += 1

        for t in self.tags_selected:
            if t in self.tag_vars:
                self.tag_vars[t].set(True)
        self.tags_selected = [t for t in self.tags_selected if t in self.tag_vars]
    
    def _delete_tag(self, tag: str):
        """Suppression DIRECTE sans confirmation."""
        if tag not in self.tags_all:
            return
        self.tags_selected = [t for t in self.tags_selected if t != tag]
        self.tags_all = [t for t in self.tags_all if t != tag]
        self._save_tag_lists_data()
        self._rebuild_tags()
        self.reset_nomenclature()

    # =========================
    # Gestion des tags (dialog)
    # =========================
    def open_load_tag_list_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Charger une liste de tags")
        apply_app_icon(dlg)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.minsize(420, 360)

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Choisir une liste").pack(anchor="w", pady=(0, 8))

        mid = ttk.Frame(outer)
        mid.pack(fill="both", expand=True)

        lb = tk.Listbox(mid, activestyle="dotbox")
        sb = ttk.Scrollbar(mid, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        names = self._get_available_tag_list_names()
        for name in names:
            lb.insert("end", f"    {name}")

        try:
            current_index = names.index(self.current_tag_list_name)
            lb.selection_set(current_index)
            lb.activate(current_index)
            lb.see(current_index)
        except Exception:
            if names:
                lb.selection_set(0)
                lb.activate(0)

        def do_load():
            sel = lb.curselection()
            if not sel:
                return
            name = names[int(sel[0])]
            self._load_tag_list_by_name(name)
            dlg.destroy()

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))

        ttk.Button(actions, text="Charger", style="Accent.TButton", command=do_load).pack(side="left")
        ttk.Button(actions, text="Fermer", style="Side.TButton", command=dlg.destroy).pack(side="right")

        lb.bind("<Double-Button-1>", lambda e: do_load())

        center_on_parent(dlg, self.root)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    def save_current_tag_list_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Sauvegarder la liste de tags")
        apply_app_icon(dlg)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.minsize(420, 160)

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Nom de la liste").pack(anchor="w", pady=(0, 6))

        name_var = tk.StringVar()
        ent = ttk.Entry(outer, textvariable=name_var)
        ent.pack(fill="x", pady=(0, 10))

        if self.current_tag_list_name and self.current_tag_list_name != "Tags actuels":
            name_var.set(self.current_tag_list_name)

        def do_save():
            name = (name_var.get() or "").strip()
            if not name:
                messagebox.showerror("Erreur", "Veuillez saisir un nom de liste.", parent=dlg)
                return
            if self._save_current_tags_as_named_list(name):
                dlg.destroy()

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(6, 0))

        ttk.Button(actions, text="Enregistrer", style="Accent.TButton", command=do_save).pack(side="left")
        ttk.Button(actions, text="Fermer", style="Side.TButton", command=dlg.destroy).pack(side="right")

        ent.focus_set()
        ent.select_range(0, "end")
        ent.bind("<Return>", lambda e: do_save())

        center_on_parent(dlg, self.root)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    
    def open_manage_tags_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Gestion des tags")
        apply_app_icon(dlg)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.minsize(520, 520)

        outer = ttk.Frame(dlg, padding=12)
        outer.pack(fill="both", expand=True)

        # Ajout
        add_row = ttk.Frame(outer)
        add_row.pack(fill="x", pady=(0, 10))

        ent = ttk.Entry(add_row)
        ent.pack(side="left", fill="x", expand=True)

        def refresh_listbox(select_index: int | None = None):
            lb.delete(0, "end")
            for t in self.tags_all:
                lb.insert("end", f"    {t}")  # 2 espaces pour “padding” visuel
            if select_index is not None and 0 <= select_index < len(self.tags_all):
                lb.selection_set(select_index)
                lb.activate(select_index)
                lb.see(select_index)

        def do_add():
            raw = (ent.get() or "").strip()
            if not raw:
                return
            if raw in self.tags_all:
                ent.delete(0, "end")
                return
            self.tags_all.append(raw)
            ent.delete(0, "end")
            self._save_tag_lists_data()
            refresh_listbox(len(self.tags_all) - 1)
            self._rebuild_tags()
            self.reset_nomenclature()

        ttk.Button(add_row, text="Ajouter", style="Accent.TButton", command=do_add).pack(side="left", padx=(8, 0))
        ent.bind("<Return>", lambda e: "break")
        ent.bind("<KP_Enter>", lambda e: "break")

        # Liste + scrollbar
        mid = ttk.Frame(outer)
        mid.pack(fill="both", expand=True)

        lb = tk.Listbox(mid, activestyle="dotbox")
        sb = ttk.Scrollbar(mid, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Actions
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))

        def sel_index() -> int | None:
            sel = lb.curselection()
            if not sel:
                return None
            try:
                return int(sel[0])
            except Exception:
                return None

        def move_up():
            i = sel_index()
            if i is None or i <= 0:
                return
            self.tags_all[i - 1], self.tags_all[i] = self.tags_all[i], self.tags_all[i - 1]
            self._save_tag_lists_data()
            refresh_listbox(i - 1)
            self._rebuild_tags()

        def move_down():
            i = sel_index()
            if i is None or i >= len(self.tags_all) - 1:
                return
            self.tags_all[i + 1], self.tags_all[i] = self.tags_all[i], self.tags_all[i + 1]
            self._save_tag_lists_data()
            refresh_listbox(i + 1)
            self._rebuild_tags()

        def delete_sel():
            """Suppression DIRECTE sans confirmation."""
            i = sel_index()
            if i is None:
                return
            tag = self.tags_all[i]
            self.tags_all = [t for t in self.tags_all if t != tag]
            self.tags_selected = [t for t in self.tags_selected if t != tag]
            self._save_tag_lists_data()
            refresh_listbox(max(0, i - 1) if self.tags_all else None)
            self._rebuild_tags()
            self.reset_nomenclature()

        # (ici on laisse en ttk : c'est dans le dialog, ça ne gêne pas)
        ttk.Button(actions, text="Monter", style="Side.TButton", command=move_up).pack(side="left")
        ttk.Button(actions, text="Descendre", style="Side.TButton", command=move_down).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Supprimer", style="Side.TButton", command=delete_sel).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Fermer", style="Side.TButton", command=dlg.destroy).pack(side="right")

        refresh_listbox(0 if self.tags_all else None)
        center_on_parent(dlg, self.root)
        def on_close():
            try:
                self._save_tag_lists_data()
                self._rebuild_tags()
                self.reset_nomenclature()
            except Exception:
                pass
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", on_close)

    # =========================
    # File list
    # =========================
    def _on_toggle_subdirs(self):
        if self.folder:
            self.load_files(self.folder)

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.folder = folder
        self.settings["last_folder"] = folder
        self.settings["include_subdirs"] = bool(self.include_subdirs.get())
        save_json(SETTINGS_PATH, self.settings)
        self.load_files(folder)

    def load_files(self, folder: str):
        self._release_current_image()
        self.files = []
        self.idx = 0
        self.folder = folder

        if self.include_subdirs.get():
            for r, _dirs, files in os.walk(folder):
                for fn in files:
                    if fn.lower().endswith(SUPPORTED_EXTS):
                        self.files.append(os.path.join(r, fn))
        else:
            for fn in os.listdir(folder):
                p = os.path.join(folder, fn)
                if os.path.isfile(p) and fn.lower().endswith(SUPPORTED_EXTS):
                    self.files.append(p)

        self.files.sort(key=lambda p: p.lower())
        self._show_current()

    def current_path(self) -> str:
        if not self.files:
            return ""
        if self.idx < 0 or self.idx >= len(self.files):
            return ""
        return self.files[self.idx]

    def prev_file(self):
        if not self.files:
            return
        self.idx = (self.idx - 1) % len(self.files)
        self._show_current()

    def next_file(self):
        if not self.files:
            return
        self.idx = (self.idx + 1) % len(self.files)
        self._show_current()

    # =========================
    # Naming
    # =========================

    def _selected_tags(self) -> list[str]:
        """
        Source de vérité = l'état des checkboxes.
        On met aussi à jour self.tags_selected pour que _rebuild_tags()
        puisse restaurer l'état après un rebuild (tri/suppression/ajout).
        """
        selected = [t for t, v in self.tag_vars.items() if v.get()]
        self.tags_selected = selected[:]  # mémorise UNIQUEMENT ce qui est coché
        return selected

    def _build_append_parts(self) -> list[str]:
        """
        Éléments à AJOUTER en fin de nom actuel.
        En mode append, on ne remet pas les préfixes PHOTO / DOCUMENTATION,
        on ajoute seulement les informations nouvelles.
        """
        year = tok_upper(self.ent_year.get())
        month = tok_upper(self.ent_month.get())
        place = tok(self.ent_place.get())
        detail = tok(self.ent_detail.get())

        parts: list[str] = []

        if year:
            parts.append(year)
        if month:
            parts.append(month)
        if place:
            parts.append(place)
        if detail:
            parts.append(detail)

        tags = self._selected_tags()
        self.tags_selected = tags[:]
        for t in tags:
            parts.append(tok(t))

        c = counter_3(self.ent_counter.get())
        if c:
            parts.append(c)

        return [p for p in parts if p]


    def _build_generated_base(self) -> str:
        if self.append_to_current_var.get():
            return self._build_generated_base_append_mode()

        year = tok_upper(self.ent_year.get())
        month = tok_upper(self.ent_month.get())
        place = tok(self.ent_place.get())
        detail = tok(self.ent_detail.get())

        parts: list[str] = []

        if self.include_doc_var.get():
            parts.append("DOCUMENTATION")

        if self.include_type_var.get():
            parts.append(TOOL_CODE)

        if year:
            parts.append(year)
        if month:
            parts.append(month)
        if place:
            parts.append(place)
        if detail:
            parts.append(detail)

        tags = self._selected_tags()
        self.tags_selected = tags[:]
        for t in tags:
            parts.append(tok(t))

        c = counter_3(self.ent_counter.get())
        if c:
            parts.append(c)

        base = "_".join([p for p in parts if p])
        if not base:
            return TOOL_CODE if self.include_type_var.get() else "SANS_TITRE"
        return base


    def _build_generated_base_append_mode(self) -> str:
        path = self.current_path()

        if path:
            current_base = os.path.splitext(os.path.basename(path))[0]
        else:
            current_base = ""

        current_base = sanitize_free_name(current_base)

        # Préfixes ajoutés AU DÉBUT en mode append
        if self.include_type_var.get():
            prefix_photo = f"{TOOL_CODE}_"
            if current_base:
                if not current_base.startswith(prefix_photo):
                    current_base = prefix_photo + current_base
            else:
                current_base = TOOL_CODE

        if self.include_doc_var.get():
            prefix_doc = "DOCUMENTATION_"
            if current_base:
                if not current_base.startswith(prefix_doc):
                    current_base = prefix_doc + current_base
            else:
                current_base = "DOCUMENTATION"

        added_parts = self._build_append_parts()

        if not current_base and not added_parts:
            return "SANS_TITRE"

        if not added_parts:
            return current_base or "SANS_TITRE"

        if not current_base:
            return "_".join(added_parts)

        return current_base + "_" + "_".join(added_parts)

    def _on_target_edited(self):
        self.manual_mode = True

    def _on_toggle_type(self):
        """
        Si on est en manuel (injecté / édité), on ajoute/retire juste le préfixe.
        Si on est en auto, on recalcule la nomenclature.
        """
        if self.manual_mode:
            cur = sanitize_free_name(self.target_name_var.get())
            prefix = f"{TOOL_CODE}_"
            if self.include_type_var.get():
                if not cur.startswith(prefix):
                    self.target_name_var.set(prefix + cur)
            else:
                if cur.startswith(prefix):
                    self.target_name_var.set(cur[len(prefix):])
        else:
            self.reset_nomenclature()

    def _on_toggle_doc(self):
        """
        Même logique que PHOTO :
        - en manuel → on injecte/retire juste le préfixe
        - en auto → on recalcule
        """
        prefix = "DOCUMENTATION_"

        if self.manual_mode:
            cur = sanitize_free_name(self.target_name_var.get())

            if self.include_doc_var.get():
                if not cur.startswith(prefix):
                    self.target_name_var.set(prefix + cur)
            else:
                if cur.startswith(prefix):
                    self.target_name_var.set(cur[len(prefix):])
        else:
            self.reset_nomenclature()

    def _on_toggle_append_mode(self):
        """
        Changement de mode :
        - en manuel, on ne touche pas au texte déjà saisi
        - en auto, on recalcule le nom cible
        """
        if not self.manual_mode:
            self.reset_nomenclature()

    def inject_current_name(self):
        path = self.current_path()
        if not path:
            return

        base = os.path.splitext(os.path.basename(path))[0]
        base = sanitize_free_name(base)

        # En mode "ajouter au nom actuel", on part du vrai nom actuel
        # puis on applique les préfixes demandés au début.
        if self.append_to_current_var.get():
            if self.include_type_var.get():
                prefix_photo = f"{TOOL_CODE}_"
                if not base.startswith(prefix_photo):
                    base = prefix_photo + base

            if self.include_doc_var.get():
                prefix_doc = "DOCUMENTATION_"
                if not base.startswith(prefix_doc):
                    base = prefix_doc + base

            self.target_name_var.set(base)
            self.manual_mode = True
            return

        # Mode normal : gestion des préfixes DOCUMENTATION puis PHOTO
        prefix_doc = "DOCUMENTATION_"
        if self.include_doc_var.get():
            if not base.startswith(prefix_doc):
                base = prefix_doc + base
        else:
            if base.startswith(prefix_doc):
                base = base[len(prefix_doc):]

        prefix_photo = f"{TOOL_CODE}_"
        if self.include_type_var.get():
            if not base.startswith(prefix_photo):
                base = prefix_photo + base
        else:
            if base.startswith(prefix_photo):
                base = base[len(prefix_photo):]

        self.target_name_var.set(base)
        self.manual_mode = True
        
    def reset_nomenclature(self):
        self.manual_mode = False
        self.target_name_var.set(self._build_generated_base())

    def _increment_counter_if_numeric(self):
        raw = (self.ent_counter.get() or "").strip()
        if not raw:
            return
        if raw.isdigit():
            try:
                n = int(raw) + 1
                self.ent_counter.delete(0, "end")
                self.ent_counter.insert(0, str(n))
            except Exception:
                pass

    # =========================
    # Display
    # =========================
    def _show_current(self):
        path = self.current_path()
        if not path:
            self.lbl_info.config(text="—")
            self.lbl_current.config(text="Nom actuel : —")
            self.target_name_var.set("")
            self.text_meta.delete("1.0", "end")
            self.canvas.delete("all")
            return

        fn = os.path.basename(path)

        try:
            sz = human_size(os.path.getsize(path))
        except Exception:
            sz = "?"
        pos = f"({format_pos(self.idx, len(self.files))})"
        self.lbl_info.config(text=f"{sz} • {pos}")

        self.lbl_current.config(text=f"Nom actuel : {fn}")

        self._fill_meta(path)
        self._load_preview(path)

        if self.append_to_current_var.get():
            self.manual_mode = False
            self.target_name_var.set(self._build_generated_base())
        elif not self.manual_mode:
            self.target_name_var.set(self._build_generated_base())

    def _fill_meta(self, path: str):
        self.text_meta.delete("1.0", "end")
        lines = []

        try:
            img = Image.open(path)
            self._src_img = img.copy()
            img.close()
        except Exception:
            self._src_img = None

        try:
            if self._src_img is not None:
                exif = None
                try:
                    exif = self._src_img.getexif()
                except Exception:
                    exif = None
                if exif:
                    for k, v in exif.items():
                        tag = ExifTags.TAGS.get(k, k)
                        lines.append(f"{tag} : {v}")
                w, h = self._src_img.size
                lines.append(f"Taille : {w}x{h}")
        except Exception:
            pass

        lines.append(f"Fichier : {os.path.basename(path)}")
        self.text_meta.insert("1.0", "\n".join(lines) if lines else "—")

    def _load_preview(self, path: str):
        self._release_current_image()
        try:
            img = Image.open(path)
            self._src_img = img.copy()
            img.close()
        except Exception:
            self._src_img = None
        self._redraw_canvas()

    def _redraw_canvas(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        if self._src_img is None:
            return

        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())

        tw = cw - 10
        th = ch - 10
        if tw < 2 or th < 2:
            return

        img = self._src_img.copy()
        img.thumbnail((tw, th))

        self._img_tk = ImageTk.PhotoImage(img)
        x = (cw - img.width) // 2
        y = (ch - img.height) // 2
        self._canvas_img_id = self.canvas.create_image(x, y, anchor="nw", image=self._img_tk)

    # =========================
    # Actions
    # =========================
    def open_current(self):
        path = self.current_path()
        if path:
            try:
                open_with_default_app(path)
            except Exception as e:
                messagebox.showerror("Erreur", str(e), parent=self.root)

    def open_current_folder(self):
        path = self.current_path()
        if not path:
            return
        try:
            open_folder_of_file(path)
        except Exception as e:
            messagebox.showerror("Erreur", str(e), parent=self.root)

    def rename_current(self):
        path = self.current_path()
        if not path:
            return

        folder = os.path.dirname(path)
        ext = os.path.splitext(path)[1]
        old_name = os.path.basename(path)

        base_final = sanitize_free_name(self.target_name_var.get())
        new_name = f"{base_final}{ext}"
        new_path = os.path.join(folder, new_name)

        if os.path.abspath(new_path).lower() == os.path.abspath(path).lower():
            self.next_file()
            return

        if os.path.exists(new_path):
            messagebox.showerror("Erreur", "Le nom cible existe déjà.", parent=self.root)
            return

        try:
            self._release_current_image()
            os.rename(path, new_path)
            self.files[self.idx] = new_path

            try:
                log_rename(
                    tool=APP_KEY,
                    session_id=self.session_id,
                    folder=folder,
                    old_path=path,
                    new_path=new_path,
                    old_name=old_name,
                    new_name=new_name,
                    status="ok",
                    user_target_mode=("MANUEL" if self.manual_mode else "AUTO"),
                    conflict_resolution="none",
                )
            except Exception:
                pass

            self._increment_counter_if_numeric()

            self._show_current()
            self.next_file()

        except Exception as e:
            try:
                log_rename(
                    tool=APP_KEY,
                    session_id=self.session_id,
                    folder=folder,
                    old_path=path,
                    new_path=new_path,
                    old_name=old_name,
                    new_name=new_name,
                    status="failed",
                    error=str(e),
                )
            except Exception:
                pass
            messagebox.showerror("Erreur", str(e), parent=self.root)

    # =========================
    # Tag actions
    # =========================
    def add_tag(self):
        raw = (self.ent_add_tag.get() or "").strip()
        if not raw:
            return
        tag = raw
        if tag in self.tags_all:
            self.ent_add_tag.delete(0, "end")
            return
        self.tags_all.append(tag)
        self._save_tag_lists_data()
        self.ent_add_tag.delete(0, "end")
        self._rebuild_tags()
        self.reset_nomenclature()

    # =========================
    # Settings
    # =========================
    def _restore_settings(self):
        last = self.settings.get("last_folder", "")
        inc = bool(self.settings.get("include_subdirs", False))
        self.include_subdirs.set(inc)
        set_default_counter(self.ent_counter, "1")

        self.tags_all = self._load_active_tags()
        if hasattr(self, "lbl_tag_list"):
            self.lbl_tag_list.config(text=f"Liste : {self.current_tag_list_name}")
        self._rebuild_tags()
        self.reset_nomenclature()

        if last and os.path.isdir(last):
            self.folder = last
            self.load_files(last)
            


def main():
    root = tk.Tk()
    PhotoRenamerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
