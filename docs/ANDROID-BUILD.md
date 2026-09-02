# Version Android — construire l'APK et l'AAB

La version Android encapsule **`web/index.html`** tel quel (aucune
réécriture) dans une coquille native via **Capacitor**. Elle parle à la même
base Supabase, avec les mêmes comptes et les mêmes rôles que les versions
Web et Windows — voir `README.md` §3 et §5. Rien de tout cela ne change ici.

Toutes les commandes ci-dessous s'exécutent depuis la **racine du dépôt**,
dans **PowerShell**, sous Windows.

---

## 1. Prérequis

| Outil | Version utilisée / testée | Pourquoi |
|---|---|---|
| Node.js + npm | Node 26, npm 11 (toute version récente convient) | Capacitor CLI |
| **JDK 21** | Temurin 21 (Eclipse Adoptium) | Compile le code Android — **Capacitor 7 exige JDK 21**, JDK 17 ne suffit plus (erreur `invalid source release: 21` sinon) |
| Android SDK | Platform 35, Build-Tools 35.0.0, Platform-Tools | Compilation et outils `adb`/`apksigner` |
| Android Studio *(optionnel)* | Dernière version stable | Confortable pour déboguer sur émulateur/téléphone, pas obligatoire : tout se fait en ligne de commande |

> Un JDK 17 (comme celui utilisé pour la version bureau, `desktop/`) reste
> parfaitement valable **pour PyInstaller** — ne le confondez pas avec celui
> utilisé ici pour Android : ce sont deux toolchains indépendantes.

---

## 2. Installation d'Android Studio (recommandé, GUI)

1. Télécharger sur <https://developer.android.com/studio> et installer
   normalement.
2. Au premier lancement, l'assistant propose d'installer le SDK — accepter
   les emplacements par défaut (`%LOCALAPPDATA%\Android\Sdk`).
3. **SDK Manager** (icône ⚙ ou *More Actions*) → onglet *SDK Platforms* :
   cocher **Android 15.0 (API 35)** → *Apply*.
4. Onglet *SDK Tools* : cocher **Android SDK Build-Tools 35** et
   **Android SDK Platform-Tools** → *Apply*.

Si vous préférez tout faire en ligne de commande sans installer l'IDE
complet (c'est ce qui a été utilisé pour valider ce projet), voir §3.

## 3. Installation du SDK en ligne de commande (alternative sans IDE)

```powershell
# 1. Télécharger "Command line tools only" pour Windows :
#    https://developer.android.com/studio#command-tools
# 2. Extraire l'archive de sorte à obtenir exactement :
#    <SDK>\cmdline-tools\latest\bin\sdkmanager.bat
#    (le zip contient un dossier "cmdline-tools" qu'il faut renommer/déplacer
#    en "latest" à l'intérieur du dossier cmdline-tools)

$env:ANDROID_HOME = "C:\Android\Sdk"
$env:JAVA_HOME     = "C:\chemin\vers\votre\jdk-21"
$env:Path = "$env:ANDROID_HOME\cmdline-tools\latest\bin;$env:ANDROID_HOME\platform-tools;$env:Path"

sdkmanager --sdk_root="$env:ANDROID_HOME" --licenses
sdkmanager --sdk_root="$env:ANDROID_HOME" "platform-tools" "platforms;android-35" "build-tools;35.0.0"
```

## 4. Installation du JDK 21

Si vous n'avez pas déjà un JDK 21 (Android Studio en embarque un, mais dédié
à son propre usage) :

```powershell
# Télécharger le .zip Temurin 21 Windows x64 :
# https://adoptium.net/temurin/releases/?version=21&os=windows&arch=x64
# Extraire, puis :
$env:JAVA_HOME = "C:\chemin\vers\jdk-21"
```

## 5. Variables d'environnement (à définir avant chaque build, ou en durable)

```powershell
# Pour la session PowerShell en cours :
$env:JAVA_HOME    = "C:\chemin\vers\jdk-21"
$env:ANDROID_HOME = "C:\chemin\vers\Android\Sdk"

# Pour les rendre durables (une fois pour toutes, à relancer PowerShell après) :
[Environment]::SetEnvironmentVariable("JAVA_HOME", "C:\chemin\vers\jdk-21", "User")
[Environment]::SetEnvironmentVariable("ANDROID_HOME", "C:\chemin\vers\Android\Sdk", "User")
```

