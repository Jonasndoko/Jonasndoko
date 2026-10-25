"""Lecture d'un code QR dans une photo (côté serveur), pour les téléphones dont le navigateur ne sait pas lire les QR tout seul
(l'API « BarcodeDetector » existe sur Chrome Android mais pas sur tous les navigateurs).

Nécessite OpenCV (`opencv-python-headless`), déjà facultatif pour la carte d'élève. Sans OpenCV : `disponible()` est faux et
l'application mobile propose seulement la saisie du matricule sur ces téléphones.
"""
import camera

COTE_MAX = 4000          # une photo de contrôle fait environ 640 x 480 : au-delà, on refuse (protège la mémoire du serveur)


def disponible() -> bool:
    return camera.disponible()


def dimensions_jpeg(jpeg: bytes):
    """(largeur, hauteur) lues dans l'en-tête JPEG, sans décoder l'image ; None si l'en-tête est illisible."""
    i, n = 2, len(jpeg)
    while i + 9 < n:
        if jpeg[i] != 0xFF:
            i += 1
            continue
        marque = jpeg[i + 1]
        if marque in (0xD8, 0x01) or 0xD0 <= marque <= 0xD7 or marque == 0xFF:
            i += 1 if marque == 0xFF else 2
            continue
        longueur = (jpeg[i + 2] << 8) | jpeg[i + 3]
        if marque in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return (jpeg[i + 7] << 8) | jpeg[i + 8], (jpeg[i + 5] << 8) | jpeg[i + 6]
        i += 2 + longueur
    return None


def lire(jpeg: bytes):
    """Texte du code QR trouvé dans la photo JPEG, ou None. Lève ValueError si l'image n'est pas un JPEG exploitable."""
    if not jpeg or jpeg[:2] != b"\xff\xd8":
        raise ValueError("La photo doit être une image JPEG.")
    dim = dimensions_jpeg(jpeg)
    if not dim or max(dim) > COTE_MAX:
        raise ValueError("Image trop grande ou illisible.")
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("Image illisible.")
    detecteur = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else cv2.QRCodeDetector()
    texte, _points, _droit = detecteur.detectAndDecode(image)
    return texte or None
