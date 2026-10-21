"""Limites de leitura das fontes CSV/TXT usadas nas importações."""

import csv

# O limite de 128 KiB do módulo csv e insuficiente para detectar registros
# anormais em arquivos oficiais extensos. O teto maior permite classificar
# esses registros sem gravar campos gigantes ou consumir memória sem limite.
MAX_PARSER_FIELD = 8 * 1024 * 1024
MAX_RECORD_FIELD = 16 * 1024
MAX_RECORD_LINES = 16
MAX_PHYSICAL_LINE = 256 * 1024


def configure_csv_field_limit() -> None:
    if csv.field_size_limit() < MAX_PARSER_FIELD:
        csv.field_size_limit(MAX_PARSER_FIELD)
