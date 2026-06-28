from __future__ import annotations

import json
import re
import time
from typing import Any

from .. import engine
from ..common import compact_state, json_object_list, json_string_list, parse_json_object, state_value_to_text
from ..context import ModelRuntimeConfig, RuntimeEnvironment, ToolRuntimeConfig
from ..model_runtime import call_chat_model, normalize_model_config
from . import builtin as _builtin  # noqa: F401 - keep builtin runtime importable from the package.


def run_tools_agent_session(
    provider: str,
    model: str,
    effective_model_config: ModelRuntimeConfig,
    selected_tools: list[dict[str, Any]],
    system_prompt: str,
    user_prompt: str,
    max_iterations: int,
    runtime_environment: RuntimeEnvironment,
    agent_context: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    messages: list[tuple[str, str]] = [
        ("system", tools_agent_system_prompt(system_prompt, selected_tools, max_iterations)),
        ("user", user_prompt),
    ]
    calls: list[dict[str, Any]] = []
    final_answer = ""
    latest_task_plan_payload: dict[str, Any] | None = None
    for iteration in range(max_iterations):
        response = call_chat_model(provider, model, messages, effective_model_config)
        content = getattr(response, "content", str(response))
        decision = parse_tool_agent_decision(content)
        tool_calls = normalize_tool_calls(decision.get("tool_calls"))
        if not tool_calls:
            final_answer = engine._first_config_value(decision.get("final_answer"), content)
            break

        observations: list[dict[str, Any]] = []
        for call_index, tool_call in enumerate(tool_calls, start=1):
            started = time.perf_counter()
            tool_name = str(tool_call.get("tool") or tool_call.get("name") or "").strip()
            args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
            tool_config = find_selected_tool(selected_tools, tool_name)
            trace_meta = registered_tool_trace_metadata(tool_config) if tool_config else {"toolName": tool_name}
            if not tool_config:
                observation = {"ok": False, "error": f"未知 Tool：{tool_name}", "errorType": "tool_args"}
            else:
                observation = invoke_registered_tool(tool_config, args, runtime_environment, effective_model_config, agent_context)
            task_plan_payload = task_plan_payload_from_observation(tool_name, observation)
            if task_plan_payload:
                latest_task_plan_payload = task_plan_payload
            recommended_next_tools = engine._recommended_next_tools(tool_name, args, observation)
            if recommended_next_tools:
                observation["recommendedNextTools"] = recommended_next_tools
            calls.append(
                {
                    "iteration": iteration + 1,
                    "index": call_index,
                    "tool": tool_name,
                    "args": args,
                    "observation": observation,
                    "recommendedNextTools": recommended_next_tools,
                    "source": trace_meta.get("source", ""),
                    "serverName": trace_meta.get("serverName", ""),
                    "agentName": trace_meta.get("agentName", ""),
                    "toolName": trace_meta.get("toolName", tool_name),
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                    "errorType": observation.get("errorType") if isinstance(observation, dict) else None,
                }
            )
            observations.append({"tool": tool_name, "observation": observation})
        messages.append(("assistant", content))
        messages.append(("user", "工具执行结果：\n" + json.dumps(observations, ensure_ascii=False, indent=2) + "\n请继续；如果已经足够，请返回 final_answer。"))
    else:
        final_answer = finalize_tools_agent_answer(provider, model, messages, effective_model_config, max_iterations)

    from app.runner.nodes.task_splitter import normalize_worker_tasks

    if latest_task_plan_payload and not normalize_worker_tasks(final_answer, max_tasks=10, fallback_goal=""):
        final_answer = json.dumps(latest_task_plan_payload, ensure_ascii=False)
    return final_answer, calls


def task_plan_payload_from_observation(tool_name: str, observation: Any) -> dict[str, Any] | None:
    if str(tool_name or "").strip() != "task_plan" or not isinstance(observation, dict) or not observation.get("ok"):
        return None
    result = observation.get("result")
    if not isinstance(result, dict):
        return None
    from app.runner.nodes.task_splitter import normalize_worker_tasks

    tasks = normalize_worker_tasks(result, max_tasks=10, fallback_goal="")
    if not tasks:
        return None
    return {"tasks": tasks}


def finalize_tools_agent_answer(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    model_config: ModelRuntimeConfig,
    max_iterations: int,
) -> str:
    messages.append(
        (
            "user",
            f"已经达到最大工具调用轮次 {max_iterations}。不要继续调用工具；请只返回 JSON，tool_calls 为空数组，并基于已有工具结果填写 final_answer。",
        )
    )
    try:
        response = call_chat_model(provider, model, messages, model_config)
    except Exception as exc:
        return f"达到最大工具调用轮次 {max_iterations}，已停止。最终总结失败：{exc.__class__.__name__}: {exc}"
    content = getattr(response, "content", str(response))
    decision = parse_tool_agent_decision(content)
    final_answer = engine._first_config_value(decision.get("final_answer"))
    return final_answer or content or f"达到最大工具调用轮次 {max_iterations}，已停止。"


def tools_agent_system_prompt(system_prompt: str, selected_tools: list[dict[str, Any]], max_iterations: int) -> str:
    tool_lines = []
    for tool in selected_tools:
        schema = parse_json_object(str(tool.get("schemaJson", "{}")))
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        tool_lines.append(
            {
                "id": tool.get("id"),
                "name": tool.get("name"),
                "source": tool.get("source"),
                "description": tool.get("description"),
                "args": properties,
                "required": required,
            }
        )
    instructions = (
        "你是一个可以自主调用工具的 Agent。"
        f"最多进行 {max_iterations} 轮工具调用；同一个工具可以反复调用，也可以在同一轮调用多个不同工具。"
        "每次回复必须是 JSON，格式为："
        '{"tool_calls":[{"tool":"工具名称","args":{}}],"final_answer":""}。'
        "如果还需要工具，填写 tool_calls；如果已经完成，tool_calls 为空数组，并填写 final_answer。"
        "不要输出 Markdown。"
    )
    tool_names = {str(tool.get("name") or tool.get("id") or "") for tool in selected_tools}
    if "task_plan" in tool_names:
        instructions += (
            "【Task Splitter 任务规划】当节点目标是拆分 Worker 任务时，必须调用 task_plan 工具提交 tasks 数组。"
            "每个任务至少包含 title 和 goal；可补充 targetFiles、suggestedTools。"
            "task_plan 工具会返回 {\"tasks\":[...]}；最终 final_answer 必须只返回该结构化 JSON，不要返回自然语言分析。"
        )
    if tool_names & {"read_file_chunk", "search_code", "list_code_symbols"}:
        instructions += (
            "【代码阅读策略】读取代码或大文件时，先用 search_code 或 list_code_symbols 定位文件、函数、类、组件或关键行；"
            "需要局部内容时使用 read_file_chunk；需要完整符号时使用 extract_code_symbol；需要大文件摘要时使用 chunk_code_semantic。"
            "如果工具结果 truncated=true，继续使用 nextOffset、start_line/end_line 或更精确的 symbol 读取后续片段。"
        )
    if "read_file" in tool_names:
        instructions += (
            "【read_file 截断处理】read_file 只适合小文本。"
            "一旦 read_file 返回 truncated=true，下一轮必须改用 search_code、read_file_chunk 或 chunk_code_semantic，不能反复直接 read_file 同一个大文件。"
        )
    if "extract_html" in tool_names:
        instructions += "读取 HTML 时优先使用 extract_html 按 CSS selector 抽取局部内容，不要直接读取整页。"
    if "extract_css_rules" in tool_names:
        instructions += "读取 CSS 时优先使用 extract_css_rules 按 selector、property 或 query 抽取规则。"
    if tool_names & {"extract_html", "extract_css_rules"}:
        instructions += "如果抽取结果 truncated=true，请缩小 selector/query 或提高匹配精度。"
    if tool_names & {"summarize_page_structure", "extract_html_by_text", "extract_css_for_html", "resolve_asset_references"}:
        instructions += (
            "【页面分析策略】分析 HTML 页面时先用 summarize_page_structure 获取页面结构；"
            "要找包含某段可见文本的区块时使用 extract_html_by_text；"
            "要分析某个 HTML 元素的样式时使用 extract_css_for_html；"
            "需要检查图片、脚本、样式表等本地资源时使用 resolve_asset_references。"
        )
    if tool_names & {"extract_code_symbol", "chunk_code_semantic"}:
        instructions += (
            "需要完整函数、类、方法、组件或 CSS/HTML 局部代码时，优先使用 extract_code_symbol；"
            "面对大代码文件时先用 chunk_code_semantic 或 list_code_symbols 获取语义片段摘要。"
            "如果 extract_code_symbol 返回 ambiguous=true，请根据 alternatives 再次指定更明确的 symbol 或 kind。"
        )
    if tool_names & {"list_directory", "search_code", "read_file_chunk"}:
        instructions += (
            "【RAG/知识库文件读取策略】面对本地知识库或资料目录时，先用 list_directory 查看目录，"
            "再用 search_code 按关键词定位文档，最后用 read_file_chunk 分段读取命中上下文。"
        )
    if tool_names & {"web_search", "fetch_url"}:
        instructions += (
            "【网络搜索策略】web_search 默认返回 DuckDuckGo SERP 结果；搜索无结果时调整关键词或中英文表达。"
            "引用网络信息时优先使用结果中的 title、url 和 snippet；fetch_url 只在需要读取已知 URL 页面内容时使用。"
        )
    if tool_names & {"propose_patch", "replace_in_file", "write_file", "run_whitelisted_command"}:
        instructions += (
            "【代码编辑策略】修改代码前必须先用读取工具定位相关文件、函数、类或页面片段。"
            "默认只能调用 propose_patch 生成待审批补丁，不要直接写文件。"
            "生成补丁后说明修改原因、影响文件和建议验证命令。"
            "如果需要验证，只能使用 run_whitelisted_command 运行白名单命令。"
        )
    if tool_names & {"replace_in_file", "write_file"}:
        instructions += (
            "【直接写入限制】replace_in_file 和 write_file 是高级高风险工具，只有运行环境显式开启 allowDirectEdits 时才可用；"
            "调用前必须说明目标文件和预期修改。"
        )
    registry = "可用工具：\n" + json.dumps(tool_lines, ensure_ascii=False, indent=2)
    return "\n\n".join(part for part in (system_prompt, instructions, registry) if part).strip()


def parse_tool_agent_decision(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {"tool_calls": [], "final_answer": ""}
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
        if isinstance(parsed, list):
            return {"tool_calls": parsed, "final_answer": ""}
        if isinstance(parsed, dict):
            return parsed
    return {"tool_calls": [], "final_answer": text}


def normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def registered_tool_trace_metadata(tool_config: dict[str, Any]) -> dict[str, str]:
    schema = parse_json_object(str(tool_config.get("schemaJson", "{}")))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    server = metadata.get("server") if isinstance(metadata.get("server"), dict) else {}
    source = str(tool_config.get("source") or metadata.get("source") or "")
    return {
        "source": "mcp" if source == "mcp" or metadata.get("kind") == "mcp_tool" else ("agent" if source == "agent" or metadata.get("kind") == "agent_tool" else source),
        "serverName": str(metadata.get("serverName") or server.get("name") or ""),
        "agentName": str(metadata.get("agentName") or ""),
        "toolName": str(metadata.get("toolName") or tool_config.get("name") or ""),
    }


def invoke_registered_tool(
    tool_config: dict[str, Any],
    args: dict[str, Any],
    runtime_environment: RuntimeEnvironment = None,
    model_config: ModelRuntimeConfig = None,
    agent_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_config = fresh_builtin_tool_config(tool_config) or tool_config
    schema = parse_json_object(str(tool_config.get("schemaJson", "{}")))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    kind = str(metadata.get("kind") or "").strip()
    source = str(tool_config.get("source") or "").strip().lower()
    try:
        if source == "builtin" or kind == "builtin_tool":
            result = _builtin.invoke_builtin_tool(metadata, args, runtime_environment)
            return {"ok": True, "result": engine._compact_tool_result(result)}
        if source == "python" or kind == "python_function":
            result = engine._invoke_python_tool(metadata, args)
            return {"ok": True, "result": engine._compact_tool_result(result)}
        if source == "mcp" or kind == "mcp_tool":
            server = metadata.get("server") if isinstance(metadata.get("server"), dict) else {}
            tool_name = str(metadata.get("toolName") or tool_config.get("name") or "").strip()
            result = engine.invoke_mcp_tool(server, tool_name, args, runtime_environment)
            return {"ok": True, "result": engine._compact_tool_result(result)}
        if source == "agent" or kind == "agent_tool":
            result = invoke_agent_tool(metadata, args, model_config, runtime_environment, agent_context)
            return {"ok": bool(result.get("ok", True)), "result": engine._compact_tool_result(result), "errorType": result.get("errorType")}
        if source in {"openapi", "http"} or kind == "openapi_operation":
            return {
                "ok": True,
                "status": "registered_not_executed",
                "message": "该工具已注册为 OpenAPI/HTTP 工具，预览运行暂未配置真实 baseUrl 调用。",
                "operation": {
                    "method": metadata.get("method"),
                    "path": metadata.get("path"),
                },
                "args": args,
            }
        return {
            "ok": True,
            "status": "registered",
            "tool": tool_config.get("name"),
            "source": source or "json",
            "args": args,
        }
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"
        return {"ok": False, "error": error, "errorType": engine._classify_tool_error(error)}


def invoke_agent_tool(
    metadata: dict[str, Any],
    args: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = agent_context or {}
    depth = int(context.get("agentDepth") or 0)
    if depth >= engine.MAX_AGENT_CALL_DEPTH:
        raise RuntimeError(f"子 Agent 调用深度超过限制：{engine.MAX_AGENT_CALL_DEPTH}")
    current_project_id = str(context.get("projectId") or "").strip()
    project_id = str(metadata.get("projectId") or "").strip()
    if not project_id:
        raise RuntimeError("Agent Tool 缺少 projectId。")
    if current_project_id and project_id == current_project_id:
        raise RuntimeError("禁止 Agent 调用当前项目自身，避免递归。")

    input_text = first_text(args.get("input"), args.get("query"), args.get("task"), args.get("message"))
    state_patch = args.get("statePatch") if isinstance(args.get("statePatch"), dict) else {}
    parent_state = context.get("state") if isinstance(context.get("state"), dict) else {}
    child_input = {
        **state_patch,
        "messages": input_text or state_value_to_text(parent_state.get("messages")),
        "chat": input_text or state_value_to_text(parent_state.get("chat") or parent_state.get("messages")),
        "parent_state": compact_state(parent_state),
    }
    started = time.perf_counter()
    child_project = engine.read_project(project_id)
    trace, output_state = engine._walk_project(
        child_project,
        engine._normalize_input(child_input),
        "live",
        normalize_model_config(model_config),
        engine._normalize_runtime_environment(runtime_environment),
        depth + 1,
    )
    error_item = next((item for item in trace if item.get("status") == "error"), None)
    final_answer = agent_child_final_answer(output_state)
    result = {
        "ok": error_item is None,
        "agentId": str(metadata.get("agentId") or ""),
        "agentName": str(metadata.get("agentName") or child_project.project.name or project_id),
        "projectId": project_id,
        "finalAnswer": final_answer,
        "outputState": compact_state(output_state),
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
    }
    if error_item:
        result["error"] = str(error_item.get("detail") or "子 Agent 执行失败。")
        result["errorType"] = "agent_runtime"
    return result


def agent_child_final_answer(output_state: dict[str, Any]) -> str:
    for key in ("final_answer", "answer", "agent_result", "tools_result", "llm_result"):
        text = state_value_to_text(output_state.get(key)).strip()
        if text:
            return text
    return engine._fallback_reply_content(output_state)


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def find_selected_tool(selected_tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = str(name or "").strip().lower()
    if not target:
        return None
    for tool in selected_tools:
        candidates = {str(tool.get("id") or "").lower(), str(tool.get("name") or "").lower()}
        if target in candidates:
            return tool
    return None


def selected_tool_configs(config: dict[str, Any], tools: ToolRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = json_string_list(config.get("toolIdsJson"))
    snapshot_tools = json_object_list(config.get("toolRegistryJson"))
    snapshot_by_id = {str(tool.get("id") or "").strip(): tool for tool in snapshot_tools if str(tool.get("id") or "").strip()}
    if not selected_ids and snapshot_tools:
        selected_ids = [str(tool.get("id") or "").strip() for tool in snapshot_tools if str(tool.get("id") or "").strip()]
    legacy_name = str(config.get("toolName") or "").strip()
    if legacy_name and legacy_name not in selected_ids:
        selected_ids.append(legacy_name)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool_id in selected_ids:
        tool = tools.get(tool_id) or snapshot_by_id.get(tool_id)
        if not tool:
            tool = next((item for item in tools.values() if str(item.get("name") or "") == tool_id), None)
        if not tool:
            continue
        key = str(tool.get("id") or tool.get("name") or tool_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(fresh_builtin_tool_config(tool) or tool)
    return result


def fresh_builtin_tool_config(tool: dict[str, Any]) -> dict[str, Any] | None:
    return engine._fresh_builtin_tool_config(tool)
