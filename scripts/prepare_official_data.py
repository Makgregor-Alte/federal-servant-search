"""Confere as duas fontes e coordena a importacao oficial por competencia."""

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.inspect_source import inspect
from db.normalize import analyze, iter_normalized


SOURCES = ("aposentados", "carreiras")


class PreparationError(Exception):
    pass


def source_filenames(competencia: str) -> dict[str, str]:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", competencia):
        raise PreparationError("Competencia deve seguir AAAA-MM (ano 2000-2099)")
    year, month = competencia.split("-")
    token = month + year
    return {
        "aposentados": f"APOSENTADOS_{token}_FULL.csv",
        "carreiras": f"CARREIRA_{token}.txt",
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_source_files(data_dir: Path, competencia: str, *, sample_rows: int = 100) -> dict:
    """Somente leitura: verifica nome, layout e competencia sem expor linhas."""
    if not 1 <= sample_rows <= 10000:
        raise PreparationError("sample_rows deve ficar entre 1 e 10000")
    paths = source_filenames(competencia)
    data_dir = data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        raise PreparationError("Diretorio de dados nao encontrado")
    if data_dir == ROOT or ROOT in data_dir.parents:
        raise PreparationError("Guarde arquivos oficiais fora do diretorio do projeto")
    summary = {"competencia": competencia, "fontes": {}}
    for source in SOURCES:
        filename = paths[source]
        path = data_dir / filename
        if not path.is_file():
            raise PreparationError(f"Arquivo obrigatorio ausente: {filename}")
        diagnostic = inspect(path, source, sample_rows=sample_rows)
        if not diagnostic["ready_for_mapping"]:
            raise PreparationError(f"Layout nao reconhecido ou linhas malformadas: {filename}")
        delimiter = "\t" if diagnostic["delimiter"] == "\\t" else diagnostic["delimiter"]
        normalized = analyze(path, source, encoding=diagnostic["encoding"],
                             delimiter=delimiter, max_rows=sample_rows)
        if not normalized["aceitas"]:
            raise PreparationError(f"Nenhum registro valido na amostra: {filename}")
        for item in iter_normalized(path, source, encoding=diagnostic["encoding"],
                                    delimiter=delimiter, max_rows=sample_rows):
            if "competencia_invalida" in item.issues:
                raise PreparationError(f"Competencia invalida detectada em: {filename}")
            if item.record and item.record["competencia"] is not None:
                if item.record["competencia"][:7] != competencia:
                    raise PreparationError(f"Competencia do arquivo diverge: {filename}")
        summary["fontes"][source] = {
            "arquivo": filename,
            "sha256": sha256(path),
            "bytes": diagnostic["file_size_bytes"],
            "codificacao": diagnostic["encoding"],
            "separador": diagnostic["delimiter"],
            "campos": sorted(diagnostic["mapped"].keys()),
            "amostra": normalized,
        }
    return summary


def docker_command(data_dir: Path, source: str, competencia: str,
                   *, apply: bool = False, batch_size: int = 1000) -> list[str]:
    if source not in SOURCES:
        raise PreparationError("Fonte desconhecida")
    if not 1 <= batch_size <= 10000:
        raise PreparationError("batch_size deve ficar entre 1 e 10000")
    file_name = source_filenames(competencia)[source]
    cmd = [
        "docker", "compose", "--project-directory", str(ROOT),
        "-f", str(ROOT / "docker-compose.yml"),
        "run", "--rm", "--no-deps",
        "--volume", f"{data_dir.expanduser().resolve()}:/dados:ro",
        "--volume", f"{ROOT}:/workspace:ro",
        "--workdir", "/workspace", "backend",
        "python", "/workspace/db/import_bulk.py",
        "--source", source, "--file", f"/dados/{file_name}",
        "--competencia", competencia, "--batch-size", str(batch_size),
    ]
    if apply:
        cmd.append("--apply")
    return cmd


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except FileNotFoundError as exc:
        raise PreparationError("Docker Compose nao encontrado neste computador") from exc
    if result.returncode != 0:
        raise PreparationError("Etapa interrompida; confira Docker, banco e o layout dos dados")


def _check_database() -> None:
    sql = (
        "SELECT (to_regclass('public.servidores') IS NOT NULL "
        "AND to_regclass('public.lotes_importacao') IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm') "
        "AND EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conrelid=to_regclass('public.servidores') "
        "AND conname='servidores_id_origem_preenchido_ck'))"
    )
    shell = (
        'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -At -v ON_ERROR_STOP=1 '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1" | grep -qx t'
    )
    _run(["docker", "compose", "--project-directory", str(ROOT), "-f",
          str(ROOT / "docker-compose.yml"), "exec", "-T", "db", "sh", "-c",
          shell, "_", sql])


def run_pipeline(data_dir: Path, competencia: str, *, mode: str = "inspect",
                 confirm: bool = False, batch_size: int = 1000,
                 sample_rows: int = 100) -> dict:
    if mode not in ("inspect", "validate", "import"):
        raise PreparationError("Modo desconhecido")
    if mode == "import" and not confirm:
        raise PreparationError("Importacao exige --confirm")
    if not 1 <= batch_size <= 10000:
        raise PreparationError("batch_size deve ficar entre 1 e 10000")
    report = check_source_files(data_dir, competencia, sample_rows=sample_rows)
    if mode == "inspect":
        report["modo"] = "inspecao"
        return report
    for source in SOURCES:
        _run(docker_command(data_dir, source, competencia, batch_size=batch_size))
    if mode == "validate":
        report["modo"] = "validacao_completa"
        return report
    # A validacao das duas fontes termina antes de qualquer escrita no banco.
    for source in SOURCES:
        path = data_dir.expanduser().resolve() / source_filenames(competencia)[source]
        if sha256(path) != report["fontes"][source]["sha256"]:
            raise PreparationError("Arquivo alterado durante a validacao")
    _check_database()
    for source in SOURCES:
        _run(docker_command(data_dir, source, competencia, apply=True,
                            batch_size=batch_size))
    report["modo"] = "importacao_executada"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepara a carga das duas bases oficiais")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--competencia", required=True, help="AAAA-MM")
    parser.add_argument("--mode", choices=("inspect", "validate", "import"),
                        default="inspect")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--sample-rows", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        summary = run_pipeline(args.data_dir, args.competencia, mode=args.mode,
                               confirm=args.confirm, batch_size=args.batch_size,
                               sample_rows=args.sample_rows)
    except (PreparationError, ValueError, OSError, UnicodeError, csv.Error, LookupError) as error:
        # Nao ecoar excecoes do parser CSV nem conteudo de registros individuais.
        message = str(error) if isinstance(error, PreparationError) else "Falha ao analisar arquivo oficial"
        print(f"Erro: {message}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
