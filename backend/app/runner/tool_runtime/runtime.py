from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import ROOT_DIR
from app.runtime_environment import default_runtime_environment, resolve_runtime_environment

from ..common import json_string_list, positive_int
from ..context import RuntimeEnvironment

CODE_TOOL_EXCLUDED_DIRS = {".git", ".hg", ".svn", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".next", ".turbo", "coverage"}
CODE_TOOL_BINARY_CHECK_BYTES = 4096


def normalize_runtime_environment(runtime_environment: RuntimeEnvironment) -> dict[str, Any]:
    if runtime_environment:
        return resolve_runtime_environment(runtime_environment)
    return default_runtime_environment().model_dump(by_alias=True)


def runtime_allowed_roots(runtime: dict[str, Any]) -> list[Path]:
    raw_roots = json_string_list(runtime.get("allowedRootsJson"))
    if not raw_roots:
        env_roots = os.getenv("GLG_FILE_TOOL_ROOTS", "")
        raw_roots = [item.strip() for item in re.split(r"[;\n]+", env_roots) if item.strip()]
    if not raw_roots:
        raw_roots = [str(ROOT_DIR)]
    roots: list[Path] = []
    for item in raw_roots:
        try:
            roots.append(Path(item).expanduser().resolve())
        except OSError:
            continue
    return roots or [ROOT_DIR.resolve()]


def resolve_runtime_path(value: str, runtime: dict[str, Any]) -> Path:
    raw_path = Path(value).expanduser()
    roots = runtime_allowed_roots(runtime)
    candidates = [raw_path] if raw_path.is_absolute() else [ROOT_DIR / raw_path, *(root / raw_path for root in roots)]
    allowed: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if any(is_relative_to(resolved, root) for root in roots):
            allowed.append(resolved)
    if allowed:
        return next((path for path in allowed if path.exists()), allowed[0])
    root_text = "；".join(str(root) for root in roots)
    first = candidates[0]
    try:
        first_resolved = first.resolve()
    except OSError:
        first_resolved = first.absolute()
    raise RuntimeError(f"路径不在当前运行环境允许目录内：{first_resolved}。允许目录：{root_text}")


def read_text_limited(path: Path, runtime: dict[str, Any], encoding: str) -> tuple[str, bool]:
    max_bytes = runtime_max_file_bytes(runtime)
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes]
    return content.decode(encoding or "utf-8", errors="replace"), truncated


def count_file_lines(path: Path, encoding: str) -> int:
    count = 0
    with path.open("r", encoding=encoding or "utf-8", errors="replace", newline="") as handle:
        for count, _line in enumerate(handle, start=1):
            pass
    return count


def is_binary_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(CODE_TOOL_BINARY_CHECK_BYTES)
    except OSError:
        return True
    return b"\x00" in sample


def iter_search_files(root: Path, file_glob: str):
    if root.is_file():
        if fnmatch.fnmatch(root.name, file_glob) or fnmatch.fnmatch(root.as_posix(), file_glob):
            yield root
        return
    if not root.is_dir():
        raise RuntimeError(f"搜索根路径不存在或不是目录：{root}")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in CODE_TOOL_EXCLUDED_DIRS and not name.startswith(".")
        ]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            rel = safe_relative_path(path, root)
            if fnmatch.fnmatch(filename, file_glob) or fnmatch.fnmatch(rel, file_glob):
                yield path


def safe_relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root if root.is_dir() else root.parent).as_posix()
    except ValueError:
        return path.name


def detect_code_language(path: Path, language_hint: str) -> str:
    normalized = language_hint.strip().lower().replace("-", "_")
    aliases = {
        "py": "python",
        "python": "python",
        "html": "html",
        "htm": "html",
        "js": "javascript",
        "jsx": "javascript",
        "javascript": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "typescript": "typescript",
        "css": "css",
        "scss": "scss",
        "sass": "scss",
        "less": "less",
        "vue": "vue",
        "svelte": "svelte",
        "json": "json",
        "jsonc": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "md": "markdown",
        "markdown": "markdown",
    }
    if normalized in aliases:
        return aliases[normalized]
    suffix = path.suffix.lower().lstrip(".")
    return aliases.get(suffix, suffix or "unknown")


def assert_network_allowed(url: str, runtime: dict[str, Any], extra_allowed_hosts: set[str] | None = None) -> None:
    if runtime.get("networkEnabled") is False:
        raise RuntimeError("当前运行环境已关闭网络访问。")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("只允许访问 http/https URL。")
    host = parsed.hostname or ""
    if runtime.get("allowAllHosts") is True:
        return
    allowed_hosts = {item.lower() for item in json_string_list(runtime.get("allowedHostsJson"))}
    allowed_hosts.update(item.lower() for item in (extra_allowed_hosts or set()))
    if allowed_hosts and not host_allowed(host, allowed_hosts):
        raise RuntimeError(f"当前运行环境不允许访问域名：{host}")


def host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    normalized = host.lower()
    for allowed in allowed_hosts:
        if not allowed:
            continue
        if allowed.startswith("*.") and normalized.endswith(allowed[1:]):
            return True
        if normalized == allowed:
            return True
    return False


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def runtime_max_file_bytes(runtime: dict[str, Any]) -> int:
    return min(positive_int(runtime.get("maxFileBytes"), 1_048_576), 16 * 1024 * 1024)


def runtime_max_http_bytes(runtime: dict[str, Any]) -> int:
    return min(positive_int(runtime.get("maxHttpBytes"), 262_144), 4 * 1024 * 1024)
