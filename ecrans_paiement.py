"""Module « Paiement des frais scolaires » : consultation, duplicata et rapport sont ouverts à tout compte ayant
accès au module ; seul l'enregistrement du paiement est soumis à vérification (poste Percepteur + droit Ajout).

1. Consultation de la situation   2. Enregistrement du paiement   3. Duplicata du reçu
4. Rapport journalier de caisse
"""
import os
import re
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import argent
import donnees
import droits
import inscription
import paiements
from calendrier import SelecteurDate
from database import journaliser, lire_iso
from theme import (BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, NUIT_CLAIR, ORANGE, ROUGE, VERT,
                   actions_barre_module, barre_haute, bouton_menu, carte, creer_bouton, creer_champ, definir_actif,
                   police, px, ZoneAdaptative)


# ================================================================== outils
def formater_date(texte):
    """'2010-03-25' -> '25/03/2010' (le texte est renvoyé tel quel s'il n'a pas ce format)."""
    if texte and re.fullmatch(r"\d{4}-\d{2}-\d{2}", texte):
        return f"{texte[8:]}/{texte[5:7]}/{texte[:4]}"
    return texte or "—"


def ouvrir_fichier(chemin):
    if sys.platform.startswith("win"):
        os.startfile(chemin)                                  # ouvre le PDF dans le lecteur : on peut l'imprimer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", chemin])
    else:
        subprocess.Popen(["xdg-open", chemin])


def imprimer_recu(app, parent, n_recu, duplicata):
    """Génère le PDF du reçu et l'affiche (aperçu + impression depuis le lecteur PDF)."""
    try:
        chemin = paiements.preparer_pdf(app.conn, app.session, n_recu, duplicata)
        ouvrir_fichier(chemin)
    except (paiements.ErreurPaiement, PermissionError) as erreur:
        messagebox.showwarning("Impression impossible", str(erreur), parent=parent)
    except OSError as erreur:
        messagebox.showerror("Erreur", f"Impossible d'ouvrir le reçu : {erreur}", parent=parent)


def imprimer_rapport(app, parent, jour, n_perc=None):
    """Génère le rapport journalier de caisse (PDF) et l'affiche pour impression."""
    try:
        chemin = paiements.preparer_rapport_pdf(app.conn, app.session, jour, n_perc)
        ouvrir_fichier(chemin)
    except (paiements.ErreurPaiement, PermissionError) as erreur:
        messagebox.showwarning("Impression impossible", str(erreur), parent=parent)
    except OSError as erreur:
        messagebox.showerror("Erreur", f"Impossible d'ouvrir le rapport : {erreur}", parent=parent)


def creer_arbre(parent, colonnes, hauteur=6):
    """colonnes : [(clé, titre, largeur, ancrage)] -> (cadre, arbre) avec barre de défilement."""
    cadre = tk.Frame(parent, bg=BLANC)
    arbre = ttk.Treeview(cadre, columns=[c[0] for c in colonnes], show="headings", height=hauteur,
                         selectmode="browse")
    for cle, titre, largeur, ancre in colonnes:
        arbre.heading(cle, text=titre, anchor=ancre)
        arbre.column(cle, width=px(largeur), minwidth=px(50), anchor=ancre)
    defil = ttk.Scrollbar(cadre, orient="vertical", command=arbre.yview)
    arbre.configure(yscrollcommand=defil.set)
    arbre.pack(side="left", fill="both", expand=True)
    defil.pack(side="right", fill="y")
    return cadre, arbre


def vider_arbre(arbre):
    for iid in arbre.get_children():
        arbre.delete(iid)


def ligne_info(parent, rangee, libelle, variable, gras=True):
    tk.Label(parent, text=libelle, font=police(9), fg=GRIS, bg=BLANC, anchor="ne").grid(
        row=rangee, column=0, sticky="ne", padx=(0, px(10)), pady=px(2))
    tk.Label(parent, textvariable=variable, font=police(10, gras=gras), fg=NUIT, bg=BLANC, anchor="w",
             justify="left", wraplength=px(300)).grid(row=rangee, column=1, sticky="nw", pady=px(2))


def titre_carte(parent, texte):
    tk.Label(parent, text=texte, font=police(12, gras=True, titre=True), fg=NUIT, bg=BLANC).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, px(8)))


# ================================================================== recherche d'élève
class ZoneRecherche(tk.Frame):
    """Saisie du nom ou du matricule. Un seul résultat : sélectionné d'office ; sinon une liste s'affiche."""

    def __init__(self, parent, app, quand_choisi, quand_efface=None):
        super().__init__(parent, bg=BLANC)
        self.app, self.quand_choisi, self.quand_efface = app, quand_choisi, quand_efface
        ligne = tk.Frame(self, bg=BLANC)
        ligne.pack(fill="x")
        tk.Label(ligne, text="Nom ou matricule de l'élève :", font=police(11, gras=True), fg=NUIT,
                 bg=BLANC).pack(side="left")
        self.var = tk.StringVar()
        self.champ = creer_champ(ligne, self.var, largeur=34)
        self.champ.pack(side="left", padx=px(10), ipady=px(6))
        self.champ.bind("<Return>", self.rechercher)
        creer_bouton(ligne, "Rechercher", self.rechercher, grand=False).pack(side="left")
        creer_bouton(ligne, "Effacer", self.effacer, style="secondaire", grand=False).pack(side="left", padx=px(8))

        self.lbl = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl.pack(fill="x", pady=(px(4), 0))
        self.cadre_liste, self.liste = creer_arbre(self, [("mat", "Matricule", 140, "w"),
                                                           ("nom", "Nom complet", 380, "w"),
                                                           ("classe", "Classe (année en cours)", 220, "w")], hauteur=4)
        self.liste.bind("<<TreeviewSelect>>", self._choisir)

    def prendre_focus(self):
        self.champ.focus_set()

    def rechercher(self, _evenement=None):
        terme = self.var.get().strip()
        vider_arbre(self.liste)
        self.cadre_liste.pack_forget()
        if len(terme) < 2:
            self.lbl.config(text="Saisissez au moins 2 caractères.", fg=ORANGE)
            return
        resultats = donnees.rechercher_eleves(self.app.conn, terme, session=self.app.session)
        if not resultats:
            self.lbl.config(text=f"Aucun élève trouvé pour « {terme} ».", fg=ROUGE)
        elif len(resultats) == 1:
            self.lbl.config(text="", fg=GRIS)
            self.quand_choisi(resultats[0]["matricule"])
        else:
            for r in resultats:
                self.liste.insert("", "end", iid=r["matricule"], values=(r["matricule"], r["nom_complet"], r["classe"]))
            suite = " Affinez la recherche si besoin." if len(resultats) >= 60 else ""
            self.lbl.config(text=f"{len(resultats)} élèves trouvés : cliquez sur le bon élève.{suite}", fg=GRIS)
            self.cadre_liste.pack(fill="x", pady=(px(4), 0))

    def _choisir(self, _evenement=None):
        selection = self.liste.selection()
        if selection:
            self.quand_choisi(selection[0])

    def effacer(self):
        self.var.set("")
        vider_arbre(self.liste)
        self.cadre_liste.pack_forget()
        self.lbl.config(text="")
        if self.quand_efface:
            self.quand_efface()
        self.champ.focus_set()


