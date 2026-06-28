from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import model_runtime
from ..common import render_template, state_value_to_text
from ..context import ExecutionContext


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    resolved_model_config = model_runtime.effective_model_config(config, ctx.model_config)
    provider, model = model_runtime.resolve_node_model(config, ctx.model_config, "openai", "gpt-4.1-mini")
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    user_prompt = render_template(str(config.get("userPrompt", "{{ state.messages }}")), state).strip()
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_prompt or state_value_to_text(state.get("messages", ""))))
    response = model_runtime.call_chat_model(provider, model, messages, resolved_model_config)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_output"))
    config_name = model_runtime.runtime_value(ctx.model_config, "name")
    suffix = f"（{config_name}）" if config_name else ""
    return {output_field: content}, f"真实调用 {provider}/{model}{suffix}，输出到 state.{output_field}"


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    field = str(config.get("outputField", "final_answer"))
    return {field: f"[dry-run] {node.label} 将调用模型 {config.get('model', 'gpt-4.1-mini')}"}, f"模拟 LLM 输出到 state.{field}"
