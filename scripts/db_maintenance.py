"""Operações de manutenção do PostgreSQL usando o serviço Docker Compose."""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ("01_schema.sql", "02_model.sql", "03_integrity.sql", "04_indexes.sql")
RESTORE_DATABASE = re.compile(r"sii_restore_[a-z0-9_]{1,50}\Z")


class MaintenanceError(Exception):
    pass


def _run(arguments, *, stdin=None, stdout=subprocess.PIPE, timeout=1800):
    try:
        process = subprocess.run(
            ["docker", "compose", *arguments], cwd=PROJECT_ROOT,
            stdin=stdin, stdout=stdout, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MaintenanceError("Docker Compose indisponível ou operação excedeu o tempo limite") from exc
    if process.returncode:
        raise MaintenanceError("Operação Docker/PostgreSQL falhou; verifique o serviço e seus logs")
    return process.stdout


def _db(shell_command, *arguments, stdin=None, stdout=subprocess.PIPE, timeout=1800):
    return _run(
        ["exec", "-T", "db", "sh", "-ec", shell_command, "db-maintenance", *arguments],
        stdin=stdin, stdout=stdout, timeout=timeout,
    )


def _safe_backup_path(output=None, directory=None):
    if output:
        path = Path(output).expanduser().resolve()
    else:
        parent = (Path(directory).expanduser().resolve() if directory
                  else PROJECT_ROOT.parent / "federal_servant_backups")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = parent / f"postgres_{stamp}_{uuid.uuid4().hex[:8]}.dump"
    if path.exists():
        raise MaintenanceError("O arquivo de backup já existe; ele não será sobrescrito")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_backup(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise MaintenanceError("Arquivo de backup não encontrado")
    with path.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise MaintenanceError("Arquivo inválido: esperado backup PostgreSQL em formato custom")
        stream.seek(0)
        _db("exec pg_restore --list", stdin=stream, stdout=subprocess.DEVNULL)
    return {"size_bytes": path.stat().st_size, "sha256": _digest(path)}


def create_backup(output=None, directory=None):
    path = _safe_backup_path(output, directory)
    partial = path.with_name(path.name + ".partial")
    try:
        with partial.open("xb") as destination:
            if os.name != "nt":
                os.chmod(partial, 0o600)
            _db(
                'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump '
                '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 6',
                stdout=destination, timeout=3600,
            )
        verify_backup(partial)
        os.replace(partial, path)
        return path
    finally:
        partial.unlink(missing_ok=True)


def migrate(directory=None):
    backup = create_backup(directory=directory)
    for name in MIGRATIONS:
        _db(
            'PGPASSWORD="$POSTGRES_PASSWORD" exec psql '
            '-v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$1"',
            "/docker-entrypoint-initdb.d/" + name,
            stdout=subprocess.DEVNULL,
        )
    return backup


def restore_backup(path, database, confirmed=False):
    if not RESTORE_DATABASE.fullmatch(database):
        raise MaintenanceError("O banco de destino deve começar por sii_restore_ e usar letras minúsculas, números ou _")
    if not confirmed:
        raise MaintenanceError("A restauração exige --confirm e nunca altera o banco original")
    verify_backup(path)
    _db(
        'PGPASSWORD="$POSTGRES_PASSWORD" exec createdb '
        '-U "$POSTGRES_USER" -- "$1"', database,
        stdout=subprocess.DEVNULL,
    )
    try:
        with Path(path).expanduser().resolve().open("rb") as stream:
            _db(
                'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore '
                '-U "$POSTGRES_USER" --no-owner --no-privileges '
                '--exit-on-error --single-transaction -d "$1"',
                database, stdin=stream, stdout=subprocess.DEVNULL, timeout=3600,
            )
    except MaintenanceError as exc:
        raise MaintenanceError(
            "Falha na restauração; o banco de destino foi preservado para inspeção e o original não foi modificado"
        ) from exc
    count = _db(
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At '
        '-v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" '
        '-c "SELECT count(*) FROM public.servidores"',
        database,
    )
    return int(count.decode("ascii").strip())


def _row_count():
    result = _db(
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At '
        '-v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        '-c "SELECT count(*) FROM public.servidores"', timeout=120,
    )
    return int(result.decode("ascii").strip())


def check_persistence(confirmed=False):
    if not confirmed:
        raise MaintenanceError("Informe --confirm-restart para autorizar a reinicialização do banco")
    before = _row_count()
    _run(["restart", "db"], stdout=subprocess.DEVNULL, timeout=120)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            _db('exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                stdout=subprocess.DEVNULL, timeout=15)
            after = _row_count()
        except MaintenanceError:
            time.sleep(2)
            continue
        if before != after:
            raise MaintenanceError("Contagem de registros mudou após a reinicialização")
        return before
    raise MaintenanceError("O banco não ficou disponível ou a contagem mudou após a reinicialização")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backup, migração e recuperação segura do PostgreSQL")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--output")
    backup.add_argument("--directory")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--file", required=True)
    migrations = subparsers.add_parser("migrate")
    migrations.add_argument("--backup-directory")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--file", required=True)
    restore.add_argument("--database", required=True)
    restore.add_argument("--confirm", action="store_true")
    persistence = subparsers.add_parser("persistence-check")
    persistence.add_argument("--confirm-restart", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            path = create_backup(output=args.output, directory=args.directory)
            print(f"Backup: {path}\nSHA-256: {_digest(path)}")
        elif args.command == "verify":
            result = verify_backup(args.file)
            print(f"Backup legível: {result['size_bytes']} bytes\nSHA-256: {result['sha256']}")
        elif args.command == "migrate":
            path = migrate(directory=args.backup_directory)
            print(f"Migrações aplicadas. Backup anterior: {path}")
        elif args.command == "restore":
            count = restore_backup(args.file, args.database, confirmed=args.confirm)
            print(f"Restauração concluída em {args.database}. Registros: {count}")
        elif args.command == "persistence-check":
            count = check_persistence(confirmed=args.confirm_restart)
            print(f"Registros antes e depois: {count}")
            if count == 0:
                print("Banco vazio: persistência dos registros ainda não comprovada")
    except MaintenanceError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
