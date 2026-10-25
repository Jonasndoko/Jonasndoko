"""Direction de discipline, 3e fonctionnalité « Convocation du parent » (secondaire et humanitaire), sans interface graphique : testable seule.

Le Directeur de discipline :
  1. SÉLECTIONNE l'élève concerné (recherche par nom, postnom, prénom ou matricule) ;
  2. RETROUVE les coordonnées de son parent ou tuteur (fiche de l'élève) et voit combien de comptes de l'application des parents sont liés à cet élève ;
  3. INDIQUE le motif de la convocation ;
  4. FIXE la date, l'heure et le lieu du rendez-vous (lieu proposé : config.CONVOCATION_LIEU_DEFAUT) ;
  5. AJOUTE des instructions complémentaires si nécessaire (documents à apporter, personne à demander...) ;
  6. ENVOIE la convocation au parent : NOTIFICATION dans l'application mobile du parent (page /parents et API /parent/api/convocations).

Règles
- Une convocation est BROUILLON (enregistrée, pas encore envoyée), ENVOYEE ou ANNULEE. « Enregistrer et envoyer » fait les deux d'un coup.
- L'envoi arrive à TOUS les comptes parents actifs liés à l'élève dont l'accès à l'enfant est valable (mêmes règles que l'application : reçu du
  frais du logiciel non annulé). Si aucun compte n'est lié, la convocation reste en brouillon et on explique pourquoi : rien n'est faussement
  marqué « envoyé ».
- Le parent ne voit que les convocations envoyées à SON compte pour SES enfants ; il peut seulement les marquer comme lues.
- Le nom et le téléphone du parent sont copiés de la fiche de l'élève au moment de l'enregistrement (une modification ultérieure de la fiche ne
  réécrit pas la convocation).
- Rien n'est supprimé. Une convocation (brouillon ou envoyée) est ANNULÉE avec un motif ; le parent qui l'a reçue la voit alors marquée « Annulée ».
- On convoque seulement pour l'année en cours, un élève ACTIF inscrit dans le secondaire et humanitaire, avec un rendez-vous qui n'est pas dans le passé
  (au plus un an à l'avance).

Droits sur « Direction de discipline » (relus dans la base à chaque appel ; refus = PermissionError) : Lecture = consulter ; Ajout = enregistrer et envoyer ;
Modification = annuler (non accordé par défaut au Directeur : à donner dans le Gestionnaire d'accès). Chaque consultation et chaque opération est
inscrite au journal.
"""
import re
from datetime import date, datetime, timedelta

import config
import donnees
import parents
import suivi_conduite
from database import iso, journaliser, maintenant

MODULE = suivi_conduite.MODULE
STATUTS = {"BROUILLON": "Brouillon", "ENVOYEE": "Envoyée", "ANNULEE": "Annulée"}
LONGUEUR_MOTIF = 300
LONGUEUR_LIEU = 100
LONGUEUR_INSTRUCTIONS = 600
LONGUEUR_MOTIF_ANNULATION = 300
MAX_RESULTATS = 60
MAX_LISTE = 200
DELAI_MAX_JOURS = 366
RE_HEURE = re.compile(r"^([01]?\d|2[0-3])[:hH]([0-5]\d)$")


class ErreurConvocation(Exception):
    """Erreur dont le message peut être affiché tel quel."""


# ================================================================== droits (mêmes règles que le suivi de la conduite)
def peut(conn, session, droit="LECTURE") -> bool:
    return suivi_conduite.peut(conn, session, droit)


def exiger(conn, session, droit="LECTURE"):
    suivi_conduite.exiger(conn, session, droit)


# ================================================================== outils
def _fr(d) -> str:
    return (d if isinstance(d, date) else date.fromisoformat(d)).strftime("%d/%m/%Y")


def _annee_courante(conn) -> str:
    a = donnees.annee_courante(conn)
    if not a:
        raise ErreurConvocation("Aucune année scolaire n'est définie : créez-la d'abord (Direction des études > Années).")
    return a


def _texte(texte, nom, maxi, obligatoire=False, mini=1) -> str:
    t = " ".join(str(texte or "").split())
    if obligatoire and len(t) < mini:
        raise ErreurConvocation(f"Renseignez {nom}." if mini <= 1 else f"Renseignez {nom} (au moins {mini} caractères).")
    if len(t) > maxi:
        raise ErreurConvocation(f"{nom[0].upper() + nom[1:]} est trop long ({maxi} caractères au plus).")
    return t


