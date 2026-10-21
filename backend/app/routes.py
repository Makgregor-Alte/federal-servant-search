"""Rotas HTTP para busca e healthcheck."""
import os

from flask import Blueprint, current_app, jsonify, request
import psycopg
from psycopg.rows import dict_row

from .search import build_fuzzy_prefix_page, build_search_queries, pagination, parse_filters

api = Blueprint("api", __name__)

DB_TIMEOUT_OPTIONS = "-c statement_timeout=3000 -c lock_timeout=1000"
FUZZY_DB_TIMEOUT_OPTIONS = "-c statement_timeout=6000 -c lock_timeout=1000"

# A conexão por si só não assegura que o esquema da aplicação esteja pronto.
READINESS_COLUMNS_SQL = "SELECT id, nome, cargo, orgao, uf, fonte FROM servidores LIMIT 0"
READINESS_TRIGRAM_SQL = "SELECT similarity('a', 'a')"


def connect_db(*, fuzzy=False):
    url = current_app.config["DATABASE_URL"]
    options = FUZZY_DB_TIMEOUT_OPTIONS if fuzzy else DB_TIMEOUT_OPTIONS
    # Compose fornece PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD via libpq.
    if url:
        return psycopg.connect(url, row_factory=dict_row, connect_timeout=5, options=options)
    if os.environ.get("PGHOST"):
        return psycopg.connect(row_factory=dict_row, connect_timeout=5, options=options)
    raise psycopg.OperationalError("Database connection is not configured")


@api.get("/health")
def health():
    try:
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.execute(READINESS_COLUMNS_SQL)
                cursor.execute(READINESS_TRIGRAM_SQL)
        return jsonify(status="ok", database="ok")
    except (psycopg.Error, OSError, RuntimeError):
        current_app.logger.warning("Healthcheck falhou")
        return jsonify(status="degraded", database="unavailable"), 503


@api.get("/servidores")
@api.get("/servants")
def search_servants():
    try:
        filters = parse_filters(request.args)
    except ValueError as exc:
        return jsonify(error="invalid_parameters", message=str(exc)), 400
    count_sql, data_sql, params, data_params = build_search_queries(filters)
    with (connect_db(fuzzy=True) if filters.name_mode == "similar" else connect_db()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(count_sql, params)
            total = cursor.fetchone()["count"]
            metadata = pagination(total, filters)
            if filters.page > max(metadata["pages"], 1):
                return jsonify(
                    error="page_not_found",
                    message="Pagina solicitada nao existe",
                    items=[],
                    pagination=metadata,
                ), 404
            if total == 0:
                return jsonify(items=[], pagination=metadata)
            prefix_page = build_fuzzy_prefix_page(filters)
            if prefix_page is not None:
                prefix_sql, prefix_params = prefix_page
                cursor.execute(prefix_sql, prefix_params)
                results = cursor.fetchall()
                # Uma página incompleta por prefixo requer a busca semelhante integral.
                if len(results) < filters.page_size:
                    cursor.execute(data_sql, data_params)
                    results = cursor.fetchall()
            else:
                cursor.execute(data_sql, data_params)
                results = cursor.fetchall()
    return jsonify(items=results, pagination=metadata)
