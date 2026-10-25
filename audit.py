"""Module « Traçabilité et audit » : retrouver QUI a fait QUOI, QUAND (sans interface graphique : testable seul).

Ce module ne modifie rien : il LIT le journal de l'application (table JOURNAL, chaînée par empreintes et en ajout
seulement : aucune ligne ne peut être modifiée ni supprimée) et les tables financières.

Qui le voit : l'Administrateur et les comptes à qui l'Administrateur a accordé la Lecture sur ce module
(Gestionnaire d'accès > Autorisations ou Rôles). Les droits sont relus dans la base à chaque appel.

Trois volets :
1. JOURNAL DES ACTIVITÉS : toutes les actions enregistrées automatiquement pour chaque utilisateur (connexion et
   déconnexion, consultation d'un dossier, ajout, modification ou suppression d'une donnée, impression ou exportation
   d'un rapport...), filtrables par période, utilisateur, catégorie et texte.
2. HISTORIQUE DES OPÉRATIONS FINANCIÈRES : paiements enregistrés (N° de reçu, élève, percepteur, utilisateur qui l'a
   saisi), reçus et duplicata imprimés, annulations de paiement (qui, quand, pourquoi), encaissements et remises de
   fonds, écarts entre le montant encaissé et le montant versé. Exemple : retrouver le paiement d'un élève et
   l'utilisateur qui l'a enregistré.
3. CONTRÔLES : vérification de la chaîne d'empreintes du journal, et concordance entre le journal et les tables
   financières (un reçu sans trace au journal, un trou dans la numérotation des reçus... sont signalés).

Toute ouverture du module, toute recherche ciblée (élève, n° de reçu), tout contrôle et tout export est lui-même
inscrit au journal : on peut aussi savoir qui a consulté l'audit.
"""
import csv
import re
from datetime import date, datetime

import argent
import config
import donnees
import droits
from database import journaliser, lire_iso, maintenant
from paiements import _bornes_utc

MODULE = "audit"
LIMITE_LIGNES = 500          # lignes affichées à l'écran (les exports, eux, contiennent toutes les lignes trouvées)