# ================================================================== 1) CONSULTATION
class PanneauConsultation(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.inscriptions = []
        # Tout le contenu est dans une colonne centrée (largeur limitée) : la consultation est « au milieu » de l'écran
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.centre = tk.Frame(self, bg=BLANC, width=px(1100))
        self.centre.grid(row=0, column=0, sticky="ns")
        self.centre.grid_propagate(False)
        self.centre.grid_columnconfigure(0, weight=1)
        self.centre.grid_rowconfigure(1, weight=1)
        self.bind("<Configure>", self._ajuster_largeur)

        self.recherche = ZoneRecherche(self.centre, self.app, self.charger_eleve, self.vider)
        self.recherche.grid(row=0, column=0, sticky="we", padx=px(8), pady=(px(14), px(6)))
        self.indication = tk.Label(self.centre, text="Saisissez le nom ou le matricule de l'élève, puis appuyez sur Entrée.",
                                   font=police(12), fg=GRIS, bg=BLANC)
        self.indication.grid(row=1, column=0)
        self.detail = tk.Frame(self.centre, bg=BLANC)
        self.detail.grid(row=1, column=0, sticky="nsew", padx=px(8), pady=(px(6), px(6)))
        self._construire_detail()
        self.detail.grid_remove()

        # Toujours visible : pour une personne pas encore inscrite (donc introuvable ci-dessus), qui veut payer son inscription
        bandeau = tk.Frame(self.centre, bg=FOND_CLAIR, highlightbackground=BORDURE, highlightthickness=1)
        bandeau.grid(row=2, column=0, sticky="we", padx=px(8), pady=(0, px(14)))
        tk.Label(bandeau, text="Pas encore inscrit ? Payez les frais d'inscription :", font=police(11, gras=True),
                 fg=NUIT, bg=FOND_CLAIR).pack(side="left", padx=px(14), pady=px(8))
        creer_bouton(bandeau, "Inscription  →", self.aller_inscription, grand=False).pack(side="left", pady=px(6))

    def aller_inscription(self):
        self.module.aller_inscription()

    def _ajuster_largeur(self, evenement):
        self.centre.config(width=max(px(560), min(px(1100), evenement.width - px(24))))

    def au_affichage(self):
        self.recherche.prendre_focus()

    # --- construction ----------------------------------------------------
    def _construire_detail(self):
        d = self.detail
        d.grid_columnconfigure((0, 1), weight=1, uniform="cartes")
        d.grid_rowconfigure(1, weight=1)

        self.v = {cle: tk.StringVar() for cle in ("matricule", "nom", "sexe", "naissance", "adresse", "telephone",
                                                  "tuteur", "classe", "niveau", "option", "statut", "totaux")}
        c1 = carte(d, padx=px(18), pady=px(12))
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        titre_carte(c1, "Identité de l'élève")
        for i, (cle, lib) in enumerate((("matricule", "Matricule"), ("nom", "Nom complet"), ("sexe", "Sexe"),
                                        ("naissance", "Naissance"), ("adresse", "Adresse"),
                                        ("telephone", "Téléphone"), ("tuteur", "Tuteur / parent")), start=1):
            ligne_info(c1, i, lib, self.v[cle])

        c2 = carte(d, padx=px(18), pady=px(12))
        c2.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))
        titre_carte(c2, "Scolarité")
        tk.Label(c2, text="Année scolaire", font=police(9), fg=GRIS, bg=BLANC).grid(
            row=1, column=0, sticky="e", padx=(0, px(10)), pady=px(2))
        self.var_annee = tk.StringVar()
        self.cb_annee = ttk.Combobox(c2, textvariable=self.var_annee, state="readonly", width=14, font=police(11))
        self.cb_annee.grid(row=1, column=1, sticky="w", pady=px(2))
        self.cb_annee.bind("<<ComboboxSelected>>", lambda _e: self.afficher_annee())
        for i, (cle, lib) in enumerate((("classe", "Classe"), ("niveau", "Niveau"), ("option", "Option"),
                                        ("statut", "Inscription")), start=2):
            ligne_info(c2, i, lib, self.v[cle])

        cadre, self.arbre = creer_arbre(d, [("frais", "Type de frais", 280, "w"),
                                            ("du", "Montant dû", 130, "e"), ("paye", "Montant payé", 130, "e"),
                                            ("reste", "Reste à payer", 130, "e"), ("statut", "Situation", 90, "w"),
                                            ("mode", "Façon de payer", 250, "w")], hauteur=5)
        cadre.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(px(12), px(6)))
        self.arbre.tag_configure("solde", foreground=VERT)
        self.arbre.tag_configure("partiel", foreground=ORANGE)
        self.arbre.tag_configure("impaye", foreground=ROUGE)

        tk.Label(d, textvariable=self.v["totaux"], font=police(10, gras=True), fg=NUIT, bg=BLANC, anchor="w",
                 justify="left").grid(row=2, column=0, columnspan=2, sticky="we")
        self.lbl_dette = tk.Label(d, text="", font=police(11, gras=True), bg=BLANC, anchor="w", justify="left",
                                  wraplength=px(1000))
        self.lbl_dette.grid(row=3, column=0, columnspan=2, sticky="we", pady=(px(4), px(8)))

        bas = tk.Frame(d, bg=BLANC)
        bas.grid(row=4, column=0, columnspan=2, sticky="we")
        self.btn_payer = creer_bouton(bas, "Enregistrer un paiement  →", self.aller_paiement)
        self.btn_payer.pack(side="left")
        if "paiement" not in self.module.autorises:                # pas le droit d'enregistrer : le bouton n'existe pas
            self.btn_payer.pack_forget()
        self.lbl_aide = tk.Label(bas, text="", font=police(10), fg=GRIS, bg=BLANC)
        self.lbl_aide.pack(side="left", padx=px(14))

    # --- données ---------------------------------------------------------
    def vider(self):
        self.detail.grid_remove()
        self.indication.grid()
        self.module.matricule = None

    def charger_eleve(self, matricule):
        conn = self.app.conn
        eleve = donnees.get_eleve(conn, matricule)
        if not eleve:
            return
        self.module.matricule = matricule
        self.module.mode_inscription = False
        self.inscriptions = donnees.inscriptions(conn, matricule)
        with conn:
            journaliser(conn, self.app.session.id_user, self.app.session.login, "SITUATION_CONSULTEE", matricule)

        v = self.v
        v["matricule"].set(eleve["MATRICULE"])
        v["nom"].set(donnees.nom_complet(eleve))
        v["sexe"].set({"M": "Masculin", "F": "Féminin"}.get(eleve["SEXE"], "—"))
        v["naissance"].set(f"{formater_date(eleve['DATE_NAISSANCE'])}  à  {eleve['LIEU_NAISSANCE'] or '—'}")
        v["adresse"].set(eleve["ADRESSE"] or "—")
        v["telephone"].set(eleve["TELEPHONE"] or "—")
        v["tuteur"].set(" - ".join(x for x in (eleve["NOM_TUTEUR"], eleve["TEL_TUTEUR"]) if x) or "—")

        annees = [i["ANNEESCO"] for i in self.inscriptions]
        courante = donnees.annee_courante(conn)
        if courante and courante not in annees:
            annees.insert(0, courante)                        # pour pouvoir afficher « non inscrit cette année »
        self.cb_annee["values"] = annees
        self.var_annee.set(courante if courante in annees else (annees[0] if annees else ""))
        self.indication.grid_remove()
        self.detail.grid()
        self.afficher_annee()

    def afficher_annee(self):
        conn = self.app.conn
        matricule, annee = self.module.matricule, self.var_annee.get()
        insc = next((i for i in self.inscriptions if i["ANNEESCO"] == annee), None)
        self.module.annee = annee
        vider_arbre(self.arbre)
        lignes = []
        if insc:
            self.v["classe"].set(insc["DESI_CLASSE"])
            self.v["niveau"].set(insc["DESI_NIVEAU"])
            self.v["option"].set(insc["DESI_OPTION"] or "— (pas encore en humanités)")
            self.v["statut"].set({"NOUVEAU": "Nouvel élève", "REDOUBLANT": "Redoublant", "TRANSFERT": "Transfert",
                                  "ANCIEN": "Ancien élève"}.get(insc["STATUT"], insc["STATUT"])
                                 + f"  (le {formater_date(insc['DATE_INSCRIPTION'])})")
            lignes = donnees.situation(conn, matricule, annee, insc["N_CLASSE"])
        else:
            for cle in ("classe", "niveau", "option"):
                self.v[cle].set("—")
            self.v["statut"].set(f"Non inscrit pour l'année {annee}" if annee else "Aucune inscription")

        for i, l in enumerate(lignes):
            tag = {"Soldé": "solde", "Partiel": "partiel"}.get(l.statut, "impaye")
            self.arbre.insert("", "end", iid=str(i), tags=(tag,), values=(
                l.designation, f"{argent.formater(l.du)} {l.devise}", f"{argent.formater(l.paye)} {l.devise}",
                f"{argent.formater(l.reste)} {l.devise}", l.statut, l.mode))
        totaux = donnees.totaux_par_devise(lignes)
        self.v["totaux"].set("   |   ".join(
            f"Total {d} :  dû {argent.formater(du)}  •  payé {argent.formater(p)}  •  reste {argent.formater(r)}"
            for d, (du, p, r) in totaux.items()) if totaux else
            ("Aucun frais défini pour cette classe." if insc else ""))

        dettes = donnees.dettes(conn, matricule)
        if dettes:
            self.lbl_dette.config(fg=ROUGE, text="⚠  DETTE :  " + "   ;   ".join(
                f"année {a} → {argent.formater(r)} {d}" for a, d, r in dettes))
        else:
            self.lbl_dette.config(fg=VERT, text="✔  Aucune dette : l'élève est en règle.")

        peut_payer = bool(insc and any(l.reste > 0 for l in lignes))
        definir_actif(self.btn_payer, peut_payer)
        self.lbl_aide.config(text="" if peut_payer else (
            "Paiement impossible : l'élève n'est pas inscrit pour cette année." if not insc else
            "Rien à payer : tous les frais de cette année sont soldés."))

    def aller_paiement(self):
        self.module.mode_inscription = False
        self.module.annee = self.var_annee.get()
        self.module.afficher_onglet("paiement")


