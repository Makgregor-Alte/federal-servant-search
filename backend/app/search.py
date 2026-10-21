"""Parâmetros de pesquisa validados e consultas SQL parametrizadas."""
from dataclasses import dataclass
from math import ceil
from unicodedata import category, normalize

UF_VALIDAS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
ALLOWED_PARAMETERS = frozenset({
    "name", "nome", "similar", "name_mode", "position", "cargo",
    "agency", "orgao", "uf", "page", "pagina", "page_size", "limit",
})


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
    """Normaliza aliases e rejeita parâmetros ambíguos."""
    unknown = set(args.keys()) - ALLOWED_PARAMETERS
    if unknown:
        raise ValueError("Parametros de busca desconhecidos")

    def read(key):
        if hasattr(args, "getlist"):
            values = args.getlist(key)
            if len(values) > 1:
                raise ValueError(f"'{key}' nao pode ser repetido")
        return args.get(key, "")

    def choice(primary, alias=None):
        if alias and primary in args and alias in args:
            raise ValueError(f"Use apenas '{primary}' ou '{alias}'")
        if primary in args:
            return read(primary), primary
        if alias and alias in args:
            return read(alias), alias
        return "", primary

    def string(value, key, max_len=150):
        if value is None:
            return ""
        text = str(value).strip()
        if len(text) > max_len:
            raise ValueError(f"'{key}' excede {max_len} caracteres")
        if any(category(character) in {"Cc", "Cf", "Cs"} for character in text):
            raise ValueError(f"'{key}' contem caracteres invalidos")
        return text

    def number(value, key, default, minimum, maximum):
        if value == "" or value is None:
            value = default
        text = str(value).strip()
        if not text or not text.isascii() or not text.isdecimal():
            raise ValueError(f"'{key}' deve ser um numero inteiro")
        try:
            parsed = int(text)
        except ValueError:
            raise ValueError(f"'{key}' deve ser um numero inteiro") from None
        if not minimum <= parsed <= maximum:
            raise ValueError(f"'{key}' deve estar entre {minimum} e {maximum}")
        return parsed

    name_raw, name_key = choice("name", "nome")
    mode = string(read("name_mode"), "name_mode", 10).lower() or "exact"
    if "similar" in args:
        if "name" in args or "nome" in args or "name_mode" in args:
            raise ValueError("'similar' nao pode ser combinado com 'nome', 'name' ou 'name_mode'")
        name_raw, name_key = read("similar"), "similar"
        mode = "pattern" if "%" in str(name_raw or "") else "similar"
    name = string(name_raw, name_key)
    if mode not in ("exact", "similar", "pattern"):
        raise ValueError("'name_mode' deve ser 'exact', 'similar' ou 'pattern'")
    if name:
        name = normalize("NFC", name)
        if mode == "exact":
            name = " ".join(name.split())
    if (name_key in args or "name_mode" in args) and not name:
        raise ValueError("O nome pesquisado nao pode ser vazio")
    if mode == "pattern" and name and not name.replace("%", "").strip():
        raise ValueError("O padrao de nome deve conter caracteres pesquisaveis")

    position_raw, position_key = choice("position", "cargo")
    position = string(position_raw, position_key)
    if position_key in args and not position:
        raise ValueError("O cargo pesquisado nao pode ser vazio")
    if position:
        position = normalize("NFC", " ".join(position.split()))

    agency_raw, agency_key = choice("agency", "orgao")
    agency = string(agency_raw, agency_key)
    if agency_key in args and not agency:
        raise ValueError("O orgao pesquisado nao pode ser vazio")
    if agency:
        agency = normalize("NFC", " ".join(agency.split()))

    page_raw, page_key = choice("page", "pagina")
    size_raw, size_key = choice("page_size", "limit")
    for value, key in ((page_raw, page_key), (size_raw, size_key)):
        if key in args and (value is None or not str(value).strip()):
            raise ValueError(f"'{key}' nao pode ser vazio")
    uf_raw = read("uf")
    if "uf" in args and uf_raw is not None and any(
        ord(character) < 32 or ord(character) == 127 for character in str(uf_raw)
    ):
        raise ValueError("'uf' contem caracteres invalidos")
    uf_text = string(uf_raw, "uf", 2)
    if "uf" in args and not uf_text:
        raise ValueError("'uf' nao pode ser vazio")
    uf = uf_text.upper()
    if uf and (not uf_text.isascii() or uf not in UF_VALIDAS):
        raise ValueError("'uf' deve ser uma sigla de estado valida")

    return SearchFilters(
        name=name,
        name_mode=mode,
        position=position,
        agency=agency,
        uf=uf,
        page=number(page_raw, page_key, 1, 1, 1_000_000),
        page_size=number(size_raw, size_key, 20, 1, 100),
    )


