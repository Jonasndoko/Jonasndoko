"""Tests de Préfecture > Documents scolaires officiels : préparer, soumettre à la signature ou à la validation, signer, imprimer.
Lancer :  python -m unittest test_documents_officiels"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web                  # noqa: E402
import config                   # noqa: E402
import documents_officiels as do   # noqa: E402
from documents_officiels import ErreurDocument   # noqa: E402
from test_notes import MDP                       # noqa: E402
from test_prefecture_v57 import Fixture          # noqa: E402

FREQ = "ATTESTATION_FREQUENTATION"


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


class Fix(Fixture):
    def preparer(self, m="0000/26", cle=FREQ, contenu="", session=None):
        return do.preparer(self.conn, session or self.prefet, self.annee, m, cle, contenu)

    def signe(self, m="0000/26", cle=FREQ):
        i = self.preparer(m, cle)
        do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")
        return i, do.signer(self.conn, self.prefet, i)


class TestCircuit(Fix):
    def test_preparer_propose_un_texte(self):
        i = self.preparer()
        d = do.lire(self.conn, self.prefet, i)
        self.assertEqual((d["statut"], d["titre"], d["numero"]), ("BROUILLON", "Attestation de fréquentation", ""))
        self.assertIn("0000/26", d["contenu"])
        self.assertIn(self.annee, d["contenu"])
        c = do.lire(self.conn, self.prefet, self.preparer("0001/26", "CERTIFICAT_SCOLARITE"))
        self.assertIn("certifie", c["contenu"])

    def test_documents_autorises_seulement(self):
        with self.assertRaises(ErreurDocument):
            self.preparer(cle="DIPLOME")
        with self.assertRaises(ErreurDocument):
            self.preparer(cle="AUTRE:Faux titre")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM DOCUMENT_OFFICIEL").fetchone()[0], 0)
        i = self.preparer(cle="AUTRE:" + config.AUTRES_DOCUMENTS_AUTORISES[0])
        self.assertIn("Complétez", do.lire(self.conn, self.prefet, i)["contenu"])

    def test_autre_document_incomplet_ne_se_soumet_pas(self):
        i = self.preparer(cle="AUTRE:" + config.AUTRES_DOCUMENTS_AUTORISES[0])
        with self.assertRaises(ErreurDocument):
            do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")
        do.modifier(self.conn, self.prefet, i, "Texte complet du document.")
        do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")

    def test_eleve_du_primaire_ou_inconnu_refuse(self):
        for m in ("0100/26", "9999/26"):
            with self.assertRaises(ErreurDocument):
                self.preparer(m)

    def test_modifier_puis_soumettre_puis_signer(self):
        i = self.preparer()
        do.modifier(self.conn, self.prefet, i, "Texte modifié par le Préfet.")
        do.soumettre(self.conn, self.prefet, i, "VALIDATION_DIRECTION")
        d = do.lire(self.conn, self.prefet, i)
        self.assertEqual((d["statut"], d["approbation_libelle"]), ("SOUMIS", "Validation de la Directrice des études"))
        with self.assertRaises(ErreurDocument):
            do.modifier(self.conn, self.prefet, i, "Trop tard")           # plus modifiable une fois soumis
        numero = do.signer(self.conn, self.prefet, i)
        self.assertEqual(numero, f"001/{self.annee}/AF")
        d = do.lire(self.conn, self.prefet, i)
        self.assertEqual((d["statut"], d["numero"], d["signe_par"]), ("SIGNE", numero, "prefet1"))
        self.assertEqual(d["contenu"], "Texte modifié par le Préfet.")

    def test_numeros_uniques_par_type_et_annee(self):
        _i, n1 = self.signe("0000/26")
        _j, n2 = self.signe("0001/26")
        _k, n3 = self.signe("0000/26", "CERTIFICAT_SCOLARITE")
        self.assertEqual((n1[:3], n2[:3], n3[:3]), ("001", "002", "001"))
        self.assertEqual(len({n1, n2, n3}), 3)

    def test_autre_autorite_exige_un_signataire(self):
        i = self.preparer()
        with self.assertRaises(ErreurDocument):
            do.soumettre(self.conn, self.prefet, i, "SIGNATURE_AUTRE")
        do.soumettre(self.conn, self.prefet, i, "SIGNATURE_AUTRE", "Inspecteur principal")
        do.signer(self.conn, self.prefet, i)
        self.assertEqual(do.lire(self.conn, self.prefet, i)["signataire"], "Inspecteur principal")
        with self.assertRaises(ErreurDocument):
            do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")   # déjà signé
        with self.assertRaises(ErreurDocument):
            do.soumettre(self.conn, self.prefet, self.preparer(), "inconnue")

    def test_renvoi_en_brouillon_avec_motif(self):
        i = self.preparer()
        do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")
        with self.assertRaises(ErreurDocument):
            do.renvoyer(self.conn, self.prefet, i, "x")
        do.renvoyer(self.conn, self.prefet, i, "Date de naissance à corriger")
        d = do.lire(self.conn, self.prefet, i)
        self.assertEqual((d["statut"], d["motif_retour"]), ("BROUILLON", "Date de naissance à corriger"))
        do.modifier(self.conn, self.prefet, i, "Texte corrigé.")
        do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")
        self.assertEqual(do.lire(self.conn, self.prefet, i)["motif_retour"], "")

    def test_annulation_avec_motif_sans_suppression(self):
        i, n = self.signe()
        with self.assertRaises(ErreurDocument):
            do.annuler(self.conn, self.prefet, i, "")
        do.annuler(self.conn, self.prefet, i, "Établi pour le mauvais élève")
        d = do.lire(self.conn, self.prefet, i)
        self.assertEqual((d["statut"], d["numero"]), ("ANNULE", n))          # le numéro n'est jamais redonné
        with self.assertRaises(ErreurDocument):
            do.signer(self.conn, self.prefet, i)
        self.assertEqual(do.liste(self.conn, self.prefet, self.annee)["resume"]["ANNULE"], 1)
        self.assertEqual(self.signe("0001/26")[1][:3], "002")
        with self.assertRaises(ErreurDocument):
            do.annuler(self.conn, self.prefet, self.preparer(), "Un brouillon ne s'annule pas")

    def test_liste_et_filtres(self):
        self.signe("0000/26")
        self.preparer("0001/26", "CERTIFICAT_SCOLARITE")
        r = do.liste(self.conn, self.prefet, self.annee)
        self.assertEqual((len(r["documents"]), r["resume"]["SIGNE"], r["resume"]["BROUILLON"]), (2, 1, 1))
        self.assertEqual(len(do.liste(self.conn, self.prefet, self.annee, "SIGNE")["documents"]), 1)
        self.assertEqual(len(do.liste(self.conn, self.prefet, self.annee, "", "CERTIFICAT_SCOLARITE")["documents"]), 1)
        self.assertEqual(len(do.liste(self.conn, self.prefet, self.annee, "", "", "Amisi")["documents"]), 1)
        self.assertEqual(len(do.liste(self.conn, self.prefet, self.annee, "", "", "/AF")["documents"]), 1)

    def test_journal(self):
        i, n = self.signe()
        do.document_pdf(self.conn, self.prefet, i)
        for a in ("DOCUMENT_OFFICIEL_PREPARE", "DOCUMENT_OFFICIEL_SOUMIS", "DOCUMENT_OFFICIEL_SIGNE", "DOCUMENT_OFFICIEL_IMPRIME"):
            self.assertEqual(len(journal(self.conn, a)), 1, a)


class TestPdf(Fix):
    def test_projet_puis_officiel(self):
        i = self.preparer()
        octets, nom = do.document_pdf(self.conn, self.prefet, i)
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertIn(b"NON SIGN", octets)
        self.assertIn("projet", nom)
        do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET")
        n = do.signer(self.conn, self.prefet, i)
        octets, nom = do.document_pdf(self.conn, self.prefet, i)
        self.assertNotIn(b"NON SIGN", octets)
        self.assertIn(n.encode(), octets)
        self.assertTrue(nom.endswith(".pdf"))


class TestDroits(Fix):
    def test_lecture_seule_pour_les_autres_postes(self):
        i = self.preparer()
        for s in (self.dird, self.secr):
            with self.assertRaises(PermissionError):
                do.liste(self.conn, s)
            with self.assertRaises(PermissionError):
                do.document_pdf(self.conn, s, i)
        self.assertEqual(len(do.liste(self.conn, self.admin, self.annee)["documents"]), 1)

    def test_ajout_et_modification_separes(self):
        i = self.preparer()
        u = self.conn.execute("SELECT ID_USER FROM UTILISATEUR WHERE LOGIN = 'prefet1'").fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'prefecture' AND DROIT = 'MODIFICATION'", (u,))
        self.assertTrue(do.liste(self.conn, self.prefet, self.annee)["peut_ajout"])
        self.preparer("0001/26")                                              # Ajout : préparer reste possible
        for f in (lambda: do.soumettre(self.conn, self.prefet, i, "SIGNATURE_PREFET"),):
            with self.assertRaises(PermissionError):
                f()
        with self.conn:
            self.conn.execute("DELETE FROM DROIT WHERE ID_USER = ? AND MODULE = 'prefecture' AND DROIT = 'AJOUT'", (u,))
        with self.assertRaises(PermissionError):
            self.preparer("0002/26")
        with self.assertRaises(PermissionError):
            do.modifier(self.conn, self.prefet, i, "x")


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "prefet1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/prefecture"

    def test_circuit_complet_par_les_pages(self):
        page = self.cl.get(self.base + "?f=documents").get_data(as_text=True)
        self.assertIn("Documents scolaires officiels", page)
        self.assertIn("Préparer un document", page)
        page = self.cl.get(self.base + "?f=documents&nouveau=1").get_data(as_text=True)
        self.assertIn("Préparer le brouillon", page)
        r = self.cl.post(self.base + "/documents/preparer", data={"annee": self.annee, "matricule": "0000/26", "type": FREQ})
        self.assertEqual(r.status_code, 302)
        page = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Brouillon préparé", page)
        i = self.conn.execute("SELECT ID_DOC FROM DOCUMENT_OFFICIEL").fetchone()[0]
        self.assertEqual(self.cl.post(self.base + "/documents/modifier", data={"doc": i, "contenu": "Nouveau texte."}).status_code, 302)
        self.assertEqual(self.cl.get(f"{self.base}/documents/{i}.pdf").mimetype, "application/pdf")
        r = self.cl.post(self.base + "/documents/soumettre", data={"doc": i, "approbation": "SIGNATURE_PREFET"})
        self.assertIn("Document soumis", self.cl.get(r.headers["Location"]).get_data(as_text=True))
        r = self.cl.post(self.base + "/documents/signer", data={"doc": i, "signataire": ""})
        page = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn(f"001/{self.annee}/AF", page)
        r = self.cl.post(self.base + "/documents/annuler", data={"doc": i, "motif": "Erreur de saisie"})
        self.assertIn("Annulé", self.cl.get(r.headers["Location"]).get_data(as_text=True))

    def test_erreurs_et_refus(self):
        r = self.cl.post(self.base + "/documents/preparer", data={"annee": self.annee, "matricule": "0100/26", "type": FREQ})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.cl.post(self.base + "/documents/inconnue", data={}).status_code, 404)
        self.assertEqual(self.cl.get(self.base + "/documents/999.pdf").status_code, 404)
        cl = self.app.test_client()
        self.assertEqual(cl.post("/connexion", data={"login": "dird1", "mdp": MDP}).status_code, 302)
        self.assertEqual(cl.get(self.base + "/documents/1.pdf").status_code, 403)
        self.assertEqual(cl.post(self.base + "/documents/preparer", data={"annee": self.annee, "matricule": "0000/26", "type": FREQ}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
