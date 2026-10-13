-- Schema inicial. Executado automaticamente pelo Postgres apenas no PRIMEIRO
-- bootstrap do volume, ou aplicado manualmente por psql nas próximas versões.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS servidores (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome TEXT NOT NULL CHECK (btrim(nome) <> ''),
    cargo TEXT NOT NULL DEFAULT '',
    orgao TEXT NOT NULL DEFAULT '',
    uf CHAR(2) NULL CHECK (uf ~ '^[A-Z]{2}$'),
    fonte TEXT NOT NULL CHECK (btrim(fonte) <> ''),
    id_origem TEXT NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT servidores_fonte_id_origem_unique UNIQUE (fonte, id_origem)
);

CREATE INDEX IF NOT EXISTS idx_servidores_nome_exato ON servidores (LOWER(nome));
CREATE INDEX IF NOT EXISTS idx_servidores_nome_similar ON servidores USING gin (LOWER(nome) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_servidores_uf ON servidores (uf);
CREATE INDEX IF NOT EXISTS idx_servidores_cargo ON servidores USING gin (cargo gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_servidores_orgao ON servidores USING gin (orgao gin_trgm_ops);
