"""Mise à jour des tables de référence (Travaux techniques > Mise à jour des tables, ADMINISTRATEUR uniquement).

Chaque table est décrite une seule fois (champs, colonnes à afficher, règles) ; l'écran et les contrôles s'en servent.
Opérations : ajouter, modifier, supprimer, désactiver / réactiver ; pour les paiements : annuler.

Règles de sécurité :
- tout est réservé à l'Administrateur (contrôle refait dans la base à chaque opération) et journalisé ;
- une donnée UTILISÉE ailleurs ne peut pas être supprimée (on propose de la désactiver : elle n'est plus proposée,
  mais l'historique reste intact) ;
- la clé d'une donnée (code, matricule...) ne se modifie pas après création : d'autres tables s'y réfèrent ;
- un reçu ne se modifie ni ne se supprime jamais : il peut seulement être annulé (motif obligatoire).
"""
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

import argent
import donnees
import droits
from database import iso, journaliser, lire_iso, maintenant


class ErreurRef(Exception):
    """Erreur dont le message peut être affiché tel quel."""


class ErreurUtilisee(ErreurRef):
    """La donnée est utilisée ailleurs : l'écran peut alors proposer de supprimer aussi les données liées."""


@dataclass(frozen=True)
class Champ:
    nom: str
    libelle: str
    type: str = "texte"            # texte | date | montant | choix | reference | oui_non | tranches
    obligatoire: bool = True
    cle: bool = False              # fait partie de la clé primaire (non modifiable après création)
    auto: bool = False             # numéro attribué automatiquement
    genere: bool = False           # texte attribué par le système à l'ajout (matricule d'un élève) : non saisi
    choix: tuple = ()              # type choix : ((valeur, libellé), ...)
    ref: Optional[str] = None      # type reference : clé de REFS
    longueur: int = 60
    majuscules: bool = False
    regex: Optional[str] = None
    regex_msg: str = ""
    defaut: object = None          # valeur proposée à l'ajout ("aujourdhui" pour une date)
    multiple: bool = False         # type reference : à l'ajout, on peut en cocher plusieurs (une ligne créée pour chacun)


@dataclass(frozen=True)
class Table:
    cle: str
    titre: str
    sql: str                       # table écrite
    champs: tuple
    from_sql: str                  # FROM de la liste affichée
    alias: str
    colonnes: tuple                # ((titre, expression SQL, largeur, ancrage, genre), ...)
    tri: str
    etat: Optional[str] = None     # expression SQL 1/0 (actif / inactif) pour la liste
    actif_col: Optional[str] = None            # colonne de désactivation de la table elle-même
    basculer: Optional[Callable] = None        # désactivation particulière (ex. percepteur -> compte)
    peut_creer: bool = True
    peut_modifier: bool = True
    peut_supprimer: bool = True
    peut_desactiver: bool = True
    peut_annuler: bool = False                 # paiements uniquement
    verif: Optional[Callable] = None           # (conn, valeurs, ancien, ancienne_cle) -> lève ErreurRef
    apres: Optional[Callable] = None           # (conn, valeurs, cle_pk) dans la même transaction
    generer: Optional[Callable] = None         # (conn, valeurs) à l'ajout : attribue clé et codes générés par le système
    verif_suppression: Optional[Callable] = None   # (conn, cle_pk) avant une suppression : lève ErreurRef pour la refuser
    aide: str = ""

    @property
    def cles(self):
        return [c for c in self.champs if c.cle]


# ================================================================== listes de choix (champs « reference »)
REFS = {
    "annees": dict(table="ANNEE_SCO", valeur="ANNEESCO", libelle="ANNEESCO", actif="ACTIF", tri="ANNEESCO DESC"),
    "niveaux": dict(table="NIVEAU", valeur="CODE_NIVEAU", libelle="CODE_NIVEAU || ' - ' || DESI_NIVEAU", actif="ACTIF",
                    tri="CODE_NIVEAU"),
    "options": dict(table="OPTION_SCO", valeur="CODE_OPTION", libelle="CODE_OPTION || ' - ' || DESI_OPTION",
                    actif="ACTIF", tri="CODE_OPTION"),
    "classes": dict(table="CLASSE", valeur="N_CLASSE", entier=True, actif="ACTIF", tri="DESI_CLASSE",
                    libelle="DESI_CLASSE || ' (' || CODE_NIVEAU || COALESCE(' / ' || CODE_OPTION, '') || ')'"),
    "devises": dict(table="DEVISE", valeur="CODE_DEVISE", libelle="CODE_DEVISE || ' - ' || DESI_DEVISE", actif="ACTIF",
                    tri="CODE_DEVISE"),
    "types_frais": dict(table="TYPE_FRAIS", valeur="CODTF", libelle="CODTF || ' - ' || DESITF", actif="ACTIF", tri="CODTF"),
    "eleves": dict(table="ELEVE", valeur="MATRICULE", actif="ACTIF", tri="NOM, POSTNOM, PRENOM",
                   libelle="MATRICULE || ' - ' || NOM || COALESCE(' ' || POSTNOM, '') || COALESCE(' ' || PRENOM, '')"),
    "comptes_percepteurs": dict(     # comptes de poste PERCEPTEUR pas encore enregistrés comme percepteurs
        table="UTILISATEUR", valeur="ID_USER", entier=True, tri="NOM_COMPLET COLLATE NOCASE",
        libelle="NOM_COMPLET || ' (' || LOGIN || ')'",
        filtre="ACTIF = 1 AND ROLE = 'PERCEPTEUR' AND ID_USER NOT IN (SELECT ID_USER FROM PERCEPTEUR)"),
}


def options(conn, ref, inclure=None) -> list:
    """[(valeur, libellé)] pour une liste déroulante. Les données désactivées ne sont pas proposées
    (sauf `inclure` : la valeur déjà enregistrée, pour pouvoir la garder)."""
    r = REFS[ref]
    conditions, params = [], []
    if r.get("filtre"):
        conditions.append(r["filtre"])
    if r.get("actif"):
        conditions.append(f"({r['actif']} = 1 OR {r['valeur']} = ?)")
        params.append(inclure)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    lignes = conn.execute(f"SELECT {r['valeur']}, {r['libelle']} FROM {r['table']}{where} ORDER BY {r['tri']}", params)
    return [(l[0], l[1]) for l in lignes]


# ================================================================== contrôles propres à certaines tables
def _nb_paiements(conn, where, params) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM PAIEMENT WHERE {where}", params).fetchone()[0]


def _verif_annee(conn, valeurs, ancien, ancienne_cle):
    a = valeurs.get("ANNEESCO")
    if a and int(a[5:]) != int(a[:4]) + 1:
        raise ErreurRef("Une année scolaire s'écrit avec deux années qui se suivent, par exemple 2026-2027.")


def _apres_annee(conn, valeurs, cle_pk):
    if valeurs.get("EN_COURS"):                       # une seule année en cours à la fois
        conn.execute("UPDATE ANNEE_SCO SET EN_COURS = 0 WHERE ANNEESCO <> ?", (cle_pk[0],))


def _designation_classe(annee_etude, division) -> str:
    """Désignation composée par le système : année d'étude + division (« 1ère A », « 7ème », « 3ème B »)."""
    return " ".join(p for p in (annee_etude, division) if p)


