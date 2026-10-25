"""Tests du passage en classe supérieure (Direction des études, fonctionnalité 7) : réussis -> classe supérieure, échoués -> même classe,
option de la 8ème saisie par la direction, fin des études, résultats en attente, répétition sans danger, annulation, droits, page web.
Lancer :  python -m unittest test_promotion"""
import unittest

import app_web          # noqa: E402
import audit            # noqa: E402
import config           # noqa: E402
import cours            # noqa: E402
import promotion        # noqa: E402
from promotion import ErreurPromotion       # noqa: E402
from test_notes import MDP                  # noqa: E402
from test_prefecture_v57 import Fixture     # noqa: E402

SUIVANTE = "2027-2028"


class Ecole(Fixture):
    """Année 2026-2027 qui se termine, année 2027-2028 créée, 7ème A, 8ème A, et des classes d'humanités (options Sciences et Commerciale).
    7ème A : Kasongo 80 % (réussit), Amisi 30 % (échoue), Zola sans point (en attente). 8ème A : Autre 70 % (réussit)."""

    def setUp(self):
        super().setUp()
        c = self.conn
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('HUM', 'Humanités')")
            c.execute("INSERT INTO OPTION_SCO (CODE_OPTION, DESI_OPTION) VALUES ('SCI', 'Sciences'), ('COM', 'Commerciale')")
            c.execute("INSERT INTO POSSEDE (CODE_NIVEAU, CODE_OPTION) VALUES ('HUM', 'SCI'), ('HUM', 'COM')")
            for desi, annee_etude, opt, div in (("1ère Sciences A", "1ère", "SCI", "A"), ("1ère Commerciale A", "1ère", "COM", "A"),
                                                ("2ème Sciences A", "2ème", "SCI", "A"), ("3ème Sciences A", "3ème", "SCI", "A"),
                                                ("4ème Sciences A", "4ème", "SCI", "A"), ("4ème Commerciale A", "4ème", "COM", "A")):
                c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, CODE_OPTION, ANNEE_ETUDE, DIVISION) VALUES (?,?,?,?,?)",
                          (desi, "HUM", opt, annee_etude, div))
        self.hum = {l["DESI_CLASSE"]: l["N_CLASSE"] for l in c.execute("SELECT N_CLASSE, DESI_CLASSE FROM CLASSE WHERE CODE_NIVEAU = 'HUM'")}
        cours.ajouter_cours(c, self.admin, {"libelle": "Mathématiques", "code_niveau": "HUM", "heures_semaine": "4"})
        for n in self.hum.values():
            cours.ouvrir_cours(c, self.admin, self.annee, n)
        self.suivante = cours.creer_annee(c, self.admin, SUIVANTE, "06/09/2027", "08/07/2028")
        self.noter(self.c7, "0000/26", 80)
        self.noter(self.c7, "0001/26", 30)
        self.noter(self.c8, "0009/26", 70)

    # ------------------------------------------------------------------ outils
    def noter(self, classe, matricule, pct):
        """Points de toutes les périodes, dans tous les cours de la classe : le résultat annuel de l'élève est alors connu."""
        c = self.conn
        with c:
            for cc in c.execute("SELECT ID_CC FROM COURS_CLASSE WHERE ANNEESCO = ? AND N_CLASSE = ?", (self.annee, classe)).fetchall():
                for per in (self.per1, self.per2, self.per3, self.per4):
                    e = c.execute("SELECT ID_EVAL FROM EVALUATION WHERE ID_CC = ? AND ID_PER = ? AND TYPE = 'PER' AND NUMERO = 1", (cc[0], per)).fetchone()
                    id_eval = e[0] if e else c.execute(
                        "INSERT INTO EVALUATION (ID_CC, ID_PER, TYPE, NUMERO, DATE_EVAL, MAXIMUM, DATE_ENREG, ENREGISTRE_PAR) "
                        "VALUES (?,?, 'PER', 1, '2026-10-01', 20, '2026-10-01T08:00:00', 'test')", (cc[0], per)).lastrowid
                    c.execute("INSERT OR REPLACE INTO NOTE (ID_EVAL, MATRICULE, POINTS, DATE_MODIF) VALUES (?,?,?,'2026-10-01T08:00:00')",
                              (id_eval, matricule, pct * 20 / 100))

    def eleve(self, matricule, nom, classe, pct=None):
        with self.conn:
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES (?,?, 'M')", (matricule, nom))
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, matricule, classe))
        if pct is not None:
            self.noter(classe, matricule, pct)

    def detail(self, classe, session=None):
        return promotion.detail(self.conn, session or self.dire, self.annee, classe)

    def ligne(self, classe, matricule, session=None):
        return next(x for x in self.detail(classe, session)["eleves"] if x["matricule"] == matricule)

    def executer(self, classe):
        return promotion.executer(self.conn, self.dire, self.annee, classe)

    def inscription(self, matricule, annee=SUIVANTE):
        l = self.conn.execute("SELECT N_CLASSE, STATUT FROM INSCRIRE WHERE ANNEESCO = ? AND MATRICULE = ?", (annee, matricule)).fetchone()
        return (l["N_CLASSE"], l["STATUT"]) if l else None

    def actions(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]


