"""Module « Contrôle numérique » en ligne (pages web). Toute la logique métier reste dans controle.py, donnees.py, sections.py et
droits.py, exactement comme dans le logiciel Windows : ici on ne fait que les pages, et on re-vérifie tout côté serveur.

Deux onglets, comme dans le logiciel :
  - Liste des élèves EN ORDRE : année scolaire, classe, option (humanités) et type de frais ; la liste s'affiche dès que les choix sont
    faits, et s'imprime en PDF ;
  - Contrôle numérique d'un élève : recherche par nom ou matricule, puis statut EN ORDRE / IMPAYÉ / NON INSCRIT avec sa situation.

Droit : la Lecture sur le module (l'Administrateur y a accès) ; sections de l'école ouvertes au compte ; chaque consultation et
chaque impression est inscrite au journal, comme dans le logiciel. Les choix en cascade (classe -> option) se font côté serveur :
choisir une classe recharge la page.
"""
from flask import abort, make_response, redirect, render_template, request, url_for

import config
import controle
import donnees
import modules
import qr
from controle import ErreurControle
from controle_pdf import TITRE_PIED

ERREURS = (ErreurControle, PermissionError)
ONGLETS = (("liste", "Liste des élèves en ordre", "/m/controle"),
           ("controle", "Contrôle numérique d'un élève", "/m/controle/eleve"))
