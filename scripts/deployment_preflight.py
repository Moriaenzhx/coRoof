"""Offline production configuration checks; no secrets or remote calls in output."""

# ruff: noqa: E402
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import dotenv_values

from app.core.config import Settings
from app.core.deployment import issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.env_file.is_file() or args.env_file.stat().st_mode & 0o077:
            raise ValueError("private_env_file_required")
        values = {
            key.removeprefix("COROOF_").lower(): value
            for key, value in dotenv_values(args.env_file, interpolate=False).items()
            if key.startswith("COROOF_") and value is not None
        }
        # Explicit file fields override process environment. Missing fields use declared defaults.
        defaults = {
            name: field.get_default(call_default_factory=True)
            for name, field in Settings.model_fields.items()
        }
        for name, value in list(values.items()):
            if isinstance(defaults.get(name), list):
                values[name] = json.loads(value)
        cfg = Settings(_env_file=None, **(defaults | values))
        missing = issues(cfg)
        if cfg.environment != "production":
            missing.append("production_environment")
        print(
            json.dumps(
                {
                    "ready": not missing,
                    "missing": missing,
                    "external_services_verified_by_this_check": False,
                }
            )
        )
        return 1 if missing else 0
    except Exception:
        print(json.dumps({"ready": False, "missing": ["valid_private_configuration"]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
