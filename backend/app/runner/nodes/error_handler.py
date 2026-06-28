from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..common import get_path, render_template
from ..context import ExecutionContext


def execute_error_handler(node: NodeIR, state: dict[str, Any]):
    config = node.config
    error_field = str(config.get("errorField", "last_error")).strip() or "last_error"
    output_field = str(config.get("outputField", "error_result")).strip() or "error_result"
    error_value = get_path(state, error_field, {})
    render_state = {**state, "error": error_value}
    template = str(config.get("template") or "流程执行失败：{{ state.last_error }}")
    message = render_template(template, render_state)
    return {
        output_field: {
            "ok": False,
            "error": error_value,
            "message": message,
        }
    }, f"Error Handler 读取 state.{error_field}，输出到 state.{output_field}"


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_error_handler(node, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_error_handler(node, state)
