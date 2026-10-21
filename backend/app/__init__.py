"""Flask application factory for Federal Servant Search."""
import os
from urllib.parse import urlsplit


def create_app():
    from flask import Flask, abort, jsonify, request
    from psycopg import Error as PostgreSQLError, errors as pg_errors
    from werkzeug.exceptions import HTTPException

    app = Flask(__name__)
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    app.config["MAX_QUERY_STRING_BYTES"] = 4096

    from .routes import api
    app.register_blueprint(api, url_prefix="/api")

    def is_api_request():
        return request.path == "/api" or request.path.startswith("/api/")

    @app.before_request
    def validate_request_size():
        if is_api_request() and len(request.query_string) > app.config["MAX_QUERY_STRING_BYTES"]:
            abort(413)

    @app.errorhandler(pg_errors.QueryCanceled)
    @app.errorhandler(pg_errors.LockNotAvailable)
    def database_timeout(error):
        app.logger.warning("PostgreSQL query timeout (%s)", type(error).__name__)
        return jsonify(error="timeout", message="Tempo limite de consulta excedido"), 504

    @app.errorhandler(PostgreSQLError)
    def database_error(error):
        app.logger.error("PostgreSQL operation failed (%s)", type(error).__name__)
        return jsonify(error="database_unavailable", message="Falha ao consultar o banco de dados"), 503

    @app.errorhandler(HTTPException)
    def api_http_error(error):
        if not is_api_request():
            return error
        messages = {
            400: "Requisicao invalida",
            404: "Recurso nao encontrado",
            405: "Metodo HTTP nao permitido",
            413: "Requisicao muito grande",
            429: "Limite de requisicoes excedido",
            500: "Erro interno do servidor",
            503: "Servico temporariamente indisponivel",
            504: "Tempo limite de resposta excedido",
        }
        codes = {
            429: "rate_limited",
            500: "internal_error",
            503: "service_unavailable",
            504: "timeout",
        }
        response = error.get_response()
        response.set_data(app.json.dumps({
            "error": codes.get(error.code, "http_error"),
            "message": messages.get(error.code, "Erro na requisicao"),
        }) + "\n")
        response.mimetype = "application/json"
        return response

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.error("Unexpected application error (%s)", type(error).__name__)
        if is_api_request():
            return jsonify(error="internal_error", message="Erro interno do servidor"), 500
        return "Erro interno do servidor", 500

    @app.after_request
    def add_response_headers(response):
        if not is_api_request():
            return response

        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.vary.add("Origin")

        origins = set()
        for value in os.getenv("ALLOWED_ORIGINS", "").split(","):
            candidate = value.strip()
            try:
                parsed = urlsplit(candidate)
                if (parsed.scheme in {"http", "https"} and parsed.netloc
                        and parsed.hostname and parsed.username is None
                        and parsed.password is None and parsed.path == ""
                        and parsed.query == "" and parsed.fragment == ""
                        and (parsed.port is None or parsed.port > 0)):
                    origins.add(candidate)
            except ValueError:
                continue

        origin = request.headers.get("Origin")
        if origin not in origins:
            return response

        if request.method == "OPTIONS" and "Access-Control-Request-Method" in request.headers:
            response.vary.add("Access-Control-Request-Method")
            response.vary.add("Access-Control-Request-Headers")
            method = request.headers["Access-Control-Request-Method"].upper()
            requested = request.headers.get("Access-Control-Request-Headers", "")
            headers = {part.strip().lower() for part in requested.split(",") if part.strip()}
            if method not in {"GET", "HEAD"} or not headers <= {"accept", "content-type"}:
                return response
            response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
            if headers:
                response.headers["Access-Control-Allow-Headers"] = "Accept, Content-Type"

        response.headers["Access-Control-Allow-Origin"] = origin
        return response

    return app
