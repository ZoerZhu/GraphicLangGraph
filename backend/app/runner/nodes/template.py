from __future__ import annotations

import json
from typing import Any

from app.ir.schemas import NodeIR

from ..common import render_template
from ..context import ExecutionContext
from ..data_runtime import resolve_input_mappings


def execute_template_node(node: NodeIR, state: dict[str, Any]):
    config = node.config
    output_field = str(config.get("outputField", "template_result")).strip() or "template_result"
    output_type = str(config.get("outputType", "text")).strip().lower()
    inputs = resolve_input_mappings(config, state)
    render_state = {**state, **inputs}
    rendered = render_template(str(config.get("template", "")), render_state)
    if output_type == "json":
        try:
            value = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Template JSON 输出解析失败：{exc}") from exc
    else:
        value = rendered
    return {output_field: value}, f"Template 渲染为 {output_type or 'text'}，输出到 state.{output_field}"


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_template_node(node, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_template_node(node, state)
