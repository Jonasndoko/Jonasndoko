"""Contrôle et audit financier (module « Traçabilité et audit », sans interface graphique : testable seul).

Ce module ne modifie rien : il LIT les tables financières (paiements, encaissements) et le journal de l'application, et
les compare. Il permet aux responsables autorisés (Administrateur, ou compte à qui l'Administrateur a accordé la Lecture
sur « Traçabilité et audit ») de vérifier :

1. LES PAIEMENTS ENREGISTRÉS ET LEURS REÇUS : chaque reçu a-t-il sa trace d'enregistrement au journal, par le bon
   compte, avec le même montant, le même élève, le même frais et une date cohérente ? Y a-t-il un trou dans la
   numérotation, un trop-perçu, un duplicata imprimé de nombreuses fois ?
2. LES MONTANTS ENCAISSÉS ET REMIS : pour chaque journée, chaque percepteur et chaque devise, le total des reçus valides,
   le montant déclaré encaissé, le montant versé, l'écart de remise (manquant / excédent) et la différence entre les
   reçus et l'encaissement déclaré.
3. LES ANNULATIONS ET CORRECTIONS : reçus annulés (qui, quand, pourquoi, après combien de temps, alors que
   l'encaissement du jour était déjà enregistré ?), encaissements modifiés ou supprimés, tarifs et frais modifiés.
4. LES DIFFÉRENCES ENTRE LES OPÉRATIONS ENREGISTRÉES ET LES RAPPORTS JOURNALIERS : le total des opérations tracées au
   journal est comparé au rapport journalier recalculé, et chaque rapport imprimé (rapport de caisse, rapport global) est
   comparé aux reçus qui existaient au moment de son impression.

Une anomalie n'est PAS une preuve de fraude : elle indique où regarder. Trois degrés de gravité : ÉLEVÉE (les données ne
concordent pas : à expliquer), MOYENNE (à vérifier), FAIBLE (à connaître).

Le contrôle ignore ce qui précède la dernière « Réinitialisation de l'application » (les tables financières ont alors
été vidées : les anciennes traces n'ont plus de ligne correspondante).
"""
import re
from datetime import date, datetime, timedelta

import argent
import donnees
from audit import ErreurAudit, _local, _montant, _noms_utilisateurs, _qui, _verifier_periode, etat_journal, exiger
from database import journaliser

GRAVITES = ("ÉLEVÉE", "MOYENNE", "FAIBLE")
_RANG = {g: i for i, g in enumerate(GRAVITES)}

CAT_RECUS = "Reçus et paiements"
CAT_CAISSE = "Encaissements et remises"
CAT_ANNUL = "Annulations et corrections"
CAT_RAPPORTS = "Rapports journaliers"
CAT_JOURNAL = "Journal"
CATEGORIES_ANOMALIES = (CAT_RECUS, CAT_CAISSE, CAT_ANNUL, CAT_RAPPORTS, CAT_JOURNAL)

TOLERANCE_DATE_SEC = 300          # écart toléré entre la date du reçu et celle de sa trace au journal
SEUIL_DUPLICATA = 3               # nombre de duplicata d'un même reçu à partir duquel on le signale
MIN_ANNULATIONS = 3               # un percepteur dont au moins 3 reçus sont annulés...
SEUIL_TAUX_ANNULATION = 0.20      # ... soit 20 % de ses reçus ou plus, est signalé

# Tables de référence dont la modification a un effet sur l'argent (titres de referentiels.py)
TABLES_FINANCIERES = ("Tarifs", "Types de frais", "Tranches de paiement", "Devises")
TITRE_ENCAISSEMENTS = "Encaissements des fonds perçus"

_RE_DETAIL_ENC = re.compile(r"^N°(\d+) \| (.*?) \| (\d{4}-\d{2}-\d{2}) \| encaissé (.+?) (\S+) \| versé (.+?) \| écart (.+)$")
_RE_N_ENC = re.compile(r"N°(\d+) \|")
_RE_RAPPORT = re.compile(r"^(\d{4}-\d{2}-\d{2}) \| (\d+) reçu\(s\)(?: \| (.*))?$")
_RE_PORTEE = re.compile(r"^(Tous les percepteurs|percepteur N°(\d+)) \| total (.*)$")
_RE_GLOBAL = re.compile(r"^(\d+) encaissement\(s\)(?: \| total (.*))?$")
_RE_MONTANT_REF = re.compile(r"MONTANT : (\d+) -> (\d+)")


# ================================================================== petits outils
def _centimes(texte):
    """'1 250,50' -> 125050 ; None si ce n'est pas un montant."""
    try:
        return argent.vers_centimes(texte)
    except ValueError:
        return None


def _ecart_centimes(texte):
    """'-5,00' -> -500 ; None si illisible (l'écart peut être négatif : excédent)."""
    texte = (texte or "").strip()
    if texte.startswith("-"):
        valeur = _centimes(texte[1:])
        return None if valeur is None else -valeur
    return _centimes(texte)


def _montant_devise(texte):
    """'45,00 USD' -> (4500, 'USD') ; None si illisible."""
    morceaux = (texte or "").strip().rsplit(" ", 1)
    if len(morceaux) != 2:
        return None
    valeur = _centimes(morceaux[0])
    return None if valeur is None else (valeur, morceaux[1])


def _lire_detail_encaissement(detail):
    """Détail d'un encaissement écrit par encaissements._detail -> dict, ou None."""
    m = _RE_DETAIL_ENC.match((detail or "").strip())
    if not m:
        return None
    return {"n_enc": int(m.group(1)), "percepteur": m.group(2), "jour": m.group(3), "devise": m.group(5),
            "encaisse": _centimes(m.group(4)), "verse": _centimes(m.group(6)), "ecart": _ecart_centimes(m.group(7))}


def _texte_encaissement(e) -> str:
    if not e:
        return "—"
    f = lambda v: "?" if v is None else argent.formater(v)
    return f"encaissé {f(e['encaisse'])} {e['devise']}, versé {f(e['verse'])}, écart {f(e['ecart'])}"


def _duree_txt(delta: timedelta) -> str:
    secondes = int(delta.total_seconds())
    if secondes < 0:
        return "—"
    jours, reste = divmod(secondes, 86400)
    heures, reste = divmod(reste, 3600)
    minutes = reste // 60
    if jours:
        return f"{jours} j {heures} h"
    if heures:
        return f"{heures} h {minutes:02d} min"
    return f"{minutes} min"


def _horodatage(quand) -> float:
    """Pour trier les anomalies : les plus récentes d'abord (sans date : en dernier)."""
    if isinstance(quand, datetime):
        return quand.timestamp()
    if isinstance(quand, date):
        return datetime.combine(quand, datetime.min.time()).timestamp()
    return 0.0


