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
-- 10. JOURNAL D'AUDIT
-- ------------------------------------------------------------
-- Une ligne par création, modification ou suppression d'une carte —
-- qui a fait quoi, et quand. Alimenté automatiquement par un trigger
-- sur "registre" : ni l'application ni aucun compte connecté ne peut
-- y écrire directement (voir la policy RLS plus bas) — seul le
-- trigger, exécuté avec les droits de son propriétaire, le peut.
--
-- registre_id n'est volontairement PAS une clé étrangère stricte :
-- une fiche supprimée doit rester traçable dans le journal, sans
-- dépendre de l'existence continue de la fiche. nom_complet est un
-- instantané pris au moment de l'action, pour rester lisible même
-- après une suppression ou un changement de nom.
--
-- Le détail des champs modifiés (details, pour une "modification")
-- s'appuie sur l'extension hstore, qui transforme une ligne en un
-- ensemble clé/valeur et permet de calculer simplement la différence
-- entre l'ancienne et la nouvelle version d'une fiche.
--
-- Différence avec la version Flask : une création issue d'un import
-- en lot n'est pas distinguée ici d'une saisie manuelle (le trigger
-- ne voit que la ligne insérée, pas l'origine de l'appel) — le
-- journal reste complet (qui, quoi, quand), seule l'étiquette
-- « import » de la version Flask n'a pas d'équivalent ici.

create extension if not exists hstore;

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

alter table public.journal_audit enable row level security;

drop policy if exists "lecture du journal pour comptes avec un role" on public.journal_audit;
create policy "lecture du journal pour comptes avec un role"
    on public.journal_audit for select
    to authenticated
    using (public.role_utilisateur() is not null);

-- Volontairement, aucune policy insert/update/delete pour "authenticated" :
-- seul le trigger ci-dessous (exécuté avec les droits de son propriétaire,
-- via security definer) écrit dans le journal — jamais l'application
-- directement — et personne ne peut modifier une entrée après coup.


-- Libellé lisible d'un champ du registre (mêmes libellés que
-- l'export/import Excel-CSV côté Flask, pour rester cohérent d'une
-- version de l'application à l'autre).
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

-- Représentation lisible d'une valeur de champ pour le journal : les
-- dates suivent le format jj/mm/aaaa, une valeur vide devient "—"
-- (mêmes règles que _texte_valeur() côté Flask).
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
        -- Ne garde que les champs qui ont réellement changé, en excluant
        -- les colonnes techniques (id, created_at/by, updated_at) qui ne
        -- font pas partie de la fiche elle-même.
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


-- ------------------------------------------------------------
-- 11. JEU D'ESSAI (à supprimer avant la mise en service réelle)
-- ------------------------------------------------------------
-- insert into public.registre
--   (nom, prenom, nom_pere, nom_mere, date_naissance, nationalite,
--    originaire_de, date_bapteme, lieu_bapteme, celebrant_bapteme, signature_1)
-- values
--   ('NGOOH', 'Hervé', 'NGOOH Paul', 'MBALLA Marie', '1990-04-12',
--    'Camerounaise', 'Yaoundé', '2024-06-02', 'Temple ICM Douala',
--    'Past. Jean ETOUNDI', 'Past. Jean ETOUNDI');
