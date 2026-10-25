"""Génération des rapports d'audit (module « Traçabilité et audit », sans interface graphique : testable seul).

Un rapport d'audit est un DOCUMENT consultable à l'écran, imprimable (PDF, A4 paysage, avec cases de signature) et
exportable (CSV pour un tableur). Il porte la période, les filtres, la date d'édition, le compte qui l'a produit et l'état
du journal (nombre de lignes, chaîne d'empreintes, dernière empreinte). Quatre rapports :

- GENERAL    : toutes les opérations enregistrées (par catégorie, module et utilisateur), les opérations sensibles
               (échecs de connexion, annulations, suppressions, droits...) et le détail de chaque opération ;
- FINANCIER  : les opérations financières : synthèse par devise, rapprochement journalier (opérations enregistrées,
               rapport journalier, encaissé, versé), reçus, annulations, corrections, rapports imprimés, anomalies ;
- ANOMALIES  : seulement les anomalies financières, de la plus grave à la moins grave, avec une piste de vérification ;
- COMPLET    : tout ce qui précède.

Un rapport ne modifie rien. Sa production est inscrite au journal (consultation : « Génération d'un rapport d'audit » ;
impression ou exportation : « Exportation d'un rapport d'audit »). Les droits sont ceux du module : l'Administrateur, ou
un compte à qui il a accordé la Lecture sur « Traçabilité et audit ».
"""
import csv
import re
from datetime import datetime

import argent
import audit
import audit_financier
import audit_recherche
import config
from audit import ErreurAudit, _nom_fichier, _periode_txt, _protege_csv, etat_journal, exiger
from database import journaliser

TYPES_RAPPORT = {
    "GENERAL": "Rapport général des opérations",
    "FINANCIER": "Rapport des opérations financières",
    "ANOMALIES": "Rapport des anomalies financières",
    "COMPLET": "Rapport d'audit complet",
}
DESCRIPTIONS = {
    "GENERAL": "Toutes les opérations enregistrées : par catégorie, module et utilisateur, opérations sensibles, détail.",
    "FINANCIER": "Paiements, reçus, encaissé et remis, annulations, corrections, rapports journaliers et anomalies.",
    "ANOMALIES": "Uniquement les anomalies financières, de la plus grave à la moins grave, avec une piste de vérification.",
    "COMPLET": "Le rapport financier, le rapport des anomalies et le rapport général en un seul document.",
}

# Actions que l'auditeur veut voir en un coup d'œil, même parmi des milliers de lignes
ACTIONS_SENSIBLES = frozenset({
    "CONNEXION_ECHEC", "CONNEXION_REFUSEE_BLOCAGE", "PAIEMENT_ANNULE", "ENCAISSEMENT_MODIFIE", "ENCAISSEMENT_SUPPRIME",
    "REF_SUPPRESSION", "REF_SUPPRESSION_AVEC_LIEES", "DROITS_MODIFIES", "DROITS_ROLE_MODIFIES", "COMPTE_DESACTIVE",
    "MDP_REINITIALISE", "CODE_RECUP_GENERE", "CODE_RECUP_DETRUIT", "RESTAURATION_EFFECTUEE", "APPLICATION_REINITIALISEE",
    "REINITIALISATION_REFUSEE", "DONNEES_ESSAI_AJOUTEES", "DONNEES_ESSAI_SUPPRIMEES", "DONNEES_ESSAI_REFUSEES",
    "MISE_A_JOUR_PROGRAMME", "MISE_A_JOUR_REFUSEE", "MISE_A_JOUR_ECHEC", "RETOUR_ANCIENNE_VERSION",
})

