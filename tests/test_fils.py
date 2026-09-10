# -*- coding: utf-8 -*-
"""Module Fils : CRUD, recherche/filtres, import Excel/CSV, activités et
pointage, historique/statistiques, export, et RBAC (mêmes rôles que le
reste de l'application — voir test_auth.py/test_presences.py : les trois
rôles écrivent, seule la suppression définitive reste réservée
secrétaire/pasteur, bloquée en plus si le fils a un historique de présence).
"""
import io


def _creer_fils(icm_app, nom="Mballa", prenom="Jean", ville="Yaoundé",
                 telephone="677123456", genre="M", statut="active"):
    with icm_app.app.app_context():
        f = icm_app.Fils(nom=nom, prenom=prenom, ville=ville,
                          telephone=telephone, genre=genre, statut=statut)
        icm_app.db.session.add(f)
        icm_app.db.session.commit()
        return f.id


def _id_type_reunion_des_fils(icm_app):
    with icm_app.app.app_context():
        return icm_app.ServiceType.query.filter_by(nom="Réunion des fils").one().id


def _creer_activite(icm_app, date_activite="2026-09-06"):
    with icm_app.app.app_context():
        from datetime import date as _date
        a = icm_app.FilsActivite(
            date_activite=_date.fromisoformat(date_activite),
            service_type_id=_id_type_reunion_des_fils(icm_app))
        icm_app.db.session.add(a)
        icm_app.db.session.commit()
        return a.id


# ------------------------------------------------------------------
#  Données de départ
# ------------------------------------------------------------------
def test_reunion_des_fils_semee_par_defaut(icm_app):
    with icm_app.app.app_context():
        noms = {t.nom for t in icm_app.ServiceType.query.all()}
        assert "Réunion des fils" in noms


