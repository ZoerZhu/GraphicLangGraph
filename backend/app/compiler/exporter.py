from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from app.config import BUILDS_DIR, EXPORTS_DIR, ensure_runtime_dirs
from app.ir.schemas import ProjectIR

from .codegen import generate_project_files, package_name


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


def export_project_zip(project: ProjectIR) -> tuple[str, Path, list[str]]:
    build_dir, file_list = build_project(project)
    export_id = f"{package_name(project)}_{uuid4().hex[:8]}"
    zip_path = EXPORTS_DIR / f"{export_id}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in build_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(build_dir).as_posix())

    return export_id, zip_path, file_list

