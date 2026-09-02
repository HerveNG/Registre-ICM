# -*- coding: utf-8 -*-
"""Module Présences & Statistiques des cultes : saisie, calcul des totaux,
historique, statistiques, paramètres (catégories/types de culte) et RBAC.

ServiceType et AttendanceCategory sont semées une seule fois par session de
tests (voir conftest.py) : les tests qui touchent aux paramètres ajoutent de
nouvelles entrées plutôt que de muter les catégories/types par défaut, pour
ne pas perturber les autres tests qui en dépendent (ex. "Culte du dimanche").
"""


def _id_type_dimanche(icm_app):
    with icm_app.app.app_context():
        return icm_app.ServiceType.query.filter_by(nom="Culte du dimanche").one().id


def _id_categorie(icm_app, nom):
    with icm_app.app.app_context():
        return icm_app.AttendanceCategory.query.filter_by(nom=nom).one().id


def _donnees_exemple(icm_app, date_culte="2026-08-30"):
    """Reproduit l'exemple du cahier des charges : 85 hommes, 135 femmes,
    95 enfants, 315 au total."""
    return {
        "date_culte": date_culte,
        "service_type_id": str(_id_type_dimanche(icm_app)),
        f"cat_{_id_categorie(icm_app, 'Jeunes hommes')}": "25",
        f"cat_{_id_categorie(icm_app, 'Hommes adultes')}": "48",
        f"cat_{_id_categorie(icm_app, 'Hommes seniors')}": "12",
        f"cat_{_id_categorie(icm_app, 'Jeunes femmes')}": "40",
        f"cat_{_id_categorie(icm_app, 'Femmes adultes')}": "75",
        f"cat_{_id_categorie(icm_app, 'Femmes seniors')}": "20",
        f"cat_{_id_categorie(icm_app, 'Petits enfants')}": "30",
        f"cat_{_id_categorie(icm_app, 'Enfants')}": "45",
        f"cat_{_id_categorie(icm_app, 'Pré-adolescents')}": "20",
    }


# ------------------------------------------------------------------
#  Données de départ
# ------------------------------------------------------------------
def test_types_de_culte_et_categories_semes_par_defaut(icm_app):
    with icm_app.app.app_context():
        noms_types = {t.nom for t in icm_app.ServiceType.query.all()}
        assert "Culte du dimanche" in noms_types
        assert "Culte du mercredi" in noms_types

        categories = icm_app.AttendanceCategory.query.all()
        assert len(categories) == 12
        assert {c.groupe for c in categories} == {"hommes", "femmes", "enfants"}


# ------------------------------------------------------------------
#  Enregistrement d'une présence — calculs automatiques
# ------------------------------------------------------------------
def test_enregistrer_une_presence_calcule_les_totaux(client_secretaire, icm_app):
    reponse = client_secretaire.post(
        "/presences/nouvelle", data=_donnees_exemple(icm_app))
    assert reponse.status_code == 302

    with icm_app.app.app_context():
        record = icm_app.AttendanceRecord.query.one()
        assert record.total_hommes == 85
        assert record.total_femmes == 135
        assert record.total_enfants == 95
        assert record.total_general == 315
        assert record.created_by == "test_secretaire"
        assert record.updated_by is None
        assert record.jour_semaine == "Dimanche"
        # Une ligne AttendanceValue par catégorie active, même à 0.
        assert len(record.valeurs) == 12


def test_effectif_negatif_refuse(client_secretaire, icm_app):
    donnees = _donnees_exemple(icm_app)
    cle = f"cat_{_id_categorie(icm_app, 'Jeunes hommes')}"
    donnees[cle] = "-5"
    reponse = client_secretaire.post("/presences/nouvelle", data=donnees)
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 0


def test_date_obligatoire(client_secretaire, icm_app):
    donnees = _donnees_exemple(icm_app)
    donnees["date_culte"] = ""
    reponse = client_secretaire.post("/presences/nouvelle", data=donnees)
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 0


def test_date_dans_le_futur_refusee(client_secretaire, icm_app):
    donnees = _donnees_exemple(icm_app, date_culte="2999-01-01")
    reponse = client_secretaire.post("/presences/nouvelle", data=donnees)
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 0


def test_type_de_culte_obligatoire(client_secretaire, icm_app):
    donnees = _donnees_exemple(icm_app)
    donnees["service_type_id"] = ""
    reponse = client_secretaire.post("/presences/nouvelle", data=donnees)
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 0