# Piste de vérification proposée pour chaque type d'anomalie (une anomalie n'est pas une preuve de fraude)
CONSEILS = {
    "RECU_SANS_TRACE": "Comparer avec le carnet de reçus ; chercher qui a accès directement à la base de données.",
    "RECU_TRACE_DOUBLE": "Vérifier si le reçu a été saisi deux fois ; consulter ses traces dans l'onglet Recherche.",
    "RECU_ENREGISTRE_PAR_AUTRE": "Demander au percepteur du reçu et au compte indiqué au journal ce qui s'est passé.",
    "RECU_DIFFERENT_DU_JOURNAL": "Comparer le reçu papier remis à l'élève avec la trace ; la table a pu être modifiée.",
    "RECU_DATE_INCOHERENTE": "Vérifier l'horloge de l'ordinateur et la date portée sur le reçu remis à l'élève.",
    "RECU_DATE_FUTURE": "Vérifier l'horloge de l'ordinateur du percepteur.",
    "RECU_ABSENT_DE_LA_TABLE": "Retrouver le reçu papier ; la base de données a pu être modifiée hors de l'application.",
    "RECU_ANNULE_SANS_TRACE": "Demander à l'Administrateur qui a annulé ce reçu et pourquoi.",
    "RECU_ANNULATION_INCOHERENTE": "Comparer l'auteur de l'annulation (reçu) avec celui du journal.",
    "RECU_ANNULATION_INCOMPLETE": "Retrouver le motif de l'annulation auprès de l'Administrateur.",
    "RECU_DUPLICATAS_MULTIPLES": "Demander pourquoi tant de duplicata ont été imprimés (reçu perdu, ou remise multiple ?).",
    "TROP_PERCU": "Rembourser ou réaffecter le trop-perçu ; vérifier les reçus de cet élève pour ce frais.",
    "NUMEROS_MANQUANTS": "Retrouver les carnets de reçus ; un numéro manquant peut cacher un reçu supprimé.",
    "CAISSE_JOURNAL_DIFFERENT": "Examiner les reçus de la journée un à un (onglet Recherche, par percepteur et par date).",
    "RECUS_SANS_ENCAISSEMENT": "Demander au percepteur de déclarer son encaissement ; contrôler la caisse.",
    "ENCAISSEMENT_SANS_RECU": "Vérifier la date et le percepteur de l'encaissement ; chercher les reçus correspondants.",
    "ENCAISSE_DIFFERENT_DES_RECUS": "Faire recompter la caisse du jour ; vérifier les annulations survenues après l'encaissement.",
    "ENCAISSEMENTS_MULTIPLES": "Vérifier qu'un même encaissement n'a pas été saisi deux fois.",
    "ENCAISSEMENT_SANS_TRACE": "Vérifier qui peut modifier directement la base ; contrôler le registre de caisse.",
    "ENCAISSEMENT_SAISI_PAR_AUTRE": "Comparer l'auteur de la saisie (table) avec celui du journal.",
    "ENCAISSEMENT_DIFFERENT_DU_JOURNAL": "Comparer avec le bordereau de versement ; la table a pu être modifiée hors de l'application.",
    "ENCAISSEMENT_ECART_INCOHERENT": "Recalculer l'écart (encaissé - versé) et comparer avec le bordereau de versement.",
    "REMISE_MANQUANT": "Faire expliquer le manquant par le percepteur et exiger le versement ou une justification écrite.",
    "REMISE_EXCEDENT": "Vérifier si un reçu manque ou si un versement a été fait en trop.",
    "ANNULATION_APRES_ENCAISSEMENT": "Faire corriger l'encaissement du jour ou justifier l'annulation par écrit.",
    "ANNULATIONS_NOMBREUSES": "Examiner les motifs des annulations de ce percepteur.",
    "ENCAISSEMENT_CORRIGE": "Comparer l'encaissement corrigé avec le bordereau de versement.",
    "ENCAISSEMENT_SUPPRIME": "Demander la raison de la suppression ; l'encaissement ne figure plus dans les rapports.",
    "RAPPORT_NON_CONFORME": "Réimprimer le rapport de la journée et le comparer avec l'exemplaire imprimé.",
    "RAPPORT_PERIME_ANNULATION": "Réimprimer le rapport de la journée : l'exemplaire archivé n'est plus à jour.",
    "RAPPORT_PERIME_AJOUT": "Réimprimer le rapport une fois la journée terminée.",
    "JOURNAL_ALTERE": "Faire une copie du fichier de base de données avant toute restauration ; prévenir la Direction.",
}
CONSEIL_PAR_DEFAUT = "Consulter les traces concernées dans l'onglet Recherche et filtrage des traces."


def _f(centimes) -> str:
    return "" if centimes is None else argent.formater(centimes)


def _filtres_txt(du, au, login, n_perc_nom, devise) -> list:
    return [x for x in (f"Période : {_periode_txt(du, au)}", f"Utilisateur : {login}" if login else "",
                        f"Percepteur : {n_perc_nom}" if n_perc_nom else "", f"Devise : {devise}" if devise else "") if x]


