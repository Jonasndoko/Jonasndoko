"""Module « Carte » en ligne (pages web). Toute la logique métier reste dans carte.py, identite.py, qr.py, carte_pdf.py, sections.py et
droits.py, exactement comme dans le logiciel Windows : ici on ne fait que les pages, et on re-vérifie tout côté serveur.

Parcours : recherche de l'élève -> fiche (informations, photo, code QR) -> photo prise avec la caméra du navigateur (ou importée) ->
carte PDF (recto + verso).

Règles propres à la version web :
  - la photo est cadrée en portrait (3 : 4) et réduite à 300 x 400 DANS LE NAVIGATEUR avant l'envoi ; le serveur la contrôle et, si OpenCV
    est installé, la normalise de nouveau (une image qui n'est pas lisible est refusée) ;
  - la caméra du navigateur exige une connexion HTTPS (ou http://localhost) : c'est le cas sur l'hébergement conseillé (voir DEPLOIEMENT.md) ;
  - droits : Lecture (fiche, impression), Ajout (première photo), Modification (remplacer), Suppression (retirer) ; sections ouvertes au compte ;
  - l'ouverture d'une fiche et l'impression d'une carte sont inscrites au journal, comme dans le logiciel.
"""
from flask import abort, jsonify, make_response, redirect, render_template, request, url_for

import camera
import carte
import config
import donnees
import modules
import qr
from carte import ErreurCarte

ERREURS = (ErreurCarte, PermissionError)
MESSAGES_OK = {"photo": "Photo enregistrée.", "retiree": "Photo retirée."}


def _svg_qr(texte: str) -> str:
    """Code QR de l'élève en SVG (une seule forme, nette à toutes les tailles). Le texte est un code attribué par le logiciel."""
    m = qr.matrice(texte)
    n = len(m)
    cases = []
    for i, ligne in enumerate(m):
        j = 0
        while j < n:
            if ligne[j]:
                k = j
                while k < n and ligne[k]:
                    k += 1
                cases.append(f"M{j + 2} {i + 2}h{k - j}v1h-{k - j}z")
                j = k
            else:
                j += 1
    taille = n + 4
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {taille} {taille}" shape-rendering="crispEdges" role="img" '
            f'aria-label="Code QR de l\'élève"><rect width="{taille}" height="{taille}" fill="#fff"/>'
            f'<path d="{"".join(cases)}" fill="#0C1B3F"/></svg>')


