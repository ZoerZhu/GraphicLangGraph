from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = ROOT_DIR / "storage" / "projects"
WORKSPACE_DIR = ROOT_DIR / "storage" / "workspace"
WORKSPACE_TOOLS_FILE = WORKSPACE_DIR / "tools.json"
WORKSPACE_MCP_FILE = WORKSPACE_DIR / "mcp_servers.json"
WORKSPACE_MODELS_FILE = WORKSPACE_DIR / "models.json"
WORKSPACE_RAG_FILE = WORKSPACE_DIR / "rag_knowledge_bases.json"
WORKSPACE_SKILLS_FILE = WORKSPACE_DIR / "skills.json"
WORKSPACE_RESOURCE_GROUPS_FILE = WORKSPACE_DIR / "resource_groups.json"
WORKSPACE_RUNTIME_ENVIRONMENTS_FILE = WORKSPACE_DIR / "runtime_environments.json"
EDIT_SESSIONS_DIR = ROOT_DIR / "storage" / "edit_sessions"
CONFIG_DIR = ROOT_DIR / "config"
CONFIG_MCP_DIR = CONFIG_DIR / "mcp"
CONFIG_TOOLS_DIR = CONFIG_DIR / "tools"
CONFIG_SKILLS_DIR = CONFIG_DIR / "skills"
EXPORTS_DIR = ROOT_DIR / "exports"
BUILDS_DIR = EXPORTS_DIR / "builds"


def ensure_runtime_dirs() -> None:
    load_runtime_env()
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    EDIT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_MCP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)


def load_runtime_env() -> None:
    for path in (ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"):
        _load_env_file(path)


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        key_value = _parse_env_line(line)
        if not key_value:
            continue
        key, value = key_value
        os.environ.setdefault(key, value)


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    if text.startswith("export "):
        text = text[7:].strip()
    key, value = text.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None
    return key, _strip_env_value(value.strip())


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value