# ================================================================== résultats et décisions
class TestDecisions(Ecole):
    def test_reussi_monte_echoue_reste_attente_en_attente(self):
        d = self.detail(self.c7)
        par = {x["matricule"]: x for x in d["eleves"]}
        self.assertEqual((par["0000/26"]["decision"], par["0000/26"]["dest_id"], par["0000/26"]["reussite"]), ("PROMU", self.c8, True))
        self.assertEqual((par["0001/26"]["decision"], par["0001/26"]["dest_id"], par["0001/26"]["reussite"]), ("REDOUBLE", self.c7, False))
        self.assertEqual((par["0002/26"]["decision"], par["0002/26"]["dest_id"]), ("ATTENTE", None))
        r = d["resume"]
        self.assertEqual((r["effectif"], r["promus"], r["redoublants"], r["attente"], r["a_choisir"], r["a_faire"]), (3, 1, 1, 1, 0, 2))
        self.assertEqual((d["annee"], d["annee_dest"]), (self.annee, SUIVANTE))

    def test_le_resultat_est_celui_de_l_annee_des_bulletins(self):
        """Seuil de réussite de l'école (50 %) : 50 % réussit, juste en dessous échoue."""
        self.eleve("0020/26", "Limite", self.c7, 50)
        self.eleve("0021/26", "Presque", self.c7, 49.5)
        self.assertEqual(self.ligne(self.c7, "0020/26")["decision"], "PROMU")
        self.assertEqual(self.ligne(self.c7, "0021/26")["decision"], "REDOUBLE")

    def test_la_classe_superieure_est_la_meme_division(self):
        with self.conn:
            self.conn.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('8ème B', 'SEC', '8ème', 'B')")
        c8b = self.conn.execute("SELECT MAX(N_CLASSE) FROM CLASSE").fetchone()[0]
        self.assertEqual(self.ligne(self.c7, "0000/26")["dest_id"], self.c8)               # 7ème A -> 8ème A (même division)
        d = self.detail(self.c7)
        self.assertEqual({x["n_classe"] for x in d["destinations"]}, {self.c8, c8b})

    def test_plusieurs_classes_sans_meme_division_la_direction_choisit(self):
        with self.conn:
            self.conn.execute("UPDATE CLASSE SET DIVISION = 'C', DESI_CLASSE = '8ème C' WHERE N_CLASSE = ?", (self.c8,))
            self.conn.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('8ème B', 'SEC', '8ème', 'B')")
        x = self.ligne(self.c7, "0000/26")
        self.assertIsNone(x["dest_id"])
        self.assertEqual(x["bloque"], "Classe d'accueil à choisir.")
        with self.assertRaises(ErreurPromotion):
            self.executer(self.c7)

    def test_eleve_desactive_ignore(self):
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0001/26'")
        self.assertEqual(sorted(x["matricule"] for x in self.detail(self.c7)["eleves"]), ["0000/26", "0002/26"])

    def test_vue_d_ensemble(self):
        a = promotion.apercu(self.conn, self.dire)
        self.assertEqual((a["annee"], a["annee_dest"], a["avertissement"]), (self.annee, SUIVANTE, ""))
        k = next(x for x in a["classes"] if x["n_classe"] == self.c7)
        self.assertEqual((k["effectif"], k["promus"], k["redoublants"], k["attente"]), (3, 1, 1, 1))
        self.assertIn(self.c8, [x["n_classe"] for x in a["classes"]])
        self.assertNotIn(self.cp, [x["n_classe"] for x in a["classes"]])                  # le primaire n'est pas concerné
        self.assertEqual(a["total"]["effectif"], 4)
        self.assertEqual(a["classes"][0]["n_classe"], self.c7)                             # 7ème d'abord, puis 8ème

    def test_primaire_refuse(self):
        with self.assertRaises(ErreurPromotion):
            promotion.detail(self.conn, self.dire, self.annee, self.cp)


