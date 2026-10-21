"""Valida estrutura, integridade, fontes e resposta HTTP sem alterar o banco."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.acceptance import collect_snapshot, evaluate_snapshot


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_http(api_url: str, expected_total: int) -> dict:
    """Confere contrato da API sem imprimir linhas com dados pessoais."""
    base = api_url.rstrip("/")
    if not base.startswith(("http://127.0.0.1:", "http://localhost:",
                            "http://backend:", "http://frontend:")):
        raise ValueError("Use uma URL local ou o endereco interno do Docker")
    if not base.endswith("/api"):
        base += "/api"

    def get(path):
        with urlopen(base + path, timeout=10) as response:
            if response.status != 200:
                raise ValueError("A API retornou um status inesperado")
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise ValueError("A API nao retornou JSON")
            return json.loads(response.read(1024 * 1024))

    health = get("/health")
    if health.get("status") != "ok" or health.get("database") != "ok":
        raise ValueError("Healthcheck da API indica indisponibilidade")
    search = get("/servidores?pagina=1&limit=5")
    items = search.get("items")
    pagination = search.get("pagination")
    if not isinstance(items, list) or not isinstance(pagination, dict):
        raise ValueError("Contrato de resposta de busca invalido")
    if (pagination.get("total") != expected_total or pagination.get("page") != 1
            or pagination.get("page_size") != 5
            or len(items) != min(expected_total, 5)):
        raise ValueError("Contagem ou paginacao incompatível entre API e PostgreSQL")
    required = {"id", "nome", "cargo", "orgao", "uf", "fonte"}
    if any(not isinstance(item, dict) or not required <= item.keys() for item in items):
        raise ValueError("Campos incompletos na resposta da API")
    return {"status": "aprovado", "registros_na_primeira_pagina": len(items)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validacao somente leitura do PostgreSQL")
    parser.add_argument("--api-url", help="Endereco HTTP da API para checar a integracao")
    parser.add_argument("--aposentados-arquivo", type=Path)
    parser.add_argument("--carreiras-arquivo", type=Path)
    args = parser.parse_args(argv)
    try:
        import psycopg
        if not os.getenv("DATABASE_URL") and not os.getenv("PGHOST"):
            raise ValueError("Conexao PostgreSQL nao configurada")
        hashes = {}
        for source, path in (("aposentados", args.aposentados_arquivo),
                             ("carreiras", args.carreiras_arquivo)):
            if path is not None:
                hashes[source] = checksum(path)
        with psycopg.connect(os.getenv("DATABASE_URL") or "", connect_timeout=5,
                             options="-c statement_timeout=60000 -c lock_timeout=2000") as conn:
            with conn.transaction():
                with conn.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                snapshot = collect_snapshot(conn)
            result = evaluate_snapshot(snapshot, file_hashes=hashes)
        if args.api_url:
            try:
                result["api"] = check_http(
                    args.api_url,
                    sum(data["registros"] for data in snapshot["sources"].values()),
                )
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
                result["erros"].append("Nao foi possivel validar a integracao HTTP")
                result["status"] = "reprovado"
        else:
            result["api"] = {"status": "nao_verificada"}
            result["pendencias"].append("Integracao HTTP ainda nao verificada")
            if result["status"] == "aprovado":
                result["status"] = "pendente"
    except Exception:
        print(json.dumps({"status": "erro", "mensagem": "Nao foi possivel validar o banco"},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "aprovado" else 1


if __name__ == "__main__":
    raise SystemExit(main())
