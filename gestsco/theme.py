"""Thème : bleu de nuit et blanc. Tailles adaptées à la résolution de l'écran."""
import tkinter as tk
from tkinter import ttk

import config

NUIT = "#0C1B3F"            # bleu de nuit
NUIT_CLAIR = "#1D3A7A"      # survol / sélection
BLEU = "#1565C0"            # boutons des modules du menu principal
BLEU_CIEL = "#87CEEB"       # bleu ciel : survol des boutons des modules
BLANC = "#FFFFFF"
FOND_CLAIR = "#EEF2FA"
BORDURE = "#C5CEE0"
GRIS = "#5A6785"
BLEU_PALE = "#B7C7EE"
ROUGE = "#B3261E"
VERT = "#1E7B34"
ORANGE = "#B45309"

# --- couleurs du modèle de tableau de bord : barre latérale bleu marine, élément actif bleu vif, cartes blanches
LATERAL = "#0A1E45"           # fond de la barre latérale
LATERAL_SURVOL = "#183268"    # survol dans la barre latérale
BLEU_ACTIF = "#1D4ED8"        # entrée active du menu
TEXTE_LATERAL = "#C5D0EA"     # texte des entrées non actives
FOND_ECRAN = "#F4F6FB"        # fond de la zone du tableau de bord
ACCENT_BLEU = "#2563EB"
ACCENT_VERT = "#16A34A"
ACCENT_VIOLET = "#7C3AED"
ACCENT_ORANGE = "#F59E0B"
ACCENT_ROUGE = "#EF4444"

POLICE_TITRE = "Georgia"
POLICE_TEXTE = "Segoe UI"
TAILLES_LOGO = (48, 96, 160, 250, 340)
TAILLES_GESTSCO = (32, 48, 64, 96, 128, 256)

_facteur = 1.0       # agrandissement des polices selon la hauteur de l'écran
_echelle_px = 1.0    # agrandissement des espacements (écrans haute densité inclus)


def initialiser(racine):
    """À appeler une fois, juste après la création de la fenêtre principale."""
    global _facteur, _echelle_px
    echelle_dpi = racine.winfo_fpixels("1i") / 96
    hauteur_logique = racine.winfo_screenheight() / echelle_dpi
    _facteur = max(0.9, min(1.3, hauteur_logique / 900))
    _echelle_px = echelle_dpi * _facteur

    style = ttk.Style(racine)
    style.theme_use("clam")
    style.configure("Treeview", background=BLANC, fieldbackground=BLANC, foreground=NUIT,
                    rowheight=px(28), font=police(10), bordercolor=BORDURE, borderwidth=1)
    style.configure("Treeview.Heading", background=NUIT, foreground=BLANC, font=police(10, gras=True),
                    relief="flat", padding=px(6))
    style.map("Treeview", background=[("selected", NUIT_CLAIR)], foreground=[("selected", BLANC)])
    style.map("Treeview.Heading", background=[("active", NUIT_CLAIR)])
    style.configure("TCombobox", fieldbackground=BLANC, background=FOND_CLAIR, foreground=NUIT,
                    arrowcolor=NUIT, bordercolor=BORDURE, padding=px(5))
    style.map("TCombobox", fieldbackground=[("readonly", BLANC)], foreground=[("readonly", NUIT)])
    racine.option_add("*TCombobox*Listbox.font", police(11))
    racine.option_add("*TCombobox*Listbox.selectBackground", NUIT_CLAIR)


def police(taille, gras=False, titre=False, italique=False):
    famille = POLICE_TITRE if titre else POLICE_TEXTE
    styles = " ".join(s for s, actif in (("bold", gras), ("italic", italique)) if actif)
    taille = max(8, round(taille * _facteur))
    return (famille, taille, styles) if styles else (famille, taille)


def px(n) -> int:
    return int(round(n * _echelle_px))


def charger_logo(largeur) -> tk.PhotoImage:
    """Choisit parmi les fichiers du logo celui qui se rapproche le plus de la largeur voulue."""
    cible = largeur * _echelle_px
    taille = min(TAILLES_LOGO, key=lambda t: abs(t - cible))
    return tk.PhotoImage(file=str(config.DOSSIER_ASSETS / f"logo_{taille}.png"))


def charger_gestisc(largeur) -> tk.PhotoImage:
    """Logo GESTSCO (engrenage bleu et histogramme : la gestion), à la taille disponible la plus proche."""
    cible = largeur * _echelle_px
    taille = min(TAILLES_GESTSCO, key=lambda t: abs(t - cible))
    return tk.PhotoImage(file=str(config.DOSSIER_ASSETS / f"gestisc_{taille}.png"))


def charger_icone(nom) -> tk.PhotoImage:
    """Pictogramme blanc 40 px (assets/<nom>.png), réduit de moitié sur un écran standard."""
    image = tk.PhotoImage(file=str(config.DOSSIER_ASSETS / f"{nom}.png"))
    return image.subsample(2, 2) if px(22) <= 30 else image


