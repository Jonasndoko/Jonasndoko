"""Données d'ESSAI : de quoi tester toute l'application sans toucher aux vraies données, puis tout retirer d'un clic.

Installation (Administrateur, Travaux techniques > Données d'essai) :
- 120 élèves fictifs (minimum 100), inscrits dans les classes EXISTANTES de l'année en cours ;
- 5 types de frais d'essai (code « ESS-... ») dont le frais scolaire qui dépend de la classe (300 en 1ère, 2ème et 3ème,
  600 en 4ème, payé en tranches libres) et une assurance payée en 3 tranches au niveau du type de frais ;
- 1 compte par poste (Administrateur, Préfet, Secrétaire, Intendant, 2 Percepteurs, Contrôleur, Directrice des études),
  avec un mot de passe aléatoire montré UNE fois et enregistré dans un fichier ;
- des opérations réelles, faites avec ces comptes par les vraies fonctions de l'application : connexions (dont un échec),
  paiements par tranches, annulations, encaissements (avec écart, correction, suppression), consultations de dossiers.
  Tout est donc visible dans le journal et dans la Traçabilité et audit.

Suppression : ne retire QUE ce qui a été créé pour l'essai (registre DONNEE_ESSAI) et ce qui s'y rattache (les reçus des
élèves ou des frais d'essai, les encaissements des percepteurs d'essai). Les vraies données ne sont jamais touchées.
Le compteur des matricules revient à sa valeur d'avant (si aucun vrai élève n'a été ajouté depuis). Le journal, lui,
est en ajout seulement : les traces de l'essai y restent, et le contrôle de concordance sait qu'elles sont retirées.
"""
import json
import os
import random
from datetime import date

import argent
import config
import donnees
import droits
import encaissements
import identite
import paiements
import referentiels
import sauvegarde
import security
from database import journaliser
from security import Session

NB_MIN, NB_DEFAUT, NB_MAX = 100, 120, 600
PHRASE_SUPPRESSION = "SUPPRIMER"
PREFIXE_LOGIN = "essai."
PREFIXE_FRAIS = "ESS-"
FICHIER_COMPTES = "comptes_essai.txt"

# frais d'essai : (code, désignation, mode)
TYPES = (
    ("ESS-INS", "Frais d'inscription (essai)"),
    ("ESS-MIN", "Frais scolaire - minerval (essai)"),
    ("ESS-EXA", "Frais d'examen (essai)"),
    ("ESS-BIB", "Frais de bibliothèque (essai)"),
    ("ESS-ASS", "Assurance scolaire (essai)"),
)

# comptes d'essai : (login, nom complet, poste, droits supplémentaires pour pouvoir tout essayer)
_TOUS = ("LECTURE", "AJOUT", "MODIFICATION", "SUPPRESSION")
COMPTES = (
    ("essai.administrateur", "Essai Administrateur", "ADMINISTRATEUR", ()),
    ("essai.prefet", "Essai Préfet", "PREFET",
     (("tableau", "LECTURE"), ("audit", "LECTURE"), ("controle", "LECTURE"), ("carte", "LECTURE"))),
    ("essai.secretaire", "Essai Secrétaire", "SECRETAIRE",
     (("carte", "LECTURE"), ("carte", "AJOUT"), ("carte", "MODIFICATION"), ("controle", "LECTURE"), ("tableau", "LECTURE"))),
    ("essai.intendant", "Essai Intendant", "INTENDANT",
     tuple(("encaissement", d) for d in _TOUS) + (("tableau", "LECTURE"), ("audit", "LECTURE"))),
    ("essai.percepteur1", "Essai Percepteur 1", "PERCEPTEUR", (("encaissement", "LECTURE"),)),
    ("essai.percepteur2", "Essai Percepteur 2", "PERCEPTEUR", (("encaissement", "LECTURE"),)),
    ("essai.controleur", "Essai Contrôleur", "CONTROLEUR",
     tuple(("controle", d) for d in _TOUS) + (("carte", "LECTURE"), ("audit", "LECTURE"))),
    ("essai.directrice", "Essai Directrice des études", "DIRECTRICE_ETUDES",
     (("tableau", "LECTURE"), ("carte", "LECTURE"), ("controle", "LECTURE"), ("paiement", "LECTURE"),
      ("presence_eleves", "LECTURE"))),
    ("essai.discipline", "Essai Directeur de discipline", "DIRECTEUR_DISCIPLINE", (("presence_eleves", "LECTURE"),)),
)

