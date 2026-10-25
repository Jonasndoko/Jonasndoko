"""Application mobile des parents : page publique de téléchargement (/parents) et API JSON (/parent/api/...). Toute la logique est dans parents.py.

Sécurité (re-vérifiée à chaque requête) :
  - session « PARENT » à part (jeton dans l'en-tête Authorization, jamais de cookie : aucune attaque CSRF) ; un jeton de parent ne vaut rien ailleurs
    et un jeton du personnel ne vaut rien ici ;
  - l'enfant demandé doit appartenir au parent du jeton, et son accès doit être valable (reçu non annulé, année en cours) ;
  - lecture seule : aucune route ne modifie une donnée de l'école (sauf le compte du parent lui-même et l'accusé de lecture de ses convocations) ;
  - aucun PDF ni fichier : seulement des données à afficher ; l'application bloque en plus les captures d'écran ;
  - essais limités par adresse (codes et mots de passe) et par compte ; messages d'erreur volontairement peu bavards ;
  - rien d'autre que ce qui concerne l'enfant n'est renvoyé (jamais de matricule, ni de données d'autres élèves : le rang est un nombre).
"""
import sys

from flask import jsonify, make_response, redirect, render_template_string, request, send_file

import config
import convocations
import page_parents
import parents
import sessions_web
from database import journaliser
from parents import AccesRefuse, ErreurParent

NOM_APK = "application_parents.apk"

