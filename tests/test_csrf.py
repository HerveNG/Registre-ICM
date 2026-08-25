# -*- coding: utf-8 -*-
"""Jeton anti-CSRF (Flask-WTF CSRFProtect) — désactivé par défaut dans les
autres fichiers de tests (WTF_CSRF_ENABLED=False, voir conftest.py) pour ne
pas avoir à extraire un jeton dans chaque test de formulaire ; réactivé ici
spécifiquement pour vérifier la protection elle-même."""
import re

from conftest import IDENTIFIANT_SECRETAIRE, MOT_DE_PASSE_SECRETAIRE


def test_post_sans_jeton_csrf_est_refuse(icm_app):
    icm_app.app.config["WTF_CSRF_ENABLED"] = True
    try:
        client = icm_app.app.test_client()
        reponse = client.post(
            "/connexion",
            data={"utilisateur": IDENTIFIANT_SECRETAIRE, "mot_de_passe": MOT_DE_PASSE_SECRETAIRE},
        )
        assert reponse.status_code == 400
    finally:
        icm_app.app.config["WTF_CSRF_ENABLED"] = False


def test_post_avec_jeton_csrf_valide_est_accepte(icm_app):
    icm_app.app.config["WTF_CSRF_ENABLED"] = True
    try:
        client = icm_app.app.test_client()
        page = client.get("/connexion").get_data(as_text=True)
        correspondance = re.search(
            r'name="csrf_token" value="([^"]+)"', page
        )
        assert correspondance, "le champ csrf_token doit être présent dans le formulaire"
        jeton = correspondance.group(1)

        reponse = client.post(
            "/connexion",
            data={
                "utilisateur": IDENTIFIANT_SECRETAIRE,
                "mot_de_passe": MOT_DE_PASSE_SECRETAIRE,
                "csrf_token": jeton,
            },
        )
        assert reponse.status_code == 302
    finally:
        icm_app.app.config["WTF_CSRF_ENABLED"] = False
