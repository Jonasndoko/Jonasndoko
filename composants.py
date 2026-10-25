"""Éléments d'interface partagés par les modules Travaux techniques et Gestionnaire d'accès :
fenêtres de dialogue, module à onglets, formulaire de compte."""
import tkinter as tk
from tkinter import ttk

import acces
import config
from theme import (BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ROUGE, VERT, barre_haute,
                   actions_barre_module, centrer_fenetre, creer_bouton, creer_champ, police, px, ZoneAdaptative)


def case_a_cocher(parent, texte, variable, commande=None):
    return tk.Checkbutton(parent, text=texte, variable=variable, command=commande, font=police(10), fg=NUIT,
                          bg=BLANC, activebackground=BLANC, selectcolor=BLANC, bd=0, highlightthickness=0,
                          cursor="hand2")


def entete(parent, titre, texte):
    tk.Label(parent, text=titre, font=police(16, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w")
    tk.Label(parent, text=texte, font=police(10), fg=GRIS, bg=BLANC, justify="left", anchor="w",
             wraplength=px(1000)).pack(anchor="w", pady=(px(2), px(10)), fill="x")


# ================================================================== module à onglets
class ModuleOnglets(tk.Frame):
    """Barre haute + onglets. Les sous-classes donnent TITRE et ONGLETS = ((clé, texte, classe de panneau), ...).
    Un panneau reçoit (zone, module) et peut définir au_affichage()."""
    TITRE = ""
    ONGLETS = ()

    def __init__(self, app, onglet=None):
        super().__init__(app, bg=BLANC)
        self.app = app
        barre = barre_haute(self, self.TITRE)
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        navigation = tk.Frame(self, bg=FOND_CLAIR)
        navigation.pack(fill="x")
        self.boutons = {}
        for i, (cle, texte, _classe) in enumerate(self.ONGLETS):
            navigation.grid_columnconfigure(i, weight=1, uniform="onglet")
            b = tk.Button(navigation, text=texte, command=lambda c=cle: self.afficher_onglet(c), relief="flat", bd=0,
                          highlightthickness=0, font=police(11, gras=True), padx=px(12), pady=px(12), cursor="hand2",
                          wraplength=px(230))
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons[cle] = b
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        self.panneaux = {cle: classe(self.zone, self) for cle, _texte, classe in self.ONGLETS}
        self.courant = None
        self.afficher_onglet(onglet or self.ONGLETS[0][0])

    def afficher_onglet(self, cle):
        for nom, panneau in self.panneaux.items():
            panneau.pack_forget()
            actif = nom == cle
            self.boutons[nom].config(bg=NUIT if actif else FOND_CLAIR, fg=BLANC if actif else NUIT,
                                     activebackground=NUIT_CLAIR if actif else BORDURE,
                                     activeforeground=BLANC if actif else NUIT)
        self.courant = self.panneaux[cle]
        self.courant.pack(fill="both", expand=True)
        if hasattr(self.courant, "au_affichage"):
            self.courant.au_affichage()


# ================================================================== fenêtres de dialogue
class Fenetre(tk.Toplevel):
    """Petite fenêtre modale : on ne peut pas toucher à la fenêtre principale tant qu'elle est ouverte."""

    def __init__(self, parent, titre, largeur=520, hauteur=420):
        super().__init__(parent)
        self.title(titre)
        self.configure(bg=BLANC)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        centrer_fenetre(self, px(largeur), px(hauteur))
        self.corps = tk.Frame(self, bg=BLANC, padx=px(24), pady=px(20))
        self.corps.pack(fill="both", expand=True)
        self.resultat = None
        self.variables = []               # Tkinter efface une variable dont plus personne ne garde la référence
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass

    def attendre(self):
        self.wait_window(self)
        return self.resultat

    def variable(self, valeur=""):
        v = tk.StringVar(value=valeur)
        self.variables.append(v)
        return v

    def champ(self, libelle, variable, lecture_seule=False, masque=False):
        tk.Label(self.corps, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        entree = creer_champ(self.corps, variable, masque, lecture_seule, largeur=34)
        entree.pack(fill="x", ipady=px(5), pady=(px(3), px(10)))
        return entree


class DialogueCompte(Fenetre):
    """Création (compte=None) ou modification d'un compte. `action(valeurs)` fait le travail et peut lever
    ErreurAcces : l'erreur s'affiche dans la fenêtre, qui reste ouverte."""

    def __init__(self, parent, session, action, compte=None, roles=None):
        creation = compte is None
        roles = roles or dict(config.LIBELLE_ROLES)
        super().__init__(parent, "Nouveau compte" if creation else "Modifier le compte", 520, 520)
        self.action, self.creation = action, creation
        self.var_nom = self.variable("" if creation else compte["NOM_COMPLET"])
        self.var_login = self.variable("" if creation else compte["LOGIN"])
        self.libelle_vers_code = {libelle: code for code, libelle in roles.items()}
        premier = next(iter(roles))
        self.var_poste = self.variable(roles[premier if creation else compte["ROLE"]] if (creation or compte["ROLE"] in roles)
                                       else compte["ROLE"])
        self.var_actif = tk.BooleanVar(value=True if creation else bool(compte["ACTIF"]))
        self.variables.append(self.var_actif)
        soi_meme = (not creation) and compte["ID_USER"] == session.id_user

        nom = self.champ("Nom complet", self.var_nom)
        self.champ("Identifiant (pour se connecter)", self.var_login, lecture_seule=not creation)
        tk.Label(self.corps, text="Rôle (poste)", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        self.liste = ttk.Combobox(self.corps, textvariable=self.var_poste, state="disabled" if soi_meme else "readonly",
                                  values=list(roles.values()), font=police(11), width=32)
        self.liste.pack(fill="x", pady=(px(3), px(8)))
        tk.Label(self.corps, font=police(9), fg=GRIS, bg=BLANC, justify="left", wraplength=px(460), text=(
            "Le compte reçoit les droits de base de son rôle ; vous pourrez les ajuster dans « Autorisations »."
            if creation else "Changer de rôle remet les autorisations aux droits de base du nouveau rôle.")
                 ).pack(anchor="w")
        if not creation:
            c = case_a_cocher(self.corps, "Compte actif (décochez pour interdire la connexion)", self.var_actif)
            c.pack(anchor="w", pady=(px(10), 0))
            if soi_meme:
                c.config(state="disabled")
        self.lbl_erreur = tk.Label(self.corps, text="", font=police(10), fg=ROUGE, bg=BLANC, wraplength=px(460),
                                   justify="left", anchor="w")
        self.lbl_erreur.pack(fill="x", pady=(px(8), px(6)))
        bas = tk.Frame(self.corps, bg=BLANC)
        bas.pack(fill="x", side="bottom")
        creer_bouton(bas, "Créer le compte" if creation else "Enregistrer", self._valider, grand=False).pack(side="left")
        creer_bouton(bas, "Annuler", self.destroy, style="secondaire", grand=False).pack(side="left", padx=px(10))
        self.bind("<Return>", lambda _e: self._valider())
        nom.focus_set()

    def _valider(self):
        valeurs = {"nom": self.var_nom.get(), "login": self.var_login.get(),
                   "poste": self.libelle_vers_code.get(self.var_poste.get()), "actif": self.var_actif.get()}
        try:
            self.resultat = self.action(valeurs) or True
        except (acces.ErreurAcces, PermissionError) as erreur:
            self.lbl_erreur.config(text=str(erreur))
            return
        self.destroy()


def afficher_mdp_provisoire(parent, login, mdp, titre="Mot de passe provisoire"):
    fen = Fenetre(parent, titre, 520, 360)
    tk.Label(fen.corps, text=titre, font=police(15, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w")
    tk.Label(fen.corps, text="Communiquez ces informations à l'utilisateur. Le mot de passe ne sera PLUS JAMAIS affiché ; "
                             "il devra en choisir un personnel dès sa première connexion.",
             font=police(10), fg=GRIS, bg=BLANC, justify="left", wraplength=px(470)).pack(anchor="w", pady=(px(4), px(14)))
    for libelle, valeur in (("Identifiant", login), ("Mot de passe provisoire", mdp)):
        tk.Label(fen.corps, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        entree = creer_champ(fen.corps, fen.variable(valeur), lecture_seule=True, largeur=34)
        entree.pack(fill="x", ipady=px(5), pady=(px(3), px(10)))
    etat = tk.Label(fen.corps, text="", font=police(9), fg=VERT, bg=BLANC)

    def copier():
        fen.clipboard_clear()
        fen.clipboard_append(mdp)
        etat.config(text="Mot de passe copié dans le presse-papiers.")

    bas = tk.Frame(fen.corps, bg=BLANC)
    bas.pack(fill="x", side="bottom")
    creer_bouton(bas, "Copier le mot de passe", copier, style="secondaire", grand=False).pack(side="left")
    creer_bouton(bas, "J'ai noté, fermer", fen.destroy, grand=False).pack(side="left", padx=px(10))
    etat.pack(anchor="w")
    fen.attendre()


def confirmer_par_saisie(parent, titre, message, mot) -> bool:
    """Confirmation forte : il faut taper `mot` en toutes lettres."""
    fen = Fenetre(parent, titre, 560, 400)
    tk.Label(fen.corps, text=titre, font=police(15, gras=True, titre=True), fg=ROUGE, bg=BLANC).pack(anchor="w")
    tk.Label(fen.corps, text=message, font=police(10), fg=NUIT, bg=BLANC, justify="left",
             wraplength=px(500)).pack(anchor="w", pady=(px(6), px(12)))
    tk.Label(fen.corps, text=f"Pour confirmer, tapez : {mot}", font=police(10, gras=True), fg=NUIT,
             bg=BLANC).pack(anchor="w")
    var = fen.variable()
    champ = creer_champ(fen.corps, var, largeur=24)
    champ.pack(anchor="w", ipady=px(5), pady=(px(4), px(10)))

    def valider():
        if var.get().strip().upper() == mot:
            fen.resultat = True
            fen.destroy()

    bas = tk.Frame(fen.corps, bg=BLANC)
    bas.pack(fill="x", side="bottom")
    creer_bouton(bas, "Confirmer", valider, style="danger", grand=False).pack(side="left")
    creer_bouton(bas, "Annuler", fen.destroy, style="secondaire", grand=False).pack(side="left", padx=px(10))
    champ.bind("<Return>", lambda _e: valider())
    champ.focus_set()
    return bool(fen.attendre())


def demander_motif(parent, titre, message, action):
    """Fenêtre qui demande un texte (motif) puis appelle `action(texte)` ; une erreur reste affichée dans la fenêtre.
    Retourne True si l'action a réussi."""
    fen = Fenetre(parent, titre, 560, 360)
    tk.Label(fen.corps, text=titre, font=police(15, gras=True, titre=True), fg=ROUGE, bg=BLANC).pack(anchor="w")
    tk.Label(fen.corps, text=message, font=police(10), fg=NUIT, bg=BLANC, justify="left",
             wraplength=px(500)).pack(anchor="w", pady=(px(6), px(12)))
    tk.Label(fen.corps, text="Motif", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
    var = fen.variable()
    champ = creer_champ(fen.corps, var, largeur=50)
    champ.pack(fill="x", ipady=px(5), pady=(px(3), px(8)))
    erreur = tk.Label(fen.corps, text="", font=police(10), fg=ROUGE, bg=BLANC, wraplength=px(500), justify="left",
                      anchor="w")
    erreur.pack(fill="x")

    def valider():
        try:
            action(var.get())
        except Exception as e:                               # noqa: BLE001 - message métier affiché tel quel
            if e.__class__.__name__ in ("ErreurRef", "ErreurAcces", "PermissionError"):
                erreur.config(text=str(e))
                return
            raise
        fen.resultat = True
        fen.destroy()

    bas = tk.Frame(fen.corps, bg=BLANC)
    bas.pack(fill="x", side="bottom")
    creer_bouton(bas, "Confirmer", valider, style="danger", grand=False).pack(side="left")
    creer_bouton(bas, "Annuler", fen.destroy, style="secondaire", grand=False).pack(side="left", padx=px(10))
    champ.bind("<Return>", lambda _e: valider())
    champ.focus_set()
    return bool(fen.attendre())
