"""Tests du Dossier personnel (Gestion du personnel, 1re fonctionnalité) : enregistrement, modification, documents
numérisés, fiche individuelle, droits et journal.
Lancer :  python test_personnel.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import config        # noqa: E402
import database      # noqa: E402
import droits        # noqa: E402
import migrations    # noqa: E402
import personnel     # noqa: E402
import security      # noqa: E402
from personnel import ErreurPersonnel  # noqa: E402

MDP = "Tr@vail-Amour-2026"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def saisie(**autres):
    base = {"nom": "mukendi", "postnom": "kabeya", "prenom": "jean-pierre", "sexe": "M", "date_naissance": "15/03/1985",
            "adresse": "12, avenue de la Paix, Kinshasa", "telephone": "+243 812 345 678", "email": "JP.Mukendi@Gmail.com",
            "date_engagement": "01/09/2015", "fonction": "Enseignant", "statut_pro": "PERMANENT", "matricule": ""}
    base.update(autres)
    return base


class TestPersonnel(unittest.TestCase):
    def setUp(self):
        self.conn = database.connecter(os.path.join(tempfile.mkdtemp(), "p.db"))
        security.creer_utilisateur(self.conn, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(self.conn, "admin1", MDP).session
        self.id_sec = security.creer_utilisateur(self.conn, "sec1", "Sophie", "SECRETAIRE", MDP)
        self.sec = security.authentifier(self.conn, "sec1", MDP).session
        self.dossier = tempfile.mkdtemp()

    def donner(self, *noms):
        with self.conn:
            droits.remplacer_droits(self.conn, self.id_sec, {("personnel", d) for d in noms})

    def fichier(self, nom, contenu):
        chemin = os.path.join(self.dossier, nom)
        with open(chemin, "wb") as f:
            f.write(contenu)
        return chemin

    def agent(self, **autres):
        return personnel.enregistrer_agent(self.conn, self.admin, saisie(**autres))["matricule"]

    def actions_journal(self):
        return [l["ACTION"] for l in self.conn.execute("SELECT ACTION FROM JOURNAL ORDER BY ID_LOG")]

    # ---------------------------------------------------------- enregistrement
    def test_enregistrer_un_agent_normalise_les_champs_et_donne_un_matricule(self):
        r = personnel.enregistrer_agent(self.conn, self.admin, saisie())
        self.assertTrue(r["matricule"].startswith("P0001/"))
        a = personnel.charger_agent(self.conn, self.admin, r["matricule"])
        self.assertEqual(a["nom_complet"], "MUKENDI KABEYA Jean-Pierre")
        self.assertEqual(a["date_naissance"], "15/03/1985")
        self.assertEqual(a["date_engagement"], "01/09/2015")
        self.assertEqual(a["email"], "jp.mukendi@gmail.com")
        self.assertEqual(a["libelle_statut"], "Permanent")
        self.assertTrue(a["actif"])
        self.assertIn("AGENT_ENREGISTRE", self.actions_journal())

    def test_les_matricules_se_suivent_et_un_matricule_saisi_est_respecte(self):
        m1, m2 = self.agent(), self.agent(nom="Kasa")
        self.assertEqual((m1[:5], m2[:5]), ("P0001", "P0002"))
        self.assertEqual(self.agent(nom="Tshala", matricule="sec-123/45"), "SEC-123/45")
        self.assertEqual(self.agent(nom="Ilunga")[:5], "P0003")                  # le compteur n'est pas perturbé

    def test_matricule_deja_pris_ou_invalide_refuse(self):
        m = self.agent()
        with self.assertRaises(ErreurPersonnel):
            self.agent(nom="Autre", matricule=m.lower())
        with self.assertRaises(ErreurPersonnel):
            self.agent(nom="Autre", matricule="a b!")
        self.assertEqual(len(personnel.rechercher(self.conn, self.admin)), 1)

    def test_champs_obligatoires_et_incoherences_refuses(self):
        cas = [{"nom": ""}, {"sexe": ""}, {"date_naissance": ""}, {"date_naissance": "31/02/1990"},
               {"date_naissance": "01/01/2015"}, {"date_naissance": "01/01/2999"}, {"adresse": " "},
               {"telephone": ""}, {"telephone": "abc"}, {"email": "pas-un-mail"}, {"date_engagement": ""},
               {"date_engagement": "01/01/2999"}, {"date_engagement": "01/01/2000"},   # 15 ans à cette date
               {"fonction": ""}, {"statut_pro": ""}, {"statut_pro": "ROI"}]
        for c in cas:
            with self.subTest(c), self.assertRaises(ErreurPersonnel):
                self.agent(**c)
        self.assertEqual(personnel.rechercher(self.conn, self.admin), [])

    def test_postnom_prenom_et_email_sont_facultatifs(self):
        m = self.agent(postnom="", prenom="", email="")
        a = personnel.charger_agent(self.conn, self.admin, m)
        self.assertEqual((a["postnom"], a["prenom"], a["email"], a["nom_complet"]), ("", "", "", "MUKENDI"))

    # ---------------------------------------------------------- modification
    def test_modifier_enregistre_seulement_ce_qui_change(self):
        m = self.agent()
        champs = personnel.modifier_agent(self.conn, self.admin, m, saisie(telephone="0990001111", fonction="Surveillant"))
        self.assertEqual(sorted(champs), ["téléphone"])          # la fonction ne change que par une affectation
        a = personnel.charger_agent(self.conn, self.admin, m)
        self.assertEqual((a["telephone"], a["fonction"], a["matricule"]), ("0990001111", "Enseignant", m))
        self.assertEqual(a["modifie_par"], "admin1")
        avant = len(self.actions_journal())
        self.assertEqual(personnel.modifier_agent(self.conn, self.admin, m, saisie(telephone="0990001111")), [])
        self.assertEqual(len(self.actions_journal()), avant)                     # rien changé : rien écrit

    def test_modifier_un_agent_inconnu_ou_avec_une_saisie_invalide(self):
        with self.assertRaises(ErreurPersonnel):
            personnel.modifier_agent(self.conn, self.admin, "ZZZ", saisie())
        m = self.agent()
        with self.assertRaises(ErreurPersonnel):
            personnel.modifier_agent(self.conn, self.admin, m, saisie(email="x"))
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m)["email"], "jp.mukendi@gmail.com")

    def test_desactiver_et_reactiver_conservent_le_dossier(self):
        m = self.agent()
        personnel.changer_activite(self.conn, self.admin, m, False)
        self.assertFalse(personnel.charger_agent(self.conn, self.admin, m)["actif"])
        self.assertEqual(len(personnel.rechercher(self.conn, self.admin, inclure_inactifs=False)), 0)
        self.assertEqual(len(personnel.rechercher(self.conn, self.admin)), 1)
        personnel.changer_activite(self.conn, self.admin, m, True)
        self.assertTrue(personnel.charger_agent(self.conn, self.admin, m)["actif"])
        self.assertEqual([a for a in self.actions_journal() if a.startswith("AGENT_ACTIV") or a.startswith("AGENT_DESAC")],
                         ["AGENT_DESACTIVE", "AGENT_ACTIVE"])

    # ---------------------------------------------------------- recherche
    def test_recherche_sans_accents_ni_casse(self):
        self.agent(nom="Kalonji", prenom="Éric", fonction="Comptable")
        self.agent(nom="Banza", fonction="Enseignant")
        self.assertEqual([a["nom"] for a in personnel.rechercher(self.conn, self.admin, "eric kalonji")], ["KALONJI"])
        self.assertEqual([a["nom"] for a in personnel.rechercher(self.conn, self.admin, "comptable")], ["KALONJI"])
        self.assertEqual([a["nom"] for a in personnel.rechercher(self.conn, self.admin, "")], ["BANZA", "KALONJI"])
        self.assertEqual(personnel.rechercher(self.conn, self.admin, "introuvable"), [])

    # ---------------------------------------------------------- documents
    def test_ajouter_ouvrir_et_supprimer_un_document(self):
        m = self.agent()
        id_doc = personnel.ajouter_document(self.conn, self.admin, m, "Diplôme", self.fichier("diplome.pdf", PDF))
        docs = personnel.liste_documents(self.conn, self.admin, m)
        self.assertEqual([(d["type_doc"], d["nom_fichier"], d["format"]) for d in docs], [("Diplôme", "diplome.pdf", "PDF")])
        self.assertEqual(personnel.charger_agent(self.conn, self.admin, m)["nb_documents"], 1)
        chemin = personnel.preparer_document(self.conn, self.admin, id_doc)
        self.assertEqual(open(chemin, "rb").read(), PDF)
        self.assertTrue(chemin.endswith(".pdf"))
        personnel.supprimer_document(self.conn, self.admin, id_doc)
        self.assertEqual(personnel.liste_documents(self.conn, self.admin, m), [])
        for a in ("AGENT_DOCUMENT_AJOUTE", "AGENT_DOCUMENT_CONSULTE", "AGENT_DOCUMENT_SUPPRIME"):
            self.assertIn(a, self.actions_journal())

    def test_le_format_est_reconnu_par_le_contenu_pas_par_l_extension(self):
        m = self.agent()
        personnel.ajouter_document(self.conn, self.admin, m, "Pièce d'identité", self.fichier("scan.dat", JPEG))
        personnel.ajouter_document(self.conn, self.admin, m, "Pièce d'identité", self.fichier("scan2.pdf", PNG))
        self.assertEqual(sorted(d["format"] for d in personnel.liste_documents(self.conn, self.admin, m)), ["JPEG", "PNG"])
        for nom, contenu in (("virus.pdf", b"MZ\x90\x00 programme"), ("vide.pdf", b"")):
            with self.subTest(nom), self.assertRaises(ErreurPersonnel):
                personnel.ajouter_document(self.conn, self.admin, m, "Autre document", self.fichier(nom, contenu))

    def test_document_trop_gros_type_manquant_ou_fichier_absent(self):
        m = self.agent()
        gros = self.fichier("gros.pdf", PDF + b"0" * personnel.TAILLE_MAX_DOCUMENT)
        with self.assertRaises(ErreurPersonnel):
            personnel.ajouter_document(self.conn, self.admin, m, "Diplôme", gros)
        with self.assertRaises(ErreurPersonnel):
            personnel.ajouter_document(self.conn, self.admin, m, "", self.fichier("a.pdf", PDF))
        with self.assertRaises(ErreurPersonnel):
            personnel.ajouter_document(self.conn, self.admin, m, "Diplôme", os.path.join(self.dossier, "absent.pdf"))
        with self.assertRaises(ErreurPersonnel):
            personnel.ajouter_document(self.conn, self.admin, "ZZZ", "Diplôme", self.fichier("b.pdf", PDF))
        self.assertEqual(personnel.liste_documents(self.conn, self.admin, m), [])

    def test_un_document_altere_n_est_pas_ouvert(self):
        m = self.agent()
        id_doc = personnel.ajouter_document(self.conn, self.admin, m, "Diplôme", self.fichier("d.pdf", PDF))
        with self.conn:
            self.conn.execute("UPDATE DOCUMENT_PERSONNEL SET CONTENU = ? WHERE ID_DOC = ?", (PDF + b"x", id_doc))
        with self.assertRaises(ErreurPersonnel):
            personnel.preparer_document(self.conn, self.admin, id_doc)

    # ---------------------------------------------------------- fiche individuelle
    def test_fiche_pdf_generee_et_journalisee(self):
        m = self.agent()
        personnel.ajouter_document(self.conn, self.admin, m, "Diplôme", self.fichier("d.pdf", PDF))
        chemin = personnel.preparer_fiche_pdf(self.conn, self.admin, m)
        donnees_pdf = open(chemin, "rb").read()
        self.assertTrue(donnees_pdf.startswith(b"%PDF-"))
        self.assertGreater(len(donnees_pdf), 1500)
        self.assertIn("AGENT_FICHE_IMPRIMEE", self.actions_journal())

    def test_fiche_pdf_avec_beaucoup_de_documents_et_textes_longs(self):
        m = self.agent(adresse="Avenue très très longue " * 8, fonction="Enseignant de mathématiques et de physique")
        for i in range(11):
            personnel.ajouter_document(self.conn, self.admin, m, "Autre document", self.fichier(f"scan_{i}_" + "x" * 90 + ".pdf", PDF))
        self.assertTrue(open(personnel.preparer_fiche_pdf(self.conn, self.admin, m), "rb").read().startswith(b"%PDF-"))

    # ---------------------------------------------------------- droits
    def test_sans_droit_rien_n_est_possible(self):
        m = self.agent()
        d = self.fichier("d.pdf", PDF)
        self.assertFalse(personnel.peut(self.conn, self.sec, "LECTURE"))
        for appel in (lambda: personnel.rechercher(self.conn, self.sec),
                      lambda: personnel.charger_agent(self.conn, self.sec, m),
                      lambda: personnel.enregistrer_agent(self.conn, self.sec, saisie()),
                      lambda: personnel.modifier_agent(self.conn, self.sec, m, saisie()),
                      lambda: personnel.changer_activite(self.conn, self.sec, m, False),
                      lambda: personnel.ajouter_document(self.conn, self.sec, m, "Diplôme", d),
                      lambda: personnel.preparer_fiche_pdf(self.conn, self.sec, m)):
            with self.assertRaises(PermissionError):
                appel()

    def test_chaque_droit_ouvre_seulement_son_operation(self):
        m = self.agent()
        d = self.fichier("d.pdf", PDF)
        self.donner("LECTURE")
        self.assertEqual(len(personnel.rechercher(self.conn, self.sec)), 1)
        personnel.preparer_fiche_pdf(self.conn, self.sec, m)
        for appel in (lambda: personnel.enregistrer_agent(self.conn, self.sec, saisie(nom="X")),
                      lambda: personnel.modifier_agent(self.conn, self.sec, m, saisie()),
                      lambda: personnel.ajouter_document(self.conn, self.sec, m, "Diplôme", d)):
            with self.assertRaises(PermissionError):
                appel()
        self.donner("LECTURE", "AJOUT")
        id_doc = personnel.ajouter_document(self.conn, self.sec, m, "Diplôme", d)
        personnel.enregistrer_agent(self.conn, self.sec, saisie(nom="Nouveau"))
        with self.assertRaises(PermissionError):
            personnel.modifier_agent(self.conn, self.sec, m, saisie())
        with self.assertRaises(PermissionError):
            personnel.supprimer_document(self.conn, self.sec, id_doc)
        self.donner("LECTURE", "MODIFICATION")
        personnel.modifier_agent(self.conn, self.sec, m, saisie(adresse="Nouvelle adresse"))
        personnel.changer_activite(self.conn, self.sec, m, False)
        self.donner("LECTURE", "SUPPRESSION")
        personnel.supprimer_document(self.conn, self.sec, id_doc)

    def test_droit_retire_effet_immediat(self):
        self.donner("LECTURE")
        personnel.rechercher(self.conn, self.sec)
        self.donner()
        with self.assertRaises(PermissionError):
            personnel.rechercher(self.conn, self.sec)

    # ---------------------------------------------------------- base et journal
    def test_la_structure_est_a_jour_et_le_journal_reste_valide(self):
        self.assertFalse(migrations.analyser(self.conn).a_faire)
        self.agent()
        self.assertEqual(database.verifier_journal(self.conn), (True, None))

    def test_le_journal_ne_contient_jamais_le_contenu_des_documents(self):
        m = self.agent()
        personnel.ajouter_document(self.conn, self.admin, m, "Diplôme", self.fichier("d.pdf", PDF))
        for l in self.conn.execute("SELECT DETAIL FROM JOURNAL"):
            self.assertNotIn("%PDF", l["DETAIL"])


if __name__ == "__main__":
    unittest.main()
