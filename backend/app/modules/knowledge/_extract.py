"""Isolated file parser. No network or application imports; JSON over stdio only."""

import csv
import io
import json
import resource
import sys
import zipfile
from datetime import date, datetime, time


class SpreadsheetError(ValueError):
    """Only fixed, non-sensitive error codes cross the subprocess boundary."""


SHEET_LIMIT = 20
ROW_LIMIT = 2_000
COLUMN_LIMIT = 100
CELL_LIMIT = 20_000
TEXT_LIMIT = 120_000


def spreadsheet_prefix(kind: str) -> str:
    return (
        f"表格来源：{kind}。以下为原始资料摘录，尚未核对为业务台账。\n"
        "保留原始行号和列位置；空白不代表零。数字为原始值，日期为 ISO 格式，"
        "不复现数字显示格式。公式只显示文本、不计算；不会访问外部内容。\n"
    )


def cell_text(value: object, formula: bool = False) -> str:
    if value is None or value == "":
        return "[空白]"
    if isinstance(value, (datetime, date, time)):
        text = value.isoformat()
    elif isinstance(value, bool):
        text = "TRUE" if value else "FALSE"
    else:
        text = str(value)
    if len(text) > 8_000 or "\x00" in text:
        raise SpreadsheetError("spreadsheet_limit")
    # JSON quoting keeps embedded newlines and delimiters inside their original cell.
    rendered = json.dumps(text, ensure_ascii=False)
    return ("[公式文本，未计算] " if formula else "") + rendered


