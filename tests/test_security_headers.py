# -*- coding: utf-8 -*-
"""En-têtes de sécurité HTTP appliqués à toutes les réponses
(ajouter_entetes_securite, dans app.py)."""


def test_entetes_securite_presents_sur_page_publique(client):
    reponse = client.get("/connexion")
    assert reponse.headers["X-Frame-Options"] == "DENY"
    assert reponse.headers["X-Content-Type-Options"] == "nosniff"
    assert reponse.headers["Referrer-Policy"] == "same-origin"
    assert "default-src 'self'" in reponse.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in reponse.headers["Content-Security-Policy"]


def test_entetes_securite_presents_apres_connexion(client_secretaire):
    reponse = client_secretaire.get("/")
    assert reponse.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in reponse.headers


def test_pas_de_hsts_quand_forcer_https_desactive(client, icm_app):
    """FORCER_HTTPS=0 en test (voir conftest) : l'en-tête HSTS ne doit pas
    être envoyé, sinon un déploiement HTTP simple deviendrait inutilisable
    (le navigateur refuserait ensuite tout accès en clair)."""
    assert icm_app.FORCER_HTTPS is False
    reponse = client.get("/connexion")
    assert "Strict-Transport-Security" not in reponse.headers


def test_page_erreur_404_generique_sans_details_techniques(client_secretaire):
    reponse = client_secretaire.get("/carte/999999")
    assert reponse.status_code == 404
    corps = reponse.get_data(as_text=True)
    assert "Page ou enregistrement introuvable." in corps
    # Rien qui ressemble à une trace Python/SQL ne doit fuiter dans la page.
    for indice_technique in ("Traceback", "sqlalchemy", "File \"", "line "):
        assert indice_technique not in corps