NOMS = ("MBUYI", "KALALA", "NGOY", "MUKENDI", "KABONGO", "TSHIALA", "MUTOMBO", "ILUNGA", "LUKUSA", "BANZA", "KASONGO",
        "MWAMBA", "TSHISEKEDI", "KABILA", "MUKWEGE", "LUMUMBA", "NZUZI", "MAKIESE", "BOLINGO", "KITENGE", "MULAMBA",
        "NTUMBA", "KAZADI", "MUJINGA", "KANKU", "BEYA", "MASUDI", "KIMBEMBE", "NSIMBA", "LOKUA")
POSTNOMS = ("KALALA", "MUKENDI", "TSHIALA", "ILUNGA", "BANZA", "MWAMBA", "NGANDU", "KABEYA", "TSHIBANGU", "LUBOYA",
            "MBAYA", "SAKA", "KIALA", "MAVUNGU", "LUZOLO", "NKULU", "KAPINGA", "MULUMBA", "KALENGA", "MUTEBA")
PRENOMS_M = ("Jean-Pierre", "Samuel", "Émile", "Joseph", "Patrick", "Daniel", "Christian", "David", "Gédéon", "Fiston",
             "Prince", "Héritier", "Trésor", "Merveille", "Jonathan", "Moïse", "Arnold", "Bienvenu", "Cédric", "Dieudonné")
PRENOMS_F = ("Béatrice", "Grâce", "Ruth", "Esther", "Sarah", "Divine", "Chantal", "Pascaline", "Nadège", "Mireille",
             "Sifa", "Gloria", "Dorcas", "Rebecca", "Léa", "Joëlle", "Prisca", "Révélation", "Bénédicte", "Madeleine")
COMMUNES = ("Gombe", "Lingwala", "Kalamu", "Ngaliema", "Limete", "Kasa-Vubu", "Bandalungwa", "Masina", "Lemba", "Barumbu")


