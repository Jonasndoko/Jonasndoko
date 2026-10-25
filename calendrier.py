"""Champ « date » de l'application : on peut TAPER la date (jj/mm/aaaa, les « / » s'ajoutent tout seuls) ou
CHOISIR dans un calendrier (bouton à droite du champ).

La logique (lecture d'un texte, mise en forme de la frappe, grille du mois) est dans saisie_date.py ; ce fichier
ne contient que l'interface Tkinter : SelecteurDate (le champ) et FenetreCalendrier (la fenêtre du calendrier).
"""
import tkinter as tk
from datetime import date
from tkinter import ttk

from saisie_date import (ANNEE_MAX, ANNEE_MIN, JOURS, MOIS, completer_frappe, decaler_mois, formater_date,
                         frappe_permise, lire_date_texte, semaines)
from theme import BLANC, BLEU_PALE, BORDURE, FOND_CLAIR, GRIS, NUIT, creer_bouton, creer_champ, police, px


# ================================================================== interface
class FenetreCalendrier(tk.Toplevel):
    """Petit calendrier : mois et année au choix (listes), flèches pour changer de mois, clic sur un jour."""

    def __init__(self, parent, depart: date, choisir, ancre=None):
        super().__init__(parent)
        self.title("Choisir une date")
        self.configure(bg=BLANC)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.choisir = choisir
        self.selection = depart
        self.annee, self.mois = depart.year, depart.month
        self.var_mois = tk.StringVar(value=MOIS[self.mois - 1])
        self.var_annee = tk.StringVar(value=str(self.annee))

        haut = tk.Frame(self, bg=BLANC)
        haut.pack(fill="x", padx=px(10), pady=(px(10), px(4)))
        tk.Button(haut, text="‹", command=lambda: self._aller(-1), relief="flat", bd=0, bg=FOND_CLAIR, fg=NUIT,
                  font=police(12, gras=True), width=3, cursor="hand2").pack(side="left")
        self.cb_mois = ttk.Combobox(haut, textvariable=self.var_mois, values=MOIS, state="readonly", width=10,
                                    font=police(11))
        self.cb_mois.pack(side="left", padx=(px(6), px(4)))
        self.cb_annee = ttk.Combobox(haut, textvariable=self.var_annee, state="readonly", width=6, font=police(11),
                                     values=[str(a) for a in range(ANNEE_MAX, ANNEE_MIN - 1, -1)])
        self.cb_annee.pack(side="left", padx=(0, px(6)))
        tk.Button(haut, text="›", command=lambda: self._aller(1), relief="flat", bd=0, bg=FOND_CLAIR, fg=NUIT,
                  font=police(12, gras=True), width=3, cursor="hand2").pack(side="left")
        self.cb_mois.bind("<<ComboboxSelected>>", self._liste_changee)
        self.cb_annee.bind("<<ComboboxSelected>>", self._liste_changee)

        self.grille = tk.Frame(self, bg=BLANC)
        self.grille.pack(padx=px(10), pady=px(4))

        bas = tk.Frame(self, bg=BLANC)
        bas.pack(fill="x", padx=px(10), pady=(px(2), px(10)))
        creer_bouton(bas, "Aujourd'hui", lambda: self._valider(date.today()), style="secondaire", grand=False
                     ).pack(side="left")
        creer_bouton(bas, "Fermer", self.destroy, style="secondaire", grand=False).pack(side="right")

        self._dessiner()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        if ancre is not None:                                   # sous le champ de saisie
            x, y = ancre.winfo_rootx(), ancre.winfo_rooty() + ancre.winfo_height() + px(2)
            x = min(x, max(0, self.winfo_screenwidth() - self.winfo_reqwidth() - px(10)))
            y = min(y, max(0, self.winfo_screenheight() - self.winfo_reqheight() - px(40)))
            self.geometry(f"+{x}+{y}")
        self.fenetre_modale = None                              # la fenêtre modale qui nous a ouverts, à rendre à la fermeture
        try:
            self.fenetre_modale = parent.grab_current()
        except tk.TclError:
            pass
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass

    def destroy(self):
        """À la fermeture, la fenêtre modale d'origine (ex. le formulaire d'un élève) reprend le contrôle."""
        modale = self.fenetre_modale
        super().destroy()
        if modale is not None:
            try:
                modale.grab_set()
            except tk.TclError:
                pass

    def _liste_changee(self, _e=None):
        self.mois = MOIS.index(self.var_mois.get()) + 1
        self.annee = int(self.var_annee.get())
        self._dessiner()

    def _aller(self, delta):
        annee, mois = decaler_mois(self.annee, self.mois, delta)
        if not ANNEE_MIN <= annee <= ANNEE_MAX:
            return
        self.annee, self.mois = annee, mois
        self.var_mois.set(MOIS[mois - 1])
        self.var_annee.set(str(annee))
        self._dessiner()

    def _valider(self, jour: date):
        self.choisir(jour)
        self.destroy()

    def _dessiner(self):
        for enfant in self.grille.winfo_children():
            enfant.destroy()
        for c, nom in enumerate(JOURS):
            tk.Label(self.grille, text=nom, font=police(10, gras=True), fg=GRIS, bg=BLANC, width=4).grid(row=0, column=c)
        aujourdhui = date.today()
        for r, semaine in enumerate(semaines(self.annee, self.mois), start=1):
            for c, jour in enumerate(semaine):
                if not jour:
                    continue
                d = date(self.annee, self.mois, jour)
                choisi, est_aujourdhui = d == self.selection, d == aujourdhui
                tk.Button(self.grille, text=str(jour), width=4, relief="flat", bd=0, cursor="hand2",
                          font=police(10, gras=choisi or est_aujourdhui),
                          bg=NUIT if choisi else (BLEU_PALE if est_aujourdhui else FOND_CLAIR),
                          fg=BLANC if choisi else NUIT, activebackground=BORDURE,
                          command=lambda d=d: self._valider(d)).grid(row=r, column=c, padx=1, pady=1)


