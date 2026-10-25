"""Tests du Secrétariat > Archives scolaires : classer et retrouver bulletins, dossiers d'anciens élèves et documents d'années précédentes.
Lancer :  python -m unittest test_archives_scolaires"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()
os.environ["GESTISC_SANS_APP"] = "1"

import app_web                 # noqa: E402
import archives_scolaires as ar    # noqa: E402
import config                  # noqa: E402
import droits                  # noqa: E402
import security                # noqa: E402
from archives_scolaires import ErreurArchives   # noqa: E402
from test_notes import MDP                      # noqa: E402
from test_prefecture_v57 import Fixture         # noqa: E402

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def journal(conn, action):
    return [l["DETAIL"] for l in conn.execute("SELECT DETAIL FROM JOURNAL WHERE ACTION = ? ORDER BY ID_LOG", (action,))]


class Fix(Fixture):
    def setUp(self):
        super().setUp()
        self.n = 0

    def classer(self, annee="2022-2023", categorie="DOSSIER", titre="Acte de naissance", matricule="0001/26", contenu=None, nom="acte.pdf", note="", s=None):
        self.n += 1
        contenu = contenu if contenu is not None else PDF + str(self.n).encode()
        return ar.classer(self.conn, s or self.secr, annee, categorie, titre, contenu, nom, matricule, note)

    def donner_suppression(self, session):
        d = droits.droits_utilisateur(self.conn, session.id_user) | {("dossier_eleve", "SUPPRESSION")}
        droits.remplacer_droits(self.conn, session.id_user, d)
        self.conn.commit()


class TestClasser(Fix):
    def test_classer_et_rouvrir_tel_quel(self):
        i = self.classer(contenu=PDF, note="reçu de l'ancienne école")
        octets, format_, nom = ar.ouvrir(self.conn, self.secr, i)
        self.assertEqual((octets, format_, nom), (PDF, "PDF", "acte.pdf"))
        self.assertEqual(ar.type_mime(format_), "application/pdf")
        self.assertEqual(len(journal(self.conn, "ARCHIVE_SCOLAIRE_CLASSEE")), 1)
        self.assertEqual(len(journal(self.conn, "ARCHIVE_SCOLAIRE_OUVERTE")), 1)

    def test_les_trois_formats_sont_reconnus_par_leur_contenu(self):
        for contenu, attendu in ((PDF, "PDF"), (JPEG, "JPEG"), (PNG, "PNG")):
            i = self.classer(contenu=contenu, nom="x.bin")
            self.assertEqual(ar.ouvrir(self.conn, self.secr, i)[1], attendu)

    def test_un_faux_pdf_est_refuse(self):
        for contenu in (b"MZ\x90\x00 programme", b"<html><script>alert(1)</script></html>", b""):
            with self.assertRaises(ErreurArchives):
                self.classer(contenu=contenu, nom="scan.pdf")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ARCHIVE_SCOLAIRE").fetchone()[0], 0)

    def test_taille_maximale(self):
        with self.assertRaises(ErreurArchives):
            self.classer(contenu=PDF + b"0" * config.TAILLE_MAX_ARCHIVE)

    def test_annee_libre_mais_bien_formee(self):
        self.classer(annee="2015-2016")                              # avant l'installation du logiciel : accepté
        for mauvaise in ("2015", "2015-2017", "20152016", "", "abcd-efgh"):
            with self.assertRaises(ErreurArchives):
                self.classer(annee=mauvaise)

    def test_categorie_et_titre_obligatoires(self):
        with self.assertRaises(ErreurArchives):
            self.classer(categorie="NIMPORTE")
        with self.assertRaises(ErreurArchives):
            self.classer(titre="   ")
        with self.assertRaises(ErreurArchives):
            self.classer(titre="x" * 121)

    def test_un_document_d_eleve_exige_un_eleve_du_secondaire(self):
        with self.assertRaises(ErreurArchives):
            self.classer(matricule="")
        with self.assertRaises(ErreurArchives):
            self.classer(matricule="9999/26")                          # inconnu
        with self.assertRaises(ErreurArchives):
            self.classer(matricule="0100/26")                          # élève du primaire : hors sujet

    def test_un_document_d_annee_n_a_pas_d_eleve(self):
        i = self.classer(categorie="DOCUMENT", titre="Procès-verbal de délibération", matricule="0001/26")
        self.assertIsNone(self.conn.execute("SELECT MATRICULE FROM ARCHIVE_SCOLAIRE WHERE ID_ARCH = ?", (i,)).fetchone()[0])

    def test_pas_deux_fois_le_meme_fichier(self):
        self.classer(contenu=PDF)
        with self.assertRaises(ErreurArchives):
            self.classer(contenu=PDF)
        self.classer(contenu=PDF, annee="2021-2022")                   # autre année : permis
        self.classer(contenu=PDF, matricule="0000/26")                 # autre élève : permis

    def test_nom_de_fichier_nettoye(self):
        i = self.classer(nom="C:\\Users\\x\\..\\scan.pdf")
        self.assertEqual(ar.ouvrir(self.conn, self.secr, i)[2], "scan.pdf")


class TestDroits(Fix):
    def test_lecture_sans_modification_ne_classe_pas(self):
        droits.remplacer_droits(self.conn, self.secr.id_user, {("dossier_eleve", "LECTURE")})
        self.conn.commit()
        self.assertEqual(ar.rechercher(self.conn, self.secr)["items"], [])
        with self.assertRaises(PermissionError):
            self.classer()
        self.assertFalse(ar.rechercher(self.conn, self.secr)["peut_classer"])

    def test_sans_lecture_rien(self):
        i = self.classer()
        for autre in (self.dire, self.dird):
            for f in (lambda s: ar.rechercher(self.conn, s), lambda s: ar.dossier(self.conn, s, "0001/26"), lambda s: ar.ouvrir(self.conn, s, i),
                      lambda s: ar.classer(self.conn, s, "2022-2023", "DOSSIER", "t", PDF, "a.pdf", "0001/26")):
                with self.assertRaises(PermissionError):
                    f(autre)

    def test_retirer_demande_le_droit_suppression(self):
        i = self.classer()
        with self.assertRaises(PermissionError):
            ar.retirer(self.conn, self.secr, i, "erreur")
        self.donner_suppression(self.secr)
        ar.retirer(self.conn, self.secr, i, "erreur")

    def test_un_compte_sans_la_section_secondaire_est_refuse(self):
        i = self.classer()
        security.creer_utilisateur(self.conn, "secr2", "Secr Deux", "SECRETAIRE", MDP)
        s2 = security.authentifier(self.conn, "secr2", MDP).session
        self.conn.execute("INSERT INTO SECTION_UTILISATEUR (ID_USER, SECTION) VALUES (?, 'PRIMAIRE')", (s2.id_user,))
        self.conn.commit()
        with self.assertRaises(PermissionError):
            ar.rechercher(self.conn, s2)
        with self.assertRaises(PermissionError):
            ar.ouvrir(self.conn, s2, i)


class TestRetrait(Fix):
    def test_le_retrait_masque_mais_conserve_le_fichier(self):
        self.donner_suppression(self.secr)
        i = self.classer()
        with self.assertRaises(ErreurArchives):
            ar.retirer(self.conn, self.secr, i, "  ")                  # motif obligatoire
        ar.retirer(self.conn, self.secr, i, "Classé au mauvais élève")
        self.assertEqual(ar.rechercher(self.conn, self.secr)["items"], [])
        self.assertEqual(ar.dossier(self.conn, self.secr, "0001/26")["items"], [])
        r = ar.rechercher(self.conn, self.secr, retires=True)
        self.assertEqual([(x["retire"], x["motif_retrait"]) for x in r["items"]], [(True, "Classé au mauvais élève")])
        self.assertEqual(ar.ouvrir(self.conn, self.secr, i)[0][:5], b"%PDF-")          # le fichier est toujours là
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ARCHIVE_SCOLAIRE").fetchone()[0], 1)
        with self.assertRaises(ErreurArchives):
            ar.retirer(self.conn, self.secr, i, "encore")
        self.assertEqual(len(journal(self.conn, "ARCHIVE_SCOLAIRE_RETIREE")), 1)

    def test_apres_un_retrait_le_meme_fichier_peut_etre_reclasse(self):
        self.donner_suppression(self.secr)
        i = self.classer(contenu=PDF)
        ar.retirer(self.conn, self.secr, i, "erreur")
        self.classer(contenu=PDF, matricule="0000/26")
        self.classer(contenu=PDF)
        self.assertEqual(len(ar.rechercher(self.conn, self.secr)["items"]), 2)


class TestRecherche(Fix):
    def setUp(self):
        super().setUp()
        self.a = self.classer("2022-2023", "DOSSIER", "Acte de naissance", "0001/26")
        self.b = self.classer("2023-2024", "BULLETIN", "Bulletin 5ème", "0001/26")
        self.c = self.classer("2022-2023", "BULLETIN", "Bulletin 4ème", "0000/26")
        self.d = self.classer("2022-2023", "DOCUMENT", "Liste générale des élèves", "")

    def titres(self, **kw):
        return sorted(x["titre"] for x in ar.rechercher(self.conn, self.secr, **kw)["items"])

    def test_sans_filtre_tout_est_liste(self):
        self.assertEqual(len(ar.rechercher(self.conn, self.secr)["items"]), 4)

    def test_par_eleve(self):
        self.assertEqual(self.titres(texte="0001/26"), ["Acte de naissance", "Bulletin 5ème"])
        self.assertEqual(self.titres(texte="Amisi"), ["Acte de naissance", "Bulletin 5ème"])              # 0001/26 = Amisi
        self.assertEqual(self.titres(texte="kasongo"), ["Bulletin 4ème"])
        self.assertEqual(self.titres(texte="inconnu-total"), [])

    def test_par_annee(self):
        self.assertEqual(self.titres(annee="2023-2024"), ["Bulletin 5ème"])
        self.assertEqual(len(self.titres(annee="2022-2023")), 3)
        self.assertEqual(self.titres(annee="2022-2023", texte="Amisi"), ["Acte de naissance"])          # élève ET année

    def test_par_type(self):
        self.assertEqual(self.titres(genre="BULLETIN"), ["Bulletin 4ème", "Bulletin 5ème"])
        self.assertEqual(self.titres(genre="DOCUMENT"), ["Liste générale des élèves"])
        self.assertEqual(len(self.titres(genre="valeur-folle")), 4)                                      # filtre invalide ignoré

    def test_document_sans_eleve_retrouve_par_son_titre(self):
        self.assertEqual(self.titres(texte="Liste générale"), ["Liste générale des élèves"])

    def test_resultat_trie_par_annee_recente(self):
        annees = [x["annee"] for x in ar.rechercher(self.conn, self.secr)["items"]]
        self.assertEqual(annees, sorted(annees, reverse=True))

    def test_eleves_trouves_avec_compte_de_documents(self):
        r = ar.rechercher(self.conn, self.secr, "Amisi")
        self.assertEqual([(e["matricule"], e["nb_documents"]) for e in r["eleves"]], [("0001/26", 2)])
        self.assertNotIn("0100/26", [e["matricule"] for e in ar.rechercher(self.conn, self.secr, "Petit")["eleves"]])     # primaire

    def test_anciens_eleves(self):
        with self.conn:
            self.conn.execute("UPDATE ELEVE SET ACTIF = 0 WHERE MATRICULE = '0000/26'")                  # désactivé
            self.conn.execute("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES ('2025-2026', 0)")
            self.conn.execute("INSERT INTO ELEVE (MATRICULE, NOM) VALUES ('0050/25', 'Ancien')")
            self.conn.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES ('2025-2026', '0050/25', ?)", (self.c7,))   # plus inscrit cette année
        self.classer("2025-2026", "DOSSIER", "Fiche d'inscription", "0050/25")
        r = ar.rechercher(self.conn, self.secr, anciens=True)
        self.assertEqual(sorted(x["titre"] for x in r["items"]), ["Bulletin 4ème", "Fiche d'inscription"])    # 0000 désactivé, 0050 non réinscrit
        r = ar.rechercher(self.conn, self.secr, "Amisi", anciens=True)
        self.assertEqual((r["eleves"], r["items"]), ([], []))                                                  # Amisi est inscrit : pas un ancien
        r = ar.rechercher(self.conn, self.secr, "Ancien")
        self.assertTrue(r["eleves"][0]["ancien"])
        self.assertFalse(ar.rechercher(self.conn, self.secr, "Amisi")["eleves"][0]["ancien"])
        self.assertTrue(ar.dossier(self.conn, self.secr, "0050/25")["ancien"])

    def test_primaire_jamais_present(self):
        with self.conn:      # même une ligne mal rangée ne sort pas : la recherche ne passe que par les élèves du secondaire
            self.conn.execute("INSERT INTO ARCHIVE_SCOLAIRE (ANNEESCO, MATRICULE, CATEGORIE, TITRE, NOM_FICHIER, FORMAT, TAILLE, EMPREINTE, CONTENU, "
                              "CLASSE_LE, CLASSE_PAR) VALUES ('2022-2023', '0100/26', 'DOSSIER', 'Intrus', 'x.pdf', 'PDF', 5, 'e', ?, '2026-01-01T10:00:00', 'x')", (PDF,))
        self.assertNotIn("Intrus", self.titres(texte="0100/26") + self.titres())

    def test_chaque_recherche_est_journalisee(self):
        ar.rechercher(self.conn, self.secr, "Amisi", "2022-2023")
        self.assertEqual(len(journal(self.conn, "ARCHIVES_SCOLAIRES_CONSULTEES")), 1)
        self.assertIn("Amisi", journal(self.conn, "ARCHIVES_SCOLAIRES_CONSULTEES")[0])


class TestDossierEtSources(Fix):
    def test_dossier_d_un_eleve_avec_parcours(self):
        self.classer(matricule="0001/26")
        d = ar.dossier(self.conn, self.secr, "0001/26")
        self.assertEqual(d["eleve"]["matricule"], "0001/26")
        self.assertEqual([(p["annee"], p["classe"]) for p in d["parcours"]], [(self.annee, "7ème A")])
        self.assertEqual(len(d["items"]), 1)
        self.assertFalse(d["ancien"])
        self.assertEqual(len(journal(self.conn, "DOSSIER_ARCHIVE_CONSULTE")), 1)
        with self.assertRaises(ErreurArchives):
            ar.dossier(self.conn, self.secr, "0100/26")

    def test_documents_officiels_signes_sont_retrouves_et_rouvrables(self):
        import documents_officiels
        t = documents_officiels.types_disponibles()[0]["cle"]
        i = documents_officiels.preparer(self.conn, self.prefet, self.annee, "0001/26", t)
        brouillon = ar.rechercher(self.conn, self.secr, "Amisi")
        self.assertEqual([x for x in brouillon["items"] if x["source"] == "officiel"], [])               # un brouillon n'apparaît pas
        documents_officiels.soumettre(self.conn, self.prefet, i, config.APPROBATIONS_DOCUMENT[0][0], "")
        documents_officiels.signer(self.conn, self.prefet, i, "Le Préfet")
        r = ar.rechercher(self.conn, self.secr, "Amisi")
        officiels = [x for x in r["items"] if x["source"] == "officiel"]
        self.assertEqual(len(officiels), 1)
        octets, nom = ar.ouvrir_document_officiel(self.conn, self.secr, officiels[0]["id"])
        self.assertTrue(octets.startswith(b"%PDF"))
        self.assertEqual(ar.rechercher(self.conn, self.secr, "Kasongo")["resume"]["officiels"], 0)       # pas son document
        with self.assertRaises(ErreurArchives):
            ar.ouvrir_document_officiel(self.conn, self.secr, 9999)
        # un document annulé ne se rouvre plus ici
        documents_officiels.annuler(self.conn, self.prefet, i, "erreur de saisie")
        with self.assertRaises(ErreurArchives):
            ar.ouvrir_document_officiel(self.conn, self.secr, i)

    def test_copies_de_bulletins_archivees_retrouvees_par_la_classe_de_l_eleve(self):
        with self.conn:
            self.conn.execute("INSERT INTO ARCHIVE_BULLETIN (ANNEESCO, N_CLASSE, CLE, NB_BULLETINS, NOM_FICHIER, CONTENU, TAILLE, ARCHIVE_LE, ARCHIVE_PAR) "
                              "VALUES (?,?,?,?,?,?,?,?,?)", (self.annee, self.c7, "A", 3, "bulletins_7A.pdf", PDF, len(PDF), "2026-12-20T09:00:00", "secr1"))
        r = ar.rechercher(self.conn, self.secr, "Amisi")                       # Amisi est en 7ème A cette année-là
        b = [x for x in r["items"] if x["source"] == "bulletin"]
        self.assertEqual((len(b), b[0]["matricule"], b[0]["classe"]), (1, "0001/26", "7ème A"))
        self.assertEqual([x for x in ar.rechercher(self.conn, self.secr, "Autre")["items"] if x["source"] == "bulletin"], [])   # 0009 est en 8ème
        octets, nom = ar.ouvrir_bulletins_classe(self.conn, self.secr, b[0]["id"])
        self.assertEqual((octets, nom), (PDF, "bulletins_7A.pdf"))
        self.assertEqual(len(ar.rechercher(self.conn, self.secr, genre=ar.GENRE_BULLETIN_CLASSE)["items"]), 1)


class TestWeb(Fix):
    def setUp(self):
        super().setUp()
        self.app = app_web.creer_app(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.cl = self.app.test_client()
        self.assertEqual(self.cl.post("/connexion", data={"login": "secr1", "mdp": MDP}).status_code, 302)
        self.base = "/m/etudes_discipline/dossier_eleve"

    def poster(self, donnees, fichier=(PDF, "scan.pdf")):
        from io import BytesIO
        d = dict(donnees)
        if fichier:
            d["fichier"] = (BytesIO(fichier[0]), fichier[1])
        return self.cl.post(self.base + "/archives/classer", data=d, content_type="multipart/form-data")

    def champs(self, **kw):
        c = {"annee": "2022-2023", "categorie": "DOSSIER", "titre": "Acte de naissance", "matricule": "0001/26", "note": ""}
        c.update(kw)
        return c

    def test_onglet_visible_et_page_de_recherche(self):
        self.assertIn("Archives scolaires", self.cl.get(self.base).get_data(as_text=True))
        page = self.cl.get(self.base + "?f=archives").get_data(as_text=True)
        self.assertIn("Classer un document", page)
        self.assertIn("Aucun document ne correspond", page)

    def test_classer_puis_retrouver_puis_ouvrir(self):
        r = self.poster(self.champs())
        self.assertEqual(r.status_code, 302)
        page = self.cl.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Document classé dans les archives", page)
        self.assertIn("Acte de naissance", page)
        page = self.cl.get(self.base + "?f=archives&q=Amisi&annee=2022-2023").get_data(as_text=True)
        self.assertIn("Acte de naissance", page)
        self.assertIn("Ouvrir le dossier", page)
        self.assertNotIn("Acte de naissance", self.cl.get(self.base + "?f=archives&annee=2019-2020").get_data(as_text=True))
        i = self.conn.execute("SELECT ID_ARCH FROM ARCHIVE_SCOLAIRE").fetchone()[0]
        r = self.cl.get(f"{self.base}/archives/classe/{i}")
        self.assertEqual((r.status_code, r.mimetype, r.data), (200, "application/pdf", PDF))
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    def test_image_servie_avec_son_vrai_type(self):
        self.poster(self.champs(titre="Photo"), (PNG, "scan.pdf"))                 # extension trompeuse : le contenu décide
        i = self.conn.execute("SELECT ID_ARCH FROM ARCHIVE_SCOLAIRE").fetchone()[0]
        self.assertEqual(self.cl.get(f"{self.base}/archives/classe/{i}").mimetype, "image/png")

    def test_erreur_reaffiche_le_formulaire_avec_les_valeurs(self):
        r = self.poster(self.champs(titre="Mon titre"), (b"pas un pdf", "x.pdf"))
        self.assertEqual(r.status_code, 400)
        page = r.get_data(as_text=True)
        self.assertIn("Format non accepté", page)
        self.assertIn("Mon titre", page)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ARCHIVE_SCOLAIRE").fetchone()[0], 0)
        r = self.poster(self.champs(), None)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Choisissez le fichier", r.get_data(as_text=True))

    def test_fichier_trop_gros(self):
        r = self.poster(self.champs(), (PDF + b"0" * (config.TAILLE_MAX_ARCHIVE + 300_000), "gros.pdf"))
        self.assertEqual(r.status_code, 413)
        self.assertIn("trop volumineux", r.get_data(as_text=True))

    def test_dossier_de_l_eleve_et_formulaire_prerempli(self):
        self.poster(self.champs())
        page = self.cl.get(self.base + "?f=archives&eleve=0001/26").get_data(as_text=True)
        self.assertIn("Amisi", page)
        self.assertIn("Parcours", page)
        self.assertIn("Acte de naissance", page)
        page = self.cl.get(self.base + "?f=archives&vue=classer&eleve=0001/26").get_data(as_text=True)
        self.assertIn('value="0001/26"', page)

    def test_retirer_demande_le_droit_puis_motif(self):
        self.poster(self.champs())
        i = self.conn.execute("SELECT ID_ARCH FROM ARCHIVE_SCOLAIRE").fetchone()[0]
        self.assertEqual(self.cl.post(self.base + "/archives/retirer", data={"id": i, "motif": "erreur", "f": "archives"}).status_code, 403)
        self.donner_suppression(self.secr)
        r = self.cl.post(self.base + "/archives/retirer", data={"id": i, "motif": " ", "f": "archives"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("motif", r.get_data(as_text=True))
        r = self.cl.post(self.base + "/archives/retirer", data={"id": i, "motif": "doublon", "f": "archives"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("Acte de naissance", self.cl.get(self.base + "?f=archives").get_data(as_text=True))
        self.assertIn("Retiré du classement", self.cl.get(self.base + "?f=archives&retires=1").get_data(as_text=True))

    def test_un_autre_poste_n_a_pas_acces(self):
        self.poster(self.champs())
        i = self.conn.execute("SELECT ID_ARCH FROM ARCHIVE_SCOLAIRE").fetchone()[0]
        cl = self.app.test_client()
        cl.post("/connexion", data={"login": "dird1", "mdp": MDP})
        self.assertEqual(cl.get(self.base + "?f=archives").status_code, 403)
        self.assertEqual(cl.get(f"{self.base}/archives/classe/{i}").status_code, 403)
        self.assertEqual(cl.get(f"{self.base}/archives/inconnu/{i}").status_code, 403)

    def test_source_inconnue_et_document_introuvable(self):
        self.assertEqual(self.cl.get(f"{self.base}/archives/inconnu/1").status_code, 404)
        self.assertEqual(self.cl.get(f"{self.base}/archives/classe/9999").status_code, 404)

    def test_les_autres_onglets_fonctionnent_toujours(self):
        for f in ("dossiers", "bulletins"):
            self.assertEqual(self.cl.get(f"{self.base}?f={f}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
