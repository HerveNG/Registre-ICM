"""
============================================================
 IN CHRIST MINISTRIES (ICM)
 Registre numérique des Baptêmes et Mariages — MVP
============================================================
 Application Flask.

 Fonctions :
   - connexion par mot de passe
   - saisie / modification / suppression d'une carte
   - recherche et filtres
   - numérotation automatique des registres
   - carte de baptême / mariage imprimable (PDF via l'impression)
   - export Excel/CSV du registre complet

 Base de données :
   - par défaut SQLite (fichier registre.db, aucune installation)
   - ou PostgreSQL/Supabase en renseignant DATABASE_URL

 Démarrage :
   pip install -r requirements.txt
   python app.py
   puis ouvrir http://127.0.0.1:5000
============================================================
"""

import base64
import binascii
import csv
import io
import json
import os
import re
import secrets
import shutil
import sys
import time
import unicodedata
import uuid

# Sur certaines consoles Windows (code page cp1252), stdout ne sait pas
# encoder les caractères comme « → » utilisés dans les messages de
# démarrage ci-dessous, ce qui plante l'application avant même qu'elle ne
# se lance. On force l'UTF-8 quand c'est possible.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import (
    Flask, Response, abort, flash, redirect, render_template,
    request, send_from_directory, session, url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import or_, func, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

try:  # facultatif : charge le fichier .env s'il existe
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:  # facultatif : seul l'import de fichiers .xlsx en a besoin (le .csv non)
    import openpyxl
except ImportError:
    openpyxl = None

# Pillow revalide et ré-encode chaque photo décodée (voir enregistrer_photo) :
# un contenu qui ne serait pas réellement une image, quel que soit ce que son
# préfixe data:URL prétend, est ainsi rejeté plutôt qu'écrit tel quel.
from PIL import Image, UnidentifiedImageError


# ------------------------------------------------------------------
#  Configuration
# ------------------------------------------------------------------
app = Flask(__name__)

# FLASK_DEBUG par défaut à "0" (production sûre par défaut) : le mode debug
# expose le débogueur interactif Werkzeug (exécution de code arbitraire pour
# quiconque atteint une page d'erreur) et des traces techniques détaillées.
# Ne le passez à 1 que sur votre poste, jamais sur un déploiement accessible
# depuis l'extérieur.
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

_secret_key = (os.getenv("SECRET_KEY") or "").strip()
if not _secret_key or _secret_key == "remplacez-par-une-longue-chaine-aleatoire":
    # Pas de clé valide fournie : on en génère une aléatoire plutôt que
    # d'utiliser une valeur fixe et prévisible (qui permettrait de forger de
    # fausses sessions). Inconvénient assumé : elle change à chaque
    # redémarrage, ce qui déconnecte tout le monde — définissez SECRET_KEY
    # dans votre fichier .env pour une installation durable.
    _secret_key = secrets.token_hex(32)
    print(
        "  ATTENTION : SECRET_KEY absente ou laissée à sa valeur d'exemple "
        "dans .env — une clé aléatoire temporaire a été générée pour ce "
        "démarrage. Toutes les sessions seront invalidées au prochain "
        "redémarrage. Définissez SECRET_KEY dans .env pour une installation "
        "durable.\n"
    )
app.config["SECRET_KEY"] = _secret_key

# Cookies de session durcis. FORCER_HTTPS gouverne l'attribut Secure : par
# défaut aligné sur DEBUG (activé dès que le mode debug est coupé, ce qui
# suppose un déploiement derrière HTTPS) — si vous exploitez volontairement
# l'application en HTTP simple sur un réseau local sans certificat, mettez
# explicitement FORCER_HTTPS=0 dans .env, sinon les cookies de session
# n'atteindront jamais le navigateur et la connexion échouera silencieusement.
FORCER_HTTPS = os.getenv("FORCER_HTTPS", "0" if DEBUG else "1") == "1"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=FORCER_HTTPS,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

csrf = CSRFProtect(app)


@app.after_request
def ajouter_entetes_securite(reponse):
    """En-têtes de sécurité HTTP appliqués à toutes les réponses : anti
    clickjacking, anti MIME-sniffing, et une CSP qui bloque le chargement de
    scripts/objets/frames externes (le CSS et le JS de l'application restent
    autorisés en ligne, quelques attributs style/onclick historiques en
    dépendent encore)."""
    reponse.headers["X-Frame-Options"] = "DENY"
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    reponse.headers["Referrer-Policy"] = "same-origin"
    reponse.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if FORCER_HTTPS:
        reponse.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return reponse

# ------------------------------------------------------------------
#  Comptes et rôles (à changer dans le fichier .env)
# ------------------------------------------------------------------
# Trois rôles possibles :
#   - secretaire : accès complet — saisie, modification, suppression,
#                  import, export (comme le compte unique d'avant).
#   - pasteur    : accès complet également, exactement comme secrétaire —
#                  un compte séparé sert surtout à savoir qui a fait quoi.
#   - visiteur   : consultation seule — recherche, fiche, carte imprimable,
#                  sans pouvoir rien modifier, importer ni exporter.
ROLE_SECRETAIRE = "secretaire"
ROLE_PASTEUR = "pasteur"
ROLE_VISITEUR = "visiteur"
ROLES_ECRITURE = {ROLE_SECRETAIRE, ROLE_PASTEUR}
LIBELLES_ROLES = {
    ROLE_SECRETAIRE: "Secrétaire",
    ROLE_PASTEUR: "Pasteur",
    ROLE_VISITEUR: "Visiteur",
}


def _compte_depuis_env(prefixe, role, identifiant_defaut=None, mot_de_passe_defaut=None):
    """Construit un compte {identifiant, hash, role} à partir des variables
    PREFIXE_USER / PREFIXE_PASSWORD_HASH / PREFIXE_PASSWORD. Le compte
    secrétaire a toujours une valeur (identifiant_defaut/mot_de_passe_defaut
    assurent la compatibilité avec les installations existantes) ; les
    comptes pasteur et visiteur sont facultatifs et renvoient None tant
    qu'ils ne sont pas renseignés dans .env."""
    identifiant = os.getenv(f"{prefixe}_USER", identifiant_defaut or "").strip()
    if not identifiant:
        return None
    hash_ = os.getenv(f"{prefixe}_PASSWORD_HASH")
    if not hash_:
        mot_de_passe = os.getenv(f"{prefixe}_PASSWORD", mot_de_passe_defaut)
        if not mot_de_passe:
            return None
        hash_ = generate_password_hash(mot_de_passe)
    return {"identifiant": identifiant, "hash": hash_, "role": role}


COMPTES = {
    c["identifiant"]: c
    for c in (
        _compte_depuis_env("ADMIN", ROLE_SECRETAIRE, "admin", "icm2026"),
        _compte_depuis_env("PASTEUR", ROLE_PASTEUR),
        _compte_depuis_env("VISITEUR", ROLE_VISITEUR),
    )
    if c
}

# Base de données : SQLite par défaut, PostgreSQL/Supabase si DATABASE_URL
database_url = os.getenv("DATABASE_URL", "").strip() or "sqlite:///registre.db"
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

