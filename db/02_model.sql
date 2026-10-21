CREATE TABLE IF NOT EXISTS lotes_importacao (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte TEXT NOT NULL CHECK (btrim(fonte) <> ''),
    nome_arquivo TEXT NOT NULL CHECK (btrim(nome_arquivo) <> ''),
    competencia DATE CHECK (competencia IS NULL OR EXTRACT(DAY FROM competencia) = 1),
    sha256 CHAR(64) CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
    estado TEXT NOT NULL DEFAULT 'iniciado'
        CHECK (estado IN ('iniciado', 'concluido', 'falhou')),
    iniciado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    concluido_em TIMESTAMPTZ,
    linhas_lidas BIGINT NOT NULL DEFAULT 0 CHECK (linhas_lidas >= 0),
    linhas_importadas BIGINT NOT NULL DEFAULT 0 CHECK (linhas_importadas >= 0),
    linhas_descartadas BIGINT NOT NULL DEFAULT 0 CHECK (linhas_descartadas >= 0),
    CONSTRAINT lotes_importacao_conclusao_ck CHECK (
        concluido_em IS NULL OR concluido_em >= iniciado_em
    )
);

ALTER TABLE servidores
    ADD COLUMN IF NOT EXISTS competencia DATE,
    ADD COLUMN IF NOT EXISTS lote_importacao_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'servidores'::regclass
          AND conname = 'servidores_competencia_primeiro_dia_ck'
    ) THEN
        ALTER TABLE servidores
            ADD CONSTRAINT servidores_competencia_primeiro_dia_ck
            CHECK (competencia IS NULL OR EXTRACT(DAY FROM competencia) = 1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'servidores'::regclass
          AND conname = 'servidores_lote_importacao_fk'
    ) THEN
        ALTER TABLE servidores
            ADD CONSTRAINT servidores_lote_importacao_fk
            FOREIGN KEY (lote_importacao_id)
            REFERENCES lotes_importacao (id) ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_servidores_lote_importacao
    ON servidores (lote_importacao_id);