# ================================================================== 2) ENREGISTREMENT DU PAIEMENT
class ZoneDefilante(tk.Frame):
    """Zone à barre de défilement verticale : le formulaire reste utilisable même sur un petit écran
    (les boutons Enregistrer / Annuler, eux, sont placés hors de cette zone et restent toujours visibles)."""

    def __init__(self, parent):
        super().__init__(parent, bg=BLANC)
        self.canvas = tk.Canvas(self, bg=BLANC, highlightthickness=0, bd=0)
        defil = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=defil.set)
        defil.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.interieur = tk.Frame(self.canvas, bg=BLANC)
        self._fenetre = self.canvas.create_window((0, 0), window=self.interieur, anchor="nw")
        self.interieur.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._fenetre, width=e.width))
        self.bind("<Enter>", self._entree)
        self.bind("<Leave>", self._sortie)

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
        if self.interieur.winfo_reqheight() <= self.canvas.winfo_height():
            return
        if getattr(evenement, "num", None) == 4:
            pas = -1
        elif getattr(evenement, "num", None) == 5:
            pas = 1
        else:
            pas = -1 if evenement.delta > 0 else 1
        self.canvas.yview_scroll(pas * 2, "units")


class PanneauPaiement(tk.Frame):
    """Deux façons d'enregistrer un paiement : pour un élève inscrit (venu de la consultation) ou, avec le bouton
    « Inscription », pour une personne pas encore élève qui paie ses frais d'inscription (reçu sans matricule)."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.insc, self.a_payer, self.dernier_recu = {}, [], None
        self.mode = "eleve"                                    # "eleve" | "inscription"
        self.erreur_perc = ""
        self.frais_insc = []                                   # [(codtf, désignation, montant, devise)]
        self.classes_insc = []                                 # [(n_classe, libellé)]

        # --- message affiché tant qu'aucun élève n'a été consulté
        self.vide = tk.Frame(self, bg=BLANC)
        tk.Label(self.vide, text="Aucun élève sélectionné.\nConsultez d'abord la situation de l'élève, ou payez les "
                                 "frais d'inscription d'une personne pas encore inscrite.",
                 font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=(px(60), px(18)))
        creer_bouton(self.vide, "Aller à la consultation", lambda: module.afficher_onglet("consultation")).pack()
        creer_bouton(self.vide, "Inscription", module.aller_inscription, style="secondaire").pack(pady=(px(12), 0))

        # --- formulaire : message et boutons EN BAS, toujours visibles ; les champs défilent au-dessus
        self.form = tk.Frame(self, bg=BLANC)
        boutons = tk.Frame(self.form, bg=BLANC)
        boutons.pack(side="bottom", fill="x", padx=px(24), pady=(px(6), px(12)))
        tk.Frame(self.form, bg=BORDURE, height=1).pack(side="bottom", fill="x")
        self.lbl_message = tk.Label(self.form, text="", font=police(11, gras=True), bg=BLANC, anchor="w",
                                    justify="left", wraplength=px(900))
        self.lbl_message.pack(side="bottom", fill="x", padx=px(26), pady=(px(4), px(4)))
        self.zone = ZoneDefilante(self.form)
        self.zone.pack(side="top", fill="both", expand=True)
        self.btn_enregistrer = creer_bouton(boutons, "Enregistrer", self.enregistrer)
        self.btn_enregistrer.pack(side="left", padx=(0, px(10)))
        self.btn_imprimer = creer_bouton(boutons, "Imprimer le reçu", self.imprimer, style="secondaire")
        self.btn_imprimer.pack(side="left", padx=(0, px(10)))
        self.btn_annuler = creer_bouton(boutons, "Annuler", self.preparer, style="danger")
        self.btn_annuler.pack(side="left", padx=(0, px(10)))
        self.btn_bascule = creer_bouton(boutons, "Inscription", self.basculer, style="secondaire")
        self.btn_bascule.pack(side="left", padx=(px(20), 0))
        bouton_menu(boutons, self.app).pack(side="right")

        self._construire_carte_eleve(self.zone.interieur)
        self._construire_carte_inscription(self.zone.interieur)

    # --- construction des deux cartes -------------------------------------
    def _construire_carte_eleve(self, parent):
        self.carte_eleve = carte(parent, padx=px(28), pady=px(16))
        boite = self.carte_eleve
        tk.Label(boite, text="Enregistrement du paiement", font=police(16, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w", pady=(0, px(10)))
        colonnes = tk.Frame(boite, bg=BLANC)
        colonnes.pack(fill="x")
        colonnes.grid_columnconfigure((0, 1), weight=1, uniform="col")
        gauche, droite = tk.Frame(colonnes, bg=BLANC), tk.Frame(colonnes, bg=BLANC)
        gauche.grid(row=0, column=0, sticky="new", padx=(0, px(20)))
        droite.grid(row=0, column=1, sticky="new", padx=(px(20), 0))

        self.vars = {k: tk.StringVar() for k in ("eleve", "matricule", "classe", "option", "devise", "reste",
                                                  "montant", "percepteur", "date", "annee", "frais", "mode")}
        self._lecture(gauche, "Élève", "eleve")
        self._lecture(gauche, "Matricule", "matricule")
        self.cb_annee = self._liste(gauche, "Année scolaire", "annee", self.maj_annee)
        self._lecture(gauche, "Classe", "classe")
        self.cadre_option = tk.Frame(gauche, bg=BLANC)                  # visible seulement si l'élève a une option
        self._lecture(self.cadre_option, "Option", "option")

        self.cb_frais = self._liste(droite, "Type de frais", "frais", self.maj_frais)
        self._lecture(droite, "Devise", "devise")
        self._lecture(droite, "Reste à payer pour ce frais", "reste")
        self._lecture(droite, "Façon de payer ce frais", "mode")
        tk.Label(droite, text="Montant à payer", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        self.champ_montant = creer_champ(droite, self.vars["montant"])
        self.champ_montant.pack(fill="x", ipady=px(6), pady=(px(3), px(10)))
        self._lecture(droite, "N° Percepteur", "percepteur")
        self._lecture(droite, "Date du paiement", "date")

    def _construire_carte_inscription(self, parent):
        self.carte_insc = carte(parent, padx=px(28), pady=px(16))
        boite = self.carte_insc
        tk.Label(boite, text="Paiement des frais d'inscription", font=police(16, gras=True, titre=True), fg=NUIT,
                 bg=BLANC).pack(anchor="w")
        tk.Label(boite, text="Pour une personne pas encore inscrite : elle n'a pas de matricule. Le reçu qu'elle recevra "
                             "servira au secrétaire pour remplir sa candidature (module Inscription).",
                 font=police(10), fg=GRIS, bg=BLANC, justify="left", wraplength=px(860)).pack(anchor="w", pady=(px(2), px(10)))
        colonnes = tk.Frame(boite, bg=BLANC)
        colonnes.pack(fill="x")
        colonnes.grid_columnconfigure((0, 1), weight=1, uniform="col")
        gauche, droite = tk.Frame(colonnes, bg=BLANC), tk.Frame(colonnes, bg=BLANC)
        gauche.grid(row=0, column=0, sticky="new", padx=(0, px(20)))
        droite.grid(row=0, column=1, sticky="new", padx=(px(20), 0))

        self.vi = {k: tk.StringVar() for k in ("nom", "postnom", "prenom", "annee", "classe", "frais", "montant",
                                                "devise", "percepteur", "date")}
        self.champs_insc = []                                           # champs de saisie, verrouillés après l'enregistrement
        for libelle, cle in (("Nom du candidat  (obligatoire)", "nom"), ("Postnom", "postnom"), ("Prénom", "prenom")):
            tk.Label(gauche, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
            champ = creer_champ(gauche, self.vi[cle])
            champ.pack(fill="x", ipady=px(6), pady=(px(3), px(10)))
            self.champs_insc.append(champ)
            if cle == "nom":
                self.champ_nom_insc = champ
        self.cb_annee_insc = self._liste(gauche, "Année scolaire", "annee", self.maj_frais_insc, self.vi)
        self.cb_classe_insc = self._liste(gauche, "Classe souhaitée", "classe", self.maj_frais_insc, self.vi)

        self.cb_frais_insc = self._liste(droite, "Type de frais d'inscription", "frais", self.maj_frais_insc, self.vi)
        self._lecture(droite, "Montant à payer (payé en une seule fois)", "montant", self.vi)
        self._lecture(droite, "Devise", "devise", self.vi)
        self._lecture(droite, "N° Percepteur", "percepteur", self.vi)
        self._lecture(droite, "Date du paiement", "date", self.vi)

    # --- petits constructeurs --------------------------------------------
    def _lecture(self, parent, libelle, cle, variables=None):
        tk.Label(parent, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        creer_champ(parent, (variables or self.vars)[cle], lecture_seule=True).pack(fill="x", ipady=px(6), pady=(px(3), px(10)))

    def _liste(self, parent, libelle, cle, quand_change, variables=None):
        tk.Label(parent, text=libelle, font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        combo = ttk.Combobox(parent, textvariable=(variables or self.vars)[cle], state="readonly", font=police(11))
        combo.pack(fill="x", ipady=px(3), pady=(px(3), px(10)))
        combo.bind("<<ComboboxSelected>>", lambda _e: quand_change())
        return combo

    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _verrouiller(self, verrouille):
        """Après un paiement enregistré : les champs sont figés et seul « Imprimer le reçu » reste possible."""
        if self.mode == "inscription":
            for combo in (self.cb_annee_insc, self.cb_classe_insc, self.cb_frais_insc):
                combo.config(state="disabled" if verrouille else "readonly")
            for champ in self.champs_insc:
                champ.config(state="disabled" if verrouille else "normal")
            definir_actif(self.btn_enregistrer, not verrouille and bool(self.frais_insc) and not self.erreur_perc)
        else:
            self.cb_annee.config(state="disabled" if verrouille else "readonly")
            self.cb_frais.config(state="disabled" if verrouille else "readonly")
            self.champ_montant.config(state="disabled" if verrouille else "normal")
            definir_actif(self.btn_enregistrer, not verrouille and bool(self.a_payer) and not self.erreur_perc)
        definir_actif(self.btn_imprimer, verrouille)
        definir_actif(self.btn_annuler, True)

    # --- cycle de vie ------------------------------------------------------
    def au_affichage(self):
        self.preparer()

    def basculer(self):
        """Bouton du bas : passe du paiement d'un élève inscrit au paiement d'inscription, et inversement."""
        if self.mode == "inscription":
            self.module.mode_inscription = False
            if not self.module.matricule:
                self.module.afficher_onglet("consultation")
                return
        else:
            self.module.mode_inscription = True
        self.preparer()

    def preparer(self):
        mod = self.module
        self.dernier_recu = None
        self.erreur_perc = ""
        if mod.mode_inscription:
            self.mode = "inscription"
        elif mod.matricule:
            self.mode = "eleve"
        else:
            self.mode = "vide"
            self.form.pack_forget()
            self.vide.pack(fill="both", expand=True)
            return
        self.vide.pack_forget()
        self.form.pack(fill="both", expand=True)
        try:
            n_perc = paiements.numero_percepteur(self.app.conn, self.app.session)
            texte_perc = f"N° {n_perc}  -  {self.app.session.nom_complet}"
        except (paiements.ErreurPaiement, PermissionError) as e:
            texte_perc, self.erreur_perc = "—", str(e)
        if self.mode == "inscription":
            self._preparer_inscription(texte_perc)
        else:
            self._preparer_eleve(texte_perc)
        self._verrouiller(False)
        if self.erreur_perc:
            self._message(self.erreur_perc)

    def _preparer_eleve(self, texte_perc):
        mod, conn = self.module, self.app.conn
        self.carte_insc.pack_forget()
        self.carte_eleve.pack(fill="x", padx=px(24), pady=(px(12), px(8)))
        self.btn_bascule.config(text="Inscription")
        eleve = donnees.get_eleve(conn, mod.matricule)
        self.insc = {i["ANNEESCO"]: i for i in donnees.inscriptions(conn, mod.matricule)}
        self.vars["eleve"].set(donnees.nom_complet(eleve))
        self.vars["matricule"].set(eleve["MATRICULE"])
        self.vars["date"].set(datetime.now().strftime("%d/%m/%Y"))
        self.vars["percepteur"].set(texte_perc)
        annees = list(self.insc)
        self.cb_annee["values"] = annees
        self.vars["annee"].set(mod.annee if mod.annee in self.insc else (annees[0] if annees else ""))
        self.maj_annee()

    def _preparer_inscription(self, texte_perc):
        conn = self.app.conn
        self.carte_eleve.pack_forget()
        self.carte_insc.pack(fill="x", padx=px(24), pady=(px(12), px(8)))
        self.btn_bascule.config(text="Élève déjà inscrit")
        for cle in ("nom", "postnom", "prenom", "frais", "montant", "devise"):
            self.vi[cle].set("")
        self.vi["date"].set(datetime.now().strftime("%d/%m/%Y"))
        self.vi["percepteur"].set(texte_perc)
        annees = inscription.annees_proposees(conn)
        self.cb_annee_insc["values"] = annees
        courante = donnees.annee_courante(conn)
        self.vi["annee"].set(courante if courante in annees else (annees[0] if annees else ""))
        self.classes_insc = inscription.classes_proposees(conn, self.app.session)
        self.cb_classe_insc["values"] = [libelle for _n, libelle in self.classes_insc]
        self.vi["classe"].set("")
        self.cb_frais_insc["values"] = []
        self.frais_insc = []
        self._message("Saisissez le nom du candidat et choisissez la classe souhaitée : le montant s'affiche tout seul.", GRIS)
        self.champ_nom_insc.focus_set()

    def _classe_insc(self):
        libelle = self.vi["classe"].get()
        return next((n for n, texte in self.classes_insc if texte == libelle), None)

    def maj_frais_insc(self):
        """Recalcule les frais d'inscription proposés (selon l'année et la classe choisies)."""
        annee, n_classe = self.vi["annee"].get(), self._classe_insc()
        precedent = self.vi["frais"].get()
        self.frais_insc = paiements.frais_inscription_pour_classe(self.app.conn, annee, n_classe) if (annee and n_classe) else []
        libelles = [f"{designation}   -   {argent.formater(montant)} {devise}"
                    for _c, designation, montant, devise in self.frais_insc]
        self.cb_frais_insc["values"] = libelles
        if libelles:
            self.cb_frais_insc.current(libelles.index(precedent) if precedent in libelles else 0)
            _c, _d, montant, devise = self.frais_insc[self.cb_frais_insc.current()]
            self.vi["montant"].set(argent.formater(montant))
            self.vi["devise"].set(devise)
            if self.lbl_message.cget("fg") != VERT:
                self._message("")
        else:
            self.vi["frais"].set("")
            self.vi["montant"].set("")
            self.vi["devise"].set("")
            if n_classe:
                self._message("Aucun frais d'inscription n'est défini pour cette classe. L'Administrateur doit marquer un type "
                              "de frais comme « frais d'inscription » et lui donner un montant (Travaux techniques > "
                              "Mise à jour des tables > Types de frais / Tarifs).")
        self._verrouiller(False)

    def maj_annee(self):
        annee = self.vars["annee"].get()
        insc = self.insc.get(annee)
        self.a_payer = []
        self.cb_frais["values"] = []
        self.vars["frais"].set("")
        for cle in ("devise", "reste", "montant", "mode"):
            self.vars[cle].set("")
        self.cadre_option.pack_forget()
        if not insc:
            self.vars["classe"].set("—")
            self._message("Cet élève n'est inscrit pour aucune année : paiement impossible.")
            self._verrouiller(False)
            return
        self.vars["classe"].set(insc["DESI_CLASSE"])
        self.vars["option"].set(insc["DESI_OPTION"] or "")
        if insc["DESI_OPTION"]:                                         # l'élève est déjà en humanités
            self.cadre_option.pack(fill="x")
        lignes = donnees.situation(self.app.conn, self.module.matricule, annee, insc["N_CLASSE"])
        self.a_payer = [l for l in lignes if l.reste > 0]
        self.cb_frais["values"] = [
            f"{l.designation}"
            + f"   -   reste {argent.formater(l.reste)} {l.devise}" for l in self.a_payer]
        if self.a_payer:
            self.cb_frais.current(0)
            self.maj_frais()
            self._message("")
        else:
            self._message("Aucun frais restant à payer pour cette année : tout est soldé.", VERT)
        self._verrouiller(False)

    def maj_frais(self):
        index = self.cb_frais.current()
        if index < 0 or index >= len(self.a_payer):
            return
        ligne = self.a_payer[index]
        self.vars["devise"].set(ligne.devise)                            # la devise est imposée par le tarif
        self.vars["reste"].set(f"{argent.formater(ligne.reste)} {ligne.devise}")
        self.vars["mode"].set(ligne.mode)
        # proposé par défaut : la prochaine tranche (ou le reste d'un frais payé en une fois) ; modifiable
        self.vars["montant"].set(argent.formater(ligne.prochain_montant if ligne.prochain_montant else ligne.reste))
        if ligne.tranches_mal_definies:
            self._message("Les tranches de ce frais ne sont pas définies pour cette classe : demandez à l'Administrateur "
                          "de les compléter (Travaux techniques > Mise à jour des tables > Tarifs).")
        elif ligne.par_tranche:
            self._message(f"Frais payé par tranches : reste de la tranche {argent.formater(ligne.prochain_montant)} {ligne.devise} "
                          f"(vous pouvez payer moins : la tranche restera ouverte).", GRIS)
        else:
            self._message("")

    # --- actions -----------------------------------------------------------
    def enregistrer(self):
        if self.mode == "inscription":
            self._enregistrer_inscription()
        else:
            self._enregistrer_eleve()

    def _enregistrer_inscription(self):
        nom = self.vi["nom"].get().strip()
        if not nom:
            self._message("Saisissez le nom du candidat.")
            self.champ_nom_insc.focus_set()
            return
        n_classe = self._classe_insc()
        if not n_classe:
            self._message("Choisissez la classe dans laquelle le candidat souhaite être inscrit.")
            return
        index = self.cb_frais_insc.current()
        if index < 0 or index >= len(self.frais_insc):
            self._message("Aucun frais d'inscription à payer : choisissez l'année et la classe.")
            return
        codtf, designation, montant, devise = self.frais_insc[index]
        annee = self.vi["annee"].get()
        identite = " ".join(self.vi[c].get().strip() for c in ("nom", "postnom", "prenom") if self.vi[c].get().strip())
        question = (f"Enregistrer ce paiement d'inscription ?\n\nCandidat : {identite.upper()}\n"
                    f"Année : {annee}\nClasse souhaitée : {self.vi['classe'].get()}\n"
                    f"Frais : {designation}\nMontant : {argent.formater(montant)} {devise}")
        if not messagebox.askyesno("Confirmer le paiement", question, parent=self):
            return
        try:
            self.dernier_recu = paiements.enregistrer_paiement_inscription(
                self.app.conn, self.app.session, annee, n_classe, codtf, montant,
                self.vi["nom"].get(), self.vi["postnom"].get(), self.vi["prenom"].get())
        except (paiements.ErreurPaiement, PermissionError) as erreur:
            self._message(str(erreur))
            return
        self._verrouiller(True)
        self._message(f"✔  Paiement d'inscription enregistré. Reçu N° {self.dernier_recu} : cliquez sur « Imprimer le reçu », "
                      f"puis envoyez le candidat chez le secrétaire avec ce reçu.", VERT)

    def _enregistrer_eleve(self):
        index = self.cb_frais.current()
        if index < 0 or index >= len(self.a_payer):
            self._message("Choisissez le type de frais à payer.")
            return
        ligne = self.a_payer[index]
        try:
            centimes = argent.vers_centimes(self.vars["montant"].get())
        except ValueError as erreur:
            self._message(str(erreur))
            return
        if centimes <= 0:
            self._message("Le montant doit être supérieur à zéro.")
            return
        if centimes > ligne.reste:
            self._message(f"Le montant dépasse le reste à payer ({argent.formater(ligne.reste)} {ligne.devise}).")
            return
        question = (f"Enregistrer ce paiement ?\n\nÉlève : {self.vars['eleve'].get()}\n"
                    f"Année : {ligne.annee}\nFrais : {ligne.designation}\n"
                    f"Montant : {argent.formater(centimes)} {ligne.devise}")
        if not messagebox.askyesno("Confirmer le paiement", question, parent=self):
            return
        try:
            self.dernier_recu = paiements.enregistrer_paiement(
                self.app.conn, self.app.session, self.module.matricule, ligne.annee, ligne.codtf, centimes)
        except (paiements.ErreurPaiement, PermissionError) as erreur:
            self._message(str(erreur))
            return
        self._verrouiller(True)
        self._message(f"✔  Paiement enregistré. Reçu N° {self.dernier_recu} : cliquez sur « Imprimer le reçu ».", VERT)

    def imprimer(self):
        if self.dernier_recu:
            imprimer_recu(self.app, self, self.dernier_recu, duplicata=False)


# ================================================================== 3) DUPLICATA
class PanneauDuplicata(tk.Frame):
    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.recherche = ZoneRecherche(self, self.app, self.charger_eleve, self.vider)
        self.recherche.pack(fill="x", padx=px(24), pady=(px(14), px(6)))

        self.corps = tk.Frame(self, bg=BLANC)
        self.corps.pack(fill="both", expand=True, padx=px(24), pady=(px(6), px(14)))
        self.lbl_eleve = tk.Label(self.corps, text="Saisissez le nom ou le matricule de l'élève pour retrouver ses reçus.",
                                  font=police(12, gras=True), fg=GRIS, bg=BLANC, anchor="w")
        self.lbl_eleve.pack(fill="x", pady=(0, px(8)))
        cadre, self.arbre = creer_arbre(self.corps, [("recu", "N° Reçu", 130, "w"), ("date", "Date", 140, "w"),
                                                      ("annee", "Année", 110, "w"), ("frais", "Type de frais", 300, "w"),
                                                      ("montant", "Montant payé", 150, "e"), ("statut", "Statut", 100, "w")],
                                        hauteur=8)
        cadre.pack(fill="both", expand=True)
        self.arbre.bind("<<TreeviewSelect>>", self._selection)
        self.arbre.bind("<Double-1>", lambda _e: self.imprimer())
        self.arbre.tag_configure("annule", foreground=GRIS)

        bas = tk.Frame(self.corps, bg=BLANC)
        bas.pack(fill="x", pady=(px(10), 0))
        self.btn_imprimer = creer_bouton(bas, "Imprimer le duplicata", self.imprimer)
        self.btn_imprimer.pack(side="left")
        definir_actif(self.btn_imprimer, False)
        tk.Label(bas, text="Sélectionnez un reçu dans la liste (double-clic pour imprimer directement).",
                 font=police(10), fg=GRIS, bg=BLANC).pack(side="left", padx=px(14))
        bouton_menu(bas, self.app).pack(side="right")

    def au_affichage(self):
        self.recherche.prendre_focus()

    def vider(self):
        vider_arbre(self.arbre)
        self.lbl_eleve.config(text="Saisissez le nom ou le matricule de l'élève pour retrouver ses reçus.", fg=GRIS)
        definir_actif(self.btn_imprimer, False)

    def charger_eleve(self, matricule):
        conn = self.app.conn
        eleve = donnees.get_eleve(conn, matricule)
        recus = paiements.recus_eleve(conn, matricule)
        paiements.journaliser_consultation_recus(conn, self.app.session, matricule)
        vider_arbre(self.arbre)
        definir_actif(self.btn_imprimer, False)
        for r in recus:
            frais = r["DESITF"]
            self.arbre.insert("", "end", iid=r["N_RECU"], tags=("annule",) if r["STATUT"] != "VALIDE" else (), values=(
                r["N_RECU"], lire_iso(r["DATE_PAY"]).astimezone().strftime("%d/%m/%Y  %H:%M"), r["ANNEESCO"], frais,
                f"{argent.formater(r['MONT_PAYE'])} {r['CODE_DEVISE']}", "Valide" if r["STATUT"] == "VALIDE" else "Annulé"))
        titre = f"{donnees.nom_complet(eleve)}   •   matricule {eleve['MATRICULE']}"
        self.lbl_eleve.config(
            text=titre + ("" if recus else "   -   aucun reçu enregistré pour cet élève."), fg=NUIT)

    def _selection(self, _evenement=None):
        selection = self.arbre.selection()
        valide = bool(selection) and self.arbre.set(selection[0], "statut") == "Valide"
        definir_actif(self.btn_imprimer, valide)

    def imprimer(self):
        selection = self.arbre.selection()
        if selection and self.arbre.set(selection[0], "statut") == "Valide":
            imprimer_recu(self.app, self, selection[0], duplicata=True)


# ================================================================== 4) RAPPORT JOURNALIER DE CAISSE
class PanneauRapport(tk.Frame):
    """Un seul paramètre : la date. Affiche les paiements encaissés par le percepteur connecté ce jour-là,
    séparés par type de frais, puis permet d'imprimer le rapport (PDF)."""

    def __init__(self, parent, module):
        super().__init__(parent, bg=BLANC)
        self.module, self.app = module, module.app
        self.rapport = None
        self.est_percepteur = self.app.session.role == "PERCEPTEUR"
        self.var_perc = tk.StringVar()
        self.choix_perc = {}                                   # libellé affiché -> n° de percepteur (None = tous)

        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", padx=px(24), pady=(px(14), px(4)))
        tk.Label(haut, text="Date du rapport (jj/mm/aaaa) :", font=police(11, gras=True), fg=NUIT,
                 bg=BLANC).pack(side="left")
        self.var_date = tk.StringVar()
        selecteur = SelecteurDate(haut, self.var_date)
        selecteur.pack(side="left", padx=px(10))
        self.champ = selecteur.champ
        self.champ.bind("<Return>", self.afficher)
        creer_bouton(haut, "Afficher", self.afficher, grand=False).pack(side="left")
        creer_bouton(haut, "Aujourd'hui", self.aujourdhui, style="secondaire", grand=False).pack(side="left", padx=px(8))
        if not self.est_percepteur:                            # un percepteur ne voit que ses propres encaissements
            tk.Label(haut, text="Percepteur :", font=police(11, gras=True), fg=NUIT, bg=BLANC).pack(side="left", padx=(px(18), px(6)))
            self.cb_perc = ttk.Combobox(haut, textvariable=self.var_perc, state="readonly", width=34, font=police(11))
            self.cb_perc.pack(side="left")
            self.cb_perc.bind("<<ComboboxSelected>>", lambda _e: self.afficher())

        self.lbl_info = tk.Label(self, text="", font=police(10), fg=GRIS, bg=BLANC, anchor="w", justify="left")
        self.lbl_info.pack(fill="x", padx=px(24), pady=(0, px(6)))

        cadre, self.arbre = creer_arbre(self, [("n", "N°", 50, "center"), ("recu", "N° Reçu", 130, "w"),
                                               ("nom", "Nom complet", 300, "w"), ("classe", "Classe", 190, "w"),
                                               ("option", "Option", 170, "w"), ("montant", "Montant", 130, "e")],
                                        hauteur=10)
        cadre.pack(fill="both", expand=True, padx=px(24))
        self.arbre.tag_configure("groupe", background=NUIT, foreground=BLANC, font=police(10, gras=True))
        self.arbre.tag_configure("total", background=FOND_CLAIR, foreground=NUIT, font=police(10, gras=True))

        self.lbl_total = tk.Label(self, text="", font=police(12, gras=True), fg=NUIT, bg=BLANC, anchor="e")
        self.lbl_total.pack(fill="x", padx=px(24), pady=(px(8), px(4)))

        bas = tk.Frame(self, bg=BLANC)
        bas.pack(fill="x", padx=px(24), pady=(px(4), px(14)))
        self.btn_imprimer = creer_bouton(bas, "Imprimer le rapport", self.imprimer)
        self.btn_imprimer.pack(side="left")
        definir_actif(self.btn_imprimer, False)
        bouton_menu(bas, self.app).pack(side="right")

    def au_affichage(self):
        if not self.est_percepteur:
            self.choix_perc = {"Tous les percepteurs": None}
            self.choix_perc.update({f"N° {n} - {nom}": n for n, nom in paiements.liste_percepteurs(self.app.conn)})
            self.cb_perc.config(values=list(self.choix_perc))
            if self.var_perc.get() not in self.choix_perc:
                self.var_perc.set("Tous les percepteurs")
        if not self.var_date.get():
            self.aujourdhui()
        self.champ.focus_set()

    def _n_perc(self):
        return None if self.est_percepteur else self.choix_perc.get(self.var_perc.get())

    def aujourdhui(self):
        self.var_date.set(datetime.now().strftime("%d/%m/%Y"))
        self.afficher()

    def _vider(self, message, couleur=ROUGE):
        vider_arbre(self.arbre)
        self.rapport = None
        self.lbl_total.config(text="")
        self.lbl_info.config(text=message, fg=couleur)
        definir_actif(self.btn_imprimer, False)

    def afficher(self, _evenement=None):
        try:
            jour = paiements.lire_date(self.var_date.get())
            rapport = paiements.rapport_journalier(self.app.conn, self.app.session, jour, self._n_perc())
        except (paiements.ErreurPaiement, PermissionError) as erreur:
            self._vider(str(erreur))
            return
        vider_arbre(self.arbre)
        self.rapport = rapport
        if not rapport["nb_recus"]:
            self._vider(f"Aucun paiement encaissé le {rapport['date_txt']}."
                        + (f"  ({rapport['nb_annules']} reçu(s) annulé(s) non comptés.)" if rapport["nb_annules"] else ""),
                        ORANGE)
            self.rapport = rapport
            return
        for i, g in enumerate(rapport["groupes"]):
            self.arbre.insert("", "end", iid=f"g{i}", tags=("groupe",),
                              values=("", "", f"TYPE DE FRAIS :  {g['type_frais'].upper()}", "", "", ""))
            for j, l in enumerate(g["lignes"], start=1):
                self.arbre.insert("", "end", iid=f"g{i}-{j}", values=(
                    j, l["n_recu"], l["nom_complet"], l["classe"], l["option"] or "-", l["montant_txt"]))
            self.arbre.insert("", "end", iid=f"t{i}", tags=("total",), values=(
                "", "", f"Total {g['type_frais']}  ({len(g['lignes'])} reçu(s))", "", "",
                "  ;  ".join(f"{argent.formater(c)} {d}" for d, c in sorted(g["totaux"].items()))))
        self.lbl_info.config(
            fg=GRIS, text=f"{rapport['etiquette']}   •   "
                          f"{rapport['nb_recus']} reçu(s) le {rapport['date_txt']}"
                          + (f"   •   {rapport['nb_annules']} reçu(s) annulé(s) non comptés" if rapport["nb_annules"] else ""))
        self.lbl_total.config(text="TOTAL GÉNÉRAL DE LA JOURNÉE :  " + "  ;  ".join(
            f"{argent.formater(c)} {d}" for d, c in rapport["totaux"]))
        definir_actif(self.btn_imprimer, True)

    def imprimer(self):
        self.afficher()                                   # on imprime toujours ce qui correspond à la date saisie
        if self.rapport and self.rapport["nb_recus"]:
            imprimer_rapport(self.app, self, self.rapport["jour"], self._n_perc())


