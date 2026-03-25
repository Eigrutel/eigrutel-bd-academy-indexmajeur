# -*- coding: utf-8 -*-
"""

"""

import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from ui_common import apply_style, apply_app_icon


APP_TITLE = "INDEX MAJEUR"
TOOLS = [
    {
        "title": "Twins",
        "subtitle": "Détection de doublons",
        "folder": "applications",
        "exe": "EigrutelTwins.exe",
        "kind": "std",
    },
    {
        "title": "Photo",
        "subtitle": "Renommer photographies et images",
        "folder": "applications",
        "exe": "EigrutelPhotoRenamer.exe",
        "kind": "std",
    },
    {
        "title": "Documentation",
        "subtitle": "Organisation des références visuelles",
        "folder": "applications",
        "exe": "EigrutelDocumentationRenamer.exe",
        "kind": "std",
    },
    {
        "title": "Index Documentation",
        "subtitle": "aka LA MORGUE",
        "folder": "applications",
        "exe": "EigrutelIndexDocumentation.exe",
        "kind": "std",
    },
]
# Palette plus vive, proche des autres programmes
COLORS = {
    "bg": "#F5F7FA",
    "card": "#2AA1AE",       # turquoise de la suite
    "card_hover": "#238E99",
    "doc": "#4B5B6B",        # couleur navigation / précédent-suivant
    "doc_hover": "#40505F",
    "orange": "#F4B183",
    "orange_hover": "#E7A06A",
    "footer_text": "#5C6C79",
    "plus_bg": "#D9E1E8",
    "plus_hover": "#C7D2DC",
    "plus_text": "#2E3C49",
    "popup_bg": "#F6F8FA",
    "popup_text": "#2F3A44",
    "popup_muted": "#50606D",
}


