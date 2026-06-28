from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..context import ExecutionContext


def execute_skill_node(node: NodeIR, skills: dict[str, dict[str, Any]], dry_run: bool):
    config = node.config
    output_field = str(config.get("outputField", "skill_result"))
    skill_id = str(config.get("skillId") or config.get("toolId") or "").strip()
    skill = skills.get(skill_id) if skill_id else None
    skill_name = str((skill or {}).get("name") or config.get("skillName") or config.get("toolName") or node.label)
    content = str((skill or {}).get("content") or config.get("skillContent") or config.get("content") or "")
    if dry_run and not content:
        content = f"[dry-run] {skill_name}"
    mode_text = "模拟读取" if dry_run else "读取"
    return {output_field: content}, f"{mode_text} Skill「{skill_name}」内容到 state.{output_field}"


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_skill_node(node, ctx.skills, dry_run=False)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_skill_node(node, ctx.skills, dry_run=True)
