"""Configuration générale de l'application."""
import os
from pathlib import Path

# ---------------------------------------------------------------- identité
# Nom de l'école imprimé sur les documents et affiché à l'écran : changez-le ici, ou définissez la variable d'environnement CSF_NOM_ECOLE.
NOM_ECOLE = (os.environ.get("CSF_NOM_ECOLE") or "NOM DE L'ÉCOLE").strip()
DEVISE_ECOLE = "DISCIPLINE  -  AMOUR  -  TRAVAIL"
SIGLE_APP = "GESTSCO"
NOM_APP = "SYSTÈME DE GESTION SCOLAIRE GESTSCO"
VERSION = "1.4"

# Identité imprimée sur le bulletin du primaire (modèle officiel) : à compléter, sinon les lignes restent à remplir à la main.
PROVINCE_BULLETIN = ""            # ex. "Kinshasa/Tshangu"
VILLE_BULLETIN = ""               # ex. "Kinshasa" (sert aussi de lieu pour « Fait à »)
COMMUNE_BULLETIN = ""             # ex. "Kimbanseke"
CODE_ECOLE_BULLETIN = ""          # code de l'école (8 cases), ex. "1-140111"

# ---------------------------------------------------------------- chemins
DOSSIER_APP = Path(__file__).resolve().parent
DOSSIER_ASSETS = DOSSIER_APP / "assets"


def url_publique() -> str:
    """Adresse du site de l'école (ex. https://csf.pythonanywhere.com), sans « / » final ; vide si non réglée (variable GESTISC_URL_PUBLIQUE).
    Elle sert à imprimer sur le reçu le lien de téléchargement de l'application des parents."""
    return os.environ.get("GESTISC_URL_PUBLIQUE", "").strip().rstrip("/")


def lien_externe_parents() -> str:
    """Lien de téléchargement ailleurs que sur ce serveur (ex. Google Play, variable GESTISC_LIEN_APPLI_PARENTS) ; vide : le fichier
    application_parents.apk du dossier des données est servi par /parents/telecharger."""
    return os.environ.get("GESTISC_LIEN_APPLI_PARENTS", "").strip()


def dossier_donnees() -> Path:
    """Dossier privé de l'utilisateur Windows (hors du dossier du programme)."""
    perso = os.environ.get("CSF_DATA_DIR")          # utilisé par les tests
    if perso:
        base = Path(perso)
    else:
        if os.name == "nt":
            racine = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        else:
            racine = Path.home() / ".local" / "share"
        base = racine / "GESTSCO"
        ancien = racine / "CollegeSainteFamille"      # dossier des versions précédentes : conservé tel quel pour ne perdre aucune donnée
        if ancien.exists() and not base.exists():
            base = ancien
    base.mkdir(parents=True, exist_ok=True)
    return base


FICHIER_BD = dossier_donnees() / "college.db"


