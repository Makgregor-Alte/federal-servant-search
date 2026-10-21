"""Importa amostras controladas de arquivos oficiais no PostgreSQL."""

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

try:
    from .integrity import assert_rows_consistent
    from .normalize import iter_normalized, parse_reference_month
    from .source_catalog import SOURCES
except ImportError:
    from integrity import assert_rows_consistent
    from normalize import iter_normalized, parse_reference_month
    from source_catalog import SOURCES

SAMPLE_SIZES = (100, 1000, 10000)


@dataclass(frozen=True)
class Sample:
    source: str
    filename: str
    checksum: str
    competence: str | None
    read: int
    rejected: int
    issues: dict[str, int]
    rows: tuple[tuple, ...]

    def report(self):
        return {
            "fonte": self.source,
            "competencia": self.competence,
            "linhas_lidas": self.read,
            "aceitas": len(self.rows),
            "rejeitadas": self.rejected,
            "ocorrencias": self.issues,
        }


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_sample(path: Path, source: str, *, max_rows: int = 100,
                competence: str | None = None, encoding: str | None = None,
                delimiter: str | None = None) -> Sample:
    """Prepara registros em memória limitada, sem gravar dados no banco."""
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida")
    if max_rows not in SAMPLE_SIZES:
        raise ValueError("A amostra deve conter 100, 1000 ou 10000 linhas")
    if competence is not None:
        competence = parse_reference_month(competence)
        if competence is None:
            raise ValueError("Competencia invalida")

    checksum = file_checksum(path)
    read = rejected = 0
    issues = Counter()
    prepared = []
    observed_months = set()
    for item in iter_normalized(path, source, encoding=encoding,
                                delimiter=delimiter, max_rows=max_rows):
        read += 1
        issues.update(item.issues)
        if "competencia_invalida" in item.issues:
            raise ValueError("Competencia invalida no arquivo")
        if item.record is None:
            rejected += 1
            continue
        row = item.record
        month = row["competencia"]
        if month is not None:
            observed_months.add(month)
            if competence is not None and month != competence:
                raise ValueError("Competencia declarada diverge do arquivo")
        # Chave provisória estável para a mesma linha do mesmo arquivo.
        origin = hashlib.sha256(
            f"{source}\x00{checksum}\x00{item.line_number}".encode("utf-8")
        ).hexdigest()
        prepared.append((row["nome"], row["cargo"], row["orgao"],
                         row["uf"], source, origin, month or competence))

    if len(observed_months) > 1:
        raise ValueError("A amostra contem multiplas competencias")
    batch_month = competence or next(iter(observed_months), None)
    rows = tuple((*row[:6], row[6] or batch_month) for row in prepared)
    return Sample(source, path.name, checksum, batch_month, read, rejected,
                  dict(sorted(issues.items())), rows)


def import_sample(connection, sample: Sample, *, batch_size: int = 500) -> dict:
    """Grava a amostra atomicamente; repetições da mesma linha não duplicam registros."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size deve estar entre 1 e 1000")
    if not sample.rows:
        raise ValueError("A amostra nao possui registros validos")
    inserted = 0
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO lotes_importacao
                       (fonte, nome_arquivo, competencia, sha256)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                (sample.source, sample.filename, sample.competence, sample.checksum),
            )
            batch_id = cursor.fetchone()[0]
            statement = """
                INSERT INTO servidores
                    (nome, cargo, orgao, uf, fonte, id_origem, competencia, lote_importacao_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (fonte, id_origem) DO NOTHING
            """
            for offset in range(0, len(sample.rows), batch_size):
                batch = sample.rows[offset:offset + batch_size]
                assert_rows_consistent(cursor, batch)
                cursor.executemany(statement, [(*row, batch_id) for row in batch])
                inserted += cursor.rowcount
            ignored = len(sample.rows) - inserted
            cursor.execute(
                """UPDATE lotes_importacao SET estado = 'concluido',
                       concluido_em = clock_timestamp(),
                       linhas_lidas = %s, linhas_importadas = %s,
                       linhas_descartadas = %s
                   WHERE id = %s""",
                (sample.read, inserted, sample.rejected + ignored, batch_id),
            )
    return {
        **sample.report(),
        "importadas": inserted,
        "ja_existentes": ignored,
        "lote_id": batch_id,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Carga experimental de dados oficiais")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--max-rows", type=int, choices=SAMPLE_SIZES, default=100)
    parser.add_argument("--competencia", help="Referencia declarada: AAAA-MM")
    parser.add_argument("--encoding")
    parser.add_argument("--delimiter")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--apply", action="store_true", help="Confirma a carga no PostgreSQL")
    args = parser.parse_args(argv)

    try:
        sample = make_sample(args.file, args.source, max_rows=args.max_rows,
                             competence=args.competencia, encoding=args.encoding,
                             delimiter=args.delimiter)
        if args.apply:
            if not os.getenv("DATABASE_URL") and not os.getenv("PGHOST"):
                raise ValueError("Conexao com PostgreSQL nao configurada")
            import psycopg
            with psycopg.connect(os.getenv("DATABASE_URL") or "", connect_timeout=5) as connection:
                report = import_sample(connection, sample, batch_size=args.batch_size)
            report["modo"] = "importacao"
        else:
            report = sample.report()
            report["modo"] = "validacao"
    except Exception as error:
        # Mensagens do driver podem conter dados de conexão ou da linha: nunca exibi-las.
        print(f"Carga nao concluida ({type(error).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
