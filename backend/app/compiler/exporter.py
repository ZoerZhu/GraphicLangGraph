from __future__ import annotations

import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import BUILDS_DIR, EXPORTS_DIR, ensure_runtime_dirs
from app.ir.schemas import ProjectIR

from .codegen import generate_project_files, package_name


@dataclass(frozen=True)
class SmokeTestResult:
    passed: bool
    command: list[str]
    exitCode: int
    durationMs: float
    stdout: str = ""
    stderr: str = ""


class SmokeTestFailedError(RuntimeError):
    def __init__(self, result: SmokeTestResult) -> None:
        super().__init__("导出工程 smoke test 未通过。")
        self.result = result


def build_project(project: ProjectIR) -> tuple[Path, list[str]]:
    ensure_runtime_dirs()
    package = package_name(project)
    build_dir = BUILDS_DIR / f"{package}_{uuid4().hex[:8]}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    files = generate_project_files(project)
    for relative_path, content in files.items():
        target = build_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return build_dir, sorted(files.keys())


def run_smoke_test(build_dir: Path, timeout: int = 60) -> SmokeTestResult:
    command = [sys.executable, "-m", "pytest", "tests/test_graph_smoke.py", "-q"]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return SmokeTestResult(
            passed=completed.returncode == 0,
            command=command,
            exitCode=completed.returncode,
            durationMs=round((time.perf_counter() - started) * 1000, 2),
            stdout=completed.stdout[-12000:],
            stderr=completed.stderr[-12000:],
        )
    except subprocess.TimeoutExpired as exc:
        return SmokeTestResult(
            passed=False,
            command=command,
            exitCode=124,
            durationMs=round((time.perf_counter() - started) * 1000, 2),
            stdout=(exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
            stderr=((exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else "") + f"\nTimed out after {timeout}s.",
        )


def export_project_zip(project: ProjectIR) -> tuple[str, Path, list[str], SmokeTestResult]:
    build_dir, file_list = build_project(project)
    smoke_test = run_smoke_test(build_dir)
    if not smoke_test.passed:
        raise SmokeTestFailedError(smoke_test)

    export_id = f"{package_name(project)}_{uuid4().hex[:8]}"
    zip_path = EXPORTS_DIR / f"{export_id}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in build_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(build_dir).as_posix())

    return export_id, zip_path, file_list, smoke_test
