from __future__ import annotations

import json
from typing import Any

from .schemas import ProjectIR


SECRET_KEY_NAMES = {"apikey", "secret", "password", "token"}
JSON_STRING_KEYS_TO_SANITIZE = {
    "mcpserversnapshotjson",
    "mcpserverregistryjson",
    "toolregistryjson",
    "agentregistryjson",
    "httpheadersjson",
    "envjson",
}


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if _is_plain_secret_key(str(key)):
                sanitized[key] = ""
            else:
                sanitized[key] = _sanitize_child(str(key), child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def _sanitize_child(key: str, value: Any) -> Any:
    if isinstance(value, str) and _should_sanitize_json_string(key):
        parsed = _parse_json_string(value)
        if parsed is not None:
            return json.dumps(sanitize_payload(parsed), ensure_ascii=False)
    return sanitize_payload(value)


def _should_sanitize_json_string(key: str) -> bool:
    normalized = "".join(ch for ch in key.lower() if ch.isalnum())
    return normalized in JSON_STRING_KEYS_TO_SANITIZE


def _parse_json_string(value: str) -> Any | None:
    text = value.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def sanitize_project_payload(project: ProjectIR) -> dict[str, Any]:
    return sanitize_payload(project.model_dump(by_alias=True, mode="json"))


def sanitized_project(project: ProjectIR) -> ProjectIR:
    return ProjectIR.model_validate(sanitize_project_payload(project))


def _is_plain_secret_key(key: str) -> bool:
    normalized = "".join(ch for ch in key.lower() if ch.isalnum())
    if normalized.endswith("env") or normalized in {"authsecret", "secretref"}:
        return False
    if normalized in SECRET_KEY_NAMES:
        return True
    return normalized.endswith(("apikey", "secret", "password", "token"))
