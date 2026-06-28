from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import engine
from ..context import ExecutionContext


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    field = str(node.config.get("outputField", "final_answer"))
    template = str(node.config.get("template", "{{ state.final_answer }}"))
    content = engine.render_template(template, state)
    if not content.strip():
        content = engine._fallback_reply_content(state)
    return {field: content}, f"终止并返回 state.{field}"


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_live(node, state, ctx)
