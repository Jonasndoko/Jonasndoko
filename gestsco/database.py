"""Accès à la base de données (SQLite) : schéma, connexion, journal infalsifiable."""
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA_UTILISATEUR = """
CREATE TABLE IF NOT EXISTS UTILISATEUR (
    ID_USER            INTEGER PRIMARY KEY AUTOINCREMENT,
    LOGIN              TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    NOM_COMPLET        TEXT    NOT NULL,
    ROLE               TEXT    NOT NULL,           -- poste : validé par l'application (config.ROLES)
    MDP_HASH           TEXT    NOT NULL,
    ACTIF              INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    DOIT_CHANGER_MDP   INTEGER NOT NULL DEFAULT 0 CHECK (DOIT_CHANGER_MDP IN (0,1)),
    DATE_CREATION      TEXT    NOT NULL,
    DERNIERE_CONNEXION TEXT
);
"""

SCHEMA_PAIEMENT = """
CREATE TABLE IF NOT EXISTS PAIEMENT (            -- un reçu = un seul type de frais ; MONT_PAYE en CENTIMES
    N_RECU      TEXT    PRIMARY KEY,
    ANNEESCO    TEXT    NOT NULL,
    NUM_SEQ     INTEGER NOT NULL,
    DATE_PAY    TEXT    NOT NULL,
    MATRICULE   TEXT,                            -- vide : paiement des frais d'inscription par un candidat pas encore élève
    N_CLASSE    INTEGER NOT NULL,                -- classe au moment du paiement (le reçu ne change jamais)
    CODTF       TEXT    NOT NULL,
    CODE_DEVISE TEXT    NOT NULL REFERENCES DEVISE(CODE_DEVISE),
    MONT_PAYE   INTEGER NOT NULL CHECK (MONT_PAYE > 0),
    N_PERC      INTEGER NOT NULL REFERENCES PERCEPTEUR(N_PERC),
    STATUT      TEXT    NOT NULL DEFAULT 'VALIDE' CHECK (STATUT IN ('VALIDE','ANNULE')),
    MOTIF_ANNULATION TEXT,                       -- remplis seulement à l'annulation (le reste du reçu ne change jamais)
    DATE_ANNULATION  TEXT,
    ANNULE_PAR       TEXT,
    NOM_PAYEUR  TEXT,                            -- nom du candidat (sans matricule) ; vide pour un élève inscrit
    UNIQUE (ANNEESCO, NUM_SEQ),
    CHECK (MATRICULE IS NOT NULL OR (NOM_PAYEUR IS NOT NULL AND TRIM(NOM_PAYEUR) <> '')),
    FOREIGN KEY (ANNEESCO, MATRICULE) REFERENCES INSCRIRE(ANNEESCO, MATRICULE),
    FOREIGN KEY (CODTF, N_CLASSE, ANNEESCO) REFERENCES TARIF(CODTF, N_CLASSE, ANNEESCO)
);
"""

SCHEMA_EVALUATION = """
CREATE TABLE IF NOT EXISTS EVALUATION (
    ID_EVAL        INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_CC          INTEGER NOT NULL REFERENCES COURS_CLASSE(ID_CC),
    ID_PER         INTEGER NOT NULL REFERENCES PERIODE_SCO(ID_PER),
    TYPE           TEXT    NOT NULL CHECK (TYPE IN ('INT','DEV','IG','EXA','PER')),
    NUMERO         INTEGER NOT NULL CHECK (NUMERO >= 1),
    DATE_EVAL      TEXT    NOT NULL,
    MAXIMUM        REAL    NOT NULL CHECK (MAXIMUM > 0 AND MAXIMUM <= 1000),
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    UNIQUE (ID_CC, ID_PER, TYPE, NUMERO)
);
"""