PAROISSE = os.getenv("PAROISSE", "In Christ Ministries")

# Dossier des photos d'identité, volontairement HORS de static/ : tout ce qui
# se trouve dans static/ est servi sans aucune authentification par Flask.
# Les photos sont des données personnelles (voir .gitignore) et ne doivent
# être accessibles qu'aux comptes connectés — elles sont donc servies par la
# route protégée /photos/<fichier> ci-dessous, jamais par /static/photos/.
DOSSIER_PHOTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
os.makedirs(DOSSIER_PHOTOS, exist_ok=True)

# Migration automatique et sans danger pour une installation existante : si
# d'anciennes photos se trouvent encore dans l'emplacement public
# static/photos/ (utilisé avant ce durcissement), on les déplace une fois
# vers le nouveau dossier privé. Idempotent : ne fait rien si déjà fait.
_ancien_dossier_photos = os.path.join(app.static_folder, "photos")
if os.path.isdir(_ancien_dossier_photos):
    for _nom in os.listdir(_ancien_dossier_photos):
        if _nom == ".gitkeep":
            continue
        _source = os.path.join(_ancien_dossier_photos, _nom)
        _destination = os.path.join(DOSSIER_PHOTOS, _nom)
        if os.path.isfile(_source) and not os.path.exists(_destination):
            try:
                shutil.move(_source, _destination)
            except OSError:
                pass

# 500 Ko : plafond imposé à chaque photo. Le navigateur (static/photo.js)
# compresse déjà l'image sous ce seuil avant de l'envoyer — ce contrôle est
# la seconde ligne de défense, côté serveur, au cas où l'envoi ne passerait
# pas par ce chemin normal (ancien navigateur, appel direct, etc.).
PHOTO_TAILLE_MAX = 500 * 1024

# Le champ caché qui porte, à l'étape de confirmation d'un import, toutes les
# lignes déjà validées (JSON) peut peser nettement plus que le fichier
# .xlsx/.csv d'origine — d'où une limite plus large que la seule photo
# encodée (~665 Ko pour 500 Ko réels) ne l'exigerait. Reste borné pour ne pas
# accepter des envois disproportionnés.
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["MAX_FORM_MEMORY_SIZE"] = 8 * 1024 * 1024

db = SQLAlchemy(app)


# ------------------------------------------------------------------
#  Anti brute-force sur la connexion
# ------------------------------------------------------------------
# Compteur en mémoire (pas de dépendance externe) : au-delà de
# TENTATIVES_MAX échecs pour un même identifiant dans la fenêtre glissante
# FENETRE_SECONDES, les tentatives suivantes sont refusées sans même
# vérifier le mot de passe, avec un délai d'attente affiché à l'utilisateur.
# Limite assumée : ce compteur est local au processus (il repart à zéro à
# chaque redémarrage, et n'est pas partagé entre plusieurs workers si
# l'application est un jour déployée avec plusieurs processus) — suffisant
# pour la taille de cette application, pas conçu pour un service exposé à
# grande échelle.
TENTATIVES_MAX = 5
FENETRE_SECONDES = 15 * 60
_tentatives_connexion = defaultdict(deque)


def _cle_limitation(identifiant):
    # Combine IP + identifiant visé : ralentit aussi bien le bourrage d'un
    # seul compte depuis une IP que le balayage de plusieurs identifiants.
    return f"{request.remote_addr}:{identifiant.lower()}"


def trop_de_tentatives(identifiant):
    """True si l'appelant doit patienter avant de retenter cet identifiant."""
    maintenant = time.monotonic()
    historique = _tentatives_connexion[_cle_limitation(identifiant)]
    while historique and maintenant - historique[0] > FENETRE_SECONDES:
        historique.popleft()
    return len(historique) >= TENTATIVES_MAX


def enregistrer_echec_connexion(identifiant):
    _tentatives_connexion[_cle_limitation(identifiant)].append(time.monotonic())


def reinitialiser_tentatives_connexion(identifiant):
    _tentatives_connexion.pop(_cle_limitation(identifiant), None)


# Hash factice contre lequel on vérifie un mot de passe quand l'identifiant
# n'existe pas : sans cela, une réponse pour un identifiant inconnu revient
# quasi instantanément (aucun hachage à calculer) alors qu'un identifiant
# connu avec un mauvais mot de passe prend le temps du calcul PBKDF2 — cet
# écart de latence mesurable permettrait à un attaquant de deviner quels
# identifiants existent sans jamais voir le message d'erreur.
_HASH_FACTICE = generate_password_hash(secrets.token_hex(16))


# ------------------------------------------------------------------
#  Modèle
# ------------------------------------------------------------------
CHAMPS_TEXTE = [
    "nom", "prenom", "nom_pere", "nom_mere", "nationalite", "originaire_de",
    "lieu_bapteme", "numero_registre_1", "celebrant_bapteme", "signature_1",
    "lieu_mariage", "conjoint", "numero_registre_2", "celebrant_mariage",
    "signature_2", "telephone", "observations",
]
CHAMPS_DATE = ["date_naissance", "date_bapteme", "date_mariage"]

# Casse imposée à certains champs texte, quelle que soit la façon dont
# l'utilisateur les a saisis (tout en majuscules, tout en minuscules,
# mélangés...) — un registre officiel ne doit pas dépendre de l'habitude de
# saisie de chacun :
#   - CHAMPS_MAJUSCULES : entièrement en MAJUSCULES (noms de famille, lieux,
#     célébrants).
#   - CHAMPS_CAPITALISES : seule la première lettre en majuscule, le reste en
#     minuscule (prénom, nationalité, origine).
# Appliquée par normaliser_casse() ci-dessous, appelée aussi bien par
# collecter_formulaire() (saisie manuelle) que par donnees_depuis_ligne()
# (import de fichier), pour que les deux chemins restent cohérents.
CHAMPS_MAJUSCULES = {
    "nom", "nom_pere", "nom_mere",
    "lieu_bapteme", "celebrant_bapteme",
    "lieu_mariage", "celebrant_mariage",
}
CHAMPS_CAPITALISES = {"prenom", "nationalite", "originaire_de"}


def normaliser_casse(champ, valeur):
    """Applique à `valeur` la casse imposée au champ `champ`, s'il en a une
    (voir CHAMPS_MAJUSCULES / CHAMPS_CAPITALISES ci-dessus). Ne touche pas
    aux valeurs vides, et laisse inchangé tout champ sans règle de casse."""
    if not valeur:
        return valeur
    if champ in CHAMPS_MAJUSCULES:
        return valeur.upper()
    if champ in CHAMPS_CAPITALISES:
        return valeur[:1].upper() + valeur[1:].lower()
    return valeur

