"""Carrega arquivos oficiais em lotes limitados, com reexecução idempotente."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

try:
    from .integrity import assert_stage_consistent
    from .import_sample import file_checksum
    from .normalize import CSVReadFailure, iter_normalized, parse_reference_month
    from .source_catalog import SOURCES
except ImportError:
    from integrity import assert_stage_consistent
    from import_sample import file_checksum
    from normalize import CSVReadFailure, iter_normalized, parse_reference_month
    from source_catalog import SOURCES


INSERT_FROM_STAGE = """
    INSERT INTO servidores
        (nome, cargo, orgao, uf, fonte, id_origem, competencia, lote_importacao_id)
    SELECT nome, cargo, orgao, uf, fonte, id_origem, competencia, %s
      FROM pg_temp.importacao_servidores_stage
     WHERE TRUE
    ON CONFLICT (fonte, id_origem) DO NOTHING
"""

CREATE_STAGE = """
    CREATE TEMP TABLE IF NOT EXISTS importacao_servidores_stage (
        nome TEXT NOT NULL,
        cargo TEXT NOT NULL,
        orgao TEXT NOT NULL,
        uf TEXT,
        fonte TEXT NOT NULL,
        id_origem TEXT NOT NULL,
        competencia DATE
    ) ON COMMIT PRESERVE ROWS
"""

STRUCTURAL_ISSUES = frozenset({
    "campo_excessivo", "registro_multilinha_excessivo", "quantidade_colunas_invalida",
    "linha_fisica_excessiva", "erro_csv",
})

COPY_STAGE = """
    COPY pg_temp.importacao_servidores_stage
        (nome, cargo, orgao, uf, fonte, id_origem, competencia)
    FROM STDIN
