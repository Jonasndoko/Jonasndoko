"""Point d'entrée WSGI pour l'hébergeur (PythonAnywhere, Render, gunicorn...) : `from wsgi import application`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app_web import application  # noqa: E402,F401