def _section(titre, colonnes, lignes, couleurs=None, notes=(), vide="Rien à signaler.") -> dict:
    return {"titre": titre, "notes": list(notes), "colonnes": colonnes, "lignes": lignes,
            "couleurs": couleurs or [None] * len(lignes), "vide": vide}


_COULEUR_STATUT = {"Anomalie": "rouge", "Écart": "rouge", "À vérifier": "orange", "Conforme, modifié depuis": "orange",
                   "Non comparable": "gris"}
_COULEUR_GRAVITE = {"ÉLEVÉE": "rouge", "MOYENNE": "orange", "FAIBLE": "gris"}


# ================================================================== sections financières
def _sections_financieres(c) -> list:
    sections = []
    sections.append(_section(
        "Synthèse financière par devise",
        [("Devise", 40, "g"), ("Reçus valides", 52, "d"), ("Total des reçus", 72, "d"), ("Reçus annulés", 52, "d"),
         ("Total annulé", 66, "d"), ("Encaissé", 72, "d"), ("Versé", 72, "d"), ("Écart de remise", 66, "d"),
         ("Encaissé - reçus", 66, "d"), ("Reçus sans encaissement", 80, "d")],
        [[s["devise"], str(s["recus_nb"]), _f(s["recus_total"]), str(s["annules_nb"]), _f(s["annules_total"]),
          _f(s["encaisse"]), _f(s["verse"]), _f(s["ecart_remise"]), _f(s["diff_recus"]), _f(s["sans_encaissement"])]
         for s in c["synthese"]],
        couleurs=["orange" if (s["ecart_remise"] or s["diff_recus"]) else None for s in c["synthese"]],
        notes=["Écart de remise = encaissé - versé (positif : manquant, négatif : excédent). "
               "Encaissé - reçus : différence entre le montant déclaré encaissé et le total des reçus valides."],
        vide="Aucune opération financière dans le périmètre choisi."))
    sections.append(_section(
        "Rapprochement journalier : opérations enregistrées, rapport journalier, encaissé et versé",
        [("Date", 48, "g"), ("Percepteur", 96, "g"), ("Devise", 34, "g"), ("Journal nb", 46, "d"),
         ("Journal total", 58, "d"), ("Annulés", 52, "d"), ("Rapport nb", 46, "d"),
         ("Rapport total", 58, "d"), ("Encaissé", 56, "d"), ("Versé", 56, "d"), ("Écart remise", 56, "d"),
         ("Statut", 50, "g"), ("Remarques", 190, "g")],
        [[g["date_txt"], g["percepteur"], g["devise"], str(g["journal_nb"]), _f(g["journal_total"]),
          _f(g["annules_total"]), str(g["recus_nb"]), _f(g["recus_total"]), _f(g["encaisse"]), _f(g["verse"]),
          _f(g["ecart_remise"]), g["statut"], g["remarques"]] for g in c["rapprochement"]],
        couleurs=[_COULEUR_STATUT.get(g["statut"]) for g in c["rapprochement"]],
        notes=["Journal = reçus enregistrés selon le journal ; Rapport = reçus valides du rapport journalier (journal - annulés "
               "doit être égal au rapport)."],
        vide="Aucune journée dans le périmètre choisi."))
    sections.append(_section(
        "Paiements enregistrés et reçus",
        [("N° reçu", 36, "g"), ("Date", 66, "g"), ("Élève", 120, "g"), ("Frais", 92, "g"), ("Montant", 50, "d"),
         ("Devise", 28, "g"), ("Percepteur", 84, "g"), ("Enregistré par", 84, "g"), ("Statut", 36, "g"),
         ("Vérification", 52, "g"), ("Remarques", 160, "g")],
        [[p["n_recu"], p["date_txt"], f"{p['matricule']} - {p['eleve']}", p["frais"], p["montant_txt"], p["devise"],
          p["percepteur"], p["enregistre_par"], p["statut"], p["verification"], p["remarques"]] for p in c["paiements"]],
        couleurs=[_COULEUR_STATUT.get(p["verification"]) or ("gris" if p["statut"] == "Annulé" else None)
                  for p in c["paiements"]],
        vide="Aucun paiement dans le périmètre choisi."))
    sections.append(_section(
        "Annulations de reçus",
        [("N° reçu", 36, "g"), ("Annulé le", 66, "g"), ("Délai", 40, "g"), ("Élève", 120, "g"), ("Montant", 50, "d"),
         ("Devise", 28, "g"), ("Motif", 150, "g"), ("Enregistré par", 90, "g"), ("Annulé par", 90, "g")],
        [[a["n_recu"], a["date_txt"], a["delai"], f"{a['matricule']} - {a['eleve']}", a["montant_txt"], a["devise"],
          a["motif"], a["enregistre_par"], a["annule_par"]] for a in c["annulations"]],
        couleurs=["orange" if a["remarques"] else None for a in c["annulations"]],
        vide="Aucune annulation dans le périmètre choisi."))
    sections.append(_section(
        "Corrections : encaissements, tarifs et frais modifiés ou supprimés",
        [("Date", 66, "g"), ("Nature", 120, "g"), ("Référence", 80, "g"), ("Fait par", 70, "g"), ("Avant", 190, "g"),
         ("Après", 190, "g")],
        [[x["date_txt"], x["nature"], x["reference"], x["par_login"] or "—", x["avant"], x["apres"]]
         for x in c["corrections"]],
        vide="Aucune correction dans le périmètre choisi."))
    sections.append(_section(
        "Rapports journaliers imprimés comparés aux reçus existant au moment de l'impression",
        [("Imprimé le", 66, "g"), ("Rapport", 70, "g"), ("Journée", 50, "g"), ("Portée", 100, "g"), ("Par", 60, "g"),
         ("Reçus imprimés", 44, "d"), ("Total imprimé", 100, "d"), ("Reçus aujourd'hui", 44, "d"),
         ("Total aujourd'hui", 100, "d"), ("Statut", 70, "g")],
        [[r["date_txt"], r["type"], r["jour_txt"], r["portee"], r["par_login"] or "—", str(r["imprime_nb"]),
          r["imprime_total"], "" if r["actuel_nb"] is None else str(r["actuel_nb"]), r["actuel_total"], r["statut"]]
         for r in c["rapports"]],
        couleurs=[_COULEUR_STATUT.get(r["statut"]) for r in c["rapports"]],
        vide="Aucun rapport journalier imprimé dans le périmètre choisi."))
    return sections