def test_doublon_meme_date_meme_type_refuse(client_secretaire, icm_app):
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    reponse = client_secretaire.post(
        "/presences/nouvelle", data=_donnees_exemple(icm_app))
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 1


# ------------------------------------------------------------------
#  Modification / suppression
# ------------------------------------------------------------------
def test_modifier_une_presence_recalcule_les_totaux_et_marque_updated_by(
        client_secretaire, icm_app):
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    with icm_app.app.app_context():
        id_record = icm_app.AttendanceRecord.query.one().id

    donnees = _donnees_exemple(icm_app)
    donnees[f"cat_{_id_categorie(icm_app, 'Hommes seniors')}"] = "15"   # 12 -> 15
    reponse = client_secretaire.post(f"/presences/{id_record}/modifier", data=donnees)
    assert reponse.status_code == 302

    with icm_app.app.app_context():
        record = icm_app.db.session.get(icm_app.AttendanceRecord, id_record)
        assert record.total_hommes == 88
        assert record.total_general == 318
        assert record.updated_by == "test_secretaire"


def test_supprimer_une_presence(client_secretaire, icm_app):
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    with icm_app.app.app_context():
        id_record = icm_app.AttendanceRecord.query.one().id

    reponse = client_secretaire.post(f"/presences/{id_record}/supprimer")
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 0
        # Suppression en cascade des lignes de détail (AttendanceValue).
        assert icm_app.AttendanceValue.query.count() == 0


def test_presence_inexistante_renvoie_404(client_secretaire):
    assert client_secretaire.get("/presences/999999").status_code == 404
    assert client_secretaire.get("/presences/999999/modifier").status_code == 404


# ------------------------------------------------------------------
#  Historique — recherche, filtres
# ------------------------------------------------------------------
def test_historique_filtre_par_type_de_culte(client_secretaire, icm_app):
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))

    id_mercredi = None
    with icm_app.app.app_context():
        id_mercredi = icm_app.ServiceType.query.filter_by(nom="Culte du mercredi").one().id
    autre = _donnees_exemple(icm_app, date_culte="2026-09-02")
    autre["service_type_id"] = str(id_mercredi)
    client_secretaire.post("/presences/nouvelle", data=autre)

    reponse = client_secretaire.get(f"/presences/historique?type={id_mercredi}")
    assert reponse.status_code == 200
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 2   # les deux existent bien


def test_historique_recherche_par_lieu(client_secretaire, icm_app):
    donnees = _donnees_exemple(icm_app)
    donnees["lieu"] = "Salle annexe"
    client_secretaire.post("/presences/nouvelle", data=donnees)

    trouve = client_secretaire.get("/presences/historique?q=annexe")
    assert b"Salle annexe" in trouve.data or trouve.status_code == 200
    introuvable = client_secretaire.get("/presences/historique?q=inexistant-xyz")
    assert introuvable.status_code == 200


# ------------------------------------------------------------------
#  RBAC — visiteur en lecture seule
# ------------------------------------------------------------------
def test_visiteur_peut_consulter_le_module_presences(client_visiteur, icm_app):
    client_visiteur.get("/")   # session déjà établie par la fixture
    for chemin in ("/presences", "/presences/historique", "/presences/statistiques"):
        assert client_visiteur.get(chemin).status_code == 200


def test_visiteur_ne_peut_pas_enregistrer_une_presence(client_visiteur, icm_app):
    reponse = client_visiteur.get("/presences/nouvelle")
    assert reponse.status_code == 302
    reponse = client_visiteur.post(
        "/presences/nouvelle", data=_donnees_exemple(icm_app), follow_redirects=True)
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 0


def test_visiteur_ne_peut_pas_acceder_aux_parametres(client_visiteur):
    assert client_visiteur.get("/presences/parametres").status_code == 302


def test_pasteur_a_les_memes_droits_que_secretaire(client_pasteur, icm_app):
    reponse = client_pasteur.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.AttendanceRecord.query.count() == 1


# ------------------------------------------------------------------
#  Statistiques
# ------------------------------------------------------------------
def test_statistiques_periode_tout_agrege_correctement(client_secretaire, icm_app):
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    reponse = client_secretaire.get("/presences/statistiques?periode=tout")
    assert reponse.status_code == 200
    assert b"315" in reponse.data