def _totaux_txt(par_devise: dict) -> str:
    return argent.resume_totaux(list(par_devise.items()))


# ================================================================== lecture des données (une seule fois par contrôle)
class _Contexte:
    """Tout ce qu'il faut pour comparer : le journal (depuis la dernière réinitialisation), les reçus, les encaissements."""

    ACTIONS_SUIVIES = ("PAIEMENT_ENREGISTRE", "PAIEMENT_ANNULE", "RECU_IMPRIME", "DUPLICATA_IMPRIME",
                       "ENCAISSEMENT_ENREGISTRE", "ENCAISSEMENT_MODIFIE", "ENCAISSEMENT_SUPPRIME",
                       "RAPPORT_CAISSE_IMPRIME", "RAPPORT_GLOBAL_IMPRIME",
                       "REF_MODIFICATION", "REF_SUPPRESSION", "REF_SUPPRESSION_AVEC_LIEES")

    def __init__(self, conn):
        self.conn = conn
        self.noms = _noms_utilisateurs(conn)
        self.percepteurs, self.perc_de_login = {}, {}
        for l in conn.execute("SELECT P.N_PERC, U.LOGIN, U.NOM_COMPLET FROM PERCEPTEUR P "
                              "JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER"):
            self.percepteurs[l["N_PERC"]] = {"nom": l["NOM_COMPLET"], "login": l["LOGIN"]}
            self.perc_de_login[l["LOGIN"].lower()] = l["N_PERC"]
        self.reset = conn.execute("SELECT COALESCE(MAX(ID_LOG), 0) FROM JOURNAL "
                                  "WHERE ACTION = 'APPLICATION_REINITIALISEE'").fetchone()[0]
        self._lire_purges()
        self._lire_journal()
        self._lire_tables()

    def nom_perc(self, n_perc) -> str:
        p = self.percepteurs.get(n_perc)
        return p["nom"] if p else f"percepteur {n_perc}"

    # --- données d'essai retirées : leurs traces restent au journal (ajout seulement) mais ne comptent plus
    def _lire_purges(self):
        """[(id du journal, {n° de reçu}, {n° d'encaissement})] des suppressions de données d'essai depuis la dernière
        réinitialisation. Une trace n'est ignorée que si elle est ANTÉRIEURE à la suppression et vise un numéro retiré :
        un numéro de reçu réutilisé ensuite (la numérotation repart de 0001) compte normalement."""
        self.purges, self.nums_purges = [], set()
        for l in self.conn.execute("SELECT ID_LOG, DETAIL FROM JOURNAL WHERE ACTION = 'DONNEES_ESSAI_SUPPRIMEES' "
                                   "AND ID_LOG > ? ORDER BY ID_LOG", (self.reset,)):
            d = l["DETAIL"] or ""
            recus = re.search(r"RECUS=([^ |]*)", d)
            nums = re.search(r"NUMS=([^ |]*)", d)
            enc = re.search(r"ENC=([^ |]*)", d)
            self.purges.append((l["ID_LOG"], set(filter(None, recus.group(1).split(","))) if recus else set(),
                                {int(x) for x in enc.group(1).split(",") if x.isdigit()} if enc else set()))
            if nums:
                self.nums_purges |= {int(x) for x in nums.group(1).split(",") if x.isdigit()}

    def _purgee(self, id_log, n_recu=None, n_enc=None) -> bool:
        return any(id_log < p and ((n_recu is not None and n_recu in recus) or (n_enc is not None and n_enc in encs))
                   for p, recus, encs in self.purges)

    # --- journal
    def _lire_journal(self):
        self.enreg, self.annul = {}, {}               # {n° de reçu: [évènements]} / {n° de reçu: évènement}
        self.imprimes, self.duplicatas = {}, {}       # {n° de reçu: nombre}
        self.enc_events = {}                          # {n° d'encaissement: [évènements]}
        self.rapports, self.refs = [], []
        self.enc_supprimes = []                       # [(id du journal, date AAAA-MM-JJ de l'encaissement supprimé)]
        marques = ",".join("?" * len(self.ACTIONS_SUIVIES))
        for l in self.conn.execute(
                f"SELECT ID_LOG, DATE_HEURE, LOGIN, ACTION, DETAIL FROM JOURNAL WHERE ID_LOG > ? AND ACTION IN ({marques}) "
                "ORDER BY ID_LOG", (self.reset, *self.ACTIONS_SUIVIES)):
            ev = {"id": l["ID_LOG"], "date": l["DATE_HEURE"], "login": l["LOGIN"] or "", "action": l["ACTION"],
                  "detail": l["DETAIL"] or ""}
            action, detail = ev["action"], ev["detail"]
            if self.purges:
                m_enc = _RE_N_ENC.search(detail)
                if self._purgee(ev["id"], detail.split(" | ")[0] if action in (
                        "PAIEMENT_ENREGISTRE", "PAIEMENT_ANNULE", "RECU_IMPRIME", "DUPLICATA_IMPRIME") else None,
                        int(m_enc.group(1)) if m_enc and action.startswith("ENCAISSEMENT_") else None):
                    continue
            if action == "PAIEMENT_ENREGISTRE":
                p = detail.split(" | ")
                ev.update(n_recu=p[0], matricule=p[1] if len(p) > 1 else "", codtf=p[2] if len(p) > 2 else "",
                          montant=_montant_devise(p[3]) if len(p) > 3 else None,
                          montant_txt=p[3] if len(p) > 3 else "")
                self.enreg.setdefault(p[0], []).append(ev)
            elif action == "PAIEMENT_ANNULE":
                p = detail.split(" | ", 1)
                ev.update(n_recu=p[0], motif=p[1] if len(p) > 1 else "")
                self.annul[p[0]] = ev
            elif action in ("RECU_IMPRIME", "DUPLICATA_IMPRIME"):
                cible = self.imprimes if action == "RECU_IMPRIME" else self.duplicatas
                cible[detail] = cible.get(detail, 0) + 1
            elif action in ("ENCAISSEMENT_ENREGISTRE", "ENCAISSEMENT_MODIFIE", "ENCAISSEMENT_SUPPRIME"):
                m = _RE_N_ENC.search(detail)
                if m:
                    self.enc_events.setdefault(int(m.group(1)), []).append(ev)
                if action == "ENCAISSEMENT_SUPPRIME":
                    e = _lire_detail_encaissement(detail)
                    if e:
                        self.enc_supprimes.append((ev["id"], e["jour"]))
            elif action in ("RAPPORT_CAISSE_IMPRIME", "RAPPORT_GLOBAL_IMPRIME"):
                self.rapports.append(ev)
            else:                                     # REF_*
                titre = detail.split(" | ", 1)[0]
                if titre in TABLES_FINANCIERES or titre == TITRE_ENCAISSEMENTS:
                    self.refs.append(ev)
                    if titre == TITRE_ENCAISSEMENTS and action != "REF_MODIFICATION":
                        m = re.search(r"DATE_ENC=(\d{4}-\d{2}-\d{2})", detail)
                        if m:
                            self.enc_supprimes.append((ev["id"], m.group(1)))

    # --- tables
    def _lire_tables(self):
        self.recus = []
        for l in self.conn.execute(
                "SELECT P.*, E.NOM, E.POSTNOM, E.PRENOM, F.DESITF FROM PAIEMENT P "
                "LEFT JOIN ELEVE E ON E.MATRICULE = P.MATRICULE LEFT JOIN TYPE_FRAIS F ON F.CODTF = P.CODTF "
                "ORDER BY P.NUM_SEQ"):
            r = dict(l)
            if r["MATRICULE"] is None:               # reçu d'inscription d'un candidat : identifié comme dans le journal
                r["MATRICULE"] = f"CANDIDAT {r['NOM_PAYEUR']}"
            r["quand"] = _local(l["DATE_PAY"])
            r["jour"] = r["quand"].date()
            r["eleve"] = (donnees.nom_complet(l) if l["NOM"] else
                          (f"{l['NOM_PAYEUR']} (candidat)" if l["MATRICULE"] is None else "(élève supprimé)"))
            r["frais"] = l["DESITF"] or l["CODTF"]
            self.recus.append(r)
        self.recus_par_n = {r["N_RECU"]: r for r in self.recus}
        self.encaissements = [dict(l) for l in self.conn.execute("SELECT * FROM ENCAISSEMENT ORDER BY N_ENC")]


