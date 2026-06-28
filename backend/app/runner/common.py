from __future__ import annotations

import json
from typing import Any

from .data_runtime import get_path, json_object_list, render_template, set_path, state_value_to_text, truthy
from .graph_runtime import (
    choose_handle,
    error_execution_target,
    first_execution_target,
    first_target,
    next_execution_target,
    target_for_handle,
)
from .policy import format_error, runtime_error_payload
from .trace import compact_state, compact_value


def json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.split(",") if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def parse_json_object(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def fallback_reply_content(state: dict[str, Any]) -> str:
    priority = ("final_answer", "tools_result", "agent_result", "llm_result", "http_response", "retrieved_context")
    for key in priority:
        text = state_value_to_text(state.get(key)).strip()
        if text:
            return text
    for key in reversed(list(state.keys())):
        if key in priority or key.endswith(("_result", "_answer", "_output")):
            text = state_value_to_text(state.get(key)).strip()
            if text:
                return text
    return ""


def agent_state_prompt(state: dict[str, Any]) -> str:
    user_text = state_value_to_text(state.get("messages", ""))
    compact = json.dumps(compact_state(state), ensure_ascii=False, indent=2)
    return f"用户输入：\n{user_text}\n\n当前流程 state：\n{compact}"


def render_json_object(template: str, state: dict[str, Any], field: str) -> dict[str, Any]:
    rendered = render_template(template.strip() or "{}", state)
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{field} 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{field} 必须是 JSON object。")
    return parsed


def render_mock_response(raw: str, state: dict[str, Any]) -> Any:
    rendered = render_template(raw.strip() or "{}", state)
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


def positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def optional_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def non_negative_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def bool_config(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def first_config_value(*values):
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
