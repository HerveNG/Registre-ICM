-- ============================================================
--  MIGRATION 05 — Présences & Statistiques des cultes
-- ============================================================
--  À exécuter UNIQUEMENT si votre base existe déjà (créée avec une
--  version antérieure de schema_supabase.sql, sans ce module).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (section 13).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Sans risque pour les données existantes : ce script ajoute
--  seulement 4 nouvelles tables (service_type, attendance_category,
--  attendance_record, attendance_value) et leurs règles d'accès — il
--  ne touche à rien de ce qui existe déjà (registre, profils,
--  journal_audit...). Idempotent, rejouable sans risque.
--
--  Réutilise les fonctions déjà en place dans votre base :
--  role_utilisateur() (schema_supabase.sql § 6) et touch_updated_at()
--  (§ 4). Si l'une des deux est absente (base très ancienne), exécutez
--  d'abord schema_supabase.sql en entier sur une base de test pour
--  vérifier, ou contactez la personne qui gère le projet.
-- ============================================================


-- service_type / attendance_category sont des données de configuration
-- (nom, tranche d'âge, ordre, actif) modifiables depuis l'application
-- (page Paramètres) : rien n'y est jamais supprimé pour ne jamais casser
-- une présence déjà enregistrée qui les référence — seulement désactivé
-- (is_active). attendance_record porte des totaux dénormalisés
-- (recalculés à l'écriture) pour que le tableau de bord et les
-- statistiques n'aient jamais à ré-agréger attendance_value à chaque
-- affichage.

create table if not exists public.service_type (
    id               uuid primary key default gen_random_uuid(),
    nom              text not null unique,
    description      text,
    ordre_affichage  integer not null default 0,
    is_active        boolean not null default true
);

comment on table public.service_type is
  'Types de culte/événement (dimanche, mercredi, prière...) — configurable, jamais supprimé.';

create table if not exists public.attendance_category (
    id               uuid primary key default gen_random_uuid(),
    nom              text not null,
    groupe           text not null check (groupe in ('hommes', 'femmes', 'enfants')),
    age_min          integer,
    age_max          integer,
    ordre_affichage  integer not null default 0,
    is_active        boolean not null default true
);

comment on table public.attendance_category is
  'Catégories d''âge au sein d''un groupe (hommes/femmes/enfants) — configurable, jamais supprimée.';

create table if not exists public.attendance_record (
    id               uuid primary key default gen_random_uuid(),
    date_culte       date not null,
    service_type_id  uuid not null references public.service_type (id),
    lieu             text,
    notes            text,

    total_hommes     integer not null default 0,
    total_femmes     integer not null default 0,
    total_enfants    integer not null default 0,
    total_general    integer not null default 0,

    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    -- text (l'e-mail du compte), pas une clé étrangère vers auth.users :
    -- cette table n'est pas exposée par l'API REST PostgREST, un simple
    -- texte lisible évite d'avoir besoin d'une fonction security definer
    -- pour l'afficher (comme journaliser_registre() a dû le faire, voir
    -- schema_supabase.sql § 10). updated_by n'est renseigné que par une
    -- véritable modification — jamais à la création (même choix côté Flask).
    created_by       text,
    updated_by       text,

    constraint attendance_totaux_non_negatifs check (
        total_hommes >= 0 and total_femmes >= 0
        and total_enfants >= 0 and total_general >= 0
    ),
    constraint attendance_lieu_longueur_raisonnable
        check (lieu is null or char_length(lieu) <= 150),
    constraint attendance_notes_longueur_raisonnable
        check (notes is null or char_length(notes) <= 2000)
);

comment on table public.attendance_record is
  'Une ligne = les présences d''un culte donné (totaux dénormalisés — voir attendance_value pour le détail par catégorie).';

create index if not exists attendance_record_date_idx
    on public.attendance_record (date_culte desc);
create index if not exists attendance_record_service_type_idx
    on public.attendance_record (service_type_id);

drop trigger if exists attendance_record_touch_updated_at on public.attendance_record;
create trigger attendance_record_touch_updated_at
    before update on public.attendance_record
    for each row execute function public.touch_updated_at();

create table if not exists public.attendance_value (
    id                    uuid primary key default gen_random_uuid(),
    attendance_record_id  uuid not null references public.attendance_record (id) on delete cascade,
    category_id           uuid not null references public.attendance_category (id),
    effectif              integer not null default 0 check (effectif >= 0),
    unique (attendance_record_id, category_id)
);

comment on table public.attendance_value is
  'Effectif d''une catégorie précise pour un culte précis.';

create index if not exists attendance_value_record_idx
    on public.attendance_value (attendance_record_id);


-- RLS : mêmes règles que le registre (schema_supabase.sql § 7) — lecture
-- pour tout compte muni d'un rôle, écriture réservée à secretaire/pasteur.
alter table public.service_type       enable row level security;
alter table public.attendance_category enable row level security;
alter table public.attendance_record   enable row level security;
alter table public.attendance_value    enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array['service_type', 'attendance_category',
                              'attendance_record', 'attendance_value']
    loop
        execute format(
            'drop policy if exists "presences lecture pour comptes avec un role" on public.%I', t);
        execute format(
            'create policy "presences lecture pour comptes avec un role" on public.%I '
            'for select to authenticated using (public.role_utilisateur() is not null)', t);

        execute format(
            'drop policy if exists "presences insertion secretaire ou pasteur" on public.%I', t);
        execute format(
            'create policy "presences insertion secretaire ou pasteur" on public.%I '
            'for insert to authenticated '
            'with check (public.role_utilisateur() in (''secretaire'', ''pasteur''))', t);

        execute format(
            'drop policy if exists "presences modification secretaire ou pasteur" on public.%I', t);
        execute format(
            'create policy "presences modification secretaire ou pasteur" on public.%I '
            'for update to authenticated '
            'using      (public.role_utilisateur() in (''secretaire'', ''pasteur'')) '
            'with check (public.role_utilisateur() in (''secretaire'', ''pasteur''))', t);

        execute format(
            'drop policy if exists "presences suppression secretaire ou pasteur" on public.%I', t);
        execute format(
            'create policy "presences suppression secretaire ou pasteur" on public.%I '
            'for delete to authenticated '
            'using (public.role_utilisateur() in (''secretaire'', ''pasteur''))', t);
    end loop;
end $$;


-- Types de culte et catégories d'âge par défaut — une seule fois (mêmes
-- valeurs que côté Flask, app.py : initialiser_donnees_presences()).
insert into public.service_type (nom, ordre_affichage)
select v.nom, v.ordre
from (values
    ('Culte du dimanche', 0), ('Culte du mercredi', 1), ('Culte du vendredi', 2),
    ('Réunion de prière', 3), ('Étude biblique', 4), ('Événement spécial', 5), ('Autre', 6)
) as v(nom, ordre)
where not exists (select 1 from public.service_type);

insert into public.attendance_category (nom, groupe, age_min, age_max, ordre_affichage)
select v.nom, v.groupe, v.age_min, v.age_max, v.ordre
from (values
    ('Garçons / adolescents', 'hommes', 13, 17, 0),
    ('Jeunes hommes',         'hommes', 18, 25, 1),
    ('Hommes adultes',        'hommes', 26, 59, 2),
    ('Hommes seniors',        'hommes', 60, null, 3),
    ('Filles / adolescentes', 'femmes', 13, 17, 0),
    ('Jeunes femmes',         'femmes', 18, 25, 1),
    ('Femmes adultes',        'femmes', 26, 59, 2),
    ('Femmes seniors',        'femmes', 60, null, 3),
    ('Bébés',                 'enfants', 0, 2, 0),
    ('Petits enfants',        'enfants', 3, 6, 1),
    ('Enfants',               'enfants', 7, 9, 2),
    ('Pré-adolescents',       'enfants', 10, 12, 3)
) as v(nom, groupe, age_min, age_max, ordre)
where not exists (select 1 from public.attendance_category);


-- ------------------------------------------------------------
-- Vérification (les 4 colonnes doivent afficher : true, true, true, true)
-- ------------------------------------------------------------
select
    (select count(*) = 4 from pg_tables where schemaname = 'public'
     and tablename in ('service_type', 'attendance_category',
                        'attendance_record', 'attendance_value'))   as tables_creees,
    (select count(*) > 0 from public.service_type)                  as types_de_culte_semes,
    (select count(*) = 12 from public.attendance_category)          as categories_semees,
    (select count(*) >= 16 from pg_policies where schemaname = 'public'
     and tablename in ('service_type', 'attendance_category',
                        'attendance_record', 'attendance_value'))   as policies_en_place;
