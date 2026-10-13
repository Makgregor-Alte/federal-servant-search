"""Validação e construção de consultas parametrizadas de servidores."""
from dataclasses import dataclass
from math import ceil

UF_VALIDAS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


@dataclass(frozen=True)
class SearchFilters:
    name: str = ""
    name_mode: str = "exact"
    position: str = ""
    agency: str = ""
    uf: str = ""
    page: int = 1
    page_size: int = 20


def parse_filters(args):
    """Recebe um Mapping semelhante a request.args (Flask)."""
    def text(key, *, max_len=150):
        value = str(args.get(key, "") or "").strip()
        if len(value) > max_len:
            raise ValueError(f"'{key}' excede {max_len} caracteres")
        return value

    def number(key, default, minimum, maximum):
        value = args.get(key, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"'{key}' deve ser um número inteiro") from None
        if not minimum <= parsed <= maximum:
            raise ValueError(f"'{key}' deve estar entre {minimum} e {maximum}")
        return parsed

    name = text("name")
    name_mode = text("name_mode", max_len=10).lower() or "exact"
    if name_mode not in ("exact", "similar"):
        raise ValueError("'name_mode' deve ser 'exact' ou 'similar'")
    uf = text("uf", max_len=2).upper()
    if uf and uf not in UF_VALIDAS:
        raise ValueError("'uf' deve ser uma sigla de estado válida")
    return SearchFilters(
        name=name,
        name_mode=name_mode,
        position=text("position"),
        agency=text("agency"),
        uf=uf,
        page=number("page", 1, 1, 1_000_000),
        page_size=number("page_size", 20, 1, 100),
    )


def like_contains(value):
    """Escapa curingas e barra invertida para pesquisa literal com ILIKE."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def build_search_queries(filters):
    """Gera SQL e parâmetros separados (nenhum texto do usuário é interpolado no SQL)."""
    where = []
    params = {}
    if filters.name:
        params["name"] = filters.name
        if filters.name_mode == "similar":
            # Índice GIN de pg_trgm suporta o operador % sobre LOWER(nome).
            where.append("LOWER(nome) %% LOWER(%(name)s)")
        else:
            where.append("LOWER(nome) = LOWER(%(name)s)")
    for field, column in (("position", "cargo"), ("agency", "orgao")):
        value = getattr(filters, field)
        if value:
            params[field] = like_contains(value)
            where.append(f"{column} ILIKE %({field})s ESCAPE '\\'")
    if filters.uf:
        params["uf"] = filters.uf
        where.append("uf = %(uf)s")
    expression = " WHERE " + " AND ".join(where) if where else ""
    base = " FROM servidores" + expression
    count_sql = "SELECT COUNT(*)" + base
    order = "ORDER BY nome, id"
    if filters.name and filters.name_mode == "similar":
        order = "ORDER BY similarity(LOWER(nome), LOWER(%(name)s)) DESC, nome, id"
    data_sql = (
        "SELECT id, nome, cargo, orgao, uf, fonte" + base + " " + order
        + " LIMIT %(limit)s OFFSET %(offset)s"
    )
    data_params = dict(params, limit=filters.page_size, offset=(filters.page - 1) * filters.page_size)
    return count_sql, data_sql, params, data_params


def pagination(total, filters):
    return {"page": filters.page, "page_size": filters.page_size,
            "total": total, "pages": ceil(total / filters.page_size)}
