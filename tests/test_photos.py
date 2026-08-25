# -*- coding: utf-8 -*-
"""Photos d'identité : revalidation réelle du contenu envoyé (Pillow),
plafond de taille, dossier hors static/, route protégée par connexion."""
import base64
import io
import os

from PIL import Image


def _png_valide(taille=(60, 60)):
    """Un PNG valide, avec assez de bruit pour ne pas se compresser à
    quelques octets (une couleur unie compresserait sous les 100 octets,
    ce que enregistrer_photo rejette comme suspect — voir _HASH_FACTICE
    plus haut pour un mécanisme similaire côté connexion)."""
    largeur, hauteur = taille
    bruit = os.urandom(largeur * hauteur * 3)
    tampon = io.BytesIO()
    Image.frombytes("RGB", taille, bruit).save(tampon, format="PNG")
    return tampon.getvalue()


def _data_url(binaire, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(binaire).decode()}"


def test_enregistrer_photo_accepte_une_vraie_image(icm_app, dossier_photos):
    nom, erreur = icm_app.enregistrer_photo(_data_url(_png_valide()))
    assert erreur is None
    assert nom is not None
    assert (dossier_photos / nom).exists()


def test_enregistrer_photo_rejette_un_contenu_qui_nest_pas_une_image(icm_app, dossier_photos):
    """Le préfixe data:URL prétend être un PNG, mais le contenu réel n'est
    pas une image valide : Pillow doit le détecter et le rejeter, quel que
    soit ce que le navigateur (ou un appel direct forgé) déclare."""
    faux_contenu = b"ceci n'est pas du tout une image, juste du texte" * 5
    nom, erreur = icm_app.enregistrer_photo(_data_url(faux_contenu))
    assert nom is None
    assert erreur is not None
    assert list(dossier_photos.iterdir()) == []


def test_enregistrer_photo_rejette_prefixe_non_reconnu(icm_app, dossier_photos):
    nom, erreur = icm_app.enregistrer_photo("data:application/pdf;base64,QUJD")
    assert nom is None
    assert "Format de photo non reconnu" in erreur


def test_enregistrer_photo_rejette_fichier_trop_lourd(icm_app, dossier_photos):
    grande_image = _png_valide(taille=(900, 900))  # bruit ~= incompressible
    assert len(grande_image) > icm_app.PHOTO_TAILLE_MAX
    nom, erreur = icm_app.enregistrer_photo(_data_url(grande_image))
    assert nom is None
    assert "trop lourde" in erreur


def test_enregistrer_photo_rejette_base64_invalide(icm_app, dossier_photos):
    nom, erreur = icm_app.enregistrer_photo("data:image/png;base64,%%%pas du base64%%%")
    assert nom is None
    assert erreur is not None


def test_chemin_photo_rejette_les_noms_suspects(icm_app):
    """Seuls des noms générés par l'application (hex + extension connue)
    doivent être acceptés — pas de traversée de répertoire ni d'extension
    arbitraire."""
    assert icm_app.chemin_photo("../../etc/passwd") is None
    assert icm_app.chemin_photo("..%2f..%2fetc%2fpasswd") is None
    assert icm_app.chemin_photo("photo.exe") is None
    assert icm_app.chemin_photo("") is None
    assert icm_app.chemin_photo(None) is None


def test_chemin_photo_accepte_un_nom_genere(icm_app):
    assert icm_app.chemin_photo("abcdef0123456789.jpg") is not None


def test_route_photo_exige_une_connexion(client, dossier_photos):
    (dossier_photos / "test.jpg").write_bytes(_png_valide())
    reponse = client.get("/photos/test.jpg")
    assert reponse.status_code == 302
    assert "/connexion" in reponse.headers["Location"]


def test_route_photo_sert_le_fichier_une_fois_connecte(client_visiteur, dossier_photos):
    (dossier_photos / "test.jpg").write_bytes(_png_valide())
    reponse = client_visiteur.get("/photos/test.jpg")
    assert reponse.status_code == 200


def test_route_photo_404_si_nom_suspect(client_secretaire, dossier_photos):
    reponse = client_secretaire.get("/photos/..%2f..%2fapp.py")
    assert reponse.status_code == 404
