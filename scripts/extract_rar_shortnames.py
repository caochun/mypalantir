#!/usr/bin/env python3
import csv
import errno
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
OUT = RAW / "2025"
STAGE = OUT / "_stage_original"
FILES = OUT / "files"
LOGS = OUT / "extract_logs"
MANIFEST = OUT / "manifest.csv"

ARCHIVES = [
    ("2025_01", RAW / "2025_01.part1.rar"),
    ("2025_02", RAW / "2025_02.part1.rar"),
    ("2025_03", RAW / "2025_03.part1.rar"),
    ("2025_04", RAW / "2025_04.part1.rar"),
    ("2025_05", RAW / "2025_05.part1.rar"),
    ("2025_06", RAW / "2025_06.part1.rar"),
    ("2025_07", RAW / "2025_07.part1.rar"),
    ("2025_07-1", RAW / "2025_07-1.part1.rar"),
    ("2025_08", RAW / "2025_08.part1.rar"),
    ("2025_09", RAW / "2025_09.part1.rar"),
    ("2025_10", RAW / "2025_10.part1.rar"),
    ("2025_11", RAW / "2025_11.part1.rar"),
    ("2025_12", RAW / "2025_12.part1.rar"),
]

ARCHIVE_BY_GROUP = dict(ARCHIVES)


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], **kwargs)


def archive_entries(archive):
    proc = run(["unrar", "lb", archive], check=True, text=True, capture_output=True)
    return [line for line in proc.stdout.splitlines() if line]


def suffix_for(path):
    suffix = PurePosixPath(path).suffix
    if not suffix:
        return ""
    if len(suffix.encode("utf-8")) > 24:
        return ""
    return suffix.replace("/", "")


def short_name(index, original_path):
    digest = hashlib.sha1(original_path.encode("utf-8")).hexdigest()[:12]
    return f"{index:06d}_{digest}{suffix_for(original_path)}"


def next_index(group_files):
    max_index = 0
    if not group_files.exists():
        return 1
    for path in group_files.iterdir():
        if not path.is_file():
            continue
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit():
            max_index = max(max_index, int(prefix))
    return max_index + 1


def extract_archive_to_stage(group, archive, password):
    group_stage = STAGE / group
    group_stage.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{group}_unrar_x.log"
    with log_path.open("wb") as log:
        proc = run(
            [
                "unrar",
                "x",
                "-idq",
                "-o+",
                f"-p{password}",
                archive,
                group_stage,
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    return proc.returncode, log_path


def move_or_stream(group, archive, password, original_path, final_path, staged_path):
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        staged_exists = staged_path.exists()
    except OSError as exc:
        if exc.errno != errno.ENAMETOOLONG:
            raise
        staged_exists = False

    if staged_exists:
        shutil.move(str(staged_path), str(final_path))
        return "moved", final_path.stat().st_size

    with final_path.open("wb") as out:
        proc = run(
            ["unrar", "p", "-inul", f"-p{password}", archive, original_path],
            stdout=out,
            stderr=subprocess.DEVNULL,
        )
    if proc.returncode == 0:
        return "streamed", final_path.stat().st_size

    final_path.unlink(missing_ok=True)
    return f"failed:{proc.returncode}", ""


def remove_empty_dirs(path):
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass


def append_stage_leftovers():
    if not STAGE.exists():
        print("no stage leftovers", flush=True)
        return 0

    appended = 0
    seen = set()
    if MANIFEST.exists():
        with MANIFEST.open("r", newline="", encoding="utf-8") as manifest:
            reader = csv.DictReader(manifest)
            for row in reader:
                seen.add(row["original_path"])

    with MANIFEST.open("a", newline="", encoding="utf-8") as manifest:
        writer = csv.writer(manifest)
        for group_dir in sorted(path for path in STAGE.iterdir() if path.is_dir()):
            group = group_dir.name
            group_files = FILES / group
            index = next_index(group_files)
            leftovers = sorted(path for path in group_dir.rglob("*") if path.is_file())
            print(f"{group}: {len(leftovers)} stage leftovers", flush=True)
            for staged_path in leftovers:
                original_path = staged_path.relative_to(group_dir).as_posix()
                if original_path in seen:
                    continue
                final_path = group_files / short_name(index, original_path)
                index += 1
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_path), str(final_path))
                writer.writerow(
                    [
                        group,
                        str(final_path.relative_to(OUT)),
                        original_path,
                        "stage_leftover",
                        final_path.stat().st_size,
                    ]
                )
                appended += 1
                if appended % 1000 == 0:
                    manifest.flush()
                    print(f"stage leftovers appended: {appended}", flush=True)

    remove_empty_dirs(STAGE)
    print(f"stage leftovers appended: {appended}", flush=True)
    return appended


