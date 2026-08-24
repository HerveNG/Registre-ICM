-- ============================================================
--  ICM — Registre Baptêmes & Mariages
--  Schéma SQLite (version locale, utilisée par l'application Flask)
-- ============================================================
--  Ce fichier est fourni à titre documentaire : l'application
--  Flask crée automatiquement cette table au premier démarrage
--  (SQLAlchemy). Vous n'avez rien à exécuter manuellement.
-- ============================================================

CREATE TABLE IF NOT EXISTS registre (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identité
    nom                 TEXT    NOT NULL,
    prenom              TEXT    NOT NULL,
    nom_pere            TEXT,
    nom_mere            TEXT,
    date_naissance      DATE,
    nationalite         TEXT,
    originaire_de       TEXT,

    -- Baptême
    date_bapteme        DATE,
    lieu_bapteme        TEXT,
    numero_registre_1   TEXT,
    celebrant_bapteme   TEXT,
    signature_1         TEXT,

    -- Mariage (facultatif)
    lieu_mariage        TEXT,
    date_mariage        DATE,
    conjoint            TEXT,
    numero_registre_2   TEXT,
    celebrant_mariage   TEXT,
    signature_2         TEXT,

    -- Photo d'identité
    -- Nom du fichier rangé dans static/photos/ — l'image elle-même
    -- n'est pas stockée dans la base.
    photo               TEXT,

    -- Divers
    telephone           TEXT,
    observations        TEXT,

    -- Traçabilité
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS registre_numero_1_unique
    ON registre (numero_registre_1)
    WHERE numero_registre_1 IS NOT NULL AND numero_registre_1 <> '';

CREATE UNIQUE INDEX IF NOT EXISTS registre_numero_2_unique
    ON registre (numero_registre_2)
    WHERE numero_registre_2 IS NOT NULL AND numero_registre_2 <> '';

CREATE INDEX IF NOT EXISTS registre_nom_idx     ON registre (nom);
CREATE INDEX IF NOT EXISTS registre_bapteme_idx ON registre (date_bapteme);
CREATE INDEX IF NOT EXISTS registre_mariage_idx ON registre (date_mariage);
