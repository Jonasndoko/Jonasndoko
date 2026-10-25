"""Les quatre espaces de l'ancien module « Gestion des études et discipline », en ligne : chacun est maintenant un module du menu principal
(config.ESPACES_MODULES) avec ses fonctionnalités en boutons groupés.

  /m/etudes, /m/discipline, /m/prefecture, /m/secretariat : ouvrent l'espace du module (s'il est ouvert au compte, sinon 403).
  /m/etudes_discipline            : ancienne adresse de l'écran d'accueil ; redirige vers le premier module ouvert au compte.
  /m/etudes_discipline/<espace>   : les fonctionnalités de l'espace (adresses inchangées, y compris celles des formulaires).

Préfecture            : réservé au Préfet                       (droit « prefecture »)  -> Tableau de bord, Suivi des élèves,
                          Situation financière des élèves (consultation seule), Décisions et rapports, Consultation de la discipline et
                          Consultation des études (consultation seule : présences, conduite, résultats, bulletins) (prefecture.py)
  Direction des études  : Directeur ou Directrice des études      (droit « direction_etudes »)      -> ..., Passage en classe supérieure, Rapport au Préfet
  Direction de discipline : Directeur de discipline               (droit « direction_discipline ») -> Gestion des présences, Suivi de la conduite,
                          Rapport au Préfet
  Secrétariat           : Secrétariat                             (droit « dossier_eleve »)

Le module ne concerne que la section « Secondaire et humanitaire » (modules.sous_menus_ouverts). Les autres fonctionnalités attendent
encore leur tour.

Chaque espace a son propre droit de Lecture (config.MODULES_DROITS), relu dans la base à chaque requête : un compte qui n'a pas
le droit d'un espace reçoit un refus (403) même s'il connaît l'adresse. L'Administrateur voit les quatre.
"""
from datetime import date

from urllib.parse import quote

from flask import Response, abort, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge

import config
import controle_notes
import etudes_gestion
import inscription
import gestion_bulletins
import statistiques_scolaires
import heures_profs
import horaires
import modules
import prefecture
import renvoi
import proclamation
import promotion
import archives_scolaires
import bulletins_secretariat
import gestion_presences
import suivi_conduite
import convocations
import listes_administratives
import documents_officiels
import secretariat
import sections
import bulletins

TITRES = {cle: titre for cle, titre, _role in config.SOUS_MENUS_ETUDES}
MESSAGES_OK = {"p_autorise": "Titulaire autorisé pour cette période.", "p_criteres": "Frais exigés enregistrés.",
               "p_valide": "Bulletins validés.", "p_retire": "Validation retirée.", "p_soumise": "Proclamation soumise au Préfet.",
               "p_decision": "Décision enregistrée.", "p_confirmee": "Proclamation confirmée : le titulaire peut imprimer les bulletins validés.",
               "pd_confirmee": "Présence confirmée.", "pd_corrigee": "Présence corrigée : le pointage du professeur est conservé.",
               "pd_classe": "Présences de la classe confirmées.", "pd_rien": "Aucune présence à confirmer : les élèves pointés ont déjà une décision valable.",
               "pd_annulee": "Décision annulée : la présence retenue redevient celle des pointages des professeurs.",
               "cd_ajoutee": "Entrée enregistrée dans le suivi de la conduite de l'élève.",
               "cv_envoyee": "Convocation envoyée : le parent la reçoit en notification dans l'application mobile.",
               "cv_brouillon": "Convocation enregistrée en brouillon : elle n'est pas encore envoyée.",
               "cv_annulee": "Convocation annulée : elle reste visible dans la liste, marquée « Annulée ».",
               "cd_annulee": "Entrée annulée : elle ne compte plus, mais reste visible dans l'historique, marquée « Annulée ».",
               "archive_classee": "Document classé dans les archives.",
               "archive_retiree": "Document retiré du classement : le fichier reste conservé dans la base (case « Afficher les documents retirés »).",
               "bulletins_archives": "Bulletins archivés : une copie PDF figée a été rangée dans les archives.",
               "doc_prepare": "Brouillon préparé : relisez le texte, puis soumettez-le à la signature ou à la validation requise.",
               "doc_modifie": "Texte du brouillon enregistré.", "doc_soumis": "Document soumis : il attend la signature ou la validation requise.",
               "doc_signe": "Signature ou validation enregistrée : le document porte son numéro et peut être imprimé.",
               "doc_renvoye": "Document renvoyé en brouillon.", "doc_annule": "Document annulé : il reste dans la liste, marqué « Annulé ».",
               "dossier_complet": "Dossier déclaré complet.", "dossier_incomplet": "Dossier remis à « incomplet ».",
               "renvoi": "Élève renvoyé : son dossier reste dans les archives (mention « Renvoyé ») et son matricule est libéré.",
               "decision": "Décision enregistrée.", "annulee": "Décision annulée : elle reste visible dans la liste, marquée « Annulée ».",
               "rapport": "Rapport envoyé au Préfet.",
               "pa_choix": "Classe d'accueil enregistrée : elle sera utilisée lors de l'exécution du passage (uniquement si l'élève réussit).",
               "pa_rien": "Aucune modification : les classes d'accueil choisies étaient déjà enregistrées.",
               "pa_execute": "Passage exécuté : les élèves qui ont réussi sont inscrits dans la classe supérieure, ceux qui ont échoué dans la même "
                             "classe (redoublants), de l'année scolaire suivante.",
               "pa_annule": "Passage annulé : l'inscription de l'année suivante est retirée ; la trace de l'opération est conservée.",
               "h_creer": "Horaire créé : placez maintenant les cours dans la grille.", "h_vacation": "Vacation de la classe modifiée.",
               "h_placer": "Cours placé.", "h_retirer": "Cours retiré de la grille.", "h_deplacer": "Cours déplacé.",
               "h_professeur": "Professeur du cours modifié.", "h_publier": "Horaire publié : les professeurs et les responsables peuvent le consulter.",
               "h_depublier": "Horaire retiré de la publication (il redevient un brouillon).", "h_supprimer": "Horaire supprimé.",
               "h_heures": "Heures de la vacation enregistrées.", "h_publier_tout": "Publication terminée.",
               "n_demander": "Demande envoyée au professeur : il la voit dans l'onglet « Corrections » de son espace.",
               "n_demander_fermee": "Demande envoyée au professeur. Attention : la saisie de cette période est fermée ; le titulaire de la classe "
                                    "doit la rouvrir pour que le professeur puisse saisir ou corriger.",
               "n_annuler": "Demande annulée : elle reste visible dans la liste, marquée « Annulée ».",
               "n_relancer": "Demandes envoyées aux professeurs concernés (voir l'onglet « Demandes »).",
               "n_rien": "Aucune nouvelle demande : chaque fiche en retard a déjà une demande ouverte (ou n'a pas de professeur)."}
MESSAGES_OK.update(etudes_gestion.MESSAGES_OK)
VUES_HORAIRE = ("classes", "heures", "professeurs", "conflits")
VUES_STATS = ("moyennes", "classement", "reussite", "comparaison", "rapports")
VUES_BULLETINS = ("apercu", "classe", "anomalies")
VUES_NOTES = ("synthese", "verif", "manquantes", "demandes")


