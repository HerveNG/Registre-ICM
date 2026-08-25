# Tests automatiques

Filet de sécurité pour les deux versions de l'application (voir § 13 du
`README.md` principal) : ces tests rejouent, à chaque modification de
`app.py` ou de `web/index.html`, les vérifications qui ont validé l'audit
de sécurité du 25/08/2026 — pour qu'une régression future (un correctif
défait par erreur, un champ qui redevient non validé...) soit signalée
avant même d'atteindre la production, plutôt que découverte plus tard.

Ils tournent automatiquement à chaque `git push` via une action GitHub
(`.github/workflows/tests.yml`, onglet **Actions** du dépôt).

## Ce que ça couvre

| Fichier | Ce qu'il teste | Comment |
|---|---|---|
| `test_auth.py` | Connexion, anti brute-force, redirection après connexion (anti-hameçonnage), contrôle d'accès par rôle | Flask test client contre `app.py` |
| `test_security_headers.py` | En-têtes HTTP de sécurité, page d'erreur générique | idem |
| `test_csrf.py` | Jeton anti-CSRF sur les formulaires | idem |
| `test_validation.py` | Règles métier (dates, longueurs, champs obligatoires), numérotation automatique, unicité | idem |
| `test_photos.py` | Revalidation réelle du contenu des photos, plafond de taille, route protégée | idem |
| `test_registre_routes.py` | Cycle de vie d'une fiche : création, modification, suppression | idem |
| `test_export_import.py` | Anti-injection de formule CSV, reconnaissance des en-têtes à l'import | idem |
| `test_journal.py` | Journal d'audit : une entrée par action, jamais modifiable | idem |
| `test_schema_supabase.py` | Garde-fous **statiques** sur `database/schema_supabase.sql` (RLS, revokes, trigger d'immuabilité du rôle) | lecture du fichier SQL, sans base réelle — voir la note plus bas |
| `test_web_index.py` | Les mêmes familles de règles (échappement HTML, dates, anti-injection CSV, validation, permissions, lecture CSV) mais côté **version en ligne** | Playwright + Chromium, en chargeant le vrai `web/index.html` et en appelant ses fonctions JS |

À la date de ce commit : 76 tests pour la version Flask, 25 pour la
version en ligne, 11 garde-fous statiques sur le schéma Supabase.

**Ce qui n'est *pas* couvert**, et pourquoi : les policies RLS et le
trigger `profils_role_immuable` ne sont testés ici que *statiquement*
(le texte du SQL est vérifié, pas son exécution) — les tester en
conditions réelles demanderait de faire tourner un projet Supabase
complet (schéma `auth`, PostgREST...) en CI, ce qui dépasse la portée
d'une action GitHub simple. `static/photo.js` (recadrage/compression
d'image côté navigateur, utilise l'API Canvas) n'est pas non plus testé
automatiquement : sa logique est visuelle et manipulée à la souris,
moins adaptée à un test scripté que le reste de l'application.

## Lancer les tests en local

```bash
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate

pip install -r requirements.txt        # dépendances de l'application
pip install -r tests/requirements.txt  # + pytest, playwright

playwright install chromium        # une seule fois : télécharge le navigateur
                                    # utilisé pour tester web/index.html

pytest tests/                      # tout lancer
pytest tests/test_auth.py -v       # un seul fichier
pytest tests/ -k "csv"             # seulement les tests dont le nom contient "csv"
```

Aucun de ces tests ne touche `registre.db` ni le dossier `photos/` réels :
chaque test utilise une base SQLite temporaire et un dossier de photos
temporaire, effacés à la fin. `test_web_index.py` n'appelle jamais un
vrai projet Supabase (les requêtes vers `*.supabase.co` sont interceptées
et bloquées pendant les tests).

Si Playwright ne trouve pas son navigateur (exécutable Chromium absent ou
version incompatible), vous pouvez pointer vers un Chromium existant sans
le retélécharger :

```bash
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/chemin/vers/chromium pytest tests/test_web_index.py
```

## Ajouter un test

- Un nouveau comportement dans `app.py` → un test dans le fichier
  `test_*.py` correspondant (ou un nouveau fichier si le sujet est
  vraiment distinct), en utilisant les fixtures de `conftest.py`
  (`client`, `client_secretaire`, `client_pasteur`, `client_visiteur`,
  `dossier_photos`, `icm_app`).
- Un nouveau comportement dans `web/index.html` → un test dans
  `test_web_index.py`, en appelant la fonction JS réelle via
  `page.evaluate(...)` plutôt qu'en réimplémentant sa logique en Python.
- Une nouvelle protection dans `database/schema_supabase.sql` → une
  assertion supplémentaire dans `test_schema_supabase.py`.
