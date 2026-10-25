"""Document scolaire officiel (attestation, certificat) au format PDF, une page A4 portrait, sans bibliothèque externe.
Même principe que recu_pdf.py : polices Helvetica intégrées, armoiries en JPEG."""
from recu_pdf import GRIS, NUIT, _Contenu, _assembler_pdf, largeur_texte

LARGEUR, HAUTEUR = 595.28, 841.89
MARGE = 64
ROUGE = (0.70, 0.10, 0.10)
BASSE_LARGEUR = LARGEUR - 2 * MARGE


def _lignes(texte, police, taille, largeur) -> list:
    """Coupe `texte` en lignes qui tiennent dans `largeur` (les sauts de ligne du texte sont respectés)."""
    sortie = []
    for paragraphe in str(texte).split("\n"):
        mots, courante = paragraphe.split(), ""
        if not mots:
            sortie.append("")
            continue
        for mot in mots:
            essai = f"{courante} {mot}".strip()
            if largeur_texte(essai, police, taille) <= largeur or not courante:
                courante = essai
            else:
                sortie.append(courante)
                courante = mot
        sortie.append(courante)
    return sortie


def generer(doc: dict, para: dict, jpeg: bytes) -> bytes:
    """doc : titre, contenu, statut, numero, annee, approbation (libellé), signataire, signe_le (jj/mm/aaaa), ville, date_edition.
    para : ecole, devise, ville. Un document non signé porte la mention « PROJET » ; un document annulé, « ANNULÉ »."""
    p = _Contenu()
    haut = HAUTEUR - 46
    p.image(LARGEUR / 2 - 24, haut - 54, 48, 54)
    y = haut - 70
    for texte, police, taille in (("RÉPUBLIQUE DÉMOCRATIQUE DU CONGO", "F2", 11),
                                  ("MINISTÈRE DE L'ENSEIGNEMENT PRIMAIRE, SECONDAIRE ET TECHNIQUE", "F1", 8.5),
                                  (str(para["ecole"]).upper(), "F2", 13), (para["devise"], "F3", 8.5)):
        p.texte_centre(LARGEUR / 2, y, texte, police, taille, NUIT if police != "F3" else GRIS)
        y -= taille + 6
    p.ligne(MARGE, y, LARGEUR - MARGE, y, 1.0)
    y -= 34
    titre = doc["titre"].upper()
    taille = 17
    while largeur_texte(titre, "F2", taille) > BASSE_LARGEUR and taille > 11:
        taille -= 1
    p.texte_centre(LARGEUR / 2, y, titre, "F2", taille)
    p.ligne(LARGEUR / 2 - largeur_texte(titre, "F2", taille) / 2, y - 4, LARGEUR / 2 + largeur_texte(titre, "F2", taille) / 2, y - 4, 0.8)
    y -= 20
    if doc["statut"] == "SIGNE" and doc["numero"]:
        p.texte_centre(LARGEUR / 2, y, f"N° {doc['numero']}", "F1", 10, GRIS)
    y -= 36
    for ligne in _lignes(doc["contenu"], "F1", 11.5, BASSE_LARGEUR):
        if ligne:
            p.texte(MARGE, y, ligne, "F1", 11.5)
        y -= 19
    y -= 24
    p.texte(MARGE, y, f"Fait à {doc['ville']}, le {doc['date_edition']}" if doc["ville"] else f"Fait le {doc['date_edition']}", "F1", 11)
    y -= 34
    p.texte_droite(LARGEUR - MARGE, y, doc["approbation"] or "Signature", "F2", 11)
    y -= 70
    if doc["statut"] == "SIGNE" and doc["signataire"]:
        p.texte_droite(LARGEUR - MARGE, y, doc["signataire"], "F2", 11)
        if doc["signe_le"]:
            p.texte_droite(LARGEUR - MARGE, y - 15, f"Signé ou validé le {doc['signe_le']}", "F3", 9, GRIS)
    # mention de statut
    if doc["statut"] != "SIGNE":
        mention = "ANNULÉ - SANS VALEUR" if doc["statut"] == "ANNULE" else "PROJET - NON SIGNÉ - NE VAUT PAS DOCUMENT OFFICIEL"
        p.texte_centre(LARGEUR / 2, 44, mention, "F2", 11, ROUGE)
    p.ligne(MARGE, 62, LARGEUR - MARGE, 62, 0.5, GRIS)
    p.texte_centre(LARGEUR / 2, 50 if doc["statut"] == "SIGNE" else 30, f"{para['ecole']} - année scolaire {doc['annee']}", "F1", 8, GRIS)
    return _assembler_pdf(p.octets(), jpeg, LARGEUR, HAUTEUR, titre=doc["titre"].replace("(", "").replace(")", ""))
