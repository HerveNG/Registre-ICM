# Quelle base de données gratuite pour le registre ICM ?

## En une phrase

**Supabase (PostgreSQL), plan gratuit** — c'est la recommandation.
500 enregistrements représentent environ **0,3 Mo**, soit moins de **0,1 %**
de ce que le plan gratuit accorde. La place n'est donc pas le sujet : ce qui
compte, c'est ce que la base apporte *en plus* du simple stockage.

---

## 1. De quelle taille parle-t-on réellement ?

Il faut compter deux espaces séparés, et c'est justement ce qui rend la
solution confortable : **le texte va dans la base, les photos vont dans un
espace fichiers**. Une carte complète (nom, parents, dates, nationalité,
origine, numéros de registre, conjoint, signatures, observations) pèse
environ **600 octets**. Une photo d'identité recadrée par l'application
pèse en pratique **40 à 120 Ko**, et ne dépasse jamais **500 Ko** — une
limite garantie par une compression automatique côté application, et
imposée en plus par la base elle-même (le bucket Supabase des photos
refuse tout fichier plus lourd).

| Nombre de cartes | Base (500 Mo gratuits) | Photos, cas courant ~90 Ko (1 Go gratuit) | Photos, pire cas 500 Ko |
|---|---|---|---|
| 500 | ≈ 0,3 Mo — **0,06 %** | ≈ 45 Mo — **4,5 %** | ≈ 250 Mo — 25 % |
| 5 000 | ≈ 3 Mo — 0,6 % | ≈ 450 Mo — 45 % | ≈ 2,4 Go — au-delà du gratuit |
| 11 000 | ≈ 7 Mo — 1,3 % | ≈ 1 Go — **100 %** | — |

**Pour 500 fidèles, vous utilisez entre 4,5 % et 25 % de l'espace photos
gratuit selon la netteté des images — jamais plus, grâce au plafond.**
Ce sont les photos, et non le registre, qui fixeront un jour la limite :
même dans le pire des cas (toutes les photos à 500 Ko), il faudrait
dépasser 2 000 fidèles photographiés avant d'y songer ; dans le cas
courant, on tient plusieurs milliers de fidèles. Vous ne paierez jamais
pour la volumétrie du texte. La vraie question est celle de la fiabilité
et de la pérennité.

---

## 2. Comparatif des solutions gratuites

| Solution | Type | Ce que donne le plan gratuit | Avantages pour l'ICM | Limites à connaître |
|---|---|---|---|---|
| **Supabase** ⭐ | PostgreSQL hébergé | ~500 Mo de base, ~1 Go de fichiers, comptes utilisateurs inclus, 2 projets actifs | Base + **stockage des photos** + **gestion des comptes** + **API web** en un seul service, sauvegardes, interface d'administration lisible, permet à plusieurs postes de travailler ensemble | Le projet est **mis en pause après ~1 semaine sans aucune activité** — un simple clic le réveille. À éviter : laisser le registre dormir des mois |
| **Neon** | PostgreSQL hébergé | ~0,5 Go de stockage, heures de calcul mensuelles plafonnées | Excellent PostgreSQL, démarrage très rapide | **Ni comptes utilisateurs, ni API web, ni stockage de fichiers** : il faudrait un serveur et un hébergeur d'images en plus. Beaucoup plus de travail |
| **MongoDB Atlas (M0)** | Base documents | 512 Mo | Gratuit sans limite de durée | Modèle « documents » mal adapté à un registre officiel, où l'on veut des **contraintes strictes** (pas deux fois le même n° de registre) |
| **Firebase / Firestore** | Base documents Google | Quota quotidien de lectures/écritures | Très simple, gestion de comptes incluse | Facturation à l'usage difficile à prévoir ; export des données moins direct qu'en SQL |
| **Airtable / Google Sheets** | Tableur en ligne | Quelques milliers de lignes | Aucune compétence technique requise | **Pas une base de données** : aucune contrainte d'intégrité, historique fragile, risque élevé d'écrasement accidentel. À proscrire pour un registre qui fait foi |
| **SQLite** (fichier local) | Fichier sur le PC | Illimité, hors ligne | Zéro configuration, zéro compte, **c'est le mode par défaut de l'application Flask livrée** | Un seul poste, aucune sauvegarde automatique. Si le disque tombe en panne, le registre disparaît |

> Les chiffres des plans gratuits évoluent régulièrement. Vérifiez-les sur la
> page tarifaire au moment de créer le compte — l'ordre de grandeur, lui,
> ne change pas : tous ces plans sont **très largement** au-dessus de vos besoins.

---

## 3. Pourquoi Supabase pour une église

Le registre des baptêmes et des mariages est un document qui **fait foi**.
Trois exigences dominent :

1. **On ne doit pas pouvoir le perdre.**
   Supabase héberge et sauvegarde la base. Un ordinateur volé ou en panne
   n'emporte plus le registre avec lui.