# ================================================================== exécution
class TestExecution(Ecole):
    def test_inscrit_les_promus_et_les_redoublants(self):
        r = self.executer(self.c7)
        self.assertEqual((r["promus"], r["redoublants"], r["termines"], r["en_attente"], r["annee_dest"]), (1, 1, 0, 1, SUIVANTE))
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))
        self.assertEqual(self.inscription("0001/26"), (self.c7, "REDOUBLANT"))
        self.assertIsNone(self.inscription("0002/26"))                                    # en attente : pas traité
        self.assertEqual(self.inscription("0000/26", self.annee), (self.c7, "NOUVEAU"))   # l'année terminée n'est pas touchée
        self.assertEqual(self.inscription("0001/26", self.annee), (self.c7, "NOUVEAU"))
        self.assertIn("PASSAGE_EXECUTE", self.actions())

    def test_l_etat_apres_execution(self):
        self.executer(self.c7)
        d = self.detail(self.c7)
        par = {x["matricule"]: x for x in d["eleves"]}
        self.assertTrue(par["0000/26"]["fait"] and par["0001/26"]["fait"])
        self.assertEqual(par["0000/26"]["dest"], "8ème A")
        self.assertEqual((d["resume"]["faits"], d["resume"]["a_faire"], d["resume"]["attente"]), (2, 0, 1))

    def test_repetable_sans_danger(self):
        self.executer(self.c7)
        with self.assertRaises(ErreurPromotion):                                           # plus rien à traiter
            self.executer(self.c7)
        n = self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ?", (SUIVANTE,)).fetchone()[0]
        self.assertEqual(n, 2)
        self.noter(self.c7, "0002/26", 65)                                                 # le résultat de Zola est connu : il peut être traité
        r = self.executer(self.c7)
        self.assertEqual((r["promus"], r["redoublants"]), (1, 0))
        self.assertEqual(self.inscription("0002/26"), (self.c8, "ANCIEN"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ?", (SUIVANTE,)).fetchone()[0], 3)

    def test_eleve_deja_inscrit_dans_l_annee_suivante_n_est_pas_touche(self):
        with self.conn:
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE, STATUT) VALUES (?,?,?, 'TRANSFERT')", (SUIVANTE, "0000/26", self.c7))
        x = self.ligne(self.c7, "0000/26")
        self.assertEqual(x["deja_inscrit"], "7ème A")
        r = self.executer(self.c7)
        self.assertEqual((r["promus"], r["redoublants"]), (0, 1))
        self.assertEqual(self.inscription("0000/26"), (self.c7, "TRANSFERT"))

    def test_rien_a_faire_si_tout_est_en_attente(self):
        with self.conn:
            self.conn.execute("DELETE FROM NOTE")
        with self.assertRaises(ErreurPromotion):
            self.executer(self.c7)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ?", (SUIVANTE,)).fetchone()[0], 0)

    def test_annee_suivante_absente(self):
        with self.conn:
            self.conn.execute("DELETE FROM ANNEE_CALENDRIER WHERE ANNEESCO = ?", (SUIVANTE,))
            self.conn.execute("DELETE FROM ANNEE_SCO WHERE ANNEESCO = ?", (SUIVANTE,))
        a = promotion.apercu(self.conn, self.dire)
        self.assertIsNone(a["annee_dest"])
        self.assertIn("pas encore créée", a["avertissement"])
        with self.assertRaises(ErreurPromotion) as e:
            self.executer(self.c7)
        self.assertIn("pas encore créée", str(e.exception))

    def test_annee_source_par_defaut(self):
        """L'année en cours a une année suivante : c'est elle qui se termine. Si l'année suivante est déjà l'année en cours, on prend l'année d'avant."""
        self.assertEqual(promotion.apercu(self.conn, self.dire)["annee"], self.annee)
        with self.conn:
            self.conn.execute("UPDATE ANNEE_SCO SET EN_COURS = 0")
            self.conn.execute("UPDATE ANNEE_SCO SET EN_COURS = 1 WHERE ANNEESCO = ?", (SUIVANTE,))
        self.assertEqual(promotion.apercu(self.conn, self.dire)["annee"], self.annee)

    def test_redoublement_dans_une_classe_desactivee_refuse(self):
        with self.conn:
            self.conn.execute("UPDATE CLASSE SET ACTIF = 0 WHERE N_CLASSE = ?", (self.c7,))
        with self.assertRaises(ErreurPromotion) as e:
            self.executer(self.c7)
        self.assertIn("désactivée", str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ?", (SUIVANTE,)).fetchone()[0], 0)

    def test_paiement_possible_dans_la_nouvelle_classe(self):
        """L'élève promu a une inscription dans l'année suivante : un paiement peut s'y rattacher."""
        self.executer(self.c7)
        with self.conn:
            self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('MIN', ?, ?, 10000, 'USD')", (self.c8, SUIVANTE))
            self.conn.execute("INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                              "VALUES ('R900', ?, 1, '2027-09-10', '0000/26', ?, 'MIN', 'USD', 5000, 1)", (SUIVANTE, self.c8))

    def test_le_journal_garde_la_trace(self):
        self.executer(self.c7)
        detail = self.conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'PASSAGE_EXECUTE'").fetchone()[0]
        self.assertIn("1 promu(s), 1 redoublant(s)", detail)
        self.assertIn("0000/26", detail)
        self.detail(self.c7)
        self.assertIn("PASSAGE_CONSULTE", self.actions())


# ================================================================== 8ème : option saisie par la direction
class TestOption8eme(Ecole):
    def test_pas_d_option_d_office(self):
        d = self.detail(self.c8)
        self.assertTrue(d["choix_option"])
        x = d["eleves"][0]
        self.assertEqual((x["decision"], x["dest_id"]), ("PROMU", None))
        self.assertEqual({c["designation"] for c in d["destinations"]}, {"1ère Sciences A", "1ère Commerciale A"})
        self.assertEqual(d["resume"]["a_choisir"], 1)
        with self.assertRaises(ErreurPromotion) as e:
            self.executer(self.c8)
        self.assertIn("option", str(e.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE ANNEESCO = ?", (SUIVANTE,)).fetchone()[0], 0)

    def test_la_direction_saisit_l_option_puis_execute(self):
        r = promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": str(self.hum["1ère Commerciale A"])})
        self.assertEqual((r["enregistres"], r["retires"]), (1, 0))
        x = self.ligne(self.c8, "0009/26")
        self.assertEqual((x["dest"], x["dest_option"], x["choisi"]), ("1ère Commerciale A", "Commerciale", self.hum["1ère Commerciale A"]))
        self.executer(self.c8)
        self.assertEqual(self.inscription("0009/26"), (self.hum["1ère Commerciale A"], "ANCIEN"))
        self.assertIn("PASSAGE_CHOIX_ENREGISTRE", self.actions())
        self.assertIn("option Commerciale", self.conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'PASSAGE_EXECUTE'").fetchone()[0])

    def test_changer_et_retirer_un_choix(self):
        sci, com = str(self.hum["1ère Sciences A"]), str(self.hum["1ère Commerciale A"])
        promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": sci})
        self.assertEqual(promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": sci})["enregistres"], 0)      # inchangé
        promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": com})
        self.assertEqual(self.ligne(self.c8, "0009/26")["dest"], "1ère Commerciale A")
        r = promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": ""})
        self.assertEqual(r["retires"], 1)
        self.assertIsNone(self.ligne(self.c8, "0009/26")["dest_id"])

    def test_choix_hors_des_classes_d_accueil_refuse(self):
        for mauvais in (self.hum["2ème Sciences A"], self.c7, self.cp, 999999, "abc"):
            with self.assertRaises(ErreurPromotion):
                promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": str(mauvais)})

    def test_choix_pour_un_eleve_d_une_autre_classe_refuse(self):
        with self.assertRaises(ErreurPromotion):
            promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0000/26": str(self.hum["1ère Sciences A"])})

    def test_option_saisie_avant_les_resultats(self):
        """Un élève dont le résultat est en attente peut déjà avoir son option : elle sert dès que ses points sont connus."""
        self.eleve("0030/26", "Tardif", self.c8)
        promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0030/26": str(self.hum["1ère Sciences A"])})
        x = self.ligne(self.c8, "0030/26")
        self.assertEqual((x["decision"], x["dest"]), ("ATTENTE", "1ère Sciences A"))
        self.noter(self.c8, "0030/26", 90)
        self.assertEqual(self.ligne(self.c8, "0030/26")["decision"], "PROMU")
        promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": str(self.hum["1ère Commerciale A"])})
        self.executer(self.c8)
        self.assertEqual(self.inscription("0030/26")[0], self.hum["1ère Sciences A"])

    def test_echoue_en_8eme_redouble_sans_option(self):
        self.eleve("0031/26", "Faible", self.c8, 20)
        x = self.ligne(self.c8, "0031/26")
        self.assertEqual((x["decision"], x["dest_id"], x["bloque"]), ("REDOUBLE", self.c8, ""))
        promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": str(self.hum["1ère Sciences A"])})
        self.executer(self.c8)
        self.assertEqual(self.inscription("0031/26"), (self.c8, "REDOUBLANT"))

    def test_meme_option_pour_tous_les_eleves_sans_choix(self):
        self.eleve("0032/26", "Deux", self.c8, 75)
        self.eleve("0033/26", "Trois", self.c8, 10)
        sci, com = self.hum["1ère Sciences A"], self.hum["1ère Commerciale A"]
        promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": str(com)})
        r = promotion.appliquer_a_tous(self.conn, self.dire, self.annee, self.c8, sci)
        self.assertEqual(r["enregistres"], 1)                                              # 0032 seulement : 0009 a son choix, 0033 échoue (il redouble)
        self.assertEqual(self.ligne(self.c8, "0009/26")["dest_id"], com)                   # son choix est gardé
        self.assertEqual(self.ligne(self.c8, "0032/26")["dest_id"], sci)
        self.assertEqual(self.ligne(self.c8, "0033/26")["dest_id"], self.c8)               # l'échoué reste dans la même classe
        with self.assertRaises(ErreurPromotion):
            promotion.appliquer_a_tous(self.conn, self.dire, self.annee, self.c8, sci)      # plus personne sans choix

    def test_aucune_classe_de_1ere_ouverte(self):
        with self.conn:
            self.conn.execute("UPDATE CLASSE SET ACTIF = 0 WHERE ANNEE_ETUDE = '1ère'")
        d = self.detail(self.c8)
        self.assertEqual(d["destinations"], [])
        self.assertIn("Aucune classe", d["eleves"][0]["bloque"])
        with self.assertRaises(ErreurPromotion):
            promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": str(self.hum["1ère Sciences A"])})
        with self.assertRaises(ErreurPromotion):
            self.executer(self.c8)


# ================================================================== humanités
class TestHumanites(Ecole):
    def test_l_option_reste_la_meme(self):
        self.eleve("0040/26", "Sci", self.hum["1ère Sciences A"], 70)
        x = self.ligne(self.hum["1ère Sciences A"], "0040/26")
        self.assertEqual((x["decision"], x["dest"]), ("PROMU", "2ème Sciences A"))
        self.executer(self.hum["1ère Sciences A"])
        self.assertEqual(self.inscription("0040/26"), (self.hum["2ème Sciences A"], "ANCIEN"))

    def test_option_sans_classe_suivante(self):
        self.eleve("0041/26", "Com", self.hum["1ère Commerciale A"], 70)         # pas de 2ème Commerciale
        x = self.ligne(self.hum["1ère Commerciale A"], "0041/26")
        self.assertEqual(x["decision"], "PROMU")
        self.assertIsNone(x["dest_id"])
        self.assertIn("Aucune classe", x["bloque"])
        with self.assertRaises(ErreurPromotion):
            self.executer(self.hum["1ère Commerciale A"])

    def test_4eme_reussie_fin_des_etudes(self):
        quatrieme = self.hum["4ème Sciences A"]
        self.eleve("0042/26", "Finissant", quatrieme, 75)
        self.eleve("0043/26", "Recale", quatrieme, 35)
        d = self.detail(quatrieme)
        par = {x["matricule"]: x for x in d["eleves"]}
        self.assertEqual((par["0042/26"]["decision"], par["0042/26"]["dest_id"]), ("TERMINE", None))
        self.assertEqual((par["0043/26"]["decision"], par["0043/26"]["dest_id"]), ("REDOUBLE", quatrieme))
        self.assertTrue(d["fin"])
        r = self.executer(quatrieme)
        self.assertEqual((r["termines"], r["redoublants"], r["promus"]), (1, 1, 0))
        self.assertIsNone(self.inscription("0042/26"))                                    # fini : inscrit nulle part
        self.assertEqual(self.inscription("0043/26"), (quatrieme, "REDOUBLANT"))
        l = self.conn.execute("SELECT DECISION, N_CLASSE_DEST FROM PROMOTION WHERE MATRICULE = '0042/26'").fetchone()
        self.assertEqual((l["DECISION"], l["N_CLASSE_DEST"]), ("TERMINE", None))
        self.assertEqual(self.ligne(quatrieme, "0042/26")["decision"], "TERMINE")           # reste affiché comme traité
        with self.assertRaises(ErreurPromotion):
            promotion.enregistrer_choix(self.conn, self.dire, self.annee, quatrieme, {"0042/26": str(quatrieme)})

    def test_parcours_complet_sur_trois_ans(self):
        """7ème -> 8ème -> option choisie -> 2ème de la même option, d'année en année."""
        self.executer(self.c7)
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))


# ================================================================== annulation
class TestAnnulation(Ecole):
    def test_annuler_retire_l_inscription_et_garde_la_trace(self):
        self.executer(self.c7)
        r = promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Passage fait par erreur")
        self.assertEqual(r["annules"], 2)
        self.assertIsNone(self.inscription("0000/26"))
        self.assertIsNone(self.inscription("0001/26"))
        self.assertEqual(self.inscription("0000/26", self.annee), (self.c7, "NOUVEAU"))
        l = self.conn.execute("SELECT STATUT, MOTIF_ANNULATION FROM PROMOTION WHERE MATRICULE = '0000/26'").fetchone()
        self.assertEqual((l["STATUT"], l["MOTIF_ANNULATION"]), ("ANNULE", "Passage fait par erreur"))
        self.assertIn("PASSAGE_ANNULE", self.actions())
        self.assertFalse(self.ligne(self.c7, "0000/26")["fait"])

    def test_on_peut_refaire_apres_annulation(self):
        self.executer(self.c7)
        promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Erreur de saisie")
        r = self.executer(self.c7)
        self.assertEqual((r["promus"], r["redoublants"]), (1, 1))
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))
        l = self.conn.execute("SELECT STATUT, MOTIF_ANNULATION FROM PROMOTION WHERE MATRICULE = '0000/26'").fetchone()
        self.assertEqual((l["STATUT"], l["MOTIF_ANNULATION"]), ("FAIT", None))

    def test_annuler_un_seul_eleve(self):
        self.executer(self.c7)
        r = promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Cet élève change d'école", ["0001/26"])
        self.assertEqual(r["annules"], 1)
        self.assertIsNone(self.inscription("0001/26"))
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))

    def test_motif_obligatoire(self):
        self.executer(self.c7)
        for motif in ("", "  ", "ab"):
            with self.assertRaises(ErreurPromotion):
                promotion.annuler(self.conn, self.admin, self.annee, self.c7, motif)
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))

    def test_refuse_si_un_paiement_existe_dans_la_nouvelle_classe(self):
        self.executer(self.c7)
        with self.conn:
            self.conn.execute("INSERT INTO TARIF (CODTF, N_CLASSE, ANNEESCO, MONTANT, CODE_DEVISE) VALUES ('MIN', ?, ?, 10000, 'USD')", (self.c8, SUIVANTE))
            self.conn.execute("INSERT INTO PAIEMENT (N_RECU, ANNEESCO, NUM_SEQ, DATE_PAY, MATRICULE, N_CLASSE, CODTF, CODE_DEVISE, MONT_PAYE, N_PERC) "
                              "VALUES ('R901', ?, 1, '2027-09-10', '0000/26', ?, 'MIN', 'USD', 5000, 1)", (SUIVANTE, self.c8))
        with self.assertRaises(ErreurPromotion) as e:
            promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Passage fait par erreur")
        self.assertIn("paiement", str(e.exception))
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))
        self.assertEqual(self.inscription("0001/26"), (self.c7, "REDOUBLANT"))              # rien n'a été annulé (tout ou rien)
        r = promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Cet élève redouble par erreur", ["0001/26"])      # les autres, un par un
        self.assertEqual(r["annules"], 1)

    def test_refuse_si_l_inscription_a_ete_changee(self):
        self.executer(self.c7)
        with self.conn:
            self.conn.execute("UPDATE INSCRIRE SET N_CLASSE = ? WHERE ANNEESCO = ? AND MATRICULE = '0000/26'", (self.hum["1ère Sciences A"], SUIVANTE))
        with self.assertRaises(ErreurPromotion) as e:
            promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Passage fait par erreur", ["0000/26"])
        self.assertIn("changée", str(e.exception))

    def test_annuler_la_fin_des_etudes(self):
        quatrieme = self.hum["4ème Sciences A"]
        self.eleve("0044/26", "Finissant", quatrieme, 80)
        self.executer(quatrieme)
        r = promotion.annuler(self.conn, self.admin, self.annee, quatrieme, "Résultat contesté")
        self.assertEqual(r["annules"], 1)
        self.assertEqual(self.ligne(quatrieme, "0044/26")["fait"], False)

    def test_rien_a_annuler(self):
        with self.assertRaises(ErreurPromotion):
            promotion.annuler(self.conn, self.admin, self.annee, self.c7, "Passage fait par erreur")


