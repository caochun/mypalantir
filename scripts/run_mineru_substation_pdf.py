#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
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
DOMAIN_ROOT = ROOT / "domains/substation"
RAW_ROOT = DOMAIN_ROOT / "raw"
OUT_ROOT = DOMAIN_ROOT / "docs_md"
DEFAULT_WORK_ROOT = OUT_ROOT / "mineru_work"
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
    doc_id: str
    category: str
    source_path: Path
    source_rel: str
    original_name: str
    input_name: str
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
        work_root / "locks",
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


def doc_id_for(index: int, source_rel: str) -> str:
    digest = hashlib.sha1(source_rel.encode("utf-8")).hexdigest()[:12]
    return f"{index:06d}_{digest}"


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


def load_jobs(limit: int | None) -> list[PdfJob]:
    done = status_sources({"ok", "failed_bad_pdf"})
    jobs: list[PdfJob] = []
    sources = sorted(RAW_ROOT.rglob("*.pdf"), key=lambda p: str(p.relative_to(RAW_ROOT)))
    for index, source_path in enumerate(sources, 1):
        source_rel = source_path.relative_to(RAW_ROOT).as_posix()
        category = source_path.relative_to(RAW_ROOT).parts[0] if len(source_path.relative_to(RAW_ROOT).parts) > 1 else "uncategorized"
        doc_id = doc_id_for(index, source_rel)
        md_path = OUT_ROOT / "md" / category / f"{doc_id}.md"
        if source_rel in done or md_path.exists():
            continue
        jobs.append(
            PdfJob(
                doc_id=doc_id,
                category=category,
                source_path=source_path,
                source_rel=source_rel,
                original_name=source_path.name,
                input_name=f"{doc_id}.pdf",
                pages=page_count(source_path),
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
                    "doc_id",
                    "category",
                    "source_path",
                    "original_name",
                    "pages",
                    "status",
                    "seconds",
                    "md_path",
                    "message",
                ]
            )