"""


@dataclass
class BulkReport:
    fonte: str
    nome_arquivo: str
    sha256: str
    competencia: str | None
    linhas_lidas: int = 0
    aceitas: int = 0
    rejeitadas: int = 0
    importadas: int = 0
    ja_existentes: int = 0
    lotes_gravados: int = 0
    ocorrencias: Counter = field(default_factory=Counter)
    lote_id: int | None = None
    linhas_suspeitas: list[int] = field(default_factory=list)
    linhas_fisicas_descartadas: int = 0
    erros_estruturais: int = 0

    def to_dict(self, mode: str) -> dict:
        result = {
            "modo": mode,
            "fonte": self.fonte,
            "arquivo": self.nome_arquivo,
            "sha256": self.sha256,
            "competencia": self.competencia,
            "linhas_lidas": self.linhas_lidas,
            "aceitas": self.aceitas,
            "rejeitadas": self.rejeitadas,
            "ocorrencias": dict(sorted(self.ocorrencias.items())),
            "linhas_suspeitas": self.linhas_suspeitas,
            "linhas_fisicas_descartadas": self.linhas_fisicas_descartadas,
            "erros_estruturais": self.erros_estruturais,
        }
        if mode == "importacao":
            result.update({
                "importadas": self.importadas,
                "ja_existentes": self.ja_existentes,
                "lotes_gravados": self.lotes_gravados,
                "lote_id": self.lote_id,
            })
        return result


def _validate_options(path: Path, source: str, batch_size: int,
                      competence: str | None, max_rows: int | None) -> str | None:
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida")
    if not 1 <= batch_size <= 10000:
        raise ValueError("batch_size deve estar entre 1 e 10000")
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows deve ser positivo")
    if not path.is_file():
        raise ValueError("Arquivo não encontrado")
    if competence is not None:
        parsed = parse_reference_month(competence)
        if parsed is None:
            raise ValueError("Competencia invalida")
        return parsed
    return None


def stream_file(path: Path, source: str, report: BulkReport, *,
                batch_size: int, competence: str | None,
                encoding: str | None = None, delimiter: str | None = None,
                max_rows: int | None = None, on_batch=None) -> BulkReport:
    """Percorre o arquivo uma vez; retém no máximo batch_size registros."""
    pending = []
    observed_month = None
    for item in iter_normalized(path, source, encoding=encoding,
                                delimiter=delimiter, max_rows=max_rows):
        report.linhas_lidas += 1
        report.ocorrencias.update(item.issues)
        if STRUCTURAL_ISSUES.intersection(item.issues):
            report.erros_estruturais += 1
            report.linhas_fisicas_descartadas += item.discarded_physical_lines
            if len(report.linhas_suspeitas) < 10:
                report.linhas_suspeitas.append(item.line_number)
        if "competencia_invalida" in item.issues:
            raise ValueError("Competencia invalida no arquivo")
        if item.record is None:
            report.rejeitadas += 1
            continue

        row = item.record
        month = row["competencia"]
        if month is not None:
            if competence is not None and month != competence:
                raise ValueError("Competencia declarada diverge dos registros")
            if observed_month is not None and month != observed_month:
                raise ValueError("Mais de uma competencia no mesmo arquivo")
            observed_month = month
        effective_month = month or competence
        origin = hashlib.sha256(
            f"{source}\x00{report.sha256}\x00{item.line_number}".encode("utf-8")
        ).hexdigest()
        pending.append((row["nome"], row["cargo"], row["orgao"], row["uf"],
                        source, origin, effective_month))
        report.aceitas += 1
        report.competencia = competence or observed_month
        if len(pending) >= batch_size:
            if on_batch is not None:
                inserted = on_batch(tuple(pending), report)
                report.importadas += inserted
                report.ja_existentes += len(pending) - inserted
                report.lotes_gravados += 1
            pending.clear()

    if pending and on_batch is not None:
        inserted = on_batch(tuple(pending), report)
        report.importadas += inserted
        report.ja_existentes += len(pending) - inserted
        report.lotes_gravados += 1
    report.competencia = competence or observed_month
    return report


def resolve_competence(path: Path, source: str, *, competence: str | None,
                       encoding: str | None = None, delimiter: str | None = None,
                       max_rows: int | None = None,
                       max_structural_errors: int = 0) -> str | None:
    """Valida a competência do recorte antes de persistir os lotes."""
    observed = None
    structural_errors = 0
    for item in iter_normalized(path, source, encoding=encoding,
                                delimiter=delimiter, max_rows=max_rows):
        if "competencia_invalida" in item.issues:
            raise ValueError("Competencia invalida no arquivo")
        if STRUCTURAL_ISSUES.intersection(item.issues):
            structural_errors += 1
            if structural_errors > max_structural_errors:
                raise CSVReadFailure(
                    f"Registro estruturalmente suspeito na linha fisica {item.line_number}; "
                    f"{structural_errors} ocorrencia(s) excedem o limite autorizado "
                    f"de {max_structural_errors}"
                )
        if item.record is None:
            continue
        month = item.record["competencia"]
        if month is None:
            continue
        if competence is not None and month != competence:
            raise ValueError("Competencia declarada diverge dos registros")
        if observed is not None and month != observed:
            raise ValueError("Mais de uma competencia no mesmo arquivo")
        observed = month
    return competence or observed


def _save_progress(connection, report: BulkReport, *, state: str | None = None):
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE lotes_importacao SET
                        competencia = %s,
                        linhas_lidas = %s,
                        linhas_importadas = %s,
                        linhas_descartadas = %s,
                        estado = COALESCE(%s::text, estado),
                        concluido_em = CASE WHEN %s::text IS NOT NULL
                            THEN clock_timestamp() ELSE concluido_em END
                   WHERE id = %s""",
                (report.competencia, report.linhas_lidas, report.importadas,
                 report.rejeitadas + report.ja_existentes,
                 state, state, report.lote_id),
            )


def _write_batch(connection, batch: tuple, report: BulkReport) -> int:
    """COPY para tabela temporária e INSERT idempotente na mesma transação."""
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE pg_temp.importacao_servidores_stage")
            with cursor.copy(COPY_STAGE) as copy:
                for record in batch:
                    copy.write_row(record)
            assert_stage_consistent(cursor)
            cursor.execute(INSERT_FROM_STAGE, (report.lote_id,))
            inserted = cursor.rowcount
            if not 0 <= inserted <= len(batch):
                raise RuntimeError("Contagem inesperada na importacao")
            cursor.execute(
                """UPDATE lotes_importacao SET
                        competencia = %s, linhas_lidas = %s,
                        linhas_importadas = %s, linhas_descartadas = %s
                   WHERE id = %s""",
                (report.competencia, report.linhas_lidas,
                 report.importadas + inserted,
                 report.rejeitadas + report.ja_existentes + len(batch) - inserted,
                 report.lote_id),
            )
    return inserted


