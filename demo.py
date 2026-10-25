"""Données de DÉMONSTRATION (entièrement fictives) pour essayer le module de paiement.
À ne jamais utiliser sur la base réelle de l'école."""
import secrets

import security
from security import Session

ANNEE_PRECEDENTE, ANNEE_COURANTE = "2025-2026", "2026-2027"


def mot_de_passe_aleatoire() -> str:
    while True:
        mdp = "Perc-" + secrets.token_urlsafe(9).replace("_", "x") + "#" + str(secrets.randbelow(90) + 10)
        if not security.verifier_politique(mdp, "percepteur1"):
            return mdp


def semer(conn, login="percepteur1", nom="Percepteur Démonstration"):
    """Insère le catalogue, les élèves et quelques paiements. Retourne (login, mot de passe)."""
    if conn.execute("SELECT COUNT(*) FROM ELEVE").fetchone()[0]:
        raise RuntimeError("La base contient déjà des élèves : démonstration refusée.")
    import paiements

    mdp = mot_de_passe_aleatoire()
    id_user = security.creer_utilisateur(conn, login, nom, "PERCEPTEUR", mdp)
    perc = Session(id_user, login, nom, "PERCEPTEUR")

    with conn:
        conn.executemany("INSERT INTO DEVISE (CODE_DEVISE, DESI_DEVISE) VALUES (?,?)", [("USD", "Dollar américain"), ("CDF", "Franc congolais")])
        conn.executemany("INSERT INTO ANNEE_SCO (ANNEESCO, EN_COURS) VALUES (?,?)", [(ANNEE_PRECEDENTE, 0), (ANNEE_COURANTE, 1)])
        conn.executemany("INSERT INTO NIVEAU (CODE_NIVEAU, DESI_NIVEAU) VALUES (?,?)", [("N7", "7ème année"), ("N8", "8ème année"),
                         ("N1", "1ère année humanités"), ("N3", "3ème année humanités"), ("N4", "4ème année humanités")])
        conn.executemany("INSERT INTO OPTION_SCO (CODE_OPTION, DESI_OPTION) VALUES (?,?)", [("SCI", "Scientifique"),
                         ("COM", "Commerciale et Gestion"), ("PED", "Pédagogie")])
        conn.executemany("INSERT INTO POSSEDE VALUES (?,?)",
                         [(n, o) for n in ("N1", "N3", "N4") for o in ("SCI", "COM", "PED")])
        classes = [(1, "7ème A", "N7", None, "7ème", "A"), (2, "8ème A", "N8", None, "8ème", "A"),
                   (3, "1ère Pédagogie", "N1", "PED", "1ère", None), (4, "3ème Scientifique", "N3", "SCI", "3ème", None),
                   (5, "4ème Commerciale et Gestion", "N4", "COM", "4ème", None)]
        conn.executemany("INSERT INTO CLASSE (N_CLASSE, DESI_CLASSE, CODE_NIVEAU, CODE_OPTION, ANNEE_ETUDE, DIVISION) "
                         "VALUES (?,?,?,?,?,?)", classes)
        # inscription et examen : un montant unique (dans le type de frais) ; minerval : montant par classe (TARIF),
        # payé en 2 tranches (moitié + moitié)
        conn.executemany("INSERT INTO TYPE_FRAIS (CODTF, DESITF, MONTANT, CODE_DEVISE, PAR_TRANCHE) "
                         "VALUES (?,?,?,?,?)", [
            ("INSC", "Frais d'inscription", 3000, "USD", 0), ("MIN1", "Frais scolaire (minerval) 1", None, None, 1),
            ("MIN2", "Frais scolaire (minerval) 2", None, None, 1), ("EXAM", "Frais d'examen", 1500, "USD", 0)])

        base = {1: 8000, 2: 9000, 3: 10000, 4: 12000, 5: 13000}       # frais scolaire, en centimes USD
        for annee in (ANNEE_PRECEDENTE, ANNEE_COURANTE):
            for n_classe, m in base.items():
                for codtf in ("MIN1", "MIN2"):
                    # frais scolaire : montant par classe, payé en 2 tranches (moitié + moitié, en centimes)
                    conn.execute("INSERT INTO TARIF VALUES (?,?,?,?,?,?)",
                                 (codtf, n_classe, annee, m, "USD", f"{m // 2};{m - m // 2}"))

        eleves = [
            ("CSF-0001", "MBUYI", "KALALA", "Jean-Pierre", "M", "2010-03-25", "Kinshasa", "Av. Kasa-Vubu 12, Lingwala", "0810000001", "Mme KALALA Rose", "0820000001"),
            ("CSF-0002", "NGOY", "MUKENDI", "Béatrice", "F", "2009-11-02", "Lubumbashi", "Rue Lukusa 8, Gombe", "0810000002", "M. NGOY Paul", "0820000002"),
            ("CSF-0003", "KABONGO", "TSHIALA", "Émile", "M", "2008-07-14", "Mbuji-Mayi", "Av. Bokassa 45, Ngaliema", "0810000003", "Mme KABONGO Léa", "0820000003"),
            ("CSF-0004", "MUTOMBO", "ILUNGA", "Grâce", "F", "2011-01-19", "Kinshasa", "Av. Huileries 3, Kalamu", "0810000004", "M. MUTOMBO Jules", "0820000004"),
            ("CSF-0005", "LUKUSA", "BANZA", "Samuel", "M", "2007-05-30", "Kananga", "Av. Libération 77, Limete", "0810000005", "Mme LUKUSA Anne", "0820000005"),
            ("CSF-0006", "KASONGO", "MWAMBA", "Ruth", "F", "2012-09-08", "Kinshasa", "Av. Kimbondo 21, Mont-Ngafula", "0810000006", "M. KASONGO Éric", "0820000006"),
        ]
        conn.executemany("INSERT INTO ELEVE (MATRICULE, NOM, POSTNOM, PRENOM, SEXE, DATE_NAISSANCE, LIEU_NAISSANCE, ADRESSE, TELEPHONE, NOM_TUTEUR, TEL_TUTEUR) VALUES (?,?,?,?,?,?,?,?,?,?,?)", eleves)

        insc = [  # (année, matricule, classe, date, statut)
            (ANNEE_PRECEDENTE, "CSF-0001", 1, "2025-09-01", "NOUVEAU"), (ANNEE_COURANTE, "CSF-0001", 2, "2026-09-01", "ANCIEN"),
            (ANNEE_PRECEDENTE, "CSF-0002", 2, "2025-09-02", "NOUVEAU"), (ANNEE_COURANTE, "CSF-0002", 3, "2026-09-01", "ANCIEN"),
            (ANNEE_PRECEDENTE, "CSF-0003", 4, "2025-09-01", "NOUVEAU"), (ANNEE_COURANTE, "CSF-0003", 5, "2026-09-02", "ANCIEN"),
            (ANNEE_COURANTE, "CSF-0004", 1, "2026-09-03", "NOUVEAU"),
            (ANNEE_PRECEDENTE, "CSF-0005", 4, "2025-09-01", "NOUVEAU"),            # n'est pas revenu cette année
            (ANNEE_PRECEDENTE, "CSF-0006", 1, "2025-09-04", "NOUVEAU"), (ANNEE_COURANTE, "CSF-0006", 1, "2026-09-02", "REDOUBLANT"),
        ]
        conn.executemany("INSERT INTO INSCRIRE VALUES (?,?,?,?,?)", insc)

    # paiements passés par la vraie fonction (mêmes contrôles qu'à l'écran)
    def payer(annee, mat, codtf, centimes):
        paiements.enregistrer_paiement(conn, perc, mat, annee, codtf, centimes)

    for codtf, c in (("INSC", 3000), ("MIN1", 8000), ("MIN2", 8000), ("EXAM", 1500)):
        payer(ANNEE_PRECEDENTE, "CSF-0001", codtf, c)                     # 0001 : tout soldé l'an dernier
    payer(ANNEE_COURANTE, "CSF-0001", "INSC", 3000)
    payer(ANNEE_COURANTE, "CSF-0001", "MIN1", 4500)                       # 0001 : 1re tranche du minerval payée
    payer(ANNEE_PRECEDENTE, "CSF-0002", "INSC", 3000)
    payer(ANNEE_PRECEDENTE, "CSF-0002", "MIN1", 9000)                     # 0002 : dette sur l'an dernier (MIN2, EXAM)
    payer(ANNEE_PRECEDENTE, "CSF-0003", "MIN1", 12000)                    # 0003 : dettes sur l'an dernier
    payer(ANNEE_COURANTE, "CSF-0003", "INSC", 3000)                       # humanités avec option
    return login, mdp
