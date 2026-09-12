-- ============================================================
--  MIGRATION 09 — Réinitialisation du journal d'audit (compte unique)
-- ============================================================
--  À exécuter UNIQUEMENT si votre base existe déjà (créée avec une
--  version de schema_supabase.sql antérieure à cette migration).
--
--  Si vous créez la base maintenant, ignorez ce fichier :
--  schema_supabase.sql contient déjà tout (section 15).
--
--  Où : Supabase > SQL Editor > New query > coller > Run
--  Sans risque pour vos données existantes : ce script ajoute seulement
--  une fonction et élargit une contrainte — il ne touche à rien du
--  contenu actuel du journal. Idempotent, rejouable sans risque.
--
--  Le journal d'audit reste immuable pour tout le monde (§ 12.3,
--  migration_04_durcissement_securite.sql : aucune policy update/delete,
--  et un REVOKE UPDATE, DELETE ... FROM authenticated). Cette migration
--  ajoute une SEULE exception, volontairement étroite : une fonction RPC
--  qui vide entièrement le journal, mais qui refuse d'agir pour tout
--  compte autre que celui dont l'e-mail figure dans son corps (vérifié à
--  partir du jeton de la personne connectée — une personne précise, pas
--  un rôle de la table "profils").
--
--  Comme journaliser_registre() (section 10) le fait déjà pour ÉCRIRE
--  dans ce même journal, cette fonction contourne le REVOKE via
--  security definer : elle s'exécute avec les droits de son propriétaire,
--  qui lui n'a jamais été privé de DELETE. Exposée en RPC à
--  "authenticated" (n'importe quel compte connecté peut l'appeler),
--  c'est la vérification interne de l'e-mail — pas le GRANT — qui
--  réserve l'effet réel au seul compte autorisé ; tout autre compte
--  reçoit une erreur, sans que rien ne soit modifié.
--
--  La réinitialisation laisse volontairement une trace : une unique
--  ligne "reinitialisation" est réécrite juste après la purge (qui,
--  quand, combien de lignes effacées) — sinon l'opération qui vide le
--  journal serait elle-même invisible dans le journal.
--
--  Pour changer le compte autorisé : remplacer l'adresse ci-dessous et
--  relancer ce script (create or replace function, sans risque).
-- ============================================================


alter table public.journal_audit drop constraint if exists journal_audit_action_check;
alter table public.journal_audit add constraint journal_audit_action_check
    check (action in ('creation', 'modification', 'suppression', 'reinitialisation'));


create or replace function public.reinitialiser_journal_audit()
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
    v_email text := auth.jwt() ->> 'email';
    v_total  bigint;
begin
    if lower(coalesce(v_email, '')) <> lower('lemoine_herve@outlook.fr') then
        raise exception 'Seul le compte autorisé peut réinitialiser le journal.'
            using errcode = '42501';   -- insufficient_privilege
    end if;

    select count(*) into v_total from public.journal_audit;

    -- "where true" : sans clause WHERE, Supabase bloque le DELETE (garde-fou
    -- anti-suppression-accidentelle, actif même en security definer) avec
    -- l'erreur "DELETE requires a WHERE clause" — cette clause satisfait le
    -- garde-fou tout en supprimant réellement toutes les lignes.
    delete from public.journal_audit where true;

    insert into public.journal_audit (utilisateur, action, registre_id, nom_complet, details)
    values (v_email, 'reinitialisation', null, 'Journal d''audit',
            jsonb_build_object('lignes_supprimees', v_total));

    return v_total;
end;
$$;

comment on function public.reinitialiser_journal_audit() is
  'Vide entièrement journal_audit puis y réécrit une seule ligne de trace — réservé à un compte unique désigné dans le corps de la fonction (voir migration_09).';

revoke all on function public.reinitialiser_journal_audit() from public, anon;
grant execute on function public.reinitialiser_journal_audit() to authenticated;


-- ------------------------------------------------------------
-- Vérification (la colonne doit afficher : true)
-- ------------------------------------------------------------
select
    (select count(*) = 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public' and p.proname = 'reinitialiser_journal_audit')  as fonction_reinit_en_place;
