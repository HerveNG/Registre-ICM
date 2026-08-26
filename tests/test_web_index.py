# -*- coding: utf-8 -*-
"""Tests de la version en ligne (web/index.html) — un seul fichier HTML
autonome, sans bundler ni framework JS. Plutôt que de réécrire sa logique
en Python, ces tests chargent le fichier réel dans un vrai navigateur
(Playwright + Chromium) et appellent directement les fonctions JS pures
qu'il définit (échappement, dates, anti-injection CSV, permissions,
lecture du CSV d'import...) — le même principe de test que pour app.py,
appliqué à l'autre moitié de l'application décrite dans le README.

Aucun de ces tests ne contacte Supabase : les requêtes vers le domaine
configuré dans CONFIG_PAR_DEFAUT sont interceptées et bloquées (voir la
fixture `page`), pour ne jamais dépendre d'un service externe ni risquer
de toucher une vraie base de données pendant les tests.
"""
import http.server
import os
import threading
from pathlib import Path

import pytest

RACINE_DEPOT = Path(__file__).resolve().parent.parent
DOSSIER_WEB = RACINE_DEPOT / "web"

playwright_sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright n'est pas installé — voir tests/README.md (pip install -r tests/requirements.txt && playwright install chromium)",
)
sync_playwright = playwright_sync_api.sync_playwright


@pytest.fixture(scope="session")
def serveur_web():
    """Sert web/ en HTTP local : un file:// direct fonctionnerait pour la
    plupart de ces tests, mais certaines API du navigateur (localStorage
    notamment) sont restreintes ou peu fiables sur l'origine file://."""
    gestionnaire = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(DOSSIER_WEB), **kw
    )
    serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), gestionnaire)
    port = serveur.server_address[1]
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    yield f"http://127.0.0.1:{port}/index.html"
    serveur.shutdown()


@pytest.fixture(scope="session")
def navigateur():
    with sync_playwright() as p:
        chemin_execution = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        options = {"executable_path": chemin_execution} if chemin_execution else {}
        navigateur = p.chromium.launch(**options)
        yield navigateur
        navigateur.close()


@pytest.fixture
def page(navigateur, serveur_web):
    contexte = navigateur.new_context()
    page = contexte.new_page()
    # Ne jamais laisser un test toucher un vrai projet Supabase : la clé
    # anon figurant dans CONFIG_PAR_DEFAUT est une vraie clé publique de
    # démonstration (voir README §3b — sans risque en elle-même, une clé
    # anon ne donne accès à rien sans compte, mais un test ne doit pas en
    # dépendre pour rester déterministe et hors-ligne).
    page.route("**://*.supabase.co/**", lambda route: route.abort())
    page.goto(serveur_web)
    page.wait_for_load_state("domcontentloaded")
    yield page
    contexte.close()


# ------------------------------------------------------------------
#  Échappement HTML (echapper) — anti-XSS sur tout texte inséré via
#  innerHTML (messages, tableau du journal, aperçu de la carte...)
# ------------------------------------------------------------------
def test_echapper_neutralise_les_caracteres_html(page):
    resultat = page.evaluate(
        "echapper('<script>alert(1)</script> & \"quote\" \\'apostrophe\\'')"
    )
    assert "<script>" not in resultat
    assert "&lt;script&gt;" in resultat
    assert "&amp;" in resultat
    assert "&quot;" in resultat
    assert "&#39;" in resultat


def test_echapper_gere_valeurs_nulles(page):
    assert page.evaluate("echapper(null)") == ""
    assert page.evaluate("echapper(undefined)") == ""


# ------------------------------------------------------------------
#  Dates
# ------------------------------------------------------------------
def test_date_fr_convertit_iso_en_jj_mm_aaaa(page):
    assert page.evaluate("dateFr('2026-01-15')") == "15/01/2026"


def test_date_fr_valeur_vide(page):
    assert page.evaluate("dateFr('')") == ""
    assert page.evaluate("dateFr(null)") == ""


def test_date_heure_fr_convertit_horodatage(page):
    assert page.evaluate("dateHeureFr('2026-01-15T09:05:00')") == "15/01/2026 à 09:05"


def test_date_heure_fr_valeur_invalide(page):
    assert page.evaluate("dateHeureFr('pas une date')") == ""


