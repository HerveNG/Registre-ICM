-- ============================================================
--  MIGRATION 06 — Reclassification des présences : Fils-ICM & Nouveaux
-- ============================================================
--  À exécuter UNIQUEMENT si votre base a déjà le module Présences (créée
--  avec une version de schema_supabase.sql antérieure au 10/09/2026, ou
--  ayant déjà reçu migration_05_presences.sql).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (section 13).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Idempotent, rejouable sans risque.
--
--  Ce que fait ce script :
--   1. Élargit la contrainte sur attendance_category.groupe pour autoriser
--      'fils_icm' et 'nouveaux' (elle n'acceptait jusqu'ici que 'hommes',
--      'femmes', 'enfants'). 'enfants' reste autorisé — vos catégories
--      d'âge existantes de ce groupe ne sont jamais supprimées, seulement
--      désactivées ci-dessous (elles restent lisibles sur les fiches déjà
--      enregistrées qui les utilisaient, voir categories_pour_edition()
--      côté Flask / categoriesParGroupe() côté web/index.html).
--   2. Ajoute à attendance_record les colonnes total_fils_icm et
--      total_nouveaux (défaut 0 — jamais renseignées pour les fiches
--      déjà enregistrées, qui gardent leur ventilation d'origine dans
--      total_hommes/total_femmes/total_enfants).
--   3. Désactive les catégories d'âge par défaut d'origine (Garçons /
--      adolescents, Jeunes hommes... Bébés, Petits enfants...) — UNIQUEMENT
--      si elles existent encore sous leur nom d'origine et sont actives ;
--      si vous les aviez renommées, ce script ne les touche pas.
--   4. Sème les nouvelles catégories par défaut : Enfants/Adolescent(e)s/
--      Adultes pour Hommes et Femmes ; Enfants/Adultes déclinés Hommes/
--      Femmes (sans tranche adolescent·e — moins pertinente pour ces deux
--      groupes) pour Fils-ICM et pour Nouveaux — seulement celles qui
--      n'existent pas déjà.
--   4b. Retire la tranche Adolescent(e)s de Fils-ICM/Nouveaux si une
--       exécution antérieure de ce script l'avait semée, et seulement si
--       aucune présence ne l'utilise déjà.
-- ============================================================


-- 1. Contrainte élargie sur groupe (garde 'enfants' pour les catégories
--    historiques désactivées à l'étape 3).
alter table public.attendance_category drop constraint if exists attendance_category_groupe_check;
alter table public.attendance_category
    add constraint attendance_category_groupe_check
    check (groupe in ('hommes', 'femmes', 'fils_icm', 'nouveaux', 'enfants'));

comment on table public.attendance_category is
  'Catégories au sein d''un groupe (hommes/femmes/fils_icm/nouveaux — enfants : legacy) — configurable, jamais supprimée.';


-- 2. Nouvelles colonnes de totaux dénormalisés sur attendance_record.
alter table public.attendance_record
    add column if not exists total_fils_icm integer not null default 0,
    add column if not exists total_nouveaux  integer not null default 0;

alter table public.attendance_record drop constraint if exists attendance_totaux_non_negatifs;
alter table public.attendance_record
    add constraint attendance_totaux_non_negatifs check (
        total_hommes >= 0 and total_femmes >= 0
        and total_fils_icm >= 0 and total_nouveaux >= 0
        and total_enfants >= 0 and total_general >= 0
    );


-- 3. Désactive les catégories par défaut d'origine (jamais supprimées —
--    voir le principe déjà appliqué dans migration_04/05).
update public.attendance_category
set is_active = false
where is_active = true
  and (nom, groupe) in (
    ('Garçons / adolescents', 'hommes'), ('Jeunes hommes', 'hommes'),
    ('Hommes adultes',        'hommes'), ('Hommes seniors', 'hommes'),
    ('Filles / adolescentes', 'femmes'), ('Jeunes femmes',  'femmes'),
    ('Femmes adultes',        'femmes'), ('Femmes seniors', 'femmes'),
    ('Bébés',                 'enfants'), ('Petits enfants', 'enfants'),
    ('Enfants',               'enfants'), ('Pré-adolescents', 'enfants')
  );


-- 4. Sème les nouvelles catégories par défaut — une seule fois chacune.
--    Fils-ICM et Nouveaux n'ont que deux tranches (Enfants/Adultes) par
--    sexe, pas trois : contrairement à Hommes/Femmes, ce ne sont pas des
--    groupes d'âge général, la distinction adolescent/adulte y est moins
--    utile (décision du 10/09/2026).
insert into public.attendance_category (nom, groupe, age_min, age_max, ordre_affichage)
select v.nom, v.groupe, v.age_min, v.age_max, v.ordre
from (values
    ('Enfants',      'hommes',   0, 12,   0),
    ('Adolescents',  'hommes',  13, 17,   1),
    ('Adultes',      'hommes',  18, null, 2),
    ('Enfants',      'femmes',   0, 12,   0),
    ('Adolescentes', 'femmes',  13, 17,   1),
    ('Adultes',      'femmes',  18, null, 2),
    ('Hommes — Enfants', 'fils_icm', 0, 12,   0),
    ('Hommes — Adultes', 'fils_icm', 18, null, 1),
    ('Femmes — Enfants', 'fils_icm', 0, 12,   2),
    ('Femmes — Adultes', 'fils_icm', 18, null, 3),
    ('Hommes — Enfants', 'nouveaux', 0, 12,   0),
    ('Hommes — Adultes', 'nouveaux', 18, null, 1),
    ('Femmes — Enfants', 'nouveaux', 0, 12,   2),
    ('Femmes — Adultes', 'nouveaux', 18, null, 3)
) as v(nom, groupe, age_min, age_max, ordre)
where not exists (
    select 1 from public.attendance_category c
    where c.nom = v.nom and c.groupe = v.groupe
);

-- 4b. Si une exécution précédente de ce script avait semé la tranche
--     Adolescent(e)s pour Fils-ICM/Nouveaux (version antérieure au
--     10/09/2026, revue le jour même), on la retire — uniquement si aucune
--     présence enregistrée ne s'en sert déjà, jamais autrement.
delete from public.attendance_category c
where c.groupe in ('fils_icm', 'nouveaux')
  and c.nom in ('Hommes — Adolescents', 'Femmes — Adolescentes')
  and not exists (
      select 1 from public.attendance_value v where v.category_id = c.id
  );


-- ------------------------------------------------------------
-- Vérification (les 3 colonnes doivent afficher : true, true, true)
-- ------------------------------------------------------------
select
    (select count(*) > 0 from information_schema.columns
     where table_schema = 'public' and table_name = 'attendance_record'
     and column_name in ('total_fils_icm', 'total_nouveaux')
     having count(*) = 2)                                                  as colonnes_totaux_ajoutees,
    (select count(*) >= 8 from public.attendance_category
     where groupe in ('fils_icm', 'nouveaux') and is_active)               as categories_fils_icm_nouveaux_semees,
    (select count(*) from pg_constraint
     where conname = 'attendance_category_groupe_check') = 1               as contrainte_groupe_elargie;
