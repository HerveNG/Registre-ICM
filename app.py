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
import unicodedata
import uuid
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask, Response, abort, flash, redirect, render_template,
    request, session, url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, func
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


# ------------------------------------------------------------------
#  Configuration
# ------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "changez-moi-en-production")

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

# Dossier des photos d'identité (les images ne vont pas dans la base)
DOSSIER_PHOTOS = os.path.join(app.static_folder, "photos")
os.makedirs(DOSSIER_PHOTOS, exist_ok=True)

# 500 Ko : plafond imposé à chaque photo. Le navigateur (static/photo.js)
# compresse déjà l'image sous ce seuil avant de l'envoyer — ce contrôle est
# la seconde ligne de défense, côté serveur, au cas où l'envoi ne passerait
# pas par ce chemin normal (ancien navigateur, appel direct, etc.).
PHOTO_TAILLE_MAX = 500 * 1024

# La photo recadrée arrive dans un champ de formulaire (texte base64, environ
# 1,33 fois plus lourd que l'image d'origine). Sans ces deux réglages, Flask
# coupe les envois volumineux avec une page d'erreur brute avant même que le
# contrôle ci-dessus s'exécute : on fixe des limites nettes, larges par
# rapport aux ~665 Ko qu'occupe une photo de 500 Ko une fois encodée, pour
# que ce soit PHOTO_TAILLE_MAX qui réponde, avec un message compréhensible.
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["MAX_FORM_MEMORY_SIZE"] = 2 * 1024 * 1024

db = SQLAlchemy(app)


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


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        utilisateur = request.form.get("utilisateur", "").strip()
        mot_de_passe = request.form.get("mot_de_passe", "")
        compte = COMPTES.get(utilisateur)
        if compte and check_password_hash(compte["hash"], mot_de_passe):
            session["utilisateur"] = utilisateur
            session["role"] = compte["role"]
            return redirect(request.args.get("suivant") or url_for("index"))
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


def enregistrer_photo(data_url):
    """Décode l'image recadrée envoyée par le navigateur et l'écrit sur disque.

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

    nom = f"{uuid.uuid4().hex}.{extension}"
    with open(os.path.join(DOSSIER_PHOTOS, nom), "wb") as fichier:
        fichier.write(binaire)
    return nom, None


def appliquer_photo(record, form):
    """Applique la photo envoyée par le formulaire à un enregistrement.

    Trois cas : nouvelle photo, retrait de la photo, ou aucun changement.
    Renvoie un message d'erreur, ou None si tout s'est bien passé.
    """
    data_url = (form.get("photo_data") or "").strip()
    retirer = form.get("photo_retiree") == "1"

    if data_url:
        nom, erreur = enregistrer_photo(data_url)
        if erreur:
            return erreur
        ancienne = record.photo
        record.photo = nom
        if ancienne and ancienne != nom:
            supprimer_photo(ancienne)
    elif retirer and record.photo:
        supprimer_photo(record.photo)
        record.photo = None
    return None


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
    donnees = {c: (form.get(c, "") or "").strip() or None for c in CHAMPS_TEXTE}
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

        erreur_photo = appliquer_photo(record, request.form)
        if erreur_photo:
            flash(erreur_photo, "error")
            return render_template("form.html", record=None,
                                   valeurs=request.form, paroisse=PAROISSE)

        db.session.add(record)
        db.session.commit()
        flash(f"Carte de {record.nom_complet} enregistrée "
              f"(N° {record.numero_registre_1 or '—'}).", "success")
        return redirect(url_for("index"))

    return render_template("form.html", record=None, valeurs={}, paroisse=PAROISSE)


@app.route("/modifier/<int:record_id>", methods=["GET", "POST"])
@ecriture_requise
def modifier(record_id):
    record = db.session.get(Registre, record_id) or abort(404)

    if request.method == "POST":
        donnees, erreurs = collecter_formulaire(request.form)
        erreurs += verifier_unicite(donnees, id_courant=record.id)
        if erreurs:
            for e in erreurs:
                flash(e, "error")
            return render_template("form.html", record=record,
                                   valeurs=request.form, paroisse=PAROISSE)

        erreur_photo = appliquer_photo(record, request.form)
        if erreur_photo:
            db.session.rollback()
            flash(erreur_photo, "error")
            return render_template("form.html", record=record,
                                   valeurs=request.form, paroisse=PAROISSE)

        for champ, valeur in attribuer_numeros(donnees).items():
            setattr(record, champ, valeur)
        db.session.commit()
        flash(f"Carte de {record.nom_complet} mise à jour.", "success")
        return redirect(url_for("index"))

    return render_template("form.html", record=record, valeurs={}, paroisse=PAROISSE)


@app.post("/supprimer/<int:record_id>")
@ecriture_requise
def supprimer(record_id):
    record = db.session.get(Registre, record_id) or abort(404)
    nom = record.nom_complet
    photo = record.photo
    db.session.delete(record)
    db.session.commit()
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


# ------------------------------------------------------------------
#  Export CSV (ouvrable directement dans Excel)
# ------------------------------------------------------------------
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
            ligne.append(valeur or "")
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
    None, dates converties."""
    donnees = {c: _valeur_texte_import(ligne_brute.get(c)) for c in CHAMPS_TEXTE}
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

        for r in valides:
            db.session.add(Registre(**attribuer_numeros(r["donnees"])))
        db.session.commit()

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

    donnees_json = json.dumps([
        {"numero_ligne": r["numero_ligne"], "donnees": donnees_vers_json(r["donnees"])}
        for r in valides
    ])

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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    print(f"\n  Registre ICM  →  http://127.0.0.1:{port}")
    for identifiant, compte in COMPTES.items():
        print(f"  Identifiant : {identifiant}  ({LIBELLES_ROLES[compte['role']]})")
    print()
    app.run(debug=debug, host="0.0.0.0", port=port)