-- ============================================================
--  MIGRATION 02 — Comptes et rôles (secrétaire / pasteur / visiteur)
-- ============================================================
--  À exécuter UNIQUEMENT si votre base existe déjà (créée avec une
--  version antérieure de schema_supabase.sql, sans les rôles).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout.
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Sans risque pour les fiches déjà enregistrées. En revanche, À
--  PARTIR de l'exécution de ce script, un compte Supabase qui n'a
--  pas encore de ligne dans "profils" ne pourra plus rien lire ni
--  écrire dans le registre — voir l'étape 5 ci-dessous, à faire
--  tout de suite après avoir lancé ce script.
-- ============================================================


-- 1. Table des rôles -----------------------------------------------
create table if not exists public.profils (
    id       uuid primary key references auth.users (id) on delete cascade,
    role     text not null check (role in ('secretaire', 'pasteur', 'visiteur')),
    cree_le  timestamptz not null default now()
);

comment on table public.profils is
  'Rôle de chaque compte Supabase autorisé à utiliser le registre ICM.';

alter table public.profils enable row level security;

drop policy if exists "chacun lit son propre profil" on public.profils;
create policy "chacun lit son propre profil"
    on public.profils for select
    to authenticated
    using (auth.uid() = id);

-- Volontairement, aucune policy insert/update/delete pour les comptes
-- "authenticated" : un rôle s'attribue à la main (étape 5), depuis le
-- SQL Editor ou le Table Editor de Supabase — jamais depuis l'appli.


-- 2. Fonction utilitaire : rôle du compte connecté ------------------
create or replace function public.role_utilisateur()
returns text
language sql
stable
security definer
set search_path = public
as $$
    select role from public.profils where id = auth.uid();
$$;

revoke all on function public.role_utilisateur() from public;
grant execute on function public.role_utilisateur() to authenticated;


-- 3. Remplace les règles de sécurité (RLS) du registre --------------
-- Avant : n'importe quel compte connecté pouvait tout faire.
-- Après : la lecture demande un rôle attribué (les trois rôles) ;
-- l'écriture (ajout, modification, suppression) est réservée à
-- secretaire et pasteur.

drop policy if exists "lecture pour utilisateurs connectes"      on public.registre;
drop policy if exists "insertion pour utilisateurs connectes"    on public.registre;
drop policy if exists "modification pour utilisateurs connectes" on public.registre;
drop policy if exists "suppression pour utilisateurs connectes"  on public.registre;

create policy "lecture pour comptes avec un role"
    on public.registre for select
    to authenticated
    using (public.role_utilisateur() is not null);

create policy "ecriture secretaire ou pasteur - insertion"
    on public.registre for insert
    to authenticated
    with check (public.role_utilisateur() in ('secretaire', 'pasteur'));

create policy "ecriture secretaire ou pasteur - modification"
    on public.registre for update
    to authenticated
    using      (public.role_utilisateur() in ('secretaire', 'pasteur'))
    with check (public.role_utilisateur() in ('secretaire', 'pasteur'));

create policy "ecriture secretaire ou pasteur - suppression"
    on public.registre for delete
    to authenticated
    using (public.role_utilisateur() in ('secretaire', 'pasteur'));


-- 4. Remplace les règles de sécurité (RLS) des photos ----------------
drop policy if exists "photos lecture connectes"      on storage.objects;
drop policy if exists "photos insertion connectes"    on storage.objects;
drop policy if exists "photos modification connectes" on storage.objects;
drop policy if exists "photos suppression connectes"  on storage.objects;

create policy "photos lecture pour comptes avec un role"
    on storage.objects for select
    to authenticated
    using (bucket_id = 'photos' and public.role_utilisateur() is not null);

create policy "photos ecriture secretaire ou pasteur - insertion"
    on storage.objects for insert
    to authenticated
    with check (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur'));

create policy "photos ecriture secretaire ou pasteur - modification"
    on storage.objects for update
    to authenticated
    using      (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur'))
    with check (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur'));

create policy "photos ecriture secretaire ou pasteur - suppression"
    on storage.objects for delete
    to authenticated
    using (bucket_id = 'photos' and public.role_utilisateur() in ('secretaire', 'pasteur'));


-- 5. Attribuer un rôle à chaque compte existant ----------------------
-- SANS CETTE ÉTAPE, PLUS PERSONNE NE PEUT LIRE LE REGISTRE après ce
-- script : chaque compte doit avoir sa ligne dans "profils".
--
-- a) Retrouvez l'identifiant (UUID) de chaque compte :
--      Authentication > Users > cliquez sur le compte > copiez "UID"
--    (ou : select id, email from auth.users;)
--
-- b) Pour chaque compte, exécutez (adaptez l'UUID et le rôle) :
--      insert into public.profils (id, role) values
--        ('00000000-0000-0000-0000-000000000000', 'secretaire');
--
--    Le compte du secrétariat qui existait déjà avant ce script doit
--    recevoir le rôle 'secretaire' pour continuer à tout faire comme
--    avant. Pour un nouveau compte pasteur ou visiteur : créez
--    d'abord le compte dans Authentication > Users > Add user, puis
--    répétez l'étape (b) avec son UUID et le rôle voulu.


-- 6. Vérification -----------------------------------------------------
-- Doit lister tous les comptes et leur rôle :
select p.role, u.email
from public.profils p
join auth.users u on u.id = p.id
order by p.role, u.email;
