"""Module « Présence des élèves » en ligne : consultation seule de la présence des élèves de toutes les classes (pointée par les professeurs).

Pour les comptes qui ont le droit « Lecture » sur « Présence des élèves » (Directeur de discipline, Directrice des études) ; la Direction des
études consulte la même page dans son espace (fonctionnalité « Présence des élèves », etudes_gestion.py). Les droits sont relus dans la base
à chaque requête (presence_eleves.peut_consulter) ; chaque consultation est inscrite au journal par presence_eleves.py.
"""
from flask import abort, render_template, request

import config
import etudes_gestion
import modules
import presence_eleves


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute la route /m/presence_eleves (paramètres venus d'app_web.creer_app)."""

    @app.get("/m/presence_eleves")
    @connecte
    def presence_accueil():
        s = session_courante()
        if not presence_eleves.peut_consulter(conn(), s):
            abort(403)
        ctx = etudes_gestion.contexte_presence(conn(), s, request.args, ep="presence_accueil", url={}, champs={})
        return render_template("presence_eleves.html", s=s, cfg=config, menu_utile=modules.menu_utile(conn(), s), **ctx)
