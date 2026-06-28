from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..context import ExecutionContext


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return {}, f"按 state.{node.config.get('field', 'intent')} 选择分支"


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_live(node, state, ctx)