class ErreurEssai(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== registre
def _noter(conn, table, cle):
    conn.execute("INSERT OR IGNORE INTO DONNEE_ESSAI (TABLE_SQL, CLE) VALUES (?, ?)", (table, str(cle)))


def _cles(conn, table) -> list:
    return [l[0] for l in conn.execute("SELECT CLE FROM DONNEE_ESSAI WHERE TABLE_SQL = ? ORDER BY CLE", (table,))]


def _liste(valeurs) -> list:
    return list(valeurs)


def _dans(conn, sql, valeurs, avant=()):
    """Exécute `sql` (qui contient « {} » pour la liste de « ? ») par paquets, pour les longues listes. Retourne le total
    des lignes touchées."""
    valeurs, total = _liste(valeurs), 0
    for i in range(0, len(valeurs), 400):
        paquet = valeurs[i:i + 400]
        total += conn.execute(sql.format(",".join("?" * len(paquet))), (*avant, *paquet)).rowcount
    return total


def _lire_dans(conn, sql, valeurs) -> list:
    valeurs, lignes = _liste(valeurs), []
    for i in range(0, len(valeurs), 400):
        paquet = valeurs[i:i + 400]
        lignes += conn.execute(sql.format(",".join("?" * len(paquet))), paquet).fetchall()
    return lignes


def installe(conn) -> bool:
    return conn.execute("SELECT 1 FROM DONNEE_ESSAI LIMIT 1").fetchone() is not None


def apercu(conn, session) -> dict:
    """Ce qui est actuellement installé pour l'essai (tout à zéro si rien)."""
    droits.exiger_admin(conn, session)
    eleves, types, users = _cles(conn, "ELEVE"), _cles(conn, "TYPE_FRAIS"), _cles(conn, "UTILISATEUR")
    recus, enc = _recus_et_encaissements(conn, eleves, types, users)
    return {"installe": installe(conn), "eleves": len(eleves), "types": len(types), "comptes": len(users),
            "recus": len(recus), "encaissements": len(enc)}


def _recus_et_encaissements(conn, eleves, types, users):
    """(lignes de reçus, lignes d'encaissements) qui appartiennent à l'essai (par élève, type de frais ou percepteur)."""
    recus = {}
    for l in _lire_dans(conn, "SELECT N_RECU, NUM_SEQ FROM PAIEMENT WHERE MATRICULE IN ({})", eleves) + \
            _lire_dans(conn, "SELECT N_RECU, NUM_SEQ FROM PAIEMENT WHERE CODTF IN ({})", types):
        recus[l["N_RECU"]] = l["NUM_SEQ"]
    percs = [l[0] for l in _lire_dans(conn, "SELECT N_PERC FROM PERCEPTEUR WHERE ID_USER IN ({})", users)]
    enc = [l[0] for l in _lire_dans(conn, "SELECT N_ENC FROM ENCAISSEMENT WHERE N_PERC IN ({})", percs)]
    return recus, enc


# ================================================================== installation
def _montant_selon_classe(annee_etude, devise_facteur):
    """(montant en centimes, tranches) du frais scolaire d'une classe : 600 en 4ème, 300 en 1ère-3ème, 250 en 7ème-8ème
    (tranches libres : nombre et montants différents d'une classe à l'autre)."""
    chiffre = next((int(c) for c in (annee_etude or "") if c.isdigit()), None)
    f = devise_facteur * 100
    if chiffre == 4:
        t = (200 * f, 200 * f, 100 * f, 100 * f)          # 4 tranches inégales
    elif chiffre in (7, 8):
        t = (125 * f, 125 * f)                              # 2 tranches
    elif chiffre in (1, 2, 3):
        t = (100 * f, 100 * f, 100 * f)                     # 3 tranches égales
    else:
        t = (150 * f, 150 * f)
    return sum(t), t


def _eleves_fictifs(n, annee_courante) -> list:
    alea = random.Random(2026)
    vus, resultat = set(), []
    while len(resultat) < n:
        sexe = alea.choice("MF")
        nom, post = alea.choice(NOMS), alea.choice(POSTNOMS)
        prenom = alea.choice(PRENOMS_M if sexe == "M" else PRENOMS_F)
        if (nom, post, prenom) in vus:
            continue
        vus.add((nom, post, prenom))
        resultat.append((nom, post, prenom, sexe, alea))
    return resultat


def _creer_comptes(conn, session) -> dict:
    """Crée les comptes d'essai. Retourne {login: (id_user, poste, mot de passe)}."""
    comptes = {}
    for login, nom, role, extras in COMPTES:
        if conn.execute("SELECT 1 FROM UTILISATEUR WHERE LOGIN = ?", (login,)).fetchone():
            raise ErreurEssai(f"Le compte « {login} » existe déjà : supprimez-le (ou renommez-le) avant d'installer l'essai.")
        mdp = security.generer_mdp_temporaire(login)
        id_user = security.creer_utilisateur(conn, login, nom, role, mdp, id_acteur=session.id_user)
        with conn:
            _noter(conn, "UTILISATEUR", id_user)
            if extras:
                droits.remplacer_droits(conn, id_user, droits.droits_utilisateur(conn, id_user) | set(extras))
        comptes[login] = (id_user, role, mdp)
    return comptes


def _fichier_comptes(comptes) -> str:
    dossier = config.dossier_donnees() / "essai"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / FICHIER_COMPTES
    lignes = ["COMPTES D'ESSAI - GESTSCO", "",
              "Ces comptes et leurs données disparaissent avec « Supprimer les données d'essai ».",
              "Ne réutilisez jamais ces mots de passe ailleurs.", ""]
    for login, (_id, role, mdp) in comptes.items():
        lignes.append(f"{config.LIBELLE_ROLES.get(role, role):<26} identifiant : {login:<22} mot de passe : {mdp}")
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    try:
        os.chmod(chemin, 0o600)
    except OSError:
        pass
    return str(chemin)


def installer(conn, session, nb_eleves=NB_DEFAUT) -> dict:
    """Installe les données d'essai. Retourne {'comptes': [(login, poste, mot de passe)], 'fichier': chemin, ...}."""
    droits.exiger_admin(conn, session)
    if installe(conn):
        raise ErreurEssai("Des données d'essai sont déjà installées : supprimez-les d'abord.")
    if not isinstance(nb_eleves, int) or not (NB_MIN <= nb_eleves <= NB_MAX):
        raise ErreurEssai(f"Le nombre d'élèves d'essai doit être compris entre {NB_MIN} et {NB_MAX}.")
    classes = conn.execute("SELECT N_CLASSE, DESI_CLASSE, ANNEE_ETUDE FROM CLASSE WHERE ACTIF = 1 ORDER BY N_CLASSE").fetchall()
    if not classes:
        raise ErreurEssai("Aucune classe active : créez d'abord les classes (Travaux techniques > Mise à jour des tables).")

    sauvegarde.sauvegarde_securite(conn, "Avant-donnees-essai")
    try:
        return _installer(conn, session, nb_eleves, classes)
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        try:
            _effacer(conn)                                      # rien ne reste d'une installation interrompue
        except Exception:
            pass
        raise


def _installer(conn, session, nb_eleves, classes) -> dict:
    # ---- année, devise (celles qui existent ; sinon une année et une devise d'essai)
    with conn:
        annee = donnees.annee_courante(conn)
        if not annee:
            annee = f"{date.today().year}-{date.today().year + 1}"
            conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES (?, 1)", (annee,))
            _noter(conn, "ANNEE_SCO", annee)
        ligne = conn.execute("SELECT CODE_DEVISE FROM DEVISE WHERE ACTIF = 1 "
                             "ORDER BY CASE CODE_DEVISE WHEN 'USD' THEN 0 ELSE 1 END, CODE_DEVISE").fetchone()
        if ligne:
            devise = ligne["CODE_DEVISE"]
        else:
            devise = "USD"
            conn.execute("INSERT INTO DEVISE (CODE_DEVISE, DESI_DEVISE) VALUES ('USD', 'Dollar américain')")
            _noter(conn, "DEVISE", "USD")
    facteur = 2500 if devise.upper() in ("CDF", "FC") else 1          # un montant de 300 serait dérisoire en francs

    # ---- types de frais et tarifs par classe
    f = 100 * facteur
    with conn:
        conn.executemany(
            "INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, PAR_TRANCHE, TRANCHES) VALUES (?,?,?,?,?,?)", [
                ("ESS-INS", TYPES[0][1], 20 * f, devise, 0, None),
                ("ESS-MIN", TYPES[1][1], None, None, 1, None),                    # le montant dépend de la classe : TARIF
                ("ESS-EXA", TYPES[2][1], 15 * f, devise, 0, None),
                ("ESS-BIB", TYPES[3][1], 5 * f, devise, 0, None),
                ("ESS-ASS", TYPES[4][1], 30 * f, devise, 1, donnees.ecrire_tranches((10 * f, 10 * f, 10 * f)))])
        for codtf, _d in TYPES:
            _noter(conn, "TYPE_FRAIS", codtf)
        for c in classes:
            montant, tranches = _montant_selon_classe(c["ANNEE_ETUDE"] or c["DESI_CLASSE"], facteur)
            conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE, TRANCHES) VALUES (?,?,?,?,?,?)",
                         ("ESS-MIN", c["N_CLASSE"], annee, montant, devise, donnees.ecrire_tranches(tranches)))

    # ---- élèves : matricules attribués par le système, inscrits dans les classes existantes
    jour = date.today()
    an2 = f"{jour.year % 100:02d}"
    avant = conn.execute("SELECT DERNIER FROM MATRICULE_SEQ WHERE ANNEE = ?", (an2,)).fetchone()
    avant = avant["DERNIER"] if avant else 0
    matricules = {}                                       # matricule -> N_CLASSE
    with conn:
        for i, (nom, post, prenom, sexe, alea) in enumerate(_eleves_fictifs(nb_eleves, annee)):
            c = classes[i % len(classes)]
            chiffre = next((int(x) for x in (c["ANNEE_ETUDE"] or "") if x.isdigit()), 1)
            naissance = date(max(1995, jour.year - 5 - chiffre - alea.randint(0, 1)), alea.randint(1, 12), alea.randint(1, 28))
            valeurs = {"NOM": nom, "POSTNOM": post, "PRENOM": prenom, "SEXE": sexe,
                       "DATE_NAISSANCE": naissance.isoformat(), "LIEU_NAISSANCE": "Kinshasa",
                       "ADRESSE": f"Av. de l'Essai {alea.randint(1, 99)}, {alea.choice(COMMUNES)}",
                       "TELEPHONE": "08" + "".join(str(alea.randint(0, 9)) for _ in range(8)),
                       "NOM_TUTEUR": f"M. ou Mme {nom}", "TEL_TUTEUR": "08" + "".join(str(alea.randint(0, 9)) for _ in range(8)),
                       "NATIONALITE": "Congolaise"}
            identite.generer(conn, valeurs)
            conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE, DATE_NAISSANCE, LIEU_NAISSANCE, ADRESSE, "
                         "TELEPHONE, NOM_TUTEUR, TEL_TUTEUR, NATIONALITE, CODE_QR) VALUES "
                         "(:MATRICULE,:NOM,:POSTNOM,:PRENOM,:SEXE,:DATE_NAISSANCE,:LIEU_NAISSANCE,:ADRESSE,:TELEPHONE,"
                         ":NOM_TUTEUR,:TEL_TUTEUR,:NATIONALITE,:CODE_QR)", valeurs)
            conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE, DATE_INSCRIPTION, STATUT) VALUES (?,?,?,?,?)",
                         (annee, valeurs["MATRICULE"], c["N_CLASSE"], jour.isoformat(), "NOUVEAU"))
            _noter(conn, "ELEVE", valeurs["MATRICULE"])
            matricules[valeurs["MATRICULE"]] = c["N_CLASSE"]
        apres = conn.execute("SELECT DERNIER FROM MATRICULE_SEQ WHERE ANNEE = ?", (an2,)).fetchone()["DERNIER"]
        _noter(conn, "MATRICULE_SEQ", json.dumps({"ANNEE": an2, "AVANT": avant, "APRES": apres}))

    # ---- comptes (1 par poste) puis connexions réelles
    comptes = _creer_comptes(conn, session)
    fichier = _fichier_comptes(comptes)
    sessions = {}
    echec = security.authentifier(conn, "essai.prefet", "mot-de-passe-faux-1")        # un échec, pour le journal
    if echec.ok:
        raise ErreurEssai("Contrôle de connexion inattendu.")
    for login, (_id, _role, mdp) in comptes.items():
        r = security.authentifier(conn, login, mdp)
        if not r.ok:
            raise ErreurEssai(f"Connexion d'essai impossible pour {login} : {r.message}")
        sessions[login] = r.session

    # ---- opérations (vraies fonctions, session de chaque utilisateur)
    nb = _operations(conn, sessions, matricules, annee, devise, facteur)
    for s in sessions.values():
        security.fermer_session(conn, s)
    with conn:
        journaliser(conn, session.id_user, session.login, "DONNEES_ESSAI_AJOUTEES",
                    f"{len(matricules)} élèves | {len(TYPES)} types de frais | {len(comptes)} comptes | "
                    f"{nb['recus']} reçus ({nb['annules']} annulés) | {nb['encaissements']} encaissements")
    conn.commit()
    return {"comptes": [(l, config.LIBELLE_ROLES.get(r, r), m) for l, (_i, r, m) in comptes.items()],
            "fichier": fichier, "eleves": len(matricules), "annee": annee, "devise": devise, **nb}


