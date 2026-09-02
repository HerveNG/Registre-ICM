# -*- coding: utf-8 -*-
"""Fixtures partagées pour les tests de la version Flask (app.py).

Ce fichier configure l'application AVANT même de l'importer : app.py lit
plusieurs variables d'environnement au niveau du module (SECRET_KEY, comptes,
DATABASE_URL...), donc tout doit être en place avant le premier `import app`.
Comme app.py crée les tables (`db.create_all()`) dès son import, chaque
session de tests pointe vers un fichier SQLite temporaire dédié — jamais
vers `registre.db`, le fichier utilisé par l'application réelle.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

RACINE_DEPOT = Path(__file__).resolve().parent.parent
if str(RACINE_DEPOT) not in sys.path:
    sys.path.insert(0, str(RACINE_DEPOT))

# Identifiants de test pour les trois rôles — jamais utilisés en dehors des
# tests (voir la fixture `_environnement_app`, qui les injecte avant import).
IDENTIFIANT_SECRETAIRE = "test_secretaire"
MOT_DE_PASSE_SECRETAIRE = "un-mot-de-passe-de-test-suffisamment-long"
IDENTIFIANT_PASTEUR = "test_pasteur"
MOT_DE_PASSE_PASTEUR = "un-autre-mot-de-passe-de-test"
IDENTIFIANT_VISITEUR = "test_visiteur"
MOT_DE_PASSE_VISITEUR = "encore-un-mot-de-passe-de-test"


@pytest.fixture(scope="session", autouse=True)
def _environnement_app(tmp_path_factory):
    """Prépare les variables d'environnement lues par app.py au moment de
    son import, avant que quoi que ce soit d'autre ne l'importe."""
    dossier = tmp_path_factory.mktemp("registre_test_db")
    base_sqlite = dossier / "registre_test.db"

    os.environ["SECRET_KEY"] = "cle-de-test-non-utilisee-en-production-0123456789"
    os.environ["FLASK_DEBUG"] = "0"
    os.environ["FORCER_HTTPS"] = "0"  # le client de test Flask n'est pas en HTTPS
    os.environ["DATABASE_URL"] = f"sqlite:///{base_sqlite}"
    os.environ["PAROISSE"] = "Paroisse de test"

    os.environ["ADMIN_USER"] = IDENTIFIANT_SECRETAIRE
    os.environ["ADMIN_PASSWORD"] = MOT_DE_PASSE_SECRETAIRE
    os.environ["PASTEUR_USER"] = IDENTIFIANT_PASTEUR
    os.environ["PASTEUR_PASSWORD"] = MOT_DE_PASSE_PASTEUR
    os.environ["VISITEUR_USER"] = IDENTIFIANT_VISITEUR
    os.environ["VISITEUR_PASSWORD"] = MOT_DE_PASSE_VISITEUR

    # Ne jamais laisser les tests écrire dans .env s'il existe déjà un
    # fichier .env local (python-dotenv le chargerait sinon en premier et
    # écraserait les valeurs ci-dessus selon l'ordre de chargement).
    os.environ.pop("DATABASE_URL_OVERRIDE", None)


@pytest.fixture(scope="session")
def icm_app(_environnement_app):
    """Importe app.py une seule fois par session de tests (import = création
    du Flask app + `db.create_all()`), puis le configure pour les tests."""
    import app as module_app  # import différé : dépend de _environnement_app

    module_app.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,  # réactivé explicitement dans test_csrf.py
        SERVER_NAME="localhost",
    )
    return module_app


@pytest.fixture(autouse=True)
def _base_propre(icm_app):
    """Vide les tables entre chaque test et réinitialise le limiteur de
    tentatives de connexion (en mémoire, sinon un test de brute-force
    pourrait faire échouer les tests suivants utilisant le même identifiant).

    ServiceType et AttendanceCategory ne sont volontairement PAS vidées : ce
    sont des données de configuration semées une seule fois par session
    (comme les comptes), pas des données de test transactionnelles — voir
    tests/test_presences.py, qui n'en dépend qu'en lecture ou en ajoutant
    de nouvelles entrées plutôt qu'en mutant les entrées par défaut."""
    yield
    with icm_app.app.app_context():
        icm_app.AttendanceValue.query.delete()
        icm_app.AttendanceRecord.query.delete()
        icm_app.JournalAudit.query.delete()
        icm_app.Registre.query.delete()
        icm_app.db.session.commit()
    icm_app._tentatives_connexion.clear()


@pytest.fixture
def dossier_photos(icm_app, tmp_path, monkeypatch):
    """Redirige DOSSIER_PHOTOS vers un dossier temporaire : les tests ne
    doivent jamais écrire dans le dossier `photos/` réel du dépôt."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    monkeypatch.setattr(icm_app, "DOSSIER_PHOTOS", str(dossier))
    return dossier


@pytest.fixture
def client(icm_app):
    return icm_app.app.test_client()


def se_connecter(client, identifiant, mot_de_passe):
    return client.post(
        "/connexion",
        data={"utilisateur": identifiant, "mot_de_passe": mot_de_passe},
        follow_redirects=False,
    )


@pytest.fixture
def client_secretaire(client):
    se_connecter(client, IDENTIFIANT_SECRETAIRE, MOT_DE_PASSE_SECRETAIRE)
    return client


@pytest.fixture
def client_pasteur(client):
    se_connecter(client, IDENTIFIANT_PASTEUR, MOT_DE_PASSE_PASTEUR)
    return client


@pytest.fixture
def client_visiteur(client):
    se_connecter(client, IDENTIFIANT_VISITEUR, MOT_DE_PASSE_VISITEUR)
    return client
