-- ============================================================
--  MIGRATION 08 — Module Fils (registre nominatif + suivi de présence)
-- ============================================================
--  À exécuter UNIQUEMENT si votre base existe déjà (créée avec une
--  version de schema_supabase.sql antérieure à ce module).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (section 14).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Sans risque pour vos données existantes : ce script ajoute seulement
--  3 nouvelles tables (fils, fils_activite, fils_presence) et leurs
--  règles d'accès — il ne touche à rien de ce qui existe déjà (registre,
--  profils, journal_audit, service_type, attendance_*...). Idempotent,
--  rejouable sans risque.
--
--  Distinct de la catégorie agrégée « Fils-ICM » du module Présences (un
--  simple compteur par tranche d'âge/sexe, sans identité) : ce module
--  tient un registre nominatif (un fils = une personne identifiée) et son
--  historique de présence individuelle, activité par activité. Les deux
--  coexistent sans lien entre eux.
--
--  fils_activite réutilise service_type (déjà en place pour Présences,
--  déjà configurable dans Paramètres) comme type d'activité plutôt qu'une
--  deuxième table de configuration — un même « Culte du dimanche » désigne
--  le même événement réel dans les deux modules. Ce script y ajoute
--  « Réunion des fils » comme nouveau type par défaut, s'il n'existe pas
--  déjà.
--
--  Droits : lecture pour tout compte muni d'un rôle ; insertion/
--  modification ouvertes aux trois rôles ; suppression définitive réservée
--  secrétaire/pasteur — même reclassification des droits que le reste de
--  l'application (voir migration_07_visiteur_ecriture.sql).
-- ============================================================


create table if not exists public.fils (
    id          uuid primary key default gen_random_uuid(),
    nom         text not null,
    prenom      text not null,
    ville       text,
    telephone   text,
    genre       text not null check (genre in ('M', 'F')),
    statut      text not null default 'active' check (statut in ('active', 'inactive')),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    constraint fils_nom_longueur_raisonnable check (char_length(nom) <= 120),
    constraint fils_prenom_longueur_raisonnable check (char_length(prenom) <= 120),
    constraint fils_ville_longueur_raisonnable check (ville is null or char_length(ville) <= 150),
    constraint fils_telephone_longueur_raisonnable check (telephone is null or char_length(telephone) <= 50)
);

comment on table public.fils is
  'Registre nominatif des fils (disciples suivis individuellement) — jamais supprimé tant qu''il a un historique de présence, voir statut.';

create index if not exists fils_telephone_idx on public.fils (telephone);
create index if not exists fils_nom_prenom_idx on public.fils (nom, prenom);

drop trigger if exists fils_touch_updated_at on public.fils;
create trigger fils_touch_updated_at
    before update on public.fils
    for each row execute function public.touch_updated_at();


create table if not exists public.fils_activite (
    id               uuid primary key default gen_random_uuid(),
    date_activite    date not null,
    service_type_id  uuid not null references public.service_type (id),
    nom              text,
    created_at       timestamptz not null default now(),

    constraint fils_activite_nom_longueur_raisonnable check (nom is null or char_length(nom) <= 150)
);

comment on table public.fils_activite is
  'Une activité datée (culte ou réunion des fils) pouvant recevoir un pointage de présence.';

create index if not exists fils_activite_date_idx on public.fils_activite (date_activite desc);
create index if not exists fils_activite_service_type_idx on public.fils_activite (service_type_id);


create table if not exists public.fils_presence (
    id           uuid primary key default gen_random_uuid(),
    fils_id      uuid not null references public.fils (id) on delete cascade,
    activite_id  uuid not null references public.fils_activite (id) on delete cascade,
    statut       text not null check (statut in ('P', 'A')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),

    unique (fils_id, activite_id)
);

comment on table public.fils_presence is
  'Un pointage Présent/Absent pour un fils, à une activité donnée.';

create index if not exists fils_presence_activite_idx on public.fils_presence (activite_id);

drop trigger if exists fils_presence_touch_updated_at on public.fils_presence;
create trigger fils_presence_touch_updated_at
    before update on public.fils_presence
    for each row execute function public.touch_updated_at();


alter table public.fils          enable row level security;
alter table public.fils_activite enable row level security;
alter table public.fils_presence enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array['fils', 'fils_activite', 'fils_presence']
    loop
        execute format(
            'drop policy if exists "fils lecture pour comptes avec un role" on public.%I', t);
        execute format(
            'create policy "fils lecture pour comptes avec un role" on public.%I '
            'for select to authenticated using (public.role_utilisateur() is not null)', t);

        execute format(
            'drop policy if exists "fils insertion tous roles" on public.%I', t);
        execute format(
            'create policy "fils insertion tous roles" on public.%I '
            'for insert to authenticated '
            'with check (public.role_utilisateur() in (''secretaire'', ''pasteur'', ''visiteur''))', t);

        execute format(
            'drop policy if exists "fils modification tous roles" on public.%I', t);
        execute format(
            'create policy "fils modification tous roles" on public.%I '
            'for update to authenticated '
            'using      (public.role_utilisateur() in (''secretaire'', ''pasteur'', ''visiteur'')) '
            'with check (public.role_utilisateur() in (''secretaire'', ''pasteur'', ''visiteur''))', t);

        execute format(
            'drop policy if exists "fils suppression secretaire ou pasteur" on public.%I', t);
        execute format(
            'create policy "fils suppression secretaire ou pasteur" on public.%I '
            'for delete to authenticated '
            'using (public.role_utilisateur() in (''secretaire'', ''pasteur''))', t);
    end loop;
end $$;


insert into public.service_type (nom, ordre_affichage)
select 'Réunion des fils',
       coalesce((select max(ordre_affichage) + 1 from public.service_type), 0)
where not exists (
    select 1 from public.service_type where lower(nom) = lower('Réunion des fils')
);


-- ------------------------------------------------------------
-- Vérification (les 3 colonnes doivent afficher : true, true, true)
-- ------------------------------------------------------------
select
    (select count(*) = 3 from pg_tables where schemaname = 'public'
     and tablename in ('fils', 'fils_activite', 'fils_presence'))          as tables_creees,
    (select count(*) >= 12 from pg_policies where schemaname = 'public'
     and tablename in ('fils', 'fils_activite', 'fils_presence'))          as policies_en_place,
    (select count(*) = 1 from public.service_type
     where lower(nom) = lower('Réunion des fils'))                        as type_reunion_des_fils_seme;
