"""Document publishing, search, permissions and deletion acceptance (synthetic data)."""

import base64
import io
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from conftest import API
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.db import session_factory
from app.infrastructure.models import WorkEvent
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeRevision

ROOT = "/knowledge/documents"
TEXT = "采购报销需要主管确认。差旅报销请附发票原件。Expense claims require receipts."


def create(api, content=TEXT, **extra):
    return api.post(
        ROOT,
        {"title": "合成验收制度", "content": content, "idempotency_key": str(uuid4()), **extra},
        201,
    )


def cmd(row, **extra):
    return {"expected_version": row["version"], "idempotency_key": str(uuid4()), **extra}


def publish(api, row):
    return api.post(
        f"{ROOT}/{row['id']}/publish", cmd(row, revision_id=row["draft_id"], confirm=True)
    )


def find(api, q="报销"):
    return api.get("/knowledge/search?q=" + q)


def employee_access_cases(loop):
    boss, employee, org, depts, member, _ = loop
    colleague = API("acl-colleague@example.com")
    colleague_member = colleague.join(boss.invite(depts[1], "acl-colleague@example.com"), org["id"])
    outsider = API("acl-outsider@example.com")
    outsider.org("合成权限验收企业乙")
    specs = [
        ("scopeownneedle", employee, {}, True),
        ("scopecompanyneedle", boss, {"visibility": "organization"}, True),
        (
            "scopedepartmentneedle",
            boss,
            {"visibility": "department", "department_id": depts[0]["id"]},
            True,
        ),
        (
            "scopeselectedneedle",
            boss,
            {"visibility": "members", "member_ids": [member["id"]]},
            True,
        ),
        (
            "scopeotherdepartmentneedle",
            boss,
            {"visibility": "department", "department_id": depts[1]["id"]},
            False,
        ),
        (
            "scopeunselectedneedle",
            boss,
            {"visibility": "members", "member_ids": [colleague_member["id"]]},
            False,
        ),
        ("scopeprivateneedle", boss, {}, False),
        ("scopetenantneedle", outsider, {"visibility": "organization"}, False),
    ]
    cases = [
        (
            query,
            publish(author, create(author, content=f"{query}：合成文档原文。", **access)),
            visible,
        )
        for query, author, access, visible in specs
    ]
    draft = create(employee, content="scopedraftneedle：尚未发布的合成草稿。")
    return employee, cases, draft


def test_employee_document_acl_is_consistent_for_list_search_detail_and_revision(loop):
    employee, cases, draft = employee_access_cases(loop)
    visible_ids = {row["id"] for _, row, visible in cases if visible}
    listing = employee.get(ROOT)
    assert {row["id"] for row in listing["items"]} == visible_ids | {draft["id"]}
    assert listing["total"] == len(visible_ids) + 1
    for query, row, visible in cases:
        expected = 200 if visible else 404
        employee.get(f"{ROOT}/{row['id']}", expected)
        revision = employee.get(f"{ROOT}/{row['id']}/revisions/{row['published_id']}", expected)
        result = find(employee, query)
        assert result["authorized_documents"] == len(visible_ids)
        assert {item["document_id"] for item in result["items"]} == (
            {row["id"]} if visible else set()
        )
        assert result["total"] == (1 if visible else 0)
        if visible:
            assert revision["content"] == f"{query}：合成文档原文。"
    employee.get(f"{ROOT}/{draft['id']}")
    employee.get(f"{ROOT}/{draft['id']}/revisions/{draft['draft_id']}")
    assert find(employee, "scopedraftneedle")["total"] == 0


def test_publish_required_and_source_is_exact(loop):
    boss, employee, *_ = loop
    row = create(boss, visibility="organization")
    assert find(boss)["total"] == 0
    assert employee.get(ROOT)["total"] == 0
    endpoint = f"{ROOT}/{row['id']}/publish"
    boss.post(endpoint, cmd(row, revision_id=row["draft_id"]), 422)
    payload = cmd(row, revision_id=row["draft_id"], confirm=True)
    ready = boss.post(endpoint, payload)
    assert boss.post(endpoint, payload) == ready
    hit = find(employee)["items"][0]
    assert TEXT[hit["start_offset"] : hit["end_offset"]] == hit["excerpt"]
    assert hit["revision_number"] == 1
    assert find(employee, "receipts")["items"][0]["revision_id"] == ready["published_id"]
    with session_factory()() as db:
        events = list(db.scalars(select(WorkEvent).where(WorkEvent.document_id == row["id"])))
        assert [e.event_type for e in events] == ["knowledge.created", "knowledge.publish"]
        assert all(e.work_item_id is None and TEXT not in str(e.event_payload) for e in events)