# ================================================================== droits et sections
class TestDroits(Ecole):
    def test_lecture_exigee(self):
        for s in (self.prefet, self.secr, self.dird):
            with self.assertRaises(PermissionError):
                promotion.apercu(self.conn, s)
            with self.assertRaises(PermissionError):
                promotion.detail(self.conn, s, self.annee, self.c7)
        promotion.apercu(self.conn, self.dire)
        promotion.apercu(self.conn, self.admin)

    def test_ajout_pour_choisir_et_executer_modification_pour_annuler(self):
        sci = str(self.hum["1ère Sciences A"])
        with self.conn:                                                # la Directrice n'a plus que la Lecture
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes' AND DROIT <> 'LECTURE'", (self.dire.id_user,))
        d = promotion.detail(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual((d["peut_ajout"], d["peut_modification"]), (False, False))
        with self.assertRaises(PermissionError):
            promotion.enregistrer_choix(self.conn, self.dire, self.annee, self.c8, {"0009/26": sci})
        with self.assertRaises(PermissionError):
            promotion.appliquer_a_tous(self.conn, self.dire, self.annee, self.c8, sci)
        with self.assertRaises(PermissionError):
            self.executer(self.c7)
        self.executer_admin = promotion.executer(self.conn, self.admin, self.annee, self.c7)
        with self.assertRaises(PermissionError):
            promotion.annuler(self.conn, self.dire, self.annee, self.c7, "Passage fait par erreur")
        self.assertEqual(self.inscription("0000/26"), (self.c8, "ANCIEN"))

    def test_droit_relu_a_chaque_appel(self):
        promotion.apercu(self.conn, self.dire)
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'direction_etudes'", (self.dire.id_user,))
        with self.assertRaises(PermissionError):
            promotion.apercu(self.conn, self.dire)

    def test_section_non_ouverte(self):
        with self.conn:                                                # compte limité à la section primaire
            self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'PRIMAIRE')", (self.dire.id_user,))
        with self.assertRaises(PermissionError):
            promotion.apercu(self.conn, self.dire)

    def test_actions_cataloguees(self):
        for a in ("PASSAGE_CONSULTE", "PASSAGE_CHOIX_ENREGISTRE", "PASSAGE_EXECUTE", "PASSAGE_ANNULE", "PASSAGE_EXPORTE", "PASSAGE_IMPRIME"):
            self.assertIn(a, audit.ACTIONS)

    def test_fonctionnalite_dans_l_espace_de_la_direction(self):
        cles = [c for c, _t, _d in config.FONCTIONNALITES_DIRECTIONS["direction_etudes"]]
        self.assertIn("passage", cles)
        self.assertEqual(cles[-1], "rapport")