def run_bulk(path: Path, source: str, *, batch_size: int = 1000,
             competence: str | None = None, encoding: str | None = None,
             delimiter: str | None = None, max_rows: int | None = None,
             connection=None, max_structural_errors: int = 0) -> dict:
    """Valida sem gravar ou importa em transações por lote com reexecução segura.

    Para importação, a conexão deve estar em autocommit e sem transação externa.
    Uma falha preserva os lotes anteriores, que serão ignorados na próxima carga.
    """
    if not 0 <= max_structural_errors <= 100000:
        raise ValueError("max_structural_errors deve ficar entre 0 e 100000")
    path = Path(path)
    competence = _validate_options(path, source, batch_size, competence, max_rows)
    original_stat = (path.stat().st_size, path.stat().st_mtime_ns)
    checksum = file_checksum(path)
    report = BulkReport(source, path.name, checksum, competence)
    if connection is None:
        stream_file(path, source, report, batch_size=batch_size,
                    competence=competence, encoding=encoding,
                    delimiter=delimiter, max_rows=max_rows)
        if original_stat != (path.stat().st_size, path.stat().st_mtime_ns):
            raise ValueError("Arquivo modificado durante a leitura")
        return report.to_dict("validacao")

    if not connection.autocommit:
        raise ValueError("A conexao deve usar autocommit=True")

    competence = resolve_competence(
        path, source, competence=competence, encoding=encoding,
        delimiter=delimiter, max_rows=max_rows,
        max_structural_errors=max_structural_errors,
    )
    if original_stat != (path.stat().st_size, path.stat().st_mtime_ns):
        raise ValueError("Arquivo modificado durante a leitura")
    report.competencia = competence

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(CREATE_STAGE)
            cursor.execute(
                """INSERT INTO lotes_importacao
                    (fonte, nome_arquivo, competencia, sha256)
                    VALUES (%s, %s, %s, %s) RETURNING id""",
                (source, path.name, competence, checksum),
            )
            report.lote_id = cursor.fetchone()[0]

    try:
        stream_file(path, source, report, batch_size=batch_size,
                    competence=competence, encoding=encoding,
                    delimiter=delimiter, max_rows=max_rows,
                    on_batch=lambda rows, state: _write_batch(connection, rows, state))
        if original_stat != (path.stat().st_size, path.stat().st_mtime_ns):
            raise ValueError("Arquivo modificado durante a leitura")
        _save_progress(connection, report, state="concluido")
    except BaseException:
        try:
            _save_progress(connection, report, state="falhou")
        except Exception:
            pass
        raise
    return report.to_dict("importacao")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Importacao incremental de arquivos oficiais")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--competencia", help="Competencia declarada: AAAA-MM")
    parser.add_argument("--encoding")
    parser.add_argument("--delimiter")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-structural-errors", type=int, default=0,
                        help="Numero maximo de erros estruturais autorizados na importacao; padrao 0")
    args = parser.parse_args(argv)
    try:
        if args.apply:
            if not os.getenv("DATABASE_URL") and not os.getenv("PGHOST"):
                raise ValueError("Conexao com PostgreSQL nao configurada")
            import psycopg
            with psycopg.connect(os.getenv("DATABASE_URL") or "",
                                 autocommit=True, connect_timeout=5) as conn:
                result = run_bulk(args.file, args.source, batch_size=args.batch_size,
                                  max_rows=args.max_rows, competence=args.competencia,
                                  encoding=args.encoding, delimiter=args.delimiter,
                                  connection=conn, max_structural_errors=args.max_structural_errors)
        else:
            result = run_bulk(args.file, args.source, batch_size=args.batch_size,
                              max_rows=args.max_rows, competence=args.competencia,
                              encoding=args.encoding, delimiter=args.delimiter,
                              max_structural_errors=args.max_structural_errors)
    except CSVReadFailure as error:
        print(f"Carga nao concluida: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Carga nao concluida ({type(error).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