def _normaliser(jpeg: bytes) -> bytes:
    """Contrôle la photo reçue. Avec OpenCV : décodage réel, recadrage 3 : 4 et 300 x 400 (comme le logiciel Windows)."""
    if not jpeg or jpeg[:2] != b"\xff\xd8":
        raise ErreurCarte("La photo doit être une image JPEG.")
    if not camera.disponible():
        return jpeg
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ErreurCarte("Cette photo n'est pas une image lisible.")
    return camera.photo_vers_jpeg(image)


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/carte/... à l'application. Les 4 derniers paramètres viennent d'app_web.creer_app."""

    def acces():
        s = session_courante()
        if not carte.peut(conn(), s, "LECTURE") or not _section_ok(s):
            abort(403)
        return s

    def _section_ok(s):
        import sections
        return sections.a_une_section_avec_carte(conn(), s)

    def poster():
        if not origine_ok():
            abort(403)

    def fiche_ou_erreur(s, matricule):
        """Fiche de l'élève, ou 404 (introuvable) / 403 (droit ou section refusés, primaire compris)."""
        try:
            return carte.fiche(conn(), s, matricule)
        except PermissionError:
            abort(403)
        except ErreurCarte:
            abort(404)

    def contexte(s, **plus):
        ctx = dict(s=s, cfg=config, menu_utile=modules.menu_utile(conn(), s), titre="Carte")
        ctx.update(plus)
        return ctx

    # ------------------------------------------------------------------ recherche
    @app.get("/m/carte")
    @connecte
    def carte_accueil():
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
                    return redirect(url_for("carte_eleve", matricule=resultats[0]["matricule"]))
        return render_template("carte_recherche.html", **contexte(s, q=terme, resultats=resultats, message=message))

    # ------------------------------------------------------------------ fiche, photo, QR
    @app.get("/m/carte/eleve/<path:matricule>")
    @connecte
    def carte_eleve(matricule):
        s = acces()
        f = fiche_ou_erreur(s, matricule)
        ok = request.args.get("ok", "")
        if not ok:                                              # pas de nouvelle ligne au journal quand on revient après un envoi
            carte.journaliser_consultation(conn(), s, matricule)
        c = conn()
        a_photo = f["a_photo"]
        manquants = [lib for cle, lib in (("sexe_txt", "le sexe"), ("nationalite", "la nationalité"), ("adresse", "l'adresse")) if not f[cle]]
        return render_template("carte_eleve.html", **contexte(
            s, f=f, svg_qr=_svg_qr(f["code_qr"]), manquants=manquants, message_ok=MESSAGES_OK.get(ok, ""),
            peut_photo=carte.peut(c, s, "MODIFICATION" if a_photo else "AJOUT"),
            peut_retirer=a_photo and carte.peut(c, s, "SUPPRESSION")))

    @app.get("/m/carte/eleve/<path:matricule>/photo.jpg")
    @connecte
    def carte_photo(matricule):
        s = acces()
        try:
            jpeg = carte.lire_photo(conn(), s, matricule)
        except PermissionError:
            abort(403)
        if jpeg is None:
            abort(404)
        rep = make_response(jpeg)
        rep.headers["Content-Type"] = "image/jpeg"
        return rep

    @app.post("/m/carte/eleve/<path:matricule>/photo")
    @connecte
    def carte_photo_envoyer(matricule):
        """Reçoit la photo (fichier « photo », JPEG) envoyée par la page ; répond en JSON."""
        poster()
        s = acces()
        if donnees.get_eleve(conn(), matricule) is None:
            return jsonify(erreur="Élève introuvable."), 404
        fichier = request.files.get("photo")
        try:
            jpeg = _normaliser(fichier.read() if fichier else b"")
            carte.enregistrer_photo(conn(), s, matricule, jpeg)
        except PermissionError as e:
            return jsonify(erreur=str(e)), 403
        except ErreurCarte as e:
            return jsonify(erreur=str(e)), 400
        return jsonify(ok=True, suite=url_for("carte_eleve", matricule=matricule, ok="photo"))

    @app.post("/m/carte/eleve/<path:matricule>/photo/retirer")
    @connecte
    def carte_photo_retirer(matricule):
        poster()
        s = acces()
        try:
            carte.supprimer_photo(conn(), s, matricule)
        except PermissionError:
            abort(403)
        except ErreurCarte as e:
            f = fiche_ou_erreur(s, matricule)
            return render_template("carte_eleve.html", **contexte(
                s, f=f, svg_qr=_svg_qr(f["code_qr"]), manquants=[], message_ok="", erreur=str(e),
                peut_photo=carte.peut(conn(), s, "AJOUT"), peut_retirer=False)), 400
        return redirect(url_for("carte_eleve", matricule=matricule, ok="retiree"))

    # ------------------------------------------------------------------ carte PDF
    @app.get("/m/carte/eleve/<path:matricule>/pdf")
    @connecte
    def carte_pdf_route(matricule):
        s = acces()
        a4 = request.args.get("format", "a4") != "carte"
        try:
            chemin = carte.preparer_carte_pdf(conn(), s, matricule, a4=a4)
        except PermissionError:
            abort(403)
        except ErreurCarte as e:
            if str(e) == "Élève introuvable.":
                abort(404)
            f = fiche_ou_erreur(s, matricule)
            return render_template("carte_eleve.html", **contexte(
                s, f=f, svg_qr=_svg_qr(f["code_qr"]), manquants=[], message_ok="", erreur=str(e),
                peut_photo=False, peut_retirer=False)), 400
        with open(chemin, "rb") as fichier:
            rep = make_response(fichier.read())
        rep.headers["Content-Type"] = "application/pdf"
        rep.headers["Content-Disposition"] = f'inline; filename="{chemin.replace(chr(92), "/").rsplit("/", 1)[-1]}"'
        return rep
