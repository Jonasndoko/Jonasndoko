"""Caméra : prise de la photo de l'élève.

Nécessite la bibliothèque OpenCV (une seule fois :  pip install opencv-python). Sans elle, le reste du programme
fonctionne normalement ; seule la prise de photo par caméra est indisponible (on peut importer un fichier JPEG).
La photo est recadrée en portrait (3 : 4), redimensionnée à 300 x 400 et enregistrée en JPEG (environ 20 à 40 Ko).
"""
import base64

try:
    import cv2
except ImportError:                      # OpenCV absent : fonctionnalité désactivée, pas d'erreur
    cv2 = None

LARGEUR_PHOTO, HAUTEUR_PHOTO = 300, 400
MESSAGE_INSTALLATION = ("La caméra nécessite la bibliothèque OpenCV.\nInstallez-la une fois : ouvrez l'Invite de commandes "
                        "et tapez\n    pip install opencv-python\npuis relancez le programme.")


def disponible() -> bool:
    return cv2 is not None


def zone_portrait(largeur, hauteur):
    """(x, y, l, h) : zone 3 : 4 centrée dans une image de `largeur` x `hauteur`."""
    if largeur * 4 >= hauteur * 3:
        l, h = hauteur * 3 // 4, hauteur
    else:
        l, h = largeur, largeur * 4 // 3
    return (largeur - l) // 2, (hauteur - h) // 2, l, h


def cameras_disponibles(maximum=4) -> list:
    """Numéros des caméras qui s'ouvrent (0, 1, 2...)."""
    if cv2 is None:
        return []
    trouvees = []
    for i in range(maximum):
        cap = _ouvrir(i)
        if cap is not None and cap.isOpened():
            trouvees.append(i)
        if cap is not None:
            cap.release()
    return trouvees


def _ouvrir(index):
    import sys
    try:
        return cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform.startswith("win") else cv2.VideoCapture(index)
    except Exception:                    # pilote défaillant
        return None


class Camera:
    def __init__(self, index=0):
        if cv2 is None:
            raise RuntimeError(MESSAGE_INSTALLATION)
        self.cap = _ouvrir(index)
        if self.cap is None or not self.cap.isOpened():
            raise RuntimeError("Impossible d'ouvrir la caméra. Vérifiez qu'elle est branchée et qu'aucun autre programme "
                               "ne l'utilise.")

    def image(self):
        """Dernière image (tableau OpenCV, BGR), ou None."""
        ok, frame = self.cap.read()
        return frame if ok else None

    def fermer(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def en_png_tk(image, largeur_max=None, hauteur_max=None) -> str:
    """Image OpenCV -> texte base64 PNG pour tkinter.PhotoImage(data=...), éventuellement réduite."""
    if largeur_max or hauteur_max:
        h, l = image.shape[:2]
        echelle = min((largeur_max or l) / l, (hauteur_max or h) / h, 1.0)
        if echelle < 1.0:
            image = cv2.resize(image, (max(1, int(l * echelle)), max(1, int(h * echelle))), interpolation=cv2.INTER_AREA)
    ok, tampon = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Image illisible.")
    return base64.b64encode(tampon.tobytes()).decode("ascii")


def photo_vers_jpeg(image) -> bytes:
    """Image OpenCV (caméra ou fichier) -> JPEG portrait 300 x 400, prêt à être enregistré."""
    h, l = image.shape[:2]
    x, y, zl, zh = zone_portrait(l, h)
    recadree = image[y:y + zh, x:x + zl]
    petite = cv2.resize(recadree, (LARGEUR_PHOTO, HAUTEUR_PHOTO), interpolation=cv2.INTER_AREA)
    ok, tampon = cv2.imencode(".jpg", petite, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("Impossible de créer la photo.")
    return tampon.tobytes()


def lire_fichier(chemin):
    """Fichier image (JPEG, PNG...) -> image OpenCV. Lève ValueError si illisible."""
    if cv2 is None:
        raise RuntimeError(MESSAGE_INSTALLATION)
    import numpy as np
    with open(chemin, "rb") as f:
        donnees = np.frombuffer(f.read(), dtype=np.uint8)
    image = cv2.imdecode(donnees, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Ce fichier n'est pas une image lisible (JPEG ou PNG).")
    return image


def jpeg_vers_png_tk(jpeg: bytes, largeur_max=None, hauteur_max=None):
    """JPEG enregistré -> base64 PNG pour l'aperçu, ou None si OpenCV n'est pas installé."""
    if cv2 is None:
        return None
    import numpy as np
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return None if image is None else en_png_tk(image, largeur_max, hauteur_max)
