"""Documents PDF du calcul automatique : bulletins, liste des résultats, proclamation (A4 portrait, sans bibliothèque externe).

IMPORTANT : la mise en page du BULLETIN est entièrement dans `_page_bulletin()` (et ses constantes en tête de fichier). Pour reproduire
exactement le modèle officiel de l'école, c'est cette seule fonction qui change : le calcul (bulletins.py) n'est pas touché.
Entrée : le dictionnaire produit par bulletins.calculer() (+ 'titulaire'), jamais la base de données.
"""
from datetime import date

import config
from inscription_pdf import MARGE
from rapport_pdf import FILET, FOND_CLAIR, HAUTEUR, LARGEUR, _assembler
from recu_pdf import GRIS, NUIT, _Contenu, _dimensions_jpeg, ajuster

DROITE = LARGEUR - MARGE
LARG_NOM = 150                    # colonne « Cours » du bulletin
HAUT_LIGNE = 17
ROUGE = (0.75, 0.22, 0.17)
VERT = (0.12, 0.56, 0.35)


def _fmt(v) -> str:
    return "-" if v is None else str(v).replace(".", ",")


def _aujourdhui() -> str:
    return date.today().strftime("%d/%m/%Y")


def _logo():
    with open(config.DOSSIER_ASSETS / "logo_recu.jpg", "rb") as f:
        jpeg = f.read()
    l, h, _ = _dimensions_jpeg(jpeg)
    return jpeg, (l, h)


def _suite_entete(p, centre, y_titre, titre, sous_titres):
    p.texte_centre(centre, y_titre, titre, "F2", 13)
    y = y_titre
    for i, (t, police, couleur) in enumerate(sous_titres):
        y -= 15
        t, taille = ajuster(t, police, 10 if i == 0 else 9.5, DROITE - MARGE)
        p.texte_centre(centre, y, t, police, taille, couleur or NUIT)
    return y - 14


def _entete(p, dims, titre, sous_titres=()):
    """Cadre, logo, nom de l'école, devise et titre du document. Retourne le y où commence le contenu."""
    centre = LARGEUR / 2
    p.rectangle(18, 18, LARGEUR - 36, HAUTEUR - 36, epaisseur=1.2)
    hl = 44
    p.image(MARGE - 4, HAUTEUR - 30 - hl, hl * dims[0] / dims[1], hl)
    p.texte_centre(centre, HAUTEUR - 52, config.NOM_ECOLE, "F2", 15)
    p.texte_centre(centre, HAUTEUR - 67, config.DEVISE_ECOLE, "F2", 8.5, espacement=0.8)
    p.ligne(MARGE, HAUTEUR - 82, DROITE, HAUTEUR - 82, 1.0)
    return _suite_entete(p, centre, HAUTEUR - 102, titre, sous_titres)


def _pied(pages, copie_date=True):
    n = len(pages)
    for i, pg in enumerate(pages, start=1):
        pg.ligne(MARGE, 44, DROITE, 44, 0.5, FILET)
        if copie_date:
            pg.texte(MARGE, 31, f"Imprimé le {_aujourdhui()}", "F3", 8, GRIS)
        pg.texte_droite(DROITE, 31, f"Page {i} / {n}", "F1", 8, GRIS)


def _etiquettes(portees) -> dict:
    """Intitulés courts des colonnes (« Pér. 1 », « Sem. 1 », « Année »), selon leur rang dans l'année."""
    n_per = n_sem = n_exa = 0
    court = {}
    for p in portees:
        if p["type"] == "periode":
            n_per += 1
            court[p["cle"]] = f"Pér. {n_per}"
        elif p["type"] == "examen":
            n_exa += 1
            court[p["cle"]] = f"Exam. {n_exa}"
        elif p["type"] == "semestre":
            n_sem += 1
            court[p["cle"]] = f"Sem. {n_sem}"
        else:
            court[p["cle"]] = "Année"
    return court


def _signatures(p, y, gauche, milieu, droite):
    for x, titre, nom in ((MARGE + 10, *gauche), (LARGEUR / 2 - 55, *milieu), (DROITE - 120, *droite)):
        if not titre:
            continue
        p.texte(x, y, titre, "F2", 9)
        p.ligne(x, y - 36, x + 110, y - 36, 0.5, GRIS)
        if nom:
            t, taille = ajuster(nom, "F1", 8.5, 112)
            p.texte(x, y - 48, t, "F1", taille, GRIS)


