"""Générateur de QR code (norme ISO 18004), sans bibliothèque externe.

Mode octets, niveau de correction M (environ 15 % du code peut être abîmé et rester lisible), versions 1 à 6
(jusqu'à 106 caractères). `matrice("texte")` retourne une liste de lignes de booléens (True = module noir),
sans la zone blanche autour (« quiet zone ») : c'est à l'appelant de la laisser.
"""

# version : (octets de données par bloc : liste de (nombre de blocs, octets de données), octets de correction par bloc)
_VERSIONS = {
    1: ([(1, 16)], 10), 2: ([(1, 28)], 16), 3: ([(1, 44)], 26),
    4: ([(2, 32)], 18), 5: ([(2, 43)], 24), 6: ([(4, 27)], 16),
}
_ALIGNEMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}

# --- corps de Galois GF(256), polynôme 0x11D
_EXP, _LOG = [0] * 512, [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i], _LOG[_x] = _x, _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generateur(n):
    poly = [1]
    for i in range(n):
        suivant = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            suivant[j] ^= c
            suivant[j + 1] ^= _mul(c, _EXP[i])
        poly = suivant
    return poly


def _correction(donnees, n):
    """Octets de correction d'erreur (Reed-Solomon) d'un bloc de données."""
    gen = _generateur(n)
    reste = list(donnees) + [0] * n
    for i in range(len(donnees)):
        c = reste[i]
        if c:
            for j, g in enumerate(gen):
                reste[i + j] ^= _mul(g, c)
    return reste[len(donnees):]


def _bits_donnees(octets, version):
    blocs, _ = _VERSIONS[version]
    capacite = sum(n * d for n, d in blocs)
    bits = "0100" + format(len(octets), "08b") + "".join(format(o, "08b") for o in octets)
    bits += "0" * min(4, capacite * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    mots = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    for k in range(capacite - len(mots)):
        mots.append(0xEC if k % 2 == 0 else 0x11)
    return mots


def _mots_finaux(octets, version):
    blocs, nec = _VERSIONS[version]
    mots = _bits_donnees(octets, version)
    parts, pos = [], 0
    for nombre, taille in blocs:
        for _ in range(nombre):
            parts.append(mots[pos:pos + taille])
            pos += taille
    corr = [_correction(p, nec) for p in parts]
    sortie = []
    for i in range(max(len(p) for p in parts)):
        sortie += [p[i] for p in parts if i < len(p)]
    for i in range(nec):
        sortie += [c[i] for c in corr]
    return sortie


def _format_bits(masque):
    """15 bits d'information de format (niveau M = 00) protégés par un code BCH."""
    donnees = (0b00 << 3) | masque
    reste = donnees << 10
    for i in range(14, 9, -1):
        if reste & (1 << i):
            reste ^= 0x537 << (i - 10)
    return ((donnees << 10) | reste) ^ 0x5412


def _fonction_masque(m, i, j):
    return [(i + j) % 2 == 0, i % 2 == 0, j % 3 == 0, (i + j) % 3 == 0, (i // 2 + j // 3) % 2 == 0,
            (i * j) % 2 + (i * j) % 3 == 0, ((i * j) % 2 + (i * j) % 3) % 2 == 0,
            ((i + j) % 2 + (i * j) % 3) % 2 == 0][m]


def _penalite(g):
    n = len(g)
    total = 0
    for lignes in (g, [list(c) for c in zip(*g)]):                  # règle 1 : séries de modules identiques
        for l in lignes:
            serie = 1
            for k in range(1, n):
                if l[k] == l[k - 1]:
                    serie += 1
                else:
                    total += serie - 2 if serie >= 5 else 0
                    serie = 1
            total += serie - 2 if serie >= 5 else 0
    for i in range(n - 1):                                          # règle 2 : blocs 2x2
        for j in range(n - 1):
            if g[i][j] == g[i][j + 1] == g[i + 1][j] == g[i + 1][j + 1]:
                total += 3
    motif = [True, False, True, True, True, False, True]            # règle 3 : motifs ressemblant au repère
    for lignes in (g, [list(c) for c in zip(*g)]):
        for l in lignes:
            for k in range(n - 6):
                if l[k:k + 7] == motif and (all(not x for x in l[max(0, k - 4):k]) and k >= 4
                                            or all(not x for x in l[k + 7:k + 11]) and k + 11 <= n):
                    total += 40
    noirs = sum(sum(l) for l in g)                                  # règle 4 : équilibre noir / blanc
    total += abs(noirs * 100 // (n * n) - 50) // 5 * 10
    return total


def matrice(texte: str):
    octets = texte.encode("utf-8")
    version = next((v for v, (blocs, _) in sorted(_VERSIONS.items())
                    if len(octets) <= sum(n * d for n, d in blocs) - 2), None)
    if version is None:
        raise ValueError("Texte trop long pour le QR code.")
    n = 17 + 4 * version
    modules = [[False] * n for _ in range(n)]
    reserve = [[False] * n for _ in range(n)]

    def poser(i, j, noir, fonction=True):
        modules[i][j] = noir
        if fonction:
            reserve[i][j] = True

    def repere(r, c):
        for i in range(-1, 8):
            for j in range(-1, 8):
                if 0 <= r + i < n and 0 <= c + j < n:
                    noir = 0 <= i <= 6 and 0 <= j <= 6 and (i in (0, 6) or j in (0, 6) or (2 <= i <= 4 and 2 <= j <= 4))
                    poser(r + i, c + j, noir)

    repere(0, 0), repere(0, n - 7), repere(n - 7, 0)
    for k in range(8, n - 8):                                        # lignes de synchronisation
        poser(6, k, k % 2 == 0)
        poser(k, 6, k % 2 == 0)
    positions = _ALIGNEMENT[version]
    for r in positions:
        for c in positions:
            if reserve[r][c]:
                continue
            for i in range(-2, 3):
                for j in range(-2, 3):
                    poser(r + i, c + j, max(abs(i), abs(j)) != 1)
    poser(n - 8, 8, True)                                            # module noir fixe
    for k in range(9):                                               # zones d'information de format (réservées)
        reserve[8][k] = reserve[k][8] = True
    for k in range(8):
        reserve[8][n - 1 - k] = reserve[n - 1 - k][8] = True

    bits = "".join(format(m, "08b") for m in _mots_finaux(octets, version))
    positions_donnees, montant, j = [], True, n - 1
    while j > 0:
        if j == 6:
            j -= 1
        for i in (range(n - 1, -1, -1) if montant else range(n)):
            for dj in (0, 1):
                if not reserve[i][j - dj]:
                    positions_donnees.append((i, j - dj))
        montant = not montant
        j -= 2
    meilleur = None
    for m in range(8):
        g = [l[:] for l in modules]
        for k, (i, j) in enumerate(positions_donnees):
            noir = k < len(bits) and bits[k] == "1"
            g[i][j] = noir != _fonction_masque(m, i, j)
        fb = _format_bits(m)
        bit = lambda k: bool((fb >> k) & 1)
        for k in range(6):                                          # première copie, autour du repère haut-gauche
            g[k][8] = bit(k)
        g[7][8], g[8][8], g[8][7] = bit(6), bit(7), bit(8)
        for k in range(9, 15):
            g[8][14 - k] = bit(k)
        for k in range(8):                                          # seconde copie, le long des deux autres repères
            g[8][n - 1 - k] = bit(k)
        for k in range(8, 15):
            g[n - 15 + k][8] = bit(k)
        p = _penalite(g)
        if meilleur is None or p < meilleur[0]:
            meilleur = (p, g)
    return meilleur[1]
