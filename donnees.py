"""Lecture des données scolaires : recherche d'élève, scolarité, situation financière."""
import unicodedata
from dataclasses import dataclass


def sans_accents(texte) -> str:
    decompose = unicodedata.normalize("NFD", (texte or "").lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def nom_complet(ligne) -> str:
    return " ".join(p for p in (ligne["NOM"], ligne["POSTNOM"], ligne["PRENOM"]) if p)


def annee_courante(conn):
    ligne = conn.execute("SELECT ANNEESCO FROM ANNEE_SCO WHERE EN_COURS = 1 ORDER BY ANNEESCO DESC LIMIT 1").fetchone()
    if ligne:
        return ligne["ANNEESCO"]
    ligne = conn.execute("SELECT MAX(ANNEESCO) AS A FROM ANNEE_SCO").fetchone()
    return ligne["A"] if ligne else None


# ------------------------------------------------------------------ recherche
def rechercher_eleves(conn, terme, limite=60, session=None):
    """Recherche par matricule (exact) ou par fragments de nom / postnom / prénom, sans tenir
    compte des accents ni de la casse. Les élèves désactivés ne sont pas proposés. Retourne une liste de dicts."""
    terme = " ".join((terme or "").split())
    if len(terme) < 2:
        return []
    base = ("SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, C.DESI_CLASSE, C.N_CLASSE "
            "FROM ELEVE E LEFT JOIN INSCRIRE I ON I.MATRICULE = E.MATRICULE AND I.ANNEESCO = ? "
            "LEFT JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE ")
    annee = annee_courante(conn)
    exact = conn.execute(base + "WHERE E.MATRICULE = ? AND E.ACTIF = 1", (annee, terme)).fetchall()
    lignes = exact
    if not exact:
        fragments = [sans_accents(f) for f in terme.split()]
        lignes = []
        for l in conn.execute(base + "WHERE E.ACTIF = 1 ORDER BY E.NOM, E.POSTNOM, E.PRENOM", (annee,)):
            texte = sans_accents(f"{l['MATRICULE']} {l['NOM']} {l['POSTNOM'] or ''} {l['PRENOM'] or ''}")
            if all(f in texte for f in fragments):
                lignes.append(l)
                if len(lignes) >= limite:
                    break
    if session is not None:                                    # seulement les élèves des sections ouvertes à ce compte
        import sections
        lignes = [l for l in lignes if sections.peut_eleve(conn, session, l["MATRICULE"])]
    return [{"matricule": l["MATRICULE"], "nom_complet": nom_complet(l), "classe": l["DESI_CLASSE"] or "—"}
            for l in lignes]


def get_eleve(conn, matricule):
    return conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (matricule,)).fetchone()


def inscriptions(conn, matricule):
    """Toutes les années où l'élève a été inscrit, la plus récente d'abord."""
    return conn.execute(
        "SELECT I.ANNEESCO, I.N_CLASSE, I.STATUT, I.DATE_INSCRIPTION, C.DESI_CLASSE, "
        "       N.DESI_NIVEAU, O.DESI_OPTION "
        "FROM INSCRIRE I JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE "
        "JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
        "LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION "
        "WHERE I.MATRICULE = ? ORDER BY I.ANNEESCO DESC", (matricule,)).fetchall()


# ------------------------------------------------------------------ montants dus et tranches
MAX_TRANCHES = 36                  # nombre maximal de tranches d'un frais (au-delà, ce serait une erreur de saisie)


def lire_tranches(texte) -> tuple:
    """Texte enregistré (« 10000;10000;10000 », centimes) -> (10000, 10000, 10000). Vide ou illisible : ()."""
    try:
        return tuple(int(x) for x in (texte or "").split(";") if x.strip())
    except ValueError:
        return ()


def ecrire_tranches(montants) -> str:
    """(10000, 10000) -> « 10000;10000 » (ce qui est enregistré dans la colonne TRANCHES)."""
    return ";".join(str(int(m)) for m in montants)


def paliers(tranches, montant, par_tranche) -> tuple | None:
    """Montants CUMULÉS (en centimes) auxquels un paiement doit s'arrêter, du premier au dernier.
    - frais payé en une seule fois : un seul palier, le montant total ;
    - frais payé par tranches : un palier par tranche ; `tranches` = montant de chaque tranche (en centimes) ;
    - retourne None si le frais est « par tranches » mais que ses tranches ne sont pas définies ou ne totalisent
      pas exactement le montant dû."""
    if not par_tranche:
        return (montant,)
    montants = tuple(tranches or ())
    if not montants or any(m <= 0 for m in montants) or sum(montants) != montant:
        return None
    resultat, cumul = [], 0
    for m in montants:
        cumul += m
        resultat.append(cumul)
    return tuple(resultat)


