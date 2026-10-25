"""Règle : les frais d'inscription sont réservés aux candidats (sans matricule). Un élève déjà inscrit ne les paie pas.
Lancer :  python test_inscription_reservee.py"""
import unittest

import test_paiement_candidat as base
import donnees
import paiements
from test_paiement_candidat import AN


class TestInscriptionReservee(base.Base):
    def eleve(self):
        return self.conn.execute("SELECT E.MATRICULE, E.NOM, E.POSTNOM, E.PRENOM, I.N_CLASSE FROM ELEVE E "
                                 "JOIN INSCRIRE I ON I.MATRICULE = E.MATRICULE WHERE I.ANNEESCO = ? LIMIT 1", (AN,)).fetchone()

    def test_un_eleve_avec_matricule_ne_peut_pas_payer_l_inscription(self):
        e = self.eleve()
        avant = self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0]
        with self.assertRaises(paiements.ErreurPaiement) as cm:
            paiements.enregistrer_paiement(self.conn, self.perc, e["MATRICULE"], AN, "INSC", 3000)
        self.assertIn("déjà inscrit", str(cm.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM PAIEMENT").fetchone()[0], avant)

    def test_les_frais_d_inscription_ne_figurent_pas_dans_la_situation_de_l_eleve(self):
        e = self.eleve()
        codes = [l.codtf for l in donnees.situation(self.conn, e["MATRICULE"], AN, e["N_CLASSE"])]
        self.assertNotIn("INSC", codes)
        self.assertTrue(codes)                                       # les autres frais restent dus

    def test_un_nom_d_eleve_existant_ne_peut_pas_payer_comme_candidat(self):
        e = self.eleve()
        with self.assertRaises(paiements.ErreurPaiement) as cm:
            self.payer(nom=e["NOM"], postnom=e["POSTNOM"] or "", prenom=e["PRENOM"] or "")
        self.assertIn(e["MATRICULE"], str(cm.exception))

    def test_un_vrai_candidat_peut_toujours_payer(self):
        self.assertTrue(self.payer(nom="Nouveau", postnom="Candidat", prenom="Test"))


if __name__ == "__main__":
    unittest.main()
