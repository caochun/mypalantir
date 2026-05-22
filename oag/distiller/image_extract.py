from __future__ import annotations

import base64
import logging
import re
from pathlib import Path

from .llm import DistillerLLM

log = logging.getLogger(__name__)

IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

TABLE_EXTRACT_PROMPT = """\
这张图片是一份技术文档中的表格。请将表格内容完整转换为 Markdown 表格格式。

要求：
- 保留所有行和列，不要遗漏
- 保持原文用词，不要改写或概括
- 如果有合并单元格，用文字说明
- 如果图片不是表格（如流程图、示意图），用文字描述其内容

直接输出 Markdown 表格，不要加解释。"""


def find_image_file(md_file: Path, ref_path: str) -> Path | None:
    doc_dir = md_file.parent
    direct = doc_dir / ref_path
    if direct.exists():
        return direct

    filename = Path(ref_path).name
    for img_dir in doc_dir.iterdir():
        if img_dir.is_dir() and img_dir.name.startswith("images"):
            candidate = img_dir / filename
            if candidate.exists():
                return candidate
    return None


def extract_tables_from_images(
    md_file: Path,
    llm: DistillerLLM,
) -> str:
    text = md_file.read_text(encoding="utf-8")
    refs = list(IMAGE_REF_RE.finditer(text))
    if not refs:
        log.info("%s: no image references found", md_file.name)
        return text

    log.info("%s: found %d image references", md_file.name, len(refs))
    replacements: list[tuple[str, str]] = []

    for match in refs:
        alt_text = match.group(1)
        ref_path = match.group(2)
        full_match = match.group(0)

        img_path = find_image_file(md_file, ref_path)
        if not img_path:
            log.warning("  Image not found: %s", ref_path)
            continue

        log.info("  Processing: %s", img_path.name)
        table_md = _image_to_markdown(llm, img_path)
        replacements.append((full_match, table_md))

    for old, new in replacements:
        text = text.replace(old, new, 1)

    return text


def _image_to_markdown(llm: DistillerLLM, img_path: Path) -> str:
    img_data = base64.b64encode(img_path.read_bytes()).decode()
    suffix = img_path.suffix.lower().lstrip(".")
    media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(suffix, "image/jpeg")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": TABLE_EXTRACT_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{img_data}"}},
            ],
        }
    ]
    return llm.chat(messages, temperature=0.1)


def process_domain_images(docs_dir: Path, llm: DistillerLLM, dry_run: bool = False) -> dict[str, int]:
    results = {}
    for md_file in sorted(docs_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        ref_count = len(IMAGE_REF_RE.findall(text))
        if ref_count == 0:
            continue

        log.info("Processing %s (%d images)", md_file.name, ref_count)
        new_text = extract_tables_from_images(md_file, llm)

        if new_text != text:
            if dry_run:
                log.info("  [dry-run] Would update %s", md_file.name)
            else:
                md_file.write_text(new_text, encoding="utf-8")
                log.info("  Updated %s", md_file.name)
            results[md_file.name] = ref_count

    return results