def _section_anomalies(c, avec_conseil=False) -> dict:
    colonnes = [("Gravité", 46, "g"), ("Catégorie", 96, "g"), ("Référence", 70, "g"), ("Date", 52, "g"),
                ("Constat", 330, "g")]
    lignes = [[a["gravite"], a["categorie"], a["reference"] or "—", a["date_txt"] or "—", a["message"]]
              for a in c["anomalies"]]
    if avec_conseil:
        colonnes.append(("Piste de vérification", 220, "g"))
        for ligne, a in zip(lignes, c["anomalies"]):
            ligne.append(CONSEILS.get(a["code"], CONSEIL_PAR_DEFAUT))
    return _section("Anomalies financières", colonnes, lignes,
                    couleurs=[_COULEUR_GRAVITE[a["gravite"]] for a in c["anomalies"]],
                    notes=["Une anomalie n'est pas une preuve de fraude : elle indique où regarder. ÉLEVÉE : les données ne "
                           "concordent pas ; MOYENNE : à vérifier ; FAIBLE : à connaître."],
                    vide="Aucune anomalie : tout concorde dans le périmètre choisi.")


def _section_repartition(c) -> dict:
    lignes = []
    for cat in audit_financier.CATEGORIES_ANOMALIES:
        nb = [sum(1 for a in c["anomalies"] if a["categorie"] == cat and a["gravite"] == g)
              for g in audit_financier.GRAVITES]
        if any(nb):
            lignes.append([cat, *map(str, nb), str(sum(nb))])
    return _section("Répartition des anomalies par catégorie",
                    [("Catégorie", 200, "g"), ("Élevée", 50, "d"), ("Moyenne", 50, "d"), ("Faible", 50, "d"),
                     ("Total", 50, "d")], lignes, vide="Aucune anomalie.")


def _resume_financier(c) -> list:
    nb = c["nb_anomalies"]
    lignes = []
    for s in c["synthese"]:
        d = s["devise"]
        lignes += [(f"Reçus valides ({d})", f"{s['recus_nb']} reçu(s) : {_f(s['recus_total'])} {d}"),
                   (f"Reçus annulés ({d})", f"{s['annules_nb']} reçu(s) : {_f(s['annules_total'])} {d}"),
                   (f"Encaissé / versé ({d})", f"{_f(s['encaisse'])} / {_f(s['verse'])} {d}"),
                   (f"Écart de remise ({d})", f"{_f(s['ecart_remise'])} {d}"
                    + (" (manquant)" if s["ecart_remise"] > 0 else " (excédent)" if s["ecart_remise"] < 0 else ""))]
        if s["sans_encaissement"]:
            lignes.append((f"Reçus sans encaissement enregistré ({d})", f"{_f(s['sans_encaissement'])} {d}"))
    lignes.append(("Anomalies financières", f"{nb['ÉLEVÉE']} élevée(s), {nb['MOYENNE']} moyenne(s), {nb['FAIBLE']} faible(s)"))
    lignes.append(("Conclusion", "Aucune anomalie : tout concorde." if not sum(nb.values())
                   else f"{sum(nb.values())} anomalie(s) à examiner (voir la section « Anomalies financières »)."))
    return lignes


# ================================================================== sections générales
def _sections_generales(conn, session, du, au, login, avec_detail) -> tuple:
    """(sections, résumé) du rapport général : toutes les opérations du journal."""
    r = audit.journal(conn, session, du, au, login=login, limite=None)
    lignes = r["lignes"]
    par_categorie, par_module, par_user = {}, {}, {}
    for l in lignes:
        module = audit_recherche.module_de(l["action"])
        par_categorie[l["categorie_txt"]] = par_categorie.get(l["categorie_txt"], 0) + 1
        par_module[audit_recherche.libelle_module(module)] = par_module.get(audit_recherche.libelle_module(module), 0) + 1
        u = par_user.setdefault(l["login"] or "—", {"nom": l["nom"], "poste": l["poste"], "nb": 0, "premiere": l["quand"],
                                                    "derniere": l["quand"], "connexions": 0, "echecs": 0, "financieres": 0})
        u["nb"] += 1
        u["premiere"], u["derniere"] = min(u["premiere"], l["quand"]), max(u["derniere"], l["quand"])
        u["connexions"] += l["action"] == "CONNEXION_OK"
        u["echecs"] += l["action"] in ("CONNEXION_ECHEC", "CONNEXION_REFUSEE_BLOCAGE")
        u["financieres"] += l["financier"]
    sensibles = [l for l in lignes if l["action"] in ACTIONS_SENSIBLES]

    def tri(d):
        return sorted(d.items(), key=lambda x: -x[1])
    sections = [
        _section("Opérations par catégorie", [("Catégorie", 220, "g"), ("Nombre", 60, "d")],
                 [[k, str(v)] for k, v in tri(par_categorie)], vide="Aucune opération dans la période."),
        _section("Opérations par module", [("Module concerné", 220, "g"), ("Nombre", 60, "d")],
                 [[k, str(v)] for k, v in tri(par_module)], vide="Aucune opération dans la période."),
        _section("Activité par utilisateur",
                 [("Identifiant", 80, "g"), ("Nom complet", 130, "g"), ("Poste", 90, "g"), ("Opérations", 50, "d"),
                  ("Connexions", 50, "d"), ("Échecs de connexion", 60, "d"), ("Opérations financières", 70, "d"),
                  ("Première", 78, "g"), ("Dernière", 78, "g")],
                 [[k, u["nom"], u["poste"], str(u["nb"]), str(u["connexions"]), str(u["echecs"]), str(u["financieres"]),
                   u["premiere"].strftime("%d/%m/%Y %H:%M"), u["derniere"].strftime("%d/%m/%Y %H:%M")]
                  for k, u in sorted(par_user.items(), key=lambda x: -x[1]["nb"])],
                 couleurs=["orange" if u["echecs"] >= 3 else None for _k, u in sorted(par_user.items(), key=lambda x: -x[1]["nb"])],
                 vide="Aucune activité dans la période."),
        _section("Opérations sensibles : échecs de connexion, annulations, suppressions, droits, sauvegardes",
                 [("Date et heure", 90, "g"), ("Utilisateur", 110, "g"), ("Module", 110, "g"), ("Action", 160, "g"),
                  ("Détail", 270, "g")],
                 [[l["date_txt"], l["login"] or "—", audit_recherche.libelle_module(audit_recherche.module_de(l["action"])),
                   l["libelle"], l["detail"]] for l in sensibles],
                 couleurs=["rouge" if l["action"] in ("CONNEXION_ECHEC", "CONNEXION_REFUSEE_BLOCAGE") else "orange"
                           for l in sensibles],
                 vide="Aucune opération sensible dans la période."),
    ]
    if avec_detail:
        sections.append(_section(
            f"Détail de toutes les opérations ({len(lignes)})",
            [("Date et heure", 90, "g"), ("Utilisateur", 90, "g"), ("Module", 100, "g"), ("Action", 160, "g"),
             ("Détail", 300, "g")],
            [[l["date_txt"], l["login"] or "—", audit_recherche.libelle_module(audit_recherche.module_de(l["action"])),
              l["libelle"], l["detail"]] for l in lignes],
            vide="Aucune opération dans la période."))
    resume = [("Opérations enregistrées", str(len(lignes))), ("Utilisateurs concernés", str(len(par_user))),
              ("Échecs de connexion", str(sum(u["echecs"] for u in par_user.values()))),
              ("Opérations financières", str(sum(u["financieres"] for u in par_user.values()))),
              ("Opérations sensibles", str(len(sensibles)))]
    return sections, resume


# ================================================================== le rapport
def generer_rapport(conn, session, type_, du=None, au=None, login=None, n_perc=None, devise=None, avec_detail=True,
                    journaliser_generation=True) -> dict:
    """Produit un rapport d'audit (voir le haut du fichier). Retourne le document :
    {"type", "titre", "periode_txt", "filtres", "genere_le", "genere_par", "journal", "resume": [(libellé, valeur)],
     "sections": [...], "nb_anomalies": {gravité: n}}. Les sections sont affichables telles quelles (écran, PDF, CSV)."""
    exiger(conn, session)
    if type_ not in TYPES_RAPPORT:
        raise ErreurAudit("Type de rapport inconnu.")
    login = (login or "").strip() or None
    sections, resume, nb = [], [], {g: 0 for g in audit_financier.GRAVITES}
    c = None
    if type_ != "GENERAL":
        c = audit_financier.controle_financier(conn, session, du, au, n_perc, devise, journaliser_controle=False)
        nb = c["nb_anomalies"]
    if type_ == "FINANCIER":
        sections = _sections_financieres(c) + [_section_anomalies(c)]
        resume = _resume_financier(c)
    elif type_ == "ANOMALIES":
        sections = [_section_repartition(c), _section_anomalies(c, avec_conseil=True)]
        resume = [("Reçus contrôlés", str(len(c["paiements"]))), ("Journées contrôlées", str(len(c["rapprochement"]))),
                  ("Anomalies élevées", str(nb["ÉLEVÉE"])), ("Anomalies moyennes", str(nb["MOYENNE"])),
                  ("Anomalies faibles", str(nb["FAIBLE"]))]
    elif type_ == "GENERAL":
        sections, resume = _sections_generales(conn, session, du, au, login, avec_detail)
    else:                                                  # COMPLET : anomalies d'abord, puis le financier, puis le général
        generales, resume_g = _sections_generales(conn, session, du, au, login, avec_detail)
        sections = ([_section_repartition(c), _section_anomalies(c, avec_conseil=True)] + _sections_financieres(c)
                    + generales)
        resume = _resume_financier(c) + resume_g
    etat = etat_journal(conn)
    pn = c["percepteur"] if c else ""
    document = {
        "type": type_, "titre": TYPES_RAPPORT[type_], "du": du, "au": au, "periode_txt": _periode_txt(du, au),
        "filtres": _filtres_txt(du, au, login if type_ in ("GENERAL", "COMPLET") else None,
                                pn if type_ != "GENERAL" else "", devise if type_ != "GENERAL" else None),
        "genere_le": datetime.now().strftime("%d/%m/%Y à %H:%M"), "genere_par": session.nom_complet,
        "journal": etat, "resume": resume, "sections": sections, "nb_anomalies": nb,
        "reinitialisation": bool(c and c["apres_reinitialisation"])}
    if journaliser_generation:
        with conn:
            journaliser(conn, session.id_user, session.login, "AUDIT_RAPPORT_GENERE",
                        f"{document['titre']} | {document['periode_txt']} | anomalies : {nb['ÉLEVÉE']} élevée(s), "
                        f"{nb['MOYENNE']} moyenne(s), {nb['FAIBLE']} faible(s)")
    return document


def _notes_pdf(d) -> list:
    e = d["journal"]
    etat = "chaîne d'empreintes intacte" if e["ok"] else f"ANOMALIE DÉTECTÉE (ligne {e['anomalie']})"
    notes = list(d["filtres"]) + [f"Édité le {d['genere_le']} par {d['genere_par']}",
                                  f"État du journal : {e['nb_lignes']} ligne(s), {etat}, "
                                  f"dernière empreinte {e['derniere_empreinte'][:16]}"]
    if d["reinitialisation"]:
        notes.append("Les opérations antérieures à la dernière réinitialisation de l'application ne sont pas contrôlées.")
    return notes


def _sections_avec_resume(d) -> list:
    resume = _section("Synthèse", [("Indicateur", 220, "g"), ("Valeur", 380, "g")], [list(x) for x in d["resume"]],
                      vide="Rien à signaler.")
    return [resume] + d["sections"]


def exporter_rapport(conn, session, type_, format_, du=None, au=None, login=None, n_perc=None, devise=None,
                     avec_detail=True) -> str:
    """Écrit le rapport en PDF (impression, A4 paysage, cases de signature) ou en CSV (tableur) et retourne le chemin.
    L'exportation est inscrite au journal."""
    format_ = (format_ or "").lower()
    if format_ not in ("csv", "pdf"):
        raise ErreurAudit("Format d'exportation inconnu : choisissez CSV ou PDF.")
    d = generer_rapport(conn, session, type_, du, au, login, n_perc, devise, avec_detail, journaliser_generation=False)
    sections = _sections_avec_resume(d)
    config.DOSSIER_AUDIT.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_AUDIT / _nom_fichier(f"Rapport_{type_.lower()}", format_))
    if format_ == "csv":
        _ecrire_csv(chemin, d, sections)
    else:
        import audit_pdf
        e = d["journal"]
        audit_pdf.generer_rapport(
            d["titre"], _notes_pdf(d), sections, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg",
            pied=(f"Édité le {d['genere_le']} par {d['genere_par']}  -  Journal : {e['nb_lignes']} ligne(s), "
                  f"{'chaîne intacte' if e['ok'] else 'ANOMALIE DÉTECTÉE'}, empreinte {e['derniere_empreinte'][:16]}"),
            signatures=[("Établi par", d["genere_par"]), ("Vérifié par", ""), ("Visa de la Direction", "")])
    with conn:
        journaliser(conn, session.id_user, session.login, "AUDIT_EXPORTE",
                    f"{d['titre']} | {format_.upper()} | {sum(len(s['lignes']) for s in d['sections'])} ligne(s) | "
                    f"{d['periode_txt']}"[:300])
    return chemin


_RE_NOMBRE = re.compile(r"-?\d[\d ]*(,\d+)?")


def _cellule_csv(valeur) -> str:
    """Un tableur exécute une cellule qui commence par = + - @ : on la neutralise, sauf un montant négatif (-5,00)."""
    return valeur if _RE_NOMBRE.fullmatch(str(valeur)) else _protege_csv(valeur)


def _ecrire_csv(chemin, d, sections):
    """Un seul fichier : chaque section a son titre, son en-tête et ses lignes, séparées par une ligne vide."""
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:         # utf-8-sig : accents corrects dans Excel
        w = csv.writer(f, delimiter=";")
        w.writerow([d["titre"]])
        for ligne in _notes_pdf(d):
            w.writerow([_protege_csv(ligne)])
        for s in sections:
            w.writerow([])
            w.writerow([s["titre"]])
            if not s["lignes"]:
                w.writerow([s.get("vide", "Rien à signaler.")])
                continue
            w.writerow([c[0] for c in s["colonnes"]])
            for ligne in s["lignes"]:
                w.writerow([_cellule_csv(v) for v in ligne])