# ================================================================== BULLETIN (le modèle : à remplacer par le modèle officiel)
def _page_bulletin(calc, eleve, colonnes, dims) -> _Contenu:
    p = _Contenu()
    classe = calc["classe"]
    lib_classe = classe["designation"] + (f" - {classe['option']}" if classe["option"] else "")
    derniere = colonnes[-1]
    y = _entete(p, dims, "BULLETIN SCOLAIRE", [(f"Classe : {lib_classe}   -   Année scolaire {calc['annee']}", "F2", None),
                                                (derniere["libelle"] if derniere["type"] != "annee" else "Résultats de l'année", "F1", GRIS)])
    # ---- identité de l'élève
    p.fond(MARGE, y - 44, DROITE - MARGE, 52, FOND_CLAIR)
    t, taille = ajuster(eleve["nom_complet"], "F2", 11, DROITE - MARGE - 190)
    p.texte(MARGE + 8, y - 6, "Élève :", "F1", 9, GRIS)
    p.texte(MARGE + 52, y - 6, t, "F2", taille)
    p.texte(DROITE - 170, y - 6, "Matricule :", "F1", 9, GRIS)
    p.texte(DROITE - 112, y - 6, eleve["matricule"], "F2", 10)
    naiss = eleve["naissance"] + (f" à {eleve['lieu_naissance']}" if eleve["lieu_naissance"] else "")
    t, taille = ajuster(naiss or "-", "F1", 9.5, 250)
    p.texte(MARGE + 8, y - 24, "Né(e) le :", "F1", 9, GRIS)
    p.texte(MARGE + 62, y - 24, t, "F1", taille)
    p.texte(DROITE - 170, y - 24, "Sexe :", "F1", 9, GRIS)
    p.texte(DROITE - 130, y - 24, eleve["sexe"] or "-", "F1", 9.5)
    p.texte(MARGE + 8, y - 38, "Effectif de la classe :", "F1", 9, GRIS)
    p.texte(MARGE + 110, y - 38, str(len(calc["eleves"])), "F1", 9.5)
    y -= 66

    # ---- tableau des cours
    court = _etiquettes(calc["portees"])
    n = len(colonnes)
    larg_col = (DROITE - MARGE - LARG_NOM) / n
    larg_sous = larg_col / 2
    x_col = {c["cle"]: MARGE + LARG_NOM + i * larg_col for i, c in enumerate(colonnes)}
    lignes_bas = 5                                           # total, %, place, conduite, résultat
    dispo = y - 190 - 2 * HAUT_LIGNE
    haut = max(11, min(HAUT_LIGNE, dispo / max(1, len(calc["cours"]) + lignes_bas)))
    p.fond(MARGE, y - 2 * HAUT_LIGNE + 12, DROITE - MARGE, 2 * HAUT_LIGNE, FOND_CLAIR)
    p.texte(MARGE + 4, y - HAUT_LIGNE / 2 - 4, "COURS", "F2", 8.5)
    for c in colonnes:
        x = x_col[c["cle"]]
        titre = court[c["cle"]] if n > 1 else c["libelle"]
        t, taille = ajuster(titre, "F2", 8.5, larg_col - 4)
        p.texte_centre(x + larg_col / 2, y + 2, t, "F2", taille)
        p.texte_centre(x + larg_sous / 2, y - HAUT_LIGNE + 2, "Max", "F1", 7.5, GRIS)
        p.texte_centre(x + larg_sous * 1.5, y - HAUT_LIGNE + 2, "Pts", "F1", 7.5, GRIS)
        p.ligne(x, y + 12, x, y - 2 * HAUT_LIGNE + 12, 0.4, FILET)
    y -= 2 * HAUT_LIGNE
    haut_tableau = y + 12
    for i, c in enumerate(calc["cours"]):
        if i % 2:
            p.fond(MARGE, y - 4 + 12 - haut, DROITE - MARGE, haut, (0.97, 0.98, 1))
        t, taille = ajuster(c["libelle"], "F1", 8.5, LARG_NOM - 8)
        p.texte(MARGE + 4, y - haut + 12 + 2, t, "F1", taille)
        for col in colonnes:
            r = eleve["cours"][c["id_cc"]].get(col["cle"])
            x = x_col[col["cle"]]
            echec = r is not None and r["pct"] is not None and r["pct"] < config.SEUIL_REUSSITE
            p.texte_centre(x + larg_sous / 2, y - haut + 12 + 2, _fmt(r["max"]) if r else "-", "F1", 8, GRIS)
            p.texte_centre(x + larg_sous * 1.5, y - haut + 12 + 2, _fmt(r["obtenu"]) if r else "-", "F2", 8.5, ROUGE if echec else NUIT)
        y -= haut
    p.ligne(MARGE, y + 12, DROITE, y + 12, 0.8)
    # ---- totaux
    def ligne_resume(titre, valeur_col, gras=True):
        nonlocal y
        p.texte(MARGE + 4, y - haut + 12 + 2, titre, "F2", 8.5)
        for col in colonnes:
            texte, couleur = valeur_col(col, eleve["portees"][col["cle"]])
            texte, taille = ajuster(texte, "F2" if gras else "F1", 8.5, larg_col - 4)
            p.texte_centre(x_col[col["cle"]] + larg_col / 2, y - haut + 12 + 2, texte, "F2" if gras else "F1", taille, couleur)
        y -= haut
        p.ligne(MARGE, y + 12, DROITE, y + 12, 0.4, FILET)

    nuit = NUIT
    ligne_resume("TOTAL (points / maximum)", lambda c, r: (f"{_fmt(r['obtenu'])} / {_fmt(r['max'])}" if r["max"] else "-", nuit))
    ligne_resume("POURCENTAGE", lambda c, r: ((_fmt(r["pct"]) + " %") if r["pct"] is not None else "-",
                                               ROUGE if r["pct"] is not None and r["pct"] < config.SEUIL_REUSSITE else nuit))
    ligne_resume("PLACE (rang / effectif)", lambda c, r: (f"{r['rang']} / {calc['stats'][c['cle']]['classes']}" if r["rang"] else "-", nuit))
    ligne_resume("CONDUITE", lambda c, r: (r["conduite"] or "-" if c["type"] == "periode" else "", nuit), gras=False)
    ligne_resume("MENTION", lambda c, r: (r["mention"] or "-" if c["type"] != "periode" and r["complet"] else "", nuit), gras=False)
    p.rectangle(MARGE, y + 12, DROITE - MARGE, haut_tableau - y - 12, epaisseur=0.8)

    # ---- décision (dernière portée : semestre ou année)
    r = eleve["portees"][derniere["cle"]]
    y -= 24
    if derniere["type"] == "periode":
        decision = f"Pourcentage de la période : {_fmt(r['pct'])} %" if r["pct"] is not None else "Aucun point enregistré pour cette période."
        couleur = nuit
    else:
        decision = r["resultat"]
        couleur = VERT if r["reussite"] is True else (ROUGE if r["reussite"] is False else GRIS)
        if decision == config.DECISION_ATTENTE:
            decision += " (il manque les points d'une période)"
        p.texte(MARGE, y, "Résultat :", "F1", 10, GRIS)
        p.texte(MARGE + 56, y, decision, "F2", 11, couleur)
        if derniere["type"] == "annee" and r["mention"]:
            p.texte_droite(DROITE, y, f"Mention : {r['mention']}", "F2", 10)
        decision = None
    if decision:
        p.texte(MARGE, y, decision, "F2", 10.5, couleur)
    p.texte(MARGE, y - 16, f"Seuil de réussite : {_fmt(config.SEUIL_REUSSITE)} %  -  les points en rouge sont sous ce seuil.", "F3", 8, GRIS)
    _signatures(p, 120, ("Le titulaire", calc.get("titulaire", "")), ("Le préfet des études", ""), ("Le parent / tuteur", ""))
    p.texte(MARGE, 52, "Fait le " + _aujourdhui(), "F3", 8, GRIS)
    return p


