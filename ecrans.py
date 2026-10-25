"""Écrans de base : accueil, connexion, premier démarrage, menu principal, fenêtre de l'application."""
import time
import tkinter as tk
from tkinter import ttk

import config
import droits
import modules
import recuperation
import security
import tableau
import theme
from modules import MODULES
from theme import (BLEU, BLEU_CIEL, BLANC, BLEU_PALE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ORANGE, ROUGE, VERT,
                   barre_haute, boutons_navigation, carte, charger_logo, creer_bouton, creer_champ, police, px)

def panneau_identite(parent):
    """Bandeau bleu de nuit à gauche : logo, nom de l'école, devise."""
    panneau = tk.Frame(parent, bg=NUIT)
    panneau.configure(width=px(340))
    panneau.pack_propagate(False)
    centre = tk.Frame(panneau, bg=NUIT)
    centre.place(relx=0.5, rely=0.5, anchor="center")
    panneau.logo = charger_logo(110)                          # garder une référence
    cadre = tk.Frame(centre, bg=BLANC, padx=2, pady=2)
    cadre.pack()
    tk.Label(cadre, image=panneau.logo, bd=0).pack()
    tk.Label(centre, text=config.NOM_ECOLE, font=police(19, gras=True, titre=True), fg=BLANC, bg=NUIT,
             wraplength=px(280), justify="center").pack(pady=(px(20), px(8)))
    tk.Frame(centre, bg=BLEU_PALE, height=2, width=px(90)).pack(pady=px(6))
    tk.Label(centre, text=config.DEVISE_ECOLE.replace("  -  ", "\n"), font=police(11, gras=True, titre=True),
             fg=BLEU_PALE, bg=NUIT, justify="center").pack(pady=(px(6), 0))
    return panneau


# ================================================================== 1) ACCUEIL
class EcranAccueil(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=BLANC)
        self.app = app
        tk.Frame(self, bg=NUIT, height=px(10)).pack(fill="x", side="top")
        tk.Frame(self, bg=NUIT, height=px(10)).pack(fill="x", side="bottom")

        centre = tk.Frame(self, bg=BLANC)
        centre.place(relx=0.5, rely=0.5, anchor="center")

        self.logo = charger_logo(250)                          # garder une référence
        cadre = tk.Frame(centre, bg=NUIT, padx=3, pady=3)
        cadre.pack()
        tk.Label(cadre, image=self.logo, bd=0).pack()

        tk.Label(centre, text=config.NOM_ECOLE, font=police(36, gras=True, titre=True),
                 fg=NUIT, bg=BLANC).pack(pady=(px(24), px(4)))
        tk.Frame(centre, bg=NUIT, height=px(3), width=px(150)).pack(pady=px(8))
        tk.Label(centre, text=config.DEVISE_ECOLE, font=police(17, gras=True, titre=True),
                 fg=NUIT_CLAIR, bg=BLANC).pack(pady=(px(6), px(26)))

        self.bouton = creer_bouton(centre, "Aller", app.aller_connexion)
        self.bouton.pack()

        tk.Label(self, text=f"{config.NOM_APP}  •  Version {config.VERSION}", font=police(9),
                 fg=GRIS, bg=BLANC).pack(side="bottom", pady=px(14))

    def au_affichage(self):
        self.app.bind("<Return>", lambda _e: self.app.aller_connexion())
        self.bouton.focus_set()


