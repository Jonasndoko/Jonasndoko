"""Enregistrement des paiements, reçus et duplicata.

Contrôles : seul l'ENREGISTREMENT d'un paiement est soumis à vérification (poste PERCEPTEUR, car le reçu porte son numéro,
ET droit Ajout). Le duplicata et le rapport journalier sont ouverts à tout compte qui a accès au module (droit Lecture)."""
from datetime import datetime, time, timedelta, timezone

import argent
import config
import donnees
import parents
import sections
import droits
import security
from database import iso, journaliser, lire_iso, maintenant


class ErreurPaiement(Exception):
    """Erreur métier dont le message peut être affiché tel quel à l'utilisateur."""


def onglets_autorises(conn, session) -> set:
    """Onglets utilisables par ce compte (règles relues dans la base). Consultation, duplicata et rapport sont ouverts
    à tout compte qui a accès au module ; seul l'enregistrement du paiement est soumis à vérification.
    Partagé par le logiciel Windows (ecrans_paiement.py) et l'application web (web_paiement.py)."""
    if not droits.a_droit(conn, session, "paiement", "LECTURE"):
        return set()
    ouverts = {"consultation", "duplicata", "rapport"}
    if session.role == "PERCEPTEUR" and droits.a_droit(conn, session, "paiement", "AJOUT"):
        ouverts.add("paiement")
    return ouverts


def motif_enregistrement_verrouille(session, conn) -> str:
    if session.role != "PERCEPTEUR":
        return "L'enregistrement des paiements est réservé aux comptes de poste Percepteur."
    return ("Votre compte n'a pas le droit « Ajout » sur ce module.\n"
            "Demandez à l'Administrateur de vous l'accorder (Gestionnaire d'accès > Autorisations).")


def numero_percepteur(conn, session) -> int:
    security.exiger_role(session, "PERCEPTEUR")
    ligne = conn.execute("SELECT N_PERC FROM PERCEPTEUR WHERE ID_USER = ?", (session.id_user,)).fetchone()
    if not ligne:
        raise ErreurPaiement("Ce compte n'est pas enregistré comme percepteur.")
    return ligne["N_PERC"]


def verifier_palier(paliers, frais, montant, devise, deja, centimes):
    """Un frais payé en une fois se règle en entier. Un frais payé par tranches peut être payé EN PARTIE : n'importe quel
    montant (jusqu'au reste dû) est accepté, même s'il ne couvre pas toute la tranche ; la tranche reste ouverte et le reçu
    indique ce qu'il reste à payer pour elle. Les tranches doivent toutefois être correctement définies."""
    if paliers is None:
        raise ErreurPaiement(f"Les tranches du frais « {frais['DESITF']} » ne sont pas définies pour cette classe : leur total "
                             f"doit faire le montant dû (Travaux techniques > Mise à jour des tables > Tarifs).")
    if frais["PAR_TRANCHE"]:
        return                                        # paiement partiel d'une tranche autorisé (plafond = reste dû, vérifié avant)
    total = deja + centimes
    if total in paliers:
        return
    suivants = [p for p in paliers if p > deja]
    prochain = (suivants[0] - deja) if suivants else (montant - deja)
    raise ErreurPaiement(f"Ce frais se paie en une seule fois : le montant à payer est {argent.formater(prochain)} {devise}.")