def _verif_classe(conn, valeurs, ancien, ancienne_cle):
    niveau, option = valeurs.get("CODE_NIVEAU"), valeurs.get("CODE_OPTION")
    a_des_options = conn.execute("SELECT 1 FROM POSSEDE WHERE CODE_NIVEAU = ?", (niveau,)).fetchone()
    if option and not conn.execute("SELECT 1 FROM POSSEDE WHERE CODE_NIVEAU = ? AND CODE_OPTION = ?",
                                   (niveau, option)).fetchone():
        raise ErreurRef(f"L'option {option} n'est pas proposée au niveau {niveau} : les options ne concernent que les "
                        f"humanités. Ajoutez-la d'abord dans « Options par niveau », ou laissez l'option vide.")
    if not option and a_des_options:
        raise ErreurRef(f"Le niveau {niveau} propose des options (humanités) : choisissez l'option de cette classe.")
    division = (valeurs.get("DIVISION") or "").upper()
    numero = ancienne_cle[0] if ancienne_cle else -1
    if conn.execute("SELECT 1 FROM CLASSE WHERE CODE_NIVEAU = ? AND LOWER(ANNEE_ETUDE) = LOWER(?) "
                    "AND COALESCE(UPPER(DIVISION), '') = ? AND COALESCE(CODE_OPTION, '') = ? AND N_CLASSE <> ?",
                    (niveau, valeurs.get("ANNEE_ETUDE"), division, option or "", numero)).fetchone():
        raise ErreurRef("Cette classe existe déjà (même niveau, même année d'étude, même division, même option).")


def _generer_classe(conn, valeurs):
    valeurs["DESI_CLASSE"] = _designation_classe(valeurs.get("ANNEE_ETUDE"), valeurs.get("DIVISION"))


def _apres_classe(conn, valeurs, cle_pk):
    """La désignation suit toujours l'année d'étude et la division (aussi après une modification)."""
    conn.execute("UPDATE CLASSE SET DESI_CLASSE = ? WHERE N_CLASSE = ?",
                 (_designation_classe(valeurs.get("ANNEE_ETUDE"), valeurs.get("DIVISION")), cle_pk[0]))


def _controler_tranches(par_tranche, montant, tranches_txt):
    """Les tranches d'un frais : le montant de CHAQUE tranche est fixé librement, en nombre libre ; leur total doit faire
    exactement le montant dû. Un frais payé en une seule fois n'a pas de tranches."""
    tranches = donnees.lire_tranches(tranches_txt)
    if not par_tranche:
        if tranches:
            raise ErreurRef("Ce frais se paie en une seule fois : laissez « Tranches » vide (ou cochez « Payé par tranches »).")
        return
    if montant is None:
        if tranches:
            raise ErreurRef("Ce frais n'a pas de montant propre (il dépend de la classe) : ne saisissez pas de tranches ici, "
                            "mais dans « Tarifs », classe par classe.")
        return
    if not tranches:
        raise ErreurRef("Frais payé par tranches : indiquez le montant de chaque tranche, séparés par « ; » "
                        "(ex. 100;100;100 ou 3x100). Leur total doit faire le montant.")
    total = sum(tranches)
    if total != montant:
        ecart = montant - total
        raise ErreurRef(f"Le total des tranches ({argent.formater(total)}) doit faire exactement le montant "
                        f"({argent.formater(montant)}) : il "
                        f"{'manque' if ecart > 0 else 'y a en trop'} {argent.formater(abs(ecart))}.")


def _verif_type_frais(conn, valeurs, ancien, ancienne_cle):
    # un frais qui dépend de la classe n'a pas de montant propre : son montant se fixe classe par classe (Tarifs)
    if (valeurs.get("MONTANT") is None) != (valeurs.get("CODE_DEVISE") is None):
        raise ErreurRef("Renseignez ensemble le montant et la devise, ou laissez les deux vides si le montant dépend de la "
                        "classe (il se fixe alors dans « Tarifs »).")
    _controler_tranches(bool(valeurs.get("PAR_TRANCHE")), valeurs.get("MONTANT"), valeurs.get("TRANCHES"))
    if valeurs.get("POUR_INSCRIPTION") and valeurs.get("PAR_TRANCHE"):
        raise ErreurRef("Les frais d'inscription se paient en une seule fois : décochez « Payé par tranches », "
                        "ou décochez « Frais d'inscription ».")
    if valeurs.get("CLASSE_CIBLE") and (valeurs.get("POUR_INSCRIPTION") or valeurs.get("POUR_APPLI_PARENTS")):
        raise ErreurRef("Un frais réservé à une année d'étude ne peut pas être « Frais d'inscription » ni « Frais du logiciel des parents ».")
    if valeurs.get("POUR_APPLI_PARENTS") and valeurs.get("POUR_INSCRIPTION"):
        raise ErreurRef("Un même frais ne peut pas être à la fois « Frais d'inscription » et « Frais du logiciel des parents ».")
    if valeurs.get("POUR_APPLI_PARENTS") and valeurs.get("PAR_TRANCHE"):
        raise ErreurRef("Le frais du logiciel des parents se paie en une seule fois : décochez « Payé par tranches », "
                        "ou décochez « Frais du logiciel des parents ».")
    if ancien is None:
        return
    if _nb_paiements(conn, "CODTF = ?", (ancien["CODTF"],)):
        if ancien["CODE_DEVISE"] and valeurs["CODE_DEVISE"] != ancien["CODE_DEVISE"]:
            raise ErreurRef("Des paiements existent pour ce type de frais : on ne peut plus changer sa devise.")
        if valeurs["PAR_TRANCHE"] != ancien["PAR_TRANCHE"]:
            raise ErreurRef("Des paiements existent pour ce type de frais : on ne peut plus changer sa façon de se payer "
                            "(en une fois ou par tranches).")


def _verif_inscription(conn, valeurs, ancien, ancienne_cle):
    if ancien is None:
        if not conn.execute("SELECT ACTIF FROM ELEVE WHERE MATRICULE = ?", (valeurs["MATRICULE"],)).fetchone()["ACTIF"]:
            raise ErreurRef("Cet élève est désactivé : inscription impossible.")
        return
    if valeurs["N_CLASSE"] != ancien["N_CLASSE"] and _nb_paiements(
            conn, "ANNEESCO = ? AND MATRICULE = ?", (ancien["ANNEESCO"], ancien["MATRICULE"])):
        raise ErreurRef("Des paiements existent déjà pour cette inscription : on ne peut plus changer la classe "
                        "(les reçus restent attachés à la classe de l'époque).")


def _verif_tarif(conn, valeurs, ancien, ancienne_cle):
    codtf = ancien["CODTF"] if ancien else valeurs["CODTF"]          # la clé n'est pas dans `valeurs` à la modification
    frais = conn.execute("SELECT PAR_TRANCHE FROM TYPE_FRAIS WHERE CODTF = ?", (codtf,)).fetchone()
    par_tranche = bool(frais and frais["PAR_TRANCHE"])
    _controler_tranches(par_tranche, valeurs["MONTANT"], valeurs.get("TRANCHES"))
    if ancien is None:
        return
    cle = (ancien["CODTF"], ancien["N_CLASSE"], ancien["ANNEESCO"])
    paye = conn.execute("SELECT COALESCE(SUM(MONT_PAYE), 0) FROM PAIEMENT WHERE CODTF = ? AND N_CLASSE = ? AND ANNEESCO = ? "
                        "AND STATUT = 'VALIDE'", cle).fetchone()[0]
    if _nb_paiements(conn, "CODTF = ? AND N_CLASSE = ? AND ANNEESCO = ?", cle):
        if par_tranche and (valeurs["MONTANT"] != ancien["MONTANT"] or valeurs.get("TRANCHES") != ancien["TRANCHES"]):
            raise ErreurRef("Ce frais est payé par tranches et des paiements existent déjà : son montant et ses tranches "
                            "ne peuvent plus changer pour cette classe et cette année (les tranches déjà payées ne "
                            "correspondraient plus).")
        if valeurs["CODE_DEVISE"] != ancien["CODE_DEVISE"]:
            raise ErreurRef("Des paiements existent pour ce tarif : on ne peut plus changer sa devise.")
        if valeurs["MONTANT"] < paye:
            raise ErreurRef(f"Des paiements pour {argent.formater(paye)} {ancien['CODE_DEVISE']} existent déjà : "
                            f"le tarif ne peut pas descendre en dessous.")