# ------------------------------------------------------------------
#  Permissions (peutEcrire) — miroir client du contrôle serveur/RLS
# ------------------------------------------------------------------
@pytest.mark.parametrize("role,attendu", [
    ("secretaire", True), ("pasteur", True), ("visiteur", False), (None, False),
])
def test_peut_ecrire_selon_le_role(page, role, attendu):
    page.evaluate("(r) => { etat.role = r; }", role)
    assert page.evaluate("peutEcrire()") is attendu


# ------------------------------------------------------------------
#  Validation du formulaire — même règles que valider_donnees (app.py)
# ------------------------------------------------------------------
def test_valider_formulaire_nom_prenom_obligatoires(page):
    erreurs = page.evaluate("validerFormulaire({nom:'', prenom:''})")
    assert any("nom" in e.lower() for e in erreurs)
    assert any("prénom" in e.lower() for e in erreurs)


def test_valider_formulaire_donnees_valides(page):
    erreurs = page.evaluate(
        "validerFormulaire({nom:'Ngooh', prenom:'Cédric'})"
    )
    assert erreurs == []


def test_valider_formulaire_date_future_refusee(page):
    erreurs = page.evaluate(
        "validerFormulaire({nom:'A', prenom:'B', date_naissance:'2999-01-01'})"
    )
    assert any("futur" in e for e in erreurs)


def test_valider_formulaire_bapteme_avant_naissance(page):
    erreurs = page.evaluate(
        "validerFormulaire({nom:'A', prenom:'B', "
        "date_naissance:'2000-06-01', date_bapteme:'2000-01-01'})"
    )
    assert any("précéder la naissance" in e for e in erreurs)


# ------------------------------------------------------------------
#  Export CSV — même anti-injection de formule que neutraliser_formule
#  côté Flask (CWE-1236), plus l'échappement CSV standard (guillemets).
# ------------------------------------------------------------------
@pytest.mark.parametrize("valeur", ["=CMD('calc')", "+1+1", "-1-1", "@SUM(A1)"])
def test_cellule_csv_neutralise_injection_formule(page, valeur):
    resultat = page.evaluate("(v) => celluleCsv(v)", valeur)
    assert resultat.startswith("'")


def test_cellule_csv_echappe_les_guillemets(page):
    resultat = page.evaluate('(v) => celluleCsv(v)', 'il a dit "bonjour"')
    assert resultat == '"il a dit ""bonjour"""'


def test_cellule_csv_texte_normal_inchange(page):
    assert page.evaluate("(v) => celluleCsv(v)", "Jean Dupont") == "Jean Dupont"


# ------------------------------------------------------------------
#  Import CSV — lecteur maison (analyserCsvTexte) et normalisation
#  des en-têtes, en miroir de lire_fichier_import côté Flask.
# ------------------------------------------------------------------
def test_normaliser_entete_import_ignore_accents_et_casse(page):
    a = page.evaluate("normaliserEnteteImport('Célébrant baptême')")
    b = page.evaluate("normaliserEnteteImport('CELEBRANT   BAPTEME')")
    assert a == b == "celebrant bapteme"


def test_detecter_delimiteur_virgule_vs_point_virgule(page):
    assert page.evaluate("detecterDelimiteurImport('Nom,Prenom\\nA,B')") == ","
    assert page.evaluate("detecterDelimiteurImport('Nom;Prenom\\nA;B')") == ";"


def test_analyser_csv_texte_gere_les_guillemets(page):
    texte = 'Nom;Note\n"Dupont; le grand";"il a dit ""bonjour"""'
    lignes = page.evaluate("(t) => analyserCsvTexte(t)", texte)
    assert lignes[0] == ["Nom", "Note"]
    assert lignes[1] == ["Dupont; le grand", 'il a dit "bonjour"']


