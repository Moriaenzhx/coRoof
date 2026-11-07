"""Synthetic spreadsheet imports keep source positions and existing document ACLs."""

import base64
import io
import zipfile
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

from app.modules.knowledge.importer import parse
from app.modules.knowledge.schemas import ImportInput


def raw_book(workbook):
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def payload(name, data):
    return ImportInput(
        title="合成表格验收",
        file_name=name,
        file_base64=base64.b64encode(data).decode(),
        idempotency_key=uuid4(),
    )


def extract(name, data):
    original, content = parse(payload(name, data))
    assert original == data
    return content


def rejected(name, data, code):
    with pytest.raises(HTTPException) as error:
        parse(payload(name, data))
    assert error.value.status_code == 400
    assert error.value.detail["code"] == code
    return error.value.detail["message"]


def alter_archive(data, path, replacement):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            target.writestr(name, replacement(content) if name == path else content)
    return output.getvalue()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "gb18030"])
def test_csv_encodings_quoted_delimiters_multiline_and_identifiers(encoding):
    content = extract(
        "legacy.csv",
        '客户,编号,备注,金额\r\n星桥,000012,"含,逗号\r\n下一行",0\r\n'.encode(encoding),
    )
    assert 'A: "星桥" | B: "000012"' in content
    assert 'C: "含,逗号\\r\\n下一行" | D: "0"' in content
    assert "原文件第 2–3 行" in content
    assert "尚未核对为业务台账" in content
    assert ("GB18030" in content) == (encoding == "gb18030")


@pytest.mark.parametrize("delimiter", [";", "\t"])
def test_csv_export_delimiters_and_blanks_preserve_positions(delimiter):
    text = delimiter.join(["客户", "备注", "编号"]) + "\n"
    text += delimiter.join(["测试公司", "", "003"]) + "\n"
    content = extract("export.csv", text.encode())
    assert 'A: "测试公司" | B: [空白] | C: "003"' in content


def test_csv_single_column_and_formula_remain_text():
    content = extract("single.csv", b"code\n001\n=1+1\n")
    assert 'A: "001"' in content
    assert '[公式文本，未计算] "=1+1"' in content


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"a,b\n1,2,3\n", "csv_structure"),
        (b'a,b\n1,"never closed\n', "csv_structure"),
        (b"a\x00,b\n1,2\n", "csv_encoding"),
        (b"\xff\xfe\x00", "csv_encoding"),
        (b"\n\n", "spreadsheet_empty"),
        (("a,b\n" + "1,2\n" * 2000).encode(), "spreadsheet_limit"),
        ((",".join(["x"] * 101) + "\n").encode(), "spreadsheet_limit"),
    ],
)
def test_csv_errors_are_explicit_without_partial_import(raw, code):
    rejected("broken.csv", raw, code)


def test_xlsx_multiple_sheets_dates_gaps_formulas_and_error_values():
    workbook = Workbook()
    first = workbook.active
    first.title = "销售清单"
    first.append(["客户", "编号", "日期", "金额"])
    first.append(["合成客户", "000123", date(2026, 11, 6), 12.5])
    first["D4"] = "=SUM(D2:D3)"
    first["B5"] = "#DIV/0!"
    second = workbook.create_sheet("交付记录")
    second["C3"] = "模拟交付依据"
    content = extract("legacy.xlsx", raw_book(workbook))
    assert '工作表："销售清单"' in content and '工作表："交付记录"' in content
    assert 'B: "000123"' in content and "2026-11-06" in content
    assert "第 4 行：A: [空白] | B: [空白] | C: [空白] | D: [公式文本，未计算]" in content
    assert '[Excel 错误值] "#DIV/0!"' in content
    assert '第 3 行：A: [空白] | B: [空白] | C: "模拟交付依据"' in content