def _basculer_percepteur(conn, cle_pk, actif):
    conn.execute("UPDATE UTILISATEUR SET ACTIF = ? WHERE ID_USER = (SELECT ID_USER FROM PERCEPTEUR WHERE N_PERC = ?) "
                 "AND ROLE = 'PERCEPTEUR'", (int(actif), cle_pk[0]))


def _simple(cle, titre, sql, alias, code, desi, long_code, aide="", verif=None):
    """Table à deux champs : un code (clé) et une désignation."""
    return Table(
        cle, titre, sql,
        champs=(Champ(code, "Code", cle=True, longueur=long_code, majuscules=True,
                      regex=r"[A-Za-z0-9._-]+", regex_msg="Le code s'écrit sans espace (lettres, chiffres, - _ .)."),
                Champ(desi, "Désignation", longueur=80)),
        from_sql=f"{sql} {alias}", alias=alias,
        colonnes=(("Code", f"{alias}.{code}", 110, "w", None), ("Désignation", f"{alias}.{desi}", 380, "w", None)),
        tri=f"{alias}.{code}", etat=f"{alias}.ACTIF", actif_col="ACTIF", aide=aide, verif=verif)


_SECTIONS = (("PRIMAIRE", "Primaire"), ("SECONDAIRE", "Secondaire et humanitaire"))
_CIBLES = (("HUM4", "4ème année des humanités"), ("PRIM6", "6ème année du primaire"), ("SEC8", "8ème année du secondaire"))
_STATUTS = (("NOUVEAU", "Nouveau"), ("REDOUBLANT", "Redoublant"), ("TRANSFERT", "Transfert"), ("ANCIEN", "Ancien"))

