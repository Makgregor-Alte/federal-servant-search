"""Prepara linhas das fontes oficiais para carga posterior no PostgreSQL."""

import argparse
import csv
import json
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

try:
    from .csv_limits import (MAX_RECORD_FIELD, MAX_RECORD_LINES,
                             MAX_PHYSICAL_LINE, configure_csv_field_limit)
    from .inspect_source import detect_format, read_header, strip_terminal_column
    from .source_catalog import SOURCES, map_headers
except ImportError:
    from csv_limits import (MAX_RECORD_FIELD, MAX_RECORD_LINES,
                            MAX_PHYSICAL_LINE, configure_csv_field_limit)
    from inspect_source import detect_format, read_header, strip_terminal_column
    from source_catalog import SOURCES, map_headers


VALID_UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)


class CSVReadFailure(ValueError):
    """Erro de leitura localizado sem incluir valores pessoais do arquivo."""


@dataclass(frozen=True)
class NormalizedRow:
    line_number: int
    record: dict | None
    issues: tuple[str, ...]
    discarded_physical_lines: int = 0


def clean_text(value: str | None) -> str:
    """Preserva letras, maiúsculas e acentos; remove espaços e controles redundantes."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFC", str(value))
    normalized = "".join(
        " " if unicodedata.category(char) in {"Cc", "Cf"} else char
        for char in normalized
    )
    return " ".join(normalized.split())


def clean_uf(value: str | None) -> str | None:
    uf = clean_text(value).upper()
    return uf if uf in VALID_UFS else None


def parse_reference_month(value: str | None) -> str | None:
    """Aceita somente competências explícitas; não deduz datas desconhecidas."""
    value = clean_text(value)
    if not value:
        return None
    parts = None
    if len(value) == 6 and value.isascii() and value.isdigit():
        parts = (value[:4], value[4:])
    elif len(value) == 7 and value[4] == "-":
        parts = (value[:4], value[5:])
    elif len(value) == 7 and value[2] == "/":
        parts = (value[3:], value[:2])
    elif len(value) == 10 and value[4:5] == "-" and value[-3:] == "-01":
        parts = (value[:4], value[5:7])
    elif len(value) == 10 and value[2:3] == "/" and value[:3] == "01/":
        parts = (value[6:], value[3:5])
    if parts is None or not all(part.isascii() and part.isdigit() for part in parts):
        return None
    try:
        return date(int(parts[0]), int(parts[1]), 1).isoformat()
    except ValueError:
        return None


def normalize_row(raw: dict[str, str], mapping: dict[str, str], source: str,
                  line_number: int = 0, *,
                  competencia_cabecalho: str | None = None) -> NormalizedRow:
    """Projeta somente campos necessários para pesquisa, sem CPF ou matrícula."""
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida")

    def get(field: str) -> str:
        return clean_text(raw.get(mapping[field])) if field in mapping else ""

    name = get("nome")
    if not name:
        return NormalizedRow(line_number, None, ("nome_ausente",))

    issues = []
    cargo = get("cargo")
    orgao = get("orgao")
    if not cargo:
        issues.append("cargo_ausente")
    if not orgao:
        issues.append("orgao_ausente")

    uf_original = get("uf")
    uf = clean_uf(uf_original)
    if source == "carreiras":
        if not uf_original:
            issues.append("uf_ausente")
        elif uf is None:
            issues.append("uf_invalida")

    competencia_original = get("mes_referencia")
    competencia = parse_reference_month(competencia_original)
    if competencia_original and not competencia:
        # Na fonte Carreiras o campo mensal pode ter apenas MM. O ano
        # deve estar expresso no preâmbulo CARREIRA.MMYYYY, nunca inferido.
        if (competencia_cabecalho and len(competencia_original) == 2
                and competencia_original.isascii() and competencia_original.isdigit()
                and competencia_original == competencia_cabecalho[5:7]):
            competencia = competencia_cabecalho
        else:
            issues.append("competencia_invalida")
    elif competencia_cabecalho and competencia and competencia != competencia_cabecalho:
        issues.append("competencia_invalida")
    elif not competencia_original and competencia_cabecalho:
        competencia = competencia_cabecalho

    record = {
        "nome": name,
        "cargo": cargo,
        "orgao": orgao,
        "uf": uf,
        "fonte": source,
        "competencia": competencia,
    }
    return NormalizedRow(line_number, record, tuple(issues))


class _OversizedPhysicalLine(Exception):
    pass


class _RecordLines:
    """Fornece ao parser somente as linhas fisicas de um registro limitado."""

    def __init__(self, stream):
        self.stream = stream
        self.count = 0
        self.limit_reached = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.count >= MAX_RECORD_LINES:
            self.limit_reached = True
            raise StopIteration
        line = self.stream.readline(MAX_PHYSICAL_LINE + 1)
        if not line:
            raise StopIteration
        self.count += 1
        if len(line) > MAX_PHYSICAL_LINE and not line.endswith(("\n", "\r")):
            # Descarta o restante da mesma linha fisica, com memoria limitada.
            while True:
                fragment = self.stream.readline(MAX_PHYSICAL_LINE + 1)
                if not fragment or fragment.endswith(("\n", "\r")):
                    break
            raise _OversizedPhysicalLine
        return line


def _resynchronize(stream, header, delimiter, name_column):
    """Procura a proxima linha que seja um registro isolado de largura valida.

    A linha de recuperacao e devolvida ao chamador, sem registrar seu conteudo.
    Descarta fragmentos apos aspas nao terminadas, sem engolir todo o arquivo.
    """
    discarded = 0
    while True:
        piece = stream.readline(MAX_PHYSICAL_LINE + 1)
        if not piece:
            return None, discarded
        discarded += 1
        if len(piece) > MAX_PHYSICAL_LINE and not piece.endswith(("\n", "\r")):
            while True:
                extra = stream.readline(MAX_PHYSICAL_LINE + 1)
                if not extra or extra.endswith(("\n", "\r")):
                    break
            continue
        try:
            parsed = next(csv.reader([piece], delimiter=delimiter, strict=True))
        except (csv.Error, StopIteration):
            continue
        if (len(parsed) == len(header) and parsed[name_column].strip()
                and all(len(field) <= MAX_RECORD_FIELD for field in parsed)):
            return piece, discarded - 1


def iter_normalized(path: Path, source: str, *, encoding: str | None = None,
                    delimiter: str | None = None, max_rows: int | None = None
                    ) -> Iterator[NormalizedRow]:
    """Processa o CSV em streaming e se recupera de registros malformados."""
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida")
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows deve ser positivo")
    if not path.is_file():
        raise ValueError("Arquivo não encontrado")

    encoding, delimiter = detect_format(path, encoding, delimiter)
    configure_csv_field_limit()
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        header, context, terminal_empty = read_header(reader, source)
        diagnostic = map_headers(header, source)
        if not diagnostic["ready_for_mapping"]:
            raise ValueError(
                "Layout incompatível: campos obrigatórios ausentes, ambíguos ou duplicados"
            )
        name_column = header.index(diagnostic["mapped"]["nome"])
        line_number = reader.line_num
        pending_line = None
        index = 0
        while max_rows is None or index < max_rows:
            record_start = line_number + 1
            window = _RecordLines(handle)
            recovered = pending_line is not None
            first_line = pending_line
            pending_line = None
            issue = None
            try:
                if recovered:
                    def input_lines():
                        yield first_line
                        yield from window
                    values = next(csv.reader(input_lines(), delimiter=delimiter, strict=True))
                else:
                    values = next(csv.reader(window, delimiter=delimiter, strict=True))
            except StopIteration:
                if window.count == 0 and not recovered:
                    break
                issue = "erro_csv"
            except _OversizedPhysicalLine:
                issue = "linha_fisica_excessiva"
            except csv.Error:
                issue = ("registro_multilinha_excessivo" if window.limit_reached
                         else "erro_csv")

            consumed = window.count + int(recovered)
            line_number += consumed
            if issue is not None:
                discarded = consumed
                if issue in {"registro_multilinha_excessivo", "erro_csv"}:
                    pending_line, skipped = _resynchronize(
                        handle, header, delimiter, name_column)
                    line_number += skipped
                    discarded += skipped
                index += 1
                yield NormalizedRow(record_start, None, (issue,), discarded)
                continue
            index += 1
            if any(len(value) > MAX_RECORD_FIELD for value in values):
                yield NormalizedRow(record_start, None, ("campo_excessivo",), consumed)
                continue
            values = strip_terminal_column(values, terminal_empty)
            if len(values) != len(header):
                yield NormalizedRow(record_start, None, ("quantidade_colunas_invalida",), consumed)
                continue
            yield normalize_row(dict(zip(header, values)), diagnostic["mapped"],
                                source, record_start,
                                competencia_cabecalho=context)


def analyze(path: Path, source: str, *, encoding: str | None = None,
            delimiter: str | None = None, max_rows: int = 1000) -> dict:
    if max_rows < 1:
        raise ValueError("max_rows deve ser positivo")
    issues = Counter()
    accepted = rejected = 0
    for item in iter_normalized(path, source, encoding=encoding,
                                delimiter=delimiter, max_rows=max_rows):
        if item.record is None:
            rejected += 1
        else:
            accepted += 1
        issues.update(item.issues)
    return {
        "fonte": source,
        "linhas_analisadas": accepted + rejected,
        "aceitas": accepted,
        "rejeitadas": rejected,
        "ocorrencias": dict(sorted(issues.items())),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Valida registros oficiais sem importar dados")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--encoding")
    parser.add_argument("--delimiter")
    parser.add_argument("--max-rows", type=int, default=1000)
    args = parser.parse_args(argv)
    try:
        summary = analyze(args.file, args.source, encoding=args.encoding,
                          delimiter=args.delimiter, max_rows=args.max_rows)
    except (ValueError, UnicodeError, csv.Error, OSError, LookupError) as error:
        if isinstance(error, CSVReadFailure):
            print(f"Erro: {error}", file=sys.stderr)
        else:
            print("Erro: arquivo, codificação ou layout inválido", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["rejeitadas"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
