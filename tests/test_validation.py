# -*- coding: utf-8 -*-
"""Règles métier de validation (valider_donnees), numérotation automatique
(prochain_numero / attribuer_numeros) et unicité des numéros de registre."""
from datetime import date, timedelta

import pytest


def _donnees_minimales(**overrides):
    donnees = {
        "nom": "Ngooh", "prenom": "Hervé", "nom_pere": None, "nom_mere": None,
        "nationalite": None, "originaire_de": None, "lieu_bapteme": None,
        "numero_registre_1": None, "celebrant_bapteme": None, "signature_1": None,
        "lieu_mariage": None, "conjoint": None, "numero_registre_2": None,
        "celebrant_mariage": None, "signature_2": None, "telephone": None,
        "observations": None, "date_naissance": None, "date_bapteme": None,
        "date_mariage": None,
    }
    donnees.update(overrides)
    return donnees


def test_nom_et_prenom_obligatoires(icm_app):
    erreurs = icm_app.valider_donnees(_donnees_minimales(nom=None, prenom=None))
    assert any("nom" in e.lower() for e in erreurs)
    assert any("prénom" in e.lower() for e in erreurs)


def test_donnees_minimales_valides_sans_erreur(icm_app):
    assert icm_app.valider_donnees(_donnees_minimales()) == []


def test_champ_trop_long_est_refuse(icm_app):
    erreurs = icm_app.valider_donnees(_donnees_minimales(nom="A" * 121))
    assert any("dépasse la longueur maximale" in e for e in erreurs)


def test_champ_a_la_limite_exacte_est_accepte(icm_app):
    erreurs = icm_app.valider_donnees(_donnees_minimales(nom="A" * 120))
    assert erreurs == []


@pytest.mark.parametrize("champ", ["date_naissance", "date_bapteme", "date_mariage"])
def test_date_dans_le_futur_est_refusee(icm_app, champ):
    demain = date.today() + timedelta(days=1)
    erreurs = icm_app.valider_donnees(_donnees_minimales(**{champ: demain}))
    assert any("futur" in e for e in erreurs)


def test_bapteme_avant_naissance_est_refuse(icm_app):
    naissance = date(2000, 1, 1)
    erreurs = icm_app.valider_donnees(_donnees_minimales(
        date_naissance=naissance, date_bapteme=naissance - timedelta(days=1),
    ))
    assert any("précéder la naissance" in e for e in erreurs)


def test_mariage_avant_naissance_est_refuse(icm_app):
    naissance = date(2000, 1, 1)
    erreurs = icm_app.valider_donnees(_donnees_minimales(
        date_naissance=naissance, date_mariage=naissance - timedelta(days=1),
    ))
    assert any("précéder la naissance" in e for e in erreurs)


def test_bapteme_le_jour_de_la_naissance_est_accepte(icm_app):
    naissance = date(2000, 1, 1)
    erreurs = icm_app.valider_donnees(_donnees_minimales(
        date_naissance=naissance, date_bapteme=naissance,
    ))
    assert erreurs == []


def test_lire_date_formats_acceptes(icm_app):
    assert icm_app.lire_date("2024-06-02") == date(2024, 6, 2)
    assert icm_app.lire_date("02/06/2024") == date(2024, 6, 2)
    assert icm_app.lire_date("02-06-2024") == date(2024, 6, 2)


def test_lire_date_valeur_vide_ou_invalide(icm_app):
    assert icm_app.lire_date("") is None
    assert icm_app.lire_date(None) is None
    assert icm_app.lire_date("pas une date") is None


def test_prochain_numero_commence_a_0001(icm_app):
    with icm_app.app.app_context():
        numero = icm_app.prochain_numero("B", icm_app.Registre.numero_registre_1, 2026)
        assert numero == "ICM-B-2026-0001"


def test_prochain_numero_incremente(icm_app):
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="A", prenom="B", numero_registre_1="ICM-B-2026-0007")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()
        numero = icm_app.prochain_numero("B", icm_app.Registre.numero_registre_1, 2026)
        assert numero == "ICM-B-2026-0008"


def test_prochain_numero_ne_melange_pas_les_annees(icm_app):
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="A", prenom="B", numero_registre_1="ICM-B-2025-0099")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()
        numero = icm_app.prochain_numero("B", icm_app.Registre.numero_registre_1, 2026)
        assert numero == "ICM-B-2026-0001"


def test_attribuer_numeros_laisse_le_numero_saisi_manuellement(icm_app):
    with icm_app.app.app_context():
        donnees = _donnees_minimales(
            date_bapteme=date(2026, 1, 1), numero_registre_1="ICM-B-2026-9999",
        )
        resultat = icm_app.attribuer_numeros(donnees)
        assert resultat["numero_registre_1"] == "ICM-B-2026-9999"


def test_attribuer_numeros_sans_date_ne_genere_rien(icm_app):
    with icm_app.app.app_context():
        resultat = icm_app.attribuer_numeros(_donnees_minimales())
        assert resultat["numero_registre_1"] is None
        assert resultat["numero_registre_2"] is None


def test_verifier_unicite_detecte_un_doublon(icm_app):
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="A", prenom="B", numero_registre_1="ICM-B-2026-0001")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()

        erreurs = icm_app.verifier_unicite(
            _donnees_minimales(numero_registre_1="ICM-B-2026-0001")
        )
        assert any("existe déjà" in e for e in erreurs)


def test_verifier_unicite_exclut_la_fiche_courante(icm_app):
    """En modification, une fiche ne doit pas se trouver « en conflit » avec
    son propre numéro de registre."""
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="A", prenom="B", numero_registre_1="ICM-B-2026-0001")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()

        erreurs = icm_app.verifier_unicite(
            _donnees_minimales(numero_registre_1="ICM-B-2026-0001"),
            id_courant=fiche.id,
        )
        assert erreurs == []


def test_normaliser_entete_ignore_accents_casse_ponctuation(icm_app):
    assert icm_app.normaliser_entete("Date de Naissance") == icm_app.normaliser_entete(
        "  date   de naissance !!"
    )
    assert icm_app.normaliser_entete("Célébrant baptême") == "celebrant bapteme"