def like_contains(value):
    """Escapa curingas de LIKE nas pesquisas comuns por trecho."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def like_pattern(value):
    """Preserva curingas e permite escapar %, _ e barra invertida."""
    parts = []
    position = 0
    while position < len(value):
        current = value[position]
        if current == "\\":
            if position + 1 < len(value) and value[position + 1] in ("%", "_", "\\"):
                parts.append("\\" + value[position + 1])
                position += 2
                continue
            parts.append("\\\\")
        elif current == "_":
            parts.append("\\_")
        else:
            parts.append(current)
        position += 1
    return "".join(parts)


def build_search_queries(filters):
    """Retorna COUNT e SELECT com parâmetros separados para o Psycopg."""
    where = []
    params = {}
    if filters.name:
        params["name"] = filters.name
        if filters.name_mode == "similar":
            contains = like_contains(filters.name)
            params["name_pattern"] = contains
            params["name_prefix"] = contains[1:]
            where.append(
                "(LOWER(nome) %% LOWER(%(name)s) "
                "OR LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\')"
            )
        elif filters.name_mode == "pattern":
            params["name_pattern"] = (like_pattern(filters.name)
                                       if "%" in filters.name else like_contains(filters.name))
            where.append("LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\'")
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
    # UNION elimina IDs repetidos sem descartar correspondências semelhantes.
    if filters.name and filters.name_mode == "similar" and not (
        filters.position or filters.agency or filters.uf
    ):
        count_sql = (
            "SELECT COUNT(*) FROM ("
            "SELECT id FROM servidores WHERE LOWER(nome) %% LOWER(%(name)s) "
            "UNION "
            "SELECT id FROM servidores WHERE "
            "LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\'"
            ") AS matched_ids"
        )

    order = "ORDER BY LOWER(nome), id"
    if filters.name and filters.name_mode == "similar":
        order = (
            "ORDER BY CASE WHEN LOWER(nome) = LOWER(%(name)s) THEN 0 "
            "WHEN LOWER(nome) LIKE LOWER(%(name_prefix)s) ESCAPE '\\' THEN 1 "
            "WHEN LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\' THEN 2 "
            "ELSE 3 END, "
            "similarity(LOWER(nome), LOWER(%(name)s)) DESC, LOWER(nome), id"
        )
    # Materializa as correspondências do padrão antes da ordenação.
    if filters.name and filters.name_mode == "pattern" and not (
        filters.position or filters.agency or filters.uf
    ):
        data_sql = (
            "WITH matched AS MATERIALIZED ("
            "SELECT id, nome, cargo, orgao, uf, fonte" + base + ") "
            "SELECT id, nome, cargo, orgao, uf, fonte FROM matched " + order
            + " LIMIT %(limit)s OFFSET %(offset)s"
        )
    else:
        data_sql = (
            "SELECT id, nome, cargo, orgao, uf, fonte" + base + " " + order
            + " LIMIT %(limit)s OFFSET %(offset)s"
        )
    data_params = dict(params, limit=filters.page_size, offset=(filters.page - 1) * filters.page_size)
    return count_sql, data_sql, params, data_params


def pagination(total, filters):
    return {
        "page": filters.page,
        "page_size": filters.page_size,
        "total": total,
        "pages": ceil(total / filters.page_size),
    }


def build_fuzzy_prefix_page(filters):
    """Consulta opcional por prefixo; utilizada somente se a página estiver completa.

    The standard fuzzy ORDER BY ranks exact names first, then all names
    matching prefix, then substring-only matches, and finally trigram-only
    matches. Consequently a full page of prefix matches at the requested
    OFFSET is identical to the full fuzzy page (including ordering).

    A short page MUST NOT be returned: the caller must run the full query.
    This fast path is limited to fuzzy searches without other filters.
    """
    if not (filters.name and filters.name_mode == "similar") or any((
        filters.position, filters.agency, filters.uf
    )):
        return None
    _, full_page, _, parameters = build_search_queries(filters)
    condition = (
        "(LOWER(nome) %% LOWER(%(name)s) "
        "OR LOWER(nome) LIKE LOWER(%(name_pattern)s) ESCAPE '\\')"
    )
    prefix_condition = "LOWER(nome) LIKE LOWER(%(name_prefix)s) ESCAPE '\\'"
    if full_page.count(condition) != 1:
        raise RuntimeError("Unexpected fuzzy SQL layout")
    return full_page.replace(condition, prefix_condition, 1), parameters