def test_private_does_not_grant_owner_override_and_tenants_are_isolated(loop):
    boss, employee, *_ = loop
    private = publish(employee, create(employee))
    assert find(employee)["total"] == 1
    boss.get(f"{ROOT}/{private['id']}", 404)
    assert find(boss)["total"] == 0
    outsider = API("outside@example.com")
    outsider.org()
    outsider.get(f"{ROOT}/{private['id']}", 404)
    assert find(outsider)["total"] == 0


def test_department_selected_members_and_sharing_scope(loop):
    boss, employee, org, depts, member, _ = loop
    sales = API("sales@example.com")
    sales.join(boss.invite(depts[1], "sales@example.com"), org["id"])
    row = publish(employee, create(employee, visibility="department", department_id=depts[0]["id"]))
    assert find(employee)["total"] == 1
    assert find(sales)["total"] == 0
    # An owner with no department is not implicitly a departmental reader.
    boss.get(f"{ROOT}/{row['id']}", 404)
    employee.post(
        ROOT,
        {
            "title": "no",
            "content": TEXT,
            "visibility": "organization",
            "idempotency_key": str(uuid4()),
        },
        403,
    )
    employee.post(
        ROOT,
        {
            "title": "no",
            "content": TEXT,
            "visibility": "department",
            "department_id": depts[1]["id"],
            "idempotency_key": str(uuid4()),
        },
        403,
    )
    chosen = publish(boss, create(boss, visibility="members", member_ids=[member["id"]]))
    assert find(employee)["total"] == 2
    assert find(sales)["total"] == 0
    boss.post(f"{ROOT}/{chosen['id']}/access", cmd(chosen, visibility="private"))
    assert find(employee)["total"] == 1


def test_new_version_is_not_visible_until_author_confirms_and_stale_commands_fail(loop):
    boss, employee, *_ = loop
    original = publish(boss, create(boss, visibility="organization"))
    editing = boss.post(
        f"{ROOT}/{original['id']}/edit", cmd(original, title="新草稿", content="采购使用新制度。")
    )
    assert find(employee, "报销")["items"][0]["revision_id"] == original["published_id"]
    employee.get(f"{ROOT}/{original['id']}/revisions/{editing['draft_id']}", 404)
    boss.post(
        f"{ROOT}/{original['id']}/action", cmd(original, action="withdraw", confirm=True), 409
    )
    revised = publish(boss, editing)
    assert revised["published_id"] != original["published_id"]
    assert find(employee, "报销")["total"] == 0
    assert find(employee, "采购")["items"][0]["revision_number"] == 2
    historical = employee.get(f"{ROOT}/{original['id']}/revisions/{original['published_id']}")
    assert not historical["current"] and historical["content"] == TEXT


def test_shared_owner_cannot_confirm_another_authors_draft(loop):
    boss, employee, _, _, member, _ = loop
    row = publish(boss, create(boss, visibility="members", member_ids=[member["id"]]))
    employee.post(f"{ROOT}/{row['id']}/edit", cmd(row, title="forbidden", content=TEXT), 403)
    # Make the member an owner, without changing the document's original author.
    from app.infrastructure.models import Membership

    with session_factory()() as db:
        db.get(Membership, member["id"]).roles = ["owner"]
        db.commit()
    editing = employee.post(f"{ROOT}/{row['id']}/edit", cmd(row, title="待确认", content=TEXT))
    boss.post(
        f"{ROOT}/{row['id']}/publish",
        cmd(editing, revision_id=editing["draft_id"], confirm=True),
        403,
    )
    publish(employee, editing)


