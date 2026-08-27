# Construit "ICM Registre.exe" — exécutable Windows autonome de la version
# bureau (voir desktop/README.md pour le détail et les prérequis).
#
# Usage, depuis la racine du dépôt :
#   powershell -ExecutionPolicy Bypass -File desktop\construire.ps1
#
# Résultat : desktop\dist\"ICM Registre.exe" — à copier tel quel sur le poste
# cible, rien d'autre à installer (Python et ses dépendances sont inclus).

$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $PSScriptRoot
Set-Location $racine

Write-Host "1/3 - Installation des dépendances de construction..."
& .venv\Scripts\python.exe -m pip install -r desktop\requirements.txt

Write-Host "2/3 - Génération de l'icône (desktop/logo_icm.png -> desktop/icone.ico)..."
& .venv\Scripts\python.exe desktop\generer_icone.py

Write-Host "3/3 - Construction de l'exécutable avec PyInstaller..."
# Chemins absolus pour --icon et --add-data : avec --specpath "desktop",
# PyInstaller réécrit les chemins relatifs dans le .spec généré comme étant
# relatifs à ce dossier (et non à la racine du dépôt), ce qui les rendait
# introuvables (desktop\desktop\icone.ico).
$racine = (Get-Location).Path
& .venv\Scripts\python.exe -m PyInstaller `
    --onefile `
    --noconsole `
    --name "ICM Registre" `
    --icon "$racine\desktop\icone.ico" `
    --add-data "$racine\web\index.html;web" `
    --distpath "desktop\dist" `
    --workpath "desktop\build" `
    --specpath "desktop" `
    desktop\app_bureau.py

Write-Host ""
Write-Host "Terminé : desktop\dist\ICM Registre.exe"
