# -*- coding: utf-8 -*-
"""Connexion, anti brute-force, redirection après connexion, contrôle d'accès
par rôle (login_requis / ecriture_requise) — cœur du § 13 Sécurité du README."""
import time

from conftest import (
    IDENTIFIANT_PASTEUR,
    IDENTIFIANT_SECRETAIRE,
    IDENTIFIANT_VISITEUR,
    MOT_DE_PASSE_PASTEUR,
    MOT_DE_PASSE_SECRETAIRE,
    MOT_DE_PASSE_VISITEUR,
    se_connecter,
)


def test_page_protegee_redirige_vers_connexion_si_anonyme(client):
    reponse = client.get("/")
    assert reponse.status_code == 302
    assert "/connexion" in reponse.headers["Location"]


def test_connexion_avec_bons_identifiants_ouvre_une_session(client):
    reponse = se_connecter(client, IDENTIFIANT_SECRETAIRE, MOT_DE_PASSE_SECRETAIRE)
    assert reponse.status_code == 302
    with client.session_transaction() as session:
        assert session["utilisateur"] == IDENTIFIANT_SECRETAIRE
        assert session["role"] == "secretaire"


def test_connexion_mauvais_mot_de_passe_message_generique(client):
    reponse = se_connecter(client, IDENTIFIANT_SECRETAIRE, "mauvais-mot-de-passe")
    assert reponse.status_code == 200
    assert "Identifiant ou mot de passe incorrect." in reponse.get_data(as_text=True)


def test_connexion_identifiant_inconnu_meme_message_generique(client):
    """Le message ne doit jamais indiquer si c'est l'identifiant ou le mot
    de passe qui est faux (sinon on révèle quels identifiants existent)."""
    reponse = se_connecter(client, "identifiant_qui_nexiste_pas", "peu importe")
    assert reponse.status_code == 200
    assert "Identifiant ou mot de passe incorrect." in reponse.get_data(as_text=True)


def test_deconnexion_efface_la_session(client):
    se_connecter(client, IDENTIFIANT_SECRETAIRE, MOT_DE_PASSE_SECRETAIRE)
    client.get("/deconnexion")
    with client.session_transaction() as session:
        assert "utilisateur" not in session
    reponse = client.get("/")
    assert reponse.status_code == 302
    assert "/connexion" in reponse.headers["Location"]


def test_anti_brute_force_bloque_apres_cinq_echecs(client, icm_app):
    for _ in range(icm_app.TENTATIVES_MAX):
        se_connecter(client, IDENTIFIANT_SECRETAIRE, "mauvais-mot-de-passe")

    reponse = se_connecter(client, IDENTIFIANT_SECRETAIRE, MOT_DE_PASSE_SECRETAIRE)
    assert reponse.status_code == 429
    assert "Trop de tentatives" in reponse.get_data(as_text=True)


def test_anti_brute_force_ne_bloque_pas_un_autre_identifiant(client, icm_app):
    for _ in range(icm_app.TENTATIVES_MAX):
        se_connecter(client, IDENTIFIANT_SECRETAIRE, "mauvais-mot-de-passe")

    # Le verrou est par couple (IP, identifiant) : le compte pasteur reste
    # utilisable depuis la même adresse.
    reponse = se_connecter(client, IDENTIFIANT_PASTEUR, MOT_DE_PASSE_PASTEUR)
    assert reponse.status_code == 302


def test_anti_brute_force_fenetre_glissante_purge_les_anciennes_tentatives(client, icm_app):
    with icm_app.app.test_request_context("/connexion"):
        cle = icm_app._cle_limitation(IDENTIFIANT_SECRETAIRE)
        maintenant = time.monotonic()
        # 5 échecs, mais hors de la fenêtre de 15 min : ne doivent plus compter.
        for _ in range(icm_app.TENTATIVES_MAX):
            icm_app._tentatives_connexion[cle].append(
                maintenant - icm_app.FENETRE_SECONDES - 1
            )
        assert icm_app.trop_de_tentatives(IDENTIFIANT_SECRETAIRE) is False


def test_redirection_apres_connexion_chemin_interne_autorise(client):
    reponse = client.post(
        "/connexion?suivant=/journal",
        data={"utilisateur": IDENTIFIANT_SECRETAIRE, "mot_de_passe": MOT_DE_PASSE_SECRETAIRE},
    )
    assert reponse.headers["Location"] == "/journal"


def test_redirection_apres_connexion_rejette_url_absolue(client, icm_app):
    """Protection anti-hameçonnage : `suivant` ne doit jamais pointer vers
    un autre site, même si l'utilisateur clique un lien de connexion piégé."""
    reponse = client.post(
        "/connexion?suivant=https://site-pirate.example/phishing",
        data={"utilisateur": IDENTIFIANT_SECRETAIRE, "mot_de_passe": MOT_DE_PASSE_SECRETAIRE},
    )
    assert "site-pirate.example" not in reponse.headers["Location"]


def test_redirection_apres_connexion_rejette_double_slash(client):
    """`//exemple.com` est traité par les navigateurs comme une URL absolue
    (même protocole), donc une redirection ouverte au même titre."""
    reponse = client.post(
        "/connexion?suivant=//site-pirate.example",
        data={"utilisateur": IDENTIFIANT_SECRETAIRE, "mot_de_passe": MOT_DE_PASSE_SECRETAIRE},
    )
    assert "site-pirate.example" not in reponse.headers["Location"]


def test_redirection_apres_connexion_rejette_antislash(client):
    reponse = client.post(
        "/connexion?suivant=/\\site-pirate.example",
        data={"utilisateur": IDENTIFIANT_SECRETAIRE, "mot_de_passe": MOT_DE_PASSE_SECRETAIRE},
    )
    assert "site-pirate.example" not in reponse.headers["Location"]


def test_destination_sure_fonction_directe(icm_app):
    sure = icm_app._destination_sure
    assert sure("/journal") == "/journal"
    assert sure("") is None
    assert sure(None) is None
    assert sure("http://site-pirate.example") is None
    assert sure("//site-pirate.example") is None
    assert sure("/\\site-pirate.example") is None


def test_visiteur_peut_consulter_le_registre(client_visiteur):
    reponse = client_visiteur.get("/")
    assert reponse.status_code == 200


def test_visiteur_ne_peut_pas_creer_une_fiche(client_visiteur):
    reponse = client_visiteur.get("/nouveau")
    assert reponse.status_code == 302
    assert reponse.headers["Location"].endswith("/") or reponse.headers["Location"] == "/"


def test_visiteur_ne_peut_pas_creer_une_fiche_meme_par_url_directe_post(client_visiteur, icm_app):
    """Le contrôle doit être fait côté serveur, pas seulement en cachant les
    boutons : un POST direct doit aussi être refusé pour un visiteur, et ne
    doit rien écrire en base."""
    reponse = client_visiteur.post(
        "/nouveau",
        data={"nom": "Dupont", "prenom": "Jean"},
        follow_redirects=True,
    )
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.Registre.query.count() == 0


def test_secretaire_et_pasteur_peuvent_creer_une_fiche(client_secretaire, client_pasteur):
    for client_role, prenom in ((client_secretaire, "Alice"), (client_pasteur, "Bob")):
        reponse = client_role.post(
            "/nouveau",
            data={"nom": "Test", "prenom": prenom},
            follow_redirects=False,
        )
        assert reponse.status_code == 302
