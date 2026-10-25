"""GESTSCO en ligne : application web (Flask, WSGI). Remplace peu à peu le logiciel Windows ; réutilise toute la logique métier existante
(security, droits, modules, notes, bulletins...) : seules les pages changent.

Lancer en local :   python app_web.py            (http://127.0.0.1:5000)
Hébergeur WSGI :    from app_web import application   (voir DEPLOIEMENT.md)

Variables d'environnement :
  GESTISC_SECRET        clé secrète des cookies (sinon générée une fois dans le dossier des données)
  GESTISC_CODE_INSTALL  code exigé pour créer le premier Administrateur (obligatoire sur Internet)
  GESTISC_PROXY=1       derrière le proxy de l'hébergeur : lit l'adresse réelle du client
  GESTISC_TZ            fuseau horaire de l'école (défaut Africa/Kinshasa) : dates et heures des reçus et des rapports
  CSF_DATA_DIR          dossier de la base (college.db) et des sessions
"""
import hmac
import os
import secrets
import sys
import time
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request, url_for

import api_professeur
import config
import database
import droits
import modules
import notes
import security
import sessions_web
import web_carte
import web_controle
import web_controle_mobile
import web_encaissement
import web_inscription
import web_paiement
import web_etudes
import web_presence
import web_parents
import web_personnel
import web_travaux
import web_acces
import web_audit
import web_tableau
import tableau

COOKIE = "gestisc_session"
TITRES_MODULES = {m[0]: m[1] for m in modules.MODULES}
# Modules déjà disponibles en ligne. Les autres affichent « en cours de migration » (voir FEUILLE_DE_ROUTE.md).
MODULES_EN_LIGNE = {"paiement", "encaissement", "inscription", "carte", "controle", "personnel", "travaux", "acces", "audit", "presence_eleves", "etudes", "discipline", "prefecture", "secretariat"}


def _cle_secrete() -> bytes:
    env = os.environ.get("GESTISC_SECRET")
    if env:
        return env.encode("utf-8")
    f = config.dossier_donnees() / "cle_web.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f.read_text().strip().encode("utf-8")


def _regler_fuseau():
    """Les dates des reçus et des rapports sont celles de l'école (Kinshasa), pas celles du serveur de l'hébergeur (souvent en UTC).
    GESTISC_TZ change de fuseau ; GESTISC_TZ="" garde celui du serveur. Sans effet sous Windows (le fuseau du PC fait foi)."""
    tz = os.environ.get("GESTISC_TZ", "Africa/Kinshasa")
    if tz and hasattr(time, "tzset"):
        os.environ["TZ"] = tz
        time.tzset()


