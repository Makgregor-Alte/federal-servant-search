"""Factory da API Flask do projeto Federal Servant Search."""
import logging
import os


def create_app():
    from flask import Flask, jsonify, request
    from psycopg import DatabaseError

    app = Flask(__name__)
    # Opcional para uso fora do Compose: conexão URI explícita.
    app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")

    from .routes import api
    app.register_blueprint(api, url_prefix="/api")

    @app.errorhandler(DatabaseError)
    def database_error(error):
        logging.exception("Erro ao acessar PostgreSQL")
        return jsonify(error="database_unavailable", message="Falha ao consultar o banco de dados"), 503

    @app.after_request
    def add_cors(response):
        # A SPA em produção faz as requisições no mesmo host via nginx.
        origins = {s.strip() for s in os.getenv("ALLOWED_ORIGINS", "").split(",") if s.strip()}
        origin = request.headers.get("Origin")
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    return app
