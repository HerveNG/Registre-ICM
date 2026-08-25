-- ============================================================
--  IN CHRIST MINISTRIES (ICM) — migration incrémentale
--  Durcissement de sécurité (audit du 25/08/2026)
-- ============================================================
--  À exécuter UNE FOIS sur un projet Supabase déjà à jour avec
--  migration_02_roles.sql et migration_03_journal.sql (ou avec
--  schema_supabase.sql dans son intégralité). Idempotent : peut être
--  rejouée sans risque si l'exécution s'interrompt en cours de route.
--
--  Ce que corrige cette migration :
--   1. Le grant EXECUTE explicite à anon/authenticated sur les
--      fonctions internes n'avait été fait qu'avec REVOKE ... FROM
--      PUBLIC, qui ne retire PAS ce que Supabase accorde par défaut
--      aux rôles nommés anon/authenticated à la création de chaque
--      fonction (ce n'est pas la même chose que le pseudo-rôle
--      PUBLIC). Corrigé ici par des REVOKE explicites, par rôle nommé.
--   2. La vue v_statistiques n'avait pas security_invoker=true : elle
--      s'exécutait avec les privilèges de son PROPRIÉTAIRE (qui,
--      possédant aussi "registre", contourne RLS par défaut) — donc
--      lisible par n'importe qui muni de la seule clé publique anon,
--      sans passer par aucun contrôle de rôle.
--   3. La protection de "profils" contre l'auto-promotion de rôle
--      (un visiteur qui se nommerait lui-même "pasteur") reposait
--      uniquement sur l'ABSENCE de policy update/insert/delete pour
--      authenticated — correct, mais fragile face à une policy future
--      ajoutée par erreur. Un REVOKE explicite + un trigger
--      indépendant de toute policy ferment ce risque.
--   4. Aucune longueur maximale sur les champs texte libres du
--      registre : un compte secretaire/pasteur pouvait gonfler la
--      base avec des champs disproportionnés.
--
--  Volontairement PAS fait ici (et pourquoi) :
--   - FORCE ROW LEVEL SECURITY sur profils/journal_audit : ces deux
--     tables ne sont écrites que par des fonctions security definer
--     (role_utilisateur() lit profils, journaliser_registre() écrit
--     journal_audit) qui s'exécutent avec les droits de leur
--     PROPRIÉTAIRE. Forcer RLS changerait aussi le comportement de
--     ces fonctions pour ce même propriétaire, avec un risque réel de
--     casser entièrement l'attribution des rôles et le journal
--     d'audit selon la façon exacte dont Supabase configure le rôle
--     "postgres" du projet — un risque jugé disproportionné par
--     rapport au gain (une protection déjà assurée par ailleurs par
--     l'absence de policy ET le REVOKE du point 3).
-- ============================================================


-- ------------------------------------------------------------
-- 1. Grants EXECUTE explicites (le REVOKE ... FROM PUBLIC existant
--    ne suffisait pas)
-- ------------------------------------------------------------
revoke execute on function public.role_utilisateur() from anon;
-- authenticated garde EXECUTE : toutes les policies RLS de ce fichier
-- (registre, journal_audit, storage.objects) en dépendent.

revoke execute on function public.journaliser_registre() from anon, authenticated;
-- Appelée uniquement par le trigger registre_journaliser, jamais
-- directement par un client (et son type de retour "trigger"
-- l'empêcherait de toute façon d'être invoquée via un simple SELECT).

alter function public.libelle_champ_registre(text) set search_path = public;
alter function public.texte_valeur_champ(text, text) set search_path = public;
alter function public.touch_updated_at() set search_path = public;
alter function public.attribuer_numeros() set search_path = public;

revoke execute on function public.libelle_champ_registre(text) from anon, authenticated;
revoke execute on function public.texte_valeur_champ(text, text) from anon, authenticated;
-- Utilisées uniquement en interne par journaliser_registre(), jamais
-- par l'application.

revoke usage, select on sequence public.seq_registre_bapteme, public.seq_registre_mariage
    from anon;
-- authenticated garde l'accès : attribuer_numeros() (déclencheur, pas
-- security definer) s'exécute avec les droits du compte connecté.


-- ------------------------------------------------------------
-- 2. Vue statistiques : exécution sous RLS, pas sous les
--    privilèges du propriétaire
-- ------------------------------------------------------------
alter view public.v_statistiques set (security_invoker = true);
revoke all on public.v_statistiques from anon;
grant select on public.v_statistiques to authenticated;