# ================================================================== export et impression
class TestExport(Ecole):
    def test_csv(self):
        csv_ = promotion.exporter_csv(self.conn, self.dire, self.annee, self.c7)
        lignes = csv_.lstrip("﻿").strip().splitlines()
        self.assertEqual(len(lignes), 4)
        self.assertIn("Classe d'accueil", lignes[0])
        self.assertTrue(any("Kasongo" in l and "8ème A" in l and "ADMIS" in l for l in lignes))
        self.assertTrue(any("Amisi" in l and "Redouble" in l for l in lignes))
        self.assertIn("PASSAGE_EXPORTE", self.actions())

    def test_impression(self):
        r = promotion.impression(self.conn, self.dire, self.annee, self.c7)
        self.assertEqual((r["resume"]["nb_monte"], r["resume"]["nb_redouble"]), (1, 1))
        self.assertTrue(all(x["situation"] for x in r["eleves"]))
        self.assertIn("PASSAGE_IMPRIME", self.actions())

    def test_export_et_impression_exigent_la_lecture(self):
        with self.assertRaises(PermissionError):
            promotion.exporter_csv(self.conn, self.prefet, self.annee, self.c7)
        with self.assertRaises(PermissionError):
            promotion.impression(self.conn, self.secr, self.annee, self.c7)