TABLES = {t.cle: t for t in (
    Table("annees", "Années scolaires", "ANNEE_SCO",
          champs=(Champ("ANNEESCO", "Année scolaire (ex. 2026-2027)", cle=True, longueur=9, regex=r"\d{4}-\d{4}",
                        regex_msg="Écrivez l'année ainsi : 2026-2027."),
                  Champ("EN_COURS", "Année en cours", type="oui_non", obligatoire=False)),
          from_sql="ANNEE_SCO A", alias="A",
          colonnes=(("Année scolaire", "A.ANNEESCO", 170, "w", None), ("En cours", "A.EN_COURS", 110, "center", "oui_non")),
          tri="A.ANNEESCO DESC", etat="A.ACTIF", actif_col="ACTIF", verif=_verif_annee, apres=_apres_annee,
          aide="Une seule année peut être « en cours » : c'est celle qui sert à la consultation et aux paiements."),
    Table("niveaux", "Niveaux", "NIVEAU",
          champs=(Champ("CODE_NIVEAU", "Code", cle=True, longueur=10, majuscules=True, regex=r"[A-Za-z0-9._-]+",
                        regex_msg="Le code s'écrit sans espace (lettres, chiffres, - _ .)."),
                  Champ("DESI_NIVEAU", "Désignation", longueur=80),
                  Champ("SECTION", "Section de l'école", type="choix", choix=_SECTIONS, defaut="SECONDAIRE")),
          from_sql="NIVEAU N", alias="N",
          colonnes=(("Code", "N.CODE_NIVEAU", 110, "w", None), ("Désignation", "N.DESI_NIVEAU", 300, "w", None),
                    ("Section", "CASE N.SECTION WHEN 'PRIMAIRE' THEN 'Primaire' ELSE 'Secondaire et humanitaire' END", 220, "w", None)),
          tri="N.CODE_NIVEAU", etat="N.ACTIF", actif_col="ACTIF",
          aide="Le niveau est le cycle d'études : Primaire (de la 1ère à la 6ème), Secondaire (7ème et 8ème) et "
               "Humanités (de la 1ère à la 4ème). La SECTION sépare l'école primaire de l'école secondaire et humanitaire : "
               "chaque compte ne voit que les sections qui lui sont ouvertes (Gestionnaire d'accès > Autorisations), il n'y a pas de "
               "carte d'élève au primaire, et le titulaire d'une classe primaire est l'unique enseignant de sa classe. "
               "Les classes (1ère A, 1ère B...) s'ajoutent ensuite dans « Classes »."),
    _simple("options", "Options", "OPTION_SCO", "O", "CODE_OPTION", "DESI_OPTION", 10,
            aide="Les options (Scientifique, Pédagogie, Commerciale et Gestion...) ne concernent que les élèves des "
                 "humanités, de la 1ère à la 4ème."),
    Table("possede", "Options par niveau", "POSSEDE",
          champs=(Champ("CODE_NIVEAU", "Niveau", type="reference", ref="niveaux", cle=True),
                  Champ("CODE_OPTION", "Option", type="reference", ref="options", cle=True)),
          from_sql="POSSEDE P JOIN NIVEAU N ON N.CODE_NIVEAU = P.CODE_NIVEAU JOIN OPTION_SCO O ON O.CODE_OPTION = P.CODE_OPTION",
          alias="P",
          colonnes=(("Niveau", "N.CODE_NIVEAU || ' - ' || N.DESI_NIVEAU", 300, "w", None),
                    ("Option", "O.CODE_OPTION || ' - ' || O.DESI_OPTION", 340, "w", None)),
          tri="N.CODE_NIVEAU, O.CODE_OPTION", peut_modifier=False, peut_desactiver=False,
          aide="Indique quelles options existent dans quel niveau : à faire pour le niveau Humanités seulement. Un niveau "
               "qui a des options exige une option dans chacune de ses classes."),
    Table("classes", "Classes", "CLASSE",
          champs=(Champ("N_CLASSE", "N° de classe", cle=True, auto=True),
                  Champ("ANNEE_ETUDE", "Classe (ex. 1ère, 2ème, 6ème, 7ème)", longueur=30),
                  Champ("DIVISION", "Division (A, B, C, D...) - vide s'il n'y en a pas", obligatoire=False, longueur=3,
                        majuscules=True, regex=r"[A-Za-z0-9]{1,3}", regex_msg="La division s'écrit avec 1 à 3 lettres ou chiffres (ex. A)."),
                  Champ("CODE_NIVEAU", "Niveau (primaire, secondaire, humanités)", type="reference", ref="niveaux"),
                  Champ("CODE_OPTION", "Option (humanités seulement)", type="reference", ref="options", obligatoire=False)),
          from_sql="CLASSE C JOIN NIVEAU N ON N.CODE_NIVEAU = C.CODE_NIVEAU LEFT JOIN OPTION_SCO O ON O.CODE_OPTION = C.CODE_OPTION",
          alias="C",
          colonnes=(("N°", "C.N_CLASSE", 60, "center", None), ("Classe", "C.DESI_CLASSE", 200, "w", None),
                    ("Division", "COALESCE(C.DIVISION, '')", 80, "center", None),
                    ("Niveau", "N.CODE_NIVEAU || ' - ' || N.DESI_NIVEAU", 220, "w", None),
                    ("Option", "COALESCE(O.CODE_OPTION || ' - ' || O.DESI_OPTION, '')", 220, "w", None)),
          tri="C.N_CLASSE", etat="C.ACTIF", actif_col="ACTIF", verif=_verif_classe, generer=_generer_classe,
          apres=_apres_classe,
          aide="Une ligne par division : 1ère A, 1ère B, 1ère C... La désignation est composée par le système (classe + "
               "division). L'option n'existe que pour le niveau Humanités (1ère à 4ème) et y est obligatoire."),
    _simple("devises", "Devises", "DEVISE", "D", "CODE_DEVISE", "DESI_DEVISE", 5),
    Table("types_frais", "Types de frais", "TYPE_FRAIS",
          champs=(Champ("CODTF", "Code", cle=True, longueur=10, majuscules=True, regex=r"[A-Za-z0-9._-]+",
                        regex_msg="Le code s'écrit sans espace (lettres, chiffres, - _ .)."),
                  Champ("DESITF", "Désignation", longueur=80),
                  Champ("MONTANT", "Montant pour toutes les classes (ex. 25 ou 25,50) - VIDE si le montant dépend de la classe",
                        type="montant", obligatoire=False),
                  Champ("CODE_DEVISE", "Devise (avec le montant)", type="reference", ref="devises", obligatoire=False),
                  Champ("PAR_TRANCHE", "Payé par tranches (réservé au frais scolaire)", type="oui_non", obligatoire=False),
                  Champ("TRANCHES", "Tranches : montant de chaque tranche, séparés par « ; » (ex. 100;100;100 ou 3x100)",
                        type="tranches", obligatoire=False),
                  Champ("POUR_INSCRIPTION", "Frais d'inscription (le module Inscription exige ce paiement avant de valider une candidature)",
                        type="oui_non", obligatoire=False),
                  Champ("POUR_APPLI_PARENTS", "Frais du logiciel des parents (son paiement génère le code d'accès à l'application mobile des parents)",
                        type="oui_non", obligatoire=False),
                  Champ("CLASSE_CIBLE", "Frais obligatoire réservé à une année d'étude (vide : toutes les classes)",
                        type="choix", choix=_CIBLES, obligatoire=False)),
          from_sql="TYPE_FRAIS F", alias="F",
          colonnes=(("Code", "F.CODTF", 90, "w", None), ("Désignation", "F.DESITF", 260, "w", None),
                    ("Montant", "COALESCE(F.MONTANT, 'Selon la classe')", 120, "e", "montant"),
                    ("Devise", "COALESCE(F.CODE_DEVISE, '')", 70, "center", None),
                    ("Paiement", "CASE WHEN F.PAR_TRANCHE = 0 THEN 'En une seule fois' "
                                 "WHEN F.MONTANT IS NULL THEN 'Par tranches (voir Tarifs)' "
                                 "WHEN F.TRANCHES IS NULL THEN 'Tranches à définir' "
                                 "ELSE (LENGTH(F.TRANCHES) - LENGTH(REPLACE(F.TRANCHES, ';', '')) + 1) || ' tranche(s)' END",
                     170, "w", None),
                    ("Tranches", "COALESCE(F.TRANCHES, '')", 230, "w", "tranches"),
                    ("Inscription", "CASE WHEN F.POUR_INSCRIPTION = 1 THEN 'Oui' ELSE '' END", 90, "center", None),
                    ("App. parents", "CASE WHEN F.POUR_APPLI_PARENTS = 1 THEN 'Oui' ELSE '' END", 90, "center", None),
                    ("Réservé à", "CASE F.CLASSE_CIBLE WHEN 'HUM4' THEN '4ème humanités' WHEN 'PRIM6' THEN '6ème primaire' "
                                  "WHEN 'SEC8' THEN '8ème secondaire' ELSE '' END", 130, "w", None)),
          tri="F.CODTF", etat="F.ACTIF", actif_col="ACTIF", verif=_verif_type_frais,
          aide="Un type de frais a un code et une désignation. Deux cas : (1) le montant est le même dans toutes les classes "
               "(inscription, examen...) : saisissez le montant et la devise ; (2) le montant DÉPEND DE LA CLASSE (frais "
               "scolaire : 300 en 1ère-3ème, 600 en 4ème) : laissez le montant vide et fixez-le classe par classe dans « Tarifs ». "
               "Un frais « payé par tranches » se règle tranche par tranche : vous choisissez librement le nombre de tranches "
               "et le montant de chacune (leur total doit faire le montant). Tous les autres frais se paient en une seule fois."),
    Table("tarifs", "Tarifs", "TARIF",
          champs=(Champ("CODTF", "Type de frais", type="reference", ref="types_frais", cle=True),
                  Champ("N_CLASSE", "Classes qui paient ce tarif (cochez une ou plusieurs classes)", type="reference",
                        ref="classes", cle=True, multiple=True),
                  Champ("ANNEESCO", "Année scolaire", type="reference", ref="annees", cle=True),
                  Champ("MONTANT", "Montant (ex. 25 ou 25,50)", type="montant"),
                  Champ("CODE_DEVISE", "Devise", type="reference", ref="devises"),
                  Champ("TRANCHES", "Tranches (frais payé par tranches) : montant de chaque tranche, séparés par « ; » "
                                    "(ex. 100;100;100 ou 3x100)", type="tranches", obligatoire=False)),
          from_sql="TARIF T JOIN TYPE_FRAIS F ON F.CODTF = T.CODTF JOIN CLASSE C ON C.N_CLASSE = T.N_CLASSE", alias="T",
          colonnes=(("Année", "T.ANNEESCO", 100, "w", None), ("Type de frais", "F.CODTF || ' - ' || F.DESITF", 230, "w", None),
                    ("Montant", "T.MONTANT", 100, "e", "montant"), ("Devise", "T.CODE_DEVISE", 70, "center", None),
                    ("Tranches", "COALESCE(T.TRANCHES, '')", 230, "w", "tranches"),
                    ("Classe qui dépend de ce tarif", "C.DESI_CLASSE || COALESCE(' - ' || C.CODE_OPTION, '')", 260, "w", None)),
          tri="T.ANNEESCO DESC, F.CODTF, T.MONTANT, C.N_CLASSE", peut_desactiver=False, verif=_verif_tarif,
          aide="Montant dû pour un type de frais, une année et les classes cochées. C'est ici que se règlent les frais qui "
               "dépendent de la classe : par exemple le frais scolaire à 300 pour la 1ère, la 2ème et la 3ème, puis un second "
               "tarif à 600 pour la 4ème. Pour un frais payé par tranches, saisissez le montant de chaque tranche (nombre libre ; "
               "total = montant). Sans tarif, c'est le montant du type de frais qui s'applique."),
    Table("eleves", "Élèves", "ELEVE",
          champs=(Champ("MATRICULE", "Matricule (attribué par le système)", cle=True, longueur=20, majuscules=True,
                        genere=True, obligatoire=False),
                  Champ("NOM", "Nom", longueur=40),
                  Champ("POSTNOM", "Postnom", obligatoire=False, longueur=40),
                  Champ("PRENOM", "Prénom", obligatoire=False, longueur=40),
                  Champ("SEXE", "Sexe", type="choix", choix=(("M", "Masculin"), ("F", "Féminin")), obligatoire=False),
                  Champ("DATE_NAISSANCE", "Date de naissance (jj/mm/aaaa)", type="date", obligatoire=False),
                  Champ("LIEU_NAISSANCE", "Lieu de naissance", obligatoire=False),
                  Champ("NATIONALITE", "Nationalité", obligatoire=False, longueur=40),
                  Champ("ADRESSE", "Adresse", obligatoire=False, longueur=120),
                  Champ("TELEPHONE", "Téléphone", obligatoire=False, longueur=30),
                  Champ("NOM_TUTEUR", "Nom du tuteur", obligatoire=False, longueur=80),
                  Champ("TEL_TUTEUR", "Téléphone du tuteur", obligatoire=False, longueur=30)),
          from_sql="ELEVE E", alias="E",
          colonnes=(("Matricule", "E.MATRICULE", 110, "w", None),
                    ("Nom complet", "E.NOM || COALESCE(' ' || E.POSTNOM, '') || COALESCE(' ' || E.PRENOM, '')", 300, "w", None),
                    ("Sexe", "COALESCE(E.SEXE, '')", 60, "center", None),
                    ("Nationalité", "COALESCE(E.NATIONALITE, '')", 120, "w", None),
                    ("Naissance", "E.DATE_NAISSANCE", 110, "center", "date"),
                    ("Tuteur", "COALESCE(E.NOM_TUTEUR, '')", 200, "w", None),
                    ("Tél. tuteur", "COALESCE(E.TEL_TUTEUR, '')", 120, "w", None)),
          tri="E.NOM, E.POSTNOM, E.PRENOM", etat="E.ACTIF", actif_col="ACTIF", generer=lambda conn, v: _identite().generer(conn, v),
          aide="Le matricule (numéro d'ordre d'ajout) et le code QR de l'élève sont attribués automatiquement par le système."),
    Table("inscriptions", "Inscriptions", "INSCRIRE",
          champs=(Champ("ANNEESCO", "Année scolaire", type="reference", ref="annees", cle=True),
                  Champ("MATRICULE", "Élève", type="reference", ref="eleves", cle=True),
                  Champ("N_CLASSE", "Classe", type="reference", ref="classes"),
                  Champ("DATE_INSCRIPTION", "Date d'inscription (jj/mm/aaaa)", type="date", obligatoire=False,
                        defaut="aujourdhui"),
                  Champ("STATUT", "Statut", type="choix", choix=_STATUTS, defaut="NOUVEAU")),
          from_sql="INSCRIRE I JOIN ELEVE E ON E.MATRICULE = I.MATRICULE JOIN CLASSE C ON C.N_CLASSE = I.N_CLASSE",
          alias="I",
          colonnes=(("Année", "I.ANNEESCO", 100, "w", None), ("Matricule", "I.MATRICULE", 110, "w", None),
                    ("Élève", "E.NOM || COALESCE(' ' || E.POSTNOM, '') || COALESCE(' ' || E.PRENOM, '')", 280, "w", None),
                    ("Classe", "C.DESI_CLASSE", 230, "w", None), ("Statut", "I.STATUT", 110, "w", None),
                    ("Inscrit le", "I.DATE_INSCRIPTION", 110, "center", "date")),
          tri="I.ANNEESCO DESC, C.N_CLASSE, E.NOM", peut_desactiver=False, verif=_verif_inscription,
          aide="Un élève est inscrit dans une seule classe par année. Sans inscription, aucun paiement n'est possible."),
    Table("percepteurs", "Percepteurs", "PERCEPTEUR",
          champs=(Champ("N_PERC", "N° de percepteur", cle=True, auto=True),
                  Champ("ID_USER", "Compte utilisateur", type="reference", ref="comptes_percepteurs")),
          from_sql="PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER", alias="P",
          colonnes=(("N°", "P.N_PERC", 60, "center", None), ("Nom complet", "U.NOM_COMPLET", 320, "w", None),
                    ("Identifiant", "U.LOGIN", 160, "w", None)),
          tri="P.N_PERC", etat="U.ACTIF", basculer=_basculer_percepteur, peut_modifier=False,
          aide="Un percepteur est un compte de poste « Percepteur ». Il est enregistré ici automatiquement quand le compte "
               "est créé (Gestionnaire d'accès > Utilisateurs). Désactiver un percepteur bloque son compte."),
    Table("paiements", "Paiements", "PAIEMENT", champs=(Champ("N_RECU", "N° de reçu", cle=True),),
          from_sql="PAIEMENT P LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF",
          alias="P",
          colonnes=(("N° de reçu", "P.N_RECU", 110, "w", None), ("Date", "P.DATE_PAY", 130, "center", "datetime"),
                    ("Matricule", "COALESCE(P.MATRICULE, '(candidat)')", 100, "w", None),
                    ("Élève", "COALESCE(E.NOM || COALESCE(' ' || E.POSTNOM, ''), P.NOM_PAYEUR)", 220, "w", None),
                    ("Frais", "F.DESITF", 170, "w", None), ("Montant", "P.MONT_PAYE", 100, "e", "montant"),
                    ("Devise", "P.CODE_DEVISE", 70, "center", None),
                    ("Statut", "CASE WHEN P.STATUT = 'VALIDE' THEN 'Valide' ELSE 'ANNULÉ' END", 80, "center", None)),
          tri="P.DATE_PAY DESC, P.N_RECU DESC", etat="CASE WHEN P.STATUT = 'VALIDE' THEN 1 ELSE 0 END",
          peut_creer=False, peut_modifier=False, peut_supprimer=False, peut_desactiver=False, peut_annuler=True,
          aide="Les paiements s'enregistrent dans le module « Paiement des frais scolaires ». Un reçu ne se modifie ni ne se "
               "supprime jamais : « Annuler le reçu » le désactive (motif obligatoire) ; il n'est plus compté et ne peut plus "
               "être réimprimé."),
    Table("encaissements", "Encaissements des fonds perçus", "ENCAISSEMENT", champs=(Champ("N_ENC", "N°", cle=True, auto=True),),
          from_sql="ENCAISSEMENT E JOIN PERCEPTEUR P ON P.N_PERC = E.N_PERC JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER",
          alias="E",
          colonnes=(("N°", "E.N_ENC", 60, "center", None), ("Date", "E.DATE_ENC", 100, "center", "date"),
                    ("Percepteur", "U.NOM_COMPLET", 260, "w", None), ("Devise", "E.CODE_DEVISE", 70, "center", None),
                    ("Encaissé", "E.MONT_ENCAISSE", 120, "e", "montant"), ("Versé", "E.MONT_VERSE", 120, "e", "montant"),
                    ("Écart", "E.ECART", 110, "e", "montant")),
          tri="E.DATE_ENC DESC, E.N_ENC DESC", peut_creer=False, peut_modifier=False, peut_desactiver=False,
          aide="Les encaissements s'enregistrent dans le module « Encaissement des fonds perçus ». Ici, l'Administrateur peut "
               "les consulter et les supprimer (par exemple des essais). Rien d'autre n'en dépend."),
)}
TITRE_SQL = {t.sql: t.titre for t in TABLES.values()}
TITRE_SQL.update({"ANNEE_CALENDRIER": "Dates des années scolaires", "SEMESTRE_SCO": "Semestres", "PERIODE_SCO": "Périodes",
                  "COURS": "Cours", "COURS_CLASSE": "Cours des classes", "COMPTE_PROFESSEUR": "Comptes des professeurs", "PRESENCE_ELEVE": "Présence des élèves",
                  "EVALUATION": "Évaluations", "NOTE": "Points des élèves", "CONDUITE": "Conduites", "PRESENCE": "Présences du personnel",
                  "AUTORISATION_ABSENCE": "Permissions et congés du personnel"})


