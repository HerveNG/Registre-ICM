# Registre numérique des Baptêmes & Mariages — In Christ Ministries

MVP construit à partir de la carte papier ICM (baptême / mariage).
Deux applications sont livrées, elles partagent le **même modèle de données** :

| | `web/index.html` — **version en ligne** | `app.py` — **version locale (Flask)** |
|---|---|---|
| Installation | aucune : un fichier HTML à ouvrir | Python + `pip install` |
| Base de données | Supabase (PostgreSQL, gratuit) | SQLite, fichier sur le PC |
| Nombre de postes | illimité, chacun avec son compte | un seul poste |
| Sauvegarde | assurée par Supabase | à faire à la main |
| À utiliser quand… | le registre est en service | pour tester, ou sans internet |

> **Par où commencer ?** Ouvrez la version Flask pour prendre l'application
> en main hors ligne. Passez à la version en ligne dès que plusieurs personnes
> doivent saisir. Voir `CHOIX_BASE_DE_DONNEES.md`.

---

## 1. Ce que l'application fait

- saisir une carte : identité, parents, naissance, nationalité, origine ;
- ajouter la **photo d'identité** : choix du fichier, recadrage au format 3/4,
  compression automatique, remplacement et retrait ;
- enregistrer le **baptême** : date, lieu, célébrant, n° de registre, signature ;
- compléter le **mariage** plus tard : lieu, date, conjoint, n° de registre, signature ;
- **attribuer automatiquement** les numéros : `ICM-B-2026-0001`, `ICM-M-2026-0001` ;
- **rechercher** par nom, prénom, n° de registre ou conjoint ;
- **filtrer** : baptisés / mariés / baptême non renseigné ;
- modifier, supprimer ;
- **imprimer la carte** remplie (ou l'enregistrer en PDF) ;
- **exporter tout le registre** en fichier Excel/CSV ;
- **protéger l'accès** par identifiant et mot de passe.

### Contrôles automatiques

L'application refuse : un nom ou prénom vide · une date dans le futur ·
un baptême ou un mariage antérieur à la naissance · un numéro de registre
déjà attribué à une autre carte.

---

## 2. Contenu du dossier

```
mvp_registre_bapteme_mariage/
├── README.md                      ← ce fichier
├── CHOIX_BASE_DE_DONNEES.md       ← comparatif et recommandation
│
├── web/
│   └── index.html                 ← APPLICATION EN LIGNE (fichier unique)
│
├── database/
│   ├── schema_supabase.sql        ← à exécuter dans Supabase
│   ├── migration_01_photo.sql     ← si la base existait AVANT les photos
│   └── schema_sqlite.sql          ← documentation du schéma local
│
├── app.py                         ← APPLICATION FLASK
├── requirements.txt
├── .env.example                   ← à copier en « .env »
├── templates/                     ← pages (connexion, liste, formulaire, carte)
└── static/
    ├── style.css
    ├── photo.js                   ← recadrage et compression des photos
    └── photos/                    ← photos enregistrées (version Flask)
```

---

## 3. Version en ligne — mise en service

**a) Créer la base (une seule fois, ~20 min)**

1. Compte gratuit sur [supabase.com](https://supabase.com) → **New project**
   (région conseillée : *eu-west-3 / Paris*).
2. **SQL Editor → New query** : coller tout `database/schema_supabase.sql`, **Run**.
   Ce script crée la table **et** l'espace de stockage des photos.
3. **Authentication → Users → Add user** : créer un compte e-mail + mot de passe
   par personne du secrétariat.
4. **Project Settings → API** : noter l'`URL` du projet et la clé `anon`.

> **Vous aviez déjà créé la base avant les photos ?** Ne rejouez pas le
> script complet : exécutez `database/migration_01_photo.sql`, qui ajoute
> seulement la colonne `photo` et le bucket, sans toucher à vos données.

**b) Relier l'application**

Ouvrez `web/index.html` dans un navigateur : le premier écran demande l'URL
et la clé. Saisissez-les, elles sont mémorisées dans ce navigateur.

Pour les inscrire une fois pour toutes dans le fichier, éditez le bloc situé
en haut de `web/index.html` :

```js
const CONFIG_PAR_DEFAUT = {
  url:  "https://xxxxxxxx.supabase.co",
  cle:  "eyJhbGciOi...",
  eglise: "In Christ Ministries"
};
```

**c) Rendre l'application accessible à tous (facultatif, gratuit)**

