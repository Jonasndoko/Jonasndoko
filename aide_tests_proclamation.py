"""Aide pour les tests : ouvre directement l'impression d'une classe (proclamation confirmée, élèves validés), sans passer par les étapes
de la Directrice et du Préfet (couvertes par test_proclamation.py)."""
import bulletins
import sections


def ouvrir_impression(conn, annee, n_classe, matricules=None):
    portees = bulletins._portees(conn, annee, sections.section_de_classe(conn, n_classe))
    eleves = list(matricules) if matricules is not None else [e["matricule"] for e in bulletins.calculer(conn, annee, n_classe)["eleves"]]
    with conn:
        for p in portees:
            conn.execute("INSERT OR REPLACE INTO PROCLAMATION (ANNEESCO, N_CLASSE, CLE, STATUT, AUTORISEE_LE, AUTORISEE_PAR, TRANSMISE_LE, TRANSMISE_PAR, "
                         "CONFIRMEE_LE, CONFIRMEE_PAR) VALUES (?,?,?,'CONFIRMEE','2026-10-01T08:00:00','test','2026-10-02T08:00:00','test','2026-10-03T08:00:00','test')",
                         (annee, n_classe, p["cle"]))
            for m in eleves:
                conn.execute("INSERT OR REPLACE INTO VALIDATION_BULLETIN (ANNEESCO, N_CLASSE, CLE, MATRICULE, VALIDE, ORIGINE, DECIDE_LE, DECIDE_PAR) "
                             "VALUES (?,?,?,?,1,'DIRECTRICE','2026-10-01T08:00:00','test')", (annee, n_classe, p["cle"], m))
