#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pypdfium2 as pdfium


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "raw/2025/manifest.csv"
OUT_ROOT = ROOT / "kunshan/documents_2025_md"
DEFAULT_WORK_ROOT = ROOT / ".mineru_2025_work"
UV = shutil.which("uv") or "/home/chun/.local/bin/uv"

MD_LINK_RE = re.compile(r"(!?\[[^\]]*]\()([^):#][^)]+)(\))")
HTML_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=["\'])([^"\':#][^"\']+)(["\'])', re.IGNORECASE)
ASSET_SUFFIXES = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}


@dataclass
class MineruApiServer:
    base_url: str
    proc: subprocess.Popen[bytes] | None
    log_handle: object | None

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    self.proc.kill()
                self.proc.wait(timeout=10)
        if self.log_handle is not None:
            self.log_handle.close()


@dataclass(frozen=True)
class PdfJob:
    group: str
    short_path: str
    original_path: str
    source_path: Path
    stem: str
    pages: int
    size_bytes: int


def ensure_dirs(work_root: Path) -> None:
    for path in [
        OUT_ROOT / "md",
        OUT_ROOT / "assets",
        OUT_ROOT / "logs/mineru_batches",
        OUT_ROOT / "failed",
        work_root / "mineru_output",
        work_root / "batches",
        work_root / "mineru_api_tasks",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def page_count(path: Path) -> int:
    try:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return len(pdf)
        finally:
            pdf.close()
    except Exception:
        return -1


def status_sources(statuses: set[str] | None = None) -> set[str]:
    path = OUT_ROOT / "status.csv"
    if not path.exists():
        return set()
    sources: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if statuses is None or row["status"] in statuses:
                sources.add(row["source_path"])
    return sources


def load_jobs(
    limit: int | None,
    groups: set[str] | None = None,
    min_pages: int | None = None,
    max_pages: int | None = None,
) -> list[PdfJob]:
    done = status_sources({"ok", "failed_bad_pdf"})
    jobs: list[PdfJob] = []
    with SOURCE_MANIFEST.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if groups is not None and row["group"] not in groups:
                continue
            short_path = row["short_path"]
            if short_path in done or not short_path.lower().endswith(".pdf"):
                continue
            source_path = ROOT / "raw/2025" / short_path
            if not source_path.exists():
                continue
            pages = page_count(source_path)
            if min_pages is not None and pages >= 0 and pages < min_pages:
                continue
            if max_pages is not None and pages >= 0 and pages > max_pages:
                continue
            md_path = OUT_ROOT / "md" / row["group"] / f"{source_path.stem}.md"
            if md_path.exists():
                continue
            jobs.append(
                PdfJob(
                    group=row["group"],
                    short_path=short_path,
                    original_path=row["original_path"],
                    source_path=source_path,
                    stem=source_path.stem,
                    pages=pages,
                    size_bytes=source_path.stat().st_size,
                )
            )
            if limit and len(jobs) >= limit:
                break
    return jobs


def write_headers() -> None:
    status_path = OUT_ROOT / "status.csv"
    if not status_path.exists():
        with status_path.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(
                [
                    "batch_id",
                    "group",
                    "source_path",
                    "original_path",
                    "pages",
                    "status",
                    "seconds",
                    "md_path",
                    "message",
                ]
            )


def fetch_api_health(base_url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urlopen(f"{base_url.rstrip('/')}/health", timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (OSError, URLError):
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if data.get("status") != "healthy":
        return None
    return data


def wait_api_ready(base_url: str, proc: subprocess.Popen[bytes] | None, timeout: int) -> dict:
    deadline = time.time() + timeout
    last_error = "mineru-api did not become healthy"
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"mineru-api exited early with rc={proc.returncode}")
        health = fetch_api_health(base_url, timeout=2)
        if health is not None:
            return health
        time.sleep(2)
    raise TimeoutError(last_error)


def start_mineru_api(
    port: int,
    api_concurrency: int,
    processing_window_size: int,
    pdf_render_threads: int,
    work_root: Path,
    startup_timeout: int,
) -> MineruApiServer:
    base_url = f"http://127.0.0.1:{port}"
    existing = fetch_api_health(base_url)
    if existing is not None:
        return MineruApiServer(base_url=base_url, proc=None, log_handle=None)

    log_path = OUT_ROOT / "logs/mineru_api.log"
    log_handle = log_path.open("ab")
    env = os.environ.copy()
    env["MINERU_DEVICE_MODE"] = "cuda"
    env["CUDA_VISIBLE_DEVICES"] = env.get("CUDA_VISIBLE_DEVICES", "0")
    env["HF_ENDPOINT"] = env.get("HF_ENDPOINT", "https://hf-mirror.com")
    env["MINERU_API_MAX_CONCURRENT_REQUESTS"] = str(api_concurrency)
    env["MINERU_PROCESSING_WINDOW_SIZE"] = str(processing_window_size)
    env["MINERU_PDF_RENDER_THREADS"] = str(pdf_render_threads)
    env["MINERU_API_OUTPUT_ROOT"] = str(work_root / "mineru_api_tasks")
    env["MINERU_PIPELINE_GPU_LOCK_PATH"] = str(work_root / "locks/pipeline_gpu.lock")
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [UV, "run", "mineru-api", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        wait_api_ready(base_url, proc, startup_timeout)
    except Exception:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
        log_handle.close()
        raise
    return MineruApiServer(base_url=base_url, proc=proc, log_handle=log_handle)


def append_status(batch_id: str, job: PdfJob, status: str, seconds: float, message: str = "") -> None:
    md_path = OUT_ROOT / "md" / job.group / f"{job.stem}.md"
    with (OUT_ROOT / "status.csv").open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(
            [
                batch_id,
                job.group,
                job.short_path,
                job.original_path,
                job.pages,
                status,
                f"{seconds:.2f}",
                str(md_path.relative_to(OUT_ROOT)) if md_path.exists() else "",
                message,
            ]
        )


def write_manifest(jobs: list[PdfJob]) -> None:
    rows: dict[str, list[str]] = {}
    status_path = OUT_ROOT / "status.csv"
    if status_path.exists():
        with status_path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "ok" or not row.get("md_path"):
                    continue
                source_path = row["source_path"]
                group = row["group"]
                stem = Path(row["md_path"]).stem
                src = ROOT / "raw/2025" / source_path
                rows[source_path] = [
                    group,
                    source_path,
                    row.get("original_path", ""),
                    row.get("pages", "0"),
                    str(src.stat().st_size) if src.exists() else "0",
                    row["md_path"],
                    f"assets/{group}/{stem}",
                ]

    for job in jobs:
        rows[job.short_path] = [
            job.group,
            job.short_path,
            job.original_path,
            str(job.pages),
            str(job.size_bytes),
            f"md/{job.group}/{job.stem}.md",
            f"assets/{job.group}/{job.stem}",
        ]

    with (OUT_ROOT / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["group", "source_path", "original_path", "pages", "size_bytes", "md_path", "assets_dir"])
        for source_path in sorted(rows):
            writer.writerow(rows[source_path])


def make_batches(jobs: list[PdfJob], max_docs: int, max_pages: int) -> list[list[PdfJob]]:
    batches: list[list[PdfJob]] = []
    current: list[PdfJob] = []
    current_pages = 0
    for job in jobs:
        if job.pages < 0:
            batches.append([job])
            continue
        pages = max(job.pages, 1)
        if current and (len(current) >= max_docs or current_pages + pages > max_pages):
            batches.append(current)
            current = []
            current_pages = 0
        current.append(job)
        current_pages += pages
    if current:
        batches.append(current)
    return batches


def prepare_input(batch: list[PdfJob], batch_id: str, work_root: Path) -> Path:
    batch_dir = work_root / "batches" / batch_id
    shutil.rmtree(batch_dir, ignore_errors=True)
    batch_dir.mkdir(parents=True, exist_ok=True)
    for job in batch:
        target = batch_dir / job.source_path.name
        try:
            os.link(job.source_path, target)
        except OSError:
            target.symlink_to(job.source_path)
    return batch_dir


def run_mineru(
    batch: list[PdfJob],
    batch_id: str,
    timeout: int,
    formula: str,
    table: str,
    api_url: str,
    work_root: Path,
) -> tuple[int, bool, Path]:
    batch_dir = prepare_input(batch, batch_id, work_root)
    output_dir = work_root / "mineru_output" / batch_id
    shutil.rmtree(output_dir, ignore_errors=True)
    log_path = OUT_ROOT / "logs/mineru_batches" / f"{batch_id}.log"
    cmd = [
        UV,
        "run",
        "mineru",
        "--api-url",
        api_url,
        "-p",
        str(batch_dir),
        "-o",
        str(output_dir),
        "-b",
        "pipeline",
        "-m",
        "auto",
        "-l",
        "ch",
        "--formula",
        formula,
        "--table",
        table,
    ]
    env = os.environ.copy()
    env["MINERU_DEVICE_MODE"] = "cuda"
    env["CUDA_VISIBLE_DEVICES"] = env.get("CUDA_VISIBLE_DEVICES", "0")
    env["HF_ENDPOINT"] = env.get("HF_ENDPOINT", "https://hf-mirror.com")
    env["PYTHONUNBUFFERED"] = "1"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return proc.wait(timeout=timeout), False, output_dir
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
            log.write(f"\nMinerU timed out after {timeout} seconds.\n".encode("utf-8"))
            return -9, True, output_dir
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)


def rewrite_links(text: str, job: PdfJob) -> str:
    prefix = f"../../assets/{job.group}/{job.stem}/"

    def repl(match: re.Match[str]) -> str:
        target = match.group(2)
        if target.startswith(("../", "/", "http://", "https://", "data:", "mailto:")):
            return match.group(0)
        return f"{match.group(1)}{prefix}{target}{match.group(3)}"

    text = MD_LINK_RE.sub(repl, text)
    return HTML_SRC_RE.sub(repl, text)


def collect_output(job: PdfJob, batch_id: str, output_dir: Path, seconds: float, missing_status: str, message: str) -> None:
    src_md = output_dir / job.stem / "auto" / f"{job.stem}.md"
    auto_dir = src_md.parent
    dst_md = OUT_ROOT / "md" / job.group / f"{job.stem}.md"
    dst_assets = OUT_ROOT / "assets" / job.group / job.stem
    if not src_md.exists():
        append_status(batch_id, job, missing_status, seconds, message)
        return

    text = src_md.read_text(encoding="utf-8", errors="ignore")
    frontmatter = "\n".join(
        [
            "---",
            f"group: {job.group}",
            f"source_path: raw/2025/{job.short_path}",
            f"original_path: {job.original_path}",
            "source_type: pdf",
            f"pages: {job.pages}",
            "---",
            "",
        ]
    )
    dst_md.parent.mkdir(parents=True, exist_ok=True)
    dst_md.write_text(frontmatter + rewrite_links(text, job), encoding="utf-8")

    if auto_dir.exists():
        dst_assets.mkdir(parents=True, exist_ok=True)
        for child in auto_dir.iterdir():
            if child.name == src_md.name:
                continue
            target = dst_assets / child.name
            if child.is_dir() and child.name in {"images", "tables"}:
                shutil.copytree(child, target, dirs_exist_ok=True)
            elif child.is_file() and child.suffix.lower() in ASSET_SUFFIXES:
                shutil.copy2(child, target)
    append_status(batch_id, job, "ok", seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract 2025 PDFs with MinerU in small batches.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--groups", nargs="+")
    parser.add_argument("--min-pages", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--batch-docs", type=int, default=20)
    parser.add_argument("--batch-pages", type=int, default=128)
    parser.add_argument("--api-port", type=int, default=51017)
    parser.add_argument("--api-concurrency", type=int, default=1)
    parser.add_argument("--processing-window-size", type=int, default=128)
    parser.add_argument("--pdf-render-threads", type=int, default=8)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--api-startup-timeout", type=int, default=600)
    parser.add_argument("--api-restart-every-batches", type=int, default=0)
    parser.add_argument("--batch-prefix", default="pdf")
    parser.add_argument("--formula", default="false", choices=["true", "false"])
    parser.add_argument("--table", default="true", choices=["true", "false"])
    args = parser.parse_args()

    work_root = args.work_root.resolve()
    ensure_dirs(work_root)
    write_headers()
    groups = set(args.groups) if args.groups else None
    jobs = load_jobs(args.limit, groups, args.min_pages, args.max_pages)
    write_manifest(jobs)
    batches = make_batches(jobs, args.batch_docs, args.batch_pages)
    runner_log = OUT_ROOT / "logs/mineru_runner.log"
    if not batches:
        with runner_log.open("a", encoding="utf-8") as log:
            log.write(
                f"[{time.strftime('%F %T')}] batch_runner jobs=0 batches=0 "
                f"timeout={args.timeout} batch_docs={args.batch_docs} batch_pages={args.batch_pages} "
                f"formula={args.formula} table={args.table} api_url=not_started "
                f"work_root={work_root}\n"
            )
        return 0

    api_server = start_mineru_api(
        args.api_port,
        args.api_concurrency,
        args.processing_window_size,
        args.pdf_render_threads,
        work_root,
        args.api_startup_timeout,
    )
    api_health = fetch_api_health(api_server.base_url) or {}

    with runner_log.open("a", encoding="utf-8") as log:
        log.write(
            f"[{time.strftime('%F %T')}] batch_runner jobs={len(jobs)} batches={len(batches)} "
            f"timeout={args.timeout} batch_docs={args.batch_docs} batch_pages={args.batch_pages} "
            f"formula={args.formula} table={args.table} api_url={api_server.base_url} "
            f"api_concurrency={api_health.get('max_concurrent_requests')} "
            f"processing_window_size={api_health.get('processing_window_size')} "
            f"pdf_render_threads={args.pdf_render_threads} work_root={work_root}\n"
        )

    try:
        for index, batch in enumerate(batches, 1):
            batch_id = f"{args.batch_prefix}_{index:06d}"
            bad_jobs = [job for job in batch if job.pages < 0]
            if bad_jobs:
                for job in bad_jobs:
                    append_status(batch_id, job, "failed_bad_pdf", 0, "pypdfium2 could not open PDF")
                continue

            pages = sum(max(job.pages, 1) for job in batch)
            with runner_log.open("a", encoding="utf-8") as log:
                log.write(
                    f"[{time.strftime('%F %T')}] {batch_id} docs={len(batch)} pages={pages} "
                    f"first={batch[0].short_path}\n"
                )
            t0 = time.time()
            rc, timed_out, output_dir = run_mineru(
                batch,
                batch_id,
                args.timeout,
                args.formula,
                args.table,
                api_server.base_url,
                work_root,
            )
            seconds = time.time() - t0
            for job in batch:
                collect_output(
                    job,
                    batch_id,
                    output_dir,
                    seconds,
                    "failed_timeout" if timed_out else "failed",
                    f"mineru rc={rc}" if not timed_out else f"mineru timed out after {args.timeout} seconds",
                )
            with runner_log.open("a", encoding="utf-8") as log:
                health = fetch_api_health(api_server.base_url) or {}
                log.write(
                    f"[{time.strftime('%F %T')}] {batch_id} rc={rc} seconds={seconds:.2f} "
                    f"api_pending={health.get('queued_tasks')} api_processing={health.get('processing_tasks')} "
                    f"api_completed={health.get('completed_tasks')} api_failed={health.get('failed_tasks')}\n"
                )
            if rc != 0:
                with (OUT_ROOT / "failed/batches.txt").open("a", encoding="utf-8") as f:
                    f.write(f"{batch_id}\n")
            if args.api_restart_every_batches > 0 and index % args.api_restart_every_batches == 0:
                with runner_log.open("a", encoding="utf-8") as log:
                    log.write(f"[{time.strftime('%F %T')}] restarting mineru-api after {index} batches\n")
                api_server.stop()
                time.sleep(3)
                api_server = start_mineru_api(
                    args.api_port,
                    args.api_concurrency,
                    args.processing_window_size,
                    args.pdf_render_threads,
                    work_root,
                    args.api_startup_timeout,
                )
    finally:
        api_server.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
