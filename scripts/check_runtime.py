"""Verifica a interface e a API HTTP de uma instalação em execução."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


class RuntimeCheckError(Exception):
    pass


def request(path, base_url, timeout):
    address = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    try:
        with urlopen(Request(address, headers={"Accept": "application/json, text/html"}), timeout=timeout) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read(1024 * 1024)
    except HTTPError as exc:
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")
        body = exc.read(1024 * 1024)
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeCheckError(f"Não foi possível acessar {path} ({type(exc).__name__})") from exc
    return status, content_type, body


def json_response(path, base_url, timeout, expected_status):
    status, content_type, body = request(path, base_url, timeout)
    if status != expected_status:
        raise RuntimeCheckError(f"{path}: HTTP {status}, esperado {expected_status}")
    if "application/json" not in content_type.lower():
        raise RuntimeCheckError(f"{path}: resposta não é JSON")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeCheckError(f"{path}: JSON inválido") from exc
    if not isinstance(payload, dict):
        raise RuntimeCheckError(f"{path}: resposta deve ser um objeto JSON")
    return payload


def validate_search_response(payload, *, requested_page, requested_size):
    if not isinstance(payload, dict):
        raise RuntimeCheckError("A resposta não é um objeto JSON")
    items = payload.get("items")
    pagination = payload.get("pagination")
    if not isinstance(items, list) or not isinstance(pagination, dict):
        raise RuntimeCheckError("A pesquisa não retornou items e pagination")
    for key in ("page", "page_size", "total", "pages"):
        value = pagination.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise RuntimeCheckError(f"Campo de paginação inválido: {key}")
    if pagination["page"] != requested_page or pagination["page_size"] != requested_size:
        raise RuntimeCheckError("A API não preservou os parâmetros de paginação")
    total = pagination["total"]
    pages = pagination["pages"]
    if total < 0 or pages != (total + requested_size - 1) // requested_size:
        raise RuntimeCheckError("Metadados de paginação inconsistentes")
    if len(items) > requested_size or len(items) > total:
        raise RuntimeCheckError("Quantidade de registros inconsistente")
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeCheckError("Registro não é um objeto JSON")
        if not isinstance(item.get("id"), int) or isinstance(item.get("id"), bool):
            raise RuntimeCheckError("Identificador de registro inválido")
        if not isinstance(item.get("nome"), str):
            raise RuntimeCheckError("Nome do registro inválido")
        for key in ("cargo", "orgao", "uf", "fonte"):
            if item.get(key) is not None and not isinstance(item.get(key), str):
                raise RuntimeCheckError(f"Campo de registro inválido: {key}")
            if key not in item:
                raise RuntimeCheckError(f"Campo de registro ausente: {key}")
    return total



def check(base_url="http://127.0.0.1:8080", timeout=10):
    parsed = urlsplit(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise RuntimeCheckError("Informe uma URL base HTTP(S) sem caminho, credenciais ou parâmetros")

    status, content_type, body = request("/", base_url, timeout)
    if status != 200 or "text/html" not in content_type.lower() or b"<html" not in body.lower():
        raise RuntimeCheckError("Frontend não respondeu com HTML e HTTP 200")

    health = json_response("/api/health", base_url, timeout, 200)
    if health.get("status") != "ok" or health.get("database") != "ok":
        raise RuntimeCheckError("O backend ou o banco não está pronto")

    results = json_response("/api/servidores?page=1", base_url, timeout, 200)
    pagination = results.get("pagination")
    if not isinstance(results.get("items"), list) or not isinstance(pagination, dict):
        raise RuntimeCheckError("A pesquisa não retornou items e pagination")
    for key in ("page", "page_size", "total", "pages"):
        if not isinstance(pagination.get(key), int) or isinstance(pagination.get(key), bool):
            raise RuntimeCheckError(f"Campo de paginação inválido: {key}")

    invalid_uf = json_response("/api/servidores?uf=ZZ", base_url, timeout, 400)
    if invalid_uf.get("error") != "invalid_parameters":
        raise RuntimeCheckError("UF inválida não gerou o erro esperado")

    return {"checks": 4, "total_records": pagination["total"]}


def check_contract(base_url="http://127.0.0.1:8080", timeout=10):
    baseline = check(base_url, timeout)
    baseline_response = json_response("/api/servidores?page=1&page_size=20", base_url, timeout, 200)
    validate_search_response(baseline_response, requested_page=1, requested_size=20)

    for parameters in (
        {"name": "Maria", "name_mode": "exact", "page": "1", "page_size": "10"},
        {"name": "Mariana", "name_mode": "similar", "page": "1", "page_size": "10"},
        {"similar": "%NOME%SOBRENOME%", "page": "1", "page_size": "10"},
    ):
        path = "/api/servidores?" + urlencode(parameters)
        response = json_response(path, base_url, timeout, 200)
        validate_search_response(response, requested_page=1, requested_size=10)

    return {"checks": baseline["checks"] + 4, "total_records": baseline["total_records"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verifica o sistema web e a API em execução")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="URL base da interface")
    parser.add_argument("--timeout", type=float, default=10, help="Timeout por requisição em segundos")
    parser.add_argument("--contract", action="store_true", help="Também valida os modos de pesquisa usados pelo frontend")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        parser.error("O timeout deve estar entre 0 e 120 segundos")
    try:
        result = check_contract(args.url, args.timeout) if args.contract else check(args.url, args.timeout)
    except RuntimeCheckError as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {result['checks']} verificações HTTP; total de registros: {result['total_records']}")
    if result["total_records"] == 0:
        print("ATENÇÃO: banco sem registros; pesquisa com dados oficiais não validada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
