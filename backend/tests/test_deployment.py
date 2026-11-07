"""Offline release controls plus real PostgreSQL migration, backup and empty-target restore."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import Settings, settings
from app.core.deployment import issues
from app.infrastructure.models import Base

ROOT = Path(__file__).resolve().parents[2]


def configured():
    return Settings(
        _env_file=None,
        environment="production",
        auth_mode="oidc",
        cookie_secure=True,
        oidc_issuer="https://identity.example.com",
        oidc_client_id="fixture-client",
        oidc_client_secret=SecretStr("fixture-client-secret-long-enough"),
        oidc_session_secret=SecretStr("fixture-signing-secret-long-enough"),
        web_origin="https://workspace.example.com",
        delivery_mode="smtp",
        smtp_host="smtp.example.com",
        smtp_username="fixture",
        smtp_from="invites@example.com",
        smtp_password=SecretStr("fixture-smtp-secret"),
        smtp_tls="starttls",
        mail_secret_key=SecretStr(Fernet.generate_key().decode()),
        ai_secret_key=SecretStr(Fernet.generate_key().decode()),
        database_url="postgresql+psycopg://coroof:fixture-database-password@postgres/coroof",
        redis_url="redis://:fixture-queue-password@redis/0",
        rate_limit_url="",
        production_release_verified=True,
    )


def test_release_requires_external_acceptance_and_safe_configuration():
    cfg = configured()
    assert issues(cfg) == []
    cfg.check_deployment()
    for field, value, expected in [
        ("production_release_verified", False, "external_release_acceptance"),
        ("auth_mode", "mock", "verified_identity"),
        ("cookie_secure", False, "secure_cookies"),
        ("smtp_tls", "local", "verified_delivery"),
        ("web_origin", "http://workspace.example.com", "web_origin"),
        ("oidc_issuer", "https://user:secret@id.example.com", "identity_issuer"),
        ("rate_limit_url", "memory://", "shared_rate_limit"),
        ("redis_url", "redis://redis/0", "redis_credentials"),
        ("database_url", "sqlite:///local.db", "postgres_credentials"),
        ("mail_secret_key", SecretStr("invalid"), "mail_encryption"),
    ]:
        changed = cfg.model_copy(update={field: value})
        assert expected in issues(changed)
        with pytest.raises(RuntimeError, match=expected):
            changed.check_deployment()


def test_preflight_uses_only_explicit_private_file_and_redacts_secrets(tmp_path, monkeypatch):
    cfg = configured()
    values = cfg.model_dump()
    private = tmp_path / "server.env"
    lines = []
    for name, value in values.items():
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        elif isinstance(value, (list, bool)):
            value = json.dumps(value)
        elif value is None:
            continue
        lines.append("COROOF_" + name.upper() + "=" + str(value))
    private.write_text("\n".join(lines))
    private.chmod(0o600)
    monkeypatch.setenv("COROOF_AUTH_MODE", "mock")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/deployment_preflight.py"), "--env-file", str(private)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["external_services_verified_by_this_check"] is False
    assert "fixture-" not in result.stdout + result.stderr
    # A local shell variable must not supply a release approval omitted from the file.
    private.write_text(
        private.read_text().replace(
            "COROOF_PRODUCTION_RELEASE_VERIFIED=true",
            "COROOF_PRODUCTION_RELEASE_VERIFIED=${LOCAL_RELEASE_ACCEPTANCE}",
        )
    )
    monkeypatch.setenv("LOCAL_RELEASE_ACCEPTANCE", "true")
    inherited = subprocess.run(
        [sys.executable, str(ROOT / "scripts/deployment_preflight.py"), "--env-file", str(private)],
        capture_output=True,
        text=True,
    )
    assert inherited.returncode == 1
    assert json.loads(inherited.stdout)["ready"] is False
    assert "fixture-" not in inherited.stdout + inherited.stderr
    private.chmod(0o644)
    denied = subprocess.run(
        [sys.executable, str(ROOT / "scripts/deployment_preflight.py"), "--env-file", str(private)],
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 1


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_database_cli_never_inherits_target_from_shell(tmp_path, monkeypatch, capsys, operation):
    spec = importlib.util.spec_from_file_location(
        "database_backup_explicit", ROOT / "scripts/database_backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private = tmp_path / "database.env"
    private.write_text("COROOF_DATABASE_URL=${LOCAL_DATABASE_TARGET}\n")
    private.chmod(0o600)
    monkeypatch.setenv(
        "LOCAL_DATABASE_TARGET",
        "postgresql+psycopg://fixture:fixture-private-password@wrong-target.invalid/coroof",
    )
    archive = tmp_path / "backup.dump"
    if operation == "restore":
        archive.write_bytes(b"synthetic archive; no restore should be attempted")
    attempts = []

    def deny_external_operation(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Database target must not come from process interpolation")

    monkeypatch.setattr(module.subprocess, "run", deny_external_operation)
    monkeypatch.setattr(module, "create_engine", deny_external_operation)
    monkeypatch.setattr(
        sys,
        "argv",
        ["database_backup.py", operation, "--env-file", str(private), "--archive", str(archive)],
    )
    assert module.main() == 1
    assert attempts == []
    if operation == "backup":
        assert not archive.exists()
    output = capsys.readouterr()
    assert "fixture-private-password" not in output.out + output.err
    assert "wrong-target.invalid" not in output.out + output.err


def test_pg_upgrade_backup_restore_preserves_data_and_refuses_existing_target(
    database, monkeypatch, tmp_path
):
    base = os.environ.get("COROOF_TEST_DATABASE_URL")
    if not base:
        pytest.skip("PostgreSQL backup and restore acceptance")
    spec = importlib.util.spec_from_file_location(
        "database_backup", ROOT / "scripts/database_backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    names = ["coroof_test_backup_" + uuid4().hex, "coroof_test_restore_" + uuid4().hex]
    engines = []
    try:
        with admin.connect() as db:
            for name in names:
                db.execute(text(f'CREATE DATABASE "{name}"'))
        urls = [
            make_url(base).set(database=name).render_as_string(hide_password=False)
            for name in names
        ]
        source, target = (create_engine(url) for url in urls)
        engines.extend([source, target])
        monkeypatch.setenv("COROOF_DATABASE_URL", urls[0])
        settings.cache_clear()
        command.upgrade(database, "0010_memory")
        org, user = str(uuid4()), str(uuid4())
        with source.begin() as db:
            db.execute(
                text(
                    "INSERT INTO organizations (id,name,timezone,created_at) "
                    "VALUES (:id,'备份验收','Asia/Shanghai',CURRENT_TIMESTAMP)"
                ),
                {"id": org},
            )
            db.execute(
                text(
                    "INSERT INTO users (id,verified_identity,name,identity_provider,created_at) "
                    "VALUES (:id,'backup@example.com','备份用户','mock',CURRENT_TIMESTAMP)"
                ),
                {"id": user},
            )
        command.upgrade(database, "head")
        command.check(database)
        with source.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM organizations")) == 1
            assert db.scalar(text("SELECT identity_provider FROM users")) == "mock"
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0019_arrangement_feedback"
            )
        archive = tmp_path / "snapshot.dump"
        module.backup(urls[0], archive)
        assert archive.stat().st_mode & 0o777 == 0o600
        with pytest.raises(ValueError, match="destination_exists"):
            module.backup(urls[0], archive)
        module.restore(urls[1], archive)
        with target.connect() as db:
            assert db.scalar(text("SELECT name FROM organizations")) == "备份验收"
            assert db.scalar(text("SELECT verified_identity FROM users")) == "backup@example.com"
        assert set(inspect(target).get_table_names()) >= set(Base.metadata.tables)
        with pytest.raises(ValueError, match="must_be_empty"):
            module.restore(urls[1], archive)
        with target.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM organizations")) == 1
    finally:
        for engine in engines:
            engine.dispose()
        with admin.connect() as db:
            for name in names:
                db.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()
