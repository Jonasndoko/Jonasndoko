"""Application mobile de contrôle (page web installable + petite API JSON). Toute la logique reste dans controle.py.

Parcours : l'autorité académique autorisée active l'application (onglet « Application mobile » du module Contrôle numérique) ->
le contrôleur ouvre /controleur sur son téléphone, se connecte (identifiant + mot de passe), choisit un type de frais ou tous
les frais, puis contrôle chaque élève en scannant le QR de sa carte ou en tapant son matricule : la situation s'affiche.

Sécurité (tout est re-vérifié côté serveur, à chaque requête) :
  - application coupée -> plus aucune connexion, et les téléphones déjà connectés sont refusés à leur prochaine action ;
  - connexion : compte actif + droit Lecture sur le module Contrôle numérique ; mêmes blocages d'essais que le site ;
  - session « CTRL » à part (jeton dans l'en-tête Authorization, pas de cookie : aucune attaque CSRF possible) ;
  - chaque contrôle est inscrit au journal (élève, frais, statut, QR ou matricule) ; un QR n'est accepté que s'il a été délivré
    par le logiciel ; les sections de l'école ouvertes au compte sont respectées.
"""
import base64
import sys

from flask import jsonify, make_response, request

import config
import controle
import page_controleur
import qr_lecture
import security
import sessions_web
from controle import ErreurControle, ErreurMobileCoupee

COULEURS = {controle.EN_ORDRE: "ordre", controle.IMPAYE: "impaye", controle.NON_INSCRIT: "autre", controle.NON_APPLICABLE: "autre"}
MOTIFS = {controle.EN_ORDRE: "Aucun frais restant à payer.", controle.IMPAYE: "Il reste des frais à payer.",
          controle.NON_INSCRIT: "Pas d'inscription pour l'année en cours.",
          controle.NON_APPLICABLE: "Ce frais n'est pas défini pour la classe de l'élève."}


