#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
CELL_SEP = "；"


@dataclass
class Cell:
    text: str
    rowspan: int = 1
    colspan: int = 1


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.rows: list[list[Cell]] = []
        self._current_row: list[Cell] | None = None
        self._current_cell: Cell | None = None
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            attr_map = {key.lower(): value for key, value in attrs if key}
            self._current_cell = Cell(
                text="",
                rowspan=_positive_int(attr_map.get("rowspan"), 1),
                colspan=_positive_int(attr_map.get("colspan"), 1),
            )
            self._cell_parts = []
        elif tag == "br" and self._current_cell is not None:
            self._cell_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None:
            self._current_cell.text = _clean_text("".join(self._cell_parts))
            if self._current_row is not None:
                self._current_row.append(self._current_cell)
            self._current_cell = None
            self._cell_parts = []
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._cell_parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._current_cell is not None:
            self._cell_parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._current_cell is not None:
            self._cell_parts.append(f"&#{name};")


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(1, parsed)


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\u3000", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\s*\n\s*", " / ", value)
    return value.strip()


def _strip_remaining_html(text: str) -> str:
    text = BR_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def expand_table(rows: list[list[Cell]]) -> list[list[str]]:
    grid: list[list[str]] = []
    active: dict[int, tuple[int, str]] = {}

    for cells in rows:
        row: list[str] = []
        col = 0
        new_spans: dict[int, tuple[int, str]] = {}

        def put(index: int, value: str) -> None:
            while len(row) <= index:
                row.append("")
            row[index] = value

        for cell in cells:
            while col in active:
                put(col, active[col][1])
                col += 1

            for offset in range(cell.colspan):
                put(col + offset, cell.text)
                if cell.rowspan > 1:
                    new_spans[col + offset] = (cell.rowspan - 1, cell.text)
            col += cell.colspan

        max_active_col = max(active.keys(), default=-1)
        while col <= max_active_col:
            if col in active:
                put(col, active[col][1])
            col += 1

        next_active: dict[int, tuple[int, str]] = {}
        for index, (remaining, value) in active.items():
            if remaining > 1:
                next_active[index] = (remaining - 1, value)
        next_active.update(new_spans)
        active = next_active

        grid.append(row)

    width = max((len(row) for row in grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def numeric_ratio(row: list[str]) -> float:
    values = [value for value in row if value]
    if not values:
        return 0.0
    numeric = 0
    for value in values:
        if re.search(r"[-+]?\d+(?:\.\d+)?%?|第?\d+号|\d{4}[-年]", value):
            numeric += 1
    return numeric / len(values)


def looks_like_data_row(row: list[str]) -> bool:
    first = next((value for value in row if value), "")
    if re.fullmatch(r"\d+[、.]?", first):
        return True
    return numeric_ratio(row) >= 0.35


def header_row_count(grid: list[list[str]]) -> int:
    if len(grid) < 2:
        return 0

    count = 1
    for index in range(1, min(4, len(grid))):
        row = grid[index]
        if looks_like_data_row(row):
            break
        if numeric_ratio(row) > 0.2:
            break
        count += 1
    return count


def make_headers(header_rows: list[list[str]], width: int) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}

    for col in range(width):
        parts: list[str] = []
        for row in header_rows:
            value = row[col].strip() if col < len(row) else ""
            if value and (not parts or parts[-1] != value):
                parts.append(value)
        header = "_".join(parts) if parts else f"列{col + 1}"
        seen[header] = seen.get(header, 0) + 1
        if seen[header] > 1:
            header = f"{header}_{seen[header]}"
        headers.append(header)

    return headers


def table_to_records(table_html: str, table_index: int) -> tuple[str, int, int]:
    parser = TableParser()
    parser.feed(table_html)
    grid = expand_table(parser.rows)
    grid = [row for row in grid if any(cell.strip() for cell in row)]
    if not grid:
        return "", 0, 0

    width = max(len(row) for row in grid)
    header_count = header_row_count(grid)

    lines = [f"表格 {table_index}（已清洗为行记录）:"]
    if header_count <= 0:
        for row_index, row in enumerate(grid, start=1):
            values = [cell for cell in row if cell]
            if values:
                lines.append(f"第{row_index}行：{CELL_SEP.join(values)}")
        return "\n".join(lines), len(grid), width

    headers = make_headers(grid[:header_count], width)
    data_rows = grid[header_count:]
    lines.append(f"列：{CELL_SEP.join(headers)}")

    for row_index, row in enumerate(data_rows, start=1):
        pairs = []
        for header, value in zip(headers, row):
            if value:
                pairs.append(f"{header}={value}")
        if pairs:
            lines.append(f"第{row_index}行：{CELL_SEP.join(pairs)}")

    return "\n".join(lines), len(grid), width


def clean_markdown(text: str) -> tuple[str, int, int, int]:
    table_count = 0
    total_rows = 0
    max_cols = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal table_count, total_rows, max_cols
        table_count += 1
        replacement, rows, cols = table_to_records(match.group(0), table_count)
        total_rows += rows
        max_cols = max(max_cols, cols)
        return f"\n\n{replacement}\n\n"

    text = TABLE_RE.sub(replace, text)
    text = _strip_remaining_html(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text, table_count, total_rows, max_cols


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean MinerU markdown by converting HTML tables to LLM-friendly row records."
    )
    parser.add_argument("--src", default="documents_mineru_md")
    parser.add_argument("--dst", default="documents_mineru_md_clean")
    parser.add_argument("--report", default="raw/logs/mineru_table_clean_report.csv")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    src_dir = Path(args.src)
    dst_dir = Path(args.dst)
    report_path = Path(args.report)
    if not src_dir.is_dir():
        raise SystemExit(f"source directory not found: {src_dir}")

    dst_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    written = 0
    skipped = 0
    for src in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src.name
        if dst.exists() and not args.overwrite:
            skipped += 1
            continue

        original = src.read_text(encoding="utf-8", errors="ignore")
        cleaned, table_count, table_rows, max_cols = clean_markdown(original)
        dst.write_text(cleaned, encoding="utf-8")
        written += 1
        rows.append(
            {
                "file": src.name,
                "tables": table_count,
                "table_rows": table_rows,
                "max_cols": max_cols,
                "original_bytes": len(original.encode("utf-8")),
                "cleaned_bytes": len(cleaned.encode("utf-8")),
            }
        )

    write_header = not report_path.exists() or args.overwrite
    with report_path.open("w" if args.overwrite or write_header else "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "tables",
                "table_rows",
                "max_cols",
                "original_bytes",
                "cleaned_bytes",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"written={written} skipped={skipped} dst={dst_dir} report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
