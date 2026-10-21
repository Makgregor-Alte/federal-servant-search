"""Verificações de integridade para importações e auditorias agregadas."""


STAGE_CONFLICTS_SQL = """
    SELECT EXISTS (
        SELECT 1
          FROM pg_temp.importacao_servidores_stage AS novo
          JOIN servidores AS anterior
            ON anterior.fonte = novo.fonte AND anterior.id_origem = novo.id_origem
         WHERE (anterior.nome, anterior.cargo, anterior.orgao,
                anterior.uf, anterior.competencia)
               IS DISTINCT FROM
               (novo.nome, novo.cargo, novo.orgao, novo.uf, novo.competencia)
    )
"""


ROW_CONFLICT_SQL = """
    WITH novos (nome, cargo, orgao, uf, fonte, id_origem, competencia) AS (
        VALUES {values}
    )
    SELECT EXISTS (
        SELECT 1
          FROM novos
          JOIN servidores AS anterior
            ON anterior.fonte = novos.fonte AND anterior.id_origem = novos.id_origem
         WHERE (anterior.nome, anterior.cargo, anterior.orgao,
                anterior.uf, anterior.competencia)
               IS DISTINCT FROM
               (novos.nome, novos.cargo, novos.orgao, novos.uf, novos.competencia)
    )
"""


CONFLICT_MESSAGE = "Identificador de origem reutilizado com dados ou competencia divergentes"


def assert_stage_consistent(cursor) -> None:
    """Impede que ON CONFLICT oculte alterações de conteúdo ou competência."""
    cursor.execute(STAGE_CONFLICTS_SQL)
    if cursor.fetchone()[0]:
        raise ValueError(CONFLICT_MESSAGE)


def assert_rows_consistent(cursor, rows: tuple[tuple, ...]) -> None:
    """Valida uma amostra de forma parametrizada, sem usar texto dos registros no SQL."""
    if not rows:
        return
    placeholders = "(%s, %s, %s, %s, %s, %s, %s::date)"
    sql = ROW_CONFLICT_SQL.format(values=", ".join([placeholders] * len(rows)))
    arguments = [value for row in rows for value in row]
    cursor.execute(sql, arguments)
    if cursor.fetchone()[0]:
        raise ValueError(CONFLICT_MESSAGE)


def audit_connection(connection) -> dict:
    """Resumo somente de contagens; não retorna identificadores nem dados pessoais."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT fonte, to_char(competencia, 'YYYY-MM'), COUNT(*),
                   COUNT(*) FILTER (WHERE uf IS NULL)
              FROM servidores
             GROUP BY fonte, competencia
             ORDER BY fonte, competencia
        """)
        groups = [
            {"fonte": source, "competencia": month, "registros": total,
             "sem_uf": no_uf}
            for source, month, total, no_uf in cursor.fetchall()
        ]
        cursor.execute("""
            SELECT COUNT(*)
              FROM servidores AS s
              JOIN lotes_importacao AS l ON l.id = s.lote_importacao_id
             WHERE s.fonte IS DISTINCT FROM l.fonte
                OR (l.competencia IS NOT NULL
                    AND s.competencia IS DISTINCT FROM l.competencia)
        """)
        mismatches = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*) FROM servidores WHERE lote_importacao_id IS NULL
        """)
        without_batch = cursor.fetchone()[0]
        cursor.execute("""
            SELECT COUNT(*) FROM lotes_importacao WHERE estado = 'falhou'
        """)
        failed_batches = cursor.fetchone()[0]
    return {
        "fontes": groups,
        "registros_sem_lote": without_batch,
        "registros_divergentes_do_lote": mismatches,
        "lotes_com_falha": failed_batches,
    }
