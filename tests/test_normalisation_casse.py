# -*- coding: utf-8 -*-
"""Casse imposée à certains champs texte (normaliser_casse), et son
application à la saisie manuelle (collecter_formulaire) comme à l'import de
fichier (donnees_depuis_ligne) — quelle que soit la façon dont l'utilisateur
a tapé le texte (tout en majuscules, tout en minuscules, mélangé)."""


def test_majuscules_sur_les_champs_identite_et_lieux(icm_app):
    champs = (
        "nom", "nom_pere", "nom_mere",
        "lieu_bapteme", "celebrant_bapteme",
        "lieu_mariage", "celebrant_mariage",
    )
    for champ in champs:
        assert icm_app.normaliser_casse(champ, "ngooh mvondo") == "NGOOH MVONDO"
        assert icm_app.normaliser_casse(champ, "Ngooh Mvondo") == "NGOOH MVONDO"
        assert icm_app.normaliser_casse(champ, "NGOOH mvondo") == "NGOOH MVONDO"


def test_premiere_lettre_majuscule_sur_prenom_nationalite_origine(icm_app):
    champs = ("prenom", "nationalite", "originaire_de")
    for champ in champs:
        assert icm_app.normaliser_casse(champ, "HERVÉ") == "Hervé"
        assert icm_app.normaliser_casse(champ, "hervé") == "Hervé"
        assert icm_app.normaliser_casse(champ, "hERvé") == "Hervé"


def test_champs_sans_regle_de_casse_restent_inchanges(icm_app):
    assert icm_app.normaliser_casse("telephone", "0612345678") == "0612345678"
    assert icm_app.normaliser_casse("signature_1", "Past. Jean ETOUNDI") == "Past. Jean ETOUNDI"
    assert icm_app.normaliser_casse("observations", "Rien à signaler") == "Rien à signaler"


def test_valeur_vide_ou_none_inchangee(icm_app):
    assert icm_app.normaliser_casse("nom", None) is None
    assert icm_app.normaliser_casse("nom", "") == ""


def test_collecter_formulaire_normalise_la_casse_a_la_saisie(icm_app):
    donnees, erreurs = icm_app.collecter_formulaire({
        "nom": "ngooh", "prenom": "HERVÉ", "nom_pere": "ngooh paul",
        "nom_mere": "MBALLA marie", "nationalite": "CAMEROUNAISE",
        "originaire_de": "YAOUNDÉ", "lieu_bapteme": "temple icm douala",
        "celebrant_bapteme": "past. jean etoundi",
        "lieu_mariage": "temple icm yaoundé", "celebrant_mariage": "PAST. paul essomba",
    })
    assert erreurs == []
    assert donnees["nom"] == "NGOOH"
    assert donnees["prenom"] == "Hervé"
    assert donnees["nom_pere"] == "NGOOH PAUL"
    assert donnees["nom_mere"] == "MBALLA MARIE"
    assert donnees["nationalite"] == "Camerounaise"
    assert donnees["originaire_de"] == "Yaoundé"
    assert donnees["lieu_bapteme"] == "TEMPLE ICM DOUALA"
    assert donnees["celebrant_bapteme"] == "PAST. JEAN ETOUNDI"
    assert donnees["lieu_mariage"] == "TEMPLE ICM YAOUNDÉ"
    assert donnees["celebrant_mariage"] == "PAST. PAUL ESSOMBA"


def test_donnees_depuis_ligne_normalise_aussi_a_limport(icm_app):
    donnees = icm_app.donnees_depuis_ligne({
        "nom": "dupont", "prenom": "alice", "lieu_bapteme": "temple icm douala",
    })
    assert donnees["nom"] == "DUPONT"
    assert donnees["prenom"] == "Alice"
    assert donnees["lieu_bapteme"] == "TEMPLE ICM DOUALA"