ONGLET_MOBILE = ("mobile", "Application mobile", "/m/controle/mobile")      # seulement pour l'autorité académique autorisée
COULEURS = {controle.EN_ORDRE: "ordre", controle.IMPAYE: "impaye", controle.NON_INSCRIT: "noninscrit"}
MOTIFS = {controle.EN_ORDRE: "Aucun frais restant à payer.", controle.IMPAYE: "Il reste des frais à payer.",
          controle.NON_INSCRIT: "Pas d'inscription pour l'année en cours."}


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/controle/... à l'application. Les 4 derniers paramètres viennent d'app_web.creer_app."""

    def acces():
        s = session_courante()
        if not controle.peut(conn(), s):
            abort(403)
        return s

    def contexte(s, onglet, **plus):
        ctx = dict(s=s, cfg=config, titre="Contrôle numérique", menu_utile=modules.menu_utile(conn(), s),
                   onglets=ONGLETS + ((ONGLET_MOBILE,) if controle.peut_gerer_mobile(conn(), s) else ()), onglet=onglet)
        ctx.update(plus)
        return ctx

    # ================================================================== 1) liste des élèves en ordre
    def choix_liste(s):
        """Choix lus dans l'adresse, nettoyés d'après les listes réelles ; la cascade classe -> option est faite ici."""
        c = conn()
        annees = controle.liste_annees(c)
        classes = controle.liste_classes(c, s)
        types = controle.liste_types_frais(c)
        annee = request.args.get("annee", "")
        if annee not in annees:
            courante = donnees.annee_courante(c)
            annee = courante if (courante in annees and "annee" not in request.args) else ""
        classe = request.args.get("classe", "")
        classe = classe if classe in classes else ""
        options = controle.liste_options(c, classe) if classe else []
        option = request.args.get("option", "")
        if option not in [o[0] for o in options]:
            option = options[0][0] if len(options) == 1 else ""
        frais = request.args.get("frais", "")
        frais = frais if frais in [t[0] for t in types] else ""
        return dict(annees=annees, classes=classes, types=types, options=options, annee=annee, classe=classe, option=option, frais=frais)

    def manque(ch):
        if not (ch["annee"] and ch["classe"] and ch["frais"]):
            return "Choisissez l'année scolaire, la classe et le type de frais."
        if ch["options"] and not ch["option"]:
            return "Choisissez l'option."
        return ""

    @app.get("/m/controle")
    @connecte
    def controle_accueil():
        s = acces()
        ch = choix_liste(s)
        liste, erreur, info = None, "", manque(ch)
        if not info:
            try:
                liste = controle.eleves_en_ordre(conn(), s, ch["annee"], ch["classe"], ch["option"] or None, ch["frais"])
                if liste["sans_tarif"]:
                    info = ("Aucun tarif n'est défini pour ce frais dans cette classe (Travaux techniques > Tarifs) : "
                            "personne ne peut être en ordre.")
                elif not liste["nb_inscrits"]:
                    info = "Aucun élève inscrit dans cette classe pour cette année."
                elif not liste["lignes"]:
                    info = "Aucun élève en ordre pour ce frais."
                controle.journaliser_liste(conn(), s, liste, "LISTE_EN_ORDRE_CONSULTEE")
            except PermissionError:
                abort(403)
            except ErreurControle as e:
                erreur, info = str(e), ""
        qs = {k: ch[k] for k in ("annee", "classe", "option", "frais") if ch[k]}
        return render_template("controle_liste.html", **contexte(
            s, "liste", ch=ch, liste=liste, erreur=erreur, info=info, qs=qs, pied=TITRE_PIED,
            sous_titre=controle.ligne_classe_option(liste) if liste else ""))

    @app.get("/m/controle/liste/pdf")
    @connecte
    def controle_liste_pdf():
        s = acces()
        ch = choix_liste(s)
        if manque(ch):
            abort(400)
        try:
            liste = controle.eleves_en_ordre(conn(), s, ch["annee"], ch["classe"], ch["option"] or None, ch["frais"])
            chemin = controle.preparer_liste_pdf(conn(), s, liste)
        except PermissionError:
            abort(403)
        except ErreurControle as e:
            return render_template("erreur.html", cfg=config, titre="Impression impossible", texte=str(e)), 400
        with open(chemin, "rb") as f:
            rep = make_response(f.read())
        rep.headers["Content-Type"] = "application/pdf"
        rep.headers["Content-Disposition"] = f'inline; filename="{chemin.replace(chr(92), "/").rsplit("/", 1)[-1]}"'
        return rep

    # ================================================================== 2) contrôle d'un élève
    @app.get("/m/controle/eleve")
    @connecte
    def controle_recherche():
        s = acces()
        terme = request.args.get("q", "").strip()
        resultats, message = [], ""
        if terme:
            if len(terme) < 2:
                message = "Saisissez au moins 2 caractères."
            else:
                resultats = donnees.rechercher_eleves(conn(), terme, session=s)
                if not resultats:
                    message = f"Aucun élève trouvé pour « {terme} »."
                elif len(resultats) == 1:
                    return redirect(url_for("controle_eleve", matricule=resultats[0]["matricule"]))
        return render_template("controle_recherche.html", **contexte(s, "controle", q=terme, resultats=resultats, message=message))

    @app.get("/m/controle/eleve/<path:matricule>")
    @connecte
    def controle_eleve(matricule):
        s = acces()
        try:
            r = controle.controler_eleve(conn(), s, matricule)
        except PermissionError:
            abort(403)
        except ErreurControle:
            abort(404)
        return render_template("controle_eleve.html", **contexte(
            s, "controle", r=r, couleur=COULEURS[r["statut"]], motif=MOTIFS[r["statut"]],
            etiquettes={"Soldé": "solde", "Partiel": "partiel"}))

    # ================================================================== 3) application mobile : activation par l'autorité académique
    def lien_application():
        return request.host_url.rstrip("/") + "/controleur"

    def svg_lien(texte):
        """Code QR de l'adresse de l'application (à scanner avec le téléphone du contrôleur) ; rien si l'adresse est trop longue."""
        try:
            from web_carte import _svg_qr
            return _svg_qr(texte)
        except Exception:
            return ""

    def page_mobile(s, **plus):
        lien = lien_application()
        return render_template("controle_mobile.html", **contexte(
            s, "mobile", etat=controle.mobile_etat(conn()), lien=lien, svg=svg_lien(lien), **plus))

    @app.get("/m/controle/mobile")
    @connecte
    def controle_mobile():
        s = acces()
        if not controle.peut_gerer_mobile(conn(), s):
            abort(403)
        fait = request.args.get("fait", "")
        message = {"activer": "L'application mobile de contrôle est activée.",
                   "couper": "L'application mobile de contrôle est coupée : les téléphones connectés sont refusés."}.get(fait, "")
        return page_mobile(s, message=message)

    @app.post("/m/controle/mobile")
    @connecte
    def controle_mobile_changer():
        s = acces()
        if not origine_ok():
            abort(403)
        if not controle.peut_gerer_mobile(conn(), s):
            abort(403)
        action = request.form.get("action", "")
        if action not in ("activer", "couper"):
            abort(400)
        controle.definir_mobile(conn(), s, action == "activer")
        return redirect(url_for("controle_mobile", fait=action))
