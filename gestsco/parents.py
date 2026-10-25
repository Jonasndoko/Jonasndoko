"""Application mobile des PARENTS : codes d'accès, comptes et lecture de la situation des enfants.

Parcours
  1. Le parent paie à la caisse le « frais du logiciel des parents » (un type de frais que l'Administrateur marque dans Travaux
     techniques > Mise à jour des tables > Types de frais : « Frais du logiciel des parents »).
  2. Quand le percepteur enregistre ce paiement (paiements.enregistrer_paiement), le système génère un CODE D'ACCÈS (ex. K7QM-4TXD-9HWB),
     écrit sur le reçu. Un paiement = un reçu = un code = un élève.
  3. Le parent télécharge l'application (page publique /parents), saisit le code, puis crée son compte (nom, téléphone ou e-mail,
     mot de passe). Le code est alors « utilisé » : il ne sert qu'une fois.
  4. Pour un autre enfant de l'école, le parent paie à la caisse (nouveau reçu, nouveau code) et ajoute le code dans l'application.

Règles de sécurité (tout est relu dans la base à CHAQUE requête, jamais fait confiance à l'application) :
  - un parent ne voit que les enfants liés à son compte ;
  - l'accès à un enfant n'existe que tant qu'un reçu VALIDE (non annulé) du frais du logiciel couvre l'année scolaire en cours
    (config.ACCES_PARENT_PAR_ANNEE) ; un reçu annulé coupe l'accès aussitôt ;
  - l'application ne fait que LIRE : aucune information ne peut être modifiée ni envoyée à l'école ;
  - pas de fichier à télécharger : l'API ne renvoie que des données affichées à l'écran (l'application bloque en plus les captures) ;
  - essais de codes et de mots de passe limités (par adresse, et par compte) ; mots de passe hachés (scrypt) ;
  - les codes sont tirés au hasard (60 bits), sans lettre ambiguë (pas de 0, O, 1, I).
"""
import re
import secrets
import time
from datetime import timedelta

import argent
import bulletins
import config
import donnees
import notes
import security
import sessions_web
from database import iso, journaliser, lire_iso, maintenant

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # 32 signes, sans 0 O 1 I
LONGUEUR_CODE = 12                                  # 12 signes = 60 bits, écrits par groupes de 4
ECHECS_MAX_COMPTE = 5
BLOCAGE_COMPTE = timedelta(minutes=15)
MDP_MIN = 8
MESSAGE_CODE = "Ce code n'est pas valide, ou il a déjà été utilisé. Vérifiez-le avec la caisse de l'école."
MESSAGE_CONNEXION = "Identifiant ou mot de passe incorrect."
RE_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,200}\.[^@\s.]{2,}$")


class ErreurParent(Exception):
    """Erreur dont le message peut être affiché tel quel au parent."""


class AccesRefuse(Exception):
    """Accès à un enfant refusé (pas le sien, ou accès non valable) : message affichable."""


# ================================================================== codes d'accès (côté caisse)
def formater_code(brut: str) -> str:
    """'K7QM4TXD9HWB' -> 'K7QM-4TXD-9HWB'."""
    return "-".join(brut[i:i + 4] for i in range(0, len(brut), 4))


def normaliser_code(texte) -> str:
    """Ce que le parent a tapé (minuscules, espaces, tirets...) -> 12 signes en majuscules. '' si ce n'est pas un code possible
    (un code ne contient jamais 0, O, 1 ni I)."""
    brut = re.sub(r"[^A-Za-z0-9]", "", str(texte or "")).upper()
    return brut if len(brut) == LONGUEUR_CODE and all(c in ALPHABET for c in brut) else ""


def _nouveau_code(conn) -> str:
    while True:
        brut = "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR_CODE))
        if not conn.execute("SELECT 1 FROM CODE_PARENT WHERE CODE = ?", (brut,)).fetchone():
            return brut


