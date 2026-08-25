# -*- coding: utf-8 -*-
"""Garde-fous statiques sur database/schema_supabase.sql.

Ce ne sont PAS des tests d'intégration contre une vraie base Postgres/
Supabase (cela exigerait de faire tourner localement le service `auth`,
que Postgres seul ne fournit pas — hors de portée d'une action GitHub
simple). Ce sont des vérifications textuelles ciblées : elles s'assurent
qu'une modification future du script SQL ne supprime pas silencieusement
une protection critique (RLS, revoke, trigger d'immuabilité...) décrite
au § 13 du README. Une régression ici est un signal fort à vérifier
manuellement — ce n'est pas un remplacement d'un vrai test contre une
base Supabase de test, seulement un filet moins coûteux à faire tourner
à chaque push.
"""
import re
from pathlib import Path

import pytest

RACINE_DEPOT = Path(__file__).resolve().parent.parent
CHEMIN_SCHEMA = RACINE_DEPOT / "database" / "schema_supabase.sql"


@pytest.fixture(scope="module")
def sql():
    return CHEMIN_SCHEMA.read_text(encoding="utf-8")


def _normalise(texte):
    """Espaces/casse insensibles, pour ne pas dépendre de la mise en forme
    exacte du fichier SQL."""
    return re.sub(r"\s+", " ", texte).lower()


@pytest.mark.parametrize("table", ["registre", "profils", "journal_audit"])
def test_rls_active_sur_les_tables_sensibles(sql, table):
    assert re.search(
        rf"alter\s+table\s+public\.{table}\s+enable\s+row\s+level\s+security",
        sql, re.IGNORECASE,
    ), f"RLS doit rester activé sur public.{table}"


def test_profils_na_pas_de_policy_insert_update_delete_pour_authenticated(sql):
    """Un compte ne doit pouvoir modifier son rôle par aucune policy RLS —
    seule une lecture de son propre profil est autorisée (voir aussi le
    test suivant, pour le filet de sécurité indépendant)."""
    bloc = _normalise(sql)
    assert 'create policy "chacun lit son propre profil"' in bloc
    # Aucune policy sur profils ne doit ouvrir insert/update/delete à un
    # rôle applicatif (le seul chemin voulu est le SQL/Table Editor, hors RLS).
    for action in ("for insert", "for update", "for delete"):
        motif = rf'create policy "[^"]*"\s+on public\.profils {action}'
        assert not re.search(motif, bloc), (
            f"une policy '{action}' sur public.profils autoriserait "
            f"l'auto-promotion de rôle par l'API"
        )


def test_auto_promotion_de_role_bloquee_par_revoke_et_trigger(sql):
    """Filet indépendant de la policy (§ 13 du README) : même si une policy
    d'écriture était ajoutée par erreur sur `profils`, le REVOKE et le
    trigger ci-dessous doivent encore bloquer un changement de rôle via
    l'API PostgREST (rôles anon/authenticated)."""
    bloc = _normalise(sql)
    assert "revoke insert, update, delete on public.profils from authenticated" in bloc
    assert re.search(
        r"create\s+trigger\s+profils_role_immuable\s+before\s+update\s+on\s+public\.profils",
        sql, re.IGNORECASE,
    )
    assert "current_user in ('anon', 'authenticated')" in bloc
    assert "raise exception" in bloc


def test_journal_audit_non_modifiable_apres_ecriture(sql):
    bloc = _normalise(sql)
    assert "revoke update, delete on public.journal_audit from authenticated" in bloc
    # Aucune policy RLS ne doit rouvrir l'update/delete sur le journal.
    for action in ("for update", "for delete"):
        motif = rf'create policy "[^"]*"\s+on public\.journal_audit {action}'
        assert not re.search(motif, bloc)


def test_fonctions_internes_non_executables_directement(sql):
    """§13 : « fonctions internes non exposées » — role_utilisateur() et
    journaliser_registre() ne doivent être exécutables que par les canaux
    prévus (authenticated pour la première, trigger seul pour la seconde),
    jamais par anon ni par un appel RPC libre côté journaliser_registre()."""
    bloc = _normalise(sql)
    assert "revoke all on function public.role_utilisateur() from public" in bloc
    assert "grant execute on function public.role_utilisateur() to authenticated" in bloc
    assert (
        "revoke execute on function public.role_utilisateur() from anon" in bloc
        or "revoke all on function public.role_utilisateur() from public" in bloc
    )
    assert (
        "revoke execute on function public.journaliser_registre() "
        "from anon, authenticated" in bloc
    )


def test_vue_statistiques_respecte_les_roles(sql):
    bloc = _normalise(sql)
    assert "revoke all on public.v_statistiques from anon" in bloc
    assert "grant select on public.v_statistiques to authenticated" in bloc


def test_bucket_photos_prive_et_limite_en_taille(sql):
    bloc = _normalise(sql)
    correspondance = re.search(
        r"insert into storage\.buckets[^;]*values\s*\("
        r"'photos',\s*'photos',\s*(true|false),\s*(\d+)", bloc,
    )
    assert correspondance, "déclaration du bucket 'photos' introuvable"
    public, taille_max = correspondance.group(1), int(correspondance.group(2))
    assert public == "false", "le bucket photos ne doit jamais être public"
    assert taille_max <= 512_000, (
        "la limite de taille du bucket doit rester alignée avec "
        "PHOTO_TAILLE_MAX côté Flask (500 Ko)"
    )


def test_registre_reserve_lecriture_a_secretaire_et_pasteur(sql):
    bloc = _normalise(sql)
    for action in ("for insert", "for update", "for delete"):
        motif = (
            rf'create policy "[^"]*"\s+on public\.registre {action}[^;]*'
            rf"role_utilisateur\(\) in \('secretaire', 'pasteur'\)"
        )
        assert re.search(motif, bloc), (
            f"la policy {action} sur public.registre doit rester réservée "
            f"aux rôles secretaire/pasteur"
        )


def test_longueurs_maximales_coherentes_avec_flask(sql):
    """§12.4 : les contraintes de longueur doivent rester présentes et
    cohérentes avec LONGUEURS_MAX (app.py) — nom/prenom à 120 caractères
    en particulier, pour ne pas diverger silencieusement entre les deux
    versions de l'application."""
    bloc = _normalise(sql)
    assert "'nom_longueur_raisonnable', 'nom', 120" in bloc
    assert "'prenom_longueur_raisonnable', 'prenom', 120" in bloc
