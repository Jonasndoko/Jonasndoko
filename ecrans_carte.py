"""Module « Carte » : on saisit le nom de l'élève, ses informations s'affichent ; on prend sa photo avec la caméra
(ou on importe un fichier) et on imprime sa carte (recto : logo, nom de l'école, photo, informations ; verso : QR code)."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import camera
import carte
import qr
from carte import ErreurCarte
from composants import Fenetre
from ecrans_paiement import ZoneRecherche, ligne_info, ouvrir_fichier, titre_carte
from theme import (BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, ORANGE, ROUGE, VERT, barre_haute, carte as cadre,
                   actions_barre_module, creer_bouton, definir_actif, police, px, ZoneAdaptative)

ERREURS = (ErreurCarte, PermissionError)
LARGEUR_APERCU, HAUTEUR_APERCU = 150, 200


# ================================================================== fenêtre de la caméra
class DialogueCamera(Fenetre):
    """Aperçu en direct de la caméra. Le cadre montre la zone qui sera gardée (portrait 3 : 4)."""
    L_VUE, H_VUE = 560, 420

    def __init__(self, parent, nom_eleve):
        super().__init__(parent, "Prendre la photo", largeur=620, hauteur=640)
        self.camera = None
        self.figee = None                       # image gelée après « Capturer »
        self.derniere = None
        self.image_tk = None
        self.boucle = None
        tk.Label(self.corps, text=nom_eleve, font=police(12, gras=True), fg=NUIT, bg=BLANC).pack(anchor="w")
        haut = tk.Frame(self.corps, bg=BLANC)
        haut.pack(fill="x", pady=(px(6), px(6)))
        tk.Label(haut, text="Caméra :", font=police(10, gras=True), fg=NUIT, bg=BLANC).pack(side="left")
        self.var_cam = self.variable("")
        self.liste = ttk.Combobox(haut, textvariable=self.var_cam, state="readonly", width=14, font=police(10))
        self.liste.pack(side="left", padx=px(8))
        self.liste.bind("<<ComboboxSelected>>", lambda _e: self._ouvrir(int(self.var_cam.get().split()[-1])))
        self.toile = tk.Canvas(self.corps, width=px(self.L_VUE), height=px(self.H_VUE), bg="#101820", highlightthickness=0)
        self.toile.pack()
        self.lbl = tk.Label(self.corps, text="", font=police(10), fg=ROUGE, bg=BLANC, wraplength=px(560), justify="left")
        self.lbl.pack(fill="x", pady=(px(6), 0))
        boutons = tk.Frame(self.corps, bg=BLANC)
        boutons.pack(fill="x", pady=(px(8), 0))
        self.btn_capturer = creer_bouton(boutons, "Capturer", self.capturer, grand=False)
        self.btn_capturer.pack(side="left")
        self.btn_reprendre = creer_bouton(boutons, "Reprendre", self.reprendre, style="secondaire", grand=False)
        self.btn_reprendre.pack(side="left", padx=px(8))
        self.btn_utiliser = creer_bouton(boutons, "Utiliser cette photo", self.utiliser, grand=False)
        self.btn_utiliser.pack(side="left")
        creer_bouton(boutons, "Annuler", self.destroy, style="secondaire", grand=False).pack(side="right")
        self._etat(figee=False)
        self.after(150, self._demarrer)

    def _etat(self, figee):
        definir_actif(self.btn_capturer, not figee and self.camera is not None)
        definir_actif(self.btn_reprendre, figee)
        definir_actif(self.btn_utiliser, figee)

    def _demarrer(self):
        numeros = camera.cameras_disponibles()
        if not numeros:
            self.lbl.config(text="Aucune caméra détectée. Branchez la caméra, fermez les autres programmes qui l'utilisent, "
                                 "puis rouvrez cette fenêtre.")
            return
        self.liste.config(values=[f"Caméra {n}" for n in numeros])
        self.var_cam.set(f"Caméra {numeros[0]}")
        self._ouvrir(numeros[0])

    def _ouvrir(self, index):
        if self.camera:
            self.camera.fermer()
            self.camera = None
        try:
            self.camera = camera.Camera(index)
        except RuntimeError as erreur:
            self.lbl.config(text=str(erreur))
            self._etat(False)
            return
        self.lbl.config(text="Placez le visage dans le cadre blanc, puis cliquez sur « Capturer ».", fg=GRIS)
        self.figee = None
        self._etat(False)
        if self.boucle is None:
            self._rafraichir()

    def _afficher(self, image):
        import cv2
        vue = cv2.resize(image, (self.L_VUE, self.H_VUE), interpolation=cv2.INTER_AREA)
        self.image_tk = tk.PhotoImage(data=camera.en_png_tk(vue))
        self.toile.delete("all")
        self.toile.create_image(0, 0, anchor="nw", image=self.image_tk)
        x, y, l, h = camera.zone_portrait(self.L_VUE, self.H_VUE)
        self.toile.create_rectangle(px(x), px(y), px(x + l), px(y + h), outline="white", width=2)

    def _rafraichir(self):
        self.boucle = None
        if self.figee is not None or self.camera is None:
            return
        image = self.camera.image()
        if image is not None:
            self.derniere = image
            self._afficher(image)
        self.boucle = self.after(40, self._rafraichir)

    def capturer(self):
        if self.derniere is None:
            return
        self.figee = self.derniere.copy()
        self._afficher(self.figee)
        self.lbl.config(text="Photo capturée. « Utiliser cette photo » pour l'enregistrer, ou « Reprendre ».", fg=VERT)
        self._etat(True)

    def reprendre(self):
        self.figee = None
        self.lbl.config(text="Placez le visage dans le cadre blanc, puis cliquez sur « Capturer ».", fg=GRIS)
        self._etat(False)
        if self.boucle is None:
            self._rafraichir()

    def utiliser(self):
        if self.figee is None:
            return
        try:
            self.resultat = camera.photo_vers_jpeg(self.figee)
        except RuntimeError as erreur:
            self.lbl.config(text=str(erreur), fg=ROUGE)
            return
        self.destroy()

    def destroy(self):
        if self.boucle is not None:
            try:
                self.after_cancel(self.boucle)
            except tk.TclError:
                pass
            self.boucle = None
        if self.camera:
            self.camera.fermer()
            self.camera = None
        super().destroy()


# ================================================================== module
class ModuleCarte(tk.Frame):
    CHAMPS = (("matricule", "Matricule"), ("nom_complet", "Nom complet"), ("sexe", "Sexe"), ("naissance", "Né(e) le"),
              ("lieu", "Lieu de naissance"), ("nationalite", "Nationalité"), ("adresse", "Adresse"),
              ("classe", "Classe"), ("option", "Option"), ("annee", "Année scolaire"), ("tuteur", "Tuteur"))

    def __init__(self, app):
        super().__init__(app, bg=BLANC)
        self.app = app
        self.matricule = None
        self.image_photo = None

        barre = barre_haute(self, "Carte")
        actions_barre_module(barre, app)
        tk.Label(barre, text=f"{app.session.nom_complet}  •  {app.session.libelle_role}", font=police(10),
                 fg=BLEU_PALE, bg=NUIT).pack(side="right", padx=px(8))

        self._adaptative = ZoneAdaptative(self)
        self._adaptative.pack(fill="both", expand=True)
        corps = tk.Frame(self._adaptative.interieur, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=px(24), pady=px(14))
        if not carte.peut(app.conn, app.session, "LECTURE"):
            tk.Label(corps, text="Votre compte n'a pas accès à ce module.\nDemandez à l'Administrateur de vous accorder le "
                                 "droit « Lecture » (Gestionnaire d'accès > Autorisations).",
                     font=police(13), fg=GRIS, bg=BLANC, justify="center").pack(pady=px(60))
            return

        self.recherche = ZoneRecherche(corps, app, self.charger_eleve, self.vider)
        self.recherche.pack(fill="x")

        zone = tk.Frame(corps, bg=BLANC)
        zone.pack(fill="both", expand=True, pady=(px(12), 0))
        zone.grid_columnconfigure(0, weight=3, uniform="c")
        zone.grid_columnconfigure(1, weight=2, uniform="c")
        zone.grid_rowconfigure(0, weight=1)

        # --- informations
        gauche = cadre(zone, padx=px(18), pady=px(14))
        gauche.grid(row=0, column=0, sticky="nsew", padx=(0, px(10)))
        titre_carte(gauche, "Informations de l'élève")
        self.vars = {cle: tk.StringVar(value="—") for cle, _ in self.CHAMPS}
        for i, (cle, libelle) in enumerate(self.CHAMPS, start=1):
            ligne_info(gauche, i, libelle, self.vars[cle], gras=cle in ("matricule", "nom_complet"))
        self.lbl_message = tk.Label(gauche, text="", font=police(10), fg=ROUGE, bg=BLANC, anchor="w", justify="left",
                                    wraplength=px(420))
        self.lbl_message.grid(row=len(self.CHAMPS) + 1, column=0, columnspan=2, sticky="w", pady=(px(10), 0))

        # --- photo, QR code, boutons
        droite = cadre(zone, padx=px(18), pady=px(14))
        droite.grid(row=0, column=1, sticky="nsew")
        titre_carte(droite, "Photo et code QR")
        milieu = tk.Frame(droite, bg=BLANC)
        milieu.grid(row=1, column=0, columnspan=2, sticky="w")
        self.lbl_photo = tk.Label(milieu, text="Aucune photo", font=police(10), fg=GRIS, bg=FOND_CLAIR,
                                  width=18, height=10, highlightbackground=BORDURE, highlightthickness=1)
        self.lbl_photo.pack(side="left")
        self.toile_qr = tk.Canvas(milieu, width=px(150), height=px(150), bg=BLANC, highlightbackground=BORDURE,
                                  highlightthickness=1)
        self.toile_qr.pack(side="left", padx=(px(14), 0), anchor="n")
        boutons = tk.Frame(droite, bg=BLANC)
        boutons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(px(12), 0))
        self.btn_prendre = creer_bouton(boutons, "Prendre la photo", self.prendre_photo, grand=False)
        self.btn_prendre.pack(side="left")
        self.btn_importer = creer_bouton(boutons, "Importer…", self.importer_photo, style="secondaire", grand=False)
        self.btn_importer.pack(side="left", padx=px(8))
        self.btn_retirer = creer_bouton(boutons, "Retirer", self.retirer_photo, style="secondaire", grand=False)
        self.btn_retirer.pack(side="left")
        self.var_a4 = tk.BooleanVar(value=True)
        tk.Checkbutton(droite, text="Feuille A4 (recto + verso côte à côte)\nDécochée : 2 pages au format de la carte",
                       variable=self.var_a4, font=police(9), fg=NUIT, bg=BLANC, activebackground=BLANC, justify="left",
                       anchor="w").grid(row=3, column=0, columnspan=2, sticky="w", pady=(px(14), 0))
        self.btn_imprimer = creer_bouton(droite, "IMPRIMER LA CARTE", self.imprimer, grand=True)
        self.btn_imprimer.grid(row=4, column=0, columnspan=2, sticky="w", pady=(px(8), 0))
        self.vider()
        self.recherche.prendre_focus()

    # ------------------------------------------------------------------ affichage
    def _message(self, texte, couleur=ROUGE):
        self.lbl_message.config(text=texte, fg=couleur)

    def _boutons(self):
        c, s = self.app.conn, self.app.session
        eleve = self.matricule is not None
        a_photo = eleve and carte.a_photo(c, self.matricule)
        definir_actif(self.btn_prendre, eleve and carte.peut(c, s, "MODIFICATION" if a_photo else "AJOUT"))
        definir_actif(self.btn_importer, eleve and carte.peut(c, s, "MODIFICATION" if a_photo else "AJOUT"))
        definir_actif(self.btn_retirer, a_photo and carte.peut(c, s, "SUPPRESSION"))
        definir_actif(self.btn_imprimer, eleve)

    def vider(self):
        self.matricule = None
        for v in self.vars.values():
            v.set("—")
        self._message("")
        self.image_photo = None
        self.lbl_photo.config(image="", text="Aucune photo", width=18, height=10)
        self.toile_qr.delete("all")
        self._boutons()

    def charger_eleve(self, matricule):
        try:
            f = carte.fiche(self.app.conn, self.app.session, matricule)
        except ERREURS as erreur:
            self.vider()
            self._message(str(erreur))
            return
        carte.journaliser_consultation(self.app.conn, self.app.session, matricule)
        self.matricule = matricule
        self.vars["matricule"].set(f["matricule"])
        self.vars["nom_complet"].set(f["nom_complet"])
        self.vars["sexe"].set(f["sexe_txt"] or "—")
        self.vars["naissance"].set(f["naissance"] or "—")
        self.vars["lieu"].set(f["lieu_naissance"] or "—")
        self.vars["nationalite"].set(f["nationalite"] or "—")
        self.vars["adresse"].set(f["adresse"] or "—")
        self.vars["classe"].set(f["classe"] or "Non inscrit pour l'année en cours")
        self.vars["option"].set(f["option"] or "—")
        self.vars["annee"].set(f["annee"] or "—")
        self.vars["tuteur"].set(f["tuteur"] + (f"  ({f['tel_tuteur']})" if f["tel_tuteur"] else "") if f["tuteur"] else "—")
        manquants = [lib for cle, lib in (("sexe_txt", "le sexe"), ("nationalite", "la nationalité"), ("adresse", "l'adresse"))
                     if not f[cle]]
        self._message(("Information manquante : " + ", ".join(manquants) + ". L'Administrateur la complète dans "
                       "Travaux techniques > Élèves.") if manquants else "", ORANGE)
        self._dessiner_qr(f["code_qr"])
        self._afficher_photo()
        self._boutons()

    def _dessiner_qr(self, texte):
        self.toile_qr.delete("all")
        m = qr.matrice(texte)
        n = len(m)
        cote = px(150) / (n + 4)
        for i, ligne in enumerate(m):
            for j, noir in enumerate(ligne):
                if noir:
                    self.toile_qr.create_rectangle((j + 2) * cote, (i + 2) * cote, (j + 3) * cote, (i + 3) * cote,
                                                   fill=NUIT, outline=NUIT)

    def _afficher_photo(self):
        try:
            jpeg = carte.lire_photo(self.app.conn, self.app.session, self.matricule)
        except ERREURS:
            jpeg = None
        if jpeg is None:
            self.image_photo = None
            self.lbl_photo.config(image="", text="Aucune photo", width=18, height=10)
            return
        png = camera.jpeg_vers_png_tk(jpeg, LARGEUR_APERCU, HAUTEUR_APERCU)
        if png is None:                                    # OpenCV absent : pas d'aperçu, mais la photo est bien là
            self.lbl_photo.config(image="", text="Photo enregistrée\n(aperçu : installer OpenCV)", width=18, height=10)
            return
        self.image_photo = tk.PhotoImage(data=png)
        self.lbl_photo.config(image=self.image_photo, text="", width=self.image_photo.width(),
                              height=self.image_photo.height())

    # ------------------------------------------------------------------ photo
    def _enregistrer(self, jpeg):
        try:
            carte.enregistrer_photo(self.app.conn, self.app.session, self.matricule, jpeg)
        except ERREURS as erreur:
            self._message(str(erreur))
            return
        self._message("Photo enregistrée.", VERT)
        self._afficher_photo()
        self._boutons()

    def prendre_photo(self):
        if self.matricule is None:
            return
        if not camera.disponible():
            messagebox.showinfo("Caméra", camera.MESSAGE_INSTALLATION, parent=self)
            return
        jpeg = DialogueCamera(self, self.vars["nom_complet"].get()).attendre()
        if jpeg:
            self._enregistrer(jpeg)

    def importer_photo(self):
        if self.matricule is None:
            return
        chemin = filedialog.askopenfilename(parent=self, title="Choisir la photo de l'élève",
                                            filetypes=[("Images", "*.jpg *.jpeg *.png"), ("Tous les fichiers", "*.*")])
        if not chemin:
            return
        try:
            if camera.disponible():
                jpeg = camera.photo_vers_jpeg(camera.lire_fichier(chemin))          # recadrée en portrait, 300 x 400
            else:
                with open(chemin, "rb") as f:                                      # sans OpenCV : JPEG pris tel quel
                    jpeg = f.read()
        except (ValueError, RuntimeError, OSError) as erreur:
            self._message(str(erreur))
            return
        self._enregistrer(jpeg)

    def retirer_photo(self):
        if self.matricule is None or not messagebox.askyesno("Retirer la photo", "Retirer la photo de cet élève ?", parent=self):
            return
        try:
            carte.supprimer_photo(self.app.conn, self.app.session, self.matricule)
        except ERREURS as erreur:
            self._message(str(erreur))
            return
        self._message("Photo retirée.", VERT)
        self._afficher_photo()
        self._boutons()

    # ------------------------------------------------------------------ impression
    def imprimer(self):
        if self.matricule is None:
            return
        if not carte.a_photo(self.app.conn, self.matricule) and not messagebox.askyesno(
                "Pas de photo", "Cet élève n'a pas encore de photo : la carte sera imprimée avec un cadre vide.\n\n"
                                "Imprimer quand même ?", parent=self):
            return
        try:
            chemin = carte.preparer_carte_pdf(self.app.conn, self.app.session, self.matricule, self.var_a4.get())
            ouvrir_fichier(chemin)
        except ERREURS as erreur:
            messagebox.showwarning("Impression impossible", str(erreur), parent=self)
        except OSError as erreur:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir la carte : {erreur}", parent=self)