class ErreurAudit(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


# ================================================================== droits
def peut(conn, session) -> bool:
    """Administrateur, ou compte ayant la Lecture sur le module « Traçabilité et audit »."""
    return droits.est_admin(conn, session) or droits.a_droit(conn, session, MODULE, "LECTURE")


def exiger(conn, session):
    if not peut(conn, session):
        raise PermissionError(f"Accès refusé : vous n'avez pas le droit « {config.LIBELLE_DROITS['LECTURE']} » "
                              f"sur le module « {config.MODULES_DROITS[MODULE][0]} ».")


# ================================================================== catalogue des actions du journal
CATEGORIES = {
    "CONNEXION": "Connexion / déconnexion",
    "CONSULTATION": "Consultation",
    "AJOUT": "Ajout de données",
    "MODIFICATION": "Modification de données",
    "SUPPRESSION": "Suppression / annulation",
    "IMPRESSION": "Impression / exportation",
    "SECURITE": "Sécurité et administration",
    "AUTRE": "Autre",
}

# code de l'action (colonne ACTION du journal) -> (catégorie, libellé lisible)
ACTIONS = {
    # --- connexion / déconnexion
    "CONNEXION_OK": ("CONNEXION", "Connexion"),
    "DECONNEXION": ("CONNEXION", "Déconnexion"),
    "DECONNEXION_INACTIVITE": ("CONNEXION", "Déconnexion automatique (inactivité)"),
    "CONNEXION_ECHEC": ("CONNEXION", "Échec de connexion"),
    "CONNEXION_REFUSEE_BLOCAGE": ("CONNEXION", "Connexion refusée (compte bloqué)"),
    "CONTROLE_MOBILE_CONNEXION": ("CONNEXION", "Connexion à l'application mobile de contrôle"),
    # --- consultation
    "SITUATION_CONSULTEE": ("CONSULTATION", "Consultation de la situation d'un élève"),
    "RECUS_ELEVE_CONSULTES": ("CONSULTATION", "Consultation des reçus d'un élève"),
    "FICHE_CARTE_CONSULTEE": ("CONSULTATION", "Consultation de la fiche d'un élève (carte)"),
    "CONTROLE_NUMERIQUE": ("CONSULTATION", "Contrôle numérique d'un élève"),
    "CONTROLE_MOBILE": ("CONSULTATION", "Contrôle d'un élève depuis l'application mobile"),
    "CONTROLE_MOBILE_ACTIVE": ("SECURITE", "Application mobile de contrôle activée"),
    "CONTROLE_MOBILE_COUPE": ("SECURITE", "Application mobile de contrôle coupée"),
    "LISTE_EN_ORDRE_CONSULTEE": ("CONSULTATION", "Consultation de la liste des élèves en ordre"),
    "TABLEAU_DE_BORD_OUVERT": ("CONSULTATION", "Ouverture du tableau de bord"),
    "AUDIT_OUVERT": ("CONSULTATION", "Ouverture du module Traçabilité et audit"),
    "AUDIT_FINANCIER_CONSULTE": ("CONSULTATION", "Recherche dans l'historique financier"),
    "AUDIT_CONTROLE_FINANCIER": ("CONSULTATION", "Contrôle et audit financier"),
    "AUDIT_RECHERCHE_TRACES": ("CONSULTATION", "Recherche ciblée dans les traces (reçu ou élève)"),
    "AUDIT_RAPPORT_GENERE": ("CONSULTATION", "Génération d'un rapport d'audit"),
    "DOCUMENTS_OFFICIELS_CONSULTES": ("CONSULTATION", "Consultation des documents scolaires officiels (Préfecture)"),
    "DOCUMENT_OFFICIEL_PREPARE": ("AJOUT", "Document scolaire officiel préparé (brouillon)"),
    "DOCUMENT_OFFICIEL_MODIFIE": ("MODIFICATION", "Brouillon d'un document scolaire officiel modifié"),
    "DOCUMENT_OFFICIEL_SOUMIS": ("MODIFICATION", "Document scolaire officiel soumis à la signature ou à la validation"),
    "DOCUMENT_OFFICIEL_SIGNE": ("MODIFICATION", "Document scolaire officiel signé ou validé (numéro attribué)"),
    "DOCUMENT_OFFICIEL_RENVOYE": ("MODIFICATION", "Document scolaire officiel renvoyé en brouillon (motif)"),
    "ELEVE_RENVOYE": ("MODIFICATION", "Élève renvoyé par le Préfet (dossier archivé, matricule libéré)"),
    "DOCUMENT_OFFICIEL_ANNULE": ("MODIFICATION", "Document scolaire officiel annulé (motif)"),
    "DOCUMENT_OFFICIEL_IMPRIME": ("IMPRESSION", "Impression d'un document scolaire officiel"),
    "DOSSIERS_ELEVES_CONSULTES": ("CONSULTATION", "Consultation de la liste des dossiers des élèves (Secrétariat)"),
    "BULLETINS_SECRETARIAT_CONSULTES": ("CONSULTATION", "Consultation des bulletins validés par la Préfecture (Secrétariat)"),
    "ARCHIVES_BULLETINS_CONSULTEES": ("CONSULTATION", "Consultation de la liste des bulletins archivés (Secrétariat)"),
    "ARCHIVE_BULLETINS_OUVERTE": ("CONSULTATION", "Ouverture d'une archive de bulletins (Secrétariat)"),
    "BULLETINS_SECRETARIAT_IMPRIMES": ("IMPRESSION", "Impression des bulletins validés par la Préfecture (Secrétariat)"),
    "BULLETINS_ARCHIVES": ("AJOUT", "Bulletins validés archivés en PDF (Secrétariat)"),
    "ARCHIVES_SCOLAIRES_CONSULTEES": ("CONSULTATION", "Recherche dans les archives scolaires (Secrétariat)"),
    "DOSSIER_ARCHIVE_CONSULTE": ("CONSULTATION", "Consultation du dossier archivé d'un élève (Secrétariat)"),
    "ARCHIVE_SCOLAIRE_OUVERTE": ("CONSULTATION", "Ouverture d'un document des archives scolaires (Secrétariat)"),
    "ARCHIVE_SCOLAIRE_CLASSEE": ("AJOUT", "Document classé dans les archives scolaires (Secrétariat)"),
    "LISTE_ADMIN_CONSULTEE": ("CONSULTATION", "Consultation d'une liste administrative : élèves ou dossiers incomplets (Secrétariat)"),
    "LISTE_ADMIN_IMPRIMEE": ("IMPRESSION", "Impression (PDF) d'une liste administrative (Secrétariat)"),
    "LISTE_ADMIN_EXPORTEE": ("IMPRESSION", "Exportation (CSV) d'une liste administrative (Secrétariat)"),
    "GESTION_PRESENCES_CONSULTEE": ("CONSULTATION", "Consultation des présences des élèves : journée, classe, absences (Direction de discipline)"),
    "PRESENCE_JOUR_CONFIRMEE": ("MODIFICATION", "Présence d'un élève confirmée pour un jour (Direction de discipline)"),
    "PRESENCE_JOUR_CORRIGEE": ("MODIFICATION", "Présence d'un élève corrigée pour un jour (motif ; pointage du professeur conservé)"),
    "PRESENCE_CLASSE_CONFIRMEE": ("MODIFICATION", "Présences d'une classe confirmées pour un jour (Direction de discipline)"),
    "PRESENCE_JOUR_ANNULEE": ("MODIFICATION", "Décision sur la présence d'un élève annulée (motif ; la décision reste dans la base)"),
    "SUIVI_CONDUITE_CONSULTE": ("CONSULTATION", "Consultation du suivi de la conduite : vue d'ensemble, cotes des professeurs, registre, historique d'un élève (Direction de discipline)"),
    "CONDUITE_ENTREE_AJOUTEE": ("AJOUT", "Observation disciplinaire, comportement inapproprié, incident ou mention enregistré pour un élève (Direction de discipline)"),
    "CONDUITE_ENTREE_ANNULEE": ("MODIFICATION", "Entrée du suivi de la conduite annulée (motif ; l'entrée reste dans la base)"),
    "ARCHIVE_SCOLAIRE_RETIREE": ("SUPPRESSION", "Document retiré du classement des archives scolaires (motif ; le fichier est conservé)"),
    "PROCLAMATION_CONSULTEE": ("CONSULTATION", "Consultation de la proclamation d'une classe (validations des bulletins)"),
    "AGENT_CONSULTE": ("CONSULTATION", "Consultation du dossier d'un agent (personnel)"),
    "AGENT_DOCUMENT_CONSULTE": ("CONSULTATION", "Ouverture d'un document numérisé d'un agent"),
    "ETAT_PRESENCES_CONSULTE": ("CONSULTATION", "Consultation d'un état des présences et absences (personnel)"),
    "LISTE_PERSONNEL_CONSULTEE": ("CONSULTATION", "Consultation de la liste du personnel (par fonction ou service)"),
    # --- ajout
    "REF_AJOUT": ("AJOUT", "Ajout d'une donnée"),
    "PAIEMENT_ENREGISTRE": ("AJOUT", "Enregistrement d'un paiement"),
    "ENCAISSEMENT_ENREGISTRE": ("AJOUT", "Enregistrement d'un encaissement"),
    "PHOTO_ENREGISTREE": ("AJOUT", "Enregistrement d'une photo"),
    "CANDIDATURE_ENREGISTREE": ("AJOUT", "Enregistrement d'une candidature (inscription)"),
    "CANDIDAT_ADMIS_AFFECTE": ("AJOUT", "Candidat admis, affecté à une classe et devenu élève (matricule attribué)"),
    "TARIF_FIGE": ("AJOUT", "Montant appliqué à une classe (automatique)"),
    "COMPTE_CREE": ("AJOUT", "Création d'un compte"),
    "ROLE_CREE": ("AJOUT", "Création d'un rôle"),
    "AGENT_ENREGISTRE": ("AJOUT", "Enregistrement d'un nouvel agent (personnel)"),
    "AGENT_DOCUMENT_AJOUTE": ("AJOUT", "Ajout d'un document numérisé au dossier d'un agent"),
    "FONCTION_AJOUT": ("AJOUT", "Ajout d'une fonction (personnel)"),
    "SERVICE_AJOUT": ("AJOUT", "Ajout d'un service (personnel)"),
    "AFFECTATION_ENREGISTREE": ("AJOUT", "Affectation d'un agent (fonction, service, responsabilité)"),
    "ANNEE_SCOLAIRE_CREEE": ("AJOUT", "Création d'une année scolaire avec ses dates"),
    "SEMESTRE_AJOUT": ("AJOUT", "Ajout d'un semestre"),
    "PERIODE_AJOUT": ("AJOUT", "Ajout d'une période"),
    "STRUCTURE_STANDARD_GENEREE": ("AJOUT", "Génération de la structure standard d'une année (2 semestres, 4 périodes)"),
    "COURS_AJOUT": ("AJOUT", "Ajout d'un cours"),
    "COURS_OUVERT_CLASSE": ("AJOUT", "Ouverture de cours dans une classe pour une année scolaire"),
    "PRESENCE_ELEVE_MARQUEE": ("MODIFICATION", "Présence ou absence d'un élève à un cours (pointage par le professeur)"),
    "PRESENCE_ELEVE_TOUS": ("MODIFICATION", "Pointage de tous les élèves d'un cours comme présents"),
    "EVALUATION_AJOUT": ("AJOUT", "Première saisie des points d'une période ou d'un examen par un professeur (colonne créée)"),
    "NOTES_ENREGISTREES": ("AJOUT", "Enregistrement de points par un professeur"),
    "CONDUITE_ENREGISTREE": ("AJOUT", "Conduite d'un élève donnée par un professeur"),
    "SECTIONS_UTILISATEUR_MODIFIEES": ("SECURITE", "Sections de l'école ouvertes à un compte (primaire, secondaire et humanitaire)"),
    "TITULAIRE_DESIGNE": ("MODIFICATION", "Désignation (ou remplacement) du professeur titulaire d'une classe"),
    "TITULAIRE_RETIRE": ("MODIFICATION", "Retrait du titulaire d'une classe"),
    "SAISIE_AUTORISEE": ("MODIFICATION", "Période ou examen ouvert à la saisie des professeurs par le titulaire de la classe"),
    "SAISIE_FERMEE": ("MODIFICATION", "Période ou examen fermé à la saisie des professeurs par le titulaire de la classe"),
    "COMPTE_PROFESSEUR_CREE": ("AJOUT", "Création du compte de connexion d'un professeur"),
    "NOTES_IMPRIMEES": ("IMPRESSION", "Impression du relevé des points d'un cours par un professeur"),
    "PRESENCE_ENREGISTREE": ("AJOUT", "Enregistrement d'une présence, d'un retard ou d'une absence (personnel)"),
    "AUTORISATION_ENREGISTREE": ("AJOUT", "Enregistrement d'une permission ou d'un congé (personnel)"),
    "JOUR_FERME_AJOUT": ("AJOUT", "Ajout d'un jour non travaillé (personnel)"),
    # --- modification
    "REF_MODIFICATION": ("MODIFICATION", "Modification d'une donnée"),
    "REF_REACTIVATION": ("MODIFICATION", "Réactivation d'une donnée"),
    "REF_DESACTIVATION": ("MODIFICATION", "Désactivation d'une donnée"),
    "ENCAISSEMENT_MODIFIE": ("MODIFICATION", "Modification d'un encaissement"),
    "CANDIDATURE_TEST_ENREGISTRE": ("MODIFICATION", "Résultat du test d'admission d'un candidat (validation ou refus)"),
    "PHOTO_REMPLACEE": ("MODIFICATION", "Remplacement d'une photo"),
    "COMPTE_MODIFIE": ("MODIFICATION", "Modification d'un compte"),
    "COMPTE_ACTIVE": ("MODIFICATION", "Activation d'un compte"),
    "COMPTE_DESACTIVE": ("MODIFICATION", "Désactivation d'un compte"),
    "DROITS_MODIFIES": ("MODIFICATION", "Modification des droits d'un compte"),
    "DROITS_ROLE_MODIFIES": ("MODIFICATION", "Modification des droits d'un rôle"),
    "DOSSIER_ELEVE_COMPLET": ("MODIFICATION", "Dossier d'un élève déclaré complet par la secrétaire"),
    "DOSSIER_ELEVE_INCOMPLET": ("MODIFICATION", "Dossier d'un élève remis à « incomplet » par la secrétaire"),
    "PROCLAMATION_AUTORISEE": ("MODIFICATION", "Titulaire autorisé pour la proclamation d'une classe (Directrice des études)"),
    "PROCLAMATION_CRITERES": ("MODIFICATION", "Frais exigés pour la proclamation d'une classe (Directrice des études)"),
    "BULLETIN_VALIDE": ("MODIFICATION", "Bulletin d'un élève validé pour la proclamation"),
    "BULLETIN_VALIDATION_RETIREE": ("MODIFICATION", "Validation du bulletin d'un élève retirée"),
    "PROCLAMATION_SOUMISE": ("MODIFICATION", "Proclamation d'une classe soumise au Préfet (Directrice des études)"),
    "PROCLAMATION_DECISION_PREFET": ("MODIFICATION", "Décision de la Directrice des études changée par le Préfet (bulletin d'un élève)"),
    "PROCLAMATION_CONFIRMEE": ("MODIFICATION", "Proclamation d'une classe confirmée par le Préfet"),
    "AGENT_MODIFIE": ("MODIFICATION", "Modification des informations d'un agent"),
    "AGENT_ACTIVE": ("MODIFICATION", "Réactivation du dossier d'un agent"),
    "AGENT_DESACTIVE": ("MODIFICATION", "Désactivation du dossier d'un agent"),
    "FONCTION_MODIFICATION": ("MODIFICATION", "Modification du nom d'une fonction"),
    "FONCTION_ACTIVATION": ("MODIFICATION", "Réactivation d'une fonction"),
    "FONCTION_DESACTIVATION": ("MODIFICATION", "Désactivation d'une fonction"),
    "SERVICE_MODIFICATION": ("MODIFICATION", "Modification du nom d'un service"),
    "SERVICE_ACTIVATION": ("MODIFICATION", "Réactivation d'un service"),
    "SERVICE_DESACTIVATION": ("MODIFICATION", "Désactivation d'un service"),
    "AFFECTATION_MODIFIEE": ("MODIFICATION", "Correction d'une affectation"),
    "AFFECTATION_TERMINEE": ("MODIFICATION", "Fin d'une affectation"),
    "ANNEE_SCOLAIRE_MODIFIEE": ("MODIFICATION", "Modification d'une année scolaire (dates, année en cours)"),
    "SEMESTRE_MODIFICATION": ("MODIFICATION", "Modification d'un semestre"),
    "PERIODE_MODIFICATION": ("MODIFICATION", "Modification d'une période"),
    "COURS_MODIFICATION": ("MODIFICATION", "Modification d'un cours"),
    "COURS_ACTIVATION": ("MODIFICATION", "Réactivation d'un cours"),
    "COURS_DESACTIVATION": ("MODIFICATION", "Désactivation d'un cours"),
    "COURS_HEURES_MODIFIEES": ("MODIFICATION", "Modification des heures d'un cours dans une classe"),
    "EVALUATION_MODIFIEE": ("MODIFICATION", "Modification du maximum des points d'une période ou d'un examen"),
    "PROFESSEUR_ATTRIBUE": ("MODIFICATION", "Attribution de cours à un professeur"),
    "PRESENCE_MODIFIEE": ("MODIFICATION", "Correction d'une présence, d'un retard ou d'une absence (personnel)"),
    "AUTORISATION_ANNULEE": ("MODIFICATION", "Annulation d'une permission ou d'un congé (personnel)"),
    # --- suppression / annulation
    "REF_SUPPRESSION": ("SUPPRESSION", "Suppression d'une donnée"),
    "REF_SUPPRESSION_AVEC_LIEES": ("SUPPRESSION", "Suppression d'une donnée et de ses données liées"),
    "ENCAISSEMENT_SUPPRIME": ("SUPPRESSION", "Suppression d'un encaissement"),
    "PHOTO_SUPPRIMEE": ("SUPPRESSION", "Suppression d'une photo"),
    "ROLE_SUPPRIME": ("SUPPRESSION", "Suppression d'un rôle"),
    "PAIEMENT_ANNULE": ("SUPPRESSION", "Annulation d'un paiement (reçu)"),
    "AGENT_DOCUMENT_SUPPRIME": ("SUPPRESSION", "Suppression d'un document numérisé d'un agent"),
    "SEMESTRE_SUPPRESSION": ("SUPPRESSION", "Suppression d'un semestre"),
    "PERIODE_SUPPRESSION": ("SUPPRESSION", "Suppression d'une période"),
    "COURS_SUPPRESSION": ("SUPPRESSION", "Suppression d'un cours jamais utilisé"),
    "COURS_RETIRE_CLASSE": ("SUPPRESSION", "Retrait d'un cours d'une classe"),
    # --- direction des études : élaboration horaire
    "HEURES_PROFS_CONSULTEES": ("CONSULTATION", "Consultation des présences et des heures des professeurs"),
    "HEURES_PROF_DETAIL_CONSULTE": ("CONSULTATION", "Consultation du détail des heures d'un professeur"),
    "HEURES_PROFS_EXPORTEES": ("IMPRESSION", "Exportation (CSV) des heures des professeurs"),
    "HORAIRE_CREE": ("AJOUT", "Horaire d'une classe créé"),
    "HORAIRE_SEANCE_PLACEE": ("AJOUT", "Cours placé dans l'horaire"),
    "HORAIRE_SEANCE_DEPLACEE": ("MODIFICATION", "Cours déplacé ou échangé dans l'horaire"),
    "HORAIRE_SEANCE_RETIREE": ("SUPPRESSION", "Cours retiré de l'horaire"),
    "HORAIRE_PROFESSEUR_AFFECTE": ("MODIFICATION", "Professeur affecté à un cours (horaire)"),
    "HORAIRE_PROFESSEUR_RETIRE": ("MODIFICATION", "Professeur retiré d'un cours (horaire)"),
    "HORAIRE_VACATION_CHANGEE": ("MODIFICATION", "Vacation d'une classe modifiée (horaire)"),
    "HORAIRE_HEURES_MODIFIEES": ("MODIFICATION", "Heures, pauses et récréations modifiées (horaire)"),
    "HORAIRE_PUBLIE": ("MODIFICATION", "Horaire publié"),
    "HORAIRE_DEPUBLIE": ("MODIFICATION", "Horaire retiré de la publication"),
    "HORAIRE_SUPPRIME": ("SUPPRESSION", "Horaire d'une classe supprimé"),
    # --- direction des études : contrôle des notes
    "NOTES_CONSULTATION": ("CONSULTATION", "Consultation des notes saisies d'un cours (contrôle des notes)"),
    "NOTES_MANQUANTES_EXPORT": ("IMPRESSION", "Exportation (CSV) des notes manquantes"),
    "CORRECTION_DEMANDEE": ("AJOUT", "Demande de saisie ou de correction de notes envoyée à un professeur"),
    "CORRECTION_TRAITEE": ("MODIFICATION", "Demande de correction marquée traitée par le professeur"),
    "CORRECTION_ANNULEE": ("MODIFICATION", "Demande de correction annulée par la direction des études"),
    "EVALUATION_SUPPRIMEE": ("SUPPRESSION", "Effacement des points d'une période, d'un examen ou d'une ancienne évaluation"),
    "PROFESSEUR_RETIRE": ("SUPPRESSION", "Retrait du professeur d'un cours"),
    "PRESENCE_SUPPRIMEE": ("SUPPRESSION", "Suppression d'un pointage saisi par erreur (personnel)"),
    "JOUR_FERME_SUPPRIME": ("SUPPRESSION", "Suppression d'un jour non travaillé (personnel)"),
    "FONCTION_SUPPRESSION": ("SUPPRESSION", "Suppression d'une fonction jamais utilisée"),
    "SERVICE_SUPPRESSION": ("SUPPRESSION", "Suppression d'un service jamais utilisé"),
    # --- impression / exportation
    "RECU_IMPRIME": ("IMPRESSION", "Impression d'un reçu"),
    "DUPLICATA_IMPRIME": ("IMPRESSION", "Impression d'un duplicata de reçu"),
    "RAPPORT_CAISSE_IMPRIME": ("IMPRESSION", "Impression du rapport journalier de caisse"),
    "RAPPORT_GLOBAL_IMPRIME": ("IMPRESSION", "Impression du rapport global des encaissements"),
    "CARTE_IMPRIMEE": ("IMPRESSION", "Impression d'une carte d'élève"),
    "FICHE_INSCRIPTION_IMPRIMEE": ("IMPRESSION", "Impression d'une fiche d'inscription"),
    "AVIS_ADMISSION_IMPRIME": ("IMPRESSION", "Impression d'un avis d'admission"),
    "AGENT_FICHE_IMPRIMEE": ("IMPRESSION", "Impression de la fiche individuelle d'un agent"),
    "ETAT_PRESENCES_IMPRIME": ("IMPRESSION", "Impression d'un état des présences et absences (personnel)"),
    "LISTE_PERSONNEL_IMPRIMEE": ("IMPRESSION", "Impression de la liste du personnel (par fonction ou service)"),
    "LISTE_EN_ORDRE_IMPRIMEE": ("IMPRESSION", "Impression de la liste des élèves en ordre"),
    "SAUVEGARDE_CREEE": ("IMPRESSION", "Exportation : sauvegarde de la base"),
    "SAUVEGARDE_TELECHARGEE": ("IMPRESSION", "Téléchargement d'une sauvegarde de la base"),
    "SAUVEGARDE_IMPORTEE": ("SECURITE", "Envoi d'un fichier de sauvegarde sur le serveur"),
    "AUDIT_EXPORTE": ("IMPRESSION", "Exportation d'un rapport d'audit"),
    # --- direction des études : bulletins, proclamation, statistiques, convocations
    "BULLETINS_CONSULTATION": ("CONSULTATION", "Consultation des bulletins calculés d'une classe (Gestion des bulletins)"),
    "BULLETINS_CONSULTATION_PDF": ("IMPRESSION", "Impression (PDF) des bulletins consultés (Gestion des bulletins)"),
    "BULLETINS_ANOMALIES_EXPORT": ("IMPRESSION", "Exportation (CSV) des anomalies des bulletins"),
    "BULLETINS_GENERES": ("IMPRESSION", "Génération (PDF) des bulletins validés d'une classe"),
    "LISTE_RESULTATS_GENEREE": ("IMPRESSION", "Génération (PDF) de la liste des résultats d'une classe"),
    "PROCLAMATION_GENEREE": ("IMPRESSION", "Génération (PDF) de la proclamation d'une classe"),
    "MAXIMUM_COURS_FIXE": ("MODIFICATION", "Maximum des points d'un cours fixé par le titulaire de la classe"),
    "NOTES_VERIFICATION": ("CONSULTATION", "Vérification des notes d'une classe (contrôle des notes)"),
    "STATISTIQUES_CONSULTEES": ("CONSULTATION", "Consultation des statistiques et rapports scolaires"),
    "STATISTIQUES_COMPARAISON": ("CONSULTATION", "Comparaison des périodes (statistiques scolaires)"),
    "STATISTIQUES_IMPRIMEES": ("IMPRESSION", "Impression des statistiques et rapports scolaires"),
    "CONVOCATION_CONSULTEE": ("CONSULTATION", "Consultation des convocations des parents (recherche, liste, détail)"),
    "CONVOCATION_ENREGISTREE": ("AJOUT", "Convocation d'un parent enregistrée"),
    "CONVOCATION_ENVOYEE": ("MODIFICATION", "Convocation envoyée au parent"),
    "CONVOCATION_ANNULEE": ("SUPPRESSION", "Convocation annulée (motif)"),
    "PASSAGE_CONSULTE": ("CONSULTATION", "Consultation du passage en classe supérieure (résultats annuels, décisions)"),
    "PASSAGE_CHOIX_ENREGISTRE": ("AJOUT", "Classe d'accueil (option de 8ème) saisie par la Direction des études à la place de l'élève"),
    "PASSAGE_EXECUTE": ("AJOUT", "Passage en classe supérieure exécuté (promus, redoublants, fin d'études inscrits dans l'année suivante)"),
    "PASSAGE_ANNULE": ("MODIFICATION", "Passage en classe supérieure annulé (motif ; l'inscription de l'année suivante est retirée)"),
    "PASSAGE_EXPORTE": ("IMPRESSION", "Exportation (CSV) de la liste de passage d'une classe"),
    "PASSAGE_IMPRIME": ("IMPRESSION", "Impression de la liste de passage d'une classe"),
    # --- préfecture
    "PREFECTURE_TABLEAU_OUVERT": ("CONSULTATION", "Ouverture du tableau de bord de la Préfecture"),
    "PREFECTURE_DOSSIER_CONSULTE": ("CONSULTATION", "Consultation du dossier d'un élève (Préfecture)"),
    "PREFECTURE_FINANCES_CONSULTEES": ("CONSULTATION", "Consultation de la situation financière des élèves (Préfecture)"),
    "PREFECTURE_FINANCE_ELEVE_CONSULTEE": ("CONSULTATION", "Consultation de la situation financière d'un élève (Préfecture)"),
    "PREFECTURE_DISCIPLINE_CONSULTEE": ("CONSULTATION", "Consultation de la discipline (Préfecture)"),
    "PREFECTURE_DISCIPLINE_ELEVE_CONSULTEE": ("CONSULTATION", "Consultation de la discipline d'un élève (Préfecture)"),
    "PREFECTURE_ETUDES_CONSULTEES": ("CONSULTATION", "Consultation des études : notes, résultats, horaires (Préfecture)"),
    "PREFECTURE_BULLETIN_CONSULTE": ("CONSULTATION", "Consultation du bulletin d'un élève (Préfecture)"),
    "PREFECTURE_RAPPORTS_CONSULTES": ("CONSULTATION", "Consultation des rapports reçus des directions (Préfecture)"),
    "PREFECTURE_DECISION_ENREGISTREE": ("AJOUT", "Décision du Préfet enregistrée (numéro attribué)"),
    "PREFECTURE_DECISION_ANNULEE": ("SUPPRESSION", "Décision du Préfet annulée"),
    "RAPPORT_ENVOYE_AU_PREFET": ("AJOUT", "Rapport envoyé au Préfet par une direction"),
    # --- application des parents
    "CODE_PARENT_GENERE": ("SECURITE", "Code d'accès à l'application des parents généré (paiement du frais)"),
    "PARENT_COMPTE_CREE": ("AJOUT", "Compte parent créé dans l'application des parents"),
    "PARENT_ENFANT_AJOUTE": ("MODIFICATION", "Enfant ajouté au compte d'un parent"),
    "PARENT_CONNEXION": ("CONNEXION", "Connexion d'un parent à l'application des parents"),
    "PARENT_MDP_CHANGE": ("SECURITE", "Changement de mot de passe d'un parent"),
    "PARENT_COMPTE_BLOQUE": ("SECURITE", "Compte parent bloqué (trop d'essais)"),
    "PARENT_CONVOCATION_LUE": ("CONSULTATION", "Convocation lue par le parent"),
    # --- sécurité et administration
    "MDP_CHANGE": ("SECURITE", "Changement de mot de passe"),
    "MDP_CHANGEMENT_REFUSE": ("SECURITE", "Changement de mot de passe refusé"),
    "MDP_REINITIALISE": ("SECURITE", "Nouveau mot de passe provisoire donné à un compte"),
    "MDP_RECUPERE": ("SECURITE", "Mot de passe récupéré avec un code"),
    "COMPTE_DEBLOQUE": ("SECURITE", "Déblocage d'un compte"),
    "CODE_RECUP_GENERE": ("SECURITE", "Code de récupération généré"),
    "CODE_RECUP_ANNULE": ("SECURITE", "Code de récupération annulé"),
    "CODE_RECUP_EXPIRE": ("SECURITE", "Code de récupération expiré"),
    "CODE_RECUP_DETRUIT": ("SECURITE", "Code de récupération détruit (trop d'essais)"),
    "CODE_RECUP_ECHEC": ("SECURITE", "Code de récupération incorrect"),
    "CODE_RECUP_UTILISE": ("SECURITE", "Code de récupération utilisé"),
    "RESTAURATION_EFFECTUEE": ("SECURITE", "Restauration d'une sauvegarde"),
    "APPLICATION_REINITIALISEE": ("SECURITE", "Réinitialisation de l'application"),
    "REINITIALISATION_REFUSEE": ("SECURITE", "Réinitialisation refusée"),
    "DONNEES_ESSAI_AJOUTEES": ("SECURITE", "Installation des données d'essai"),
    "DONNEES_ESSAI_SUPPRIMEES": ("SECURITE", "Suppression des données d'essai"),
    "DONNEES_ESSAI_REFUSEES": ("SECURITE", "Suppression des données d'essai refusée"),
    "MISE_A_JOUR_PROGRAMME": ("SECURITE", "Mise à jour du programme"),
    "MISE_A_JOUR_REFUSEE": ("SECURITE", "Mise à jour du programme refusée"),
    "MISE_A_JOUR_ECHEC": ("SECURITE", "Mise à jour du programme échouée (version précédente remise)"),
    "RETOUR_ANCIENNE_VERSION": ("SECURITE", "Retour à une ancienne version du programme"),
    "STRUCTURE_MISE_A_JOUR": ("SECURITE", "Mise à jour de la structure de la base"),
    "INTEGRITE_VERIFIEE": ("SECURITE", "Vérification de l'intégrité de la base"),
    "AUDIT_CONTROLE": ("SECURITE", "Contrôle du journal et de la concordance"),
}

# Actions qui concernent l'argent des frais scolaires (filtre « opérations financières seulement »)
ACTIONS_FINANCIERES = frozenset({
    "PAIEMENT_ENREGISTRE", "PAIEMENT_ANNULE", "RECU_IMPRIME", "DUPLICATA_IMPRIME", "RAPPORT_CAISSE_IMPRIME",
    "RAPPORT_GLOBAL_IMPRIME", "ENCAISSEMENT_ENREGISTRE", "ENCAISSEMENT_MODIFIE", "ENCAISSEMENT_SUPPRIME", "TARIF_FIGE",
    "AUDIT_FINANCIER_CONSULTE", "AUDIT_CONTROLE_FINANCIER",
})


def categorie_de(action) -> str:
    return ACTIONS.get(action, ("AUTRE", ""))[0]


def libelle_action(action) -> str:
    """Libellé lisible ; pour un code inconnu (version future du programme), le code lui-même est affiché."""
    return ACTIONS[action][1] if action in ACTIONS else action


# ================================================================== outils
def _verifier_periode(du, au):
    for jour in (du, au):
        if jour is not None and (not isinstance(jour, date) or isinstance(jour, datetime)):
            raise ErreurAudit("Date invalide.")
    if du and au and du > au:
        raise ErreurAudit("La date de début ne peut pas être après la date de fin.")


def _local(texte_iso) -> datetime:
    """Date/heure stockée en UTC -> heure locale (sans fuseau), pour l'affichage."""
    return lire_iso(texte_iso).astimezone().replace(tzinfo=None)


def _noms_utilisateurs(conn) -> dict:
    """{identifiant en minuscules: nom complet}."""
    return {l["LOGIN"].lower(): l["NOM_COMPLET"] for l in conn.execute("SELECT LOGIN, NOM_COMPLET FROM UTILISATEUR")}


def _like(texte) -> str:
    return "%" + texte.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _bornes(du, au):
    return (_bornes_utc(du)[0] if du else None), (_bornes_utc(au)[1] if au else None)


def _dans(texte_iso, debut, fin) -> bool:
    return (debut is None or texte_iso >= debut) and (fin is None or texte_iso < fin)


def _etiquette_ecart(ecart) -> str:
    return "manquant" if ecart > 0 else ("excédent" if ecart < 0 else "aucun écart")


def _montant(centimes, devise="") -> str:
    return f"{argent.formater(centimes)} {devise}".strip()


# ================================================================== 1) journal des activités
def liste_utilisateurs(conn, session) -> list:
    """[(identifiant, nom complet)] : les comptes actuels puis les identifiants qui n'apparaissent que dans le journal
    (tentatives de connexion avec un identifiant inconnu, ancien compte...)."""
    exiger(conn, session)
    noms = _noms_utilisateurs(conn)
    resultat = {}
    for l in conn.execute("SELECT LOGIN FROM UTILISATEUR ORDER BY LOGIN COLLATE NOCASE"):
        resultat[l["LOGIN"].lower()] = (l["LOGIN"], noms.get(l["LOGIN"].lower(), ""))
    for l in conn.execute("SELECT DISTINCT LOGIN FROM JOURNAL WHERE LOGIN IS NOT NULL AND LOGIN <> ''"):
        resultat.setdefault(l["LOGIN"].lower(), (l["LOGIN"], noms.get(l["LOGIN"].lower(), "")))
    return sorted(resultat.values(), key=lambda x: x[0].lower())


def _conditions_journal(du, au, login, categorie, financier_seul):
    cond, params = [], []
    debut, fin = _bornes(du, au)
    if debut:
        cond.append("J.DATE_HEURE >= ?")
        params.append(debut)
    if fin:
        cond.append("J.DATE_HEURE < ?")
        params.append(fin)
    if login:
        cond.append("J.LOGIN = ? COLLATE NOCASE")
        params.append(login)
    if categorie:
        if categorie not in CATEGORIES:
            raise ErreurAudit("Catégorie inconnue.")
        if categorie == "AUTRE":
            connus = list(ACTIONS)
            cond.append(f"J.ACTION NOT IN ({','.join('?' * len(connus))})")
            params += connus
        else:
            codes = [c for c, (cat, _l) in ACTIONS.items() if cat == categorie]
            cond.append(f"J.ACTION IN ({','.join('?' * len(codes))})")
            params += codes
    if financier_seul:
        codes = sorted(ACTIONS_FINANCIERES)
        cond.append(f"J.ACTION IN ({','.join('?' * len(codes))})")
        params += codes
    return cond, params


def _ligne_journal(l, noms, roles) -> dict:
    quand = _local(l["DATE_HEURE"])
    action = l["ACTION"]
    login = l["LOGIN"] or ""
    role = l["ROLE"]
    return {
        "id": l["ID_LOG"], "quand": quand, "date_txt": quand.strftime("%d/%m/%Y  %H:%M:%S"),
        "login": login, "nom": l["NOM_COMPLET"] or noms.get(login.lower(), ""),
        "poste": roles.get(role, role or ""),
        "action": action, "libelle": libelle_action(action), "categorie": categorie_de(action),
        "categorie_txt": CATEGORIES[categorie_de(action)], "detail": l["DETAIL"] or "",
        "financier": action in ACTIONS_FINANCIERES,
    }


def journal(conn, session, du=None, au=None, login=None, categorie=None, texte=None, financier_seul=False,
            limite=LIMITE_LIGNES) -> dict:
    """Journal des activités, de la plus récente à la plus ancienne.
    `du` / `au` : dates (incluses) ; `login` : un utilisateur ; `categorie` : clé de CATEGORIES ; `texte` : mot cherché
    dans l'action, l'identifiant, le nom et le détail (sans tenir compte des accents ni de la casse) ;
    `limite` : nombre de lignes retournées (None = toutes). `total` donne toujours le nombre de lignes trouvées."""
    exiger(conn, session)
    _verifier_periode(du, au)
    cond, params = _conditions_journal(du, au, login and login.strip(), categorie, financier_seul)
    sql = ("SELECT J.ID_LOG, J.DATE_HEURE, J.LOGIN, J.ACTION, J.DETAIL, U.NOM_COMPLET, U.ROLE "
           "FROM JOURNAL J LEFT JOIN UTILISATEUR U ON U.ID_USER = J.ID_USER "
           + ("WHERE " + " AND ".join(cond) + " " if cond else "") + "ORDER BY J.ID_LOG DESC")
    noms = _noms_utilisateurs(conn)
    roles = droits.roles(conn)                 # {code du poste: libellé}
    texte = " ".join((texte or "").split())
    if texte:
        # le texte est cherché en Python : insensible aux accents (« déconnexion » trouve « DECONNEXION »)
        fragments = [donnees.sans_accents(f) for f in texte.split()]
        lignes = []
        for l in conn.execute(sql, params):
            ligne = _ligne_journal(l, noms, roles)
            cible = donnees.sans_accents(" ".join((ligne["action"], ligne["libelle"], ligne["login"], ligne["nom"],
                                                   ligne["detail"])))
            if all(f in cible for f in fragments):
                lignes.append(ligne)
        total = len(lignes)
        if limite is not None:
            lignes = lignes[:limite]
    else:
        total = conn.execute("SELECT COUNT(*) FROM JOURNAL J " + ("WHERE " + " AND ".join(cond) if cond else ""),
                             params).fetchone()[0]
        lignes = [_ligne_journal(l, noms, roles)
                  for l in conn.execute(sql + (" LIMIT ?" if limite is not None else ""),
                                        params + ([limite] if limite is not None else []))]
    return {"lignes": lignes, "total": total, "du": du, "au": au, "login": login or "", "categorie": categorie or "",
            "texte": texte, "financier_seul": bool(financier_seul),
            "genere_le": datetime.now().strftime("%d/%m/%Y à %H:%M")}


# ================================================================== 2) historique des opérations financières
TYPES_OPERATION = {
    "PAIEMENT": "Paiement enregistré",
    "ANNULATION": "Annulation de paiement",
    "ENCAISSEMENT": "Encaissement et remise des fonds",
    "ENC_MODIFIE": "Encaissement modifié",
    "ENC_SUPPRIME": "Encaissement supprimé",
    "RECU_IMPRIME": "Reçu imprimé",
    "DUPLICATA": "Duplicata imprimé",
}
_RE_ENCAISSEMENT = re.compile(r"N°(\d+)")


def _chercher_matricules(conn, terme) -> set:
    """Matricules des élèves dont le matricule ou le nom correspond (élèves désactivés compris : un audit doit
    pouvoir retrouver tous les paiements)."""
    terme = " ".join((terme or "").split())
    exact = conn.execute("SELECT MATRICULE FROM ELEVE WHERE MATRICULE = ? COLLATE NOCASE", (terme,)).fetchall()
    if exact:
        return {l["MATRICULE"] for l in exact}
    fragments = [donnees.sans_accents(f) for f in terme.split()]
    trouves = set()
    for l in conn.execute("SELECT MATRICULE, NOM, POSTNOM, PRENOM FROM ELEVE"):
        cible = donnees.sans_accents(f"{l['MATRICULE']} {l['NOM']} {l['POSTNOM'] or ''} {l['PRENOM'] or ''}")
        if all(f in cible for f in fragments):
            trouves.add(l["MATRICULE"])
    return trouves


def _variantes_recu(texte) -> set:
    """« 12 » -> {'12', '0012'} : les reçus sont numérotés 0001, 0002..."""
    texte = (texte or "").strip()
    variantes = {texte}
    if texte.isdigit():
        variantes.add(texte.zfill(4))
    return variantes


def _enregistreurs(conn) -> dict:
    """{n° de reçu: identifiant du compte qui l'a enregistré}, d'après le journal."""
    resultat = {}
    for l in conn.execute("SELECT LOGIN, DETAIL FROM JOURNAL WHERE ACTION = 'PAIEMENT_ENREGISTRE' ORDER BY ID_LOG"):
        resultat[(l["DETAIL"] or "").split(" | ", 1)[0]] = l["LOGIN"] or ""
    return resultat


def _info_recu(conn, n_recu, cache):
    if n_recu not in cache:
        cache[n_recu] = conn.execute(
            "SELECT P.N_RECU, P.MATRICULE, P.NOM_PAYEUR, P.MONT_PAYE, P.CODE_DEVISE, P.ANNEESCO, E.NOM, E.POSTNOM, E.PRENOM, "
            "F.DESITF FROM PAIEMENT P LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE "
            "JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF WHERE P.N_RECU = ?", (n_recu,)).fetchone()
    return cache[n_recu]


def _operation(quand_iso, type_op, reference, par_login, noms, **plus) -> dict:
    quand = _local(quand_iso)
    base = {"quand": quand, "date_txt": quand.strftime("%d/%m/%Y  %H:%M"), "type": type_op,
            "type_txt": TYPES_OPERATION[type_op], "reference": reference, "matricule": "", "eleve": "", "detail": "",
            "montant": None, "verse": None, "ecart": None, "devise": "", "statut": "",
            "par_login": par_login or "", "par_nom": noms.get((par_login or "").lower(), "")}
    base.update(plus)
    base["montant_txt"] = argent.formater(base["montant"]) if base["montant"] is not None else ""
    base["verse_txt"] = argent.formater(base["verse"]) if base["verse"] is not None else ""
    base["ecart_txt"] = argent.formater(base["ecart"]) if base["ecart"] is not None else ""
    return base


def historique_financier(conn, session, du=None, au=None, eleve=None, n_recu=None, login=None, type_op=None,
                         ecart_seul=False, limite=LIMITE_LIGNES, journaliser_recherche=True) -> dict:
    """Historique des opérations liées aux frais scolaires, de la plus récente à la plus ancienne.

    Filtres : `eleve` (matricule ou fragment du nom), `n_recu`, `login` (utilisateur qui a fait l'opération),
    `type_op` (clé de TYPES_OPERATION), `du` / `au`, `ecart_seul` (encaissements avec un écart seulement).
    Chaque opération porte l'utilisateur qui l'a faite (`par_login`, `par_nom`). `totaux` : par devise, les paiements,
    annulations, montants encaissés, versés et écarts des lignes trouvées."""
    exiger(conn, session)
    _verifier_periode(du, au)
    if type_op and type_op not in TYPES_OPERATION:
        raise ErreurAudit("Type d'opération inconnu.")
    eleve = " ".join((eleve or "").split())
    n_recu = (n_recu or "").strip()
    login = (login or "").strip()
    matricules = None
    if eleve:
        matricules = _chercher_matricules(conn, eleve)
        if not matricules:
            raise ErreurAudit(f"Aucun élève trouvé pour « {eleve} ».")
    variantes = _variantes_recu(n_recu) if n_recu else None
    debut, fin = _bornes(du, au)
    noms = _noms_utilisateurs(conn)
    ciblee = bool(eleve or n_recu)                      # recherche sur une personne ou un reçu : inscrite au journal
    operations = []

    # ---- paiements et annulations (table PAIEMENT)
    cond, params = [], []
    if variantes:
        cond.append(f"P.N_RECU IN ({','.join('?' * len(variantes))})")
        params += sorted(variantes)
    if matricules is not None:
        cond.append(f"P.MATRICULE IN ({','.join('?' * len(matricules))})")
        params += sorted(matricules)
    if debut or fin:
        sous, p2 = [], []
        for colonne in ("P.DATE_PAY", "P.DATE_ANNULATION"):
            bloc = []
            if debut:
                bloc.append(f"{colonne} >= ?")
                p2.append(debut)
            if fin:
                bloc.append(f"{colonne} < ?")
                p2.append(fin)
            sous.append("(" + " AND ".join(bloc) + ")")
        cond.append("(" + " OR ".join(sous) + ")")
        params += p2
    enregistreurs = _enregistreurs(conn)
    for p in conn.execute(
            "SELECT P.N_RECU, P.DATE_PAY, P.MATRICULE, P.ANNEESCO, P.MONT_PAYE, P.CODE_DEVISE, P.STATUT, "
            "P.MOTIF_ANNULATION, P.DATE_ANNULATION, P.ANNULE_PAR, P.NOM_PAYEUR, E.NOM, E.POSTNOM, E.PRENOM, C.DESI_CLASSE, "
            "F.DESITF, U.LOGIN AS PERC_LOGIN, U.NOM_COMPLET AS PERC_NOM "
            "FROM PAIEMENT P LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE "
            "JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF JOIN PERCEPTEUR R ON R.N_PERC = P.N_PERC "
            "JOIN UTILISATEUR U ON U.ID_USER = R.ID_USER "
            + ("WHERE " + " AND ".join(cond) + " " if cond else "") + "ORDER BY P.DATE_PAY", params).fetchall():
        nom_eleve = donnees.nom_complet(p) if p["NOM"] else f"{p['NOM_PAYEUR']} (candidat)"
        commun = {"matricule": p["MATRICULE"] or "", "eleve": nom_eleve, "montant": p["MONT_PAYE"],
                  "devise": p["CODE_DEVISE"]}
        if _dans(p["DATE_PAY"], debut, fin):
            operations.append(_operation(
                p["DATE_PAY"], "PAIEMENT", p["N_RECU"], enregistreurs.get(p["N_RECU"]) or p["PERC_LOGIN"], noms,
                detail=f"{p['DESITF']} | {p['DESI_CLASSE']} ({p['ANNEESCO']}) | Percepteur : {p['PERC_NOM']}",
                statut="Valide" if p["STATUT"] == "VALIDE" else "Annulé", **commun))
        if p["STATUT"] == "ANNULE" and p["DATE_ANNULATION"] and _dans(p["DATE_ANNULATION"], debut, fin):
            operations.append(_operation(
                p["DATE_ANNULATION"], "ANNULATION", p["N_RECU"], p["ANNULE_PAR"], noms,
                detail=f"Motif : {p['MOTIF_ANNULATION'] or '—'} | {p['DESITF']} | reçu du "
                       f"{_local(p['DATE_PAY']).strftime('%d/%m/%Y')} enregistré par "
                       f"{enregistreurs.get(p['N_RECU']) or p['PERC_LOGIN']}",
                statut="Annulé", **commun))

    # ---- encaissements et remises de fonds (table ENCAISSEMENT) : sans objet pour une recherche sur un élève / un reçu
    if not ciblee:
        cond, params = [], []
        if debut:
            cond.append("N.DATE_SAISIE >= ?")
            params.append(debut)
        if fin:
            cond.append("N.DATE_SAISIE < ?")
            params.append(fin)
        for n in conn.execute(
                "SELECT N.N_ENC, N.DATE_ENC, N.DATE_SAISIE, N.CODE_DEVISE, N.MONT_ENCAISSE, N.MONT_VERSE, N.ECART, "
                "N.SAISI_PAR, U.NOM_COMPLET AS PERC_NOM FROM ENCAISSEMENT N "
                "JOIN PERCEPTEUR R ON R.N_PERC = N.N_PERC JOIN UTILISATEUR U ON U.ID_USER = R.ID_USER "
                + ("WHERE " + " AND ".join(cond) + " " if cond else "") + "ORDER BY N.DATE_SAISIE", params):
            operations.append(_operation(
                n["DATE_SAISIE"], "ENCAISSEMENT", f"ENC-{n['N_ENC']}", n["SAISI_PAR"], noms,
                detail=f"Percepteur : {n['PERC_NOM']} | Journée du "
                       f"{date.fromisoformat(n['DATE_ENC']).strftime('%d/%m/%Y')} | "
                       f"{_etiquette_ecart(n['ECART'])}",
                montant=n["MONT_ENCAISSE"], verse=n["MONT_VERSE"], ecart=n["ECART"], devise=n["CODE_DEVISE"],
                statut="Enregistré"))

    # ---- événements du journal : encaissements modifiés / supprimés, reçus et duplicata imprimés
    cond = ["J.ACTION IN ('ENCAISSEMENT_MODIFIE','ENCAISSEMENT_SUPPRIME','RECU_IMPRIME','DUPLICATA_IMPRIME')"]
    params = []
    if debut:
        cond.append("J.DATE_HEURE >= ?")
        params.append(debut)
    if fin:
        cond.append("J.DATE_HEURE < ?")
        params.append(fin)
    cache = {}
    for j in conn.execute("SELECT J.DATE_HEURE, J.LOGIN, J.ACTION, J.DETAIL FROM JOURNAL J WHERE "
                          + " AND ".join(cond) + " ORDER BY J.ID_LOG", params):
        detail = j["DETAIL"] or ""
        if j["ACTION"] in ("RECU_IMPRIME", "DUPLICATA_IMPRIME"):
            info = _info_recu(conn, detail, cache)
            if info is None or (variantes and detail not in variantes) or \
                    (matricules is not None and info["MATRICULE"] not in matricules):
                continue
            operations.append(_operation(
                j["DATE_HEURE"], "RECU_IMPRIME" if j["ACTION"] == "RECU_IMPRIME" else "DUPLICATA", detail, j["LOGIN"],
                noms, matricule=info["MATRICULE"] or "",
                eleve=donnees.nom_complet(info) if info["NOM"] else f"{info['NOM_PAYEUR']} (candidat)",
                detail=f"{info['DESITF']} ({info['ANNEESCO']})", montant=info["MONT_PAYE"], devise=info["CODE_DEVISE"],
                statut="Imprimé"))
        elif not ciblee:
            m = _RE_ENCAISSEMENT.search(detail)
            operations.append(_operation(
                j["DATE_HEURE"], "ENC_MODIFIE" if j["ACTION"] == "ENCAISSEMENT_MODIFIE" else "ENC_SUPPRIME",
                f"ENC-{m.group(1)}" if m else "ENC-?", j["LOGIN"], noms, detail=detail[:600],
                statut="Modifié" if j["ACTION"] == "ENCAISSEMENT_MODIFIE" else "Supprimé"))

    # ---- filtres communs puis tri
    if login:
        operations = [o for o in operations if o["par_login"].lower() == login.lower()]
    if type_op:
        operations = [o for o in operations if o["type"] == type_op]
    if ecart_seul:
        operations = [o for o in operations if o["type"] == "ENCAISSEMENT" and o["ecart"]]
    operations.sort(key=lambda o: (o["quand"], o["reference"]), reverse=True)

    totaux = {}
    for o in operations:
        if not o["devise"] or o["type"] not in ("PAIEMENT", "ANNULATION", "ENCAISSEMENT"):
            continue
        t = totaux.setdefault(o["devise"], {"devise": o["devise"], "paiements_nb": 0, "paiements": 0, "annulations_nb": 0,
                                            "annulations": 0, "encaissements_nb": 0, "encaisse": 0, "verse": 0,
                                            "ecart": 0})
        if o["type"] == "PAIEMENT":
            t["paiements_nb"] += 1
            t["paiements"] += o["montant"]
        elif o["type"] == "ANNULATION":
            t["annulations_nb"] += 1
            t["annulations"] += o["montant"]
        else:
            t["encaissements_nb"] += 1
            t["encaisse"] += o["montant"]
            t["verse"] += o["verse"]
            t["ecart"] += o["ecart"]
    for t in totaux.values():
        t["net"] = t["paiements"] - t["annulations"]

    if ciblee and journaliser_recherche:
        with conn:
            journaliser(conn, session.id_user, session.login, "AUDIT_FINANCIER_CONSULTE",
                        " | ".join(x for x in (f"élève : {eleve}" if eleve else "", f"reçu : {n_recu}" if n_recu else "",
                                               f"{len(operations)} opération(s)") if x))
    total = len(operations)
    return {"operations": operations if limite is None else operations[:limite], "total": total,
            "totaux": [totaux[d] for d in sorted(totaux)], "du": du, "au": au, "eleve": eleve, "n_recu": n_recu,
            "login": login, "type_op": type_op or "", "ecart_seul": bool(ecart_seul),
            "genere_le": datetime.now().strftime("%d/%m/%Y à %H:%M")}


def trace_operation(conn, session, reference) -> dict:
    """Fiche complète d'une opération : un reçu (N° de reçu) ou un encaissement (ENC-n), avec TOUS les événements du
    journal qui s'y rapportent (enregistrement, impressions, annulation, modifications...).
    Retourne {"titre", "champs": [(libellé, valeur)], "evenements": [lignes du journal]}."""
    exiger(conn, session)
    reference = (reference or "").strip()
    noms = _noms_utilisateurs(conn)
    if reference.upper().startswith("ENC-"):
        return _trace_encaissement(conn, reference, noms)
    p = conn.execute(
        "SELECT P.*, E.NOM, E.POSTNOM, E.PRENOM, C.DESI_CLASSE, F.DESITF, U.LOGIN AS PERC_LOGIN, "
        "U.NOM_COMPLET AS PERC_NOM FROM PAIEMENT P LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE "
        "JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
        "JOIN PERCEPTEUR R ON R.N_PERC = P.N_PERC JOIN UTILISATEUR U ON U.ID_USER = R.ID_USER "
        "WHERE P.N_RECU = ?", (reference,)).fetchone()
    if not p:
        raise ErreurAudit("Opération introuvable.")
    evenements = []
    for j in conn.execute("SELECT ID_LOG, DATE_HEURE, LOGIN, ACTION, DETAIL FROM JOURNAL WHERE ACTION IN "
                          "('PAIEMENT_ENREGISTRE','PAIEMENT_ANNULE','RECU_IMPRIME','DUPLICATA_IMPRIME') ORDER BY ID_LOG"):
        detail = j["DETAIL"] or ""
        if detail == reference or detail.startswith(reference + " | "):
            evenements.append(_evenement(j, noms))
    enreg = next((e["login"] for e in evenements if e["action"] == "PAIEMENT_ENREGISTRE"), "")
    champs = [
        ("N° de reçu", p["N_RECU"]),
        ("Élève", f"{donnees.nom_complet(p)}  (matricule {p['MATRICULE']})" if p["MATRICULE"]
                   else f"{p['NOM_PAYEUR']}  (candidat, pas encore élève)"),
        ("Classe / année", f"{p['DESI_CLASSE']}  -  {p['ANNEESCO']}"),
        ("Type de frais", p["DESITF"]),
        ("Montant payé", _montant(p["MONT_PAYE"], p["CODE_DEVISE"])),
        ("Date et heure du paiement", _local(p["DATE_PAY"]).strftime("%d/%m/%Y  %H:%M:%S")),
        ("Percepteur du reçu", f"{p['PERC_NOM']}  ({p['PERC_LOGIN']})"),
        ("Enregistré par (journal)", _qui(enreg, noms) if enreg else "Aucune trace au journal"),
        ("Statut", "Valide" if p["STATUT"] == "VALIDE" else "ANNULÉ"),
    ]
    if p["STATUT"] == "ANNULE":
        champs += [("Annulé par", _qui(p["ANNULE_PAR"], noms)),
                   ("Date de l'annulation", _local(p["DATE_ANNULATION"]).strftime("%d/%m/%Y  %H:%M:%S")
                    if p["DATE_ANNULATION"] else "—"),
                   ("Motif de l'annulation", p["MOTIF_ANNULATION"] or "—")]
    return {"titre": f"Reçu N° {p['N_RECU']}", "champs": champs, "evenements": evenements}


def _qui(login, noms) -> str:
    nom = noms.get((login or "").lower(), "")
    return f"{nom}  ({login})" if nom else (login or "—")


def _evenement(j, noms) -> dict:
    quand = _local(j["DATE_HEURE"])
    return {"id": j["ID_LOG"], "quand": quand, "date_txt": quand.strftime("%d/%m/%Y  %H:%M:%S"),
            "login": j["LOGIN"] or "", "nom": noms.get((j["LOGIN"] or "").lower(), ""), "action": j["ACTION"],
            "libelle": libelle_action(j["ACTION"]), "detail": j["DETAIL"] or ""}


def _trace_encaissement(conn, reference, noms) -> dict:
    texte = reference[4:]
    if not texte.isdigit():
        raise ErreurAudit("Opération introuvable.")
    n_enc = int(texte)
    evenements = []
    for j in conn.execute("SELECT ID_LOG, DATE_HEURE, LOGIN, ACTION, DETAIL FROM JOURNAL WHERE ACTION IN "
                          "('ENCAISSEMENT_ENREGISTRE','ENCAISSEMENT_MODIFIE','ENCAISSEMENT_SUPPRIME') ORDER BY ID_LOG"):
        detail = j["DETAIL"] or ""
        if detail.startswith(f"N°{n_enc} |") or f"avant : N°{n_enc} |" in detail:
            evenements.append(_evenement(j, noms))
    n = conn.execute(
        "SELECT N.*, U.NOM_COMPLET AS PERC_NOM, U.LOGIN AS PERC_LOGIN FROM ENCAISSEMENT N "
        "JOIN PERCEPTEUR R ON R.N_PERC = N.N_PERC JOIN UTILISATEUR U ON U.ID_USER = R.ID_USER "
        "WHERE N.N_ENC = ?", (n_enc,)).fetchone()
    if not n and not evenements:
        raise ErreurAudit("Opération introuvable.")
    if not n:                                    # encaissement supprimé : il ne reste que le journal
        return {"titre": f"Encaissement ENC-{n_enc} (supprimé)",
                "champs": [("État", "Cet encaissement a été supprimé : seules les traces du journal subsistent.")],
                "evenements": evenements}
    jour = date.fromisoformat(n["DATE_ENC"])
    debut, fin = _bornes_utc(jour)
    recus = conn.execute(
        "SELECT COUNT(*) AS NB, COALESCE(SUM(P.MONT_PAYE), 0) AS TOTAL FROM PAIEMENT P "
        "WHERE P.N_PERC = ? AND P.CODE_DEVISE = ? AND P.STATUT = 'VALIDE' AND P.DATE_PAY >= ? AND P.DATE_PAY < ?",
        (n["N_PERC"], n["CODE_DEVISE"], debut, fin)).fetchone()
    champs = [
        ("Référence", f"ENC-{n['N_ENC']}"),
        ("Percepteur", f"{n['PERC_NOM']}  ({n['PERC_LOGIN']})"),
        ("Journée encaissée", jour.strftime("%d/%m/%Y")),
        ("Montant encaissé", _montant(n["MONT_ENCAISSE"], n["CODE_DEVISE"])),
        ("Montant versé (remise des fonds)", _montant(n["MONT_VERSE"], n["CODE_DEVISE"])),
        ("Écart (encaissé - versé)", f"{_montant(n['ECART'], n['CODE_DEVISE'])}  ({_etiquette_ecart(n['ECART'])})"),
        ("Reçus valides du percepteur ce jour-là",
         f"{recus['NB']} reçu(s) pour {_montant(recus['TOTAL'], n['CODE_DEVISE'])}"),
        ("Enregistré par", _qui(n["SAISI_PAR"], noms)),
        ("Enregistré le", _local(n["DATE_SAISIE"]).strftime("%d/%m/%Y  %H:%M:%S")),
    ]
    return {"titre": f"Encaissement ENC-{n['N_ENC']}", "champs": champs, "evenements": evenements}


# ================================================================== 3) contrôles
def etat_journal(conn) -> dict:
    """Nombre de lignes, période couverte, dernière empreinte et résultat du contrôle de la chaîne. Sans droit requis :
    sert aussi à l'en-tête des exports (la dernière empreinte permet de prouver, plus tard, que le journal n'a pas
    été réécrit)."""
    import database
    ok, id_log = database.verifier_journal(conn)
    ligne = conn.execute("SELECT COUNT(*) AS N, MIN(DATE_HEURE) AS DEBUT, MAX(DATE_HEURE) AS FIN FROM JOURNAL").fetchone()
    derniere = conn.execute("SELECT EMPREINTE FROM JOURNAL ORDER BY ID_LOG DESC LIMIT 1").fetchone()
    return {"ok": ok, "anomalie": id_log, "nb_lignes": ligne["N"],
            "debut": _local(ligne["DEBUT"]).strftime("%d/%m/%Y %H:%M") if ligne["DEBUT"] else "",
            "fin": _local(ligne["FIN"]).strftime("%d/%m/%Y %H:%M") if ligne["FIN"] else "",
            "derniere_empreinte": derniere["EMPREINTE"] if derniere else database.EMPREINTE_INITIALE}


def controle_journal(conn, session) -> dict:
    """Vérifie que personne n'a modifié le journal (chaîne d'empreintes). Inscrit au journal."""
    exiger(conn, session)
    etat = etat_journal(conn)
    with conn:
        journaliser(conn, session.id_user, session.login, "AUDIT_CONTROLE",
                    f"chaîne d'empreintes : {'OK' if etat['ok'] else 'ANOMALIE ligne ' + str(etat['anomalie'])} | "
                    f"{etat['nb_lignes']} ligne(s)")
    return etat


def controle_concordance(conn, session) -> list:
    """Compare le journal et les tables financières. Retourne une liste d'anomalies [{"gravite", "message"}] (liste
    vide : tout concorde). Une anomalie ne prouve pas une fraude : elle indique où regarder."""
    exiger(conn, session)
    anomalies = []

    def signaler(gravite, message):
        anomalies.append({"gravite": gravite, "message": message})

    enregistres = {}
    for l in conn.execute("SELECT LOGIN, DETAIL FROM JOURNAL WHERE ACTION = 'PAIEMENT_ENREGISTRE'"):
        enregistres[(l["DETAIL"] or "").split(" | ", 1)[0]] = l["LOGIN"]
    annules = {(l["DETAIL"] or "").split(" | ", 1)[0] for l in
               conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'PAIEMENT_ANNULE'")}
    for p in conn.execute("SELECT P.N_RECU, P.STATUT, P.NUM_SEQ, U.LOGIN AS PERC_LOGIN FROM PAIEMENT P "
                          "JOIN PERCEPTEUR R ON R.N_PERC = P.N_PERC JOIN UTILISATEUR U ON U.ID_USER = R.ID_USER "
                          "ORDER BY P.NUM_SEQ"):
        if p["N_RECU"] not in enregistres:
            signaler("ÉLEVÉE", f"Reçu {p['N_RECU']} : aucune trace de son enregistrement dans le journal.")
        elif enregistres[p["N_RECU"]].lower() != p["PERC_LOGIN"].lower():
            signaler("ÉLEVÉE", f"Reçu {p['N_RECU']} : le journal indique {enregistres[p['N_RECU']]} alors que le reçu "
                               f"porte le percepteur {p['PERC_LOGIN']}.")
        if p["STATUT"] == "ANNULE" and p["N_RECU"] not in annules:
            signaler("ÉLEVÉE", f"Reçu {p['N_RECU']} : annulé, mais aucune trace de l'annulation dans le journal.")
    # trous dans la numérotation continue des reçus (format 0001, 0002... ; les anciens numéros 2026-000001 sont ignorés)
    suite = [l["NUM_SEQ"] for l in conn.execute("SELECT NUM_SEQ FROM PAIEMENT WHERE N_RECU NOT GLOB '*[^0-9]*' "
                                                "ORDER BY NUM_SEQ")]
    if suite:
        manquants = sorted(set(range(suite[0], suite[-1] + 1)) - set(suite))
        if manquants:
            signaler("MOYENNE", "Numéros de reçu manquants dans la suite : "
                                + ", ".join(f"{n:04d}" for n in manquants[:15]) + ("…" if len(manquants) > 15 else "")
                                + ".")
    # encaissements
    traces = [l["DETAIL"] or "" for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'ENCAISSEMENT_ENREGISTRE'")]
    for n in conn.execute("SELECT N_ENC, MONT_ENCAISSE, MONT_VERSE, ECART FROM ENCAISSEMENT ORDER BY N_ENC"):
        if not any(t.startswith(f"N°{n['N_ENC']} |") for t in traces):
            signaler("ÉLEVÉE", f"Encaissement ENC-{n['N_ENC']} : aucune trace de son enregistrement dans le journal.")
        if n["MONT_ENCAISSE"] - n["MONT_VERSE"] != n["ECART"]:
            signaler("ÉLEVÉE", f"Encaissement ENC-{n['N_ENC']} : l'écart enregistré ({argent.formater(n['ECART'])}) ne "
                               f"correspond pas à encaissé - versé.")
    with conn:
        journaliser(conn, session.id_user, session.login, "AUDIT_CONTROLE",
                    f"concordance : {len(anomalies)} anomalie(s)")
    return anomalies


# ================================================================== exports (CSV et PDF)
COLONNES_JOURNAL = [("Date et heure", 112, "g"), ("Utilisateur", 78, "g"), ("Nom complet", 100, "g"),
                    ("Poste", 62, "g"), ("Catégorie", 88, "g"), ("Action", 125, "g"), ("Détail", 216.89, "g")]
COLONNES_FINANCES = [("Date et heure", 80, "g"), ("Opération", 92, "g"), ("Référence", 50, "g"), ("Élève", 100, "g"),
                     ("Détail", 190, "g"), ("Montant", 58, "d"), ("Versé", 52, "d"), ("Écart", 48, "d"),
                     ("Devise", 28, "g"), ("Utilisateur", 66, "g"), ("Statut", 17.89, "g")]


def _texte_filtre(valeur, libelle):
    return f"{libelle} : {valeur}" if valeur else ""


def _periode_txt(du, au) -> str:
    f = lambda d: d.strftime("%d/%m/%Y")
    if du and au:
        return f"du {f(du)} au {f(au)}"
    if du:
        return f"depuis le {f(du)}"
    if au:
        return f"jusqu'au {f(au)}"
    return "toutes les dates"


def _lignes_journal(r) -> list:
    return [[l["date_txt"], l["login"], l["nom"], l["poste"], l["categorie_txt"], l["libelle"], l["detail"]]
            for l in r["lignes"]]


def _lignes_finances(r) -> list:
    return [[o["date_txt"], o["type_txt"], o["reference"], o["eleve"] or "", o["detail"], o["montant_txt"],
             o["verse_txt"], o["ecart_txt"], o["devise"], o["par_login"], o["statut"]] for o in r["operations"]]


def _protege_csv(texte) -> str:
    """Un tableur exécute une cellule qui commence par = + - @ : on la neutralise (les textes viennent des utilisateurs)."""
    texte = "" if texte is None else str(texte)
    return "'" + texte if texte[:1] in ("=", "+", "-", "@", "\t", "\r") else texte


def _ecrire_csv(chemin, colonnes, lignes, numeriques=()):
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:        # utf-8-sig : accents corrects dans Excel
        w = csv.writer(f, delimiter=";")
        w.writerow([c[0] for c in colonnes])
        for ligne in lignes:
            w.writerow([c if i in numeriques else _protege_csv(c) for i, c in enumerate(ligne)])


def _nom_fichier(prefixe, extension) -> str:
    return f"{prefixe}_{maintenant().astimezone().strftime('%Y%m%d_%H%M%S')}.{extension}"


def exporter_journal(conn, session, format_, du=None, au=None, login=None, categorie=None, texte=None,
                     financier_seul=False) -> str:
    """Exporte TOUTES les lignes du journal qui répondent aux filtres, en CSV (tableur) ou PDF (impression).
    L'exportation est elle-même inscrite au journal. Retourne le chemin du fichier."""
    r = journal(conn, session, du, au, login, categorie, texte, financier_seul, limite=None)
    if not r["lignes"]:
        raise ErreurAudit("Aucune ligne à exporter avec ces filtres.")
    filtres = [f"Période : {_periode_txt(du, au)}", _texte_filtre(login, "Utilisateur"),
               _texte_filtre(CATEGORIES.get(categorie, ""), "Catégorie"), _texte_filtre(texte, "Texte"),
               "Opérations financières seulement" if financier_seul else ""]
    return _exporter(conn, session, "journal", format_, "Journal des activités", filtres, COLONNES_JOURNAL,
                     _lignes_journal(r), r["total"], numeriques=())


def exporter_historique(conn, session, format_, du=None, au=None, eleve=None, n_recu=None, login=None, type_op=None,
                        ecart_seul=False) -> str:
    """Exporte l'historique des opérations financières (toutes les lignes trouvées), en CSV ou PDF."""
    r = historique_financier(conn, session, du, au, eleve, n_recu, login, type_op, ecart_seul, limite=None,
                             journaliser_recherche=False)
    if not r["operations"]:
        raise ErreurAudit("Aucune opération à exporter avec ces filtres.")
    filtres = [f"Période : {_periode_txt(du, au)}", _texte_filtre(eleve, "Élève"), _texte_filtre(n_recu, "N° de reçu"),
               _texte_filtre(login, "Utilisateur"), _texte_filtre(TYPES_OPERATION.get(type_op, ""), "Opération"),
               "Écarts seulement" if ecart_seul else ""]
    totaux = [f"{t['devise']} :  paiements {argent.formater(t['paiements'])} ({t['paiements_nb']})  -  annulations "
              f"{argent.formater(t['annulations'])} ({t['annulations_nb']})  =  net {argent.formater(t['net'])}   |   "
              f"encaissé {argent.formater(t['encaisse'])}  -  versé {argent.formater(t['verse'])}  =  écart "
              f"{argent.formater(t['ecart'])}" for t in r["totaux"]]
    return _exporter(conn, session, "historique", format_, "Historique des opérations financières", filtres,
                     COLONNES_FINANCES, _lignes_finances(r), r["total"], supplement=totaux, numeriques=(5, 6, 7))


def _exporter(conn, session, nature, format_, titre, filtres, colonnes, lignes, total, supplement=(), numeriques=()):
    format_ = (format_ or "").lower()
    if format_ not in ("csv", "pdf"):
        raise ErreurAudit("Format d'exportation inconnu : choisissez CSV ou PDF.")
    config.DOSSIER_AUDIT.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_AUDIT / _nom_fichier(f"Audit_{nature}", format_))
    if format_ == "csv":
        _ecrire_csv(chemin, colonnes, lignes, numeriques)
    else:
        import audit_pdf
        etat = etat_journal(conn)
        audit_pdf.generer(
            titre, [f for f in filtres if f] + list(supplement), colonnes, lignes, chemin,
            config.DOSSIER_ASSETS / "logo_recu.jpg",
            pied=(f"Édité le {datetime.now().strftime('%d/%m/%Y à %H:%M')} par {session.nom_complet}  -  "
                  f"Journal : {etat['nb_lignes']} ligne(s), {'chaîne intacte' if etat['ok'] else 'ANOMALIE DÉTECTÉE'}, "
                  f"empreinte {etat['derniere_empreinte'][:16]}"))
    with conn:
        journaliser(conn, session.id_user, session.login, "AUDIT_EXPORTE",
                    f"{titre} | {format_.upper()} | {len(lignes)} ligne(s) | "
                    + " ; ".join(f for f in filtres if f)[:300])
    return chemin


def journaliser_ouverture(conn, session):
    """Inscrit l'ouverture du module au journal (appelé par l'écran)."""
    with conn:
        journaliser(conn, session.id_user, session.login, "AUDIT_OUVERT", "")