def _date_rdv(texte) -> date:
    t = str(texte or "").strip()
    if not t:
        raise ErreurConvocation("Indiquez la date du rendez-vous.")
    d = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            d = datetime.strptime(t, fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        raise ErreurConvocation("La date du rendez-vous n'est pas valable (exemple : 15/11/2026).")
    if d < date.today():
        raise ErreurConvocation("La date du rendez-vous est déjà passée.")
    if d > date.today() + timedelta(days=DELAI_MAX_JOURS):
        raise ErreurConvocation("La date du rendez-vous est trop lointaine (un an au plus).")
    return d


def _heure_rdv(texte) -> str:
    m = RE_HEURE.match(str(texte or "").strip())
    if not m:
        raise ErreurConvocation("L'heure du rendez-vous n'est pas valable (exemple : 09:30).")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _tracer(conn, session, action, detail):
    journaliser(conn, session.id_user, session.login, action, detail)


def _eleve_actif(conn, matricule, annee):
    """(élève, n° de classe) pour un élève actif inscrit cette année dans le secondaire et humanitaire ; sinon erreur ou refus."""
    try:
        e = suivi_conduite._eleve_secondaire(conn, matricule)
    except suivi_conduite.ErreurConduite as ex:
        raise ErreurConvocation(str(ex)) from None
    n_classe = suivi_conduite._inscription(conn, e, annee)
    if n_classe is None:
        raise PermissionError("Accès refusé : cet élève n'est pas inscrit dans le secondaire et humanitaire cette année.")
    if not e["ACTIF"]:
        raise ErreurConvocation("Cet élève est désactivé : on ne convoque plus son parent.")
    return e, n_classe


def _classe_nom(conn, n_classe) -> str:
    l = conn.execute("SELECT DESI_CLASSE FROM CLASSE WHERE N_CLASSE = ?", (n_classe,)).fetchone()
    return l["DESI_CLASSE"] if l else ""


def _comptes_destinataires(conn, matricule) -> list:
    """Comptes parents actifs liés à l'élève dont l'accès à l'enfant est valable aujourd'hui."""
    res = []
    for l in conn.execute("SELECT P.ID_PARENT, P.NOM_COMPLET FROM ENFANT_PARENT L JOIN COMPTE_PARENT P ON P.ID_PARENT = L.ID_PARENT "
                          "WHERE L.MATRICULE = ? AND P.ACTIF = 1 ORDER BY L.ID_LIEN", (matricule,)):
        if parents._acces_valable(conn, l["ID_PARENT"], matricule):
            res.append({"id_parent": l["ID_PARENT"], "nom": l["NOM_COMPLET"]})
    return res


# ================================================================== 1 et 2. choisir l'élève, retrouver le parent
def chercher_eleves(conn, session, texte) -> dict:
    """Élèves actifs inscrits cette année dans le secondaire et humanitaire dont le nom, le postnom, le prénom ou le matricule contient `texte`."""
    exiger(conn, session)
    annee = _annee_courante(conn)
    texte = str(texte or "").strip()
    eleves = []
    if texte:
        for e in conn.execute(
                "SELECT E.*, C.DESI_CLASSE FROM INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
                "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU WHERE I.ANNEESCO = ? AND N.SECTION = 'SECONDAIRE' AND E.ACTIF = 1 "
                "AND (E.MATRICULE LIKE ? OR E.NOM LIKE ? OR COALESCE(E.POSTNOM, '') LIKE ? OR COALESCE(E.PRENOM, '') LIKE ?) "
                "ORDER BY E.NOM COLLATE NOCASE, E.POSTNOM COLLATE NOCASE, E.PRENOM COLLATE NOCASE LIMIT ?", (annee, *([f"%{texte}%"] * 4), MAX_RESULTATS + 1)):
            eleves.append({"matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "classe": e["DESI_CLASSE"]})
    with conn:
        _tracer(conn, session, "CONVOCATION_CONSULTEE", f"recherche élève « {texte[:40]} » | {annee}")
    return {"annee": annee, "texte": texte, "eleves": eleves[:MAX_RESULTATS], "tronque": len(eleves) > MAX_RESULTATS}


def coordonnees_parent(conn, session, matricule) -> dict:
    """Fiche d'envoi d'un élève : identité, classe, parent ou tuteur (nom et téléphone de la fiche de l'élève), comptes de l'application des parents
    qui recevraient la notification, et convocations déjà faites pour cet élève cette année."""
    exiger(conn, session)
    annee = _annee_courante(conn)
    e, n_classe = _eleve_actif(conn, matricule, annee)
    comptes = _comptes_destinataires(conn, e["MATRICULE"])
    deja = [_vue(l) for l in conn.execute("SELECT * FROM CONVOCATION_PARENT WHERE MATRICULE = ? AND ANNEESCO = ? ORDER BY ID_CONV DESC LIMIT 10",
                                          (e["MATRICULE"], annee))]
    nom_t, tel_t = (e["NOM_TUTEUR"] or "").strip(), (e["TEL_TUTEUR"] or "").strip()
    with conn:
        _tracer(conn, session, "CONVOCATION_CONSULTEE", f"coordonnées du parent | {e['MATRICULE']} | {annee}")
    return {"annee": annee, "matricule": e["MATRICULE"], "nom_complet": donnees.nom_complet(e), "classe": _classe_nom(conn, n_classe), "n_classe": n_classe,
            "parent": {"nom": nom_t, "telephone": tel_t, "adresse": (e["ADRESSE"] or "").strip(), "renseigne": bool(nom_t or tel_t)},
            "comptes": comptes, "peut_notifier": bool(comptes), "deja": deja}


# ================================================================== vues
def _vue(l, avec_destinataires=None) -> dict:
    v = {"id": l["ID_CONV"], "annee": l["ANNEESCO"], "matricule": l["MATRICULE"], "n_classe": l["N_CLASSE"],
         "parent": l["NOM_PARENT"] or "Parent ou tuteur", "telephone": l["TEL_PARENT"], "motif": l["MOTIF"],
         "date": _fr(l["DATE_RDV"]), "jour": l["DATE_RDV"], "heure": l["HEURE_RDV"], "lieu": l["LIEU"], "instructions": l["INSTRUCTIONS"],
         "statut": l["STATUT"], "statut_libelle": STATUTS[l["STATUT"]], "par": l["ENREGISTRE_PAR"], "le": _fr(l["ENREGISTRE_LE"][:10]),
         "envoyee_le": _fr(l["ENVOYE_LE"][:10]) if l["ENVOYE_LE"] else "", "envoyee_par": l["ENVOYE_PAR"] or "",
         "annulee_le": _fr(l["ANNULE_LE"][:10]) if l["ANNULE_LE"] else "", "annulee_par": l["ANNULE_PAR"] or "",
         "motif_annulation": l["MOTIF_ANNULATION"] or "", "passee": l["DATE_RDV"] < date.today().isoformat()}
    if avec_destinataires is not None:
        v["destinataires"] = avec_destinataires
    return v


def _destinataires_de(conn, id_conv) -> list:
    return [{"nom": d["NOM_COMPLET"], "envoye_le": d["ENVOYE_LE"], "lue": bool(d["LU_LE"]), "lue_le": d["LU_LE"] or ""}
            for d in conn.execute("SELECT D.*, P.NOM_COMPLET FROM CONVOCATION_DESTINATAIRE D JOIN COMPTE_PARENT P ON P.ID_PARENT = D.ID_PARENT "
                                  "WHERE D.ID_CONV = ? ORDER BY P.NOM_COMPLET COLLATE NOCASE", (id_conv,))]


def lettre(c: dict, eleve: str, classe: str) -> dict:
    """Contenu de la lettre (même modèle à l'écran de la Direction et dans l'application du parent)."""
    return {"ecole": config.NOM_ECOLE, "service": config.CONVOCATION_SERVICE, "titre": "CONVOCATION DU PARENT",
            "lignes": [("Élève", eleve), ("Classe", classe), ("Parent ou tuteur", c["parent"]), ("Motif", c["motif"]),
                       ("Date du rendez-vous", c["date"]), ("Heure", c["heure"]), ("Lieu", c["lieu"])],
            "instructions": c["instructions"], "texte": config.CONVOCATION_TEXTE, "signature": config.CONVOCATION_SIGNATURE}


# ================================================================== 3 à 6. enregistrer, envoyer, annuler
def enregistrer(conn, session, matricule, motif, date_texte, heure_texte, lieu="", instructions="", envoyer=False) -> dict:
    """Enregistre une convocation (droit Ajout) et, si `envoyer`, la notifie aussitôt aux parents. Retourne {'id', 'envoyee', 'destinataires', 'raison'} :
    quand l'envoi est demandé mais impossible (aucun compte parent lié), la convocation reste en brouillon et `raison` l'explique."""
    exiger(conn, session, "AJOUT")
    annee = _annee_courante(conn)
    e, n_classe = _eleve_actif(conn, matricule, annee)
    motif = _texte(motif, "le motif de la convocation", LONGUEUR_MOTIF, True, 5)
    d = _date_rdv(date_texte)
    h = _heure_rdv(heure_texte)
    lieu = _texte(lieu, "le lieu du rendez-vous", LONGUEUR_LIEU) or config.CONVOCATION_LIEU_DEFAUT
    instructions = _texte(instructions, "les instructions", LONGUEUR_INSTRUCTIONS)
    with conn:
        cur = conn.execute("INSERT INTO CONVOCATION_PARENT (ANNEESCO, MATRICULE, N_CLASSE, NOM_PARENT, TEL_PARENT, MOTIF, DATE_RDV, HEURE_RDV, LIEU, INSTRUCTIONS, STATUT, "
                           "ENREGISTRE_LE, ENREGISTRE_PAR) VALUES (?,?,?,?,?,?,?,?,?,?,'BROUILLON',?,?)",
                           (annee, e["MATRICULE"], n_classe, (e["NOM_TUTEUR"] or "").strip(), (e["TEL_TUTEUR"] or "").strip(), motif, d.isoformat(), h, lieu, instructions,
                            iso(maintenant()), session.login))
        _tracer(conn, session, "CONVOCATION_ENREGISTREE", f"n° {cur.lastrowid} | {annee} | {e['MATRICULE']} | {donnees.nom_complet(e)} | {motif[:80]} | {_fr(d)} {h}")
    id_conv = cur.lastrowid
    res = {"id": id_conv, "envoyee": False, "destinataires": 0, "raison": ""}
    if envoyer:
        try:
            res.update(envoyer_convocation(conn, session, id_conv), envoyee=True, raison="")
        except ErreurConvocation as ex:
            res["raison"] = str(ex)
    return res


def _charger(conn, id_conv):
    try:
        id_conv = int(id_conv)
    except (TypeError, ValueError):
        raise ErreurConvocation("Convocation introuvable.") from None
    c = conn.execute("SELECT * FROM CONVOCATION_PARENT WHERE ID_CONV = ?", (id_conv,)).fetchone()
    if not c:
        raise ErreurConvocation("Convocation introuvable.")
    return c


def envoyer_convocation(conn, session, id_conv) -> dict:
    """Envoie un brouillon : notification dans l'application des parents liés à l'élève (droit Ajout)."""
    exiger(conn, session, "AJOUT")
    c = _charger(conn, id_conv)
    if c["STATUT"] == "ENVOYEE":
        raise ErreurConvocation("Cette convocation est déjà envoyée.")
    if c["STATUT"] == "ANNULEE":
        raise ErreurConvocation("Cette convocation est annulée : enregistrez-en une nouvelle.")
    if c["DATE_RDV"] < date.today().isoformat():
        raise ErreurConvocation("La date du rendez-vous est déjà passée : annulez cette convocation et enregistrez-en une nouvelle.")
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (c["MATRICULE"],)).fetchone()
    if not e["ACTIF"]:
        raise ErreurConvocation("Cet élève est désactivé : on ne convoque plus son parent.")
    comptes = _comptes_destinataires(conn, c["MATRICULE"])
    if not comptes:
        raise ErreurConvocation("Aucun parent n'a de compte actif dans l'application pour cet élève : la convocation est enregistrée en brouillon, "
                                "mais personne ne peut la recevoir. Prévenez le parent par un autre moyen ou attendez l'activation de son compte.")
    maint = iso(maintenant())
    with conn:
        for p in comptes:
            conn.execute("INSERT OR IGNORE INTO CONVOCATION_DESTINATAIRE (ID_CONV, ID_PARENT, ENVOYE_LE) VALUES (?,?,?)", (c["ID_CONV"], p["id_parent"], maint))
        conn.execute("UPDATE CONVOCATION_PARENT SET STATUT = 'ENVOYEE', ENVOYE_LE = ?, ENVOYE_PAR = ? WHERE ID_CONV = ?", (maint, session.login, c["ID_CONV"]))
        _tracer(conn, session, "CONVOCATION_ENVOYEE",
                f"n° {c['ID_CONV']} | {c['MATRICULE']} | {donnees.nom_complet(e)} | notification à {len(comptes)} compte(s) parent | {_fr(c['DATE_RDV'])} {c['HEURE_RDV']}")
    return {"id": c["ID_CONV"], "destinataires": len(comptes)}


def annuler(conn, session, id_conv, motif) -> dict:
    """Annule une convocation (droit Modification ; motif obligatoire). Le parent qui l'avait reçue la voit marquée « Annulée »."""
    exiger(conn, session, "MODIFICATION")
    c = _charger(conn, id_conv)
    if c["STATUT"] == "ANNULEE":
        raise ErreurConvocation("Cette convocation est déjà annulée.")
    motif = _texte(motif, "le motif de l'annulation", LONGUEUR_MOTIF_ANNULATION, True, 3)
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (c["MATRICULE"],)).fetchone()
    with conn:
        conn.execute("UPDATE CONVOCATION_PARENT SET STATUT = 'ANNULEE', ANNULE_LE = ?, ANNULE_PAR = ?, MOTIF_ANNULATION = ? WHERE ID_CONV = ?",
                     (iso(maintenant()), session.login, motif, c["ID_CONV"]))
        _tracer(conn, session, "CONVOCATION_ANNULEE", f"n° {c['ID_CONV']} | {c['MATRICULE']} | {donnees.nom_complet(e)} | {motif}")
    return {"id": c["ID_CONV"]}


# ================================================================== consultation : liste et détail
def liste(conn, session, statut="", n_classe="", texte="") -> dict:
    """Convocations de l'année en cours (les plus récentes d'abord), filtrables par statut, classe et élève (nom ou matricule)."""
    exiger(conn, session)
    annee = _annee_courante(conn)
    statut = statut if statut in STATUTS else ""
    cond, param = ["V.ANNEESCO = ?"], [annee]
    if statut:
        cond.append("V.STATUT = ?")
        param.append(statut)
    if str(n_classe or "").strip():
        try:
            suivi_conduite._classe(conn, n_classe)
        except suivi_conduite.ErreurConduite as ex:
            raise ErreurConvocation(str(ex)) from None
        cond.append("V.N_CLASSE = ?")
        param.append(int(n_classe))
    texte = str(texte or "").strip()
    if texte:
        cond.append("(E.MATRICULE LIKE ? OR E.NOM LIKE ? OR COALESCE(E.POSTNOM, '') LIKE ? OR COALESCE(E.PRENOM, '') LIKE ?)")
        param += [f"%{texte}%"] * 4
    lignes = conn.execute("SELECT V.*, E.NOM, E.POSTNOM, E.PRENOM, C.DESI_CLASSE, "
                          "(SELECT COUNT(*) FROM CONVOCATION_DESTINATAIRE D WHERE D.ID_CONV = V.ID_CONV) AS NB_DEST, "
                          "(SELECT COUNT(*) FROM CONVOCATION_DESTINATAIRE D WHERE D.ID_CONV = V.ID_CONV AND D.LU_LE IS NOT NULL) AS NB_LUS "
                          "FROM CONVOCATION_PARENT V JOIN ELEVE E ON E.MATRICULE = V.MATRICULE JOIN CLASSE C ON C.N_CLASSE = V.N_CLASSE "
                          f"WHERE {' AND '.join(cond)} ORDER BY V.ID_CONV DESC LIMIT ?", (*param, MAX_LISTE + 1)).fetchall()
    convocations = []
    for l in lignes[:MAX_LISTE]:
        v = _vue(l)
        v.update(eleve=donnees.nom_complet(l), classe=l["DESI_CLASSE"], nb_destinataires=l["NB_DEST"], nb_lues=l["NB_LUS"])
        convocations.append(v)
    toutes = conn.execute("SELECT STATUT, COUNT(*) AS N FROM CONVOCATION_PARENT WHERE ANNEESCO = ? GROUP BY STATUT", (annee,)).fetchall()
    totaux = {s: 0 for s in STATUTS}
    totaux.update({t["STATUT"]: t["N"] for t in toutes})
    with conn:
        _tracer(conn, session, "CONVOCATION_CONSULTEE", f"liste | {annee}")
    return {"annee": annee, "convocations": convocations, "tronque": len(lignes) > MAX_LISTE, "totaux": totaux, "statuts": STATUTS}


def detail(conn, session, id_conv) -> dict:
    """Une convocation : lettre telle que le parent la voit, état de l'envoi et de la lecture par compte parent."""
    exiger(conn, session)
    c = _charger(conn, id_conv)
    e = conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (c["MATRICULE"],)).fetchone()
    v = _vue(c, _destinataires_de(conn, c["ID_CONV"]))
    v.update(eleve=donnees.nom_complet(e), classe=_classe_nom(conn, c["N_CLASSE"]))
    v["lettre"] = lettre(v, v["eleve"], v["classe"])
    v["peut_envoyer"] = c["STATUT"] == "BROUILLON" and not v["passee"]
    with conn:
        _tracer(conn, session, "CONVOCATION_CONSULTEE", f"n° {c['ID_CONV']} | {c['MATRICULE']}")
    return v


