"""Rotas HTTP para busca e healthcheck."""
import os

from flask import Blueprint, current_app, jsonify, request
import psycopg
from psycopg.rows import dict_row

from .search import build_search_queries, pagination, parse_filters

api = Blueprint("api", __name__)


def connect_db():
    url = current_app.config["DATABASE_URL"]
    # Compose fornece PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD via libpq.
    if url:
        return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)
    if os.environ.get("PGHOST"):
        return psycopg.connect(row_factory=dict_row, connect_timeout=5)
    raise RuntimeError("Configure DATABASE_URL ou as variáveis PG* do PostgreSQL")


@api.get("/health")
def health():
    try:
        with connect_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        return jsonify(status="ok", database="ok")
    except (psycopg.Error, OSError, RuntimeError):
        current_app.logger.warning("Healthcheck falhou", exc_info=True)
        return jsonify(status="degraded", database="unavailable"), 503


@api.get("/servidores")
@api.get("/servants")
def search_servants():
    try:
        filters = parse_filters(request.args)
    except ValueError as exc:
        return jsonify(error="invalid_parameters", message=str(exc)), 400
    count_sql, data_sql, params, data_params = build_search_queries(filters)
    with connect_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(count_sql, params)
            total = cursor.fetchone()["count"]
            cursor.execute(data_sql, data_params)
            results = cursor.fetchall()
    return jsonify(items=results, pagination=pagination(total, filters))