def write_manifest(jobs: list[PdfJob]) -> None:
    manifest_path = OUT_ROOT / "manifest.csv"
    write_header = not manifest_path.exists()
    with manifest_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["doc_id", "category", "source_path", "original_name", "pages", "size_bytes", "md_path", "assets_dir"])
        for job in jobs:
            writer.writerow(
                [
                    job.doc_id,
                    job.category,
                    job.source_rel,
                    job.original_name,
                    job.pages,
                    job.size_bytes,
                    f"md/{job.category}/{job.doc_id}.md",
                    f"assets/{job.category}/{job.doc_id}",
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
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"mineru-api exited early with rc={proc.returncode}")
        health = fetch_api_health(base_url, timeout=2)
        if health is not None:
            return health
        time.sleep(2)
    raise TimeoutError("mineru-api did not become healthy")


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
    md_path = OUT_ROOT / "md" / job.category / f"{job.doc_id}.md"
    with (OUT_ROOT / "status.csv").open("a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(
            [
                batch_id,
                job.doc_id,
                job.category,
                job.source_rel,
                job.original_name,
                job.pages,
                status,
                f"{seconds:.2f}",
                str(md_path.relative_to(OUT_ROOT)) if md_path.exists() else "",
                message,
            ]
        )


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
        target = batch_dir / job.input_name
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
    prefix = f"../../assets/{job.category}/{job.doc_id}/"

    def repl(match: re.Match[str]) -> str:
        target = match.group(2)
        if target.startswith(("../", "/", "http://", "https://", "data:", "mailto:")):
            return match.group(0)
        return f"{match.group(1)}{prefix}{target}{match.group(3)}"

    text = MD_LINK_RE.sub(repl, text)
    return HTML_SRC_RE.sub(repl, text)


def collect_output(job: PdfJob, batch_id: str, output_dir: Path, seconds: float, missing_status: str, message: str) -> None:
    src_stem = Path(job.input_name).stem
    src_md = output_dir / src_stem / "auto" / f"{src_stem}.md"
    auto_dir = src_md.parent
    dst_md = OUT_ROOT / "md" / job.category / f"{job.doc_id}.md"
    dst_assets = OUT_ROOT / "assets" / job.category / job.doc_id
    if not src_md.exists():
        append_status(batch_id, job, missing_status, seconds, message)
        return

    text = src_md.read_text(encoding="utf-8", errors="ignore")
    frontmatter = "\n".join(
        [
            "---",
            f"domain: substation",
            f"doc_id: {job.doc_id}",
            f"category: {job.category}",
            f"source_path: domains/substation/raw/{job.source_rel}",
            f"original_name: {job.original_name}",
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


def wait_for_service(service: str, poll_seconds: int) -> None:
    if not service:
        return
    while True:
        rc = subprocess.run(["systemctl", "--user", "is-active", "--quiet", service], cwd=ROOT).returncode
        if rc != 0:
            return
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract substation domain PDFs with MinerU.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--batch-docs", type=int, default=8)
    parser.add_argument("--batch-pages", type=int, default=192)
    parser.add_argument("--api-port", type=int, default=51019)
    parser.add_argument("--api-concurrency", type=int, default=2)
    parser.add_argument("--processing-window-size", type=int, default=96)
    parser.add_argument("--pdf-render-threads", type=int, default=8)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--api-startup-timeout", type=int, default=600)
    parser.add_argument("--api-restart-every-batches", type=int, default=3)
    parser.add_argument("--formula", default="false", choices=["true", "false"])
    parser.add_argument("--table", default="false", choices=["true", "false"])
    parser.add_argument("--wait-service", default="")
    parser.add_argument("--wait-poll-seconds", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    work_root = args.work_root.resolve()
    ensure_dirs(work_root)
    write_headers()

    runner_log = OUT_ROOT / "logs/mineru_runner.log"
    if args.wait_service:
        with runner_log.open("a", encoding="utf-8") as log:
            log.write(f"[{time.strftime('%F %T')}] waiting for service {args.wait_service}\n")
        wait_for_service(args.wait_service, args.wait_poll_seconds)

    jobs = load_jobs(args.limit)
    write_manifest(jobs)
    batches = make_batches(jobs, args.batch_docs, args.batch_pages)
    if args.dry_run:
        total_pages = sum(max(job.pages, 0) for job in jobs)
        with runner_log.open("a", encoding="utf-8") as log:
            log.write(
                f"[{time.strftime('%F %T')}] dry_run jobs={len(jobs)} batches={len(batches)} "
                f"pages={total_pages} batch_docs={args.batch_docs} batch_pages={args.batch_pages}\n"
            )
        print(f"jobs={len(jobs)} batches={len(batches)} pages={total_pages}")
        return 0
    if not jobs:
        with runner_log.open("a", encoding="utf-8") as log:
            log.write(f"[{time.strftime('%F %T')}] no pending substation pdf jobs\n")
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
            f"[{time.strftime('%F %T')}] substation_runner jobs={len(jobs)} batches={len(batches)} "
            f"timeout={args.timeout} batch_docs={args.batch_docs} batch_pages={args.batch_pages} "
            f"formula={args.formula} table={args.table} api_url={api_server.base_url} "
            f"api_concurrency={api_health.get('max_concurrent_requests')} "
            f"processing_window_size={api_health.get('processing_window_size')} "
            f"pdf_render_threads={args.pdf_render_threads} work_root={work_root}\n"
        )

    try:
        for index, batch in enumerate(batches, 1):
            batch_id = f"pdf_{index:06d}"
            bad_jobs = [job for job in batch if job.pages < 0]
            if bad_jobs:
                for job in bad_jobs:
                    append_status(batch_id, job, "failed_bad_pdf", 0, "pypdfium2 could not open PDF")
                continue

            pages = sum(max(job.pages, 1) for job in batch)
            with runner_log.open("a", encoding="utf-8") as log:
                log.write(
                    f"[{time.strftime('%F %T')}] {batch_id} docs={len(batch)} pages={pages} "
                    f"first={batch[0].source_rel}\n"
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