SCHEMA = SCHEMA_UTILISATEUR + """
-- Droits d'accès accordés par l'administrateur : une ligne = un droit sur un module
CREATE TABLE IF NOT EXISTS DROIT (
    ID_USER INTEGER NOT NULL REFERENCES UTILISATEUR(ID_USER),
    MODULE  TEXT    NOT NULL,
    DROIT   TEXT    NOT NULL,
    PRIMARY KEY (ID_USER, MODULE, DROIT)
);

-- Sections de l'école (PRIMAIRE ; SECONDAIRE = secondaire et humanitaire) ouvertes à un compte (sections.py). Sans ligne : toutes
-- les sections (comptes existants) ; l'Administrateur voit toujours tout.
CREATE TABLE IF NOT EXISTS SECTION_UTILISATEUR (
    ID_USER INTEGER NOT NULL REFERENCES UTILISATEUR(ID_USER),
    SECTION TEXT    NOT NULL CHECK (SECTION IN ('PRIMAIRE','SECONDAIRE')),
    PRIMARY KEY (ID_USER, SECTION)
);

-- Droits de base de chaque rôle (copiés sur un compte à sa création ou quand son rôle change)
CREATE TABLE IF NOT EXISTS ROLE_DROIT (
    ROLE   TEXT NOT NULL,
    MODULE TEXT NOT NULL,
    DROIT  TEXT NOT NULL,
    PRIMARY KEY (ROLE, MODULE, DROIT)
);

-- Rôles créés par l'administrateur (les 8 postes de base sont dans config.py et ne sont pas stockés ici)
CREATE TABLE IF NOT EXISTS ROLE (
    CODE    TEXT PRIMARY KEY,
    LIBELLE TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- Compteur d'échecs par identifiant saisi (qu'il existe ou non : pas de fuite d'information)
CREATE TABLE IF NOT EXISTS TENTATIVE_CONNEXION (
    LOGIN         TEXT    PRIMARY KEY COLLATE NOCASE,
    ECHECS        INTEGER NOT NULL DEFAULT 0,
    NB_BLOCAGES   INTEGER NOT NULL DEFAULT 0,
    BLOQUE_JUSQUA TEXT
);

-- Codes de récupération du mot de passe : générés par le système, remis par l'Administrateur, valables 2 minutes.
-- Le code n'est JAMAIS stocké en clair (seulement son empreinte) ; une ligne est supprimée dès qu'elle sert, expire,
-- est annulée ou remplacée : il y a au plus un code par compte.
CREATE TABLE IF NOT EXISTS CODE_RECUPERATION (
    ID_USER         INTEGER PRIMARY KEY REFERENCES UTILISATEUR(ID_USER),
    CODE_HASH       TEXT    NOT NULL,
    DATE_CREATION   TEXT    NOT NULL,
    DATE_EXPIRATION TEXT    NOT NULL,
    ESSAIS          INTEGER NOT NULL DEFAULT 0,
    CREE_PAR        TEXT    NOT NULL
);

-- Journal chaîné : chaque ligne contient l'empreinte de la précédente
CREATE TABLE IF NOT EXISTS JOURNAL (
    ID_LOG         INTEGER PRIMARY KEY AUTOINCREMENT,
    DATE_HEURE     TEXT    NOT NULL,
    ID_USER        INTEGER,
    LOGIN          TEXT,
    ACTION         TEXT    NOT NULL,
    DETAIL         TEXT    NOT NULL DEFAULT '',
    EMPREINTE_PREC TEXT    NOT NULL,
    EMPREINTE      TEXT    NOT NULL
);

-- Le journal est en ajout seulement : aucune modification ni suppression
CREATE TRIGGER IF NOT EXISTS JOURNAL_NO_UPDATE BEFORE UPDATE ON JOURNAL
BEGIN SELECT RAISE(ABORT, 'Le journal est en lecture seule'); END;

CREATE TRIGGER IF NOT EXISTS JOURNAL_NO_DELETE BEFORE DELETE ON JOURNAL
BEGIN SELECT RAISE(ABORT, 'Le journal est en lecture seule'); END;

-- Application mobile de contrôle : un seul réglage (ligne 1). Il est activé ou coupé par l'autorité académique autorisée
-- (droit Modification sur le module Contrôle numérique) ; sans ligne, l'application mobile est coupée.
CREATE TABLE IF NOT EXISTS CONTROLE_MOBILE (
    ID          INTEGER PRIMARY KEY CHECK (ID = 1),
    ACTIF       INTEGER NOT NULL DEFAULT 0,
    MODIFIE_PAR TEXT,
    MODIFIE_LE  TEXT
);

-- ===================== Données scolaires =====================
CREATE TABLE IF NOT EXISTS NIVEAU (
    CODE_NIVEAU TEXT PRIMARY KEY,
    DESI_NIVEAU TEXT NOT NULL,
    ACTIF       INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    SECTION     TEXT NOT NULL DEFAULT 'SECONDAIRE' CHECK (SECTION IN ('PRIMAIRE','SECONDAIRE'))   -- section de l'école (sections.py)
);
CREATE TABLE IF NOT EXISTS OPTION_SCO (
    CODE_OPTION TEXT PRIMARY KEY,
    DESI_OPTION TEXT NOT NULL,
    ACTIF       INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1))
);
CREATE TABLE IF NOT EXISTS POSSEDE (
    CODE_NIVEAU TEXT NOT NULL REFERENCES NIVEAU(CODE_NIVEAU),
    CODE_OPTION TEXT NOT NULL REFERENCES OPTION_SCO(CODE_OPTION),
    PRIMARY KEY (CODE_NIVEAU, CODE_OPTION)
);
CREATE TABLE IF NOT EXISTS CLASSE (
    N_CLASSE    INTEGER PRIMARY KEY AUTOINCREMENT,
    DESI_CLASSE TEXT NOT NULL,             -- année d'étude + division, composée par le système (ex. « 1ère A »)
    CODE_NIVEAU TEXT NOT NULL REFERENCES NIVEAU(CODE_NIVEAU),   -- cycle : primaire, secondaire (7ème-8ème), humanités
    CODE_OPTION TEXT,                      -- uniquement en humanités (obligatoire quand le niveau a des options)
    ACTIF       INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    ANNEE_ETUDE TEXT,                      -- 1ère, 2ème, ... 6ème, 7ème, 8ème (migration 5 : lu dans DESI_CLASSE)
    DIVISION    TEXT,                      -- A, B, C, D... (vide : classe unique)
    FOREIGN KEY (CODE_NIVEAU, CODE_OPTION) REFERENCES POSSEDE(CODE_NIVEAU, CODE_OPTION)
);
CREATE TABLE IF NOT EXISTS ANNEE_SCO (
    ANNEESCO TEXT PRIMARY KEY CHECK (ANNEESCO GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'),
    EN_COURS INTEGER NOT NULL DEFAULT 0 CHECK (EN_COURS IN (0,1)),
    ACTIF    INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1))
);
CREATE TABLE IF NOT EXISTS ELEVE (
    MATRICULE      TEXT PRIMARY KEY COLLATE NOCASE,
    NOM            TEXT NOT NULL,
    POSTNOM        TEXT,
    PRENOM         TEXT,
    SEXE           TEXT CHECK (SEXE IN ('M','F')),
    DATE_NAISSANCE TEXT,
    LIEU_NAISSANCE TEXT,
    ADRESSE        TEXT,
    TELEPHONE      TEXT,
    NOM_TUTEUR     TEXT,
    TEL_TUTEUR     TEXT,
    ACTIF          INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    NATIONALITE    TEXT,
    CODE_QR        TEXT                      -- attribué par le système (identite.py) ; index unique : migration 4
);
-- Ancien compteur des matricules (versions 0.10 et 0.11, format 000001) : conservé pour les anciennes bases
CREATE TABLE IF NOT EXISTS ELEVE_SEQ (
    N         INTEGER PRIMARY KEY AUTOINCREMENT,
    MATRICULE TEXT
);
-- Dernier numéro d'ordre attribué pour chaque année d'inscription (2 chiffres) : le matricule est « 0001/26 »
-- (numéro d'ordre / année). Le compteur ne recule jamais : un numéro supprimé n'est pas redonné.
CREATE TABLE IF NOT EXISTS MATRICULE_SEQ (
    ANNEE   TEXT PRIMARY KEY,
    DERNIER INTEGER NOT NULL DEFAULT 0
);
-- Photo de l'élève (JPEG) prise avec la caméra dans le module Carte
CREATE TABLE IF NOT EXISTS PHOTO_ELEVE (
    MATRICULE  TEXT PRIMARY KEY REFERENCES ELEVE(MATRICULE) ON DELETE CASCADE,
    PHOTO      BLOB NOT NULL,
    DATE_PHOTO TEXT NOT NULL,
    PRIS_PAR   TEXT NOT NULL
);
-- Secrétariat : état du dossier d'un élève (un seul état par élève, valable sans limite d'année). C'est la secrétaire qui décide
-- qu'un dossier est complet : aucune pièce n'est obligatoire, donc rien n'est calculé ni vérifié. Pas de ligne = dossier incomplet.
CREATE TABLE IF NOT EXISTS DOSSIER_ELEVE (
    MATRICULE     TEXT PRIMARY KEY COLLATE NOCASE REFERENCES ELEVE(MATRICULE) ON DELETE CASCADE,
    COMPLET       INTEGER NOT NULL DEFAULT 0 CHECK (COMPLET IN (0,1)),
    DATE_DECISION TEXT NOT NULL,
    DECIDE_PAR    TEXT NOT NULL
);
-- Proclamation (proclamation.py) : la Directrice des études autorise le titulaire d'une classe pour une période, un semestre ou l'année
-- (CLE : P<id>, X<id>, S<id> ou A), choisit les frais exigés, valide les bulletins des élèves en ordre, puis soumet au Préfet qui
-- confirme. Le titulaire n'imprime que les bulletins validés d'une proclamation CONFIRMÉE ; il peut toujours les consulter.
CREATE TABLE IF NOT EXISTS PROCLAMATION (
    ANNEESCO      TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE      INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    CLE           TEXT    NOT NULL,
    STATUT        TEXT    NOT NULL DEFAULT 'AUTORISEE' CHECK (STATUT IN ('AUTORISEE','TRANSMISE','CONFIRMEE')),
    AUTORISEE_LE  TEXT    NOT NULL,
    AUTORISEE_PAR TEXT    NOT NULL,
    TRANSMISE_LE  TEXT,
    TRANSMISE_PAR TEXT,
    CONFIRMEE_LE  TEXT,
    CONFIRMEE_PAR TEXT,
    PRIMARY KEY (ANNEESCO, N_CLASSE, CLE)
);
-- Frais exigés pour qu'un élève soit « en ordre » : TRANCHE vide = la totalité du frais ; sinon payé au moins jusqu'à cette tranche.
CREATE TABLE IF NOT EXISTS PROCLAMATION_FRAIS (
    ANNEESCO TEXT    NOT NULL,
    N_CLASSE INTEGER NOT NULL,
    CLE      TEXT    NOT NULL,
    CODTF    TEXT    NOT NULL REFERENCES TYPE_FRAIS(CODTF),
    TRANCHE  INTEGER CHECK (TRANCHE IS NULL OR TRANCHE >= 1),
    PRIMARY KEY (ANNEESCO, N_CLASSE, CLE, CODTF),
    FOREIGN KEY (ANNEESCO, N_CLASSE, CLE) REFERENCES PROCLAMATION(ANNEESCO, N_CLASSE, CLE) ON DELETE CASCADE
);
-- Décision sur le bulletin d'un élève : VALIDE = 1 (proclamé) ou 0 (retiré). ORIGINE : DIRECTRICE ou PREFET (qui a changé la décision,
-- avec son motif). Jamais supprimée : le journal garde en plus chaque changement.
CREATE TABLE IF NOT EXISTS VALIDATION_BULLETIN (
    ANNEESCO  TEXT    NOT NULL,
    N_CLASSE  INTEGER NOT NULL,
    CLE       TEXT    NOT NULL,
    MATRICULE TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    VALIDE    INTEGER NOT NULL CHECK (VALIDE IN (0,1)),
    ORIGINE   TEXT    NOT NULL CHECK (ORIGINE IN ('DIRECTRICE','PREFET')),
    DECIDE_LE TEXT    NOT NULL,
    DECIDE_PAR TEXT   NOT NULL,
    MOTIF     TEXT,
    PRIMARY KEY (ANNEESCO, N_CLASSE, CLE, MATRICULE),
    FOREIGN KEY (ANNEESCO, N_CLASSE, CLE) REFERENCES PROCLAMATION(ANNEESCO, N_CLASSE, CLE) ON DELETE CASCADE
);
-- Archive des bulletins (bulletins_secretariat.py) : copie PDF figée des bulletins validés par la Préfecture, pour une classe et une
-- période (CLE : P<id>, X<id>, S<id> ou A). Chaque archivage crée une nouvelle ligne ; l'application ne modifie ni ne supprime une archive.
CREATE TABLE IF NOT EXISTS ARCHIVE_BULLETIN (
    ID_ARCHIVE   INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO     TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE     INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    CLE          TEXT    NOT NULL,
    NB_BULLETINS INTEGER NOT NULL CHECK (NB_BULLETINS >= 1),
    NOM_FICHIER  TEXT    NOT NULL,
    CONTENU      BLOB    NOT NULL,
    TAILLE       INTEGER NOT NULL,
    ARCHIVE_LE   TEXT    NOT NULL,
    ARCHIVE_PAR  TEXT    NOT NULL,
    ID_USER      INTEGER REFERENCES UTILISATEUR(ID_USER)
);
CREATE INDEX IF NOT EXISTS IDX_ARCHIVE_BULLETIN ON ARCHIVE_BULLETIN (ANNEESCO, N_CLASSE, CLE);
-- Archives scolaires (archives_scolaires.py) : documents numérisés (PDF, JPEG ou PNG) classés par la secrétaire : dossiers d'anciens élèves,
-- bulletins ou documents d'années précédentes. L'année est libre (format AAAA-AAAA) : elle peut précéder l'installation du logiciel.
-- MATRICULE est vide pour un document qui concerne toute l'année (procès-verbal, liste, registre...). Rien n'est supprimé : « retirer du
-- classement » remplit RETIRE_LE / RETIRE_PAR / MOTIF_RETRAIT et le fichier reste dans la base (et dans les sauvegardes).
CREATE TABLE IF NOT EXISTS ARCHIVE_SCOLAIRE (
    ID_ARCH      INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO     TEXT    NOT NULL,
    MATRICULE    TEXT    REFERENCES ELEVE(MATRICULE),
    CATEGORIE    TEXT    NOT NULL,
    TITRE        TEXT    NOT NULL,
    NOTE         TEXT,
    NOM_FICHIER  TEXT    NOT NULL,
    FORMAT       TEXT    NOT NULL CHECK (FORMAT IN ('PDF','JPEG','PNG')),
    TAILLE       INTEGER NOT NULL,
    EMPREINTE    TEXT    NOT NULL,
    CONTENU      BLOB    NOT NULL,
    CLASSE_LE    TEXT    NOT NULL,
    CLASSE_PAR   TEXT    NOT NULL,
    ID_USER      INTEGER REFERENCES UTILISATEUR(ID_USER),
    RETIRE_LE    TEXT,
    RETIRE_PAR   TEXT,
    MOTIF_RETRAIT TEXT
);
CREATE INDEX IF NOT EXISTS IDX_ARCHIVE_SCOLAIRE ON ARCHIVE_SCOLAIRE (ANNEESCO, MATRICULE);
-- Documents scolaires officiels (documents_officiels.py) : attestation de fréquentation, certificat de scolarité ou autre document autorisé,
-- préparé dans la Préfecture (BROUILLON), soumis à la signature ou à la validation requise (SOUMIS), puis SIGNE (numéro attribué) ou renvoyé
-- en brouillon avec un motif. Un document signé ne se modifie plus ; il peut être ANNULE avec un motif. Jamais supprimé.
CREATE TABLE IF NOT EXISTS DOCUMENT_OFFICIEL (
    ID_DOC       INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO     TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE    TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE     INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    TYPE         TEXT    NOT NULL,
    TITRE        TEXT    NOT NULL,
    CONTENU      TEXT    NOT NULL,
    STATUT       TEXT    NOT NULL DEFAULT 'BROUILLON' CHECK (STATUT IN ('BROUILLON','SOUMIS','SIGNE','ANNULE')),
    APPROBATION  TEXT,
    SIGNATAIRE   TEXT,
    MOTIF_RETOUR TEXT,
    NUMERO       TEXT,
    CREE_LE      TEXT    NOT NULL,
    CREE_PAR     TEXT    NOT NULL,
    SOUMIS_LE    TEXT,
    SOUMIS_PAR   TEXT,
    SIGNE_LE     TEXT,
    SIGNE_PAR    TEXT,
    ANNULE_LE    TEXT,
    ANNULE_PAR   TEXT,
    MOTIF_ANNULATION TEXT
);
CREATE INDEX IF NOT EXISTS IDX_DOCUMENT_OFFICIEL ON DOCUMENT_OFFICIEL (ANNEESCO, STATUT);
CREATE UNIQUE INDEX IF NOT EXISTS IDX_DOCUMENT_NUMERO ON DOCUMENT_OFFICIEL (NUMERO) WHERE NUMERO IS NOT NULL;
CREATE TABLE IF NOT EXISTS INSCRIRE (
    ANNEESCO         TEXT NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE        TEXT NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE         INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    DATE_INSCRIPTION TEXT,
    STATUT           TEXT NOT NULL DEFAULT 'NOUVEAU' CHECK (STATUT IN ('NOUVEAU','REDOUBLANT','TRANSFERT','ANCIEN')),
    PRIMARY KEY (ANNEESCO, MATRICULE)      -- une seule classe par élève et par année
);

-- ===================== Frais et paiements =====================
CREATE TABLE IF NOT EXISTS DEVISE (
    CODE_DEVISE TEXT PRIMARY KEY,
    DESI_DEVISE TEXT NOT NULL,
    ACTIF       INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1))
);
CREATE TABLE IF NOT EXISTS TYPE_FRAIS (          -- MONTANT en CENTIMES : montant habituel du frais, dans la devise CODE_DEVISE
    CODTF         TEXT PRIMARY KEY,                   -- (vide : le montant dépend de la classe et se fixe dans TARIF)
    DESITF        TEXT NOT NULL,
    ACTIF         INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    MONTANT       INTEGER CHECK (MONTANT IS NULL OR MONTANT > 0),
    CODE_DEVISE   TEXT REFERENCES DEVISE(CODE_DEVISE),
    PAR_TRANCHE   INTEGER NOT NULL DEFAULT 0 CHECK (PAR_TRANCHE IN (0,1)),   -- 1 : payé par tranches (frais scolaire)
    TRANCHES      TEXT,                               -- montant de chaque tranche en centimes, séparés par « ; » (« 10000;10000;10000 ») :
                                                      -- le total fait MONTANT ; nombre de tranches libre ; vide si PAR_TRANCHE = 0
    POUR_INSCRIPTION INTEGER NOT NULL DEFAULT 0 CHECK (POUR_INSCRIPTION IN (0,1)),  -- 1 : frais d'inscription (module Inscription)
    POUR_APPLI_PARENTS INTEGER NOT NULL DEFAULT 0 CHECK (POUR_APPLI_PARENTS IN (0,1)),  -- 1 : frais du logiciel des parents : son paiement génère le code d'accès (parents.py)
    CLASSE_CIBLE  TEXT CHECK (CLASSE_CIBLE IS NULL OR CLASSE_CIBLE IN ('HUM4','PRIM6','SEC8'))  -- frais obligatoire réservé à une année d'étude : HUM4 = 4ème humanités, PRIM6 = 6ème primaire, SEC8 = 8ème secondaire (donnees.cible_de_classe) ; vide = toutes les classes
);
-- TARIF : montant particulier d'un frais pour une classe et une année (sinon le montant du type de frais s'applique).
-- C'est ici que se règlent les frais qui dépendent de la classe (ex. frais scolaire : 300 en 1ère-3ème, 600 en 4ème).
CREATE TABLE IF NOT EXISTS TARIF (               -- montant en CENTIMES
    CODTF       TEXT    NOT NULL REFERENCES TYPE_FRAIS(CODTF),
    N_CLASSE    INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    ANNEESCO    TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MONTANT     INTEGER NOT NULL CHECK (MONTANT > 0),
    CODE_DEVISE TEXT    NOT NULL REFERENCES DEVISE(CODE_DEVISE),
    TRANCHES    TEXT,                                 -- tranches de ce tarif (frais payé par tranches), comme TYPE_FRAIS.TRANCHES
    PRIMARY KEY (CODTF, N_CLASSE, ANNEESCO)
);
CREATE TABLE IF NOT EXISTS PERCEPTEUR (
    N_PERC  INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_USER INTEGER NOT NULL UNIQUE REFERENCES UTILISATEUR(ID_USER)
);
""" + SCHEMA_PAIEMENT + """
CREATE INDEX IF NOT EXISTS IDX_PAIEMENT_ELEVE ON PAIEMENT (MATRICULE, ANNEESCO, CODTF);

-- Un reçu n'est jamais supprimé ni modifié : seul son statut peut passer à ANNULE
CREATE TRIGGER IF NOT EXISTS PAIEMENT_NO_DELETE BEFORE DELETE ON PAIEMENT
BEGIN SELECT RAISE(ABORT, 'Un reçu ne peut pas être supprimé (utilisez l''annulation)'); END;

CREATE TRIGGER IF NOT EXISTS PAIEMENT_NO_UPDATE
BEFORE UPDATE OF N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, NOM_PAYEUR, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC
ON PAIEMENT
BEGIN SELECT RAISE(ABORT, 'Un reçu ne peut pas être modifié'); END;

-- ===================== Encaissement des fonds perçus =====================
-- Un enregistrement = ce qu'un percepteur déclare avoir encaissé et ce qu'il a versé, à une date, dans une devise.
-- Montants en CENTIMES. ECART = MONT_ENCAISSE - MONT_VERSE (positif : manquant ; négatif : excédent).
CREATE TABLE IF NOT EXISTS ENCAISSEMENT (
    N_ENC         INTEGER PRIMARY KEY AUTOINCREMENT,
    DATE_ENC      TEXT    NOT NULL,                 -- date de l'encaissement (AAAA-MM-JJ)
    N_PERC        INTEGER NOT NULL REFERENCES PERCEPTEUR(N_PERC),
    CODE_DEVISE   TEXT    NOT NULL REFERENCES DEVISE(CODE_DEVISE),
    MONT_ENCAISSE INTEGER NOT NULL CHECK (MONT_ENCAISSE > 0),
    MONT_VERSE    INTEGER NOT NULL CHECK (MONT_VERSE >= 0),
    ECART         INTEGER NOT NULL,
    SAISI_PAR     TEXT    NOT NULL,                 -- identifiant du compte qui a enregistré
    DATE_SAISIE   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS IDX_ENCAISSEMENT_DATE ON ENCAISSEMENT (DATE_ENC, N_PERC);

-- ===================== Inscription =====================
-- Parcours : le candidat paie à la caisse (un reçu d'un type de frais « d'inscription ») -> il va chez le secrétaire, qui remplit
-- le formulaire (CANDIDATURE) avec le numéro du reçu -> le candidat est mis sur la liste d'attente (STATUT = 'EN_ATTENTE').
-- Le paiement n'est PAS enregistré ici : il reste dans PAIEMENT (module Paiement des frais). Une candidature n'existe que si
-- elle s'appuie sur un reçu VALIDE de frais d'inscription (contrôlé par l'application ET par le déclencheur ci-dessous).
CREATE TABLE IF NOT EXISTS CANDIDATURE (
    N_CAND          INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO        TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    ORDRE           INTEGER NOT NULL,                 -- numéro d'arrivée dans l'année : sert à l'ordre de la liste d'attente
    NUM_CAND        TEXT    NOT NULL UNIQUE,          -- « C0001/26 » : donné par le système
    N_RECU          TEXT    NOT NULL UNIQUE REFERENCES PAIEMENT(N_RECU),   -- un reçu = une seule candidature
    -- identité du candidat
    NOM             TEXT    NOT NULL,
    POSTNOM         TEXT,
    PRENOM          TEXT,
    SEXE            TEXT    NOT NULL CHECK (SEXE IN ('M','F')),
    DATE_NAISSANCE  TEXT    NOT NULL,                 -- AAAA-MM-JJ
    LIEU_NAISSANCE  TEXT,
    NATIONALITE     TEXT,
    ADRESSE         TEXT    NOT NULL,
    TELEPHONE       TEXT,
    -- parcours scolaire
    ECOLE_ORIGINE   TEXT    NOT NULL,                 -- ancienne école
    POURCENT_ORIGINE REAL   NOT NULL CHECK (POURCENT_ORIGINE >= 0 AND POURCENT_ORIGINE <= 100),   -- pourcentage obtenu
    DOUBLANT        INTEGER NOT NULL CHECK (DOUBLANT IN (0,1)),
    N_CLASSE        INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),   -- classe dans laquelle il veut être inscrit
    -- tuteur
    NOM_TUTEUR      TEXT    NOT NULL,
    TEL_TUTEUR      TEXT    NOT NULL,
    ADRESSE_TUTEUR  TEXT    NOT NULL,
    -- suivi
    STATUT          TEXT    NOT NULL DEFAULT 'EN_ATTENTE' CHECK (STATUT IN ('EN_ATTENTE','ADMIS','REFUSE','RETIRE')),
    MATRICULE       TEXT    REFERENCES ELEVE(MATRICULE),      -- rempli quand le candidat est admis et devient élève
    -- test d'admission, validation et affectation (2ème fonctionnalité)
    NOTE_TEST       REAL,                             -- note du test, sur 100 (vide : test pas encore passé)
    RESULTAT_TEST   TEXT,                             -- REUSSI (dossier validé) ou ECHOUE (candidature refusée)
    DATE_TEST       TEXT,                             -- date et heure de l'enregistrement du résultat (UTC)
    TEST_PAR        TEXT,                             -- compte qui a enregistré le résultat
    N_CLASSE_AFFECTEE INTEGER REFERENCES CLASSE(N_CLASSE),   -- classe d'affectation (peut différer de la classe souhaitée)
    DATE_DECISION   TEXT,                             -- date et heure de la décision finale (admis ou refusé)
    DECISION_PAR    TEXT,                             -- compte qui a affecté le candidat (ou dont le test a décidé du refus)
    DATE_ENREG      TEXT    NOT NULL,                 -- date et heure de l'enregistrement (UTC)
    ENREGISTRE_PAR  TEXT    NOT NULL,                 -- identifiant du compte qui a rempli le formulaire
    UNIQUE (ANNEESCO, ORDRE)
);
CREATE INDEX IF NOT EXISTS IDX_CANDIDATURE_LISTE ON CANDIDATURE (ANNEESCO, STATUT, N_CLASSE, ORDRE);

-- Pas de candidature sans paiement : le reçu doit exister, être VALIDE (non annulé), porter sur un type de frais d'inscription
-- et être de la même année scolaire que la candidature.
CREATE TRIGGER IF NOT EXISTS CANDIDATURE_EXIGE_PAIEMENT BEFORE INSERT ON CANDIDATURE
WHEN NOT EXISTS (SELECT 1 FROM PAIEMENT P JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF
                 WHERE P.N_RECU = NEW.N_RECU AND P.STATUT = 'VALIDE' AND F.POUR_INSCRIPTION = 1 AND P.ANNEESCO = NEW.ANNEESCO)
BEGIN SELECT RAISE(ABORT, 'Candidature refusée : aucun paiement valide des frais d''inscription pour ce reçu'); END;

-- Le reçu, l'année, le numéro et l'ordre d'arrivée ne changent jamais après l'enregistrement
CREATE TRIGGER IF NOT EXISTS CANDIDATURE_NO_UPDATE
BEFORE UPDATE OF N_CAND, ANNEESCO, ORDRE, NUM_CAND, N_RECU, DATE_ENREG, ENREGISTRE_PAR ON CANDIDATURE
BEGIN SELECT RAISE(ABORT, 'Une candidature ne peut pas être modifiée sur ces champs'); END;

-- Un candidat ne devient ADMIS (élève) qu'après un test REUSSI, avec un matricule et une classe d'affectation
CREATE TRIGGER IF NOT EXISTS CANDIDATURE_ADMIS_EXIGE_TEST BEFORE UPDATE OF STATUT ON CANDIDATURE
WHEN NEW.STATUT = 'ADMIS' AND (NEW.RESULTAT_TEST IS NOT 'REUSSI' OR NEW.MATRICULE IS NULL OR NEW.N_CLASSE_AFFECTEE IS NULL)
BEGIN SELECT RAISE(ABORT, 'Admission refusée : le test doit être réussi, avec un matricule et une classe d''affectation'); END;

-- ===================== Gestion du personnel : dossier personnel =====================
-- Un agent = un dossier. Il n'est jamais supprimé : quand il quitte l'école on le DÉSACTIVE (son historique reste).
-- Le matricule (« P0001/26 ») est attribué par le système, ou saisi (matricule officiel) ; il ne change plus après création.
CREATE TABLE IF NOT EXISTS PERSONNEL (
    MATRICULE       TEXT PRIMARY KEY COLLATE NOCASE,
    NOM             TEXT NOT NULL,
    POSTNOM         TEXT,
    PRENOM          TEXT,
    SEXE            TEXT NOT NULL CHECK (SEXE IN ('M','F')),
    DATE_NAISSANCE  TEXT NOT NULL,                  -- AAAA-MM-JJ
    ADRESSE         TEXT NOT NULL,
    TELEPHONE       TEXT NOT NULL,
    EMAIL           TEXT,
    DATE_ENGAGEMENT TEXT NOT NULL,                  -- AAAA-MM-JJ
    FONCTION        TEXT NOT NULL,
    STATUT_PRO      TEXT NOT NULL,                  -- validé par l'application (personnel.STATUTS)
    ACTIF           INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    DATE_ENREG      TEXT NOT NULL,
    ENREGISTRE_PAR  TEXT NOT NULL,
    DATE_MODIF      TEXT,
    MODIFIE_PAR     TEXT
);
-- Documents administratifs numérisés (PDF, JPEG ou PNG) rangés dans la base : ils suivent donc les sauvegardes.
CREATE TABLE IF NOT EXISTS DOCUMENT_PERSONNEL (
    ID_DOC      INTEGER PRIMARY KEY AUTOINCREMENT,
    MATRICULE   TEXT    NOT NULL REFERENCES PERSONNEL(MATRICULE),
    TYPE_DOC    TEXT    NOT NULL,
    NOM_FICHIER TEXT    NOT NULL,
    FORMAT      TEXT    NOT NULL CHECK (FORMAT IN ('PDF','JPEG','PNG')),
    TAILLE      INTEGER NOT NULL,
    EMPREINTE   TEXT    NOT NULL,                   -- SHA-256 du contenu
    CONTENU     BLOB    NOT NULL,
    DATE_AJOUT  TEXT    NOT NULL,
    AJOUTE_PAR  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS IDX_DOCUMENT_PERSONNEL ON DOCUMENT_PERSONNEL (MATRICULE);

-- ===================== Gestion du personnel : fonctions et affectations =====================
-- Listes déterminées par l'école. Une fonction ou un service utilisé n'est jamais supprimé : on le désactive.
CREATE TABLE IF NOT EXISTS FONCTION_PERSONNEL (
    ID_FONCTION INTEGER PRIMARY KEY AUTOINCREMENT,
    LIBELLE     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    ACTIF       INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1))
);
CREATE TABLE IF NOT EXISTS SERVICE_PERSONNEL (
    ID_SERVICE INTEGER PRIMARY KEY AUTOINCREMENT,
    LIBELLE    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    ACTIF      INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1))
);
-- Une ligne = une période pendant laquelle l'agent occupe une fonction, dans un service et/ou avec une responsabilité.
-- Les lignes ne sont jamais supprimées : elles forment l'HISTORIQUE des changements de fonction.
-- DATE_FIN vide = affectation sans date de fin (en cours). Les périodes d'un même agent ne se chevauchent pas (contrôlé par l'application).
CREATE TABLE IF NOT EXISTS AFFECTATION (
    ID_AFF         INTEGER PRIMARY KEY AUTOINCREMENT,
    MATRICULE      TEXT    NOT NULL REFERENCES PERSONNEL(MATRICULE),
    ID_FONCTION    INTEGER NOT NULL REFERENCES FONCTION_PERSONNEL(ID_FONCTION),
    ID_SERVICE     INTEGER REFERENCES SERVICE_PERSONNEL(ID_SERVICE),
    RESPONSABILITE TEXT,                            -- ex. « Titulaire de la 3ème A », « Chef de service »
    DATE_DEBUT     TEXT    NOT NULL,                -- AAAA-MM-JJ
    DATE_FIN       TEXT,
    MOTIF          TEXT,
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    DATE_MODIF     TEXT,
    MODIFIE_PAR    TEXT,
    CHECK (DATE_FIN IS NULL OR DATE_FIN >= DATE_DEBUT)
);
CREATE INDEX IF NOT EXISTS IDX_AFFECTATION_AGENT ON AFFECTATION (MATRICULE, DATE_DEBUT);

-- ===================== Présence et absence (Gestion du personnel, 3ème fonctionnalité) =====================
-- Un enregistrement par agent et par jour. SOURCE : 'MANUEL' (saisie au clavier) ; 'BIOMETRIQUE' réservé au futur pointeur.
CREATE TABLE IF NOT EXISTS PRESENCE (
    ID_PRES        INTEGER PRIMARY KEY AUTOINCREMENT,
    MATRICULE      TEXT    NOT NULL REFERENCES PERSONNEL(MATRICULE),
    DATE_JOUR      TEXT    NOT NULL,                -- AAAA-MM-JJ
    STATUT         TEXT    NOT NULL CHECK (STATUT IN ('PRESENT','RETARD','ABSENT')),
    HEURE_ARRIVEE  TEXT,                            -- HH:MM
    MINUTES_RETARD INTEGER NOT NULL DEFAULT 0 CHECK (MINUTES_RETARD >= 0),
    MOTIF          TEXT,
    SOURCE         TEXT    NOT NULL DEFAULT 'MANUEL' CHECK (SOURCE IN ('MANUEL','BIOMETRIQUE')),
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    DATE_MODIF     TEXT,
    MODIFIE_PAR    TEXT,
    UNIQUE (MATRICULE, DATE_JOUR)
);
CREATE INDEX IF NOT EXISTS IDX_PRESENCE_JOUR ON PRESENCE (DATE_JOUR);
-- Permissions et congés : une période autorisée ; ses jours comptent comme « permission » ou « congé », jamais comme absence.
CREATE TABLE IF NOT EXISTS AUTORISATION_ABSENCE (
    ID_AUT         INTEGER PRIMARY KEY AUTOINCREMENT,
    MATRICULE      TEXT    NOT NULL REFERENCES PERSONNEL(MATRICULE),
    TYPE           TEXT    NOT NULL CHECK (TYPE IN ('PERMISSION','CONGE')),
    NATURE         TEXT,                            -- ex. « Congé de maladie », « Raison familiale »
    DATE_DEBUT     TEXT    NOT NULL,
    DATE_FIN       TEXT    NOT NULL,
    MOTIF          TEXT,
    STATUT         TEXT    NOT NULL DEFAULT 'ACCORDE' CHECK (STATUT IN ('ACCORDE','ANNULE')),
    MOTIF_ANNULATION TEXT,
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    DATE_ANNULATION TEXT,
    ANNULE_PAR     TEXT,
    CHECK (DATE_FIN >= DATE_DEBUT)
);
CREATE INDEX IF NOT EXISTS IDX_AUTORISATION_AGENT ON AUTORISATION_ABSENCE (MATRICULE, DATE_DEBUT);
-- Jours où l'école ne travaille pas (fêtes, vacances) : ils ne comptent pas dans les jours de travail. Samedi et dimanche : config.py.
CREATE TABLE IF NOT EXISTS JOUR_FERME (
    DATE_JOUR TEXT PRIMARY KEY,
    LIBELLE   TEXT NOT NULL
);

-- ===================== Direction des études : cours et enseignants =====================
-- Calendrier scolaire : dates d'une année scolaire (l'année elle-même est dans ANNEE_SCO), ses semestres, leurs périodes.
CREATE TABLE IF NOT EXISTS ANNEE_CALENDRIER (
    ANNEESCO   TEXT PRIMARY KEY REFERENCES ANNEE_SCO(ANNEESCO),
    DATE_DEBUT TEXT NOT NULL,                       -- AAAA-MM-JJ
    DATE_FIN   TEXT NOT NULL,
    CHECK (DATE_FIN > DATE_DEBUT)
);
CREATE TABLE IF NOT EXISTS SEMESTRE_SCO (
    ID_SEM     INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO   TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    LIBELLE    TEXT    NOT NULL,                    -- ex. « 1er semestre » (secondaire et humanitaire) ou « 1er trimestre » (primaire)
    DATE_DEBUT TEXT    NOT NULL,
    DATE_FIN   TEXT    NOT NULL,
    SECTION    TEXT    NOT NULL DEFAULT 'SECONDAIRE' CHECK (SECTION IN ('PRIMAIRE','SECONDAIRE')),   -- calendrier de quelle section
    CHECK (DATE_FIN >= DATE_DEBUT),
    UNIQUE (ANNEESCO, LIBELLE)
);
CREATE TABLE IF NOT EXISTS PERIODE_SCO (
    ID_PER     INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_SEM     INTEGER NOT NULL REFERENCES SEMESTRE_SCO(ID_SEM),
    LIBELLE    TEXT    NOT NULL,                    -- ex. « 1ère période », « Examens du 1er semestre »
    DATE_DEBUT TEXT    NOT NULL,
    DATE_FIN   TEXT    NOT NULL,
    CHECK (DATE_FIN >= DATE_DEBUT),
    UNIQUE (ID_SEM, LIBELLE)
);
-- Cours : définis une fois, pour un niveau, une option (si elle s'applique) et une année d'étude (si elle s'applique).
CREATE TABLE IF NOT EXISTS COURS (
    ID_COURS       INTEGER PRIMARY KEY AUTOINCREMENT,
    LIBELLE        TEXT    NOT NULL,
    CODE_NIVEAU    TEXT    NOT NULL REFERENCES NIVEAU(CODE_NIVEAU),
    CODE_OPTION    TEXT,                            -- vide : commun à toutes les options du niveau
    ANNEE_ETUDE    TEXT,                            -- vide : toutes les années d'étude du niveau (ex. « 3ème »)
    HEURES_SEMAINE INTEGER NOT NULL DEFAULT 0 CHECK (HEURES_SEMAINE BETWEEN 0 AND 40),
    ACTIF          INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    FOREIGN KEY (CODE_NIVEAU, CODE_OPTION) REFERENCES POSSEDE(CODE_NIVEAU, CODE_OPTION)
);
CREATE UNIQUE INDEX IF NOT EXISTS IDX_COURS_UNIQUE ON COURS (LIBELLE COLLATE NOCASE, CODE_NIVEAU, COALESCE(CODE_OPTION, ''),
                                                           COALESCE(ANNEE_ETUDE, ''));
-- Un cours donné dans une classe pendant une année scolaire, avec son professeur (un agent du personnel).
CREATE TABLE IF NOT EXISTS COURS_CLASSE (
    ID_CC          INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO       TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE       INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    ID_COURS       INTEGER NOT NULL REFERENCES COURS(ID_COURS),
    HEURES_SEMAINE INTEGER NOT NULL DEFAULT 0 CHECK (HEURES_SEMAINE BETWEEN 0 AND 40),
    MATRICULE_PROF TEXT REFERENCES PERSONNEL(MATRICULE),
    MAX_PERIODE    REAL,   -- secondaire : maximum d'une période fixé par le titulaire de la classe (examen = 2 x, semestre = 4 x, année = 8 x)
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    DATE_MODIF     TEXT,
    MODIFIE_PAR    TEXT,
    UNIQUE (ANNEESCO, N_CLASSE, ID_COURS)
);
CREATE INDEX IF NOT EXISTS IDX_COURS_CLASSE_PROF ON COURS_CLASSE (MATRICULE_PROF, ANNEESCO);

-- Saisie des points par les professeurs (page web : serveur_notes.py ; logique : notes.py)
-- Le compte de connexion d'un professeur est relié à son dossier d'agent : c'est ce lien (jamais une donnée envoyée par le
-- navigateur) qui décide de ce qu'il voit.
CREATE TABLE IF NOT EXISTS COMPTE_PROFESSEUR (
    ID_USER   INTEGER PRIMARY KEY REFERENCES UTILISATEUR(ID_USER),
    MATRICULE TEXT    NOT NULL UNIQUE REFERENCES PERSONNEL(MATRICULE)
);
-- Une évaluation = les points d'un cours dans une classe : PER = les points d'une période (un seul par cours, classe et période,
-- saisi à la fin de la période) ; EXA = l'examen du semestre (rangé dans la dernière période du semestre). Les types INT, DEV et IG
-- (interrogation, devoir, interrogation générale) n'existent plus à la saisie : ils restent permis pour conserver les anciens points.
-- MAXIMUM : points maximum.
""" + SCHEMA_EVALUATION + """
-- POINTS vide = pas de note (absent, pas encore corrigé) : la ligne n'existe simplement pas.
CREATE TABLE IF NOT EXISTS NOTE (
    ID_EVAL    INTEGER NOT NULL REFERENCES EVALUATION(ID_EVAL) ON DELETE CASCADE,
    MATRICULE  TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    POINTS     REAL    NOT NULL CHECK (POINTS >= 0),
    DATE_MODIF TEXT    NOT NULL,
    PRIMARY KEY (ID_EVAL, MATRICULE)
);
-- Conduite d'un élève pour une période, donnée par le professeur du cours (COTE : code de notes.COTES_CONDUITE)
CREATE TABLE IF NOT EXISTS CONDUITE (
    ID_CC      INTEGER NOT NULL REFERENCES COURS_CLASSE(ID_CC),
    ID_PER     INTEGER NOT NULL REFERENCES PERIODE_SCO(ID_PER),
    MATRICULE  TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    COTE       TEXT    NOT NULL,
    DATE_MODIF TEXT    NOT NULL,
    PRIMARY KEY (ID_CC, ID_PER, MATRICULE)
);

-- Présence des élèves à un cours (saisie par le professeur du cours : page web ; logique : presence_eleves.py).
-- Une ligne par élève pointé pour un cours et un jour : STATUT 'P' (présent) ou 'A' (absent). Pas de ligne = pas encore pointé.
-- Un élève est considéré présent pour la journée seulement s'il est présent à tous les cours pointés ce jour-là.
CREATE TABLE IF NOT EXISTS PRESENCE_ELEVE (
    ID_CC      INTEGER NOT NULL REFERENCES COURS_CLASSE(ID_CC) ON DELETE CASCADE,
    DATE_COURS TEXT    NOT NULL,
    MATRICULE  TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    STATUT     TEXT    NOT NULL CHECK (STATUT IN ('P','A')),
    DATE_MODIF TEXT    NOT NULL,
    MODIFIE_PAR TEXT   NOT NULL,
    PRIMARY KEY (ID_CC, DATE_COURS, MATRICULE)
);
CREATE INDEX IF NOT EXISTS IDX_PRESENCE_ELEVE_JOUR ON PRESENCE_ELEVE (DATE_COURS);

-- Direction de discipline > Gestion des présences (gestion_presences.py) : décision de la Direction sur la présence d'UN élève pour UNE journée.
-- Les pointages des professeurs (PRESENCE_ELEVE) ne sont jamais modifiés : la décision se superpose. GENRE 'CONFIRME' = la Direction confirme
-- le statut tiré des pointages (STATUT_PROF au moment de la décision) ; 'CORRIGE' = elle retient un autre statut, avec un motif. Une seule décision
-- ACTIVE par élève et par jour ; une nouvelle décision ou une annulation ne supprime rien : l'ancienne ligne reçoit ANNULE_LE / ANNULE_PAR / MOTIF_ANNULATION.
CREATE TABLE IF NOT EXISTS PRESENCE_DECISION (
    ID_DEC          INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO        TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE       TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE        INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    DATE_JOUR       TEXT    NOT NULL,
    STATUT_PROF     TEXT    NOT NULL DEFAULT '' CHECK (STATUT_PROF IN ('P','A','')),
    STATUT          TEXT    NOT NULL CHECK (STATUT IN ('P','A')),
    GENRE           TEXT    NOT NULL CHECK (GENRE IN ('CONFIRME','CORRIGE')),
    MOTIF           TEXT    NOT NULL DEFAULT '',
    DECIDE_LE       TEXT    NOT NULL,
    DECIDE_PAR      TEXT    NOT NULL,
    ANNULE_LE       TEXT,
    ANNULE_PAR      TEXT,
    MOTIF_ANNULATION TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS IDX_PRESENCE_DECISION_ACTIVE ON PRESENCE_DECISION (ANNEESCO, MATRICULE, DATE_JOUR) WHERE ANNULE_LE IS NULL;
CREATE INDEX IF NOT EXISTS IDX_PRESENCE_DECISION_CLASSE ON PRESENCE_DECISION (ANNEESCO, N_CLASSE, DATE_JOUR);

-- Direction de discipline > Suivi de la conduite (suivi_conduite.py) : observation disciplinaire, comportement inapproprié, incident ou mention
-- (positive ou négative, selon config.REGLEMENT_CONDUITE) enregistré par la Direction pour UN élève. GENRE : OBSERVATION (texte libre, nature
-- choisie, sans points), COMPORTEMENT, INCIDENT, MENTION. CODE / LIBELLE / GRAVITE / POINTS sont copiés du règlement au moment de l'enregistrement
-- (un changement ultérieur du règlement ne réécrit pas l'historique). Rien n'est supprimé : une annulation remplit ANNULE_LE / ANNULE_PAR / MOTIF_ANNULATION.
CREATE TABLE IF NOT EXISTS CONDUITE_OBSERVATION (
    ID_OBS          INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO        TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE       TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE        INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    DATE_FAIT       TEXT    NOT NULL,
    GENRE           TEXT    NOT NULL CHECK (GENRE IN ('OBSERVATION','COMPORTEMENT','INCIDENT','MENTION')),
    CODE            TEXT    NOT NULL DEFAULT '',
    LIBELLE         TEXT    NOT NULL DEFAULT '',
    NATURE          TEXT    NOT NULL CHECK (NATURE IN ('POSITIF','NEGATIF','NEUTRE')),
    GRAVITE         TEXT    NOT NULL DEFAULT '' CHECK (GRAVITE IN ('','LEGERE','MOYENNE','GRAVE')),
    POINTS          INTEGER NOT NULL DEFAULT 0,
    LIEU            TEXT    NOT NULL DEFAULT '',
    DESCRIPTION     TEXT    NOT NULL,
    MESURE          TEXT    NOT NULL DEFAULT '',
    ENREGISTRE_LE   TEXT    NOT NULL,
    ENREGISTRE_PAR  TEXT    NOT NULL,
    ANNULE_LE       TEXT,
    ANNULE_PAR      TEXT,
    MOTIF_ANNULATION TEXT
);
CREATE INDEX IF NOT EXISTS IDX_CONDUITE_OBS_ELEVE ON CONDUITE_OBSERVATION (MATRICULE, ANNEESCO);
CREATE INDEX IF NOT EXISTS IDX_CONDUITE_OBS_CLASSE ON CONDUITE_OBSERVATION (ANNEESCO, N_CLASSE, DATE_FAIT);

-- Direction de discipline > Convocation du parent (convocations.py) : convocation d'un parent ou tuteur pour un élève (motif, date, heure et lieu du
-- rendez-vous, instructions). STATUT : BROUILLON (enregistrée, pas envoyée), ENVOYEE (notification dans l'application des parents) ou ANNULEE (avec motif).
-- NOM_PARENT / TEL_PARENT sont copiés de la fiche de l'élève au moment de l'enregistrement. Rien n'est supprimé.
CREATE TABLE IF NOT EXISTS CONVOCATION_PARENT (
    ID_CONV         INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO        TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE       TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE        INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    NOM_PARENT      TEXT    NOT NULL DEFAULT '',
    TEL_PARENT      TEXT    NOT NULL DEFAULT '',
    MOTIF           TEXT    NOT NULL,
    DATE_RDV        TEXT    NOT NULL,                 -- AAAA-MM-JJ
    HEURE_RDV       TEXT    NOT NULL,                 -- HH:MM
    LIEU            TEXT    NOT NULL,
    INSTRUCTIONS    TEXT    NOT NULL DEFAULT '',
    STATUT          TEXT    NOT NULL DEFAULT 'BROUILLON' CHECK (STATUT IN ('BROUILLON','ENVOYEE','ANNULEE')),
    ENREGISTRE_LE   TEXT    NOT NULL,
    ENREGISTRE_PAR  TEXT    NOT NULL,
    ENVOYE_LE       TEXT,
    ENVOYE_PAR      TEXT,
    ANNULE_LE       TEXT,
    ANNULE_PAR      TEXT,
    MOTIF_ANNULATION TEXT
);
CREATE INDEX IF NOT EXISTS IDX_CONVOCATION_ELEVE ON CONVOCATION_PARENT (MATRICULE, ANNEESCO);
CREATE INDEX IF NOT EXISTS IDX_CONVOCATION_DATE ON CONVOCATION_PARENT (ANNEESCO, DATE_RDV);
-- Comptes parents (application mobile) qui ont reçu la notification d'une convocation ; LU_LE : le parent l'a ouverte.
CREATE TABLE IF NOT EXISTS CONVOCATION_DESTINATAIRE (
    ID_CONV    INTEGER NOT NULL REFERENCES CONVOCATION_PARENT(ID_CONV),
    ID_PARENT  INTEGER NOT NULL REFERENCES COMPTE_PARENT(ID_PARENT),
    ENVOYE_LE  TEXT    NOT NULL,
    LU_LE      TEXT,
    PRIMARY KEY (ID_CONV, ID_PARENT)
);
CREATE INDEX IF NOT EXISTS IDX_CONVOCATION_DEST_PARENT ON CONVOCATION_DESTINATAIRE (ID_PARENT);

-- Passage en classe supérieure (promotion.py). PROMOTION : une ligne par élève traité à la fin d'une année (ANNEESCO = année qui se termine) ;
-- DECISION : PROMU (classe supérieure), REDOUBLE (même classe), TERMINE (fin des études : N_CLASSE_DEST vide) ; STATUT : FAIT ou ANNULE
-- (la trace d'un passage annulé est gardée). PROMOTION_CHOIX : classe d'accueil saisie à l'avance par la direction des études (option de la 8ème),
-- supprimée dès que le passage de l'élève est exécuté.
CREATE TABLE IF NOT EXISTS PROMOTION (
    ANNEESCO         TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE        TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE         INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    ANNEESCO_DEST    TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE_DEST    INTEGER REFERENCES CLASSE(N_CLASSE),
    DECISION         TEXT    NOT NULL CHECK (DECISION IN ('PROMU','REDOUBLE','TERMINE')),
    POURCENTAGE      REAL,
    STATUT           TEXT    NOT NULL DEFAULT 'FAIT' CHECK (STATUT IN ('FAIT','ANNULE')),
    FAIT_LE          TEXT    NOT NULL,
    FAIT_PAR         TEXT    NOT NULL,
    ANNULE_LE        TEXT,
    ANNULE_PAR       TEXT,
    MOTIF_ANNULATION TEXT,
    PRIMARY KEY (ANNEESCO, MATRICULE)
);
CREATE INDEX IF NOT EXISTS IDX_PROMOTION_CLASSE ON PROMOTION (ANNEESCO, N_CLASSE, STATUT);
CREATE TABLE IF NOT EXISTS PROMOTION_CHOIX (
    ANNEESCO      TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE     TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    N_CLASSE_DEST INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    CHOISI_LE     TEXT    NOT NULL,
    CHOISI_PAR    TEXT    NOT NULL,
    PRIMARY KEY (ANNEESCO, MATRICULE)
);

-- Professeur titulaire d'une classe pour une année (un seul par classe et par année). Lui seul voit et lance la fonctionnalité
-- « Calcul automatique et bulletins » (bulletins.py) dans la page web des professeurs. Désigné par la direction des études
-- (Direction des études > Enseignants et classes) : le lien se lit dans la base à chaque appel.
CREATE TABLE IF NOT EXISTS TITULAIRE_CLASSE (
    ANNEESCO       TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE       INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    MATRICULE      TEXT    NOT NULL REFERENCES PERSONNEL(MATRICULE),
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    PRIMARY KEY (ANNEESCO, N_CLASSE)
);
CREATE INDEX IF NOT EXISTS IDX_TITULAIRE_PROF ON TITULAIRE_CLASSE (MATRICULE, ANNEESCO);

-- Périodes et examens dont le TITULAIRE d'une classe autorise la saisie aux professeurs de sa classe. Une ligne = une période
-- (CLE « P<id> ») ou un examen de semestre (CLE « X<id> ») ouvert à la saisie dans cette classe. Sans ligne, rien ne s'ouvre.
CREATE TABLE IF NOT EXISTS AUTORISATION_SAISIE (
    ANNEESCO       TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE       INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    CLE            TEXT    NOT NULL,
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    PRIMARY KEY (ANNEESCO, N_CLASSE, CLE)
);

-- ===================== Application mobile des parents (parents.py) =====================
-- Un parent a un compte (identifiant = téléphone ou e-mail). Il y accède à ses enfants grâce à un CODE D'ACCÈS : un code par
-- paiement validé du « frais du logiciel des parents » (TYPE_FRAIS.POUR_APPLI_PARENTS), donc un code = un élève, utilisable une seule fois.
CREATE TABLE IF NOT EXISTS COMPTE_PARENT (
    ID_PARENT          INTEGER PRIMARY KEY AUTOINCREMENT,
    IDENTIFIANT        TEXT    NOT NULL UNIQUE,
    NOM_COMPLET        TEXT    NOT NULL,
    MDP_HASH           TEXT    NOT NULL,
    ACTIF              INTEGER NOT NULL DEFAULT 1 CHECK (ACTIF IN (0,1)),
    DATE_CREATION      TEXT    NOT NULL,
    DERNIERE_CONNEXION TEXT,
    ECHECS             INTEGER NOT NULL DEFAULT 0,
    BLOQUE_JUSQUA      TEXT
);
CREATE TABLE IF NOT EXISTS CODE_PARENT (
    ID_CODE          INTEGER PRIMARY KEY AUTOINCREMENT,
    CODE             TEXT    NOT NULL UNIQUE,
    N_RECU           TEXT    NOT NULL UNIQUE REFERENCES PAIEMENT(N_RECU),
    MATRICULE        TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    ANNEESCO         TEXT    NOT NULL,
    DATE_GEN         TEXT    NOT NULL,
    ID_PARENT        INTEGER REFERENCES COMPTE_PARENT(ID_PARENT),      -- vide : code pas encore utilisé
    DATE_UTILISATION TEXT
);
CREATE TABLE IF NOT EXISTS ENFANT_PARENT (
    ID_LIEN    INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_PARENT  INTEGER NOT NULL REFERENCES COMPTE_PARENT(ID_PARENT),
    MATRICULE  TEXT    NOT NULL REFERENCES ELEVE(MATRICULE),
    DATE_LIEN  TEXT    NOT NULL,
    UNIQUE (ID_PARENT, MATRICULE)
);

-- ===================== Préfecture : décisions du Préfet et rapports des responsables (prefecture.py) =====================
-- Une décision n'est jamais supprimée : si elle est retirée, elle passe au statut ANNULEE avec le motif, l'auteur et la date.
CREATE TABLE IF NOT EXISTS DECISION_PREFET (
    ID_DECISION   INTEGER PRIMARY KEY AUTOINCREMENT,
    DATE_DECISION TEXT    NOT NULL,                       -- AAAA-MM-JJ
    CATEGORIE     TEXT    NOT NULL,                       -- clé de config.CATEGORIES_DECISION
    OBJET         TEXT    NOT NULL,
    DETAIL        TEXT    NOT NULL DEFAULT '',
    ANNEESCO      TEXT    REFERENCES ANNEE_SCO(ANNEESCO),
    MATRICULE     TEXT    REFERENCES ELEVE(MATRICULE),    -- élève concerné (facultatif)
    STATUT        TEXT    NOT NULL DEFAULT 'EN_VIGUEUR' CHECK (STATUT IN ('EN_VIGUEUR','ANNULEE')),
    DATE_ENREG    TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT   NOT NULL,
    DATE_ANNUL    TEXT,
    ANNULE_PAR    TEXT,
    MOTIF_ANNUL   TEXT
);
CREATE INDEX IF NOT EXISTS IDX_DECISION_PREFET_DATE ON DECISION_PREFET (DATE_DECISION);

-- Renvoi d'un élève par le Préfet (renvoi.py). L'élève renvoyé reste dans les archives avec TOUT son historique (reçus, notes, présences...) :
-- son dossier est simplement re-clé vers une clé d'archive (« 0007/26-R ») pour que son ancien matricule soit libéré.
-- Un renvoi n'est jamais supprimé ni modifié.
CREATE TABLE IF NOT EXISTS RENVOI (
    ID_RENVOI         INTEGER PRIMARY KEY AUTOINCREMENT,
    MATRICULE_ARCHIVE TEXT    NOT NULL UNIQUE COLLATE NOCASE REFERENCES ELEVE(MATRICULE),   -- clé actuelle du dossier de l'élève renvoyé
    ANCIEN_MATRICULE  TEXT    NOT NULL COLLATE NOCASE,                                      -- matricule qu'il portait (libéré, réattribuable)
    DATE_RENVOI       TEXT    NOT NULL,                                                     -- AAAA-MM-JJ
    MOTIF             TEXT    NOT NULL,
    ANNEESCO          TEXT    REFERENCES ANNEE_SCO(ANNEESCO),
    ID_DECISION       INTEGER REFERENCES DECISION_PREFET(ID_DECISION),
    DECIDE_PAR        TEXT    NOT NULL,
    DATE_ENREG        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS IDX_RENVOI_ANCIEN ON RENVOI (ANCIEN_MATRICULE);
CREATE TRIGGER IF NOT EXISTS RENVOI_NO_DELETE BEFORE DELETE ON RENVOI
BEGIN SELECT RAISE(ABORT, 'Un renvoi ne peut pas être supprimé'); END;
CREATE TRIGGER IF NOT EXISTS RENVOI_NO_UPDATE BEFORE UPDATE ON RENVOI
BEGIN SELECT RAISE(ABORT, 'Un renvoi ne peut pas être modifié'); END;

-- Numéros d'ordre libérés par un renvoi, par année d'inscription (2 chiffres) : le prochain élève inscrit cette année-là reçoit
-- d'abord le plus petit numéro libre, avant que le compteur MATRICULE_SEQ n'avance.
CREATE TABLE IF NOT EXISTS MATRICULE_LIBRE (
    ANNEE     TEXT    NOT NULL,
    ORDRE     INTEGER NOT NULL,
    LIBERE_LE TEXT    NOT NULL,
    PRIMARY KEY (ANNEE, ORDRE)
);

-- Rapport qu'un responsable (Direction des études, Direction de discipline) adresse au Préfet. Lecture seule pour le Préfet.
CREATE TABLE IF NOT EXISTS RAPPORT_RESPONSABLE (
    ID_RAPPORT   INTEGER PRIMARY KEY AUTOINCREMENT,
    ESPACE       TEXT    NOT NULL,                        -- clé du sous-menu de l'auteur (direction_etudes, direction_discipline)
    TITRE        TEXT    NOT NULL,
    CONTENU      TEXT    NOT NULL,
    DATE_RAPPORT TEXT    NOT NULL,                        -- AAAA-MM-JJ
    ANNEESCO     TEXT    REFERENCES ANNEE_SCO(ANNEESCO),
    DATE_ENREG   TEXT    NOT NULL,
    ID_USER      INTEGER REFERENCES UTILISATEUR(ID_USER),
    AUTEUR       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS IDX_RAPPORT_RESPONSABLE ON RAPPORT_RESPONSABLE (ESPACE, DATE_RAPPORT);

-- Direction des études : contrôle des notes (controle_notes.py). La direction demande à un professeur de saisir des points manquants
-- (TYPE 'MANQUANTE') ou de corriger des points déjà saisis (TYPE 'CORRECTION') pour un cours de classe et une période (CLE « P<id> ») ou
-- un examen (CLE « X<id> »). MATRICULE vide : toute la fiche ; sinon un élève précis. La direction ne modifie jamais un point : c'est le
-- professeur qui corrige, puis marque la demande « traitée ». STATUT : OUVERTE -> TRAITEE (par le professeur) ou ANNULEE (par la direction).
CREATE TABLE IF NOT EXISTS DEMANDE_CORRECTION (
    ID_DEMANDE     INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO       TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    ID_CC          INTEGER NOT NULL REFERENCES COURS_CLASSE(ID_CC),
    CLE            TEXT    NOT NULL,
    MATRICULE      TEXT    REFERENCES ELEVE(MATRICULE),
    TYPE           TEXT    NOT NULL CHECK (TYPE IN ('MANQUANTE','CORRECTION')),
    MOTIF          TEXT    NOT NULL,
    STATUT         TEXT    NOT NULL DEFAULT 'OUVERTE' CHECK (STATUT IN ('OUVERTE','TRAITEE','ANNULEE')),
    DATE_DEMANDE   TEXT    NOT NULL,
    DEMANDE_PAR    TEXT    NOT NULL,
    ID_USER        INTEGER REFERENCES UTILISATEUR(ID_USER),
    DATE_TRAITEMENT TEXT,
    TRAITE_PAR     TEXT,
    REPONSE        TEXT
);
CREATE INDEX IF NOT EXISTS IDX_DEMANDE_CORRECTION_CC ON DEMANDE_CORRECTION (ID_CC, STATUT);

-- ===================== Direction des études : élaboration horaire (horaires.py) =====================
-- Réglage des heures d'une vacation (matin ou après-midi) pour une année : début, durée d'un cours, nombre de cours avant et après la
-- pause, durée de la pause, récréation facultative (RECREATION_APRES = 0 : pas de récréation). Les créneaux se calculent à partir d'ici.
CREATE TABLE IF NOT EXISTS HORAIRE_PARAM (
    ANNEESCO         TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    VACATION         TEXT    NOT NULL CHECK (VACATION IN ('MATIN','APRES_MIDI')),
    DEBUT            TEXT    NOT NULL,                  -- HH:MM
    DUREE_COURS      INTEGER NOT NULL CHECK (DUREE_COURS BETWEEN 20 AND 120),
    NB_AVANT         INTEGER NOT NULL CHECK (NB_AVANT BETWEEN 1 AND 9),
    DUREE_PAUSE      INTEGER NOT NULL CHECK (DUREE_PAUSE BETWEEN 5 AND 90),
    NB_APRES         INTEGER NOT NULL CHECK (NB_APRES BETWEEN 0 AND 9),
    RECREATION_APRES INTEGER NOT NULL DEFAULT 0 CHECK (RECREATION_APRES BETWEEN 0 AND 9),
    DUREE_RECREATION INTEGER NOT NULL DEFAULT 10 CHECK (DUREE_RECREATION BETWEEN 5 AND 60),
    DATE_MODIF       TEXT    NOT NULL,
    MODIFIE_PAR      TEXT    NOT NULL,
    PRIMARY KEY (ANNEESCO, VACATION)
);
-- Horaire d'une classe pour une année (un seul par classe) : sa vacation et son état. BROUILLON : visible de la direction seule ;
-- PUBLIE : consultable par les professeurs et les responsables.
CREATE TABLE IF NOT EXISTS HORAIRE (
    ID_HOR         INTEGER PRIMARY KEY AUTOINCREMENT,
    ANNEESCO       TEXT    NOT NULL REFERENCES ANNEE_SCO(ANNEESCO),
    N_CLASSE       INTEGER NOT NULL REFERENCES CLASSE(N_CLASSE),
    VACATION       TEXT    NOT NULL CHECK (VACATION IN ('MATIN','APRES_MIDI')),
    STATUT         TEXT    NOT NULL DEFAULT 'BROUILLON' CHECK (STATUT IN ('BROUILLON','PUBLIE')),
    DATE_PUB       TEXT,
    PUBLIE_PAR     TEXT,
    DATE_ENREG     TEXT    NOT NULL,
    ENREGISTRE_PAR TEXT    NOT NULL,
    DATE_MODIF     TEXT,
    MODIFIE_PAR    TEXT,
    UNIQUE (ANNEESCO, N_CLASSE)
);
-- Une séance = un cours (COURS_CLASSE, donc son professeur) placé un jour, au Nième cours de la journée de la classe.
CREATE TABLE IF NOT EXISTS HORAIRE_SEANCE (
    ID_SEANCE INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_HOR    INTEGER NOT NULL REFERENCES HORAIRE(ID_HOR) ON DELETE CASCADE,
    JOUR      INTEGER NOT NULL,                         -- 0 = lundi ... 6 = dimanche
    ORDRE     INTEGER NOT NULL,                         -- 1 = premier cours de la journée
    ID_CC     INTEGER NOT NULL REFERENCES COURS_CLASSE(ID_CC),
    DATE_ENREG     TEXT NOT NULL,
    ENREGISTRE_PAR TEXT NOT NULL,
    UNIQUE (ID_HOR, JOUR, ORDRE)
);
CREATE INDEX IF NOT EXISTS IDX_SEANCE_CC ON HORAIRE_SEANCE (ID_CC);

-- Données d'ESSAI (Travaux techniques > Données d'essai) : une ligne par donnée créée pour les tests, afin de pouvoir
-- retirer exactement celles-là (et jamais les vraies données). TABLE_SQL : nom de la table ; CLE : sa clé (JSON).
CREATE TABLE IF NOT EXISTS DONNEE_ESSAI (
    TABLE_SQL TEXT NOT NULL,
    CLE       TEXT NOT NULL,
    PRIMARY KEY (TABLE_SQL, CLE)
);
"""

