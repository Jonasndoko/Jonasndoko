"""Module « Traçabilité et audit » en ligne (pages web) : consultation seule. Il est ouvert à l'Administrateur et aux comptes à qui
l'Administrateur a accordé la Lecture sur ce module (Gestionnaire d'accès). Toute la logique reste dans audit.py, audit_financier.py,
audit_recherche.py, audit_rapports.py et audit_pdf.py, exactement comme dans le logiciel Windows (ecrans_audit*.py) : ici on ne fait que
les pages. Le droit est relu dans la base à chaque appel ; l'ouverture du module, les recherches ciblées, les contrôles et les
exportations sont inscrits au journal par la logique métier.

Six fonctionnalités, comme dans le logiciel Windows :
  1. Journal des activités            : qui a fait quoi, quand (filtres : période, utilisateur, catégorie, texte) ;
  2. Opérations financières           : paiements, reçus, annulations, encaissements, remises, écarts ; fiche d'une opération ;
  3. Contrôles                        : intégrité du journal (chaîne d'empreintes) et concordance avec les tables financières ;
  4. Contrôle et audit financier      : reçus, rapprochement encaissé / remis, annulations, corrections, rapports journaliers, anomalies ;
  5. Recherche et filtrage des traces : utilisateur, période, module, type d'action, n° de reçu, matricule ;
  6. Rapports d'audit                 : consultables à l'écran, exportables en PDF (à signer) et en CSV.

Particularités de la version web :
  - les filtres voyagent dans l'adresse (GET) : une recherche se garde en favori et l'exportation reprend exactement les mêmes filtres ;
  - un fichier exporté est fabriqué, envoyé au navigateur puis effacé du serveur (il ne contient que des données personnelles).
"""
import os
from datetime import date

from flask import abort, make_response, redirect, render_template, request, url_for

import argent
import audit
import audit_financier
import audit_rapports
import audit_recherche
import config
import modules
from audit import ErreurAudit
from saisie_date import lire_date_texte

LIMITE_ECRAN = 300                       # lignes montrées par section dans un rapport affiché (le PDF / CSV contient tout)
TAG_GRAVITE = {"ÉLEVÉE": "rouge", "MOYENNE": "orange", "FAIBLE": "gris"}
TAG_STATUT = {"Anomalie": "rouge", "Écart": "rouge", "À vérifier": "orange", "Conforme, modifié depuis": "orange",
              "Non comparable": "gris"}

ONGLETS = (
    ("journal", "Journal des activités", "audit_journal"),
    ("finances", "Opérations financières", "audit_finances"),
    ("controles", "Contrôles", "audit_controles"),
    ("financier", "Contrôle et audit financier", "audit_financier_page"),
    ("recherche", "Recherche et filtrage des traces", "audit_recherche_page"),
    ("rapports", "Rapports d'audit", "audit_rapports_page"),
)
TYPES_MIME = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