# ================================================================== page web
class TestWeb(Ecole):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "dire1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/direction_etudes"
        self.url = f"{self.base}?f=passage"

    def page(self, **q):
        plus = "".join(f"&{k}={v}" for k, v in q.items())
        r = self.cl.get(self.url + plus)
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    def test_onglet_et_vue_d_ensemble(self):
        self.assertIn("Passage en classe supérieure", self.cl.get(self.base).get_data(as_text=True))
        h = self.page()
        for mot in ("Année qui se termine", "7ème A", "8ème A", "Année d'accueil", SUIVANTE, "Montent"):
            self.assertIn(mot, h)

    def test_page_d_une_classe(self):
        h = self.page(annee=self.annee, classe=self.c7)
        for mot in ("Kasongo", "Amisi", "Zola", "Monte", "Redouble", "En attente", "Exécuter le passage", "Imprimer la liste", "8ème A"):
            self.assertIn(mot, h)

    def test_page_de_la_8eme_demande_l_option(self):
        h = self.page(annee=self.annee, classe=self.c8)
        for mot in ("Option choisie", "Choisir l&#39;option", "1ère Sciences A", "1ère Commerciale A", "Enregistrer les options choisies", "Option Sciences"):
            self.assertIn(mot, h)
        self.assertIn("disabled", h)                                       # exécution impossible tant que l'option n'est pas saisie

    def test_saisir_l_option_puis_executer_par_la_page(self):
        com = self.hum["1ère Commerciale A"]
        r = self.cl.post(f"{self.base}/passage/choix", data={"annee": self.annee, "classe": self.c8, "dest_0009/26": com})
        self.assertEqual(r.status_code, 302)
        h = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Classe d&#39;accueil enregistrée", h)
        r = self.cl.post(f"{self.base}/passage/executer", data={"annee": self.annee, "classe": self.c8})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.inscription("0009/26"), (com, "ANCIEN"))
        h = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Passage exécuté", h)
        self.assertIn("Passage fait", h)

    def test_execution_refusee_affiche_le_message(self):
        r = self.cl.post(f"{self.base}/passage/executer", data={"annee": self.annee, "classe": self.c8})
        self.assertEqual(r.status_code, 400)
        self.assertIn("option", r.get_data(as_text=True))
        self.assertIsNone(self.inscription("0009/26"))

    def test_meme_classe_pour_tous_et_annulation_par_la_page(self):
        sci = self.hum["1ère Sciences A"]
        self.assertEqual(self.cl.post(f"{self.base}/passage/choix_tous", data={"annee": self.annee, "classe": self.c8, "dest_tous": sci}).status_code, 302)
        self.assertEqual(self.cl.post(f"{self.base}/passage/executer", data={"annee": self.annee, "classe": self.c8}).status_code, 302)
        self.assertEqual(self.inscription("0009/26"), (sci, "ANCIEN"))
        h = self.page(annee=self.annee, classe=self.c8)
        self.assertIn("Annuler un passage", h)
        r = self.cl.post(f"{self.base}/passage/annuler_tout", data={"annee": self.annee, "classe": self.c8, "motif": "Erreur de saisie"})
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self.inscription("0009/26"))
        r = self.cl.post(f"{self.base}/passage/annuler", data={"annee": self.annee, "classe": self.c8, "motif": "Erreur de saisie"})
        self.assertEqual(r.status_code, 400)                              # rien de coché, rien à annuler

    def test_export_et_impression(self):
        r = self.cl.get(f"{self.base}/passage/export.csv?annee={self.annee}&classe={self.c7}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("Kasongo", r.get_data(as_text=True))
        r = self.cl.get(f"{self.base}/passage/impression?annee={self.annee}&classe={self.c7}")
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        for mot in ("window.print()", "Kasongo", "Imprimé le", "Passage en classe supérieure"):
            self.assertIn(mot, h)
        self.assertEqual(self.cl.get(f"{self.base}/passage/impression?annee={self.annee}&classe=99999").status_code, 404)
        self.assertEqual(self.cl.get(f"{self.base}/passage/export.csv?annee={self.annee}&classe=abc").status_code, 404)

    def test_autres_postes_refuses(self):
        for login in ("prefet1", "perc1", "secr1", "dird1"):
            cl = self.app.test_client()
            cl.post("/connexion", data={"login": login, "mdp": MDP})
            for url in (self.url, f"{self.base}/passage/export.csv?annee={self.annee}&classe={self.c7}",
                        f"{self.base}/passage/impression?annee={self.annee}&classe={self.c7}"):
                self.assertEqual(cl.get(url).status_code, 403, (login, url))
            self.assertEqual(cl.post(f"{self.base}/passage/executer", data={"annee": self.annee, "classe": self.c7}).status_code, 403, login)
        self.assertIsNone(self.inscription("0000/26"))

    def test_action_inconnue_et_sans_session(self):
        self.assertEqual(self.cl.post(f"{self.base}/passage/inconnue", data={}).status_code, 404)
        anonyme = self.app.test_client()
        self.assertIn(anonyme.get(self.url).status_code, (302, 401, 403))
        self.assertIn(anonyme.post(f"{self.base}/passage/executer", data={"annee": self.annee, "classe": self.c7}).status_code, (302, 401, 403))
        self.assertIsNone(self.inscription("0000/26"))


if __name__ == "__main__":
    unittest.main()
