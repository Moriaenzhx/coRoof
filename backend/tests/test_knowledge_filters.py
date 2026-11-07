"""Knowledge browsing and organizing filters stay inside the current server ACL."""

from urllib.parse import urlencode

import pytest
from test_knowledge import ROOT, TEXT, cmd, create, employee_access_cases, publish

from app.infrastructure.db import session_factory
from app.infrastructure.models import Membership


def listing(api, **query):
    return api.get(ROOT + "?" + urlencode(query))


def test_published_categories_filter_current_acl_for_list_and_search(loop):
    employee, cases, draft = employee_access_cases(loop)
    visible = [row for _, row, allowed in cases if allowed]
    assert listing(employee)["total"] == len(visible) + 1  # Existing API default is unchanged.
    published = listing(employee, view="published")
    assert {row["id"] for row in published["items"]} == {row["id"] for row in visible}
    assert draft["id"] not in {row["id"] for row in published["items"]}
    for visibility in ("organization", "department", "members", "private"):
        expected = {row["id"] for row in visible if row["visibility"] == visibility}
        page = listing(employee, view="published", visibility=visibility)
        assert page["total"] == len(expected)
        assert {row["id"] for row in page["items"]} == expected
        for query, row, allowed in cases:
            result = employee.get(
                "/knowledge/search?" + urlencode({"q": query, "visibility": visibility})
            )
            assert result["authorized_documents"] == len(expected)
            assert {item["document_id"] for item in result["items"]} == (
                {row["id"]} if allowed and row["visibility"] == visibility else set()
            )


def test_organizing_separates_own_drafts_created_and_withdrawn(loop):
    boss, employee, *_ = loop
    draft = create(employee)
    published = publish(employee, create(employee))
    editing = employee.post(
        f"{ROOT}/{published['id']}/edit", cmd(published, title="新草稿标题", content=TEXT)
    )
    withdrawn = publish(employee, create(employee))
    employee.post(
        f"{ROOT}/{withdrawn['id']}/action", cmd(withdrawn, action="withdraw", confirm=True)
    )
    publish(boss, create(boss, visibility="organization"))
    create(boss, visibility="organization")
    assert {row["id"] for row in listing(employee, view="my_drafts")["items"]} == {
        draft["id"],
        editing["id"],
    }
    assert {row["id"] for row in listing(employee, view="mine")["items"]} == {
        draft["id"],
        editing["id"],
        withdrawn["id"],
    }
    assert {row["id"] for row in listing(employee, view="my_withdrawn")["items"]} == {
        withdrawn["id"]
    }
    assert listing(boss, view="published", visibility="private")["total"] == 0
    assert listing(employee, view="published", visibility="private")["total"] == 1
    draft_search = listing(employee, view="my_drafts", q="新草稿标题")
    assert draft_search["total"] == 1
    assert draft_search["items"][0]["title"] == "新草稿标题"
    assert listing(employee, view="published", q="新草稿标题")["total"] == 0


def test_my_drafts_uses_revision_author_and_still_rechecks_visibility(loop):
    boss, employee, _, _, member, _ = loop
    row = publish(boss, create(boss, visibility="members", member_ids=[member["id"]]))
    with session_factory()() as db:
        actor = db.get(Membership, member["id"])
        assert actor is not None
        actor.roles = ["owner"]
        db.commit()
    edited = employee.post(
        f"{ROOT}/{row['id']}/edit", cmd(row, title="负责人整理的新草稿", content=TEXT)
    )
    assert listing(boss, view="my_drafts")["total"] == 0
    assert listing(employee, view="my_drafts")["items"][0]["id"] == row["id"]
    assert listing(employee, view="mine")["total"] == 0
    boss.post(f"{ROOT}/{row['id']}/access", cmd(edited, visibility="private"))
    assert listing(employee, view="my_drafts")["total"] == 0


def test_category_and_title_filter_before_count_and_pagination(loop):
    boss, employee, *_ = loop
    shared = [
        publish(boss, create(boss, title=title, visibility="organization"))
        for title in ("流程甲", "流程乙", "流程%_literal")
    ]
    create(boss, title="流程待发布", visibility="organization")
    publish(boss, create(boss, title="流程私有"))
    pages = [
        listing(employee, view="published", visibility="organization", q="流程", offset=n, limit=1)
        for n in range(4)
    ]
    assert all(page["total"] == 3 for page in pages)
    assert [len(page["items"]) for page in pages] == [1, 1, 1, 0]
    assert {row["id"] for page in pages for row in page["items"]} == {row["id"] for row in shared}
    literal = listing(employee, view="published", q="%_")
    assert literal["total"] == 1 and literal["items"][0]["id"] == shared[2]["id"]
    assert listing(employee, view="published", q="' OR 1=1 --")["total"] == 0
    hits = [
        employee.get(f"/knowledge/search?q=报销&visibility=organization&offset={n}&limit=1")
        for n in range(4)
    ]
    assert all(page["total"] == 3 and page["authorized_documents"] == 3 for page in hits)
    assert {item["document_id"] for page in hits for item in page["items"]} == {
        row["id"] for row in shared
    }
    assert hits[-1]["items"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/knowledge/documents?view=other_members_drafts",
        "/knowledge/documents?visibility=all_tenants",
        "/knowledge/search?q=资料&visibility=all_tenants",
        "/knowledge/documents?q=" + "a" * 201,
    ],
)
def test_invalid_filters_are_rejected(loop, path):
    loop[1].get(path, 422)