def _f(centimes) -> str:
    return "" if centimes is None else argent.formater(centimes)


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/audit/... à l'application (paramètres venus d'app_web.creer_app)."""

    # ------------------------------------------------------------------ utilitaires communs
    def acces():
        s = session_courante()
        if not audit.peut(conn(), s):
            abort(403)
        return s

    def arg(nom) -> str:
        return (request.args.get(nom) or "").strip()

    def jour(nom, libelle):
        """Champ date (JJ/MM/AAAA ou AAAA-MM-JJ) -> date, ou None si vide."""
        texte = arg(nom)
        if not texte:
            return None
        d = lire_date_texte(texte)
        if d is None:
            raise ErreurAudit(f"La date « {libelle} » est invalide. Écrivez-la ainsi : 08/10/2026")
        return d

    def entier(nom, message):
        texte = arg(nom)
        if not texte:
            return None
        try:
            return int(texte)
        except ValueError:
            raise ErreurAudit(message) from None

    def contexte(s, onglet, **plus):
        ctx = dict(s=s, cfg=config, titre="Traçabilité et audit", menu_utile=modules.menu_utile(conn(), s), onglet=onglet,
                   onglets=[(c, lib, url_for(ep)) for c, lib, ep in ONGLETS], erreur="", q={}, aujourdhui=date.today().isoformat())
        ctx.update(plus)
        return ctx

    def filtres_q(*noms) -> dict:
        """Filtres de la requête (valeurs non vides), pour recopier dans les liens d'exportation."""
        return {n: arg(n) for n in noms if arg(n)}

    def utilisateurs(s):
        return [(login, f"{login} - {nom}" if nom else login) for login, nom in audit.liste_utilisateurs(conn(), s)]

    def executer(s, onglet, modele, fabrique, **defauts):
        """Appelle `fabrique()` (lecture des filtres + appel métier) et rend la page ; une erreur de saisie réaffiche la page
        (avec les valeurs par défaut `defauts`, que le résultat de `fabrique()` complète ou remplace)."""
        ctx = dict(defauts)
        try:
            ctx.update(fabrique())
        except ErreurAudit as e:
            return render_template(modele, **contexte(s, onglet, **ctx, erreur=str(e))), 400
        except PermissionError:
            abort(403)
        return render_template(modele, **contexte(s, onglet, **ctx))

    @app.get("/m/audit")
    @connecte
    def audit_accueil():
        s = acces()
        audit.journaliser_ouverture(conn(), s)
        return redirect(url_for("audit_journal"))

    # ================================================================== 1) journal des activités
    @app.get("/m/audit/journal")
    @connecte
    def audit_journal():
        s = acces()
        cles = ("du", "au", "u", "cat", "texte", "fin")

        def faire():
            r = audit.journal(conn(), s, jour("du", "du"), jour("au", "au"), arg("u") or None, arg("cat") or None, arg("texte") or None,
                              arg("fin") == "1")
            return dict(r=r)
        return executer(s, "journal", "audit_journal.html", faire, q=filtres_q(*cles), v=request.args,
                        utilisateurs=utilisateurs(s), categories=audit.CATEGORIES, r=None, limite=audit.LIMITE_LIGNES)

    # ================================================================== 2) opérations financières
    @app.get("/m/audit/finances")
    @connecte
    def audit_finances():
        s = acces()
        cles = ("du", "au", "eleve", "recu", "u", "type", "ecart")

        def faire():
            r = audit.historique_financier(conn(), s, jour("du", "du"), jour("au", "au"), arg("eleve") or None, arg("recu") or None,
                                           arg("u") or None, arg("type") or None, arg("ecart") == "1")
            return dict(r=r)
        return executer(s, "finances", "audit_finances.html", faire, q=filtres_q(*cles), v=request.args,
                        utilisateurs=utilisateurs(s), types=audit.TYPES_OPERATION, r=None, f=argent.formater, limite=audit.LIMITE_LIGNES)

    @app.get("/m/audit/fiche")
    @connecte
    def audit_fiche():
        s = acces()
        try:
            t = audit.trace_operation(conn(), s, arg("ref"))
        except ErreurAudit as e:
            return render_template("audit_fiche.html", **contexte(s, "finances", erreur=str(e), t=None, retour=request.args.get("retour", ""))), 404
        except PermissionError:
            abort(403)
        retour = request.args.get("retour", "")
        if not retour.startswith("/m/audit/finances"):         # jamais d'adresse venue d'ailleurs
            retour = url_for("audit_finances")
        return render_template("audit_fiche.html", **contexte(s, "finances", t=t, retour=retour))

    # ================================================================== 3) contrôles
    def page_controles(s, journal_=None, concordance=None, code=200):
        return render_template("audit_controles.html", **contexte(s, "controles", journal=journal_, concordance=concordance)), code

    @app.get("/m/audit/controles")
    @connecte
    def audit_controles():
        return page_controles(acces())[0]

    @app.post("/m/audit/controles/journal")
    @connecte
    def audit_controle_journal():
        if not origine_ok():
            abort(403)
        s = acces()
        try:
            return page_controles(s, journal_=audit.controle_journal(conn(), s))[0]
        except PermissionError:
            abort(403)

    @app.post("/m/audit/controles/concordance")
    @connecte
    def audit_controle_concordance():
        if not origine_ok():
            abort(403)
        s = acces()
        try:
            return page_controles(s, concordance=audit.controle_concordance(conn(), s))[0]
        except PermissionError:
            abort(403)

    # ================================================================== 4) contrôle et audit financier
    def listes_financieres(s):
        return dict(percepteurs=audit_financier.liste_percepteurs(conn(), s), devises=[(d, d) for d in audit_financier.liste_devises(conn(), s)])

    def tables_controle(c) -> list:
        """Les six tableaux du contrôle : [{cle, titre, colonnes, lignes: [(valeurs, tag, constat)]}]. Le constat n'est montré que
        pour une ligne à signaler (couleur), sinon il n'est que l'infobulle."""
        T = lambda cle, titre, colonnes, lignes: dict(cle=cle, titre=titre, colonnes=colonnes, lignes=lignes)
        return [
            T("anomalies", "Anomalies", [("Gravité", ""), ("Catégorie", ""), ("Référence", ""), ("Date", ""), ("Constat", "")],
              [((a["gravite"], a["categorie"], a["reference"] or "—", a["date_txt"] or "—", a["message"]), TAG_GRAVITE[a["gravite"]],
                "Piste de vérification : " + audit_rapports.CONSEILS.get(a["code"], audit_rapports.CONSEIL_PAR_DEFAUT))
               for a in c["anomalies"]]),
            T("paiements", "Paiements et reçus", [("N° reçu", ""), ("Date", ""), ("Élève", ""), ("Frais", ""), ("Montant", "d"), ("Devise", ""),
                                                  ("Percepteur", ""), ("Enregistré par", ""), ("Statut", ""), ("Vérification", "")],
              [((p["n_recu"], p["date_txt"], f"{p['matricule']} - {p['eleve']}", p["frais"], p["montant_txt"], p["devise"], p["percepteur"],
                 p["enregistre_par"], p["statut"], p["verification"]),
                TAG_STATUT.get(p["verification"]) or ("gris" if p["statut"] == "Annulé" else ""), p["remarques"]) for p in c["paiements"]]),
            T("caisse", "Encaissé et remis (rapprochement journalier)",
              [("Date", ""), ("Percepteur", ""), ("Devise", ""), ("Journal : reçus", "d"), ("Journal : total", "d"), ("Annulés", "d"),
               ("Rapport : reçus", "d"), ("Rapport : total", "d"), ("Encaissé", "d"), ("Versé", "d"), ("Écart de remise", "d"),
               ("Encaissé - reçus", "d"), ("Statut", "")],
              [((g["date_txt"], g["percepteur"], g["devise"], g["journal_nb"], _f(g["journal_total"]), _f(g["annules_total"]), g["recus_nb"],
                 _f(g["recus_total"]), _f(g["encaisse"]), _f(g["verse"]), _f(g["ecart_remise"]), _f(g["diff_recus"]), g["statut"]),
                TAG_STATUT.get(g["statut"], ""), g["remarques"]) for g in c["rapprochement"]]),
            T("annulations", "Annulations", [("N° reçu", ""), ("Annulé le", ""), ("Délai", ""), ("Élève", ""), ("Montant", "d"), ("Devise", ""),
                                             ("Motif", ""), ("Enregistré par", ""), ("Annulé par", "")],
              [((a["n_recu"], a["date_txt"], a["delai"], f"{a['matricule']} - {a['eleve']}", a["montant_txt"], a["devise"], a["motif"],
                 a["enregistre_par"], a["annule_par"]), "orange" if a["remarques"] else "", a["remarques"]) for a in c["annulations"]]),
            T("corrections", "Corrections", [("Date", ""), ("Nature", ""), ("Référence", ""), ("Fait par", ""), ("Avant", ""), ("Après", "")],
              [((x["date_txt"], x["nature"], x["reference"], x["par_login"] or "—", x["avant"], x["apres"]), "", "") for x in c["corrections"]]),
            T("rapports", "Rapports journaliers imprimés",
              [("Imprimé le", ""), ("Rapport", ""), ("Journée", ""), ("Portée", ""), ("Par", ""), ("Reçus imprimés", "d"), ("Total imprimé", "d"),
               ("Reçus aujourd'hui", "d"), ("Total aujourd'hui", "d"), ("Statut", "")],
              [((r["date_txt"], r["type"], r["jour_txt"], r["portee"], r["par_login"] or "—", r["imprime_nb"], r["imprime_total"],
                 "" if r["actuel_nb"] is None else r["actuel_nb"], r["actuel_total"], r["statut"]), TAG_STATUT.get(r["statut"], ""), r["remarques"])
               for r in c["rapports"]]),
        ]

    @app.get("/m/audit/financier")
    @connecte
    def audit_financier_page():
        s = acces()
        cles = ("du", "au", "perc", "devise")

        def faire():
            if arg("lancer") != "1":
                return {}
            c = audit_financier.controle_financier(conn(), s, jour("du", "du"), jour("au", "au"),
                                                   entier("perc", "Percepteur inconnu."), arg("devise") or None)
            return dict(c=c, tables=tables_controle(c))
        return executer(s, "financier", "audit_financier.html", faire, q=filtres_q(*cles), v=request.args,
                        c=None, tables=[], f=_f, limite_ecran=LIMITE_ECRAN, **listes_financieres(s))

    # ================================================================== 5) recherche et filtrage des traces
    @app.get("/m/audit/recherche")
    @connecte
    def audit_recherche_page():
        s = acces()
        cles = ("du", "au", "u", "module", "action", "recu", "eleve", "texte")

        def faire():
            r = audit_recherche.rechercher_traces(conn(), s, jour("du", "du"), jour("au", "au"), arg("u") or None, arg("module") or None,
                                                  arg("action") or None, arg("recu") or None, arg("eleve") or None, arg("texte") or None)
            return dict(r=r, filtres_txt=audit_recherche.decrire_filtres(r))
        return executer(s, "recherche", "audit_recherche.html", faire, q=filtres_q(*cles), v=request.args, r=None, filtres_txt=[],
                        **listes_recherche(s))

    def listes_recherche(s):
        groupes = {}
        for code, libelle in audit_recherche.liste_actions():
            groupes.setdefault(audit_recherche.module_de(code), []).append((code, libelle))
        return dict(utilisateurs=utilisateurs(s), modules_traces=audit_recherche.MODULES_TRACES,
                    groupes=[(audit_recherche.libelle_module(m), lst) for m, lst in groupes.items()], limite=audit.LIMITE_LIGNES)

    # ================================================================== 6) rapports d'audit
    @app.get("/m/audit/rapports")
    @connecte
    def audit_rapports_page():
        s = acces()
        cles = ("type", "du", "au", "u", "perc", "devise", "detail", "consulter")
        type_ = arg("type") or "FINANCIER"
        avec_detail = arg("detail") == "1" if arg("consulter") == "1" else True

        def faire():
            if arg("consulter") != "1":
                return {}
            d = audit_rapports.generer_rapport(conn(), s, type_, jour("du", "du"), jour("au", "au"), arg("u") or None,
                                               entier("perc", "Percepteur inconnu."), arg("devise") or None, avec_detail)
            return dict(d=d, sections=audit_rapports._sections_avec_resume(d))
        return executer(s, "rapports", "audit_rapports.html", faire, q=filtres_q(*cles), v=request.args, type_=type_, avec_detail=avec_detail,
                        types=audit_rapports.TYPES_RAPPORT, descriptions=audit_rapports.DESCRIPTIONS, limite_ecran=LIMITE_ECRAN,
                        d=None, sections=[], utilisateurs=utilisateurs(s), **listes_financieres(s))

    # ================================================================== exportations (CSV et PDF)
    @app.get("/m/audit/export/<nature>")
    @connecte
    def audit_export(nature):
        s = acces()
        format_ = arg("format")
        try:
            if nature == "journal":
                chemin = audit.exporter_journal(conn(), s, format_, jour("du", "du"), jour("au", "au"), arg("u") or None,
                                                arg("cat") or None, arg("texte") or None, arg("fin") == "1")
            elif nature == "historique":
                chemin = audit.exporter_historique(conn(), s, format_, jour("du", "du"), jour("au", "au"), arg("eleve") or None,
                                                   arg("recu") or None, arg("u") or None, arg("type") or None, arg("ecart") == "1")
            elif nature == "traces":
                chemin = audit_recherche.exporter_traces(conn(), s, format_, jour("du", "du"), jour("au", "au"), arg("u") or None,
                                                         arg("module") or None, arg("action") or None, arg("recu") or None,
                                                         arg("eleve") or None, arg("texte") or None)
            elif nature == "rapport":
                chemin = audit_rapports.exporter_rapport(conn(), s, arg("type") or "FINANCIER", format_, jour("du", "du"), jour("au", "au"),
                                                         arg("u") or None, entier("perc", "Percepteur inconnu."), arg("devise") or None,
                                                         arg("detail") == "1")
            else:
                abort(404)
        except ErreurAudit as e:
            return render_template("erreur.html", cfg=config, titre="Exportation impossible", texte=str(e)), 400
        except PermissionError:
            abort(403)
        try:
            with open(chemin, "rb") as f:
                contenu = f.read()
            nom = os.path.basename(chemin)
        finally:
            try:
                os.remove(chemin)                              # le fichier ne reste pas sur le serveur
            except OSError:
                pass
        rep = make_response(contenu)
        rep.headers["Content-Type"] = TYPES_MIME[format_]
        rep.headers["Content-Disposition"] = f'attachment; filename="{nom}"'
        rep.headers["Cache-Control"] = "no-store, private"
        return rep
