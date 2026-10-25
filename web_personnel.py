"""Module « Gestion du personnel » en ligne (pages web). Toute la logique métier reste dans personnel.py, affectations.py,
presences.py, personnel_pdf.py, presences_pdf.py et droits.py, exactement comme dans le logiciel Windows : ici on ne fait que les
pages, et on re-vérifie tout côté serveur (droits relus dans la base à chaque action, chaque opération inscrite au journal).

Trois fonctionnalités, chacune avec ses onglets (comme dans le logiciel) :
  1. Dossier personnel         : Nouvel agent, Dossier de l'agent (modifier, désactiver, documents numérisés, fiche PDF) ;
  2. Fonctions et affectations : Fonctions et services, Affectations et historique, Liste du personnel (PDF) ;
  3. Présence et absence       : Pointage du jour (+ jours non travaillés), Permissions et congés, États récapitulatifs (PDF).

Droits (module « personnel ») : Lecture (ouvrir, consulter, imprimer), Ajout, Modification, Suppression : voir personnel.py.
Particularités de la version web :
  - le matricule d'un agent contient un « / » (P0001/26) : il voyage dans un paramètre (?m=...) ou un champ de formulaire, jamais dans le chemin ;
  - les documents numérisés (PDF, JPEG, PNG, 5 Mo) sont reçus du navigateur, contrôlés d'après leur CONTENU, puis relus de la base
    avec contrôle d'empreinte : aucune copie n'est écrite sur le disque du serveur ;
  - les PDF de listes et d'états portent un nom de fichier fixe : leur génération est sérialisée (un verrou) pour que deux
    utilisateurs simultanés ne reçoivent jamais le fichier l'un de l'autre.
"""
import threading
from datetime import date
from urllib.parse import quote

from flask import abort, make_response, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

import affectations
import config
import modules
import personnel
import presences
from personnel import ErreurPersonnel

_VERROU_PDF = threading.Lock()
TYPES_MIME = {"PDF": "application/pdf", "JPEG": "image/jpeg", "PNG": "image/png"}

ONGLETS = {
    "nouveau": ("Nouvel agent", "personnel_nouveau"),
    "dossier": ("Dossier de l'agent", "personnel_dossier"),
    "fonctions": ("Fonctions et services", "personnel_fonctions"),
    "affectation": ("Affectations et historique", "personnel_affectation"),
    "liste": ("Liste du personnel", "personnel_liste"),
    "pointage": ("Pointage du jour", "personnel_pointage"),
    "autorisations": ("Permissions et congés", "personnel_autorisations"),
    "etats": ("États récapitulatifs", "personnel_etats"),
}
FONCTIONNALITES = (
    ("1   Dossier personnel", ("nouveau", "dossier")),
    ("2   Fonctions et affectations", ("fonctions", "affectation", "liste")),
    ("3   Présence et absence", ("pointage", "autorisations", "etats")),
)
AVEC_AGENT = ("dossier", "affectation", "autorisations")      # onglets qui gardent l'agent choisi quand on change d'onglet

MESSAGES_OK = {
    "cree": "Agent enregistré.", "modifie": "Modifications enregistrées.", "inchange": "Aucun changement à enregistrer.",
    "desactive": "Dossier désactivé : l'agent n'est plus proposé, son dossier est conservé.", "reactive": "Dossier réactivé.",
    "doc_ajoute": "Document joint au dossier.", "doc_retire": "Document retiré.",
    "ref_ajoute": "Ajouté à la liste.", "ref_renomme": "Nom modifié.", "ref_active": "Réactivé.", "ref_desactive": "Désactivé : il n'est plus proposé, l'historique est conservé.",
    "ref_retire": "Retiré de la liste.",
    "aff_cree": "Affectation enregistrée.", "aff_corrigee": "Affectation corrigée.", "aff_inchangee": "Aucun changement à enregistrer.",
    "aff_terminee": "Affectation terminée.",
    "pointe": "Pointage enregistré.", "pointe_efface": "Pointage effacé : le jour redevient « Non renseigné ».",
    "ferme_ajoute": "Jour non travaillé ajouté.", "ferme_retire": "Jour non travaillé retiré.",
    "aut_annulee": "Autorisation annulée : ses jours redeviennent « Non renseigné ».",
}


