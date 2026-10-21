-- Indices para igualdade, paginacao ordenada e busca textual.
-- Reexecutavel em bases previamente inicializadas.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_servidores_nome_ordenacao
    ON servidores (LOWER(nome), id);
CREATE INDEX IF NOT EXISTS idx_servidores_uf_nome
    ON servidores (uf, LOWER(nome), id);

-- O primeiro campo de cada indice composto substitui estes indices antigos.
DROP INDEX IF EXISTS idx_servidores_nome_exato;
DROP INDEX IF EXISTS idx_servidores_uf;