Créez aussi `android/local.properties` (jamais commité, propre à chaque
poste — voir `android/.gitignore`) :

```
sdk.dir=C\:\\chemin\\vers\\Android\\Sdk
```

## 6. Installation des dépendances du projet

```powershell
npm install
```

Installe `@capacitor/core`, `@capacitor/android`, `@capacitor/app`
(bouton retour Android) et `@capacitor/cli`/`@capacitor/assets`
(génération d'icônes) — voir `package.json` à la racine.

## 7. Synchronisation Capacitor

À refaire à chaque modification de `web/index.html`, `capacitor.config.json`
ou après l'ajout d'un plugin :

```powershell
npm run android:sync
```

Copie `web/` dans `android/app/src/main/assets/public` et régénère la
configuration des plugins natifs.

## 8. Ouvrir le projet dans Android Studio (optionnel)

```powershell
npm run android:open
```

Utile pour déboguer sur un émulateur, inspecter les logs (`Logcat`), ou
simplement lancer un build depuis l'IDE plutôt que la ligne de commande.

## 9. Génération de l'APK Debug

```powershell
npm run android:apk
```

Équivaut à `cd android && gradlew.bat assembleDebug`. Ne nécessite **aucune**
signature — Gradle utilise un certificat de debug généré automatiquement.

## 10. Emplacement de l'APK Debug

```
android\app\build\outputs\apk\debug\app-debug.apk
```

## 11. Génération de l'APK Release

```powershell
npm run android:apk:release
```

Équivaut à `cd android && gradlew.bat assembleRelease`. **Sans**
`android/signing.properties` (voir §14), le résultat est un APK **non
signé** — utile pour vérifier que tout compile, mais **pas installable tel
quel** sur un téléphone (Android refuse les APK non signés) ni publiable.

## 12. Emplacement de l'APK Release

```
# Signé (avec signing.properties configuré) :
android\app\build\outputs\apk\release\app-release.apk

# Non signé (sans signing.properties) :
android\app\build\outputs\apk\release\app-release-unsigned.apk
```

## 13. Génération de l'AAB (Android App Bundle, pour le Play Store)

```powershell
npm run android:aab
```

Équivaut à `cd android && gradlew.bat bundleRelease`.

**Emplacement :**
```
android\app\build\outputs\bundle\release\app-release.aab
```

Comme pour l'APK Release, une signature réelle (§14) est nécessaire avant
tout envoi au Play Store.

## 14. Configuration de la signature Release

Le Play Store et l'installation directe d'un APK Release exigent une
signature avec **votre propre clé**, différente de la clé de debug. Cette
clé doit être **conservée indéfiniment** : la perdre empêche de publier la
moindre mise à jour de l'application sous le même identifiant.

**a) Générer le keystore (une seule fois, à faire vous-même — jamais par un
outil automatisé, cette clé vous appartient) :**

```powershell
& "$env:JAVA_HOME\bin\keytool.exe" -genkeypair -v `
    -keystore icm-registre-release.jks `
    -alias icm-registre `
    -keyalg RSA -keysize 2048 -validity 10000
```

Répondez aux questions (nom, organisation « ElMan », ville, pays…) et
choisissez un mot de passe robuste. **Sauvegardez ce fichier `.jks` et son
mot de passe en lieu sûr, hors du dépôt** (gestionnaire de mots de passe,
coffre-fort numérique) : ni l'un ni l'autre ne doivent jamais être commités.

**b) Placer le keystore et déclarer ses informations :**

```powershell
New-Item -ItemType Directory -Force -Path android\keystore
Move-Item icm-registre-release.jks android\keystore\

