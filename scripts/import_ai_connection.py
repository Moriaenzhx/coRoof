"""Explicitly import a saved API connection into one tenant. Does not call a model."""

# ruff: noqa: E402
import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.infrastructure.db import session_factory
from app.infrastructure.models import Membership
from app.modules.ai_admin.imports import import_saved_connection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True, type=UUID, help="Active owner membership ID")
    parser.add_argument("--config-file", required=True, help="JSON file; '-' reads stdin")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    settings().check_deployment()
    try:
        source = sys.stdin if args.config_file == "-" else Path(args.config_file).open()
        with source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError
        config = json.loads(raw)
        if not isinstance(config, dict):
            raise ValueError
        with session_factory()() as db:
            actor = db.scalar(
                select(Membership).where(
                    Membership.id == str(args.actor_id),
                    Membership.organization_id == str(args.organization_id),
                )
            )
            if actor is None:
                raise ValueError
            result = import_saved_connection(db, actor, config, args.name)
            print(
                json.dumps(
                    {
                        "connection_id": result.id,
                        "usage_scope": result.usage_scope,
                        "state": result.state,
                        "activated": False,
                    },
                    ensure_ascii=False,
                )
            )
    except (ValueError, ValidationError, HTTPException, OSError):
        # Do not expose raw validation errors, config contents or source credentials.
        print(
            "Import failed: check configuration, active owner and server encryption setup.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