def enregistrer(app, conn):
    """Ajoute /controleur et /mobile/api/... à l'application (paramètre venant d'app_web.creer_app)."""

    def erreur(texte, code, **plus):
        return jsonify(erreur=texte, **plus), code

    def jeton_et_session():
        h = request.headers.get("Authorization", "")
        jeton = h[7:].strip() if h.startswith("Bearer ") else ""
        return jeton, sessions_web.retrouver(conn(), jeton, "CTRL")

    def exige_session():
        """(jeton, session) ; sinon (None, réponse d'erreur à renvoyer)."""
        jeton, s = jeton_et_session()
        if s is None:
            return None, erreur("Session expirée : reconnectez-vous.", 401)
        return (jeton, s), None

    def proteger(f):
        """Session CTRL valide + application activée + droit de contrôle, sinon réponse d'erreur propre ; erreurs inattendues masquées."""
        def enveloppe(*a, **k):
            ok, refus = exige_session()
            if refus:
                return refus
            jeton, s = ok
            try:
                controle.exiger_mobile(conn(), s)
                if s.doit_changer_mdp and f.__name__ != "mobile_mdp":
                    return erreur("Changez d'abord votre mot de passe.", 403)
                return f(jeton, s, *a, **k)
            except ErreurMobileCoupee as e:
                sessions_web.fermer(jeton)
                return erreur(str(e), 403, coupee=True)
            except PermissionError as e:
                return erreur(str(e), 403)
            except (ErreurControle, ValueError) as e:
                return erreur(str(e), 400)
            except Exception as e:                                    # erreur inattendue : message neutre, détail dans le journal du serveur
                print("Erreur serveur (contrôle mobile) :", repr(e), file=sys.stderr)
                return erreur("Erreur du serveur.", 500)
        enveloppe.__name__ = f.__name__
        return enveloppe

    # ------------------------------------------------------------------ la page et son manifeste (installable)
    @app.get("/controleur")
    def controleur_page():
        rep = make_response(page_controleur.PAGE.replace("__ECOLE__", config.NOM_ECOLE))
        rep.headers["Content-Type"] = "text/html; charset=utf-8"
        return rep

    @app.get("/controleur/manifest.webmanifest")
    def controleur_manifeste():
        """Manifeste d'installation : nom, icônes (dont une « maskable » pour Android), écran de démarrage, mode application."""
        rep = jsonify({
            "id": "/controleur", "name": "Contrôle numérique — " + config.NOM_ECOLE, "short_name": "Contrôle",
            "description": "Contrôle des frais des élèves : scan du QR de la carte ou matricule.",
            "start_url": "/controleur", "scope": "/controleur",
            "display": "standalone", "display_override": ["standalone", "minimal-ui"], "orientation": "portrait",
            "background_color": "#0A1E45", "theme_color": "#0A1E45", "lang": "fr", "categories": ["education", "utilities"],
            "icons": [{"src": "/assets/controleur_192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/assets/controleur_512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/assets/controleur_maskable_192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
                      {"src": "/assets/controleur_maskable_512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]})
        rep.headers["Content-Type"] = "application/manifest+json"
        return rep

    @app.get("/controleur-sw.js")
    def controleur_sw():
        """Service worker : rend l'application installable et affiche un écran clair hors connexion. Il ne touche jamais à /mobile/api."""
        rep = make_response(page_controleur.SERVICE_WORKER.replace("__VERSION__", config.VERSION))
        rep.headers["Content-Type"] = "text/javascript; charset=utf-8"
        rep.headers["Service-Worker-Allowed"] = "/controleur"
        return rep

    # ------------------------------------------------------------------ connexion
    @app.post("/mobile/api/connexion")
    def mobile_connexion():
        c = conn()
        if not controle.mobile_actif(c):                              # coupée : on ne vérifie même pas le mot de passe
            return erreur(controle.MESSAGE_MOBILE_COUPEE, 403, coupee=True)
        adresse = request.remote_addr or "?"
        if sessions_web.trop_d_echecs(adresse):
            return erreur("Trop d'essais depuis cet appareil. Patientez quelques minutes.", 429)
        d = request.get_json(silent=True)
        d = d if isinstance(d, dict) else {}
        r = security.authentifier(c, str(d.get("login", "")), str(d.get("mdp", "")))
        if not r.ok:
            sessions_web.noter_echec(adresse)
            msg = r.message + (f" Réessayez dans {security.formater_duree(r.secondes_blocage)}." if r.secondes_blocage else "")
            return erreur(msg, 401)
        if not controle.peut(c, r.session):
            security.fermer_session(c, r.session)
            return erreur("Ce compte n'a pas le droit de faire le contrôle. Adressez-vous à l'Administrateur.", 403)
        try:
            jeton = sessions_web.ouvrir(r.session.id_user, "CTRL")
        except RuntimeError as e:
            return erreur(str(e), 503)
        with c:
            from database import journaliser
            journaliser(c, r.session.id_user, r.session.login, "CONTROLE_MOBILE_CONNEXION", "")
        return jsonify(jeton=jeton, nom=r.session.nom_complet, poste=r.session.libelle_role,
                       doit_changer_mdp=r.session.doit_changer_mdp)

    @app.post("/mobile/api/mot-de-passe")
    @proteger
    def mobile_mdp(jeton, s):
        d = request.get_json(silent=True)
        d = d if isinstance(d, dict) else {}
        security.changer_mdp(conn(), s, str(d.get("ancien", "")), str(d.get("nouveau", "")), str(d.get("confirmation", "")))
        return jsonify(ok=True)

    @app.post("/mobile/api/deconnexion")
    def mobile_deconnexion():
        jeton, s = jeton_et_session()
        if s:
            security.fermer_session(conn(), s)
        sessions_web.fermer(jeton)
        return jsonify(ok=True)

    # ------------------------------------------------------------------ choix du frais, lecture du QR, contrôle
    @app.get("/mobile/api/frais")
    @proteger
    def mobile_frais(jeton, s):
        return jsonify(frais=[list(t) for t in controle.frais_pour_mobile(conn(), s)])

    @app.post("/mobile/api/decoder")
    @proteger
    def mobile_decoder(jeton, s):
        """Lecture du QR sur le serveur, pour les téléphones sans lecteur de QR dans le navigateur (OpenCV nécessaire)."""
        if not qr_lecture.disponible():
            return jsonify(code=None, indisponible=True)
        return jsonify(code=qr_lecture.lire(request.get_data(cache=False)))

    @app.post("/mobile/api/controle")
    @proteger
    def mobile_controle(jeton, s):
        d = request.get_json(silent=True)
        d = d if isinstance(d, dict) else {}
        c = conn()
        r = controle.controler_mobile(c, s, str(d.get("code", "")), str(d.get("frais", controle.TOUS_LES_FRAIS)))
        r["couleur"], r["motif"] = COULEURS[r["statut"]], MOTIFS[r["statut"]]
        jpeg = controle.photo_pour_controle(c, s, r["matricule"])
        r["photo"] = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii") if jpeg else None
        return jsonify(r)