# ------------------------------------------------------------------
#  CRUD
# ------------------------------------------------------------------
def test_creer_un_fils(client_secretaire, icm_app):
    reponse = client_secretaire.post("/fils/nouveau", data={
        "nom": "ateba", "prenom": "marie", "ville": "douala",
        "telephone": "691-23.45 67", "genre": "F", "statut": "active",
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        f = icm_app.Fils.query.one()
        assert f.nom == "ATEBA"          # casse imposée (majuscules)
        assert f.prenom == "Marie"       # casse imposée (capitalisée)
        assert f.ville == "Douala"
        assert f.telephone == "691234567"   # nettoyé (espaces/tirets/points retirés)
        assert f.genre == "F"


def test_nom_et_prenom_obligatoires(client_secretaire, icm_app):
    reponse = client_secretaire.post("/fils/nouveau", data={"nom": "", "prenom": "", "genre": "M"})
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.Fils.query.count() == 0


def test_genre_obligatoire(client_secretaire, icm_app):
    reponse = client_secretaire.post("/fils/nouveau", data={"nom": "X", "prenom": "Y"})
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.Fils.query.count() == 0


def test_modifier_un_fils(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    reponse = client_secretaire.post(f"/fils/{id_fils}/modifier", data={
        "nom": "Mballa", "prenom": "Jean", "ville": "Douala",
        "telephone": "699000000", "genre": "M", "statut": "inactive",
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        f = icm_app.db.session.get(icm_app.Fils, id_fils)
        assert f.ville == "Douala"
        assert f.statut == "inactive"


def test_supprimer_un_fils_sans_historique(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    reponse = client_secretaire.post(f"/fils/{id_fils}/supprimer")
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.Fils, id_fils) is None


def test_supprimer_un_fils_avec_historique_refuse(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    id_activite = _creer_activite(icm_app)
    with icm_app.app.app_context():
        icm_app.db.session.add(icm_app.FilsPresence(
            fils_id=id_fils, activite_id=id_activite, statut="P"))
        icm_app.db.session.commit()

    reponse = client_secretaire.post(f"/fils/{id_fils}/supprimer", follow_redirects=True)
    assert b"Impossible de supprimer" in reponse.data
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.Fils, id_fils) is not None


def test_fils_inexistant_renvoie_404(client_secretaire):
    assert client_secretaire.get("/fils/999999").status_code == 404
    assert client_secretaire.get("/fils/999999/modifier").status_code == 404


# ------------------------------------------------------------------
#  Liste — recherche, filtres
# ------------------------------------------------------------------
def test_recherche_et_filtres(client_secretaire, icm_app):
    _creer_fils(icm_app, nom="Ateba", prenom="Marie", ville="Douala", telephone="1", genre="F")
    _creer_fils(icm_app, nom="Fotso", prenom="Paul", ville="Bafoussam", telephone="2", genre="M")

    assert b"Ateba" in client_secretaire.get("/fils?q=ateba").data
    assert b"Fotso" not in client_secretaire.get("/fils?q=ateba").data
    assert b"Ateba" in client_secretaire.get("/fils?ville=Douala").data
    assert b"Fotso" not in client_secretaire.get("/fils?ville=Douala").data
    assert b"Ateba" in client_secretaire.get("/fils?genre=F").data
    assert b"Fotso" not in client_secretaire.get("/fils?genre=F").data


# ------------------------------------------------------------------
#  Import Excel/CSV
# ------------------------------------------------------------------
def _fichier_csv(contenu):
    return {"fichier": (io.BytesIO(contenu.encode("utf-8-sig")), "fils.csv")}


def test_import_reconnait_synonymes_dentetes(client_secretaire, icm_app):
    contenu = "Nom;Prenom;Ville;TEL;SEXE\nMballa;Jean;Yaounde;677123456;M\n"
    reponse = client_secretaire.post("/fils/importer", data=_fichier_csv(contenu),
                                      content_type="multipart/form-data")
    assert reponse.status_code == 200
    assert b"1 ligne(s) pr\xc3\xaate(s) \xc3\xa0 importer" in reponse.data
    with icm_app.app.app_context():
        assert icm_app.Fils.query.count() == 0   # étape d'aperçu seulement


def test_import_detecte_doublon_intra_fichier_et_avec_la_base(client_secretaire, icm_app):
    _creer_fils(icm_app, nom="Mballa", prenom="Jean", telephone="677123456")
    contenu = (
        "Nom;Prenom;Ville;Telephone;Genre\n"
        "Ateba;Marie;Douala;691234567;F\n"
        "Ateba;Marie;Douala;691234567;F\n"     # doublon intra-fichier
        "Mballa;Jean;Yaounde;677123456;M\n"    # doublon avec la base
    )
    reponse = client_secretaire.post("/fils/importer", data=_fichier_csv(contenu),
                                      content_type="multipart/form-data")
    assert reponse.status_code == 200
    assert b"1 ligne(s) pr\xc3\xaate(s)" in reponse.data
    assert b"2 ligne(s) en erreur" in reponse.data
    assert "utilisé aussi à la ligne".encode() in reponse.data
    assert "existe déjà".encode() in reponse.data


def test_import_colonnes_essentielles_manquantes(client_secretaire):
    contenu = "Ville;Telephone\nDouala;691234567\n"
    reponse = client_secretaire.post("/fils/importer", data=_fichier_csv(contenu),
                                      content_type="multipart/form-data")
    assert reponse.status_code == 302   # redirigé avec message d'erreur, rien à afficher


def test_import_confirmation_ecrit_seulement_les_lignes_valides(client_secretaire, icm_app):
    contenu = "Nom;Prenom;Ville;Telephone;Genre\nMballa;Jean;Yaounde;677123456;M\n"
    client_secretaire.post("/fils/importer", data=_fichier_csv(contenu),
                            content_type="multipart/form-data")
    with icm_app.app.app_context():
        donnees_json = [{"numero_ligne": 2,
                          "donnees": {"nom": "MBALLA", "prenom": "Jean", "ville": "Yaounde",
                                      "telephone": "677123456", "genre": "M"}}]
    import json as _json
    reponse = client_secretaire.post("/fils/importer", data={
        "etape": "confirmer", "donnees_json": _json.dumps(donnees_json),
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.Fils.query.count() == 1


def test_modele_import_fils_telechargeable(client_secretaire):
    reponse = client_secretaire.get("/fils/importer/modele.csv")
    assert reponse.status_code == 200
    assert reponse.mimetype == "text/csv"
    contenu = reponse.data.decode("utf-8-sig")
    assert "Nom;Prénom;Ville;Téléphone;Genre" in contenu


# ------------------------------------------------------------------
#  Activités & pointage
# ------------------------------------------------------------------
def test_creer_une_activite(client_secretaire, icm_app):
    id_type = _id_type_reunion_des_fils(icm_app)
    reponse = client_secretaire.post("/fils/activites", data={
        "date_activite": "2026-09-06", "service_type_id": str(id_type),
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.FilsActivite.query.count() == 1


def test_supprimer_une_activite_sans_presences(client_secretaire, icm_app):
    id_activite = _creer_activite(icm_app)
    reponse = client_secretaire.post(f"/fils/activites/{id_activite}/supprimer")
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.FilsActivite, id_activite) is None


def test_supprimer_une_activite_avec_presences_refuse(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    id_activite = _creer_activite(icm_app)
    with icm_app.app.app_context():
        icm_app.db.session.add(icm_app.FilsPresence(
            fils_id=id_fils, activite_id=id_activite, statut="P"))
        icm_app.db.session.commit()

    reponse = client_secretaire.post(f"/fils/activites/{id_activite}/supprimer", follow_redirects=True)
    assert b"Impossible de supprimer" in reponse.data
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.FilsActivite, id_activite) is not None


def test_visiteur_ne_peut_pas_supprimer_une_activite(client_visiteur, icm_app):
    id_activite = _creer_activite(icm_app)
    reponse = client_visiteur.post(f"/fils/activites/{id_activite}/supprimer")
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.FilsActivite, id_activite) is not None


def test_pointage_groupe_enregistre_tous_les_statuts(client_secretaire, icm_app):
    id_present = _creer_fils(icm_app, nom="Mballa", prenom="Jean", telephone="1")
    id_absent = _creer_fils(icm_app, nom="Ateba", prenom="Marie", telephone="2", genre="F")
    id_activite = _creer_activite(icm_app)

    reponse = client_secretaire.post(f"/fils/activites/{id_activite}/pointage", data={
        f"statut_{id_present}": "P", f"statut_{id_absent}": "A",
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        presences = {p.fils_id: p.statut for p in
                     icm_app.FilsPresence.query.filter_by(activite_id=id_activite).all()}
        assert presences[id_present] == "P"
        assert presences[id_absent] == "A"


def test_pointage_corrige_un_statut_deja_enregistre(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    id_activite = _creer_activite(icm_app)
    client_secretaire.post(f"/fils/activites/{id_activite}/pointage",
                            data={f"statut_{id_fils}": "P"})
    client_secretaire.post(f"/fils/activites/{id_activite}/pointage",
                            data={f"statut_{id_fils}": "A"})
    with icm_app.app.app_context():
        assert icm_app.FilsPresence.query.filter_by(
            fils_id=id_fils, activite_id=id_activite).one().statut == "A"
        # Une seule ligne (corrigée), pas un doublon.
        assert icm_app.FilsPresence.query.filter_by(activite_id=id_activite).count() == 1


def test_pointage_ignore_les_fils_inactifs(client_secretaire, icm_app):
    _creer_fils(icm_app, nom="Inactif", prenom="Test", telephone="9", statut="inactive")
    id_activite = _creer_activite(icm_app)
    reponse = client_secretaire.get(f"/fils/activites/{id_activite}/pointage")
    assert b"Inactif" not in reponse.data


# ------------------------------------------------------------------
#  Historique et statistiques
# ------------------------------------------------------------------
def test_historique_et_taux_sur_la_fiche(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    id_activite = _creer_activite(icm_app)
    with icm_app.app.app_context():
        icm_app.db.session.add(icm_app.FilsPresence(
            fils_id=id_fils, activite_id=id_activite, statut="P"))
        icm_app.db.session.commit()

    reponse = client_secretaire.get(f"/fils/{id_fils}")
    assert reponse.status_code == 200
    assert "100.0 %".encode() in reponse.data


def test_statistiques_periode_tout(client_secretaire, icm_app):
    id_fils = _creer_fils(icm_app)
    id_activite = _creer_activite(icm_app)
    with icm_app.app.app_context():
        icm_app.db.session.add(icm_app.FilsPresence(
            fils_id=id_fils, activite_id=id_activite, statut="P"))
        icm_app.db.session.commit()

    reponse = client_secretaire.get("/fils/statistiques?periode=tout")
    assert reponse.status_code == 200
    assert b"1" in reponse.data


# ------------------------------------------------------------------
#  Export
# ------------------------------------------------------------------
def test_export_csv_fils(client_secretaire, icm_app):
    _creer_fils(icm_app)
    reponse = client_secretaire.get("/fils/export.csv")
    assert reponse.status_code == 200
    assert reponse.mimetype == "text/csv"
    contenu = reponse.data.decode("utf-8-sig")
    assert "Mballa" in contenu


# ------------------------------------------------------------------
#  RBAC — mêmes règles que le reste de l'application
# ------------------------------------------------------------------
def test_visiteur_peut_consulter_creer_et_importer(client_visiteur, icm_app):
    assert client_visiteur.get("/fils").status_code == 200
    assert client_visiteur.get("/fils/nouveau").status_code == 200
    reponse = client_visiteur.post("/fils/nouveau", data={
        "nom": "Visiteur", "prenom": "Test", "genre": "M",
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.Fils.query.filter_by(nom="VISITEUR").count() == 1


def test_visiteur_ne_peut_pas_supprimer_un_fils(client_visiteur, icm_app):
    id_fils = _creer_fils(icm_app)
    reponse = client_visiteur.post(f"/fils/{id_fils}/supprimer")
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.Fils, id_fils) is not None


def test_pasteur_a_les_memes_droits_que_secretaire(client_pasteur, icm_app):
    reponse = client_pasteur.post("/fils/nouveau", data={
        "nom": "Pasteur", "prenom": "Test", "genre": "F",
    })
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.Fils.query.count() == 1
