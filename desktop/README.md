# Version bureau — exécutable Windows

Un `.exe` autonome à double-cliquer, sans navigateur visible, sans Python ni
rien d'autre à installer sur le poste cible. Ce n'est **pas** une troisième
application : c'est la version en ligne (`web/index.html`, déjà connectée à
Supabase — voir `README.md` §3) simplement affichée dans une fenêtre native
au lieu d'un onglet de navigateur.

**Rien ne change côté données ni sécurité** : même connexion à Supabase,
mêmes comptes, mêmes rôles (secrétaire / pasteur / visiteur), mêmes règles
RLS. Un poste sur lequel ce `.exe` est installé n'a accès à rien de plus
qu'un poste ouvrant `web/index.html` dans un navigateur — les deux
nécessitent un compte Supabase valide avec un rôle attribué (§5 du README
principal). Aucun identifiant n'est intégré dans l'exécutable, seule la clé
`anon`, publique par conception.

## Construire le .exe

Prérequis : l'environnement virtuel Python du projet déjà créé (`README.md`
§4), sur un poste Windows.

```powershell
powershell -ExecutionPolicy Bypass -File desktop\construire.ps1
```

Ce script :
1. installe `pywebview` et `pyinstaller` dans `.venv` (build uniquement,
   jamais nécessaires pour faire tourner l'exécutable une fois construit) ;
2. convertit `static/logo.png` en icône Windows (`desktop/icone.ico`) ;
3. produit `desktop\dist\Registre-ICM.exe`.

## Installer sur un autre poste

Copier uniquement `desktop\dist\Registre-ICM.exe` sur le poste cible (clé
USB, partage réseau, e-mail) et le lancer. Rien d'autre à installer — sauf
sur un Windows très ancien ou allégé où le runtime **WebView2** ne serait
pas déjà présent (il l'est nativement sur toute installation Windows 10/11
à jour) : Windows proposera alors de l'installer automatiquement au premier
lancement, ou téléchargez-le depuis
[developer.microsoft.com/microsoft-edge/webview2](https://developer.microsoft.com/microsoft-edge/webview2/).

Le poste doit simplement avoir accès à Internet pour joindre Supabase — pas
de VPN ni de configuration réseau particulière, exactement comme pour
`web/index.html` dans un navigateur.

## Limites connues

- Si l'adresse ou la clé Supabase changent un jour (nouveau projet), il
  faut reconstruire l'exécutable après avoir modifié `CONFIG_PAR_DEFAUT` en
  haut de `web/index.html`, puis redistribuer le nouveau `.exe` à tous les
  postes — pas de mise à jour automatique.
- L'exécutable n'est pas signé numériquement : Windows SmartScreen peut
  afficher un avertissement au premier lancement sur un poste qui ne l'a
  jamais vu (« Éditeur inconnu »). C'est normal pour un exécutable non
  signé et sans rapport avec la sécurité de l'application elle-même.
