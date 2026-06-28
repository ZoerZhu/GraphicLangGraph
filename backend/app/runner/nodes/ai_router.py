from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import model_runtime
from ..common import render_template
from ..context import ExecutionContext
from ..router_runtime import infer_router_key, normalize_route_key, parse_router_scenarios, router_prompt


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    resolved_model_config = model_runtime.effective_model_config(config, ctx.model_config)
    field = str(config.get("routeField", "route_key"))
    fallback = str(config.get("fallback", "other"))
    reason_field = str(config.get("reasonField", "route_reason"))
    keyword_route = infer_router_key(config, state) or fallback
    if str(config.get("routeMode", "keyword")) != "llm":
        return {field: keyword_route, reason_field: "live-run keyword router"}, f"关键词路由选择 {keyword_route}"

    provider, model = model_runtime.resolve_node_model(config, ctx.model_config, "openai", "gpt-4.1-mini")
    text = render_template(str(config.get("inputText", "{{ state.messages }}")), state)
    prompt = router_prompt(str(config.get("instruction", "")), text, parse_router_scenarios(str(config.get("scenarios", ""))), fallback)
    try:
        response = model_runtime.call_chat_model(provider, model, [("user", prompt)], resolved_model_config)
    except Exception as exc:
        return {field: keyword_route, reason_field: f"llm router failed, fallback to keyword: {exc}"}, f"LLM 路由失败，回退到 {keyword_route}"
    route = normalize_route_key(getattr(response, "content", str(response)), config, fallback)
    return {field: route, reason_field: "live-run llm router"}, f"LLM 路由选择 {route}"


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    field = str(config.get("routeField", "route_key"))
    fallback = str(config.get("fallback", "other"))
    route = infer_router_key(config, state) or fallback
    reason_field = str(config.get("reasonField", "route_reason"))
    return {field: route, reason_field: "dry-run router decision"}, f"模拟 AI Router 选择 {route}"
