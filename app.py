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
import os
import re
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


# ------------------------------------------------------------------
#  Configuration
# ------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "changez-moi-en-production")

# Identifiants du secrétariat (à changer dans le fichier .env)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH") or generate_password_hash(
    os.getenv("ADMIN_PASSWORD", "icm2026")
)

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
PHOTO_TAILLE_MAX = 3 * 1024 * 1024      # 3 Mo après recadrage : très large

# La photo recadrée arrive dans un champ de formulaire (texte base64).
# Sans ces deux réglages, Flask coupe les envois volumineux avec une page
# d'erreur brute : on fixe des limites nettes, bien au-dessus d'une photo
# d'identité (≈ 60 à 120 Ko), pour que ce soit le contrôle ci-dessus qui
# réponde, avec un message compréhensible.
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["MAX_FORM_MEMORY_SIZE"] = 6 * 1024 * 1024

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
    @wraps(vue)
    def wrapper(*args, **kwargs):
        if not session.get("utilisateur"):
            return redirect(url_for("connexion", suivant=request.path))
        return vue(*args, **kwargs)
    return wrapper


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        utilisateur = request.form.get("utilisateur", "").strip()
        mot_de_passe = request.form.get("mot_de_passe", "")
        if utilisateur == ADMIN_USER and check_password_hash(
            ADMIN_PASSWORD_HASH, mot_de_passe
        ):
            session["utilisateur"] = utilisateur
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
        return None, "Photo trop lourde."
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


def collecter_formulaire(form):
    """Lit le formulaire et renvoie (données, liste d'erreurs)."""
    donnees = {c: (form.get(c, "") or "").strip() or None for c in CHAMPS_TEXTE}
    for c in CHAMPS_DATE:
        donnees[c] = lire_date(form.get(c))

    erreurs = []
    if not donnees["nom"]:
        erreurs.append("Le nom est obligatoire.")
    if not donnees["prenom"]:
        erreurs.append("Le prénom est obligatoire.")

    aujourdhui = date.today()
    for libelle, champ in (
        ("naissance", "date_naissance"),
        ("baptême", "date_bapteme"),
        ("mariage", "date_mariage"),
    ):
        if donnees[champ] and donnees[champ] > aujourdhui:
            erreurs.append(f"La date de {libelle} ne peut pas être dans le futur.")

    if donnees["date_naissance"] and donnees["date_bapteme"] \
            and donnees["date_bapteme"] < donnees["date_naissance"]:
        erreurs.append("Le baptême ne peut pas précéder la naissance.")
    if donnees["date_naissance"] and donnees["date_mariage"] \
            and donnees["date_mariage"] < donnees["date_naissance"]:
        erreurs.append("Le mariage ne peut pas précéder la naissance.")

    return donnees, erreurs


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
@login_requis
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
@login_requis
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
@login_requis
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
@login_requis
def export_csv():
    colonnes = [
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
        message="L'envoi est trop volumineux. La photo doit peser moins de "
                "3 Mo une fois recadrée — reprenez-la avec une image plus petite."
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
    print(f"  Identifiant : {ADMIN_USER}\n")
    app.run(debug=debug, host="0.0.0.0", port=port)
