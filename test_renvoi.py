"""Tests du renvoi d'un élève par le Préfet : élève archivé avec la mention « Renvoyé », historique conservé, matricule libéré puis
réattribué sans héritage, droits, section, reçus toujours verrouillés, contrôle numérique, journal.
Lancer :  python -m unittest test_renvoi"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import archives_scolaires               # noqa: E402
import controle                         # noqa: E402
import droits                           # noqa: E402
import identite                         # noqa: E402
import prefecture                       # noqa: E402
import renvoi                           # noqa: E402
from prefecture import ErreurPrefecture  # noqa: E402
from renvoi import ErreurRenvoi         # noqa: E402
from test_prefecture_v57 import Fixture  # noqa: E402

AUJOURDHUI = date.today().isoformat()
MOTIF = "Violences répétées envers un camarade"


class TestRenvoi(Fixture):
    def renvoyer(self, matricule="0001/26", **plus):
        champs = dict(date_renvoi=AUJOURDHUI, motif=MOTIF)
        champs.update(plus)
        return renvoi.renvoyer_eleve(self.conn, self.prefet, matricule, **champs)

    def donner(self, session, module, droit="LECTURE"):
        d = droits.droits_utilisateur(self.conn, session.id_user) | {(module, droit)}
        droits.remplacer_droits(self.conn, session.id_user, d)
        self.conn.commit()

    def eleve(self, m):
        return self.conn.execute("SELECT * FROM ELEVE WHERE MATRICULE = ?", (m,)).fetchone()

    # ------------------------------------------------------------------ l'élève renvoyé reste, marqué « renvoyé »
    def test_l_eleve_reste_dans_les_archives_marque_renvoye(self):
        r = self.renvoyer()
        self.assertEqual((r["ancien"], r["archive"]), ("0001/26", "0001/26-R"))
        e = self.eleve("0001/26-R")
        self.assertEqual((e["NOM"], e["ACTIF"]), ("Amisi", 0))
        i = renvoi.info(self.conn, "0001/26-R")
        self.assertEqual((i["ancien_matricule"], i["motif"], i["par"]), ("0001/26", MOTIF, "prefet1"))
        self.assertTrue(renvoi.est_renvoye(self.conn, "0001/26-R"))
        self.assertFalse(renvoi.est_renvoye(self.conn, "0000/26"))
        d = archives_scolaires.dossier(self.conn, self.secr, "0001/26-R")
        self.assertEqual(d["renvoi"]["ancien_matricule"], "0001/26")
        self.assertTrue(d["ancien"])
        self.assertFalse(d["eleve"]["actif"])

    def test_l_historique_suit_l_eleve_renvoye(self):
        self.renvoyer()
        self.assertEqual(self.conn.execute("SELECT MATRICULE FROM PAIEMENT WHERE N_RECU = 'R2'").fetchone()[0], "0001/26-R")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE MATRICULE = '0001/26-R'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE MATRICULE = '0001/26'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.nb_paiements(), (2, 14000))                                          # aucun reçu perdu ni modifié

    def test_la_decision_et_le_journal(self):
        r = self.renvoyer()
        dec = self.conn.execute("SELECT * FROM DECISION_PREFET WHERE ID_DECISION = ?", (r["decision"],)).fetchone()
        self.assertEqual((dec["CATEGORIE"], dec["MATRICULE"], dec["DETAIL"]), ("disciplinaire", "0001/26-R", MOTIF))
        lignes = [l[0] for l in self.conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = 'ELEVE_RENVOYE'")]
        self.assertEqual(len(lignes), 1)
        self.assertIn("0001/26", lignes[0])
        self.assertIn("0001/26-R", lignes[0])

    # ------------------------------------------------------------------ matricule libéré, puis réattribué sans héritage
    def test_le_matricule_libere_est_redonne_au_prochain_eleve_sans_historique(self):
        self.renvoyer()
        self.assertEqual(self.conn.execute("SELECT ORDRE FROM MATRICULE_LIBRE WHERE ANNEE = '26'").fetchall()[0][0], 1)
        with self.conn:
            nouveau = identite.nouveau_matricule(self.conn)
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES (?, 'Nouveau', 'M')", (nouveau,))
        self.assertEqual(nouveau, "0001/26")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PAIEMENT WHERE MATRICULE = ?", (nouveau,)).fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM INSCRIRE WHERE MATRICULE = ?", (nouveau,)).fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM MATRICULE_LIBRE").fetchone()[0], 0)       # le numéro est repris, pas deux fois
        with self.conn:
            suivant = identite.nouveau_matricule(self.conn)
        self.assertNotEqual(suivant, "0001/26")                                                              # puis le compteur reprend
        # l'élève renvoyé garde son nom et son reçu sous sa clé d'archive
        self.assertEqual(self.eleve("0001/26-R")["NOM"], "Amisi")
        self.assertEqual(self.eleve("0001/26")["NOM"], "Nouveau")

    def test_le_plus_petit_numero_libre_d_abord_et_meme_annee_seulement(self):
        self.renvoyer("0002/26")
        self.renvoyer("0001/26")
        with self.conn:
            self.assertEqual(identite.nouveau_matricule(self.conn), "0001/26")
        with self.conn:
            self.assertEqual(identite.nouveau_matricule(self.conn, date(2027, 3, 1)), "0001/27")             # le 26 reste réservé à l'année 26
        self.assertEqual(self.conn.execute("SELECT ORDRE FROM MATRICULE_LIBRE WHERE ANNEE = '26'").fetchone()[0], 2)

    def test_ancien_qr_ne_donne_pas_acces_au_nouvel_eleve(self):
        ancien_qr = self.eleve("0001/26")["CODE_QR"]
        self.renvoyer()
        with self.conn:
            m = identite.nouveau_matricule(self.conn)
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE, CODE_QR) VALUES (?, 'Nouveau', 'M', ?)", (m, identite.nouveau_code_qr(self.conn, m)))
        self.assertNotEqual(self.eleve("0001/26")["CODE_QR"], ancien_qr)

    # ------------------------------------------------------------------ garde-fous
    def test_droits_section_et_double_renvoi(self):
        with self.assertRaises(PermissionError):
            renvoi.renvoyer_eleve(self.conn, self.dire, "0001/26", AUJOURDHUI, MOTIF)          # la directrice n'a pas le droit
        with self.assertRaises(PermissionError):
            self.renvoyer("0100/26")                                                            # élève du primaire
        with self.assertRaises(ErreurRenvoi):
            self.renvoyer("9999/26")                                                            # inconnu
        self.renvoyer()
        with self.assertRaises(ErreurRenvoi):
            self.renvoyer("0001/26-R")                                                          # déjà renvoyé
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM RENVOI").fetchone()[0], 1)

    def test_motif_et_date_obligatoires_et_rien_n_est_modifie_en_cas_de_refus(self):
        for plus in (dict(motif=""), dict(motif="ok"), dict(date_renvoi="pas une date"),
                     dict(date_renvoi=date(2099, 1, 1).isoformat())):
            with self.assertRaises(ErreurPrefecture):
                self.renvoyer(**plus)
        self.assertEqual(self.eleve("0001/26")["ACTIF"], 1)
        self.assertIsNone(self.eleve("0001/26-R"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM MATRICULE_LIBRE").fetchone()[0], 0)

    def test_les_recus_restent_verrouilles_et_un_renvoi_ne_se_modifie_pas(self):
        self.renvoyer()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute("UPDATE PAIEMENT SET MONT_PAYE = 1 WHERE N_RECU = 'R2'")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute("UPDATE RENVOI SET MOTIF = 'autre'")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.conn:
                self.conn.execute("DELETE FROM RENVOI")

    def test_le_controle_numerique_refuse_l_eleve_renvoye(self):
        self.renvoyer()
        self.donner(self.prefet, controle.MODULE)
        with self.assertRaises(controle.ErreurControle):
            controle.controler_eleve(self.conn, self.prefet, "0001/26-R")

    def test_liste_des_renvois(self):
        self.renvoyer()
        l = renvoi.liste_renvois(self.conn, self.prefet)
        self.assertEqual([(x["archive"], x["ancien_matricule"], x["matricule_libre"], x["reattribue_a"]) for x in l],
                         [("0001/26-R", "0001/26", True, "")])
        with self.conn:
            m = identite.nouveau_matricule(self.conn)
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM, SEXE) VALUES (?, 'Nouveau', 'M')", (m,))
        l = renvoi.liste_renvois(self.conn, self.prefet)
        self.assertEqual((l[0]["matricule_libre"], l[0]["reattribue_a"]), (False, "Nouveau"))


if __name__ == "__main__":
    unittest.main()
