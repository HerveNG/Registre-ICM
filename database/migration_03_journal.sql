-- ============================================================
--  MIGRATION 03 — Journal d'audit (qui a créé/modifié/supprimé
--  quelle carte, et quand — avec le détail des champs modifiés)
-- ============================================================
--  À exécuter UNIQUEMENT si votre base existe déjà (créée avec une
--  version antérieure de schema_supabase.sql, sans le journal).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (section 10).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Sans risque pour les fiches déjà enregistrées : ce script ne
--  touche pas à "registre", il ajoute seulement une table de
--  journal et un trigger qui l'alimente pour les créations,
--  modifications et suppressions à venir (les faits antérieurs à
--  cette migration ne sont pas rétroactivement journalisés).
-- ============================================================


-- 1. Extension hstore -------------------------------------------------
-- Sert à calculer la différence entre l'ancienne et la nouvelle
-- version d'une fiche lors d'une modification.
create extension if not exists hstore;


-- 2. Table du journal ---------------------------------------------------
-- registre_id n'est volontairement PAS une clé étrangère stricte : une
-- fiche supprimée doit rester traçable dans le journal, indépendamment
-- de l'existence continue de la fiche.
create table if not exists public.journal_audit (
    id           bigint generated always as identity primary key,
    horodatage   timestamptz not null default now(),
    utilisateur  text not null,
    action       text not null check (action in ('creation', 'modification', 'suppression')),
    registre_id  uuid,
    nom_complet  text not null,
    details      jsonb    -- [{"champ","avant","apres"}, ...] pour une modification
);

comment on table public.journal_audit is
  'Journal d''audit du registre ICM : qui a créé, modifié ou supprimé quelle fiche, et quand.';

create index if not exists journal_audit_registre_id_idx on public.journal_audit (registre_id);
create index if not exists journal_audit_horodatage_idx  on public.journal_audit (horodatage desc);
create index if not exists journal_audit_nom_complet_idx on public.journal_audit (lower(nom_complet));


-- 3. Sécurité (RLS) du journal --------------------------------------
-- Lecture ouverte aux trois rôles (secrétaire, pasteur, visiteur) :
-- consulter le journal est une lecture, pas une écriture. Aucune
-- policy insert/update/delete pour "authenticated" : seul le trigger
-- de l'étape 5 (exécuté avec les droits de son propriétaire) écrit
-- dans le journal — jamais l'application, jamais un compte connecté.
alter table public.journal_audit enable row level security;

drop policy if exists "lecture du journal pour comptes avec un role" on public.journal_audit;
create policy "lecture du journal pour comptes avec un role"
    on public.journal_audit for select
    to authenticated
    using (public.role_utilisateur() is not null);


-- 4. Fonctions utilitaires (libellés + mise en forme) -----------------
create or replace function public.libelle_champ_registre(p_champ text)
returns text
language sql
immutable
as $$
    select case p_champ
        when 'nom'               then 'Nom'
        when 'prenom'            then 'Prénom'
        when 'nom_pere'          then 'Fils/Fille de'
        when 'nom_mere'          then 'Et de'
        when 'date_naissance'    then 'Date de naissance'
        when 'nationalite'       then 'Nationalité'
        when 'originaire_de'     then 'Originaire de'
        when 'date_bapteme'      then 'Date de baptême'
        when 'lieu_bapteme'      then 'Lieu du baptême'
        when 'numero_registre_1' then 'N° Registre (1)'
        when 'celebrant_bapteme' then 'Célébrant baptême'
        when 'signature_1'       then 'Signature (1)'
        when 'lieu_mariage'      then 'Lieu du mariage'
        when 'date_mariage'      then 'Date du mariage'
        when 'conjoint'          then 'Conjoint'
        when 'numero_registre_2' then 'N° Registre (2)'
        when 'celebrant_mariage' then 'Célébrant mariage'
        when 'signature_2'       then 'Signature (2)'
        when 'telephone'         then 'Téléphone'
        when 'observations'      then 'Observations'
        when 'photo'             then 'Photo'
        else p_champ
    end;
$$;

create or replace function public.texte_valeur_champ(p_champ text, p_valeur text)
returns text
language sql
immutable
as $$
    select case
        when p_valeur is null or p_valeur = '' then '—'
        when p_champ in ('date_naissance', 'date_bapteme', 'date_mariage')
            then to_char(p_valeur::date, 'DD/MM/YYYY')
        else p_valeur
    end;
$$;


-- 5. Trigger : alimente le journal à chaque création/modification/
--    suppression d'une fiche ------------------------------------------
create or replace function public.journaliser_registre()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
    v_utilisateur text;
    v_diff        hstore;
    v_changements jsonb := '[]'::jsonb;
    v_cle         text;
    v_apres       text;
begin
    -- Résout l'email du compte connecté : auth.users n'est pas exposé
    -- via l'API REST, mais security definer permet de le lire ici.
    select email into v_utilisateur from auth.users where id = auth.uid();
    v_utilisateur := coalesce(v_utilisateur, auth.uid()::text, 'inconnu');

    if tg_op = 'INSERT' then
        insert into public.journal_audit (utilisateur, action, registre_id, nom_complet)
        values (v_utilisateur, 'creation', new.id, new.nom || ' ' || new.prenom);
        return new;

    elsif tg_op = 'UPDATE' then
        v_diff := (hstore(new) - hstore(old))
                    - array['id', 'created_at', 'created_by', 'updated_at']::text[];

        if v_diff = ''::hstore then
            return new;   -- rien de suivi n'a changé (ex. seul updated_at a bougé)
        end if;

        for v_cle, v_apres in select key, value from each(v_diff) loop
            v_changements := v_changements || jsonb_build_object(
                'champ', public.libelle_champ_registre(v_cle),
                'avant', public.texte_valeur_champ(v_cle, hstore(old) -> v_cle),
                'apres', public.texte_valeur_champ(v_cle, v_apres)
            );
        end loop;

        insert into public.journal_audit (utilisateur, action, registre_id, nom_complet, details)
        values (v_utilisateur, 'modification', new.id, new.nom || ' ' || new.prenom, v_changements);
        return new;

    elsif tg_op = 'DELETE' then
        insert into public.journal_audit (utilisateur, action, registre_id, nom_complet)
        values (v_utilisateur, 'suppression', old.id, old.nom || ' ' || old.prenom);
        return old;
    end if;

    return null;
end;
$$;

revoke all on function public.journaliser_registre() from public;

drop trigger if exists registre_journaliser on public.registre;
create trigger registre_journaliser
    after insert or update or delete on public.registre
    for each row execute function public.journaliser_registre();


-- 6. Vérification -----------------------------------------------------
-- Doit renvoyer les 5 nouveaux objets (table, 2 fonctions utilitaires,
-- la fonction du trigger, et le trigger lui-même) :
select 'table journal_audit'      as objet, to_regclass('public.journal_audit') is not null as ok
union all
select 'fonction libelle_champ_registre', to_regprocedure('public.libelle_champ_registre(text)') is not null
union all
select 'fonction texte_valeur_champ', to_regprocedure('public.texte_valeur_champ(text, text)') is not null
union all
select 'fonction journaliser_registre', to_regprocedure('public.journaliser_registre()') is not null
union all
select 'trigger registre_journaliser', exists (
    select 1 from pg_trigger where tgname = 'registre_journaliser'
);