class Chevron(tk.Canvas):
    """Petit bouton-chevron cliquable. sens : « gauche », « droite », « haut » ou « bas » ; `dessiner(sens)` le change."""

    def __init__(self, parent, sens, couleur, fond, commande, taille=24, survol=None):
        t = px(taille)
        super().__init__(parent, width=t, height=t, bg=fond, highlightthickness=0, bd=0, cursor="hand2")
        self._couleur, self._fond, self._survol, self._t = couleur, fond, survol or fond, t
        self.sens = sens
        self.bind("<Button-1>", lambda _e: commande())
        self.bind("<Enter>", lambda _e: self.config(bg=self._survol))
        self.bind("<Leave>", lambda _e: self.config(bg=self._fond))
        self.dessiner(sens)

    def dessiner(self, sens):
        self.sens = sens
        self.delete("all")
        m, c = self._t * 0.34, self._t / 2
        pts = {"gauche": (c + m / 2, c - m, c - m / 2, c, c + m / 2, c + m),
               "droite": (c - m / 2, c - m, c + m / 2, c, c - m / 2, c + m),
               "haut": (c - m, c + m / 2, c, c - m / 2, c + m, c + m / 2),
               "bas": (c - m, c - m / 2, c, c + m / 2, c + m, c - m / 2)}[sens]
        self.create_line(*pts, fill=self._couleur, width=max(2, px(2)), capstyle="round", joinstyle="round")


# ------------------------------------------------------------------ composants
_STYLES_BOUTON = {                 # fond, texte, survol
    "principal": (NUIT, BLANC, NUIT_CLAIR),
    "secondaire": (FOND_CLAIR, NUIT, BORDURE),
    "danger": ("#FDECEA", ROUGE, "#F8CFCB"),
}


def creer_bouton(parent, texte, commande, style="principal", grand=True):
    fond, couleur, survol = _STYLES_BOUTON[style]
    bouton = tk.Button(
        parent, text=texte, command=commande, bg=fond, fg=couleur, activebackground=survol,
        activeforeground=couleur, disabledforeground="#6E7A98", font=police(12 if grand else 10, gras=True),
        relief="flat", bd=0, highlightthickness=0, cursor="hand2",
        padx=px(30 if grand else 14), pady=px(9 if grand else 6))
    bouton.fond_normal = fond
    bouton.bind("<Enter>", lambda _e: bouton.config(bg=survol) if str(bouton["state"]) == "normal" else None)
    bouton.bind("<Leave>", lambda _e: bouton.config(bg=bouton.fond_normal) if str(bouton["state"]) == "normal" else None)
    return bouton


def definir_actif(bouton, actif: bool):
    bouton.config(state="normal" if actif else "disabled", bg=bouton.fond_normal if actif else "#DDE3F0",
                  cursor="hand2" if actif else "arrow")


def creer_champ(parent, variable, masque=False, lecture_seule=False, largeur=28):
    return tk.Entry(
        parent, textvariable=variable, show="●" if masque else "", font=police(12), relief="flat", bd=0,
        bg=FOND_CLAIR if lecture_seule else BLANC, readonlybackground=FOND_CLAIR, fg=NUIT,
        state="readonly" if lecture_seule else "normal", insertbackground=NUIT, width=largeur,
        highlightthickness=1, highlightbackground=BORDURE, highlightcolor=NUIT)


def carte(parent, **options):
    return tk.Frame(parent, bg=BLANC, highlightbackground=BORDURE, highlightthickness=1, **options)