@pytest.mark.parametrize("kind", ["sheet", "very_hidden", "row", "column", "name"])
def test_hidden_content_is_rejected_including_original_file(kind):
    workbook = Workbook()
    workbook.active["A1"] = "可见资料"
    if kind in {"sheet", "very_hidden"}:
        hidden = workbook.create_sheet("私人工作表")
        hidden["A1"] = "不能进入共享原件"
        hidden.sheet_state = "hidden" if kind == "sheet" else "veryHidden"
    elif kind == "row":
        workbook.active.row_dimensions[2].hidden = True
    elif kind == "column":
        workbook.active.column_dimensions["C"].hidden = True
    else:
        workbook.defined_names.add(DefinedName("private_name", attr_text='"secret"', hidden=True))
    message = rejected("hidden.xlsx", raw_book(workbook), "spreadsheet_hidden")
    assert "可分享副本" in message and "secret" not in message


def test_external_relationships_are_rejected_without_network_access():
    workbook = Workbook()
    workbook.active["A1"] = "外部链接"
    workbook.active["A1"].hyperlink = "https://invalid.example/confidential"
    rejected("links.xlsx", raw_book(workbook), "spreadsheet_active")


@pytest.mark.parametrize("path", ["xl/vbaProject.bin", "xl/embeddings/oleObject1.bin"])
def test_disguised_active_content_is_rejected(path):
    workbook = Workbook()
    workbook.active["A1"] = "合成数据"
    output = io.BytesIO(raw_book(workbook))
    with zipfile.ZipFile(output, "a") as archive:
        archive.writestr(path, b"synthetic")
    rejected("ordinary.xlsx", output.getvalue(), "spreadsheet_active")


def test_xlsx_does_not_trust_understated_dimensions_or_recalculate():
    workbook = Workbook()
    workbook.active["A1"] = "标题"
    workbook.active["B3"] = "不可丢失的第三行"
    data = alter_archive(
        raw_book(workbook),
        "xl/worksheets/sheet1.xml",
        lambda value: value.replace(b'ref="A1:B3"', b'ref="A1:A1"'),
    )
    assert '第 3 行：A: [空白] | B: "不可丢失的第三行"' in extract("dimensions.xlsx", data)


@pytest.mark.parametrize("coordinate", ["A2001", "CW1"])
def test_xlsx_sparse_ranges_are_rejected_before_iteration(coordinate):
    workbook = Workbook()
    workbook.active[coordinate] = "超出范围的合成数据"
    rejected("sparse.xlsx", raw_book(workbook), "spreadsheet_limit")


def test_xlsx_empty_and_old_xls_are_explicitly_rejected():
    rejected("empty.xlsx", raw_book(Workbook()), "spreadsheet_empty")
    message = rejected("old.xls", b"legacy", "unsupported_file")
    assert "XLSX 或 CSV" in message


def test_spreadsheet_draft_publish_and_original_download_obey_acl(loop):
    boss, employee, *_ = loop
    data = "客户,订单\n合成星桥,TEST-00001\n".encode()
    body = {
        "title": "模拟旧系统导出",
        "file_name": "legacy.csv",
        "file_base64": base64.b64encode(data).decode(),
        "idempotency_key": str(uuid4()),
        "visibility": "organization",
    }
    document = boss.post("/knowledge/import", body, 201)
    assert boss.post("/knowledge/import", body, 201)["id"] == document["id"]
    assert employee.get("/knowledge/search?q=TEST-00001")["total"] == 0
    employee.get(f"/knowledge/documents/{document['id']}", 404)
    published = boss.post(
        f"/knowledge/documents/{document['id']}/publish",
        {
            "expected_version": document["version"],
            "revision_id": document["draft_id"],
            "confirm": True,
            "idempotency_key": str(uuid4()),
        },
    )
    assert employee.get("/knowledge/search?q=TEST-00001")["total"] > 0
    original = employee.request(
        "GET",
        f"/knowledge/documents/{document['id']}/revisions/{published['published_id']}/file",
    )
    assert original.content == data
    boss.post(
        f"/knowledge/documents/{document['id']}/action",
        {
            "expected_version": published["version"],
            "action": "withdraw",
            "confirm": True,
            "idempotency_key": str(uuid4()),
        },
    )
    employee.get(f"/knowledge/documents/{document['id']}", 404)
    assert employee.get("/knowledge/search?q=TEST-00001")["total"] == 0
