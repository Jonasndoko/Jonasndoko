"""Point d'entrée : python main.py"""
import sys

import database


def activer_nettete_windows():
    """Évite le rendu flou sur les écrans Windows à haute résolution."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    activer_nettete_windows()
    from ecrans import Application            # import tardif : Tk n'est chargé qu'ici
    conn = database.connecter()
    try:
        Application(conn).mainloop()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