def creer_app(chemin_bd=None) -> Flask:
    _regler_fuseau()
    app = Flask(__name__, static_folder=str(config.DOSSIER_ASSETS), static_url_path="/assets")
    app.config["MAX_CONTENT_LENGTH"] = 300_000
    app.secret_key = _cle_secrete()
    app.config["CHEMIN_BD"] = chemin_bd
    if os.environ.get("GESTISC_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    def conn():
        if "conn" not in g:
            g.conn = database.connecter(app.config["CHEMIN_BD"])
        return g.conn

    @app.teardown_request
    def _fermer(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.after_request
    def _entetes(r):
        r.headers["Cache-Control"] = "no-store"
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "same-origin"      # (no-referrer ferait envoyer « Origin: null » par les navigateurs)
        r.headers["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                "script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
        if request.is_secure:
            r.headers["Strict-Transport-Security"] = "max-age=31536000"
        return r

    def _origine_ok() -> bool:
        o = request.headers.get("Origin")
        return not o or urlparse(o).netloc == request.host

    def session_courante():
        if "sess" not in g:
            g.sess = sessions_web.retrouver(conn(), request.cookies.get(COOKIE, ""), "PERSONNEL")
        return g.sess

    def connecte(f):
        @wraps(f)
        def enveloppe(*a, **k):
            s = session_courante()
            if s is None:
                return redirect(url_for("connexion"))
            if s.role == notes.ROLE_PROFESSEUR:
                return redirect(url_for("espace_professeur"))
            if s.doit_changer_mdp and request.endpoint not in ("mot_de_passe", "deconnexion"):
                return redirect(url_for("mot_de_passe"))
            return f(*a, **k)
        return enveloppe

    def _poser_cookie(rep, jeton):
        rep.set_cookie(COOKIE, jeton, httponly=True, samesite="Strict", secure=request.is_secure, path="/")
        return rep

    # ------------------------------------------------------------------ installation (premier Administrateur)
    @app.route("/installation", methods=["GET", "POST"])
    def installation():
        if not security.aucun_administrateur(conn()):
            abort(404)
        code_attendu = os.environ.get("GESTISC_CODE_INSTALL", "")
        erreur = ""
        if request.method == "POST":
            f = request.form
            if not _origine_ok():
                abort(403)
            if not code_attendu or not hmac.compare_digest(f.get("code", ""), code_attendu):
                erreur = "Code d'installation incorrect."
            elif f.get("mdp") != f.get("confirmation"):
                erreur = "Les deux mots de passe ne sont pas identiques."
            else:
                problemes = security.verifier_politique(f.get("mdp", ""), f.get("login", ""))
                if problemes:
                    erreur = "Mot de passe trop faible :\n- " + "\n- ".join(problemes)
                else:
                    try:
                        security.creer_utilisateur(conn(), f.get("login", ""), f.get("nom", "").strip() or "Administrateur",
                                                   config.ADMINISTRATEUR, f.get("mdp", ""))
                        return redirect(url_for("connexion"))
                    except ValueError as e:
                        erreur = str(e)
        return render_template("installation.html", erreur=erreur, code_requis=bool(code_attendu), cfg=config)

    # ------------------------------------------------------------------ connexion
    @app.route("/connexion", methods=["GET", "POST"])
    def connexion():
        if security.aucun_administrateur(conn()):
            return redirect(url_for("installation"))
        erreur = ""
        if request.method == "POST":
            if not _origine_ok():
                abort(403)
            adresse = request.remote_addr or "?"
            if sessions_web.trop_d_echecs(adresse):
                erreur = "Trop d'essais depuis cet appareil. Patientez quelques minutes."
            else:
                r = security.authentifier(conn(), request.form.get("login", ""), request.form.get("mdp", ""))
                if r.ok and r.session.role == notes.ROLE_PROFESSEUR:
                    erreur = "Les professeurs se connectent depuis l'espace professeurs."
                elif not r.ok:
                    sessions_web.noter_echec(adresse)
                    erreur = r.message
                    if r.secondes_blocage:
                        erreur += f" Réessayez dans {security.formater_duree(r.secondes_blocage)}."
                else:
                    jeton = sessions_web.ouvrir(r.session.id_user, "PERSONNEL")
                    return _poser_cookie(make_response(redirect(url_for("accueil"))), jeton)
        return render_template("connexion.html", erreur=erreur, cfg=config)

    @app.post("/deconnexion")
    def deconnexion():
        if not _origine_ok():
            abort(403)
        s = session_courante()
        if s:
            security.fermer_session(conn(), s)
        sessions_web.fermer(request.cookies.get(COOKIE, ""))
        rep = make_response(redirect(url_for("connexion")))
        rep.delete_cookie(COOKIE, path="/")
        return rep

    @app.route("/mot-de-passe", methods=["GET", "POST"])
    @connecte
    def mot_de_passe():
        s = session_courante()
        erreur = ""
        if request.method == "POST":
            if not _origine_ok():
                abort(403)
            try:
                security.changer_mdp(conn(), s, request.form.get("ancien", ""), request.form.get("nouveau", ""),
                                     request.form.get("confirmation", ""))
                return redirect(url_for("accueil"))
            except ValueError as e:
                erreur = str(e)
        return render_template("mot_de_passe.html", erreur=erreur, s=s, cfg=config, obligatoire=s.doit_changer_mdp)

    # ------------------------------------------------------------------ menu et modules
    @app.get("/")
    @connecte
    def accueil():
        s = session_courante()
        if tableau.peut(conn(), s):                      # comme dans le logiciel Windows : le tableau de bord est la page d'accueil
            return redirect(url_for("tableau_de_bord"))
        return menu_principal()

    @app.get("/menu")
    @connecte
    def menu():
        return menu_principal()

    def menu_principal():
        s = session_courante()
        ouverts = modules.modules_ouverts(conn(), s)
        direct = modules.module_direct(conn(), s)
        if direct:
            return redirect(url_for("module", cle=direct))
        return render_template("menu.html", s=s, cfg=config, tableau_ok=tableau.peut(conn(), s), actif="menu", modules=[(c, TITRES_MODULES[c], c in MODULES_EN_LIGNE) for c in ouverts])

    @app.get("/m/<cle>")
    @connecte
    def module(cle):
        s = session_courante()
        if cle not in modules.modules_ouverts(conn(), s):
            abort(403)
        return render_template("module.html", s=s, cfg=config, cle=cle, titre=TITRES_MODULES[cle], en_ligne=cle in MODULES_EN_LIGNE,
                               menu_utile=modules.menu_utile(conn(), s))

    # ------------------------------------------------------------------ Tableau de bord (/tableau-de-bord, page d'accueil des comptes autorisés)
    web_tableau.enregistrer(app, conn, session_courante, connecte, _origine_ok, MODULES_EN_LIGNE)

    # ------------------------------------------------------------------ module Paiement des frais (/m/paiement/...)
    web_paiement.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Encaissement des fonds perçus (/m/encaissement/...)
    web_encaissement.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Inscription (/m/inscription/...)
    web_inscription.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Carte (/m/carte/...)
    web_carte.enregistrer(app, conn, session_courante, connecte, origine_ok=_origine_ok)

    # ------------------------------------------------------------------ module Contrôle numérique (/m/controle/...)
    web_controle.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Gestion du personnel (/m/personnel/...)
    web_personnel.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Présence des élèves
    web_presence.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Gestion des études et discipline (/m/etudes_discipline/...)
    web_etudes.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Travaux techniques (/m/travaux/... et /mot-de-passe-oublie)
    web_travaux.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Gestionnaire d'accès (/m/acces/...)
    web_acces.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ module Traçabilité et audit (/m/audit/...)
    web_audit.enregistrer(app, conn, session_courante, connecte, _origine_ok)

    # ------------------------------------------------------------------ application mobile de contrôle (/controleur et /mobile/api/...)
    web_controle_mobile.enregistrer(app, conn)

    # ------------------------------------------------------------------ application mobile des parents (/parents, /parent/api/...)
    web_parents.enregistrer(app, conn)

    # ------------------------------------------------------------------ espace professeurs (page existante + son API JSON)
    @app.get("/professeur")
    def espace_professeur():
        from page_professeur import PAGE
        return PAGE

    @app.get("/professeur/manifest.webmanifest")
    def professeur_manifeste():
        """Manifeste d'installation de l'espace professeurs : nom et icône du logiciel (GESTSCO), plein écran, icône « maskable » pour Android."""
        rep = jsonify({
            "id": "/professeur", "name": "Système de Gestion Scolaire " + config.SIGLE_APP, "short_name": config.SIGLE_APP,
            "description": "Espace des professeurs : saisie des points, présences et bulletins.",
            "start_url": "/professeur", "scope": "/professeur",
            "display": "standalone", "display_override": ["standalone", "minimal-ui"],
            "background_color": "#0A1E45", "theme_color": "#0A1E45", "lang": "fr", "categories": ["education", "productivity"],
            "icons": [{"src": "/assets/gestsco_192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/assets/gestsco_512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/assets/gestsco_maskable_192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
                      {"src": "/assets/gestsco_maskable_512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]})
        rep.headers["Content-Type"] = "application/manifest+json"
        return rep

    @app.get("/professeur-sw.js")
    def professeur_sw():
        """Service worker de l'espace professeurs : application installable, écran clair hors connexion ; ne touche jamais à /api."""
        from page_professeur import SERVICE_WORKER
        rep = make_response(SERVICE_WORKER.replace("__VERSION__", config.VERSION))
        rep.headers["Content-Type"] = "text/javascript; charset=utf-8"
        rep.headers["Service-Worker-Allowed"] = "/professeur"
        return rep

    @app.route("/api/<path:chemin>", methods=["GET", "POST"])
    def api(chemin):
        adresse = request.remote_addr or "?"
        if chemin == "connexion" and request.method == "POST":
            if sessions_web.trop_d_echecs(adresse):
                return jsonify(erreur="Trop d'essais depuis cet appareil. Patientez quelques minutes."), 429
            d = request.get_json(silent=True) or {}
            r = security.authentifier(conn(), str(d.get("login", "")), str(d.get("mdp", "")), role=notes.ROLE_PROFESSEUR)
            if not r.ok:
                sessions_web.noter_echec(adresse)
                msg = r.message + (f" Réessayez dans {security.formater_duree(r.secondes_blocage)}." if r.secondes_blocage else "")
                return jsonify(erreur=msg), 401
            try:
                notes.mes_classes(conn(), r.session)
                jeton = sessions_web.ouvrir(r.session.id_user, "PROF")
            except PermissionError as e:
                return jsonify(erreur=str(e)), 403
            except (notes.ErreurNotes, RuntimeError) as e:
                return jsonify(erreur=str(e)), 503
            return jsonify(jeton=jeton, nom=r.session.nom_complet, doit_changer_mdp=r.session.doit_changer_mdp)
        h = request.headers.get("Authorization", "")
        jeton = h[7:].strip() if h.startswith("Bearer ") else ""
        s = sessions_web.retrouver(conn(), jeton, "PROF")
        if s is None:
            return jsonify(erreur="Session expirée : reconnectez-vous."), 401
        if chemin == "deconnexion":
            security.fermer_session(conn(), s)
            sessions_web.fermer(jeton)
            return jsonify(ok=True)
        d = request.get_json(silent=True) or {} if request.method == "POST" else {k: v for k, v in request.args.items()}
        if not isinstance(d, dict):
            return jsonify(erreur="Requête illisible."), 400
        try:
            res = api_professeur.traiter(conn(), s, request.method, chemin, d)
        except PermissionError as e:
            return jsonify(erreur=str(e)), 403
        except (notes.ErreurNotes, ValueError) as e:
            return jsonify(erreur=str(e)), 400
        except Exception as e:                                         # erreur inattendue : message neutre, détail dans le journal du serveur
            print("Erreur serveur :", repr(e), file=sys.stderr)
            return jsonify(erreur="Erreur du serveur."), 500
        if isinstance(res, tuple):                                     # PDF : (octets, nom du fichier)
            rep = make_response(res[0])
            rep.headers["Content-Type"] = "application/pdf"
            rep.headers["Content-Disposition"] = f'inline; filename="{res[1]}"'
            return rep
        return jsonify(res)

    @app.errorhandler(403)
    def _403(_e):
        return render_template("erreur.html", cfg=config, titre="Accès refusé", texte="Vous n'avez pas accès à cette page."), 403

    @app.errorhandler(404)
    def _404(_e):
        return render_template("erreur.html", cfg=config, titre="Page introuvable", texte="Cette page n'existe pas."), 404

    return app


application = creer_app() if __name__ != "__main__" and os.environ.get("GESTISC_SANS_APP") != "1" else None

if __name__ == "__main__":
    creer_app().run(host=os.environ.get("HOTE", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