# ================================================================== le contrôle
class _Controle:
    def __init__(self, ctx, du, au, n_perc, devise):
        self.c, self.du, self.au, self.n_perc, self.devise = ctx, du, au, n_perc, devise
        self.anomalies = []
        self.aujourdhui = date.today()

    # --- visibilité (filtres)
    def _jour_ok(self, jour) -> bool:
        return (self.du is None or jour >= self.du) and (self.au is None or jour <= self.au)

    def visible(self, jour, n_perc=None, devise=None) -> bool:
        if jour is not None and not self._jour_ok(jour):
            return False
        if self.n_perc is not None and n_perc is not None and n_perc != self.n_perc:
            return False
        if self.devise and devise and devise != self.devise:
            return False
        return True

    def signaler(self, code, gravite, categorie, reference, message, quand=None, visible=True):
        """Enregistre une anomalie (si elle est dans le périmètre demandé) et la retourne (None sinon)."""
        if not visible:
            return None
        jour = quand.date() if isinstance(quand, datetime) else quand
        a = {"code": code, "gravite": gravite, "categorie": categorie, "reference": reference, "message": message,
             "quand": quand, "date_txt": (quand.strftime("%d/%m/%Y") if isinstance(quand, date) else "") if quand else "",
             "jour": jour}
        self.anomalies.append(a)
        return a

    @staticmethod
    def _statut(anomalies) -> str:
        anomalies = [a for a in anomalies if a]
        if not anomalies:
            return "Conforme"
        return "Anomalie" if any(a["gravite"] == "ÉLEVÉE" for a in anomalies) else "À vérifier"

    # ------------------------------------------------------------ 1) paiements et reçus
    def verifier_recus(self) -> list:
        c, noms = self.c, self.c.noms
        lignes = []
        for r in c.recus:
            n_recu, perc = r["N_RECU"], c.percepteurs.get(r["N_PERC"], {"login": "", "nom": ""})
            ok_vue = self.visible(r["jour"], r["N_PERC"], r["CODE_DEVISE"])
            ref = n_recu
            mes = []                                              # anomalies de ce reçu
            sig = lambda *a, **k: mes.append(self.signaler(*a, visible=ok_vue, **k))
            traces = c.enreg.get(n_recu, [])
            t = traces[0] if traces else None
            if not t:
                sig("RECU_SANS_TRACE", "ÉLEVÉE", CAT_RECUS, ref,
                    f"Reçu {n_recu} : aucune trace de son enregistrement dans le journal.", r["quand"])
            else:
                if len(traces) > 1:
                    sig("RECU_TRACE_DOUBLE", "ÉLEVÉE", CAT_RECUS, ref,
                        f"Reçu {n_recu} : enregistré {len(traces)} fois au journal.", r["quand"])
                if t["login"].lower() != perc["login"].lower():
                    sig("RECU_ENREGISTRE_PAR_AUTRE", "ÉLEVÉE", CAT_RECUS, ref,
                        f"Reçu {n_recu} : le journal indique {t['login'] or '—'} alors que le reçu porte le percepteur "
                        f"{perc['login'] or '—'}.", r["quand"])
                diffs = []
                if t["matricule"].lower() != r["MATRICULE"].lower():
                    diffs.append(f"élève (journal {t['matricule']} / reçu {r['MATRICULE']})")
                if t["codtf"] != r["CODTF"]:
                    diffs.append(f"frais (journal {t['codtf']} / reçu {r['CODTF']})")
                if t["montant"] != (r["MONT_PAYE"], r["CODE_DEVISE"]):
                    diffs.append(f"montant (journal {t['montant_txt'] or '—'} / reçu {_montant(r['MONT_PAYE'], r['CODE_DEVISE'])})")
                if diffs:
                    sig("RECU_DIFFERENT_DU_JOURNAL", "ÉLEVÉE", CAT_RECUS, ref,
                        f"Reçu {n_recu} : ne correspond pas à sa trace au journal : " + " ; ".join(diffs) + ".", r["quand"])
                ecart_sec = abs((_local(t["date"]) - r["quand"]).total_seconds())
                if ecart_sec > TOLERANCE_DATE_SEC:
                    sig("RECU_DATE_INCOHERENTE", "MOYENNE", CAT_RECUS, ref,
                        f"Reçu {n_recu} : daté du {r['quand'].strftime('%d/%m/%Y %H:%M')} mais enregistré au journal le "
                        f"{_local(t['date']).strftime('%d/%m/%Y %H:%M')}.", r["quand"])
            if r["quand"] > datetime.now() + timedelta(seconds=TOLERANCE_DATE_SEC):
                sig("RECU_DATE_FUTURE", "MOYENNE", CAT_RECUS, ref,
                    f"Reçu {n_recu} : daté du futur ({r['quand'].strftime('%d/%m/%Y %H:%M')}).", r["quand"])
            if r["STATUT"] == "ANNULE":
                a = c.annul.get(n_recu)
                if not a:
                    sig("RECU_ANNULE_SANS_TRACE", "ÉLEVÉE", CAT_ANNUL, ref,
                        f"Reçu {n_recu} : annulé, mais aucune trace de l'annulation dans le journal.", r["quand"])
                elif (r["ANNULE_PAR"] or "").lower() != a["login"].lower():
                    sig("RECU_ANNULATION_INCOHERENTE", "ÉLEVÉE", CAT_ANNUL, ref,
                        f"Reçu {n_recu} : annulé par {r['ANNULE_PAR'] or '—'} selon le reçu, par {a['login'] or '—'} "
                        f"selon le journal.", r["quand"])
                if not (r["MOTIF_ANNULATION"] and r["DATE_ANNULATION"] and r["ANNULE_PAR"]):
                    sig("RECU_ANNULATION_INCOMPLETE", "ÉLEVÉE", CAT_ANNUL, ref,
                        f"Reçu {n_recu} : annulé sans motif, sans date ou sans auteur.", r["quand"])
            nb_dup = c.duplicatas.get(n_recu, 0)
            if nb_dup >= SEUIL_DUPLICATA:
                sig("RECU_DUPLICATAS_MULTIPLES", "FAIBLE", CAT_RECUS, ref,
                    f"Reçu {n_recu} : {nb_dup} duplicata imprimés.", r["quand"])
            if ok_vue:
                lignes.append({
                    "n_recu": n_recu, "quand": r["quand"], "date_txt": r["quand"].strftime("%d/%m/%Y  %H:%M"),
                    "matricule": r["MATRICULE"], "eleve": r["eleve"], "frais": r["frais"], "annee": r["ANNEESCO"],
                    "montant": r["MONT_PAYE"], "montant_txt": argent.formater(r["MONT_PAYE"]), "devise": r["CODE_DEVISE"],
                    "n_perc": r["N_PERC"], "percepteur": perc["nom"],
                    "enregistre_par": _qui(t["login"], noms) if t else "— aucune trace —",
                    "statut": "Valide" if r["STATUT"] == "VALIDE" else "Annulé",
                    "recus_imprimes": c.imprimes.get(n_recu, 0), "duplicatas": nb_dup,
                    "verification": self._statut(mes),
                    "remarques": " | ".join(a["message"] for a in mes if a)})
        self._trop_percus()
        self._traces_sans_recu()
        self._numerotation()
        lignes.sort(key=lambda x: (x["quand"], x["n_recu"]), reverse=True)
        return lignes

    def _trop_percus(self):
        """Le total des reçus valides d'un élève pour un frais ne peut pas dépasser ce qui est dû."""
        groupes = {}
        for r in self.c.recus:
            if r["STATUT"] == "VALIDE":
                groupes.setdefault((r["ANNEESCO"], r["MATRICULE"], r["CODTF"], r["N_CLASSE"]), []).append(r)
        for (annee, matricule, codtf, n_classe), recus in groupes.items():
            du = donnees.montant_du(self.c.conn, codtf, n_classe, annee)
            total = sum(r["MONT_PAYE"] for r in recus)
            if du and total > du[0]:
                dernier = max(recus, key=lambda r: r["quand"])
                self.signaler(
                    "TROP_PERCU", "ÉLEVÉE", CAT_RECUS, dernier["N_RECU"],
                    f"Élève {matricule}, frais {codtf} ({annee}) : {argent.formater(total)} {du[1]} payés pour "
                    f"{argent.formater(du[0])} dus (reçus {', '.join(r['N_RECU'] for r in recus)}).", dernier["quand"],
                    visible=self.visible(dernier["jour"], dernier["N_PERC"], dernier["CODE_DEVISE"]))

    def _traces_sans_recu(self):
        """Un reçu tracé au journal mais absent de la table : supprimé en dehors de l'application ?"""
        for n_recu, traces in self.c.enreg.items():
            if n_recu in self.c.recus_par_n:
                continue
            t = traces[0]
            quand = _local(t["date"])
            n_perc = self.c.perc_de_login.get(t["login"].lower())
            devise = t["montant"][1] if t["montant"] else None
            self.signaler("RECU_ABSENT_DE_LA_TABLE", "ÉLEVÉE", CAT_RECUS, n_recu,
                          f"Reçu {n_recu} : enregistré au journal le {quand.strftime('%d/%m/%Y %H:%M')} par "
                          f"{t['login'] or '—'} ({t['montant_txt'] or '—'}), mais absent de la table des paiements "
                          f"(supprimé en dehors de l'application ?).", quand,
                          visible=self.visible(quand.date(), n_perc, devise))

    def _numerotation(self):
        """Trous dans la numérotation continue des reçus (0001, 0002... ; les anciens numéros 2026-000001 sont ignorés)."""
        suite = sorted(r["NUM_SEQ"] for r in self.c.recus if r["N_RECU"].isdigit())
        if self.devise or self.n_perc is not None or not suite:
            return                       # le contrôle d'une suite n'a de sens que sur l'ensemble des reçus
        manquants = sorted(set(range(suite[0], suite[-1] + 1)) - set(suite) - self.c.nums_purges)
        if manquants:
            self.signaler("NUMEROS_MANQUANTS", "MOYENNE", CAT_RECUS, "",
                          "Numéros de reçu manquants dans la suite : " + ", ".join(f"{n:04d}" for n in manquants[:15])
                          + ("…" if len(manquants) > 15 else "") + ".")

    # ------------------------------------------------------------ 2) encaissé, remis et rapports journaliers
    def rapprochement(self) -> list:
        """Une ligne par journée, percepteur et devise : opérations tracées au journal / rapport journalier / encaissement."""
        c = self.c
        groupes = {}

        def groupe(cle):
            return groupes.setdefault(cle, {"recus_nb": 0, "recus_total": 0, "annules_nb": 0, "annules_total": 0,
                                            "journal_nb": 0, "journal_total": 0, "enc": []})
        for r in c.recus:
            g = groupe((r["jour"], r["N_PERC"], r["CODE_DEVISE"]))
            if r["STATUT"] == "VALIDE":
                g["recus_nb"] += 1
                g["recus_total"] += r["MONT_PAYE"]
            else:
                g["annules_nb"] += 1
                g["annules_total"] += r["MONT_PAYE"]
            traces = c.enreg.get(r["N_RECU"])
            if traces and traces[0]["montant"]:
                g["journal_nb"] += 1
                g["journal_total"] += traces[0]["montant"][0]
        for n_recu, traces in c.enreg.items():                         # reçus tracés mais absents de la table
            if n_recu not in c.recus_par_n and traces[0]["montant"]:
                quand = _local(traces[0]["date"])
                g = groupe((quand.date(), c.perc_de_login.get(traces[0]["login"].lower()), traces[0]["montant"][1]))
                g["journal_nb"] += 1
                g["journal_total"] += traces[0]["montant"][0]
        for e in c.encaissements:
            groupe((date.fromisoformat(e["DATE_ENC"]), e["N_PERC"], e["CODE_DEVISE"]))["enc"].append(e)

        lignes = []
        for (jour, n_perc, devise), g in sorted(groupes.items(), key=lambda x: (x[0][0], str(x[0][1]), x[0][2]), reverse=True):
            if not self.visible(jour, n_perc, devise):
                continue
            nom = c.nom_perc(n_perc) if n_perc is not None else "(inconnu)"
            ref = f"{jour.strftime('%d/%m/%Y')} - {nom} - {devise}"
            mes = []
            sig = lambda *a, **k: mes.append(self.signaler(*a, **k))
            enc = g["enc"]
            encaisse = sum(e["MONT_ENCAISSE"] for e in enc)
            verse = sum(e["MONT_VERSE"] for e in enc)
            ecart_remise = sum(e["ECART"] for e in enc)
            diff_recus = (encaisse - g["recus_total"]) if enc else None
            diff_journal = g["journal_total"] - g["annules_total"] - g["recus_total"]
            nb_diff = g["journal_nb"] - g["annules_nb"] - g["recus_nb"]
            if diff_journal or nb_diff:
                sig("CAISSE_JOURNAL_DIFFERENT", "ÉLEVÉE", CAT_RAPPORTS, ref,
                    f"{ref} : les opérations enregistrées au journal ({g['journal_nb']} reçu(s), "
                    f"{argent.formater(g['journal_total'])}) moins les annulations ({g['annules_nb']}, "
                    f"{argent.formater(g['annules_total'])}) ne donnent pas le rapport journalier ({g['recus_nb']} "
                    f"reçu(s), {argent.formater(g['recus_total'])}) : différence {argent.formater(diff_journal)} {devise}.", jour)
            if not enc and g["recus_nb"]:
                sig("RECUS_SANS_ENCAISSEMENT", "MOYENNE" if jour < self.aujourdhui else "FAIBLE", CAT_CAISSE, ref,
                    f"{ref} : {g['recus_nb']} reçu(s) valide(s) pour {argent.formater(g['recus_total'])} {devise}, "
                    f"mais aucun encaissement n'est enregistré"
                    + (" (journée en cours)." if jour >= self.aujourdhui else "."), jour)
            if enc and not g["recus_nb"]:
                sig("ENCAISSEMENT_SANS_RECU", "MOYENNE", CAT_CAISSE, ref,
                    f"{ref} : un encaissement de {argent.formater(encaisse)} {devise} est enregistré alors qu'aucun reçu "
                    f"valide n'existe ce jour-là pour ce percepteur.", jour)
            if enc and g["recus_nb"] and diff_recus:
                sig("ENCAISSE_DIFFERENT_DES_RECUS", "ÉLEVÉE", CAT_CAISSE, ref,
                    f"{ref} : le montant encaissé déclaré ({argent.formater(encaisse)}) ne correspond pas au total des "
                    f"reçus valides ({argent.formater(g['recus_total'])}) : différence {argent.formater(diff_recus)} "
                    f"{devise}" + (" (des reçus ont été annulés)." if g["annules_nb"] else "."), jour)
            if len(enc) > 1:
                sig("ENCAISSEMENTS_MULTIPLES", "FAIBLE", CAT_CAISSE, ref,
                    f"{ref} : {len(enc)} encaissements enregistrés (ENC-" + ", ENC-".join(str(e['N_ENC']) for e in enc)
                    + ") : doublon possible.", jour)
            for e in enc:
                mes.extend(self._verifier_encaissement(e, jour, ref))
            lignes.append({
                "jour": jour, "date_txt": jour.strftime("%d/%m/%Y"), "n_perc": n_perc, "percepteur": nom, "devise": devise,
                "journal_nb": g["journal_nb"], "journal_total": g["journal_total"],
                "annules_nb": g["annules_nb"], "annules_total": g["annules_total"],
                "recus_nb": g["recus_nb"], "recus_total": g["recus_total"],
                "encaisse": encaisse if enc else None, "verse": verse if enc else None,
                "ecart_remise": ecart_remise if enc else None, "diff_recus": diff_recus, "diff_journal": diff_journal,
                "references": ", ".join(f"ENC-{e['N_ENC']}" for e in enc),
                "statut": self._statut(mes), "remarques": " | ".join(a["message"] for a in mes if a)})
        return lignes

    def _verifier_encaissement(self, e, jour, ref) -> list:
        """Anomalies propres à un encaissement : trace au journal, écart, remise incomplète."""
        c = self.c
        n = e["N_ENC"]
        mes = []
        quand = _local(e["DATE_SAISIE"])
        sig = lambda *a: mes.append(self.signaler(*a, quand))
        events = c.enc_events.get(n, [])
        enregistre = next((x for x in events if x["action"] == "ENCAISSEMENT_ENREGISTRE"), None)
        if not enregistre:
            sig("ENCAISSEMENT_SANS_TRACE", "ÉLEVÉE", CAT_CAISSE, f"ENC-{n}",
                f"Encaissement ENC-{n} : aucune trace de son enregistrement dans le journal.")
        else:
            if enregistre["login"].lower() != (e["SAISI_PAR"] or "").lower():
                sig("ENCAISSEMENT_SAISI_PAR_AUTRE", "ÉLEVÉE", CAT_CAISSE, f"ENC-{n}",
                    f"Encaissement ENC-{n} : saisi par {e['SAISI_PAR']} selon la table, par {enregistre['login']} "
                    f"selon le journal.")
            dernier = events[-1]
            etat = dernier["detail"].split(" || après : ", 1)[1] if dernier["action"] == "ENCAISSEMENT_MODIFIE" \
                and " || après : " in dernier["detail"] else dernier["detail"]
            attendu = (f"| {e['DATE_ENC']} | encaissé {argent.formater(e['MONT_ENCAISSE'])} {e['CODE_DEVISE']} | "
                       f"versé {argent.formater(e['MONT_VERSE'])} | écart {argent.formater(e['ECART'])}")
            if dernier["action"] != "ENCAISSEMENT_SUPPRIME" and not etat.endswith(attendu):
                sig("ENCAISSEMENT_DIFFERENT_DU_JOURNAL", "ÉLEVÉE", CAT_CAISSE, f"ENC-{n}",
                    f"Encaissement ENC-{n} : la table (encaissé {argent.formater(e['MONT_ENCAISSE'])}, versé "
                    f"{argent.formater(e['MONT_VERSE'])}, journée du {jour.strftime('%d/%m/%Y')}) ne correspond pas à "
                    f"la dernière trace du journal : modifié en dehors de l'application ?")
        if e["MONT_ENCAISSE"] - e["MONT_VERSE"] != e["ECART"]:
            sig("ENCAISSEMENT_ECART_INCOHERENT", "ÉLEVÉE", CAT_CAISSE, f"ENC-{n}",
                f"Encaissement ENC-{n} : l'écart enregistré ({argent.formater(e['ECART'])}) ne correspond pas à "
                f"encaissé - versé ({argent.formater(e['MONT_ENCAISSE'] - e['MONT_VERSE'])}).")
        if e["ECART"] > 0:
            sig("REMISE_MANQUANT", "ÉLEVÉE", CAT_CAISSE, f"ENC-{n}",
                f"Encaissement ENC-{n} : {c.nom_perc(e['N_PERC'])} a encaissé {argent.formater(e['MONT_ENCAISSE'])} mais "
                f"n'a versé que {argent.formater(e['MONT_VERSE'])} {e['CODE_DEVISE']} : manquant "
                f"{argent.formater(e['ECART'])}.")
        elif e["ECART"] < 0:
            sig("REMISE_EXCEDENT", "MOYENNE", CAT_CAISSE, f"ENC-{n}",
                f"Encaissement ENC-{n} : {c.nom_perc(e['N_PERC'])} a versé {argent.formater(e['MONT_VERSE'])} pour "
                f"{argent.formater(e['MONT_ENCAISSE'])} {e['CODE_DEVISE']} encaissés : excédent "
                f"{argent.formater(-e['ECART'])}.")
        return mes

    # ------------------------------------------------------------ 3) annulations et corrections
    def annulations(self) -> list:
        c = self.c
        lignes, par_perc = [], {}
        for r in c.recus:
            if self.visible(r["jour"], r["N_PERC"], r["CODE_DEVISE"]):
                p = par_perc.setdefault(r["N_PERC"], [0, 0])
                p[0] += 1
                p[1] += r["STATUT"] == "ANNULE"
        for r in c.recus:
            if r["STATUT"] != "ANNULE":
                continue
            a = c.annul.get(r["N_RECU"])
            quand = _local(r["DATE_ANNULATION"]) if r["DATE_ANNULATION"] else (_local(a["date"]) if a else r["quand"])
            if not self.visible(quand.date(), r["N_PERC"], r["CODE_DEVISE"]):
                continue
            t = (c.enreg.get(r["N_RECU"]) or [None])[0]
            mes = []
            # annulation après que l'encaissement de la journée ait été enregistré : le rapprochement est faussé
            avant = [e for e in c.encaissements if e["N_PERC"] == r["N_PERC"] and e["CODE_DEVISE"] == r["CODE_DEVISE"]
                     and e["DATE_ENC"] == r["jour"].isoformat() and self._saisi_avant(e, a, r)]
            if avant:
                mes.append(self.signaler(
                    "ANNULATION_APRES_ENCAISSEMENT", "MOYENNE", CAT_ANNUL, r["N_RECU"],
                    f"Reçu {r['N_RECU']} ({argent.formater(r['MONT_PAYE'])} {r['CODE_DEVISE']}) annulé le "
                    f"{quand.strftime('%d/%m/%Y')} alors que l'encaissement du {r['jour'].strftime('%d/%m/%Y')} "
                    f"(ENC-{avant[0]['N_ENC']}) était déjà enregistré : l'encaissement ne correspond plus aux reçus valides.",
                    quand))
            lignes.append({
                "n_recu": r["N_RECU"], "quand": quand, "date_txt": quand.strftime("%d/%m/%Y  %H:%M"),
                "date_paiement_txt": r["quand"].strftime("%d/%m/%Y  %H:%M"), "matricule": r["MATRICULE"],
                "eleve": r["eleve"], "frais": r["frais"], "montant": r["MONT_PAYE"],
                "montant_txt": argent.formater(r["MONT_PAYE"]), "devise": r["CODE_DEVISE"],
                "motif": r["MOTIF_ANNULATION"] or "—", "percepteur": c.nom_perc(r["N_PERC"]),
                "enregistre_par": _qui(t["login"], c.noms) if t else "— aucune trace —",
                "annule_par": _qui(r["ANNULE_PAR"], c.noms) if r["ANNULE_PAR"] else "—",
                "delai": _duree_txt(quand - r["quand"]),
                "remarques": " | ".join(x["message"] for x in mes if x)})
        for n_perc, (total, annules) in par_perc.items():
            if annules >= MIN_ANNULATIONS and annules / total >= SEUIL_TAUX_ANNULATION:
                self.signaler("ANNULATIONS_NOMBREUSES", "MOYENNE", CAT_ANNUL, c.nom_perc(n_perc),
                              f"{c.nom_perc(n_perc)} : {annules} reçu(s) annulé(s) sur {total} "
                              f"({annules * 100 // total} %) : proportion inhabituelle.")
        lignes.sort(key=lambda x: x["quand"], reverse=True)
        return lignes

    def _saisi_avant(self, e, annulation, recu) -> bool:
        """L'encaissement `e` a-t-il été enregistré avant l'annulation du reçu ? (ordre du journal, sinon les dates)"""
        saisie = next((x for x in self.c.enc_events.get(e["N_ENC"], []) if x["action"] == "ENCAISSEMENT_ENREGISTRE"), None)
        if saisie and annulation:
            return saisie["id"] < annulation["id"]
        return bool(recu["DATE_ANNULATION"]) and e["DATE_SAISIE"] < recu["DATE_ANNULATION"]

    def corrections(self) -> list:
        """Encaissements modifiés ou supprimés, tarifs / frais / tranches / devises modifiés ou supprimés."""
        c = self.c
        lignes = []
        for n, events in c.enc_events.items():
            for ev in events:
                if ev["action"] == "ENCAISSEMENT_ENREGISTRE":
                    continue
                quand = _local(ev["date"])
                modif = ev["action"] == "ENCAISSEMENT_MODIFIE"
                if modif and " || après : " in ev["detail"]:
                    brut_avant, brut_apres = ev["detail"].split(" || après : ", 1)
                    avant, apres = _lire_detail_encaissement(brut_avant[len("avant : "):]), _lire_detail_encaissement(brut_apres)
                else:
                    avant, apres = _lire_detail_encaissement(ev["detail"]), None
                if not self.visible(quand.date(), None, (avant or apres or {}).get("devise")):
                    continue
                ref = f"ENC-{n}"
                if modif:
                    a_e, p_e = (avant or {}).get("ecart"), (apres or {}).get("ecart")
                    reduit = a_e is not None and p_e is not None and a_e != 0 and abs(p_e) < abs(a_e)
                    gravite = "MOYENNE" if reduit else "FAIBLE"
                    message = (f"Encaissement {ref} corrigé par {ev['login']} : {_texte_encaissement(avant)} -> "
                               f"{_texte_encaissement(apres)}" + (" : l'écart a été réduit." if reduit else "."))
                    self.signaler("ENCAISSEMENT_CORRIGE", gravite, CAT_ANNUL, ref, message, quand)
                    nature = "Encaissement modifié"
                else:
                    ecart = (avant or {}).get("ecart")
                    gravite = "ÉLEVÉE" if ecart else "MOYENNE"
                    self.signaler("ENCAISSEMENT_SUPPRIME", gravite, CAT_ANNUL, ref,
                                  f"Encaissement {ref} supprimé par {ev['login']} : {_texte_encaissement(avant)}"
                                  + (" : il présentait un écart." if ecart else "."), quand)
                    nature = "Encaissement supprimé"
                lignes.append(self._ligne_correction(ev, quand, nature, ref, _texte_encaissement(avant),
                                                     _texte_encaissement(apres) if modif else "—"))
        for ev in c.refs:
            quand = _local(ev["date"])
            if not self.visible(quand.date()):
                continue
            titre, _, reste = ev["detail"].partition(" | ")
            cle, _, plus = reste.partition(" | ")
            if ev["action"] == "REF_MODIFICATION":
                nature, avant, apres = f"{titre} : modification", "", plus
                joli = _RE_MONTANT_REF.sub(lambda m: f"MONTANT : {argent.formater(int(m.group(1)))} -> "
                                                       f"{argent.formater(int(m.group(2)))}", plus)
                avant, apres = "voir ci-contre", joli
            else:
                nature = f"{titre} : suppression"
                avant, apres = plus or "—", "—"
            lignes.append(self._ligne_correction(ev, quand, nature, f"{titre} {cle}", avant, apres))
        lignes.sort(key=lambda x: x["quand"], reverse=True)
        return lignes

    def _ligne_correction(self, ev, quand, nature, reference, avant, apres) -> dict:
        return {"quand": quand, "date_txt": quand.strftime("%d/%m/%Y  %H:%M"), "nature": nature, "reference": reference,
                "par_login": ev["login"], "par_nom": self.c.noms.get(ev["login"].lower(), ""), "avant": avant,
                "apres": apres}

    # ------------------------------------------------------------ 4) rapports journaliers imprimés
    def rapports_imprimes(self) -> list:
        """Compare chaque rapport imprimé aux reçus qui existaient AU MOMENT de l'impression, puis à ceux d'aujourd'hui."""
        c = self.c
        lignes = []
        for ev in c.rapports:
            global_ = ev["action"] == "RAPPORT_GLOBAL_IMPRIME"
            m = _RE_RAPPORT.match(ev["detail"])
            if not m:
                continue
            jour, nb_imprime, reste = date.fromisoformat(m.group(1)), int(m.group(2)), m.group(3) or ""
            quand = _local(ev["date"])
            portee_perc, total_imprime, nb_enc_imprime = None, None, None      # portée (None = tous), totaux imprimés
            comparable = True
            if global_:
                g = _RE_GLOBAL.match(reste)
                if g:
                    nb_enc_imprime, total_imprime = int(g.group(1)), g.group(2)
                else:
                    comparable = False
            else:
                p = _RE_PORTEE.match(reste)
                if p:
                    portee_perc = int(p.group(2)) if p.group(2) else None
                    total_imprime = p.group(3)
                else:
                    comparable = False                  # ancienne trace : la portée n'est pas connue
            scope_perc = portee_perc
            if self.n_perc is not None and scope_perc is not None and scope_perc != self.n_perc:
                continue
            if not self._jour_ok(jour):
                continue
            ref = f"{'Rapport global' if global_ else 'Rapport de caisse'} du {jour.strftime('%d/%m/%Y')}"
            base = {"quand": quand, "date_txt": quand.strftime("%d/%m/%Y  %H:%M"),
                    "type": "Rapport global" if global_ else "Rapport de caisse", "jour": jour,
                    "jour_txt": jour.strftime("%d/%m/%Y"),
                    "portee": ("Tous les percepteurs" if portee_perc is None else c.nom_perc(portee_perc))
                    if comparable or global_ else "inconnue (ancienne trace)",
                    "par_login": ev["login"], "imprime_nb": nb_imprime,
                    "imprime_total": total_imprime or "—"}
            if not comparable and not global_:
                lignes.append(dict(base, actuel_nb=None, actuel_total="—", statut="Non comparable",
                                   remarques="Trace ancienne : la portée et les totaux du rapport n'ont pas été conservés."))
                continue
            # reçus qui existaient à l'impression : enregistrés avant, et pas encore annulés à ce moment-là
            t_imprime = ev["date"]
            a_ce_moment, maintenant_, annules_apres, ajoutes_apres = [0, {}], [0, {}], 0, 0
            for r in c.recus:
                if r["jour"] != jour or (portee_perc is not None and r["N_PERC"] != portee_perc):
                    continue
                valide = r["STATUT"] == "VALIDE"
                if valide:
                    maintenant_[0] += 1
                    maintenant_[1][r["CODE_DEVISE"]] = maintenant_[1].get(r["CODE_DEVISE"], 0) + r["MONT_PAYE"]
                t_reg = (c.enreg.get(r["N_RECU"]) or [None])[0]
                a_ann = c.annul.get(r["N_RECU"])
                enregistre_avant = t_reg["id"] < ev["id"] if t_reg else r["DATE_PAY"] <= t_imprime
                annule_apres = a_ann["id"] > ev["id"] if a_ann else (r["DATE_ANNULATION"] or "") > t_imprime
                present = enregistre_avant and (valide or annule_apres)
                if present:
                    a_ce_moment[0] += 1
                    a_ce_moment[1][r["CODE_DEVISE"]] = a_ce_moment[1].get(r["CODE_DEVISE"], 0) + r["MONT_PAYE"]
                    annules_apres += not valide
                elif valide:
                    ajoutes_apres += 1
            mes = []
            sig = lambda *a: mes.append(self.signaler(*a, quand))
            ecarts = []
            if a_ce_moment[0] != nb_imprime:
                ecarts.append(f"{nb_imprime} reçu(s) imprimés, {a_ce_moment[0]} existaient à ce moment-là")
            if total_imprime is not None and total_imprime != _totaux_txt(a_ce_moment[1]):
                ecarts.append(f"total imprimé {total_imprime}, total des reçus existant alors {_totaux_txt(a_ce_moment[1])}")
            if global_ and nb_enc_imprime is not None:
                existants = 0
                for e in c.encaissements:
                    if e["DATE_ENC"] != jour.isoformat():
                        continue
                    saisie = next((x for x in c.enc_events.get(e["N_ENC"], []) if x["action"] == "ENCAISSEMENT_ENREGISTRE"), None)
                    existants += saisie["id"] < ev["id"] if saisie else e["DATE_SAISIE"] <= t_imprime
                supprimes_apres = sum(1 for id_log, j in c.enc_supprimes if j == jour.isoformat() and id_log > ev["id"])
                if existants + supprimes_apres != nb_enc_imprime:
                    ecarts.append(f"{nb_enc_imprime} encaissement(s) imprimés, {existants + supprimes_apres} "
                                  f"connus à ce moment-là")
            if ecarts:
                sig("RAPPORT_NON_CONFORME", "ÉLEVÉE", CAT_RAPPORTS, ref,
                    f"{ref} imprimé le {quand.strftime('%d/%m/%Y à %H:%M')} par {ev['login']} : " + " ; ".join(ecarts)
                    + " : le rapport ne correspond pas aux opérations enregistrées.")
            depuis = []
            if annules_apres:
                depuis.append(f"{annules_apres} reçu(s) annulé(s)")
                sig("RAPPORT_PERIME_ANNULATION", "MOYENNE", CAT_RAPPORTS, ref,
                    f"{ref} imprimé le {quand.strftime('%d/%m/%Y à %H:%M')} : {annules_apres} reçu(s) annulé(s) depuis, "
                    f"le rapport imprimé n'est plus à jour.")
            if ajoutes_apres:
                depuis.append(f"{ajoutes_apres} reçu(s) enregistré(s) après")
                sig("RAPPORT_PERIME_AJOUT", "FAIBLE", CAT_RAPPORTS, ref,
                    f"{ref} imprimé le {quand.strftime('%d/%m/%Y à %H:%M')} : {ajoutes_apres} reçu(s) enregistré(s) après "
                    f"l'impression (journée non terminée ?).")
            if ecarts:
                statut = "Écart"
            elif depuis:
                statut = "Conforme, modifié depuis"
            else:
                statut = "Conforme"
            lignes.append(dict(base, actuel_nb=maintenant_[0], actuel_total=_totaux_txt(maintenant_[1]), statut=statut,
                               remarques=" | ".join(x["message"] for x in mes if x)
                               or ("Depuis l'impression : " + ", ".join(depuis) + "." if depuis else "")))
        lignes.sort(key=lambda x: x["quand"], reverse=True)
        return lignes


