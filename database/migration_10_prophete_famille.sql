-- ============================================================
--  MIGRATION 10 — Rubrique « Prophète/Famille » (14/09/2026)
-- ============================================================
--  À exécuter UNIQUEMENT si votre base a déjà le module Présences (créée
--  avec une version de schema_supabase.sql antérieure au 14/09/2026, ou
--  ayant déjà reçu migration_05_presences.sql / migration_06_categorisation_
--  fils_icm_nouveaux.sql).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (section 13).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Idempotent, rejouable sans risque.
--
--  Ce que fait ce script :
--   1. Élargit la contrainte sur attendance_category.groupe pour autoriser
--      'prophete' (nouveau groupe, à côté de 'hommes', 'femmes', 'fils_icm',
--      'nouveaux', 'enfants').
--   2. Ajoute à attendance_record la colonne total_prophete (défaut 0 —
--      jamais renseignée pour les fiches déjà enregistrées).
--   3. Sème la catégorie par défaut « Prophète/Famille » — un seul
--      compteur global, sans détail par âge ni par sexe (contrairement à
--      Fils-ICM/Nouveaux) — uniquement si elle n'existe pas déjà.
-- ============================================================


-- 1. Contrainte élargie sur groupe.
alter table public.attendance_category drop constraint if exists attendance_category_groupe_check;
alter table public.attendance_category
    add constraint attendance_category_groupe_check
    check (groupe in ('hommes', 'femmes', 'fils_icm', 'nouveaux', 'prophete', 'enfants'));

comment on table public.attendance_category is
  'Catégories au sein d''un groupe (hommes/femmes/fils_icm/nouveaux/prophete — enfants : legacy) — configurable, jamais supprimée.';


-- 2. Nouvelle colonne de total dénormalisé sur attendance_record.
alter table public.attendance_record
    add column if not exists total_prophete integer not null default 0;

alter table public.attendance_record drop constraint if exists attendance_totaux_non_negatifs;
alter table public.attendance_record
    add constraint attendance_totaux_non_negatifs check (
        total_hommes >= 0 and total_femmes >= 0
        and total_fils_icm >= 0 and total_nouveaux >= 0
        and total_prophete >= 0
        and total_enfants >= 0 and total_general >= 0
    );


-- 3. Sème la catégorie par défaut — une seule fois.
insert into public.attendance_category (nom, groupe, age_min, age_max, ordre_affichage)
select 'Prophète/Famille', 'prophete', null, null, 0
where not exists (
    select 1 from public.attendance_category where groupe = 'prophete'
);


-- ------------------------------------------------------------
-- Vérification (les 3 colonnes doivent afficher : true, true, true)
-- ------------------------------------------------------------
select
    (select count(*) > 0 from information_schema.columns
     where table_schema = 'public' and table_name = 'attendance_record'
     and column_name = 'total_prophete')                                  as colonne_total_ajoutee,
    (select count(*) >= 1 from public.attendance_category
     where groupe = 'prophete' and is_active)                             as categorie_prophete_semee,
    (select count(*) from pg_constraint
     where conname = 'attendance_category_groupe_check') = 1              as contrainte_groupe_elargie;
