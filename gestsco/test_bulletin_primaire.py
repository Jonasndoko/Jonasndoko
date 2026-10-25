"""Tests du bulletin du primaire (bulletin_primaire_pdf.py) : correspondance cours/branches, contenu du PDF, un bulletin par élève.
Lancer :  python -m unittest test_bulletin_primaire"""
import os
import tempfile
import unittest

os.environ.setdefault("CSF_DATA_DIR", tempfile.mkdtemp())

import bulletin_primaire_pdf as bp   # noqa: E402
import bulletins                     # noqa: E402
import cours                         # noqa: E402
import notes                         # noqa: E402
import personnel                    # noqa: E402
import security                     # noqa: E402
import test_notes as tb             # noqa: E402

NOMS_COURS = ["Grammaire et Conjugaison Expression", "Lecture (langues congolaises)", "Orale & Vocabulaire", "Orthographe et rédaction",
              "Orthographe", "Lecture", "Elocution et récitation", "Phraséologie écrite et rédaction", "Compréhension orale - Vocabulaire",
              "Analyse - Conjugaison - Grammaire", "Anatomie - botanique", "Formes géométriques", "Informatique / Technologie",
              "Mesures des grandeurs", "Opérations", "Physique / zoologie", "Numération", "Problèmes", "Education à la vie",
              "Education civique et morale", "Education à la santé et à l'environnement", "Géographie", "Histoire", "Art plastique",
              "Art dramatique", "Initiation au travail productif", "Education physique et sportive", "Religion"]


class TestBulletinPrimaire(tb.Base):
    """Une classe du primaire (5ème A) dont les cours portent les noms des branches du modèle, 2 élèves, calendrier en 3 trimestres."""
    def setUp(self):
        super().setUp()
        c = self.conn
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRI', 'Primaire', 'PRIMAIRE')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('5ème A', 'PRI', '5ème', 'A')")
        self.c6 = c.execute("SELECT N_CLASSE FROM CLASSE WHERE DESI_CLASSE = '5ème A'").fetchone()[0]
        for n in NOMS_COURS:
            cours.ajouter_cours(c, self.admin, {"libelle": n, "code_niveau": "PRI", "heures_semaine": "2"})
        cours.ouvrir_cours(c, self.admin, self.annee, self.c6)
        cours.generer_structure_standard(c, self.admin, self.annee, "PRIMAIRE")
        self.pers6 = [r[0] for r in c.execute("SELECT P.ID_PER FROM PERIODE_SCO P JOIN SEMESTRE_SCO S ON S.ID_SEM = P.ID_SEM "
                                              "WHERE S.SECTION = 'PRIMAIRE' ORDER BY P.DATE_DEBUT")]
        self.m3 = personnel.enregistrer_agent(c, self.admin, tb.agent(nom="lumbala", prenom="eric"))["matricule"]
        self.p3 = notes.creer_compte_professeur(c, self.admin, self.m3)
        self.s3 = security.authentifier(c, self.p3["login"], self.p3["mdp_temporaire"]).session
        with c:
            for m, nom in (("0201/26", "Bope"), ("0202/26", "Ilunga")):
                c.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES (?,?,?,?,?)", (m, nom, "X", "Y", "F"))
                c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, m, self.c6))
        bulletins.designer_titulaire(c, self.admin, self.annee, self.c6, self.m3)

    def remplir(self):
        ids = [r[0] for r in self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c6,))]
        for per in self.pers6:
            for cc in ids:
                notes.definir_maximum(self.conn, self.s3, cc, per, 10)
                notes.enregistrer_points(self.conn, self.s3, cc, per, {"0201/26": "8", "0202/26": "5"})
        return ids

    def test_les_28_branches_du_modele_trouvent_leur_cours(self):
        calc = bulletins.calculer(self.conn, self.annee, self.c6)
        corr = bp.correspondance(calc)
        self.assertEqual(len(corr), 28)
        self.assertEqual(len(set(corr.values())), 28)                      # un cours ne sert qu'une branche
        lecture_congo = corr[("DOMAINE DES LANGUES", "LANGUES CONGOLAISES", "Lecture")]
        lecture_fr = corr[("DOMAINE DES LANGUES", "FRANÇAIS", "Lecture")]
        self.assertNotEqual(lecture_congo, lecture_fr)
        noms = {c["id_cc"]: c["libelle"] for c in calc["cours"]}
        self.assertEqual(noms[lecture_congo], "Lecture (langues congolaises)")
        self.assertEqual(noms[lecture_fr], "Lecture")

    def test_maxima_du_modele(self):
        total = sum(mx for _d, gs in bp.BRANCHES for _t, ls in gs for _l, mx, _a in ls)
        self.assertEqual(total, 310)
        self.assertEqual(12 * total, 3720)

    def test_pdf_un_bulletin_par_eleve(self):
        self.remplir()
        calc = bulletins.calculer(self.conn, self.annee, self.c6)
        pdf = bp.bulletins(calc, calc["eleves"])
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertEqual(pdf.count(b"/Type /Page "), 2)
        for mot in (b"REPUBLIQUE DEMOCRATIQUE DU CONGO", b"PREMIER TRIMESTRE", b"POURCENTAGE", b"Maxima g", b"IGE/P.S/003"):
            self.assertIn(mot, pdf)

    def test_mise_en_page_conforme_au_modele(self):
        """En-tête centré sur l'axe de la feuille, cases du modèle (27 / 9 / 13), cadre de la feuille, colonnes aux largeurs du modèle."""
        import re
        self.remplir()
        calc = bulletins.calculer(self.conn, self.annee, self.c6)
        page = bp._page(calc, calc["eleves"][0], bp.correspondance(calc), bp.parametres())
        for texte in ("REPUBLIQUE DEMOCRATIQUE DU CONGO", "MINISTERE DE L'ENSEIGNEMENT PRIMAIRE, SECONDAIRE", "ET TECHNIQUE"):
            op = next(o for o in page.ops if o.endswith(f"({texte}) Tj ET"))
            taille = float(re.search(r"/F5 ([\d.]+) Tf", op).group(1))
            x = float(re.search(r"Tc ([\d.]+) ", op).group(1))
            self.assertAlmostEqual(x + bp._largeur(texte, "F5", taille) / 2, bp.CENTRE, delta=0.6)       # centré, quelle que soit la ligne
            self.assertEqual(taille, 11)                                                                    # même corps sur les trois lignes
        cases = [o for o in page.ops if o.endswith(" re S") and o.startswith("0.6 w")]
        self.assertEqual(len(cases), 27 + 9 + 13)
        larg = [c[2] for c in bp.COLS]
        self.assertAlmostEqual(sum(larg), bp.D - bp.G, places=6)
        self.assertLess(larg[0] / (bp.D - bp.G), 0.14)                                                     # colonne des branches étroite comme sur le modèle

    def test_document_pdf_du_titulaire_utilise_le_modele_du_primaire(self):
        self.remplir()
        octets, nom = bulletins.document_pdf(self.conn, self.s3, "bulletins", self.annee, self.c6, "A")
        self.assertIn(b"DEUXIEME TRIMESTRE", octets)
        self.assertTrue(nom.endswith(".pdf"))

    def test_le_secondaire_garde_son_bulletin(self):
        calc = bulletins.calculer(self.conn, self.annee, self.c7)
        self.assertFalse(calc["classe"]["primaire"])


if __name__ == "__main__":
    unittest.main()