def main():
    password = os.environ.get("RAR_PASSWORD")
    if not password:
        print("RAR_PASSWORD is required", file=sys.stderr)
        return 2

    shutil.rmtree(OUT, ignore_errors=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(parents=True, exist_ok=True)

    with MANIFEST.open("w", newline="", encoding="utf-8") as manifest:
        writer = csv.writer(manifest)
        writer.writerow(
            [
                "group",
                "short_path",
                "original_path",
                "status",
                "size_bytes",
            ]
        )

        total = 0
        failures = 0
        for group, archive in ARCHIVES:
            if not archive.exists():
                raise FileNotFoundError(archive)

            entries = archive_entries(archive)
            print(f"{group}: {len(entries)} entries", flush=True)

            code, log_path = extract_archive_to_stage(group, archive, password)
            print(f"{group}: unrar x exit={code}, log={log_path.relative_to(ROOT)}", flush=True)

            group_files = FILES / group
            for index, original_path in enumerate(entries, 1):
                final_path = group_files / short_name(index, original_path)
                staged_path = STAGE / group / original_path
                status, size = move_or_stream(
                    group, archive, password, original_path, final_path, staged_path
                )
                if status.startswith("failed:"):
                    failures += 1
                total += 1
                writer.writerow(
                    [
                        group,
                        str(final_path.relative_to(OUT)),
                        original_path,
                        status,
                        size,
                    ]
                )

                if index % 1000 == 0:
                    manifest.flush()
                    print(f"{group}: {index}/{len(entries)}", flush=True)

            remove_empty_dirs(STAGE / group)

    remove_empty_dirs(STAGE)
    print(f"done: total={total}, failures={failures}, manifest={MANIFEST.relative_to(ROOT)}", flush=True)
    return 1 if failures else 0


def continue_leftovers_main():
    appended = append_stage_leftovers()
    print(f"done leftovers: appended={appended}, manifest={MANIFEST.relative_to(ROOT)}", flush=True)
    return 0


def append_group_main(group, stream_only=False):
    password = os.environ.get("RAR_PASSWORD")
    if not password:
        print("RAR_PASSWORD is required", file=sys.stderr)
        return 2
    archive = ARCHIVE_BY_GROUP.get(group)
    if archive is None:
        print(f"unknown group: {group}", file=sys.stderr)
        return 2
    if not archive.exists():
        raise FileNotFoundError(archive)

    LOGS.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        with MANIFEST.open("w", newline="", encoding="utf-8") as manifest:
            csv.writer(manifest).writerow(["group", "short_path", "original_path", "status", "size_bytes"])

    seen = set()
    with MANIFEST.open("r", newline="", encoding="utf-8") as manifest:
        for row in csv.DictReader(manifest):
            if row["group"] == group:
                seen.add(row["original_path"])

    entries = archive_entries(archive)
    remaining = [entry for entry in entries if entry not in seen]
    print(f"{group}: {len(entries)} entries, {len(remaining)} remaining", flush=True)
    if not remaining:
        return 0

    if stream_only:
        code = 0
        print(f"{group}: stream-only mode; skipping unrar x stage", flush=True)
    else:
        code, log_path = extract_archive_to_stage(group, archive, password)
        print(f"{group}: unrar x exit={code}, log={log_path.relative_to(ROOT)}", flush=True)

    total = 0
    failures = 0
    group_files = FILES / group
    index = next_index(group_files)
    with MANIFEST.open("a", newline="", encoding="utf-8") as manifest:
        writer = csv.writer(manifest)
        for original_path in remaining:
            final_path = group_files / short_name(index, original_path)
            staged_path = STAGE / group / original_path
            if stream_only:
                staged_path = STAGE / "__stream_only_missing__"
            status, size = move_or_stream(group, archive, password, original_path, final_path, staged_path)
            if status.startswith("failed:"):
                failures += 1
            total += 1
            writer.writerow([group, str(final_path.relative_to(OUT)), original_path, status, size])
            index += 1
            if total % 1000 == 0:
                manifest.flush()
                print(f"{group}: appended {total}/{len(remaining)}", flush=True)

    remove_empty_dirs(STAGE / group)
    remove_empty_dirs(STAGE)
    print(f"done append {group}: total={total}, failures={failures}, manifest={MANIFEST.relative_to(ROOT)}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    if "--continue-leftovers" in sys.argv:
        raise SystemExit(continue_leftovers_main())
    if "--append-group" in sys.argv:
        pos = sys.argv.index("--append-group")
        try:
            group = sys.argv[pos + 1]
        except IndexError:
            print("--append-group requires a group name", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(append_group_main(group, stream_only="--stream-only" in sys.argv))
    raise SystemExit(main())
