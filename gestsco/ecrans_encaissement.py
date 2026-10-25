"""Module « Encaissement des fonds perçus ».

1. Enregistrement de l'encaissement : on choisit le percepteur (liste), on saisit le montant encaissé, on choisit la
   devise et la date, on saisit le montant versé ; l'ÉCART s'affiche seul (encaissé - versé).
   Boutons : ENREGISTRER, ANNULER.
2. Rapport global : une seule information, la date. Le système extrait les paiements de TOUS les percepteurs par type de
   frais, puis les encaissements, versements et écarts. Boutons : CONSULTER, IMPRIMER, ANNULER.
"""
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import argent
import encaissements
from calendrier import SelecteurDate
from ecrans_paiement import creer_arbre, ouvrir_fichier, vider_arbre
from encaissements import ErreurEncaissement
from theme import (BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ORANGE, ROUGE, VERT,
                   actions_barre_module, barre_haute, bouton_menu, carte, creer_bouton, creer_champ, definir_actif,
                   police, px, ZoneAdaptative)

ERREURS = (ErreurEncaissement, PermissionError)


def aujourdhui_txt() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def _etiquette(parent, texte):
    tk.Label(parent, text=texte, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")


# ================================================================== 1) ENREGISTREMENT
class PanneauEnregistrement(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.percepteurs, self.devises = {}, {}        # libellé affiché -> n° de percepteur / code de la devise
        self.vars = {k: tk.StringVar() for k in ("percepteur", "encaisse", "devise", "date", "verse", "ecart")}

        boite = carte(self, padx=px(28), pady=px(20))
        boite.pack(fill="x", padx=px(24), pady=(px(16), px(8)))
        self.lbl_titre = tk.Label(boite, text="Enregistrement de l'encaissement", font=police(16, gras=True, titre=True),
                                  fg=NUIT, bg=BLANC)
        self.lbl_titre.pack(anchor="w", pady=(0, px(12)))
        colonnes = tk.Frame(boite, bg=BLANC)
        colonnes.pack(fill="x")
        colonnes.grid_columnconfigure((0, 1), weight=1, uniform="col")
        gauche, droite = tk.Frame(colonnes, bg=BLANC), tk.Frame(colonnes, bg=BLANC)
        gauche.grid(row=0, column=0, sticky="new", padx=(0, px(20)))
        droite.grid(row=0, column=1, sticky="new", padx=(px(20), 0))

        _etiquette(gauche, "Percepteur")
        self.cb_perc = ttk.Combobox(gauche, textvariable=self.vars["percepteur"], state="readonly", font=police(11))
        self.cb_perc.pack(fill="x", ipady=px(3), pady=(px(3), px(10)))
        _etiquette(gauche, "Montant encaissé")
        self.champ_encaisse = creer_champ(gauche, self.vars["encaisse"])
        self.champ_encaisse.pack(fill="x", ipady=px(6), pady=(px(3), px(10)))
        _etiquette(gauche, "Devise")
        self.cb_devise = ttk.Combobox(gauche, textvariable=self.vars["devise"], state="readonly", font=police(11))
        self.cb_devise.pack(fill="x", ipady=px(3), pady=(px(3), px(10)))

        _etiquette(droite, "Date (jj/mm/aaaa) - tapez-la ou choisissez dans le calendrier")
        self.champ_date = SelecteurDate(droite, self.vars["date"])
        self.champ_date.pack(fill="x", pady=(px(3), px(10)))
        _etiquette(droite, "Montant versé")
        self.champ_verse = creer_champ(droite, self.vars["verse"])
        self.champ_verse.pack(fill="x", ipady=px(6), pady=(px(3), px(10)))
        _etiquette(droite, "Écart  (calculé par le système : encaissé - versé)")
        creer_champ(droite, self.vars["ecart"], lecture_seule=True).pack(fill="x", ipady=px(6), pady=(px(3), px(2)))
        self.lbl_nature = tk.Label(droite, text="", font=police(10, gras=True), bg=BLANC, anchor="w")
        self.lbl_nature.pack(fill="x")

        self.lbl_message = tk.Label(self, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(900))
        self.lbl_message.pack(fill="x", padx=px(26), pady=(px(4), px(6)))

        boutons = tk.Frame(self, bg=BLANC)
        boutons.pack(fill="x", padx=px(24), pady=(0, px(14)))
        self.btn_enregistrer = creer_bouton(boutons, "ENREGISTRER", self.enregistrer)
        self.btn_enregistrer.pack(side="left", padx=(0, px(10)))
        creer_bouton(boutons, "ANNULER", self.annuler, style="danger").pack(side="left", padx=(0, px(10)))
        bouton_menu(boutons, self.app).pack(side="right")

        for cle in ("encaisse", "verse", "devise"):                       # l'écart se recalcule à chaque frappe
            self.vars[cle].trace_add("write", self.maj_ecart)

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        self.preparer()

    def _charger_listes(self):
        conn = self.app.conn
        self.percepteurs = {f"N° {n} - {nom}": n for n, nom in encaissements.liste_percepteurs(conn)}
        self.devises = {libelle: code for code, libelle in encaissements.liste_devises(conn)}
        self.cb_perc.config(values=list(self.percepteurs))
        self.cb_devise.config(values=list(self.devises))

    def preparer(self):
        """Formulaire vide pour un nouvel encaissement."""
        self._charger_listes()
        for cle in ("percepteur", "encaisse", "devise", "verse"):
            self.vars[cle].set("")
        self.vars["date"].set(aujourdhui_txt())
        self.maj_ecart()
        peut_ajouter = encaissements.peut(self.app.conn, self.app.session, "AJOUT")
        definir_actif(self.btn_enregistrer, peut_ajouter)
        if not peut_ajouter:
            self._message("Votre compte n'a pas le droit « Ajout » sur ce module.", ROUGE)
        elif not self.percepteurs:
            self._message("Aucun percepteur actif : créez d'abord un compte de poste Percepteur "
                          "(Gestionnaire d'accès > Utilisateurs).", ORANGE)
        elif not self.devises:
            self._message("Aucune devise : l'Administrateur doit en ajouter une (Travaux techniques > Devises).", ORANGE)
        else:
            self._message("")
        self.cb_perc.focus_set()

    # --- affichage -----------------------------------------------------------
    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def maj_ecart(self, *_):
        """Affiche l'écart dès que le montant encaissé et le montant versé sont valides."""
        try:
            encaisse = encaissements.lire_montant(self.vars["encaisse"].get())
            verse = encaissements.lire_montant(self.vars["verse"].get(), zero_permis=True)
        except ErreurEncaissement:
            self.vars["ecart"].set("")
            self.lbl_nature.config(text="")
            return
        ecart = encaissements.calculer_ecart(encaisse, verse)
        devise = self.devises.get(self.vars["devise"].get(), "")
        self.vars["ecart"].set(f"{argent.formater(ecart)} {devise}".strip())
        self.lbl_nature.config(text=encaissements.etiquette_ecart(ecart),
                               fg=ROUGE if ecart > 0 else (VERT if ecart < 0 else GRIS))

    # --- actions -------------------------------------------------------------
    def enregistrer(self):
        n_perc = self.percepteurs.get(self.vars["percepteur"].get())
        code = self.devises.get(self.vars["devise"].get())
        try:
            if n_perc is None:
                raise ErreurEncaissement("Choisissez un percepteur dans la liste.")
            encaisse = encaissements.lire_montant(self.vars["encaisse"].get(), "montant encaissé")
            if not code:
                raise ErreurEncaissement("Choisissez la devise.")
            verse = encaissements.lire_montant(self.vars["verse"].get(), "montant versé", zero_permis=True)
            n_enc = encaissements.enregistrer(self.app.conn, self.app.session, n_perc, self.vars["date"].get(),
                                              code, encaisse, verse)
        except ERREURS as erreur:
            self._message(str(erreur), ROUGE)
            return
        self.preparer()
        self._message(f"Encaissement N° {n_enc} enregistré.", VERT)

    def annuler(self):
        """Efface la saisie."""
        self.preparer()


# ================================================================== 2) RAPPORT GLOBAL
class PanneauRapport(tk.Frame):
    """Un seul paramètre : la date. CONSULTER affiche, IMPRIMER imprime (PDF), ANNULER efface l'écran."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.rapport = None

        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(4)))
        tk.Label(haut, text="Date du rapport (jj/mm/aaaa) :", font=police(11, gras=True), fg=NUIT,
                 bg=BLANC).pack(side="left")
        self.var_date = tk.StringVar()
        selecteur = SelecteurDate(haut, self.var_date)
        selecteur.pack(side="left", padx=px(10))
        self.champ = selecteur.champ
        self.champ.bind("<Return>", self.consulter)
        creer_bouton(haut, "CONSULTER", self.consulter, grand=False).pack(side="left")
        self.btn_imprimer = creer_bouton(haut, "IMPRIMER", self.imprimer, style="secondaire", grand=False)
        self.btn_imprimer.pack(side="left", padx=px(8))
        creer_bouton(haut, "ANNULER", self.annuler, style="danger", grand=False).pack(side="left")
        definir_actif(self.btn_imprimer, False)

        self.lbl_info = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left",
                                 wraplength=px(1000))
        self.lbl_info.pack(fill="x", padx=px(24), pady=(0, px(6)))

        cadre, self.arbre = creer_arbre(self, [("a", "N°", 60, "center"), ("b", "Percepteur", 300, "w"),
                                               ("c", "Reçus / Devise", 110, "center"), ("d", "Encaissé", 160, "e"),
                                               ("e", "Versé", 140, "e"), ("f", "Écart", 140, "e")], hauteur=10)
        cadre.pack(fill="both", expand=True, padx=px(24))
        self.arbre.tag_configure("groupe", background=NUIT, foreground=BLANC, font=police(10, gras=True))
        self.arbre.tag_configure("entete", background=FOND_CLAIR, foreground=GRIS, font=police(9, gras=True))
        self.arbre.tag_configure("total", background=FOND_CLAIR, foreground=NUIT, font=police(10, gras=True))
        self.arbre.tag_configure("manquant", foreground=ROUGE)
        self.arbre.tag_configure("excedent", foreground=VERT)

        self.lbl_total = tk.Label(self, text="", font=police(11, gras=True), fg=NUIT, bg=BLANC, anchor="e",
                                  justify="right", wraplength=px(1000))
        self.lbl_total.pack(fill="x", padx=px(24), pady=(px(8), px(4)))
        bas = tk.Frame(self, bg=BLANC)
        bas.pack(fill="x", padx=px(24), pady=(px(4), px(14)))
        bouton_menu(bas, self.app).pack(side="right")

    def au_affichage(self):
        if not self.var_date.get():
            self.var_date.set(aujourdhui_txt())
        self.champ.focus_set()

    def _vider(self, message="", couleur=ROUGE):
        vider_arbre(self.arbre)
        self.rapport = None
        self.lbl_total.config(text="")
        self.lbl_info.config(text=message, fg=couleur)
        definir_actif(self.btn_imprimer, False)

    def annuler(self):
        """Annule l'écran : efface le résultat et la date saisie."""
        self._vider()
        self.var_date.set("")
        self.champ.focus_set()

    def consulter(self, _evenement=None):
        try:
            rapport = encaissements.rapport_global(self.app.conn, self.app.session, self.var_date.get())
        except ERREURS as erreur:
            self._vider(str(erreur))
            return
        self._vider()
        if encaissements.rapport_vide(rapport):
            self.lbl_info.config(text=f"Aucun paiement ni encaissement enregistré le {rapport['date_txt']}."
                                 + (f"  ({rapport['nb_annules']} reçu(s) annulé(s) non comptés.)"
                                    if rapport["nb_annules"] else ""), fg=ORANGE)
            return
        self.rapport = rapport
        arbre = self.arbre

        arbre.insert("", "end", tags=("groupe",), values=("", "1.  PAIEMENTS DE LA JOURNÉE, PAR TYPE DE FRAIS", "", "", "", ""))
        if not rapport["groupes"]:
            arbre.insert("", "end", values=("", "Aucun paiement enregistré à cette date.", "", "", "", ""))
        for i, g in enumerate(rapport["groupes"]):
            arbre.insert("", "end", tags=("entete",), values=("", f"TYPE DE FRAIS :  {g['type_frais'].upper()}", "Reçus",
                                                              "Montant encaissé (reçus)", "", ""))
            for j, l in enumerate(g["lignes"], start=1):
                arbre.insert("", "end", values=(j, l["percepteur"], l["nb_recus"], l["montant_txt"], "", ""))
            arbre.insert("", "end", tags=("total",), values=(
                "", f"Total {g['type_frais']}", g["nb_recus"],
                "  ;  ".join(f"{argent.formater(c)} {d}" for d, c in g["totaux"]), "", ""))

        arbre.insert("", "end", tags=("groupe",), values=("", "2.  ENCAISSEMENTS ET VERSEMENTS DES PERCEPTEURS", "", "", "", ""))
        if not rapport["versements"]:
            arbre.insert("", "end", values=("", "Aucun encaissement enregistré à cette date.", "", "", "", ""))
        else:
            arbre.insert("", "end", tags=("entete",), values=("N° op.", "Percepteur", "Devise", "Encaissé", "Versé", "Écart"))
            for v in rapport["versements"]:
                etiquette = ("manquant",) if v["ecart"] > 0 else (("excedent",) if v["ecart"] < 0 else ())
                arbre.insert("", "end", tags=etiquette, values=(
                    v["n_enc"], v["percepteur"], v["devise"], v["encaisse_txt"], v["verse_txt"], v["ecart_txt"]))
            for devise, enc, ver, ecart in rapport["totaux_versements"]:
                arbre.insert("", "end", tags=("total",), values=(
                    "", f"Total {devise}", devise, argent.formater(enc), argent.formater(ver), argent.formater(ecart)))

        info = f"Tous les percepteurs   •   {rapport['nb_recus']} reçu(s) et {rapport['nb_encaissements']} encaissement(s) le {rapport['date_txt']}"
        if rapport["nb_annules"]:
            info += f"   •   {rapport['nb_annules']} reçu(s) annulé(s) non comptés"
        if rapport["sans_versement"]:
            info += "\nAttention : aucun encaissement enregistré pour : " + ", ".join(rapport["sans_versement"])
        self.lbl_info.config(text=info, fg=ORANGE if rapport["sans_versement"] else GRIS)
        self.lbl_total.config(text=("TOTAL DES PAIEMENTS :  " + "  ;  ".join(
            f"{argent.formater(c)} {d}" for d, c in rapport["totaux"])) if rapport["totaux"] else "")
        definir_actif(self.btn_imprimer, True)

    def imprimer(self):
        self.consulter()                                   # on imprime toujours ce qui correspond à la date saisie
        if not self.rapport:
            return
        try:
            chemin = encaissements.preparer_rapport_pdf(self.app.conn, self.app.session, self.rapport["jour"])
            ouvrir_fichier(chemin)
        except ERREURS as erreur:
            messagebox.showwarning("Impression impossible", str(erreur), parent=self)
        except OSError as erreur:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le rapport : {erreur}", parent=self)


# ================================================================== MODULE
def onglets_autorises(conn, session) -> set:
    """Onglets utilisables par ce compte (droits relus dans la base)."""
    if not encaissements.peut(conn, session, "LECTURE"):
        return set()
    ouverts = {"rapport"}
    if encaissements.peut(conn, session, "AJOUT"):
        ouverts.add("enregistrement")
    return ouverts


class ModuleEncaissement(tk.Frame):
    ONGLETS = (("enregistrement", "1   Enregistrement de l'encaissement"),
               ("rapport", "2   Rapport global"))
    CLASSES = {"enregistrement": PanneauEnregistrement, "rapport": PanneauRapport}

    def __init__(self, app, onglet=None):
        super().__init__(app, bg=BLANC)
        self.app = app
        self.autorises = onglets_autorises(app.conn, app.session)

        barre = barre_haute(self, "Encaissement des fonds perçus")
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        navigation = tk.Frame(self, bg=FOND_CLAIR)
        navigation.pack(fill="x")
        self.boutons = {}
        for i, (cle, texte) in enumerate(self.ONGLETS):        # les onglets sont toujours visibles
            navigation.grid_columnconfigure(i, weight=1, uniform="onglet")
            verrouille = cle not in self.autorises
            b = tk.Button(navigation, text=texte + ("   (réservé)" if verrouille else ""),
                          command=lambda c=cle: self.afficher_onglet(c), relief="flat", bd=0, highlightthickness=0,
                          font=police(11, gras=True), padx=px(12), pady=px(12), cursor="hand2", wraplength=px(300))
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons[cle] = b
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        self.panneaux = {cle: self.CLASSES[cle](self.zone, self) for cle, _ in self.ONGLETS if cle in self.autorises}
        self.courant = None
        premier = next((c for c, _ in self.ONGLETS if c in self.panneaux), None)
        if premier:
            self.afficher_onglet(onglet if onglet in self.panneaux else premier)
        else:
            tk.Label(self.zone, text="Votre compte n'a pas accès à ce module.\nDemandez à l'Administrateur de vous accorder "
                                     "le droit « Lecture » (Gestionnaire d'accès > Autorisations).",
                     font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=px(60))

    def afficher_onglet(self, cle):
        if cle not in self.panneaux:                      # onglet verrouillé : on explique pourquoi, sans bouger
            if cle == "enregistrement":
                messagebox.showinfo("Enregistrement de l'encaissement",
                                    "Votre compte n'a pas le droit « Ajout » sur ce module.\n"
                                    "Demandez à l'Administrateur de vous l'accorder (Gestionnaire d'accès > Autorisations).",
                                    parent=self)
            return
        for panneau in self.panneaux.values():
            panneau.pack_forget()
        for nom, bouton in self.boutons.items():
            actif = nom == cle
            verrouille = nom not in self.panneaux
            bouton.config(bg=NUIT if actif else FOND_CLAIR,
                          fg=BLANC if actif else ("#8A96B3" if verrouille else NUIT),
                          activebackground=NUIT_CLAIR if actif else BORDURE,
                          activeforeground=BLANC if actif else NUIT)
        self.courant = self.panneaux[cle]
        self.courant.pack(fill="both", expand=True)
        if hasattr(self.courant, "au_affichage"):
            self.courant.au_affichage()
