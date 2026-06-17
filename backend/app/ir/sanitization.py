from __future__ import annotations

from typing import Any

from .schemas import ProjectIR


SECRET_KEY_NAMES = {"apikey", "secret", "password", "token"}


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if _is_plain_secret_key(str(key)):
                sanitized[key] = ""
            else:
                sanitized[key] = sanitize_payload(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


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