class SelecteurDate(tk.Frame):
    """Champ de saisie de date + bouton calendrier. La valeur est le texte « jj/mm/aaaa » de `variable`.
    `self.champ` est l'entrée de texte (pour le focus)."""

    def __init__(self, parent, variable, largeur=14, lecture_seule=False, bg=BLANC):
        super().__init__(parent, bg=bg)
        self.variable = variable
        self.champ = creer_champ(self, variable, lecture_seule=lecture_seule, largeur=largeur)
        self.champ.pack(side="left", fill="x", expand=True, ipady=px(5))
        self.bouton = tk.Button(self, text="📅", command=self.ouvrir, relief="flat", bd=0, bg=FOND_CLAIR, fg=NUIT,
                                activebackground=BORDURE, font=police(12), cursor="hand2", padx=px(8))
        self.bouton.pack(side="left", fill="y", padx=(px(4), 0))
        if lecture_seule:
            self.bouton.config(state="disabled")
        else:
            self.champ.config(validate="key", validatecommand=(self.register(frappe_permise), "%P"))
            self.champ.bind("<KeyRelease>", self._apres_frappe)

    def _apres_frappe(self, evenement):
        if getattr(evenement, "keysym", "") in ("BackSpace", "Delete", "Left", "Right", "Home", "End", "Tab",
                                                "Shift_L", "Shift_R", "Control_L", "Control_R", "Return"):
            return
        texte = self.variable.get()
        suite = completer_frappe(texte)
        if suite != texte:
            self.variable.set(suite)
            self.champ.icursor("end")

    def ouvrir(self):
        depart = lire_date_texte(self.variable.get()) or date.today()
        FenetreCalendrier(self, depart, lambda d: self.variable.set(formater_date(d)), ancre=self.champ)

    def focus_set(self):
        self.champ.focus_set()