# Frais obligatoires réservés à une année d'étude (TYPE_FRAIS.CLASSE_CIBLE) : code -> libellé
CIBLES = {"HUM4": "4ème année des humanités", "PRIM6": "6ème année du primaire", "SEC8": "8ème année du secondaire"}


def cible_de_classe(conn, n_classe):
    """Code (HUM4, PRIM6, SEC8) de l'année d'étude de la classe, ou None si elle n'est aucune de ces trois-là.
    La section du niveau distingue le primaire du secondaire : « 4ème » du secondaire = 4ème humanités, « 6ème » du primaire,
    « 8ème » du secondaire. L'année d'étude est lue dans ANNEE_ETUDE, à défaut dans la désignation de la classe."""
    import re
    try:
        n_classe = int(n_classe)
    except (TypeError, ValueError):
        return None
    l = conn.execute("SELECT C.ANNEE_ETUDE, C.DESI_CLASSE, N.SECTION FROM CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU "
                     "WHERE C.N_CLASSE = ?", (n_classe,)).fetchone()
    if not l:
        return None
    m = re.search(r"\d+", l["ANNEE_ETUDE"] or l["DESI_CLASSE"] or "")
    annee = int(m.group()) if m else None
    if l["SECTION"] == "PRIMAIRE":
        return "PRIM6" if annee == 6 else None
    return {4: "HUM4", 8: "SEC8"}.get(annee)


