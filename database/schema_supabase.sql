-- ============================================================
--  IN CHRIST MINISTRIES (ICM)
--  Registre numérique des Baptêmes et Mariages
--  Schéma PostgreSQL — à exécuter dans Supabase > SQL Editor
-- ============================================================
--  Mode d'emploi :
--   1. Créer un projet sur https://supabase.com (plan gratuit)
--   2. Ouvrir "SQL Editor" > "New query"
--   3. Coller TOUT ce fichier puis cliquer "Run"
--   4. Créer ensuite chaque compte (secrétariat, pasteur…) dans
--      "Authentication" > "Users" > "Add user"
--   5. Attribuer son rôle à chaque compte : voir la section 6
--      ci-dessous (COMPTES ET RÔLES) — sans cette étape, un compte
--      créé ne peut rien lire ni écrire dans le registre.
-- ============================================================


-- ------------------------------------------------------------
-- 1. TABLE PRINCIPALE
-- ------------------------------------------------------------
-- Un enregistrement = une carte (un fidèle).
-- Le bloc "mariage" reste vide tant que la personne n'est pas mariée,
-- exactement comme sur la carte papier.

create table if not exists public.registre (
    id                  uuid primary key default gen_random_uuid(),

    -- Identité --------------------------------------------------
    nom                 text not null,
    prenom              text not null,
    nom_pere            text,                       -- "Fils de :"
    nom_mere            text,                       -- "Et de :"
    date_naissance      date,
    nationalite         text,
    originaire_de       text,

    -- Baptême ---------------------------------------------------
    date_bapteme        date,
    lieu_bapteme        text,
    numero_registre_1   text,                       -- "N° du Registre (1)"
    celebrant_bapteme   text,
    signature_1         text,                       -- "certifié exact" — Signature (1)

    -- Mariage (facultatif) --------------------------------------
    lieu_mariage        text,                       -- "A :"
    date_mariage        date,                       -- "Le ..../..../...."
    conjoint            text,                       -- "Avec :"
    numero_registre_2   text,                       -- "N° du Registre (2)"
    celebrant_mariage   text,
    signature_2         text,                       -- Signature (2)

    -- Photo d'identité ------------------------------------------
    -- L'image n'est PAS stockée ici : seulement son chemin dans le
    -- bucket « photos » (section 8). Exemple : "fideles/ab12cd34.jpg"
    photo               text,

    -- Divers ----------------------------------------------------
    telephone           text,
    observations        text,

    -- Traçabilité -----------------------------------------------
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    created_by          uuid references auth.users (id) on delete set null,

    -- Garde-fous ------------------------------------------------
    constraint nom_non_vide          check (length(trim(nom)) > 0),
    constraint prenom_non_vide       check (length(trim(prenom)) > 0),
    constraint bapteme_apres_naissance
        check (date_bapteme is null or date_naissance is null
               or date_bapteme >= date_naissance),
    constraint mariage_apres_naissance
        check (date_mariage is null or date_naissance is null
               or date_mariage >= date_naissance)
);

comment on table public.registre is
  'Registre ICM des baptêmes et mariages — une ligne par carte de fidèle.';


-- ------------------------------------------------------------
-- 2. UNICITÉ DES NUMÉROS DE REGISTRE
-- ------------------------------------------------------------
-- Deux fidèles ne peuvent pas porter le même numéro de registre.
-- (index partiel : les champs vides ne bloquent rien)

create unique index if not exists registre_numero_1_unique
    on public.registre (numero_registre_1)
    where numero_registre_1 is not null and numero_registre_1 <> '';

create unique index if not exists registre_numero_2_unique
    on public.registre (numero_registre_2)
    where numero_registre_2 is not null and numero_registre_2 <> '';


-- ------------------------------------------------------------
-- 3. INDEX DE RECHERCHE
-- ------------------------------------------------------------
create index if not exists registre_nom_idx     on public.registre (lower(nom));
create index if not exists registre_prenom_idx  on public.registre (lower(prenom));
create index if not exists registre_bapteme_idx on public.registre (date_bapteme);
create index if not exists registre_mariage_idx on public.registre (date_mariage);


-- ------------------------------------------------------------
-- 4. MISE À JOUR AUTOMATIQUE DE updated_at
-- ------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists registre_touch_updated_at on public.registre;
create trigger registre_touch_updated_at
    before update on public.registre
    for each row execute function public.touch_updated_at();


-- ------------------------------------------------------------
-- 5. NUMÉROTATION AUTOMATIQUE DES REGISTRES
-- ------------------------------------------------------------
-- Si le numéro n'est pas saisi à la main, il est généré :
--   Baptême : ICM-B-2026-0001
--   Mariage : ICM-M-2026-0001

create sequence if not exists public.seq_registre_bapteme start 1;
create sequence if not exists public.seq_registre_mariage start 1;

