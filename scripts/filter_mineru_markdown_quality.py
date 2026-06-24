#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path


HTML_TAG_RE = re.compile(r"<[^>]+>")
TABLE_RE = re.compile(r"<table\b|\|[^\n]*\|", re.IGNORECASE)
IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
PHONE_RE = re.compile(r"(?:\+?86[- ]?)?1[3-9]\d{9}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def content_text(text: str) -> str:
    """Return markdown body without MinerU/frontmatter metadata."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2]


def informative_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        clean = re.sub(r"!\[[^\]]*]\([^)]+\)", "", line)
        clean = re.sub(r"^#+\s*", "", clean).strip()
        if clean:
            result.append(clean)
    return result


def quality_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    body = content_text(text)
    size = len(body)
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    info_lines = informative_lines(lines)
    html_tags = len(HTML_TAG_RE.findall(body))
    tables = len(TABLE_RE.findall(body))
    images = len(IMAGE_RE.findall(body))
    word_chars = len(WORD_RE.findall(body))
    cjk_chars = len(CJK_RE.findall(body))
    phones = len(PHONE_RE.findall(body))
    emails = len(EMAIL_RE.findall(body))

    if size < 120:
        reasons.append("too_short")
    if len(lines) <= 2 and size < 500:
        reasons.append("too_few_lines")
    if word_chars < 30:
        reasons.append("too_little_text")
    if cjk_chars < 20:
        reasons.append("too_little_cjk_text")
    if cjk_chars == 0 and size > 40:
        reasons.append("no_cjk_text")
    if size < 500 and cjk_chars < 30 and (phones or emails):
        reasons.append("contact_only_or_metadata")
    if len(info_lines) <= 3 and cjk_chars < 40 and size < 700:
        reasons.append("too_few_informative_lines")
    if size and html_tags >= 1000:
        reasons.append("html_tag_heavy")
    if tables >= 20:
        reasons.append("table_heavy")
    if images >= 20 and word_chars < 500:
        reasons.append("image_heavy_low_text")
    if "�" in body:
        reasons.append("replacement_chars")

    return reasons


def classify(reasons: list[str]) -> str:
    hard_bad = {
        "too_short",
        "too_few_lines",
        "too_little_text",
        "no_cjk_text",
        "contact_only_or_metadata",
        "too_few_informative_lines",
    }
    if any(reason in hard_bad for reason in reasons):
        return "bad"
    if reasons:
        return "suspect"
    return "good"


def copy_incremental(src: Path, dst: Path, overwrite: bool) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        return False
    shutil.copy2(src, dst)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split MinerU markdown files into good/suspect/bad directories."
    )
    parser.add_argument("--src", default="documents_mineru_md")
    parser.add_argument("--good", default="documents_mineru_md_good")
    parser.add_argument("--suspect", default="documents_mineru_md_suspect")
    parser.add_argument("--bad", default="documents_mineru_md_bad")
    parser.add_argument("--report", default="raw/logs/mineru_md_quality_report.csv")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    src_dir = Path(args.src)
    if not src_dir.is_dir():
        raise SystemExit(f"source directory not found: {src_dir}")

    good_dir = Path(args.good)
    suspect_dir = Path(args.suspect)
    bad_dir = Path(args.bad)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    counts = {"good": 0, "suspect": 0, "bad": 0}
    copied = 0

    rows = []
    for path in sorted(src_dir.rglob("*.md")):
        rel_path = path.relative_to(src_dir)
        text = path.read_text(encoding="utf-8", errors="ignore")
        reasons = quality_reasons(text)
        label = classify(reasons)
        counts[label] += 1

        target_root = {"good": good_dir, "suspect": suspect_dir, "bad": bad_dir}[label]
        if copy_incremental(path, target_root / rel_path, args.overwrite):
            copied += 1

        rows.append({
            "file": rel_path.as_posix(),
            "label": label,
            "reasons": ";".join(reasons),
            "bytes": path.stat().st_size,
            "lines": sum(1 for _ in text.splitlines()),
            "html_tags": len(HTML_TAG_RE.findall(text)),
            "tables": len(TABLE_RE.findall(text)),
            "images": len(IMAGE_RE.findall(text)),
        })

    with report_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "label", "reasons", "bytes", "lines", "html_tags", "tables", "images"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(
        " ".join([
            f"good={counts['good']}",
            f"suspect={counts['suspect']}",
            f"bad={counts['bad']}",
            f"copied={copied}",
            f"report={report_path}",
        ])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
