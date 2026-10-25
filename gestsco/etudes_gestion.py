"""Direction des études, en ligne : gestion des cours et des enseignants, et présence des élèves (pages web).

Ces fonctionnalités étaient celles de l'ancien module « Gestion scolaire », supprimé : elles sont maintenant des fonctionnalités de l'espace
« Direction des études » (web_etudes.py), avec les droits de « Direction des études » (Lecture / Ajout / Modification / Suppression), relus dans
la base à chaque action et contrôlés par la logique métier (cours.py, bulletins.py, notes.py, presence_eleves.py) ; chaque opération est
inscrite au journal.

Fonctionnalités : calendrier (années, semestres ou trimestres, périodes) | cours (par niveau, option, année d'étude) |
programme (ouvrir les cours d'une classe, attribuer un professeur, heures) |
enseignants (charge de chaque professeur, titulaire de classe, compte de connexion du professeur) |
presence_eleves (toutes les classes, lecture : situation du jour, détail par élève, récapitulatif d'une période).

Ce module fournit les données des pages (contexte_gestion) et les routes d'écriture (enregistrer). Les pages elles-mêmes sont les modèles
templates/_etudes_gestion_*.html, affichés dans l'espace Direction des études. La présence des élèves est aussi un module à part
(web_presence.py) pour les comptes qui n'ont pas accès à la Direction des études (Directeur de discipline).

Le bouton « serveur des professeurs » du logiciel Windows n'a pas d'objet en ligne : l'application web EST ce serveur.
"""
from datetime import date, timedelta

from flask import abort, make_response, redirect, render_template, request, url_for

import bulletins
import config
import cours
import droits
import modules
import notes
import presence_eleves
import sections
from cours import ErreurCours

ESPACE = "direction_etudes"
FONCTIONS = ("calendrier", "cours", "programme", "enseignants", "presence_eleves")
ERREURS = (ErreurCours, notes.ErreurNotes)          # bulletins.ERREURS et presence_eleves.ERREURS sont ces mêmes classes

MESSAGES_OK = {
    "g_annee_creee": "Année scolaire créée.", "g_dates": "Dates enregistrées.", "g_en_cours": "Cette année est maintenant l'année en cours.",
    "g_standard": "Structure standard créée.", "g_ajoute": "Ajouté.", "g_modifie": "Modification enregistrée.", "g_supprime": "Supprimé.",
    "g_cours_cree": "Cours enregistré.", "g_cours_modifie": "Cours modifié.", "g_active": "Cours réactivé.",
    "g_desactive": "Cours désactivé : il n'est plus proposé.",
    "g_ouvert": "Cours ouverts dans la classe.", "g_attribue": "Professeur attribué.", "g_retire_prof": "Professeur retiré des cours choisis.",
    "g_retire_cours": "Cours retiré de la classe.", "g_heures": "Heures enregistrées.", "g_associe": "Cours attribués.",
    "g_detache": "Cours détachés.", "g_titulaire": "Titulaire désigné.", "g_titulaire_retire": "Titulaire retiré.",
}


def en_iso(texte) -> str:
    """'25/03/2010' -> '2010-03-25' (valeur d'un champ <input type=date>) ; tout autre texte est rendu tel quel."""
    t = (texte or "").strip()
    p = t.split("/")
    if len(p) == 3 and all(x.isdigit() for x in p):
        return f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}"
    return t


def _entier(texte, defaut=None):
    try:
        return int(texte)
    except (TypeError, ValueError):
        return defaut


def _annees_cours(c, s):
    try:
        return cours.lister_annees(c, s)
    except ERREURS:
        return []


def _annee_choisie(liste, args, cle="a"):
    a = args.get(cle, "")
    if a in [x["annee"] for x in liste]:
        return a
    return next((x["annee"] for x in liste if x["en_cours"]), liste[0]["annee"] if liste else "")