# profil de paiement d'un élève (i % 6) : nombre de tranches payées par frais (None : tout le frais)
_PROFILS = (
    {"ESS-INS": None, "ESS-MIN": None, "ESS-EXA": None, "ESS-BIB": None, "ESS-ASS": None},      # tout soldé
    {"ESS-INS": None, "ESS-MIN": 1},
    {"ESS-INS": None, "ESS-MIN": 2},
    {"ESS-INS": None},
    {},                                                                                           # rien payé
    {"ESS-INS": None, "ESS-MIN": 1, "ESS-BIB": None, "ESS-ASS": 1},
)


def _payer(conn, caissier, matricule, n_classe, annee, codtf, nb_tranches) -> list:
    """Paie `nb_tranches` tranches (ou tout) du frais, un reçu par tranche. Retourne les numéros de reçu."""
    du = donnees.conditions_du(conn, codtf, n_classe, annee)
    par = bool(conn.execute("SELECT PAR_TRANCHE FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()[0])
    pal = donnees.paliers(du[2], du[0], par)
    recus, deja = [], 0
    for palier in pal[:nb_tranches] if nb_tranches else pal:
        n = paiements.enregistrer_paiement(conn, caissier, matricule, annee, codtf, palier - deja)
        _noter(conn, "PAIEMENT", n)
        recus.append(n)
        deja = palier
    return recus


def _operations(conn, s, matricules, annee, devise, facteur) -> dict:
    perc = (s["essai.percepteur1"], s["essai.percepteur2"])
    recus = []                                            # (n° de reçu, matricule, perc)
    for i, (mat, n_classe) in enumerate(matricules.items()):
        caissier = perc[i % 2]
        for codtf, k in _PROFILS[i % len(_PROFILS)].items():
            for n in _payer(conn, caissier, mat, n_classe, annee, codtf, k):
                recus.append((n, mat, caissier))

    # annulations (Administrateur d'essai) : 3 reçus, puis l'un d'eux est réencaissé
    annules = [recus[j] for j in (5, len(recus) // 2, len(recus) - 3)]
    for n, _mat, _c in annules:
        referentiels.annuler_paiement(conn, s["essai.administrateur"], n, "Essai : erreur de saisie du percepteur")
    n, mat, caissier = annules[0]
    mont = conn.execute("SELECT MONT_PAYE, CODTF FROM PAIEMENT WHERE N_RECU = ?", (n,)).fetchone()
    nouveau = paiements.enregistrer_paiement(conn, caissier, mat, annee, mont["CODTF"], mont["MONT_PAYE"])
    _noter(conn, "PAIEMENT", nouveau)

    # encaissements du jour (Intendant d'essai) : p1 correct après une correction ; p2 avec un manquant de 5,00
    aujourdhui, intendant = date.today(), s["essai.intendant"]
    for k, p in enumerate(perc):
        n_perc = paiements.numero_percepteur(conn, p)
        total = conn.execute("SELECT COALESCE(SUM(MONT_PAYE), 0) FROM PAIEMENT WHERE N_PERC = ? AND STATUT = 'VALIDE' "
                             "AND CODE_DEVISE = ?", (n_perc, devise)).fetchone()[0]       # compte neuf : que des reçus d'essai
        total_local = max(total, 1)
        if k == 0:                                         # saisie fausse corrigée ensuite
            n_enc = encaissements.enregistrer(conn, intendant, n_perc, aujourdhui, devise, total_local + 1000, total_local + 1000)
            _noter(conn, "ENCAISSEMENT", n_enc)
            encaissements.modifier(conn, intendant, n_enc, n_perc, aujourdhui, devise, total_local, total_local)
        else:                                              # saisie en double supprimée, puis saisie juste avec écart
            double = encaissements.enregistrer(conn, intendant, n_perc, aujourdhui, devise, total_local, total_local)
            _noter(conn, "ENCAISSEMENT", double)
            encaissements.supprimer(conn, intendant, double)
            n_enc = encaissements.enregistrer(conn, intendant, n_perc, aujourdhui, devise, total_local,
                                              max(0, total_local - 5 * 100 * facteur))
            _noter(conn, "ENCAISSEMENT", n_enc)

    # consultations de dossiers par les autres postes
    import carte
    liste = list(matricules)
    for k, login in enumerate(("essai.secretaire", "essai.controleur", "essai.directrice")):
        for mat in liste[k * 3:k * 3 + 3]:
            try:
                carte.journaliser_consultation(conn, s[login], mat)
            except PermissionError:
                pass
    for mat in liste[:3]:
        paiements.journaliser_consultation_recus(conn, s["essai.percepteur1"], mat)
    conn.commit()
    return {"recus": len(recus) + 1, "annules": len(annules), "encaissements": 3}


# ================================================================== suppression
def supprimer(conn, session, mot_de_passe, confirmation) -> dict:
    """Retire les données d'essai (et seulement elles). Mot de passe de l'Administrateur et phrase de confirmation."""
    droits.exiger_admin(conn, session)
    if (confirmation or "").strip().upper() != PHRASE_SUPPRESSION:
        raise ErreurEssai(f"Tapez exactement « {PHRASE_SUPPRESSION} » pour confirmer.")
    ligne = conn.execute("SELECT MDP_HASH FROM UTILISATEUR WHERE ID_USER = ?", (session.id_user,)).fetchone()
    if not ligne or not security.verifier_mdp(mot_de_passe or "", ligne["MDP_HASH"]):
        with conn:
            journaliser(conn, session.id_user, session.login, "DONNEES_ESSAI_REFUSEES", "mot de passe incorrect")
        raise ErreurEssai("Mot de passe incorrect.")
    if not installe(conn):
        raise ErreurEssai("Il n'y a aucune donnée d'essai à supprimer.")
    securite = sauvegarde.sauvegarde_securite(conn, "Avant-suppression-essai")
    conn.commit()
    effaces = _effacer(conn, session, securite.name)
    effaces["securite"] = securite
    return effaces


def _effacer(conn, session=None, nom_securite="") -> dict:
    eleves, types, users = _cles(conn, "ELEVE"), _cles(conn, "TYPE_FRAIS"), _cles(conn, "UTILISATEUR")
    recus, enc = _recus_et_encaissements(conn, eleves, types, users)
    recus_tous = set(recus) | set(_cles(conn, "PAIEMENT"))
    enc_tous = {int(x) for x in enc} | {int(x) for x in _cles(conn, "ENCAISSEMENT")}
    nums = {n for n in recus.values()}
    percs = [l[0] for l in _lire_dans(conn, "SELECT N_PERC FROM PERCEPTEUR WHERE ID_USER IN ({})", users)]
    effaces = {"élèves": len(eleves), "types de frais": len(types), "comptes": len(users),
               "reçus": len(recus), "encaissements": len(enc)}

    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    try:
        # les reçus sont protégés contre la suppression : protections retirées le temps de l'opération, remises après
        conn.execute("DROP TRIGGER IF EXISTS PAIEMENT_NO_DELETE")
        with conn:
            _dans(conn, "DELETE FROM PAIEMENT WHERE MATRICULE IN ({})", eleves)
            _dans(conn, "DELETE FROM PAIEMENT WHERE CODTF IN ({})", types)
            _dans(conn, "DELETE FROM ENCAISSEMENT WHERE N_PERC IN ({})", percs)
            _dans(conn, "DELETE FROM INSCRIRE WHERE MATRICULE IN ({})", eleves)
            _dans(conn, "DELETE FROM PHOTO_ELEVE WHERE MATRICULE IN ({})", eleves)
            _dans(conn, "DELETE FROM DOSSIER_ELEVE WHERE MATRICULE IN ({})", eleves)
            _dans(conn, "DELETE FROM ELEVE WHERE MATRICULE IN ({})", eleves)
            _dans(conn, "DELETE FROM TARIF WHERE CODTF IN ({})", types)
            _dans(conn, "DELETE FROM TYPE_FRAIS WHERE CODTF IN ({})", types)

            # comptes : supprimés, sauf si un vrai reçu y est rattaché (le compte est alors seulement désactivé)
            gardes = set()
            for l in _lire_dans(conn, "SELECT DISTINCT N_PERC FROM PAIEMENT WHERE N_PERC IN ({})", percs):
                gardes.add(l[0])
            garder_users = {l[0] for l in _lire_dans(conn, "SELECT ID_USER FROM PERCEPTEUR WHERE N_PERC IN ({})", gardes)} \
                if gardes else set()
            a_retirer = [u for u in users if int(u) not in garder_users]
            if garder_users:
                _dans(conn, "UPDATE UTILISATEUR SET ACTIF = 0 WHERE ID_USER IN ({})", garder_users)
            logins = [l[0] for l in _lire_dans(conn, "SELECT LOGIN FROM UTILISATEUR WHERE ID_USER IN ({})", a_retirer)]
            _dans(conn, "DELETE FROM DROIT WHERE ID_USER IN ({})", a_retirer)
            _dans(conn, "DELETE FROM CODE_RECUPERATION WHERE ID_USER IN ({})", a_retirer)
            _dans(conn, "DELETE FROM TENTATIVE_CONNEXION WHERE LOGIN IN ({})", logins)
            _dans(conn, "DELETE FROM PERCEPTEUR WHERE ID_USER IN ({})", a_retirer)
            _dans(conn, "DELETE FROM UTILISATEUR WHERE ID_USER IN ({})", a_retirer)
            effaces["comptes"] = len(a_retirer)
            effaces["comptes désactivés"] = len(garder_users)

            # année et devise créées pour l'essai (seulement si plus rien ne s'y rattache)
            for annee in _cles(conn, "ANNEE_SCO"):
                if not conn.execute("SELECT 1 FROM INSCRIRE WHERE ANNEESCO = ? UNION SELECT 1 FROM TARIF WHERE ANNEESCO = ?",
                                    (annee, annee)).fetchone():
                    conn.execute("DELETE FROM ANNEE_SCO WHERE ANNEESCO = ?", (annee,))
            for dev in _cles(conn, "DEVISE"):
                if not conn.execute("SELECT 1 FROM PAIEMENT WHERE CODE_DEVISE = ? UNION SELECT 1 FROM TARIF WHERE CODE_DEVISE = ? "
                                    "UNION SELECT 1 FROM TYPE_FRAIS WHERE CODE_DEVISE = ? UNION SELECT 1 FROM ENCAISSEMENT "
                                    "WHERE CODE_DEVISE = ?", (dev, dev, dev, dev)).fetchone():
                    conn.execute("DELETE FROM DEVISE WHERE CODE_DEVISE = ?", (dev,))

            # compteur des matricules : revient à sa valeur d'avant seulement si aucun vrai élève n'a été ajouté depuis
            for texte in _cles(conn, "MATRICULE_SEQ"):
                m = json.loads(texte)
                actuel = conn.execute("SELECT DERNIER FROM MATRICULE_SEQ WHERE ANNEE = ?", (m["ANNEE"],)).fetchone()
                if actuel and actuel["DERNIER"] == m["APRES"]:
                    if m["AVANT"]:
                        conn.execute("UPDATE MATRICULE_SEQ SET DERNIER = ? WHERE ANNEE = ?", (m["AVANT"], m["ANNEE"]))
                    else:
                        conn.execute("DELETE FROM MATRICULE_SEQ WHERE ANNEE = ?", (m["ANNEE"],))

            conn.execute("DELETE FROM DONNEE_ESSAI")
            if session is not None:
                journaliser(conn, session.id_user, session.login, "DONNEES_ESSAI_SUPPRIMEES",
                            f"{effaces['élèves']} élèves | {effaces['reçus']} reçus | {effaces['encaissements']} encaissements"
                            f" | {effaces['comptes']} comptes | sécurité : {nom_securite}"
                            f" | RECUS={','.join(sorted(recus_tous))} | NUMS={','.join(str(n) for n in sorted(nums))}"
                            f" | ENC={','.join(str(n) for n in sorted(enc_tous))}")
    finally:
        try:
            conn.executescript("CREATE TRIGGER IF NOT EXISTS PAIEMENT_NO_DELETE BEFORE DELETE ON PAIEMENT "
                               "BEGIN SELECT RAISE(ABORT, 'Un reçu ne peut pas être supprimé (utilisez l''annulation)'); END;")
        finally:
            conn.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")
    return effaces