Copy-Item android\signing.properties.example android\signing.properties
# Puis éditer android\signing.properties avec vos vraies valeurs
# (storeFile, storePassword, keyAlias, keyPassword).
```

`android/signing.properties` et `android/keystore/` sont ignorés par git
(voir `android/.gitignore`) : ils ne partent jamais sur GitHub.

**c) Reconstruire :**

```powershell
npm run android:apk:release
npm run android:aab
```

Cette fois, `android\app\src\main\build.gradle` détecte automatiquement
`signing.properties` et signe les deux sorties.

## 15. Installer l'APK sur un téléphone Android

**Par câble USB (débogage activé)** — *Paramètres → À propos du téléphone →
taper 7 fois sur « Numéro de build »* pour activer le mode développeur, puis
*Paramètres → Options pour développeurs → Débogage USB* :

```powershell
& "$env:ANDROID_HOME\platform-tools\adb.exe" install android\app\build\outputs\apk\debug\app-debug.apk
```

**Sans câble** : envoyer le fichier `.apk` (Drive, e-mail, clé USB…), puis
l'ouvrir depuis le téléphone. Android demandera d'autoriser
« Installer des applications inconnues » pour la source utilisée (une seule
fois) — c'est normal pour un APK hors Play Store, sans rapport avec la
sécurité de l'application elle-même (même remarque que pour le `.exe` non
signé, voir `desktop/README.md`).

## 16. Préparer Google Play Console

1. Compte développeur Google Play (paiement unique de 25 $, une fois pour
   toutes) sur <https://play.google.com/console>.
2. **Créer l'application** → renseigner nom, catégorie, coordonnées.
3. **Version de production → Créer une version** → importer
   `app-release.aab` (§13, **signé**).
4. Activer **Play App Signing** (recommandé, proposé automatiquement) :
   Google conserve alors la clé d'upload de manière sécurisée en plus de
   votre keystore.
5. Renseigner la **fiche Store** (description, captures d'écran, icône
   512×512 — dérivable de `desktop/logo_icm.png`), la **politique de
   confidentialité** (obligatoire : l'application traite des données
   personnelles — noms, dates, photos d'identité) et le
   **questionnaire de classification du contenu**.
6. Définir le **public cible** et répondre au questionnaire sur la
   **sécurité des données** (l'application transmet des données à Supabase,
   en HTTPS, avec authentification — décrire cela honnêtement dans le
   formulaire).
7. Soumettre pour examen.

## 17. Erreurs fréquentes

| Erreur | Cause | Solution |
|---|---|---|
| `error: invalid source release: 21` | JDK 17 (ou antérieur) utilisé au lieu de JDK 21 | Vérifier `$env:JAVA_HOME` → doit pointer vers un JDK **21** (§4-5) |
| `SDK location not found` | `ANDROID_HOME` non défini ou `android/local.properties` absent | Voir §5 |
| `Failed to install the following Android SDK packages... License not accepted` | Licences SDK non acceptées | `sdkmanager --licenses` puis taper `y` à chaque question |
| Téléchargement Gradle/Maven qui échoue ou reste bloqué | Pare-feu/proxy d'entreprise bloquant `repo.maven.apache.org` ou `dl.google.com` | Vérifier la connexion Internet directe (sans proxy restrictif) ; réessayer — Gradle reprend les téléchargements interrompus |
| `app-release-unsigned.apk` refusé à l'installation (« Application non installée ») | APK Release non signé (normal sans `signing.properties`, voir §11) | Configurer la signature (§14) puis reconstruire |
| `keytool` introuvable | Pas dans le `PATH` | Utiliser le chemin complet `$env:JAVA_HOME\bin\keytool.exe` (§14a) |
| L'app affiche un écran blanc au lancement | `web/` non synchronisé après une modification | `npm run android:sync` avant de reconstruire |
| Bouton « Imprimer / Enregistrer en PDF » inactif sur le téléphone | Normal : la WebView Android n'a pas de boîte de dialogue d'impression native — un message l'indique désormais à l'utilisateur (voir `web/index.html`, bloc Capacitor en fin de fichier) | Utiliser la version Web (navigateur) ou Windows pour imprimer/exporter en PDF |

---

## Pour aller plus vite : script tout-en-un

```powershell
$env:JAVA_HOME    = "C:\Android\jdk-21"
$env:ANDROID_HOME = "C:\Android\Sdk"
npm install
npm run android:sync
npm run android:apk           # debug
npm run android:apk:release   # release (signé si signing.properties existe)
npm run android:aab           # bundle Play Store
```