# ================================================================== données des pages
def contexte_gestion(c, s, fonction, args, erreur="", saisie=None) -> dict:
    """Variables du modèle de la fonctionnalité `fonction`. Les droits sont relus dans la base ; sans Lecture : refus (403)."""
    if fonction == "presence_eleves":
        return contexte_presence(c, s, args, erreur)
    if not cours.peut(c, s, "LECTURE"):
        abort(403)
    ctx = {"erreur": erreur, "admin": droits.est_admin(c, s),
           "d": {"ajout": cours.peut(c, s, "AJOUT"), "modif": cours.peut(c, s, "MODIFICATION"), "suppr": cours.peut(c, s, "SUPPRESSION")}}
    ctx.update({"calendrier": _calendrier, "cours": _cours, "programme": _programme, "enseignants": _enseignants}[fonction](
        c, s, args, ctx, saisie))
    return ctx


def _calendrier(c, s, args, ctx, saisie):
    liste = _annees_cours(c, s)
    a = _annee_choisie(liste, args)
    section = args.get("s") if args.get("s") in sections.TOUTES else sections.SECONDAIRE
    cal = None
    if a:
        try:
            cal = cours.calendrier_annee(c, s, a, section)
        except ERREURS as e:
            ctx["erreur"] = ctx["erreur"] or str(e)
    return dict(annees=liste, a=a, cal=cal, section=section, sections=sections.SECTIONS, mot=cours.mot_periode_longue(section))


def _cours(c, s, args, ctx, saisie):
    n = args.get("n", "")
    q = args.get("q", "").strip()
    choix = cours.choix_cours(c, s)
    liste = cours.lister_cours(c, s, n or None, q)
    modif = None
    e = _entier(args.get("e"))
    if e is not None:
        modif = next((x for x in cours.lister_cours(c, s) if x["id"] == e), None)
    formulaire = saisie if saisie is not None else (
        {"libelle": modif["libelle"], "code_niveau": modif["code_niveau"], "code_option": modif["code_option"],
         "annee_etude": modif["annee_etude"], "heures_semaine": str(modif["heures"])} if modif else {"heures_semaine": ""})
    return dict(n=n, q=q, choix=choix, liste=liste, modif=modif, f=formulaire)


def _programme(c, s, args, ctx, saisie):
    liste = _annees_cours(c, s)
    a = _annee_choisie(liste, args)
    classes = cours.lister_classes(c, s)
    n_classe = _entier(args.get("c"))
    if n_classe not in [k["n_classe"] for k in classes]:
        n_classe = None
    prog, profs = None, []
    if a and n_classe is not None:
        try:
            prog = cours.programme_classe(c, s, a, n_classe)
            profs = cours.lister_professeurs(c, s, a)
        except ERREURS as e:
            ctx["erreur"] = ctx["erreur"] or str(e)
    return dict(annees=liste, a=a, classes=classes, c=n_classe, prog=prog, profs=profs)


def _enseignants(c, s, args, ctx, saisie):
    liste = _annees_cours(c, s)
    a = _annee_choisie(liste, args)
    classes = cours.lister_classes(c, s)
    n_classe = _entier(args.get("c"))
    if n_classe not in [k["n_classe"] for k in classes]:
        n_classe = classes[0]["n_classe"] if classes else None
    q, seuls = args.get("q", "").strip(), args.get("seuls") == "1"
    profs, m, charge, titulaire = [], args.get("m", ""), None, None
    if a:
        try:
            profs = cours.lister_professeurs(c, s, a, q, seuls)
            if m:
                charge = cours.classes_du_professeur(c, s, a, m)
                charge["nom"] = next((p["nom_complet"] for p in cours.lister_professeurs(c, s, a) if p["matricule"] == m), "")
            if n_classe is not None:
                titulaire = bulletins.lister_titulaires(c, s, a).get(n_classe)
        except ERREURS as e:
            ctx["erreur"] = ctx["erreur"] or str(e)
    avec_compte = {r[0] for r in c.execute("SELECT MATRICULE FROM COMPTE_PROFESSEUR")}
    return dict(annees=liste, a=a, classes=classes, c=n_classe, q=q, seuls=seuls, profs=profs, m=m, charge=charge,
                titulaire=titulaire, avec_compte=avec_compte)


