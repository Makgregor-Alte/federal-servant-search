"""Stable search scenarios and response contracts for HTTP load tests."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchCase:
    label: str
    params: tuple[tuple[str, str], ...]


CASES = (
    SearchCase("exact", (("nome", "ANA"), ("page", "1"))),
    SearchCase("similar", (("similar", "ANA%SILVA%"), ("limit", "20"))),
    SearchCase("position", (("cargo", "ANALISTA"), ("page", "1"))),
    SearchCase("agency", (("orgao", "MINISTERIO"), ("page", "1"))),
    SearchCase("state", (("uf", "RS"), ("page", "1"))),
    SearchCase("combined", (("cargo", "ANALISTA"), ("uf", "RS"), ("page", "1"))),
)


def validate_search_response(status, payload, *, overload=False):
    """Return a stable classification or raise ValueError for malformed responses."""
    if not isinstance(payload, dict):
        raise ValueError("Resposta HTTP nao contem objeto JSON")
    if status == 429:
        if payload.get("error") != "rate_limited":
            raise ValueError("Limite de requisicoes sem contrato JSON esperado")
        if not overload:
            raise ValueError("HTTP 429 durante carga normal")
        return "limited"
    if status != 200:
        raise ValueError(f"Status HTTP inesperado: {status}")
    items = payload.get("items")
    pagination = payload.get("pagination")
    if not isinstance(items, list) or not isinstance(pagination, dict):
        raise ValueError("JSON sem items ou pagination")
    for field in ("page", "page_size", "total", "pages"):
        value = pagination.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Metadados de paginacao invalidos")
    if pagination["page"] != 1 or not 1 <= pagination["page_size"] <= 100:
        raise ValueError("Pagina ou tamanho inesperado")
    if len(items) > pagination["page_size"]:
        raise ValueError("Numero de registros maior que o limite solicitado")
    if pagination["total"] == 0 and items:
        raise ValueError("Contagem total inconsistente")
    if pagination["total"] > 0 and not items:
        raise ValueError("Pagina inicial sem registros apesar de total positivo")
    if pagination["pages"] != (pagination["total"] + pagination["page_size"] - 1) // pagination["page_size"]:
        raise ValueError("Numero de paginas inconsistente")
    return "ok"
