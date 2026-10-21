-- Restrições para novos registros; NOT VALID preserva registros legados.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'servidores'::regclass
           AND conname = 'servidores_id_origem_preenchido_ck'
    ) THEN
        ALTER TABLE servidores ADD CONSTRAINT servidores_id_origem_preenchido_ck
            CHECK (btrim(id_origem) <> '') NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'servidores'::regclass
           AND conname = 'servidores_uf_valida_ck'
    ) THEN
        ALTER TABLE servidores ADD CONSTRAINT servidores_uf_valida_ck
            CHECK (uf IS NULL OR uf IN (
                'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO',
                'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI',
                'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
            )) NOT VALID;
    END IF;
END
$$;
