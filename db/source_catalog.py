"""Dicionários de colunas dos dois conjuntos oficiais de gestão de pessoas."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDefinition:
    code: str
    title: str
    dictionary_url: str
    dataset_url: str
    fields: dict[str, tuple[str, ...]]
    required_fields: frozenset[str]
    unavailable_fields: frozenset[str]


def normalized_header(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value).strip().lstrip("\ufeff"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.casefold())


SOURCES = {
    "aposentados": SourceDefinition(
        code="aposentados",
        title="Gestão de Pessoas do Executivo Federal — Aposentados",
        dictionary_url="https://repositorio.dados.gov.br/segrt/1.20180829-DadosRecursos-Aposentados.pdf",
        dataset_url="https://dados.gov.br/dados/conjuntos-dados/gestao-de-pessoas-executivo-federal--aposentados",
        fields={
            "nome": ("Nome", "Nome do aposentado"),
            "cpf": ("CPF",),
            "matricula": ("Matrícula do Servidor", "Matricula do Servidor"),
            "orgao": ("Nome do órgão", "Nome do orgao", "Orgao", "Órgão"),
            "sigla_orgao": ("Sigla do órgão", "Sigla do orgao", "Sigla Orgao", "Sigla Órgão"),
            "codigo_orgao_superior": ("Código do órgão superior",),
            "cargo": ("Cargo", "Cargo emprego", "Cargo/Emprego"),
            "classe": ("Classe",),
            "padrao": ("Padrão",),
            "referencia": ("Referência",),
            "nivel": ("Nível",),
            "tipo_aposentadoria": ("Tipo de Aposentadoria",),
            "fundamentacao_inatividade": ("Fundamentação da inatividade",),
            "nome_diploma_legal": ("Nome Diploma Legal",),
            "data_publicacao_diploma": ("Data publicação do Diploma Legal",),
            "ocorrencia_ingresso": ("Ocorrência de ingresso no serviço público",),
            "data_ingresso": ("Data de ocorrência de ingresso no serviço público",),
            "rendimento_liquido": ("Valor do Rendimento Líquido",),
        },
        required_fields=frozenset({"nome", "cargo", "orgao"}),
        unavailable_fields=frozenset({"uf"}),
    ),
    "carreiras": SourceDefinition(
        code="carreiras",
        title="Gestão de Pessoas do Executivo Federal — Carreiras/Cargos",
        dictionary_url="https://repositorio.dados.gov.br/segrt/2.20190709-DadosRecursos-Carreiras.pdf",
        dataset_url="https://dados.gov.br/dados/conjuntos-dados/gestao-de-pessoas-executivo-federal---carreiras--cargos",
        fields={
            "nome": ("Nome", "Nome do servidor/empregado público"),
            "cpf": ("CPF",),
            "codigo_carreira": ("Código da Carreira",),
            "cargo": ("Descrição do Cargo/Emprego", "Descricao do Cargo/Emprego"),
            "uf": ("UF da UPAG de vinculação", "UF da UPAG de vinculacao"),
            "orgao": ("Denominação do Órgão de atuação", "Denominacao do Orgao de atuacao"),
            "mes_referencia": ("Mês de referência", "Mes de referencia"),
            "remuneracao": ("Valor da Remunração", "Valor da Remuneração"),
        },
        required_fields=frozenset({"nome", "cargo", "orgao", "uf"}),
        unavailable_fields=frozenset(),
    ),
}


def map_headers(headers: list[str], source: str) -> dict:
    """Identifica correspondências explícitas sem adivinhar colunas desconhecidas."""
    if source not in SOURCES:
        raise ValueError("Fonte desconhecida")
    spec = SOURCES[source]
    normalized = {}
    for column in headers:
        key = normalized_header(column)
        if not key:
            raise ValueError("Cabeçalho contém coluna vazia")
        normalized.setdefault(key, []).append(column)
    duplicates = sorted({col for values in normalized.values() if len(values) > 1 for col in values})

    mapped = {}
    ambiguous = {}
    for field, labels in spec.fields.items():
        keys = {normalized_header(label) for label in labels}
        candidates = [col for key in keys for col in normalized.get(key, [])]
        if len(candidates) == 1:
            mapped[field] = candidates[0]
        elif len(candidates) > 1:
            ambiguous[field] = sorted(candidates)

    unmapped = sorted(col for col in headers if col not in mapped.values())
    missing = sorted(spec.required_fields - mapped.keys())
    return {
        "source": source,
        "mapped": mapped,
        "missing_required": missing,
        "ambiguous": ambiguous,
        "duplicate_headers": duplicates,
        "unmapped_headers": unmapped,
        "unavailable_in_source": sorted(spec.unavailable_fields),
        "ready_for_mapping": not missing and not ambiguous and not duplicates,
    }