# ================================================================== point d'entrée
def controle_financier(conn, session, du=None, au=None, n_perc=None, devise=None, journaliser_controle=True) -> dict:
    """Contrôle et audit financier. Filtres : période (`du` / `au`, dates incluses), percepteur (`n_perc`), devise.

    Retourne un dict : `synthese` (par devise), `paiements`, `rapprochement`, `annulations`, `corrections`, `rapports`,
    `anomalies` (de la plus grave à la moins grave), `nb_anomalies` (par gravité), `journal` (état de la chaîne
    d'empreintes). Le contrôle lui-même est inscrit au journal (sauf `journaliser_controle=False`)."""
    exiger(conn, session)
    _verifier_periode(du, au)
    ctx = _Contexte(conn)
    if n_perc is not None and n_perc not in ctx.percepteurs:
        raise ErreurAudit("Percepteur inconnu.")
    if devise and not conn.execute("SELECT 1 FROM DEVISE WHERE CODE_DEVISE = ?", (devise,)).fetchone():
        raise ErreurAudit("Devise inconnue.")
    ctl = _Controle(ctx, du, au, n_perc, devise)
    etat = etat_journal(conn)
    if not etat["ok"]:
        ctl.signaler("JOURNAL_ALTERE", "ÉLEVÉE", CAT_JOURNAL, "",
                     f"Le journal a été modifié à partir de la ligne {etat['anomalie']} : les conclusions de ce contrôle "
                     f"reposent sur un journal qui n'est plus fiable.")
    paiements = ctl.verifier_recus()
    rapprochement = ctl.rapprochement()
    annulations = ctl.annulations()
    corrections = ctl.corrections()
    rapports = ctl.rapports_imprimes()

    anomalies = sorted(ctl.anomalies, key=lambda a: (_RANG[a["gravite"]], -_horodatage(a["quand"]), a["reference"]))
    nb = {g: sum(1 for a in anomalies if a["gravite"] == g) for g in GRAVITES}

    synthese = {}
    for g in rapprochement:
        s = synthese.setdefault(g["devise"], {
            "devise": g["devise"], "recus_nb": 0, "recus_total": 0, "annules_nb": 0, "annules_total": 0, "encaisse": 0,
            "verse": 0, "ecart_remise": 0, "diff_recus": 0, "sans_encaissement": 0})
        s["recus_nb"] += g["recus_nb"]
        s["recus_total"] += g["recus_total"]
        s["annules_nb"] += g["annules_nb"]
        s["annules_total"] += g["annules_total"]
        if g["encaisse"] is None:
            s["sans_encaissement"] += g["recus_total"]
        else:
            s["encaisse"] += g["encaisse"]
            s["verse"] += g["verse"]
            s["ecart_remise"] += g["ecart_remise"]
            s["diff_recus"] += g["diff_recus"] or 0
    resultat = {
        "du": du, "au": au, "n_perc": n_perc, "percepteur": ctx.nom_perc(n_perc) if n_perc is not None else "",
        "devise": devise or "", "genere_le": datetime.now().strftime("%d/%m/%Y à %H:%M"), "journal": etat,
        "synthese": [synthese[d] for d in sorted(synthese)], "paiements": paiements, "rapprochement": rapprochement,
        "annulations": annulations, "corrections": corrections, "rapports": rapports, "anomalies": anomalies,
        "nb_anomalies": nb, "apres_reinitialisation": bool(ctx.reset)}
    if journaliser_controle:
        with conn:
            journaliser(conn, session.id_user, session.login, "AUDIT_CONTROLE_FINANCIER",
                        f"{len(paiements)} reçu(s), {len(rapprochement)} journée(s) | anomalies : {nb['ÉLEVÉE']} élevée(s), "
                        f"{nb['MOYENNE']} moyenne(s), {nb['FAIBLE']} faible(s)"
                        + (f" | du {du.strftime('%d/%m/%Y')}" if du else "")
                        + (f" au {au.strftime('%d/%m/%Y')}" if au else "")
                        + (f" | {ctx.nom_perc(n_perc)}" if n_perc is not None else "")
                        + (f" | {devise}" if devise else ""))
    return resultat


def liste_percepteurs(conn, session) -> list:
    """[(n_perc, nom complet)] de tous les percepteurs (actifs ou non : un audit doit pouvoir les retrouver)."""
    exiger(conn, session)
    return [(l["N_PERC"], l["NOM_COMPLET"]) for l in conn.execute(
        "SELECT P.N_PERC, U.NOM_COMPLET FROM PERCEPTEUR P JOIN UTILISATEUR U ON U.ID_USER = P.ID_USER "
        "ORDER BY U.NOM_COMPLET COLLATE NOCASE")]


def liste_devises(conn, session) -> list:
    exiger(conn, session)
    return [l["CODE_DEVISE"] for l in conn.execute("SELECT CODE_DEVISE FROM DEVISE ORDER BY CODE_DEVISE")]