def column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def csv_extract(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "UTF-16 BOM"
        try:
            text = data.decode("utf-16")
        except UnicodeError as exc:
            raise SpreadsheetError("csv_encoding") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
            encoding = "UTF-8"
        except UnicodeDecodeError:
            try:
                text = data.decode("gb18030")
                encoding = "GB18030（请核对中文是否正确）"
            except UnicodeError as exc:
                raise SpreadsheetError("csv_encoding") from exc
    if "\x00" in text:
        raise SpreadsheetError("csv_encoding")
    csv.field_size_limit(8_000)
    try:
        dialect = csv.Sniffer().sniff(text[:65_536], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        # A single-column export needs no delimiter; ambiguous multi-column data is rejected.
        if any(char in text for char in ",;\t"):
            raise SpreadsheetError("csv_structure") from None
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    delimiter_label = {",": "逗号", ";": "分号", "\t": "制表符"}[delimiter]
    parts = [spreadsheet_prefix(f"CSV；编码 {encoding}；分隔符 {delimiter_label}")]
    width = 0
    records = 0
    cells = 0
    length = len(parts[0])
    prior_line = 0
    try:
        for row in reader:
            first_line = prior_line + 1
            prior_line = reader.line_num
            if not row or all(value == "" for value in row):
                continue
            records += 1
            cells += len(row)
            if records > ROW_LIMIT or len(row) > COLUMN_LIMIT or cells > CELL_LIMIT:
                raise SpreadsheetError("spreadsheet_limit")
            if not width:
                width = len(row)
            elif width != len(row):
                raise SpreadsheetError("csv_structure")
            line = " | ".join(
                f"{column_name(index)}: {cell_text(value, value.startswith('='))}"
                for index, value in enumerate(row, 1)
            )
            span = (
                str(first_line)
                if first_line == reader.line_num
                else f"{first_line}–{reader.line_num}"
            )
            line = f"第 {records} 条（原文件第 {span} 行）：{line}"
            length += len(line) + 1
            if length > TEXT_LIMIT:
                raise SpreadsheetError("spreadsheet_limit")
            parts.append(line)
    except csv.Error as exc:
        raise SpreadsheetError("csv_structure") from exc
    if records == 0:
        raise SpreadsheetError("spreadsheet_empty")
    return "\n".join(parts)


def check_xlsx_archive(data: bytes) -> None:
    from defusedxml import ElementTree
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = archive.infolist()
        if len(files) > 200 or sum(item.file_size for item in files) > 8_000_000:
            raise SpreadsheetError("spreadsheet_limit")
        cells = 0
        rows = 0
        for item in files:
            name = item.filename.lower()
            if item.flag_bits & 1 or any(
                marker in name for marker in ("vba", "activex", "embeddings/", "externallinks/")
            ):
                raise SpreadsheetError("spreadsheet_active")
            if not name.endswith((".xml", ".rels")):
                continue
            root = ElementTree.fromstring(archive.read(item))
            for node in root.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if (
                    node.get("hidden") in {"1", "true"}
                    or node.get("zeroHeight") in {"1", "true"}
                    or node.get("state") in {"hidden", "veryHidden"}
                ):
                    # The original file is downloadable; omitting hidden text alone is unsafe.
                    raise SpreadsheetError("spreadsheet_hidden")
                if (
                    node.get("TargetMode", "").lower() == "external"
                    or "macroenabled" in node.get("ContentType", "").lower()
                ):
                    raise SpreadsheetError("spreadsheet_active")
                if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                    if tag == "row":
                        rows += 1
                        if rows > ROW_LIMIT or int(node.get("r", "0")) > ROW_LIMIT:
                            raise SpreadsheetError("spreadsheet_limit")
                    elif tag == "c":
                        cells += 1
                        coordinate = node.get("r")
                        if coordinate:
                            column, row = coordinate_from_string(coordinate)
                            if column_index_from_string(column) > COLUMN_LIMIT or row > ROW_LIMIT:
                                raise SpreadsheetError("spreadsheet_limit")
                        if cells > CELL_LIMIT:
                            raise SpreadsheetError("spreadsheet_limit")


def xlsx_extract(data: bytes) -> str:
    from openpyxl import load_workbook

    check_xlsx_archive(data)
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        if len(workbook.sheetnames) > SHEET_LIMIT:
            raise SpreadsheetError("spreadsheet_limit")
        parts = [spreadsheet_prefix("Excel XLSX")]
        length = len(parts[0])
        cells = 0
        rows = 0
        nonempty = False
        for sheet in workbook.worksheets:
            parts.append(f"\n工作表：{json.dumps(sheet.title, ensure_ascii=False)}")
            length += len(parts[-1]) + 1
            # Do not trust producer-supplied dimensions, which may under-report actual data.
            sheet.reset_dimensions()
            for row_number, row in enumerate(sheet.iter_rows(), 1):
                rows += 1
                cells += len(row)
                if rows > ROW_LIMIT or len(row) > COLUMN_LIMIT or cells > CELL_LIMIT:
                    raise SpreadsheetError("spreadsheet_limit")
                if all(cell.value is None for cell in row):
                    continue
                nonempty = True
                values = []
                for index, cell in enumerate(row, 1):
                    value = cell.value
                    formula = cell.data_type == "f"
                    if formula and not isinstance(value, str):
                        value = "[数组或数据表公式，请在原表核对]"
                    rendered = cell_text(value, formula)
                    if cell.data_type == "e":
                        rendered = "[Excel 错误值] " + rendered
                    values.append(f"{column_name(index)}: {rendered}")
                line = f"第 {row_number} 行：" + " | ".join(values)
                length += len(line) + 1
                if length > TEXT_LIMIT:
                    raise SpreadsheetError("spreadsheet_limit")
                parts.append(line)
        if not nonempty:
            raise SpreadsheetError("spreadsheet_empty")
        return "\n".join(parts)
    finally:
        workbook.close()


def extract(data: bytes, suffix: str) -> str:
    if suffix == "csv":
        return csv_extract(data)
    if suffix == "xlsx":
        return xlsx_extract(data)
    if suffix in {"txt", "md"}:
        return data.decode("utf-8-sig")
    if suffix == "docx":
        from docx import Document
        from docx.text.paragraph import Paragraph

        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = archive.infolist()
            if (
                len(files) > 200
                or sum(item.file_size for item in files) > 8_000_000
                or any("vba" in item.filename.lower() or item.flag_bits & 1 for item in files)
            ):
                raise ValueError("archive_limit")
        document = Document(io.BytesIO(data))
        parts = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                parts.append(block.text)
            else:
                parts.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
        return "\n".join(parts)
    if suffix == "pdf":
        from pypdf import PdfReader, filters

        filters.ZLIB_MAX_OUTPUT_LENGTH = 2_000_000
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("pdf_limit")
        parts = []
        length = 0
        for page in reader.pages:
            content = page.get_contents()
            if content is not None and len(content.get_data()) > 2_000_000:
                raise ValueError("pdf_stream_limit")
            value = page.extract_text()
            length += len(value)
            if length > 120_000:
                raise ValueError("text_limit")
            parts.append(value)
        return "\n\n".join(parts)
    raise ValueError("unsupported_format")


if __name__ == "__main__":
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        raw = sys.stdin.buffer.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("file_limit")
        content = extract(raw, sys.argv[1]).strip()
        if not content or len(content) > 120_000 or "\x00" in content:
            raise ValueError("unsupported_content")
        print(json.dumps({"content": content}))
    except SpreadsheetError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception:
        # Parsing errors may contain original content; never relay them to logs or clients.
        print(json.dumps({"error": "file_not_supported"}))
        sys.exit(1)