def _identite():
    import identite
    return identite


def table(cle) -> Table:
    try:
        return TABLES[cle]
    except KeyError:
        raise ErreurRef("Table inconnue.") from None


# ================================================================== conversions texte <-> valeur
_DATES = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d")


def _lire_date(texte) -> str:
    for modele in _DATES:
        try:
            d = datetime.strptime(texte, modele).date()
        except ValueError:
            continue
        if not date(1900, 1, 1) <= d <= date(2100, 12, 31):
            break
        return d.isoformat()
    raise ErreurRef("Date invalide. Écrivez-la ainsi : 08/10/2026")


def _lire_tranches_saisies(nom, texte) -> str:
    """« 100;100;100 », « 3x100 », « 100 + 50,50 » -> texte enregistré (centimes séparés par « ; »)."""
    montants = []
    for morceau in re.split(r"[;+]", texte):
        morceau = morceau.strip()
        if not morceau:
            continue
        fois = re.fullmatch(r"(\d{1,2})\s*[xX×*]\s*(.+)", morceau)
        nombre, valeur = (int(fois.group(1)), fois.group(2)) if fois else (1, morceau)
        try:
            centimes = argent.vers_centimes(valeur)
        except ValueError:
            raise ErreurRef(f"{nom} : « {morceau} » n'est pas un montant. Écrivez par exemple 100;100;100 ou 3x100.") from None
        if centimes <= 0 or nombre <= 0:
            raise ErreurRef(f"{nom} : chaque tranche doit être supérieure à zéro.")
        montants += [centimes] * nombre
    if not montants:
        raise ErreurRef(f"{nom} : indiquez au moins une tranche.")
    if len(montants) > donnees.MAX_TRANCHES:
        raise ErreurRef(f"{nom} : {donnees.MAX_TRANCHES} tranches au maximum.")
    return donnees.ecrire_tranches(montants)