-- ------------------------------------------------------------
-- 3. "profils" : filet de sécurité indépendant de la policy contre
--    l'auto-promotion de rôle
-- ------------------------------------------------------------
revoke insert, update, delete on public.profils from authenticated;


-- ------------------------------------------------------------
-- 3 bis. "journal_audit" : même filet, contre une modification ou
--    suppression d'entrée après coup (le journal doit rester
--    immuable une fois écrit par le trigger)
-- ------------------------------------------------------------
revoke update, delete on public.journal_audit from authenticated;

-- Surtout PAS security definer ici : le but est justement de lire
-- current_user tel que l'appelant réel l'a positionné (authenticated /
-- anon via PostgREST, ou postgres depuis le SQL/Table Editor). Un
-- security definer changerait current_user pour celui du PROPRIÉTAIRE
-- de la fonction pendant son exécution, rendant ce test toujours faux
-- et le trigger inopérant quel que soit l'appelant réel.
create or replace function public.proteger_role_profil()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    -- Ne bloque que les tentatives passant par l'API (rôles anon /
    -- authenticated, tels que PostgREST les positionne pour la durée
    -- de la requête) : un changement fait depuis le SQL Editor ou le
    -- Table Editor de Supabase (rôle postgres) reste possible — c'est
    -- le canal prévu pour attribuer un rôle (voir schema_supabase.sql,
    -- section 6).
    if new.role is distinct from old.role
       and current_user in ('anon', 'authenticated') then
        raise exception
            'Modification du role interdite par ce canal (API). Changez-le '
            'depuis le SQL Editor ou le Table Editor de Supabase.';
    end if;
    return new;
end;
$$;

revoke all on function public.proteger_role_profil() from public, anon, authenticated;

drop trigger if exists profils_role_immuable on public.profils;
create trigger profils_role_immuable
    before update on public.profils
    for each row execute function public.proteger_role_profil();


-- ------------------------------------------------------------
-- 4. Longueurs maximales raisonnables sur les champs texte libres
--    (cohérent avec LONGUEURS_MAX côté Flask, app.py)
-- ------------------------------------------------------------
do $$
declare
    r record;
begin
    for r in select * from (values
        ('nom_longueur_raisonnable',               'nom',               120),
        ('prenom_longueur_raisonnable',             'prenom',            120),
        ('nom_pere_longueur_raisonnable',           'nom_pere',          200),
        ('nom_mere_longueur_raisonnable',           'nom_mere',          200),
        ('nationalite_longueur_raisonnable',        'nationalite',       100),
        ('originaire_de_longueur_raisonnable',      'originaire_de',     150),
        ('lieu_bapteme_longueur_raisonnable',       'lieu_bapteme',      200),
        ('numero_registre_1_longueur_raisonnable',  'numero_registre_1', 80),
        ('celebrant_bapteme_longueur_raisonnable',  'celebrant_bapteme', 150),
        ('signature_1_longueur_raisonnable',        'signature_1',       150),
        ('lieu_mariage_longueur_raisonnable',       'lieu_mariage',      200),
        ('conjoint_longueur_raisonnable',           'conjoint',          250),
        ('numero_registre_2_longueur_raisonnable',  'numero_registre_2', 80),
        ('celebrant_mariage_longueur_raisonnable',  'celebrant_mariage', 150),
        ('signature_2_longueur_raisonnable',        'signature_2',       150),
        ('telephone_longueur_raisonnable',          'telephone',         50),
        ('observations_longueur_raisonnable',       'observations',      5000)
    ) as contraintes(nom_contrainte, colonne, longueur_max)
    loop
        if not exists (
            select 1 from pg_constraint where conname = r.nom_contrainte
        ) then
            execute format(
                'alter table public.registre add constraint %I '
                'check (%I is null or char_length(%I) <= %s)',
                r.nom_contrainte, r.colonne, r.colonne, r.longueur_max
            );
        end if;
    end loop;
end $$;


-- ------------------------------------------------------------
-- Vérification (les 4 colonnes doivent afficher : 1, 1, 1, true)
-- ------------------------------------------------------------
select
    (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public' and p.proname = 'proteger_role_profil')          as fonction_protection_role,
    (select count(*) from pg_trigger where tgname = 'profils_role_immuable' and not tgisinternal)
                                                                                  as trigger_protection_role,
    (select count(*) from pg_constraint where conname = 'observations_longueur_raisonnable')
                                                                                  as contrainte_longueur_ok,
    (select coalesce(
        (select option_value::boolean from pg_options_to_table(
            (select reloptions from pg_class where oid = 'public.v_statistiques'::regclass)
        ) where option_name = 'security_invoker'), false)
    )                                                                            as vue_stats_security_invoker;
