"""PostgreSQL custom backups and non-destructive restore into an empty target database."""
# ruff: noqa: E402

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def connection_environment(url: str) -> dict[str, str]:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not parsed.database:
        raise ValueError("postgres_database_required")
    # Pass credentials only through subprocess environment, never argv or logs.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    values = {
        "PGDATABASE": parsed.database,
        "PGHOST": parsed.host,
        "PGPORT": str(parsed.port) if parsed.port else None,
        "PGUSER": parsed.username,
        "PGPASSWORD": parsed.password,
    }
    for key, value in values.items():
        if value is not None:
            env[key] = value
    for key, target in (
        ("host", "PGHOST"),
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("options", "PGOPTIONS"),
    ):
        value = parsed.query.get(key)
        if isinstance(value, str):
            env[target] = value
    env["PGCONNECT_TIMEOUT"] = "10"
    return env


def backup(url: str, destination: Path) -> None:
    if destination.exists():
        raise ValueError("backup_destination_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".backup-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            subprocess.run(
                ["pg_dump", "--format=custom", "--no-owner", "--no-acl"],
                env=connection_environment(url),
                stdout=handle,
                stderr=subprocess.PIPE,
                check=True,
                timeout=3600,
            )
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic creation without replacing an existing backup, even in a race.
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def restore(url: str, archive: Path) -> None:
    env = connection_environment(url)
    if not archive.is_file():
        raise ValueError("backup_missing")
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            count = db.scalar(
                text("""
                SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f')
            """)
            )
            if count:
                raise ValueError("restore_target_must_be_empty")
        subprocess.run(
            [
                "pg_restore",
                "--dbname",
                env["PGDATABASE"],
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                str(archive.resolve()),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=3600,
        )
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument(
        "--env-file",
        type=Path,
        required=True,
        help="Private deployment env; restore uses its explicit target database",
    )
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.env_file.is_file() or args.env_file.stat().st_mode & 0o077:
            raise ValueError("private_env_file_required")
        # The supplied file is authoritative; no accidental local database fallback.
        from dotenv import dotenv_values

        values = dotenv_values(args.env_file, interpolate=False)
        database = values.get("COROOF_DATABASE_URL")
        if not database:
            raise ValueError("explicit_database_required")
        if args.operation == "backup":
            backup(database, args.archive)
        else:
            restore(database, args.archive)
    except Exception:
        print(
            "Database operation failed; check private configuration, archive and empty target.",
            file=sys.stderr,
        )
        return 1
    print(
        "Backup completed."
        if args.operation == "backup"
        else "Restore completed into empty target."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