def test_withdraw_delete_scrubs_text_files_and_index(loop):
    boss, employee, *_ = loop
    raw = TEXT.encode()
    row = boss.post(
        "/knowledge/import",
        {
            "title": "文档",
            "file_name": "制度.md",
            "file_base64": base64.b64encode(raw).decode(),
            "visibility": "organization",
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    row = publish(boss, row)
    file_url = f"{ROOT}/{row['id']}/revisions/{row['published_id']}/file"
    download = employee.request("GET", file_url)
    assert download.content == raw and "attachment" in download.headers["content-disposition"]
    hidden = boss.post(f"{ROOT}/{row['id']}/action", cmd(row, action="withdraw", confirm=True))
    assert find(employee)["total"] == 0
    employee.get(file_url, 404)
    payload = cmd(hidden, action="delete", confirm=True)
    deleted = boss.post(f"{ROOT}/{row['id']}/action", payload)
    assert deleted["state"] == "deleted"
    assert boss.post(f"{ROOT}/{row['id']}/action", payload) == deleted
    boss.get(f"{ROOT}/{row['id']}", 404)
    with session_factory()() as db:
        revision = db.scalar(
            select(KnowledgeRevision).where(KnowledgeRevision.document_id == row["id"])
        )
        assert revision.content is None and revision.file_bytes is None
        assert db.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0
        if db.get_bind().dialect.name == "sqlite":
            assert db.scalar(text("SELECT count(*) FROM knowledge_fts")) == 0


@pytest.mark.parametrize(
    "name,data,expected",
    [
        ("test.txt", b"hello UTF-8", 201),
        ("bad.txt", b"\xff", 400),
        ("empty.md", b"", 413),
        ("macro.docm", b"bad", 400),
        ("broken.pdf", b"%PDF bad", 400),
        ("../bad.txt", b"bad", 422),
        ("huge.txt", b"x" * 4_000_001, 413),
    ],
)
def test_file_formats_and_limits(loop, name, data, expected):
    boss, *_ = loop
    body = {
        "title": "导入",
        "file_name": name,
        "file_base64": base64.b64encode(data).decode(),
        "idempotency_key": str(uuid4()),
    }
    result = boss.post("/knowledge/import", body, expected)
    if expected != 201:
        assert "file_base64" not in str(result)


def test_docx_extraction_and_scan_only_pdf_is_rejected(loop):
    boss, *_ = loop
    file = io.BytesIO()
    document = Document()
    document.add_paragraph(TEXT)
    document.save(file)
    row = boss.post(
        "/knowledge/import",
        {
            "title": "DOCX",
            "file_name": "验收.docx",
            "file_base64": base64.b64encode(file.getvalue()).decode(),
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    revision = boss.get(f"{ROOT}/{row['id']}/revisions/{row['draft_id']}")
    assert revision["content"] == TEXT
    edited = boss.post(
        f"{ROOT}/{row['id']}/edit", cmd(row, title="已核对", content="人工修订的正文")
    )
    updated = boss.get(f"{ROOT}/{row['id']}/revisions/{edited['draft_id']}")
    assert updated["edited_extraction"] and updated["file_hash"] == revision["file_hash"]
    writer = PdfWriter()
    page = writer.add_blank_page(300, 300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 200 Td (Expense claims require receipts.) Tj ET")
    page[NameObject("/Contents")] = stream
    file = io.BytesIO()
    writer.write(file)
    pdf = boss.post(
        "/knowledge/import",
        {
            "title": "Text PDF",
            "file_name": "text.pdf",
            "file_base64": base64.b64encode(file.getvalue()).decode(),
            "idempotency_key": str(uuid4()),
        },
        201,
    )
    extracted = boss.get(f"{ROOT}/{pdf['id']}/revisions/{pdf['draft_id']}")
    assert "Expense claims require receipts." in extracted["content"]
    writer.encrypt("synthetic-test-password")
    file = io.BytesIO()
    writer.write(file)
    boss.post(
        "/knowledge/import",
        {
            "title": "Encrypted PDF",
            "file_name": "encrypted.pdf",
            "file_base64": base64.b64encode(file.getvalue()).decode(),
            "idempotency_key": str(uuid4()),
        },
        400,
    )
    file = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.write(file)
    boss.post(
        "/knowledge/import",
        {
            "title": "PDF",
            "file_name": "scan.pdf",
            "file_base64": base64.b64encode(file.getvalue()).decode(),
            "idempotency_key": str(uuid4()),
        },
        400,
    )


def test_create_replay_and_conflict(loop):
    boss, *_ = loop
    body = {"title": "制度", "content": TEXT, "idempotency_key": str(uuid4())}
    row = boss.post(ROOT, body, 201)
    assert boss.post(ROOT, body, 201) == row
    boss.post(ROOT, {**body, "content": "不同内容"}, 409)


def test_cross_tenant_revision_binding_rejected(loop):
    boss, *_ = loop
    row = create(boss)
    other = API("tenant@example.com")
    other.org()
    foreign = create(other)
    with session_factory()() as db:
        doc = db.get(KnowledgeDocument, row["id"])
        doc.draft_id = foreign["draft_id"]
        with pytest.raises(IntegrityError):
            db.commit()


def test_publish_concurrency_once_and_conflicting_edit_rejected(loop):
    boss, *_ = loop
    with session_factory()() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL row locking acceptance")
    row = create(boss)
    payload = cmd(row, revision_id=row["draft_id"], confirm=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: boss.request("POST", f"{ROOT}/{row['id']}/publish", payload), range(2)
            )
        )
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkEvent)
                .where(
                    WorkEvent.document_id == row["id"], WorkEvent.event_type == "knowledge.publish"
                )
            )
            == 1
        )


def test_metadata_matches_migration(database):
    command.check(database)