def generer_code_pour_recu(conn, session, n_recu, matricule, annee, codtf, paye_total, du):
    """À appeler dans la transaction qui enregistre le reçu. Si `codtf` est le frais du logiciel des parents et que l'élève l'a maintenant
    payé en entier, crée le code d'accès de ce reçu et le retourne (sinon None). Un paiement = un code = un élève."""
    f = conn.execute("SELECT POUR_APPLI_PARENTS FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
    if not f or not f["POUR_APPLI_PARENTS"] or not matricule or paye_total < du:
        return None
    brut = _nouveau_code(conn)
    conn.execute("INSERT INTO CODE_PARENT (CODE, N_RECU, MATRICULE, ANNEESCO, DATE_GEN) VALUES (?,?,?,?,?)",
                 (brut, n_recu, matricule, annee, iso(maintenant())))
    journaliser(conn, session.id_user, session.login, "CODE_PARENT_GENERE", f"{n_recu} | {matricule} | {annee}")
    return formater_code(brut)


def code_du_recu(conn, n_recu):
    """{'code': 'K7QM-4TXD-9HWB' ou '', 'utilise': bool} pour un reçu qui a un code ; None s'il n'en a pas. Le code d'un code déjà utilisé n'est
    plus montré (il ne sert plus à rien)."""
    l = conn.execute("SELECT CODE, ID_PARENT FROM CODE_PARENT WHERE N_RECU = ?", (n_recu,)).fetchone()
    if not l:
        return None
    utilise = l["ID_PARENT"] is not None
    return {"code": "" if utilise else formater_code(l["CODE"]), "utilise": utilise}


# ================================================================== comptes
def normaliser_identifiant(texte) -> str:
    """Téléphone (chiffres, + au début) ou e-mail (minuscules). Lève ErreurParent si ce n'est ni l'un ni l'autre."""
    t = "".join(str(texte or "").split())
    if "@" in t:
        t = t.lower()
        if not RE_EMAIL.match(t):
            raise ErreurParent("Cette adresse e-mail n'est pas valide.")
        return t
    chiffres = re.sub(r"[().\-]", "", t)
    if not re.fullmatch(r"\+?\d{8,15}", chiffres):
        raise ErreurParent("Saisissez un numéro de téléphone (8 à 15 chiffres, avec l'indicatif si possible) ou une adresse e-mail.")
    return chiffres


def verifier_mdp_parent(mdp, identifiant=""):
    if not isinstance(mdp, str) or len(mdp) < MDP_MIN:
        raise ErreurParent(f"Le mot de passe doit avoir au moins {MDP_MIN} caractères.")
    if len(mdp) > 128:
        raise ErreurParent("Le mot de passe est trop long.")
    if not (re.search(r"[A-Za-z]", mdp) and re.search(r"\d", mdp)):
        raise ErreurParent("Le mot de passe doit contenir au moins une lettre et un chiffre.")
    if identifiant and mdp.lower() == identifiant.lower():
        raise ErreurParent("Le mot de passe ne doit pas être identique à l'identifiant.")


def _code_libre(conn, code_saisi):
    """Ligne du code s'il est utilisable (pas encore utilisé, reçu valide, élève actif), sinon ErreurParent (message volontairement unique)."""
    brut = normaliser_code(code_saisi)
    if not brut:
        raise ErreurParent(MESSAGE_CODE)
    l = conn.execute(
        "SELECT C.*, P.STATUT, E.ACTIF FROM CODE_PARENT C JOIN PAIEMENT P ON P.N_RECU = C.N_RECU JOIN ELEVE E ON E.MATRICULE = C.MATRICULE "
        "WHERE C.CODE = ?", (brut,)).fetchone()
    if not l or l["ID_PARENT"] is not None or l["STATUT"] != "VALIDE" or not l["ACTIF"]:
        raise ErreurParent(MESSAGE_CODE)
    return l


def _identite_enfant(conn, matricule, annee) -> dict:
    e = donnees.get_eleve(conn, matricule)
    insc = conn.execute("SELECT C.DESI_CLASSE FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE WHERE I.ANNEESCO = ? AND I.MATRICULE = ?",
                        (annee, matricule)).fetchone()
    return {"nom": donnees.nom_complet(e), "prenom": e["PRENOM"] or "", "classe": insc["DESI_CLASSE"] if insc else "", "annee": annee}


def verifier_code(conn, code) -> dict:
    """Étape 1 de l'activation : le code est-il bon ? Retourne le prénom, la classe et l'année pour que le parent confirme que c'est bien son enfant."""
    l = _code_libre(conn, code)
    ident = _identite_enfant(conn, l["MATRICULE"], l["ANNEESCO"])
    return {"prenom": ident["prenom"], "classe": ident["classe"], "annee": ident["annee"]}


def creer_compte(conn, code, nom, identifiant, mdp) -> int:
    """Étape 2 : crée le compte du parent et lui lie l'enfant du code (le code est « consommé »). Retourne l'ID_PARENT."""
    nom = " ".join(str(nom or "").split())
    if len(nom) < 3 or len(nom) > 80:
        raise ErreurParent("Saisissez votre nom complet (3 à 80 caractères).")
    ident = normaliser_identifiant(identifiant)
    verifier_mdp_parent(mdp, ident)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        l = _code_libre(conn, code)
        if conn.execute("SELECT 1 FROM COMPTE_PARENT WHERE IDENTIFIANT = ?", (ident,)).fetchone():
            raise ErreurParent("Un compte existe déjà avec ce numéro ou cette adresse. Connectez-vous, puis ajoutez le code depuis l'application.")
        c = conn.execute("INSERT INTO COMPTE_PARENT (IDENTIFIANT, NOM_COMPLET, MDP_HASH, DATE_CREATION) VALUES (?,?,?,?)",
                         (ident, nom, security.hacher_mdp(mdp), iso(maintenant())))
        id_parent = c.lastrowid
        _lier(conn, id_parent, l)
        journaliser(conn, None, f"parent:{id_parent}", "PARENT_COMPTE_CREE", f"{l['MATRICULE']} | reçu {l['N_RECU']}")
        conn.commit()
        return id_parent
    except BaseException:
        conn.rollback()
        raise


def _lier(conn, id_parent, code_ligne):
    conn.execute("UPDATE CODE_PARENT SET ID_PARENT = ?, DATE_UTILISATION = ? WHERE ID_CODE = ? AND ID_PARENT IS NULL",
                 (id_parent, iso(maintenant()), code_ligne["ID_CODE"]))
    if not conn.execute("SELECT 1 FROM ENFANT_PARENT WHERE ID_PARENT = ? AND MATRICULE = ?", (id_parent, code_ligne["MATRICULE"])).fetchone():
        conn.execute("INSERT INTO ENFANT_PARENT (ID_PARENT, MATRICULE, DATE_LIEN) VALUES (?,?,?)",
                     (id_parent, code_ligne["MATRICULE"], iso(maintenant())))


def ajouter_enfant(conn, id_parent, code) -> dict:
    """Le parent connecté ajoute un autre enfant (ou renouvelle l'accès d'un enfant déjà lié) avec un nouveau code."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        l = _code_libre(conn, code)
        _lier(conn, id_parent, l)
        journaliser(conn, None, f"parent:{id_parent}", "PARENT_ENFANT_AJOUTE", f"{l['MATRICULE']} | reçu {l['N_RECU']}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return next(e for e in enfants(conn, id_parent) if e["matricule_interne"] == l["MATRICULE"])


def _echec_compte(conn, ligne):
    n = ligne["ECHECS"] + 1
    bloque = iso(maintenant() + BLOCAGE_COMPTE) if n >= ECHECS_MAX_COMPTE else None
    with conn:
        conn.execute("UPDATE COMPTE_PARENT SET ECHECS = ?, BLOQUE_JUSQUA = ? WHERE ID_PARENT = ?", (0 if bloque else n, bloque, ligne["ID_PARENT"]))
        if bloque:
            journaliser(conn, None, f"parent:{ligne['ID_PARENT']}", "PARENT_COMPTE_BLOQUE", "trop d'essais")


def authentifier(conn, identifiant, mdp) -> int:
    """ID_PARENT si l'identifiant et le mot de passe sont bons. Lève ErreurParent (message unique) sinon ; compte bloqué 15 minutes après 5 échecs."""
    try:
        ident = normaliser_identifiant(identifiant)
    except ErreurParent:
        ident = ""
    l = conn.execute("SELECT * FROM COMPTE_PARENT WHERE IDENTIFIANT = ?", (ident,)).fetchone() if ident else None
    if l is not None and l["BLOQUE_JUSQUA"] and maintenant() < lire_iso(l["BLOQUE_JUSQUA"]):
        raise ErreurParent("Trop d'essais. Patientez quelques minutes avant de réessayer.")
    stocke = l["MDP_HASH"] if l is not None else security._hash_factice_pour_temps_constant()
    bon = security.verifier_mdp(str(mdp or ""), stocke)
    if l is None or not bon or not l["ACTIF"]:
        if l is not None and l["ACTIF"]:
            _echec_compte(conn, l)
        raise ErreurParent(MESSAGE_CONNEXION)
    with conn:
        conn.execute("UPDATE COMPTE_PARENT SET ECHECS = 0, BLOQUE_JUSQUA = NULL, DERNIERE_CONNEXION = ? WHERE ID_PARENT = ?", (iso(maintenant()), l["ID_PARENT"]))
        journaliser(conn, None, f"parent:{l['ID_PARENT']}", "PARENT_CONNEXION", "")
    return l["ID_PARENT"]


def changer_mdp(conn, id_parent, ancien, nouveau):
    l = conn.execute("SELECT * FROM COMPTE_PARENT WHERE ID_PARENT = ? AND ACTIF = 1", (id_parent,)).fetchone()
    if not l or not security.verifier_mdp(str(ancien or ""), l["MDP_HASH"]):
        raise ErreurParent("Le mot de passe actuel est incorrect.")
    verifier_mdp_parent(nouveau, l["IDENTIFIANT"])
    if nouveau == ancien:
        raise ErreurParent("Le nouveau mot de passe doit être différent de l'actuel.")
    with conn:
        conn.execute("UPDATE COMPTE_PARENT SET MDP_HASH = ? WHERE ID_PARENT = ?", (security.hacher_mdp(nouveau), id_parent))
        journaliser(conn, None, f"parent:{id_parent}", "PARENT_MDP_CHANGE", "")


def compte(conn, id_parent):
    """Ligne du compte actif, ou None (compte désactivé ou supprimé : la session ne sert plus)."""
    return conn.execute("SELECT * FROM COMPTE_PARENT WHERE ID_PARENT = ? AND ACTIF = 1", (id_parent,)).fetchone()


# ================================================================== enfants et accès
def _acces_valable(conn, id_parent, matricule) -> bool:
    """Un reçu valide du frais du logiciel, lié à ce parent et à cet élève, couvre l'année en cours (ou, selon config, n'importe quelle année)."""
    annee = donnees.annee_courante(conn)
    ligne = conn.execute(
        "SELECT C.ANNEESCO FROM CODE_PARENT C JOIN PAIEMENT P ON P.N_RECU = C.N_RECU AND P.STATUT = 'VALIDE' "
        "WHERE C.ID_PARENT = ? AND C.MATRICULE = ? ORDER BY C.ANNEESCO DESC LIMIT 1", (id_parent, matricule)).fetchone()
    if not ligne:
        return False
    return (not config.ACCES_PARENT_PAR_ANNEE) or (annee is None) or ligne["ANNEESCO"] >= annee


def enfants(conn, id_parent) -> list:
    """Les enfants liés au compte, avec leur identité, leur classe actuelle et l'état de l'accès. `matricule_interne` ne part jamais vers l'application."""
    annee = donnees.annee_courante(conn)
    resultat = []
    for l in conn.execute("SELECT * FROM ENFANT_PARENT WHERE ID_PARENT = ? ORDER BY ID_LIEN", (id_parent,)):
        ident = _identite_enfant(conn, l["MATRICULE"], annee)
        ok = _acces_valable(conn, id_parent, l["MATRICULE"])
        resultat.append({"id": l["ID_LIEN"], "nom": ident["nom"], "prenom": ident["prenom"], "classe": ident["classe"], "annee": annee or "",
                         "acces": ok,
                         "message": "" if ok else "Votre accès à cet enfant n'est plus valable pour cette année scolaire. Payez le frais du logiciel à la "
                                                  "caisse, puis ajoutez le nouveau code avec le bouton « Ajouter un enfant ».",
                         "matricule_interne": l["MATRICULE"]})
    return resultat


def enfant_autorise(conn, id_parent, id_lien):
    """(matricule, année scolaire en cours) de l'enfant, après avoir vérifié qu'il appartient bien à CE parent et que l'accès est valable."""
    l = conn.execute("SELECT MATRICULE FROM ENFANT_PARENT WHERE ID_LIEN = ? AND ID_PARENT = ?", (id_lien, id_parent)).fetchone()
    if not l:
        raise AccesRefuse("Cet enfant n'est pas associé à votre compte.")
    if not _acces_valable(conn, id_parent, l["MATRICULE"]):
        raise AccesRefuse("Votre accès à cet enfant n'est plus valable. Payez le frais du logiciel à la caisse et ajoutez le nouveau code.")
    return l["MATRICULE"], donnees.annee_courante(conn)


def _annee_et_classe(conn, matricule, annee):
    insc = conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE ANNEESCO = ? AND MATRICULE = ?", (annee, matricule)).fetchone()
    return insc["N_CLASSE"] if insc else None


# ================================================================== situation financière
def _montant(c) -> dict:
    return {"centimes": c, "texte": argent.formater(c)}


def frais(conn, matricule, annee) -> dict:
    """Frais à payer, payés et dettes. Le frais du logiciel des parents n'est pas listé (c'est le paiement qui ouvre l'application)."""
    n_classe = _annee_et_classe(conn, matricule, annee)
    lignes, totaux = [], {}
    if n_classe is not None:
        masques = {r[0] for r in conn.execute("SELECT CODTF FROM TYPE_FRAIS WHERE POUR_APPLI_PARENTS = 1")}
        for l in donnees.situation(conn, matricule, annee, n_classe):
            if l.codtf in masques:
                continue
            lignes.append({"designation": l.designation, "devise": l.devise, "du": _montant(l.du), "paye": _montant(min(l.paye, l.du)),
                           "reste": _montant(l.reste), "statut": l.statut, "mode": l.mode,
                           "prochain": _montant(l.prochain_montant) if l.reste > 0 and not l.tranches_mal_definies else None})
            t = totaux.setdefault(l.devise, [0, 0, 0])
            t[0] += l.du
            t[1] += min(l.paye, l.du)
            t[2] += l.reste
    dettes = []
    for a, devise, reste in donnees.dettes(conn, matricule):
        if a != annee:
            dettes.append({"annee": a, "devise": devise, "reste": _montant(reste)})
    recus = [{"n_recu": r["N_RECU"], "date": lire_iso(r["DATE_PAY"]).astimezone().strftime("%d/%m/%Y"), "frais": r["DESITF"],
              "montant": _montant(r["MONT_PAYE"]), "devise": r["CODE_DEVISE"]}
             for r in conn.execute("SELECT P.N_RECU, P.DATE_PAY, F.DESITF, P.MONT_PAYE, P.CODE_DEVISE FROM PAIEMENT P JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
                                   "WHERE P.MATRICULE = ? AND P.ANNEESCO = ? AND P.STATUT = 'VALIDE' AND F.POUR_APPLI_PARENTS = 0 "
                                   "ORDER BY P.DATE_PAY DESC, P.N_RECU DESC", (matricule, annee))]
    return {"annee": annee, "inscrit": n_classe is not None, "lignes": lignes,
            "totaux": [{"devise": d, "du": _montant(t[0]), "paye": _montant(t[1]), "reste": _montant(t[2])} for d, t in sorted(totaux.items())],
            "dettes_anterieures": dettes, "paiements": recus}


# ================================================================== présences
def presences(conn, matricule, annee) -> dict:
    """Présence de l'enfant, jour par jour (règle de l'école : présent pour la journée seulement s'il est présent à tous les cours pointés ce jour-là),
    avec les cours manqués et les totaux. Du plus récent au plus ancien."""
    jours = {}
    for l in conn.execute(
            "SELECT PE.DATE_COURS, PE.STATUT, C.LIBELLE FROM PRESENCE_ELEVE PE JOIN COURS_CLASSE X ON X.ID_CC = PE.ID_CC "
            "JOIN COURS C ON C.ID_COURS = X.ID_COURS WHERE X.ANNEESCO = ? AND PE.MATRICULE = ? "
            "ORDER BY PE.DATE_COURS DESC, C.LIBELLE COLLATE NOCASE", (annee, matricule)):
        j = jours.setdefault(l["DATE_COURS"], {"date": l["DATE_COURS"], "statut": "P", "manques": [], "pointes": 0})
        j["pointes"] += 1
        if l["STATUT"] == "A":
            j["statut"] = "A"
            j["manques"].append(l["LIBELLE"])
    liste = sorted(jours.values(), key=lambda j: j["date"], reverse=True)
    p = sum(1 for j in liste if j["statut"] == "P")
    a = len(liste) - p
    return {"annee": annee, "jours": liste, "presents": p, "absents": a, "taux": round(100.0 * p / (p + a), 1) if p + a else None}


# ================================================================== résultats et conduite
_CACHE = {}                         # (fichier de la base, année, classe) -> (instant, résultat de bulletins.calculer)
_CACHE_SECONDES = 30


def _calcul_classe(conn, annee, n_classe):
    """Résultats de toute la classe (le rang en a besoin). Gardés 30 secondes : plusieurs parents de la même classe ne refont pas le calcul."""
    fichier = conn.execute("PRAGMA database_list").fetchone()[2] or ""
    cle = (fichier, annee, n_classe)
    pris = _CACHE.get(cle)
    if pris and time.monotonic() - pris[0] < _CACHE_SECONDES:
        return pris[1]
    calc = bulletins.calculer(conn, annee, n_classe)
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[cle] = (time.monotonic(), calc)
    return calc


def _eleve_du_calcul(calc, matricule):
    return next((e for e in calc["eleves"] if e["matricule"] == matricule), None)


def resultats(conn, matricule, annee) -> dict:
    """Points de l'enfant dans chaque cours, période par période (puis examen, semestre et année), avec ses totaux, son rang et son résultat."""
    n_classe = _annee_et_classe(conn, matricule, annee)
    if n_classe is None:
        return {"annee": annee, "inscrit": False, "colonnes": [], "cours": [], "totaux": [], "seuil": config.SEUIL_REUSSITE}
    calc = _calcul_classe(conn, annee, n_classe)
    e = _eleve_du_calcul(calc, matricule)
    if e is None:
        return {"annee": annee, "inscrit": False, "colonnes": [], "cours": [], "totaux": [], "seuil": config.SEUIL_REUSSITE}
    colonnes = [{"cle": p["cle"], "type": p["type"], "libelle": p["libelle"], "semestre": p["semestre"]} for p in calc["portees"]]

    def case(c):
        return None if c is None else {"obtenu": c["obtenu"], "max": c["max"], "pct": c["pct"]}
    cours = [{"libelle": c["libelle"], "professeur": c["professeur"],
              "cotes": {p["cle"]: case(e["cours"].get(c["id_cc"], {}).get(p["cle"])) for p in calc["portees"]}} for c in calc["cours"]]
    totaux = []
    for p in calc["portees"]:
        r = e["portees"][p["cle"]]
        totaux.append({"cle": p["cle"], "obtenu": r["obtenu"], "max": r["max"], "pct": r["pct"], "rang": r["rang"], "effectif": calc["stats"][p["cle"]]["effectif"],
                       "mention": r["mention"], "resultat": r["resultat"], "reussite": r["reussite"], "complet": r["complet"]})
    return {"annee": annee, "inscrit": True, "classe": calc["classe"]["designation"], "colonnes": colonnes, "cours": cours, "totaux": totaux,
            "seuil": config.SEUIL_REUSSITE}


def conduite(conn, matricule, annee) -> dict:
    """Conduite de l'enfant : pour chaque période, la cote retenue (la plus fréquente parmi les cours) et la cote donnée par chaque professeur."""
    libelles = dict(notes.COTES_CONDUITE)
    n_classe = _annee_et_classe(conn, matricule, annee)
    if n_classe is None:
        return {"annee": annee, "inscrit": False, "periodes": [], "legende": [{"code": c, "libelle": l} for c, l in notes.COTES_CONDUITE]}
    calc = _calcul_classe(conn, annee, n_classe)
    e = _eleve_du_calcul(calc, matricule)
    detail = {}
    for l in conn.execute("SELECT C.ID_PER, C.COTE, K.LIBELLE FROM CONDUITE C JOIN COURS_CLASSE X ON X.ID_CC = C.ID_CC JOIN COURS K ON K.ID_COURS = X.ID_COURS "
                          "WHERE X.ANNEESCO = ? AND C.MATRICULE = ? ORDER BY K.LIBELLE COLLATE NOCASE", (annee, matricule)):
        detail.setdefault(l["ID_PER"], []).append({"cours": l["LIBELLE"], "cote": l["COTE"], "libelle": libelles.get(l["COTE"], l["COTE"])})
    periodes = []
    for p in calc["portees"]:
        if p["type"] != "periode":
            continue
        cote = e["portees"][p["cle"]]["conduite"] if e else ""
        periodes.append({"periode": p["libelle"], "semestre": p["semestre"], "cote": cote, "libelle": libelles.get(cote, ""),
                         "par_cours": detail.get(p["periodes"][0], [])})
    return {"annee": annee, "inscrit": True, "periodes": periodes, "legende": [{"code": c, "libelle": l} for c, l in notes.COTES_CONDUITE]}
