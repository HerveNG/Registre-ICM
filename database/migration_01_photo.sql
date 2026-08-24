-- ============================================================
--  MIGRATION 01 — Ajout de la photo d'identité
-- ============================================================
--  À exécuter UNIQUEMENT si vous aviez déjà créé la base avec la
--  première version de schema_supabase.sql (sans les photos).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout.
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Sans risque : ne touche à aucune donnée existante.
-- ============================================================


-- 1. La colonne qui garde le chemin de la photo -------------------
alter table public.registre
    add column if not exists photo text;

comment on column public.registre.photo is
  'Chemin de la photo dans le bucket « photos ». Exemple : fideles/ab12cd34.jpg';


-- 2. L'espace de stockage des photos ------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', false, 5242880, array['image/jpeg','image/png','image/webp'])
on conflict (id) do update
  set file_size_limit    = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;


-- 3. Qui a le droit de déposer et de consulter les photos ---------
drop policy if exists "photos lecture connectes"      on storage.objects;
drop policy if exists "photos insertion connectes"    on storage.objects;
drop policy if exists "photos modification connectes" on storage.objects;
drop policy if exists "photos suppression connectes"  on storage.objects;

create policy "photos lecture connectes"
    on storage.objects for select
    to authenticated using (bucket_id = 'photos');

create policy "photos insertion connectes"
    on storage.objects for insert
    to authenticated with check (bucket_id = 'photos');

create policy "photos modification connectes"
    on storage.objects for update
    to authenticated using (bucket_id = 'photos') with check (bucket_id = 'photos');

create policy "photos suppression connectes"
    on storage.objects for delete
    to authenticated using (bucket_id = 'photos');


-- 4. Vérification -------------------------------------------------
-- Doit renvoyer une ligne « photo | text » :
select column_name, data_type
from information_schema.columns
where table_name = 'registre' and column_name = 'photo';

-- Doit renvoyer une ligne « photos | false » :
select id, public from storage.buckets where id = 'photos';
