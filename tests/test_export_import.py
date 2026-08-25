# -*- coding: utf-8 -*-
"""Export CSV (neutralisation de l'injection de formule) et import du
registre papier (.csv) : reconnaissance des en-têtes, doublons, validation."""
import io

from conftest import IDENTIFIANT_VISITEUR, MOT_DE_PASSE_VISITEUR


def test_neutraliser_formule_prefixe_les_caracteres_dangereux(icm_app):
    for valeur in ("=CMD('calc')", "+1+1", "-1-1", "@SUM(A1)", "\ttabulation"):
        resultat = icm_app.neutraliser_formule(valeur)
        assert resultat.startswith("'")
        assert resultat[1:] == valeur


def test_neutraliser_formule_laisse_le_texte_normal_intact(icm_app):
    assert icm_app.neutraliser_formule("Jean Dupont") == "Jean Dupont"
    assert icm_app.neutraliser_formule(None) is None


def test_export_csv_neutralise_une_observation_piegee(client_secretaire, icm_app):
    with icm_app.app.app_context():
        icm_app.db.session.add(icm_app.Registre(
            nom="Cible", prenom="Test", observations="=HYPERLINK(\"http://evil\")",
        ))
        icm_app.db.session.commit()

    reponse = client_secretaire.get("/export.csv")
    assert reponse.status_code == 200
    corps = reponse.get_data(as_text=True)
    assert "'=HYPERLINK" in corps
    assert "﻿" in corps  # BOM pour l'affichage correct des accents dans Excel


def test_export_csv_refuse_a_un_visiteur(client_visiteur):
    reponse = client_visiteur.get("/export.csv")
    assert reponse.status_code == 302


def test_lire_fichier_import_rejette_format_inconnu(icm_app):
    class FauxFichier:
        filename = "registre.pdf"

    lignes, colonnes, erreur = icm_app.lire_fichier_import(FauxFichier())
    assert lignes is None
    assert "Format non reconnu" in erreur


def test_lire_fichier_import_csv_reconnait_les_entetes(icm_app):
    contenu = "Nom;Prénom;Date de naissance\nDupont;Alice;12/04/1990\n"

    class FauxFichier:
        filename = "registre.csv"

        def read(self_inner):
            return contenu.encode("utf-8-sig")

    lignes, colonnes_ignorees, erreur = icm_app.lire_fichier_import(FauxFichier())
    assert erreur is None
    assert len(lignes) == 1
    assert lignes[0]["nom"] == "Dupont"
    assert lignes[0]["prenom"] == "Alice"


def test_lire_fichier_import_csv_sans_colonnes_essentielles(icm_app):
    contenu = "Colonne inconnue;Autre colonne\nX;Y\n"

    class FauxFichier:
        filename = "registre.csv"

        def read(self_inner):
            return contenu.encode("utf-8")

    lignes, colonnes, erreur = icm_app.lire_fichier_import(FauxFichier())
    assert lignes is None
    assert "introuvables" in erreur


def test_analyser_lignes_detecte_doublon_dans_le_meme_fichier(icm_app):
    with icm_app.app.app_context():
        donnees_1 = {"nom": "A", "prenom": "B", "numero_registre_1": "ICM-B-2026-0001"}
        donnees_2 = {"nom": "C", "prenom": "D", "numero_registre_1": "ICM-B-2026-0001"}
        for d in (donnees_1, donnees_2):
            d.setdefault("date_naissance", None)
            d.setdefault("date_bapteme", None)
            d.setdefault("date_mariage", None)

        resultats = icm_app.analyser_lignes([(2, donnees_1), (3, donnees_2)])
        assert resultats[0]["erreurs"] == []
        assert any("aussi à la ligne 2" in e for e in resultats[1]["erreurs"])


def test_route_importer_refusee_a_un_visiteur(client_visiteur):
    donnees = {
        "fichier": (io.BytesIO(b"Nom;Prenom\nA;B\n"), "fichier.csv"),
    }
    reponse = client_visiteur.post(
        "/importer", data=donnees, content_type="multipart/form-data"
    )
    assert reponse.status_code == 302


def test_route_importer_analyse_puis_necessite_confirmation(client_secretaire, icm_app):
    contenu = "Nom;Prénom\nDupont;Alice\n"
    donnees = {"fichier": (io.BytesIO(contenu.encode("utf-8-sig")), "fichier.csv")}
    reponse = client_secretaire.post(
        "/importer", data=donnees, content_type="multipart/form-data"
    )
    assert reponse.status_code == 200
    # Rien n'est écrit tant que l'étape de confirmation n'a pas eu lieu.
    with icm_app.app.app_context():
        assert icm_app.Registre.query.count() == 0
