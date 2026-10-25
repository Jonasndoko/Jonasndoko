"""Tests des sections de l'école (sections.py) : primaire, et secondaire et humanitaire, dans un seul logiciel.
Droits par section (paiement, inscription, carte, contrôle), pas de carte au primaire, titulaire = unique enseignant au primaire.
Lancer :  python test_sections.py"""
import os
import tempfile
import unittest

os.environ["CSF_DATA_DIR"] = tempfile.mkdtemp()

import audit              # noqa: E402
import bulletins          # noqa: E402
import carte              # noqa: E402
import config             # noqa: E402
import controle           # noqa: E402
import cours              # noqa: E402
import database           # noqa: E402
import demo               # noqa: E402
import donnees            # noqa: E402
import inscription        # noqa: E402
import migrations         # noqa: E402
import modules            # noqa: E402
import notes              # noqa: E402
import paiements          # noqa: E402
import personnel          # noqa: E402
import referentiels       # noqa: E402
import sections           # noqa: E402
import security           # noqa: E402
import test_bulletins as tb   # noqa: E402

AN = demo.ANNEE_COURANTE
MDP = "Tr@vail-Amour-2026"


class Fondation(unittest.TestCase):
    """Données de démonstration (tout en secondaire) + une classe PRIMAIRE (6ème A) et un élève du primaire."""
    def setUp(self):
        self.conn = c = database.connecter(":memory:")
        self.login, self.mdp = demo.semer(c)
        self.perc = security.authentifier(c, self.login, self.mdp).session
        security.creer_utilisateur(c, "admin1", "Alice", "ADMINISTRATEUR", MDP)
        self.admin = security.authentifier(c, "admin1", MDP).session
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('N6', '6ème année primaire', 'PRIMAIRE')")
            c.execute("INSERT INTO CLASSE (N_CLASSE, DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES (60, '6ème A', 'N6', '6ème', 'A')")
            c.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES ('CSF-0100', 'PETIT', 'ELEVE', 'Paul', 'M')")
            c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?, 'CSF-0100', 60)", (AN,))

    def limiter(self, *ouvertes):
        id_user = self.perc.id_user
        sections.definir_sections(self.conn, self.admin, id_user, set(ouvertes))


class Droits(Fondation):
    def test_par_defaut_toutes_les_sections_et_l_admin_voit_tout(self):
        self.assertEqual(sections.sections_de(self.conn, self.perc), sections.TOUTES)
        self.assertEqual(sections.sections_de(self.conn, self.admin), sections.TOUTES)
        self.assertEqual(sections.section_de_classe(self.conn, 60), "PRIMAIRE")
        self.assertEqual(sections.section_de_classe(self.conn, 1), "SECONDAIRE")
        self.assertEqual(sections.section_de_eleve(self.conn, "CSF-0100"), "PRIMAIRE")

    def test_definir_les_sections_d_un_compte(self):
        self.limiter("SECONDAIRE")
        self.assertEqual(sections.sections_de(self.conn, self.perc), frozenset({"SECONDAIRE"}))
        self.assertEqual(sections.resume(self.conn, self.perc.id_user), "Secondaire et humanitaire")
        self.limiter("PRIMAIRE", "SECONDAIRE")                                      # les deux : plus de restriction
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM SECTION_UTILISATEUR").fetchone()[0], 0)
        self.assertEqual(sections.resume(self.conn, self.perc.id_user), "Toutes les sections")
        self.assertTrue(any(l["ACTION"] == "SECTIONS_UTILISATEUR_MODIFIEES" for l in self.conn.execute("SELECT * FROM JOURNAL")))
        self.assertIn("SECTIONS_UTILISATEUR_MODIFIEES", audit.ACTIONS)

    def test_seul_l_administrateur_regle_les_sections_et_une_section_au_moins(self):
        with self.assertRaises(PermissionError):
            sections.definir_sections(self.conn, self.perc, self.perc.id_user, {"PRIMAIRE"})
        with self.assertRaises(sections.ErreurSection):
            sections.definir_sections(self.conn, self.admin, self.perc.id_user, set())
        with self.assertRaises(sections.ErreurSection):
            sections.definir_sections(self.conn, self.admin, 9999, {"PRIMAIRE"})

    def test_la_migration_range_les_anciens_niveaux(self):
        with self.conn:
            self.conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('PRIM', 'Primaire')")
            self.conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('P5', 'Ecole primaire 5')")
            self.conn.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES ('HUM', 'Humanités')")
        migrations._mig_sections(self.conn)
        sec = dict(self.conn.execute("SELECT CODE_NIVEAU, SECTION FROM NIVEAU").fetchall())
        self.assertEqual((sec["PRIM"], sec["P5"], sec["HUM"], sec["N7"]), ("PRIMAIRE", "PRIMAIRE", "SECONDAIRE", "SECONDAIRE"))
        self.assertGreaterEqual(migrations.VERSION_SCHEMA, 12)

    def test_le_niveau_se_cree_avec_sa_section(self):
        t = referentiels.TABLES["niveaux"]
        self.assertIn("SECTION", [c.nom for c in t.champs])
        self.assertEqual({v for v, _ in next(c for c in t.champs if c.nom == "SECTION").choix}, {"PRIMAIRE", "SECONDAIRE"})


