from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from app.config import ROOT_DIR
from app.ir.schemas import EdgeKind, NodeIR, NodeType, ProjectIR


RunMode = Literal["dry", "live"]

TEMPLATE_RE = re.compile(r"{{\s*state\.([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
MAX_STEPS = 80


class LiveRunUnsupportedError(RuntimeError):
    pass


def run_project_preview(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _walk_project(project, _normalize_input(input_state), mode)


def _walk_project(project: ProjectIR, input_state: dict[str, Any], mode: RunMode) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes = {node.id: node for node in project.nodes}
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    if not start:
        return [], dict(input_state)

    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    current = _first_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        started = time.perf_counter()
        try:
            delta, detail = _execute_node(node, state, mode)
            state.update(delta)
            status = "ok"
        except Exception as exc:  # Keep the preview response structured instead of surfacing a 500.
            delta = {}
            detail = _format_error(exc)
            status = "error"

        trace.append(
            {
                "nodeId": node.id,
                "type": str(node.type),
                "label": node.label,
                "status": status,
                "detail": detail,
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
                "inputState": _compact_state(before),
                "outputDelta": _compact_state(delta),
            }
        )
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        edges = outgoing.get(node.id, [])
        if not edges:
            break
        conditional_edges = [edge for edge in edges if edge.kind == EdgeKind.CONDITIONAL]
        if conditional_edges:
            handle = _choose_handle(node, state)
            current = _target_for_handle(conditional_edges, handle) or _first_target(conditional_edges)
        else:
            current = _first_target(edges)

    if visited >= MAX_STEPS:
        trace.append(
            {
                "nodeId": "__runtime__",
                "type": "custom_function",
                "label": "运行预览",
                "status": "error",
                "detail": f"路径超过 {MAX_STEPS} 步，可能存在循环。",
                "durationMs": 0,
                "inputState": _compact_state(state),
                "outputDelta": {},
            }
        )
    return trace, state


def _execute_node(node: NodeIR, state: dict[str, Any], mode: RunMode) -> tuple[dict[str, Any], str]:
    if mode == "dry":
        return _execute_dry_node(node, state)
    return _execute_live_node(node, state)


def _execute_dry_node(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    if node.type == NodeType.LLM:
        field = str(config.get("outputField", "final_answer"))
        return {field: f"[dry-run] {node.label} 将调用模型 {config.get('model', 'gpt-4.1-mini')}"}, f"模拟 LLM 输出到 state.{field}"
    if node.type == NodeType.AGENT:
        field = str(config.get("outputField", "agent_result"))
        return {field: f"[dry-run] {node.label} 将作为 Agent 执行"}, f"模拟 Agent 输出到 state.{field}"
    if node.type == NodeType.TOOL:
        field = str(config.get("outputField", "tool_result"))
        return {
            field: {"tool": config.get("toolName", node.label), "status": "dry-run"},
        }, f"模拟 Tool 输出到 state.{field}"
    if node.type == NodeType.RETRIEVER:
        field = str(config.get("outputField", "retrieved_context"))
        return {
            field: f"[dry-run] 从 {config.get('path', './knowledge')} 检索 top_k={config.get('topK', 4)}",
        }, f"模拟 Retriever 输出到 state.{field}"
    if node.type == NodeType.CONDITION:
        return {}, f"按 state.{config.get('field', 'intent')} 选择分支"
    if node.type == NodeType.AI_ROUTER:
        field = str(config.get("routeField", "route_key"))
        fallback = str(config.get("fallback", "other"))
        route = _infer_router_key(config, state) or fallback
        reason_field = str(config.get("reasonField", "route_reason"))
        return {field: route, reason_field: "dry-run router decision"}, f"模拟 AI Router 选择 {route}"
    if node.type == NodeType.HUMAN_APPROVAL:
        action_field = str(config.get("actionField", "approval_action"))
        action = str(state.get(action_field) or config.get("defaultAction", "approved"))
        output_field = str(config.get("outputField", "approval_result"))
        return {
            action_field: action,
            output_field: {"action": action, "status": "dry-run"},
        }, f"模拟人工审批动作 {action}"
    if node.type == NodeType.HTTP:
        field = str(config.get("outputField", "http_response"))
        return {field: {"url": config.get("url", ""), "status": "dry-run"}}, f"模拟 HTTP 输出到 state.{field}"
    if node.type == NodeType.DIRECT_REPLY:
        field = str(config.get("outputField", "final_answer"))
        return {field: state.get(field) or "[dry-run] Direct Reply"}, f"终止并返回 state.{field}"
    if node.type in {NodeType.SKILL_NODE, NodeType.MCP_NODE, NodeType.AGENT_REF, NodeType.CUSTOM_FUNCTION}:
        field = str(config.get("outputField", f"{node.type}_result"))
        return {field: f"[dry-run] {node.label}"}, f"模拟输出到 state.{field}"
    return {}, "跳过未知节点"


def _execute_live_node(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    if node.type == NodeType.LLM:
        return _execute_live_llm(node, state)
    if node.type == NodeType.RETRIEVER:
        return _execute_live_retriever(node, state)
    if node.type == NodeType.CONDITION:
        return {}, f"按 state.{config.get('field', 'intent')} 选择分支"
    if node.type == NodeType.AI_ROUTER:
        field = str(config.get("routeField", "route_key"))
        fallback = str(config.get("fallback", "other"))
        route = _infer_router_key(config, state) or fallback
        reason_field = str(config.get("reasonField", "route_reason"))
        return {field: route, reason_field: "live-run v1 keyword router"}, f"v1 使用关键词路由，选择 {route}"
    if node.type == NodeType.DIRECT_REPLY:
        field = str(config.get("outputField", "final_answer"))
        content = render_template(str(config.get("template", "{{ state.final_answer }}")), state)
        return {field: content}, f"终止并返回 state.{field}"
    raise LiveRunUnsupportedError(f"真实运行 v1 暂不执行 {node.type} 节点；请改用 dry-run，或先使用 LLM/Retriever/Direct Reply 链路。")


def _execute_live_llm(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    provider = str(config.get("provider", "openai")).strip() or "openai"
    model = str(config.get("model", "gpt-4.1-mini")).strip() or "gpt-4.1-mini"
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    user_prompt = render_template(str(config.get("userPrompt", "{{ state.messages }}")), state).strip()
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_prompt or _state_value_to_text(state.get("messages", ""))))
    response = _call_chat_model(provider, model, messages)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_output"))
    return {output_field: content}, f"真实调用 {provider}/{model}，输出到 state.{output_field}"


def _execute_live_retriever(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_context"))
    root = _resolve_path(str(config.get("path", "./knowledge")))
    top_k = _positive_int(config.get("topK", 4), 4)
    query = render_template(str(config.get("query", "{{ state.messages }}")), state)
    if not root.exists():
        return {output_field: ""}, f"知识库目录不存在：{root}"

    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)
    ranked = _rank_documents(files, query)
    selected = ranked[:top_k] if ranked else []
    context_parts = []
    for score, path, text in selected:
        try:
            source = path.relative_to(root).as_posix()
        except ValueError:
            source = path.as_posix()
        context_parts.append(f"来源: {source}\n相关度: {score}\n{text[:2400]}")
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"检索 {len(files)} 个文档，返回 {len(context_parts)} 段到 state.{output_field}"


def _call_chat_model(provider: str, model: str, messages: list[tuple[str, str]]) -> Any:
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError("后端缺少 LangChain 模型运行依赖，请安装 requirements-dev.txt 后重试。") from exc

    try:
        chat_model = init_chat_model(model, model_provider=provider)
        return chat_model.invoke(messages)
    except Exception as exc:
        raise RuntimeError(f"模型调用失败：{exc}") from exc


def render_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        return _state_value_to_text(state.get(match.group(1), ""))

    return TEMPLATE_RE.sub(replace, template)


def _rank_documents(files: list[Path], query: str) -> list[tuple[int, Path, str]]:
    terms = _query_terms(query)
    ranked: list[tuple[int, Path, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if not terms:
            score = 1
        else:
            score = sum(lowered.count(term) for term in terms)
        if score > 0:
            ranked.append((score, path, text))
    ranked.sort(key=lambda item: (-item[0], item[1].as_posix()))
    if ranked:
        return ranked

    fallback: list[tuple[int, Path, str]] = []
    for path in files:
        try:
            fallback.append((0, path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return fallback


def _query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms = [term for term in re.split(r"[\s,，。！？；;:：、/\\]+", normalized) if len(term) >= 2]
    cjk_pairs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    for phrase in cjk_pairs:
        terms.extend(phrase[index : index + 2] for index in range(max(0, len(phrase) - 1)))
    return sorted(set(terms), key=lambda item: (-len(item), item))


def _choose_handle(node: NodeIR, state: dict[str, Any]) -> str:
    config = node.config
    if node.type == NodeType.CONDITION:
        field = str(config.get("field", ""))
        current = state.get(field)
        expected = str(config.get("value", ""))
        matched = _compare(current, expected, str(config.get("operator", "equals")))
        return str(config.get("trueBranch" if matched else "falseBranch", config.get("fallback", "fallback")))
    if node.type == NodeType.AI_ROUTER:
        return str(state.get(str(config.get("routeField", "route_key"))) or config.get("fallback", "other"))
    if node.type == NodeType.HUMAN_APPROVAL:
        return str(state.get(str(config.get("actionField", "approval_action"))) or config.get("fallback", "rejected"))
    return str(config.get("fallback", "fallback"))


def _compare(current: Any, expected: str, operator: str) -> bool:
    current_text = "" if current is None else str(current)
    if operator == "not_equals":
        return current_text != expected
    if operator == "contains":
        return expected in current_text
    if operator == "not_contains":
        return expected not in current_text
    if operator == "is_empty":
        return not current_text
    if operator == "is_not_empty":
        return bool(current_text)
    return current_text == expected


def _infer_router_key(config: dict[str, Any], state: dict[str, Any]) -> str | None:
    text = json.dumps(state, ensure_ascii=False).lower()
    for line in str(config.get("scenarios", "")).splitlines():
        parts = (line.split(":", 2) + ["", ""])[:3]
        key = parts[0].strip()
        keywords = [item.strip().lower() for item in parts[2].split(",") if item.strip()]
        if key and keywords and any(keyword in text for keyword in keywords):
            return key
    return None


def _normalize_input(input_state: dict[str, Any]) -> dict[str, Any]:
    state = dict(input_state)
    if "messages" not in state:
        if "message" in state:
            state["messages"] = state["message"]
        elif "input" in state:
            state["messages"] = state["input"]
    return state


def _state_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and "content" in item:
                parts.append(str(item["content"]))
            else:
                parts.append(_state_value_to_text(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: _compact_value(value) for key, value in state.items()}


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:12]]
    if isinstance(value, str) and len(value) > 1200:
        return value[:1200] + "...[truncated]"
    return value


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _format_error(exc: Exception) -> str:
    if isinstance(exc, LiveRunUnsupportedError):
        return str(exc)
    return f"{exc.__class__.__name__}: {exc}"


def _first_target(edges: list) -> str | None:
    return edges[0].target if edges else None


def _target_for_handle(edges: list, handle: str) -> str | None:
    for edge in edges:
        if edge.sourceHandle == handle:
            return edge.target
    return None