PAGE_TELECHARGEMENT = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GESTSCO Parents - {{ ecole }}</title>
<style>
 body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#f3f5fa;color:#14213d}
 main{max-width:520px;margin:0 auto;padding:28px 18px}
 .carte{background:#fff;border:1px solid #d6dbea;border-radius:14px;padding:22px}
 h1{font-size:1.35rem;margin:0 0 4px} .sous{color:#5b647a;margin:0 0 16px}
 a.bouton{display:block;text-align:center;background:#1d4ed8;color:#fff;text-decoration:none;font-weight:600;padding:14px;border-radius:10px;margin:14px 0}
 ol{padding-left:20px;line-height:1.55} .note{font-size:.85rem;color:#5b647a}
 .attente{background:#fff7e6;border:1px solid #f0d49a;border-radius:10px;padding:12px;margin:14px 0}
</style></head><body><main><div class="carte">
<h1>Application Parents</h1><p class="sous">Système de Gestion Scolaire GESTSCO · {{ ecole }}</p>
<p>Suivez à tout moment la situation de votre enfant : frais payés et dettes, présences, conduite et résultats par cours.</p>
{% if disponible %}<a class="bouton" href="/parents/telecharger">Télécharger l'application (Android)</a>
{% else %}<div class="attente">L'application n'est pas encore disponible au téléchargement. Revenez bientôt ou demandez le lien à l'école.</div>{% endif %}
<ol>
 <li>Payez à la caisse de l'école le frais du logiciel des parents : le caissier vous remet un <b>code d'accès</b> sur le reçu.</li>
 <li>Installez l'application, puis saisissez le code.</li>
 <li>Créez votre compte (nom, téléphone ou e-mail, mot de passe).</li>
 <li>Un autre enfant à l'école ? Payez pour lui à la caisse et ajoutez son nouveau code dans l'application.</li>
</ol>
<p class="note">Un code = un paiement = un enfant ; il ne s'utilise qu'une fois. Android : si le téléphone demande l'autorisation d'installer une
application de cette source, acceptez-la pour cette installation seulement.</p>
</div></main></body></html>"""


def enregistrer(app, conn):
    """Ajoute /parents et /parent/api/... à l'application (paramètre venant d'app_web.creer_app)."""

    def erreur(texte, code, **plus):
        return jsonify(erreur=texte, **plus), code

    def donnees_json():
        d = request.get_json(silent=True)
        return d if isinstance(d, dict) else {}

    def adresse():
        return request.remote_addr or "?"

    def jeton_demande():
        h = request.headers.get("Authorization", "")
        return h[7:].strip() if h.startswith("Bearer ") else ""

    def ouvrir_session(id_parent):
        c = conn()
        enfants = [{k: v for k, v in e.items() if k != "matricule_interne"} for e in parents.enfants(c, id_parent)]
        p = parents.compte(c, id_parent)
        return jsonify(jeton=sessions_web.ouvrir(id_parent, "PARENT"), parent={"nom": p["NOM_COMPLET"], "identifiant": p["IDENTIFIANT"]}, enfants=enfants,
                   convocations_non_lues=convocations.nombre_non_lues(c, id_parent))

    def public(f):
        """Route sans connexion (code, activation, connexion) : essais limités par adresse, erreurs inattendues masquées."""
        def enveloppe(*a, **k):
            if sessions_web.trop_d_echecs(adresse()):
                return erreur("Trop d'essais depuis ce téléphone. Patientez quelques minutes.", 429)
            try:
                return f(*a, **k)
            except ErreurParent as e:
                sessions_web.noter_echec(adresse())
                return erreur(str(e), 400)
            except RuntimeError as e:                                  # trop de sessions ouvertes
                return erreur(str(e), 503)
            except Exception as e:
                print("Erreur serveur (parents) :", repr(e), file=sys.stderr)
                return erreur("Erreur du serveur.", 500)
        enveloppe.__name__ = f.__name__
        return enveloppe

    def protege(f):
        """Session PARENT valide + compte actif ; f(id_parent, ...). Les accès refusés et les erreurs inattendues donnent des réponses propres."""
        def enveloppe(*a, **k):
            id_parent = sessions_web.retrouver_id(jeton_demande(), "PARENT")
            if id_parent is None or parents.compte(conn(), id_parent) is None:
                return erreur("Session expirée : reconnectez-vous.", 401)
            try:
                return f(id_parent, *a, **k)
            except AccesRefuse as e:
                return erreur(str(e), 403, acces=False)
            except ErreurParent as e:
                return erreur(str(e), 400)
            except Exception as e:
                print("Erreur serveur (parents) :", repr(e), file=sys.stderr)
                return erreur("Erreur du serveur.", 500)
        enveloppe.__name__ = f.__name__
        return enveloppe

    # ------------------------------------------------------------------ téléchargement
    def chemin_apk():
        return config.dossier_donnees() / NOM_APK

    @app.get("/parents")
    def parents_espace():
        """Espace parents en ligne (v0.59) : la page web qui utilise l'API ci-dessous."""
        rep = make_response(page_parents.PAGE.replace("__ECOLE__", config.NOM_ECOLE))
        rep.headers["Content-Type"] = "text/html; charset=utf-8"
        return rep

    @app.get("/parents/application")
    def parents_page():
        rep = make_response(render_template_string(PAGE_TELECHARGEMENT, ecole=config.NOM_ECOLE, disponible=chemin_apk().exists() or bool(config.lien_externe_parents())))
        rep.headers["Content-Type"] = "text/html; charset=utf-8"
        return rep

    @app.get("/parents/telecharger")
    def parents_telecharger():
        externe = config.lien_externe_parents()
        if externe:
            return redirect(externe)
        f = chemin_apk()
        if not f.exists():
            return redirect("/parents/application")
        return send_file(f, mimetype="application/vnd.android.package-archive", as_attachment=True, download_name="GESTSCO-Parents.apk")

    # ------------------------------------------------------------------ activation et connexion
    @app.get("/parent/api/etat")
    def parent_etat():
        return jsonify(ecole=config.NOM_ECOLE, version=config.VERSION)

    @app.post("/parent/api/code/verifier")
    @public
    def parent_code_verifier():
        return jsonify(**parents.verifier_code(conn(), donnees_json().get("code")))

    @app.post("/parent/api/inscription")
    @public
    def parent_inscription():
        d = donnees_json()
        id_parent = parents.creer_compte(conn(), d.get("code"), d.get("nom"), d.get("identifiant"), d.get("mdp"))
        return ouvrir_session(id_parent)

    @app.post("/parent/api/connexion")
    @public
    def parent_connexion():
        d = donnees_json()
        return ouvrir_session(parents.authentifier(conn(), d.get("identifiant"), d.get("mdp")))

    @app.post("/parent/api/deconnexion")
    def parent_deconnexion():
        sessions_web.fermer(jeton_demande())
        return jsonify(ok=True)

    @app.post("/parent/api/mot-de-passe")
    @protege
    def parent_mdp(id_parent):
        d = donnees_json()
        parents.changer_mdp(conn(), id_parent, d.get("ancien"), d.get("nouveau"))
        sessions_web.fermer_toutes(id_parent, "PARENT")                # les autres téléphones doivent se reconnecter
        return ouvrir_session(id_parent)

    # ------------------------------------------------------------------ enfants
    def sans_interne(e):
        return {k: v for k, v in e.items() if k != "matricule_interne"}

    @app.get("/parent/api/enfants")
    @protege
    def parent_enfants(id_parent):
        return jsonify(enfants=[sans_interne(e) for e in parents.enfants(conn(), id_parent)])

    @app.post("/parent/api/enfants")
    @protege
    def parent_enfant_ajouter(id_parent):
        if sessions_web.trop_d_echecs(adresse()):
            return erreur("Trop d'essais depuis ce téléphone. Patientez quelques minutes.", 429)
        try:
            e = parents.ajouter_enfant(conn(), id_parent, donnees_json().get("code"))
        except ErreurParent:
            sessions_web.noter_echec(adresse())
            raise
        return jsonify(enfant=sans_interne(e))

    def lecture(nom_action, fonction):
        """Route de lecture d'un enfant : vérifie l'appartenance et l'accès, puis renvoie le résultat de `fonction(conn, matricule, annee)`."""
        def route(id_parent, id_lien):
            matricule, annee = parents.enfant_autorise(conn(), id_parent, id_lien)
            return jsonify(**fonction(conn(), matricule, annee))
        route.__name__ = "parent_" + nom_action
        return route

    # ------------------------------------------------------------------ convocations (notifications de la Direction de discipline)
    @app.get("/parent/api/convocations")
    @protege
    def parent_convocations(id_parent):
        """Convocations envoyées à CE compte (pour ses enfants dont l'accès est valable) et nombre de non lues."""
        return jsonify(**convocations.pour_parent(conn(), id_parent))

    @app.post("/parent/api/convocations/<int:id_conv>/lue")
    @protege
    def parent_convocation_lue(id_parent, id_conv):
        """Accusé de lecture : la seule écriture permise au parent, limitée à ses propres convocations."""
        return jsonify(**convocations.marquer_lue(conn(), id_parent, id_conv))

    for chemin, nom, fonction in (("frais", "frais", parents.frais), ("presences", "presences", parents.presences),
                                  ("conduite", "conduite", parents.conduite), ("resultats", "resultats", parents.resultats)):
        app.add_url_rule(f"/parent/api/enfants/<int:id_lien>/{chemin}", endpoint="parent_" + nom, methods=["GET"],
                         view_func=protege(lecture(nom, fonction)))