EMPREINTE_INITIALE = "0" * 64


# ------------------------------------------------------------------ temps
def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def lire_iso(texte: str) -> datetime:
    return datetime.fromisoformat(texte)


# ------------------------------------------------------------- connexion
_PG_VERIFIEES = set()            # bases PostgreSQL dont la structure a déjà été contrôlée dans ce processus


def connecter(chemin=None):
    """Ouvre la base. Si GESTSCO_DATABASE_URL est définie : PostgreSQL (pgconn.py) ; sinon le fichier SQLite `chemin`.
    Si sa structure est ancienne (ou si elle n'existe pas encore), elle est mise à jour automatiquement (voir
    migrations.py) : l'application ne démarre jamais avec des tables incomplètes."""
    import migrations
    url = config.url_postgresql()
    if url:
        import pgconn
        schema = pgconn.schema_de(chemin) if os.environ.get("GESTSCO_PG_ISOLER") else None
        conn = pgconn.connecter_pg(url, SCHEMA, schema)
        cle = (url, schema)
        if cle not in _PG_VERIFIEES:                  # contrôle de structure une seule fois par processus (pas à chaque requête web)
            migrations.mettre_a_jour(conn, chemin=conn.identifiant)
            _PG_VERIFIEES.add(cle)
        return conn
    chemin = chemin or config.FICHIER_BD
    conn = sqlite3.connect(chemin)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrations.mettre_a_jour(conn, chemin=chemin)
    if os.name != "nt":                      # sous Windows, le dossier LOCALAPPDATA est déjà privé
        try:
            os.chmod(chemin, 0o600)
        except OSError:
            pass
    return conn