# Colonnes de l'export CSV — et, à l'identique (moins la photo), du modèle
# d'import et de la reconnaissance des en-têtes d'un fichier envoyé. Garder
# une seule liste ici garantit que l'export et l'import restent en accord.
COLONNES_EXPORT = [
    ("nom", "Nom"), ("prenom", "Prénom"), ("nom_pere", "Fils/Fille de"),
    ("nom_mere", "Et de"), ("date_naissance", "Date de naissance"),
    ("nationalite", "Nationalité"), ("originaire_de", "Originaire de"),
    ("date_bapteme", "Date de baptême"), ("lieu_bapteme", "Lieu du baptême"),
    ("numero_registre_1", "N° Registre (1)"),
    ("celebrant_bapteme", "Célébrant baptême"), ("signature_1", "Signature (1)"),
    ("lieu_mariage", "Lieu du mariage"), ("date_mariage", "Date du mariage"),
    ("conjoint", "Conjoint"), ("numero_registre_2", "N° Registre (2)"),
    ("celebrant_mariage", "Célébrant mariage"), ("signature_2", "Signature (2)"),
    ("telephone", "Téléphone"), ("observations", "Observations"),
    ("photo", "Fichier photo"),
]


class Registre(db.Model):
    __tablename__ = "registre"

    id = db.Column(db.Integer, primary_key=True)

    # Identité
    nom = db.Column(db.String(120), nullable=False)
    prenom = db.Column(db.String(120), nullable=False)
    nom_pere = db.Column(db.String(200))
    nom_mere = db.Column(db.String(200))
    date_naissance = db.Column(db.Date)
    nationalite = db.Column(db.String(100))
    originaire_de = db.Column(db.String(150))

    # Baptême
    date_bapteme = db.Column(db.Date)
    lieu_bapteme = db.Column(db.String(200))
    numero_registre_1 = db.Column(db.String(80))
    celebrant_bapteme = db.Column(db.String(150))
    signature_1 = db.Column(db.String(150))

    # Mariage
    lieu_mariage = db.Column(db.String(200))
    date_mariage = db.Column(db.Date)
    conjoint = db.Column(db.String(250))
    numero_registre_2 = db.Column(db.String(80))
    celebrant_mariage = db.Column(db.String(150))
    signature_2 = db.Column(db.String(150))

    # Photo d'identité : nom du fichier rangé dans static/photos/
    photo = db.Column(db.String(120))

    # Divers
    telephone = db.Column(db.String(50))
    observations = db.Column(db.Text)

    # Traçabilité
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    @property
    def nom_complet(self):
        return f"{self.nom} {self.prenom}".strip()

    @property
    def est_marie(self):
        return self.date_mariage is not None


class JournalAudit(db.Model):
    """Une ligne par création, modification ou suppression d'une carte.

    registre_id n'est volontairement PAS une clé étrangère stricte : une
    fiche supprimée doit rester traçable dans le journal, donc l'entrée
    d'audit ne dépend pas de l'existence continue de la fiche. nom_complet
    est un instantané pris au moment de l'action, pour rester lisible même
    si la fiche a depuis été supprimée ou renommée.
    """
    __tablename__ = "journal_audit"

    id = db.Column(db.Integer, primary_key=True)
    horodatage = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    utilisateur = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(20), nullable=False)   # creation | modification | suppression
    registre_id = db.Column(db.Integer)
    nom_complet = db.Column(db.String(250), nullable=False)
    details = db.Column(db.Text)   # JSON : [{"champ","avant","apres"}, ...] ou {"origine":"import"}

    @property
    def changements(self):
        """Liste des champs modifiés (pour l'affichage), ou None."""
        if not self.details:
            return None
        try:
            valeur = json.loads(self.details)
        except ValueError:
            return None
        return valeur if isinstance(valeur, list) else None

    @property
    def vient_de_limport(self):
        if not self.details:
            return False
        try:
            valeur = json.loads(self.details)
        except ValueError:
            return False
        return isinstance(valeur, dict) and valeur.get("origine") == "import"


# ------------------------------------------------------------------
#  Authentification
# ------------------------------------------------------------------
def login_requis(vue):
    """Vue accessible à tout compte connecté, quel que soit son rôle
    (secrétaire, pasteur ou visiteur) : consultation du registre, carte
    imprimable."""
    @wraps(vue)
    def wrapper(*args, **kwargs):
        if not session.get("utilisateur"):
            return redirect(url_for("connexion", suivant=request.path))
        return vue(*args, **kwargs)
    return wrapper


def ecriture_requise(vue):
    """Comme @login_requis, mais réserve la vue aux rôles secrétaire et
    pasteur. Un visiteur connecté qui tente d'y accéder — même par une
    URL tapée directement — est renvoyé vers le registre avec un message,
    sans que rien ne soit modifié : le contrôle est fait ici, côté
    serveur, pas seulement en cachant les boutons dans les pages."""
    @wraps(vue)
    def wrapper(*args, **kwargs):
        if not session.get("utilisateur"):
            return redirect(url_for("connexion", suivant=request.path))
        if session.get("role") not in ROLES_ECRITURE:
            flash("Accès réservé au secrétariat et au pasteur.", "error")
            return redirect(url_for("index"))
        return vue(*args, **kwargs)
    return wrapper


def _destination_sure(suivant):
    """N'accepte `suivant` (redirection post-connexion) que s'il s'agit d'un
    chemin relatif interne à l'application — jamais une URL absolue ni un
    « //hôte » — pour empêcher une redirection ouverte vers un site externe
    (phishing) après une connexion légitime."""
    if not suivant or not suivant.startswith("/") or suivant.startswith("//"):
        return None
    if "\\" in suivant or suivant.startswith("/\\"):
        return None
    return suivant


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        utilisateur = request.form.get("utilisateur", "").strip()
        mot_de_passe = request.form.get("mot_de_passe", "")

        if trop_de_tentatives(utilisateur):
            flash(
                "Trop de tentatives avec cet identifiant. Réessayez dans "
                "quelques minutes.", "error"
            )
            return render_template("connexion.html", paroisse=PAROISSE), 429

        compte = COMPTES.get(utilisateur)
        # check_password_hash s'exécute toujours, même sans compte trouvé
        # (contre un hash factice), pour que le temps de réponse ne trahisse
        # pas l'existence de l'identifiant (voir _HASH_FACTICE ci-dessus).
        mot_de_passe_ok = check_password_hash(
            compte["hash"] if compte else _HASH_FACTICE, mot_de_passe
        )
        if compte and mot_de_passe_ok:
            reinitialiser_tentatives_connexion(utilisateur)
            session.clear()
            session["utilisateur"] = utilisateur
            session["role"] = compte["role"]
            session.permanent = True
            destination = _destination_sure(request.args.get("suivant"))
            return redirect(destination or url_for("index"))

        enregistrer_echec_connexion(utilisateur)
        flash("Identifiant ou mot de passe incorrect.", "error")
    return render_template("connexion.html", paroisse=PAROISSE)


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    flash("Vous êtes déconnecté.", "success")
    return redirect(url_for("connexion"))


# ------------------------------------------------------------------
#  Utilitaires
# ------------------------------------------------------------------
def lire_date(valeur):
    """Convertit une chaîne 'AAAA-MM-JJ' en date, ou None si vide/invalide."""
    valeur = (valeur or "").strip()
    if not valeur:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(valeur, fmt).date()
        except ValueError:
            continue
    return None