def frais_concerne(conn, codtf, n_classe) -> bool:
    """Un frais sans classe cible concerne toutes les classes ; un frais cible ne concerne que les élèves de cette année d'étude."""
    l = conn.execute("SELECT CLASSE_CIBLE FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
    return bool(l) and (l["CLASSE_CIBLE"] is None or l["CLASSE_CIBLE"] == cible_de_classe(conn, n_classe))


def conditions_du(conn, codtf, n_classe, annee):
    """(montant en centimes, devise, tranches) dû pour ce frais dans cette classe et cette année, ou None s'il n'y en a pas.
    Le tarif particulier de la classe (montant, devise ET tranches) s'il existe ; sinon ceux du type de frais."""
    l = conn.execute(
        "SELECT F.PAR_TRANCHE, T.CODTF AS A_TARIF, T.MONTANT AS TM, T.CODE_DEVISE AS TD, T.TRANCHES AS TT, "
        "       F.MONTANT AS FM, F.CODE_DEVISE AS FD, F.TRANCHES AS FT "
        "FROM TYPE_FRAIS F LEFT JOIN TARIF T ON T.CODTF = F.CODTF AND T.N_CLASSE = ? AND T.ANNEESCO = ? "
        "WHERE F.CODTF = ?", (n_classe, annee, codtf)).fetchone()
    if not l or not frais_concerne(conn, codtf, n_classe):
        return None
    montant, devise, tranches = (l["TM"], l["TD"], l["TT"]) if l["A_TARIF"] else (l["FM"], l["FD"], l["FT"])
    if montant is None or not devise:
        return None
    return montant, devise, lire_tranches(tranches)


def montant_du(conn, codtf, n_classe, annee):
    """(montant en centimes, devise) dû pour ce frais dans cette classe et cette année, ou None s'il n'y en a pas."""
    c = conditions_du(conn, codtf, n_classe, annee)
    return (c[0], c[1]) if c else None


# ------------------------------------------------------------------ situation financière
@dataclass
class LigneSituation:
    annee: str
    codtf: str
    designation: str
    devise: str
    du: int
    paye: int
    par_tranche: bool = False
    paliers: tuple = ()            # paliers cumulés ; vide : frais par tranches dont les tranches sont mal définies

    @property
    def reste(self) -> int:
        return max(0, self.du - self.paye)

    @property
    def statut(self) -> str:
        if self.paye >= self.du:
            return "Soldé"
        return "Partiel" if self.paye > 0 else "Non payé"

    @property
    def tranches_mal_definies(self) -> bool:
        return self.par_tranche and not self.paliers

    @property
    def prochain_montant(self) -> int:
        """Ce que l'élève doit payer maintenant : la prochaine tranche (ou le reste, pour un frais payé en une fois)."""
        if self.reste <= 0:
            return 0
        suivants = [p for p in self.paliers if p > self.paye]
        return (suivants[0] - self.paye) if suivants else self.reste

    @property
    def numero_tranche(self) -> int:
        """N° de la prochaine tranche à payer (1 si rien n'est payé)."""
        return 1 + sum(1 for p in self.paliers if p <= self.paye)

    @property
    def mode(self) -> str:
        if not self.par_tranche:
            return "Paiement en une seule fois"
        if not self.paliers:
            return "Tranches non définies (leur total doit faire le montant dû)"
        return f"Par tranches : tranche {self.numero_tranche} sur {len(self.paliers)}" if self.reste > 0 \
            else f"Par tranches : {len(self.paliers)} tranche(s) payée(s)"


def situation(conn, matricule, annee, n_classe):
    """Frais dus par l'élève pour une année (selon sa classe) et ce qu'il a déjà payé. Un frais est dû s'il a un
    tarif pour cette classe et cette année, ou, à défaut, un montant dans le type de frais (si le type est actif).
    Un frais sans tarif pour la classe et sans montant dans le type n'est pas dû (il dépend de la classe).
    Les frais d'inscription ne sont jamais dus par un élève déjà inscrit (il a un matricule) : ils ne concernent que les
    candidats qui souhaitent s'inscrire à l'école. Un frais obligatoire réservé à une année d'étude (examen d'État et dissertation en
    4ème humanités, ENAFEP en 6ème primaire, TENASSOP en 8ème) n'est dû que par les élèves de cette année d'étude."""
    lignes = conn.execute(
        "SELECT F.CODTF, F.DESITF, F.PAR_TRANCHE, "
        "  CASE WHEN T.CODTF IS NOT NULL THEN T.CODE_DEVISE ELSE F.CODE_DEVISE END AS DEVISE, "
        "  CASE WHEN T.CODTF IS NOT NULL THEN T.MONTANT ELSE F.MONTANT END AS MONTANT, "
        "  CASE WHEN T.CODTF IS NOT NULL THEN T.TRANCHES ELSE F.TRANCHES END AS TRANCHES, "
        "  COALESCE((SELECT SUM(P.MONT_PAYE) FROM PAIEMENT P WHERE P.ANNEESCO = ? "
        "            AND P.MATRICULE = ? AND P.CODTF = F.CODTF AND P.STATUT = 'VALIDE'), 0) AS PAYE "
        "FROM TYPE_FRAIS F LEFT JOIN TARIF T ON T.CODTF = F.CODTF AND T.ANNEESCO = ? AND T.N_CLASSE = ? "
        "WHERE (CASE WHEN T.CODTF IS NOT NULL THEN T.MONTANT ELSE F.MONTANT END) IS NOT NULL "
        "  AND (CASE WHEN T.CODTF IS NOT NULL THEN T.CODE_DEVISE ELSE F.CODE_DEVISE END) IS NOT NULL "
        "  AND (T.CODTF IS NOT NULL OR F.ACTIF = 1) "
        "  AND F.POUR_INSCRIPTION = 0 "
        "  AND (F.CLASSE_CIBLE IS NULL OR F.CLASSE_CIBLE = ?) "
        "ORDER BY F.CODTF", (annee, matricule, annee, n_classe, cible_de_classe(conn, n_classe))).fetchall()
    resultat = []
    for l in lignes:
        pal = paliers(lire_tranches(l["TRANCHES"]), l["MONTANT"], bool(l["PAR_TRANCHE"]))
        resultat.append(LigneSituation(annee, l["CODTF"], l["DESITF"], l["DEVISE"],
                                       l["MONTANT"], l["PAYE"], bool(l["PAR_TRANCHE"]), tuple(pal or ())))
    return resultat


def totaux_par_devise(lignes):
    """{devise: (dû, payé, reste)}"""
    totaux = {}
    for l in lignes:
        du, paye, reste = totaux.get(l.devise, (0, 0, 0))
        totaux[l.devise] = (du + l.du, paye + min(l.paye, l.du), reste + l.reste)
    return totaux


def dettes(conn, matricule):
    """Dettes restantes, toutes années confondues : liste de (année, devise, reste)."""
    resultat = []
    for insc in inscriptions(conn, matricule):
        reste_par_devise = {}
        for l in situation(conn, matricule, insc["ANNEESCO"], insc["N_CLASSE"]):
            if l.reste:
                reste_par_devise[l.devise] = reste_par_devise.get(l.devise, 0) + l.reste
        resultat += [(insc["ANNEESCO"], d, r) for d, r in reste_par_devise.items()]
    return resultat
