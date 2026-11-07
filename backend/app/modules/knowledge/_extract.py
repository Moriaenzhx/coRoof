"""Isolated file parser. No network or application imports; JSON over stdio only."""

import io
import json
import resource
import sys
import zipfile


def extract(data: bytes, suffix: str) -> str:
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
    except Exception:
        # Parsing errors may contain original content; never relay them to logs or clients.
        print(json.dumps({"error": "file_not_supported"}))
        sys.exit(1)
