"""Écran principal : barre latérale rétractable (menu principal) + tableau de bord sur le MÊME écran.

- À gauche : logo GESTSCO, puis « Tableau de bord » et la liste des modules ouverts au compte (« Menu principal »).
  Le chevron en haut de la barre la replie en une colonne de pictogrammes (et la rouvre) ; le chevron de « Menu
  principal » plie / déplie la liste des modules.
- À droite : le tableau de bord (cartes, camembert, courbe) avec son propre chevron plier / déplier.
Un clic sur un module l'ouvre ; le bouton « Menu principal » du module ramène ici.
"""
import tkinter as tk

import config
import theme
from modules import MODULES
from ecrans_tableau import PanneauTableau
from theme import (BLANC, BLEU_ACTIF, BORDURE, FOND_ECRAN, GRIS, LATERAL, LATERAL_SURVOL, NUIT, TEXTE_LATERAL,
                   Chevron, ZoneAdaptative, charger_gestisc, charger_icone, creer_bouton, police, px)

LARGEUR_OUVERTE, LARGEUR_REPLIEE = 270, 68


class EcranPrincipal(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=FOND_ECRAN)
        self.app = app
        s = app.session
        self._images = []
        self._lignes = []                      # (ligne, icône, texte, titre) de chaque entrée du menu
        self._infobulle = None
        self._anim = None
        self.replie = bool(getattr(app, "lateral_replie", False))
        self.modules_visibles = True

        self.lateral = tk.Frame(self, bg=LATERAL)
        self.lateral.pack(side="left", fill="y")
        self.lateral.pack_propagate(False)
        self.lateral.configure(width=px(LARGEUR_REPLIEE if self.replie else LARGEUR_OUVERTE))
        droite = tk.Frame(self, bg=FOND_ECRAN)
        droite.pack(side="left", fill="both", expand=True)

        self._construire_lateral()
        self._construire_barre(droite, s)

        zone = ZoneAdaptative(droite)
        zone.canvas.configure(bg=FOND_ECRAN)
        zone.interieur.configure(bg=FOND_ECRAN)
        zone.pack(fill="both", expand=True)
        contenu = tk.Frame(zone.interieur, bg=FOND_ECRAN)
        contenu.pack(fill="both", expand=True, padx=px(28), pady=px(22))
        if app.tableau_autorise():
            PanneauTableau(contenu, app).pack(fill="both", expand=True)
        else:
            self._accueil_sans_tableau(contenu, s)
        self._appliquer_etat()

    # ------------------------------------------------------------------ barre latérale
    def _construire_lateral(self):
        app = self.app
        entete = tk.Frame(self.lateral, bg=LATERAL)
        entete.pack(fill="x", padx=px(12), pady=(px(16), px(8)))
        self._logo = charger_gestisc(40)
        self.logo = tk.Label(entete, image=self._logo, bg=LATERAL, bd=0, cursor="hand2")
        self.logo.pack(side="left")
        self.bloc_nom = tk.Frame(entete, bg=LATERAL)
        self.bloc_nom.pack(side="left", padx=(px(10), 0))
        tk.Label(self.bloc_nom, text=config.SIGLE_APP, font=police(15, gras=True, titre=True), fg=BLANC,
                 bg=LATERAL).pack(anchor="w")
        tk.Label(self.bloc_nom, text=config.NOM_ECOLE.title(),
                 font=police(8), fg=TEXTE_LATERAL, bg=LATERAL, wraplength=px(130), justify="left").pack(anchor="w")
        self.chev_lateral = Chevron(entete, "gauche", BLANC, LATERAL, self.basculer_lateral, survol=LATERAL_SURVOL)
        self.chev_lateral.pack(side="right")
        self.entete = entete
        tk.Frame(self.lateral, bg=LATERAL_SURVOL, height=1).pack(fill="x", padx=px(12), pady=(px(6), px(10)))

        # --- Tableau de bord (actif : on est dessus)
        if app.tableau_autorise():
            self._entree(self.lateral, "Tableau de bord", "ico_tableau", None, actif=True)

        # --- Menu principal : titre de section + chevron, puis les modules
        self.section = tk.Frame(self.lateral, bg=LATERAL)
        self.section.pack(fill="x", padx=px(18), pady=(px(14), px(4)))
        self.titre_section = tk.Label(self.section, text="MENU PRINCIPAL", font=police(9, gras=True),
                                      fg=TEXTE_LATERAL, bg=LATERAL, cursor="hand2")
        self.titre_section.pack(side="left")
        self.chev_section = Chevron(self.section, "bas", TEXTE_LATERAL, LATERAL, self.basculer_modules, taille=18,
                                    survol=LATERAL_SURVOL)
        self.chev_section.pack(side="right")
        self.titre_section.bind("<Button-1>", lambda _e: self.basculer_modules())
        self.liste_modules = tk.Frame(self.lateral, bg=LATERAL)
        self.liste_modules.pack(fill="x")
        ouverts = [m for m in MODULES if m[3](app.conn, app.session)]
        for cle, titre, _d, _r in ouverts:
            self._entree(self.liste_modules, titre, f"ico_{cle}", cle)
        if not ouverts:
            tk.Label(self.liste_modules, text="Aucun module ouvert", font=police(9), fg=TEXTE_LATERAL, bg=LATERAL
                     ).pack(anchor="w", padx=px(18))

        # --- bas : déconnexion
        pied = self.pied = tk.Frame(self.lateral, bg=LATERAL)
        pied.pack(side="bottom", fill="x", pady=(0, px(14)))
        tk.Frame(pied, bg=LATERAL_SURVOL, height=1).pack(fill="x", padx=px(12), pady=(0, px(8)))
        self._entree(pied, "Se déconnecter", "ico_sortie", None, commande=app.deconnexion)

    def _entree(self, parent, titre, icone, cle, actif=False, commande=None):
        fond = BLEU_ACTIF if actif else LATERAL
        ligne = tk.Frame(parent, bg=fond, cursor="hand2" if not actif else "")
        ligne.pack(fill="x", padx=px(10), pady=1)
        image = charger_icone(icone)
        self._images.append(image)
        ico = tk.Label(ligne, image=image, bg=fond, bd=0)
        ico.pack(side="left", padx=(px(12), px(12)), pady=px(8))
        texte = tk.Label(ligne, text=titre, font=police(11, gras=actif), fg=BLANC if actif else TEXTE_LATERAL, bg=fond,
                         anchor="w", justify="left", wraplength=px(LARGEUR_OUVERTE - 110))
        texte.pack(side="left", fill="x", expand=True)
        if commande is None and cle is not None:
            commande = lambda k=cle: self.app.ouvrir_module(k)       # noqa: E731
        for w in (ligne, ico, texte):
            if commande:
                w.bind("<Button-1>", lambda _e, c=commande: c())
            if not actif:
                w.bind("<Enter>", lambda _e, l=ligne, i=ico, t=texte, ti=titre: self._survol(l, i, t, True, ti))
                w.bind("<Leave>", lambda _e, l=ligne, i=ico, t=texte, ti=titre: self._survol(l, i, t, False, ti))
        self._lignes.append((ligne, ico, texte, titre))
        return ligne

    def _survol(self, ligne, ico, texte, dessus, titre):
        fond = LATERAL_SURVOL if dessus else LATERAL
        for w in (ligne, ico, texte):
            w.config(bg=fond)
        texte.config(fg=BLANC if dessus else TEXTE_LATERAL)
        if self.replie and dessus:
            self._montrer_infobulle(ligne, titre)
        else:
            self._cacher_infobulle()

    def _montrer_infobulle(self, ligne, titre):
        self._cacher_infobulle()
        bulle = tk.Toplevel(self)
        bulle.wm_overrideredirect(True)
        tk.Label(bulle, text=titre, font=police(10, gras=True), fg=BLANC, bg=NUIT, padx=px(10), pady=px(5)).pack()
        bulle.wm_geometry(f"+{ligne.winfo_rootx() + ligne.winfo_width() + px(6)}+{ligne.winfo_rooty() + px(4)}")
        self._infobulle = bulle

    def _cacher_infobulle(self):
        if self._infobulle is not None:
            self._infobulle.destroy()
            self._infobulle = None

    # ------------------------------------------------------------------ plier / déplier
    def basculer_lateral(self):
        self.replie = not self.replie
        self.app.lateral_replie = self.replie
        self._cacher_infobulle()
        self._appliquer_etat(anime=True)

    def basculer_modules(self):
        self.modules_visibles = not self.modules_visibles
        self._appliquer_etat()

    def _appliquer_etat(self, anime=False):
        """Affiche ou masque les textes selon l'état replié / ouvert ; la largeur est animée."""
        cible = px(LARGEUR_REPLIEE if self.replie else LARGEUR_OUVERTE)
        if self.replie:                                         # on masque les textes avant de rétrécir
            self._basculer_textes(False)
        if anime:
            self._animer(cible)
        else:
            self.lateral.configure(width=cible)
            self._basculer_textes(not self.replie)
        self.chev_lateral.dessiner("droite" if self.replie else "gauche")
        self.chev_section.dessiner("bas" if self.modules_visibles else "haut")
        self._placer_liste()

    def _placer_liste(self):
        """La liste des modules est visible si elle n'est pas pliée, ou si la barre est repliée (pictogrammes seuls)."""
        self.liste_modules.pack_forget()
        if self.modules_visibles or self.replie:
            if self.section.winfo_manager():
                self.liste_modules.pack(fill="x", after=self.section)
            else:
                self.liste_modules.pack(fill="x", before=self.pied)

    def _basculer_textes(self, visible):
        for _ligne, _ico, texte, _t in self._lignes:
            if visible:
                texte.pack(side="left", fill="x", expand=True)
            else:
                texte.pack_forget()
        if visible:
            self.chev_lateral.pack_forget()
            self.chev_lateral.pack(side="right")
            self.bloc_nom.pack(side="left", padx=(px(10), 0), before=self.chev_lateral)
            self.section.pack(fill="x", padx=px(18), pady=(px(14), px(4)),
                              **({"before": self.liste_modules} if self.liste_modules.winfo_manager()
                                 else {"before": self.pied}))
            self._placer_liste()
        else:
            self.bloc_nom.pack_forget()
            self.section.pack_forget()
            self.chev_lateral.pack_forget()                        # le chevron de la barre du haut rouvre la barre
        self.entete.update_idletasks()

    def _animer(self, cible):
        if self._anim:
            self.after_cancel(self._anim)
        actuelle = self.lateral.winfo_width()
        if abs(cible - actuelle) <= px(6):
            self.lateral.configure(width=cible)
            self._anim = None
            if not self.replie:
                self._basculer_textes(True)
            return
        self.lateral.configure(width=int(actuelle + (cible - actuelle) * 0.4))
        self._anim = self.after(14, lambda: self._animer(cible))

    def destroy(self):
        self._cacher_infobulle()
        if self._anim:
            self.after_cancel(self._anim)
        super().destroy()

    # ------------------------------------------------------------------ barre du haut
    def _construire_barre(self, parent, s):
        barre = tk.Frame(parent, bg=BLANC)
        barre.pack(fill="x")
        tk.Frame(parent, bg=BORDURE, height=1).pack(fill="x")
        Chevron(barre, "gauche", NUIT, BLANC, self.basculer_lateral, taille=26, survol=FOND_ECRAN
                ).pack(side="left", padx=(px(14), px(8)), pady=px(14))
        tk.Label(barre, text=config.NOM_APP, font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC,
                 wraplength=px(620), justify="left").pack(side="left", pady=px(8))
        creer_bouton(barre, "Se déconnecter", self.app.deconnexion, style="secondaire", grand=False
                     ).pack(side="right", padx=px(16))
        creer_bouton(barre, "Mon mot de passe", self.app.afficher_changement_mdp, style="secondaire", grand=False
                     ).pack(side="right", padx=(0, px(8)))
        tk.Label(barre, text=f"{s.nom_complet}  •  {s.libelle_role}", font=police(10), fg=GRIS, bg=BLANC
                 ).pack(side="right", padx=px(8))

    def _accueil_sans_tableau(self, parent, s):
        carte = theme.carte(parent, padx=px(28), pady=px(24))
        carte.pack(anchor="nw")
        tk.Label(carte, text="Menu principal", font=police(22, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        tk.Label(carte, text=f"Bienvenue, {s.nom_complet}", font=police(12), fg=GRIS, bg=BLANC
                 ).pack(anchor="w", pady=(px(2), px(12)))
        tk.Label(carte, text="Choisissez un module dans la barre latérale pour commencer.\n"
                             "Le tableau de bord n'est pas ouvert à votre compte (droit « Lecture » à demander "
                             "à l'Administrateur).", font=police(11), fg=NUIT, bg=BLANC, justify="left").pack(anchor="w")
