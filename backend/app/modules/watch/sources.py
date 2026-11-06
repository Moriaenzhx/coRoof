"""Evidence/configuration fingerprints and source freshness for background reads."""

import hashlib
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.infrastructure.models import AIConnection, AISettings, Membership, WorkItem, now, utc
from app.modules.agent.capabilities import scope_hash
from app.modules.connectors.models import Connector, SourceLink
from app.modules.watch.models import WatchPolicy
from app.modules.watch.service import fingerprint


def source_stamp(db: Session, work: WorkItem) -> tuple[str | None, dict[str, Any]]:
    if work.source_authority == "native":
        return None, {"kind": "native"}
    result = db.execute(
        select(SourceLink, Connector)
        .join(
            Connector,
            (Connector.organization_id == SourceLink.organization_id)
            & (Connector.id == SourceLink.connector_id),
        )
        .where(
            SourceLink.organization_id == work.organization_id, SourceLink.work_item_id == work.id
        )
    ).first()
    if result is None:
        return "source_unavailable", {"kind": "external", "available": False}
    link, connector = result
    stamp = {
        "kind": "external",
        "link": link.id,
        "record": link.record_id,
        "connector": connector.id,
        "state": connector.state,
        "error": connector.last_error,
    }
    if link.state != "linked" or connector.state != "active" or connector.last_error:
        return "source_unavailable", stamp
    if connector.synced_at is None or utc(connector.synced_at) < now() - timedelta(hours=24):
        return "source_stale", stamp
    return None, stamp


def model_stamp(db: Session, actor: Membership, cfg: Settings) -> dict[str, Any]:
    config = db.scalar(
        select(AISettings).where(AISettings.organization_id == actor.organization_id)
    )
    connection = (
        db.get(AIConnection, config.connection_id) if config and config.connection_id else None
    )
    return {
        "provider": cfg.ai_provider,
        "model": cfg.ai_model,
        "endpoint": cfg.ai_base_url,
        "verified": cfg.ai_model_verified,
        "revision": config.version if config else 0,
        "connection_version": connection.version if connection else None,
        "connection_state": connection.state if connection else None,
        "credential_fingerprint": hashlib.sha256(
            cfg.ai_api_key.get_secret_value().encode()
        ).hexdigest(),
    }


def context_hash(
    db: Session, actor: Membership, policy: WatchPolicy, work: WorkItem, cfg: Settings
) -> str:
    _, source = source_stamp(db, work)
    return fingerprint(
        {
            "policy_version": policy.version,
            "source": source,
            "scope": scope_hash(db, actor, work.id, include_events=True),
            "model": model_stamp(db, actor, cfg),
        }
    )