2. **On doit savoir qui y touche.**
   Chaque personne du secrétariat reçoit son propre compte (e-mail + mot de
   passe). Les règles de sécurité livrées dans `database/schema_supabase.sql`
   font que **sans compte valide, la base ne répond rien** — même si
   quelqu'un récupérait le fichier de l'application.

3. **On ne doit pas pouvoir y écrire n'importe quoi.**
   Le schéma refuse un baptême antérieur à la naissance, refuse deux fois le
   même numéro de registre, et attribue automatiquement le numéro suivant
   (`ICM-B-2026-0001`). Un tableur ne fait rien de tout cela.

S'y ajoute une quatrième exigence, apparue avec les photos :

4. **Les visages des fidèles ne doivent pas traîner sur le web.**
   Les photos sont rangées dans un espace **privé** : aucune adresse
   publique ne permet d'y accéder. L'application demande un lien temporaire
   d'une heure à chaque affichage, et seuls les comptes connectés peuvent en
   obtenir un. Un hébergement d'images ordinaire ne donne pas cette garantie.

S'ajoute un argument pratique : Supabase fournit **en même temps** la base,
le stockage des photos, les comptes utilisateurs et l'accès web. C'est ce qui
permet à l'application livrée dans `web/index.html` de fonctionner **sans
aucun serveur à installer ni à payer**.

---

## 4. La stratégie recommandée

**Commencez en local, basculez en ligne quand le besoin arrive.**

| Étape | Base | Application | Quand ? |
|---|---|---|---|
| 1 — Prise en main | SQLite (fichier `registre.db`) | Flask, sur un seul PC | Tout de suite, pour saisir les premières cartes sans rien créer en ligne |
| 2 — Mise en service | Supabase (gratuit) | `web/index.html`, depuis n'importe quel poste | Dès que plusieurs personnes saisissent, ou dès que vous voulez des sauvegardes |
| 3 — Si vous grandissez | Supabase payant (~25 $/mois) | inchangée | Uniquement si vous dépassez le plan gratuit — improbable avant plusieurs milliers de cartes |

Le passage de l'étape 1 à l'étape 2 ne perd rien : l'export CSV de
l'application Flask se réimporte directement dans Supabase.

---

## 5. Les deux précautions à prendre

**a) La mise en pause après inactivité.**
Le plan gratuit Supabase suspend un projet resté sans aucune activité pendant
environ une semaine. Rien n'est perdu — le projet se relance en un clic depuis
le tableau de bord — mais l'application affichera une erreur en attendant.
Si l'activité de saisie est très irrégulière, prenez l'habitude d'ouvrir
l'application une fois par semaine.

**b) La sauvegarde vous appartient aussi.**
Une fois par mois, cliquez sur **Export Excel** dans l'application et rangez
le fichier obtenu ailleurs (clé USB, Google Drive, e-mail à vous-même).
Un hébergeur gratuit ne vous doit aucune garantie contractuelle : cette copie
mensuelle est votre vraie assurance, et elle prend dix secondes.

Attention : **cet export ne contient pas les photos**, seulement le nom de
fichier de chacune. Pour les sauvegarder, passez par Supabase →
**Storage → photos → Download**. Une à deux fois par an suffit.

---

## 6. Ce que Supabase demande comme travail, concrètement

1. Créer un compte sur `supabase.com` (gratuit, sans carte bancaire).
2. Créer un projet — choisir la région la plus proche
   (par exemple *eu-west-3, Paris*, la plus rapide depuis l'Afrique centrale).
3. Ouvrir **SQL Editor**, coller le contenu de
   `database/schema_supabase.sql`, cliquer **Run**. Ce script crée la table,
   les règles de sécurité **et** l'espace de stockage des photos.
4. Dans **Authentication → Users → Add user**, créer un compte par personne
   du secrétariat.
5. Dans **Project Settings → API**, copier l'`URL` et la clé `anon`,
   les coller dans l'application.

Si la base existait déjà avant l'ajout des photos, exécutez plutôt
`database/migration_01_photo.sql` : il ajoute la colonne et le bucket
sans toucher aux fiches déjà saisies.

Comptez une vingtaine de minutes la première fois.

> ⚠️ La clé `anon` est faite pour être dans l'application : elle ne donne
> accès à rien tant que l'utilisateur ne s'est pas connecté, grâce aux règles
> de sécurité du script SQL. En revanche, la clé `service_role` ne doit
> **jamais** sortir du tableau de bord Supabase : elle contourne toutes les
> règles.

---

*Sources consultées pour les plans gratuits :*
[Supabase Pricing 2026 — UI Bakery](https://uibakery.io/blog/supabase-pricing) ·
[Supabase Free Tier Limits 2026](https://www.itpathsolutions.com/supabase-free-tier-limits) ·
[Neon — managed Postgres free tiers](https://neon.com/faqs/managed-postgres-databases-free-tier)