class Paiements(Fondation):
    def test_le_percepteur_du_primaire_paie_au_primaire_seulement(self):
        self.limiter("PRIMAIRE")
        n = paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0100", AN, "INSC", 3000)
        self.assertTrue(n)
        with self.assertRaises(PermissionError):                                     # élève du secondaire : section fermée
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)

    def test_le_percepteur_du_secondaire_ne_paie_pas_au_primaire(self):
        self.limiter("SECONDAIRE")
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0100", AN, "INSC", 3000)
        self.assertTrue(paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000))

    def test_la_recherche_ne_propose_que_les_eleves_de_ses_sections(self):
        noms = lambda: [r["matricule"] for r in donnees.rechercher_eleves(self.conn, "CSF-", session=self.perc)]
        self.assertIn("CSF-0100", noms())
        self.limiter("SECONDAIRE")
        self.assertNotIn("CSF-0100", noms())
        self.assertIn("CSF-0004", noms())
        self.limiter("PRIMAIRE")
        self.assertEqual(noms(), ["CSF-0100"])

    def test_le_rapport_journalier_se_limite_aux_sections(self):
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0100", AN, "INSC", 3000)
        paiements.enregistrer_paiement(self.conn, self.perc, "CSF-0004", AN, "INSC", 3000)
        jour = __import__("datetime").datetime.now().date()
        tout = paiements.rapport_journalier(self.conn, self.perc, jour)["nb_recus"]
        self.limiter("PRIMAIRE")
        self.assertEqual(paiements.rapport_journalier(self.conn, self.perc, jour)["nb_recus"], 1)
        self.limiter("SECONDAIRE")
        self.assertEqual(paiements.rapport_journalier(self.conn, self.perc, jour)["nb_recus"], tout - 1)

    def test_les_frais_d_inscription_d_un_candidat_suivent_la_section(self):
        with self.conn:
            self.conn.execute("UPDATE TYPE_FRAIS SET POUR_INSCRIPTION = 1 WHERE CODTF = 'INSC'")
        self.limiter("SECONDAIRE")
        with self.assertRaises(PermissionError):
            paiements.enregistrer_paiement_inscription(self.conn, self.perc, AN, 60, "INSC", 3000, "Candidat")
        self.assertTrue(paiements.enregistrer_paiement_inscription(self.conn, self.perc, AN, 1, "INSC", 3000, "Candidat"))


class InscriptionCarteControle(Fondation):
    def test_les_classes_proposees_suivent_les_sections(self):
        self.assertIn(60, [n for n, _ in inscription.classes_proposees(self.conn, self.perc)])
        self.limiter("SECONDAIRE")
        propo = [n for n, _ in inscription.classes_proposees(self.conn, self.perc)]
        self.assertNotIn(60, propo)
        self.assertIn(1, propo)
        self.assertIn(60, [n for n, _ in inscription.classes_proposees(self.conn)])         # sans session : toutes (usage interne)

    def test_pas_de_carte_au_primaire_meme_pour_l_administrateur(self):
        with self.assertRaises(PermissionError) as e:
            carte.fiche(self.conn, self.admin, "CSF-0100")
        self.assertIn("primaire", str(e.exception))
        with self.assertRaises(PermissionError):
            carte.enregistrer_photo(self.conn, self.admin, "CSF-0100", b"\xff\xd8\xff")
        self.assertEqual(carte.fiche(self.conn, self.admin, "CSF-0004")["matricule"], "CSF-0004")

    def test_le_module_carte_disparait_pour_un_compte_limite_au_primaire(self):
        with self.conn:
            self.conn.execute("INSERT INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'carte', 'LECTURE')", (self.perc.id_user,))
        self.assertIn("carte", modules.modules_ouverts(self.conn, self.perc))
        self.limiter("PRIMAIRE")
        self.assertNotIn("carte", modules.modules_ouverts(self.conn, self.perc))
        self.assertIn("carte", modules.modules_ouverts(self.conn, self.admin))

    def test_controle_numerique_et_liste_en_ordre(self):
        with self.conn:
            self.conn.execute("INSERT INTO DROIT (ID_USER, MODULE, DROIT) VALUES (?, 'controle', 'LECTURE')", (self.perc.id_user,))
        self.assertIn("6ème A", controle.liste_classes(self.conn, self.perc))
        self.limiter("SECONDAIRE")
        self.assertNotIn("6ème A", controle.liste_classes(self.conn, self.perc))
        with self.assertRaises(PermissionError):
            controle.controler_eleve(self.conn, self.perc, "CSF-0100")
        with self.assertRaises(controle.ErreurControle):
            controle.eleves_en_ordre(self.conn, self.perc, AN, "6ème A", None, "INSC")
        self.assertEqual(controle.controler_eleve(self.conn, self.perc, "CSF-0004")["matricule"], "CSF-0004")


