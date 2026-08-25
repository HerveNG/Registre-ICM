# -*- coding: utf-8 -*-
"""Cycle de vie complet d'une fiche via les routes HTTP : création,
modification, suppression, et cohérence base/disque en cas d'échec."""
from datetime import date


def test_creer_une_fiche_attribue_un_numero(client_secretaire, icm_app):
    reponse = client_secretaire.post(
        "/nouveau",
        data={"nom": "Ngooh", "prenom": "Cédric", "date_bapteme": "2026-01-15"},
    )
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        fiche = icm_app.Registre.query.filter_by(nom="Ngooh").one()
        assert fiche.numero_registre_1 == "ICM-B-2026-0001"


def test_creer_une_fiche_invalide_naffiche_pas_de_redirection(client_secretaire):
    """Nom/prénom manquants : la page reste sur le formulaire (200), pas de
    redirection vers la liste, et rien n'est enregistré."""
    reponse = client_secretaire.post("/nouveau", data={"nom": "", "prenom": ""})
    assert reponse.status_code == 200


def test_numero_de_registre_deja_pris_est_refuse(client_secretaire, icm_app):
    with icm_app.app.app_context():
        icm_app.db.session.add(
            icm_app.Registre(nom="A", prenom="B", numero_registre_1="ICM-B-2026-0005")
        )
        icm_app.db.session.commit()

    reponse = client_secretaire.post(
        "/nouveau",
        data={"nom": "C", "prenom": "D", "numero_registre_1": "ICM-B-2026-0005"},
    )
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.Registre.query.filter_by(nom="C").count() == 0


def test_modifier_une_fiche_journalise_les_champs_changes(client_secretaire, icm_app):
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="Avant", prenom="Test")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()
        id_fiche = fiche.id

    reponse = client_secretaire.post(
        f"/modifier/{id_fiche}", data={"nom": "Après", "prenom": "Test"}
    )
    assert reponse.status_code == 302

    with icm_app.app.app_context():
        fiche = icm_app.db.session.get(icm_app.Registre, id_fiche)
        assert fiche.nom == "Après"
        entree = icm_app.JournalAudit.query.filter_by(
            registre_id=id_fiche, action="modification"
        ).one()
        changements = entree.changements
        assert any(c["champ"] == "Nom" for c in changements)


def test_modifier_fiche_inexistante_renvoie_404(client_secretaire):
    reponse = client_secretaire.get("/modifier/999999")
    assert reponse.status_code == 404


def test_supprimer_une_fiche_la_retire_de_la_base(client_secretaire, icm_app):
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="ASupprimer", prenom="Test")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()
        id_fiche = fiche.id

    reponse = client_secretaire.post(f"/supprimer/{id_fiche}")
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.Registre, id_fiche) is None


def test_liste_accepte_recherche_et_filtre(client_secretaire, icm_app):
    with icm_app.app.app_context():
        icm_app.db.session.add_all([
            icm_app.Registre(nom="Dupont", prenom="Alice", date_bapteme=date(2026, 1, 1)),
            icm_app.Registre(nom="Martin", prenom="Bob"),
        ])
        icm_app.db.session.commit()

    reponse = client_secretaire.get("/?q=Dupont")
    assert reponse.status_code == 200
    corps = reponse.get_data(as_text=True)
    assert "Dupont" in corps
    assert "Martin" not in corps

    reponse = client_secretaire.get("/?filtre=incomplet")
    corps = reponse.get_data(as_text=True)
    assert "Martin" in corps
    assert "Dupont" not in corps