def bulletins(calc, eleves, colonnes) -> bytes:
    """Un bulletin (une page) par élève. Classe du primaire : modèle officiel du primaire (bulletin_primaire_pdf.py)."""
    if calc["classe"].get("primaire"):
        import bulletin_primaire_pdf
        return bulletin_primaire_pdf.bulletins(calc, eleves)
    import bulletin_secondaire_pdf                       # secondaire et humanités (7ème à 4ème) : modèle officiel du secondaire
    return bulletin_secondaire_pdf.bulletins(calc, eleves)


# ================================================================== LISTE DES RÉSULTATS
def liste_resultats(calc, portee) -> bytes:
    jpeg, dims = _logo()
    classe = calc["classe"]
    lib_classe = classe["designation"] + (f" - {classe['option']}" if classe["option"] else "")
    cle = portee["cle"]
    avec_cond = portee["type"] == "periode"
    cols = [("rang", "Rang", 34, "c"), ("nom", "Nom complet", 0, "g"), ("pts", "Points", 66, "c"), ("pct", "%", 40, "c"),
            ("mention", "Mention", 92, "c"), ("res", "Résultat", 78, "c")] + ([("cond", "CDT", 30, "c")] if avec_cond else [])
    fixe = sum(c[2] for c in cols)
    pos, x = {}, MARGE
    for k, t, l, a in cols:
        l = l or (DROITE - MARGE - fixe)
        pos[k] = (x, l)
        x += l
    from bulletins import ordre_reussite                                      # réussites d'abord, puis échecs, puis « en attente »
    lignes = sorted(calc["eleves"], key=lambda e: (ordre_reussite(e["portees"][cle]), e["nom_complet"].lower()))

    pages = []

    def nouvelle():
        p = _Contenu()
        y = _entete(p, dims, "LISTE DES RÉUSSITES ET DES ÉCHECS", [(f"Classe : {lib_classe}   -   Année scolaire {calc['annee']}", "F2", None),
                                                      (portee["libelle"], "F1", GRIS)])
        p.fond(MARGE, y - 6, DROITE - MARGE, 20, FOND_CLAIR)
        for k, t, l, a in cols:
            x0, l0 = pos[k]
            p.texte(x0 + 4, y, t, "F2", 8.5) if a == "g" else p.texte_centre(x0 + l0 / 2, y, t, "F2", 8.5)
        pages.append(p)
        return p, y - 22

    p, y = nouvelle()
    for i, e in enumerate(lignes):
        if y < 150:
            p, y = nouvelle()
        r = e["portees"][cle]
        if i % 2 == 0:
            p.fond(MARGE, y - 5, DROITE - MARGE, HAUT_LIGNE - 1, (0.97, 0.98, 1))
        p.texte_centre(pos["rang"][0] + pos["rang"][1] / 2, y, str(r["rang"] or "-"), "F2", 8.5)
        t, taille = ajuster(e["nom_complet"], "F1", 8.5, pos["nom"][1] - 8)
        p.texte(pos["nom"][0] + 4, y, t, "F1", taille)
        p.texte_centre(pos["pts"][0] + pos["pts"][1] / 2, y, f"{_fmt(r['obtenu'])} / {_fmt(r['max'])}" if r["max"] else "-", "F1", 8.5)
        p.texte_centre(pos["pct"][0] + pos["pct"][1] / 2, y, _fmt(r["pct"]), "F2", 8.5)
        p.texte_centre(pos["mention"][0] + pos["mention"][1] / 2, y, r["mention"] or "-", "F1", 8)
        couleur = VERT if r["reussite"] is True else (ROUGE if r["reussite"] is False else GRIS)
        p.texte_centre(pos["res"][0] + pos["res"][1] / 2, y, r["resultat"], "F2", 7.5, couleur)
        if avec_cond:
            p.texte_centre(pos["cond"][0] + pos["cond"][1] / 2, y, r["conduite"] or "-", "F1", 8.5)
        y -= HAUT_LIGNE
    if not lignes:
        p.texte_centre(LARGEUR / 2, y - 10, "Aucun élève inscrit dans cette classe.", "F3", 10, GRIS)
    s = calc["stats"][cle]
    if y < 150:
        p, y = nouvelle()
    p.ligne(MARGE, y + 8, DROITE, y + 8, 0.8)
    y -= 8
    p.texte(MARGE, y, f"Effectif : {s['effectif']}   -   Réussites : {s['reussis']}   -   Échecs : {s['echecs']}   -   En attente : {s['en_attente']}"
                      f"   -   Taux de réussite : {_fmt(s['taux'])} %   -   Moyenne de la classe : {_fmt(s['moyenne'])} %", "F2", 8)
    _signatures(p, 100, ("Le titulaire", calc.get("titulaire", "")), ("", ""), ("Le préfet des études", ""))
    _pied(pages)
    return _assembler([pg.octets() for pg in pages], jpeg, titre="Liste des réussites et des échecs")