def _convertir(conn, champ, brut):
    """Texte saisi -> valeur à enregistrer. Lève ErreurRef (message affichable)."""
    nom = f"« {champ.libelle} »"
    if champ.type == "oui_non":
        return 1 if brut in (True, 1, "1", "oui", "Oui") else 0
    texte = " ".join(str(brut).split()) if brut is not None else ""
    if not texte:
        if champ.defaut == "aujourdhui" and champ.type == "date":
            return date.today().isoformat()
        if champ.obligatoire:
            raise ErreurRef(f"{nom} est obligatoire.")
        return None
    if champ.type == "montant":
        try:
            centimes = argent.vers_centimes(texte)
        except ValueError as erreur:
            raise ErreurRef(f"{nom} : {erreur}") from None
        if centimes <= 0:
            raise ErreurRef(f"{nom} doit être supérieur à zéro.")
        return centimes
    if champ.type == "date":
        return _lire_date(texte)
    if champ.type == "tranches":
        return _lire_tranches_saisies(nom, texte)
    if champ.type == "choix":
        if texte not in {v for v, _ in champ.choix}:
            raise ErreurRef(f"{nom} : valeur non permise.")
        return texte
    if champ.type == "reference":
        r = REFS[champ.ref]
        valeur = texte
        if r.get("entier"):
            try:
                valeur = int(texte)
            except ValueError:
                raise ErreurRef(f"{nom} : choisissez une valeur dans la liste.") from None
        controle = f" AND ({r['filtre']})" if r.get("strict") and r.get("filtre") else ""
        if not conn.execute(f"SELECT 1 FROM {r['table']} WHERE {r['valeur']} = ?{controle}", (valeur,)).fetchone():
            raise ErreurRef(f"{nom} : choisissez une valeur dans la liste.")
        return valeur
    if len(texte) > champ.longueur:
        raise ErreurRef(f"{nom} : {champ.longueur} caractères au maximum.")
    if champ.regex and not re.fullmatch(champ.regex, texte):
        raise ErreurRef(champ.regex_msg or f"{nom} : format invalide.")
    return texte.upper() if champ.majuscules else texte


def afficher_valeur(champ, valeur) -> str:
    """Valeur enregistrée -> texte pour le formulaire."""
    if valeur is None:
        return ""
    if champ.type == "date":
        return datetime.strptime(valeur, "%Y-%m-%d").strftime("%d/%m/%Y")
    if champ.type == "montant":
        return argent.formater(valeur)
    if champ.type == "tranches":
        return " ; ".join(argent.formater(m) for m in donnees.lire_tranches(valeur))
    return str(valeur)


def _formater_cellule(genre, valeur) -> str:
    if valeur is None or valeur == "":
        return ""
    try:
        if genre == "date":
            return datetime.strptime(valeur, "%Y-%m-%d").strftime("%d/%m/%Y")
        if genre == "datetime":
            return lire_iso(valeur).astimezone().strftime("%d/%m/%Y %H:%M")
        if genre == "montant":
            return argent.formater(valeur)
        if genre == "oui_non":
            return "Oui" if valeur else "Non"
        if genre == "tranches":
            return " ; ".join(argent.formater(m) for m in donnees.lire_tranches(valeur))
    except (ValueError, TypeError):
        return str(valeur)
    return str(valeur)


def valeurs_par_defaut(cle) -> dict:
    """Valeurs proposées dans le formulaire d'ajout."""
    resultat = {}
    for c in table(cle).champs:
        if c.defaut == "aujourdhui":
            resultat[c.nom] = date.today().strftime("%d/%m/%Y")
        elif c.defaut is not None:
            resultat[c.nom] = c.defaut
    return resultat


# ================================================================== lecture
def _clause_cle(t):
    return " AND ".join(f"{c.nom} = ?" for c in t.cles)


def lister(conn, session, cle, recherche="") -> dict:
    """{'colonnes': [(titre, largeur, ancrage)], 'lignes': [{'cle': tuple, 'valeurs': [texte], 'actif': bool|None}]}"""
    droits.exiger_admin(conn, session)
    t = table(cle)
    cles = ", ".join(f"{t.alias}.{c.nom}" for c in t.cles)
    cols = ", ".join(c[1] for c in t.colonnes)
    sql = f"SELECT {cles}, {t.etat or 'NULL'}, {cols} FROM {t.from_sql} ORDER BY {t.tri}"
    n = len(t.cles)
    fragments = [f for f in (recherche or "").lower().split() if f]
    import donnees
    lignes = []
    for l in conn.execute(sql):
        valeurs = [_formater_cellule(c[4], l[n + 1 + i]) for i, c in enumerate(t.colonnes)]
        if fragments:
            texte = donnees.sans_accents(" ".join(valeurs))
            if not all(donnees.sans_accents(f) in texte for f in fragments):
                continue
        lignes.append({"cle": tuple(l[:n]), "valeurs": valeurs, "actif": None if l[n] is None else bool(l[n])})
    return {"colonnes": [(c[0], c[2], c[3]) for c in t.colonnes], "lignes": lignes}


def lire(conn, session, cle, cle_pk) -> dict:
    """Valeurs enregistrées d'une ligne (pour pré-remplir le formulaire de modification)."""
    droits.exiger_admin(conn, session)
    t = table(cle)
    ligne = conn.execute(f"SELECT * FROM {t.sql} WHERE {_clause_cle(t)}", tuple(cle_pk)).fetchone()
    if not ligne:
        raise ErreurRef("Cette donnée n'existe plus.")
    return dict(ligne)


def utilisations(conn, cle, cle_pk) -> list:
    """Où cette donnée est-elle utilisée ? [(nom de table, nombre)] - calculé d'après les liens de la base."""
    t = table(cle)
    ligne = conn.execute(f"SELECT * FROM {t.sql} WHERE {_clause_cle(t)}", tuple(cle_pk)).fetchone()
    if not ligne:
        return []
    resultat = []
    for enfant in [l[0] for l in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]:
        if enfant in ("PHOTO_ELEVE", "DOSSIER_ELEVE"):   # la photo et l'état du dossier suivent l'élève (suppression en cascade) : ils ne bloquent pas
            continue
        groupes = {}
        for fk in conn.execute(f'PRAGMA foreign_key_list("{enfant}")'):
            if fk["table"] == t.sql:
                groupes.setdefault(fk["id"], []).append((fk["from"], fk["to"]))
        for colonnes in groupes.values():
            cond = " AND ".join(f'"{de}" = ?' for de, _ in colonnes)
            nombre = conn.execute(f'SELECT COUNT(*) FROM "{enfant}" WHERE {cond}',
                                  [ligne[vers] for _, vers in colonnes]).fetchone()[0]
            if nombre:
                resultat.append((TITRE_SQL.get(enfant, enfant), nombre))
    return resultat