def url_postgresql() -> str:
    """Adresse de la base PostgreSQL (variable GESTSCO_DATABASE_URL, ex. postgresql://gestsco:secret@localhost:5432/gestsco).
    Vide : l'application utilise le fichier SQLite (college.db), comme avant."""
    return (os.environ.get("GESTSCO_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()

# ---------------------------------------------------------------- postes (rôles)
ADMINISTRATEUR = "ADMINISTRATEUR"
ROLES = ("PREFET", "ADMINISTRATEUR", "SECRETAIRE", "INTENDANT", "PERCEPTEUR", "CONTROLEUR", "DIRECTRICE_ETUDES",
         "DIRECTEUR_DISCIPLINE")
LIBELLE_ROLES = {
    "PREFET": "Préfet",
    "ADMINISTRATEUR": "Administrateur",
    "SECRETAIRE": "Secrétaire",
    "INTENDANT": "Intendant",
    "PERCEPTEUR": "Percepteur",
    "CONTROLEUR": "Contrôleur",
    "DIRECTRICE_ETUDES": "Directrice des études",
    "DIRECTEUR_DISCIPLINE": "Directeur de discipline",
}
# Anciens noms de postes (versions 0.1 à 0.3) -> nouveaux postes. Sert uniquement à la mise à jour des tables.
ANCIENS_ROLES = {"DIRECTION": "ADMINISTRATEUR", "SECRETARIAT": "SECRETAIRE", "CELLULE_FINANCIERE": "INTENDANT"}

# ---------------------------------------------------------------- droits d'accès
# Droits que l'administrateur peut accorder, module par module.
DROITS = ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")
LIBELLE_DROITS = {
    "LECTURE": "Lecture",
    "AJOUT": "Ajout",
    "MODIFICATION": "Modification",
    "SUPPRESSION": "Suppression",
}
# Modules soumis aux droits : clé -> (titre, droits qui ont un sens dans ce module).
# Paiement : Lecture = ouvrir le module (consultation, duplicata, rapport journalier) ; Ajout = enregistrer un paiement.
# Un reçu ne se modifie ni ne se supprime jamais : seule l'annulation existe (Travaux techniques, Administrateur).
# Un futur module = une ligne de plus ici. (« Travaux techniques » et « Gestionnaire d'accès » ne sont pas ici :
# ils sont réservés à l'ADMINISTRATEUR, sans exception.)
MODULES_DROITS = {
    "paiement": ("Paiement des frais", ("LECTURE", "AJOUT")),
    "encaissement": ("Encaissement des fonds perçus", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    # Contrôle numérique : Lecture = ouvrir le module, contrôler un élève, lister les élèves en ordre, et se connecter à l'application
    # mobile de contrôle (quand elle est activée) ; Modification = activer ou couper l'application mobile (autorité académique).
    "controle": ("Contrôle numérique", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    "carte": ("Carte", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    # Inscription : Lecture = ouvrir le module (liste d'attente) ; Ajout = remplir le formulaire d'inscription d'un candidat ;
    # Modification = valider / affecter : enregistrer le résultat du test, puis affecter à une classe (le candidat devient élève).
    # Une candidature se garde toujours (elle s'appuie sur un reçu) : pas de Suppression.
    "inscription": ("Inscription", ("LECTURE", "AJOUT", "MODIFICATION")),
    # Gestion du personnel : 1re fonctionnalité « Dossier personnel », 2ème « Fonctions et affectations ».
    # Lecture = ouvrir le module, consulter un dossier, l'historique des affectations et les listes du personnel, imprimer la
    #   fiche individuelle et les listes, ouvrir un document ;
    # Ajout = enregistrer un agent, joindre un document, créer une fonction ou un service, affecter un agent ;
    # Modification = modifier un dossier (et le désactiver / réactiver), renommer ou désactiver une fonction ou un service,
    #   corriger ou terminer une affectation ;
    # Suppression = retirer un document joint par erreur, ou une fonction / un service jamais utilisé (un agent et une
    #   affectation ne sont jamais supprimés : l'historique est conservé).
    "personnel": ("Gestion du personnel", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    # Tableau de bord : seule la Lecture existe (c'est un écran de consultation). Il ne figure pas parmi les gros boutons
    # du menu : il s'affiche en premier à la connexion (plus de bouton « Tableau de bord » dans la barre bleue).
    "tableau": ("Tableau de bord", ("LECTURE",)),
    # Traçabilité et audit : consultation seule (journal des activités, historique des opérations financières, contrôles).
    # Réservé à l'Administrateur par défaut ; il peut accorder la Lecture à un poste de contrôle (Préfet, Intendant...).
    "audit": ("Traçabilité et audit", ("LECTURE",)),
    # Présence des élèves : consultation seule de la présence des élèves aux cours (toutes les classes), pointée par les professeurs.
    # Pour le Directeur de discipline et la Directrice des études ; ni le titulaire d'une classe ni les autres professeurs n'y ont accès.
    "presence_eleves": ("Présence des élèves", ("LECTURE",)),
    # Gestion des études et discipline : un droit par sous-menu (le module s'ouvre dès qu'un des quatre est accordé).
    # Les fonctionnalités de chaque sous-menu viendront ensuite ; les quatre droits habituels sont déjà prévus.
    #   Préfecture (Préfet) - Direction des études (Directrice des études) - Direction de discipline (Directeur de discipline)
    #   - Secrétariat (clé « dossier_eleve » conservée).
    # Ce module ne concerne que la section « Secondaire et humanitaire » (sections.py).
    "prefecture": ("Préfecture", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    "direction_etudes": ("Direction des études", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    "direction_discipline": ("Direction de discipline", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
    "dossier_eleve": ("Secrétariat", ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")),
}
# Droits de base de chaque rôle au départ (l'administrateur peut les changer : Gestionnaire d'accès > Rôles).
# Ils sont copiés dans la table ROLE_DROIT à la création de la base, puis c'est cette table qui fait foi.
DROITS_PAR_DEFAUT = {
    "PREFET": {"paiement": ("LECTURE",), "prefecture": ("LECTURE", "AJOUT", "MODIFICATION")},
    "ADMINISTRATEUR": {"paiement": ("LECTURE",)},
    # Inscription : intégrée au Secrétariat (onglet « Inscription »), avec son propre droit : Lecture = liste d'attente, Ajout = formulaire,
    # Modification = test d'admission et affectation. Pour une base déjà installée : Gestionnaire d'accès > Rôles (appliquer aux comptes existants).
    "SECRETAIRE": {"dossier_eleve": ("LECTURE", "MODIFICATION"), "inscription": ("LECTURE", "AJOUT", "MODIFICATION")},
    "INTENDANT": {"paiement": ("LECTURE",)},
    "PERCEPTEUR": {"paiement": ("LECTURE", "AJOUT")},
    "CONTROLEUR": {"paiement": ("LECTURE",)},
    "DIRECTRICE_ETUDES": {"presence_eleves": ("LECTURE",), "direction_etudes": ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")},
    "DIRECTEUR_DISCIPLINE": {"presence_eleves": ("LECTURE",), "direction_discipline": ("LECTURE", "AJOUT")},
}
# Sous-menus du module « Gestion des études et discipline » : (clé du droit, titre, poste auquel il est réservé).
SOUS_MENUS_ETUDES = (
    ("prefecture", "Préfecture", "PREFET"),
    ("direction_etudes", "Direction des études", "DIRECTRICE_ETUDES"),
    ("direction_discipline", "Direction de discipline", "DIRECTEUR_DISCIPLINE"),
    ("dossier_eleve", "Secrétariat", "SECRETAIRE"),
)
# Courte description de chaque sous-menu (affichée sous son titre).
DESCRIPTIONS_SOUS_MENUS_ETUDES = {
    "prefecture": "Supervision générale et validation des décisions autorisées.",
    "direction_etudes": "Notes, bulletins, résultats, dossiers scolaires, suivi pédagogique.",
    "direction_discipline": "Présences, absences, justificatifs, retards, conduite et incidents.",
    "dossier_eleve": "Dossiers des élèves et formalités administratives.",
}
# Fonctionnalités du sous-menu Secrétariat : (clé, titre, description).
FONCTIONNALITES_SECRETARIAT = (
    ("dossiers", "Dossiers des élèves",
     "La secrétaire décide qu'un dossier est complet. Aucune pièce n'est obligatoire : rien n'est vérifié automatiquement."),
    ("inscription", "Inscription",
     "Inscrire un candidat (reçu des frais d'inscription), suivre la liste d'attente, enregistrer le test d'admission et affecter le candidat à une classe."),
    ("bulletins", "Bulletins scolaires",
     "Consulter, imprimer et archiver les bulletins validés par la Préfecture, par classe, période et option."),
    ("archives", "Archives scolaires",
     "Classer les bulletins, les dossiers des anciens élèves et les documents des années précédentes ; recherche par élève et année scolaire."),
    ("listes", "Listes et rapports administratifs",
     "Générer et imprimer les listes d'élèves par classe, option et année scolaire, ainsi que les listes des dossiers incomplets."),
)
# Archives scolaires (Secrétariat) : catégories de classement. (clé, libellé, rattaché à un élève ?)
CATEGORIES_ARCHIVES = (
    ("BULLETIN", "Bulletin d'une année scolaire", True),
    ("DOSSIER", "Dossier d'un ancien élève (inscription, acte de naissance, certificats...)", True),
    ("DOCUMENT", "Document d'une année scolaire (procès-verbal, liste, registre...)", False),
)
TAILLE_MAX_ARCHIVE = 5 * 1024 * 1024                  # 5 Mo par fichier classé
# Écran d'accueil du module (comme la maquette) : le Préfet en haut, puis un espace par poste. Clé du sous-menu -> (titre de la carte, icône).
ESPACES_ETUDES = {
    "prefecture": ("Préfet des études", "prefet"),
    "direction_etudes": ("Espace Études", "etudes"),
    "direction_discipline": ("Espace Discipline", "discipline"),
    "dossier_eleve": ("Secrétariat", "secretariat"),
}
# Fonctionnalités du sous-menu Préfecture : (clé, titre, description).
FONCTIONNALITES_PREFECTURE = (
    ("tableau", "Tableau de bord", "Vue générale de la situation scolaire, alertes et dossiers en attente."),
    ("suivi", "Suivi des élèves", "Consulter le profil, le dossier scolaire, la classe et l'historique de chaque élève."),
    ("finances", "Situation financière des élèves",
     "Consulter les frais dus, les montants payés et les dettes, sans effectuer d'encaissement."),
    ("decisions", "Décisions et rapports",
     "Enregistrer les décisions relevant du préfet et consulter les rapports des responsables."),
    ("discipline", "Consultation de la discipline",
     "Consulter les présences, les absences, les justificatifs, la conduite et les rapports disciplinaires."),
    ("etudes", "Consultation des études",
     "Consulter les résultats, les bulletins et la situation pédagogique des élèves, sans gérer directement les notes."),
    ("proclamation", "Proclamation des résultats",
     "Consulter les bulletins validés par la Directrice des études, changer une décision (avec motif) et confirmer la proclamation."),
    ("documents", "Documents scolaires officiels",
     "Préparer les attestations de fréquentation, certificats de scolarité et autres documents autorisés, puis les soumettre à la signature ou à la validation requise."),
    ("renvois", "Renvoi d'élèves",
     "Renvoyer un élève : il reste dans les archives avec la mention « Renvoyé » et son matricule est libéré."),
    ("listes", "Liste des élèves", "Générer et imprimer la liste des élèves par classe, option et année scolaire (effectifs garçons et filles), exporter en CSV."),
)
# Fonctionnalités des espaces des directions : (clé, titre, description). Le rapport est lu par le Préfet (Préfecture > Décisions et rapports).
FONCTIONNALITES_DIRECTIONS = {
    "direction_etudes": (
        ("horaire", "Élaboration horaire", "Créer les horaires des classes, placer les cours et les professeurs, détecter les conflits, publier."),
        ("heures", "Présences et heures des professeurs",
         "Consulter la présence des professeurs et calculer leurs heures de cours : prévues, données, manquées."),
        ("notes", "Contrôle des notes",
         "Consulter les notes saisies par les professeurs, repérer les notes manquantes et demander des corrections."),
        ("bulletins", "Gestion des bulletins",
         "Consulter les bulletins calculés automatiquement, vérifier les moyennes et les appréciations, détecter les erreurs et les données manquantes."),
        ("proclamation", "Proclamation des résultats",
         "Autoriser les titulaires, choisir les frais exigés, valider les bulletins des élèves en ordre et soumettre la proclamation au Préfet."),
        ("statistiques", "Statistiques et rapports scolaires",
         "Moyennes par élève, classe et cours, classement, taux de réussite et d'échec, comparaison des périodes, rapports sur les enseignants et les classes, impression."),
        ("passage", "Passage en classe supérieure",
         "En fin d'année, affecter les élèves qui ont réussi à la classe supérieure, laisser les échoués dans la même classe (redoublants) "
         "et saisir à la place des élèves de 8ème l'option choisie pour la 1ère humanités."),
        ("calendrier", "Années et périodes",
         "Créer les années scolaires, leurs semestres ou trimestres et leurs périodes ; choisir l'année en cours."),
        ("cours", "Cours", "Définir les cours par niveau, option et année d'étude, les modifier, les désactiver."),
        ("programme", "Programme des classes",
         "Ouvrir les cours d'une classe pour une année, attribuer un professeur à chaque cours et fixer les heures par semaine."),
        ("enseignants", "Enseignants et classes",
         "Charge de chaque professeur, association à une classe, désignation du titulaire de classe et compte de connexion du professeur."),
        ("presence_eleves", "Présence des élèves",
         "Consulter la présence des élèves de toutes les classes, pointée par les professeurs : situation du jour, détail par élève, récapitulatif d'une période."),
        ("listes", "Liste des élèves", "Générer et imprimer la liste des élèves par classe, option et année scolaire (effectifs garçons et filles), exporter en CSV."),
        ("rapport", "Rapport au Préfet", "Rédiger un rapport pour le Préfet et retrouver les rapports envoyés."),
    ),
    "direction_discipline": (
        ("presences", "Gestion des présences",
         "Consulter les présences saisies par les professeurs, vérifier la présence journalière des élèves, confirmer ou corriger le statut de présence "
         "et consulter les absences par classe et par élève."),
        ("conduite", "Suivi de la conduite",
         "Consulter les observations de conduite des professeurs, ajouter ses propres observations disciplinaires, enregistrer les incidents et les "
         "comportements inappropriés, suivre les mentions positives et négatives selon le règlement scolaire et consulter l'historique de conduite de chaque élève."),
        ("convocation", "Convocation du parent",
         "Convoquer le parent ou tuteur d'un élève : choisir l'élève, retrouver les coordonnées du parent, indiquer le motif, fixer la date, l'heure et "
         "le lieu du rendez-vous, ajouter des instructions et envoyer la convocation par notification dans l'application mobile du parent."),
        ("listes", "Liste des élèves", "Générer et imprimer la liste des élèves par classe, option et année scolaire (effectifs garçons et filles), exporter en CSV."),
        ("rapport", "Rapport au Préfet", "Rédiger un rapport pour le Préfet et retrouver les rapports envoyés."),
    ),
}
# Espace Études : module à part entière du menu principal (clé « etudes »). L'espace reste celui de la Direction des études (droit
# « direction_etudes », mêmes adresses /m/etudes_discipline/direction_etudes/...), mais il n'est plus une carte du module « Gestion des études
# et discipline » : il a sa propre entrée dans le menu et ses fonctionnalités s'affichent en boutons, regroupées par thème.
MODULE_ETUDES = "etudes"
ESPACE_ETUDES = "direction_etudes"
TITRE_MODULE_ETUDES = "Espace Études"
# (titre du groupe, clés des fonctionnalités de FONCTIONNALITES_DIRECTIONS["direction_etudes"]). Une clé absente des groupes est ajoutée
# à la fin sous « Autres » : aucune fonctionnalité ne peut disparaître par oubli.
GROUPES_ESPACE_ETUDES = (
    ("Organisation des cours", ("horaire", "calendrier", "cours", "programme", "enseignants")),
    ("Suivi pédagogique", ("notes", "bulletins", "proclamation", "statistiques", "passage")),
    ("Présences", ("heures", "presence_eleves")),
    ("Listes et communication", ("listes", "rapport")),
)
# Espace Discipline : même principe que l'Espace Études (module à part, clé « discipline », entrée /m/discipline, droit « direction_discipline »).
MODULE_DISCIPLINE = "discipline"
ESPACE_DISCIPLINE = "direction_discipline"
TITRE_MODULE_DISCIPLINE = "Espace Discipline"
GROUPES_ESPACE_DISCIPLINE = (
    ("Présences et conduite", ("presences", "conduite")),
    ("Parents", ("convocation",)),
    ("Listes et communication", ("listes", "rapport")),
)
# Préfecture et Secrétariat : mêmes principes (modules « prefecture » et « secretariat », entrées /m/prefecture et /m/secretariat).
MODULE_PREFECTURE = "prefecture"
ESPACE_PREFECTURE = "prefecture"
TITRE_MODULE_PREFECTURE = "Préfecture"
GROUPES_ESPACE_PREFECTURE = (
    ("Supervision", ("tableau", "suivi", "finances")),
    ("Décisions et documents", ("decisions", "proclamation", "renvois", "documents")),
    ("Consultation", ("discipline", "etudes")),
    ("Listes", ("listes",)),
)
MODULE_SECRETARIAT = "secretariat"
ESPACE_SECRETARIAT = "dossier_eleve"
TITRE_MODULE_SECRETARIAT = "Secrétariat"
GROUPES_ESPACE_SECRETARIAT = (
    ("Dossiers et inscription", ("dossiers", "inscription")),
    ("Bulletins et archives", ("bulletins", "archives")),
    ("Listes et rapports", ("listes",)),
)
# Les quatre espaces de l'ancien module « Gestion des études et discipline » sont chacun un module du menu : {clé de l'espace (droit) :
# (clé du module, titre du module, groupes de boutons)}. L'ancien module d'accueil n'existe plus ; /m/etudes_discipline redirige vers le premier
# module ouvert au compte. Les adresses /m/etudes_discipline/<espace>/... ne changent pas.
ESPACES_MODULES = {
    ESPACE_ETUDES: (MODULE_ETUDES, TITRE_MODULE_ETUDES, GROUPES_ESPACE_ETUDES),
    ESPACE_DISCIPLINE: (MODULE_DISCIPLINE, TITRE_MODULE_DISCIPLINE, GROUPES_ESPACE_DISCIPLINE),
    ESPACE_PREFECTURE: (MODULE_PREFECTURE, TITRE_MODULE_PREFECTURE, GROUPES_ESPACE_PREFECTURE),
    ESPACE_SECRETARIAT: (MODULE_SECRETARIAT, TITRE_MODULE_SECRETARIAT, GROUPES_ESPACE_SECRETARIAT),
}

# Convocation du parent (convocations.py) : lieu proposé par défaut, texte de la lettre et signature (adaptez-les à l'école).
CONVOCATION_LIEU_DEFAUT = "Direction de discipline"
CONVOCATION_TEXTE = ("Nous vous prions de bien vouloir vous présenter à l'établissement à la date et à l'heure indiquées afin d'échanger sur la "
                     "situation scolaire de votre enfant.")
CONVOCATION_SIGNATURE = "Le Directeur de discipline"
CONVOCATION_SERVICE = "Direction de discipline"
# Élaboration horaire (horaires.py). Jours de classe : config.JOURS_DE_TRAVAIL. Une journée = 7 cours de 45 minutes : 5 cours, la pause, puis 2 cours.
# La journée commence à 7 h (vacation du matin) ou à 12 h (vacation de l'après-midi) ; la Directrice des études peut régler chaque valeur.
VACATIONS_HORAIRE = (("MATIN", "Matin"), ("APRES_MIDI", "Après-midi"))
HORAIRE_PAR_DEFAUT = {
    "MATIN": {"debut": "07:00", "duree_cours": 45, "nb_avant": 5, "duree_pause": 20, "nb_apres": 2, "recreation_apres": 0, "duree_recreation": 10},
    "APRES_MIDI": {"debut": "12:00", "duree_cours": 45, "nb_avant": 5, "duree_pause": 20, "nb_apres": 2, "recreation_apres": 0, "duree_recreation": 10},
}
NOMS_JOURS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
# Catégories d'une décision du Préfet : (clé, libellé).
CATEGORIES_DECISION = (
    ("pedagogique", "Pédagogique"),
    ("disciplinaire", "Disciplinaire"),
    ("administrative", "Administrative"),
    ("autre", "Autre"),
)
# Documents scolaires officiels (Préfecture) : (clé, titre). L'établissement choisit ici les documents qu'il autorise ; « AUTRE » s'applique
# aux titres de AUTRES_DOCUMENTS_AUTORISES (un titre hors de cette liste est refusé).
DOCUMENTS_OFFICIELS = (
    ("ATTESTATION_FREQUENTATION", "Attestation de fréquentation"),
    ("CERTIFICAT_SCOLARITE", "Certificat de scolarité"),
    ("AUTRE", "Autre document autorisé"),
)
AUTRES_DOCUMENTS_AUTORISES = ("Attestation de bonne conduite", "Attestation de réussite", "Attestation d'inscription", "Attestation de perte de bulletin")
# Signature ou validation requise avant qu'un document soit délivré : (clé, libellé).
APPROBATIONS_DOCUMENT = (
    ("SIGNATURE_PREFET", "Signature du Préfet des études"),
    ("VALIDATION_DIRECTION", "Validation de la Directrice des études"),
    ("SIGNATURE_AUTRE", "Signature d'une autre autorité"),
)
# Alerte « absences répétées » : nombre de jours d'absence sur les 30 derniers jours à partir duquel un élève est signalé.
SEUIL_ABSENCES_REPETEES = 3

# Suivi de la conduite (suivi_conduite.py, Direction de discipline).
# RÈGLEMENT SCOLAIRE : liste des mentions, comportements inappropriés et incidents que la Direction peut enregistrer. Chaque ligne :
#   (code, libellé, genre, nature, gravité, points)
#   genre   : "MENTION" (mention positive ou négative), "COMPORTEMENT" (comportement inapproprié), "INCIDENT"
#   nature  : "POSITIF" ou "NEGATIF"
#   gravité : "" (mention), "LEGERE", "MOYENNE" ou "GRAVE"
#   points  : barème de conduite (positif = bon point, négatif = point perdu) ; la somme des entrées valables d'une année est le « solde de conduite ».
# Les valeurs ci-dessous sont un point de départ : adaptez-les au règlement d'ordre intérieur du collège (changer cette liste ne modifie jamais
# les entrées déjà enregistrées : le libellé, la gravité et les points sont copiés dans chaque entrée au moment de l'enregistrement).
REGLEMENT_CONDUITE = (
    ("FELICITATIONS", "Félicitations de la Direction", "MENTION", "POSITIF", "", 3),
    ("ENCOURAGEMENTS", "Encouragements", "MENTION", "POSITIF", "", 2),
    ("SERVICE", "Service rendu à l'école", "MENTION", "POSITIF", "", 2),
    ("BONNE_CONDUITE", "Bonne conduite remarquée", "MENTION", "POSITIF", "", 1),
    ("AVERTISSEMENT", "Avertissement", "MENTION", "NEGATIF", "", -1),
    ("MISE_EN_GARDE", "Mise en garde écrite aux parents", "MENTION", "NEGATIF", "", -2),
    ("BLAME", "Blâme", "MENTION", "NEGATIF", "", -3),
    ("RETARD", "Retards répétés", "COMPORTEMENT", "NEGATIF", "LEGERE", -1),
    ("TENUE", "Tenue non conforme au règlement", "COMPORTEMENT", "NEGATIF", "LEGERE", -1),
    ("BAVARDAGE", "Indiscipline en classe (bavardage, perturbation)", "COMPORTEMENT", "NEGATIF", "LEGERE", -1),
    ("TELEPHONE", "Usage du téléphone en classe", "COMPORTEMENT", "NEGATIF", "MOYENNE", -2),
    ("INSOLENCE", "Insolence ou manque de respect", "COMPORTEMENT", "NEGATIF", "MOYENNE", -2),
    ("SORTIE", "Sortie sans autorisation", "COMPORTEMENT", "NEGATIF", "MOYENNE", -2),
    ("AUTRE_COMPORTEMENT", "Autre comportement inapproprié (à décrire)", "COMPORTEMENT", "NEGATIF", "LEGERE", -1),
    ("DEGRADATION", "Dégradation du matériel ou des locaux", "INCIDENT", "NEGATIF", "MOYENNE", -3),
    ("FRAUDE", "Fraude ou tricherie", "INCIDENT", "NEGATIF", "GRAVE", -4),
    ("BAGARRE", "Bagarre", "INCIDENT", "NEGATIF", "GRAVE", -4),
    ("VIOLENCE", "Violence ou menaces", "INCIDENT", "NEGATIF", "GRAVE", -5),
    ("VOL", "Vol", "INCIDENT", "NEGATIF", "GRAVE", -5),
    ("AUTRE_INCIDENT", "Autre incident (à décrire)", "INCIDENT", "NEGATIF", "MOYENNE", -2),
)
LIBELLE_GRAVITES = {"": "", "LEGERE": "Légère", "MOYENNE": "Moyenne", "GRAVE": "Grave"}
# Un élève est signalé « à suivre » quand son solde de conduite de l'année descend à ce seuil, ou quand il cumule ce nombre d'entrées négatives valables.
SEUIL_SOLDE_CONDUITE = -5
SEUIL_ENTREES_NEGATIVES = 3

# ---------------------------------------------------------------- calcul des résultats et bulletins (bulletins.py)
# Règles de calcul : à adapter ici si l'école change de règle (rien d'autre à modifier).
SEUIL_REUSSITE = 50.0        # pourcentage minimal pour réussir (période, semestre, année)
# Mentions, de la plus haute à la plus basse : (pourcentage minimal, libellé). Sous le seuil de réussite : pas de mention.
MENTIONS = ((80.0, "Grande distinction"), (70.0, "Distinction"), (60.0, "Satisfaction"), (50.0, "Passable"))
# Une évaluation sans point pour un élève (absent, pas corrigée) : « IGNOREE » = elle ne compte ni au numérateur ni au maximum
# (même règle que la fiche de saisie) ; « ZERO » = elle compte comme 0 sur le maximum.
NOTE_MANQUANTE = "IGNOREE"
# Saisie des points par les professeurs (notes.py) : un seul point par élève et par période, et un point d'examen par semestre.
# Le professeur ne saisit que la période (ou l'examen) que le TITULAIRE de la classe a autorisée (bulletins.py : autorisations).
# Le total du semestre = période 1 + période 2 (+ examen si EXAMEN_DANS_SEMESTRE) ; il n'est visible que du titulaire.
EXAMEN_DANS_SEMESTRE = True     # True : total du semestre = périodes + examen ; False : total du semestre = périodes seules
MAXIMUM_PERIODE = 20            # maximum des points d'une période
MAXIMUM_EXAMEN = 40             # maximum de l'examen d'un semestre
DECISION_REUSSI = "ADMIS(E)"       # résultat de l'année
DECISION_ECHEC = "AJOURNÉ(E)"
RESULTAT_REUSSI = "RÉUSSI(E)"      # résultat d'une période ou d'un semestre
RESULTAT_ECHEC = "ÉCHEC"
DECISION_ATTENTE = "EN ATTENTE"   # l'année n'est pas complète : il manque les points d'une période

# ---------------------------------------------------------------- sécurité
LONGUEUR_MIN_MDP = 12
LONGUEUR_MAX_MDP = 128

MAX_ECHECS = 5               # échecs consécutifs avant blocage
DUREE_BLOCAGE_MIN = 15       # 1er blocage ; doublé à chaque blocage suivant
BLOCAGE_MAX_MIN = 480        # plafond : 8 heures
DELAI_INACTIVITE_MIN = 10    # fermeture automatique de la session
DELAI_INACTIVITE_CTRL_MIN = 60   # idem pour l'application mobile de contrôle (le contrôleur reste à la porte, chaque contrôle prolonge la session)
DELAI_INACTIVITE_PROF_MIN = 30   # idem pour la page web des professeurs (ils saisissent des points sur tablette ou téléphone)
DELAI_INACTIVITE_PARENT_JOURS = 30   # application mobile des parents : le téléphone reste connecté tant qu'il est utilisé au moins une fois par mois
ACCES_PARENT_PAR_ANNEE = True    # True : l'accès d'un parent à un enfant vaut pour l'année scolaire du paiement ; à la rentrée suivante, un nouveau
                                 # paiement (donc un nouveau code) est nécessaire. False : l'accès dure tant que le reçu n'est pas annulé.
PORT_PROFESSEURS = 8765      # port du serveur web de la saisie des points

# Code de récupération du mot de passe (généré par le système, remis par l'Administrateur)
DUREE_CODE_RECUPERATION_SEC = 120    # le code disparaît après 2 minutes
LONGUEUR_CODE_RECUPERATION = 8       # caractères (sans I, O, 0, 1 : lisible à voix haute)
MAX_ESSAIS_CODE = 3                  # essais faux avant que le code soit détruit

# ---------------------------------------------------------------- reçus
DOSSIER_RECUS = dossier_donnees() / "recus"

# ---------------------------------------------------------------- sauvegardes
DOSSIER_SAUVEGARDES = dossier_donnees() / "sauvegardes"
EXTENSION_SAUVEGARDE = ".csfbak"      # archive zip : base de données + manifeste (date, version, empreinte)

# ---------------------------------------------------------------- traçabilité et audit
DOSSIER_PERSONNEL = dossier_donnees() / "personnel"   # fiches individuelles (PDF) et copies temporaires des documents ouverts
DOSSIER_AUDIT = dossier_donnees() / "audit"      # exports du journal et de l'historique financier (CSV, PDF)

# ---------------------------------------------------------------- admission (module Inscription, 2ème fonctionnalité)
SEUIL_REUSSITE_TEST = 50.0   # note minimale (sur 100, en %) pour réussir le test d'admission ; en dessous : candidature refusée

# ---------------------------------------------------------------- présence et absence (personnel)
HEURE_DEBUT_SERVICE = "07:30"        # heure d'arrivée attendue : au-delà, l'agent est en retard
JOURS_DE_TRAVAIL = (0, 1, 2, 3, 4)   # 0 = lundi ... 6 = dimanche (ici lundi à vendredi)