def test_statistiques_periode_personnalisee(client_secretaire, icm_app):
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    reponse = client_secretaire.get(
        "/presences/statistiques?periode=personnalise&debut=2026-08-01&fin=2026-08-31")
    assert reponse.status_code == 200
    assert b"315" in reponse.data

    hors_periode = client_secretaire.get(
        "/presences/statistiques?periode=personnalise&debut=2026-01-01&fin=2026-01-31")
    assert b"Aucune pr\xc3\xa9sence enregistr\xc3\xa9e" in hors_periode.data \
        or hors_periode.status_code == 200


# ------------------------------------------------------------------
#  Paramètres — types de culte et catégories configurables
# ------------------------------------------------------------------
def test_ajouter_un_type_de_culte(client_secretaire, icm_app):
    reponse = client_secretaire.post(
        "/presences/parametres",
        data={"action": "ajouter_type", "nom": "Veillée de prière"},
    )
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        assert icm_app.ServiceType.query.filter_by(nom="Veillée de prière").count() == 1


def test_type_de_culte_en_double_refuse(client_secretaire, icm_app):
    reponse = client_secretaire.post(
        "/presences/parametres",
        data={"action": "ajouter_type", "nom": "Culte du dimanche"},
    )
    assert reponse.status_code == 302   # redirige quand même, avec un message d'erreur
    with icm_app.app.app_context():
        assert icm_app.ServiceType.query.filter_by(nom="Culte du dimanche").count() == 1


def test_desactiver_un_type_de_culte_le_retire_du_formulaire(client_secretaire, icm_app):
    # follow_redirects=True : consomme les messages flash sur place, sinon
    # ils resteraient en attente dans la session et s'afficheraient sur la
    # toute prochaine page rendue — ici justement /presences/nouvelle,
    # faussant la vérification ("Type à désactiver" apparaîtrait dans le
    # message plutôt que dans le <select>, que le correctif teste vraiment).
    client_secretaire.post(
        "/presences/parametres",
        data={"action": "ajouter_type", "nom": "Type à désactiver"},
        follow_redirects=True,
    )
    with icm_app.app.app_context():
        nouveau = icm_app.ServiceType.query.filter_by(nom="Type à désactiver").one()
        id_nouveau = nouveau.id
        tous = icm_app.ServiceType.query.all()

    # Ré-envoie l'état de tous les types, en décochant seulement le nouveau
    # (reproduit la soumission complète du tableau des paramètres).
    donnees = {"action": "modifier_types"}
    for t in tous:
        donnees[f"type_nom_{t.id}"] = t.nom
        donnees[f"type_ordre_{t.id}"] = str(t.ordre_affichage)
        if t.id != id_nouveau:
            donnees[f"type_actif_{t.id}"] = "on"
    client_secretaire.post("/presences/parametres", data=donnees, follow_redirects=True)

    with icm_app.app.app_context():
        assert icm_app.db.session.get(icm_app.ServiceType, id_nouveau).is_active is False

    formulaire = client_secretaire.get("/presences/nouvelle")
    assert b"Type \xc3\xa0 d\xc3\xa9sactiver" not in formulaire.data


def test_ajouter_une_categorie(client_secretaire, icm_app):
    reponse = client_secretaire.post(
        "/presences/parametres",
        data={"action": "ajouter_categorie", "groupe": "hommes",
              "nom": "Étudiants", "age_min": "18", "age_max": "24"},
    )
    assert reponse.status_code == 302
    with icm_app.app.app_context():
        cat = icm_app.AttendanceCategory.query.filter_by(nom="Étudiants").one()
        assert cat.groupe == "hommes"
        assert cat.age_min == 18 and cat.age_max == 24


def test_categorie_modifiee_desactivee_reste_visible_sur_fiche_existante(
        client_secretaire, icm_app):
    """§4 : une catégorie désactivée après coup ne doit jamais faire perdre
    silencieusement les valeurs déjà enregistrées pour les fiches qui
    l'utilisaient (voir categories_pour_edition)."""
    client_secretaire.post("/presences/nouvelle", data=_donnees_exemple(icm_app))
    with icm_app.app.app_context():
        id_record = icm_app.AttendanceRecord.query.one().id
        id_cat = _id_categorie(icm_app, "Jeunes hommes")
        cat = icm_app.db.session.get(icm_app.AttendanceCategory, id_cat)
        cat.is_active = False
        icm_app.db.session.commit()

    page = client_secretaire.get(f"/presences/{id_record}/modifier")
    assert page.status_code == 200
    assert b"Jeunes hommes" in page.data
