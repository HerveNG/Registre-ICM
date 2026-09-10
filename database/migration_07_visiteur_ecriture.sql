-- ============================================================
--  MIGRATION 07 — Reclassification des droits : le Visiteur peut écrire
-- ============================================================
--  À exécuter UNIQUEMENT si votre base existe déjà (créée avec une
--  version de schema_supabase.sql antérieure au 10/09/2026).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (sections 7, 8, 13).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Idempotent, rejouable sans risque.
--
--  Ce que fait ce script : jusqu'ici, le Visiteur ne pouvait que consulter
--  (recherche, fiche, carte imprimable) — secrétaire et pasteur avaient
--  seuls le droit de créer, modifier, importer, exporter ou supprimer.
--  Depuis le 10/09/2026, les trois rôles ont exactement les mêmes droits
--  d'écriture (créer une fiche/présence, la modifier, importer, exporter,
--  gérer les paramètres des présences) — SEULE la suppression définitive
--  (fiche, présence, catégorie, type de culte, photo) reste réservée à
--  secrétaire et pasteur. Ce script remplace les policies RLS
--  d'insertion/modification pour :
--   1. La table registre (§7 de schema_supabase.sql).
--   2. Le bucket de stockage des photos (§8).
--   3. Les quatre tables du module Présences : service_type,
--      attendance_category, attendance_record, attendance_value (§13).
--  Les policies de suppression ne sont pas touchées : elles restent
--  réservées secrétaire/pasteur, exactement comme avant.
-- ============================================================


-- 1. Registre des baptêmes/mariages.
drop policy if exists "ecriture secretaire ou pasteur - insertion"    on public.registre;
drop policy if exists "ecriture secretaire ou pasteur - modification" on public.registre;

create policy "ecriture tous roles - insertion"
    on public.registre for insert
    to authenticated
    with check (public.role_utilisateur() in ('secretaire', 'pasteur', 'visiteur'));

create policy "ecriture tous roles - modification"
    on public.registre for update
    to authenticated
    using      (public.role_utilisateur() in ('secretaire', 'pasteur', 'visiteur'))
    with check (public.role_utilisateur() in ('secretaire', 'pasteur', 'visiteur'));

-- Renomme la policy de suppression existante pour rester cohérent avec
-- schema_supabase.sql (aucun changement de droits ici).
drop policy if exists "ecriture secretaire ou pasteur - suppression" on public.registre;
create policy "suppression secretaire ou pasteur"
    on public.registre for delete
    to authenticated
    using (public.role_utilisateur() in ('secretaire', 'pasteur'));


-- 2. Bucket de stockage des photos.
drop policy if exists "photos ecriture secretaire ou pasteur - insertion"    on storage.objects;
drop policy if exists "photos ecriture secretaire ou pasteur - modification" on storage.objects;

create policy "photos ecriture tous roles - insertion"
    on storage.objects for insert
    to authenticated
    with check (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur', 'visiteur'));

create policy "photos ecriture tous roles - modification"
    on storage.objects for update
    to authenticated
    using      (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur', 'visiteur'))
    with check (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur', 'visiteur'));

drop policy if exists "photos ecriture secretaire ou pasteur - suppression" on storage.objects;
create policy "photos suppression secretaire ou pasteur"
    on storage.objects for delete
    to authenticated
    using (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur'));


-- 3. Module Présences (les quatre tables partagent les mêmes règles).
do $$
declare
    t text;
begin
    foreach t in array array['service_type', 'attendance_category',
                              'attendance_record', 'attendance_value']
    loop
        execute format(
            'drop policy if exists "presences insertion secretaire ou pasteur" on public.%I', t);
        execute format(
            'create policy "presences insertion tous roles" on public.%I '
            'for insert to authenticated '
            'with check (public.role_utilisateur() in (''secretaire'', ''pasteur'', ''visiteur''))', t);

        execute format(
            'drop policy if exists "presences modification secretaire ou pasteur" on public.%I', t);
        execute format(
            'create policy "presences modification tous roles" on public.%I '
            'for update to authenticated '
            'using      (public.role_utilisateur() in (''secretaire'', ''pasteur'', ''visiteur'')) '
            'with check (public.role_utilisateur() in (''secretaire'', ''pasteur'', ''visiteur''))', t);
        -- La policy de suppression n'est pas touchée : elle reste
        -- "presences suppression secretaire ou pasteur", inchangée.
    end loop;
end $$;


-- ------------------------------------------------------------
-- Vérification (les 3 colonnes doivent afficher : true, true, true)
-- ------------------------------------------------------------
select
    (select count(*) = 1 from pg_policies
     where schemaname = 'public' and tablename = 'registre'
     and policyname = 'ecriture tous roles - insertion')             as registre_ouvert_visiteur,
    (select count(*) = 1 from pg_policies
     where schemaname = 'storage' and tablename = 'objects'
     and policyname = 'photos ecriture tous roles - insertion')       as photos_ouvertes_visiteur,
    (select count(*) = 4 from pg_policies
     where schemaname = 'public' and policyname = 'presences insertion tous roles'
     and tablename in ('service_type', 'attendance_category',
                        'attendance_record', 'attendance_value'))     as presences_ouvertes_visiteur;
