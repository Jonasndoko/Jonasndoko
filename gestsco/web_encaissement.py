"""Module « Encaissement des fonds perçus » en ligne (pages web). Toute la logique métier reste dans encaissements.py, argent.py et
droits.py, exactement comme dans le logiciel Windows : ici on ne fait que les pages, et on re-vérifie tout côté serveur.

Deux onglets, comme dans le logiciel :
  - Enregistrement de l'encaissement : percepteur, montant encaissé, devise, date, montant versé ; l'ÉCART est calculé par le serveur
    (encaissé - versé), jamais saisi. Réservé aux comptes qui ont le droit « Ajout » ;
  - Rapport global d'une date (tous les percepteurs) : paiements par type de frais, puis encaissements, versements et écarts ; PDF.

Règles propres à la version web :
  - l'enregistrement passe par une page de confirmation (un encaissement enregistré ne se modifie pas dans cet écran) ;
  - un double clic ne crée pas deux encaissements : si le même encaissement (percepteur, date, devise, montants) vient d'être saisi par le
    même compte il y a moins de GARDE_DOUBLE_CLIC_S secondes, on renvoie vers lui au lieu d'en créer un second.
"""
from datetime import datetime, timedelta

from flask import abort, make_response, redirect, render_template, request, url_for

import argent
import config
import encaissements
import modules
from database import lire_iso, maintenant
from encaissements import ErreurEncaissement

GARDE_DOUBLE_CLIC_S = 60

ONGLETS = (("enregistrement", "Enregistrement de l'encaissement", "/m/encaissement"),
           ("rapport", "Rapport global", "/m/encaissement/rapport"))


