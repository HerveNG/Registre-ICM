"""Convertit static/logo.png en .ico multi-tailles pour l'icône de l'exécutable
Windows (PyInstaller --icon n'accepte pas les .png). Lancé une seule fois par
construire.ps1 avant l'appel à PyInstaller."""
import os

from PIL import Image

ICI = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(ICI, "..", "static", "logo.png")
DESTINATION = os.path.join(ICI, "icone.ico")

if __name__ == "__main__":
    image = Image.open(SOURCE).convert("RGBA")
    tailles = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    image.save(DESTINATION, format="ICO", sizes=tailles)
    print(f"Icône écrite : {DESTINATION}")
