"""Explicit operator import into one authorized tenant; never auto-scan local secrets."""

import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.models import AIConfigEvent, Membership
from app.modules.ai_admin.api import create_connection
from app.modules.ai_admin.schemas import ConnectionInput, ConnectionOut
from app.modules.ai_admin.service import lock_tenant, record
from app.modules.model_gateway.catalog import PROVIDERS


def import_saved_connection(
    db: Session, actor: Membership, config: dict[str, Any], name: str
) -> ConnectionOut:
    provider = config.get("provider")
    provider = "bailian" if provider == "bailian_coding_plan" else provider
    preset = PROVIDERS.get(provider) if isinstance(provider, str) else None
    values = {
        "name": name,
        "provider": provider,
        "model": config.get("model"),
        "base_url": config.get("base_url"),
        "api_key": config.get("api_key"),
        "output_mode": config.get("output_mode", preset.output_mode if preset else "schema"),
    }
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    request_key = uuid5(
        NAMESPACE_URL, f"coroof-ai-import:{actor.organization_id}:{actor.id}:{fingerprint}"
    )
    payload = ConnectionInput.model_validate({**values, "idempotency_key": request_key})
    result = create_connection(payload, db, actor)
    lock_tenant(db, actor)
    audit_key = str(uuid5(request_key, "import-audit"))
    if not db.scalar(
        select(AIConfigEvent.id).where(
            AIConfigEvent.organization_id == actor.organization_id,
            AIConfigEvent.actor_id == actor.id,
            AIConfigEvent.request_key == audit_key,
        )
    ):
        record(
            db,
            actor,
            "connection.imported",
            result.version,
            "从已保存配置导入；未自动测试或启用，原有模型选择保持不变",
            result.id,
            audit_key,
        )
        db.commit()
    return result