Le fichier fonctionne en double-cliquant dessus. Pour y accéder depuis
n'importe quel poste ou téléphone, déposez le dossier `web/` sur
[app.netlify.com/drop](https://app.netlify.com/drop) ou sur Vercel : vous
obtenez une adresse web en une minute, sans compte payant.

> **Sécurité.** La clé `anon` est prévue pour figurer dans l'application :
> les règles RLS du script SQL font qu'elle ne donne accès à rien sans
> connexion. Ne mettez **jamais** la clé `service_role` dans ce fichier.

---

## 4. Version locale (Flask) — installation

```bash
python -m venv .venv
```

Windows :
```bat
.venv\Scripts\activate
```
macOS / Linux :
```bash
source .venv/bin/activate
```

Puis :
```bash
pip install -r requirements.txt
copy .env.example .env        REM Windows   (cp .env.example .env ailleurs)
python app.py
```

Ouvrir <http://127.0.0.1:5000>.
Identifiants par défaut : **admin / icm2026** — *à changer dans `.env` avant
toute utilisation réelle.* La base `registre.db` est créée automatiquement.

### Brancher Flask sur Supabase plutôt que SQLite

1. Décommenter `psycopg[binary]` dans `requirements.txt`, puis réinstaller.
2. Renseigner dans `.env` :
   `DATABASE_URL=postgresql://postgres.xxxx:MOT_DE_PASSE@aws-0-eu-west-3.pooler.supabase.com:5432/postgres`

---

## 5. Imprimer une carte en PDF

Cliquer **Carte** sur une ligne du registre → **Imprimer / Enregistrer en PDF**
→ dans la fenêtre d'impression, choisir *Destination : Enregistrer au format PDF*.

La carte sort sur deux pages A5 paysage : la couverture (verset de
Galates 3 : 26-27 et titre) puis l'intérieur rempli.
Pensez à cocher **« Graphiques d'arrière-plan »** pour conserver les filets dorés.

Le logo ICM est représenté par un rond portant le sigle. Pour utiliser le
logo réel, remplacez dans `templates/carte.html` (et dans `web/index.html`)
le bloc `<div class="sigle-carte">ICM</div>` par
`<img src="logo.png" style="width:26mm">`.

---

## 6. Photos d'identité

Dans le formulaire, **Choisir une photo** ouvre une fenêtre de recadrage :
faites glisser l'image pour centrer le visage, ajustez le zoom, validez.
L'application produit alors un JPEG 600 × 800 (format identité 3/4)
d'environ 60 à 120 Ko, quelle que soit la taille de l'original — une photo
de téléphone de 5 Mo est ramenée à moins de 100 Ko.

La photo apparaît ensuite en vignette dans le registre et dans le cadre
en haut à droite de la carte imprimée.

**L'image n'est jamais stockée dans la base**, seulement son emplacement :

| Version | Où vit l'image | Colonne `photo` |
|---|---|---|
| En ligne | bucket Supabase `photos`, **privé** | `fideles/ab12cd34.jpg` |
| Flask | dossier `static/photos/` | `ab12cd34.jpg` |

Le bucket étant privé, une photo n'est accessible par aucune adresse
publique : l'application demande un lien temporaire (valable 1 h) à chaque
affichage, et seuls les comptes connectés peuvent en obtenir un.

Remplacer ou retirer une photo, ou supprimer une carte, efface l'ancien
fichier — le stockage ne se remplit pas d'images orphelines.

---

## 7. Sauvegardes

Une fois par mois : bouton **Export Excel** → ranger le fichier
`registre_icm_AAAA-MM-JJ.csv` en dehors de l'ordinateur (clé USB, Drive).
C'est la seule sauvegarde qui vous appartienne vraiment.

> ⚠️ **L'export ne contient pas les images**, seulement le nom du fichier
> photo de chaque fidèle. Pour sauvegarder aussi les photos :
> - version en ligne : Supabase → **Storage → photos → Download** ;
> - version Flask : copier le dossier `static/photos/`.

---

## 8. Ce qui reste à faire pour une version 2

- comptes différenciés (secrétaire / pasteur / lecture seule) ;
- journal d'audit : qui a créé ou modifié quelle carte, et quand ;
- import du registre papier existant depuis un fichier Excel ;
- signature scannée du célébrant sur la carte ;
- séparation des personnes et des actes (un mariage = deux fidèles liés) ;
- attestations et statistiques annuelles imprimables ;
- envoi automatique de la carte par e-mail ou WhatsApp.

---

## 9. Modèle de données

Un enregistrement = une carte = un fidèle. Le bloc mariage reste vide tant
que la personne n'est pas mariée, exactement comme sur la carte papier.

| Champ | Correspondance sur la carte |
|---|---|
| `nom`, `prenom` | Nom, Prénom |
| `nom_pere`, `nom_mere` | Fils de :, Et de : |
| `date_naissance` | Né(e) le : |
| `date_bapteme` | Baptisé(e) le : |
| `numero_registre_1` | N° du Registre (1) |
| `nationalite`, `originaire_de` | Nationalité, Originaire de |
| `signature_1` | Signature (1) — *certifié exact* |
| `lieu_mariage` | MARIAGE — A : |
| `date_mariage` | Le : |
| `conjoint` | Avec : |
| `numero_registre_2` | N° du Registre (2) |
| `signature_2` | Signature (2) |
| `photo` | cadre photo en haut à droite de l'intérieur |
| `lieu_bapteme`, `celebrant_*`, `telephone`, `observations` | ajouts utiles au registre |