# ------------------------------------------------------------------
#  Régression XSS de bout en bout sur le tableau du registre : un nom de
#  fiche malveillant ne doit jamais devenir un élément HTML actif dans la
#  page (pas seulement echapper() testée isolément — la fonction de rendu
#  réelle, dessinerTableau, doit bien l'appeler sur chaque champ affiché).
# ------------------------------------------------------------------
def test_dessiner_tableau_echappe_un_nom_malveillant(page):
    page.evaluate(
        """() => {
            window.__xss = false;
            etat.lignes = [{
                id: 1,
                nom: '<img src=x onerror="window.__xss = true">',
                prenom: 'Test', photo: null, date_naissance: null,
                date_bapteme: null, lieu_bapteme: null, numero_registre_1: null,
                date_mariage: null, numero_registre_2: null, conjoint: null,
                originaire_de: null,
            }];
            etat.total = 1;
            etat.role = 'secretaire';
            dessinerTableau();
        }"""
    )
    page.wait_for_timeout(100)
    assert page.evaluate("window.__xss") is False
    nb_images = page.evaluate("document.querySelectorAll('#corps-tableau img').length")
    assert nb_images == 0  # `photo` est null : aucune vignette attendue


def test_lire_date_import_formats_multiples(page):
    assert page.evaluate("lireDateImport('2026-01-15')") == "2026-01-15"
    assert page.evaluate("lireDateImport('15/01/2026')") == "2026-01-15"
    assert page.evaluate("lireDateImport('')") is None
    assert page.evaluate("lireDateImport(null)") is None


# ------------------------------------------------------------------
#  Casse imposée à certains champs texte (normaliserCasseChamp), en miroir
#  de normaliser_casse côté Flask (app.py) — voir tests/test_normalisation_casse.py.
# ------------------------------------------------------------------
def test_normaliser_casse_champ_majuscules(page):
    for champ in ("nom", "nom_pere", "nom_mere", "lieu_bapteme",
                  "celebrant_bapteme", "lieu_mariage", "celebrant_mariage"):
        assert page.evaluate(f"normaliserCasseChamp('{champ}', 'ngooh mvondo')") == "NGOOH MVONDO"


def test_normaliser_casse_champ_capitalise(page):
    for champ in ("prenom", "nationalite", "originaire_de"):
        assert page.evaluate(f"normaliserCasseChamp('{champ}', 'HERVÉ')") == "Hervé"


def test_normaliser_casse_champ_sans_regle_inchange(page):
    assert page.evaluate("normaliserCasseChamp('telephone', '0612345678')") == "0612345678"


def test_lire_formulaire_applique_la_normalisation_de_casse(page):
    page.evaluate("""() => {
        $("f-nom").value = "ngooh";
        $("f-prenom").value = "HERVÉ";
    }""")
    donnees = page.evaluate("lireFormulaire()")
    assert donnees["nom"] == "NGOOH"
    assert donnees["prenom"] == "Hervé"


# ------------------------------------------------------------------
#  Régression : validerFormulaire comparait la date saisie (locale, telle
#  que rendue par <input type="date">) à `new Date().toISOString()` (UTC).
#  Entre minuit et l'heure de décalage local, dans un fuseau en avance sur
#  UTC (ex. Afrique centrale, UTC+1), cela renvoyait encore la veille et
#  rejetait à tort une date d'aujourd'hui comme « dans le futur ». C'était
#  le bug du calendrier — aujourdhuiLocalISO() le corrige.
# ------------------------------------------------------------------
def test_validation_accepte_la_date_locale_du_jour(page):
    """Preuve directe du bug corrigé : si validerFormulaire utilisait encore
    la date UTC, la date locale du jour se retrouverait à tort strictement
    supérieure à « aujourd'hui » dès que UTC et le fuseau local divergent
    de date — ce test le vérifie sans dépendre de l'heure à laquelle il
    tourne, en comparant directement les deux calculs de date."""
    aujourdhui_local = page.evaluate("aujourdhuiLocalISO()")
    aujourdhui_utc = page.evaluate("new Date().toISOString().slice(0,10)")
    erreurs = page.evaluate(
        "(d) => validerFormulaire({nom:'A', prenom:'B', date_naissance:d})",
        aujourdhui_local,
    )
    assert erreurs == [], (
        f"date locale du jour ({aujourdhui_local!r}) rejetée comme future "
        f"(comparée à {aujourdhui_utc!r} en UTC)"
    )


def test_aujourdhui_local_iso_suit_lheure_locale_de_la_machine(page):
    attendu = page.evaluate(
        """() => { const d=new Date(); const p=n=>String(n).padStart(2,"0");
           return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`; }"""
    )
    assert page.evaluate("aujourdhuiLocalISO()") == attendu