create or replace function public.attribuer_numeros()
returns trigger
language plpgsql
as $$
begin
    if new.date_bapteme is not null
       and (new.numero_registre_1 is null or trim(new.numero_registre_1) = '') then
        new.numero_registre_1 := 'ICM-B-'
            || to_char(new.date_bapteme, 'YYYY') || '-'
            || lpad(nextval('public.seq_registre_bapteme')::text, 4, '0');
    end if;

    if new.date_mariage is not null
       and (new.numero_registre_2 is null or trim(new.numero_registre_2) = '') then
        new.numero_registre_2 := 'ICM-M-'
            || to_char(new.date_mariage, 'YYYY') || '-'
            || lpad(nextval('public.seq_registre_mariage')::text, 4, '0');
    end if;

    return new;
end;
$$;

drop trigger if exists registre_attribuer_numeros on public.registre;
create trigger registre_attribuer_numeros
    before insert or update on public.registre
    for each row execute function public.attribuer_numeros();


-- ------------------------------------------------------------
-- 6. COMPTES ET RÔLES
-- ------------------------------------------------------------
-- Une ligne par compte Supabase autorisé à utiliser le registre.
-- role vaut 'secretaire', 'pasteur' ou 'visiteur' :
--   - secretaire / pasteur : accès complet (saisie, modification,
--     suppression, import, export) — mêmes droits pour les deux,
--     seul le compte diffère (savoir qui a fait quoi).
--   - visiteur : consultation seule (recherche, fiche, carte
--     imprimable), aucune écriture.
-- Un compte Authentication sans ligne ici ne peut rien lire ni
-- écrire : voir l'étape 5 du mode d'emploi, en haut de ce fichier.

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
-- "authenticated" : un rôle s'attribue à la main (étape 5, en haut de
-- ce fichier), depuis le SQL Editor ou le Table Editor de Supabase —
-- jamais depuis l'application elle-même.

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


-- ------------------------------------------------------------
-- 7. SÉCURITÉ (RLS) — indispensable
-- ------------------------------------------------------------
-- Sans ces règles, la clé publique de l'application donnerait accès
-- au registre à n'importe qui. Ici, la lecture demande un compte
-- muni d'un rôle (section 6) ; l'écriture (ajout, modification,
-- suppression) est réservée aux rôles secretaire et pasteur.

alter table public.registre enable row level security;

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


-- ------------------------------------------------------------
-- 8. PHOTOS D'IDENTITÉ — espace de stockage
-- ------------------------------------------------------------
-- Les photos ne sont pas mises dans la table : elles vont dans un
-- « bucket » de fichiers, et la colonne registre.photo garde
-- seulement leur chemin. La base reste ainsi légère et rapide.
--
-- Le bucket est PRIVÉ : une photo n'est jamais accessible par une
-- simple adresse web. L'application demande un lien temporaire
-- (valable 1 h) à chaque affichage, et seuls les comptes connectés
-- peuvent en obtenir un.
--
-- Limite fixée à 512 000 octets (500 Ko) : l'application compresse déjà
-- chaque photo sous ce seuil avant l'envoi (static/photo.js) — cette
-- limite est la seconde ligne de défense, imposée par la base elle-même.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('photos', 'photos', false, 512000, array['image/jpeg','image/png','image/webp'])
on conflict (id) do update
  set file_size_limit    = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

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

-- Si cette section renvoie une erreur de permission (« must be owner
-- of table objects »), créez le bucket à la main :
--   Storage > New bucket > nom « photos » > décocher « Public »
--   > Additional configuration > File size limit > 500 KB (ou 0.5 MB
--   selon l'unité proposée par l'écran)
-- puis, dans l'onglet Policies du bucket, autorisez SELECT pour tout
-- compte muni d'un rôle, et INSERT/UPDATE/DELETE pour secretaire et
-- pasteur uniquement (mêmes conditions que ci-dessus).


-- ------------------------------------------------------------
-- 9. VUE STATISTIQUES (facultatif, pratique pour le tableau de bord)
-- ------------------------------------------------------------
create or replace view public.v_statistiques as
select
    count(*)                                          as total_fideles,
    count(*) filter (where date_bapteme is not null)  as total_baptemes,
    count(*) filter (where date_mariage is not null)  as total_mariages,
    count(*) filter (where date_bapteme >= date_trunc('year', current_date))
                                                      as baptemes_annee_en_cours,
    count(*) filter (where date_mariage >= date_trunc('year', current_date))
                                                      as mariages_annee_en_cours
from public.registre;


-- ------------------------------------------------------------
-- 10. JEU D'ESSAI (à supprimer avant la mise en service réelle)
-- ------------------------------------------------------------
-- insert into public.registre
--   (nom, prenom, nom_pere, nom_mere, date_naissance, nationalite,
--    originaire_de, date_bapteme, lieu_bapteme, celebrant_bapteme, signature_1)
-- values
--   ('NGOOH', 'Hervé', 'NGOOH Paul', 'MBALLA Marie', '1990-04-12',
--    'Camerounaise', 'Yaoundé', '2024-06-02', 'Temple ICM Douala',
--    'Past. Jean ETOUNDI', 'Past. Jean ETOUNDI');