def _contexte_prefecture(c, s, forcer=None) -> dict:
    """Données de la page Préfecture : fonctionnalité choisie (?f=tableau|suivi|finances|decisions|discipline|etudes), année (?annee=), filtres (?q=, ?classe=,
    ?filtre=, ?cle= : période des résultats) et élève ouvert (?eleve=). Le calcul et les droits restent dans prefecture.py (relus à chaque requête)."""
    cles = [f[0] for f in config.FONCTIONNALITES_PREFECTURE]
    f = forcer or request.args.get("f", cles[0])
    f = f if f in cles else cles[0]
    ctx = {"prefecture": True, "fonction": f, "fonctions": config.FONCTIONNALITES_PREFECTURE, "erreur": "",
           "annees": [], "annee": request.args.get("annee", "").strip(), "q": request.args.get("q", "").strip(),
           "classe": request.args.get("classe", "").strip(), "filtre": request.args.get("filtre", "").strip(),
           "tb": None, "liste": None, "classes": [], "dossier": None, "fin": None, "fin_eleve": None,
           "disc": None, "disc_eleve": None, "etu": None, "bulletin": None, "cle": request.args.get("cle", "").strip(),
           "docs": None, "liste_eleves": None, "decisions": None, "renvois": None, "rapports": [], "categories": config.CATEGORIES_DECISION, "directions": [],
           "categorie": request.args.get("categorie", "").strip(), "dir_filtre": request.args.get("direction", "").strip(),
           "aujourdhui": date.today().isoformat(), "form": {}, "peut_ajout": False, "peut_modif": False}
    try:
        prefecture.exiger(c, s)
        ctx["annees"] = prefecture.liste_annees(c)
        if f == "tableau":
            ctx["tb"] = prefecture.tableau_de_bord(c, s, ctx["annee"])
            ctx["annee"] = ctx["tb"]["annee"] or ""
        elif f == "suivi":
            eleve = request.args.get("eleve", "").strip()
            if eleve:
                try:
                    ctx["dossier"] = prefecture.profil_eleve(c, s, eleve)
                except prefecture.ErreurPrefecture as ex:
                    ctx["erreur"] = str(ex)
            if ctx["dossier"] is None:
                ctx["liste"] = prefecture.chercher_eleves(c, s, ctx["annee"], ctx["q"], ctx["classe"])
                ctx["annee"] = ctx["liste"]["annee"] or ""
                ctx["classes"] = prefecture.classes_pour_le_suivi(c, s, ctx["annee"])
        elif f == "finances":
            try:
                prefecture.exiger_finances(c, s)
            except PermissionError as ex:                 # pas de Lecture sur « Paiement des frais » : message dans la page, pas de refus brutal
                ctx["erreur"] = str(ex)
            else:
                eleve = request.args.get("eleve", "").strip()
                if eleve:
                    try:
                        ctx["fin_eleve"] = prefecture.finances_eleve(c, s, eleve, ctx["annee"])
                        ctx["annee"] = ctx["fin_eleve"]["annee"]
                    except prefecture.ErreurPrefecture as ex:
                        ctx["erreur"] = str(ex)
                if ctx["fin_eleve"] is None:
                    ctx["fin"] = prefecture.situation_financiere(c, s, ctx["annee"], ctx["q"], ctx["classe"], ctx["filtre"])
                    ctx["annee"] = ctx["fin"]["annee"] or ""
                    ctx["filtre"] = ctx["fin"]["filtre"]
                    ctx["classes"] = prefecture.classes_pour_le_suivi(c, s, ctx["annee"])
        elif f == "discipline":
            eleve = request.args.get("eleve", "").strip()
            if eleve:
                try:
                    ctx["disc_eleve"] = prefecture.discipline_eleve(c, s, eleve, ctx["annee"])
                    ctx["annee"] = ctx["disc_eleve"]["annee"]
                except prefecture.ErreurPrefecture as ex:
                    ctx["erreur"] = str(ex)
            if ctx["disc_eleve"] is None:
                ctx["disc"] = prefecture.consultation_discipline(c, s, ctx["annee"], ctx["q"], ctx["classe"], ctx["filtre"])
                ctx["annee"] = ctx["disc"]["annee"] or ""
                ctx["filtre"] = ctx["disc"]["filtre"]
                ctx["classes"] = prefecture.classes_pour_le_suivi(c, s, ctx["annee"])
        elif f == "etudes":
            eleve = request.args.get("eleve", "").strip()
            if eleve:
                try:
                    ctx["bulletin"] = prefecture.bulletin_eleve(c, s, eleve, ctx["annee"])
                    ctx["annee"] = ctx["bulletin"]["annee"]
                except prefecture.ErreurPrefecture as ex:
                    ctx["erreur"] = str(ex)
            if ctx["bulletin"] is None:
                ctx["etu"] = prefecture.consultation_etudes(c, s, ctx["annee"], ctx["classe"], ctx["cle"])
                ctx["annee"] = ctx["etu"]["annee"] or ""
        elif f == "renvois":
            ctx["peut_renvoyer"] = renvoi.peut_renvoyer(c, s)
            ctx["renvois"] = renvoi.liste_renvois(c, s)
        elif f == "proclamation":
            ctx["pr"] = _contexte_proclamation(c, s, "prefecture")
        elif f == "documents":
            ctx["docs"] = _contexte_documents(c, s)
        elif f == "listes":
            ctx["liste_eleves"] = _donnees_listes(c, s, "prefecture")
        else:                                              # decisions
            ctx["peut_ajout"] = prefecture.peut_ecrire(c, s, "AJOUT")
            ctx["peut_modif"] = prefecture.peut_ecrire(c, s, "MODIFICATION")
            ctx["decisions"] = prefecture.liste_decisions(c, s, ctx["annee"], ctx["categorie"])
            ctx["rapports"] = prefecture.rapports_des_responsables(c, s, ctx["dir_filtre"], ctx["annee"])
            ctx["directions"] = [(cle, TITRES[cle]) for cle in config.FONCTIONNALITES_DIRECTIONS]
    except prefecture.ErreurPrefecture as ex:
        ctx["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return ctx


def _contexte_horaire(c, s, args=None) -> dict:
    """Page « Élaboration horaire » : vue (?vue=classes|heures|professeurs|conflits), année (?annee=), classe ouverte (?classe=) et
    professeur (?prof=). Tout le calcul et les droits sont dans horaires.py (relus à chaque requête)."""
    a = args if args is not None else request.args
    vue = a.get("vue", "classes") if a.get("vue", "classes") in VUES_HORAIRE else "classes"
    h = {"vue": vue, "vues": (("classes", "Horaires des classes"), ("heures", "Heures, pauses et récréations"),
                              ("professeurs", "Horaires des professeurs"), ("conflits", "Conflits")),
         "annee": a.get("annee", "").strip(), "annees": [], "classes": [], "grille": None, "params": None, "profs": [], "prof": None,
         "conflits": None, "agents": [], "peut": {}, "nb_conflits": 0, "jours": horaires.jours(), "classe": a.get("classe", "").strip(),
         "matricule": a.get("prof", "").strip(), "erreur": ""}
    try:
        horaires.exiger(c, s, "LECTURE")
        h["peut"] = {d: horaires.peut(c, s, d) for d in ("AJOUT", "MODIFICATION", "SUPPRESSION")}
        h["annees"] = horaires.liste_annees(c)
        liste = horaires.classes(c, s, h["annee"])
        h["annee"], h["classes"], h["nb_conflits"] = liste["annee"], liste["classes"], liste["nb_conflits"]
        if vue == "classes" and h["classe"]:
            h["grille"] = horaires.grille(c, s, h["annee"], h["classe"])
            h["agents"] = horaires.professeurs(c, s)
        elif vue == "heures":
            h["params"] = horaires.parametres(c, s, h["annee"])["vacations"]
        elif vue == "professeurs":
            h["profs"] = horaires.liste_professeurs_horaire(c, s, h["annee"])["professeurs"]
            if h["matricule"]:
                h["prof"] = horaires.horaire_professeur(c, s, h["annee"], h["matricule"])
        elif vue == "conflits":
            h["conflits"] = horaires.conflits(c, s, h["annee"])
    except horaires.ErreurHoraire as ex:
        h["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return h


def _contexte_heures(c, s, args=None) -> dict:
    """Page « Présences et heures des professeurs » : année (?annee=), période (?du=, ?au=), recherche (?q=) et professeur ouvert (?prof=).
    Consultation seule ; le calcul et les droits sont dans heures_profs.py (relus à chaque requête)."""
    a = args if args is not None else request.args
    hp = {"annee": a.get("annee", "").strip(), "annees": [], "du": a.get("du", "").strip(), "au": a.get("au", "").strip(),
          "q": a.get("q", "").strip(), "matricule": a.get("prof", "").strip(), "r": None, "d": None, "erreur": "",
          "raccourcis": heures_profs.raccourcis(), "legende": heures_profs.LIBELLES}
    if not hp["du"] and not hp["au"]:
        hp["du"], hp["au"] = heures_profs.periode_par_defaut()
    try:
        horaires.exiger(c, s, "LECTURE")
        hp["annees"] = horaires.liste_annees(c)
        if hp["matricule"]:
            hp["d"] = heures_profs.detail(c, s, hp["annee"], hp["matricule"], hp["du"], hp["au"])
            hp["annee"] = hp["d"]["annee"]
        else:
            hp["r"] = heures_profs.liste(c, s, hp["annee"], hp["du"], hp["au"], hp["q"])
            hp["annee"] = hp["r"]["annee"]
    except horaires.ErreurHoraire as ex:
        hp["erreur"] = str(ex)
        if not hp["annee"] and hp["annees"]:
            hp["annee"] = hp["annees"][0]
    except PermissionError:
        abort(403)
    return hp


def _contexte_notes(c, s, args=None) -> dict:
    """Page « Contrôle des notes » : vue (?vue=synthese|manquantes|demandes), année (?annee=), période (?cle=), classe (?classe=), professeur
    (?prof=), statut des demandes (?statut=), périodes en cours (?en_cours=1) et fiche ouverte (?cc= avec ?cle=). Tout le calcul et les droits
    sont dans controle_notes.py (relus à chaque requête)."""
    a = args if args is not None else request.args
    vue = a.get("vue", "synthese") if a.get("vue", "synthese") in VUES_NOTES else "synthese"
    n = {"vue": vue, "vues": (("synthese", "Situation par période"), ("verif", "Vérification des notes"), ("manquantes", "Notes manquantes"), ("demandes", "Demandes de correction")),
         "annee": a.get("annee", "").strip(), "annees": [], "cle": a.get("cle", "").strip(), "classe": a.get("classe", "").strip(),
         "prof": a.get("prof", "").strip(), "statut": a.get("statut", "OUVERTE").strip(), "en_cours": a.get("en_cours", "") == "1",
         "cc": a.get("cc", "").strip(), "eleve": a.get("eleve", "").strip(), "id_cours": a.get("cours", "").strip(), "verif": None, "classes": [], "cours": [], "synthese": None, "manquantes": None, "demandes": None, "fiche": None, "peut": {}, "erreur": "",
         "statuts": controle_notes.STATUTS, "types": controle_notes.TYPES_DEMANDE}
    try:
        controle_notes.exiger(c, s, "LECTURE")
        n["peut"] = {d: controle_notes.peut(c, s, d) for d in ("AJOUT", "MODIFICATION")}
        n["annees"] = controle_notes.liste_annees(c)
        if n["cc"]:
            n["fiche"] = controle_notes.fiche(c, s, n["cc"], n["cle"])
            n["annee"], n["cle"] = n["fiche"]["annee"], n["fiche"]["cle"]
        elif vue == "synthese":
            n["synthese"] = controle_notes.synthese(c, s, n["annee"], n["cle"], n["classe"] or None)
            n["annee"], n["cle"] = n["synthese"]["annee"], n["synthese"]["cle"]
        elif vue == "verif":
            n["annee"] = controle_notes._annee(c, n["annee"])
            n["classes"] = controle_notes.liste_classes(c, n["annee"])
            n["cours"] = controle_notes.liste_cours(c, n["annee"], n["classe"] or None)
            n["periodes"] = controle_notes.calendrier(c, n["annee"])
            if n["classe"] or n["eleve"] or n["id_cours"]:
                n["verif"] = controle_notes.verifier(c, s, n["annee"], n["classe"] or None, n["id_cours"] or None, n["eleve"], n["cle"])
        elif vue == "manquantes":
            n["manquantes"] = controle_notes.manquantes(c, s, n["annee"], n["prof"], n["en_cours"])
            n["annee"] = n["manquantes"]["annee"]
        else:
            n["demandes"] = controle_notes.liste_demandes(c, s, n["annee"], "" if n["statut"] == "tout" else n["statut"], n["prof"])
            n["annee"] = n["demandes"][0]["annee"] if n["demandes"] else (n["annee"] or (n["annees"][0] if n["annees"] else ""))
    except controle_notes.ErreurControle as ex:
        n["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return n


def _contexte_bulletins(c, s, args=None) -> dict:
    """Page « Gestion des bulletins » : vue (?vue=apercu|classe|anomalies), année (?annee=), période, semestre ou année (?cle=), classe (?classe=),
    élève (?eleve=, avec la classe), filtres des anomalies (?gravite=, ?code=) et périodes en cours (?en_cours=1). Calcul et droits : gestion_bulletins.py."""
    a = args if args is not None else request.args
    vue = a.get("vue", "apercu") if a.get("vue", "apercu") in VUES_BULLETINS else "apercu"
    b = {"vue": vue, "vues": (("apercu", "Vue d'ensemble"), ("classe", "Résultats d'une classe"), ("anomalies", "Erreurs et données manquantes")),
         "annee": a.get("annee", "").strip(), "annees": [], "cle": a.get("cle", "").strip(), "classe": a.get("classe", "").strip(),
         "eleve": a.get("eleve", "").strip(), "gravite": a.get("gravite", "").strip(), "code": a.get("code", "").strip(),
         "en_cours": a.get("en_cours", "") == "1", "apercu": None, "resultats": None, "bulletin": None, "anomalies": None, "classes": [], "erreur": ""}
    try:
        gestion_bulletins.exiger(c, s, "LECTURE")
        b["annees"] = gestion_bulletins.liste_annees(c)
        b["annee"] = gestion_bulletins.controle_notes._annee(c, b["annee"])
        b["classes"] = gestion_bulletins._classes_visibles(c, s, b["annee"])
        if vue == "classe" and b["classe"] and b["eleve"]:
            b["bulletin"] = gestion_bulletins.bulletin_eleve(c, s, b["annee"], b["classe"], b["eleve"], b["cle"], b["en_cours"])
            b["cle"] = b["bulletin"]["cle"]
        elif vue == "classe" and b["classe"]:
            b["resultats"] = gestion_bulletins.resultats_classe(c, s, b["annee"], b["classe"], b["cle"], b["en_cours"])
            b["cle"] = b["resultats"]["cle"]
        elif vue == "anomalies":
            b["anomalies"] = gestion_bulletins.anomalies(c, s, b["annee"], b["classe"] or None, b["cle"], b["gravite"], b["code"], b["en_cours"])
        elif vue == "apercu":
            b["apercu"] = gestion_bulletins.apercu(c, s, b["annee"], b["cle"], b["en_cours"])
            b["cle"] = b["apercu"]["cle"]
    except controle_notes.ErreurControle as ex:
        b["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return b


def _contexte_stats(c, s, args=None) -> dict:
    """Page « Statistiques et rapports scolaires » : vue (?vue=moyennes|classement|reussite|comparaison|rapports), année (?annee=), période, examen,
    semestre ou année (?cle=), classe (?classe=) et niveau de comparaison (?niveau=). Calcul et droits : statistiques_scolaires.py."""
    a = args if args is not None else request.args
    vue = a.get("vue", "moyennes") if a.get("vue", "moyennes") in VUES_STATS else "moyennes"
    t = {"vue": vue, "vues": (("moyennes", "Moyennes"), ("classement", "Classement"), ("reussite", "Réussite et échec"),
                              ("comparaison", "Comparaison des périodes"), ("rapports", "Rapports classes et enseignants")),
         "annee": a.get("annee", "").strip(), "annees": [], "cle": a.get("cle", "").strip(), "classe": a.get("classe", "").strip(),
         "niveau": a.get("niveau", "classes").strip(), "niveaux": statistiques_scolaires.NIVEAUX_COMPARAISON, "classes": [], "portees": [],
         "s": None, "c": None, "erreur": ""}
    try:
        statistiques_scolaires.exiger(c, s, "LECTURE")
        t["annees"] = statistiques_scolaires.liste_annees(c)
        t["annee"] = statistiques_scolaires.controle_notes._annee(c, t["annee"])
        t["classes"] = statistiques_scolaires.classes_disponibles(c, s, t["annee"])
        if vue == "comparaison":
            t["c"] = statistiques_scolaires.comparaison(c, s, t["annee"], t["niveau"], t["classe"] or None) if (t["niveau"] == "classes" or t["classe"]) else None
            if t["c"] is None:
                t["erreur"] = "Choisissez une classe pour comparer ses cours ou ses élèves."
        elif vue == "classement" and not t["classe"]:
            t["s"] = statistiques_scolaires.statistiques(c, s, t["annee"], t["cle"], None)
            t["portees"], t["cle"] = t["s"]["portees"], t["s"]["cle"]
        else:
            t["s"] = statistiques_scolaires.statistiques(c, s, t["annee"], t["cle"], t["classe"] or None if vue in ("moyennes", "classement") else None)
            t["portees"], t["cle"] = t["s"]["portees"], t["s"]["cle"]
    except controle_notes.ErreurControle as ex:
        t["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return t


def _contexte_proclamation(c, s, sous, a=None, erreur="") -> dict:
    """Proclamation des résultats (?annee=, ?classe=, ?cle=) : liste des proclamations de l'année et, si une classe et une période sont
    choisies, le détail (frais exigés, élèves, décisions). Calcul et droits : proclamation.py (relus à chaque requête)."""
    a = a if a is not None else request.args
    pr = {"sous": sous, "annee": a.get("annee", "").strip(), "classe": a.get("classe", "").strip(), "cle": a.get("cle", "").strip(),
          "liste": {"annees": [], "proclamations": []}, "classes": [], "portees": [], "detail": None, "frais": [], "erreur": erreur}
    try:
        pr["liste"] = proclamation.liste_proclamations(c, s, pr["annee"] or None)
        pr["annee"] = pr["liste"]["annee"]
        if sous == "direction_etudes":
            pr["classes"] = gestion_bulletins._classes_visibles(c, s, pr["annee"])
            pr["portees"] = bulletins._portees(c, pr["annee"], sections.SECONDAIRE)
        if pr["classe"] and pr["cle"]:
            pr["detail"] = proclamation.apercu(c, s, pr["annee"], pr["classe"], pr["cle"])
            if sous == "direction_etudes" and pr["detail"]["statut"] == "AUTORISEE":
                pr["frais"] = proclamation.frais_disponibles(c, s, pr["annee"], pr["classe"])
    except (proclamation.ErreurProclamation, controle_notes.ErreurControle) as ex:
        pr["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return pr


def _contexte_documents(c, s, erreur="") -> dict:
    """Préfecture > Documents scolaires officiels : liste (?annee=, ?etat=, ?type=, ?q=) ; ?doc=<n> ouvre un document (texte, étapes, PDF) ;
    ?nouveau=1 ouvre le formulaire de préparation. Règles et droits : documents_officiels.py (relus à chaque requête)."""
    a = request.values
    d = {"liste": None, "doc": None, "eleves": [], "form": {}, "erreur": erreur, "annee": a.get("annee", "").strip(), "etat": a.get("etat", "").strip(),
         "type": a.get("type", "").strip(), "q": a.get("q", "").strip(), "nouveau": a.get("nouveau") == "1"}
    try:
        if a.get("doc", "").strip():
            d["doc"] = documents_officiels.lire(c, s, a.get("doc"))
            d["peut_ajout"], d["peut_modif"] = documents_officiels.peut(c, s, "AJOUT"), documents_officiels.peut(c, s, "MODIFICATION")
            d["approbations"] = config.APPROBATIONS_DOCUMENT
        else:
            d["liste"] = documents_officiels.liste(c, s, d["annee"], d["etat"], d["type"], d["q"])
            d["annee"] = d["liste"]["annee"] or ""
            if d["nouveau"] and d["liste"]["peut_ajout"]:
                d["eleves"] = documents_officiels.eleves_inscrits(c, s, d["annee"])["eleves"]
    except documents_officiels.ErreurDocument as ex:
        d["erreur"] = str(ex)
        if d["liste"] is None and d["doc"] is None:
            d["liste"] = documents_officiels.liste(c, s, d["annee"], "", "", "")
    except prefecture.ErreurPrefecture as ex:
        d["erreur"] = str(ex)
    return d


def _contexte_secretariat(c, s, erreur="") -> dict:
    """Page Secrétariat : liste des dossiers des élèves (?classe=, ?etat=, ?q=). L'état « complet » est décidé par la secrétaire
    (secretariat.py : droits relus à chaque requête, aucune pièce obligatoire)."""
    classe = request.values.get("classe", "").strip()
    classe = classe if classe.isdigit() else ""
    q = request.values.get("q", "").strip()
    fonction = request.values.get("f", "dossiers")
    fonction = fonction if fonction in [x[0] for x in config.FONCTIONNALITES_SECRETARIAT] else "dossiers"
    ctx = {"secr": {"fonctions": config.FONCTIONNALITES_SECRETARIAT, "fonction": fonction, "classe": classe, "q": q,
                    "etats": secretariat.ETATS, "classes": [], "liste": None, "peut_modifier": False}, "erreur": erreur}
    if fonction == "bulletins":
        return _contexte_bulletins_secretariat(c, s, ctx)
    if fonction == "archives":
        return _contexte_archives(c, s, ctx)
    if fonction == "listes":
        return _contexte_listes(c, s, ctx)
    try:
        ctx["secr"]["classes"] = secretariat.classes_pour_le_filtre(c, s)
        ctx["secr"]["liste"] = secretariat.liste_dossiers(c, s, request.args.get("etat", "tous"), q, classe or None)
        ctx["secr"]["peut_modifier"] = secretariat.peut(c, s, "MODIFICATION")
    except PermissionError:
        abort(403)
    return ctx


def _parametres_listes(a) -> dict:
    """Paramètres des listes administratives lus dans la requête : ?genre= (eleves | incomplets), ?annee=, ?classe=, ?option=, ?desactives=1."""
    return {"genre": a.get("genre", "eleves") if a.get("genre") in dict(listes_administratives.GENRES) else "eleves",
            "annee": a.get("annee", "").strip(), "n_classe": a.get("classe", "").strip(), "option": a.get("option", "").strip(),
            "desactives": a.get("desactives") == "1"}


def _contexte_listes(c, s, ctx) -> dict:
    """Secrétariat > Listes et rapports administratifs : liste des élèves ou des dossiers incomplets par classe, option et année scolaire.
    Droits et règles : listes_administratives.py (relus à chaque requête)."""
    ctx["secr"]["listes"] = _donnees_listes(c, s, "dossier_eleve")
    return ctx


def _donnees_listes(c, s, espace) -> dict:
    """Liste des élèves par classe, option et année pour un espace (Secrétariat, Direction des études, Direction de discipline, Préfecture) :
    filtres de la requête, années, classes et liste. Le droit de Lecture du module de l'espace est relu ici."""
    p = _parametres_listes(request.args)
    if espace != "dossier_eleve":
        p["genre"] = "eleves"                        # les dossiers incomplets sont propres au Secrétariat
    li = {"p": p, "espace": espace, "genres": listes_administratives.GENRES, "annees": [], "filtres": None, "liste": None}
    try:
        li["annees"] = listes_administratives.annees(c, s, espace)
        p["annee"] = p["annee"] or (li["annees"][0] if li["annees"] else "")
        li["filtres"] = listes_administratives.filtres(c, s, p["annee"], espace)
        li["liste"] = listes_administratives.liste(c, s, espace=espace, **p)
    except PermissionError:
        abort(403)
    return li


def _contexte_archives(c, s, ctx, saisie=None, params=None) -> dict:
    """Secrétariat > Archives scolaires : recherche (?q= élève, ?annee=, ?genre=, ?anciens=1, ?retires=1), dossier d'un élève (?eleve=) ou
    formulaire de classement (?vue=classer, éventuellement ?eleve=). `saisie` : valeurs du formulaire à réafficher après une erreur ;
    `params` : paramètres à utiliser à la place de ceux de la requête. Droits et règles : archives_scolaires.py (relus à chaque requête)."""
    a = params if params is not None else request.values
    ar = {"vue": "recherche", "rech": None, "dossier": None, "genres": archives_scolaires.genres(), "categories": archives_scolaires.categories(),
          "annees": [], "saisie": saisie or {}, "peut_classer": False, "taille_max_mo": config.TAILLE_MAX_ARCHIVE // (1024 * 1024),
          "q": a.get("q", "").strip(), "annee": a.get("annee", "").strip(), "genre": a.get("genre", "").strip(), "anciens": a.get("anciens") == "1",
          "retires": a.get("retires") == "1", "eleve": a.get("eleve", "").strip()}
    ctx["secr"]["arch"] = ar
    try:
        ar["annees"] = archives_scolaires.annees(c)
        ar["peut_classer"] = archives_scolaires.peut(c, s, "MODIFICATION")
        if a.get("vue") == "classer" and ar["peut_classer"]:
            ar["vue"] = "classer"
            if ar["eleve"]:
                try:
                    ar["eleve_nom"] = archives_scolaires._eleve(c, s, ar["eleve"])["nom"]
                except archives_scolaires.ErreurArchives:
                    ar["eleve"] = ""
        elif ar["eleve"]:
            ar["vue"] = "dossier"
            ar["dossier"] = archives_scolaires.dossier(c, s, ar["eleve"])
        else:
            ar["rech"] = archives_scolaires.rechercher(c, s, ar["q"], ar["annee"], ar["genre"], ar["anciens"], ar["retires"])
    except PermissionError:
        abort(403)
    except archives_scolaires.ErreurArchives as ex:
        ctx["erreur"] = ctx.get("erreur") or str(ex)
        ar["vue"] = "recherche"
        ar["eleve"] = ""
        ar["rech"] = archives_scolaires.rechercher(c, s, ar["q"], ar["annee"], ar["genre"], ar["anciens"], ar["retires"])
    return ctx


def _contexte_bulletins_secretariat(c, s, ctx) -> dict:
    """Secrétariat > Bulletins scolaires : liste des bulletins validés par la Préfecture (?annee=, ?classe=, ?cle=, ?option=), puis le détail
    d'une classe et d'une période (?classe= et ?cle= : les deux), avec ses archives. Droits et règles : bulletins_secretariat.py."""
    a = request.values
    b = {"annee": a.get("annee", "").strip(), "classe": ctx["secr"]["classe"], "cle": a.get("cle", "").strip(), "option": a.get("option", "").strip(),
         "liste": None, "detail": None, "archives": [], "peut_archiver": False, "erreur": ""}
    ctx["secr"]["bul"] = b
    try:
        b["liste"] = bulletins_secretariat.liste(c, s, b["annee"], b["classe"] or None, b["cle"], b["option"])
        b["annee"] = b["liste"]["annee"]
        b["peut_archiver"] = bulletins_secretariat.peut(c, s, "MODIFICATION")
        if a.get("vue") == "archives":
            b["archives"] = bulletins_secretariat.archives(c, s, b["annee"], b["classe"] or None, b["cle"], b["option"])
        elif b["classe"] and b["cle"]:
            b["detail"] = bulletins_secretariat.detail(c, s, b["annee"], b["classe"], b["cle"])
    except PermissionError:
        abort(403)
    except (bulletins_secretariat.ErreurBulletinsSecretariat, controle_notes.ErreurControle) as ex:   # ex. : aucune année scolaire définie
        b["erreur"] = str(ex)
    b["vue"] = "archives" if a.get("vue") == "archives" else "bulletins"
    return ctx


VUES_CONDUITE = (("apercu", "Vue d'ensemble"), ("professeurs", "Observations des professeurs"), ("registre", "Observations, incidents et mentions"),
                 ("eleve", "Historique d'un élève"))


def _contexte_conduite(c, s, args=None) -> dict:
    """Direction de discipline > Suivi de la conduite : vue (?vue=apercu|professeurs|registre|eleve), année (?annee=), classe (?classe=), période
    (?periode=), filtres du registre (?genre=, ?nature=, ?du=, ?au=, ?annulees=1), recherche (?q=) et élève (?eleve=). Calculs et droits : suivi_conduite.py."""
    a = args if args is not None else request.args
    vue = a.get("vue", "apercu") if a.get("vue", "apercu") in dict(VUES_CONDUITE) else "apercu"
    cd = {"vue": vue, "vues": VUES_CONDUITE, "annee": a.get("annee", "").strip(), "annees": [], "classe": a.get("classe", "").strip(), "periode": a.get("periode", "").strip(),
          "genre": a.get("genre", "").strip(), "nature": a.get("nature", "").strip(), "du": a.get("du", "").strip(), "au": a.get("au", "").strip(),
          "annulees": a.get("annulees", "") == "1", "q": a.get("q", "").strip(), "eleve": a.get("eleve", "").strip(),
          "apercu": None, "profs": None, "registre": None, "recherche": None, "fiche": None, "classes": [], "erreur": "", "form": {},
          "peut_ajouter": False, "peut_annuler": False, "reglement": suivi_conduite.reglement(), "genres": suivi_conduite.GENRES,
          "natures": suivi_conduite.NATURES, "aujourdhui": date.today().isoformat()}
    try:
        suivi_conduite.exiger(c, s)
        cd["peut_ajouter"] = suivi_conduite.peut(c, s, "AJOUT")
        cd["peut_annuler"] = suivi_conduite.peut(c, s, "MODIFICATION")
        cd["annees"] = suivi_conduite.liste_annees(c, s)
        cd["annee"] = cd["annee"] or next((x["annee"] for x in cd["annees"] if x["en_cours"]), cd["annees"][0]["annee"] if cd["annees"] else "")
        cd["classes"] = suivi_conduite.classes(c, s, cd["annee"])
        if vue == "apercu":
            cd["apercu"] = suivi_conduite.apercu(c, s, cd["annee"], cd["classe"])
        elif vue == "professeurs" and cd["classe"]:
            cd["profs"] = suivi_conduite.observations_professeurs(c, s, cd["annee"], cd["classe"], cd["periode"])
        elif vue == "registre":
            cd["registre"] = suivi_conduite.registre(c, s, cd["annee"], cd["classe"], cd["genre"], cd["nature"], cd["du"], cd["au"], cd["annulees"])
        elif vue == "eleve":
            if cd["eleve"]:
                cd["fiche"] = suivi_conduite.historique_eleve(c, s, cd["eleve"], cd["annee"])
                cd["annee"] = cd["fiche"]["annee"]
            elif cd["q"]:
                cd["recherche"] = suivi_conduite.chercher_eleves(c, s, cd["annee"], cd["q"])
    except suivi_conduite.ErreurConduite as ex:
        cd["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return cd


VUES_CONVOCATION = (("nouvelle", "Nouvelle convocation"), ("liste", "Convocations enregistrées"))


def _contexte_convocation(c, s, args=None) -> dict:
    """Direction de discipline > Convocation du parent : vue (?vue=nouvelle|liste), recherche d'élève (?q=), élève choisi (?eleve=), statut (?statut=),
    classe (?classe=), recherche dans la liste (?recherche=) et convocation ouverte (?id=). Calculs et droits : convocations.py."""
    a = args if args is not None else request.args
    vue = a.get("vue", "nouvelle") if a.get("vue", "nouvelle") in dict(VUES_CONVOCATION) else "nouvelle"
    if a.get("id", "").strip():
        vue = "liste"
    cv = {"vue": vue, "vues": VUES_CONVOCATION, "q": a.get("q", "").strip(), "eleve": a.get("eleve", "").strip(), "statut": a.get("statut", "").strip(),
          "classe": a.get("classe", "").strip(), "recherche": a.get("recherche", "").strip(), "id": a.get("id", "").strip(), "erreur": "", "form": {},
          "trouves": None, "fiche": None, "liste": None, "detail": None, "classes": [], "peut_envoyer": False, "peut_annuler": False,
          "aujourdhui": date.today().isoformat(), "lieu_defaut": config.CONVOCATION_LIEU_DEFAUT}
    try:
        convocations.exiger(c, s)
        cv["peut_envoyer"] = convocations.peut(c, s, "AJOUT")
        cv["peut_annuler"] = convocations.peut(c, s, "MODIFICATION")
        if vue == "nouvelle":
            if cv["eleve"]:
                cv["fiche"] = convocations.coordonnees_parent(c, s, cv["eleve"])
            elif cv["q"]:
                cv["trouves"] = convocations.chercher_eleves(c, s, cv["q"])
        else:
            cv["classes"] = suivi_conduite.classes(c, s)
            if cv["id"]:
                cv["detail"] = convocations.detail(c, s, cv["id"])
            else:
                cv["liste"] = convocations.liste(c, s, cv["statut"], cv["classe"], cv["recherche"])
    except (convocations.ErreurConvocation, suivi_conduite.ErreurConduite) as ex:
        cv["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return cv


VUES_PRESENCES = (("jour", "Présence du jour"), ("classe", "Absences par classe"), ("eleve", "Absences par élève"))


def _contexte_presences(c, s, args=None) -> dict:
    """Direction de discipline > Gestion des présences : vue (?vue=jour|classe|eleve), année (?annee=), jour (?jour=), classe (?classe=),
    période (?du=, ?au=), recherche (?q=) et élève (?eleve=). Le calcul et les droits sont dans gestion_presences.py (relus à chaque requête)."""
    a = args if args is not None else request.args
    vue = a.get("vue", "jour") if a.get("vue", "jour") in dict(VUES_PRESENCES) else "jour"
    pd = {"vue": vue, "vues": VUES_PRESENCES, "annee": a.get("annee", "").strip(), "annees": [], "jour": a.get("jour", "").strip(), "classe": a.get("classe", "").strip(),
          "du": a.get("du", "").strip(), "au": a.get("au", "").strip(), "q": a.get("q", "").strip(), "eleve": a.get("eleve", "").strip(),
          "journee": None, "detail": None, "absences": None, "recherche": None, "fiche": None, "classes": [], "erreur": "", "form": {},
          "peut_decider": False, "peut_annuler": False, "statuts": gestion_presences.STATUTS, "aujourdhui": date.today().isoformat()}
    try:
        gestion_presences.exiger(c, s)
        pd["peut_decider"] = gestion_presences.peut(c, s, "AJOUT")
        pd["peut_annuler"] = gestion_presences.peut(c, s, "MODIFICATION")
        pd["annees"] = gestion_presences.liste_annees(c, s)
        pd["annee"] = pd["annee"] or next((x["annee"] for x in pd["annees"] if x["en_cours"]), pd["annees"][0]["annee"] if pd["annees"] else "")
        pd["classes"] = gestion_presences.classes(c, s, pd["annee"])
        if vue == "jour":
            if pd["classe"]:
                pd["detail"] = gestion_presences.classe_du_jour(c, s, pd["annee"], pd["classe"], pd["jour"])
            else:
                pd["journee"] = gestion_presences.journee(c, s, pd["annee"], pd["jour"])
        elif vue == "classe" and pd["classe"]:
            pd["absences"] = gestion_presences.absences_classe(c, s, pd["annee"], pd["classe"], pd["du"], pd["au"])
        elif vue == "eleve":
            if pd["eleve"]:
                pd["fiche"] = gestion_presences.absences_eleve(c, s, pd["annee"], pd["eleve"], pd["du"], pd["au"])
            elif pd["q"]:
                pd["recherche"] = gestion_presences.chercher_eleves(c, s, pd["annee"], pd["q"])
    except gestion_presences.ErreurPresences as ex:
        pd["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return pd


def _contexte_passage(c, s, args=None) -> dict:
    """Passage en classe supérieure : année qui se termine (?annee=) puis vue d'ensemble des classes, ou détail d'une classe (?classe=).
    Calcul et droits : promotion.py (Lecture = consulter ; Ajout = choisir la classe d'accueil et exécuter ; Modification = annuler)."""
    a = args if args is not None else request.args
    pa = {"erreur": "", "annees": [], "annee": (a.get("annee") or "").strip(), "classe": (a.get("classe") or "").strip(), "apercu": None, "detail": None}
    try:
        promotion.exiger(c, s, "LECTURE")
        pa["annees"] = promotion.liste_annees(c)
        if pa["classe"]:
            try:
                pa["detail"] = promotion.detail(c, s, pa["annee"], pa["classe"])
                pa["annee"] = pa["detail"]["annee"]
            except promotion.ErreurPromotion as ex:
                pa["erreur"] = str(ex)
        if pa["detail"] is None:
            pa["apercu"] = promotion.apercu(c, s, pa["annee"])
            pa["annee"] = pa["apercu"]["annee"]
    except promotion.ErreurPromotion as ex:
        pa["erreur"] = str(ex)
    except PermissionError:
        abort(403)
    return pa


def _contexte_direction(c, s, sous, f=None, args=None, extra=None) -> dict:
    """Page d'une direction : fonctionnalité choisie (?f=), puis soit l'élaboration horaire (Direction des études), soit « Rapport au
    Préfet » : formulaire d'envoi (droit Ajout) et rapports déjà envoyés (droit Lecture)."""
    fonctions = config.FONCTIONNALITES_DIRECTIONS[sous]
    cles = [x[0] for x in fonctions]
    f = f or request.args.get("f", cles[0])
    f = f if f in cles else cles[0]
    ctx = {"direction": True, "fonctions": fonctions, "fonction": f, "erreur": "", "form": {},
           "aujourdhui": date.today().isoformat(), "peut_envoyer": False, "rapports": [], "h": None, "hp": None, "n": None, "b": None, "st": None, "pa": None, "liste_eleves": None, "pd": None, "cd": None, "cv": None}
    if f in etudes_gestion.FONCTIONS and sous == "direction_etudes":      # cours, enseignants, présence des élèves (etudes_gestion.py)
        extra = extra or {}
        ctx.update(etudes_gestion.contexte_gestion(c, s, f, args if args is not None else request.args, extra.get("erreur", ""), extra.get("saisie")))
        return ctx
    if f == "horaire":
        ctx["h"] = _contexte_horaire(c, s, args)
        return ctx
    if f == "heures":
        ctx["hp"] = _contexte_heures(c, s, args)
        return ctx
    if f == "notes":
        ctx["n"] = _contexte_notes(c, s, args)
        return ctx
    if f == "bulletins":
        ctx["b"] = _contexte_bulletins(c, s, args)
        return ctx
    if f == "statistiques":
        ctx["st"] = _contexte_stats(c, s, args)
        return ctx
    if f == "listes":
        ctx["liste_eleves"] = _donnees_listes(c, s, sous)
        return ctx
    if f == "passage" and sous == "direction_etudes":
        ctx["pa"] = _contexte_passage(c, s, args)
        return ctx
    if f == "presences" and sous == "direction_discipline":
        ctx["pd"] = _contexte_presences(c, s, args)
        return ctx
    if f == "conduite" and sous == "direction_discipline":
        ctx["cd"] = _contexte_conduite(c, s, args)
        return ctx
    if f == "convocation" and sous == "direction_discipline":
        ctx["cv"] = _contexte_convocation(c, s, args)
        return ctx
    if f == "proclamation" and sous == "direction_etudes":
        ctx["pr"] = _contexte_proclamation(c, s, sous, args)
        return ctx
    ctx["peut_envoyer"] = prefecture.peut_rapport(c, s, sous, "AJOUT")
    try:
        ctx["rapports"] = prefecture.rapports_de_la_direction(c, s, sous)
    except PermissionError:
        abort(403)
    return ctx


def _fonctions_espace(sous) -> tuple:
    """Fonctionnalités (clé, titre, description) d'un espace, telles que la configuration les déclare."""
    if sous == config.ESPACE_PREFECTURE:
        return config.FONCTIONNALITES_PREFECTURE
    if sous == config.ESPACE_SECRETARIAT:
        return config.FONCTIONNALITES_SECRETARIAT
    return config.FONCTIONNALITES_DIRECTIONS.get(sous, ())


def _groupes_boutons(sous, fonctions) -> list:
    """[(titre du groupe, [(clé, titre, description)])] : les fonctionnalités d'un espace en module à part rangées selon ses groupes
    (config.ESPACES_MODULES). Une fonctionnalité qui n'est dans aucun groupe est ajoutée à la fin (« Autres ») : aucune ne peut disparaître
    d'un oubli de configuration."""
    par_cle = {f[0]: f for f in (fonctions or ())}
    groupes, vus = [], set()
    for titre, cles in config.ESPACES_MODULES[sous][2]:
        membres = [par_cle[k] for k in cles if k in par_cle]
        vus.update(k for k in cles if k in par_cle)
        if membres:
            groupes.append((titre, membres))
    reste = [f for k, f in par_cle.items() if k not in vus]
    if reste:
        groupes.append(("Autres", reste))
    return groupes


def enregistrer(app, conn, session_courante, connecte, origine_ok):
    app.jinja_env.globals["groupes_boutons_espace"] = lambda sous: _groupes_boutons(sous, _fonctions_espace(sous))   # pages d'Inscription du Secrétariat

    @app.context_processor
    def _sous_menus_barre_laterale():
        """Espaces ouverts au compte et droit d'inscription, pour les gabarits (barre latérale, pages d'inscription)."""
        try:
            s = session_courante()
        except Exception:
            s = None
        ouverts = modules.sous_menus_ouverts(conn(), s) if s is not None else []
        try:
            peut_inscription = bool(s is not None and inscription.peut(conn(), s, "LECTURE"))
        except Exception:
            peut_inscription = False
        return {"sous_menus_etudes": ouverts, "peut_inscription": peut_inscription}

    def poster():
        if not origine_ok():
            abort(403)

    def page_espace(sous, s, ctx, statut=200):
        ouverts = modules.sous_menus_ouverts(conn(), s)
        ctx.setdefault("ok", MESSAGES_OK.get(request.args.get("ok", ""), ""))
        module_propre = sous in config.ESPACES_MODULES          # chaque espace est un module à part : titre du module, fonctionnalités en boutons
        ctx.setdefault("groupes_boutons", _groupes_boutons(sous, _fonctions_espace(sous)) if module_propre else [])
        return render_template("etudes_sous_menu.html", s=s, cfg=config,
                               titre=config.ESPACES_MODULES[sous][1], sous=sous,
                               titre_sous=config.ESPACES_ETUDES[sous][0], sous_menus=ouverts, module_propre=module_propre,
                               menu_utile=modules.menu_utile(conn(), s), **ctx), statut

    def espace_autorise(sous):
        s = session_courante()
        ouverts = modules.sous_menus_ouverts(conn(), s)
        if sous not in TITRES:
            abort(404)
        if sous not in [c for c, _t in ouverts]:
            abort(403)
        return s

    @app.get("/m/etudes_discipline")
    @connecte
    def etudes_accueil():
        """Ancienne adresse de l'accueil du module (liens enregistrés) : redirige vers le premier module d'espace ouvert au compte."""
        ouverts = modules.modules_ouverts(conn(), session_courante())
        for espace, (cle_module, _titre, _groupes) in config.ESPACES_MODULES.items():
            if cle_module in ouverts:
                return redirect(url_for("etudes_sous_menu", sous=espace))
        abort(403)

    def _route_module(espace, cle_module):
        """/m/<module> d'un espace devenu module à part : s'ouvre directement sur ses fonctionnalités (boutons). Droit relu à chaque requête."""
        @app.get("/m/" + cle_module, endpoint="module_espace_" + cle_module)
        @connecte
        def ouvrir():
            if cle_module not in modules.modules_ouverts(conn(), session_courante()):
                abort(403)
            return redirect(url_for("etudes_sous_menu", sous=espace))
        return ouvrir

    for _espace, (_cle_module, _titre, _groupes) in config.ESPACES_MODULES.items():
        _route_module(_espace, _cle_module)

    # ------------------------------------------------------------------ Direction des études : cours, enseignants, présence des élèves
    def _rendre_gestion(fonction, s, args, erreur, code, saisie):
        """Réaffiche la page d'une fonctionnalité de etudes_gestion.py avec le message d'erreur d'une action refusée."""
        ctx = _contexte_direction(conn(), s, "direction_etudes", fonction, args, {"erreur": erreur, "saisie": saisie})
        return page_espace("direction_etudes", s, ctx, code)

    etudes_gestion.enregistrer(app, conn, session_courante, connecte, origine_ok, espace_autorise, _rendre_gestion)

    # ------------------------------------------------------------------ Direction des études : élaboration horaire
    def _retour_horaire(champs, **plus):
        """Adresse de la page horaire après une action : mêmes année, vue, classe et professeur."""
        args = {k: champs.get(k, "") for k in ("annee", "vue", "classe", "prof") if champs.get(k, "")}
        args.update(plus)
        return url_for("etudes_sous_menu", sous="direction_etudes", f="horaire", **args)

    @app.post("/m/etudes_discipline/direction_etudes/horaire/<action>")
    @connecte
    def etudes_horaire_action(action):
        poster()
        s = espace_autorise("direction_etudes")
        c = conn()
        f = request.form
        annee, classe = f.get("annee", ""), f.get("classe", "")
        faire = {
            "creer": lambda: horaires.creer_horaire(c, s, annee, classe, f.get("vacation", "")),
            "vacation": lambda: horaires.changer_vacation(c, s, annee, classe, f.get("vacation", "")),
            "placer": lambda: horaires.placer(c, s, annee, classe, f.get("jour", ""), f.get("ordre", ""), f.get("id_cc", "")),
            "retirer": lambda: horaires.retirer(c, s, annee, f.get("seance", "")),
            "deplacer": lambda: horaires.deplacer(c, s, annee, f.get("seance", ""), f.get("jour", ""), f.get("ordre", "")),
            "professeur": lambda: horaires.affecter_professeur(c, s, annee, f.get("id_cc", ""), f.get("matricule", "")),
            "publier": lambda: horaires.publier(c, s, annee, classe),
            "depublier": lambda: horaires.retirer_publication(c, s, annee, classe),
            "supprimer": lambda: horaires.supprimer_horaire(c, s, annee, classe),
            "publier_tout": lambda: horaires.publier_tout(c, s, annee),
            "heures": lambda: horaires.definir_parametres(c, s, annee, f.get("vacation", ""), f.get("debut", ""), f.get("duree_cours", ""),
                                                          f.get("nb_avant", ""), f.get("duree_pause", ""), f.get("nb_apres", ""),
                                                          f.get("recreation_apres", "0"), f.get("duree_recreation", "10")),
        }
        if action not in faire:
            abort(404)
        try:
            resultat = faire[action]()
        except PermissionError:
            abort(403)
        except horaires.ErreurHoraire as ex:
            ctx = _contexte_direction(c, s, "direction_etudes", "horaire", f)
            ctx["h"]["erreur"] = str(ex)
            return page_espace("direction_etudes", s, ctx, 400)
        if action == "publier_tout" and resultat["refuses"]:
            ctx = _contexte_direction(c, s, "direction_etudes", "horaire", f)
            ctx["h"]["erreur"] = "Non publiés : " + " | ".join(f"{r['classe']} : {' ; '.join(r['raisons'])}" for r in resultat["refuses"])
            ctx["ok"] = f"{len(resultat['publies'])} horaire(s) publié(s)."
            return page_espace("direction_etudes", s, ctx, 200)
        return redirect(_retour_horaire(f, ok="h_" + action))

    # ------------------------------------------------------------------ consultation et impression des horaires (publiés, sauf pour la direction)
    def _consultation(fonction, *a):
        s = session_courante()
        c = conn()
        if not modules.sous_menus_ouverts(c, s):
            abort(403)
        try:
            return s, fonction(c, s, *a)
        except PermissionError:
            abort(403)
        except horaires.ErreurHoraire:
            abort(404)

    @app.get("/m/etudes_discipline/horaires")
    @connecte
    def etudes_horaires():
        """Consultation des horaires publiés : classes et professeurs, avec le lien d'impression de chacun."""
        annee = request.args.get("annee", "").strip()
        s, l = _consultation(horaires.classes, annee)
        _s, profs = _consultation(horaires.liste_professeurs_horaire, l["annee"])
        return render_template("etudes_horaires.html", s=s, cfg=config, titre="Horaires", classes=l["classes"], profs=profs["professeurs"],
                               annee=l["annee"], annees=horaires.liste_annees(conn()), complet=l["complet"],
                               menu_utile=modules.menu_utile(conn(), s), sous_menus=modules.sous_menus_ouverts(conn(), s))

    @app.get("/m/etudes_discipline/horaires/classe/<int:n_classe>")
    @connecte
    def etudes_horaire_classe(n_classe):
        s, g = _consultation(horaires.grille, request.args.get("annee", ""), n_classe)
        if not g["existe"]:
            abort(404)
        return render_template("etudes_horaire_impression.html", cfg=config, g=g, p=None, aujourdhui=date.today().strftime("%d/%m/%Y"))

    @app.get("/m/etudes_discipline/horaires/professeur/<path:matricule>")
    @connecte
    def etudes_horaire_professeur(matricule):
        s, p = _consultation(horaires.horaire_professeur, request.args.get("annee", ""), matricule)
        return render_template("etudes_horaire_impression.html", cfg=config, g=None, p=p, aujourdhui=date.today().strftime("%d/%m/%Y"))


    # ------------------------------------------------------------------ Direction des études : présences et heures des professeurs (consultation seule)
    def _heures(fonction, *a):
        s = session_courante()
        try:
            return s, fonction(conn(), s, *a)
        except PermissionError:
            abort(403)
        except horaires.ErreurHoraire:
            abort(404)

    @app.get("/m/etudes_discipline/direction_etudes/heures/impression")
    @connecte
    def etudes_heures_impression():
        """Page imprimable : le récapitulatif de tous les professeurs, ou le détail d'un professeur (?prof=)."""
        a = request.args
        if a.get("prof", "").strip():
            s, d = _heures(heures_profs.detail, a.get("annee", ""), a.get("prof", ""), a.get("du", ""), a.get("au", ""))
            r = None
        else:
            s, r = _heures(heures_profs.liste, a.get("annee", ""), a.get("du", ""), a.get("au", ""), a.get("q", ""))
            d = None
        return render_template("etudes_heures_impression.html", cfg=config, r=r, d=d, aujourdhui=date.today().strftime("%d/%m/%Y"))

    @app.get("/m/etudes_discipline/direction_etudes/heures/export.csv")
    @connecte
    def etudes_heures_csv():
        a = request.args
        s, contenu = _heures(heures_profs.exporter_csv, a.get("annee", ""), a.get("du", ""), a.get("au", ""), a.get("q", ""))
        return Response(contenu, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="heures_professeurs.csv"'})

    # ------------------------------------------------------------------ Direction des études : contrôle des notes
    def _retour_notes(champs, **plus):
        """Adresse de la page « Contrôle des notes » après une action : mêmes vue, année, période, fiche, classe, professeur et filtres."""
        args = {k: champs.get(k, "") for k in ("vue", "annee", "cle", "cc", "classe", "prof", "statut", "en_cours", "eleve", "cours") if champs.get(k, "")}
        args.update(plus)
        return url_for("etudes_sous_menu", sous="direction_etudes", f="notes", **args)

    @app.post("/m/etudes_discipline/direction_etudes/notes/<action>")
    @connecte
    def etudes_notes_action(action):
        poster()
        s = espace_autorise("direction_etudes")
        c = conn()
        f = request.form
        if action not in ("demander", "annuler", "relancer"):
            abort(404)
        try:
            ok = "n_" + action
            if action == "demander":
                r = controle_notes.demander(c, s, f.get("id_cc", ""), f.get("cle", ""), f.get("type", ""), f.get("motif", ""), f.getlist("matricule"))
                ok = "n_demander_fermee" if r["fermee"] else "n_demander"
            elif action == "annuler":
                controle_notes.annuler_demande(c, s, f.get("id", ""))
            else:
                ok = "n_relancer" if controle_notes.demander_les_manquantes(c, s, f.get("annee", ""), f.get("prof", ""), f.get("en_cours", "") == "1")["creees"] else "n_rien"
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle as ex:
            ctx = _contexte_direction(c, s, "direction_etudes", "notes", f)
            ctx["n"]["erreur"] = str(ex)
            ctx["n"]["form"] = f
            return page_espace("direction_etudes", s, ctx, 400)
        return redirect(_retour_notes(f, ok=ok))

    # ------------------------------------------------------------------ Direction des études : passage en classe supérieure
    @app.post("/m/etudes_discipline/direction_etudes/passage/<action>")
    @connecte
    def etudes_passage_action(action):
        """Saisir la classe d'accueil (option de 8ème), exécuter le passage d'une classe, l'annuler (droits relus dans promotion.py)."""
        poster()
        s = espace_autorise("direction_etudes")
        c = conn()
        f = request.form
        if action not in ("choix", "choix_tous", "executer", "annuler", "annuler_tout"):
            abort(404)
        try:
            annee, classe = f.get("annee", ""), f.get("classe", "")
            if action == "choix":
                choix = {cle[5:]: v for cle, v in f.items() if cle.startswith("dest_") and cle != "dest_tous"}
                r = promotion.enregistrer_choix(c, s, annee, classe, choix)
                ok = "pa_choix" if r["enregistres"] or r["retires"] else "pa_rien"
            elif action == "choix_tous":
                promotion.appliquer_a_tous(c, s, annee, classe, f.get("dest_tous", ""))
                ok = "pa_choix"
            elif action == "executer":
                promotion.executer(c, s, annee, classe)
                ok = "pa_execute"
            else:
                promotion.annuler(c, s, annee, classe, f.get("motif", ""), f.getlist("matricule") if action == "annuler" else None)
                ok = "pa_annule"
        except PermissionError:
            abort(403)
        except promotion.ErreurPromotion as ex:
            ctx = _contexte_direction(c, s, "direction_etudes", "passage", f)
            ctx["pa"]["erreur"] = str(ex)
            return page_espace("direction_etudes", s, ctx, 400)
        retour = {k: f.get(k) for k in ("annee", "classe") if f.get(k)}
        return redirect(url_for("etudes_sous_menu", sous="direction_etudes", f="passage", ok=ok, **retour))

    @app.get("/m/etudes_discipline/direction_etudes/passage/impression")
    @connecte
    def etudes_passage_impression():
        """Page imprimable de la liste de passage d'une classe (droit Lecture, inscrite au journal)."""
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            r = promotion.impression(conn(), s, a.get("annee", ""), a.get("classe", ""))
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        return render_template("etudes_passage_impression.html", cfg=config, r=r, aujourdhui=date.today().strftime("%d/%m/%Y"),
                               par=s.nom_complet or s.login)

    @app.get("/m/etudes_discipline/direction_etudes/passage/export.csv")
    @connecte
    def etudes_passage_csv():
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            contenu = promotion.exporter_csv(conn(), s, a.get("annee", ""), a.get("classe", ""))
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        return Response(contenu, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="passage_classe_superieure.csv"'})

    # ------------------------------------------------------------------ Direction des études : statistiques et rapports scolaires (lecture seule)
    @app.get("/m/etudes_discipline/direction_etudes/statistiques/impression")
    @connecte
    def etudes_stats_impression():
        """Page imprimable des statistiques : ne contient que ce que le compte est autorisé à voir (droit Lecture, classes de ses sections)."""
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            r = statistiques_scolaires.impression(conn(), s, a.get("vue", ""), a.get("annee", ""), a.get("cle", ""), a.get("classe", "") or None,
                                                  a.get("niveau", "classes"))
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        titres = {"moyennes": "Moyennes par classe, cours et élève", "classement": "Classement des élèves", "reussite": "Taux de réussite et d'échec",
                  "comparaison": "Comparaison des résultats entre les périodes", "rapports": "Rapport sur la performance des classes et des enseignants"}
        return render_template("etudes_stats_impression.html", cfg=config, r=r, titre=titres[r["vue"]], aujourdhui=date.today().strftime("%d/%m/%Y"),
                               par=s.nom_complet or s.login)

    # ------------------------------------------------------------------ Direction des études : gestion des bulletins (lecture seule)
    @app.get("/m/etudes_discipline/direction_etudes/bulletins/bulletin.pdf")
    @connecte
    def etudes_bulletins_pdf():
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            octets, nom = gestion_bulletins.document_pdf(conn(), s, a.get("annee", ""), a.get("classe", ""), a.get("cle", ""), a.get("eleve", "") or None)
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        return Response(octets, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @app.get("/m/etudes_discipline/direction_etudes/bulletins/anomalies.csv")
    @connecte
    def etudes_bulletins_csv():
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            contenu = gestion_bulletins.exporter_anomalies_csv(conn(), s, a.get("annee", ""), a.get("classe", "") or None, a.get("cle", ""),
                                                               a.get("gravite", ""), a.get("code", ""), a.get("en_cours", "") == "1")
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        return Response(contenu, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="bulletins_anomalies.csv"'})

    @app.get("/m/etudes_discipline/direction_etudes/notes/verification.csv")
    @connecte
    def etudes_notes_verification_csv():
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            contenu = controle_notes.exporter_verification_csv(conn(), s, a.get("annee", ""), a.get("classe", "") or None, a.get("cours", "") or None,
                                                               a.get("eleve", ""), a.get("cle", ""))
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        return Response(contenu, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="verification_notes.csv"'})

    @app.get("/m/etudes_discipline/direction_etudes/notes/manquantes.csv")
    @connecte
    def etudes_notes_csv():
        s = espace_autorise("direction_etudes")
        a = request.args
        try:
            contenu = controle_notes.exporter_manquantes_csv(conn(), s, a.get("annee", ""), a.get("prof", ""), a.get("en_cours", "") == "1")
        except PermissionError:
            abort(403)
        except controle_notes.ErreurControle:
            abort(404)
        return Response(contenu, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="notes_manquantes.csv"'})


    # ------------------------------------------------------------------ Direction de discipline : gestion des présences
    @app.post("/m/etudes_discipline/direction_discipline/presences/<action>")
    @connecte
    def etudes_presences_action(action):
        """Confirmer ou corriger la présence d'un élève, confirmer une classe, annuler une décision (droits relus dans gestion_presences.py)."""
        poster()
        s = espace_autorise("direction_discipline")
        c = conn()
        f = request.form
        if action not in ("confirmer", "corriger", "confirmer_classe", "annuler"):
            abort(404)
        try:
            if action == "confirmer":
                gestion_presences.confirmer(c, s, f.get("annee", ""), f.get("matricule", ""), f.get("jour", ""))
                ok = "pd_confirmee"
            elif action == "corriger":
                gestion_presences.corriger(c, s, f.get("annee", ""), f.get("matricule", ""), f.get("jour", ""), f.get("statut", ""), f.get("motif", ""))
                ok = "pd_corrigee"
            elif action == "confirmer_classe":
                ok = "pd_classe" if gestion_presences.confirmer_classe(c, s, f.get("annee", ""), f.get("classe", ""), f.get("jour", ""))["faits"] else "pd_rien"
            else:
                gestion_presences.annuler(c, s, f.get("id", ""), f.get("motif_annulation", ""))
                ok = "pd_annulee"
        except PermissionError:
            abort(403)
        except gestion_presences.ErreurPresences as ex:
            ctx = _contexte_direction(c, s, "direction_discipline", "presences", f)
            ctx["pd"]["erreur"] = str(ex)
            ctx["pd"]["form"] = f
            return page_espace("direction_discipline", s, ctx, 400)
        retour = {k: f.get(k) for k in ("vue", "annee", "jour", "classe", "du", "au", "q", "eleve") if f.get(k)}
        return redirect(url_for("etudes_sous_menu", sous="direction_discipline", f="presences", ok=ok, **retour))

    # ------------------------------------------------------------------ Direction de discipline : suivi de la conduite
    @app.post("/m/etudes_discipline/direction_discipline/conduite/<action>")
    @connecte
    def etudes_conduite_action(action):
        """Enregistrer une observation, un comportement, un incident ou une mention ; annuler une entrée (droits relus dans suivi_conduite.py)."""
        poster()
        s = espace_autorise("direction_discipline")
        c = conn()
        f = request.form
        if action not in ("ajouter", "annuler"):
            abort(404)
        try:
            if action == "ajouter":
                suivi_conduite.enregistrer(c, s, f.get("annee", ""), f.get("matricule", ""), f.get("type_entree", ""), f.get("code", ""),
                                           f.get("date_fait", ""), f.get("description", ""), f.get("lieu", ""), f.get("mesure", ""), f.get("nature_obs", ""))
                ok = "cd_ajoutee"
            else:
                suivi_conduite.annuler(c, s, f.get("id", ""), f.get("motif_annulation", ""))
                ok = "cd_annulee"
        except PermissionError:
            abort(403)
        except suivi_conduite.ErreurConduite as ex:
            ctx = _contexte_direction(c, s, "direction_discipline", "conduite", f)
            ctx["cd"]["erreur"] = str(ex)
            ctx["cd"]["form"] = f
            return page_espace("direction_discipline", s, ctx, 400)
        retour = {k: f.get(k) for k in ("vue", "annee", "classe", "periode", "genre", "nature", "du", "au", "annulees", "q", "eleve") if f.get(k)}
        return redirect(url_for("etudes_sous_menu", sous="direction_discipline", f="conduite", ok=ok, **retour))

    # ------------------------------------------------------------------ Direction de discipline : convocation du parent
    @app.post("/m/etudes_discipline/direction_discipline/convocation/<action>")
    @connecte
    def etudes_convocation_action(action):
        """Enregistrer (et envoyer) une convocation, envoyer un brouillon, annuler (droits relus dans convocations.py)."""
        poster()
        s = espace_autorise("direction_discipline")
        c = conn()
        f = request.form
        if action not in ("enregistrer", "envoyer", "annuler"):
            abort(404)
        retour = {"vue": "liste"}
        try:
            if action == "enregistrer":
                r = convocations.enregistrer(c, s, f.get("matricule", ""), f.get("motif", ""), f.get("date_rdv", ""), f.get("heure_rdv", ""),
                                             f.get("lieu", ""), f.get("instructions", ""), envoyer=f.get("envoyer") == "1")
                if f.get("envoyer") == "1" and not r["envoyee"]:
                    ctx = _contexte_direction(c, s, "direction_discipline", "convocation", {"vue": "nouvelle", "eleve": f.get("matricule", "")})
                    ctx["cv"]["erreur"] = r["raison"]
                    ctx["cv"]["form"] = f
                    ctx["ok"] = MESSAGES_OK["cv_brouillon"]
                    return page_espace("direction_discipline", s, ctx)
                ok = "cv_envoyee" if r["envoyee"] else "cv_brouillon"
                retour["id"] = r["id"]
            elif action == "envoyer":
                convocations.envoyer_convocation(c, s, f.get("id", ""))
                ok, retour["id"] = "cv_envoyee", f.get("id", "")
            else:
                convocations.annuler(c, s, f.get("id", ""), f.get("motif_annulation", ""))
                ok, retour["id"] = "cv_annulee", f.get("id", "")
        except PermissionError:
            abort(403)
        except convocations.ErreurConvocation as ex:
            if action == "enregistrer":
                ctx = _contexte_direction(c, s, "direction_discipline", "convocation", {"vue": "nouvelle", "eleve": f.get("matricule", "")})
            else:
                ctx = _contexte_direction(c, s, "direction_discipline", "convocation", {"id": f.get("id", "")})
            ctx["cv"]["erreur"] = str(ex)
            ctx["cv"]["form"] = f
            return page_espace("direction_discipline", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="direction_discipline", f="convocation", ok=ok, **retour))

    @app.get("/m/etudes_discipline/direction_discipline/convocation/<int:id_conv>/impression")
    @connecte
    def etudes_convocation_impression(id_conv):
        """Lettre de convocation imprimable (même modèle que dans l'application du parent) : droit Lecture."""
        s = espace_autorise("direction_discipline")
        try:
            v = convocations.detail(conn(), s, id_conv)
        except PermissionError:
            abort(403)
        except convocations.ErreurConvocation:
            abort(404)
        return render_template("etudes_convocation_impression.html", cfg=config, v=v, aujourdhui=date.today().strftime("%d/%m/%Y"))

    @app.get("/m/etudes_discipline/<sous>")
    @connecte
    def etudes_sous_menu(sous):
        s = espace_autorise(sous)
        c = conn()
        if sous == "prefecture":
            ctx = _contexte_prefecture(c, s)
        elif sous in config.FONCTIONNALITES_DIRECTIONS:
            ctx = _contexte_direction(c, s, sous)
        elif sous == "dossier_eleve":
            ctx = _contexte_secretariat(c, s)
        else:
            ctx = {}
        return page_espace(sous, s, ctx)

    @app.post("/m/etudes_discipline/<sous>/proclamation/<action>")
    @connecte
    def etudes_proclamation_action(sous, action):
        """Étapes de la proclamation : Directrice des études (autoriser, criteres, valider, valider_ordre, retirer, soumettre) et Préfet
        (decision, confirmer). Tous les droits sont relus dans proclamation.py."""
        poster()
        actions = {"direction_etudes": ("autoriser", "criteres", "valider", "valider_ordre", "retirer", "soumettre"),
                   "prefecture": ("decision", "confirmer")}
        if sous not in actions or action not in actions[sous]:
            abort(404)
        s = espace_autorise(sous)
        c = conn()
        f = request.form
        annee, classe, cle = f.get("annee", ""), f.get("classe", ""), f.get("cle", "")
        try:
            if action == "autoriser":
                proclamation.autoriser(c, s, annee, classe, cle)
                ok = "p_autorise"
            elif action == "criteres":
                crit = []
                for cle_form in f:
                    if cle_form.startswith("frais_") and f.get(cle_form, "") != "":
                        v = f.get(cle_form)
                        crit.append({"codtf": cle_form[len("frais_"):], "tranche": None if v == "T" else v})
                proclamation.definir_criteres(c, s, annee, classe, cle, crit)
                ok = "p_criteres"
            elif action == "valider":
                proclamation.valider(c, s, annee, classe, cle, f.getlist("matricule"))
                ok = "p_valide"
            elif action == "valider_ordre":
                proclamation.valider(c, s, annee, classe, cle, None)
                ok = "p_valide"
            elif action == "retirer":
                proclamation.retirer_validation(c, s, annee, classe, cle, f.getlist("matricule"))
                ok = "p_retire"
            elif action == "soumettre":
                proclamation.soumettre(c, s, annee, classe, cle)
                ok = "p_soumise"
            elif action == "decision":
                proclamation.changer_decision(c, s, annee, classe, cle, f.get("matricule", ""), f.get("valide") == "1", f.get("motif", ""))
                ok = "p_decision"
            else:
                proclamation.confirmer(c, s, annee, classe, cle)
                ok = "p_confirmee"
        except PermissionError:
            abort(403)
        except (proclamation.ErreurProclamation, controle_notes.ErreurControle) as ex:
            args = {"annee": annee, "classe": classe, "cle": cle}
            ctx = (_contexte_direction(c, s, sous, "proclamation", args) if sous == "direction_etudes"
                   else _contexte_prefecture(c, s, "proclamation"))
            ctx["pr"] = _contexte_proclamation(c, s, sous, args, str(ex))
            return page_espace(sous, s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous=sous, f="proclamation", annee=annee, classe=classe, cle=cle, ok=ok))

    # ------------------------------------------------------------------ Secrétariat : bulletins scolaires validés par la Préfecture
    @app.get("/m/etudes_discipline/dossier_eleve/bulletins/bulletin.pdf")
    @connecte
    def etudes_secretariat_bulletins_pdf():
        """Impression (PDF) des bulletins validés d'une classe pour une période, ou d'un seul élève (?eleve=)."""
        s = espace_autorise("dossier_eleve")
        a = request.args
        try:
            octets, nom = bulletins_secretariat.document_pdf(conn(), s, a.get("annee", ""), a.get("classe", ""), a.get("cle", ""), a.get("eleve", "") or None)
        except PermissionError:
            abort(403)
        except bulletins_secretariat.ErreurBulletinsSecretariat:
            abort(404)
        return Response(octets, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @app.get("/m/etudes_discipline/dossier_eleve/bulletins/archive/<int:id_archive>.pdf")
    @connecte
    def etudes_secretariat_archive_pdf(id_archive):
        s = espace_autorise("dossier_eleve")
        try:
            octets, nom = bulletins_secretariat.archive_pdf(conn(), s, id_archive)
        except PermissionError:
            abort(403)
        except bulletins_secretariat.ErreurBulletinsSecretariat:
            abort(404)
        return Response(octets, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @app.post("/m/etudes_discipline/dossier_eleve/bulletins/archiver")
    @connecte
    def etudes_secretariat_archiver():
        """La secrétaire archive les bulletins validés d'une classe pour une période (droit « Modification » sur « Secrétariat »)."""
        poster()
        s = espace_autorise("dossier_eleve")
        c = conn()
        f = request.form
        retour = {"f": "bulletins", "annee": f.get("annee", "") or None, "classe": f.get("classe", "") or None, "cle": f.get("cle", "") or None,
                  "option": f.get("option", "") or None}
        try:
            bulletins_secretariat.archiver(c, s, f.get("annee", ""), f.get("classe", ""), f.get("cle", ""))
        except PermissionError:
            abort(403)
        except bulletins_secretariat.ErreurBulletinsSecretariat as ex:
            ctx = _contexte_secretariat(c, s, str(ex))
            return page_espace("dossier_eleve", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="dossier_eleve", ok="bulletins_archives", **retour))

    # ------------------------------------------------------------------ Secrétariat : listes et rapports administratifs
    def _parametres_liste_espace(sous):
        p = _parametres_listes(request.args)
        if sous != "dossier_eleve":
            p["genre"] = "eleves"
        return dict(p, espace=sous)

    @app.get("/m/etudes_discipline/<sous>/listes/liste.pdf")
    @connecte
    def etudes_liste_pdf(sous):
        """Impression (PDF) de la liste des élèves (ou des dossiers incomplets, Secrétariat) : droit « Lecture » sur le module de l'espace."""
        if sous not in listes_administratives.ESPACES:
            abort(404)
        s = espace_autorise(sous)
        try:
            octets, nom = listes_administratives.document_pdf(conn(), s, **_parametres_liste_espace(sous))
        except PermissionError:
            abort(403)
        except listes_administratives.ErreurListes:
            abort(404)
        return Response(octets, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @app.get("/m/etudes_discipline/<sous>/listes/liste.csv")
    @connecte
    def etudes_liste_csv(sous):
        if sous not in listes_administratives.ESPACES:
            abort(404)
        s = espace_autorise(sous)
        try:
            texte, nom = listes_administratives.exporter_csv(conn(), s, **_parametres_liste_espace(sous))
        except PermissionError:
            abort(403)
        except listes_administratives.ErreurListes:
            abort(404)
        return Response("\ufeff" + texte, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    # ------------------------------------------------------------------ Secrétariat : archives scolaires
    @app.get("/m/etudes_discipline/dossier_eleve/archives/<source>/<int:ident>")
    @connecte
    def etudes_secretariat_archive_ouvrir(source, ident):
        """Ouvre un document des archives : source = classe (classé par la secrétaire), bulletin (copie de bulletins) ou officiel (document signé)."""
        s = espace_autorise("dossier_eleve")
        c = conn()
        mime, nom = "application/pdf", "document.pdf"
        try:
            if source == "classe":
                octets, format_, nom = archives_scolaires.ouvrir(c, s, ident)
                mime = archives_scolaires.type_mime(format_)
            elif source == "bulletin":
                octets, nom = archives_scolaires.ouvrir_bulletins_classe(c, s, ident)
            elif source == "officiel":
                octets, nom = archives_scolaires.ouvrir_document_officiel(c, s, ident)
            else:
                abort(404)
        except PermissionError:
            abort(403)
        except archives_scolaires.ErreurArchives:
            abort(404)
        return Response(octets, mimetype=mime, headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(nom)}",
                                                        "X-Content-Type-Options": "nosniff"})

    @app.post("/m/etudes_discipline/dossier_eleve/archives/classer")
    @connecte
    def etudes_secretariat_archive_classer():
        """La secrétaire classe un fichier numérisé (droit « Modification » sur « Secrétariat »)."""
        poster()
        s = espace_autorise("dossier_eleve")
        c = conn()
        request.max_content_length = config.TAILLE_MAX_ARCHIVE + 200_000          # (le plafond général de 300 Ko est trop bas ici)
        saisie = {}
        try:
            f = request.form
            saisie = {k: f.get(k, "") for k in ("annee", "categorie", "titre", "matricule", "note")}
            fichier = request.files.get("fichier")
            octets = fichier.read(config.TAILLE_MAX_ARCHIVE + 1) if fichier is not None and fichier.filename else b""
            nom_fichier = fichier.filename if fichier is not None else ""
        except RequestEntityTooLarge:
            erreur = f"Le fichier est trop volumineux : {config.TAILLE_MAX_ARCHIVE // (1024 * 1024)} Mo au plus."
            return _page_classer_erreur(c, s, erreur, saisie, 413)
        try:
            if not octets:
                raise archives_scolaires.ErreurArchives("Choisissez le fichier à classer.")
            archives_scolaires.classer(c, s, saisie["annee"], saisie["categorie"], saisie["titre"], octets, nom_fichier, saisie["matricule"], saisie["note"])
        except PermissionError:
            abort(403)
        except archives_scolaires.ErreurArchives as ex:
            return _page_classer_erreur(c, s, str(ex), saisie, 400)
        retour = {"f": "archives", "ok": "archive_classee"}
        if saisie["matricule"].strip():
            retour["eleve"] = saisie["matricule"].strip()
        else:
            retour["annee"] = saisie["annee"].strip()
        return redirect(url_for("etudes_sous_menu", sous="dossier_eleve", **retour))

    def _page_classer_erreur(c, s, erreur, saisie, statut):
        """Réaffiche le formulaire de classement avec l'erreur et les valeurs saisies (sans relire le corps de la requête)."""
        ctx = {"secr": {"fonctions": config.FONCTIONNALITES_SECRETARIAT, "fonction": "archives", "classe": "", "q": "", "etats": secretariat.ETATS,
                        "classes": [], "liste": None, "peut_modifier": False}, "erreur": erreur}
        ctx = _contexte_archives(c, s, ctx, saisie, {"vue": "classer", "eleve": saisie.get("matricule", "").strip()})
        return page_espace("dossier_eleve", s, ctx, statut)

    @app.post("/m/etudes_discipline/dossier_eleve/archives/retirer")
    @connecte
    def etudes_secretariat_archive_retirer():
        """La secrétaire (avec le droit « Suppression ») retire un document du classement : motif obligatoire, le fichier est conservé."""
        poster()
        s = espace_autorise("dossier_eleve")
        c = conn()
        f = request.form
        try:
            archives_scolaires.retirer(c, s, f.get("id", ""), f.get("motif", ""))
        except PermissionError:
            abort(403)
        except archives_scolaires.ErreurArchives as ex:
            ctx = _contexte_secretariat(c, s, str(ex))
            return page_espace("dossier_eleve", s, ctx, 400)
        retour = {"f": "archives", "ok": "archive_retiree"}
        for k in ("eleve", "q", "annee", "genre"):
            if f.get(k):
                retour[k] = f.get(k)
        for k in ("anciens", "retires"):
            if f.get(k) == "1":
                retour[k] = "1"
        return redirect(url_for("etudes_sous_menu", sous="dossier_eleve", **retour))

    @app.post("/m/etudes_discipline/dossier_eleve/etat")
    @connecte
    def etudes_dossier_etat():
        """La secrétaire déclare un dossier complet ou incomplet (droit « Modification » sur « Secrétariat »)."""
        poster()
        s = espace_autorise("dossier_eleve")
        c = conn()
        f = request.form
        etat = f.get("etat", "")
        retour = {"classe": f.get("classe", "") or None, "q": f.get("q", "") or None, "etat": f.get("filtre", "") or None}
        try:
            if etat not in ("complet", "incomplet"):
                raise secretariat.ErreurSecretariat("État demandé invalide.")
            secretariat.definir_etat(c, s, f.get("matricule", ""), etat == "complet")
        except PermissionError:
            abort(403)
        except secretariat.ErreurSecretariat as ex:
            ctx = _contexte_secretariat(c, s, str(ex))
            return page_espace("dossier_eleve", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="dossier_eleve", ok="dossier_" + etat, **retour))

    # ------------------------------------------------------------------ Préfecture : documents scolaires officiels
    @app.get("/m/etudes_discipline/prefecture/documents/<int:id_doc>.pdf")
    @connecte
    def etudes_document_pdf(id_doc):
        s = espace_autorise("prefecture")
        try:
            octets, nom = documents_officiels.document_pdf(conn(), s, id_doc)
        except PermissionError:
            abort(403)
        except documents_officiels.ErreurDocument:
            abort(404)
        return Response(octets, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @app.post("/m/etudes_discipline/prefecture/documents/<action>")
    @connecte
    def etudes_document_action(action):
        """Étapes d'un document : preparer, modifier (Ajout) ; soumettre, signer, renvoyer, annuler (Modification). Droits relus dans documents_officiels.py."""
        poster()
        if action not in ("preparer", "modifier", "soumettre", "signer", "renvoyer", "annuler"):
            abort(404)
        s = espace_autorise("prefecture")
        c = conn()
        f = request.form
        id_doc = f.get("doc", "")
        ok = {"preparer": "doc_prepare", "modifier": "doc_modifie", "soumettre": "doc_soumis", "signer": "doc_signe", "renvoyer": "doc_renvoye",
              "annuler": "doc_annule"}[action]
        try:
            if action == "preparer":
                id_doc = documents_officiels.preparer(c, s, f.get("annee", ""), f.get("matricule", ""), f.get("type", ""), f.get("contenu", ""))
            elif action == "modifier":
                documents_officiels.modifier(c, s, id_doc, f.get("contenu", ""))
            elif action == "soumettre":
                documents_officiels.soumettre(c, s, id_doc, f.get("approbation", ""), f.get("signataire", ""))
            elif action == "signer":
                documents_officiels.signer(c, s, id_doc, f.get("signataire", ""))
            elif action == "renvoyer":
                documents_officiels.renvoyer(c, s, id_doc, f.get("motif", ""))
            else:
                documents_officiels.annuler(c, s, id_doc, f.get("motif", ""))
        except PermissionError:
            abort(403)
        except (documents_officiels.ErreurDocument, prefecture.ErreurPrefecture) as ex:
            ctx = _contexte_prefecture(c, s, "documents")
            ctx["docs"] = _contexte_documents(c, s, str(ex))
            return page_espace("prefecture", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="prefecture", f="documents", doc=id_doc, ok=ok))

    @app.post("/m/etudes_discipline/prefecture/decisions")
    @connecte
    def etudes_decision_ajouter():
        poster()
        s = espace_autorise("prefecture")
        c = conn()
        f = request.form
        try:
            prefecture.enregistrer_decision(c, s, f.get("date", ""), f.get("categorie", ""), f.get("objet", ""), f.get("detail", ""),
                                            f.get("annee", ""), f.get("matricule", ""))
        except PermissionError:
            abort(403)
        except prefecture.ErreurPrefecture as ex:
            ctx = _contexte_prefecture(c, s, "decisions")
            ctx.update(erreur=str(ex), form=f)
            return page_espace("prefecture", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="prefecture", f="decisions", ok="decision"))

    @app.post("/m/etudes_discipline/prefecture/renvois")
    @connecte
    def etudes_renvoi_enregistrer():
        poster()
        s = espace_autorise("prefecture")
        c = conn()
        f = request.form
        try:
            renvoi.renvoyer_eleve(c, s, f.get("matricule", ""), f.get("date", ""), f.get("motif", ""), f.get("annee", ""))
        except PermissionError:
            abort(403)
        except prefecture.ErreurPrefecture as ex:
            ctx = _contexte_prefecture(c, s, "renvois")
            ctx.update(erreur=str(ex), form=f)
            return page_espace("prefecture", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="prefecture", f="renvois", ok="renvoi"))

    @app.post("/m/etudes_discipline/prefecture/decisions/<int:numero>/annuler")
    @connecte
    def etudes_decision_annuler(numero):
        poster()
        s = espace_autorise("prefecture")
        c = conn()
        try:
            prefecture.annuler_decision(c, s, numero, request.form.get("motif", ""))
        except PermissionError:
            abort(403)
        except prefecture.ErreurPrefecture as ex:
            ctx = _contexte_prefecture(c, s, "decisions")
            ctx.update(erreur=str(ex))
            return page_espace("prefecture", s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous="prefecture", f="decisions", ok="annulee"))

    @app.post("/m/etudes_discipline/<sous>/rapport")
    @connecte
    def etudes_rapport_envoyer(sous):
        poster()
        s = espace_autorise(sous)
        if sous not in config.FONCTIONNALITES_DIRECTIONS:
            abort(404)
        c = conn()
        f = request.form
        try:
            prefecture.deposer_rapport(c, s, sous, f.get("titre", ""), f.get("contenu", ""), f.get("date", ""))
        except PermissionError:
            abort(403)
        except prefecture.ErreurPrefecture as ex:
            ctx = _contexte_direction(c, s, sous, "rapport")
            ctx.update(erreur=str(ex), form=f)
            return page_espace(sous, s, ctx, 400)
        return redirect(url_for("etudes_sous_menu", sous=sous, f="rapport", ok="rapport"))
