import base64
import binascii
import json
import subprocess
import sys
from pathlib import Path
from threading import BoundedSemaphore

from app.core.errors import fail
from app.modules.knowledge.schemas import ImportInput

PARSERS = BoundedSemaphore(2)


def parse(payload: ImportInput) -> tuple[bytes, str]:
    suffix = Path(payload.file_name).suffix.lower().removeprefix(".")
    if suffix not in {"txt", "md", "pdf", "docx"}:
        fail("unsupported_file", "支持 TXT、Markdown、文本 PDF 和 DOCX")
    try:
        data = base64.b64decode(payload.file_base64.get_secret_value(), validate=True)
    except (ValueError, binascii.Error):
        fail("invalid_file", "文件编码无效")
    if not data or len(data) > 4_000_000:
        fail("file_limit", "文件须小于 4 MB 且不为空", 413)
    if not PARSERS.acquire(blocking=False):
        fail("parser_busy", "文件解析繁忙，请稍后重试", 429)
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("_extract.py")), suffix],
            input=data,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            fail(
                "unsupported_content",
                "无法提取文本：请检查格式、加密或文件大小；扫描 PDF 暂不支持 OCR",
            )
        content = json.loads(result.stdout).get("content")
        if not isinstance(content, str) or not content or len(content) > 120_000:
            fail("unsupported_content", "文件没有可用文本或文本过长")
        return data, content
    except (subprocess.TimeoutExpired, OSError, ValueError):
        fail("parse_failed", "文件解析失败或超时，请使用纯文本版本")
    finally:
        PARSERS.release()
