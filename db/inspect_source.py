"""Inspeciona cabeçalhos e formato de um dataset local sem divulgar registros."""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    from .csv_limits import (MAX_RECORD_FIELD, MAX_RECORD_LINES,
                             configure_csv_field_limit)
    from .source_catalog import SOURCES, map_headers
except ImportError:
    from csv_limits import (MAX_RECORD_FIELD, MAX_RECORD_LINES,
                            configure_csv_field_limit)
    from source_catalog import SOURCES, map_headers


# Alguns TXT de Carreiras iniciam com a competência antes do cabeçalho tabular.
CAREER_PREAMBLE = re.compile(r"^CARREIRA[._ -](0[1-9]|1[0-2])(20\d{2})$", re.IGNORECASE)


def read_header(reader, source: str):
    """Lê o cabeçalho e, se existir, a competência explícita do preâmbulo."""
    try:
        header = next(reader)
    except StopIteration as error:
        raise ValueError("Arquivo sem cabeçalho") from error
    context = None
    if source == "carreiras" and len(header) == 1:
        marker = CAREER_PREAMBLE.fullmatch(header[0].lstrip("\ufeff").strip())
        if marker:
            month, year = marker.groups()
            context = f"{year}-{month}-01"
            try:
                header = next(reader)
            except StopIteration as error:
                raise ValueError("Arquivo de Carreiras sem cabeçalho") from error
    header = [column.lstrip("\ufeff").strip() for column in header]
    terminal_empty = bool(header and header[-1] == "")
    if terminal_empty:
        header = header[:-1]
    if len(header) < 2:
        raise ValueError("Cabeçalho sem campos suficientes; revise o separador")
    return header, context, terminal_empty


def strip_terminal_column(values: list[str], terminal_empty: bool) -> list[str]:
    """Remove só o campo vazio provocado pelo separador final do cabeçalho."""
    if not terminal_empty:
        return values
    if not values or values[-1].strip():
        return values  # a checagem de largura sinalizará a linha inválida
    return values[:-1]


def detect_format(path: Path, encoding: str | None = None, delimiter: str | None = None):
    if path.suffix.lower() not in {".csv", ".txt"}:
        raise ValueError("Arquivo deve ser CSV ou TXT; extraia arquivos ZIP antes de inspecionar")
    with path.open("rb") as handle:
        sample = handle.read(65536)
    if not sample:
        raise ValueError("Arquivo vazio")
    if encoding is None:
        for candidate in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                decoded = sample.decode(candidate)
                encoding = candidate
                break
            except UnicodeDecodeError:
                if candidate == "utf-8-sig":
                    try:
                        decoded = sample[:-4].decode(candidate)
                        encoding = candidate
                        break
                    except UnicodeDecodeError:
                        pass
    else:
        decoded = sample.decode(encoding)
    if delimiter is None:
        sniff_sample = decoded
        first, separator, remainder = decoded.partition("\n")
        if separator and CAREER_PREAMBLE.fullmatch(first.lstrip("\ufeff").strip()):
            sniff_sample = remainder
        try:
            dialect = csv.Sniffer().sniff(sniff_sample, delimiters=";,\t|")
            delimiter = dialect.delimiter
        except csv.Error as error:
            first_line = sniff_sample.splitlines()[0] if sniff_sample.splitlines() else ""
            counts = {sep: len(next(csv.reader([first_line], delimiter=sep))) for sep in ";,\t|"}
            delimiter = max(counts, key=counts.get)
            if counts[delimiter] < 2:
                raise ValueError("Separador não identificado; informe --delimiter") from error
    if len(delimiter) != 1 or delimiter not in ";,\t|":
        raise ValueError("Separador deve ser ; , TAB ou |")
    return encoding, delimiter


def inspect(path: Path, source: str, *, encoding: str | None = None,
            delimiter: str | None = None, sample_rows: int = 100) -> dict:
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida")
    if not 0 <= sample_rows <= 10000:
        raise ValueError("Amostra deve ficar entre 0 e 10000 linhas")
    if not path.is_file():
        raise ValueError("Arquivo não encontrado")
    encoding, delimiter = detect_format(path, encoding, delimiter)
    configure_csv_field_limit()
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        header, context, terminal_empty = read_header(reader, source)
        mapping = map_headers(header, source)
        checked = 0
        malformed = 0
        previous_line = reader.line_num
        while checked < sample_rows:
            try:
                row = next(reader)
            except StopIteration:
                break
            checked += 1
            span = reader.line_num - previous_line
            previous_line = reader.line_num
            row = strip_terminal_column(row, terminal_empty)
            if (len(row) != len(header) or span > MAX_RECORD_LINES
                    or any(len(field) > MAX_RECORD_FIELD for field in row)):
                malformed += 1
    return {
        "source": source,
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "encoding": encoding,
        "delimiter": "\\t" if delimiter == "\t" else delimiter,
        "total_columns": len(header),
        "columns": header,
        "competencia_cabecalho": context,
        "sample_rows_checked": checked,
        "sample_rows_with_wrong_width": malformed,
        **mapping,
        "ready_for_mapping": mapping["ready_for_mapping"] and malformed == 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico de layout de dados oficiais (sem importar registros)")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--encoding", help="Ex.: utf-8-sig ou cp1252; padrão: detectar")
    parser.add_argument("--delimiter", help="Separador de campos; padrão: detectar")
    parser.add_argument("--sample-rows", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        report = inspect(args.file, args.source, encoding=args.encoding,
                         delimiter=args.delimiter, sample_rows=args.sample_rows)
    except (ValueError, UnicodeError, csv.Error, OSError, LookupError) as error:
        print(f"Erro ao inspecionar arquivo: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ready_for_mapping"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