# ================================================================== écriture
def _message_integrite(erreur) -> str:
    texte = str(erreur)
    if "UNIQUE" in texte or "PRIMARY KEY" in texte:
        return "Cette donnée existe déjà (même code, matricule ou combinaison)."
    if "FOREIGN KEY" in texte:
        return "Une des valeurs choisies n'existe pas ou n'est pas permise ici."
    if "CHECK" in texte:
        return "Une des valeurs saisies n'est pas permise."
    if "NOT NULL" in texte:
        return "Un champ obligatoire est vide."
    return f"Enregistrement refusé : {texte}"


def _detail(t, cle_pk, plus=""):
    return f"{t.titre} | {','.join(str(v) for v in cle_pk)}" + (f" | {plus}" if plus else "")


# Tables dont les valeurs sont des données personnelles : le journal n'en garde JAMAIS le contenu (seulement quels
# champs ont changé). Les autres tables (classes, frais, tarifs, devises...) sont tracées avec leurs valeurs.
TABLES_PERSONNELLES = frozenset({"ELEVE"})


def _valeur_txt(valeur) -> str:
    """Valeur d'un champ pour le journal (courte ; jamais de contenu binaire)."""
    if isinstance(valeur, (bytes, bytearray, memoryview)):
        return "(binaire)"
    texte = "—" if valeur in (None, "") else str(valeur)
    return texte if len(texte) <= 60 else texte[:57] + "..."


def _resume_valeurs(valeurs, noms=None) -> str:
    """« nom=MBUYI, sexe=M » : les valeurs saisies, pour que le journal montre CE qui a été ajouté."""
    return ", ".join(f"{n}={_valeur_txt(valeurs[n])}" for n in (noms or valeurs))[:500]


def _resume_changements(ancien, valeurs, modifies) -> str:
    """« nom : MBUYI -> MBUYA ; sexe : M -> F » : ce qui a changé, avant et après."""
    return " ; ".join(f"{n} : {_valeur_txt(ancien[n])} -> {_valeur_txt(valeurs[n])}" for n in modifies)[:500]


def _liste_choisie(brut) -> list:
    """Choix multiple : liste (ou texte « 1,2,3 ») -> liste de textes sans doublon, dans l'ordre."""
    if brut is None:
        return []
    elements = brut.split(",") if isinstance(brut, str) else list(brut)
    vus, resultat = set(), []
    for e in elements:
        e = str(e).strip()
        if e and e not in vus:
            vus.add(e)
            resultat.append(e)
    return resultat


def enregistrer(conn, session, cle, saisie, ancienne_cle=None) -> tuple:
    """Ajoute (ancienne_cle=None) ou modifie une ligne. `saisie` : {nom de champ: texte saisi}.
    Retourne la clé de la ligne (la première, quand un champ à choix multiple crée plusieurs lignes : tout est
    alors enregistré, ou rien)."""
    droits.exiger_admin(conn, session)
    t = table(cle)
    if ancienne_cle is None and not t.peut_creer:
        raise ErreurRef(f"L'ajout n'est pas prévu pour « {t.titre} ».")
    if ancienne_cle is not None and not t.peut_modifier:
        raise ErreurRef(f"La modification n'est pas prévue pour « {t.titre} » (supprimez puis ajoutez, ou désactivez).")
    multiple = next((c for c in t.champs if c.multiple), None) if ancienne_cle is None else None
    valeurs, choix_multiples = {}, []
    for c in t.champs:
        if c.auto or c.genere or (ancienne_cle is not None and c.cle):
            continue
        if c is multiple:
            choix_multiples = _liste_choisie(saisie.get(c.nom))
            if not choix_multiples:
                raise ErreurRef(f"« {c.libelle} » : cochez au moins un choix dans la liste.")
            valeurs[c.nom] = [_convertir(conn, c, v) for v in choix_multiples]
            continue
        valeurs[c.nom] = _convertir(conn, c, saisie.get(c.nom))
    ancien = None
    if ancienne_cle is not None:
        ancien = lire(conn, session, cle, ancienne_cle)
        modifies = [n for n in valeurs if valeurs[n] != ancien[n]]
        if not modifies:
            return tuple(ancienne_cle)
    # une ligne à écrire par choix coché (une seule dans les cas ordinaires)
    lignes = [dict(valeurs, **{multiple.nom: v}) for v in valeurs[multiple.nom]] if multiple else [valeurs]
    if multiple:
        deja = []
        libelles = dict(options(conn, multiple.ref))
        for v in lignes:
            if conn.execute(f"SELECT 1 FROM {t.sql} WHERE " + " AND ".join(f"{c.nom} = ?" for c in t.cles),
                            [v[c.nom] for c in t.cles]).fetchone():
                deja.append(str(libelles.get(v[multiple.nom], v[multiple.nom])))
        if deja:
            raise ErreurRef(f"« {t.titre} » : cette donnée existe déjà pour : {', '.join(deja)}.\n"
                            f"Décochez ces choix, ou modifiez la ligne existante.")
    if t.verif:
        for v in lignes:
            t.verif(conn, v, ancien, ancienne_cle)
    cles_ajoutees = []
    try:
        with conn:
            for v in lignes:
                if ancienne_cle is None:
                    if t.generer:
                        t.generer(conn, v)
                    noms = list(v)
                    curseur = conn.execute(f"INSERT INTO {t.sql} ({', '.join(noms)}) VALUES ({', '.join('?' * len(noms))})",
                                           [v[n] for n in noms])
                    cle_pk = (curseur.lastrowid,) if any(c.auto for c in t.cles) else tuple(v[c.nom] for c in t.cles)
                    action, plus = "REF_AJOUT", ("" if t.sql in TABLES_PERSONNELLES else _resume_valeurs(v))
                else:
                    conn.execute(f"UPDATE {t.sql} SET {', '.join(f'{n} = ?' for n in modifies)} WHERE {_clause_cle(t)}",
                                 [v[n] for n in modifies] + list(ancienne_cle))
                    cle_pk, action = tuple(ancienne_cle), "REF_MODIFICATION"
                    plus = ("champs : " + ", ".join(modifies) if t.sql in TABLES_PERSONNELLES
                            else _resume_changements(ancien, v, modifies))
                if t.apres:
                    t.apres(conn, v, cle_pk)
                journaliser(conn, session.id_user, session.login, action, _detail(t, cle_pk, plus))
                cles_ajoutees.append(cle_pk)
    except sqlite3.IntegrityError as erreur:
        raise ErreurRef(_message_integrite(erreur)) from erreur
    return cles_ajoutees[0]