def normaliser_entete(texte):
    """Réduit un en-tête de colonne à une forme comparable : minuscules,
    sans accents, sans ponctuation. Sert à reconnaître les en-têtes d'un
    fichier importé même s'ils ne sont pas exactement identiques au modèle
    (majuscules, accents oubliés, espaces en trop…)."""
    texte = unicodedata.normalize("NFKD", str(texte or ""))
    texte = texte.encode("ascii", "ignore").decode("ascii")
    texte = re.sub(r"[^a-z0-9]+", " ", texte.lower()).strip()
    return texte


def prochain_numero(prefixe, colonne, annee):
    """Génère ICM-B-2026-0001 / ICM-M-2026-0001 en continuant la numérotation."""
    motif = f"ICM-{prefixe}-{annee}-%"
    dernier = (
        db.session.query(func.max(colonne))
        .filter(colonne.like(motif))
        .scalar()
    )
    suivant = 1
    if dernier:
        try:
            suivant = int(dernier.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            suivant = 1
    return f"ICM-{prefixe}-{annee}-{suivant:04d}"


# ------------------------------------------------------------------
#  Photos d'identité
# ------------------------------------------------------------------
MOTIF_DATA_URL = re.compile(r"^data:image/(jpeg|jpg|png|webp);base64,(.+)$", re.S)
MOTIF_NOM_PHOTO = re.compile(r"^[A-Za-z0-9_-]+\.(jpg|png|webp)$")


def chemin_photo(nom_fichier):
    """Chemin sur disque d'une photo, ou None si le nom est suspect."""
    if not nom_fichier or not MOTIF_NOM_PHOTO.match(nom_fichier):
        return None
    return os.path.join(DOSSIER_PHOTOS, nom_fichier)


def supprimer_photo(nom_fichier):
    chemin = chemin_photo(nom_fichier)
    if chemin and os.path.exists(chemin):
        try:
            os.remove(chemin)
        except OSError:
            pass


FORMATS_PHOTO = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}


def enregistrer_photo(data_url):
    """Décode l'image recadrée envoyée par le navigateur, la revalide
    réellement (pas seulement le type déclaré dans le préfixe data:URL, qui
    vient du navigateur et pourrait être falsifié par un appel direct au
    formulaire) et l'écrit sur disque.

    Renvoie (nom_du_fichier, erreur). L'un des deux est toujours None.
    """
    correspondance = MOTIF_DATA_URL.match((data_url or "").strip())
    if not correspondance:
        return None, "Format de photo non reconnu."

    extension, donnees = correspondance.group(1), correspondance.group(2)
    if extension == "jpeg":
        extension = "jpg"

    try:
        binaire = base64.b64decode(donnees, validate=True)
    except (binascii.Error, ValueError):
        return None, "La photo n'a pas pu être décodée."

    if len(binaire) > PHOTO_TAILLE_MAX:
        return None, (
            f"Photo trop lourde ({len(binaire) // 1024} Ko) : le maximum "
            f"autorisé est {PHOTO_TAILLE_MAX // 1024} Ko. Réessayez avec "
            f"une image plus simple, ou reprenez le recadrage."
        )
    if len(binaire) < 100:
        return None, "Photo vide ou illisible."

    # On ne stocke jamais les octets reçus tels quels : on les décode comme
    # une vraie image, puis on la ré-encode nous-mêmes. Tout contenu qui
    # n'est pas une image valide est rejeté ici (quel que soit ce que le
    # préfixe data:URL prétendait), et un éventuel contenu malveillant logé
    # dans les métadonnées d'un vrai fichier image ne survit pas au
    # ré-encodage.
    try:
        image = Image.open(BytesIO(binaire))
        image.verify()
        image = Image.open(BytesIO(binaire))  # verify() consomme l'objet : on rouvre
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None, "Ce fichier n'est pas une image valide."

    format_pillow = FORMATS_PHOTO.get(extension, "JPEG")
    if format_pillow == "JPEG" and image.mode in ("RGBA", "P", "LA"):
        image = image.convert("RGB")

    options = {"quality": 90} if format_pillow in ("JPEG", "WEBP") else {}
    tampon = BytesIO()
    try:
        image.save(tampon, format=format_pillow, **options)
    except (OSError, ValueError):
        return None, "Ce fichier n'a pas pu être traité comme une image."
    binaire = tampon.getvalue()

    if len(binaire) > PHOTO_TAILLE_MAX:
        return None, (
            f"Photo trop lourde une fois revalidée ({len(binaire) // 1024} Ko) : "
            f"le maximum autorisé est {PHOTO_TAILLE_MAX // 1024} Ko."
        )

    nom = f"{uuid.uuid4().hex}.{extension}"
    with open(os.path.join(DOSSIER_PHOTOS, nom), "wb") as fichier:
        fichier.write(binaire)
    return nom, None


def appliquer_photo(record, form):
    """Applique la photo envoyée par le formulaire à un enregistrement.

    Trois cas : nouvelle photo, retrait de la photo, ou aucun changement.
    Ne supprime jamais un fichier elle-même : renvoie
    (erreur, nouvelle_photo, photo_a_supprimer) pour que l'appelant ne
    supprime l'ancienne photo (ou, en cas d'échec, la nouvelle) qu'après un
    commit() réussi — les effets sur le disque restent ainsi cohérents avec
    la base même si la transaction échoue en cours de route.
    """
    data_url = (form.get("photo_data") or "").strip()
    retirer = form.get("photo_retiree") == "1"

    if data_url:
        nom, erreur = enregistrer_photo(data_url)
        if erreur:
            return erreur, None, None
        ancienne = record.photo
        record.photo = nom
        return None, nom, (ancienne if ancienne and ancienne != nom else None)
    if retirer and record.photo:
        ancienne = record.photo
        record.photo = None
        return None, None, ancienne
    return None, None, None


# Longueurs maximales des champs texte — doivent rester cohérentes avec les
# colonnes db.String(n) du modèle Registre ci-dessus. Validées ici, côté
# serveur, avant tout insert/update : le `maxlength` HTML des formulaires
# n'est qu'un confort de saisie et ne protège en rien un appel direct
# (formulaire forgé, requête HTTP construite à la main).
LONGUEURS_MAX = {
    "nom": 120, "prenom": 120, "nom_pere": 200, "nom_mere": 200,
    "nationalite": 100, "originaire_de": 150, "lieu_bapteme": 200,
    "numero_registre_1": 80, "celebrant_bapteme": 150, "signature_1": 150,
    "lieu_mariage": 200, "conjoint": 250, "numero_registre_2": 80,
    "celebrant_mariage": 150, "signature_2": 150, "telephone": 50,
    "observations": 5000,
}


