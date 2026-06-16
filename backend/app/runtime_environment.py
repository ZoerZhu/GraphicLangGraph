from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.config import ROOT_DIR, WORKSPACE_RUNTIME_ENVIRONMENTS_FILE, ensure_runtime_dirs


DEFAULT_RUNTIME_ENVIRONMENT_ID = "runtime_local_backend"


class RuntimeEnvironmentConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = DEFAULT_RUNTIME_ENVIRONMENT_ID
    name: str = "本地后端"
    kind: str = "local_backend"
    description: str = "由当前 FastAPI 后端所在机器执行工具。"
    allowed_roots_json: str = Field("[]", alias="allowedRootsJson")
    network_enabled: bool = Field(True, alias="networkEnabled")
    allowed_hosts_json: str = Field("[]", alias="allowedHostsJson")
    max_file_bytes: int = Field(1_048_576, alias="maxFileBytes")
    max_http_bytes: int = Field(262_144, alias="maxHttpBytes")


def default_runtime_environment() -> RuntimeEnvironmentConfig:
    return RuntimeEnvironmentConfig(
        allowedRootsJson=json.dumps([str(ROOT_DIR)], ensure_ascii=False, indent=2),
        allowedHostsJson=json.dumps(["api.duckduckgo.com"], ensure_ascii=False, indent=2),
    )


def read_runtime_environments() -> list[RuntimeEnvironmentConfig]:
    ensure_runtime_dirs()
    if not WORKSPACE_RUNTIME_ENVIRONMENTS_FILE.exists():
        return [default_runtime_environment()]
    try:
        raw = json.loads(WORKSPACE_RUNTIME_ENVIRONMENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return [default_runtime_environment()]
    if not isinstance(raw, list):
        return [default_runtime_environment()]
    normalized = normalize_runtime_environments(
        [RuntimeEnvironmentConfig.model_validate(item) for item in raw if isinstance(item, dict)]
    )
    return normalized or [default_runtime_environment()]


def write_runtime_environments(items: list[RuntimeEnvironmentConfig]) -> None:
    normalized = normalize_runtime_environments(items)
    ensure_runtime_dirs()
    WORKSPACE_RUNTIME_ENVIRONMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = WORKSPACE_RUNTIME_ENVIRONMENTS_FILE.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps([item.model_dump(by_alias=True) for item in normalized], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(WORKSPACE_RUNTIME_ENVIRONMENTS_FILE)


def normalize_runtime_environments(items: list[RuntimeEnvironmentConfig]) -> list[RuntimeEnvironmentConfig]:
    normalized: list[RuntimeEnvironmentConfig] = []
    seen: set[str] = set()
    for item in items:
        item_id = item.id.strip() or f"runtime_{uuid4().hex[:8]}"
        if item_id in seen:
            item_id = f"runtime_{uuid4().hex[:8]}"
        seen.add(item_id)
        normalized.append(
            item.model_copy(
                update={
                    "id": item_id,
                    "name": item.name.strip() or "本地后端",
                    "kind": "local_backend",
                    "description": item.description.strip(),
                    "allowed_roots_json": _ensure_json_list_text(item.allowed_roots_json, [str(ROOT_DIR)]),
                    "network_enabled": item.network_enabled is not False,
                    "allowed_hosts_json": _ensure_json_list_text(item.allowed_hosts_json, ["api.duckduckgo.com"]),
                    "max_file_bytes": _positive_int(item.max_file_bytes, 1_048_576),
                    "max_http_bytes": _positive_int(item.max_http_bytes, 262_144),
                }
            )
        )
    return normalized


def resolve_runtime_environment(value: Any = None, project_runtime_environment_id: str = "") -> dict[str, Any]:
    if value:
        if hasattr(value, "model_dump"):
            return RuntimeEnvironmentConfig.model_validate(value.model_dump(by_alias=True)).model_dump(by_alias=True)
        if isinstance(value, dict):
            return RuntimeEnvironmentConfig.model_validate(value).model_dump(by_alias=True)
    environments = read_runtime_environments()
    selected = next((item for item in environments if item.id == project_runtime_environment_id), None) or environments[0]
    return selected.model_dump(by_alias=True)


def runtime_environment_summary(value: Any = None) -> str:
    data = resolve_runtime_environment(value) if value is not None else default_runtime_environment().model_dump(by_alias=True)
    network = "网络开启" if data.get("networkEnabled") is not False else "网络关闭"
    roots = _json_string_list(data.get("allowedRootsJson"))
    return f"{data.get('name') or '本地后端'} · {network} · {len(roots)} 个文件根目录"


def _ensure_json_list_text(value: str, fallback: list[str]) -> str:
    parsed = _json_string_list(value)
    if not parsed:
        parsed = fallback
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.replace(";", "\n").replace(",", "\n").splitlines() if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback
