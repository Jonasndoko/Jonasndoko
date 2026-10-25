"""Recherche et filtrage des traces (module « Traçabilité et audit », sans interface graphique : testable seul).

Retrouver rapidement une opération dans le journal en combinant les filtres :
- UTILISATEUR            : le compte qui a fait l'action ;
- PÉRIODE ou DATE        : du ... au ... (une seule date = ce jour-là) ;
- MODULE CONCERNÉ        : Paiement des frais, Encaissement des fonds perçus, Contrôle numérique, Carte, Travaux
                           techniques, Gestionnaire d'accès, Connexion et authentification, Traçabilité et audit... ;
- TYPE D'ACTION          : « Enregistrement d'un paiement », « Annulation d'un paiement (reçu) », « Connexion »... ;
- NUMÉRO DE REÇU         : toutes les traces de ce reçu (enregistrement, impressions, duplicata, annulation) ;
- MATRICULE DE L'ÉLÈVE   : toutes les traces qui concernent cet élève (ses paiements, la consultation de sa situation,
                           sa carte, les impressions et annulations de ses reçus...). Un fragment de nom est accepté.
Un texte libre (sans tenir compte des accents ni de la casse) complète les filtres.

Les filtres se cumulent (ET). Le journal n'est jamais modifié. Une recherche ciblée sur un reçu ou un élève est elle-même
inscrite au journal (comme dans l'historique financier) : on peut savoir qui a cherché quoi.
"""
import re
from datetime import datetime

import audit
import donnees
import droits
from audit import (ACTIONS, ErreurAudit, LIMITE_LIGNES, _chercher_matricules, _conditions_journal, _ligne_journal,
                   _noms_utilisateurs, _variantes_recu, _verifier_periode, exiger)
from database import journaliser

# ================================================================== modules concernés
MODULES_TRACES = {
    "paiement": "Paiement des frais",
    "encaissement": "Encaissement des fonds perçus",
    "controle": "Contrôle numérique",
    "carte": "Carte",
    "inscription": "Inscription",
    "personnel": "Gestion du personnel",
    "travaux": "Travaux techniques",
    "acces": "Gestionnaire d'accès",
    "connexion": "Connexion et authentification",
    "tableau": "Tableau de bord",
    "audit": "Traçabilité et audit",
    "etudes": "Gestion des études et discipline",
    "parents": "Application des parents",
    "autre": "Autre",
}

# code de l'action (colonne ACTION du journal) -> module concerné par l'opération
MODULE_DE_L_ACTION = {
    # connexion et authentification
    "CONNEXION_OK": "connexion", "DECONNEXION": "connexion", "DECONNEXION_INACTIVITE": "connexion",
    "CONNEXION_ECHEC": "connexion", "CONNEXION_REFUSEE_BLOCAGE": "connexion", "MDP_CHANGE": "connexion",
    "MDP_CHANGEMENT_REFUSE": "connexion", "MDP_REINITIALISE": "connexion", "MDP_RECUPERE": "connexion",
    "COMPTE_DEBLOQUE": "connexion", "CODE_RECUP_GENERE": "connexion", "CODE_RECUP_ANNULE": "connexion",
    "CODE_RECUP_EXPIRE": "connexion", "CODE_RECUP_DETRUIT": "connexion", "CODE_RECUP_ECHEC": "connexion",
    "CODE_RECUP_UTILISE": "connexion",
    # paiement des frais (l'annulation d'un reçu et le « tarif figé » concernent les paiements)
    "SITUATION_CONSULTEE": "paiement", "RECUS_ELEVE_CONSULTES": "paiement", "PAIEMENT_ENREGISTRE": "paiement",
    "RECU_IMPRIME": "paiement", "DUPLICATA_IMPRIME": "paiement", "RAPPORT_CAISSE_IMPRIME": "paiement",
    "PAIEMENT_ANNULE": "paiement", "TARIF_FIGE": "paiement",
    # encaissement des fonds perçus
    "ENCAISSEMENT_ENREGISTRE": "encaissement", "ENCAISSEMENT_MODIFIE": "encaissement",
    "ENCAISSEMENT_SUPPRIME": "encaissement", "RAPPORT_GLOBAL_IMPRIME": "encaissement",
    # contrôle numérique
    "CONTROLE_MOBILE_CONNEXION": "controle", "CONTROLE_MOBILE": "controle", "CONTROLE_MOBILE_ACTIVE": "controle",
    "CONTROLE_MOBILE_COUPE": "controle", "CONTROLE_NUMERIQUE": "controle", "LISTE_EN_ORDRE_CONSULTEE": "controle", "LISTE_EN_ORDRE_IMPRIMEE": "controle",
    # carte
    "FICHE_CARTE_CONSULTEE": "carte", "PHOTO_ENREGISTREE": "carte", "PHOTO_REMPLACEE": "carte",
    "PHOTO_SUPPRIMEE": "carte", "CARTE_IMPRIMEE": "carte",
    # inscription (formulaire, test d'admission, affectation)
    "CANDIDATURE_ENREGISTREE": "inscription", "FICHE_INSCRIPTION_IMPRIMEE": "inscription",
    "CANDIDATURE_TEST_ENREGISTRE": "inscription", "CANDIDAT_ADMIS_AFFECTE": "inscription",
    "AVIS_ADMISSION_IMPRIME": "inscription",
    # gestion du personnel (dossier personnel)
    "AGENT_ENREGISTRE": "personnel", "AGENT_MODIFIE": "personnel", "AGENT_ACTIVE": "personnel",
    "AGENT_DESACTIVE": "personnel", "AGENT_CONSULTE": "personnel", "AGENT_FICHE_IMPRIMEE": "personnel",
    "AGENT_DOCUMENT_AJOUTE": "personnel", "AGENT_DOCUMENT_CONSULTE": "personnel", "AGENT_DOCUMENT_SUPPRIME": "personnel",
    "FONCTION_AJOUT": "personnel", "FONCTION_MODIFICATION": "personnel", "FONCTION_ACTIVATION": "personnel",
    "FONCTION_DESACTIVATION": "personnel", "FONCTION_SUPPRESSION": "personnel", "SERVICE_AJOUT": "personnel",
    "SERVICE_MODIFICATION": "personnel", "SERVICE_ACTIVATION": "personnel", "SERVICE_DESACTIVATION": "personnel",
    "SERVICE_SUPPRESSION": "personnel", "AFFECTATION_ENREGISTREE": "personnel", "AFFECTATION_MODIFIEE": "personnel",
    "AFFECTATION_TERMINEE": "personnel", "LISTE_PERSONNEL_CONSULTEE": "personnel", "LISTE_PERSONNEL_IMPRIMEE": "personnel",
    "PRESENCE_ENREGISTREE": "personnel", "PRESENCE_MODIFIEE": "personnel", "PRESENCE_SUPPRIMEE": "personnel",
    "AUTORISATION_ENREGISTREE": "personnel", "AUTORISATION_ANNULEE": "personnel", "JOUR_FERME_AJOUT": "personnel",
    "JOUR_FERME_SUPPRIME": "personnel", "ETAT_PRESENCES_CONSULTE": "personnel", "ETAT_PRESENCES_IMPRIME": "personnel",
    # gestion scolaire (cours et enseignants)
    "ANNEE_SCOLAIRE_CREEE": "etudes",
    "SEMESTRE_AJOUT": "etudes",
    "PERIODE_AJOUT": "etudes",
    "STRUCTURE_STANDARD_GENEREE": "etudes",
    "COURS_AJOUT": "etudes",
    "PRESENCE_ELEVE_MARQUEE": "etudes",
    "PRESENCE_ELEVE_TOUS": "etudes",
    "NOTES_CONSULTATION": "etudes",
    "NOTES_MANQUANTES_EXPORT": "etudes",
    "CORRECTION_DEMANDEE": "etudes",
    "CORRECTION_TRAITEE": "etudes",
    "CORRECTION_ANNULEE": "etudes",
    "EVALUATION_AJOUT": "etudes",
    "NOTES_IMPRIMEES": "etudes",
    "NOTES_ENREGISTREES": "etudes",
    "CONDUITE_ENREGISTREE": "etudes",
    "TITULAIRE_DESIGNE": "etudes",
    "TITULAIRE_RETIRE": "etudes",
    "SAISIE_AUTORISEE": "etudes",
    "SAISIE_FERMEE": "etudes",
    "COMPTE_PROFESSEUR_CREE": "etudes",
    "EVALUATION_MODIFIEE": "etudes",
    "EVALUATION_SUPPRIMEE": "etudes",
    "COURS_OUVERT_CLASSE": "etudes",
    "ANNEE_SCOLAIRE_MODIFIEE": "etudes",
    "SEMESTRE_MODIFICATION": "etudes",
    "PERIODE_MODIFICATION": "etudes",
    "COURS_MODIFICATION": "etudes",
    "COURS_ACTIVATION": "etudes",
    "COURS_DESACTIVATION": "etudes",
    "COURS_HEURES_MODIFIEES": "etudes",
    "PROFESSEUR_ATTRIBUE": "etudes",
    "SEMESTRE_SUPPRESSION": "etudes",
    "PERIODE_SUPPRESSION": "etudes",
    "COURS_SUPPRESSION": "etudes",
    "COURS_RETIRE_CLASSE": "etudes",
    "PROFESSEUR_RETIRE": "etudes",
    # travaux techniques
    "REF_AJOUT": "travaux", "REF_MODIFICATION": "travaux", "REF_REACTIVATION": "travaux",
    "REF_DESACTIVATION": "travaux", "REF_SUPPRESSION": "travaux", "REF_SUPPRESSION_AVEC_LIEES": "travaux",
    "SAUVEGARDE_TELECHARGEE": "travaux", "SAUVEGARDE_IMPORTEE": "travaux", "SAUVEGARDE_CREEE": "travaux", "RESTAURATION_EFFECTUEE": "travaux", "APPLICATION_REINITIALISEE": "travaux",
    "REINITIALISATION_REFUSEE": "travaux", "DONNEES_ESSAI_AJOUTEES": "travaux", "DONNEES_ESSAI_SUPPRIMEES": "travaux",
    "DONNEES_ESSAI_REFUSEES": "travaux", "MISE_A_JOUR_PROGRAMME": "travaux", "MISE_A_JOUR_REFUSEE": "travaux",
    "MISE_A_JOUR_ECHEC": "travaux", "RETOUR_ANCIENNE_VERSION": "travaux", "STRUCTURE_MISE_A_JOUR": "travaux", "INTEGRITE_VERIFIEE": "travaux",
    # gestionnaire d'accès
    "COMPTE_CREE": "acces", "COMPTE_MODIFIE": "acces", "COMPTE_ACTIVE": "acces", "COMPTE_DESACTIVE": "acces",
    "ROLE_CREE": "acces", "ROLE_SUPPRIME": "acces", "DROITS_MODIFIES": "acces", "SECTIONS_UTILISATEUR_MODIFIEES": "acces", "DROITS_ROLE_MODIFIES": "acces",
    # gestion des études et discipline (préfecture, directions, secrétariat)
    "DOCUMENTS_OFFICIELS_CONSULTES": "etudes", "DOCUMENT_OFFICIEL_PREPARE": "etudes",
    "DOCUMENT_OFFICIEL_MODIFIE": "etudes", "DOCUMENT_OFFICIEL_SOUMIS": "etudes", "DOCUMENT_OFFICIEL_SIGNE": "etudes",
    "DOCUMENT_OFFICIEL_RENVOYE": "etudes", "ELEVE_RENVOYE": "etudes", "DOCUMENT_OFFICIEL_ANNULE": "etudes",
    "DOCUMENT_OFFICIEL_IMPRIME": "etudes", "DOSSIERS_ELEVES_CONSULTES": "etudes",
    "BULLETINS_SECRETARIAT_CONSULTES": "etudes", "ARCHIVES_BULLETINS_CONSULTEES": "etudes",
    "ARCHIVE_BULLETINS_OUVERTE": "etudes", "BULLETINS_SECRETARIAT_IMPRIMES": "etudes",
    "BULLETINS_ARCHIVES": "etudes", "ARCHIVES_SCOLAIRES_CONSULTEES": "etudes", "DOSSIER_ARCHIVE_CONSULTE": "etudes",
    "ARCHIVE_SCOLAIRE_OUVERTE": "etudes", "ARCHIVE_SCOLAIRE_CLASSEE": "etudes", "LISTE_ADMIN_CONSULTEE": "etudes",
    "LISTE_ADMIN_IMPRIMEE": "etudes", "LISTE_ADMIN_EXPORTEE": "etudes", "GESTION_PRESENCES_CONSULTEE": "etudes",
    "PRESENCE_JOUR_CONFIRMEE": "etudes", "PRESENCE_JOUR_CORRIGEE": "etudes", "PRESENCE_CLASSE_CONFIRMEE": "etudes",
    "PRESENCE_JOUR_ANNULEE": "etudes", "SUIVI_CONDUITE_CONSULTE": "etudes", "CONDUITE_ENTREE_AJOUTEE": "etudes",
    "CONDUITE_ENTREE_ANNULEE": "etudes", "ARCHIVE_SCOLAIRE_RETIREE": "etudes", "PROCLAMATION_CONSULTEE": "etudes",
    "DOSSIER_ELEVE_COMPLET": "etudes", "DOSSIER_ELEVE_INCOMPLET": "etudes", "PROCLAMATION_AUTORISEE": "etudes",
    "PROCLAMATION_CRITERES": "etudes", "BULLETIN_VALIDE": "etudes", "BULLETIN_VALIDATION_RETIREE": "etudes",
    "PROCLAMATION_SOUMISE": "etudes", "PROCLAMATION_DECISION_PREFET": "etudes", "PROCLAMATION_CONFIRMEE": "etudes",
    "HEURES_PROFS_CONSULTEES": "etudes", "HEURES_PROF_DETAIL_CONSULTE": "etudes", "HEURES_PROFS_EXPORTEES": "etudes",
    "HORAIRE_CREE": "etudes", "HORAIRE_SEANCE_PLACEE": "etudes", "HORAIRE_SEANCE_DEPLACEE": "etudes",
    "HORAIRE_SEANCE_RETIREE": "etudes", "HORAIRE_PROFESSEUR_AFFECTE": "etudes",
    "HORAIRE_PROFESSEUR_RETIRE": "etudes", "HORAIRE_VACATION_CHANGEE": "etudes",
    "HORAIRE_HEURES_MODIFIEES": "etudes", "HORAIRE_PUBLIE": "etudes", "HORAIRE_DEPUBLIE": "etudes",
    "HORAIRE_SUPPRIME": "etudes", "BULLETINS_CONSULTATION": "etudes", "BULLETINS_CONSULTATION_PDF": "etudes",
    "BULLETINS_ANOMALIES_EXPORT": "etudes", "BULLETINS_GENERES": "etudes", "LISTE_RESULTATS_GENEREE": "etudes",
    "PROCLAMATION_GENEREE": "etudes", "MAXIMUM_COURS_FIXE": "etudes", "NOTES_VERIFICATION": "etudes",
    "STATISTIQUES_CONSULTEES": "etudes", "STATISTIQUES_COMPARAISON": "etudes", "STATISTIQUES_IMPRIMEES": "etudes",
    "CONVOCATION_CONSULTEE": "etudes", "CONVOCATION_ENREGISTREE": "etudes", "CONVOCATION_ENVOYEE": "etudes",
    "CONVOCATION_ANNULEE": "etudes", "PASSAGE_CONSULTE": "etudes", "PASSAGE_CHOIX_ENREGISTRE": "etudes", "PASSAGE_EXECUTE": "etudes",
    "PASSAGE_ANNULE": "etudes", "PASSAGE_EXPORTE": "etudes", "PASSAGE_IMPRIME": "etudes", "PREFECTURE_TABLEAU_OUVERT": "etudes", "PREFECTURE_DOSSIER_CONSULTE": "etudes",
    "PREFECTURE_FINANCES_CONSULTEES": "etudes", "PREFECTURE_FINANCE_ELEVE_CONSULTEE": "etudes",
    "PREFECTURE_DISCIPLINE_CONSULTEE": "etudes", "PREFECTURE_DISCIPLINE_ELEVE_CONSULTEE": "etudes",
    "PREFECTURE_ETUDES_CONSULTEES": "etudes", "PREFECTURE_BULLETIN_CONSULTE": "etudes",
    "PREFECTURE_RAPPORTS_CONSULTES": "etudes", "PREFECTURE_DECISION_ENREGISTREE": "etudes",
    "PREFECTURE_DECISION_ANNULEE": "etudes", "RAPPORT_ENVOYE_AU_PREFET": "etudes",
    # application des parents
    "CODE_PARENT_GENERE": "parents", "PARENT_COMPTE_CREE": "parents", "PARENT_ENFANT_AJOUTE": "parents",
    "PARENT_CONNEXION": "parents", "PARENT_MDP_CHANGE": "parents", "PARENT_COMPTE_BLOQUE": "parents",
    "PARENT_CONVOCATION_LUE": "parents",
    # tableau de bord, traçabilité et audit
    "TABLEAU_DE_BORD_OUVERT": "tableau",
    "AUDIT_OUVERT": "audit", "AUDIT_FINANCIER_CONSULTE": "audit", "AUDIT_CONTROLE_FINANCIER": "audit",
    "AUDIT_RECHERCHE_TRACES": "audit", "AUDIT_RAPPORT_GENERE": "audit", "AUDIT_EXPORTE": "audit",
    "AUDIT_CONTROLE": "audit",
}


def module_de(action) -> str:
    """Clé du module concerné par une action du journal ('autre' pour un code inconnu)."""
    return MODULE_DE_L_ACTION.get(action, "autre")


def libelle_module(cle) -> str:
    return MODULES_TRACES.get(cle, MODULES_TRACES["autre"])


def liste_actions() -> list:
    """[(code, libellé)] des types d'action, classés par module puis par libellé : pour la liste déroulante."""
    return sorted(((code, lib) for code, (_cat, lib) in ACTIONS.items()),
                  key=lambda x: (list(MODULES_TRACES).index(module_de(x[0])), x[1]))


def actions_du_module(module) -> list:
    return [c for c in ACTIONS if module_de(c) == module]


# ================================================================== extraction des références d'une trace
_ACTIONS_RECU = ("PAIEMENT_ENREGISTRE", "PAIEMENT_ANNULE", "RECU_IMPRIME", "DUPLICATA_IMPRIME")
# actions dont le détail commence par le matricule de l'élève
_ACTIONS_REFERENTIEL = ("REF_AJOUT", "REF_MODIFICATION", "REF_REACTIVATION", "REF_DESACTIVATION", "REF_SUPPRESSION",
                        "REF_SUPPRESSION_AVEC_LIEES")       # « Élèves | 0001/26 », « Inscriptions | 2026-2027,0001/26 »
_ACTIONS_MATRICULE = ("RECUS_ELEVE_CONSULTES", "SITUATION_CONSULTEE", "FICHE_CARTE_CONSULTEE", "CONTROLE_NUMERIQUE",
                      "PHOTO_ENREGISTREE", "PHOTO_REMPLACEE", "PHOTO_SUPPRIMEE", "CARTE_IMPRIMEE")


def n_recu_de(action, detail) -> str:
    """N° de reçu d'une trace de paiement ('' pour les autres traces)."""
    return (detail or "").split(" | ", 1)[0].strip() if action in _ACTIONS_RECU else ""


def _matricule_de(action, detail, matricule_du_recu) -> str:
    """Matricule de l'élève que la trace désigne explicitement ('' si elle n'en désigne pas)."""
    premier = (detail or "").split(" | ")
    if action == "PAIEMENT_ENREGISTRE" and len(premier) > 1:
        return premier[1].strip()
    if action in _ACTIONS_MATRICULE:
        return premier[0].strip()
    if action in ("PAIEMENT_ANNULE", "RECU_IMPRIME", "DUPLICATA_IMPRIME"):
        return matricule_du_recu.get(premier[0].strip(), "")
    return ""


def _motif(matricules):
    """Expression qui reconnaît un matricule entier dans un détail (pas « 0001/26 » dans « 10001/26 »)."""
    return re.compile(r"(?<![\w/-])(?:" + "|".join(re.escape(m) for m in sorted(matricules, key=len, reverse=True))
                      + r")(?![\w/])", re.IGNORECASE)


# ================================================================== la recherche
def rechercher_traces(conn, session, du=None, au=None, login=None, module=None, action=None, n_recu=None,
                      matricule=None, texte=None, limite=LIMITE_LIGNES, journaliser_recherche=True) -> dict:
    """Recherche dans les traces du journal, de la plus récente à la plus ancienne.

    `du` / `au` : dates incluses ; `login` : un utilisateur ; `module` : clé de MODULES_TRACES ; `action` : code d'une
    action (liste_actions) ; `n_recu` : numéro de reçu (« 12 » trouve « 0012 ») ; `matricule` : matricule ou fragment du
    nom de l'élève ; `texte` : mot cherché dans l'action, l'utilisateur, le nom et le détail. `limite` : nombre de lignes
    retournées (None = toutes) ; `total` donne toujours le nombre de traces trouvées.

    Chaque ligne a, en plus des champs du journal, `module`, `module_txt`, `n_recu` et `matricule`."""
    exiger(conn, session)
    _verifier_periode(du, au)
    login = (login or "").strip() or None
    module = (module or "").strip() or None
    action = (action or "").strip() or None
    n_recu = (n_recu or "").strip()
    terme_eleve = " ".join((matricule or "").split())
    texte = " ".join((texte or "").split())
    if module and module not in MODULES_TRACES:
        raise ErreurAudit("Module inconnu.")
    if action and action not in ACTIONS:
        raise ErreurAudit("Type d'action inconnu.")
    if module and action and module_de(action) != module:
        raise ErreurAudit(f"L'action « {audit.libelle_action(action)} » ne fait pas partie du module « "
                          f"{libelle_module(module)} » : choisissez l'un ou l'autre, ou une action de ce module.")

    cond, params = _conditions_journal(du, au, login, None, False)
    codes = None                                           # actions retenues par le module et / ou le type d'action
    if action:
        codes = [action]
    elif module:
        codes = actions_du_module(module)
        if module == "autre":
            connus = list(ACTIONS)
            cond.append(f"J.ACTION NOT IN ({','.join('?' * len(connus))})")
            params += connus
            codes = None
        elif not codes:
            codes = ["_AUCUNE_"]
    if codes is not None:
        cond.append(f"J.ACTION IN ({','.join('?' * len(codes))})")
        params += codes

    variantes = _variantes_recu(n_recu) if n_recu else None
    if variantes:                                           # seules les traces de paiement portent un n° de reçu
        cond.append(f"J.ACTION IN ({','.join('?' * len(_ACTIONS_RECU))})")
        params += list(_ACTIONS_RECU)

    motif_eleve, matricules = None, set()
    if terme_eleve:
        matricules = _chercher_matricules(conn, terme_eleve) or {terme_eleve}      # élève supprimé : le texte tel quel
        motif_eleve = _motif(matricules)
        minuscules = {m.lower() for m in matricules}

    sql = ("SELECT J.ID_LOG, J.DATE_HEURE, J.LOGIN, J.ACTION, J.DETAIL, U.NOM_COMPLET, U.ROLE "
           "FROM JOURNAL J LEFT JOIN UTILISATEUR U ON U.ID_USER = J.ID_USER "
           + ("WHERE " + " AND ".join(cond) + " " if cond else "") + "ORDER BY J.ID_LOG DESC")
    noms = _noms_utilisateurs(conn)
    roles = droits.roles(conn)
    fragments = [donnees.sans_accents(f) for f in texte.split()]
    matricule_du_recu = {l["N_RECU"]: l["MATRICULE"] for l in conn.execute("SELECT N_RECU, MATRICULE FROM PAIEMENT")}

    lignes, total = [], 0
    for l in conn.execute(sql, params):
        action, detail = l["ACTION"], l["DETAIL"] or ""
        recu = n_recu_de(action, detail)
        if variantes and recu not in variantes:
            continue
        mat = _matricule_de(action, detail, matricule_du_recu)
        if motif_eleve is not None and not ((mat and mat.lower() in minuscules)
                                            or (action in _ACTIONS_REFERENTIEL and motif_eleve.search(detail))):
            continue
        ligne = None
        if fragments:                                       # le texte se cherche en Python : insensible aux accents
            ligne = _ligne_journal(l, noms, roles)
            cible = donnees.sans_accents(" ".join((ligne["action"], ligne["libelle"], ligne["login"], ligne["nom"],
                                                   ligne["detail"], libelle_module(module_de(action)))))
            if not all(f in cible for f in fragments):
                continue
        total += 1
        if limite is None or len(lignes) < limite:
            ligne = ligne or _ligne_journal(l, noms, roles)
            ligne.update(module=module_de(action), module_txt=libelle_module(module_de(action)), n_recu=recu,
                         matricule=mat)
            lignes.append(ligne)

    ciblee = bool(n_recu or terme_eleve)
    if ciblee and journaliser_recherche:
        with conn:
            journaliser(conn, session.id_user, session.login, "AUDIT_RECHERCHE_TRACES",
                        " | ".join(x for x in (f"reçu : {n_recu}" if n_recu else "",
                                               f"élève : {terme_eleve}" if terme_eleve else "",
                                               f"{total} trace(s)") if x))
    return {"lignes": lignes, "total": total, "du": du, "au": au, "login": login or "", "module": module or "",
            "action": action or "", "n_recu": n_recu, "matricule": terme_eleve, "texte": texte,
            "genere_le": datetime.now().strftime("%d/%m/%Y à %H:%M")}


def decrire_filtres(r) -> list:
    """Les filtres d'une recherche, en clair (pour l'en-tête d'un export ou le résumé affiché)."""
    f = lambda d: d.strftime("%d/%m/%Y")
    periode = (f"du {f(r['du'])} au {f(r['au'])}" if r["du"] and r["au"] else f"depuis le {f(r['du'])}" if r["du"]
               else f"jusqu'au {f(r['au'])}" if r["au"] else "")
    return [x for x in (
        f"Période : {periode}" if periode else "", f"Utilisateur : {r['login']}" if r["login"] else "",
        f"Module : {libelle_module(r['module'])}" if r["module"] else "",
        f"Action : {audit.libelle_action(r['action'])}" if r["action"] else "",
        f"N° de reçu : {r['n_recu']}" if r["n_recu"] else "", f"Élève : {r['matricule']}" if r["matricule"] else "",
        f"Texte : {r['texte']}" if r["texte"] else "") if x]


# ================================================================== exportation (CSV et PDF)
COLONNES_TRACES = [("Date et heure", 100, "g"), ("Utilisateur", 78, "g"), ("Module", 100, "g"), ("Action", 135, "g"),
                   ("N° reçu", 40, "g"), ("Matricule", 58, "g"), ("Détail", 231.89, "g")]


def exporter_traces(conn, session, format_, du=None, au=None, login=None, module=None, action=None, n_recu=None,
                    matricule=None, texte=None) -> str:
    """Exporte TOUTES les traces trouvées, en CSV (tableur) ou PDF (impression). L'exportation est inscrite au journal."""
    r = rechercher_traces(conn, session, du, au, login, module, action, n_recu, matricule, texte, limite=None,
                          journaliser_recherche=False)
    if not r["lignes"]:
        raise ErreurAudit("Aucune trace à exporter avec ces filtres.")
    lignes = [[l["date_txt"], l["login"], l["module_txt"], l["libelle"], l["n_recu"], l["matricule"], l["detail"]]
              for l in r["lignes"]]
    return audit._exporter(conn, session, "traces", format_, "Recherche dans les traces", decrire_filtres(r),
                           COLONNES_TRACES, lignes, r["total"])
