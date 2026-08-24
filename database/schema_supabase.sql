-- ============================================================
--  IN CHRIST MINISTRIES (ICM)
--  Registre numérique des Baptêmes et Mariages
--  Schéma PostgreSQL — à exécuter dans Supabase > SQL Editor
-- ============================================================
--  Mode d'emploi :
--   1. Créer un projet sur https://supabase.com (plan gratuit)
--   2. Ouvrir "SQL Editor" > "New query"
--   3. Coller TOUT ce fichier puis cliquer "Run"
--   4. Créer ensuite le compte du secrétariat dans
--      "Authentication" > "Users" > "Add user"
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
    -- bucket « photos » (section 9). Exemple : "fideles/ab12cd34.jpg"
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
-- 6. SÉCURITÉ (RLS) — indispensable
-- ------------------------------------------------------------
-- Sans ces règles, la clé publique de l'application donnerait
-- accès au registre à n'importe qui. Ici, SEULES les personnes
-- connectées (comptes créés par vous dans Authentication) peuvent
-- lire et écrire.

alter table public.registre enable row level security;

drop policy if exists "lecture pour utilisateurs connectes"     on public.registre;
drop policy if exists "insertion pour utilisateurs connectes"   on public.registre;
drop policy if exists "modification pour utilisateurs connectes" on public.registre;
drop policy if exists "suppression pour utilisateurs connectes" on public.registre;

create policy "lecture pour utilisateurs connectes"
    on public.registre for select
    to authenticated
    using (true);

create policy "insertion pour utilisateurs connectes"
    on public.registre for insert
    to authenticated
    with check (true);

create policy "modification pour utilisateurs connectes"
    on public.registre for update
    to authenticated
    using (true) with check (true);

create policy "suppression pour utilisateurs connectes"
    on public.registre for delete
    to authenticated
    using (true);


-- ------------------------------------------------------------
-- 7. PHOTOS D'IDENTITÉ — espace de stockage
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

create policy "photos lecture connectes"
    on storage.objects for select
    to authenticated
    using (bucket_id = 'photos');

create policy "photos insertion connectes"
    on storage.objects for insert
    to authenticated
    with check (bucket_id = 'photos');

create policy "photos modification connectes"
    on storage.objects for update
    to authenticated
    using (bucket_id = 'photos')
    with check (bucket_id = 'photos');

create policy "photos suppression connectes"
    on storage.objects for delete
    to authenticated
    using (bucket_id = 'photos');

-- Si cette section renvoie une erreur de permission (« must be owner
-- of table objects »), créez le bucket à la main :
--   Storage > New bucket > nom « photos » > décocher « Public »
--   > Additional configuration > File size limit > 500 KB (ou 0.5 MB
--   selon l'unité proposée par l'écran)
-- puis, dans l'onglet Policies du bucket, autorisez SELECT, INSERT,
-- UPDATE et DELETE pour le rôle « authenticated ».


-- ------------------------------------------------------------
-- 8. VUE STATISTIQUES (facultatif, pratique pour le tableau de bord)
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
-- 9. JEU D'ESSAI (à supprimer avant la mise en service réelle)
-- ------------------------------------------------------------
-- insert into public.registre
--   (nom, prenom, nom_pere, nom_mere, date_naissance, nationalite,
--    originaire_de, date_bapteme, lieu_bapteme, celebrant_bapteme, signature_1)
-- values
--   ('NGOOH', 'Hervé', 'NGOOH Paul', 'MBALLA Marie', '1990-04-12',
--    'Camerounaise', 'Yaoundé', '2024-06-02', 'Temple ICM Douala',
--    'Past. Jean ETOUNDI', 'Past. Jean ETOUNDI');