def get_launcher_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resolve_tool_exe(folder, exe_name):
    base = get_launcher_dir()
    candidates = [
        os.path.join(base, folder, exe_name),           # IndexMajeur/applications/MonExe.exe
        os.path.join(base, exe_name),                   # fallback : exe à côté du launcher
        os.path.join(base, "dist", folder, exe_name),   # fallback dev éventuel
        os.path.join(base, "dist", exe_name),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def launch_tool(folder, exe_name):
    exe_path = resolve_tool_exe(folder, exe_name)
    if not os.path.exists(exe_path):
        messagebox.showerror(
            "Introuvable",
            "Impossible de trouver :\n"
            f"{exe_name}\n\n"
            "Attendu ici :\n"
            f"{exe_path}",
        )
        return
    try:
        subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
    except Exception as e:
        messagebox.showerror("Erreur lancement", str(e))


def center_window(win, width, height, parent=None):
    win.update_idletasks()
    if parent is None:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max((sw - width) // 2, 0)
        y = max((sh - height) // 2, 0)
    else:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(px + (pw - width) // 2, 0)
        y = max(py + (ph - height) // 2, 0)
    win.geometry(f"{width}x{height}+{x}+{y}")

def configure_extra_styles(root):
    style = ttk.Style(root)

    style.configure(
        "Plus.TButton",
        background="#2e3440",
        foreground="#FFFFFF",
        font=("Segoe UI", 11, "bold"),
        padding=4,
        borderwidth=0,
    )

    style.map(
        "Plus.TButton",
        background=[
            ("active", "#2e3440"),
            ("pressed", "#2e3440"),
        ],
        foreground=[
            ("active", "#FFFFFF"),
            ("pressed", "#FFFFFF"),
        ],
    )

def bind_click_recursive(widget, callback):
    widget.bind("<Button-1>", callback)
    for child in widget.winfo_children():
        child.bind("<Button-1>", callback)


def set_card_hover(frame, title_lbl, sub_lbl, color, hover):
    def enter(_event=None):
        frame.configure(bg=hover)
        title_lbl.configure(bg=hover)
        sub_lbl.configure(bg=hover)

    def leave(_event=None):
        frame.configure(bg=color)
        title_lbl.configure(bg=color)
        sub_lbl.configure(bg=color)

    for w in (frame, title_lbl, sub_lbl):
        w.bind("<Enter>", enter)
        w.bind("<Leave>", leave)


def build_card(parent, tool):
    if tool["kind"] == "doc":
        color = COLORS["doc"]
        hover = COLORS["doc_hover"]
        title_fg = "#FFFFFF"
        sub_fg = "#EAF3F6"
    elif tool["kind"] == "orange":
        color = COLORS["orange"]
        hover = "#FFAA3C"
        title_fg = "#FFFFFF"
        sub_fg = "#FFEBD6"
    else:
        color = COLORS["card"]
        hover = COLORS["card_hover"]
        title_fg = "#FFFFFF"
        sub_fg = "#EAF3F6"
    card = tk.Frame(
        parent,
        bg=color,
        bd=0,
        highlightthickness=2,
        highlightbackground="#FFFFFF",
        cursor="hand2",
        padx=16,
        pady=12,
    )

    title = tk.Label(
        card,
        text=tool["title"],
        bg=color,
        fg=title_fg,
        font=("Segoe UI", 13, "bold"),
        anchor="center",
        justify="center",
    )
    title.pack(anchor="center")

    subtitle = tk.Label(
        card,
        text=tool["subtitle"],
        bg=color,
        fg=sub_fg,
        font=("Segoe UI", 9),
        anchor="center",
        justify="center",
        wraplength=320,
    )
    subtitle.pack(anchor="center", pady=(4, 0))

    callback = lambda _e=None, f=tool["folder"], e=tool["exe"]: launch_tool(f, e)
    bind_click_recursive(card, callback)
    set_card_hover(card, title, subtitle, color, hover)
    return card


def open_search_help(root):
    popup = tk.Toplevel(root)
    popup.title("La suite Index Majeur")
    apply_app_icon(popup)
    popup.configure(bg=COLORS["popup_bg"])
    popup.transient(root)
    popup.resizable(False, False)

    # === zone scrollable ===
    outer = tk.Frame(popup, bg=COLORS["popup_bg"])
    outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(
        outer,
        bg=COLORS["popup_bg"],
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(side="left", fill="both", expand=True)

    scrollbar = ttk.Scrollbar(
        outer,
        orient="vertical",
        command=canvas.yview,
    )
    scrollbar.pack(side="right", fill="y")

    canvas.configure(yscrollcommand=scrollbar.set)

    content_frame = tk.Frame(canvas, bg=COLORS["popup_bg"])
    canvas_window = canvas.create_window((0, 0), window=content_frame, anchor="nw")

    def _on_frame_configure(event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event):
        canvas.itemconfigure(canvas_window, width=event.width)

    content_frame.bind("<Configure>", _on_frame_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    # === vrai contenu ===
    inner = tk.Frame(content_frame, bg=COLORS["popup_bg"], padx=18, pady=16)
    inner.pack(fill="both", expand=True)
    tk.Label(
        inner,
        text="INDEX MAJEUR",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 12, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(0, 10))

    tk.Label(
        inner,
        text="Un fichier mal nommé est perdu.\nUn fichier bien nommé est retrouvable.",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 10, "bold"),
        anchor="w",
        justify="left",
        wraplength=760,
    ).pack(anchor="w", pady=(0, 10))

    tk.Label(
        inner,
        text="img064.jpg → introuvable\nDOCUMENTATION_gorille_marche_profil.jpg → retrouvable immédiatement",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Arial", 10),
        anchor="w",
        justify="left",
        wraplength=760,
    ).pack(anchor="w", pady=(0, 14))

    content = tk.Frame(inner, bg=COLORS["popup_bg"])
    content.pack(fill="both", expand=True)

    def add_section(title):
        tk.Label(
            content,
            text=title,
            bg=COLORS["popup_bg"],
            fg = COLORS["popup_text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(10, 6))

    def add_table(headers, rows, widths=(18, 18, 44)):
        table = tk.Frame(content, bg=COLORS["popup_bg"])
        table.pack(fill="x", anchor="w")

        for i, h in enumerate(headers):
            tk.Label(
                table,
                text=h,
                width=widths[i],
                bg=COLORS["popup_bg"],
                fg = COLORS["popup_text"],
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).grid(row=0, column=i, sticky="w", padx=(0, 10), pady=(0, 4))

        for r, row in enumerate(rows, start=1):
            for c, val in enumerate(row):
                if c == 2:
                    font = ("Arial", 9)
                    fg = COLORS["popup_text"]
                elif c == 1:
                    font = ("Arial", 9)
                    fg = COLORS["popup_muted"]
                else:
                    font = ("Segoe UI", 9)
                    fg = COLORS["popup_text"]

                tk.Label(
                    table,
                    text=val,
                    width=widths[c],
                    bg=COLORS["popup_bg"],
                    fg=fg,
                    font=font,
                    anchor="w",
                ).grid(row=r, column=c, sticky="w", padx=(0, 10), pady=1)

    # --- MORGUE ---

    add_section("La morgue (tradition d’illustrateur)")

    tk.Label(
        content,
        text="Depuis les illustrateurs de presse jusqu’aux auteurs de bande dessinée, tous ont constitué \nleur propre morgue : une réserve d’images, classées, prêtes à servir.\n\n"
             "Sans organisation, une morgue devient inutilisable.\n"
             "Accumuler des images ne suffit pas.",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 10),
        anchor="w",
        justify="left",
        wraplength=760,
    ).pack(anchor="w", pady=(0, 10))

    tk.Label(
        content,
        text="Index Majeur transforme une morgue en outil de travail.",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(0, 8))

    # --- NOMENCLATURE ---

    add_section("Pourquoi nommer correctement ?")

    tk.Label(
        content,
        text="Sans nomenclature :",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(4, 2))

    tk.Label(
        content,
        text=(
            "img064.jpg → perdu\n"
            "IMG_2025 → confus\n"
            "cheval.jpg → trop vague\n"
            "images mélangées → chaos\n"
            "archives massives → inutilisables"
        ),
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_muted"],
        font=("Arial", 10),
        anchor="w",
        justify="left",
    ).pack(anchor="w", pady=(0, 8))

    tk.Label(
        content,
        text="Avec une bonne nomenclature :",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(6, 2))

    tk.Label(
        content,
        text=(
            "DOCUMENTATION_guitare_atelier_luthier_silhouette_composition_lignes → retrouvable immédiatement"
        ),
        bg=COLORS["popup_bg"],
        fg="#2BA3B8",
        font=("Arial", 10),
        anchor="w",
        justify="left",
    ).pack(anchor="w", pady=(0, 10))
    tk.Label(
        content,
        text=(
            
            "classement automatique\n"
            "gorille_marche_profil → recherche précise\n"
            "regroupement immédiat par mots-clés\n"
            "bibliothèque exploitable"
        ),
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Arial", 10),
        anchor="w",
        justify="left",
    ).pack(anchor="w", pady=(0, 10))

    # --- LOGIQUE GRAPHQUE ---

    add_section("Sujet + intérêt graphique")

    tk.Label(
        content,
        text="Une image n’est pas seulement un sujet.\nElle est aussi un outil graphique.",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(0, 8))


    # --- OUTILS ---

    add_section("Les outils")

    add_table(
        ("Outil", "Rôle", "Utilité"),
        [
            ("Twins", "nettoyage", "supprimer doublons"),
            ("Photo", "renommage", "tri rapide"),
            ("Documentation", "structuration", "niveaux + dossiers"),
            ("Index", "exploitation", "recherche + dessin"),
        ],
    )

    # --- WORKFLOW ---

    add_section("Workflow conseillé")

    tk.Label(
            content,
            text="Twins → Photo  → Documentation → Index Documentation",
            bg=COLORS["popup_bg"],
            fg=COLORS["popup_text"],
            font=("Segoe UI", 10,),
            anchor="w",
        ).pack(anchor="w", pady=(8, 0))
    tk.Label(
        content,
        text="Trier → Nommer → Structurer → Exploiter",
        bg=COLORS["popup_bg"],
        fg="#2BA3B8",
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(0, 6))

    # --- BONUS WINDOWS ---

    tk.Label(
        inner,
        text="BONUS — Recherche Windows",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 12, "bold"),
        anchor="w",
    ).pack(anchor="w", pady=(14, 10))

    
    

    
    content = tk.Frame(inner, bg=COLORS["popup_bg"])
    content.pack(fill="both", expand=True)

    def add_section(title):
        tk.Label(
            content,
            text=title,
            bg=COLORS["popup_bg"],
            fg=COLORS["popup_text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(10, 6))

    def add_table(headers, rows, widths=(22, 16, 38)):
        table = tk.Frame(content, bg=COLORS["popup_bg"])
        table.pack(fill="x", anchor="w")

        for i, h in enumerate(headers):
            tk.Label(
                table,
                text=h,
                width=widths[i],
                bg=COLORS["popup_bg"],
                fg=COLORS["popup_text"],
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                justify="left",
            ).grid(row=0, column=i, sticky="w", padx=(0, 10), pady=(0, 4))

        for r, row in enumerate(rows, start=1):
            for c, val in enumerate(row):

                if c == 2:  # colonne EXEMPLES
                    font = ("Arial", 9)
                    fg = "#2BA3B8"   # rouge
                elif c == 1:  # syntaxe
                    font = ("Arial", 9)
                    fg = COLORS["popup_muted"]
                else:  # description
                    font = ("Segoe UI", 9)
                    fg = COLORS["popup_text"]

                tk.Label(
                    table,
                    text=val,
                    width=widths[c],
                    bg=COLORS["popup_bg"],
                    fg = COLORS["popup_text"],
                    font=font,
                    anchor="w",
                    justify="left",
                ).grid(row=r, column=c, sticky="w", padx=(0, 10), pady=1)

    add_section("Règles générales")
    add_table(
        ("Règle", "Tolérance", "Exemple"),
        [
            ("Casse", "Ignorée", "papa = PAPA = Papa"),
            ("Accents", "Souvent ignorés", "scenario = scénario"),
            ("Séparateurs", "Souvent tolérés", "papa_jean = papa-jean = papa jean"),
            ("Ordre des mots", "Libre", "jean papa = papa jean"),
            ("Pluriels", "Tolérance partielle", "cheval ≠ toujours chevaux"),
        ],
        widths=(22, 18, 34),
    )

    add_section("Opérateurs logiques")
    add_table(
        ("Fonction", "Mot-clé / signe", "Exemple"),
        [
            ("ET (implicite)", "AND / espace", "papa 2026"),
            ("OU", "OR / |", "papa OR jean"),
            ("SAUF", "NOT / -", "papa -simon"),
            ("Expression exacte", '" "', '"festival BD"'),
        ],
        widths=(22, 18, 34),
    )

    add_section("Comparateurs numériques")
    add_table(
        ("Fonction", "Signe", "Exemple"),
        [
            ("Supérieur à", ">", "size:>10MB"),
            ("Inférieur à", "<", "size:<1MB"),
            ("Supérieur ou égal", ">=", "size:>=5MB"),
            ("Inférieur ou égal", "<=", "size:<=100KB"),
            ("Intervalle", "..", "datemodified:01/01/2026..31/01/2026"),
        ],
        widths=(22, 12, 40),
    )

    add_section("Symboles spéciaux")
    add_table(
        ("Symbole", "Fonction", "Exemple"),
        [
            ("*", "Remplace plusieurs caractères", "scena*"),
            ("?", "Remplace un caractère", "file?.txt"),
            ('"', "Recherche exacte", '"séquencier final"'),
            ("-", "Exclusion rapide", "comptabilité -urssaf"),
            ("()", "Regroupement logique", "(rapport OR facture) 2026"),
        ],
        widths=(12, 28, 34),
    )

    add_section("Filtres par propriétés (AQS)")
    add_table(
        ("Propriété", "Syntaxe", "Exemple"),
        [
            ("Nom", "name:", "name:rapport"),
            ("Extension", "ext:", "ext:pdf"),
            ("Type", "type:", "type:image"),
            ("Taille", "size:", "size:>5MB"),
            ("Date modification", "datemodified:", "datemodified:this month"),
            ("Auteur", "author:", "author:Simon"),
            ("Titre", "title:", "title:Projet"),
            ("Contenu texte", "content:", "content:contrat"),
        ],
        widths=(22, 18, 32),
    )

    # --- CRÉDITS / SITE ---

    sep = tk.Label(
        inner,
        text="—",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_muted"],
        font=("Segoe UI", 10),
    )
    sep.pack(anchor="w", pady=(14, 6))

    tk.Label(
        inner,
        text="Programmes conçus, réalisés et offerts par Simon Léturgie.",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 9),
        anchor="w",
        justify="left",
    ).pack(anchor="w")

    tk.Label(
        inner,
        text="Eigrutel BD Academy - 2026",
        bg=COLORS["popup_bg"],
        fg=COLORS["popup_text"],
        font=("Segoe UI", 9),
        anchor="w",
    ).pack(anchor="w", pady=(0, 4))


    # --- lien cliquable ---
    def open_site(event):
        import webbrowser
        webbrowser.open("https://www.stripmee.com")

    link = tk.Label(
        inner,
        text="stripmee.com",
        bg=COLORS["popup_bg"],
        fg="#2BA3B8",
        font=("Segoe UI", 9, "underline"),
        cursor="hand2",
        anchor="w",
    )

    link.pack(anchor="w")
    link.bind("<Button-1>", open_site)
    close_btn = tk.Button(
        inner,
        text="Fermer",
        bg=COLORS["doc"],
        fg="#FFFFFF",
        activebackground=COLORS["doc_hover"],
        activeforeground="#FFFFFF",
        relief="flat",
        bd=0,
        padx=14,
        pady=8,
        font=("Segoe UI", 10, "bold"),
        command=lambda: (canvas.unbind_all("<MouseWheel>"), popup.destroy()),
        cursor="hand2",
    )
    close_btn.pack(anchor="e", pady=(14, 0))

    def _on_close():
        canvas.unbind_all("<MouseWheel>")
        popup.destroy()

    popup.protocol("WM_DELETE_WINDOW", _on_close)

    center_window(popup, 860, 560, parent=root)
    popup.grab_set()
    popup.focus_set()

def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    apply_app_icon(root)
    root.minsize(750, 480)

    apply_style(root)
    configure_extra_styles(root)
    center_window(root, 750, 480)
    root.configure(bg=COLORS["bg"])

    top = ttk.Frame(root, style="Topbar.TFrame")
    top.pack(fill="x")
    top.grid_columnconfigure(0, weight=1)

    ttk.Label(
        top,
        text="INDEX MAJEUR",
        style="TopbarTitle.TLabel",
        anchor="center",
    ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))

    tk.Label(
        top,
        text="Reprendre la main sur les noms de fichier.",
        bg="#2E3440",
        fg="#FFFFFF",
        font=("Segoe UI", 10),
        anchor="center",
        justify="center",
    ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

    body = tk.Frame(root, bg=COLORS["bg"], padx=20, pady=18)
    body.pack(fill="both", expand=True)

    grid = tk.Frame(body, bg=COLORS["bg"])
    grid.pack(anchor="center")

    card_w = 350
    for col in (0, 1):
        grid.grid_columnconfigure(col, minsize=card_w)

    for i, tool in enumerate(TOOLS):
        r = i // 2
        c = i % 2
        card = build_card(grid, tool)
        card.grid(row=r, column=c, sticky="nsew", padx=12, pady=12)

    # --- WORKFLOW (entre les cartes et le footer) ---

    workflow = tk.Frame(root, bg=COLORS["bg"])
    workflow.pack(fill="x", padx=16, pady=(0, 0))

    tk.Label(
        workflow,
        text="Trier → Nommer → Structurer → Exploiter",
        bg=COLORS["bg"],
        fg="#2E3440",
        font=("Segoe UI", 10),
        anchor="w",
    ).pack(fill="x", padx=16, pady=(0, 0))

    tk.Label(
        workflow,
        text="TWINS → PHOTO → DOCUMENTATION → INDEX DOCUMENTATION",
        bg=COLORS["bg"],
        fg=COLORS["footer_text"],
        font=("Segoe UI", 9),
        anchor="w",
    ).pack(fill="x", padx=16, pady=(0, 0))

    footer = tk.Frame(root, bg=COLORS["bg"], padx=16, pady=8)
    footer.pack(fill="x")

    ttk.Separator(footer).pack(fill="x", pady=(0, 8))

    foot_row = tk.Frame(footer, bg=COLORS["bg"])
    foot_row.pack(fill="x")

    tk.Label(
        foot_row,
        text="Suite d’outils pour organiser la documentation visuelle — Eigrutel BD Academy 2026",
        bg=COLORS["bg"],
        fg=COLORS["footer_text"],
        font=("Segoe UI", 9),
    ).pack(side="left")

    help_wrap = tk.Frame(foot_row, bg=COLORS["bg"])
    help_wrap.pack(side="right")

    plus_btn = ttk.Button(
        help_wrap,
        text="+",
        width=3,
        style="Plus.TButton",
        command=lambda: open_search_help(root),
    )
    plus_btn.pack(side="right")
        
    

    #tk.Label(
     #   help_wrap,
      #  text="En savoir plus",
       # bg=COLORS["bg"],
        #fg="#2E3440",
 #       font=("Segoe UI", 9, ),
#    ).pack(side="right", padx=(0, 8))

    root.mainloop()


if __name__ == "__main__":
    main()