def enregistrer_paiement(conn, session, matricule, annee, codtf, centimes) -> str:
    """Enregistre un reçu (un seul type de frais) et retourne son numéro."""
    droits.exiger_droit(conn, session, "paiement", "AJOUT")
    n_perc = numero_percepteur(conn, session)
    if not isinstance(centimes, int) or centimes <= 0:
        raise ErreurPaiement("Le montant doit être supérieur à zéro.")

    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")                  # verrou d'écriture : pas de double numéro de reçu
    try:
        insc = conn.execute("SELECT N_CLASSE FROM INSCRIRE WHERE ANNEESCO = ? AND MATRICULE = ?",
                            (annee, matricule)).fetchone()
        if not insc:
            raise ErreurPaiement(f"Cet élève n'est pas inscrit pour l'année {annee}.")
        sections.exiger_classe(conn, session, insc["N_CLASSE"])          # section de l'école ouverte à ce compte
        if not conn.execute("SELECT ACTIF FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()["ACTIF"]:
            raise ErreurPaiement("Cet élève est désactivé : aucun paiement ne peut être enregistré.")
        frais = conn.execute("SELECT ACTIF, DESITF, PAR_TRANCHE, POUR_INSCRIPTION FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
        if not frais:
            raise ErreurPaiement("Ce type de frais n'existe pas.")
        if frais["POUR_INSCRIPTION"]:
            raise ErreurPaiement(MSG_ELEVE_INSCRIT)
        if not frais["ACTIF"]:
            raise ErreurPaiement("Ce type de frais est désactivé : aucun paiement ne peut être enregistré.")
        if not donnees.frais_concerne(conn, codtf, insc["N_CLASSE"]):
            cible = conn.execute("SELECT CLASSE_CIBLE FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()[0]
            raise ErreurPaiement(f"Ce frais est réservé aux élèves de la {donnees.CIBLES.get(cible, cible)} : "
                                 f"cet élève n'est pas dans cette classe.")
        du = donnees.conditions_du(conn, codtf, insc["N_CLASSE"], annee)
        if not du:
            raise ErreurPaiement("Aucun montant n'est défini pour ce frais dans cette classe "
                                 "(montant du type de frais ou tarif de la classe).")
        montant, devise, tranches = du
        deja = conn.execute("SELECT COALESCE(SUM(MONT_PAYE), 0) FROM PAIEMENT WHERE ANNEESCO = ? AND MATRICULE = ? "
                            "AND CODTF = ? AND STATUT = 'VALIDE'", (annee, matricule, codtf)).fetchone()[0]
        reste = montant - deja
        if reste <= 0:
            raise ErreurPaiement("Ce frais est déjà entièrement payé.")
        if centimes > reste:
            raise ErreurPaiement(f"Le montant dépasse le reste à payer ({argent.formater(reste)} {devise}).")
        verifier_palier(donnees.paliers(tranches, montant, bool(frais["PAR_TRANCHE"])), frais, montant, devise, deja, centimes)

        # le montant appliqué à cette classe pour cette année est « figé » dans TARIF : le reçu s'y rattache et un
        # changement ultérieur du montant du type de frais ne modifie pas ce qui est déjà engagé
        if not conn.execute("SELECT 1 FROM TARIF WHERE CODTF = ? AND N_CLASSE = ? AND ANNEESCO = ?",
                            (codtf, insc["N_CLASSE"], annee)).fetchone():
            conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE, TRANCHES) VALUES (?,?,?,?,?,?)",
                         (codtf, insc["N_CLASSE"], annee, montant, devise, donnees.ecrire_tranches(tranches) or None))
            journaliser(conn, session.id_user, session.login, "TARIF_FIGE",
                        f"{codtf} | classe {insc['N_CLASSE']} | {annee} | {argent.formater(montant)} {devise}")
        tarif = {"CODE_DEVISE": devise}

        # numéro de reçu : 0001, 0002... continu d'une année à l'autre (les anciens reçus gardent leur numéro)
        seq = conn.execute("SELECT COALESCE(MAX(NUM_SEQ), 0) + 1 FROM PAIEMENT").fetchone()[0]
        n_recu = f"{seq:04d}"
        while conn.execute("SELECT 1 FROM PAIEMENT WHERE N_RECU = ?", (n_recu,)).fetchone():
            seq += 1
            n_recu = f"{seq:04d}"
        conn.execute(
            "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (n_recu, annee, seq, iso(maintenant()), matricule, insc["N_CLASSE"], codtf, tarif["CODE_DEVISE"], centimes, n_perc))
        journaliser(conn, session.id_user, session.login, "PAIEMENT_ENREGISTRE",
                    f"{n_recu} | {matricule} | {codtf} | {argent.formater(centimes)} {tarif['CODE_DEVISE']}")
        parents.generer_code_pour_recu(conn, session, n_recu, matricule, annee, codtf, deja + centimes, montant)   # frais du logiciel des parents : code d'accès
        conn.commit()
        return n_recu
    except BaseException:
        conn.rollback()
        raise


# ------------------------------------------------------------------ paiement des frais d'inscription (candidat sans matricule)
MSG_ELEVE_INSCRIT = ("Les frais d'inscription ne peuvent pas être payés par un élève déjà inscrit (qui possède un matricule) : "
                     "ils sont réservés aux candidats qui souhaitent s'inscrire à l'école.")


def nettoyer_nom(texte) -> str:
    return " ".join((texte or "").split()).upper()


def frais_inscription_pour_classe(conn, annee, n_classe) -> list:
    """[(codtf, désignation, montant en centimes, devise)] des frais d'inscription actifs qui ont un montant pour cette classe."""
    resultat = []
    for l in conn.execute("SELECT CODTF, DESITF FROM TYPE_FRAIS WHERE POUR_INSCRIPTION = 1 AND ACTIF = 1 ORDER BY CODTF"):
        du = donnees.conditions_du(conn, l["CODTF"], n_classe, annee)
        if du:
            resultat.append((l["CODTF"], l["DESITF"], du[0], du[1]))
    return resultat


def enregistrer_paiement_inscription(conn, session, annee, n_classe, codtf, centimes, nom, postnom="", prenom="") -> str:
    """Reçu des frais d'INSCRIPTION d'une personne qui n'est pas (encore) élève : pas de matricule, le reçu garde son nom
    et la classe souhaitée. Les frais d'inscription se paient en une seule fois. Le reçu servira ensuite à remplir sa
    candidature (module Inscription). Retourne le numéro du reçu."""
    droits.exiger_droit(conn, session, "paiement", "AJOUT")
    n_perc = numero_percepteur(conn, session)
    nom_payeur = nettoyer_nom(" ".join(p for p in (nom, postnom, prenom) if p and p.strip()))
    if not nettoyer_nom(nom):
        raise ErreurPaiement("Saisissez le nom du candidat.")
    if len(nom_payeur) > 150:
        raise ErreurPaiement("Le nom du candidat est trop long.")
    if not isinstance(centimes, int) or centimes <= 0:
        raise ErreurPaiement("Le montant doit être supérieur à zéro.")

    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not conn.execute("SELECT 1 FROM ANNEE_SCO WHERE ANNEESCO = ?", (annee,)).fetchone():
            raise ErreurPaiement("Choisissez l'année scolaire.")
        classe = conn.execute("SELECT ACTIF FROM CLASSE WHERE N_CLASSE = ?", (n_classe,)).fetchone()
        if not classe or not classe["ACTIF"]:
            raise ErreurPaiement("Choisissez la classe dans laquelle le candidat souhaite être inscrit.")
        sections.exiger_classe(conn, session, n_classe)
        # un élève déjà enregistré (matricule) ne paie pas l'inscription : on refuse si ce nom est celui d'un élève existant
        for e in conn.execute("SELECT MATRICULE, NOM, POSTNOM, PRENOM FROM ELEVE WHERE UPPER(NOM) = ?", (nettoyer_nom(nom),)):
            if nettoyer_nom(" ".join(p for p in (e["NOM"], e["POSTNOM"], e["PRENOM"]) if p and p.strip())) == nom_payeur:
                raise ErreurPaiement(f"{nom_payeur} est déjà élève de l'école (matricule {e['MATRICULE']}). " + MSG_ELEVE_INSCRIT)
        frais = conn.execute("SELECT ACTIF, DESITF, POUR_INSCRIPTION FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
        if not frais or not frais["POUR_INSCRIPTION"]:
            raise ErreurPaiement("Ce type de frais n'est pas un frais d'inscription.")
        if not frais["ACTIF"]:
            raise ErreurPaiement("Ce type de frais est désactivé : aucun paiement ne peut être enregistré.")
        du = donnees.conditions_du(conn, codtf, n_classe, annee)
        if not du:
            raise ErreurPaiement("Aucun montant n'est défini pour ces frais d'inscription dans cette classe "
                                 "(montant du type de frais ou tarif de la classe).")
        montant, devise, tranches = du
        if centimes != montant:
            raise ErreurPaiement(f"Les frais d'inscription se paient en une seule fois : le montant est "
                                 f"{argent.formater(montant)} {devise}.")
        # même personne, même année, mêmes frais : un seul reçu valide (sinon, duplicata ou annulation par l'administrateur)
        doublon = conn.execute(
            "SELECT N_RECU FROM PAIEMENT WHERE MATRICULE IS NULL AND ANNEESCO = ? AND CODTF = ? AND STATUT = 'VALIDE' "
            "AND UPPER(NOM_PAYEUR) = ?", (annee, codtf, nom_payeur)).fetchone()
        if doublon:
            raise ErreurPaiement(f"{nom_payeur} a déjà payé ces frais d'inscription (reçu N° {doublon['N_RECU']}). "
                                 f"Pour un nouveau papier, imprimez un duplicata (onglet 3).")
        if not conn.execute("SELECT 1 FROM TARIF WHERE CODTF = ? AND N_CLASSE = ? AND ANNEESCO = ?",
                            (codtf, n_classe, annee)).fetchone():
            conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE, TRANCHES) VALUES (?,?,?,?,?,?)",
                         (codtf, n_classe, annee, montant, devise, donnees.ecrire_tranches(tranches) or None))
            journaliser(conn, session.id_user, session.login, "TARIF_FIGE",
                        f"{codtf} | classe {n_classe} | {annee} | {argent.formater(montant)} {devise}")
        seq = conn.execute("SELECT COALESCE(MAX(NUM_SEQ), 0) + 1 FROM PAIEMENT").fetchone()[0]
        n_recu = f"{seq:04d}"
        while conn.execute("SELECT 1 FROM PAIEMENT WHERE N_RECU = ?", (n_recu,)).fetchone():
            seq += 1
            n_recu = f"{seq:04d}"
        conn.execute(
            "INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, NOM_PAYEUR, N_CLASSE, CODTF, CODE_DEVISE, "
            "MONT_PAYE, N_PERC) VALUES (?,?,?,?,NULL,?,?,?,?,?,?)",
            (n_recu, annee, seq, iso(maintenant()), nom_payeur, n_classe, codtf, devise, centimes, n_perc))
        journaliser(conn, session.id_user, session.login, "PAIEMENT_ENREGISTRE",
                    f"{n_recu} | CANDIDAT {nom_payeur} | {codtf} | {argent.formater(centimes)} {devise}")
        conn.commit()
        return n_recu
    except BaseException:
        conn.rollback()
        raise


# ------------------------------------------------------------------ reçus
def _tranche_du_recu(conn, l):
    """Pour un reçu de frais payé par tranches : la tranche concernée (la dernière atteinte par ce paiement) et ce qu'il reste
    à payer pour elle après ce reçu. Calculé sur les paiements valides de l'élève jusqu'à ce reçu (même résultat à chaque
    impression : l'original et le duplicata sont identiques). None pour un frais payé en une fois ou une inscription."""
    if not l["PAR_TRANCHE"] or l["MATRICULE"] is None:
        return None
    du = donnees.conditions_du(conn, l["CODTF"], l["N_CLASSE"], l["ANNEESCO"])
    if not du:
        return None
    montant, devise, tranches = du
    pal = donnees.paliers(tranches, montant, True)
    if not pal:
        return None
    cumul = conn.execute("SELECT COALESCE(SUM(MONT_PAYE), 0) FROM PAIEMENT WHERE ANNEESCO = ? AND MATRICULE = ? AND CODTF = ? "
                         "AND STATUT = 'VALIDE' AND NUM_SEQ <= ?", (l["ANNEESCO"], l["MATRICULE"], l["CODTF"], l["NUM_SEQ"])).fetchone()[0]
    indice = next((i for i, x in enumerate(pal) if cumul <= x), len(pal) - 1)
    return {"numero": indice + 1, "nombre": len(pal), "reste_txt": argent.formater(max(0, pal[indice] - cumul))}


def charger_recu(conn, n_recu) -> dict:
    l = conn.execute(
        "SELECT P.*, E.NOM, E.POSTNOM, E.PRENOM, C.DESI_CLASSE, N.DESI_NIVEAU, O.DESI_OPTION, F.DESITF, "
        "       F.PAR_TRANCHE, U.NOM_COMPLET AS NOM_PERCEPTEUR "
        "FROM PAIEMENT P LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE "
        "JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
        "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        "JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
        "JOIN PERCEPTEUR PE ON PE.N_PERC = P.N_PERC JOIN UTILISATEUR U ON U.ID_USER = PE.ID_USER "
        "WHERE P.N_RECU = ?", (n_recu,)).fetchone()
    if not l:
        raise ErreurPaiement("Reçu introuvable.")
    type_frais = l["DESITF"]
    tranche = _tranche_du_recu(conn, l)
    return {
        "n_recu": l["N_RECU"],
        "date_txt": lire_iso(l["DATE_PAY"]).astimezone().strftime("%d/%m/%Y"),
        "heure_txt": lire_iso(l["DATE_PAY"]).astimezone().strftime("%H:%M"),
        "matricule": l["MATRICULE"] or "",
        "nom_complet": donnees.nom_complet(l) if l["NOM"] else (l["NOM_PAYEUR"] or ""),
        "candidat": l["MATRICULE"] is None,
        "classe": l["DESI_CLASSE"],
        "option": l["DESI_OPTION"] or "",
        "annee": l["ANNEESCO"],
        "type_frais": type_frais,
        "motif": (f"Paiement des frais d'inscription - Année {l['ANNEESCO']}" if l["MATRICULE"] is None
                  else f"Paiement des frais scolaires - Année {l['ANNEESCO']}"),
        "montant_txt": argent.formater(l["MONT_PAYE"]),
        "devise": l["CODE_DEVISE"],
        "tranche": tranche,       # None, ou {"numero", "nombre", "reste_txt"} pour un frais payé par tranches
        "n_perc": l["N_PERC"],
        "nom_percepteur": l["NOM_PERCEPTEUR"],
        "statut": l["STATUT"],
        "code_parent": parents.code_du_recu(conn, l["N_RECU"]),        # code d'accès de l'application des parents (frais du logiciel), sinon None
    }


def journaliser_consultation_recus(conn, session, matricule):
    """Inscrit au journal la consultation des reçus d'un élève (onglet « Duplicata du reçu »)."""
    with conn:
        journaliser(conn, session.id_user, session.login, "RECUS_ELEVE_CONSULTES", matricule)


def recus_eleve(conn, matricule):
    return conn.execute(
        "SELECT P.N_RECU, P.DATE_PAY, P.ANNEESCO, F.DESITF, P.MONT_PAYE, P.CODE_DEVISE, P.STATUT "
        "FROM PAIEMENT P JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
        "WHERE P.MATRICULE = ? ORDER BY P.DATE_PAY DESC, P.N_RECU DESC", (matricule,)).fetchall()


def preparer_pdf(conn, session, n_recu, duplicata=False) -> str:
    """Génère le PDF du reçu (ou de son duplicata, identique : aucune mention) et retourne son chemin.
    Chaque impression est tracée au journal avec le compte qui l'a faite."""
    import recu_pdf
    droits.exiger_droit(conn, session, "paiement", "LECTURE")
    recu = charger_recu(conn, n_recu)
    if recu["statut"] != "VALIDE":
        raise ErreurPaiement("Ce reçu est annulé : impression impossible.")
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    chemin = str(config.DOSSIER_RECUS / f"Recu_{n_recu}.pdf")      # même nom, même contenu : rien ne distingue un duplicata
    recu_pdf.generer_recu_pdf(recu, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg")
    with conn:
        journaliser(conn, session.id_user, session.login,
                    "DUPLICATA_IMPRIME" if duplicata else "RECU_IMPRIME", n_recu)
    return chemin


# ------------------------------------------------------------------ rapport journalier de caisse
def lire_date(texte):
    """'08/10/2026' (ou 08-10-2026, 08.10.2026, 2026-10-08) -> date. Lève ErreurPaiement si invalide."""
    texte = (texte or "").strip()
    for modele in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texte, modele).date()
        except ValueError:
            continue
    raise ErreurPaiement("Date invalide. Écrivez-la ainsi : 08/10/2026")


def _bornes_utc(jour):
    """Début et fin de la journée LOCALE, converties en UTC (les dates sont stockées en UTC)."""
    debut = datetime.combine(jour, time.min).astimezone()
    fin = datetime.combine(jour + timedelta(days=1), time.min).astimezone()
    return iso(debut.astimezone(timezone.utc)), iso(fin.astimezone(timezone.utc))


def liste_percepteurs(conn) -> list:
    """[(n_perc, nom complet)] : pour choisir le percepteur dont on veut le rapport."""
    return [(l["N_PERC"], l["NOM_COMPLET"]) for l in conn.execute(
        "SELECT P.N_PERC, U.NOM_COMPLET FROM PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER "
        "ORDER BY U.NOM_COMPLET COLLATE NOCASE")]


def rapport_journalier(conn, session, jour, n_perc=None) -> dict:
    """Paiements valides encaissés à la date `jour`, séparés par type de frais, avec sous-totaux par devise.
    - Un percepteur obtient toujours SES encaissements.
    - Les autres comptes ayant accès au module choisissent un percepteur (`n_perc`) ou, sans choix, voient TOUS
      les percepteurs."""
    droits.exiger_droit(conn, session, "paiement", "LECTURE")
    if session.role == "PERCEPTEUR":
        n_perc = numero_percepteur(conn, session)
        nom = session.nom_complet
    elif n_perc is not None:
        ligne = conn.execute("SELECT U.NOM_COMPLET FROM PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER "
                             "WHERE P.N_PERC = ?", (n_perc,)).fetchone()
        if not ligne:
            raise ErreurPaiement("Percepteur introuvable.")
        nom = ligne["NOM_COMPLET"]
    else:
        nom = "Tous les percepteurs"
    debut, fin = _bornes_utc(jour)
    filtre, param = ("AND P.N_PERC = ? ", (n_perc,)) if n_perc is not None else ("", ())
    fs, ps = sections.filtre_classes(conn, session, "P.N_CLASSE")          # seulement les sections ouvertes à ce compte
    if fs:
        filtre, param = filtre + "AND " + fs + " ", param + ps
    lignes = conn.execute(
        "SELECT P.N_RECU, P.MONT_PAYE, P.CODE_DEVISE, P.CODTF, E.NOM, E.POSTNOM, E.PRENOM, P.NOM_PAYEUR, C.DESI_CLASSE, "
        "       O.DESI_OPTION, F.DESITF "
        "FROM PAIEMENT P LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE JOIN CLASSE C ON C.N_CLASSE = P.N_CLASSE "
        "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
        "WHERE P.STATUT = 'VALIDE' AND P.DATE_PAY >= ? AND P.DATE_PAY < ? " + filtre +
        "ORDER BY F.CODTF, P.DATE_PAY, P.N_RECU", (debut, fin) + param).fetchall()
    nb_annules = conn.execute(
        "SELECT COUNT(*) FROM PAIEMENT P WHERE P.STATUT = 'ANNULE' AND P.DATE_PAY >= ? AND P.DATE_PAY < ? " + filtre,
        (debut, fin) + param).fetchone()[0]

    groupes, generaux = {}, {}
    for l in lignes:
        g = groupes.setdefault(l["CODTF"], {
            "type_frais": l["DESITF"],
            "lignes": [], "totaux": {}})
        g["lignes"].append({"n_recu": l["N_RECU"], "nom_complet": donnees.nom_complet(l) if l["NOM"] else (l["NOM_PAYEUR"] or "") + " (candidat)",
                            "classe": l["DESI_CLASSE"], "option": l["DESI_OPTION"] or "", "devise": l["CODE_DEVISE"],
                            "montant_txt": f"{argent.formater(l['MONT_PAYE'])} {l['CODE_DEVISE']}"})
        g["totaux"][l["CODE_DEVISE"]] = g["totaux"].get(l["CODE_DEVISE"], 0) + l["MONT_PAYE"]
        generaux[l["CODE_DEVISE"]] = generaux.get(l["CODE_DEVISE"], 0) + l["MONT_PAYE"]
    return {
        "date_txt": jour.strftime("%d/%m/%Y"), "jour": jour, "n_perc": n_perc, "nom_percepteur": nom,
        "etiquette": f"Percepteur N° {n_perc} - {nom}" if n_perc is not None else nom,
        "etiquette_courte": f"N° {n_perc}  -  {nom}" if n_perc is not None else nom,
        "groupes": list(groupes.values()), "totaux": sorted(generaux.items()), "nb_recus": len(lignes),
        "nb_annules": nb_annules, "edite_le": datetime.now().strftime("%d/%m/%Y à %H:%M"),
    }


def preparer_rapport_pdf(conn, session, jour, n_perc=None) -> str:
    """Génère le PDF du rapport journalier de caisse et retourne son chemin."""
    import rapport_pdf
    rapport = rapport_journalier(conn, session, jour, n_perc)      # vérifie le droit Lecture
    if not rapport["nb_recus"]:
        raise ErreurPaiement("Aucun paiement encaissé à cette date : rien à imprimer.")
    config.DOSSIER_RECUS.mkdir(parents=True, exist_ok=True)
    cible = f"P{rapport['n_perc']}" if rapport["n_perc"] is not None else "Tous"
    chemin = str(config.DOSSIER_RECUS / f"Rapport_caisse_{jour.isoformat()}_{cible}.pdf")
    rapport_pdf.generer_rapport_pdf(rapport, chemin, config.DOSSIER_ASSETS / "logo_recu.jpg")
    with conn:
        # la trace garde la portée et les totaux imprimés : l'audit peut ainsi comparer le rapport aux reçus (audit_financier.py)
        portee = f"percepteur N°{rapport['n_perc']}" if rapport["n_perc"] is not None else "Tous les percepteurs"
        journaliser(conn, session.id_user, session.login, "RAPPORT_CAISSE_IMPRIME",
                    f"{jour.isoformat()} | {rapport['nb_recus']} reçu(s) | {portee} | "
                    f"total {argent.resume_totaux(rapport['totaux'])}")
    return chemin
