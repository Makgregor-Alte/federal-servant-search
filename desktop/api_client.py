"""Cliente HTTP da API de servidores, independente da interface gráfica."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class ApiError(Exception):
    pass


def normalize_url(value):
    value = str(value).strip().rstrip("/")
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.path not in {"", "/"}
                or parts.query or parts.fragment):
            raise ValueError
        _ = parts.port
    except ValueError:
        raise ApiError("Informe a URL base da aplicação, como http://127.0.0.1:8081.") from None
    return value


def build_query(filters, page):
    name = str(filters.get("name", "")).strip()
    position = str(filters.get("position", "")).strip()
    agency = str(filters.get("agency", "")).strip()
    uf = str(filters.get("uf", "")).strip().upper()
    mode = filters.get("name_mode", "exact")
    size = filters.get("page_size", 20)

    if not any((name, position, agency, uf)):
        raise ApiError("Informe pelo menos um filtro para pesquisar.")
    if mode not in {"exact", "similar", "pattern"}:
        raise ApiError("Modo de busca inválido.")
    for field in (name, position, agency):
        if len(field) > 150:
            raise ApiError("Cada campo de texto aceita até 150 caracteres.")
    if mode == "pattern" and name and not name.replace("%", "").strip():
        raise ApiError("O padrão deve conter texto além de %.")
    if name and mode == "pattern" and "%" not in name:
        raise ApiError("Use % no nome para pesquisar por padrão.")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= 1_000_000:
        raise ApiError("Página inválida.")
    if isinstance(size, bool) or str(size) not in {"10", "20", "50", "100"}:
        raise ApiError("Quantidade por página inválida.")
    if uf and uf not in set("AC AL AP AM BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()):
        raise ApiError("UF inválida.")

    params = {"page": page, "page_size": int(size)}
    if name:
        params["name"] = name
        params["name_mode"] = mode
    if position:
        params["position"] = position
    if agency:
        params["agency"] = agency
    if uf:
        params["uf"] = uf
    return params


def validate_payload(data, page, page_size):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ApiError("A API retornou dados em formato inesperado.")
    paging = data.get("pagination")
    if not isinstance(paging, dict):
        raise ApiError("A API não retornou informações de paginação.")
    for key in ("page", "page_size", "total", "pages"):
        val = paging.get(key)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ApiError("A API retornou paginação inválida.")
    if (paging["page"] != page or paging["page_size"] != page_size
            or paging["pages"] != math.ceil(paging["total"] / page_size)
            or len(data["items"]) > page_size or len(data["items"]) > paging["total"]):
        raise ApiError("A API retornou paginação inconsistente.")
    for item in data["items"]:
        if (not isinstance(item, dict) or type(item.get("id")) is not int
                or not isinstance(item.get("nome"), str)
                or any(key not in item or (item[key] is not None and not isinstance(item[key], str))
                       for key in ("cargo", "orgao", "uf", "fonte"))):
            raise ApiError("A API retornou um registro inválido.")
    return data


def fetch_servants(base_url, filters, page=1, *, timeout=20, opener=urlopen):
    url = normalize_url(base_url)
    params = build_query(filters, page)
    request = Request(url + "/api/servidores?" + urlencode(params),
                      headers={"Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            content = response.read(2_000_001)
        if len(content) > 2_000_000:
            raise ApiError("A resposta da API excedeu o tamanho permitido.")
        payload = json.loads(content.decode("utf-8"))
    except HTTPError as exc:
        messages = {
            400: "Filtros inválidos. Revise os campos informados.",
            404: "Página inexistente. Faça uma nova busca.",
            429: "Muitas consultas. Aguarde alguns segundos e tente novamente.",
            502: "A API não está disponível no momento.",
            503: "A API ou o banco estão temporariamente indisponíveis.",
            504: "A consulta excedeu o limite de tempo. Tente outro filtro.",
        }
        raise ApiError(messages.get(exc.code, f"Falha de comunicação com a API (HTTP {exc.code}).")) from None
    except (URLError, TimeoutError, OSError):
        raise ApiError("Não foi possível acessar a API. Confira a URL e o Docker.") from None
    except (UnicodeError, json.JSONDecodeError):
        raise ApiError("A API retornou uma resposta JSON inválida.") from None
    return validate_payload(payload, page, params["page_size"])