# --------------------------------------------------------------- journal
def _calculer_empreinte(prec, date, id_user, login, action, detail) -> str:
    bloc = json.dumps([prec, date, id_user, login, action, detail], ensure_ascii=False)
    return hashlib.sha256(bloc.encode("utf-8")).hexdigest()


def journaliser(conn, id_user, login, action, detail=""):
    """Ajoute une ligne au journal. Ne valide pas la transaction (c'est l'appelant qui le fait)."""
    ligne = conn.execute("SELECT EMPREINTE FROM JOURNAL ORDER BY ID_LOG DESC LIMIT 1").fetchone()
    prec = ligne["EMPREINTE"] if ligne else EMPREINTE_INITIALE
    date = iso(maintenant())
    empreinte = _calculer_empreinte(prec, date, id_user, login, action, detail)
    conn.execute(
        "INSERT INTO JOURNAL (DATE_HEURE, ID_USER, LOGIN, ACTION, DETAIL, EMPREINTE_PREC, EMPREINTE) "
        "VALUES (?,?,?,?,?,?,?)",
        (date, id_user, login, action, detail, prec, empreinte),
    )


def verifier_journal(conn):
    """Contrôle la chaîne d'empreintes. Retourne (True, None) ou (False, ID_LOG de la 1re anomalie)."""
    prec = EMPREINTE_INITIALE
    for l in conn.execute("SELECT * FROM JOURNAL ORDER BY ID_LOG"):
        attendu = _calculer_empreinte(prec, l["DATE_HEURE"], l["ID_USER"], l["LOGIN"], l["ACTION"], l["DETAIL"])
        if l["EMPREINTE_PREC"] != prec or l["EMPREINTE"] != attendu:
            return False, l["ID_LOG"]
        prec = l["EMPREINTE"]
    return True, None