# ================================================================== côté parent (application mobile) : lecture et accusé de lecture
def _vue_parent(conn, l) -> dict:
    ident = parents._identite_enfant(conn, l["MATRICULE"], l["ANNEESCO"])
    v = _vue(l)
    eleve = ident["nom"]
    v.update(enfant=eleve, classe=ident["classe"] or "", lue=bool(l["LU_LE"]), envoyee_le_iso=l["ENVOYE_LE"] or "")
    v["lettre"] = lettre(v, eleve, v["classe"])
    for secret in ("matricule", "par", "envoyee_par", "annulee_par", "n_classe", "telephone"):
        v.pop(secret, None)                                  # rien d'interne ne part vers l'application
    return v


def pour_parent(conn, id_parent) -> dict:
    """Convocations reçues par CE compte parent (envoyées ou annulées après envoi), pour les enfants dont l'accès est valable ; les plus récentes
    d'abord, avec le nombre de convocations non lues."""
    liste_ = []
    for l in conn.execute("SELECT V.*, D.LU_LE FROM CONVOCATION_DESTINATAIRE D JOIN CONVOCATION_PARENT V ON V.ID_CONV = D.ID_CONV "
                          "WHERE D.ID_PARENT = ? AND V.STATUT IN ('ENVOYEE','ANNULEE') ORDER BY V.ENVOYE_LE DESC, V.ID_CONV DESC", (id_parent,)).fetchall():
        if parents._acces_valable(conn, id_parent, l["MATRICULE"]):
            liste_.append(_vue_parent(conn, l))
    return {"convocations": liste_, "non_lues": sum(1 for v in liste_ if not v["lue"] and v["statut"] == "ENVOYEE")}