def contexte_presence(c, s, args, erreur="", ep="etudes_sous_menu", url=None, champs=None) -> dict:
    """Présence des élèves de toutes les classes (lecture) : année (?a=), jour (?j=), classe (?c=), récapitulatif (?mode=recap, ?d1=, ?d2=).
    `ep`, `url` et `champs` disent aux liens et formulaires de la page où se trouve la fonctionnalité (espace Direction des études, ou
    module « Présence des élèves » seul)."""
    if not presence_eleves.peut_consulter(c, s):
        abort(403)
    try:
        liste = presence_eleves.lister_annees(c, s)
    except ERREURS:
        liste = []
    a = _annee_choisie(liste, args)
    jour = args.get("j", "") or date.today().isoformat()
    try:
        d = date.fromisoformat(jour)
    except ValueError:
        d, erreur = date.today(), erreur or "Date invalide."
    d_iso = d.isoformat()
    mode = "recap" if args.get("mode") == "recap" else "jour"
    n_classe = _entier(args.get("c"))
    d1, d2 = args.get("d1", "") or d_iso, args.get("d2", "") or d_iso
    jour_r, classe_r, recap = None, None, None
    if a:
        try:
            jour_r = presence_eleves.classes_du_jour(c, s, a, d_iso)
            if n_classe is not None and n_classe in [k["n_classe"] for k in jour_r["classes"]]:
                if mode == "recap":
                    recap = presence_eleves.recapitulatif_classe(c, s, a, n_classe, d1, d2)
                else:
                    classe_r = presence_eleves.eleves_de_la_classe(c, s, a, n_classe, d_iso)
            else:
                n_classe = None
        except ERREURS as e:
            erreur = erreur or str(e)
    veille = (d - timedelta(days=1)).isoformat()
    lendemain = (d + timedelta(days=1)).isoformat() if d < date.today() else ""
    return dict(erreur=erreur, annees=liste, a=a, j=d_iso, aujourdhui=date.today().isoformat(), veille=veille, lendemain=lendemain,
                jour_r=jour_r, c=n_classe, classe_r=classe_r, recap=recap, mode=mode, d1=d1, d2=d2,
                pres_ep=ep, pres_url=url if url is not None else {"sous": ESPACE, "f": "presence_eleves"},
                pres_champs=champs if champs is not None else {"f": "presence_eleves"})


