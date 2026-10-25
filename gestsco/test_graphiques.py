"""Tests du camembert du tableau de bord (géométrie, sans interface graphique).
Lancer :  python test_graphiques.py"""
import unittest

import graphiques as g

TAILLES = [(360, 240), (520, 300), (900, 500)]
ECHELLES = [1.0, 1.5]


def dans_la_zone(prims, largeur, hauteur, marge=1.5):
    for p in prims:
        if p["t"] in ("oval", "arc", "rect"):
            x0, y0, x1, y1 = p["b"]
            assert -marge <= min(x0, x1) and max(x0, x1) <= largeur + marge, p
            assert -marge <= min(y0, y1) and max(y0, y1) <= hauteur + marge, p
        elif p["t"] == "text":
            x, y = p["p"]
            assert 0 <= x <= largeur and 0 <= y <= hauteur, p


class TestOutils(unittest.TestCase):
    def test_tronquer(self):
        self.assertEqual(g.tronquer("En règle", 500, 9, 1.0), "En règle")
        court = g.tronquer("Un libellé vraiment très long", 60, 9, 1.0)
        self.assertTrue(court.endswith("…") and len(court) < 29)

    def test_pourcentage(self):
        self.assertEqual(g.formater_pourcentage(3, 8), "37,5 %")
        self.assertEqual(g.formater_pourcentage(0, 0), "0 %")


class TestCamembert(unittest.TestCase):
    PARTS = [("En règle", 3, g.MENTHE), ("Pas en règle", 5, g.CORAIL)]

    def test_reste_dans_la_zone(self):
        for l, h in TAILLES:
            for e in ECHELLES:
                dans_la_zone(g.camembert(self.PARTS, l, h, e), l, h)

    def test_secteurs_et_legende(self):
        prims = g.camembert(self.PARTS, 520, 300)
        arcs = [p for p in prims if p["t"] == "arc"]
        self.assertEqual(len(arcs), 2)
        self.assertAlmostEqual(sum(a["extent"] for a in arcs), 360.0)
        self.assertAlmostEqual(arcs[0]["extent"], 135.0)
        textes = [p["s"] for p in prims if p["t"] == "text"]
        for attendu in ("37,5 %", "62,5 %", "En règle (3)", "Pas en règle (5)"):
            self.assertIn(attendu, textes)

    def test_un_seul_secteur_est_un_disque(self):
        prims = g.camembert([("En règle", 4, g.MENTHE), ("Pas en règle", 0, g.CORAIL)], 520, 300)
        self.assertFalse([p for p in prims if p["t"] == "arc"])
        self.assertEqual(len([p for p in prims if p["t"] == "oval" and p["fill"] == g.MENTHE and
                              p["b"][2] - p["b"][0] > 50]), 1)
        self.assertIn("100,0 %", [p["s"] for p in prims if p["t"] == "text"])

    def test_le_camembert_ne_recouvre_pas_la_legende(self):
        for l, h in TAILLES + [(300, 240)]:
            for e in ECHELLES:
                prims = g.camembert(self.PARTS, l, h, e)
                bas_disque = max(p["b"][3] for p in prims if p["t"] in ("arc", "oval") and p["b"][2] - p["b"][0] > 30 * e)
                haut_legende = min(p["p"][1] for p in prims if p["t"] == "text" and p["s"].endswith(")"))
                self.assertLess(bas_disque, haut_legende, (l, h, e))

    def test_aucune_donnee(self):
        for parts in ([], [("a", 0, "#fff")]):
            self.assertEqual([p["t"] for p in g.camembert(parts, 400, 300)], ["text"])


if __name__ == "__main__":
    unittest.main()


class TestCourbeEtBarres(unittest.TestCase):
    POINTS = [("2023-2024", 40), ("2024-2025", 55), ("2025-2026", 62), ("2026-2027", 70)]
    GROUPES = [(a, [v // 2, v - v // 2]) for a, v in POINTS]
    SERIES = [("Filles", g.VIOLET), ("Garçons", g.BLEU)]

    def test_courbe_dans_la_zone(self):
        for l, h in TAILLES:
            for e in ECHELLES:
                prims = g.courbe(self.POINTS, l, h, e)
                dans_la_zone(prims, l, h)
                self.assertTrue(any(p["t"] == "line" for p in prims))

    def test_barres_dans_la_zone(self):
        for l, h in TAILLES:
            for e in ECHELLES:
                prims = g.barres(self.GROUPES, self.SERIES, l, h, e)
                dans_la_zone(prims, l, h)
                self.assertEqual(sum(p["t"] == "rect" for p in prims), 8)

    def test_sans_donnee_message(self):
        self.assertEqual(g.courbe([], 400, 250)[0]["t"], "text")
        self.assertEqual(g.barres([("2026-2027", [0, 0])], self.SERIES, 400, 250)[0]["t"], "text")

    def test_un_seul_point_ne_plante_pas(self):
        dans_la_zone(g.courbe([("2026-2027", 12)], 500, 300), 500, 300)