def nombre_non_lues(conn, id_parent) -> int:
    return pour_parent(conn, id_parent)["non_lues"]


def marquer_lue(conn, id_parent, id_conv) -> dict:
    """Le parent a ouvert la convocation (accusé de lecture, vu par la Direction). Refusé si elle n'a pas été envoyée à ce compte."""
    try:
        id_conv = int(id_conv)
    except (TypeError, ValueError):
        raise parents.AccesRefuse("Cette convocation n'est pas destinée à votre compte.") from None
    d = conn.execute("SELECT D.LU_LE FROM CONVOCATION_DESTINATAIRE D JOIN CONVOCATION_PARENT V ON V.ID_CONV = D.ID_CONV "
                     "WHERE D.ID_CONV = ? AND D.ID_PARENT = ? AND V.STATUT IN ('ENVOYEE','ANNULEE')", (id_conv, id_parent)).fetchone()
    if not d:
        raise parents.AccesRefuse("Cette convocation n'est pas destinée à votre compte.")
    if not d["LU_LE"]:
        with conn:
            conn.execute("UPDATE CONVOCATION_DESTINATAIRE SET LU_LE = ? WHERE ID_CONV = ? AND ID_PARENT = ?", (iso(maintenant()), id_conv, id_parent))
            journaliser(conn, None, f"parent:{id_parent}", "PARENT_CONVOCATION_LUE", f"n° {id_conv}")
    return {"id": id_conv, "lue": True}
