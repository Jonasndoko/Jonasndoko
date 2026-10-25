"""Module « Gestionnaire d'accès » (réservé à l'Administrateur).

1. Utilisateurs : créer les comptes, choisir leur rôle, désactiver, nouveau mot de passe, débloquer.
2. Rôles : les 8 postes de base, les rôles que vous créez, et leurs droits de base.
3. Autorisations : les droits de chaque utilisateur, module par module.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog

import acces
import config
import droits
import sections
from composants import DialogueCompte, ModuleOnglets, afficher_mdp_provisoire, case_a_cocher, entete
from database import lire_iso, maintenant
from ecrans_paiement import creer_arbre, vider_arbre
from theme import BLANC, GRIS, NUIT, ROUGE, VERT, carte, creer_bouton, definir_actif, police, px


def formater_horodatage(texte) -> str:
    try:
        return lire_iso(texte).astimezone().strftime("%d/%m/%Y  %H:%M")
    except (TypeError, ValueError):
        return "jamais" if not texte else texte


class MatriceDroits(tk.Frame):
    """Cases à cocher module x droit. Seuls les droits qui existent dans au moins un module sont affichés ;
    une case sans objet pour un module est grisée."""

    def __init__(self, parent):
        super().__init__(parent, bg=BLANC)
        utilises = [d for d in config.DROITS if any(d in possibles for _t, possibles in config.MODULES_DROITS.values())]
        tk.Label(self, text="Module", font=police(10, gras=True), fg=NUIT, bg=BLANC).grid(row=0, column=0, sticky="w")
        for c, droit in enumerate(utilises, start=1):
            tk.Label(self, text=config.LIBELLE_DROITS[droit], font=police(9, gras=True), fg=NUIT,
                     bg=BLANC).grid(row=0, column=c, padx=px(8))
        self.variables, self.cases = {}, []
        for r, (module, (titre, possibles)) in enumerate(config.MODULES_DROITS.items(), start=1):
            tk.Label(self, text=titre, font=police(10), fg=NUIT, bg=BLANC, anchor="w", justify="left",
                     wraplength=px(190)).grid(row=r, column=0, sticky="w", pady=px(4))
            for c, droit in enumerate(utilises, start=1):
                var = tk.BooleanVar(value=False)
                self.variables[(module, droit)] = var
                case = tk.Checkbutton(self, variable=var, bg=BLANC, activebackground=BLANC, selectcolor=BLANC, bd=0,
                                      highlightthickness=0, cursor="hand2",
                                      state="normal" if droit in possibles else "disabled")
                case.grid(row=r, column=c)
                if droit in possibles:
                    self.cases.append(case)

    def definir(self, accordes):
        for cle, var in self.variables.items():
            var.set(cle in accordes)

    def lire(self) -> set:
        return {cle for cle, var in self.variables.items() if var.get()}

    def activer(self, actif):
        for case in self.cases:
            case.config(state="normal" if actif else "disabled")
        if not actif:
            self.definir(set())


def note_droits(parent, texte=None):
    return tk.Label(parent, text=texte or (
        "Droits : Ajout, Modification, Lecture, Suppression. « Lecture » est accordée d'office dès qu'un autre droit l'est "
        "et ouvre le module. Dans Paiement des frais, Ajout permet d'enregistrer un paiement (réservé en plus au rôle "
        "Percepteur) ; un reçu ne se modifie ni ne se supprime. « Travaux techniques » et « Gestionnaire d'accès » "
        "sont réservés au rôle Administrateur. « Tableau de bord » : seule la Lecture existe ; les comptes qui l'ont "
        "voient le tableau de bord en premier à la connexion (l'Administrateur y a toujours accès). « Traçabilité et audit » : "
        "seule la Lecture existe (journal des activités, historique financier, contrôles) ; l'Administrateur y a toujours accès."),
        font=police(9), fg=GRIS, bg=BLANC, justify="left", anchor="w", wraplength=px(430))


# ================================================================== 1) UTILISATEURS
class PanneauUtilisateurs(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.id_courant = None
        self.comptes = {}
        corps = tk.Frame(self, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        entete(corps, "Utilisateurs", "Créez les comptes et attribuez à chacun un rôle. Le mot de passe provisoire "
                                      "n'est affiché qu'une seule fois ; l'utilisateur devra le changer à sa première connexion.")
        cadre, self.arbre = creer_arbre(corps, [("nom", "Nom complet", 250, "w"), ("login", "Identifiant", 140, "w"),
                                                ("role", "Rôle", 170, "w"), ("etat", "État", 220, "w"),
                                                ("derniere", "Dernière connexion", 160, "w")], hauteur=12)
        cadre.pack(fill="both", expand=True)
        self.arbre.tag_configure("inactif", foreground=GRIS)
        self.arbre.tag_configure("bloque", foreground=ROUGE)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)
        boutons = tk.Frame(corps, bg=BLANC)
        boutons.pack(fill="x", pady=(px(8), 0))
        creer_bouton(boutons, "Nouvel utilisateur", self.nouveau, grand=False).pack(side="left")
        self.btn_modifier = creer_bouton(boutons, "Modifier", self.modifier, style="secondaire", grand=False)
        self.btn_modifier.pack(side="left", padx=px(8))
        self.btn_mdp = creer_bouton(boutons, "Nouveau mot de passe", self.reinitialiser, style="secondaire", grand=False)
        self.btn_mdp.pack(side="left")
        self.btn_debloquer = creer_bouton(boutons, "Débloquer", self.debloquer, style="secondaire", grand=False)
        self.btn_debloquer.pack(side="left", padx=px(8))
        self.btn_activer = creer_bouton(boutons, "Activer", lambda: self.changer_etat(True), style="secondaire", grand=False)
        self.btn_activer.pack(side="left")
        self.btn_desactiver = creer_bouton(boutons, "Désactiver", lambda: self.changer_etat(False), style="danger", grand=False)
        self.btn_desactiver.pack(side="left", padx=px(8))
        creer_bouton(boutons, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False).pack(side="right")
        self.lbl_message = tk.Label(corps, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(1000))
        self.lbl_message.pack(fill="x", pady=(px(8), 0))
        self._activer(False)

    def au_affichage(self):
        self.recharger()

    def _activer(self, actif):
        for b in (self.btn_modifier, self.btn_mdp, self.btn_debloquer):
            definir_actif(b, actif)
        compte = self.comptes.get(self.id_courant) if actif else None
        definir_actif(self.btn_activer, bool(compte) and not compte["ACTIF"])        # un seul des deux est utilisable :
        definir_actif(self.btn_desactiver, bool(compte) and bool(compte["ACTIF"]))   # selon l'état du compte choisi

    @staticmethod
    def etat_de(c) -> tuple:
        if not c["ACTIF"]:
            return "Désactivé", "inactif"
        if c["BLOQUE_JUSQUA"] and lire_iso(c["BLOQUE_JUSQUA"]) > maintenant():
            return "Bloqué (trop d'échecs)", "bloque"
        return ("Actif - mot de passe provisoire" if c["DOIT_CHANGER_MDP"] else "Actif"), ""

    def recharger(self, choisir=None):
        try:
            lignes = acces.lister_utilisateurs(self.app.conn, self.app.session)
        except PermissionError as erreur:
            messagebox.showwarning("Accès refusé", str(erreur), parent=self)
            return
        self.comptes = {c["ID_USER"]: c for c in lignes}
        vider_arbre(self.arbre)
        for c in lignes:
            etat, tag = self.etat_de(c)
            self.arbre.insert("", "end", iid=str(c["ID_USER"]), tags=(tag,) if tag else (), values=(
                c["NOM_COMPLET"], c["LOGIN"], droits.libelle_role(self.app.conn, c["ROLE"]), etat,
                formater_horodatage(c["DERNIERE_CONNEXION"])))
        cible = choisir or self.id_courant
        if cible in self.comptes:
            self.arbre.selection_set(str(cible))
            self.id_courant = cible
            self._activer(True)                 # états des boutons Activer / Désactiver d'après les données rechargées
        else:
            self.id_courant = None
            self._activer(False)

    def _selection(self, _e=None):
        selection = self.arbre.selection()
        if selection:
            self.id_courant = int(selection[0])
            self._activer(True)

    def _message(self, texte, couleur=VERT):
        self.lbl_message.config(text=texte, fg=couleur)

    def nouveau(self):
        conn, session = self.app.conn, self.app.session
        resultat = DialogueCompte(self, session, lambda v: acces.creer_compte(
            conn, session, v["login"], v["nom"], v["poste"]), roles=droits.roles(conn)).attendre()
        if not resultat:
            return
        id_user, mdp = resultat
        self.recharger(choisir=id_user)
        self._message("Compte créé.")
        afficher_mdp_provisoire(self, self.comptes[id_user]["LOGIN"], mdp)

    def modifier(self):
        if self.id_courant is None:
            return
        conn, session, id_user = self.app.conn, self.app.session, self.id_courant
        if DialogueCompte(self, session, lambda v: acces.modifier_compte(
                conn, session, id_user, v["nom"], v["poste"], v["actif"]), compte=self.comptes[id_user],
                roles=droits.roles(conn)).attendre():
            self.recharger(choisir=id_user)
            self._message("Compte modifié.")

    def changer_etat(self, actif):
        """Boutons Activer / Désactiver."""
        if self.id_courant is None:
            return
        c = self.comptes[self.id_courant]
        if not actif and not messagebox.askyesno(
                "Désactiver le compte",
                f"Désactiver le compte de {c['NOM_COMPLET']} ({c['LOGIN']}) ?\n\nIl ne pourra plus se connecter. "
                "Son historique (reçus, journal) est conservé et vous pourrez le réactiver à tout moment.", parent=self):
            return
        try:
            acces.changer_etat_compte(self.app.conn, self.app.session, self.id_courant, actif)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        self._message(f"Compte de {c['NOM_COMPLET']} " + ("activé." if actif else "désactivé."))

    def reinitialiser(self):
        if self.id_courant is None:
            return
        c = self.comptes[self.id_courant]
        if not messagebox.askyesno("Nouveau mot de passe",
                                   f"Donner un nouveau mot de passe provisoire à {c['NOM_COMPLET']} ?\n"
                                   "L'ancien mot de passe cessera de fonctionner.", parent=self):
            return
        try:
            mdp = acces.reinitialiser_mdp(self.app.conn, self.app.session, self.id_courant)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        afficher_mdp_provisoire(self, c["LOGIN"], mdp, "Nouveau mot de passe provisoire")

    def debloquer(self):
        if self.id_courant is None:
            return
        try:
            acces.debloquer(self.app.conn, self.app.session, self.id_courant)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        self._message("Compte débloqué.")


# ================================================================== 2) RÔLES
class PanneauRoles(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.role_courant = None
        self.roles = {}
        self.grid_columnconfigure(0, weight=3, uniform="col")
        self.grid_columnconfigure(1, weight=2, uniform="col")
        self.grid_rowconfigure(0, weight=1)

        gauche = tk.Frame(self, bg=BLANC)
        gauche.grid(row=0, column=0, sticky="nsew", padx=(px(24), px(8)), pady=px(14))
        entete(gauche, "Rôles", "Les 8 postes de base de l'école et ceux que vous créez. Les droits de base d'un rôle sont donnés à tout nouveau compte "
                                "de ce rôle, et quand un compte change de rôle.")
        cadre, self.arbre = creer_arbre(gauche, [("role", "Rôle", 190, "w"), ("nb", "Utilisateurs actifs", 130, "center"),
                                                 ("droits", "Droits de base", 330, "w")], hauteur=10)
        cadre.pack(fill="both", expand=True)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)
        boutons = tk.Frame(gauche, bg=BLANC)
        boutons.pack(fill="x", pady=(px(8), 0))
        creer_bouton(boutons, "Nouveau rôle", self.nouveau_role, grand=False).pack(side="left")
        self.btn_supprimer = creer_bouton(boutons, "Supprimer le rôle", self.supprimer_role, style="secondaire", grand=False)
        self.btn_supprimer.pack(side="left", padx=px(8))
        creer_bouton(boutons, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False).pack(side="right")

        droite = carte(self, padx=px(18), pady=px(14))
        droite.grid(row=0, column=1, sticky="nsew", padx=(px(8), px(24)), pady=px(14))
        self.lbl_titre = tk.Label(droite, text="Droits de base du rôle", font=police(13, gras=True, titre=True), fg=NUIT,
                                  bg=BLANC, anchor="w")
        self.lbl_titre.pack(fill="x", pady=(0, px(10)))
        self.matrice = MatriceDroits(droite)
        self.matrice.pack(fill="x")
        note_droits(droite).pack(fill="x", pady=(px(10), px(8)))
        self.var_appliquer = tk.BooleanVar(value=False)
        case_a_cocher(droite, "Appliquer aussi aux comptes existants de ce rôle\n(leurs autorisations personnelles sont remplacées)",
                      self.var_appliquer).pack(anchor="w", pady=(0, px(8)))
        self.btn_enregistrer = creer_bouton(droite, "Enregistrer les droits du rôle", self.enregistrer, grand=False)
        self.btn_enregistrer.pack(anchor="w")
        self.lbl_message = tk.Label(droite, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(430))
        self.lbl_message.pack(fill="x", pady=(px(8), 0))
        self._activer(False)

    def au_affichage(self):
        self.recharger()

    def _activer(self, actif):
        definir_actif(self.btn_enregistrer, actif)
        definir_actif(self.btn_supprimer, actif and self.role_courant not in config.ROLES)
        self.matrice.activer(actif)
        if not actif:
            self.lbl_titre.config(text="Droits de base du rôle")

    def nouveau_role(self):
        libelle = simpledialog.askstring("Nouveau rôle", "Nom du nouveau rôle (poste) :", parent=self)
        if libelle is None:
            return
        try:
            code = acces.creer_role(self.app.conn, self.app.session, libelle)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self.lbl_message.config(text=str(erreur), fg=ROUGE)
            return
        self.role_courant = code
        self.recharger()
        self._selection()
        self.lbl_message.config(fg=VERT, text="Rôle créé. Cochez ses droits de base puis enregistrez.")

    def supprimer_role(self):
        if self.role_courant is None:
            return
        libelle = self.roles[self.role_courant]["libelle"]
        if not messagebox.askyesno("Supprimer le rôle", f"Supprimer le rôle « {libelle} » ?", parent=self):
            return
        try:
            acces.supprimer_role(self.app.conn, self.app.session, self.role_courant)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self.lbl_message.config(text=str(erreur), fg=ROUGE)
            return
        self.role_courant = None
        self.recharger()
        self._activer(False)
        self.lbl_message.config(fg=VERT, text=f"Rôle « {libelle} » supprimé.")

    def recharger(self):
        try:
            lignes = acces.lister_roles(self.app.conn, self.app.session)
        except PermissionError as erreur:
            messagebox.showwarning("Accès refusé", str(erreur), parent=self)
            return
        self.roles = {r["role"]: r for r in lignes}
        vider_arbre(self.arbre)
        for r in lignes:
            self.arbre.insert("", "end", iid=r["role"], values=(r["libelle"], r["nb_utilisateurs"], droits.resume(r["droits"])))
        if self.role_courant in self.roles:
            self.arbre.selection_set(self.role_courant)

    def _selection(self, _e=None):
        selection = self.arbre.selection()
        if not selection:
            return
        self.role_courant = selection[0]
        r = self.roles[self.role_courant]
        self._activer(True)
        self.lbl_titre.config(text=f"Droits de base : {r['libelle']}")
        self.matrice.definir(r["droits"])
        self.var_appliquer.set(False)

    def enregistrer(self):
        if self.role_courant is None:
            return
        libelle = self.roles[self.role_courant]["libelle"]
        appliquer = self.var_appliquer.get()
        if appliquer and not messagebox.askyesno(
                "Appliquer aux comptes existants",
                f"Remplacer les autorisations de TOUS les comptes « {libelle} » par ces droits de base ?", parent=self):
            return
        try:
            accordes, n = acces.definir_droits_role(self.app.conn, self.app.session, self.role_courant,
                                                    self.matrice.lire(), appliquer)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self.lbl_message.config(text=str(erreur), fg=ROUGE)
            return
        self.recharger()
        self.matrice.definir(accordes)
        self.var_appliquer.set(False)
        self.lbl_message.config(fg=VERT, text=f"Droits du rôle « {libelle} » enregistrés : {droits.resume(accordes)}."
                                + (f"\nAppliqués à {n} compte(s)." if appliquer else ""))


# ================================================================== 3) AUTORISATIONS
class PanneauAutorisations(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.id_courant = None
        self.comptes = {}
        self.grid_columnconfigure(0, weight=3, uniform="col")
        self.grid_columnconfigure(1, weight=2, uniform="col")
        self.grid_rowconfigure(0, weight=1)

        gauche = tk.Frame(self, bg=BLANC)
        gauche.grid(row=0, column=0, sticky="nsew", padx=(px(24), px(8)), pady=px(14))
        entete(gauche, "Autorisations", "Choisissez un utilisateur, cochez ce qu'il peut faire dans chaque module, "
                                        "puis enregistrez. Le changement est immédiat, même s'il est connecté.")
        cadre, self.arbre = creer_arbre(gauche, [("nom", "Nom complet", 230, "w"), ("login", "Identifiant", 130, "w"),
                                                 ("role", "Rôle", 150, "w"), ("sections", "Sections", 150, "w"),
                                                 ("droits", "Autorisations", 240, "w")],
                                        hauteur=10)
        cadre.pack(fill="both", expand=True)
        self.arbre.tag_configure("inactif", foreground=GRIS)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)
        creer_bouton(gauche, "Menu principal", self.app.afficher_menu, style="secondaire", grand=False
                     ).pack(anchor="w", pady=(px(8), 0))

        droite = carte(self, padx=px(18), pady=px(14))
        droite.grid(row=0, column=1, sticky="nsew", padx=(px(8), px(24)), pady=px(14))
        self.lbl_titre = tk.Label(droite, text="Autorisations du compte", font=police(13, gras=True, titre=True), fg=NUIT,
                                  bg=BLANC, anchor="w", justify="left", wraplength=px(430))
        self.lbl_titre.pack(fill="x")
        self.lbl_role = tk.Label(droite, text="Choisissez un utilisateur dans la liste.", font=police(10), fg=GRIS,
                                 bg=BLANC, anchor="w", justify="left", wraplength=px(430))
        self.lbl_role.pack(fill="x", pady=(0, px(10)))
        self.matrice = MatriceDroits(droite)
        self.matrice.pack(fill="x")
        tk.Label(droite, text="Sections de l'école ouvertes à ce compte", font=police(10, gras=True), fg=NUIT, bg=BLANC,
                 anchor="w").pack(fill="x", pady=(px(10), 0))
        self.var_sections = {s: tk.BooleanVar(value=True) for s, _t in sections.SECTIONS}
        self.cases_sections = []
        for s, texte in sections.SECTIONS:
            case = case_a_cocher(droite, texte, self.var_sections[s])
            case.pack(anchor="w")
            self.cases_sections.append(case)
        tk.Label(droite, text="Le compte ne voit que les élèves, classes, paiements et inscriptions des sections cochées. "
                              "Il n'y a pas de carte d'élève au primaire.", font=police(9), fg=GRIS, bg=BLANC, anchor="w",
                 justify="left", wraplength=px(430)).pack(fill="x", pady=(px(2), 0))
        note_droits(droite).pack(fill="x", pady=(px(10), px(8)))
        self.btn_enregistrer = creer_bouton(droite, "Enregistrer les autorisations", self.enregistrer, grand=False)
        self.btn_enregistrer.pack(anchor="w")
        self.btn_defaut = creer_bouton(droite, "Rétablir les droits de base de son rôle", self.droits_du_role,
                                       style="secondaire", grand=False)
        self.btn_defaut.pack(anchor="w", pady=(px(8), 0))
        self.lbl_message = tk.Label(droite, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(430))
        self.lbl_message.pack(fill="x", pady=(px(8), 0))
        self._activer(False)

    def au_affichage(self):
        self.recharger()

    def _activer(self, actif):
        for b in (self.btn_enregistrer, self.btn_defaut):
            definir_actif(b, actif)
        self.matrice.activer(actif)
        for case in self.cases_sections:
            case.config(state="normal" if actif else "disabled")
        if not actif:
            self.lbl_titre.config(text="Autorisations du compte")
            self.lbl_role.config(text="Choisissez un utilisateur dans la liste.")

    def recharger(self, choisir=None):
        try:
            lignes = acces.lister_utilisateurs(self.app.conn, self.app.session)
        except PermissionError as erreur:
            messagebox.showwarning("Accès refusé", str(erreur), parent=self)
            return
        self.comptes = {c["ID_USER"]: c for c in lignes}
        vider_arbre(self.arbre)
        for c in lignes:
            accordes = droits.droits_utilisateur(self.app.conn, c["ID_USER"])
            self.arbre.insert("", "end", iid=str(c["ID_USER"]), tags=(() if c["ACTIF"] else ("inactif",)), values=(
                c["NOM_COMPLET"], c["LOGIN"], droits.libelle_role(self.app.conn, c["ROLE"]),
                sections.resume(self.app.conn, c["ID_USER"]), droits.resume(accordes)))
        cible = choisir or self.id_courant
        if cible in self.comptes:
            self.arbre.selection_set(str(cible))
        else:
            self.id_courant = None
            self._activer(False)

    def _selection(self, _e=None):
        selection = self.arbre.selection()
        if not selection:
            return
        self.id_courant = int(selection[0])
        c = self.comptes[self.id_courant]
        self._activer(True)
        admin = c["ROLE"] == config.ADMINISTRATEUR
        self.lbl_titre.config(text=f"Autorisations de {c['NOM_COMPLET']}")
        self.lbl_role.config(text=f"Rôle : {droits.libelle_role(self.app.conn, c['ROLE'])}   •   identifiant : {c['LOGIN']}\n"
                                  f"Travaux techniques et Gestionnaire d'accès : {'accès accordé' if admin else 'accès non accordé'} "
                                  f"(selon le rôle)")
        self.matrice.definir(acces.lire_droits(self.app.conn, self.app.session, self.id_courant))
        ouvertes = sections.sections_explicites(self.app.conn, self.id_courant) or sections.TOUTES
        for s, var in self.var_sections.items():
            var.set(s in ouvertes)

    def _message(self, texte, couleur=VERT):
        self.lbl_message.config(text=texte, fg=couleur)

    def enregistrer(self):
        if self.id_courant is None:
            return
        try:
            choisies = {s for s, var in self.var_sections.items() if var.get()}
            sections.definir_sections(self.app.conn, self.app.session, self.id_courant, choisies)
            accordes = acces.definir_droits(self.app.conn, self.app.session, self.id_courant, self.matrice.lire())
        except (acces.ErreurAcces, sections.ErreurSection, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        self.matrice.definir(accordes)
        self._message("Autorisations enregistrées : " + droits.resume(accordes) + " ; sections : "
                      + sections.resume(self.app.conn, self.id_courant) + ". Effet immédiat.")

    def droits_du_role(self):
        if self.id_courant is None:
            return
        try:
            accordes = acces.droits_par_defaut_du_poste(self.app.conn, self.app.session, self.id_courant)
        except (acces.ErreurAcces, PermissionError) as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.recharger(choisir=self.id_courant)
        self.matrice.definir(accordes)
        self._message("Droits de base du rôle rétablis : " + droits.resume(accordes) + ".")


# ================================================================== MODULE
class ModuleAcces(ModuleOnglets):
    TITRE = "Gestionnaire d'accès"
    ONGLETS = (("utilisateurs", "1   Utilisateurs", PanneauUtilisateurs),
               ("roles", "2   Rôles", PanneauRoles),
               ("autorisations", "3   Autorisations", PanneauAutorisations))