# ================================================================== routes d'écriture
def enregistrer(app, conn, session_courante, connecte, origine_ok, espace_autorise, rendre):
    """Ajoute les routes d'écriture /m/etudes_discipline/direction_etudes/gestion/... (paramètres venus de web_etudes.enregistrer).
    espace_autorise(sous) -> session (refus 403 si l'espace n'est pas ouvert) ; rendre(fonction, s, args, erreur, code, saisie) -> page."""
    app.jinja_env.filters["en_iso"] = en_iso
    base = f"/m/etudes_discipline/{ESPACE}/gestion"

    def poster():
        if not origine_ok():
            abort(403)

    def acces():
        s = espace_autorise(ESPACE)
        if not cours.peut(conn(), s, "LECTURE"):
            abort(403)
        return s

    def garder(*noms):
        """Paramètres de navigation à conserver après une action (année, classe, agent...)."""
        return {n: request.values[n] for n in noms if request.values.get(n)}

    def agir(fonction, ok, action, *noms):
        """Exécute action() : réussite -> retour sur la page avec un message ; erreur métier -> la page est réaffichée avec l'erreur."""
        poster()
        try:
            action()
        except PermissionError:
            abort(403)
        except ERREURS as e:
            return rendre(fonction, session_courante(), request.form, str(e), 400, None)
        return redirect(url_for("etudes_sous_menu", sous=ESPACE, f=fonction, ok="g_" + ok, **garder(*noms)))

    def ids_cochees():
        return [i for i in (_entier(x) for x in request.form.getlist("ids")) if i is not None]

    # ------------------------------------------------------------------ années, semestres, périodes
    def cal(fn, ok, *noms):
        return agir("calendrier", ok, fn, *noms)

    @app.post(base + "/calendrier/annee")
    @connecte
    def gestion_annee_creer():
        poster()
        s = acces()
        f = request.form
        try:
            a = cours.creer_annee(conn(), s, f.get("annee", ""), f.get("debut", ""), f.get("fin", ""))
        except PermissionError:
            abort(403)
        except ERREURS as e:
            return rendre("calendrier", s, f, str(e), 400, None)
        return redirect(url_for("etudes_sous_menu", sous=ESPACE, f="calendrier", a=a, s=f.get("s", ""), ok="g_annee_creee"))

    @app.post(base + "/calendrier/dates")
    @connecte
    def gestion_annee_dates():
        s = acces()
        return cal(lambda: cours.modifier_dates_annee(conn(), s, request.form.get("a", ""), request.form.get("debut", ""),
                                                      request.form.get("fin", "")), "dates", "a", "s")

    @app.post(base + "/calendrier/en-cours")
    @connecte
    def gestion_annee_en_cours():
        s = acces()
        return cal(lambda: cours.definir_annee_en_cours(conn(), s, request.form.get("a", "")), "en_cours", "a", "s")

    @app.post(base + "/calendrier/standard")
    @connecte
    def gestion_structure_standard():
        s = acces()
        return cal(lambda: cours.generer_structure_standard(conn(), s, request.form.get("a", ""), request.form.get("s", sections.SECONDAIRE)),
                   "standard", "a", "s")

    @app.post(base + "/calendrier/semestre")
    @connecte
    def gestion_semestre_ajouter():
        s = acces()
        f = request.form
        return cal(lambda: cours.ajouter_semestre(conn(), s, f.get("a", ""), f.get("libelle", ""), f.get("debut", ""), f.get("fin", ""),
                                                  f.get("s", sections.SECONDAIRE)), "ajoute", "a", "s")

    @app.post(base + "/calendrier/periode")
    @connecte
    def gestion_periode_ajouter():
        s = acces()
        f = request.form
        return cal(lambda: cours.ajouter_periode(conn(), s, _entier(f.get("id_sem"), -1), f.get("libelle", ""), f.get("debut", ""),
                                                 f.get("fin", "")), "ajoute", "a", "s")

    @app.post(base + "/calendrier/modifier")
    @connecte
    def gestion_calendrier_modifier():
        s = acces()
        f = request.form
        fn = cours.modifier_semestre if f.get("genre") == "S" else cours.modifier_periode
        return cal(lambda: fn(conn(), s, _entier(f.get("id"), -1), f.get("libelle", ""), f.get("debut", ""), f.get("fin", "")),
                   "modifie", "a", "s")

    @app.post(base + "/calendrier/supprimer")
    @connecte
    def gestion_calendrier_supprimer():
        s = acces()
        f = request.form
        fn = cours.supprimer_semestre if f.get("genre") == "S" else cours.supprimer_periode
        return cal(lambda: fn(conn(), s, _entier(f.get("id"), -1)), "supprime", "a", "s")

    # ------------------------------------------------------------------ cours
    @app.post(base + "/cours/enregistrer")
    @connecte
    def gestion_cours_enregistrer():
        poster()
        s = acces()
        f = request.form
        saisie = {k: f.get(k, "") for k in ("libelle", "code_niveau", "code_option", "annee_etude", "heures_semaine")}
        ident = _entier(f.get("id"))
        try:
            if ident is None:
                cours.ajouter_cours(conn(), s, saisie)
            else:
                cours.modifier_cours(conn(), s, ident, saisie)
        except PermissionError:
            abort(403)
        except ERREURS as e:
            return rendre("cours", s, f, str(e), 400, saisie)
        return redirect(url_for("etudes_sous_menu", sous=ESPACE, f="cours", ok="g_cours_cree" if ident is None else "g_cours_modifie",
                                **garder("n", "q")))

    @app.post(base + "/cours/activite")
    @connecte
    def gestion_cours_activite():
        s = acces()
        actif = request.form.get("action") == "activer"
        return agir("cours", "active" if actif else "desactive",
                    lambda: cours.changer_activite_cours(conn(), s, _entier(request.form.get("id"), -1), actif), "n", "q")

    @app.post(base + "/cours/supprimer")
    @connecte
    def gestion_cours_supprimer():
        s = acces()
        return agir("cours", "supprime", lambda: cours.supprimer_cours(conn(), s, _entier(request.form.get("id"), -1)), "n", "q")

    # ------------------------------------------------------------------ programme des classes
    def prog(fn, ok):
        return agir("programme", ok, fn, "a", "c")

    @app.post(base + "/programme/ouvrir")
    @connecte
    def gestion_programme_ouvrir():
        s = acces()
        f = request.form
        ids = None if f.get("tous") == "1" else ids_cochees()
        if ids is not None and not ids:
            poster()
            return rendre("programme", s, f, "Cochez au moins un cours à ouvrir.", 400, None)
        return prog(lambda: cours.ouvrir_cours(conn(), s, f.get("a", ""), _entier(f.get("c"), -1), ids), "ouvert")

    @app.post(base + "/programme/attribuer")
    @connecte
    def gestion_programme_attribuer():
        s = acces()
        return prog(lambda: cours.attribuer_professeur(conn(), s, ids_cochees(), request.form.get("matricule", "")), "attribue")

    @app.post(base + "/programme/retirer-prof")
    @connecte
    def gestion_programme_retirer_prof():
        s = acces()
        return prog(lambda: cours.attribuer_professeur(conn(), s, ids_cochees(), ""), "retire_prof")

    @app.post(base + "/programme/retirer-cours")
    @connecte
    def gestion_programme_retirer_cours():
        s = acces()

        def action():
            ids = ids_cochees()
            if not ids:
                raise ErreurCours("Choisissez au moins un cours dans la liste.")
            for i in ids:
                cours.retirer_cours_de_classe(conn(), s, i)
        return prog(action, "retire_cours")

    @app.post(base + "/programme/heures")
    @connecte
    def gestion_programme_heures():
        s = acces()
        return prog(lambda: cours.modifier_heures(conn(), s, _entier(request.form.get("id"), -1), request.form.get("heures", "")), "heures")

    # ------------------------------------------------------------------ enseignants et classes
    def ens(fn, ok):
        return agir("enseignants", ok, fn, "a", "c", "q", "seuls", "m")

    @app.post(base + "/enseignants/associer")
    @connecte
    def gestion_enseignants_associer():
        s = acces()
        f = request.form

        def action():
            if not f.get("m"):
                raise ErreurCours("Choisissez d'abord un agent dans la liste.")
            p = cours.programme_classe(conn(), s, f.get("a", ""), _entier(f.get("c"), -1))
            ids = [l["id"] for l in p["cours"] if not l["matricule"]]
            if not ids:
                raise ErreurCours(f"Cette classe n'a aucun cours sans professeur pour {f.get('a', '')}. Ouvrez d'abord ses cours "
                                  "(onglet « Programme des classes »).")
            return cours.attribuer_professeur(conn(), s, ids, f.get("m"))
        return ens(action, "associe")

    @app.post(base + "/enseignants/detacher")
    @connecte
    def gestion_enseignants_detacher():
        s = acces()
        return ens(lambda: cours.attribuer_professeur(conn(), s, ids_cochees(), ""), "detache")

    @app.post(base + "/enseignants/titulaire")
    @connecte
    def gestion_titulaire_designer():
        s = acces()
        f = request.form

        def action():
            if not f.get("m"):
                raise ErreurCours("Choisissez d'abord un agent dans la liste.")
            return bulletins.designer_titulaire(conn(), s, f.get("a", ""), _entier(f.get("c"), -1), f.get("m"))
        return ens(action, "titulaire")

    @app.post(base + "/enseignants/titulaire-retirer")
    @connecte
    def gestion_titulaire_retirer():
        s = acces()
        return ens(lambda: bulletins.retirer_titulaire(conn(), s, request.form.get("a", ""), _entier(request.form.get("c"), -1)),
                   "titulaire_retire")

    @app.post(base + "/enseignants/compte")
    @connecte
    def gestion_compte_professeur():
        """Compte de connexion du professeur (Administrateur) : l'identifiant et le mot de passe provisoire ne sont montrés qu'ici, une fois."""
        poster()
        s = acces()
        try:
            r = notes.creer_compte_professeur(conn(), s, request.form.get("m", ""))
        except PermissionError:
            abort(403)
        except ERREURS as e:
            return rendre("enseignants", s, request.form, str(e), 400, None)
        rep = make_response(render_template("etudes_gestion_secret.html", s=s, cfg=config, menu_utile=modules.menu_utile(conn(), s), r=r, retour=url_for(
            "etudes_sous_menu", sous=ESPACE, f="enseignants", **garder("a", "c", "q", "seuls", "m"))))
        rep.headers["Cache-Control"] = "no-store, private"
        return rep
