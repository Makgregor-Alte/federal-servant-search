"""Audita integridade e proveniência usando somente contagens agregadas."""

import json
import os
import sys

try:
    from .integrity import audit_connection
except ImportError:
    from integrity import audit_connection


def main() -> int:
    if not os.getenv("DATABASE_URL") and not os.getenv("PGHOST"):
        print("Conexao PostgreSQL nao configurada", file=sys.stderr)
        return 2
    try:
        import psycopg
        with psycopg.connect(os.getenv("DATABASE_URL") or "", connect_timeout=5) as conn:
            result = audit_connection(conn)
    except Exception:
        print("Nao foi possivel auditar o banco", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["registros_divergentes_do_lote"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