# ================================================================== 2) CONNEXION
class EcranConnexion(tk.Frame):
    def __init__(self, app, info=""):
        super().__init__(app, bg=FOND_CLAIR)
        self.app = app
        self._fin_blocage = 0.0
        self._id_after = None

        panneau_identite(self).pack(side="left", fill="y")
        droite = tk.Frame(self, bg=FOND_CLAIR)
        droite.pack(side="left", fill="both", expand=True)

        boite = carte(droite, padx=px(44), pady=px(36))
        boite.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(boite, text="Connexion", font=police(24, gras=True, titre=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        tk.Label(boite, text="Accès réservé au personnel autorisé", font=police(10), fg=GRIS,
                 bg=BLANC).pack(anchor="w", pady=(px(2), px(18)))

        self.var_login, self.var_mdp, self.var_poste = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.postes = {libelle: code for code, libelle in droits.roles(app.conn).items()}

        tk.Label(boite, text="Poste (rôle)", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        self.liste_postes = ttk.Combobox(boite, textvariable=self.var_poste, values=list(self.postes),
                                         state="readonly", font=police(12))
        self.liste_postes.pack(fill="x", ipady=px(4), pady=(px(4), px(14)))

        tk.Label(boite, text="Identifiant", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        self.champ_login = creer_champ(boite, self.var_login)
        self.champ_login.pack(fill="x", ipady=px(7), pady=(px(4), px(14)))

        tk.Label(boite, text="Mot de passe", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        self.champ_mdp = creer_champ(boite, self.var_mdp, masque=True)
        self.champ_mdp.pack(fill="x", ipady=px(7), pady=(px(4), px(4)))
        self.champ_mdp.bind("<KeyPress>", self._surveiller_majuscules)

        self.var_afficher = tk.BooleanVar(value=False)
        tk.Checkbutton(boite, text="Afficher le mot de passe", variable=self.var_afficher,
                       command=self._basculer_affichage, font=police(9), fg=GRIS, bg=BLANC,
                       activebackground=BLANC, selectcolor=BLANC, bd=0, highlightthickness=0,
                       cursor="hand2").pack(anchor="w")

        self.lbl_majuscules = tk.Label(boite, text="", font=police(9, gras=True), fg=ORANGE, bg=BLANC)
        self.lbl_majuscules.pack(anchor="w", pady=(px(6), 0))

        self.lbl_message = tk.Label(boite, text=info, font=police(10), fg=NUIT if info else ROUGE, bg=BLANC,
                                    wraplength=px(330), justify="left", height=3, anchor="nw")
        self.lbl_message.pack(fill="x", pady=(px(4), px(6)))

        self.bouton = creer_bouton(boite, "Se connecter", self._valider)
        self.bouton.pack(fill="x")
        lien = tk.Button(boite, text="Mot de passe oublié ?", command=lambda: app.afficher(EcranRecuperation),
                         font=police(10, gras=True), fg=BLEU, bg=BLANC, activeforeground=NUIT, activebackground=BLANC,
                         relief="flat", bd=0, highlightthickness=0, cursor="hand2")
        lien.pack(pady=(px(10), 0))
        creer_bouton(boite, "←  Retour à l'accueil", lambda: app.afficher(EcranAccueil),
                     style="secondaire", grand=False).pack(pady=(px(8), 0))

    def au_affichage(self):
        self.app.bind("<Return>", self._valider)
        self.liste_postes.focus_set()

    def destroy(self):
        if self._id_after:
            self.after_cancel(self._id_after)
        super().destroy()

    def _basculer_affichage(self):
        self.champ_mdp.config(show="" if self.var_afficher.get() else "●")

    def _surveiller_majuscules(self, evenement):
        if evenement.char and evenement.char.isalpha():
            actif = bool(evenement.state & 0x2)                # bit « Lock » = Verr. Maj.
            self.lbl_majuscules.config(text="⚠  Verrouillage des majuscules activé" if actif else "")

    def _montrer(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _valider(self, _evenement=None):
        if self._fin_blocage > time.monotonic():
            return
        poste = self.postes.get(self.var_poste.get())
        if poste is None:
            self._montrer("Choisissez votre poste dans la liste.")
            return
        resultat = security.authentifier(self.app.conn, self.var_login.get(), self.var_mdp.get(), poste)
        self.var_mdp.set("")                                  # on ne garde jamais le mot de passe saisi
        self.var_afficher.set(False)
        self._basculer_affichage()
        if resultat.ok:
            self.app.connexion_reussie(resultat.session)
            return
        self._montrer(resultat.message)
        if resultat.secondes_blocage:
            self._demarrer_blocage(resultat.secondes_blocage)
        else:
            self.champ_mdp.focus_set()

    def _demarrer_blocage(self, secondes):
        self._fin_blocage = time.monotonic() + secondes
        theme.definir_actif(self.bouton, False)
        self._decompte()

    def _decompte(self):
        reste = self._fin_blocage - time.monotonic()
        if reste <= 0:
            self._fin_blocage = 0.0
            theme.definir_actif(self.bouton, True)
            self._montrer("Vous pouvez réessayer.", GRIS)
            return
        self._montrer(f"Trop de tentatives. Compte bloqué pendant encore "
                      f"{security.formater_duree(int(reste) + 1)}.")
        self._id_after = self.after(1000, self._decompte)


# ================================================================== 3) PREMIER DÉMARRAGE
class EcranPremierDemarrage(tk.Frame):
    """Affiché uniquement tant qu'aucun compte Administrateur n'existe : aucun mot de passe par défaut n'est livré."""

    def __init__(self, app):
        super().__init__(app, bg=FOND_CLAIR)
        self.app = app
        panneau_identite(self).pack(side="left", fill="y")
        droite = tk.Frame(self, bg=FOND_CLAIR)
        droite.pack(side="left", fill="both", expand=True)

        boite = carte(droite, padx=px(36), pady=px(28))
        boite.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(boite, text="Premier démarrage", font=police(22, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(boite, text="Créez le compte de l'Administrateur. Il servira ensuite à créer les autres comptes et à gérer leurs droits.\n"
                             "Notez bien ce mot de passe : il ne peut pas être récupéré.",
                 font=police(9), fg=GRIS, bg=BLANC, justify="left"
                 ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(2), px(14)))

        self.var_nom, self.var_login = tk.StringVar(), tk.StringVar()
        self.var_mdp, self.var_conf = tk.StringVar(), tk.StringVar()

        champs = tk.Frame(boite, bg=BLANC)
        champs.grid(row=2, column=0, sticky="n")
        self.entrees = []
        for libelle, variable, masque in (("Nom complet", self.var_nom, False),
                                          ("Identifiant", self.var_login, False),
                                          ("Mot de passe", self.var_mdp, True),
                                          ("Confirmer le mot de passe", self.var_conf, True)):
            tk.Label(champs, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
            entree = creer_champ(champs, variable, masque, largeur=28)
            entree.pack(fill="x", ipady=px(5), pady=(px(3), px(10)))
            entree.bind("<KeyRelease>", self._maj_exigences)
            self.entrees.append(entree)

        liste = tk.Frame(boite, bg=BLANC)
        liste.grid(row=2, column=1, sticky="n", padx=(px(28), 0))
        tk.Label(liste, text="Le mot de passe doit avoir :", font=police(10, gras=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w", pady=(0, px(6)))
        self.lbl_exigences = []
        for _ in security.exigences_mdp(""):
            lbl = tk.Label(liste, text="", font=police(9), bg=BLANC, anchor="w", wraplength=px(250), justify="left")
            lbl.pack(anchor="w", pady=1)
            self.lbl_exigences.append(lbl)

        self.lbl_erreur = tk.Label(boite, text="", font=police(10), fg=ROUGE, bg=BLANC, wraplength=px(520),
                                   justify="left", anchor="w")
        self.lbl_erreur.grid(row=3, column=0, columnspan=2, sticky="we", pady=(px(4), px(6)))
        creer_bouton(boite, "Créer le compte Administrateur", self._creer).grid(row=4, column=0, columnspan=2, sticky="we")
        creer_bouton(boite, "←  Retour à l'accueil", lambda: app.afficher(EcranAccueil), style="secondaire",
                     grand=False).grid(row=5, column=0, columnspan=2, pady=(px(10), 0))
        self._maj_exigences()

    def au_affichage(self):
        self.app.bind("<Return>", self._creer)
        self.entrees[0].focus_set()

    def _maj_exigences(self, _e=None):
        for lbl, (texte, ok) in zip(self.lbl_exigences,
                                    security.exigences_mdp(self.var_mdp.get(), self.var_login.get())):
            lbl.config(text=("✔  " if ok else "✘  ") + texte, fg=VERT if ok else GRIS)

    def _creer(self, _e=None):
        if self.var_mdp.get() != self.var_conf.get():
            self.lbl_erreur.config(text="Les deux mots de passe ne sont pas identiques.")
            return
        try:
            security.creer_utilisateur(self.app.conn, self.var_login.get(), self.var_nom.get(),
                                       config.ADMINISTRATEUR, self.var_mdp.get())
        except ValueError as erreur:
            self.lbl_erreur.config(text=str(erreur))
            return
        for variable in (self.var_mdp, self.var_conf):
            variable.set("")
        self.app.afficher(EcranConnexion, info="Compte créé. Vous pouvez maintenant vous connecter.")


# ================================================================== 3 bis) CHANGEMENT DE MOT DE PASSE
class EcranChangementMdp(tk.Frame):
    """Obligatoire à la première connexion (mot de passe provisoire donné par l'Administrateur) ;
    sinon accessible depuis le menu (« Mon mot de passe »)."""

    def __init__(self, app, obligatoire=True):
        super().__init__(app, bg=FOND_CLAIR)
        self.app, self.obligatoire = app, obligatoire
        panneau_identite(self).pack(side="left", fill="y")
        droite = tk.Frame(self, bg=FOND_CLAIR)
        droite.pack(side="left", fill="both", expand=True)
        boite = carte(droite, padx=px(36), pady=px(28))
        boite.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(boite, text="Changer mon mot de passe", font=police(22, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(boite, text=("Votre mot de passe est provisoire : choisissez-en un personnel pour continuer."
                              if obligatoire else "Saisissez votre mot de passe actuel, puis le nouveau."),
                 font=police(9), fg=GRIS, bg=BLANC, justify="left"
                 ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(2), px(14)))

        self.var_ancien, self.var_nouveau, self.var_conf = tk.StringVar(), tk.StringVar(), tk.StringVar()
        champs = tk.Frame(boite, bg=BLANC)
        champs.grid(row=2, column=0, sticky="n")
        self.entrees = []
        for libelle, variable in (("Mot de passe actuel", self.var_ancien), ("Nouveau mot de passe", self.var_nouveau),
                                  ("Confirmer le nouveau mot de passe", self.var_conf)):
            tk.Label(champs, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
            entree = creer_champ(champs, variable, True, largeur=28)
            entree.pack(fill="x", ipady=px(5), pady=(px(3), px(10)))
            entree.bind("<KeyRelease>", self._maj_exigences)
            self.entrees.append(entree)

        liste = tk.Frame(boite, bg=BLANC)
        liste.grid(row=2, column=1, sticky="n", padx=(px(28), 0))
        tk.Label(liste, text="Le mot de passe doit avoir :", font=police(10, gras=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w", pady=(0, px(6)))
        self.lbl_exigences = []
        for _ in security.exigences_mdp(""):
            lbl = tk.Label(liste, text="", font=police(9), bg=BLANC, anchor="w", wraplength=px(250), justify="left")
            lbl.pack(anchor="w", pady=1)
            self.lbl_exigences.append(lbl)

        self.lbl_erreur = tk.Label(boite, text="", font=police(10), fg=ROUGE, bg=BLANC, wraplength=px(520),
                                   justify="left", anchor="w")
        self.lbl_erreur.grid(row=3, column=0, columnspan=2, sticky="we", pady=(px(4), px(6)))
        creer_bouton(boite, "Enregistrer", self._valider).grid(row=4, column=0, columnspan=2, sticky="we")
        creer_bouton(boite, "Annuler" if not obligatoire else "Se déconnecter",
                     app.afficher_accueil if not obligatoire else app.deconnexion,
                     style="secondaire", grand=False).grid(row=5, column=0, columnspan=2, pady=(px(10), 0))
        self._maj_exigences()

    def au_affichage(self):
        self.app.bind("<Return>", self._valider)
        self.entrees[0].focus_set()

    def _maj_exigences(self, _e=None):
        for lbl, (texte, ok) in zip(self.lbl_exigences, security.exigences_mdp(
                self.var_nouveau.get(), self.app.session.login)):
            lbl.config(text=("✔  " if ok else "✘  ") + texte, fg=VERT if ok else GRIS)

    def _valider(self, _e=None):
        try:
            security.changer_mdp(self.app.conn, self.app.session, self.var_ancien.get(),
                                 self.var_nouveau.get(), self.var_conf.get())
        except ValueError as erreur:
            self.lbl_erreur.config(text=str(erreur))
            return
        for variable in (self.var_ancien, self.var_nouveau, self.var_conf):
            variable.set("")
        self.app.afficher_accueil()


# ================================================================== 3 ter) MOT DE PASSE OUBLIÉ
class EcranRecuperation(tk.Frame):
    """Mot de passe oublié : l'utilisateur saisit son identifiant, le code de récupération que l'Administrateur lui a
    donné (valable quelques minutes seulement) et choisit un nouveau mot de passe."""

    def __init__(self, app):
        super().__init__(app, bg=FOND_CLAIR)
        self.app = app
        panneau_identite(self).pack(side="left", fill="y")
        droite = tk.Frame(self, bg=FOND_CLAIR)
        droite.pack(side="left", fill="both", expand=True)
        boite = carte(droite, padx=px(36), pady=px(28))
        boite.place(relx=0.5, rely=0.5, anchor="center")

        duree = config.DUREE_CODE_RECUPERATION_SEC
        tk.Label(boite, text="Mot de passe oublié", font=police(22, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(boite, text=("Demandez un code de récupération à l'Administrateur (il vérifiera votre identité).\n"
                              f"Le code disparaît après {duree // 60} minute(s) : saisissez-le sans attendre."),
                 font=police(9), fg=GRIS, bg=BLANC, justify="left"
                 ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(2), px(14)))

        self.var_login, self.var_code = tk.StringVar(), tk.StringVar()
        self.var_nouveau, self.var_conf = tk.StringVar(), tk.StringVar()
        champs = tk.Frame(boite, bg=BLANC)
        champs.grid(row=2, column=0, sticky="n")
        self.entrees = []
        for libelle, variable, masque in (("Identifiant", self.var_login, False),
                                          ("Code de récupération", self.var_code, False),
                                          ("Nouveau mot de passe", self.var_nouveau, True),
                                          ("Confirmer le nouveau mot de passe", self.var_conf, True)):
            tk.Label(champs, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
            entree = creer_champ(champs, variable, masque, largeur=28)
            entree.pack(fill="x", ipady=px(5), pady=(px(3), px(10)))
            entree.bind("<KeyRelease>", self._maj_exigences)
            self.entrees.append(entree)

        liste = tk.Frame(boite, bg=BLANC)
        liste.grid(row=2, column=1, sticky="n", padx=(px(28), 0))
        tk.Label(liste, text="Le mot de passe doit avoir :", font=police(10, gras=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w", pady=(0, px(6)))
        self.lbl_exigences = []
        for _ in security.exigences_mdp(""):
            lbl = tk.Label(liste, text="", font=police(9), bg=BLANC, anchor="w", wraplength=px(250), justify="left")
            lbl.pack(anchor="w", pady=1)
            self.lbl_exigences.append(lbl)

        self.lbl_erreur = tk.Label(boite, text="", font=police(10), fg=ROUGE, bg=BLANC, wraplength=px(520),
                                   justify="left", anchor="w")
        self.lbl_erreur.grid(row=3, column=0, columnspan=2, sticky="we", pady=(px(4), px(6)))
        creer_bouton(boite, "Changer mon mot de passe", self._valider).grid(row=4, column=0, columnspan=2, sticky="we")
        creer_bouton(boite, "←  Retour à la connexion", lambda: app.afficher(EcranConnexion), style="secondaire",
                     grand=False).grid(row=5, column=0, columnspan=2, pady=(px(10), 0))
        self._maj_exigences()

    def au_affichage(self):
        self.app.bind("<Return>", self._valider)
        self.entrees[0].focus_set()

    def _maj_exigences(self, _e=None):
        for lbl, (texte, ok) in zip(self.lbl_exigences,
                                    security.exigences_mdp(self.var_nouveau.get(), self.var_login.get())):
            lbl.config(text=("✔  " if ok else "✘  ") + texte, fg=VERT if ok else GRIS)

    def _valider(self, _e=None):
        try:
            recuperation.recuperer_mdp(self.app.conn, self.var_login.get(), self.var_code.get(),
                                       self.var_nouveau.get(), self.var_conf.get())
        except recuperation.ErreurRecuperation as erreur:
            self.var_code.set("")                              # un code faux n'est pas gardé à l'écran
            for variable in (self.var_nouveau, self.var_conf):
                variable.set("")
            self._maj_exigences()
            self.lbl_erreur.config(text=str(erreur))
            return
        for variable in (self.var_code, self.var_nouveau, self.var_conf):
            variable.set("")
        self.app.afficher(EcranConnexion, info="Mot de passe modifié. Vous pouvez maintenant vous connecter.")


# ================================================================== APPLICATION
class Application(tk.Tk):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.session = None
        self._ecran = None

        theme.initialiser(self)
        self.title(f"{config.NOM_ECOLE} - {config.NOM_APP}")
        self.configure(bg=BLANC)
        self.minsize(px(860), px(600))
        largeur, hauteur = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{int(largeur * 0.9)}x{int(hauteur * 0.88)}+{int(largeur * 0.05)}+{int(hauteur * 0.04)}")
        try:
            self.state("zoomed")                  # plein écran adapté (Windows)
        except tk.TclError:
            pass
        try:
            self._icone = tk.PhotoImage(file=str(config.DOSSIER_ASSETS / "gestisc_64.png"))
            self.iconphoto(True, self._icone)
        except tk.TclError:
            pass

        for evenement in ("<Key>", "<Button>", "<Motion>"):
            self.bind_all(evenement, self._activite, add="+")
        self.after(10_000, self._verifier_inactivite)
        self.protocol("WM_DELETE_WINDOW", self.quitter)
        self.afficher(EcranAccueil)

    # --- navigation ------------------------------------------------------
    def afficher(self, classe, **options):
        self.unbind("<Return>")
        if self._ecran is not None:
            self._ecran.destroy()
        self._ecran = classe(self, **options)
        self._ecran.pack(fill="both", expand=True)
        if hasattr(self._ecran, "au_affichage"):
            self._ecran.au_affichage()

    def aller_connexion(self):
        if security.aucun_administrateur(self.conn):
            self.afficher(EcranPremierDemarrage)
        else:
            self.afficher(EcranConnexion)

    def afficher_menu(self):
        """Menu principal. Un compte qui n'a qu'un seul module n'a pas de menu : son module en tient lieu."""
        cle = modules.module_direct(self.conn, self.session)
        if cle:
            self.ouvrir_module(cle)
        else:
            from ecrans_principal import EcranPrincipal       # barre latérale (menu principal) + tableau de bord
            self.afficher(EcranPrincipal)

    def afficher_accueil(self):
        """Premier écran après la connexion : l'écran principal (barre latérale + tableau de bord), ou directement le
        module si le compte n'en a qu'un seul."""
        self.afficher_menu()

    def tableau_autorise(self) -> bool:
        return bool(self.session) and tableau.peut(self.conn, self.session)

    def afficher_tableau(self):
        if not self.tableau_autorise():                      # double contrôle : jamais seulement l'affichage
            return
        self.afficher_menu()                                  # le tableau de bord est sur l'écran principal

    def menu_utile(self) -> bool:
        return modules.menu_utile(self.conn, self.session)

    def afficher_changement_mdp(self):
        self.afficher(EcranChangementMdp, obligatoire=False)

    def ouvrir_module(self, cle):
        autorises = set(modules.modules_ouverts(self.conn, self.session))
        if cle not in autorises:                              # double contrôle : jamais seulement l'affichage
            return
        if cle == "paiement":
            from ecrans_paiement import ModulePaiement
            self.afficher(ModulePaiement)
        elif cle == "travaux":
            from ecrans_travaux import ModuleTravaux
            self.afficher(ModuleTravaux)
        elif cle == "acces":
            from ecrans_acces import ModuleAcces
            self.afficher(ModuleAcces)
        elif cle == "encaissement":
            from ecrans_encaissement import ModuleEncaissement
            self.afficher(ModuleEncaissement)
        elif cle == "controle":
            from ecrans_controle import ModuleControle
            self.afficher(ModuleControle)
        elif cle == "carte":
            from ecrans_carte import ModuleCarte
            self.afficher(ModuleCarte)
        elif cle == "audit":
            from ecrans_audit import ModuleAudit
            self.afficher(ModuleAudit)
        elif cle == "inscription":
            from ecrans_inscription import ModuleInscription
            self.afficher(ModuleInscription)
        elif cle == "presence_eleves":
            from ecrans_gestion import ModulePresenceEleves
            self.afficher(ModulePresenceEleves)
        elif cle in [m[0] for m in config.ESPACES_MODULES.values()]:        # Espace Études, Espace Discipline
            from ecrans_etudes import ModuleEtudesDiscipline
            espace = next(e for e, m in config.ESPACES_MODULES.items() if m[0] == cle)
            self.afficher(ModuleEtudesDiscipline, module_propre=espace)
        elif cle == "personnel":
            from ecrans_personnel import ModulePersonnel
            self.afficher(ModulePersonnel)

    # --- session ---------------------------------------------------------
    def connexion_reussie(self, session):
        self.session = session
        if session.doit_changer_mdp:
            self.afficher(EcranChangementMdp, obligatoire=True)
        else:
            self.afficher_accueil()

    def session_terminee(self, info=""):
        """Retour à la connexion sans toucher à la base (après une restauration : l'ancienne session n'a plus de sens)."""
        self.session = None
        self.afficher(EcranConnexion, info=info)

    def deconnexion(self, motif="DECONNEXION", info=""):
        if self.session:
            security.fermer_session(self.conn, self.session, motif)
            self.session = None
        self.afficher(EcranConnexion, info=info)

    def _activite(self, _evenement=None):
        if self.session:
            self.session.toucher()

    def _verifier_inactivite(self):
        if self.session and self.session.expiree():
            self.deconnexion("DECONNEXION_INACTIVITE",
                             f"Session fermée après {config.DELAI_INACTIVITE_MIN} minutes d'inactivité.")
        self.after(10_000, self._verifier_inactivite)

    def quitter(self):
        if self.session:
            security.fermer_session(self.conn, self.session)
        self.destroy()
