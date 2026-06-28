from __future__ import annotations

import json
import re
from typing import Any

from . import model_runtime
from .context import ModelRuntimeConfig
from .data_runtime import state_value_to_text
from .trace import compact_state, compact_value


def mcp_tool_selection_mode(config: dict[str, Any], has_explicit_tool: bool) -> str:
    if has_explicit_tool:
        return "manual"
    mode = str(config.get("toolSelectionMode") or "").strip().lower()
    return mode if mode in {"manual", "heuristic", "model"} else "heuristic"


def select_mcp_tool_with_model(
    config: dict[str, Any],
    tools: list[dict[str, Any]],
    base_args: dict[str, Any],
    state: dict[str, Any],
    runtime_model_config: ModelRuntimeConfig,
) -> dict[str, Any]:
    available = [tool for tool in tools if str(tool.get("name") or "").strip()]
    if not available:
        raise RuntimeError("MCP Server 未暴露可调用 Tool。")
    selection_config = mcp_tool_selection_model_config(config)
    effective_model_config = model_runtime.effective_model_config(selection_config, runtime_model_config)
    provider, model = model_runtime.resolve_node_model(selection_config, runtime_model_config, "openai", "gpt-4.1-mini")
    messages = [
        ("system", mcp_tool_selection_system_prompt(config, available)),
        ("user", mcp_tool_selection_user_prompt(state, base_args)),
    ]
    response = model_runtime.call_chat_model(provider, model, messages, effective_model_config)
    content = getattr(response, "content", str(response))
    selection = parse_mcp_tool_selection(content)
    tool_name = str(selection.get("tool") or selection.get("toolName") or selection.get("name") or "").strip()
    if not tool_name:
        raise RuntimeError("模型没有返回要调用的 MCP Tool。")
    selection["tool"] = tool_name
    args = selection.get("args")
    if args is None:
        selection["args"] = {}
    elif not isinstance(args, dict):
        raise RuntimeError("模型选择 MCP Tool 时返回的 args 必须是 JSON object。")
    return selection


def mcp_tool_selection_model_config(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(config)
    mapping = {
        "toolSelectionModelProvider": "provider",
        "toolSelectionModel": "model",
        "toolSelectionModelConfigId": "modelConfigId",
        "toolSelectionModelConfigName": "modelConfigName",
        "toolSelectionBaseUrl": "baseUrl",
        "toolSelectionApiKeyEnv": "apiKeyEnv",
        "toolSelectionApiKey": "apiKey",
        "toolSelectionApiVersion": "apiVersion",
        "toolSelectionOrganization": "organization",
        "toolSelectionApiFormat": "apiFormat",
    }
    for source, target in mapping.items():
        value = config.get(source)
        if value is not None and str(value).strip():
            result[target] = value
    return result


def mcp_tool_selection_system_prompt(config: dict[str, Any], tools: list[dict[str, Any]]) -> str:
    instruction = str(config.get("toolSelectionInstruction") or "").strip()
    tool_specs = [
        {
            "name": str(tool.get("name") or ""),
            "title": str(tool.get("title") or ""),
            "description": str(tool.get("description") or ""),
            "inputSchema": compact_value(tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}, string_limit=1800, list_limit=10),
        }
        for tool in tools
    ]
    base = (
        "你负责为 MCP Node 选择一个 MCP Tool 并生成调用参数。"
        "只能从可用工具列表中选择一个工具；不要编造工具名。"
        "只输出 JSON object，格式固定为："
        '{"tool":"工具名","args":{},"reason":"选择原因"}。'
        "args 必须是 JSON object。"
    )
    sections = [base]
    if instruction:
        sections.append("额外选择要求：\n" + instruction)
    sections.append("可用 MCP Tools：\n" + json.dumps(tool_specs, ensure_ascii=False, indent=2))
    return "\n\n".join(sections)


def mcp_tool_selection_user_prompt(state: dict[str, Any], base_args: dict[str, Any]) -> str:
    payload = {
        "state": compact_state(state),
        "baseArgs": base_args,
        "queryText": mcp_state_query_text(state),
    }
    return "请根据当前流程 state 和基础参数选择 MCP Tool：\n" + json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def parse_mcp_tool_selection(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise RuntimeError("模型选择 MCP Tool 的响应为空。")
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("模型选择 MCP Tool 的响应不是合法 JSON object。")


def select_default_mcp_tool(tools: list[dict[str, Any]], args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    available = [tool for tool in tools if str(tool.get("name") or "").strip()]
    if not available:
        raise RuntimeError("MCP Server 未暴露可调用 Tool。")
    if len(available) == 1:
        return available[0]
    by_name = {str(tool.get("name") or "").strip(): tool for tool in available}
    query_text = str(args.get("query") or "").strip() or mcp_state_query_text(state)
    if query_text and "web_search_exa" in by_name:
        return by_name["web_search_exa"]
    search_tools = [tool for tool in available if "search" in str(tool.get("name") or "").lower()]
    if len(search_tools) == 1:
        return search_tools[0]
    candidates = ", ".join(str(tool.get("name") or "") for tool in available)
    raise RuntimeError(f"MCP Node 未选择 Tool，且无法自动判断。可选工具：{candidates}")


def ensure_mcp_default_args(args: dict[str, Any], selected_tool: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any]:
    if args or not selected_tool or not mcp_tool_needs_query(selected_tool):
        return args
    query = mcp_state_query_text(state)
    return {"query": query} if query else args


def mcp_tool_needs_query(tool: dict[str, Any]) -> bool:
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    return "query" in properties or "query" in {str(item) for item in required}


def mcp_state_query_text(state: dict[str, Any]) -> str:
    for key in ("chat", "messages", "message", "input", "query"):
        text = state_value_to_text(state.get(key)).strip()
        if text:
            return text
    return ""


def mcp_tool_summary(tool: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(tool.get("name") or ""),
        "title": str(tool.get("title") or ""),
        "description": str(tool.get("description") or ""),
    }
