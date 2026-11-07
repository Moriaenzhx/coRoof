"""Synthetic file previews: no persistence and no cross-author file oracle."""

import base64
import hashlib
from uuid import uuid4

from sqlalchemy import func, select

from app.infrastructure.db import session_factory
from app.infrastructure.models import WorkEvent
from app.modules.knowledge.models import KnowledgeDocument


def payload(**extra):
    return {
        "title": "合成旧系统导出资料",
        "file_name": "合成测试.txt",
        "file_base64": base64.b64encode("合成订单编号001；金额未核对".encode()).decode(),
        "idempotency_key": str(uuid4()),
        **extra,
    }


def counts():
    with session_factory()() as db:
        return (
            db.scalar(select(func.count()).select_from(KnowledgeDocument)),
            db.scalar(select(func.count()).select_from(WorkEvent)),
        )


def test_preview_does_not_persist_and_same_file_is_only_a_personal_hint(loop):
    boss, employee, *_ = loop
    body = payload()
    before = counts()
    preview = boss.post("/knowledge/import/preview", body)
    assert counts() == before
    assert preview["file_hash"] == hashlib.sha256(base64.b64decode(body["file_base64"])).hexdigest()
    assert preview["content"] == "合成订单编号001；金额未核对"
    assert preview["duplicate_document_id"] is None
    row = boss.post("/knowledge/import", body, 201)
    assert row["state"] == "draft" and row["published_id"] is None
    # Filename and idempotency key do not defeat the file-content hint.
    repeated = boss.post("/knowledge/import/preview", payload(file_name="重新导出的文件.txt"))
    assert repeated["duplicate_document_id"] == row["id"]
    assert repeated["duplicate_title"] == body["title"]
    assert employee.post("/knowledge/import/preview", body)["duplicate_document_id"] is None
    after = counts()
    assert boss.post("/knowledge/import", body, 201)["id"] == row["id"]
    assert counts() == after


def test_preview_rejects_invalid_share_and_parser_failure_without_writing(loop):
    boss, employee, *_ = loop
    before = counts()
    employee.post("/knowledge/import/preview", payload(visibility="organization"), 403)
    boss.post("/knowledge/import/preview", payload(file_name="不支持.xls"), 400)
    boss.post("/knowledge/import/preview", payload(file_base64="not base64"), 400)
    assert counts() == before


def test_deleted_file_is_not_reported_as_reusable_duplicate(loop):
    boss, *_ = loop
    row = boss.post("/knowledge/import", payload(), 201)
    boss.post(
        f"/knowledge/documents/{row['id']}/action",
        {
            "expected_version": row["version"],
            "idempotency_key": str(uuid4()),
            "action": "delete",
            "confirm": True,
        },
    )
    assert boss.post("/knowledge/import/preview", payload())["duplicate_document_id"] is None