def valider_donnees(donnees):
    """Règles métier sur un dict de données déjà typé (dates en `date`,
    textes vides ramenés à None). Renvoie la liste des erreurs trouvées.
    Utilisé aussi bien par le formulaire de saisie que par l'import de
    fichier, pour que les deux chemins appliquent exactement les mêmes
    règles."""
    erreurs = []
    if not donnees.get("nom"):
        erreurs.append("Le nom est obligatoire.")
    if not donnees.get("prenom"):
        erreurs.append("Le prénom est obligatoire.")

    for champ, maximum in LONGUEURS_MAX.items():
        valeur = donnees.get(champ)
        if valeur and len(valeur) > maximum:
            erreurs.append(
                f"« {LIBELLES_CHAMPS.get(champ, champ)} » dépasse la longueur "
                f"maximale autorisée ({maximum} caractères)."
            )

    aujourdhui = date.today()
    for libelle, champ in (
        ("naissance", "date_naissance"),
        ("baptême", "date_bapteme"),
        ("mariage", "date_mariage"),
    ):
        if donnees.get(champ) and donnees[champ] > aujourdhui:
            erreurs.append(f"La date de {libelle} ne peut pas être dans le futur.")

    if donnees.get("date_naissance") and donnees.get("date_bapteme") \
            and donnees["date_bapteme"] < donnees["date_naissance"]:
        erreurs.append("Le baptême ne peut pas précéder la naissance.")
    if donnees.get("date_naissance") and donnees.get("date_mariage") \
            and donnees["date_mariage"] < donnees["date_naissance"]:
        erreurs.append("Le mariage ne peut pas précéder la naissance.")

    return erreurs


def collecter_formulaire(form):
    """Lit le formulaire et renvoie (données, liste d'erreurs)."""
    donnees = {
        c: normaliser_casse(c, (form.get(c, "") or "").strip() or None)
        for c in CHAMPS_TEXTE
    }
    for c in CHAMPS_DATE:
        donnees[c] = lire_date(form.get(c))
    return donnees, valider_donnees(donnees)


def verifier_unicite(donnees, id_courant=None):
    """Empêche deux cartes de porter le même numéro de registre."""
    erreurs = []
    for champ, libelle in (
        ("numero_registre_1", "de baptême"),
        ("numero_registre_2", "de mariage"),
    ):
        valeur = donnees.get(champ)
        if not valeur:
            continue
        colonne = getattr(Registre, champ)
        requete = Registre.query.filter(colonne == valeur)
        if id_courant:
            requete = requete.filter(Registre.id != id_courant)
        if requete.first():
            erreurs.append(f"Le numéro de registre {libelle} « {valeur} » existe déjà.")
    return erreurs


def attribuer_numeros(donnees):
    """Attribue automatiquement un numéro si l'utilisateur ne l'a pas saisi."""
    if donnees.get("date_bapteme") and not donnees.get("numero_registre_1"):
        donnees["numero_registre_1"] = prochain_numero(
            "B", Registre.numero_registre_1, donnees["date_bapteme"].year
        )
    if donnees.get("date_mariage") and not donnees.get("numero_registre_2"):
        donnees["numero_registre_2"] = prochain_numero(
            "M", Registre.numero_registre_2, donnees["date_mariage"].year
        )
    return donnees


# ------------------------------------------------------------------
#  Journal d'audit
# ------------------------------------------------------------------
# Champs suivis par le journal : les mêmes que l'export/import, plus la
# photo (dont l'export n'a besoin que du nom de fichier).
CHAMPS_SUIVIS = CHAMPS_TEXTE + CHAMPS_DATE + ["photo"]
LIBELLES_CHAMPS = dict(COLONNES_EXPORT)


def _texte_valeur(valeur):
    """Représentation lisible d'une valeur de champ pour le journal."""
    if valeur is None or valeur == "":
        return "—"
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    return str(valeur)


def journaliser(action, record, avant=None, origine=None):
    """Ajoute une entrée au journal d'audit (dans la transaction en cours —
    n'appelle pas commit() elle-même, pour rester atomique avec l'écriture
    qu'elle journalise).

    - action : "creation", "modification" ou "suppression".
    - record : la fiche concernée, encore accessible (y compris juste
      avant sa suppression).
    - avant : pour une modification, dict {champ: valeur_avant} capturé
      avant les setattr — sert à calculer le détail des champs changés.
      Si aucun champ suivi n'a réellement changé, aucune entrée n'est créée.
    - origine : par exemple "import", pour distinguer une création en lot
      d'une saisie manuelle.
    """
    details = None

    if action == "modification" and avant is not None:
        changements = []
        for champ, valeur_avant in avant.items():
            valeur_apres = getattr(record, champ)
            if valeur_avant != valeur_apres:
                changements.append({
                    "champ": LIBELLES_CHAMPS.get(champ, champ),
                    "avant": _texte_valeur(valeur_avant),
                    "apres": _texte_valeur(valeur_apres),
                })
        if not changements:
            return
        details = json.dumps(changements, ensure_ascii=False)
    elif action == "creation" and origine:
        details = json.dumps({"origine": origine}, ensure_ascii=False)

    db.session.add(JournalAudit(
        utilisateur=session.get("utilisateur", "?"),
        action=action,
        registre_id=record.id,
        nom_complet=record.nom_complet,
        details=details,
    ))


def historique_fiche(record_id):
    """(entrée de création, dernière entrée de modification) d'une fiche —
    pour afficher « Créée par … le … » sur le formulaire. L'un des deux
    (ou les deux) peut être None : la création peut précéder l'existence
    du journal, et une fiche n'a pas forcément été modifiée depuis."""
    creation = (JournalAudit.query
                .filter_by(registre_id=record_id, action="creation")
                .order_by(JournalAudit.horodatage.asc()).first())
    derniere_modif = (JournalAudit.query
                       .filter_by(registre_id=record_id, action="modification")
                       .order_by(JournalAudit.horodatage.desc()).first())
    return creation, derniere_modif


