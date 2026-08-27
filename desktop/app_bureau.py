"""Version bureau (exécutable Windows) du registre ICM.

Ouvre `web/index.html` — la version en ligne existante, déjà connectée à
Supabase via la clé « anon » intégrée dans ce fichier — dans une fenêtre
native (WebView2, déjà présent sur Windows 10/11), sans barre d'adresse ni
menu de navigateur. C'est un simple habillage : toute la logique applicative
et la connexion à la base restent celles de web/index.html, inchangées.

Fonctionne aussi bien lancé directement (`python app_bureau.py`, pour
tester) qu'empaqueté en .exe autonome avec PyInstaller (voir
desktop/README.md) — dans ce second cas, PyInstaller extrait le dossier
`web/` à côté de ce script dans un dossier temporaire (sys._MEIPASS), d'où
la détection ci-dessous.
"""
import os
import sys

import webview


def chemin_index_html():
    """Chemin vers web/index.html, que ce script tourne depuis les sources
    ou depuis un .exe PyInstaller (--onefile)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    candidats = [
        os.path.join(base, "web", "index.html"),          # empaqueté (--add-data)
        os.path.join(base, "..", "web", "index.html"),     # lancé depuis desktop/ en source
    ]
    for chemin in candidats:
        if os.path.isfile(chemin):
            return os.path.abspath(chemin)
    raise FileNotFoundError(
        "web/index.html introuvable — vérifiez le dossier d'installation "
        "ou l'option --add-data au moment de l'empaquetage PyInstaller."
    )


def principal():
    fichier = chemin_index_html()
    webview.create_window(
        "Registre ICM — Baptêmes & Mariages",
        f"file://{fichier}",
        width=1200,
        height=800,
        min_size=(900, 600),
    )
    webview.start()


if __name__ == "__main__":
    principal()