# ================================================================== MODULE
# onglets_autorises et motif_enregistrement_verrouille sont dans paiements.py (partagés avec la version web)
from paiements import motif_enregistrement_verrouille, onglets_autorises  # noqa: E402,F401


class ModulePaiement(tk.Frame):
    ONGLETS = (("consultation", "1   Consultation de la situation"),
               ("paiement", "2   Enregistrement du paiement"),
               ("duplicata", "3   Duplicata du reçu"),
               ("rapport", "4   Rapport journalier de caisse"))
    CLASSES = {"consultation": PanneauConsultation, "paiement": PanneauPaiement,
               "duplicata": PanneauDuplicata, "rapport": PanneauRapport}

    def __init__(self, app, onglet="consultation"):
        super().__init__(app, bg=BLANC)
        self.app = app
        self.matricule = None          # élève retenu à l'étape 1
        self.annee = None
        self.mode_inscription = False  # True : l'onglet 2 enregistre le paiement des frais d'inscription d'un candidat
        self.autorises = onglets_autorises(app.conn, app.session)

        barre = barre_haute(self, "Paiement des frais scolaires")
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        navigation = tk.Frame(self, bg=FOND_CLAIR)
        navigation.pack(fill="x")
        self.boutons = {}
        for i, (cle, texte) in enumerate(self.ONGLETS):        # les 4 onglets sont toujours visibles
            navigation.grid_columnconfigure(i, weight=1, uniform="onglet")
            verrouille = cle not in self.autorises
            b = tk.Button(navigation, text=texte + ("   (réservé)" if verrouille else ""),
                          command=lambda c=cle: self.afficher_onglet(c), relief="flat",
                          bd=0, highlightthickness=0, font=police(11, gras=True), padx=px(12), pady=px(12),
                          cursor="hand2", wraplength=px(230))
            b.grid(row=0, column=i, sticky="nsew")
            self.boutons[cle] = b
        tk.Frame(self, bg=BORDURE, height=1).pack(fill="x")

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        self.zone = self._adaptative.interieur
        self.panneaux = {cle: self.CLASSES[cle](self.zone, self) for cle, _ in self.ONGLETS if cle in self.autorises}
        self.courant = None
        self.afficher_onglet(onglet if onglet in self.panneaux else "consultation")

    def aller_inscription(self):
        """Bouton « Inscription » : ouvre l'enregistrement du paiement pour une personne pas encore inscrite."""
        if "paiement" not in self.panneaux:               # compte sans droit d'enregistrer : on explique pourquoi
            self.afficher_onglet("paiement")
            return
        self.mode_inscription = True
        self.afficher_onglet("paiement")

    def afficher_onglet(self, cle):
        if cle not in self.panneaux:                      # onglet verrouillé : on explique pourquoi, sans bouger
            if cle == "paiement":
                messagebox.showinfo("Enregistrement du paiement", motif_enregistrement_verrouille(self.app.session, self.app.conn),
                                    parent=self)
            return
        for nom, panneau in self.panneaux.items():
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