def _iso(texte_ou_date) -> str:
    """'25/03/2010' -> '2010-03-25' (valeur d'un champ <input type=date>) ; tout autre texte est rendu tel quel."""
    t = (texte_ou_date or "").strip() if not isinstance(texte_ou_date, date) else texte_ou_date.isoformat()
    parties = t.split("/")
    if len(parties) == 3 and all(p.isdigit() for p in parties):
        return f"{parties[2]}-{parties[1].zfill(2)}-{parties[0].zfill(2)}"
    return t


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    """Ajoute les routes /m/personnel/... à l'application. Les 4 derniers paramètres viennent d'app_web.creer_app."""
    app.jinja_env.filters["en_iso"] = _iso

    # ------------------------------------------------------------------ utilitaires communs
    def acces():
        s = session_courante()
        if not personnel.peut(conn(), s, "LECTURE"):
            abort(403)
        return s

    def poster():
        if not origine_ok():
            abort(403)

    def droits_de(s):
        c = conn()
        return {"ajout": personnel.peut(c, s, "AJOUT"), "modif": personnel.peut(c, s, "MODIFICATION"),
                "suppr": personnel.peut(c, s, "SUPPRESSION")}

    def contexte(s, onglet, m="", **plus):
        """Données communes : barre du module, onglets de la fonctionnalité affichée, droits."""
        d = droits_de(s)
        fonct = []
        for libelle, cles in FONCTIONNALITES:
            onglets = []
            for cle in cles:
                lib, endpoint = ONGLETS[cle]
                verrou = cle == "nouveau" and not d["ajout"]
                lien = url_for(endpoint, m=m) if (m and cle in AVEC_AGENT) else url_for(endpoint)
                onglets.append({"cle": cle, "libelle": lib, "lien": lien, "actif": cle == onglet, "verrou": verrou})
            libres = [o for o in onglets if not o["verrou"]] or onglets
            # un agent est choisi : la fonctionnalité s'ouvre sur son onglet « par agent » (l'agent reste sélectionné)
            premier = next((o for o in libres if m and o["cle"] in AVEC_AGENT), libres[0])
            fonct.append({"libelle": libelle, "lien": premier["lien"], "actif": onglet in cles, "onglets": onglets})
        ctx = dict(s=s, cfg=config, titre="Gestion du personnel", menu_utile=modules.menu_utile(conn(), s),
                   fonct=fonct, onglet=onglet, m=m, d=d)
        ctx.update(plus)
        return ctx

    def message_ok():
        code = request.args.get("ok", "")
        return MESSAGES_OK.get(code, "")

    def pdf_reponse(fabrique):
        """Génère un PDF (fabrique() -> chemin) sous verrou et le renvoie ; PermissionError -> 403."""
        with _VERROU_PDF:
            chemin = fabrique()
            with open(chemin, "rb") as f:
                contenu = f.read()
        rep = make_response(contenu)
        rep.headers["Content-Type"] = "application/pdf"
        rep.headers["Content-Disposition"] = f'inline; filename="{chemin.replace(chr(92), "/").rsplit("/", 1)[-1]}"'
        return rep

    def champs(*noms):
        return {n: request.form.get(n, "") for n in noms}

    def rafraichir():
        try:
            affectations.rafraichir_fonctions(conn())        # une affectation a pu commencer ou finir avec le temps
        except Exception:                                    # simple reflet de l'historique : ne bloque jamais une page
            pass

    # ------------------------------------------------------------------ choix d'un agent (commun à 3 onglets)
    def choix_agent(s, q, m, consulter=False):
        """(agents trouvés, agent choisi ou None, erreur). consulter=True : la consultation est inscrite au journal."""
        c = conn()
        agents = personnel.rechercher(c, s, q)[:300]
        agent, erreur = None, ""
        if m:
            try:
                agent = personnel.consulter_dossier(c, s, m) if consulter else personnel.charger_agent(c, s, m)
            except ErreurPersonnel as e:
                erreur = str(e)
        return agents, agent, erreur

    @app.get("/m/personnel")
    @connecte
    def personnel_accueil():
        s = acces()
        return redirect(url_for("personnel_nouveau" if personnel.peut(conn(), s, "AJOUT") else "personnel_dossier"))

    # ================================================================== 1a) nouvel agent
    def page_nouveau(s, valeurs=None, erreur="", code=200):
        fonctions = [f["libelle"] for f in affectations.liste_referentiel(conn(), s, "FONCTION", inclure_inactifs=False)]
        propositions = fonctions + [f for f in personnel.FONCTIONS if f not in fonctions]
        defauts = {k: "" for k in CHAMPS_AGENT + ("fonction", "matricule")}
        defauts.update(valeurs or {})
        return render_template("personnel_nouveau.html", **contexte(
            s, "nouveau", valeurs=defauts, erreur=erreur, propositions=propositions, statuts=personnel.STATUTS,
            aujourdhui=date.today().isoformat())), code

    CHAMPS_AGENT = ("nom", "postnom", "prenom", "sexe", "date_naissance", "adresse", "telephone", "email", "date_engagement",
                    "statut_pro")

    @app.get("/m/personnel/nouveau")
    @connecte
    def personnel_nouveau():
        s = acces()
        if not personnel.peut(conn(), s, "AJOUT"):
            abort(403)
        return page_nouveau(s)[0]

    @app.post("/m/personnel/nouveau")
    @connecte
    def personnel_nouveau_envoyer():
        poster()
        s = acces()
        saisie = champs(*CHAMPS_AGENT, "fonction", "matricule")
        try:
            r = personnel.enregistrer_agent(conn(), s, saisie)
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            return page_nouveau(s, saisie, str(e), 400)
        return redirect(url_for("personnel_dossier", m=r["matricule"], ok="cree"))

    # ================================================================== 1b) dossier de l'agent
    def page_dossier(s, q="", m="", erreur="", saisie=None, code=200, consulter=False):
        rafraichir()
        c = conn()
        agents, agent, err = choix_agent(s, q, m, consulter=consulter)
        docs, valeurs = [], {}
        if agent:
            docs = personnel.liste_documents(c, s, agent["matricule"])
            valeurs = {k: _iso(agent[k]) for k in CHAMPS_AGENT}
            if saisie:
                valeurs.update({k: saisie.get(k, "") for k in CHAMPS_AGENT})
        return render_template("personnel_dossier.html", **contexte(
            s, "dossier", m=agent["matricule"] if agent else "", q=q, agents=agents, agent=agent, docs=docs, valeurs=valeurs,
            erreur=erreur or err, ok=message_ok(), statuts=personnel.STATUTS, types_document=personnel.TYPES_DOCUMENT,
            taille_max_mo=personnel.TAILLE_MAX_DOCUMENT // (1024 * 1024))), code

    @app.get("/m/personnel/dossier")
    @connecte
    def personnel_dossier():
        s = acces()
        m = request.args.get("m", "")
        return page_dossier(s, request.args.get("q", "").strip(), m, consulter=bool(m) and not request.args.get("ok"))[0]

    def retour_dossier(m, **plus):
        return redirect(url_for("personnel_dossier", m=m, **plus))

    @app.post("/m/personnel/dossier/modifier")
    @connecte
    def personnel_modifier():
        poster()
        s = acces()
        m = request.form.get("m", "")
        saisie = champs(*CHAMPS_AGENT)
        try:
            changes = personnel.modifier_agent(conn(), s, m, saisie)
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            return page_dossier(s, "", m, str(e), saisie, 400)
        return retour_dossier(m, ok="modifie" if changes else "inchange")

    @app.post("/m/personnel/dossier/activite")
    @connecte
    def personnel_activite():
        poster()
        s = acces()
        m, actif = request.form.get("m", ""), request.form.get("actif") == "1"
        try:
            personnel.changer_activite(conn(), s, m, actif)
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            return page_dossier(s, "", m, str(e), None, 400)
        return retour_dossier(m, ok="reactive" if actif else "desactive")

    @app.get("/m/personnel/dossier/fiche.pdf")
    @connecte
    def personnel_fiche_pdf():
        s = acces()
        m = request.args.get("m", "")
        try:
            return pdf_reponse(lambda: personnel.preparer_fiche_pdf(conn(), s, m))
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            return page_dossier(s, "", "", str(e), None, 404)

    @app.post("/m/personnel/dossier/document")
    @connecte
    def personnel_document_ajouter():
        poster()
        s = acces()
        request.max_content_length = personnel.TAILLE_MAX_DOCUMENT + 200_000      # (le plafond général de 300 Ko est trop bas ici)
        try:
            m, type_doc = request.form.get("m", ""), request.form.get("type_doc", "")
            fichier = request.files.get("fichier")
        except RequestEntityTooLarge:
            return page_dossier(s, "", request.args.get("m", ""), "Le fichier est trop volumineux : "
                                f"{personnel.TAILLE_MAX_DOCUMENT // (1024 * 1024)} Mo au plus.", None, 413)
        try:
            if fichier is None or not fichier.filename:
                raise ErreurPersonnel("Choisissez le fichier à joindre.")
            personnel.ajouter_document_octets(conn(), s, m, type_doc, fichier.read(personnel.TAILLE_MAX_DOCUMENT + 1), fichier.filename)
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            return page_dossier(s, "", m, str(e), None, 400)
        return retour_dossier(m, ok="doc_ajoute")

    @app.get("/m/personnel/dossier/document/<int:id_doc>")
    @connecte
    def personnel_document_ouvrir(id_doc):
        s = acces()
        try:
            contenu, format_, nom = personnel.lire_document(conn(), s, id_doc)
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            if "introuvable" in str(e):
                abort(404)
            return page_dossier(s, "", personnel.matricule_du_document(conn(), id_doc) or "", str(e), None, 409)
        rep = make_response(contenu)
        rep.headers["Content-Type"] = TYPES_MIME[format_]
        rep.headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(nom)}"
        return rep

    @app.post("/m/personnel/dossier/document/<int:id_doc>/retirer")
    @connecte
    def personnel_document_retirer(id_doc):
        poster()
        s = acces()
        m = personnel.matricule_du_document(conn(), id_doc) or ""
        try:
            personnel.supprimer_document(conn(), s, id_doc)
        except PermissionError:
            abort(403)
        except ErreurPersonnel as e:
            return page_dossier(s, "", m, str(e), None, 404)
        return retour_dossier(m, ok="doc_retire")

    # ================================================================== 2a) fonctions et services
    def page_fonctions(s, erreur="", code=200, saisie=None):
        c = conn()
        return render_template("personnel_fonctions.html", **contexte(
            s, "fonctions", erreur=erreur, ok=message_ok(), saisie=saisie or {},
            blocs=(("FONCTION", "Fonctions", affectations.liste_referentiel(c, s, "FONCTION")),
                   ("SERVICE", "Services", affectations.liste_referentiel(c, s, "SERVICE"))))), code

    @app.get("/m/personnel/fonctions")
    @connecte
    def personnel_fonctions():
        return page_fonctions(acces())[0]

    @app.post("/m/personnel/fonctions")
    @connecte
    def personnel_fonctions_agir():
        poster()
        s = acces()
        genre, action = request.form.get("genre", ""), request.form.get("action", "")
        libelle = request.form.get("libelle", "")
        try:
            if genre not in affectations.GENRES:
                raise ErreurPersonnel("Liste inconnue.")
            id_ = int(request.form.get("id") or 0)
            if action == "ajouter":
                affectations.ajouter_referentiel(conn(), s, genre, libelle)
                code = "ref_ajoute"
            elif action == "renommer":
                affectations.renommer_referentiel(conn(), s, genre, id_, libelle)
                code = "ref_renomme"
            elif action in ("activer", "desactiver"):
                affectations.changer_activite_referentiel(conn(), s, genre, id_, action == "activer")
                code = "ref_active" if action == "activer" else "ref_desactive"
            elif action == "supprimer":
                affectations.supprimer_referentiel(conn(), s, genre, id_)
                code = "ref_retire"
            else:
                raise ErreurPersonnel("Action inconnue.")
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_fonctions(s, str(e), 400, {"genre": genre, "action": action, "libelle": libelle})
        return redirect(url_for("personnel_fonctions", ok=code))

    # ================================================================== 2b) affectations et historique
    CHAMPS_AFF = ("id_fonction", "id_service", "responsabilite", "date_debut", "date_fin", "motif")

    def page_affectation(s, q="", m="", erreur="", saisie=None, id_en_erreur=None, info=None, code=200):
        rafraichir()
        c = conn()
        agents, agent, err = choix_agent(s, q, m)
        histo, actuelle = [], None
        if agent:
            histo = affectations.historique_agent(c, s, agent["matricule"])
            actuelle = next((a for a in histo if a["statut"] == "EN_COURS"), None)
        return render_template("personnel_affectation.html", **contexte(
            s, "affectation", m=agent["matricule"] if agent else "", q=q, agents=agents, agent=agent, histo=histo,
            actuelle=actuelle, erreur=erreur or err, ok=message_ok(), info=info or [], saisie=saisie or {},
            id_en_erreur=id_en_erreur, fonctions=affectations.liste_referentiel(c, s, "FONCTION"),
            services=affectations.liste_referentiel(c, s, "SERVICE"), aujourdhui=date.today().isoformat())), code

    @app.get("/m/personnel/affectation")
    @connecte
    def personnel_affectation():
        s = acces()
        return page_affectation(s, request.args.get("q", "").strip(), request.args.get("m", ""))[0]

    @app.post("/m/personnel/affectation/affecter")
    @connecte
    def personnel_affecter():
        poster()
        s = acces()
        m, saisie = request.form.get("m", ""), champs(*CHAMPS_AFF)
        try:
            r = affectations.affecter(conn(), s, m, saisie)
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_affectation(s, "", m, str(e), saisie, 0, code=400)
        if r["terminees"]:                                   # on dit ce qui s'est terminé tout seul : pas de redirection muette
            return page_affectation(s, "", m, "", None, None, info=["L'affectation précédente a pris fin la veille : "
                                                                    + t for t in r["terminees"]])
        return redirect(url_for("personnel_affectation", m=m, ok="aff_cree"))

    @app.post("/m/personnel/affectation/corriger")
    @connecte
    def personnel_affectation_corriger():
        poster()
        s = acces()
        m, saisie = request.form.get("m", ""), champs(*CHAMPS_AFF)
        try:
            id_aff = int(request.form.get("id_aff") or 0)
            changes = affectations.modifier_affectation(conn(), s, id_aff, saisie)
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_affectation(s, "", m, str(e), saisie, _entier(request.form.get("id_aff")), code=400)
        return redirect(url_for("personnel_affectation", m=m, ok="aff_corrigee" if changes else "aff_inchangee"))

    @app.post("/m/personnel/affectation/terminer")
    @connecte
    def personnel_affectation_terminer():
        poster()
        s = acces()
        m = request.form.get("m", "")
        try:
            affectations.terminer_affectation(conn(), s, int(request.form.get("id_aff") or 0), request.form.get("date_fin", ""),
                                              request.form.get("motif", ""))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_affectation(s, "", m, str(e), None, _entier(request.form.get("id_aff")), code=400)
        return redirect(url_for("personnel_affectation", m=m, ok="aff_terminee"))

    def _entier(texte):
        try:
            return int(texte)
        except (TypeError, ValueError):
            return None

    # ================================================================== 2c) liste du personnel
    def choix_liste():
        mode = request.args.get("mode", "")
        mode = mode if mode in affectations.MODES else ""
        genre, _, ident = request.args.get("filtre", "").partition(":")      # « FONCTION:3 » : le filtre dit de quelle liste il vient
        if ident and (genre != mode or not ident.isdigit()):
            raise ErreurPersonnel("Le filtre choisi ne correspond pas au regroupement : choisissez une fonction avec « par fonction », "
                                  "un service avec « par service ».")
        return mode, ident, request.args.get("jour", "")

    @app.get("/m/personnel/liste")
    @connecte
    def personnel_liste():
        s = acces()
        c = conn()
        rafraichir()
        liste, erreur = None, ""
        try:
            mode, filtre, jour = choix_liste()
            if mode:
                liste = affectations.liste_personnel(c, s, mode, filtre or None, jour)
        except (ErreurPersonnel, ValueError) as e:
            erreur = str(e)
            mode, filtre, jour = request.args.get("mode", ""), "", request.args.get("jour", "")
        return render_template("personnel_liste.html", **contexte(
            s, "liste", mode=mode, filtre=filtre, jour=jour or date.today().isoformat(), liste=liste, erreur=erreur,
            modes=affectations.MODES, options={g: affectations.liste_referentiel(c, s, g) for g in affectations.GENRES}))

    @app.get("/m/personnel/liste.pdf")
    @connecte
    def personnel_liste_pdf():
        s = acces()
        try:
            mode, filtre, jour = choix_liste()
            if not mode:
                abort(404)
            return pdf_reponse(lambda: affectations.preparer_liste_pdf(conn(), s, mode, filtre or None, jour))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return render_template("erreur.html", cfg=config, titre="Impression impossible", texte=str(e)), 400

    # ================================================================== 3a) pointage du jour (et jours non travaillés)
    def page_pointage(s, jour="", fonction="", erreur="", info=None, code=200, annee=None):
        c = conn()
        rafraichir()
        feuille = None
        try:
            feuille = presences.feuille_du_jour(c, s, jour, fonction or None)
        except (ErreurPersonnel, ValueError) as e:
            erreur = erreur or str(e)
        annee_f = annee or (feuille["jour_iso"][:4] if feuille else str(date.today().year))
        try:
            fermes = presences.liste_jours_fermes(c, s, annee_f)
        except (ErreurPersonnel, ValueError):
            fermes = []
        return render_template("presence_pointage.html", **contexte(
            s, "pointage", jour=feuille["jour_iso"] if feuille else (jour or date.today().isoformat()), fonction=fonction,
            feuille=feuille, erreur=erreur, ok=message_ok(), info=info or [], fermes=fermes, annee=annee_f, statuts_jour=presences.STATUTS_JOUR,
            fonctions=affectations.liste_referentiel(c, s, "FONCTION"), statuts=presences.STATUTS_POINTAGE,
            heure_ouverture=config.HEURE_DEBUT_SERVICE, aujourdhui=date.today().isoformat())), code

    @app.get("/m/personnel/pointage")
    @connecte
    def personnel_pointage():
        s = acces()
        return page_pointage(s, request.args.get("jour", ""), request.args.get("fonction", ""),
                             annee=request.args.get("annee") or None)[0]

    def retour_pointage(jour, fonction, ok):
        return redirect(url_for("personnel_pointage", jour=jour, fonction=fonction or None, ok=ok))

    @app.post("/m/personnel/pointage/enregistrer")
    @connecte
    def personnel_pointer():
        poster()
        s = acces()
        f = request.form
        jour, fonction = f.get("jour", ""), f.get("fonction", "")
        try:
            presences.enregistrer_pointage(conn(), s, f.get("m", ""), jour, f.get("statut", ""), f.get("heure", ""), f.get("motif", ""))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_pointage(s, jour, fonction, str(e), code=400)
        return retour_pointage(jour, fonction, "pointe")

    @app.post("/m/personnel/pointage/effacer")
    @connecte
    def personnel_pointage_effacer():
        poster()
        s = acces()
        jour, fonction = request.form.get("jour", ""), request.form.get("fonction", "")
        try:
            presences.supprimer_pointage(conn(), s, request.form.get("m", ""), jour)
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_pointage(s, jour, fonction, str(e), code=400)
        return retour_pointage(jour, fonction, "pointe_efface")

    @app.post("/m/personnel/pointage/tous-presents")
    @connecte
    def personnel_marquer_presents():
        poster()
        s = acces()
        jour, fonction = request.form.get("jour", ""), request.form.get("fonction", "")
        try:
            r = presences.marquer_presents(conn(), s, jour, fonction or None)
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_pointage(s, jour, fonction, str(e), code=400)
        info = [f"{r['faits']} agent(s) marqué(s) présent(s)."] + [f"{conn_nom(m)} : {msg}" for m, msg in r["refuses"]]
        return page_pointage(s, jour, fonction, info=info)

    def conn_nom(matricule):
        l = conn().execute("SELECT NOM, POSTNOM, PRENOM FROM PERSONNEL WHERE MATRICULE = ?", (matricule,)).fetchone()
        return " ".join(p for p in (l["NOM"], l["POSTNOM"], l["PRENOM"]) if p) if l else matricule

    @app.post("/m/personnel/pointage/jour-non-travaille")
    @connecte
    def personnel_ferme_ajouter():
        poster()
        s = acces()
        jour, fonction = request.form.get("jour", ""), request.form.get("fonction", "")
        try:
            presences.ajouter_jour_ferme(conn(), s, request.form.get("date_ferme", ""), request.form.get("libelle", ""))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_pointage(s, jour, fonction, str(e), code=400)
        return retour_pointage(jour, fonction, "ferme_ajoute")

    @app.post("/m/personnel/pointage/jour-non-travaille/retirer")
    @connecte
    def personnel_ferme_retirer():
        poster()
        s = acces()
        jour, fonction = request.form.get("jour", ""), request.form.get("fonction", "")
        try:
            presences.supprimer_jour_ferme(conn(), s, request.form.get("date_ferme", ""))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_pointage(s, jour, fonction, str(e), code=400)
        return retour_pointage(jour, fonction, "ferme_retire")

    # ================================================================== 3b) permissions et congés
    def page_autorisations(s, q="", m="", erreur="", saisie=None, info=None, code=200):
        c = conn()
        agents, agent, err = choix_agent(s, q, m)
        suivi = presences.liste_autorisations(c, s, agent["matricule"]) if agent else None
        return render_template("presence_autorisations.html", **contexte(
            s, "autorisations", m=agent["matricule"] if agent else "", q=q, agents=agents, agent=agent, suivi=suivi,
            erreur=erreur or err, ok=message_ok(), info=info or [], saisie=saisie or {}, types=presences.TYPES_AUTORISATION,
            natures=sorted({n for liste in presences.NATURES.values() for n in liste}),
            aujourdhui=date.today().isoformat())), code

    @app.get("/m/personnel/autorisations")
    @connecte
    def personnel_autorisations():
        s = acces()
        info = []
        if request.args.get("ok") == "aut_cree":
            n, r = _entier(request.args.get("n")) or 0, _entier(request.args.get("r")) or 0
            info = [f"Autorisation enregistrée : {n} jour(s) de travail."
                    + (f" {r} absence(s) déjà marquée(s) ont été régularisée(s)." if r else "")]
        return page_autorisations(s, request.args.get("q", "").strip(), request.args.get("m", ""), info=info)[0]

    @app.post("/m/personnel/autorisations/accorder")
    @connecte
    def personnel_autorisation_accorder():
        poster()
        s = acces()
        m, f = request.form.get("m", ""), request.form
        saisie = {k: f.get(k, "") for k in ("type", "nature", "debut", "fin", "motif")}
        try:
            r = presences.accorder_autorisation(conn(), s, m, saisie["type"], saisie["nature"], saisie["debut"], saisie["fin"],
                                                saisie["motif"])
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_autorisations(s, "", m, str(e), saisie, code=400)
        return redirect(url_for("personnel_autorisations", m=m, ok="aut_cree", n=r["jours"], r=r["regularisees"]))

    @app.post("/m/personnel/autorisations/annuler")
    @connecte
    def personnel_autorisation_annuler():
        poster()
        s = acces()
        m = request.form.get("m", "")
        try:
            presences.annuler_autorisation(conn(), s, int(request.form.get("id_aut") or 0), request.form.get("motif", ""))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return page_autorisations(s, "", m, str(e), code=400)
        return redirect(url_for("personnel_autorisations", m=m, ok="aut_annulee"))

    # ================================================================== 3c) états récapitulatifs
    def choix_etat():
        """Période et portée lues dans l'adresse. cible : '' (tout le personnel), 'FONCTION:3' ou 'SERVICE:2'."""
        a = request.args
        cible = a.get("cible", "")
        mode, _, ident = cible.partition(":")
        if mode not in ("FONCTION", "SERVICE") or not ident.isdigit():
            mode, ident, cible = None, None, ""
        return a.get("debut", ""), a.get("fin", ""), cible, mode, ident

    @app.get("/m/personnel/etats")
    @connecte
    def personnel_etats():
        s = acces()
        c = conn()
        debut, fin, cible, mode, ident = choix_etat()
        etat, erreur = None, ""
        if debut or fin:
            try:
                etat = presences.etat_recapitulatif(c, s, debut, fin, mode, ident)
            except (ErreurPersonnel, ValueError) as e:
                erreur = str(e)
        auj = date.today()
        raccourcis = (("Cette semaine", presences.periode_de_la_semaine(auj)), ("Ce mois", presences.periode_du_mois(auj)),
                      ("Mois précédent", presences.periode_mois_precedent(auj)))
        d0, f0 = presences.periode_du_mois(auj)
        return render_template("presence_etats.html", **contexte(
            s, "etats", debut=debut or d0.isoformat(), fin=fin or f0.isoformat(), cible=cible, etat=etat, erreur=erreur,
            raccourcis=[(n, d.isoformat(), f.isoformat()) for n, (d, f) in raccourcis],
            options={g: affectations.liste_referentiel(c, s, g) for g in affectations.GENRES}, statuts=presences.STATUTS_JOUR))

    @app.get("/m/personnel/etats.pdf")
    @connecte
    def personnel_etats_pdf():
        s = acces()
        debut, fin, _cible, mode, ident = choix_etat()
        try:
            return pdf_reponse(lambda: presences.preparer_etat_pdf(conn(), s, debut, fin, mode, ident,
                                                                    avec_detail=request.args.get("detail", "1") != "0"))
        except PermissionError:
            abort(403)
        except (ErreurPersonnel, ValueError) as e:
            return render_template("erreur.html", cfg=config, titre="Impression impossible", texte=str(e)), 400