class PrimaireTitulaireEnseignant(tb.Base):
    """Au primaire, le titulaire est l'unique enseignant : tous les cours de sa classe lui sont attribués, sans rien à autoriser."""
    def setUp(self):
        super().setUp()
        c = self.conn
        with c:
            c.execute("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU, SECTION) VALUES ('PRI', 'Primaire', 'PRIMAIRE')")
            c.execute("INSERT INTO CLASSE (DESI_CLASSE, CODE_NIVEAU, ANNEE_ETUDE, DIVISION) VALUES ('6ème A', 'PRI', '6ème', 'A')")
        self.c6 = c.execute("SELECT N_CLASSE FROM CLASSE WHERE DESI_CLASSE = '6ème A'").fetchone()[0]
        for n in ("Calcul", "Lecture", "Dessin"):
            cours.ajouter_cours(c, self.admin, {"libelle": n, "code_niveau": "PRI", "heures_semaine": "3"})
        cours.ouvrir_cours(c, self.admin, self.annee, self.c6)
        cours.generer_structure_standard(c, self.admin, self.annee, "PRIMAIRE")           # calendrier du primaire : 3 trimestres, 6 périodes
        self.sems6 = [r[0] for r in c.execute("SELECT ID_SEM FROM SEMESTRE_SCO WHERE SECTION = 'PRIMAIRE' ORDER BY DATE_DEBUT")]
        self.pers6 = [r[0] for r in c.execute("SELECT P.ID_PER FROM PERIODE_SCO P JOIN SEMESTRE_SCO S ON S.ID_SEM = P.ID_SEM "
                                              "WHERE S.SECTION = 'PRIMAIRE' ORDER BY P.DATE_DEBUT")]
        self.m3 = personnel.enregistrer_agent(c, self.admin, tb.agent(nom="lumbala", prenom="eric"))["matricule"]
        self.p3 = notes.creer_compte_professeur(c, self.admin, self.m3)
        self.s3 = security.authentifier(c, self.p3["login"], self.p3["mdp_temporaire"]).session
        with c:
            for m, nom in (("0201/26", "Bope"), ("0202/26", "Ilunga")):
                c.execute("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE) VALUES (?,?,?,?,?)", (m, nom, "X", "Y", "F"))
                c.execute("INSERT INTO INSCRIRE (ANNEESCO, MATRICULE, N_CLASSE) VALUES (?,?,?)", (self.annee, m, self.c6))

    def profs(self):
        return {l[0] for l in self.conn.execute("SELECT MATRICULE_PROF FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c6,))}

    def test_designer_le_titulaire_lui_donne_tous_les_cours(self):
        self.assertEqual(self.profs(), {None})
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        self.assertEqual(self.profs(), {self.m3})
        classes = notes.mes_classes(self.conn, self.s3)["classes"]
        self.assertEqual([k["designation"] for k in classes], ["6ème A"])
        self.assertEqual(len(classes[0]["cours"]), 3)
        self.assertEqual(bulletins.acces(self.conn, self.s3), {"titulaire": True, "enseigne": True})

    def test_aucun_autre_enseignant_au_primaire(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        cc = self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c6,)).fetchone()[0]
        with self.assertRaises(cours.ErreurCours) as e:
            cours.attribuer_professeur(self.conn, self.admin, [cc], self.m2)
        self.assertIn("unique enseignant", str(e.exception))
        with self.assertRaises(cours.ErreurCours):
            cours.attribuer_professeur(self.conn, self.admin, [cc], "")                   # pas de retrait non plus
        self.assertEqual(self.profs(), {self.m3})

    def test_un_nouveau_titulaire_reprend_les_cours_et_le_retrait_les_libere(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m2)
        self.assertEqual(self.profs(), {self.m2})
        bulletins.retirer_titulaire(self.conn, self.admin, self.annee, self.c6)
        self.assertEqual(self.profs(), {None})

    def test_un_cours_ouvert_plus_tard_va_au_titulaire(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        cours.ajouter_cours(self.conn, self.admin, {"libelle": "Chant", "code_niveau": "PRI", "heures_semaine": "1"})
        self.assertEqual(cours.ouvrir_cours(self.conn, self.admin, self.annee, self.c6), 1)
        self.assertEqual(self.profs(), {self.m3})

    def test_le_secondaire_ne_change_pas(self):
        self.assertEqual({l[0] for l in self.conn.execute("SELECT MATRICULE_PROF FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c7,))},
                         {self.m1, self.m2})
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c7, self.m2)
        self.assertEqual({l[0] for l in self.conn.execute("SELECT MATRICULE_PROF FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c7,))},
                         {self.m1, self.m2})

    def test_tout_est_ouvert_a_la_saisie_sans_autorisation(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM AUTORISATION_SAISIE WHERE N_CLASSE = ?", (self.c6,)).fetchone()[0], 0)
        self.assertEqual(notes.autorisees(self.conn, self.annee, self.c6), {f"P{i}" for i in self.pers6} | {f"X{i}" for i in self.sems6})
        cc = self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c6,)).fetchone()[0]
        notes.definir_maximum(self.conn, self.s3, cc, self.pers6[0], 10)
        notes.enregistrer_points(self.conn, self.s3, cc, self.pers6[0], {"0201/26": "9", "0202/26": "4"})
        r = bulletins.resultats(self.conn, self.s3, self.annee, self.c6, f"P{self.pers6[0]}")
        self.assertEqual([l["nom_complet"].split()[0] for l in r["lignes"]], ["Bope", "Ilunga"])
        f = bulletins.fiche_eleve(self.conn, self.s3, self.annee, self.c6, "0201/26")
        self.assertEqual(len(f["cours"]), 3)
        self.assertEqual(notes.autorisees(self.conn, self.annee, self.c7), {f"P{i}" for i in self.pers} | {f"X{i}" for i in self.sems})  # c7 : secondaire

    def test_le_titulaire_du_primaire_n_a_pas_d_autorisation_a_donner(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        a = bulletins.autorisations(self.conn, self.s3, self.annee, self.c6)
        self.assertTrue(a["primaire"])
        self.assertEqual(a["elements"], [])
        with self.assertRaises(bulletins.ErreurBulletins):
            bulletins.definir_autorisation(self.conn, self.s3, self.annee, self.c6, f"P{self.pers6[0]}", False)
        self.assertFalse(bulletins.autorisations(self.conn, self.s1, self.annee, self.c7)["primaire"])


class PrimaireTrimestres(PrimaireTitulaireEnseignant):
    """Le primaire n'a pas de semestres mais 3 trimestres de 2 périodes (6 périodes) ; le secondaire garde 2 semestres de 2 périodes."""
    def test_calendrier_du_primaire_et_du_secondaire_sont_separes(self):
        c = self.conn
        lib = lambda section: [r[0] for r in c.execute("SELECT LIBELLE FROM SEMESTRE_SCO WHERE SECTION = ? ORDER BY DATE_DEBUT", (section,))]
        self.assertEqual(lib("PRIMAIRE"), ["1er trimestre", "2ème trimestre", "3ème trimestre"])
        self.assertEqual(lib("SECONDAIRE"), ["1er semestre", "2ème semestre"])
        self.assertEqual((len(self.pers6), len(self.pers)), (6, 4))
        cal = cours.calendrier_annee(c, self.admin, self.annee, "PRIMAIRE")
        self.assertEqual([len(s["periodes"]) for s in cal["semestres"]], [2, 2, 2])
        self.assertEqual(len(cours.calendrier_annee(c, self.admin, self.annee)["semestres"]), 5)          # tous les calendriers

    def test_limites_par_section(self):
        with self.assertRaises(cours.ErreurCours) as e:
            cours.ajouter_semestre(self.conn, self.admin, self.annee, "4ème trimestre", "01/07/2027", "10/07/2027", "PRIMAIRE")
        self.assertIn("3 trimestres", str(e.exception))
        with self.assertRaises(cours.ErreurCours):
            cours.ajouter_semestre(self.conn, self.admin, self.annee, "3ème semestre", "01/07/2027", "10/07/2027", "SECONDAIRE")
        with self.assertRaises(cours.ErreurCours):
            cours.generer_structure_standard(self.conn, self.admin, self.annee, "PRIMAIRE")               # déjà fait

    def test_portees_du_calcul_suivent_la_section_de_la_classe(self):
        p6 = bulletins.calculer(self.conn, self.annee, self.c6)["portees"]
        p7 = bulletins.calculer(self.conn, self.annee, self.c7)["portees"]
        count = lambda ps, t: len([p for p in ps if p["type"] == t])
        self.assertEqual([count(p6, t) for t in ("periode", "examen", "semestre", "annee")], [6, 3, 3, 1])
        self.assertEqual([count(p7, t) for t in ("periode", "examen", "semestre", "annee")], [4, 2, 2, 1])
        self.assertEqual([p["libelle"] for p in p6 if p["type"] == "semestre"], ["1er trimestre", "2ème trimestre", "3ème trimestre"])

    def test_le_primaire_saisit_dans_ses_periodes_et_pas_dans_celles_du_secondaire(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        cc = self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ?", (self.c6,)).fetchone()[0]
        with self.assertRaises(notes.ErreurNotes):
            notes.definir_maximum(self.conn, self.s3, cc, self.pers[0], 10)                              # période du secondaire
        with self.assertRaises(notes.ErreurNotes):
            notes.definir_maximum(self.conn, self.s3, cc, f"X{self.sems[0]}", 10)                        # examen d'un semestre du secondaire
        notes.definir_maximum(self.conn, self.s3, cc, self.pers6[5], 10)                                 # 6ème période
        notes.definir_maximum(self.conn, self.s3, cc, f"X{self.sems6[2]}", 10)                           # examen du 3ème trimestre

    def test_ce_que_voit_le_titulaire_enseignant_du_primaire(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        k = notes.mes_classes(self.conn, self.s3)["classes"][0]
        self.assertEqual(k["section"], "PRIMAIRE")
        self.assertEqual([s["libelle"] for s in k["semestres"]], ["1er trimestre", "2ème trimestre", "3ème trimestre"])
        self.assertEqual(sum(len(s["periodes"]) for s in k["semestres"]), 6)
        b = bulletins.mes_classes(self.conn, self.s3)["classes"][0]
        self.assertEqual(len([p for p in b["portees"] if p["type"] == "periode"]), 6)
        self.assertEqual(b["portee_defaut"], "A")                                                          # rien saisi : la dernière
        k7 = notes.mes_classes(self.conn, self.s1)["classes"][0]
        self.assertEqual([s["libelle"] for s in k7["semestres"]], ["1er semestre", "2ème semestre"])

    def test_l_annee_du_primaire_additionne_les_6_periodes(self):
        bulletins.designer_titulaire(self.conn, self.admin, self.annee, self.c6, self.m3)
        ids = [r[0] for r in self.conn.execute("SELECT ID_CC FROM COURS_CLASSE WHERE N_CLASSE = ? ORDER BY ID_CC", (self.c6,))]
        for per in self.pers6:
            for cc in ids:
                notes.definir_maximum(self.conn, self.s3, cc, per, 10)
                notes.enregistrer_points(self.conn, self.s3, cc, per, {"0201/26": "8", "0202/26": "5"})
        r = bulletins.resultats(self.conn, self.s3, self.annee, self.c6, "A")
        bope = next(l for l in r["lignes"] if l["nom_complet"].startswith("Bope"))
        self.assertEqual((bope["obtenu"], bope["max"], bope["pct"]), (8 * 6 * 3, 10 * 6 * 3, 80.0))     # 6 périodes x 3 cours
        self.assertTrue(bope["reussite"])
        ilunga = next(l for l in r["lignes"] if l["nom_complet"].startswith("Ilunga"))
        self.assertEqual(ilunga["pct"], 50.0)
        r1 = bulletins.resultats(self.conn, self.s3, self.annee, self.c6, f"S{self.sems6[0]}")
        self.assertEqual(r1["lignes"][0]["max"], 10 * 2 * 3)                                             # un trimestre = 2 périodes
        self.assertEqual(bulletins.portee_par_defaut(self.conn, self.annee, self.c6), "A")


if __name__ == "__main__":
    unittest.main()
