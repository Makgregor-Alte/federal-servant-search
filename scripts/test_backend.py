"""Run backend, PostgreSQL and live HTTP tests using Docker Compose."""
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    if not (root / ".env").is_file():
        print("Arquivo .env ausente. Configure-o a partir de .env.example.", file=sys.stderr)
        return 2

    commands = (
        ["docker", "compose", "up", "-d", "--build", "--wait", "db", "backend"],
        [
            "docker", "compose", "run", "--rm", "--no-deps",
            "-v", f"{root}:/workspace:ro",
            "-w", "/workspace/backend",
            "-e", "PYTHONPATH=/workspace/backend",
            "-e", "RUN_DB_INTEGRATION_TESTS=1",
            "-e", "RUN_HTTP_SMOKE_TESTS=1",
            "-e", "API_BASE_URL=http://backend:5000",
            "backend", "python", "-m", "unittest", "discover", "-s", "tests", "-v",
        ],
    )
    for command in commands:
        try:
            subprocess.run(command, cwd=root, check=True)
        except FileNotFoundError:
            print("Docker Compose nao encontrado.", file=sys.stderr)
            return 2
        except subprocess.CalledProcessError as error:
            return error.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