def centrer_fenetre(fenetre, largeur, hauteur):
    x = max(0, (fenetre.winfo_screenwidth() - largeur) // 2)
    y = max(0, (fenetre.winfo_screenheight() - hauteur) // 3)
    fenetre.geometry(f"{largeur}x{hauteur}+{x}+{y}")


def barre_haute(parent, titre, clair=False):
    """Barre commune au menu et aux modules (logo + titre). `clair` : barre blanche (menu principal)."""
    fond, texte = (BLANC, NUIT) if clair else (NUIT, BLANC)
    barre = tk.Frame(parent, bg=fond)
    barre.pack(fill="x")
    barre.logo = charger_logo(40)
    tk.Label(barre, image=barre.logo, bg=fond, bd=0).pack(side="left", padx=(px(16), px(10)), pady=px(6))
    tk.Label(barre, text=titre, font=police(15, gras=True, titre=True), fg=texte, bg=fond).pack(side="left")
    if clair:
        tk.Frame(parent, bg=BLEU, height=px(3)).pack(fill="x")
    return barre


def _mettre_en_evidence(bouton):
    """Bouton de l'écran affiché : bleu ciel, pour qu'on voie où l'on est."""
    bouton.fond_normal = BLEU_CIEL
    bouton.config(bg=BLEU_CIEL, activebackground=BLEU_CIEL)


def bouton_menu(parent, app, grand=True):
    """« Menu principal » si le compte a le choix entre plusieurs modules ; sinon (un seul module, ouvert
    directement à la connexion) le menu n'a pas de sens : le bouton devient « Se déconnecter »."""
    if app.menu_utile():
        return creer_bouton(parent, "Menu principal", app.afficher_menu, style="secondaire", grand=grand)
    return creer_bouton(parent, "Se déconnecter", app.deconnexion, style="secondaire", grand=grand)


def actions_barre_module(barre, app):
    """Boutons à droite de la barre bleue d'un module : « Menu principal » ou, si le compte n'a pas de menu (un seul
    module), « Mon mot de passe » puis « Se déconnecter » (sinon il ne pourrait plus changer son mot de passe).
    De gauche à droite : Mon mot de passe, Se déconnecter."""
    bouton_menu(barre, app, grand=False).pack(side="right", padx=px(16))
    if not app.menu_utile():
        creer_bouton(barre, "Mon mot de passe", app.afficher_changement_mdp, style="secondaire",
                     grand=False).pack(side="right", padx=(0, px(8)))


def boutons_navigation(barre, app, courant):
    """Boutons à droite de la barre bleue du menu principal (courant = "menu") et du tableau de bord
    (courant = "tableau"). De droite à gauche : [Se déconnecter] [Mon mot de passe] puis, en bleu ciel, le bouton de
    retour : « Retour au menu principal » sur le tableau de bord, « Retour au tableau de bord » sur le menu principal
    (seulement pour un compte qui a le droit de voir le tableau de bord)."""
    creer_bouton(barre, "Se déconnecter", app.deconnexion, style="secondaire", grand=False
                 ).pack(side="right", padx=px(16))
    creer_bouton(barre, "Mon mot de passe", app.afficher_changement_mdp, style="secondaire",
                 grand=False).pack(side="right", padx=(0, px(8)))
    if courant == "tableau":
        retour = creer_bouton(barre, "Retour au menu principal", app.afficher_menu, style="secondaire", grand=False)
    elif courant == "menu" and app.tableau_autorise():
        retour = creer_bouton(barre, "Retour au tableau de bord", app.afficher_tableau, style="secondaire",
                              grand=False)
    else:
        return
    retour.pack(side="right", padx=(0, px(8)))
    _mettre_en_evidence(retour)


# ------------------------------------------------------------------ contenu qui s'adapte à l'écran
class ZoneAdaptative(tk.Frame):
    """Contenu d'un module. Sur un grand écran il remplit toute la place ; sur un petit écran (portable, écran à
    forte mise à l'échelle) rien n'est coupé : des barres de défilement apparaissent seulement quand il le faut
    (molette de la souris incluse). Les panneaux se placent dans `self.interieur`."""

    def __init__(self, parent):
        super().__init__(parent, bg=BLANC)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BLANC, highlightthickness=0, bd=0)
        self.barre_v = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.barre_h = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.barre_v.set, xscrollcommand=self.barre_h.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.interieur = tk.Frame(self.canvas, bg=BLANC)
        self._fenetre = self.canvas.create_window((0, 0), window=self.interieur, anchor="nw")
        self.canvas.bind("<Configure>", self._ajuster)
        self.interieur.bind("<Configure>", self._ajuster)
        self.bind("<Enter>", self._entree)
        self.bind("<Leave>", self._sortie)

    def _ajuster(self, _evenement=None):
        largeur, hauteur = self.canvas.winfo_width(), self.canvas.winfo_height()
        besoin_l, besoin_h = self.interieur.winfo_reqwidth(), self.interieur.winfo_reqheight()
        total_l, total_h = max(largeur, besoin_l), max(hauteur, besoin_h)
        self.canvas.itemconfigure(self._fenetre, width=total_l, height=total_h)
        self.canvas.configure(scrollregion=(0, 0, total_l, total_h))
        if total_h > hauteur + 1:
            self.barre_v.grid(row=0, column=1, sticky="ns")
        else:
            self.barre_v.grid_remove()
        if total_l > largeur + 1:
            self.barre_h.grid(row=1, column=0, sticky="ew")
        else:
            self.barre_h.grid_remove()

    def _entree(self, _evenement=None):
        self.canvas.bind_all("<MouseWheel>", self._molette)
        self.canvas.bind_all("<Button-4>", self._molette)
        self.canvas.bind_all("<Button-5>", self._molette)

    def _sortie(self, _evenement=None):
        sous_la_souris = self.winfo_containing(*self.winfo_pointerxy())
        if sous_la_souris is None or not str(sous_la_souris).startswith(str(self)):
            for evenement in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(evenement)

    def _molette(self, evenement):
        if evenement.widget.winfo_class() in ("Treeview", "Listbox", "TCombobox", "Text", "Canvas"):
            return                                   # une liste, un tableau ou un autre défilement ont leur propre molette
        if self.interieur.winfo_reqheight() <= self.canvas.winfo_height():
            return
        if getattr(evenement, "num", None) == 4:
            pas = -1
        elif getattr(evenement, "num", None) == 5:
            pas = 1
        else:
            pas = -1 if evenement.delta > 0 else 1
        self.canvas.yview_scroll(pas * 2, "units")
