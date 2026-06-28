from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR
from app import mcp_runtime

from ..common import render_json_object, truthy
from ..context import ExecutionContext
from ..mcp_selection import ensure_mcp_default_args, mcp_tool_selection_mode, mcp_tool_summary, select_default_mcp_tool, select_mcp_tool_with_model
from ..resources import mcp_server_for_node


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_mcp_node(node, state, ctx.model_config, ctx.runtime_environment, ctx.mcp_servers)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    field = str(node.config.get("outputField", f"{node.type}_result"))
    return {field: f"[dry-run] {node.label}"}, f"模拟输出到 state.{field}"


def execute_mcp_node(
    node: NodeIR,
    state: dict[str, Any],
    model_config: dict[str, Any] | None,
    runtime_environment: dict[str, Any] | None,
    mcp_servers: dict[str, dict[str, Any]],
):
    config = node.config
    output_field = str(config.get("outputField", "mcp_result")).strip() or "mcp_result"
    server = mcp_server_for_node(config, mcp_servers)
    if not server:
        raise RuntimeError("MCP Node 未绑定有效 MCP Server。")
    tool_name = str(config.get("toolName") or "").strip()
    args = render_json_object(str(config.get("toolArgsJson") or "{}"), state, "toolArgsJson")
    available_tools: list[dict[str, Any]] = []
    auto_selected = False
    selected_by_model = False
    selection_reason = ""
    selection_mode = mcp_tool_selection_mode(config, bool(tool_name))
    selected_tool: dict[str, Any] | None = None
    if not tool_name:
        available_tools = mcp_runtime.list_mcp_tools(server, runtime_environment)
        if selection_mode == "manual":
            candidates = ", ".join(str(tool.get("name") or "") for tool in available_tools if str(tool.get("name") or "").strip())
            raise RuntimeError(f"MCP Node 未选择 MCP Tool。可选工具：{candidates}" if candidates else "MCP Node 未选择 MCP Tool。")
        if selection_mode == "model":
            try:
                selection = select_mcp_tool_with_model(config, available_tools, args, state, model_config)
                tool_name = str(selection.get("tool") or "").strip()
                selected_tool = next((tool for tool in available_tools if str(tool.get("name") or "").strip() == tool_name), None)
                selected_args = selection.get("args")
                if not selected_tool:
                    raise RuntimeError(f"模型选择了不存在或不可用的 MCP Tool：{tool_name}")
                if not isinstance(selected_args, dict):
                    raise RuntimeError("模型选择 MCP Tool 时返回的 args 必须是 JSON object。")
                args = {**args, **selected_args}
                selected_by_model = True
                selection_reason = str(selection.get("reason") or "").strip()
            except Exception:
                if not truthy(config.get("fallbackToHeuristic")):
                    raise
                selected_tool = select_default_mcp_tool(available_tools, args, state)
                tool_name = str(selected_tool.get("name") or "").strip()
                selection_reason = "model_selection_failed_fallback_to_heuristic"
        else:
            selected_tool = select_default_mcp_tool(available_tools, args, state)
            tool_name = str(selected_tool.get("name") or "").strip()
        tool_name = str(selected_tool.get("name") or "").strip()
        auto_selected = True
    if not tool_name:
        raise RuntimeError("MCP Node 未选择 MCP Tool，且无法自动选择。")
    if selected_tool is None and available_tools:
        selected_tool = next((tool for tool in available_tools if str(tool.get("name") or "") == tool_name), None)
    args = ensure_mcp_default_args(args, selected_tool, state)
    result = mcp_runtime.invoke_mcp_tool(server, tool_name, args, runtime_environment)
    if isinstance(result, dict):
        result["autoSelectedTool"] = auto_selected
        result["selectionMode"] = selection_mode
        result["selectedByModel"] = selected_by_model
        result["selectionReason"] = selection_reason
        if available_tools:
            result["availableTools"] = [mcp_tool_summary(tool) for tool in available_tools]
    server_name = str(result.get("serverName") or server.get("name") or "未命名 MCP")
    return {output_field: result}, f"真实调用 MCP「{server_name}」工具 {tool_name}，输出到 state.{output_field}"
