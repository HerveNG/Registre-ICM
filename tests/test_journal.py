# -*- coding: utf-8 -*-
"""Journal d'audit : une entrée par création/modification/suppression,
lecture ouverte aux trois rôles, jamais modifiable depuis l'application."""


def test_creation_journalisee(client_secretaire, icm_app):
    client_secretaire.post("/nouveau", data={"nom": "Traçable", "prenom": "Test"})
    with icm_app.app.app_context():
        entree = icm_app.JournalAudit.query.filter_by(action="creation").one()
        # "Traçable" saisi devient "TRAÇABLE" une fois normalisé (voir
        # normaliser_casse) — le journal reflète la valeur réellement stockée.
        assert entree.nom_complet == "TRAÇABLE Test"
        assert entree.utilisateur


def test_suppression_journalisee_avec_nom_conserve(client_secretaire, icm_app):
    with icm_app.app.app_context():
        fiche = icm_app.Registre(nom="Effacee", prenom="Test")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()
        id_fiche = fiche.id

    client_secretaire.post(f"/supprimer/{id_fiche}")

    with icm_app.app.app_context():
        entree = icm_app.JournalAudit.query.filter_by(
            registre_id=id_fiche, action="suppression"
        ).one()
        # La fiche n'existe plus, mais le journal garde son nom en instantané.
        assert entree.nom_complet == "Effacee Test"
        assert icm_app.db.session.get(icm_app.Registre, id_fiche) is None


def test_modification_sans_changement_ne_journalise_rien(client_secretaire, icm_app):
    with icm_app.app.app_context():
        # "STABLE" (déjà en majuscules) : la valeur qu'aurait réellement la
        # fiche si elle avait été créée via le formulaire, une fois passée
        # par normaliser_casse — voir test_normalisation_casse.py.
        fiche = icm_app.Registre(nom="STABLE", prenom="Test")
        icm_app.db.session.add(fiche)
        icm_app.db.session.commit()
        id_fiche = fiche.id

    # Renvoie la même valeur ("Stable" redevient "STABLE" une fois normalisé) :
    # aucun changement réel, donc rien à journaliser.
    client_secretaire.post(f"/modifier/{id_fiche}", data={"nom": "Stable", "prenom": "Test"})

    with icm_app.app.app_context():
        assert icm_app.JournalAudit.query.filter_by(
            registre_id=id_fiche, action="modification"
        ).count() == 0


def test_journal_accessible_aux_trois_roles(client_secretaire, client_pasteur, client_visiteur):
    for client_role in (client_secretaire, client_pasteur, client_visiteur):
        reponse = client_role.get("/journal")
        assert reponse.status_code == 200


def test_journal_refuse_les_anonymes(client):
    reponse = client.get("/journal")
    assert reponse.status_code == 302
    assert "/connexion" in reponse.headers["Location"]


def test_aucune_route_ne_permet_de_modifier_le_journal(icm_app):
    """Filet de sécurité contre une régression future : aucune règle d'URL
    de l'application ne doit cibler JournalAudit en écriture."""
    routes_ecriture = {
        str(regle) for regle in icm_app.app.url_map.iter_rules()
        if regle.methods and {"POST", "PUT", "PATCH", "DELETE"} & regle.methods
    }
    for route in routes_ecriture:
        assert "journal" not in route.lower() or route == "/journal"
