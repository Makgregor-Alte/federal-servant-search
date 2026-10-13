"""Importa uma amostra CSV oficial sem pressupor o layout das colunas.

Execute --dry-run primeiro. Os dados só são gravados depois de validar o CSV.
Para conexão, use DATABASE_URL ou variáveis de ambiente PGHOST/PGUSER/PGPASSWORD/PGDATABASE.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

VALID_UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


def nonempty(value):
    return str(value or "").strip()


def record_from_row(row, args):
    def take(column):
        return nonempty(row.get(column)) if column else ""
    name = take(args.name_column)
    if not name:
        return None
    raw_uf = take(args.uf_column).upper()
    uf = raw_uf if raw_uf in VALID_UFS else None
    origin_id = take(args.id_column)
    if not origin_id:
        # Sem identificador oficial: hash determinístico da linha completa.
        origin_id = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return (name, take(args.position_column), take(args.agency_column), uf, args.source, origin_id)


def main():
    parser = argparse.ArgumentParser(description="Importar amostra de CSV no PostgreSQL")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", required=True, help="ex.: carreira ou aposentados")
    parser.add_argument("--name-column", required=True)
    parser.add_argument("--position-column")
    parser.add_argument("--agency-column")
    parser.add_argument("--uf-column")
    parser.add_argument("--id-column")
    parser.add_argument("--delimiter", default=";")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.source.strip():
        parser.error("--source não pode ser vazio")
    if not 1 <= args.limit <= 100_000:
        parser.error("--limit deve estar entre 1 e 100000")
    if len(args.delimiter) != 1:
        parser.error("--delimiter precisa ter um caractere")
    with args.file.open("r", encoding=args.encoding, newline="") as stream:
        reader = csv.DictReader(stream, delimiter=args.delimiter)
        available = set(reader.fieldnames or [])
        required = [args.name_column, args.position_column, args.agency_column, args.uf_column, args.id_column]
        missing = [c for c in required if c and c not in available]
        if missing:
            parser.error(f"Colunas inexistentes: {missing}. Disponíveis: {reader.fieldnames}")
        records = []
        for row in reader:
            record = record_from_row(row, args)
            if record:
                records.append(record)
            if len(records) >= args.limit:
                break
    print(f"Colunas detectadas: {sorted(available)}")
    print(f"Registros válidos na amostra: {len(records)} (fonte={args.source})")
    if args.dry_run:
        return 0
    if not records:
        print("Nenhum registro para importar", file=sys.stderr)
        return 1
    import psycopg
    url = os.environ.get("DATABASE_URL", "")
    if not url and not os.environ.get("PGHOST"):
        print("Configure DATABASE_URL ou PGHOST/PGUSER/PGPASSWORD/PGDATABASE", file=sys.stderr)
        return 2
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO servidores (nome, cargo, orgao, uf, fonte, id_origem)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (fonte, id_origem) DO UPDATE SET
                    nome = EXCLUDED.nome, cargo = EXCLUDED.cargo,
                    orgao = EXCLUDED.orgao, uf = EXCLUDED.uf, atualizado_em = now()
                """, records)
    print("Importação confirmada no PostgreSQL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