# ------------------------------------------------------------------
#  Liste et recherche
# ------------------------------------------------------------------
@app.route("/")
@login_requis
def index():
    q = request.args.get("q", "").strip()
    filtre = request.args.get("filtre", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    par_page = 20

    requete = Registre.query
    if q:
        motif = f"%{q}%"
        requete = requete.filter(or_(
            Registre.nom.ilike(motif),
            Registre.prenom.ilike(motif),
            Registre.numero_registre_1.ilike(motif),
            Registre.numero_registre_2.ilike(motif),
            Registre.conjoint.ilike(motif),
        ))
    if filtre == "bapteme":
        requete = requete.filter(Registre.date_bapteme.isnot(None))
    elif filtre == "mariage":
        requete = requete.filter(Registre.date_mariage.isnot(None))
    elif filtre == "incomplet":
        requete = requete.filter(Registre.date_bapteme.is_(None))

    pagination = requete.order_by(Registre.nom.asc(), Registre.prenom.asc()) \
                        .paginate(page=page, per_page=par_page, error_out=False)

    stats = {
        "total": Registre.query.count(),
        "baptemes": Registre.query.filter(Registre.date_bapteme.isnot(None)).count(),
        "mariages": Registre.query.filter(Registre.date_mariage.isnot(None)).count(),
    }

    return render_template(
        "index.html", pagination=pagination, records=pagination.items,
        q=q, filtre=filtre, stats=stats, paroisse=PAROISSE,
    )


# ------------------------------------------------------------------
#  Création / modification / suppression
# ------------------------------------------------------------------
@app.route("/nouveau", methods=["GET", "POST"])
@ecriture_requise
def nouveau():
    if request.method == "POST":
        donnees, erreurs = collecter_formulaire(request.form)
        erreurs += verifier_unicite(donnees)
        if erreurs:
            for e in erreurs:
                flash(e, "error")
            return render_template("form.html", record=None,
                                   valeurs=request.form, paroisse=PAROISSE)

        record = Registre(**attribuer_numeros(donnees))

        erreur_photo, nouvelle_photo, _ = appliquer_photo(record, request.form)
        if erreur_photo:
            flash(erreur_photo, "error")
            return render_template("form.html", record=None,
                                   valeurs=request.form, paroisse=PAROISSE)

        db.session.add(record)
        try:
            db.session.flush()      # attribue record.id sans clôturer la transaction
            journaliser("creation", record)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if nouvelle_photo:
                supprimer_photo(nouvelle_photo)
            flash(
                "Ce numéro de registre vient d'être attribué à une autre "
                "carte au même instant. Réessayez l'enregistrement.", "error"
            )
            return render_template("form.html", record=None,
                                   valeurs=request.form, paroisse=PAROISSE)
        flash(f"Carte de {record.nom_complet} enregistrée "
              f"(N° {record.numero_registre_1 or '—'}).", "success")
        return redirect(url_for("index"))

    return render_template("form.html", record=None, valeurs={}, paroisse=PAROISSE)


@app.route("/modifier/<int:record_id>", methods=["GET", "POST"])
@ecriture_requise
def modifier(record_id):
    record = db.session.get(Registre, record_id) or abort(404)

    if request.method == "POST":
        avant = {champ: getattr(record, champ) for champ in CHAMPS_SUIVIS}

        donnees, erreurs = collecter_formulaire(request.form)
        erreurs += verifier_unicite(donnees, id_courant=record.id)
        if erreurs:
            for e in erreurs:
                flash(e, "error")
            return render_template("form.html", record=record,
                                   valeurs=request.form, paroisse=PAROISSE)

        erreur_photo, nouvelle_photo, ancienne_photo = appliquer_photo(record, request.form)
        if erreur_photo:
            db.session.rollback()
            if nouvelle_photo:
                supprimer_photo(nouvelle_photo)
            flash(erreur_photo, "error")
            return render_template("form.html", record=record,
                                   valeurs=request.form, paroisse=PAROISSE)

        for champ, valeur in attribuer_numeros(donnees).items():
            setattr(record, champ, valeur)
        try:
            journaliser("modification", record, avant=avant)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if nouvelle_photo:
                supprimer_photo(nouvelle_photo)
            flash(
                "Ce numéro de registre vient d'être attribué à une autre "
                "carte au même instant. Réessayez l'enregistrement.", "error"
            )
            return render_template("form.html", record=record,
                                   valeurs=request.form, paroisse=PAROISSE)
        if ancienne_photo:
            supprimer_photo(ancienne_photo)
        flash(f"Carte de {record.nom_complet} mise à jour.", "success")
        return redirect(url_for("index"))

    creation, derniere_modif = historique_fiche(record.id)
    return render_template("form.html", record=record, valeurs={}, paroisse=PAROISSE,
                           creation=creation, derniere_modif=derniere_modif)


@app.post("/supprimer/<int:record_id>")
@ecriture_requise
def supprimer(record_id):
    record = db.session.get(Registre, record_id) or abort(404)
    nom = record.nom_complet
    photo = record.photo
    journaliser("suppression", record)
    db.session.delete(record)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("La suppression a échoué. Réessayez.", "error")
        return redirect(url_for("index"))
    supprimer_photo(photo)          # la fiche partie, l'image n'a plus de raison d'être
    flash(f"Carte de {nom} supprimée.", "success")
    return redirect(url_for("index"))


# ------------------------------------------------------------------
#  Carte imprimable (→ PDF via « Imprimer > Enregistrer en PDF »)
# ------------------------------------------------------------------
@app.route("/carte/<int:record_id>")
@login_requis
def carte(record_id):
    record = db.session.get(Registre, record_id) or abort(404)
    return render_template("carte.html", r=record, paroisse=PAROISSE)


@app.route("/photos/<nom_fichier>")
@login_requis
def photo(nom_fichier):
    """Sert une photo d'identité — réservé aux comptes connectés. Les photos
    ne sont plus dans static/ (servi sans authentification par Flask) : ce
    sont des données personnelles, elles ne doivent être visibles qu'à
    quelqu'un déjà identifié dans l'application, quel que soit son rôle."""
    if not chemin_photo(nom_fichier):
        abort(404)
    return send_from_directory(DOSSIER_PHOTOS, nom_fichier)


# ------------------------------------------------------------------
#  Journal d'audit — qui a créé/modifié/supprimé quelle carte, et quand.
#  Consultation ouverte aux trois rôles : c'est une lecture, pas une
#  écriture (les entrées elles-mêmes ne sont jamais modifiables).
# ------------------------------------------------------------------
@app.route("/journal")
@login_requis
def journal():
    q = request.args.get("q", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    par_page = 30

    requete = JournalAudit.query
    if q:
        requete = requete.filter(JournalAudit.nom_complet.ilike(f"%{q}%"))

    pagination = requete.order_by(JournalAudit.horodatage.desc()) \
                        .paginate(page=page, per_page=par_page, error_out=False)

    return render_template("journal.html", pagination=pagination,
                           entrees=pagination.items, q=q, paroisse=PAROISSE)


# ------------------------------------------------------------------
#  Export CSV (ouvrable directement dans Excel)
# ------------------------------------------------------------------
CARACTERES_FORMULE = ("=", "+", "-", "@", "\t", "\r")


def neutraliser_formule(valeur):
    """Empêche l'injection de formule CSV (CWE-1236) : un champ texte libre
    (observations, célébrant, signature…) qui commencerait par =, +, -, @ ou
    une tabulation serait interprété comme une formule par Excel/LibreOffice/
    Google Sheets à l'ouverture du fichier exporté — potentiellement piégée
    (lien trompeur, exfiltration de données d'autres cellules). On neutralise
    en préfixant d'une apostrophe, ce qu'Excel affiche tel quel comme texte."""
    if isinstance(valeur, str) and valeur.startswith(CARACTERES_FORMULE):
        return "'" + valeur
    return valeur


@app.route("/export.csv")
@ecriture_requise
def export_csv():
    colonnes = COLONNES_EXPORT

    tampon = io.StringIO()
    tampon.write("﻿")  # BOM : Excel affiche correctement les accents
    writer = csv.writer(tampon, delimiter=";")
    writer.writerow([libelle for _, libelle in colonnes])

    for r in Registre.query.order_by(Registre.nom, Registre.prenom).all():
        ligne = []
        for champ, _ in colonnes:
            valeur = getattr(r, champ)
            if isinstance(valeur, date):
                valeur = valeur.strftime("%d/%m/%Y")
            ligne.append(neutraliser_formule(valeur) or "")
        writer.writerow(ligne)

    nom_fichier = f"registre_icm_{date.today():%Y-%m-%d}.csv"
    return Response(
        tampon.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


# ------------------------------------------------------------------
#  Import du registre papier existant (fichier Excel .xlsx ou .csv)
# ------------------------------------------------------------------
# Reconnaît les en-têtes du fichier envoyé en les comparant, une fois
# normalisés (minuscules, sans accents), à ceux du modèle/export. La photo
# ne fait pas partie de l'import : un fichier Excel ne contient pas
# d'images, seulement un nom de fichier qui ne correspondrait à rien.
CHAMPS_PAR_ENTETE = {
    normaliser_entete(libelle): champ
    for champ, libelle in COLONNES_EXPORT if champ != "photo"
}


def _decoder_texte(brut):
    """Décode un fichier .csv quel que soit son encodage d'origine — Excel,
    selon la version et la langue de Windows, enregistre parfois en
    Windows-1252 plutôt qu'en UTF-8."""
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            return brut.decode(encodage)
        except UnicodeDecodeError:
            continue
    return brut.decode("latin-1")  # ne déclenche jamais d'erreur : dernier recours


def _lire_csv(fichier):
    texte = _decoder_texte(fichier.read())
    lignes_texte = texte.splitlines()
    if not lignes_texte:
        return [], []
    try:
        delimiteur = csv.Sniffer().sniff(lignes_texte[0], delimiters=";,").delimiter
    except csv.Error:
        delimiteur = ";"
    lignes = list(csv.reader(lignes_texte, delimiter=delimiteur))
    return (lignes[1:], lignes[0]) if lignes else ([], [])


def _lire_xlsx(fichier):
    classeur = openpyxl.load_workbook(fichier, read_only=True, data_only=True)
    feuille = classeur.worksheets[0]
    lignes = feuille.iter_rows(values_only=True)
    try:
        entetes = list(next(lignes))
    except StopIteration:
        return [], []
    return [list(l) for l in lignes], entetes


def lire_fichier_import(fichier):
    """Lit un fichier .xlsx ou .csv envoyé par le secrétariat.

    Renvoie (lignes, colonnes_ignorees, erreur). `lignes` est une liste de
    dicts {champ_interne: valeur_brute} — une entrée par ligne non vide du
    fichier. `erreur` est une chaîne si le fichier n'a pas pu être exploité
    du tout (mauvais format, colonnes essentielles introuvables…), et dans
    ce cas les deux autres valeurs sont None.
    """
    nom_fichier = (fichier.filename or "").lower()
    try:
        if nom_fichier.endswith((".xlsx", ".xlsm")):
            if openpyxl is None:
                return None, None, (
                    "L'import de fichiers .xlsx nécessite le paquet "
                    "« openpyxl » (ajouté à requirements.txt — réinstallez "
                    "les dépendances avec pip install -r requirements.txt), "
                    "ou envoyez plutôt un fichier .csv."
                )
            lignes_brutes, entetes = _lire_xlsx(fichier)
        elif nom_fichier.endswith(".csv"):
            lignes_brutes, entetes = _lire_csv(fichier)
        else:
            return None, None, "Format non reconnu : envoyez un fichier .xlsx ou .csv."
    except Exception:
        return None, None, (
            "Le fichier n'a pas pu être lu. Vérifiez qu'il n'est pas "
            "corrompu ou protégé par un mot de passe."
        )

    correspondance = {}
    for i, entete in enumerate(entetes):
        champ = CHAMPS_PAR_ENTETE.get(normaliser_entete(entete))
        if champ:
            correspondance[i] = champ

    if "nom" not in correspondance.values() or "prenom" not in correspondance.values():
        return None, None, (
            "Les colonnes « Nom » et « Prénom » sont introuvables dans ce "
            "fichier. Téléchargez le modèle ci-dessous et gardez ses "
            "en-têtes tels quels."
        )

    colonnes_ignorees = [
        entete for i, entete in enumerate(entetes)
        if i not in correspondance and str(entete or "").strip()
    ]

    lignes = []
    for valeurs in lignes_brutes:
        ligne = {
            champ: (valeurs[i] if i < len(valeurs) else None)
            for i, champ in correspondance.items()
        }
        if any(v not in (None, "") for v in ligne.values()):
            lignes.append(ligne)

    return lignes, colonnes_ignorees, None


def _valeur_texte_import(valeur):
    if valeur is None:
        return None
    if isinstance(valeur, str):
        return valeur.strip() or None
    if isinstance(valeur, float):
        return str(int(valeur)) if valeur.is_integer() else str(valeur)
    return str(valeur).strip() or None


def _valeur_date_import(valeur):
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str):
        return lire_date(valeur)
    return None


def donnees_depuis_ligne(ligne_brute):
    """Convertit une ligne brute (valeurs telles que lues dans le fichier)
    dans le même format typé que collecter_formulaire : textes vides à
    None, dates converties, et la même casse imposée (voir
    normaliser_casse) — un fidèle importé depuis le registre papier suit
    exactement la même règle qu'une fiche saisie à la main."""
    donnees = {
        c: normaliser_casse(c, _valeur_texte_import(ligne_brute.get(c)))
        for c in CHAMPS_TEXTE
    }
    for c in CHAMPS_DATE:
        donnees[c] = _valeur_date_import(ligne_brute.get(c))
    return donnees


def donnees_vers_json(donnees):
    """Rend un dict `donnees` sérialisable en JSON (dates → texte ISO), pour
    le champ caché qui fait le pont entre l'aperçu et la confirmation."""
    d = dict(donnees)
    for c in CHAMPS_DATE:
        if isinstance(d.get(c), date):
            d[c] = d[c].isoformat()
    return d


def donnees_depuis_json(d):
    donnees = {c: (d.get(c) or None) for c in CHAMPS_TEXTE}
    for c in CHAMPS_DATE:
        donnees[c] = lire_date(d.get(c))
    return donnees


def analyser_lignes(paires):
    """Valide une liste de (numero_ligne, donnees) : règles métier, doublons
    avec la base existante, et doublons entre lignes du même fichier.
    Renvoie une liste de dicts {numero_ligne, donnees, erreurs}."""
    resultats = []
    vus = {"numero_registre_1": {}, "numero_registre_2": {}}
    libelles = {"numero_registre_1": "baptême", "numero_registre_2": "mariage"}

    for numero_ligne, donnees in paires:
        erreurs = valider_donnees(donnees) + verifier_unicite(donnees)
        for champ, dejavu in vus.items():
            valeur = donnees.get(champ)
            if not valeur:
                continue
            if valeur in dejavu:
                erreurs.append(
                    f"N° de registre {libelles[champ]} « {valeur} » utilisé "
                    f"aussi à la ligne {dejavu[valeur]} de ce fichier."
                )
            else:
                dejavu[valeur] = numero_ligne
        resultats.append({
            "numero_ligne": numero_ligne, "donnees": donnees, "erreurs": erreurs,
        })
    return resultats


@app.route("/importer", methods=["GET", "POST"])
@ecriture_requise
def importer():
    if request.method == "GET":
        return render_template("importer.html", resultats=None, paroisse=PAROISSE)

    etape = request.form.get("etape", "analyser")

    # -------- Étape 2 : la personne a vérifié l'aperçu et confirme --------
    if etape == "confirmer":
        try:
            lot = json.loads(request.form.get("donnees_json") or "[]")
        except ValueError:
            flash("La session d'import a expiré ou est invalide. Recommencez.", "error")
            return redirect(url_for("importer"))

        paires = [
            (item.get("numero_ligne"), donnees_depuis_json(item.get("donnees") or {}))
            for item in lot
        ]
        # On revalide entièrement : le champ cache a pu voyager côté
        # navigateur entre l'aperçu et la confirmation, et la base a pu
        # changer entre-temps (nouvelle fiche, numéro déjà pris…).
        resultats = analyser_lignes(paires)
        valides = [r for r in resultats if not r["erreurs"]]

        nouvelles_fiches = []
        for r in valides:
            record = Registre(**attribuer_numeros(r["donnees"]))
            db.session.add(record)
            nouvelles_fiches.append(record)
        try:
            db.session.flush()      # attribue un id à chaque fiche avant de journaliser
            for record in nouvelles_fiches:
                journaliser("creation", record, origine="import")
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                "L'import a échoué : un numéro de registre s'est trouvé en "
                "double au moment d'enregistrer (peut-être une autre "
                "création simultanée). Aucune fiche n'a été importée — "
                "réessayez.", "error"
            )
            return redirect(url_for("importer"))

        ignorees = len(resultats) - len(valides)
        message = f"{len(valides)} fiche(s) importée(s) depuis le fichier."
        if ignorees:
            message += (
                f" {ignorees} ligne(s) ignorée(s) : devenue(s) invalide(s) "
                f"ou en doublon depuis l'aperçu."
            )
        flash(message, "success" if valides else "error")
        return redirect(url_for("index"))

    # -------- Étape 1 : lecture et analyse du fichier envoyé --------
    fichier = request.files.get("fichier")
    if not fichier or not fichier.filename:
        flash("Choisissez un fichier .xlsx ou .csv à importer.", "error")
        return redirect(url_for("importer"))

    lignes_brutes, colonnes_ignorees, erreur = lire_fichier_import(fichier)
    if erreur:
        flash(erreur, "error")
        return redirect(url_for("importer"))
    if not lignes_brutes:
        flash("Ce fichier ne contient aucune ligne de données à importer.", "error")
        return redirect(url_for("importer"))

    paires = [
        (i, donnees_depuis_ligne(ligne))
        for i, ligne in enumerate(lignes_brutes, start=2)  # ligne 1 = en-têtes
    ]
    resultats = analyser_lignes(paires)
    valides = [r for r in resultats if not r["erreurs"]]

    # Passé tel quel (liste Python, pas déjà sérialisé) : le template le
    # sérialise avec le filtre |tojson, échappé pour un contexte HTML plutôt
    # qu'avec un json.dumps() brut inséré directement dans l'attribut.
    donnees_json = [
        {"numero_ligne": r["numero_ligne"], "donnees": donnees_vers_json(r["donnees"])}
        for r in valides
    ]

    return render_template(
        "importer.html", paroisse=PAROISSE, resultats=resultats,
        nb_valides=len(valides), nb_erreurs=len(resultats) - len(valides),
        colonnes_ignorees=colonnes_ignorees, donnees_json=donnees_json,
        nom_fichier=fichier.filename,
    )


@app.route("/importer/modele.csv")
@ecriture_requise
def importer_modele():
    exemple = {
        "nom": "NGOOH", "prenom": "Hervé", "nom_pere": "NGOOH Paul",
        "nom_mere": "MBALLA Marie", "date_naissance": "12/04/1990",
        "nationalite": "Camerounaise", "originaire_de": "Yaoundé",
        "date_bapteme": "02/06/2024", "lieu_bapteme": "Temple ICM Douala",
        "celebrant_bapteme": "Past. Jean ETOUNDI",
        "signature_1": "Past. Jean ETOUNDI", "telephone": "677000000",
        "observations": "Exemple à supprimer avant l'import",
    }
    colonnes = [(c, l) for c, l in COLONNES_EXPORT if c != "photo"]

    tampon = io.StringIO()
    tampon.write("﻿")
    writer = csv.writer(tampon, delimiter=";")
    writer.writerow([libelle for _, libelle in colonnes])
    writer.writerow([exemple.get(champ, "") for champ, _ in colonnes])

    return Response(
        tampon.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="modele_import_icm.csv"'},
    )


# ------------------------------------------------------------------
#  Filtres d'affichage
# ------------------------------------------------------------------
@app.template_filter("jj_mm_aaaa")
def jj_mm_aaaa(valeur):
    return valeur.strftime("%d/%m/%Y") if valeur else ""


@app.template_filter("iso")
def iso(valeur):
    return valeur.strftime("%Y-%m-%d") if valeur else ""


@app.template_filter("jj_mm_aaaa_hhmm")
def jj_mm_aaaa_hhmm(valeur):
    return valeur.strftime("%d/%m/%Y à %H:%M") if valeur else ""


@app.errorhandler(404)
def page_introuvable(_):
    return render_template("erreur.html", code=404,
                           message="Page ou enregistrement introuvable."), 404


@app.errorhandler(413)
def envoi_trop_gros(_):
    return render_template(
        "erreur.html", code=413,
        message="L'envoi est trop volumineux. La photo dépasse la limite de "
                "500 Ko même après compression automatique — revenez en "
                "arrière et reprenez le recadrage avec une image plus simple."
    ), 413


# ------------------------------------------------------------------
#  Démarrage
# ------------------------------------------------------------------
with app.app_context():
    db.create_all()
    # Empêche deux fiches de partager le même numéro de registre au niveau
    # de la base elle-même — pas seulement par le contrôle applicatif
    # verifier_unicite(), qui ne couvre pas une numérotation automatique
    # concurrente (deux créations/imports simultanés). NULL reste autorisé
    # en plusieurs exemplaires (une fiche pas encore baptisée/mariée), donc
    # un index unique simple suffit, sans clause partielle. Idempotent et
    # sans danger sur une base existante : si des doublons s'y trouvent déjà
    # (l'ancienne race condition, avant ce correctif), la création échoue
    # silencieusement et un avertissement s'affiche plutôt que de bloquer le
    # démarrage — nettoyez alors les doublons signalés puis redémarrez.
    for _nom_index, _colonne in (
        ("ux_registre_numero_registre_1", "numero_registre_1"),
        ("ux_registre_numero_registre_2", "numero_registre_2"),
    ):
        try:
            db.session.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_nom_index} "
                f"ON registre ({_colonne})"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            print(
                f"  ATTENTION : impossible de garantir l'unicité de "
                f"« {_colonne} » (des doublons existent déjà en base ?). "
                f"Vérifiez et corrigez-les manuellement."
            )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n  Registre ICM  →  http://127.0.0.1:{port}")
    for identifiant, compte in COMPTES.items():
        print(f"  Identifiant : {identifiant}  ({LIBELLES_ROLES[compte['role']]})")
    if DEBUG:
        print("  Mode debug ACTIVÉ — ne jamais utiliser ce réglage sur un "
              "déploiement accessible depuis l'extérieur.")
    print()
    app.run(debug=DEBUG, host="0.0.0.0", port=port)