# ================================================================== PROCLAMATION DES RÉSULTATS (année)
def proclamation(calc) -> bytes:
    jpeg, dims = _logo()
    classe = calc["classe"]
    lib_classe = classe["designation"] + (f" - {classe['option']}" if classe["option"] else "")
    cle = "A"
    groupes = [("ÉLÈVES ADMIS", config.DECISION_REUSSI, VERT), ("ÉLÈVES AJOURNÉS", config.DECISION_ECHEC, ROUGE),
               ("RÉSULTATS EN ATTENTE (points manquants)", config.DECISION_ATTENTE, GRIS)]
    pages = []

    def nouvelle(suite=False):
        p = _Contenu()
        y = _entete(p, dims, "PROCLAMATION DES RÉSULTATS", [(f"Classe : {lib_classe}   -   Année scolaire {calc['annee']}", "F2", None),
                                                             ("Proclamation de fin d'année" + (" (suite)" if suite else ""), "F1", GRIS)])
        pages.append(p)
        return p, y

    p, y = nouvelle()
    s = calc["stats"][cle]
    p.fond(MARGE, y - 30, DROITE - MARGE, 40, FOND_CLAIR)
    p.texte(MARGE + 8, y - 6, f"Effectif : {s['effectif']}      Admis : {s['reussis']}      Ajournés : {s['echecs']}      En attente : {s['en_attente']}",
            "F2", 9.5)
    p.texte(MARGE + 8, y - 22, f"Taux de réussite : {_fmt(s['taux'])} %      Moyenne de la classe : {_fmt(s['moyenne'])} %      "
                               f"Seuil de réussite : {_fmt(config.SEUIL_REUSSITE)} %", "F1", 9)
    y -= 54
    for titre, decision, couleur in groupes:
        membres = sorted((e for e in calc["eleves"] if e["portees"][cle]["resultat"] == decision),
                         key=lambda e: (e["portees"][cle]["rang"] is None, e["portees"][cle]["rang"] or 0, e["nom_complet"].lower()))
        if not membres and decision == config.DECISION_ATTENTE:
            continue
        if y < 200:
            p, y = nouvelle(True)
        p.texte(MARGE, y, f"{titre} ({len(membres)})", "F2", 10, couleur)
        p.ligne(MARGE, y - 4, DROITE, y - 4, 0.6, couleur)
        y -= 20
        if not membres:
            p.texte(MARGE + 8, y, "Aucun.", "F3", 9, GRIS)
            y -= 20
            continue
        for i, e in enumerate(membres):
            if y < 110:
                p, y = nouvelle(True)
            r = e["portees"][cle]
            if i % 2 == 0:
                p.fond(MARGE, y - 5, DROITE - MARGE, HAUT_LIGNE - 1, (0.97, 0.98, 1))
            p.texte_centre(MARGE + 18, y, str(r["rang"] or "-"), "F2", 8.5)
            t, taille = ajuster(e["nom_complet"], "F1", 9, 290)
            p.texte(MARGE + 44, y, t, "F1", taille)
            p.texte_centre(DROITE - 130, y, (_fmt(r["pct"]) + " %") if r["pct"] is not None else "-", "F2", 8.5)
            p.texte_centre(DROITE - 50, y, r["mention"] or "", "F1", 8)
            y -= HAUT_LIGNE
        y -= 12
    if y < 120:
        p, y = nouvelle(True)
    p.texte(MARGE, y - 4, "Proclamé le " + _aujourdhui(), "F3", 8.5, GRIS)
    _signatures(p, 100, ("Le titulaire", calc.get("titulaire", "")), ("", ""), ("Le préfet des études", ""))
    _pied(pages)
    return _assembler([pg.octets() for pg in pages], jpeg, titre="Proclamation des résultats")