def onglets_autorises(conn, session) -> set:
    """Onglets utilisables par ce compte (droits relus dans la base) : même règle que le logiciel Windows."""
    if not encaissements.peut(conn, session, "LECTURE"):
        return set()
    ouverts = {"rapport"}
    if encaissements.peut(conn, session, "AJOUT"):
        ouverts.add("enregistrement")
    return ouverts


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/encaissement/... à l'application. Les 4 derniers paramètres viennent d'app_web.creer_app."""
    app.jinja_env.filters.setdefault("montant", argent.formater)

    # ------------------------------------------------------------------ utilitaires
    def contexte(onglet, **plus):
        s = session_courante()
        autorises = onglets_autorises(conn(), s)
        ctx = dict(s=s, cfg=config, titre="Encaissement des fonds perçus", menu_utile=modules.menu_utile(conn(), s),
                   autorises=autorises, onglets=ONGLETS, onglet=onglet)
        ctx.update(plus)
        return ctx

    def acces(onglet):
        """Session du compte, après vérification qu'il a le module et l'onglet. 403 sinon."""
        s = session_courante()
        if onglet not in onglets_autorises(conn(), s):
            abort(403)
        return s

    def poster():
        if not origine_ok():
            abort(403)

    def page(modele, onglet, statut=200, **plus):
        return make_response(render_template(modele, **contexte(onglet, **plus)), statut)

    def listes():
        c = conn()
        return encaissements.liste_percepteurs(c), encaissements.liste_devises(c)

    def lire_saisie(source):
        """Saisie brute du formulaire (pour la réafficher en cas d'erreur)."""
        return {k: (source.get(k) or "").strip() for k in ("perc", "devise", "date", "encaisse", "verse")}

    def valider(s, saisie):
        """(n_perc, code_devise, jour, encaisse, verse, ecart) contrôlés comme dans le logiciel ; lève ErreurEncaissement."""
        c = conn()
        n_perc = int(saisie["perc"]) if saisie["perc"].isdigit() else None
        if n_perc is None:
            raise ErreurEncaissement("Choisissez un percepteur dans la liste.")
        encaisse = encaissements.lire_montant(saisie["encaisse"], "montant encaissé")
        code = saisie["devise"]
        if not code:
            raise ErreurEncaissement("Choisissez la devise.")
        verse = encaissements.lire_montant(saisie["verse"], "montant versé", zero_permis=True)
        jour = encaissements._controler(c, saisie["date"], n_perc, code, encaisse, verse)    # mêmes contrôles que enregistrer()
        return n_perc, code, jour, encaisse, verse, encaissements.calculer_ecart(encaisse, verse)

    def formulaire(statut=200, saisie=None, erreur="", succes=""):
        percepteurs, devises = listes()
        saisie = saisie or {"perc": "", "devise": "", "date": datetime.now().strftime("%d/%m/%Y"), "encaisse": "", "verse": ""}
        avertissement = ""
        if not percepteurs:
            avertissement = ("Aucun percepteur actif : créez d'abord un compte de poste Percepteur "
                             "(Gestionnaire d'accès > Utilisateurs).")
        elif not devises:
            avertissement = "Aucune devise : l'Administrateur doit en ajouter une (Travaux techniques > Devises)."
        return page("encaissement_formulaire.html", "enregistrement", statut=statut, saisie=saisie, erreur=erreur, succes=succes,
                    percepteurs=percepteurs, devises=devises, avertissement=avertissement)

    # ================================================================== 1) ENREGISTREMENT
    @app.get("/m/encaissement")
    @connecte
    def encaissement_accueil():
        s = session_courante()
        autorises = onglets_autorises(conn(), s)
        if "enregistrement" not in autorises:
            if "rapport" in autorises:
                return redirect(url_for("encaissement_rapport"))
            abort(403)
        succes = ""
        n = request.args.get("ok", "")
        if n.isdigit() and conn().execute("SELECT 1 FROM ENCAISSEMENT WHERE N_ENC = ? AND SAISI_PAR = ?",
                                          (int(n), s.login)).fetchone():
            succes = f"Encaissement N° {n} enregistré."
            if request.args.get("deja") == "1":
                succes += " (Il venait déjà d'être enregistré : aucun doublon n'a été créé.)"
        return formulaire(succes=succes)

    @app.post("/m/encaissement/confirmer")
    @connecte
    def encaissement_confirmer():
        poster()
        s = acces("enregistrement")
        saisie = lire_saisie(request.form)
        try:
            n_perc, code, jour, encaisse, verse, ecart = valider(s, saisie)
        except (ErreurEncaissement, PermissionError) as e:
            return formulaire(400 if isinstance(e, ErreurEncaissement) else 403, saisie, str(e))
        return page("encaissement_confirmer.html", "enregistrement", saisie=saisie,
                    nom_perc=encaissements._nom_percepteur(conn(), n_perc), code=code, jour=jour, encaisse=encaisse,
                    verse=verse, ecart=ecart, nature=encaissements.etiquette_ecart(ecart))

    @app.post("/m/encaissement/enregistrer")
    @connecte
    def encaissement_enregistrer():
        poster()
        s = acces("enregistrement")
        c = conn()
        saisie = lire_saisie(request.form)
        try:
            n_perc, code, jour, encaisse, verse, _ecart = valider(s, saisie)
            limite = (maintenant() - timedelta(seconds=GARDE_DOUBLE_CLIC_S))
            recents = c.execute(
                "SELECT N_ENC, DATE_SAISIE FROM ENCAISSEMENT WHERE SAISI_PAR = ? AND DATE_ENC = ? AND N_PERC = ? AND CODE_DEVISE = ? "
                "AND MONT_ENCAISSE = ? AND MONT_VERSE = ? ORDER BY N_ENC DESC",
                (s.login, jour.isoformat(), n_perc, code, encaisse, verse)).fetchall()
            for l in recents:
                if lire_iso(l["DATE_SAISIE"]) >= limite:                     # double clic : c'est le même encaissement
                    return redirect(url_for("encaissement_accueil", ok=l["N_ENC"], deja=1))
            n_enc = encaissements.enregistrer(c, s, n_perc, jour, code, encaisse, verse)
        except (ErreurEncaissement, PermissionError) as e:
            return formulaire(400 if isinstance(e, ErreurEncaissement) else 403, saisie, str(e))
        return redirect(url_for("encaissement_accueil", ok=n_enc))

    # ================================================================== 2) RAPPORT GLOBAL
    @app.get("/m/encaissement/rapport")
    @connecte
    def encaissement_rapport():
        s = acces("rapport")
        texte_date = request.args.get("date", "").strip() or datetime.now().strftime("%d/%m/%Y")
        rapport, erreur = None, ""
        try:
            rapport = encaissements.rapport_global(conn(), s, texte_date)
        except ErreurEncaissement as e:
            erreur = str(e)
        except PermissionError:
            abort(403)
        return page("encaissement_rapport.html", "rapport", rapport=rapport, erreur=erreur, texte_date=texte_date,
                    vide=bool(rapport) and encaissements.rapport_vide(rapport))

    @app.get("/m/encaissement/rapport/pdf")
    @connecte
    def encaissement_rapport_pdf():
        s = acces("rapport")
        try:
            jour = encaissements._lire_jour(request.args.get("date", ""))
            chemin = encaissements.preparer_rapport_pdf(conn(), s, jour)
        except ErreurEncaissement as e:
            return render_template("erreur.html", cfg=config, titre="Impression impossible", texte=str(e)), 400
        except PermissionError:
            abort(403)
        with open(chemin, "rb") as f:
            rep = make_response(f.read())
        rep.headers["Content-Type"] = "application/pdf"
        rep.headers["Content-Disposition"] = f'inline; filename="Rapport_global_{jour.isoformat()}.pdf"'
        return rep
