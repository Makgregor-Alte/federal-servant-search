"""Verificações de aceitação do PostgreSQL, sem exposição de registros individuais."""

try:
    from .integrity import audit_connection
except ImportError:
    from integrity import audit_connection


REQUIRED_COLUMNS = {
    "servidores": {
        "id", "nome", "cargo", "orgao", "uf", "fonte", "id_origem",
        "competencia", "lote_importacao_id",
    },
    "lotes_importacao": {
        "id", "fonte", "nome_arquivo", "competencia", "sha256", "estado",
        "linhas_lidas", "linhas_importadas", "linhas_descartadas",
    },
}
REQUIRED_INDEXES = {
    "idx_servidores_nome_ordenacao",
    "idx_servidores_nome_similar",
    "idx_servidores_uf_nome",
    "idx_servidores_cargo",
    "idx_servidores_orgao",
}
REQUIRED_CONSTRAINTS = {
    "servidores_fonte_id_origem_unique",
    "servidores_lote_importacao_fk",
    "servidores_competencia_primeiro_dia_ck",
    "servidores_id_origem_preenchido_ck",
    "servidores_uf_valida_ck",
}
REQUIRED_SOURCES = {"aposentados", "carreiras"}


def collect_snapshot(connection) -> dict:
    """Consulta somente metadados e contagens; não retorna valores dos servidores."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT table_name, column_name
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name IN ('servidores', 'lotes_importacao')
        """)
        columns = {}
        for table, column in cursor.fetchall():
            columns.setdefault(table, set()).add(column)

        cursor.execute("""
            SELECT index_table.relname
              FROM pg_index AS idx
              JOIN pg_class AS base_table ON base_table.oid = idx.indrelid
              JOIN pg_namespace AS ns ON ns.oid = base_table.relnamespace
              JOIN pg_class AS index_table ON index_table.oid = idx.indexrelid
             WHERE ns.nspname = current_schema()
               AND base_table.relname = 'servidores'
               AND idx.indisvalid AND idx.indisready
        """)
        indexes = {row[0] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT conname, convalidated FROM pg_constraint
             WHERE conrelid = to_regclass('servidores')
        """)
        constraints = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')")
        pg_trgm = bool(cursor.fetchone()[0])

        if any(table not in columns for table in REQUIRED_COLUMNS):
            return {
                "columns": columns, "indexes": indexes,
                "constraints": constraints, "pg_trgm": pg_trgm,
                "sources": {}, "data_issues": {}, "batches": {}, "provenance": {},
                "audit": {},
            }

        cursor.execute("""
            SELECT fonte, COUNT(*), COUNT(*) FILTER (WHERE uf IS NULL),
                   COUNT(*) FILTER (WHERE lote_importacao_id IS NULL)
              FROM servidores GROUP BY fonte ORDER BY fonte
        """)
        sources = {
            source: {"registros": total, "sem_uf": no_uf, "sem_lote": no_batch}
            for source, total, no_uf, no_batch in cursor.fetchall()
        }
        cursor.execute("""
            SELECT COUNT(*) FILTER (WHERE nome IS NULL OR btrim(nome) = ''),
                   COUNT(*) FILTER (WHERE id_origem IS NULL OR btrim(id_origem) = ''),
                   COUNT(*) FILTER (WHERE uf IS NOT NULL AND uf NOT IN (
                       'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS',
                       'MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC',
                       'SP','SE','TO'))
              FROM servidores
        """)
        data_issues = dict(zip(("nome_vazio", "id_origem_vazio", "uf_invalida"),
                               cursor.fetchone()))
        cursor.execute("""
            SELECT COUNT(*) FROM lotes_importacao AS l
             WHERE estado = 'concluido'
               AND (linhas_lidas <> linhas_importadas + linhas_descartadas
                    OR linhas_importadas <> (
                        SELECT COUNT(*) FROM servidores AS s
                         WHERE s.lote_importacao_id = l.id))
        """)
        data_issues["contagem_lote_inconsistente"] = cursor.fetchone()[0]
        cursor.execute("""
            SELECT fonte, estado, COUNT(*)
              FROM lotes_importacao GROUP BY fonte, estado ORDER BY fonte, estado
        """)
        batches = {}
        for source, state, total in cursor.fetchall():
            batches.setdefault(source, {})[state] = total
        cursor.execute("""
            SELECT fonte, sha256
              FROM lotes_importacao
             WHERE estado = 'concluido' AND sha256 IS NOT NULL
             GROUP BY fonte, sha256
        """)
        provenance = {}
        for source, checksum in cursor.fetchall():
            provenance.setdefault(source, set()).add(checksum)

    return {
        "columns": columns, "indexes": indexes, "constraints": constraints,
        "pg_trgm": pg_trgm, "sources": sources, "data_issues": data_issues,
        "batches": batches, "provenance": provenance,
        "audit": audit_connection(connection),
    }


def evaluate_snapshot(snapshot: dict, *, file_hashes: dict | None = None) -> dict:
    """Separa falhas estruturais de pendências de carga e de comprovação de origem."""
    errors = []
    pending = []
    warnings = []
    for table, required in REQUIRED_COLUMNS.items():
        missing = required - snapshot["columns"].get(table, set())
        if missing:
            errors.append(f"Colunas ausentes em {table}: {', '.join(sorted(missing))}")
    missing_indexes = REQUIRED_INDEXES - snapshot["indexes"]
    if missing_indexes:
        errors.append("Indices ausentes: " + ", ".join(sorted(missing_indexes)))
    missing_constraints = REQUIRED_CONSTRAINTS - set(snapshot["constraints"])
    if missing_constraints:
        errors.append("Restricoes ausentes: " + ", ".join(sorted(missing_constraints)))
    if not snapshot["pg_trgm"]:
        errors.append("Extensao pg_trgm ausente")

    for issue, count in snapshot["data_issues"].items():
        if count:
            errors.append(f"{issue}: {count} registro(s)")
    if snapshot["audit"].get("registros_divergentes_do_lote", 0):
        errors.append("Registros incompatíveis com seus lotes de importacao")
    if snapshot["sources"].get("aposentados", {}).get("registros", 0) > 0:
        with_uf = (snapshot["sources"]["aposentados"]["registros"] -
                   snapshot["sources"]["aposentados"]["sem_uf"])
        if with_uf:
            warnings.append("Aposentados com UF preenchida: conferir a origem do campo")

    for source in sorted(REQUIRED_SOURCES):
        total = snapshot["sources"].get(source, {}).get("registros", 0)
        if not total:
            pending.append(f"Sem registros da fonte {source}")
        elif not snapshot["batches"].get(source, {}).get("concluido", 0):
            pending.append(f"Sem lote concluido para {source}")
    if snapshot["audit"].get("registros_sem_lote", 0):
        warnings.append("Existem registros sem vinculo de lote (legado ou carga manual)")
    if snapshot["audit"].get("lotes_com_falha", 0):
        warnings.append("Existem lotes com falha; verificar se foram reimportados")

    file_hashes = file_hashes or {}
    for source, digest in sorted(file_hashes.items()):
        if digest not in snapshot["provenance"].get(source, set()):
            pending.append(f"Checksum do arquivo {source} nao consta em lote concluido")

    status = "reprovado" if errors else "pendente" if pending else "aprovado"
    return {
        "status": status,
        "erros": errors,
        "pendencias": pending,
        "avisos": warnings,
        "registros_por_fonte": {
            source: data["registros"] for source, data in sorted(snapshot["sources"].items())
        },
        "lotes_concluidos_por_fonte": {
            source: snapshot["batches"].get(source, {}).get("concluido", 0)
            for source in sorted(REQUIRED_SOURCES)
        },
        "arquivos_conferidos": sorted(file_hashes),
    }