def supprimer(conn, session, cle, cle_pk):
    """Supprime une ligne qui n'est utilisée nulle part. Sinon : message clair (et conseil de désactiver)."""
    droits.exiger_admin(conn, session)
    t = table(cle)
    if not t.peut_supprimer:
        raise ErreurRef(f"La suppression n'est pas permise pour « {t.titre} ».")
    avant = lire(conn, session, cle, cle_pk)              # vérifie qu'elle existe
    if t.verif_suppression:
        t.verif_suppression(conn, cle_pk)
    usages = utilisations(conn, cle, cle_pk)
    if usages:
        liste = ", ".join(f"{titre} ({n})" for titre, n in usages)
        raise ErreurUtilisee(f"Suppression impossible : cette donnée est utilisée par {liste}."
                        + ("\nDésactivez-la plutôt : elle ne sera plus proposée, mais l'historique reste intact."
                           if t.peut_desactiver else ""))
    try:
        with conn:
            conn.execute(f"DELETE FROM {t.sql} WHERE {_clause_cle(t)}", tuple(cle_pk))
            journaliser(conn, session.id_user, session.login, "REF_SUPPRESSION",
                        _detail(t, cle_pk, "" if t.sql in TABLES_PERSONNELLES else _resume_valeurs(avant)))
    except sqlite3.IntegrityError as erreur:
        raise ErreurRef(_message_integrite(erreur)) from erreur


# ------------------------------------------------------------------ suppression avec les données liées
def _enfants_directs(conn, parent, ligne) -> list:
    """[(table enfant, rowid)] des lignes qui référencent directement `ligne` (une ligne de `parent`)."""
    resultat = []
    for enfant in [l[0] for l in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]:
        groupes = {}
        for fk in conn.execute(f'PRAGMA foreign_key_list("{enfant}")'):
            if fk["table"] == parent:
                groupes.setdefault(fk["id"], []).append((fk["from"], fk["to"]))
        for colonnes in groupes.values():
            cond = " AND ".join(f'"{de}" = ?' for de, _ in colonnes)
            for l in conn.execute(f'SELECT rowid FROM "{enfant}" WHERE {cond}', [ligne[vers] for _, vers in colonnes]):
                resultat.append((enfant, l[0]))
    return resultat


def _plan_suppression(conn, table_sql, rowid, vus, ordre):
    """Remplit `ordre` : les lignes à supprimer, les plus dépendantes d'abord (puis la ligne elle-même)."""
    if (table_sql, rowid) in vus:
        return
    vus.add((table_sql, rowid))
    ligne = conn.execute(f'SELECT * FROM "{table_sql}" WHERE rowid = ?', (rowid,)).fetchone()
    if ligne is None:
        return
    for enfant, r in _enfants_directs(conn, table_sql, ligne):
        _plan_suppression(conn, enfant, r, vus, ordre)
    ordre.append((table_sql, rowid))


def apercu_suppression(conn, session, cle, cle_pk) -> dict:
    """Ce qu'entraînerait la suppression de cette donnée avec tout ce qui en dépend :
    {'liees': [(nom de table, nombre)], 'recus': nombre de reçus concernés, 'possible': bool, 'ordre': [...]}.
    Elle est IMPOSSIBLE dès qu'un reçu de paiement en dépend : un reçu ne se supprime jamais (même annulé)."""
    droits.exiger_admin(conn, session)
    t = table(cle)
    ligne = conn.execute(f"SELECT rowid FROM {t.sql} WHERE {_clause_cle(t)}", tuple(cle_pk)).fetchone()
    if not ligne:
        raise ErreurRef("Cette donnée n'existe plus.")
    ordre = []
    _plan_suppression(conn, t.sql, ligne[0], set(), ordre)
    comptes = {}
    for nom, _ in ordre[:-1]:                                 # le dernier élément est la donnée elle-même
        comptes[nom] = comptes.get(nom, 0) + 1
    recus = comptes.get("PAIEMENT", 0)
    return {"liees": sorted((TITRE_SQL.get(n, n), c) for n, c in comptes.items()), "recus": recus,
            "possible": recus == 0, "ordre": ordre}


def supprimer_avec_liees(conn, session, cle, cle_pk) -> dict:
    """Supprime la donnée ET toutes les données qui en dépendent (tarifs, inscriptions, encaissements...).
    Refusé si un reçu de paiement en dépend. Une seule opération : tout est supprimé ou rien."""
    droits.exiger_admin(conn, session)
    t = table(cle)
    if not t.peut_supprimer:
        raise ErreurRef(f"La suppression n'est pas permise pour « {t.titre} ».")
    apercu = apercu_suppression(conn, session, cle, cle_pk)
    if not apercu["possible"]:
        raise ErreurRef(
            f"Suppression impossible : {apercu['recus']} reçu(s) de paiement dépendent de cette donnée, et un reçu ne se "
            "supprime jamais (même annulé), car il appartient à la comptabilité.\n"
            + ("Désactivez plutôt cette donnée : elle ne sera plus proposée, mais l'historique reste intact.\n"
               if t.peut_desactiver else "")
            + "Pour repartir d'une application vide (par exemple après des essais), utilisez Travaux techniques > "
              "Réinitialisation.")
    try:
        with conn:
            for nom, rowid in apercu["ordre"]:
                conn.execute(f'DELETE FROM "{nom}" WHERE rowid = ?', (rowid,))
            detail = _detail(t, cle_pk, "avec : " + ", ".join(f"{n} ({c})" for n, c in apercu["liees"])
                             if apercu["liees"] else "")
            journaliser(conn, session.id_user, session.login, "REF_SUPPRESSION_AVEC_LIEES", detail)
    except sqlite3.IntegrityError as erreur:
        raise ErreurRef(_message_integrite(erreur)) from erreur
    return apercu


def changer_etat(conn, session, cle, cle_pk, actif):
    """Désactive (actif=False) ou réactive une donnée : elle n'est plus proposée dans les listes,
    mais tout ce qui s'y rapporte est conservé."""
    droits.exiger_admin(conn, session)
    t = table(cle)
    if not t.peut_desactiver:
        raise ErreurRef(f"La désactivation n'existe pas pour « {t.titre} ».")
    ligne = lire(conn, session, cle, cle_pk)
    if cle == "annees" and not actif and ligne["EN_COURS"]:
        raise ErreurRef("Désignez d'abord une autre année « en cours » avant de désactiver celle-ci.")
    with conn:
        if t.basculer:
            t.basculer(conn, cle_pk, actif)
        else:
            conn.execute(f"UPDATE {t.sql} SET {t.actif_col} = ? WHERE {_clause_cle(t)}", (int(actif), *cle_pk))
        journaliser(conn, session.id_user, session.login, "REF_REACTIVATION" if actif else "REF_DESACTIVATION",
                    _detail(t, cle_pk))


def annuler_paiement(conn, session, n_recu, motif):
    """Annule un reçu (définitif) : il n'est plus compté dans la situation de l'élève ni dans les rapports,
    et ne peut plus être réimprimé. Le reçu lui-même n'est ni modifié ni supprimé."""
    droits.exiger_admin(conn, session)
    motif = " ".join((motif or "").split())
    if len(motif) < 5:
        raise ErreurRef("Indiquez le motif de l'annulation (au moins 5 caractères).")
    ligne = conn.execute("SELECT STATUT FROM PAIEMENT WHERE N_RECU = ?", (n_recu,)).fetchone()
    if not ligne:
        raise ErreurRef("Reçu introuvable.")
    if ligne["STATUT"] == "ANNULE":
        raise ErreurRef("Ce reçu est déjà annulé.")
    with conn:
        conn.execute("UPDATE PAIEMENT SET STATUT = 'ANNULE', MOTIF_ANNULATION = ?, DATE_ANNULATION = ?, ANNULE_PAR = ? "
                     "WHERE N_RECU = ? AND STATUT = 'VALIDE'", (motif, iso(maintenant()), session.login, n_recu))
        journaliser(conn, session.id_user, session.login, "PAIEMENT_ANNULE", f"{n_recu} | {motif}")
