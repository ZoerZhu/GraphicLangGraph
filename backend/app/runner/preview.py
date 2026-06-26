from __future__ import annotations

import asyncio
import ast
import fnmatch
import html as html_lib
import importlib.util
import inspect
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from html.parser import HTMLParser
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Literal
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib import request as urllib_request
from urllib.error import URLError

import httpx

from app.builtin_tools import builtin_tool_config_by_id
from app.code_intelligence import (
    glg_asset_references,
    glg_chunk_code_semantic,
    glg_extract_code_symbol,
    glg_extract_css_for_html,
    glg_extract_html_by_text,
    glg_semantic_symbols,
    glg_summarize_page_structure,
)
from app.config import ROOT_DIR, WORKSPACE_MCP_FILE, WORKSPACE_TOOLS_FILE
from app.edit_sessions import EditSessionError, propose_patch, replace_in_file, run_whitelisted_command, write_file
from app.ir.schemas import EdgeKind, NodeIR, NodeType, ProjectIR
from app.mcp_runtime import invoke_mcp_tool, list_mcp_tools, make_mcp_agent_tool_config, normalize_mcp_server_config
from app.project_store import read_project
from app.runtime_environment import default_runtime_environment, resolve_runtime_environment


RunMode = Literal["dry", "live"]
ModelRuntimeConfig = dict[str, Any] | None
RuntimeEnvironment = dict[str, Any] | None
SkillRuntimeConfig = dict[str, dict[str, Any]]
ToolRuntimeConfig = dict[str, dict[str, Any]]
McpRuntimeConfig = dict[str, dict[str, Any]]
AgentRuntimeConfig = dict[str, dict[str, Any]]

TEMPLATE_RE = re.compile(r"{{\s*state\.([a-zA-Z_][a-zA-Z0-9_\.\[\]]*)\s*}}")
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
MAX_STEPS = 80
MAX_AGENT_CALL_DEPTH = 3
TOOL_OBSERVATION_STRING_LIMIT = 12_000
SKILL_CORE_RUNTIME_LIMIT = 60_000
SKILL_REFERENCES_RUNTIME_LIMIT = 30_000
SKILL_SUPPORT_FILES_RUNTIME_LIMIT = 12_000
CODE_TOOL_EXCLUDED_DIRS = {".git", ".hg", ".svn", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".next", ".turbo", "coverage"}
CODE_TOOL_BINARY_CHECK_BYTES = 4096
OPENAI_COMPATIBLE_PROVIDERS = {
    "custom",
    "openai_compatible",
    "deepseek",
    "moonshot",
    "qwen",
    "zhipu",
    "minimax",
    "baichuan",
    "groq",
    "ollama",
}
OPENAI_COMPATIBLE_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "moonshot": "https://api.moonshot.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax": "https://api.minimax.chat/v1",
    "baichuan": "https://api.baichuan-ai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
}


class NodePolicyError(RuntimeError):
    def __init__(self, node: NodeIR, original: Exception, payload: dict[str, Any], attempts: list[dict[str, Any]], policy: dict[str, Any]):
        super().__init__(str(payload.get("message") or original))
        self.node = node
        self.original = original
        self.payload = payload
        self.attempts = attempts
        self.policy = policy


class NodeTimeoutError(RuntimeError):
    pass
PROVIDER_ALIASES = {
    "google": "google_genai",
}


class LiveRunUnsupportedError(RuntimeError):
    pass


def run_project_preview(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
    model_config: ModelRuntimeConfig = None,
    runtime_environment: RuntimeEnvironment = None,
    agent_depth: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _walk_project(
        project,
        _normalize_input(input_state),
        mode,
        _normalize_model_config(model_config),
        _normalize_runtime_environment(runtime_environment),
        agent_depth,
    )


def iter_project_preview_events(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode = "dry",
    model_config: ModelRuntimeConfig = None,
    runtime_environment: RuntimeEnvironment = None,
    agent_depth: int = 0,
):
    yield from _walk_project_events(
        project,
        _normalize_input(input_state),
        mode,
        _normalize_model_config(model_config),
        _normalize_runtime_environment(runtime_environment),
        agent_depth,
    )


def collect_data_shaping_paths(project: ProjectIR, state: dict[str, Any] | None = None, run_record: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = {}

    def add(path: str, value_type: str, source: str, label: str = "", value: Any = _MISSING) -> None:
        if not path:
            return
        item = paths.setdefault(
            path,
            {
                "path": path,
                "type": value_type or "Any",
                "source": source,
                "label": label or path,
            },
        )
        if value is not _MISSING and "value" not in item:
            item["value"] = _compact_value(value)

    for field in getattr(project.state, "fields", []) or []:
        add(field.name, field.type, "state", field.description or field.name)

    for node in project.nodes:
        for path, value_type in _declared_output_fields_for_node(node):
            add(path, value_type, "node", f"{node.label} 输出")

    runtime_states: list[tuple[str, dict[str, Any]]] = []
    if isinstance(state, dict):
        runtime_states.append(("input", state))
    if isinstance(run_record, dict):
        result = run_record.get("result") if isinstance(run_record.get("result"), dict) else {}
        output_state = result.get("outputState") if isinstance(result.get("outputState"), dict) else {}
        if output_state:
            runtime_states.append(("run_output", output_state))
        for trace_item in result.get("trace") or []:
            if not isinstance(trace_item, dict):
                continue
            output_delta = trace_item.get("outputDelta")
            if isinstance(output_delta, dict):
                runtime_states.append((f"trace:{trace_item.get('nodeId') or ''}", output_delta))

    for source, runtime_state in runtime_states:
        for item in _collect_value_paths(runtime_state):
            add(str(item["path"]), str(item["type"]), source, str(item.get("label") or item["path"]), item.get("value", _MISSING))

    return sorted(paths.values(), key=lambda item: (item["path"].count("."), item["path"]))


def preview_data_shaping_node(
    project: ProjectIR,
    node_id: str,
    state: dict[str, Any] | None = None,
    model_config: ModelRuntimeConfig = None,
) -> dict[str, Any]:
    node = next((item for item in project.nodes if item.id == node_id), None)
    if node is None:
        return {"ok": False, "nodeId": node_id, "errors": ["Node not found"]}
    working_state = _normalize_input(state or {})
    result: dict[str, Any] = {
        "ok": True,
        "nodeId": node.id,
        "nodeType": str(node.type),
        "inputs": {},
        "delta": {},
        "validation": None,
        "repair": None,
        "detail": "",
        "errors": [],
    }
    try:
        result["inputs"] = _resolve_input_mappings(node.config, working_state)
        if node.type == NodeType.VARIABLE_ASSIGN:
            delta, detail = _execute_variable_assign(node, working_state)
        elif node.type == NodeType.TEMPLATE:
            delta, detail = _execute_template_node(node, working_state)
        elif node.type == NodeType.JSON_EXTRACTOR:
            delta, detail = _execute_live_json_extractor(node, working_state, model_config)
        elif node.type == NodeType.JSON_VALIDATOR:
            delta, detail = _execute_json_validator(node, working_state, model_config, allow_repair=True)
        else:
            raise RuntimeError("只支持预览 Variable Assign、Template、JSON Extractor、JSON Validator。")
        validation_field = str(node.config.get("validationField", "validation_result"))
        repair_field = str(node.config.get("repairResultField", "repair_result"))
        result.update(
            {
                "delta": delta,
                "validation": delta.get(validation_field),
                "repair": delta.get(repair_field),
                "detail": detail,
            }
        )
    except Exception as exc:
        result["ok"] = False
        result["errors"] = [str(exc)]
    return result


def _walk_project(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_depth: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nodes = {node.id: node for node in project.nodes}
    skills = _enabled_skills_by_id(project)
    tools = _tool_configs_by_id(project)
    mcp_servers = _mcp_configs_by_id(project)
    agents = _agent_configs_by_id(project)
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    if not start:
        return [], dict(input_state)

    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    current = _first_execution_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        started = time.perf_counter()
        handled_error_target: str | None = None
        trace_meta: dict[str, Any] = {}
        try:
            delta, detail, trace_meta = _execute_node_with_policy(node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            state.update(delta)
            status = "ok"
        except Exception as exc:  # Keep the preview response structured instead of surfacing a 500.
            handled_error_target = _error_execution_target(node, outgoing)
            trace_meta = _trace_meta_from_exception(exc)
            if handled_error_target:
                delta = {"last_error": _runtime_error_payload(node, exc)}
                state.update(delta)
                detail = f"{_format_error(exc)}；已转入 error 分支。"
                status = "ok"
            else:
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
                **trace_meta,
            }
        )
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        current = handled_error_target or _next_execution_target(node, nodes, outgoing, state)

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


def _walk_project_events(
    project: ProjectIR,
    input_state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_depth: int,
):
    nodes = {node.id: node for node in project.nodes}
    skills = _enabled_skills_by_id(project)
    tools = _tool_configs_by_id(project)
    mcp_servers = _mcp_configs_by_id(project)
    agents = _agent_configs_by_id(project)
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    start = next((node for node in project.nodes if node.type == NodeType.START), None)
    state = dict(input_state)
    trace: list[dict[str, Any]] = []
    if not start:
        yield {
            "event": "run_end",
            "trace": trace,
            "outputState": _compact_state(state),
        }
        return

    current = _first_execution_target(outgoing.get(start.id, []))
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        visited += 1
        node = nodes[current]
        before = dict(state)
        yield {
            "event": "node_start",
            "nodeId": node.id,
            "type": str(node.type),
            "label": node.label,
            "inputState": _compact_state(before),
        }
        started = time.perf_counter()
        handled_error_target: str | None = None
        child_trace_items: list[dict[str, Any]] = []
        trace_meta: dict[str, Any] = {}
        try:
            if mode == "live" and node.type == NodeType.PARALLEL_TOOLS:
                def run_parallel_tools_stream():
                    stream_delta, stream_detail = yield from _execute_live_parallel_tools_events(project, node, state, model_config, runtime_environment, tools)
                    return stream_delta, stream_detail, []

                delta, detail, child_trace_items, trace_meta = yield from _execute_stream_node_with_policy(node, state, run_parallel_tools_stream)
            elif mode == "live" and node.type == NodeType.FOR_EACH:
                def run_for_each_stream():
                    return (yield from _execute_for_each_node_events(project, node, state, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth))

                delta, detail, child_trace_items, trace_meta = yield from _execute_stream_node_with_policy(node, state, run_for_each_stream)
            else:
                delta, detail, trace_meta = _execute_node_with_policy(node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            state.update(delta)
            status = "ok"
        except Exception as exc:  # Keep streamed events structured instead of surfacing a 500.
            handled_error_target = _error_execution_target(node, outgoing)
            trace_meta = _trace_meta_from_exception(exc)
            if handled_error_target:
                delta = {"last_error": _runtime_error_payload(node, exc)}
                state.update(delta)
                detail = f"{_format_error(exc)}；已转入 error 分支。"
                status = "ok"
            else:
                delta = {}
                detail = _format_error(exc)
                status = "error"

        trace_item = {
            "nodeId": node.id,
            "type": str(node.type),
            "label": node.label,
            "status": status,
            "detail": detail,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            "inputState": _compact_state(before),
            "outputDelta": _compact_state(delta),
            **trace_meta,
        }
        trace.extend(child_trace_items)
        trace.append(trace_item)
        yield {
            "event": "node_end",
            "traceItem": trace_item,
            "outputState": _compact_state(state),
        }
        if status == "error" or node.type == NodeType.DIRECT_REPLY:
            break

        current = handled_error_target or _next_execution_target(node, nodes, outgoing, state)

    if visited >= MAX_STEPS:
        trace_item = {
            "nodeId": "__runtime__",
            "type": "custom_function",
            "label": "运行预览",
            "status": "error",
            "detail": f"路径超过 {MAX_STEPS} 步，可能存在循环。",
            "durationMs": 0,
            "inputState": _compact_state(state),
            "outputDelta": {},
        }
        trace.append(trace_item)
        yield {
            "event": "node_end",
            "traceItem": trace_item,
            "outputState": _compact_state(state),
        }

    yield {
        "event": "run_end",
        "trace": trace,
        "outputState": _compact_state(state),
    }


def _execute_node(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    if mode == "dry":
        return _execute_dry_node(node, state, skills, tools)
    return _execute_live_node(node, project, state, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)


def _execute_node_with_policy(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    policy = _node_runtime_policy(node.config)
    attempts: list[dict[str, Any]] = []
    max_attempts = 1 + (policy["maxRetries"] if policy["retryEnabled"] else 0)
    last_exc: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            delta, detail = _call_node_with_timeout(
                lambda: _execute_node(node, project, state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth),
                policy["timeoutSec"],
            )
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "ok",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            if attempt_index > 1:
                detail = f"{detail}；重试第 {attempt_index} 次后成功。"
            trace_meta = _successful_policy_trace_meta(node, attempts)
            trace_meta.update(_data_shaping_trace_meta(node, state, delta))
            return delta, detail, trace_meta
        except Exception as exc:
            last_exc = exc
            error_type = _policy_error_type(exc)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "error",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                    "errorType": error_type,
                    "message": str(exc),
                }
            )
            if attempt_index < max_attempts and _should_retry_error(policy, error_type, exc):
                backoff_ms = min(max(policy["backoffMs"], 0) * attempt_index, 5000)
                if backoff_ms:
                    time.sleep(backoff_ms / 1000)
                continue
            break
    assert last_exc is not None
    payload = _runtime_error_payload(node, last_exc)
    payload["attempts"] = attempts
    payload["errorPolicy"] = policy["errorPolicy"]
    if policy["timeoutSec"]:
        payload["timeoutSec"] = policy["timeoutSec"]
    policy_name = policy["errorPolicy"]
    if policy_name == "fallback":
        delta = _fallback_policy_delta(node, state, policy, payload)
        return delta, f"{payload['errorType']}: {payload['message']}；已按 fallback 策略继续。", _failed_policy_trace_meta(node, attempts, policy)
    if policy_name == "continue":
        field = policy["errorOutputField"] or "last_error"
        return {field: payload}, f"{payload['errorType']}: {payload['message']}；已按 continue 策略继续。", _failed_policy_trace_meta(node, attempts, policy)
    raise NodePolicyError(node, last_exc, payload, attempts, policy)


def _call_node_with_timeout(fn, timeout_sec: float | None) -> tuple[dict[str, Any], str]:
    if not timeout_sec:
        return fn()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FutureTimeoutError as exc:
        future.cancel()
        raise NodeTimeoutError(f"节点执行超过 {timeout_sec}s。") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _execute_stream_node_with_policy(
    node: NodeIR,
    state: dict[str, Any],
    stream_factory,
):
    policy = _node_runtime_policy(node.config)
    attempts: list[dict[str, Any]] = []
    max_attempts = 1 + (policy["maxRetries"] if policy["retryEnabled"] else 0)
    last_exc: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            delta, detail, child_trace_items = yield from _call_stream_with_timeout(stream_factory, policy["timeoutSec"])
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "ok",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            if attempt_index > 1:
                detail = f"{detail}；重试第 {attempt_index} 次后成功。"
            return delta, detail, child_trace_items or [], _successful_policy_trace_meta(node, attempts)
        except Exception as exc:
            last_exc = exc
            error_type = _policy_error_type(exc)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "error",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                    "errorType": error_type,
                    "message": str(exc),
                }
            )
            if attempt_index < max_attempts and _should_retry_error(policy, error_type, exc):
                backoff_ms = min(max(policy["backoffMs"], 0) * attempt_index, 5000)
                if backoff_ms:
                    time.sleep(backoff_ms / 1000)
                continue
            break
    assert last_exc is not None
    payload = _runtime_error_payload(node, last_exc)
    payload["attempts"] = attempts
    payload["errorPolicy"] = policy["errorPolicy"]
    if policy["timeoutSec"]:
        payload["timeoutSec"] = policy["timeoutSec"]
    if policy["errorPolicy"] == "fallback":
        delta = _fallback_policy_delta(node, state, policy, payload)
        return delta, f"{payload['errorType']}: {payload['message']}；已按 fallback 策略继续。", [], _failed_policy_trace_meta(node, attempts, policy)
    if policy["errorPolicy"] == "continue":
        field = policy["errorOutputField"] or "last_error"
        return {field: payload}, f"{payload['errorType']}: {payload['message']}；已按 continue 策略继续。", [], _failed_policy_trace_meta(node, attempts, policy)
    raise NodePolicyError(node, last_exc, payload, attempts, policy)


def _call_stream_with_timeout(stream_factory, timeout_sec: float | None):
    if not timeout_sec:
        return (yield from stream_factory())
    event_queue: Queue[tuple[str, Any]] = Queue()

    def pump() -> None:
        try:
            generator = stream_factory()
            while True:
                try:
                    event_queue.put(("event", next(generator)))
                except StopIteration as stop:
                    event_queue.put(("result", stop.value))
                    return
        except Exception as exc:
            event_queue.put(("error", exc))

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(pump)
    deadline = time.perf_counter() + timeout_sec
    try:
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                future.cancel()
                raise NodeTimeoutError(f"节点执行超过 {timeout_sec}s。")
            try:
                kind, payload = event_queue.get(timeout=min(0.05, remaining))
            except Empty:
                continue
            if kind == "event":
                yield payload
                continue
            if kind == "result":
                return payload
            if kind == "error":
                raise payload
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _execute_dry_node(node: NodeIR, state: dict[str, Any], skills: SkillRuntimeConfig, tools: ToolRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    if node.type == NodeType.LLM:
        field = str(config.get("outputField", "final_answer"))
        return {field: f"[dry-run] {node.label} 将调用模型 {config.get('model', 'gpt-4.1-mini')}"}, f"模拟 LLM 输出到 state.{field}"
    if node.type == NodeType.AGENT:
        field = str(config.get("outputField", "agent_result"))
        return {field: f"[dry-run] {node.label} 将作为 Agent 执行"}, f"模拟 Agent 输出到 state.{field}"
    if node.type == NodeType.TOOL:
        field = str(config.get("outputField", "tool_result"))
        selected_tools = _selected_tool_configs(config, tools)
        return {
            field: f"[dry-run] {node.label} 可在 {len(selected_tools)} 个 Tool 中自主选择并多轮调用",
            f"{field}_tool_calls": [
                {"tool": tool.get("name") or tool.get("id"), "status": "registered"} for tool in selected_tools
            ],
        }, f"模拟 Tools Agent 注册 {len(selected_tools)} 个 Tool，输出到 state.{field}"
    if node.type == NodeType.TASK_SPLITTER:
        field = str(config.get("outputField", "worker_tasks"))
        max_tasks = min(_positive_int(config.get("maxTasks"), 5), 10)
        return {
            field: [
                {
                    "id": f"task_{index}",
                    "title": f"示例子任务 {index}",
                    "goal": f"[dry-run] 根据规划结果拆分的第 {index} 个代码阅读任务",
                    "targetFiles": [],
                    "suggestedTools": [],
                    "status": "pending",
                }
                for index in range(1, min(max_tasks, 3) + 1)
            ]
        }, f"模拟拆分 {min(max_tasks, 3)} 个 Worker 任务，输出到 state.{field}"
    if node.type == NodeType.PARALLEL_TOOLS:
        field = str(config.get("outputField", "worker_results"))
        selected_tools = _selected_tool_configs(config, tools)
        return {
            field: [
                {
                    "taskId": "task_1",
                    "title": "[dry-run] 示例 Worker",
                    "status": "ok",
                    "durationMs": 0,
                    "summary": f"{node.label} 将并行调用 {len(selected_tools)} 个可用 Tool 完成子任务。",
                    "evidence": [],
                    "warnings": [],
                }
            ]
        }, f"模拟 Parallel Tools 并行 Worker，输出到 state.{field}"
    if node.type == NodeType.VARIABLE_ASSIGN:
        delta, detail = _execute_variable_assign(node, state)
        return delta, f"[dry-run] {detail}"
    if node.type == NodeType.TEMPLATE:
        delta, detail = _execute_template_node(node, state)
        return delta, f"[dry-run] {detail}"
    if node.type == NodeType.JSON_EXTRACTOR:
        output_field = str(config.get("outputField", "extracted_json"))
        validation_field = str(config.get("validationField", "validation_result"))
        schema = _json_schema_from_config(config)
        output = _sample_json_from_schema(schema)
        validation = _validation_result(output, schema)
        return {
            output_field: output,
            validation_field: validation,
        }, f"模拟 JSON Extractor 输出到 state.{output_field}"
    if node.type == NodeType.JSON_VALIDATOR:
        delta, detail = _execute_json_validator(node, state)
        return delta, f"[dry-run] {detail}"
    if node.type == NodeType.FOR_EACH:
        return _execute_for_each_node(node, project, state, "dry", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
    if node.type == NodeType.MERGE:
        return _execute_merge_node(node, state, [state])
    if node.type == NodeType.ERROR_HANDLER:
        delta, detail = _execute_error_handler(node, state)
        return delta, f"[dry-run] {detail}"
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
        return {field: state.get(field) or _fallback_reply_content(state) or "[dry-run] Direct Reply"}, f"终止并返回 state.{field}"
    if node.type == NodeType.SKILL_NODE:
        return _execute_skill_node(node, skills, dry_run=True)
    if node.type in {NodeType.MCP_NODE, NodeType.AGENT_REF, NodeType.CUSTOM_FUNCTION}:
        field = str(config.get("outputField", f"{node.type}_result"))
        return {field: f"[dry-run] {node.label}"}, f"模拟输出到 state.{field}"
    return {}, "跳过未知节点"


def _execute_live_node(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    config = node.config
    if node.type == NodeType.LLM:
        return _execute_live_llm(node, state, model_config)
    if node.type == NodeType.AGENT:
        return _execute_live_agent(node, project, state, model_config, runtime_environment, skills, mcp_servers, agents, agent_depth)
    if node.type == NodeType.AGENT_REF:
        return _execute_live_agent_ref(node, project, state, model_config, runtime_environment, agent_depth)
    if node.type == NodeType.SKILL_NODE:
        return _execute_skill_node(node, skills, dry_run=False)
    if node.type == NodeType.MCP_NODE:
        return _execute_live_mcp_node(node, state, model_config, runtime_environment, mcp_servers)
    if node.type == NodeType.TOOL:
        return _execute_live_tool(node, state, model_config, runtime_environment, tools)
    if node.type == NodeType.TASK_SPLITTER:
        return _execute_live_task_splitter(node, state)
    if node.type == NodeType.PARALLEL_TOOLS:
        return _execute_live_parallel_tools(project, node, state, model_config, runtime_environment, tools)
    if node.type == NodeType.VARIABLE_ASSIGN:
        return _execute_variable_assign(node, state)
    if node.type == NodeType.TEMPLATE:
        return _execute_template_node(node, state)
    if node.type == NodeType.JSON_EXTRACTOR:
        return _execute_live_json_extractor(node, state, model_config)
    if node.type == NodeType.JSON_VALIDATOR:
        return _execute_json_validator(node, state, model_config, allow_repair=True)
    if node.type == NodeType.FOR_EACH:
        return _execute_for_each_node(node, project, state, "live", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
    if node.type == NodeType.MERGE:
        return _execute_merge_node(node, state, [state])
    if node.type == NodeType.ERROR_HANDLER:
        return _execute_error_handler(node, state)
    if node.type == NodeType.RETRIEVER:
        return _execute_live_retriever(node, state)
    if node.type == NodeType.CONDITION:
        return {}, f"按 state.{config.get('field', 'intent')} 选择分支"
    if node.type == NodeType.AI_ROUTER:
        return _execute_live_ai_router(node, state, model_config)
    if node.type == NodeType.HUMAN_APPROVAL:
        return _execute_live_human_approval(node, state)
    if node.type == NodeType.HTTP:
        return _execute_live_http(node, state)
    if node.type == NodeType.DIRECT_REPLY:
        field = str(config.get("outputField", "final_answer"))
        content = render_template(str(config.get("template", "{{ state.final_answer }}")), state)
        if not content.strip():
            content = _fallback_reply_content(state)
        return {field: content}, f"终止并返回 state.{field}"
    raise LiveRunUnsupportedError(f"真实运行 v1 暂不执行 {node.type} 节点；请改用 dry-run，或先使用 LLM/Retriever/Direct Reply 链路。")


def _execute_live_llm(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    effective_model_config = _effective_model_config(config, model_config)
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    user_prompt = render_template(str(config.get("userPrompt", "{{ state.messages }}")), state).strip()
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_prompt or _state_value_to_text(state.get("messages", ""))))
    response = _call_chat_model(provider, model, messages, effective_model_config)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_output"))
    config_name = _runtime_value(model_config, "name")
    suffix = f"（{config_name}）" if config_name else ""
    return {output_field: content}, f"真实调用 {provider}/{model}{suffix}，输出到 state.{output_field}"


def _execute_live_agent(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    config = node.config
    effective_model_config = _effective_model_config(config, model_config)
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    system_prompt = _append_selected_skills(system_prompt, _selected_skill_configs(config, skills))
    user_prompt = str(config.get("userPrompt", "")).strip()
    if user_prompt:
        user_text = render_template(user_prompt, state)
    else:
        user_text = _agent_state_prompt(state)
    selected_mcp_servers = _selected_mcp_server_configs(config, mcp_servers)
    selected_agents = _selected_agent_configs(config, agents)
    if selected_mcp_servers or selected_agents:
        max_iterations = min(_positive_int(config.get("maxIterations", 4), 4), 12)
        mcp_tools = _mcp_agent_tool_configs(selected_mcp_servers, runtime_environment)
        agent_tools = _agent_tool_configs(selected_agents, project)
        registered_tools = [*mcp_tools, *agent_tools]
        if selected_mcp_servers and not mcp_tools:
            raise RuntimeError("Agent 已选择 MCP Server，但没有可用 MCP Tool。")
        if selected_agents and not agent_tools:
            raise RuntimeError("Agent 已选择子 Agent，但没有可用 Agent Tool。")
        final_answer, calls = _run_tools_agent_session(
            provider,
            model,
            effective_model_config,
            registered_tools,
            system_prompt,
            user_text,
            max_iterations,
            runtime_environment,
            {
                "projectId": project.project.id,
                "projectName": project.project.name,
                "state": state,
                "agentDepth": agent_depth,
                "modelConfig": effective_model_config,
            },
        )
        output_field = str(config.get("outputField", f"{node.id}_result"))
        skill_count = len(_selected_skill_configs(config, skills))
        skill_hint = f"，注入 {skill_count} 个 Skill" if skill_count else ""
        result = {
            output_field: final_answer,
        }
        if mcp_tools:
            result[f"{output_field}_mcp_tool_calls"] = [call for call in calls if str(call.get("source") or "") == "mcp"]
        if agent_tools:
            result[f"{output_field}_agent_tool_calls"] = [call for call in calls if str(call.get("source") or "") == "agent"]
        return result, f"真实调用 Agent 模型 {provider}/{model}{skill_hint}，注册 {len(registered_tools)} 个工具，执行 {len(calls)} 次调用，输出到 state.{output_field}"
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    messages.append(("user", user_text))
    response = _call_chat_model(provider, model, messages, effective_model_config)
    content = getattr(response, "content", str(response))
    output_field = str(config.get("outputField", f"{node.id}_result"))
    tools = str(config.get("tools", "")).strip()
    tool_hint = f"，参考工具/前置结果：{tools}" if tools else ""
    skill_count = len(_selected_skill_configs(config, skills))
    skill_hint = f"，注入 {skill_count} 个 Skill" if skill_count else ""
    return {output_field: content}, f"真实调用 Agent 模型 {provider}/{model}{tool_hint}{skill_hint}，输出到 state.{output_field}"


def _execute_skill_node(node: NodeIR, skills: SkillRuntimeConfig, dry_run: bool) -> tuple[dict[str, Any], str]:
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


def _execute_live_mcp_node(
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    mcp_servers: McpRuntimeConfig,
) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", "mcp_result")).strip() or "mcp_result"
    server = _mcp_server_for_node(config, mcp_servers)
    if not server:
        raise RuntimeError("MCP Node 未绑定有效 MCP Server。")
    tool_name = str(config.get("toolName") or "").strip()
    args = _render_json_object(str(config.get("toolArgsJson") or "{}"), state, "toolArgsJson")
    available_tools: list[dict[str, Any]] = []
    auto_selected = False
    selected_by_model = False
    selection_reason = ""
    selection_mode = _mcp_tool_selection_mode(config, bool(tool_name))
    selected_tool: dict[str, Any] | None = None
    if not tool_name:
        available_tools = list_mcp_tools(server, runtime_environment)
        if selection_mode == "manual":
            candidates = ", ".join(str(tool.get("name") or "") for tool in available_tools if str(tool.get("name") or "").strip())
            raise RuntimeError(f"MCP Node 未选择 MCP Tool。可选工具：{candidates}" if candidates else "MCP Node 未选择 MCP Tool。")
        if selection_mode == "model":
            try:
                selection = _select_mcp_tool_with_model(config, available_tools, args, state, model_config)
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
                if not _truthy(config.get("fallbackToHeuristic")):
                    raise
                selected_tool = _select_default_mcp_tool(available_tools, args, state)
                tool_name = str(selected_tool.get("name") or "").strip()
                selection_reason = "model_selection_failed_fallback_to_heuristic"
        else:
            selected_tool = _select_default_mcp_tool(available_tools, args, state)
            tool_name = str(selected_tool.get("name") or "").strip()
        tool_name = str(selected_tool.get("name") or "").strip()
        auto_selected = True
    if not tool_name:
        raise RuntimeError("MCP Node 未选择 MCP Tool，且无法自动选择。")
    if selected_tool is None and available_tools:
        selected_tool = next((tool for tool in available_tools if str(tool.get("name") or "") == tool_name), None)
    args = _ensure_mcp_default_args(args, selected_tool, state)
    result = invoke_mcp_tool(server, tool_name, args, runtime_environment)
    if isinstance(result, dict):
        result["autoSelectedTool"] = auto_selected
        result["selectionMode"] = selection_mode
        result["selectedByModel"] = selected_by_model
        result["selectionReason"] = selection_reason
        if available_tools:
            result["availableTools"] = [_mcp_tool_summary(tool) for tool in available_tools]
    server_name = str(result.get("serverName") or server.get("name") or "未命名 MCP")
    return {output_field: result}, f"真实调用 MCP「{server_name}」工具 {tool_name}，输出到 state.{output_field}"


def _mcp_tool_selection_mode(config: dict[str, Any], has_explicit_tool: bool) -> str:
    if has_explicit_tool:
        return "manual"
    mode = str(config.get("toolSelectionMode") or "").strip().lower()
    return mode if mode in {"manual", "heuristic", "model"} else "heuristic"


def _select_mcp_tool_with_model(
    config: dict[str, Any],
    tools: list[dict[str, Any]],
    base_args: dict[str, Any],
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
) -> dict[str, Any]:
    available = [tool for tool in tools if str(tool.get("name") or "").strip()]
    if not available:
        raise RuntimeError("MCP Server 未暴露可调用 Tool。")
    selection_config = _mcp_tool_selection_model_config(config)
    effective_model_config = _effective_model_config(selection_config, model_config)
    provider, model = _resolve_node_model(selection_config, model_config, "openai", "gpt-4.1-mini")
    messages = [
        ("system", _mcp_tool_selection_system_prompt(config, available)),
        ("user", _mcp_tool_selection_user_prompt(state, base_args)),
    ]
    response = _call_chat_model(provider, model, messages, effective_model_config)
    content = getattr(response, "content", str(response))
    selection = _parse_mcp_tool_selection(content)
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


def _mcp_tool_selection_model_config(config: dict[str, Any]) -> dict[str, Any]:
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


def _mcp_tool_selection_system_prompt(config: dict[str, Any], tools: list[dict[str, Any]]) -> str:
    instruction = str(config.get("toolSelectionInstruction") or "").strip()
    tool_specs = [
        {
            "name": str(tool.get("name") or ""),
            "title": str(tool.get("title") or ""),
            "description": str(tool.get("description") or ""),
            "inputSchema": _compact_value(tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}, string_limit=1800, list_limit=10),
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


def _mcp_tool_selection_user_prompt(state: dict[str, Any], base_args: dict[str, Any]) -> str:
    payload = {
        "state": _compact_state(state),
        "baseArgs": base_args,
        "queryText": _mcp_state_query_text(state),
    }
    return "请根据当前流程 state 和基础参数选择 MCP Tool：\n" + json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _parse_mcp_tool_selection(content: str) -> dict[str, Any]:
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


def _select_default_mcp_tool(tools: list[dict[str, Any]], args: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    available = [tool for tool in tools if str(tool.get("name") or "").strip()]
    if not available:
        raise RuntimeError("MCP Server 未暴露可调用 Tool。")
    if len(available) == 1:
        return available[0]
    by_name = {str(tool.get("name") or "").strip(): tool for tool in available}
    query_text = str(args.get("query") or "").strip() or _mcp_state_query_text(state)
    if query_text and "web_search_exa" in by_name:
        return by_name["web_search_exa"]
    search_tools = [tool for tool in available if "search" in str(tool.get("name") or "").lower()]
    if len(search_tools) == 1:
        return search_tools[0]
    candidates = ", ".join(str(tool.get("name") or "") for tool in available)
    raise RuntimeError(f"MCP Node 未选择 Tool，且无法自动判断。可选工具：{candidates}")


def _ensure_mcp_default_args(args: dict[str, Any], selected_tool: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any]:
    if args or not selected_tool or not _mcp_tool_needs_query(selected_tool):
        return args
    query = _mcp_state_query_text(state)
    return {"query": query} if query else args


def _mcp_tool_needs_query(tool: dict[str, Any]) -> bool:
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    return "query" in properties or "query" in {str(item) for item in required}


def _mcp_state_query_text(state: dict[str, Any]) -> str:
    for key in ("chat", "messages", "message", "input", "query"):
        text = _state_value_to_text(state.get(key)).strip()
        if text:
            return text
    return ""


def _mcp_tool_summary(tool: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(tool.get("name") or ""),
        "title": str(tool.get("title") or ""),
        "description": str(tool.get("description") or ""),
    }


def _enabled_skills_by_id(project: ProjectIR) -> SkillRuntimeConfig:
    result: SkillRuntimeConfig = {}
    for skill in getattr(project, "skills", []) or []:
        if getattr(skill, "enabled", True) is False:
            continue
        skill_id = str(getattr(skill, "id", "")).strip()
        if not skill_id:
            continue
        result[skill_id] = {
            "id": skill_id,
            "name": str(getattr(skill, "name", "") or skill_id),
            "description": str(getattr(skill, "description", "") or ""),
            "sourcePath": str(getattr(skill, "source_path", "") or ""),
            "filePath": str(getattr(skill, "file_path", "") or ""),
            "content": str(getattr(skill, "content", "") or ""),
            "metadataJson": str(getattr(skill, "metadata_json", "") or "{}"),
        }
    return result


def _selected_skill_configs(config: dict[str, Any], skills: SkillRuntimeConfig) -> list[dict[str, Any]]:
    ids = _json_string_list(config.get("skillIdsJson"))
    fallback_id = str(config.get("skillId") or "").strip()
    if fallback_id and fallback_id not in ids:
        ids.append(fallback_id)
    return [skills[skill_id] for skill_id in ids if skill_id in skills]


def _append_selected_skills(system_prompt: str, selected_skills: list[dict[str, Any]]) -> str:
    if not selected_skills:
        return system_prompt
    sections = ["可用 Skills:"]
    for skill in selected_skills:
        name = str(skill.get("name") or skill.get("id") or "Skill").strip()
        content = _skill_runtime_content(skill).strip()
        if content:
            sections.append(f"### {name}\n{content}")
        else:
            sections.append(f"### {name}\n（该 Skill 暂无内容）")
    skill_prompt = "\n\n".join(sections)
    return f"{system_prompt}\n\n{skill_prompt}".strip() if system_prompt else skill_prompt


def _skill_runtime_content(skill: dict[str, Any]) -> str:
    content = str(skill.get("content") or "").strip()
    metadata = _skill_metadata(skill)
    sections: list[str] = []
    if content:
        sections.append(_limit_text(content, SKILL_CORE_RUNTIME_LIMIT, "SKILL.md 内容已截断"))

    package_metadata = metadata.get("packageMetadata") if isinstance(metadata.get("packageMetadata"), dict) else {}
    if package_metadata:
        summary = _skill_package_metadata_summary(package_metadata)
        if summary:
            sections.append(f"#### Package Metadata\n{summary}")

    references = metadata.get("relatedMarkdown")
    if isinstance(references, list) and references:
        reference_text = _skill_references_runtime_text(references)
        if reference_text:
            sections.append(f"#### Related References\n{reference_text}")

    support_files = metadata.get("supportFiles")
    if isinstance(support_files, list) and support_files:
        support_text = _skill_support_files_runtime_text(support_files)
        if support_text:
            sections.append(f"#### Support Files\n{support_text}")

    if metadata.get("relatedMarkdownTruncated"):
        sections.append("注意：部分 reference 文件因数量或长度限制已截断。需要更精确内容时，请使用文件读取工具读取对应路径。")
    return "\n\n".join(sections)


def _skill_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    raw = skill.get("metadataJson")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _skill_package_metadata_summary(metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("version", "organization", "technology", "category", "abstract"):
        value = metadata.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    references = metadata.get("references")
    if isinstance(references, list) and references:
        compact = ", ".join(str(item) for item in references[:8] if str(item).strip())
        if compact:
            lines.append(f"- references: {compact}")
    return _limit_text("\n".join(lines), 4000, "package metadata 已截断")


def _skill_references_runtime_text(references: list[Any]) -> str:
    lines: list[str] = []
    used = 0
    for raw_item in references:
        if not isinstance(raw_item, dict):
            continue
        path = str(raw_item.get("path") or "reference.md")
        title = str(raw_item.get("title") or path)
        content = str(raw_item.get("content") or "").strip()
        if not content:
            continue
        header = f"##### {title} ({path})"
        block = f"{header}\n{content}"
        remaining = SKILL_REFERENCES_RUNTIME_LIMIT - used
        if remaining <= 0:
            break
        block = _limit_text(block, remaining, "reference 内容已截断")
        used += len(block)
        lines.append(block)
    return "\n\n".join(lines)


def _skill_support_files_runtime_text(files: list[Any]) -> str:
    lines: list[str] = []
    used = 0
    for raw_item in files:
        if not isinstance(raw_item, dict):
            continue
        path = str(raw_item.get("path") or "").strip()
        if not path:
            continue
        kind = str(raw_item.get("kind") or "file")
        size = raw_item.get("size", 0)
        preview = str(raw_item.get("preview") or "").strip()
        line = f"- {kind}: {path} ({size} bytes)"
        if preview:
            line = f"{line}\n  preview:\n{_indent_text(_limit_text(preview, 1800, 'preview 已截断'), '  ')}"
        remaining = SKILL_SUPPORT_FILES_RUNTIME_LIMIT - used
        if remaining <= 0:
            break
        line = _limit_text(line, remaining, "support files 清单已截断")
        used += len(line)
        lines.append(line)
    return "\n".join(lines)


def _limit_text(value: str, max_chars: int, note: str) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\n\n[{note}]"


def _indent_text(value: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in value.splitlines())


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.split(",") if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _execute_live_ai_router(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    effective_model_config = _effective_model_config(config, model_config)
    field = str(config.get("routeField", "route_key"))
    fallback = str(config.get("fallback", "other"))
    reason_field = str(config.get("reasonField", "route_reason"))
    keyword_route = _infer_router_key(config, state) or fallback
    if str(config.get("routeMode", "keyword")) != "llm":
        return {field: keyword_route, reason_field: "live-run keyword router"}, f"关键词路由选择 {keyword_route}"

    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    text = render_template(str(config.get("inputText", "{{ state.messages }}")), state)
    prompt = _router_prompt(str(config.get("instruction", "")), text, _parse_router_scenarios(str(config.get("scenarios", ""))), fallback)
    try:
        response = _call_chat_model(provider, model, [("user", prompt)], effective_model_config)
    except Exception as exc:
        return {field: keyword_route, reason_field: f"llm router failed, fallback to keyword: {exc}"}, f"LLM 路由失败，回退到 {keyword_route}"
    route = _normalize_route_key(getattr(response, "content", str(response)), config, fallback)
    return {field: route, reason_field: "live-run llm router"}, f"LLM 路由选择 {route}"


def _execute_live_human_approval(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    action_field = str(config.get("actionField", "approval_action"))
    output_field = str(config.get("outputField", "approval_result"))
    action = str(state.get(action_field) or config.get("previewAction") or config.get("defaultAction", "approved"))
    prompt = render_template(str(config.get("prompt", "")), state)
    result = {
        "action": action,
        "prompt": prompt,
        "status": "live-preview",
    }
    return {action_field: action, output_field: result}, f"使用预览审批动作 {action}，继续流程"


def _execute_live_http(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_response"))
    if _truthy(config.get("mockEnabled")) or str(config.get("mockResponseJson", "")).strip():
        value = _render_mock_response(str(config.get("mockResponseJson", "")), state)
        return {output_field: value}, f"使用 HTTP mock 响应写入 state.{output_field}"

    method = str(config.get("method", "GET")).upper()
    url = render_template(str(config.get("url", "")), state).strip()
    if not url:
        raise RuntimeError("HTTP 节点缺少 URL。")
    headers: dict[str, str] = {}
    auth_secret = str(config.get("authSecret", "")).strip()
    if auth_secret:
        token = os.getenv(auth_secret, "").strip()
        if not token:
            raise RuntimeError(f"HTTP 节点引用的环境变量 {auth_secret} 未设置。")
        headers["Authorization"] = f"Bearer {token}"
    body = str(config.get("body", ""))
    response = httpx.request(
        method,
        url,
        headers=headers,
        content=render_template(body, state) if body else None,
        timeout=_positive_float(config.get("timeoutSeconds", 30), 30),
    )
    response.raise_for_status()
    try:
        value = response.json()
    except ValueError:
        value = response.text
    return {output_field: value}, f"真实 HTTP {method} {url}，写入 state.{output_field}"


def _execute_live_tool(
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    tools: ToolRuntimeConfig,
) -> tuple[dict[str, Any], str]:
    config = node.config
    source = str(config.get("source", "")).strip().lower()
    legacy_single_tool = not _json_string_list(config.get("toolIdsJson")) and not _json_object_list(config.get("toolRegistryJson"))
    if legacy_single_tool and (source == "http" or str(config.get("url", "")).strip() or str(config.get("mockResponseJson", "")).strip()):
        return _execute_live_http(node, state)
    output_field = str(config.get("outputField", f"{node.id}_result"))
    selected_tools = _selected_tool_configs(config, tools)
    if not selected_tools and legacy_single_tool:
        return {
            output_field: {
                "tool": config.get("toolName", node.label),
                "source": source or "declarative",
                "status": "configured",
            }
        }, f"声明式 Tool 已记录到 state.{output_field}"
    if not selected_tools:
        raise RuntimeError("Tools 节点没有选择任何已配置 Tool。")

    effective_model_config = _effective_model_config(config, model_config)
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    max_iterations = min(_positive_int(config.get("maxIterations", 4), 4), 12)
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip()
    user_prompt = render_template(str(config.get("userPrompt") or _agent_state_prompt(state)), state)
    final_answer, calls = _run_tools_agent_session(
        provider,
        model,
        effective_model_config,
        selected_tools,
        system_prompt,
        user_prompt,
        max_iterations,
        runtime_environment,
    )

    return {
        output_field: final_answer,
        f"{output_field}_tool_calls": calls,
    }, f"Tools Agent 注册 {len(selected_tools)} 个 Tool，执行 {len(calls)} 次工具调用，输出到 state.{output_field}"


def _run_tools_agent_session(
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
        ("system", _tools_agent_system_prompt(system_prompt, selected_tools, max_iterations)),
        ("user", user_prompt),
    ]
    calls: list[dict[str, Any]] = []
    final_answer = ""
    latest_task_plan_payload: dict[str, Any] | None = None
    for iteration in range(max_iterations):
        response = _call_chat_model(provider, model, messages, effective_model_config)
        content = getattr(response, "content", str(response))
        decision = _parse_tool_agent_decision(content)
        tool_calls = _normalize_tool_calls(decision.get("tool_calls"))
        if not tool_calls:
            final_answer = _first_config_value(decision.get("final_answer"), content)
            break

        observations: list[dict[str, Any]] = []
        for call_index, tool_call in enumerate(tool_calls, start=1):
            started = time.perf_counter()
            tool_name = str(tool_call.get("tool") or tool_call.get("name") or "").strip()
            args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
            tool_config = _find_selected_tool(selected_tools, tool_name)
            trace_meta = _registered_tool_trace_metadata(tool_config) if tool_config else {"toolName": tool_name}
            if not tool_config:
                observation = {"ok": False, "error": f"未知 Tool：{tool_name}", "errorType": "tool_args"}
            else:
                observation = _invoke_registered_tool(tool_config, args, runtime_environment, effective_model_config, agent_context)
            task_plan_payload = _task_plan_payload_from_observation(tool_name, observation)
            if task_plan_payload:
                latest_task_plan_payload = task_plan_payload
            recommended_next_tools = _recommended_next_tools(tool_name, args, observation)
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
        final_answer = _finalize_tools_agent_answer(provider, model, messages, effective_model_config, max_iterations)
    if latest_task_plan_payload and not _normalize_worker_tasks(final_answer, max_tasks=10, fallback_goal=""):
        final_answer = json.dumps(latest_task_plan_payload, ensure_ascii=False)
    return final_answer, calls


def _task_plan_payload_from_observation(tool_name: str, observation: Any) -> dict[str, Any] | None:
    if str(tool_name or "").strip() != "task_plan" or not isinstance(observation, dict) or not observation.get("ok"):
        return None
    result = observation.get("result")
    if not isinstance(result, dict):
        return None
    tasks = _normalize_worker_tasks(result, max_tasks=10, fallback_goal="")
    if not tasks:
        return None
    return {"tasks": tasks}


def _execute_live_task_splitter(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    input_field = str(config.get("inputField", "task_plan")).strip() or "task_plan"
    output_field = str(config.get("outputField", "worker_tasks")).strip() or "worker_tasks"
    max_tasks = min(_positive_int(config.get("maxTasks"), 5), 10)
    fallback_enabled = _truthy(config.get("fallbackToSingleTask", True))
    value = state.get(input_field)
    tasks = _normalize_worker_tasks(value, max_tasks=max_tasks, fallback_goal="")
    if not tasks and fallback_enabled:
        fallback_goal = _state_value_to_text(state.get("messages")).strip() or _state_value_to_text(value).strip() or "阅读代码并回答用户问题"
        tasks = _normalize_worker_tasks([{"goal": fallback_goal}], max_tasks=1, fallback_goal=fallback_goal)
    if not tasks:
        raise RuntimeError(f"Task Splitter 无法从 state.{input_field} 解析出 tasks。")
    return {output_field: tasks}, f"解析并标准化 {len(tasks)} 个 Worker 任务，输出到 state.{output_field}"


def _execute_variable_assign(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    assignments = _json_object_list(config.get("assignmentsJson"))
    if not assignments:
        assignments = [
            {
                "target": str(config.get("targetField") or "assigned_value"),
                "operation": "overwrite",
                "sourceType": "template",
                "source": str(config.get("value") or "{{ state.messages }}"),
                "valueType": "auto",
            }
        ]
    input_values = _resolve_input_mappings(config, state)
    delta: dict[str, Any] = {}
    operations: list[dict[str, Any]] = []
    working = {**state}
    for raw in assignments:
        if not isinstance(raw, dict):
            continue
        target = str(raw.get("target") or raw.get("field") or raw.get("name") or "").strip()
        if not target:
            continue
        operation = str(raw.get("operation") or "overwrite").strip().lower()
        source_type = str(raw.get("sourceType") or raw.get("source_type") or "template").strip().lower()
        source = str(raw.get("source") if raw.get("source") is not None else raw.get("value") if raw.get("value") is not None else "")
        value_type = str(raw.get("valueType") or raw.get("value_type") or "auto")
        transform = str(raw.get("transform") or "none").strip().lower()
        transform_args = _render_transform_args(raw.get("transformArgsJson") or raw.get("transform_args_json"), {**working, **delta})
        if source_type == "input":
            value = input_values.get(source)
            value = _apply_mapping_transform(value, transform, transform_args, {**working, **delta})
            value = _coerce_mapped_value(value, value_type)
        else:
            value = _resolve_mapping_value(source_type, source, value_type, {**working, **delta}, transform, transform_args)
        previous = _get_path({**working, **delta}, target)
        if operation == "clear":
            next_value = None
        elif operation == "append":
            current = previous if isinstance(previous, list) else ([] if previous in (None, "") else [previous])
            next_value = [*current, *(value if isinstance(value, list) else [value])]
        elif operation == "merge":
            base = previous if isinstance(previous, dict) else {}
            if not isinstance(value, dict):
                raise RuntimeError(f"Variable Assign merge 需要 object 值：{target}")
            next_value = {**base, **value}
        else:
            operation = "overwrite"
            next_value = value
        _set_path(delta, target, next_value, {**working, **delta})
        operations.append({"target": target, "operation": operation, "previous": _compact_value(previous), "value": _compact_value(next_value)})
    result_field = str(config.get("resultField", "assignment_result")).strip() or "assignment_result"
    if result_field:
        delta[result_field] = {
            "ok": True,
            "changedFields": [item["target"] for item in operations],
            "operations": operations,
        }
    return delta, f"Variable Assign 写入 {len(operations)} 个字段"


def _execute_template_node(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", "template_result")).strip() or "template_result"
    output_type = str(config.get("outputType", "text")).strip().lower()
    inputs = _resolve_input_mappings(config, state)
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


def _execute_live_json_extractor(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", "extracted_json")).strip() or "extracted_json"
    validation_field = str(config.get("validationField", "validation_result")).strip() or "validation_result"
    repair_field = str(config.get("repairResultField", "repair_result")).strip() or "repair_result"
    schema = _json_schema_from_config(config)
    inputs = _resolve_input_mappings(config, state)
    input_text = str(config.get("inputText") or "").strip()
    if input_text:
        source_text = render_template(input_text, {**state, **inputs})
    else:
        source_text = _state_value_to_text(inputs.get("input") if "input" in inputs else state.get("messages", ""))
    effective_model_config = _effective_model_config(config, model_config)
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    response = _call_chat_model(
        provider,
        model,
        [
            ("system", _json_extractor_system_prompt(config, schema)),
            ("user", "请从以下输入中抽取结构化 JSON：\n" + source_text),
        ],
        effective_model_config,
    )
    raw_content = getattr(response, "content", str(response))
    parse_error = ""
    try:
        output = _parse_json_object_from_text(raw_content)
    except RuntimeError as exc:
        output = {}
        parse_error = str(exc)
    validation = _validation_result(output, schema)
    repair_result: dict[str, Any] | None = None
    if parse_error:
        validation["errors"].insert(0, parse_error)
        validation["valid"] = False
    if not validation["valid"] and _truthy(config.get("repairEnabled")):
        repair_result = _repair_json_output(
            config,
            output,
            schema,
            validation["errors"],
            source_text,
            provider,
            model,
            effective_model_config,
            raw_content=raw_content,
        )
        if repair_result.get("ok") and isinstance(repair_result.get("output"), dict):
            output = repair_result["output"]
            validation = repair_result["validation"]
    delta = {
        output_field: output,
        validation_field: validation,
    }
    if repair_result is not None:
        delta[repair_field] = repair_result
    repair_detail = "，已尝试修复" if repair_result is not None else ""
    return delta, f"JSON Extractor 抽取到 state.{output_field}，校验 {'通过' if validation['valid'] else '未通过'}{repair_detail}"


def _execute_json_validator(node: NodeIR, state: dict[str, Any], model_config: ModelRuntimeConfig = None, allow_repair: bool = False) -> tuple[dict[str, Any], str]:
    config = node.config
    input_field = str(config.get("inputField", "extracted_json")).strip() or "extracted_json"
    output_field = str(config.get("outputField", "validated_json")).strip() or "validated_json"
    validation_field = str(config.get("validationField", "validation_result")).strip() or "validation_result"
    repair_field = str(config.get("repairResultField", "repair_result")).strip() or "repair_result"
    schema = _json_schema_from_config(config)
    value = _get_path(state, input_field)
    validation = _validation_result(value, schema)
    repair_result: dict[str, Any] | None = None
    if allow_repair and not validation["valid"] and _truthy(config.get("repairEnabled")):
        effective_model_config = _effective_model_config(config, model_config)
        provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
        repair_result = _repair_json_output(
            config,
            value,
            schema,
            validation["errors"],
            _state_value_to_text(state.get("messages", "")),
            provider,
            model,
            effective_model_config,
        )
        if repair_result.get("ok") and isinstance(repair_result.get("output"), dict):
            value = repair_result["output"]
            validation = repair_result["validation"]
    delta = {
        output_field: value,
        validation_field: validation,
    }
    if repair_result is not None:
        delta[repair_field] = repair_result
    repair_detail = "，已尝试修复" if repair_result is not None else ""
    return delta, f"JSON Validator 校验 state.{input_field}，结果 {'valid' if validation['valid'] else 'invalid'}{repair_detail}"


def _execute_for_each_node(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    config = node.config
    nodes = {item.id: item for item in project.nodes}
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    item_start = _target_for_handle([edge for edge in outgoing.get(node.id, []) if edge.kind != EdgeKind.ERROR], "item")
    if not item_start:
        raise RuntimeError("ForEach 未连接 item 循环体。")
    merge_node = _find_for_each_merge_node(item_start, nodes, outgoing)
    if merge_node is None:
        raise RuntimeError("ForEach 循环体必须连接到 Merge 节点。")

    items_field = str(config.get("itemsField", "worker_tasks")).strip() or "worker_tasks"
    item_field = str(config.get("itemField", "current_item")).strip() or "current_item"
    index_field = str(config.get("indexField", "current_index")).strip() or "current_index"
    max_items = min(_positive_int(config.get("maxItems"), 50), 100)
    items_value = _get_path(state, items_field)
    if isinstance(items_value, dict) and isinstance(items_value.get("tasks"), list):
        items = items_value.get("tasks") or []
    elif isinstance(items_value, list):
        items = items_value
    else:
        raise RuntimeError(f"ForEach 需要 state.{items_field} 是 array。")
    items = list(items)[:max_items]
    item_states: list[dict[str, Any]] = []
    iterations: list[dict[str, Any]] = []
    execution_mode = str(config.get("executionMode") or "sequential").strip().lower()
    item_failure_policy = str(config.get("itemFailurePolicy") or "fail_fast").strip().lower()
    preserve_order = _bool_config(config.get("preserveOrder"), True)
    parallel = mode == "live" and execution_mode == "parallel" and len(items) > 1
    if parallel:
        max_concurrency = min(_positive_int(config.get("maxConcurrency"), 3), 12)
        futures = {}
        with ThreadPoolExecutor(max_workers=min(max_concurrency, len(items))) as executor:
            for index, item in enumerate(items):
                futures[
                    executor.submit(
                        _run_for_each_item_job,
                        index,
                        item,
                        state,
                        item_field,
                        index_field,
                        item_start,
                        merge_node.id,
                        project,
                        nodes,
                        outgoing,
                        mode,
                        model_config,
                        runtime_environment,
                        skills,
                        tools,
                        mcp_servers,
                        agents,
                        agent_depth,
                    )
                ] = (index, item)
            results: list[dict[str, Any]] = []
            for future in as_completed(futures):
                index, item = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    if item_failure_policy != "collect_errors":
                        raise
                    item_state = dict(state)
                    item_state[item_field] = item
                    item_state[index_field] = index
                    error_payload = _runtime_error_payload(node, exc)
                    item_state["last_error"] = error_payload
                    item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                    results.append({"index": index, "item": item, "itemState": item_state, "reachedMerge": True, "error": error_payload})
        if preserve_order:
            results.sort(key=lambda item: int(item["index"]))
        for result in results:
            if not result.get("reachedMerge"):
                raise RuntimeError(f"ForEach 第 {int(result['index']) + 1} 项没有到达 Merge 节点。")
            item_state = result["itemState"]
            item_states.append(item_state)
            iteration = {"index": result["index"], "item": _compact_value(result["item"]), "output": _compact_state(item_state)}
            if result.get("error"):
                iteration["error"] = _compact_value(result["error"])
            iterations.append(iteration)
    else:
        for index, item in enumerate(items):
            item_state = dict(state)
            item_state[item_field] = item
            item_state[index_field] = index
            try:
                reached_merge = _run_for_each_item_chain(
                    item_start,
                    merge_node.id,
                    item_state,
                    project,
                    nodes,
                    outgoing,
                    mode,
                    model_config,
                    runtime_environment,
                    skills,
                    tools,
                    mcp_servers,
                    agents,
                    agent_depth,
                )
            except Exception as exc:
                if item_failure_policy != "collect_errors":
                    raise
                error_payload = _runtime_error_payload(node, exc)
                item_state["last_error"] = error_payload
                item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                reached_merge = True
            if not reached_merge:
                raise RuntimeError(f"ForEach 第 {index + 1} 项没有到达 Merge 节点。")
            item_states.append(item_state)
            iterations.append({"index": index, "item": _compact_value(item), "output": _compact_state(item_state)})

    delta, detail = _execute_merge_node(merge_node, state, item_states)
    merge_result_field = str(merge_node.config.get("resultField", "merge_result")).strip() or "merge_result"
    if isinstance(delta.get(merge_result_field), dict):
        delta[merge_result_field]["iterations"] = iterations
    result_field = str(config.get("resultField") or "").strip()
    if result_field:
        delta[result_field] = {
            "ok": True,
            "itemsField": items_field,
            "count": len(items),
            "mergeNodeId": merge_node.id,
            "iterations": iterations,
            "parallel": parallel,
            "itemFailurePolicy": item_failure_policy,
        }
    mode_label = "并发" if parallel else "顺序"
    return delta, f"ForEach {mode_label}处理 {len(items)} 项；{detail}"


def _execute_for_each_node_events(
    project: ProjectIR,
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
):
    config = node.config
    nodes = {item.id: item for item in project.nodes}
    outgoing: dict[str, list] = {}
    for edge in project.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    item_start = _target_for_handle([edge for edge in outgoing.get(node.id, []) if edge.kind != EdgeKind.ERROR], "item")
    if not item_start:
        raise RuntimeError("ForEach 未连接 item 循环体。")
    merge_node = _find_for_each_merge_node(item_start, nodes, outgoing)
    if merge_node is None:
        raise RuntimeError("ForEach 循环体必须连接到 Merge 节点。")

    items_field = str(config.get("itemsField", "worker_tasks")).strip() or "worker_tasks"
    item_field = str(config.get("itemField", "current_item")).strip() or "current_item"
    index_field = str(config.get("indexField", "current_index")).strip() or "current_index"
    max_items = min(_positive_int(config.get("maxItems"), 50), 100)
    items_value = _get_path(state, items_field)
    if isinstance(items_value, dict) and isinstance(items_value.get("tasks"), list):
        items = items_value.get("tasks") or []
    elif isinstance(items_value, list):
        items = items_value
    else:
        raise RuntimeError(f"ForEach 需要 state.{items_field} 是 array。")
    items = list(items)[:max_items]
    item_states: list[dict[str, Any]] = []
    iterations: list[dict[str, Any]] = []
    child_trace_items: list[dict[str, Any]] = []
    execution_mode = str(config.get("executionMode") or "sequential").strip().lower()
    item_failure_policy = str(config.get("itemFailurePolicy") or "fail_fast").strip().lower()
    preserve_order = _bool_config(config.get("preserveOrder"), True)
    parallel = execution_mode == "parallel" and len(items) > 1
    if parallel:
        max_concurrency = min(_positive_int(config.get("maxConcurrency"), 3), 12)
        futures = {}
        event_queue: Queue[dict[str, Any]] = Queue()
        with ThreadPoolExecutor(max_workers=min(max_concurrency, len(items))) as executor:
            for index, item in enumerate(items):
                futures[
                    executor.submit(
                        _collect_for_each_item_events,
                        item_start,
                        merge_node.id,
                        dict(state),
                        item_field,
                        index_field,
                        item,
                        index,
                        project,
                        nodes,
                        outgoing,
                        model_config,
                        runtime_environment,
                        skills,
                        tools,
                        mcp_servers,
                        agents,
                        agent_depth,
                        node,
                        event_queue,
                    )
                ] = (index, item)
            results: list[dict[str, Any]] = []
            pending = set(futures)
            while pending:
                try:
                    yield event_queue.get(timeout=0.05)
                except Empty:
                    pass
                for future in [item for item in pending if item.done()]:
                    pending.remove(future)
                    index, item = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        if item_failure_policy != "collect_errors":
                            raise
                        item_state = dict(state)
                        item_state[item_field] = item
                        item_state[index_field] = index
                        error_payload = _runtime_error_payload(node, exc)
                        item_state["last_error"] = error_payload
                        item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                        result = {"index": index, "item": item, "itemState": item_state, "reachedMerge": True, "events": [], "childTrace": [], "error": error_payload}
                    results.append(result)
                    child_trace_items.extend(result.get("childTrace", []))
            while True:
                try:
                    yield event_queue.get_nowait()
                except Empty:
                    break
        if preserve_order:
            results.sort(key=lambda item: int(item["index"]))
        for result in results:
            if not result.get("reachedMerge"):
                raise RuntimeError(f"ForEach 第 {int(result['index']) + 1} 项没有到达 Merge 节点。")
            item_state = result["itemState"]
            item_states.append(item_state)
            iteration = {"index": result["index"], "item": _compact_value(result["item"]), "output": _compact_state(item_state)}
            if result.get("error"):
                iteration["error"] = _compact_value(result["error"])
            iterations.append(iteration)
    else:
        for index, item in enumerate(items):
            item_state = dict(state)
            item_state[item_field] = item
            item_state[index_field] = index
            try:
                reached_merge = yield from _run_for_each_item_chain_events(
                    item_start,
                    merge_node.id,
                    item_state,
                    project,
                    nodes,
                    outgoing,
                    model_config,
                    runtime_environment,
                    skills,
                    tools,
                    mcp_servers,
                    agents,
                    agent_depth,
                    node,
                    index,
                    item,
                    child_trace_items,
                )
            except Exception as exc:
                if item_failure_policy != "collect_errors":
                    raise
                error_payload = _runtime_error_payload(node, exc)
                item_state["last_error"] = error_payload
                item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                reached_merge = True
            if not reached_merge:
                raise RuntimeError(f"ForEach 第 {index + 1} 项没有到达 Merge 节点。")
            item_states.append(item_state)
            iterations.append({"index": index, "item": _compact_value(item), "output": _compact_state(item_state)})

    delta, detail = _execute_merge_node(merge_node, state, item_states)
    merge_result_field = str(merge_node.config.get("resultField", "merge_result")).strip() or "merge_result"
    if isinstance(delta.get(merge_result_field), dict):
        delta[merge_result_field]["iterations"] = iterations
    result_field = str(config.get("resultField") or "").strip()
    if result_field:
        delta[result_field] = {
            "ok": True,
            "itemsField": items_field,
            "count": len(items),
            "mergeNodeId": merge_node.id,
            "iterations": iterations,
            "parallel": parallel,
            "itemFailurePolicy": item_failure_policy,
        }
    mode_label = "并发" if parallel else "顺序"
    return delta, f"ForEach {mode_label}处理 {len(items)} 项；{detail}", child_trace_items


def _run_for_each_item_job(
    index: int,
    item: Any,
    base_state: dict[str, Any],
    item_field: str,
    index_field: str,
    item_start: str,
    merge_node_id: str,
    project: ProjectIR,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> dict[str, Any]:
    item_state = dict(base_state)
    item_state[item_field] = item
    item_state[index_field] = index
    reached_merge = _run_for_each_item_chain(
        item_start,
        merge_node_id,
        item_state,
        project,
        nodes,
        outgoing,
        mode,
        model_config,
        runtime_environment,
        skills,
        tools,
        mcp_servers,
        agents,
        agent_depth,
    )
    return {"index": index, "item": item, "itemState": item_state, "reachedMerge": reached_merge}


def _collect_for_each_item_events(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    item_field: str,
    index_field: str,
    item: Any,
    index: int,
    project: ProjectIR,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
    parent_node: NodeIR,
    event_queue: Queue[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item_state[item_field] = item
    item_state[index_field] = index
    child_trace: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    generator = _run_for_each_item_chain_events(
        start_node_id,
        merge_node_id,
        item_state,
        project,
        nodes,
        outgoing,
        model_config,
        runtime_environment,
        skills,
        tools,
        mcp_servers,
        agents,
        agent_depth,
        parent_node,
        index,
        item,
        child_trace,
    )
    reached_merge = False
    while True:
        try:
            event = next(generator)
            events.append(event)
            if event_queue is not None:
                event_queue.put(event)
        except StopIteration as stop:
            reached_merge = bool(stop.value)
            break
    return {"index": index, "item": item, "itemState": item_state, "reachedMerge": reached_merge, "events": events, "childTrace": child_trace}


def _run_for_each_item_chain(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    project: ProjectIR,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    mode: RunMode,
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
) -> bool:
    current = start_node_id
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        if current == merge_node_id:
            return True
        visited += 1
        child = nodes[current]
        if child.type in {NodeType.FOR_EACH, NodeType.MERGE}:
            raise RuntimeError(f"ForEach v1 不支持嵌套或提前执行 {child.type} 节点。")
        try:
            delta, _detail, _trace_meta = _execute_node_with_policy(child, project, item_state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            item_state.update(delta)
        except Exception as exc:
            error_target = _error_execution_target(child, outgoing)
            if not error_target:
                raise
            item_state["last_error"] = _runtime_error_payload(child, exc)
            current = error_target
            continue
        if child.type == NodeType.DIRECT_REPLY:
            return False
        current = _next_execution_target(child, nodes, outgoing, item_state)
    if visited >= MAX_STEPS:
        raise RuntimeError(f"ForEach 子链路超过 {MAX_STEPS} 步，可能存在循环。")
    return False


def _run_for_each_item_chain_events(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    project: ProjectIR,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    skills: SkillRuntimeConfig,
    tools: ToolRuntimeConfig,
    mcp_servers: McpRuntimeConfig,
    agents: AgentRuntimeConfig,
    agent_depth: int,
    parent_node: NodeIR,
    iteration_index: int,
    iteration_item: Any,
    child_trace_items: list[dict[str, Any]],
) -> bool:
    current = start_node_id
    visited = 0
    while current and current in nodes and visited < MAX_STEPS:
        if current == merge_node_id:
            return True
        visited += 1
        child = nodes[current]
        if child.type in {NodeType.FOR_EACH, NodeType.MERGE}:
            raise RuntimeError(f"ForEach v1 不支持嵌套或提前执行 {child.type} 节点。")
        before = dict(item_state)
        event_meta = {
            "parentNodeId": parent_node.id,
            "iterationIndex": iteration_index,
            "iterationItem": _compact_value(iteration_item),
            "sourceNodeId": child.id,
        }
        yield {
            "event": "node_start",
            "nodeId": child.id,
            "type": str(child.type),
            "label": child.label,
            "inputState": _compact_state(before),
            **event_meta,
        }
        started = time.perf_counter()
        handled_error_target: str | None = None
        trace_meta: dict[str, Any] = {}
        try:
            delta, detail, trace_meta = _execute_node_with_policy(child, project, item_state, "live", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            item_state.update(delta)
            status = "ok"
        except Exception as exc:
            handled_error_target = _error_execution_target(child, outgoing)
            trace_meta = _trace_meta_from_exception(exc)
            delta = {"last_error": _runtime_error_payload(child, exc)}
            item_state.update(delta)
            detail = f"{_format_error(exc)}；已转入 error 分支。" if handled_error_target else _format_error(exc)
            status = "error"
        trace_item = {
            "nodeId": child.id,
            "type": str(child.type),
            "label": child.label,
            "status": status,
            "detail": detail,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            "inputState": _compact_state(before),
            "outputDelta": _compact_state(delta),
            **trace_meta,
            **event_meta,
        }
        child_trace_items.append(trace_item)
        yield {
            "event": "node_end",
            "traceItem": trace_item,
            "outputState": _compact_state(item_state),
        }
        if status == "error" and not handled_error_target:
            raise RuntimeError(detail)
        if child.type == NodeType.DIRECT_REPLY:
            return False
        current = handled_error_target or _next_execution_target(child, nodes, outgoing, item_state)
    if visited >= MAX_STEPS:
        raise RuntimeError(f"ForEach 子链路超过 {MAX_STEPS} 步，可能存在循环。")
    return False


def _execute_merge_node(node: NodeIR, state: dict[str, Any], item_states: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    config = node.config
    merge_mode = str(config.get("mergeMode") or "auto").strip().lower() or "auto"
    reducers = _json_object_list(config.get("reducersJson"))
    if not reducers:
        reducers = [{"target": "merged_results", "source": "item_result", "reducer": "append"}]
    delta: dict[str, Any] = {}
    summaries: list[dict[str, Any]] = []
    for reducer in reducers:
        target = str(reducer.get("target") or reducer.get("field") or reducer.get("name") or "").strip()
        source = str(reducer.get("source") or reducer.get("sourceField") or "").strip()
        operation = str(reducer.get("reducer") or reducer.get("operation") or "append").strip().lower()
        if not target or not source:
            continue
        values = [_get_path(item_state, source) for item_state in item_states]
        previous = _get_path({**state, **delta}, target)
        next_value = _reduce_values(operation, values, previous, target)
        _set_path(delta, target, next_value, {**state, **delta})
        summaries.append(
            {
                "target": target,
                "source": source,
                "reducer": operation,
                "count": len(values),
                "value": _compact_value(next_value),
            }
        )
    result_field = str(config.get("resultField", "merge_result")).strip() or "merge_result"
    if result_field:
        delta[result_field] = {
            "ok": True,
            "mergeMode": merge_mode,
            "itemCount": len(item_states),
            "reducers": summaries,
        }
    mode_label = "Branch Merge" if merge_mode == "branch" else "Merge"
    return delta, f"{mode_label} 聚合 {len(item_states)} 项，写入 {len(summaries)} 个字段"


def _reduce_values(operation: str, values: list[Any], previous: Any, target: str) -> Any:
    if operation == "concat":
        result: list[Any] = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return result
    if operation == "merge":
        result = dict(previous) if isinstance(previous, dict) else {}
        for value in values:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise RuntimeError(f"Merge reducer merge 需要 object 值：{target}")
            result.update(value)
        return result
    if operation == "overwrite" or operation == "last":
        return values[-1] if values else previous
    if operation == "first":
        for value in values:
            if value is not None:
                return value
        return previous
    if operation != "append":
        operation = "append"
    return list(values)


def _execute_error_handler(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    error_field = str(config.get("errorField", "last_error")).strip() or "last_error"
    output_field = str(config.get("outputField", "error_result")).strip() or "error_result"
    error_value = _get_path(state, error_field, {})
    render_state = {**state, "error": error_value}
    template = str(config.get("template") or "流程执行失败：{{ state.last_error }}")
    message = render_template(template, render_state)
    return {
        output_field: {
            "ok": False,
            "error": error_value,
            "message": message,
        }
    }, f"Error Handler 读取 state.{error_field}，输出到 state.{output_field}"


def _execute_live_parallel_tools(
    project: ProjectIR,
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    tools: ToolRuntimeConfig,
) -> tuple[dict[str, Any], str]:
    delta, detail, _events = _run_parallel_tools_node(project, node, state, model_config, runtime_environment, tools, emit_worker_events=False)
    return delta, detail


def _execute_live_parallel_tools_events(
    project: ProjectIR,
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    tools: ToolRuntimeConfig,
):
    config = node.config
    tasks_field = str(config.get("tasksField", "worker_tasks")).strip() or "worker_tasks"
    output_field = str(config.get("outputField", "worker_results")).strip() or "worker_results"
    tasks = _normalize_worker_tasks(state.get(tasks_field), max_tasks=10, fallback_goal=_state_value_to_text(state.get("messages")))
    if not tasks:
        raise RuntimeError(f"Parallel Tools 未能从 state.{tasks_field} 获取任务列表。")
    selected_tools = _selected_tool_configs(config, tools)
    if not selected_tools:
        raise RuntimeError("Parallel Tools 节点没有选择任何已配置 Tool。")

    effective_model_config = _effective_model_config(config, model_config)
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    max_iterations = min(_positive_int(config.get("maxIterationsPerTask"), 6), 12)
    max_workers = min(_positive_int(config.get("maxConcurrentWorkers"), 3), 6, len(tasks))
    store_tool_calls = _truthy(config.get("storeToolCalls", False))
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip() or "你是代码阅读 Worker，只完成分配给你的子任务。"
    worker_nodes = _parallel_worker_nodes(project, node.id)
    slots = _parallel_worker_task_slots(worker_nodes, tasks, max_workers)

    def run_slot(slot: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        slot_results: list[dict[str, Any]] = []
        try:
            for task_item in slot["tasks"]:
                result = _run_parallel_worker_task(
                    task_item["task"],
                    int(task_item["taskIndex"]),
                    state,
                    provider,
                    model,
                    effective_model_config,
                    selected_tools,
                    system_prompt,
                    max_iterations,
                    runtime_environment,
                    store_tool_calls,
                )
                result["workerNodeId"] = slot.get("nodeId") or ""
                result["workerIndex"] = int(slot.get("workerIndex") or 0)
                slot_results.append(result)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "nodeId": slot.get("nodeId"),
                "label": slot.get("label"),
                "workerIndex": slot.get("workerIndex"),
                "status": "error" if slot_results and all(item.get("status") == "error" for item in slot_results) else "ok",
                "durationMs": duration_ms,
                "results": slot_results,
            }
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "nodeId": slot.get("nodeId"),
                "label": slot.get("label"),
                "workerIndex": slot.get("workerIndex"),
                "status": "error",
                "durationMs": duration_ms,
                "results": [
                    {
                        "taskId": str((slot.get("tasks") or [{}])[0].get("task", {}).get("id") or f"worker_{slot.get('workerIndex') or 1}"),
                        "title": str(slot.get("label") or "Worker")[:120],
                        "status": "error",
                        "durationMs": duration_ms,
                        "summary": "",
                        "evidence": [],
                        "warnings": [],
                        "error": _format_error(exc),
                    }
                ],
            }

    for slot in slots:
        if slot.get("nodeId"):
            yield {
                "event": "node_start",
                "nodeId": slot["nodeId"],
                "type": "parallel_worker",
                "label": slot["label"],
                "inputState": {"tasks": [item["task"] for item in slot["tasks"]]},
            }

    ordered: list[dict[str, Any] | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=max(1, min(len(slots), max_workers))) as executor:
        future_to_slot = {executor.submit(run_slot, slot): slot for slot in slots}
        for future in as_completed(future_to_slot):
            slot = future_to_slot[future]
            slot_result = future.result()
            for result in slot_result.get("results") or []:
                task_index = int(result.get("taskIndex", -1))
                if 0 <= task_index < len(ordered):
                    ordered[task_index] = result
            if slot.get("nodeId"):
                yield _parallel_worker_end_event(slot, slot_result, state)

    results = [item for item in ordered if isinstance(item, dict)]
    if results and all(item.get("status") == "error" for item in results):
        raise RuntimeError("Parallel Tools 所有 Worker 均执行失败。")
    return {output_field: results}, f"Parallel Tools 并行执行 {len(slots)} 个 Worker 槽位，完成 {len(results)} 个任务，输出到 state.{output_field}"


def _run_parallel_tools_node(
    project: ProjectIR,
    node: NodeIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    tools: ToolRuntimeConfig,
    emit_worker_events: bool,
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    config = node.config
    tasks_field = str(config.get("tasksField", "worker_tasks")).strip() or "worker_tasks"
    output_field = str(config.get("outputField", "worker_results")).strip() or "worker_results"
    tasks = _normalize_worker_tasks(state.get(tasks_field), max_tasks=10, fallback_goal=_state_value_to_text(state.get("messages")))
    if not tasks:
        raise RuntimeError(f"Parallel Tools 未能从 state.{tasks_field} 获取任务列表。")
    selected_tools = _selected_tool_configs(config, tools)
    if not selected_tools:
        raise RuntimeError("Parallel Tools 节点没有选择任何已配置 Tool。")

    effective_model_config = _effective_model_config(config, model_config)
    provider, model = _resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    max_iterations = min(_positive_int(config.get("maxIterationsPerTask"), 6), 12)
    max_workers = min(_positive_int(config.get("maxConcurrentWorkers"), 3), 6, len(tasks))
    store_tool_calls = _truthy(config.get("storeToolCalls", False))
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip() or "你是代码阅读 Worker，只完成分配给你的子任务。"
    events: list[dict[str, Any]] = []
    worker_nodes = _parallel_worker_nodes(project, node.id)
    slots = _parallel_worker_task_slots(worker_nodes, tasks, max_workers)

    def run_slot(slot: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        slot_results: list[dict[str, Any]] = []
        try:
            for task_item in slot["tasks"]:
                result = _run_parallel_worker_task(
                    task_item["task"],
                    int(task_item["taskIndex"]),
                    state,
                    provider,
                    model,
                    effective_model_config,
                    selected_tools,
                    system_prompt,
                    max_iterations,
                    runtime_environment,
                    store_tool_calls,
                )
                result["workerNodeId"] = slot.get("nodeId") or ""
                result["workerIndex"] = int(slot.get("workerIndex") or 0)
                slot_results.append(result)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "nodeId": slot.get("nodeId"),
                "label": slot.get("label"),
                "workerIndex": slot.get("workerIndex"),
                "status": "error" if slot_results and all(item.get("status") == "error" for item in slot_results) else "ok",
                "durationMs": duration_ms,
                "results": slot_results,
            }
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "nodeId": slot.get("nodeId"),
                "label": slot.get("label"),
                "workerIndex": slot.get("workerIndex"),
                "status": "error",
                "durationMs": duration_ms,
                "results": [
                    {
                        "taskId": str((slot.get("tasks") or [{}])[0].get("task", {}).get("id") or f"worker_{slot.get('workerIndex') or 1}"),
                        "title": str(slot.get("label") or "Worker")[:120],
                        "status": "error",
                        "durationMs": duration_ms,
                        "summary": "",
                        "evidence": [],
                        "warnings": [],
                        "error": _format_error(exc),
                    }
                ],
            }

    for slot in slots:
        if emit_worker_events and slot.get("nodeId"):
            events.append(
                {
                    "event": "node_start",
                    "nodeId": slot["nodeId"],
                    "type": "parallel_worker",
                    "label": slot["label"],
                    "inputState": {"tasks": [item["task"] for item in slot["tasks"]]},
                }
            )

    ordered: list[dict[str, Any] | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=max(1, min(len(slots), max_workers))) as executor:
        future_to_slot = {executor.submit(run_slot, slot): slot for slot in slots}
        for future in as_completed(future_to_slot):
            slot = future_to_slot[future]
            slot_result = future.result()
            for result in slot_result.get("results") or []:
                task_index = int(result.get("taskIndex", -1))
                if 0 <= task_index < len(ordered):
                    ordered[task_index] = result
            if emit_worker_events and slot.get("nodeId"):
                events.append(_parallel_worker_end_event(slot, slot_result, state))

    results = [item for item in ordered if isinstance(item, dict)]
    if results and all(item.get("status") == "error" for item in results):
        raise RuntimeError("Parallel Tools 所有 Worker 均执行失败。")
    return {output_field: results}, f"Parallel Tools 并行执行 {len(slots)} 个 Worker 槽位，完成 {len(results)} 个任务，输出到 state.{output_field}", events


def _parallel_worker_nodes(project: ProjectIR, parent_node_id: str) -> list[NodeIR]:
    return sorted(
        [
            node
            for node in project.nodes
            if node.type == NodeType.PARALLEL_WORKER and str(node.config.get("parentNodeId") or "") == parent_node_id
        ],
        key=lambda item: (int(item.config.get("workerIndex") or 0), item.id),
    )


def _parallel_worker_task_slots(worker_nodes: list[NodeIR], tasks: list[dict[str, Any]], fallback_worker_count: int) -> list[dict[str, Any]]:
    count = max(1, min(len(worker_nodes) or fallback_worker_count or 1, 6, len(tasks)))
    slots: list[dict[str, Any]] = []
    for index in range(count):
        node = worker_nodes[index] if index < len(worker_nodes) else None
        slots.append(
            {
                "nodeId": node.id if node else "",
                "label": node.label if node else f"Worker {index + 1}",
                "workerIndex": int(node.config.get("workerIndex") or index + 1) if node else index + 1,
                "tasks": [],
            }
        )
    for task_index, task in enumerate(tasks):
        slots[task_index % count]["tasks"].append({"taskIndex": task_index, "task": task})
    return [slot for slot in slots if slot["tasks"]]


def _run_parallel_worker_task(
    task: dict[str, Any],
    task_index: int,
    state: dict[str, Any],
    provider: str,
    model: str,
    effective_model_config: ModelRuntimeConfig,
    selected_tools: list[dict[str, Any]],
    system_prompt: str,
    max_iterations: int,
    runtime_environment: RuntimeEnvironment,
    store_tool_calls: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        final_answer, calls = _run_tools_agent_session(
            provider,
            model,
            effective_model_config,
            selected_tools,
            _parallel_worker_system_prompt(system_prompt),
            _parallel_worker_user_prompt(state, task),
            max_iterations,
            runtime_environment,
        )
        result = _normalize_worker_final_answer(task, final_answer)
        result["durationMs"] = round((time.perf_counter() - started) * 1000, 2)
        result["taskIndex"] = task_index
        if store_tool_calls:
            result["toolCalls"] = _compact_value(calls, string_limit=3000, list_limit=12)
        return result
    except Exception as exc:
        return {
            "taskId": str(task.get("id") or f"task_{task_index + 1}"),
            "taskIndex": task_index,
            "title": str(task.get("title") or task.get("goal") or f"任务 {task_index + 1}")[:120],
            "status": "error",
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            "summary": "",
            "evidence": [],
            "warnings": [],
            "error": _format_error(exc),
        }


def _parallel_worker_end_event(slot: dict[str, Any], slot_result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    results = slot_result.get("results") if isinstance(slot_result.get("results"), list) else []
    status = "error" if slot_result.get("status") == "error" else "ok"
    first_error = str((results[0] or {}).get("error") or "") if results else ""
    detail = first_error or f"完成 {len(results)} 个任务"
    return {
        "event": "node_end",
        "traceItem": {
            "nodeId": str(slot.get("nodeId") or ""),
            "type": "parallel_worker",
            "label": str(slot.get("label") or "Worker"),
            "status": status,
            "detail": detail[:300] if detail else f"完成 {len(results)} 个任务",
            "durationMs": float(slot_result.get("durationMs") or 0),
            "inputState": _compact_state({"tasks": [item["task"] for item in slot.get("tasks", [])]}),
            "outputDelta": _compact_state({"workerResults": results}),
        },
        "outputState": _compact_state(state),
    }


def _normalize_worker_tasks(value: Any, max_tasks: int, fallback_goal: str = "") -> list[dict[str, Any]]:
    parsed = _parse_task_payload(value)
    raw_tasks: Any
    if isinstance(parsed, dict):
        raw_tasks = parsed.get("tasks")
    else:
        raw_tasks = parsed
    if isinstance(raw_tasks, dict):
        raw_tasks = [raw_tasks]
    if not isinstance(raw_tasks, list):
        return []
    tasks: list[dict[str, Any]] = []
    max_tasks = max(1, min(int(max_tasks or 5), 10))
    for index, item in enumerate(raw_tasks[:max_tasks], start=1):
        if isinstance(item, str):
            task = {"goal": item}
        elif isinstance(item, dict):
            task = dict(item)
        else:
            continue
        goal = _first_text(task.get("goal"), task.get("description"), task.get("task"), fallback_goal).strip()
        title = _first_text(task.get("title"), task.get("name"), goal, f"任务 {index}").strip()
        target_files = _normalize_string_list(task.get("targetFiles") if "targetFiles" in task else task.get("target_files"))
        suggested_tools = _normalize_string_list(task.get("suggestedTools") if "suggestedTools" in task else task.get("suggested_tools"))
        if not goal and not title:
            continue
        tasks.append(
            {
                "id": str(task.get("id") or f"task_{index}").strip() or f"task_{index}",
                "title": title[:160] or f"任务 {index}",
                "goal": goal or title,
                "targetFiles": target_files,
                "suggestedTools": suggested_tools,
                "status": "pending",
            }
        )
    return tasks


def _parse_task_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = _state_value_to_text(value).strip()
    if not text:
        return None
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    list_start = text.find("[")
    list_end = text.rfind("]")
    if 0 <= list_start < list_end:
        candidates.append(text[list_start : list_end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in re.split(r"[,，\n]+", text) if item.strip()]


def _parallel_worker_system_prompt(base_prompt: str) -> str:
    return (
        f"{base_prompt}\n"
        "你是并行代码阅读 Worker，只完成分配给你的子任务。"
        "严格控制上下文：先定位，再读取小片段；不要读取完整大文件。"
        "最终请返回 JSON，格式为："
        '{"summary":"结论","evidence":[{"path":"文件路径","symbol":"符号或 selector","startLine":1,"endLine":1,"note":"证据说明"}],"warnings":[]}'
        "。不要输出完整工具调用 JSON。"
    )


def _parallel_worker_user_prompt(state: dict[str, Any], task: dict[str, Any]) -> str:
    payload = {
        "userQuestion": _state_value_to_text(state.get("messages")),
        "task": task,
    }
    return "请完成以下代码阅读子任务：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_worker_final_answer(task: dict[str, Any], final_answer: str) -> dict[str, Any]:
    parsed = _parse_task_payload(final_answer)
    task_id = str(task.get("id") or "")
    title = str(task.get("title") or task.get("goal") or task_id)
    if isinstance(parsed, dict):
        evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
        warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
        summary = _state_value_to_text(parsed.get("summary") or parsed.get("final_answer") or parsed.get("answer") or final_answer).strip()
        return {
            "taskId": task_id,
            "title": title[:120],
            "status": "ok",
            "durationMs": 0,
            "summary": summary,
            "evidence": _compact_value(evidence, string_limit=1200, list_limit=12),
            "warnings": [str(item) for item in warnings[:8]],
        }
    return {
        "taskId": task_id,
        "title": title[:120],
        "status": "ok",
        "durationMs": 0,
        "summary": final_answer.strip(),
        "evidence": [],
        "warnings": [],
    }


def _parallel_virtual_start_event(node: NodeIR, task: dict[str, Any], index: int, total: int) -> dict[str, Any]:
    return {
        "event": "virtual_node_start",
        "nodeId": _parallel_virtual_node_id(node, task, index),
        "parentNodeId": node.id,
        "type": "tool",
        "label": f"Worker: {str(task.get('title') or task.get('goal') or f'任务 {index + 1}')[:48]}",
        "inputState": {"task": task},
        "position": _parallel_virtual_position(node, index, total),
    }


def _parallel_virtual_end_event(node: NodeIR, task: dict[str, Any], result: dict[str, Any], index: int, total: int) -> dict[str, Any]:
    status = "error" if result.get("status") == "error" else "ok"
    return {
        "event": "virtual_node_end",
        "traceItem": {
            "nodeId": _parallel_virtual_node_id(node, task, index),
            "type": "tool",
            "label": f"Worker: {str(task.get('title') or task.get('goal') or f'任务 {index + 1}')[:48]}",
            "status": status,
            "detail": str(result.get("error") or result.get("summary") or "Worker 完成")[:300],
            "durationMs": float(result.get("durationMs") or 0),
            "inputState": {"task": task},
            "outputDelta": result,
            "virtual": True,
            "parentNodeId": node.id,
            "position": _parallel_virtual_position(node, index, total),
        },
    }


def _parallel_virtual_node_id(node: NodeIR, task: dict[str, Any], index: int) -> str:
    raw = str(task.get("id") or f"task_{index + 1}")
    safe = re.sub(r"[^A-Za-z0-9_:-]+", "_", raw).strip("_") or f"task_{index + 1}"
    return f"{node.id}::worker_{safe}"


def _parallel_virtual_position(node: NodeIR, index: int, total: int) -> dict[str, float]:
    spacing = 210
    start_y = float(node.position.y) - ((max(total, 1) - 1) * spacing / 2)
    return {"x": float(node.position.x) + 330, "y": start_y + index * spacing}


def _finalize_tools_agent_answer(
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
        response = _call_chat_model(provider, model, messages, model_config)
    except Exception as exc:
        return f"达到最大工具调用轮次 {max_iterations}，已停止。最终总结失败：{exc.__class__.__name__}: {exc}"
    content = getattr(response, "content", str(response))
    decision = _parse_tool_agent_decision(content)
    final_answer = _first_config_value(decision.get("final_answer"))
    return final_answer or content or f"达到最大工具调用轮次 {max_iterations}，已停止。"


def _tools_agent_system_prompt(system_prompt: str, selected_tools: list[dict[str, Any]], max_iterations: int) -> str:
    tool_lines = []
    for tool in selected_tools:
        schema = _parse_json_object(str(tool.get("schemaJson", "{}")))
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


def _parse_tool_agent_decision(content: str) -> dict[str, Any]:
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


def _normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            calls.append(item)
    return calls


def _registered_tool_trace_metadata(tool_config: dict[str, Any]) -> dict[str, str]:
    schema = _parse_json_object(str(tool_config.get("schemaJson", "{}")))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    server = metadata.get("server") if isinstance(metadata.get("server"), dict) else {}
    source = str(tool_config.get("source") or metadata.get("source") or "")
    return {
        "source": "mcp" if source == "mcp" or metadata.get("kind") == "mcp_tool" else ("agent" if source == "agent" or metadata.get("kind") == "agent_tool" else source),
        "serverName": str(metadata.get("serverName") or server.get("name") or ""),
        "agentName": str(metadata.get("agentName") or ""),
        "toolName": str(metadata.get("toolName") or tool_config.get("name") or ""),
    }


def _invoke_registered_tool(
    tool_config: dict[str, Any],
    args: dict[str, Any],
    runtime_environment: RuntimeEnvironment = None,
    model_config: ModelRuntimeConfig = None,
    agent_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_config = _fresh_builtin_tool_config(tool_config) or tool_config
    schema = _parse_json_object(str(tool_config.get("schemaJson", "{}")))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    kind = str(metadata.get("kind") or "").strip()
    source = str(tool_config.get("source") or "").strip().lower()
    try:
        if source == "builtin" or kind == "builtin_tool":
            result = _invoke_builtin_tool(metadata, args, runtime_environment)
            return {"ok": True, "result": _compact_tool_result(result)}
        if source == "python" or kind == "python_function":
            result = _invoke_python_tool(metadata, args)
            return {"ok": True, "result": _compact_tool_result(result)}
        if source == "mcp" or kind == "mcp_tool":
            server = metadata.get("server") if isinstance(metadata.get("server"), dict) else {}
            tool_name = str(metadata.get("toolName") or tool_config.get("name") or "").strip()
            result = invoke_mcp_tool(server, tool_name, args, runtime_environment)
            return {"ok": True, "result": _compact_tool_result(result)}
        if source == "agent" or kind == "agent_tool":
            result = _invoke_agent_tool(metadata, args, model_config, runtime_environment, agent_context)
            return {"ok": bool(result.get("ok", True)), "result": _compact_tool_result(result), "errorType": result.get("errorType")}
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
        return {"ok": False, "error": error, "errorType": _classify_tool_error(error)}


def _invoke_agent_tool(
    metadata: dict[str, Any],
    args: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_context: dict[str, Any] | None,
) -> dict[str, Any]:
    context = agent_context or {}
    depth = int(context.get("agentDepth") or 0)
    if depth >= MAX_AGENT_CALL_DEPTH:
        raise RuntimeError(f"子 Agent 调用深度超过限制：{MAX_AGENT_CALL_DEPTH}")
    current_project_id = str(context.get("projectId") or "").strip()
    project_id = str(metadata.get("projectId") or "").strip()
    if not project_id:
        raise RuntimeError("Agent Tool 缺少 projectId。")
    if current_project_id and project_id == current_project_id:
        raise RuntimeError("禁止 Agent 调用当前项目自身，避免递归。")

    input_text = _first_text(args.get("input"), args.get("query"), args.get("task"), args.get("message"))
    state_patch = args.get("statePatch") if isinstance(args.get("statePatch"), dict) else {}
    parent_state = context.get("state") if isinstance(context.get("state"), dict) else {}
    child_input = {
        **state_patch,
        "messages": input_text or _state_value_to_text(parent_state.get("messages")),
        "chat": input_text or _state_value_to_text(parent_state.get("chat") or parent_state.get("messages")),
        "parent_state": _compact_state(parent_state),
    }
    started = time.perf_counter()
    child_project = read_project(project_id)
    trace, output_state = _walk_project(
        child_project,
        _normalize_input(child_input),
        "live",
        _normalize_model_config(model_config),
        _normalize_runtime_environment(runtime_environment),
        depth + 1,
    )
    error_item = next((item for item in trace if item.get("status") == "error"), None)
    final_answer = _agent_child_final_answer(output_state)
    result = {
        "ok": error_item is None,
        "agentId": str(metadata.get("agentId") or ""),
        "agentName": str(metadata.get("agentName") or child_project.project.name or project_id),
        "projectId": project_id,
        "finalAnswer": final_answer,
        "outputState": _compact_state(output_state),
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
    }
    if error_item:
        result["error"] = str(error_item.get("detail") or "子 Agent 执行失败。")
        result["errorType"] = "agent_runtime"
    return result


def _execute_live_agent_ref(
    node: NodeIR,
    project: ProjectIR,
    state: dict[str, Any],
    model_config: ModelRuntimeConfig,
    runtime_environment: RuntimeEnvironment,
    agent_depth: int,
) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField") or "agent_ref_result").strip() or "agent_ref_result"
    project_id = str(config.get("agentProjectId") or "").strip()
    if not project_id:
        raise RuntimeError("Agent Ref 未绑定 Agent。")
    if project_id == project.project.id:
        raise RuntimeError("禁止 Agent Ref 调用当前项目自身。")
    instruction = render_template(str(config.get("instruction") or ""), state).strip()
    input_text = instruction or _state_value_to_text(state.get("messages") or state.get("chat")) or _agent_state_prompt(state)
    result = _invoke_agent_tool(
        {
            "agentId": str(config.get("agentId") or project_id),
            "agentName": str(config.get("agentName") or node.label or project_id),
            "projectId": project_id,
        },
        {"input": input_text, "statePatch": {}},
        model_config,
        runtime_environment,
        {"projectId": project.project.id, "projectName": project.project.name, "state": state, "agentDepth": agent_depth},
    )
    detail = f"真实调用 Agent Ref「{result.get('agentName')}」({config.get('protocol', 'handoff')})，输出到 state.{output_field}"
    return {output_field: result}, detail


def _agent_child_final_answer(output_state: dict[str, Any]) -> str:
    for key in ("final_answer", "answer", "agent_result", "tools_result", "llm_result"):
        text = _state_value_to_text(output_state.get(key)).strip()
        if text:
            return text
    return _fallback_reply_content(output_state)


def _recommended_next_tools(tool_name: str, args: dict[str, Any], observation: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(observation, dict):
        return []
    recommendations: list[dict[str, Any]] = []
    result = observation.get("result") if isinstance(observation.get("result"), dict) else {}
    path = _first_text(args.get("path"), args.get("file"), result.get("path") if isinstance(result, dict) else "")
    language = _language_from_path(path)
    truncated = _has_truthy_key(result, "truncated") or bool(observation.get("truncated"))
    ambiguous = _has_truthy_key(result, "ambiguous")
    tool_key = str(tool_name or "").strip()

    if truncated:
        if tool_key == "read_file" and path:
            recommendations.extend(
                [
                    _next_tool("read_file_chunk", "read_file 返回已截断，改用 offset 或行号继续读取。", {"path": path, "offset": _content_length(result), "max_chars": 6000}),
                    _next_tool("search_code", "先用关键词定位需要的片段，避免再次读取整文件。", {"root": _path_parent(path), "query": "<关键词>", "file_glob": _path_name(path)}),
                ]
            )
            if language in {"python", "javascript", "typescript", "html", "css", "scss", "less", "vue", "svelte", "json", "yaml", "markdown"}:
                recommendations.append(_next_tool("chunk_code_semantic", "按语义片段拆分大文件后再选择具体片段。", {"path": path, "max_chunks": 40}))
        elif path:
            recommendations.append(_next_tool("read_file_chunk", "结果被截断，可缩小范围或按片段继续读取。", {"path": path, "max_chars": 6000}))

    if path and language in {"html", "vue", "svelte"} and tool_key in {"read_file", "read_file_chunk", "list_code_symbols"}:
        recommendations.extend(
            [
                _next_tool("summarize_page_structure", "HTML 页面先摘要结构，再选择局部 selector。", {"path": path}),
                _next_tool("extract_html", "按 CSS selector 抽取局部 HTML，避免读取整页。", {"path": path, "selector": "body", "mode": "html"}),
            ]
        )
    if path and language in {"css", "scss", "less"} and tool_key in {"read_file", "read_file_chunk", "list_code_symbols"}:
        recommendations.append(_next_tool("extract_css_rules", "样式文件优先按 selector、property 或 query 抽取规则。", {"path": path, "query": "<样式关键词>"}))

    if ambiguous and path:
        alternatives = result.get("alternatives") if isinstance(result.get("alternatives"), list) else []
        first = next((item for item in alternatives if isinstance(item, dict)), None)
        if first:
            recommendations.append(
                _next_tool(
                    "extract_code_symbol",
                    "当前符号有歧义，使用 alternatives 中更明确的 name/kind 重新抽取。",
                    {"path": path, "symbol": first.get("name", ""), "kind": first.get("kind", "any")},
                )
            )

    if not observation.get("ok"):
        error_type = str(observation.get("errorType") or _classify_tool_error(str(observation.get("error") or "")))
        if error_type == "tool_args":
            recommendations.append(_next_tool(tool_key or "<tool>", "检查必填参数和参数名后重试。", args))
        elif error_type == "parse_error" and path:
            recommendations.append(_next_tool("read_file_chunk", "解析失败时先读取相关片段确认语法或内容格式。", {"path": path, "max_chars": 4000}))

    return _dedupe_recommendations(recommendations)


def _classify_tool_error(message: str) -> str:
    text = str(message or "")
    lower = text.lower()
    if "mcp" in lower and ("json" in lower or "参数" in text or "arguments" in lower):
        return "tool_args"
    if "白名单" in text or "黑名单" in text or "审批" in text or "approval" in lower or "命令不在" in text:
        return "permission"
    if "允许目录" in text or "路径不在" in text:
        return "path_permission"
    if "网络访问" in text or "不允许访问域名" in text or "只允许访问 http/https" in text or "domain" in lower:
        return "network_permission"
    if "超过当前运行环境" in text or "文件太大" in text or "max file" in lower:
        return "file_too_large"
    if "解析失败" in text or "正则表达式无效" in text or "jsondecode" in lower or "syntaxerror" in lower or "parse" in lower:
        return "parse_error"
    if ("需要" in text and "参数" in text) or "missing" in lower or "required" in lower or "未知 Tool" in text:
        return "tool_args"
    return "tool_error"


def _next_tool(tool: str, reason: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"tool": tool, "reason": reason, "args": args}


def _dedupe_recommendations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = f"{item.get('tool')}:{json.dumps(item.get('args', {}), ensure_ascii=False, sort_keys=True, default=str)}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 5:
            break
    return result


def _has_truthy_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        if bool(value.get(key)):
            return True
        return any(_has_truthy_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_has_truthy_key(item, key) for item in value[:20])
    return False


def _content_length(value: dict[str, Any]) -> int:
    content = value.get("content")
    return len(content) if isinstance(content, str) else 0


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_") or "agent"


def _path_name(path: str) -> str:
    return Path(path).name if path else "*"


def _path_parent(path: str) -> str:
    if not path:
        return "."
    parent = Path(path).parent.as_posix()
    return parent if parent and parent != "." else "."


def _language_from_path(path: str) -> str:
    if not path:
        return "unknown"
    return _detect_code_language(Path(path), "")


def _invoke_builtin_tool(metadata: dict[str, Any], args: dict[str, Any], runtime_environment: RuntimeEnvironment) -> Any:
    builtin_id = str(metadata.get("builtinId") or metadata.get("id") or "").strip()
    runtime = _normalize_runtime_environment(runtime_environment)
    if builtin_id == "web_search":
        return _builtin_web_search(args, runtime)
    if builtin_id == "read_file":
        return _builtin_read_file(args, runtime)
    if builtin_id == "list_directory":
        return _builtin_list_directory(args, runtime)
    if builtin_id == "task_plan":
        return _builtin_task_plan(args)
    if builtin_id == "read_file_chunk":
        return _builtin_read_file_chunk(args, runtime)
    if builtin_id == "search_code":
        return _builtin_search_code(args, runtime)
    if builtin_id == "list_code_symbols":
        return _builtin_list_code_symbols(args, runtime)
    if builtin_id == "extract_html":
        return _builtin_extract_html(args, runtime)
    if builtin_id == "extract_css_rules":
        return _builtin_extract_css_rules(args, runtime)
    if builtin_id == "extract_html_by_text":
        return _builtin_extract_html_by_text(args, runtime)
    if builtin_id == "extract_css_for_html":
        return _builtin_extract_css_for_html(args, runtime)
    if builtin_id == "summarize_page_structure":
        return _builtin_summarize_page_structure(args, runtime)
    if builtin_id == "resolve_asset_references":
        return _builtin_resolve_asset_references(args, runtime)
    if builtin_id == "extract_code_symbol":
        return _builtin_extract_code_symbol(args, runtime)
    if builtin_id == "chunk_code_semantic":
        return _builtin_chunk_code_semantic(args, runtime)
    if builtin_id == "fetch_url":
        return _builtin_fetch_url(args, runtime)
    if builtin_id == "propose_patch":
        return _builtin_propose_patch(args, runtime)
    if builtin_id == "apply_patch_set":
        raise RuntimeError("apply_patch_set 只能通过前端变更集应用面板调用，Agent 运行中不能直接应用补丁。")
    if builtin_id == "rollback_patch_set":
        raise RuntimeError("rollback_patch_set 只能通过前端变更集应用面板调用。")
    if builtin_id == "replace_in_file":
        return _builtin_replace_in_file(args, runtime)
    if builtin_id == "write_file":
        return _builtin_write_file(args, runtime)
    if builtin_id == "run_whitelisted_command":
        return _builtin_run_whitelisted_command(args, runtime)
    raise RuntimeError(f"未知内置 Tool：{builtin_id or '未配置 builtinId'}")


def _builtin_web_search(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        raise RuntimeError("web_search 需要 query 参数。")
    mode = str(args.get("mode") or args.get("search_mode") or "serp").strip().lower()
    if mode not in {"auto", "instant", "serp"}:
        mode = "serp"
    serp_fallback = args.get("serp_fallback", args.get("fallback", True)) is not False
    max_results = min(_positive_int(args.get("max_results", args.get("limit", 5)), 5), 12)

    data: dict[str, Any] = {}
    related_topics: list[dict[str, str]] = []
    if mode != "serp":
        _assert_network_allowed("https://api.duckduckgo.com/", runtime, extra_allowed_hosts={"api.duckduckgo.com"})
        params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }
        url = "https://api.duckduckgo.com/?" + urlencode(params)
        response = httpx.get(url, timeout=12, follow_redirects=True, headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        related_topics = _duckduckgo_related_topics(data.get("RelatedTopics"), max_results)

    has_instant_answer = _duckduckgo_has_instant_answer(data, related_topics)
    should_run_serp = mode == "serp" or (mode == "auto" and serp_fallback and not has_instant_answer)
    serp_results = _duckduckgo_serp_results(query, max_results, runtime) if should_run_serp else []
    source = "duckduckgo_serp" if mode == "serp" else "duckduckgo_serp_fallback" if serp_results and not has_instant_answer else "duckduckgo_instant_answer"
    return {
        "query": query,
        "source": source,
        "searchMode": mode,
        "serpFallbackUsed": bool(serp_results and mode != "serp" and not has_instant_answer),
        "answer": data.get("Answer") or "",
        "abstract": data.get("AbstractText") or data.get("Abstract") or "",
        "abstractUrl": data.get("AbstractURL") or "",
        "definition": data.get("Definition") or "",
        "relatedTopics": related_topics,
        "serpResults": serp_results,
        "rawLimited": _compact_value(data),
    }


def _duckduckgo_has_instant_answer(data: dict[str, Any], related_topics: list[dict[str, str]]) -> bool:
    return bool(
        str(data.get("Answer") or "").strip()
        or str(data.get("AbstractText") or data.get("Abstract") or "").strip()
        or str(data.get("Definition") or "").strip()
        or related_topics
    )


def _duckduckgo_serp_results(query: str, limit: int, runtime: dict[str, Any]) -> list[dict[str, str]]:
    _assert_network_allowed(
        "https://html.duckduckgo.com/html/",
        runtime,
        extra_allowed_hosts={"duckduckgo.com", "html.duckduckgo.com"},
    )
    params = {"q": query}
    response = httpx.get(
        "https://html.duckduckgo.com/html/?" + urlencode(params),
        timeout=15,
        follow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "GraphicLangGraph/0.1 (+https://local)",
        },
    )
    response.raise_for_status()
    parser = DuckDuckGoHtmlResultsParser(limit)
    parser.feed(response.text)
    parser.close()
    return parser.results[:limit]


class DuckDuckGoHtmlResultsParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: list[dict[str, str]] = []
        self._active_title: dict[str, Any] | None = None
        self._active_snippet_index: int | None = None
        self._snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.results) >= self.limit:
            return
        attr = {key: value or "" for key, value in attrs}
        class_name = attr.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._active_title = {"href": attr.get("href", ""), "parts": []}
            return
        if tag in {"a", "div"} and "result__snippet" in class_name and self.results:
            self._active_snippet_index = len(self.results) - 1
            self._snippet_depth = 1
            return
        if self._active_snippet_index is not None:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_title is not None:
            title = _clean_search_text(" ".join(self._active_title["parts"]))
            url = _duckduckgo_result_url(str(self._active_title.get("href") or ""))
            if title and url and not any(item["url"] == url for item in self.results):
                self.results.append({"title": title, "url": url, "snippet": ""})
            self._active_title = None
            return
        if self._active_snippet_index is not None:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                self._active_snippet_index = None

    def handle_data(self, data: str) -> None:
        if self._active_title is not None:
            self._active_title["parts"].append(data)
            return
        if self._active_snippet_index is not None and 0 <= self._active_snippet_index < len(self.results):
            current = self.results[self._active_snippet_index].get("snippet", "")
            self.results[self._active_snippet_index]["snippet"] = _clean_search_text(f"{current} {data}")


def _duckduckgo_result_url(raw_url: str) -> str:
    url = html_lib.unescape(raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = f"https://duckduckgo.com{url}"
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target.strip()
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return ""


def _clean_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def _duckduckgo_related_topics(value: Any, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    def visit(items: Any) -> None:
        if len(results) >= limit or not isinstance(items, list):
            return
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("Topics"), list):
                visit(item["Topics"])
                continue
            text = str(item.get("Text") or "").strip()
            url = str(item.get("FirstURL") or "").strip()
            if text or url:
                results.append({"title": text[:180], "url": url, "snippet": text})

    visit(value)
    return results


def _builtin_read_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("read_file 需要 path 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可读取文件：{path}")
    max_bytes = min(_positive_int(args.get("max_bytes", runtime.get("maxFileBytes")), _runtime_max_file_bytes(runtime)), _runtime_max_file_bytes(runtime))
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes]
    text = content.decode(encoding, errors="replace")
    max_chars = _positive_int(args.get("max_chars"), len(text))
    if max_chars < len(text):
        text = text[:max_chars]
        truncated = True
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "truncated": truncated,
        "content": text,
    }


def _builtin_list_directory(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or ".").strip() or "."
    directory = _resolve_runtime_path(raw_path, runtime)
    if not directory.is_dir():
        raise RuntimeError(f"不是可列出的目录：{directory}")
    pattern = str(args.get("pattern") or "*").strip() or "*"
    recursive = _truthy(args.get("recursive"))
    max_entries = min(_positive_int(args.get("max_entries"), 100), 500)
    iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
    entries: list[dict[str, Any]] = []
    for item in iterator:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if not _is_relative_to(resolved, directory):
            continue
        stat = resolved.stat()
        entries.append(
            {
                "name": resolved.name,
                "path": str(resolved),
                "relativePath": resolved.relative_to(directory).as_posix(),
                "type": "directory" if resolved.is_dir() else "file",
                "size": stat.st_size if resolved.is_file() else 0,
            }
        )
        if len(entries) >= max_entries:
            break
    return {
        "path": str(directory),
        "pattern": pattern,
        "recursive": recursive,
        "entries": entries,
        "truncated": len(entries) >= max_entries,
    }


def _builtin_task_plan(args: dict[str, Any]) -> dict[str, Any]:
    max_tasks = min(_positive_int(args.get("maxTasks", args.get("max_tasks", 6)), 6), 10)
    payload = {"tasks": args.get("tasks")}
    tasks = _normalize_worker_tasks(payload, max_tasks=max_tasks, fallback_goal=str(args.get("sourceGoal") or args.get("source_goal") or ""))
    if not tasks:
        raise RuntimeError("task_plan 需要 tasks 数组，且每个任务至少包含 goal、description、task、title 或 name。")
    return {
        "format": "task_splitter_v1",
        "taskCount": len(tasks),
        "tasks": tasks,
    }


def _builtin_read_file_chunk(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("read_file_chunk 需要 path 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可读取文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"read_file_chunk 只读取文本文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_chars = min(_positive_int(args.get("max_chars"), 4000), _runtime_max_file_bytes(runtime))
    start_line = _optional_positive_int(args.get("start_line", args.get("startLine")))
    end_line = _optional_positive_int(args.get("end_line", args.get("endLine")))

    if start_line is not None:
        return _read_file_chunk_by_lines(path, start_line, end_line, max_chars, encoding)

    offset = _non_negative_int(args.get("offset"), 0)
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    total_lines = _count_file_lines(path, encoding)
    end = min(len(text), offset + max_chars)
    content = text[offset:end] if offset < len(text) else ""
    truncated = source_truncated or end < len(text)
    start_line_for_offset = text[:offset].count("\n") + 1 if text else 1
    end_line_for_offset = start_line_for_offset + content.count("\n") if content else start_line_for_offset
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "startLine": start_line_for_offset,
        "endLine": end_line_for_offset,
        "totalLines": total_lines,
        "offset": offset,
        "nextOffset": end if truncated and end > offset else None,
        "truncated": truncated,
        "content": content,
    }


def _read_file_chunk_by_lines(path: Path, start_line: int, end_line: int | None, max_chars: int, encoding: str) -> dict[str, Any]:
    if end_line is not None and end_line < start_line:
        raise RuntimeError("read_file_chunk 的 end_line 不能小于 start_line。")
    content_parts: list[str] = []
    total_lines = 0
    last_returned_line: int | None = None
    truncated = False
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        for line_no, line in enumerate(handle, start=1):
            total_lines = line_no
            if line_no < start_line:
                continue
            if end_line is not None and line_no > end_line:
                continue
            current_len = sum(len(part) for part in content_parts)
            if current_len + len(line) > max_chars:
                remaining = max_chars - current_len
                if remaining > 0:
                    content_parts.append(line[:remaining])
                    last_returned_line = line_no
                truncated = True
                continue
            content_parts.append(line)
            last_returned_line = line_no
    content = "".join(content_parts)
    if truncated and last_returned_line is not None and last_returned_line < total_lines:
        next_start_line = last_returned_line + 1
    elif end_line is not None and end_line < total_lines:
        next_start_line = end_line + 1
    else:
        next_start_line = None
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "startLine": start_line,
        "endLine": last_returned_line,
        "totalLines": total_lines,
        "offset": None,
        "nextOffset": None,
        "nextStartLine": next_start_line,
        "truncated": truncated,
        "content": content,
    }


def _builtin_search_code(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise RuntimeError("search_code 需要 query 参数。")
    root = _resolve_runtime_path(str(args.get("root") or args.get("path") or ".").strip() or ".", runtime)
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    file_glob = str(args.get("file_glob") or args.get("glob") or "*").strip() or "*"
    regex = _truthy(args.get("regex"))
    case_sensitive = _truthy(args.get("case_sensitive", args.get("caseSensitive")))
    context_lines = min(_positive_int(args.get("context_lines", args.get("contextLines")), 0), 8)
    max_results = min(_positive_int(args.get("max_results", args.get("limit")), 50), 200)
    pattern = None
    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            raise RuntimeError(f"search_code 正则表达式无效：{exc}") from exc

    matches: list[dict[str, Any]] = []
    scanned_files = 0
    skipped_binary = 0
    for file_path in _iter_search_files(root, file_glob):
        if len(matches) >= max_results:
            break
        if _is_binary_file(file_path):
            skipped_binary += 1
            continue
        scanned_files += 1
        try:
            text, file_truncated = _read_text_limited(file_path, runtime, encoding)
        except OSError:
            continue
        lines = text.splitlines()
        haystack_query = query if case_sensitive else query.lower()
        for index, line in enumerate(lines):
            if pattern:
                match = pattern.search(line)
                if not match:
                    continue
                column = match.start() + 1
            else:
                haystack_line = line if case_sensitive else line.lower()
                found = haystack_line.find(haystack_query)
                if found < 0:
                    continue
                column = found + 1
            matches.append(
                {
                    "path": str(file_path),
                    "relativePath": _safe_relative_path(file_path, root),
                    "line": index + 1,
                    "column": column,
                    "text": line,
                    "before": lines[max(0, index - context_lines) : index] if context_lines else [],
                    "after": lines[index + 1 : index + 1 + context_lines] if context_lines else [],
                    "fileTruncated": file_truncated,
                }
            )
            if len(matches) >= max_results:
                break
    return {
        "root": str(root),
        "query": query,
        "regex": regex,
        "fileGlob": file_glob,
        "matches": matches,
        "scannedFiles": scanned_files,
        "skippedBinaryFiles": skipped_binary,
        "truncated": len(matches) >= max_results,
    }


def _builtin_list_code_symbols(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("list_code_symbols 需要 path 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析文件：{path}")
    if _is_binary_file(path):
        return {"path": str(path), "language": "binary", "symbols": [], "warnings": ["疑似二进制文件，已跳过。"]}
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_symbols = min(_positive_int(args.get("max_symbols", args.get("limit")), 100), 500)
    language = _detect_code_language(path, str(args.get("language") or ""))
    text, truncated = _read_text_limited(path, runtime, encoding)
    symbols, warnings = glg_semantic_symbols(text, language, max_symbols)
    if truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，符号列表可能不完整。")
    return {
        "path": str(path),
        "language": language,
        "symbols": symbols[:max_symbols],
        "truncated": truncated or len(symbols) > max_symbols,
        "warnings": warnings,
    }


def _builtin_extract_html(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    selector = str(args.get("selector") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_html 需要 path 参数。")
    if not selector:
        raise RuntimeError("extract_html 需要 selector 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 HTML 的文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"extract_html 只读取文本 HTML 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    mode = str(args.get("mode") or "html").strip().lower()
    if mode not in {"html", "text", "attributes"}:
        mode = "html"
    max_results = min(_positive_int(args.get("max_results", args.get("limit")), 20), 100)
    max_chars = min(_positive_int(args.get("max_chars"), 4000), _runtime_max_file_bytes(runtime))
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("后端缺少 beautifulsoup4，请安装 requirements.txt 后重试。") from exc

    soup = BeautifulSoup(text, "html.parser")
    try:
        selected = soup.select(selector)
    except Exception as exc:
        raise RuntimeError(f"extract_html selector 无效：{exc}") from exc

    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    search_from = 0
    truncated = source_truncated or len(selected) > max_results
    for index, element in enumerate(selected[:max_results], start=1):
        outer_html = str(element)
        start_line, end_line, search_from = _best_effort_html_lines(text, outer_html, search_from)
        if start_line is None:
            sourceline = getattr(element, "sourceline", None)
            if isinstance(sourceline, int):
                start_line = sourceline
                end_line = sourceline
        item: dict[str, Any] = {
            "index": index,
            "selector": selector,
            "startLine": start_line,
            "endLine": end_line,
        }
        if mode == "text":
            value = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            clipped, was_truncated = _clip_text(value, max_chars)
            item["text"] = clipped
        elif mode == "attributes":
            item["attributes"] = {
                str(key): (" ".join(value) if isinstance(value, list) else str(value))
                for key, value in element.attrs.items()
            }
            was_truncated = False
        else:
            clipped, was_truncated = _clip_text(outer_html, max_chars)
            item["html"] = clipped
        if was_truncated:
            item["truncated"] = True
            truncated = True
        matches.append(item)
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，HTML 抽取结果可能不完整。")
    return {
        "path": str(path),
        "selector": selector,
        "mode": mode,
        "matches": matches,
        "count": len(matches),
        "totalMatched": len(selected),
        "truncated": truncated,
        "warnings": warnings,
    }


def _builtin_extract_css_rules(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    selector = str(args.get("selector") or "").strip()
    property_name = str(args.get("property") or args.get("property_name") or args.get("propertyName") or "").strip()
    query = str(args.get("query") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_css_rules 需要 path 参数。")
    if not selector and not property_name and not query:
        raise RuntimeError("extract_css_rules 需要 selector、property 或 query 至少一个参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 CSS 的文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"extract_css_rules 只读取文本 CSS 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_results = min(_positive_int(args.get("max_results", args.get("limit")), 50), 200)
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    rules, parse_warnings = _parse_css_rules(text)
    matched: list[dict[str, Any]] = []
    total_matched = 0
    selector_key = _normalize_css_selector(selector) if selector else ""
    property_key = property_name.lower()
    query_key = query.lower()
    for rule in rules:
        if selector_key and selector_key not in {_normalize_css_selector(item) for item in rule["selectors"]}:
            continue
        if property_key and not any(str(name).lower() == property_key for name in rule["declarations"].keys()):
            continue
        if query_key and query_key not in str(rule["css"]).lower():
            continue
        total_matched += 1
        if len(matched) < max_results:
            matched.append(rule)
    warnings = list(parse_warnings)
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，CSS 抽取结果可能不完整。")
    return {
        "path": str(path),
        "selector": selector,
        "property": property_name,
        "query": query,
        "rules": matched,
        "count": len(matched),
        "totalMatched": total_matched,
        "truncated": source_truncated or total_matched > max_results,
        "warnings": warnings,
    }


def _builtin_extract_html_by_text(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    query = str(args.get("query") or args.get("text") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_html_by_text 需要 path 参数。")
    if not query:
        raise RuntimeError("extract_html_by_text 需要 query 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 HTML 的文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"extract_html_by_text 只读取文本 HTML 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_results = min(_positive_int(args.get("max_results", args.get("limit")), 20), 100)
    max_chars = min(_positive_int(args.get("max_chars"), 4000), _runtime_max_file_bytes(runtime))
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    result = glg_extract_html_by_text(
        text=text,
        query=query,
        regex=_truthy(args.get("regex")),
        mode=str(args.get("mode") or "html"),
        max_results=max_results,
        max_chars=max_chars,
        case_sensitive=_truthy(args.get("case_sensitive", args.get("caseSensitive"))),
    )
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，HTML 文本抽取结果可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["truncated"] = bool(result.get("truncated") or source_truncated)
    result["warnings"] = warnings
    return result


def _builtin_extract_css_for_html(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("css_path") or args.get("cssPath") or "").strip()
    selector = str(args.get("selector") or args.get("html_selector") or args.get("htmlSelector") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_css_for_html 需要 path 参数。")
    if not selector:
        raise RuntimeError("extract_css_for_html 需要 selector 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 CSS 的文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"extract_css_for_html 只读取文本 CSS 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_results = min(_positive_int(args.get("max_results", args.get("limit")), 50), 200)
    css_text, css_truncated = _read_text_limited(path, runtime, encoding)
    html_text = ""
    html_path_text = str(args.get("html_path") or args.get("htmlPath") or "").strip()
    html_path: Path | None = None
    html_truncated = False
    if html_path_text:
        html_path = _resolve_runtime_path(html_path_text, runtime)
        if not html_path.is_file():
            raise RuntimeError(f"不是可分析 HTML 的文件：{html_path}")
        if _is_binary_file(html_path):
            raise RuntimeError(f"extract_css_for_html 只读取文本 HTML 文件，疑似二进制文件：{html_path}")
        html_text, html_truncated = _read_text_limited(html_path, runtime, encoding)
    result = glg_extract_css_for_html(css_text=css_text, selector=selector, html_text=html_text, max_results=max_results)
    warnings = list(result.get("warnings") or [])
    if css_truncated:
        warnings.append("CSS 文件内容超过当前运行环境单次读取大小，样式匹配可能不完整。")
    if html_truncated:
        warnings.append("HTML 文件内容超过当前运行环境单次读取大小，元素 token 推导可能不完整。")
    result["path"] = str(path)
    result["htmlPath"] = str(html_path) if html_path else ""
    result["encoding"] = encoding
    result["truncated"] = bool(result.get("truncated") or css_truncated or html_truncated)
    result["warnings"] = warnings
    return result


def _builtin_summarize_page_structure(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("summarize_page_structure 需要 path 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析 HTML 的文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"summarize_page_structure 只读取文本 HTML 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_items = min(_positive_int(args.get("max_items", args.get("limit")), 50), 200)
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    result = glg_summarize_page_structure(text, max_items)
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，页面结构摘要可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["truncated"] = source_truncated
    result["warnings"] = warnings
    return result


def _builtin_resolve_asset_references(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("resolve_asset_references 需要 path 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可扫描资源引用的文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"resolve_asset_references 只读取文本 HTML/CSS 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    language = _detect_code_language(path, str(args.get("language") or ""))
    max_results = min(_positive_int(args.get("max_results", args.get("limit")), 200), 500)
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    result = glg_asset_references(text, language, max_results)
    references = [_enrich_asset_reference(item, path, runtime) for item in result.get("references", []) if isinstance(item, dict)]
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，资源引用可能不完整。")
    return {
        "path": str(path),
        "language": language,
        "references": references,
        "count": len(references),
        "totalMatched": result.get("totalMatched", len(references)),
        "truncated": bool(result.get("truncated") or source_truncated),
        "warnings": warnings,
    }


def _builtin_extract_code_symbol(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    symbol = str(args.get("symbol") or args.get("name") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_code_symbol 需要 path 参数。")
    if not symbol:
        raise RuntimeError("extract_code_symbol 需要 symbol 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"extract_code_symbol 只读取文本代码文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    language = _detect_code_language(path, str(args.get("language") or ""))
    max_chars = min(_positive_int(args.get("max_chars"), 4000), _runtime_max_file_bytes(runtime))
    include_context = _truthy(args.get("include_context", args.get("includeContext")))
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    result = glg_extract_code_symbol(
        text=text,
        language=language,
        symbol=symbol,
        kind=str(args.get("kind") or "any"),
        max_chars=max_chars,
        include_context=include_context,
    )
    if not result.get("found"):
        alternatives = result.get("alternatives")
        hint = ""
        if isinstance(alternatives, list) and alternatives:
            names = ", ".join(str(item.get("name") or "") for item in alternatives[:8] if isinstance(item, dict))
            hint = f"。候选符号：{names}" if names else ""
        raise RuntimeError(f"未找到符号：{symbol}{hint}")
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，符号抽取结果可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["warnings"] = warnings
    result["truncated"] = bool(result.get("truncated") or source_truncated)
    result.pop("found", None)
    return result


def _builtin_chunk_code_semantic(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("chunk_code_semantic 需要 path 参数。")
    path = _resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析文件：{path}")
    if _is_binary_file(path):
        raise RuntimeError(f"chunk_code_semantic 只读取文本代码文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    language = _detect_code_language(path, str(args.get("language") or ""))
    max_chars = min(_positive_int(args.get("max_chars"), 4000), _runtime_max_file_bytes(runtime))
    max_chunks = min(_positive_int(args.get("max_chunks", args.get("limit")), 80), 500)
    include_content = _truthy(args.get("include_content", args.get("includeContent")))
    text, source_truncated = _read_text_limited(path, runtime, encoding)
    result = glg_chunk_code_semantic(
        text=text,
        language=language,
        max_chars=max_chars,
        max_chunks=max_chunks,
        include_content=include_content,
    )
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，语义分片可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["truncated"] = bool(result.get("truncated") or source_truncated)
    result["warnings"] = warnings
    return result


def _builtin_fetch_url(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    if not url:
        raise RuntimeError("fetch_url 需要 url 参数。")
    _assert_network_allowed(url, runtime)
    max_bytes = _runtime_max_http_bytes(runtime)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    body = response.content[: max_bytes + 1]
    truncated = len(body) > max_bytes
    if truncated:
        body = body[:max_bytes]
    encoding = response.encoding or "utf-8"
    text = body.decode(encoding, errors="replace")
    max_chars = _positive_int(args.get("max_chars"), len(text))
    if max_chars < len(text):
        text = text[:max_chars]
        truncated = True
    return {
        "url": str(response.url),
        "statusCode": response.status_code,
        "contentType": response.headers.get("content-type", ""),
        "truncated": truncated,
        "text": text,
    }


def _builtin_propose_patch(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return propose_patch(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def _builtin_replace_in_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return replace_in_file(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def _builtin_write_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return write_file(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def _builtin_run_whitelisted_command(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    try:
        return run_whitelisted_command(args, runtime)
    except EditSessionError as exc:
        raise RuntimeError(str(exc)) from exc


def _normalize_runtime_environment(runtime_environment: RuntimeEnvironment) -> dict[str, Any]:
    if runtime_environment:
        return resolve_runtime_environment(runtime_environment)
    return default_runtime_environment().model_dump(by_alias=True)


def _runtime_allowed_roots(runtime: dict[str, Any]) -> list[Path]:
    raw_roots = _json_string_list(runtime.get("allowedRootsJson"))
    if not raw_roots:
        env_roots = os.getenv("GLG_FILE_TOOL_ROOTS", "")
        raw_roots = [item.strip() for item in re.split(r"[;\n]+", env_roots) if item.strip()]
    if not raw_roots:
        raw_roots = [str(ROOT_DIR)]
    roots: list[Path] = []
    for item in raw_roots:
        try:
            roots.append(Path(item).expanduser().resolve())
        except OSError:
            continue
    return roots or [ROOT_DIR.resolve()]


def _resolve_runtime_path(value: str, runtime: dict[str, Any]) -> Path:
    raw_path = Path(value).expanduser()
    roots = _runtime_allowed_roots(runtime)
    candidates = [raw_path] if raw_path.is_absolute() else [ROOT_DIR / raw_path, *(root / raw_path for root in roots)]
    allowed: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if any(_is_relative_to(resolved, root) for root in roots):
            allowed.append(resolved)
    if allowed:
        return next((path for path in allowed if path.exists()), allowed[0])
    root_text = "；".join(str(root) for root in roots)
    first = candidates[0]
    try:
        first_resolved = first.resolve()
    except OSError:
        first_resolved = first.absolute()
    raise RuntimeError(f"路径不在当前运行环境允许目录内：{first_resolved}。允许目录：{root_text}")


def _enrich_asset_reference(reference: dict[str, Any], base_file: Path, runtime: dict[str, Any]) -> dict[str, Any]:
    item = dict(reference)
    raw_url = str(item.get("url") or "").strip()
    item["url"] = raw_url
    parsed = urlparse(raw_url)
    if not raw_url:
        item.update({"external": False, "allowed": False, "exists": False, "resolvedPath": ""})
        return item
    if parsed.scheme in {"http", "https", "data", "blob", "mailto", "tel"} or raw_url.startswith(("#", "//")):
        item.update({"external": True, "allowed": None, "exists": None, "resolvedPath": ""})
        return item
    relative_part = unquote(raw_url.split("?", 1)[0].split("#", 1)[0])
    if not relative_part:
        item.update({"external": False, "allowed": False, "exists": False, "resolvedPath": ""})
        return item
    candidate = (base_file.parent / relative_part).resolve()
    allowed = any(_is_relative_to(candidate, root) for root in _runtime_allowed_roots(runtime))
    item.update(
        {
            "external": False,
            "allowed": allowed,
            "exists": candidate.exists() if allowed else False,
            "resolvedPath": str(candidate) if allowed else "",
        }
    )
    return item


def _read_text_limited(path: Path, runtime: dict[str, Any], encoding: str) -> tuple[str, bool]:
    max_bytes = _runtime_max_file_bytes(runtime)
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes]
    return content.decode(encoding or "utf-8", errors="replace"), truncated


def _count_file_lines(path: Path, encoding: str) -> int:
    count = 0
    with path.open("r", encoding=encoding or "utf-8", errors="replace", newline="") as handle:
        for count, _line in enumerate(handle, start=1):
            pass
    return count


def _is_binary_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(CODE_TOOL_BINARY_CHECK_BYTES)
    except OSError:
        return True
    return b"\x00" in sample


def _iter_search_files(root: Path, file_glob: str):
    if root.is_file():
        if fnmatch.fnmatch(root.name, file_glob) or fnmatch.fnmatch(root.as_posix(), file_glob):
            yield root
        return
    if not root.is_dir():
        raise RuntimeError(f"搜索根路径不存在或不是目录：{root}")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in CODE_TOOL_EXCLUDED_DIRS and not name.startswith(".")
        ]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            rel = _safe_relative_path(path, root)
            if fnmatch.fnmatch(filename, file_glob) or fnmatch.fnmatch(rel, file_glob):
                yield path


def _safe_relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root if root.is_dir() else root.parent).as_posix()
    except ValueError:
        return path.name


def _detect_code_language(path: Path, language_hint: str) -> str:
    normalized = language_hint.strip().lower().replace("-", "_")
    aliases = {
        "py": "python",
        "python": "python",
        "html": "html",
        "htm": "html",
        "js": "javascript",
        "jsx": "javascript",
        "javascript": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "typescript": "typescript",
        "css": "css",
        "scss": "scss",
        "sass": "scss",
        "less": "less",
        "vue": "vue",
        "svelte": "svelte",
        "json": "json",
        "jsonc": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "md": "markdown",
        "markdown": "markdown",
    }
    if normalized in aliases:
        return aliases[normalized]
    suffix = path.suffix.lower().lstrip(".")
    return aliases.get(suffix, suffix or "unknown")


def _python_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    tree = ast.parse(text)
    lines = text.splitlines()
    symbols: list[dict[str, Any]] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_python_symbol_dict(item.name, "function", item, lines))
        elif isinstance(item, ast.ClassDef):
            symbols.append(_python_symbol_dict(item.name, "class", item, lines))
            for child in item.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(_python_symbol_dict(f"{item.name}.{child.name}", "method", child, lines))
        if len(symbols) >= max_symbols:
            break
    return sorted(symbols, key=lambda symbol: (symbol["startLine"], symbol["name"]))[:max_symbols]


def _python_symbol_dict(name: str, kind: str, node: Any, lines: list[str]) -> dict[str, Any]:
    start = int(getattr(node, "lineno", 1) or 1)
    end = int(getattr(node, "end_lineno", start) or start)
    preview = lines[start - 1].strip() if 0 <= start - 1 < len(lines) else name
    return {"name": name, "kind": kind, "startLine": start, "endLine": end, "preview": preview}


class HtmlSymbolParser(HTMLParser):
    def __init__(self, max_symbols: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_symbols = max_symbols
        self.symbols: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.symbols) >= self.max_symbols:
            return
        attr = {key: value or "" for key, value in attrs}
        line, _column = self.getpos()
        name_parts = [tag]
        if attr.get("id"):
            name_parts.append(f"#{attr['id']}")
        if attr.get("class"):
            classes = ".".join(part for part in attr["class"].split() if part)
            if classes:
                name_parts.append(f".{classes}")
        preview_attrs = " ".join(f'{key}="{value}"' for key, value in attr.items() if key in {"id", "class", "name", "src", "href"} and value)
        self.symbols.append(
            {
                "name": "".join(name_parts),
                "kind": "tag",
                "startLine": line,
                "endLine": line,
                "preview": f"<{tag}{(' ' + preview_attrs) if preview_attrs else ''}>",
            }
        )


def _html_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    parser = HtmlSymbolParser(max_symbols)
    parser.feed(text)
    parser.close()
    return parser.symbols[:max_symbols]


def _javascript_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    patterns = [
        ("class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
        ("function", re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
        ("function", re.compile(r"\b([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?function\s*\(")),
    ]
    symbols: list[dict[str, Any]] = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            symbols.append({"name": match.group(1), "kind": kind, "startLine": line_no, "endLine": line_no, "preview": line.strip()})
            break
        if len(symbols) >= max_symbols:
            break
    return symbols


def _css_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    pending: list[str] = []
    start_line = 1
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("/*", "*", "@")):
            continue
        if "{" in stripped:
            before = stripped.split("{", 1)[0].strip() or " ".join(pending).strip()
            pending = []
            if before:
                symbols.append({"name": before, "kind": "css_rule", "startLine": start_line, "endLine": line_no, "preview": before + " {"})
        elif not pending:
            pending = [stripped]
            start_line = line_no
        else:
            pending.append(stripped)
        if len(symbols) >= max_symbols:
            break
    return symbols


def _clip_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _best_effort_html_lines(source: str, fragment: str, start_offset: int) -> tuple[int | None, int | None, int]:
    if not fragment:
        return None, None, start_offset
    index = source.find(fragment, start_offset)
    if index < 0:
        index = source.find(fragment)
    if index < 0:
        return None, None, start_offset
    start_line = source.count("\n", 0, index) + 1
    end_line = start_line + fragment.count("\n")
    return start_line, end_line, index + len(fragment)


def _strip_css_comments_preserve_lines(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        return "".join("\n" if char == "\n" else " " for char in value)

    return re.sub(r"/\*.*?\*/", replace, text, flags=re.DOTALL)


def _parse_css_rules(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if re.search(r"@[A-Za-z-]+\s+[^{]*{[^{}]*{", text, re.DOTALL):
        warnings.append("检测到可能的嵌套 at-rule，CSS 解析按普通规则 best-effort 处理。")
    clean = _strip_css_comments_preserve_lines(text)
    rules: list[dict[str, Any]] = []
    for match in re.finditer(r"(?s)([^{}]+)\{([^{}]*)\}", clean):
        selector_text = match.group(1).strip()
        body = match.group(2).strip()
        if not selector_text or not body or selector_text.startswith("@"):
            continue
        selectors = [part.strip() for part in selector_text.split(",") if part.strip()]
        declarations: dict[str, str] = {}
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            name = name.strip()
            if not name:
                continue
            declarations[name] = value.strip()
        if not declarations:
            continue
        selector_start = match.start(1) + (len(match.group(1)) - len(match.group(1).lstrip()))
        start_line = clean.count("\n", 0, selector_start) + 1
        end_line = clean.count("\n", 0, match.end()) + 1
        css = text[selector_start : match.end()].strip()
        rules.append(
            {
                "selector": selector_text,
                "selectors": selectors,
                "declarations": declarations,
                "startLine": start_line,
                "endLine": end_line,
                "css": css,
            }
        )
    return rules, warnings


def _normalize_css_selector(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _assert_network_allowed(url: str, runtime: dict[str, Any], extra_allowed_hosts: set[str] | None = None) -> None:
    if runtime.get("networkEnabled") is False:
        raise RuntimeError("当前运行环境已关闭网络访问。")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("只允许访问 http/https URL。")
    host = parsed.hostname or ""
    if runtime.get("allowAllHosts") is True:
        return
    allowed_hosts = {item.lower() for item in _json_string_list(runtime.get("allowedHostsJson"))}
    allowed_hosts.update(item.lower() for item in (extra_allowed_hosts or set()))
    if allowed_hosts and not _host_allowed(host, allowed_hosts):
        raise RuntimeError(f"当前运行环境不允许访问域名：{host}")


def _host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    normalized = host.lower()
    for allowed in allowed_hosts:
        if not allowed:
            continue
        if allowed.startswith("*.") and normalized.endswith(allowed[1:]):
            return True
        if normalized == allowed:
            return True
    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _runtime_max_file_bytes(runtime: dict[str, Any]) -> int:
    return min(_positive_int(runtime.get("maxFileBytes"), 1_048_576), 16 * 1024 * 1024)


def _runtime_max_http_bytes(runtime: dict[str, Any]) -> int:
    return min(_positive_int(runtime.get("maxHttpBytes"), 262_144), 4 * 1024 * 1024)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _invoke_python_tool(metadata: dict[str, Any], args: dict[str, Any]) -> Any:
    source_path = str(metadata.get("sourcePath") or "").strip()
    function_name = str(metadata.get("function") or "").strip()
    if not source_path or not function_name:
        raise RuntimeError("Python Tool 缺少 sourcePath 或 function 元数据。")
    path = Path(source_path).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    if not path.is_file():
        raise RuntimeError(f"Python Tool 文件不存在：{path}")
    module_name = f"graphic_tool_{abs(hash(path))}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Python Tool 文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, function_name, None)
    if function is None:
        raise RuntimeError(f"Python Tool 函数不存在：{function_name}")
    if hasattr(function, "invoke") and callable(function.invoke):
        result = function.invoke(args)
    elif callable(function):
        result = function(**args)
    else:
        raise RuntimeError(f"Python Tool 不可调用：{function_name}")
    if inspect.isawaitable(result):
        result = _run_awaitable(result)
    return result


def _run_awaitable(value: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(value)
    finally:
        loop.close()


def _compact_tool_result(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) or len(value) <= TOOL_OBSERVATION_STRING_LIMIT else value[:TOOL_OBSERVATION_STRING_LIMIT] + "...[truncated]"
    try:
        json.dumps(value, ensure_ascii=False)
        return _compact_value(value, string_limit=TOOL_OBSERVATION_STRING_LIMIT, list_limit=20)
    except TypeError:
        return str(value)


def _find_selected_tool(selected_tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    normalized = name.strip().lower()
    if not normalized:
        return None
    for tool in selected_tools:
        candidates = {str(tool.get("id") or "").lower(), str(tool.get("name") or "").lower()}
        if normalized in candidates:
            return tool
    return None


def _fresh_builtin_tool_config(tool: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    schema = _parse_json_object(str(tool.get("schemaJson") or tool.get("tool_schema") or "{}"))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    source = str(tool.get("source") or "").strip().lower()
    builtin_id = str(metadata.get("builtinId") or "").strip()
    candidate_ids: list[str] = []
    existing_id = str(tool.get("id") or "").strip()
    if existing_id:
        candidate_ids.append(existing_id)
    if builtin_id:
        candidate_ids.append(f"builtin_{builtin_id}")
    if source == "builtin" or metadata.get("kind") == "builtin_tool" or builtin_id:
        for candidate_id in candidate_ids:
            fresh = builtin_tool_config_by_id(candidate_id)
            if fresh:
                return fresh
    return None


def _selected_tool_configs(config: dict[str, Any], tools: ToolRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = _json_string_list(config.get("toolIdsJson"))
    snapshot_tools = _json_object_list(config.get("toolRegistryJson"))
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
        result.append(_fresh_builtin_tool_config(tool) or tool)
    return result


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return _flatten_json_object_list(value)
    if isinstance(value, dict):
        return [value]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    return _flatten_json_object_list(parsed) if isinstance(parsed, list) else []


def _flatten_json_object_list(value: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, list):
            result.extend(_flatten_json_object_list(item))
    return result


def _declared_output_fields_for_node(node: NodeIR) -> list[tuple[str, str]]:
    config = node.config
    if node.type == NodeType.VARIABLE_ASSIGN:
        fields = [(str(config.get("resultField") or "assignment_result"), "dict")]
        for assignment in _json_object_list(config.get("assignmentsJson")):
            target = str(assignment.get("target") or assignment.get("field") or assignment.get("name") or "").strip()
            if target:
                fields.append((target, "Any"))
        return fields
    if node.type == NodeType.TEMPLATE:
        return [(str(config.get("outputField") or "template_result"), "dict" if str(config.get("outputType") or "text") == "json" else "str")]
    if node.type == NodeType.JSON_EXTRACTOR:
        return [
            (str(config.get("outputField") or "extracted_json"), "dict"),
            (str(config.get("validationField") or "validation_result"), "dict"),
            (str(config.get("repairResultField") or "repair_result"), "dict"),
        ]
    if node.type == NodeType.JSON_VALIDATOR:
        return [
            (str(config.get("outputField") or "validated_json"), "dict"),
            (str(config.get("validationField") or "validation_result"), "dict"),
            (str(config.get("repairResultField") or "repair_result"), "dict"),
        ]
    output_field = str(config.get("outputField") or "").strip()
    return [(output_field, "Any")] if output_field else []


def _collect_value_paths(value: Any, prefix: str = "", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    result: list[dict[str, Any]] = []
    if prefix:
        result.append({"path": prefix, "type": _value_type_name(value), "label": prefix, "value": _compact_value(value)})
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            result.extend(_collect_value_paths(child, child_path, depth + 1))
    elif isinstance(value, list):
        if value:
            result.extend(_collect_value_paths(value[0], f"{prefix}.0" if prefix else "0", depth + 1))
            if prefix:
                wildcard_base = f"{prefix}[]"
                result.append({"path": wildcard_base, "type": "list", "label": wildcard_base, "value": _compact_value(value)})
                sample = value[0]
                if isinstance(sample, dict):
                    for key, child in sample.items():
                        result.extend(_collect_value_paths(child, f"{wildcard_base}.{key}", depth + 1))
                else:
                    result.extend(_collect_value_paths(sample, wildcard_base, depth + 1))
    return result


def _value_type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "None"
    return "str"


def _resolve_input_mappings(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mapping in _json_object_list(config.get("inputMappingsJson")):
        name = str(mapping.get("name") or "").strip()
        if not name:
            continue
        result[name] = _resolve_mapping_entry(mapping, state)
    return result


def _resolve_mapping_entry(mapping: dict[str, Any], state: dict[str, Any]) -> Any:
    source_type = str(mapping.get("sourceType") or mapping.get("source_type") or "state").strip().lower()
    source = str(mapping.get("source") or "")
    value_type = str(mapping.get("valueType") or mapping.get("value_type") or "auto")
    transform = str(mapping.get("transform") or "none").strip().lower()
    transform_args = _render_transform_args(mapping.get("transformArgsJson") or mapping.get("transform_args_json"), state)
    return _resolve_mapping_value(source_type, source, value_type, state, transform, transform_args)


def _resolve_mapping_value(
    source_type: str,
    source: str,
    value_type: str,
    state: dict[str, Any],
    transform: str = "none",
    transform_args: dict[str, Any] | None = None,
) -> Any:
    if source_type == "state":
        value = _get_path(state, source)
    elif source_type == "literal":
        value = source
    elif source_type == "json":
        rendered = render_template(source, state)
        try:
            value = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"输入映射 JSON 解析失败：{exc}") from exc
    else:
        value = render_template(source, state)
    value = _apply_mapping_transform(value, transform, transform_args or {}, state)
    return _coerce_mapped_value(value, value_type)


def _render_transform_args(value: Any, state: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    rendered = render_template(text, state)
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Transform 参数 JSON 解析失败：{exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Transform 参数必须是 JSON object。")
    return parsed


def _apply_mapping_transform(value: Any, transform: str, args: dict[str, Any], state: dict[str, Any]) -> Any:
    kind = str(transform or "none").strip().lower()
    if kind in {"", "none"}:
        return value
    if kind == "default":
        return _resolve_transform_value(args.get("value", args.get("default")), state) if _is_empty_value(value) else value
    if kind == "coalesce":
        candidates = [value]
        raw_candidates = args.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raw_candidates = [raw_candidates]
        candidates.extend(_resolve_transform_value(candidate, state) for candidate in raw_candidates)
        for candidate in candidates:
            if not _is_empty_value(candidate):
                return candidate
        return None
    if kind == "split":
        separator = str(args.get("separator", "\n"))
        text = _state_value_to_text(value)
        parts = text.split(separator) if separator else list(text)
        if _truthy(args.get("trim", True)):
            parts = [part.strip() for part in parts]
        if _truthy(args.get("dropEmpty", args.get("drop_empty", True))):
            parts = [part for part in parts if part != ""]
        return parts
    if kind == "join":
        separator = str(args.get("separator", "\n"))
        values = value if isinstance(value, list) else ([] if value is None else [value])
        return separator.join(_state_value_to_text(item) for item in values)
    if kind == "pick":
        paths = _normalize_string_list(args.get("paths") or args.get("fields"))
        return _pick_paths(value, paths)
    if kind == "omit":
        paths = _normalize_string_list(args.get("paths") or args.get("fields"))
        return _omit_paths(value, paths)
    raise RuntimeError(f"不支持的 Transform：{transform}")


def _resolve_transform_value(value: Any, state: dict[str, Any]) -> Any:
    if isinstance(value, dict) and ("sourceType" in value or "source" in value):
        return _resolve_mapping_entry(value, state)
    if isinstance(value, str):
        return render_template(value, state)
    return value


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _coerce_mapped_value(value: Any, value_type: str) -> Any:
    kind = str(value_type or "auto").strip().lower()
    if kind in {"", "auto", "any"}:
        return value
    if kind == "string":
        return _state_value_to_text(value)
    if kind == "number":
        return float(value)
    if kind == "integer":
        return int(value)
    if kind == "boolean":
        return _truthy(value)
    if kind == "json":
        if isinstance(value, (dict, list)):
            return value
        return json.loads(str(value or "null"))
    return value


_MISSING = object()


def _get_path(value: Any, path: str, default: Any = None) -> Any:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return value
    resolved = _get_path_parts(value, parts)
    return default if resolved is _MISSING else resolved


def _get_path_parts(value: Any, parts: list[str]) -> Any:
    if not parts:
        return value
    part = parts[0]
    if part.endswith("[]"):
        key = part[:-2]
        collection = _get_path_part(value, key) if key else value
        if not isinstance(collection, list):
            return []
        values: list[Any] = []
        for item in collection:
            child = _get_path_parts(item, parts[1:])
            if child is _MISSING:
                continue
            if isinstance(child, list):
                values.extend(child)
            else:
                values.append(child)
        return values
    next_value = _get_path_part(value, part)
    if next_value is _MISSING:
        return _MISSING
    return _get_path_parts(next_value, parts[1:])


def _get_path_part(value: Any, part: str) -> Any:
    if part == "":
        return value
    if isinstance(value, dict):
        return value.get(part, _MISSING)
    if isinstance(value, list) and part.isdigit():
        index = int(part)
        return value[index] if 0 <= index < len(value) else _MISSING
    return _MISSING


def _set_path(target: dict[str, Any], path: str, value: Any, base: dict[str, Any] | None = None) -> None:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return
    if any(part.endswith("[]") for part in parts):
        raise RuntimeError(f"写入路径不支持数组通配：{path}")
    if len(parts) == 1:
        target[parts[0]] = value
        return
    first = parts[0]
    if first not in target:
        existing = (base or {}).get(first)
        target[first] = dict(existing) if isinstance(existing, dict) else {}
    current = target[first]
    if not isinstance(current, dict):
        current = {}
        target[first] = current
    for part in parts[1:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _pick_paths(value: Any, paths: list[str]) -> Any:
    if not paths:
        return value
    result: dict[str, Any] = {}
    for path in paths:
        picked = _get_path(value, path, _MISSING)
        if picked is _MISSING:
            continue
        _set_path(result, path.replace("[].", "."), picked)
    return result


def _omit_paths(value: Any, paths: list[str]) -> Any:
    try:
        result = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return value
    for path in paths:
        _delete_path(result, path)
    return result


def _delete_path(value: Any, path: str) -> None:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return
    current = value
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return
    leaf = parts[-1]
    if isinstance(current, dict):
        current.pop(leaf, None)
    elif isinstance(current, list) and leaf.isdigit():
        index = int(leaf)
        if 0 <= index < len(current):
            current.pop(index)


def _json_schema_from_config(config: dict[str, Any]) -> dict[str, Any]:
    preset = str(config.get("schemaPreset") or "").strip()
    if preset == "task_plan_v1":
        return _task_plan_json_schema()
    return _json_schema_from_fields(config.get("schemaFieldsJson"))


def _task_plan_json_schema() -> dict[str, Any]:
    task_item = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "可选任务 ID；不填时自动生成 task_1、task_2。"},
            "title": {"type": "string", "description": "任务标题，简短可扫描。"},
            "goal": {"type": "string", "description": "Worker 需要完成的具体目标。"},
            "description": {"type": "string", "description": "goal 的别名；仅在 goal 为空时使用。"},
            "targetFiles": {"type": "array", "items": {"type": "string"}, "description": "建议优先读取的文件路径。"},
            "suggestedTools": {"type": "array", "items": {"type": "string"}, "description": "建议 Worker 使用的工具名。"},
        },
        "anyOf": [{"required": ["title"]}, {"required": ["goal"]}],
        "additionalProperties": True,
    }
    return {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": task_item,
                "description": "Task Splitter 可直接解析的任务数组。",
            }
        },
        "required": ["tasks"],
        "additionalProperties": True,
        "x-graphic-preset": "task_plan_v1",
    }


def _json_schema_from_fields(value: Any) -> dict[str, Any]:
    fields = _json_object_list(value)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        schema = _json_schema_for_field(field)
        properties[name] = schema
        if _truthy(field.get("required")):
            required.append(name)
    schema = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    return schema


def _json_schema_for_field(field: dict[str, Any]) -> dict[str, Any]:
    field_type = str(field.get("type") or "string").strip().lower()
    if field_type not in {"string", "number", "integer", "boolean", "object", "array"}:
        field_type = "string"
    schema: dict[str, Any] = {"type": field_type}
    description = str(field.get("description") or "").strip()
    if description:
        schema["description"] = description
    enum_values = _enum_values(field.get("enumValues") or field.get("enum_values"))
    if enum_values:
        schema["enum"] = enum_values
    default_value = _field_default_value(field.get("defaultValue"))
    if default_value is not None:
        schema["default"] = default_value
    if field_type == "object":
        children = _json_object_list(field.get("children") or field.get("fields"))
        child_schema = _json_schema_from_fields(children)
        schema["properties"] = child_schema.get("properties", {})
        if child_schema.get("required"):
            schema["required"] = child_schema["required"]
        schema["additionalProperties"] = True
    if field_type == "array":
        item_type = str(field.get("itemType") or field.get("item_type") or "").strip().lower()
        item_fields = _json_object_list(field.get("itemFields") or field.get("item_fields"))
        if item_fields:
            item_schema = _json_schema_from_fields(item_fields)
            schema["items"] = item_schema
        elif item_type in {"string", "number", "integer", "boolean", "object", "array"}:
            schema["items"] = {"type": item_type}
        else:
            schema["items"] = {}
    return schema


def _enum_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，\n;；]+", text) if item.strip()]


def _field_default_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _validation_result(value: Any, schema: dict[str, Any]) -> dict[str, Any]:
    errors = _validate_json_value(value, schema, "$")
    return {
        "valid": not errors,
        "errors": errors,
        "schema": schema,
        "output": value,
    }


def _validate_json_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = str(schema.get("type") or "object")
    if not _json_type_matches(value, expected_type):
        return [f"{path} expected {expected_type}, got {type(value).__name__}"]
    if "enum" in schema and isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']}")
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        if not any(_schema_condition_matches(value, item) for item in any_of if isinstance(item, dict)):
            errors.append(f"{path} must satisfy at least one anyOf condition")
    if expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and item_schema:
            for index, item in enumerate(value):
                errors.extend(_validate_json_value(item, item_schema, f"{path}[{index}]"))
        return errors
    if expected_type != "object" or not isinstance(value, dict):
        return errors
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = {str(item) for item in schema.get("required", []) if str(item)}
    for key in sorted(required):
        if key not in value or value.get(key) is None:
            errors.append(f"{path}.{key} is required")
    for key, property_schema in properties.items():
        if key not in value or value.get(key) is None:
            continue
        if isinstance(property_schema, dict):
            errors.extend(_validate_json_value(value.get(key), property_schema, f"{path}.{key}"))
    return errors


def _schema_condition_matches(value: Any, schema: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    required = {str(item) for item in schema.get("required", []) if str(item)}
    for key in required:
        if key not in value or value.get(key) in (None, ""):
            return False
    if schema.get("properties") or schema.get("type"):
        return not _validate_json_value(value, {**schema, "anyOf": []}, "$")
    return True


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _sample_json_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    result: dict[str, Any] = {}
    for key, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            result[key] = ""
            continue
        result[key] = _sample_value_from_schema(field_schema)
    return result


def _sample_value_from_schema(schema: dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    field_type = str(schema.get("type") or "string")
    if field_type == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return [_sample_value_from_schema(item_schema)] if item_schema else []
    if field_type == "object":
        return _sample_json_from_schema(schema)
    if field_type == "boolean":
        return False
    if field_type in {"number", "integer"}:
        return 0
    return ""


def _json_extractor_system_prompt(config: dict[str, Any], schema: dict[str, Any]) -> str:
    instruction = str(config.get("instruction") or "").strip()
    prompt = (
        "你是 JSON Extractor。请严格根据 JSON Schema 从用户输入中抽取一个 JSON object。"
        "只输出 JSON object，不要输出 Markdown 或解释。缺失且非必填的字段可以省略。"
    )
    if instruction:
        prompt += "\n\n抽取说明：\n" + instruction
    prompt += "\n\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False, indent=2)
    return prompt


def _repair_json_output(
    config: dict[str, Any],
    value: Any,
    schema: dict[str, Any],
    errors: list[str],
    source_text: str,
    provider: str,
    model: str,
    runtime_config: ModelRuntimeConfig,
    raw_content: str = "",
) -> dict[str, Any]:
    instruction = str(config.get("repairInstruction") or "").strip()
    system_prompt = (
        "你是 JSON Repair。请把候选内容修复为严格符合 JSON Schema 的 JSON object。"
        "只输出 JSON object，不要输出 Markdown 或解释。不要编造与输入无关的信息。"
    )
    if instruction:
        system_prompt += "\n\n修复说明：\n" + instruction
    system_prompt += "\n\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False, indent=2)
    payload = {
        "validationErrors": errors,
        "candidate": value,
        "rawContent": raw_content,
        "sourceText": source_text,
    }
    response = _call_chat_model(
        provider,
        model,
        [
            ("system", system_prompt),
            ("user", "请修复以下 JSON 候选内容：\n" + json.dumps(payload, ensure_ascii=False, default=str, indent=2)),
        ],
        runtime_config,
    )
    response_content = getattr(response, "content", str(response))
    result: dict[str, Any] = {
        "attempted": True,
        "ok": False,
        "errors": list(errors),
        "before": _compact_value(value),
        "raw": _compact_value(response_content),
    }
    try:
        repaired = _parse_json_object_from_text(response_content)
    except RuntimeError as exc:
        result["errors"] = [*list(errors), str(exc)]
        return result
    validation = _validation_result(repaired, schema)
    result.update(
        {
            "ok": validation["valid"],
            "output": repaired,
            "validation": validation,
            "after": _compact_value(repaired),
        }
    )
    if not validation["valid"]:
        result["errors"] = validation["errors"]
    return result


def _parse_json_object_from_text(content: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(content or "").strip()
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
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    if fallback is not None:
        return fallback
    raise RuntimeError("模型响应不是合法 JSON object。")


def _tool_configs_by_id(project: ProjectIR) -> ToolRuntimeConfig:
    result: ToolRuntimeConfig = {}
    for tool in _workspace_tool_dicts():
        _register_tool_config(result, tool)
    for tool in getattr(project, "tools", []) or []:
        _register_tool_config(result, _model_to_tool_dict(tool))
    for node in project.nodes:
        for tool in _json_object_list(node.config.get("toolRegistryJson")):
            _register_tool_config(result, tool)
    return result


def _mcp_configs_by_id(project: ProjectIR) -> McpRuntimeConfig:
    result: McpRuntimeConfig = {}
    for server in _workspace_mcp_dicts():
        _register_mcp_config(result, server)
    for server in getattr(project, "mcpServers", []) or []:
        _register_mcp_config(result, _model_to_mcp_dict(server))
    for node in project.nodes:
        for server in _json_object_list(node.config.get("mcpServerRegistryJson")):
            _register_mcp_config(result, server)
        for server in _json_object_list(node.config.get("mcpServerSnapshotJson")):
            _register_mcp_config(result, server)
    return result


def _agent_configs_by_id(project: ProjectIR) -> AgentRuntimeConfig:
    result: AgentRuntimeConfig = {}
    for agent in getattr(project, "importedAgents", []) or []:
        _register_agent_config(result, _model_to_agent_dict(agent))
    for node in project.nodes:
        for agent in _json_object_list(node.config.get("agentRegistryJson")):
            _register_agent_config(result, agent)
    return result


def _model_to_agent_dict(agent: Any) -> dict[str, Any]:
    if isinstance(agent, dict):
        return dict(agent)
    if hasattr(agent, "model_dump"):
        return agent.model_dump(by_alias=True)
    return {
        "id": str(getattr(agent, "id", "") or ""),
        "name": str(getattr(agent, "name", "") or "导入的 Agent"),
        "projectId": str(getattr(agent, "project_id", "") or ""),
        "role": str(getattr(agent, "role", "") or "sub_agent"),
        "description": str(getattr(agent, "description", "") or ""),
    }


def _register_agent_config(registry: AgentRuntimeConfig, agent: dict[str, Any]) -> None:
    if not isinstance(agent, dict):
        return
    agent_id = str(agent.get("id") or "").strip()
    project_id = str(agent.get("projectId") or agent.get("project_id") or "").strip()
    name = str(agent.get("name") or "").strip()
    if not agent_id and project_id:
        agent_id = project_id
        agent["id"] = agent_id
    if agent_id:
        registry[agent_id] = agent
    if project_id and project_id not in registry:
        registry[project_id] = agent
    if name and name not in registry:
        registry[name] = agent


def _workspace_mcp_dicts() -> list[dict[str, Any]]:
    if not WORKSPACE_MCP_FILE.exists():
        return []
    try:
        data = json.loads(WORKSPACE_MCP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _flatten_json_object_list(data) if isinstance(data, list) else []


def _model_to_mcp_dict(server: Any) -> dict[str, Any]:
    if isinstance(server, dict):
        return server
    if isinstance(server, list):
        return {}
    if hasattr(server, "model_dump"):
        return server.model_dump(by_alias=True)
    return {
        "id": str(getattr(server, "id", "") or ""),
        "name": str(getattr(server, "name", "") or ""),
        "transport": str(getattr(server, "transport", "") or "stdio"),
        "command": str(getattr(server, "command", "") or ""),
        "argsJson": str(getattr(server, "args_json", "") or "[]"),
        "envJson": str(getattr(server, "env_json", "") or "{}"),
        "envVarsJson": str(getattr(server, "env_vars_json", "") or "[]"),
        "cwd": str(getattr(server, "cwd", "") or ""),
        "url": str(getattr(server, "url", "") or ""),
        "apiKey": str(getattr(server, "api_key", "") or ""),
        "apiKeyEnv": str(getattr(server, "api_key_env", "") or ""),
        "apiKeyMode": str(getattr(server, "api_key_mode", "") or "env"),
        "apiKeyHeader": str(getattr(server, "api_key_header", "") or "Authorization"),
        "apiKeyPrefix": str(getattr(server, "api_key_prefix", "") or "Bearer"),
        "bearerTokenEnvVar": str(getattr(server, "bearer_token_env_var", "") or ""),
        "httpHeadersJson": str(getattr(server, "http_headers_json", "") or "{}"),
        "envHttpHeadersJson": str(getattr(server, "env_http_headers_json", "") or "{}"),
        "enabled": getattr(server, "enabled", True) is not False,
        "startupTimeoutSec": int(getattr(server, "startup_timeout_sec", 10) or 10),
        "toolTimeoutSec": int(getattr(server, "tool_timeout_sec", 60) or 60),
        "enabledToolsJson": str(getattr(server, "enabled_tools_json", "") or "[]"),
        "disabledToolsJson": str(getattr(server, "disabled_tools_json", "") or "[]"),
        "defaultToolsApprovalMode": str(getattr(server, "default_tools_approval_mode", "") or ""),
        "sourceType": str(getattr(server, "source_type", "") or "manual"),
        "sourcePath": str(getattr(server, "source_path", "") or ""),
        "description": str(getattr(server, "description", "") or ""),
    }


def _register_mcp_config(registry: McpRuntimeConfig, server: dict[str, Any]) -> None:
    if not isinstance(server, dict):
        return
    normalized = normalize_mcp_server_config(server)
    server_id = str(normalized.get("id") or "").strip()
    if server_id:
        registry[server_id] = normalized
    server_name = str(normalized.get("name") or "").strip()
    if server_name and server_name not in registry:
        registry[server_name] = normalized


def _selected_mcp_server_configs(config: dict[str, Any], mcp_servers: McpRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = _json_string_list(config.get("mcpServerIdsJson"))
    snapshots = _json_object_list(config.get("mcpServerRegistryJson"))
    snapshot_by_id = {str(server.get("id") or "").strip(): server for server in snapshots if str(server.get("id") or "").strip()}
    if not selected_ids and snapshots:
        selected_ids = [str(server.get("id") or "").strip() for server in snapshots if str(server.get("id") or "").strip()]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for server_id in selected_ids:
        server = mcp_servers.get(server_id) or snapshot_by_id.get(server_id)
        if not server:
            server = next((item for item in mcp_servers.values() if str(item.get("name") or "") == server_id), None)
        if not server:
            continue
        normalized = normalize_mcp_server_config(server)
        key = str(normalized.get("id") or normalized.get("name") or server_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _selected_agent_configs(config: dict[str, Any], agents: AgentRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = _json_string_list(config.get("agentIdsJson"))
    snapshots = _json_object_list(config.get("agentRegistryJson"))
    snapshot_by_id = {str(agent.get("id") or "").strip(): agent for agent in snapshots if str(agent.get("id") or "").strip()}
    snapshot_by_project = {str(agent.get("projectId") or "").strip(): agent for agent in snapshots if str(agent.get("projectId") or "").strip()}
    if not selected_ids and snapshots:
        selected_ids = [str(agent.get("id") or agent.get("projectId") or "").strip() for agent in snapshots if str(agent.get("id") or agent.get("projectId") or "").strip()]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id in selected_ids:
        agent = agents.get(agent_id) or snapshot_by_id.get(agent_id) or snapshot_by_project.get(agent_id)
        if not agent:
            continue
        key = str(agent.get("projectId") or agent.get("id") or agent_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(agent)
    return result


def _agent_tool_configs(agents: list[dict[str, Any]], project: ProjectIR) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for agent in agents:
        project_id = str(agent.get("projectId") or agent.get("project_id") or "").strip()
        if not project_id or project_id == project.project.id:
            continue
        agent_id = str(agent.get("id") or project_id).strip()
        agent_name = str(agent.get("name") or project_id).strip()
        tool_name = f"agent_{_slugify(agent_id or agent_name)}"
        schema = {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "要交给子 Agent 处理的任务内容。"},
                "statePatch": {"type": "object", "description": "可选，传给子 Agent 的额外 state。"},
            },
            "required": ["input"],
            "x-graphic": {
                "kind": "agent_tool",
                "source": "agent",
                "agentId": agent_id,
                "agentName": agent_name,
                "projectId": project_id,
                "role": str(agent.get("role") or "sub_agent"),
            },
        }
        result.append(
            {
                "id": f"agent::{agent_id}",
                "name": tool_name,
                "description": str(agent.get("description") or f"调用子 Agent：{agent_name}"),
                "source": "agent",
                "schemaJson": json.dumps(schema, ensure_ascii=False),
            }
        )
    return result


def _mcp_server_for_node(config: dict[str, Any], mcp_servers: McpRuntimeConfig) -> dict[str, Any] | None:
    server_id = str(config.get("serverId") or "").strip()
    server = mcp_servers.get(server_id) if server_id else None
    if not server:
        server_name = str(config.get("serverName") or "").strip()
        server = mcp_servers.get(server_name) if server_name else None
    if not server:
        snapshots = _json_object_list(config.get("mcpServerSnapshotJson"))
        server = snapshots[0] if snapshots else None
    if not server:
        server = {
            "id": server_id,
            "name": str(config.get("serverName") or "未命名 MCP"),
            "transport": str(config.get("transport") or "stdio"),
            "command": str(config.get("command") or ""),
            "url": str(config.get("url") or ""),
        }
    normalized = normalize_mcp_server_config(server)
    if not normalized.get("id") and server_id:
        normalized["id"] = server_id
    return normalized


def _mcp_agent_tool_configs(servers: list[dict[str, Any]], runtime_environment: RuntimeEnvironment) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for server in servers:
        for tool in list_mcp_tools(server, runtime_environment, require_enabled=True):
            tools.append(make_mcp_agent_tool_config(server, tool))
    return tools


def _render_json_object(template: str, state: dict[str, Any], field: str) -> dict[str, Any]:
    rendered = render_template(template.strip() or "{}", state)
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{field} 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{field} 必须是 JSON object。")
    return parsed


def _workspace_tool_dicts() -> list[dict[str, Any]]:
    if not WORKSPACE_TOOLS_FILE.exists():
        return []
    try:
        data = json.loads(WORKSPACE_TOOLS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _flatten_json_object_list(data) if isinstance(data, list) else []


def _model_to_tool_dict(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return tool
    if isinstance(tool, list):
        return {}
    if hasattr(tool, "model_dump"):
        return tool.model_dump(by_alias=True)
    return {
        "id": str(getattr(tool, "id", "") or ""),
        "name": str(getattr(tool, "name", "") or ""),
        "description": str(getattr(tool, "description", "") or ""),
        "source": str(getattr(tool, "source", "") or ""),
        "schemaJson": str(getattr(tool, "tool_schema", "") or "{}"),
    }


def _register_tool_config(registry: ToolRuntimeConfig, tool: dict[str, Any]) -> None:
    if not isinstance(tool, dict):
        return
    tool = _fresh_builtin_tool_config(tool) or tool
    tool_id = str(tool.get("id") or "").strip()
    name = str(tool.get("name") or "").strip()
    if not tool_id and not name:
        return
    normalized = {
        "id": tool_id or name,
        "name": name or tool_id,
        "description": str(tool.get("description") or ""),
        "source": str(tool.get("source") or "python"),
        "schemaJson": str(tool.get("schemaJson") or tool.get("tool_schema") or "{}"),
    }
    registry[normalized["id"]] = normalized
    registry[normalized["name"]] = normalized


def _execute_live_retriever(node: NodeIR, state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_context"))
    root = _resolve_path(str(config.get("path", "./knowledge")))
    top_k = _positive_int(config.get("topK", 4), 4)
    query = render_template(str(config.get("query", "{{ state.messages }}")), state)
    if not root.exists():
        return {output_field: ""}, f"知识库目录不存在：{root}"

    if _is_chroma_retriever(config, root):
        return _execute_live_chroma_retriever(config, root, output_field, query, top_k)

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


def _is_chroma_retriever(config: dict[str, Any], root: Path) -> bool:
    source = str(config.get("source", "")).strip().lower()
    source_type = str(config.get("sourceType", "")).strip().lower()
    return source == "vectorstore" or source_type == "vectorstore" or (root / "chroma.sqlite3").exists()


def _execute_live_chroma_retriever(
    config: dict[str, Any],
    root: Path,
    output_field: str,
    query: str,
    top_k: int,
) -> tuple[dict[str, Any], str]:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("后端缺少 chromadb，请安装 requirements-dev.txt 后重试。") from exc

    hints = _chroma_runtime_hints(config, root)
    try:
        client = chromadb.PersistentClient(path=str(root))
        collection_name = _first_config_value(
            config.get("collection"),
            hints.get("collection"),
            hints.get("collectionName"),
            hints.get("COLLECTION_NAME"),
        )
        collection = _get_chroma_collection(client, collection_name)
        collection_name = getattr(collection, "name", collection_name or "default")
        count = int(collection.count())
        if count <= 0:
            return {output_field: ""}, f"Chroma collection {collection_name} 为空。"

        include = ["documents", "metadatas", "distances"]
        n_results = min(top_k, count)
        query_embedding = _build_chroma_query_embedding(config, hints, query)
        if query_embedding:
            result = collection.query(query_embeddings=[query_embedding], n_results=n_results, include=include)
            detail_mode = "query_embeddings"
        else:
            result = collection.query(query_texts=[query], n_results=n_results, include=include)
            detail_mode = "query_texts"
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(_format_chroma_error(exc, bool(_chroma_embedding_model(config, hints)))) from exc

    context_parts = _format_chroma_results(result)
    return {
        output_field: "\n\n---\n\n".join(context_parts),
    }, f"查询 Chroma collection {collection_name}（{count} 条，{detail_mode}），返回 {len(context_parts)} 段到 state.{output_field}"


def _get_chroma_collection(client: Any, collection_name: str) -> Any:
    if collection_name:
        return client.get_collection(name=collection_name)
    collections = client.list_collections()
    if not collections:
        raise RuntimeError("Chroma 目录中没有可用 collection。")
    first = collections[0]
    first_name = getattr(first, "name", str(first))
    return client.get_collection(name=first_name)


def _chroma_runtime_hints(config: dict[str, Any], root: Path) -> dict[str, Any]:
    hints = _parse_json_object(str(config.get("metadataJson", "") or "{}"))
    sidecar = _read_chroma_sidecar_config(root)
    for key, value in sidecar.items():
        hints.setdefault(key, value)
    return hints


def _read_chroma_sidecar_config(root: Path) -> dict[str, Any]:
    candidates = [root / "runtime_config.json", root.parent / "runtime_config.json"]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _build_chroma_query_embedding(config: dict[str, Any], hints: dict[str, Any], query: str) -> list[float] | None:
    model = _chroma_embedding_model(config, hints)
    base_url = _first_config_value(
        hints.get("embeddingBaseUrl"),
        hints.get("embeddingApiBase"),
        hints.get("baseUrl"),
        hints.get("apiBase"),
        hints.get("EMBEDDING_API_BASE"),
    )
    api_key_env = _first_config_value(hints.get("embeddingApiKeyEnv"), hints.get("apiKeyEnv"), hints.get("EMBEDDING_API_KEY_ENV"))
    api_key = _first_config_value(hints.get("embeddingApiKey"), hints.get("apiKey"), hints.get("EMBEDDING_API_KEY"), _read_api_key(api_key_env))
    if not model or not base_url:
        return None
    if not api_key:
        raise RuntimeError("Chroma 查询需要生成 query embedding，但没有可用的 embedding API Key。请在 RAG 元数据 JSON 配置 embeddingApiKeyEnv，或设置 EMBEDDING_API_KEY。")
    return _call_openai_compatible_embedding(model, base_url, api_key, query)


def _chroma_embedding_model(config: dict[str, Any], hints: dict[str, Any]) -> str:
    metadata_model = _first_config_value(hints.get("embeddingModel"))
    if metadata_model:
        return metadata_model
    config_model = _first_config_value(config.get("embeddingModel"))
    sidecar_model = _first_config_value(hints.get("EMBEDDING_MODEL"))
    if config_model and config_model != "bge-m3":
        return config_model
    return sidecar_model or config_model


def _call_openai_compatible_embedding(model: str, base_url: str, api_key: str, query: str) -> list[float]:
    url = base_url.rstrip("/")
    if not url.endswith("/embeddings"):
        url = f"{url}/embeddings"
    payload = json.dumps({"model": model, "input": query}, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Embedding 接口调用失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Embedding 接口返回了无法解析的 JSON。") from exc

    try:
        embedding = body["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Embedding 接口响应缺少 data[0].embedding。") from exc
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Embedding 接口返回的 embedding 为空。")
    return [float(value) for value in embedding]


def _format_chroma_results(result: dict[str, Any]) -> list[str]:
    ids = _first_result_list(result.get("ids"))
    documents = _first_result_list(result.get("documents"))
    metadatas = _first_result_list(result.get("metadatas"))
    distances = _first_result_list(result.get("distances"))
    context_parts: list[str] = []
    for index, document in enumerate(documents):
        text = "" if document is None else str(document)
        metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        source = _metadata_source(metadata) or (str(ids[index]) if index < len(ids) else f"document_{index + 1}")
        distance = distances[index] if index < len(distances) else None
        lines = [f"来源: {source}"]
        if distance is not None:
            lines.append(f"距离: {distance}")
        if metadata:
            lines.append(f"元数据: {json.dumps(metadata, ensure_ascii=False)}")
        lines.append(text[:2400])
        context_parts.append("\n".join(lines))
    return context_parts


def _metadata_source(metadata: dict[str, Any]) -> str:
    for key in ("source", "file", "filename", "path", "url", "title"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _first_result_list(value: Any) -> list[Any]:
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else value


def _parse_json_object(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_config_value(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _format_chroma_error(exc: Exception, has_embedding_model: bool) -> str:
    message = str(exc)
    if "dimension" in message.lower() or "embedding" in message.lower():
        if has_embedding_model:
            return f"Chroma 查询失败：{message}"
        return (
            "Chroma 查询失败：该 collection 可能使用了非默认 embedding 维度。"
            "请在 RAG 配置中填写 Embedding 模型，并在元数据 JSON 配置 embeddingBaseUrl 与 embeddingApiKeyEnv。"
            f"原始错误：{message}"
        )
    return f"Chroma 查询失败：{message}"


def _call_chat_model(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    runtime_config: ModelRuntimeConfig = None,
) -> Any:
    provider_key = _normalize_provider(provider)
    base_url = _runtime_value(runtime_config, "baseUrl", "base_url")
    api_format = _normalize_provider(_runtime_value(runtime_config, "apiFormat", "api_format"))
    api_key_env = _safe_api_key_env(_runtime_value(runtime_config, "apiKeyEnv", "api_key_env"))
    api_key = _runtime_value(runtime_config, "apiKey", "api_key") or _read_api_key(api_key_env)
    organization = _runtime_value(runtime_config, "organization")
    api_version = _runtime_value(runtime_config, "apiVersion", "api_version")

    try:
        if provider_key == "azure_openai":
            return _call_azure_openai(model, messages, base_url, api_key, api_key_env, api_version)
        if api_format == "openai_compatible" or provider_key in OPENAI_COMPATIBLE_PROVIDERS or base_url:
            return _call_openai_compatible(provider_key, model, messages, base_url, api_key, api_key_env, organization)

        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError("后端缺少 LangChain 模型运行依赖，请安装 requirements-dev.txt 后重试。") from exc

    try:
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        chat_model = init_chat_model(model, model_provider=PROVIDER_ALIASES.get(provider_key, provider_key), **kwargs)
        return chat_model.invoke(messages)
    except Exception as exc:
        raise RuntimeError(f"模型调用失败：{exc}") from exc


def _call_openai_compatible(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    base_url: str,
    api_key: str,
    api_key_env: str,
    organization: str,
) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("后端缺少 langchain-openai，请安装 requirements-dev.txt 后重试。") from exc

    resolved_base_url = base_url or OPENAI_COMPATIBLE_BASE_URLS.get(provider, "")
    resolved_api_key = api_key or ("ollama" if provider == "ollama" else "")
    if not resolved_api_key and resolved_base_url and not api_key_env:
        resolved_api_key = "not-needed"
    if not resolved_api_key and api_key_env:
        raise RuntimeError(f"模型配置引用的环境变量 {api_key_env} 未设置。")

    kwargs: dict[str, Any] = {"model": model}
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    if resolved_api_key:
        kwargs["api_key"] = resolved_api_key
    if organization:
        kwargs["organization"] = organization
    chat_model = ChatOpenAI(**kwargs)
    return chat_model.invoke(messages)


def _call_azure_openai(
    model: str,
    messages: list[tuple[str, str]],
    azure_endpoint: str,
    api_key: str,
    api_key_env: str,
    api_version: str,
) -> Any:
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:
        raise RuntimeError("后端缺少 langchain-openai，请安装 requirements-dev.txt 后重试。") from exc

    if not azure_endpoint:
        raise RuntimeError("Azure OpenAI 运行配置需要填写 Base URL/Azure Endpoint。")
    if not api_version:
        raise RuntimeError("Azure OpenAI 运行配置需要填写 API Version。")
    if not api_key and api_key_env:
        raise RuntimeError(f"模型配置引用的环境变量 {api_key_env} 未设置。")

    kwargs: dict[str, Any] = {
        "azure_deployment": model,
        "azure_endpoint": azure_endpoint,
        "api_version": api_version,
    }
    if api_key:
        kwargs["api_key"] = api_key
    chat_model = AzureChatOpenAI(**kwargs)
    return chat_model.invoke(messages)


def _normalize_model_config(config: ModelRuntimeConfig) -> ModelRuntimeConfig:
    if not config:
        return None
    if hasattr(config, "model_dump"):
        config = config.model_dump(by_alias=True)
    if not isinstance(config, dict):
        return None
    if config.get("enabled") is False:
        return None
    return {str(key): value for key, value in config.items() if value is not None}


def _effective_model_config(node_config: dict[str, Any], runtime_config: ModelRuntimeConfig) -> ModelRuntimeConfig:
    base = _normalize_model_config(runtime_config) or {}
    node_fields: dict[str, Any] = {}
    for key in (
        "id",
        "name",
        "provider",
        "model",
        "baseUrl",
        "base_url",
        "apiKey",
        "api_key",
        "apiKeyEnv",
        "api_key_env",
        "apiVersion",
        "api_version",
        "organization",
        "apiFormat",
        "api_format",
    ):
        value = node_config.get(key)
        if value is not None and str(value).strip():
            node_fields[key] = value
    return {**base, **node_fields} if base or node_fields else None


def _runtime_value(config: ModelRuntimeConfig, *keys: str) -> str:
    if not config:
        return ""
    for key in keys:
        value = config.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _resolve_node_model(
    config: dict[str, Any],
    runtime_config: ModelRuntimeConfig,
    default_provider: str,
    default_model: str,
) -> tuple[str, str]:
    node_provider = str(config.get("provider", "")).strip()
    node_model = str(config.get("model", "")).strip()
    runtime_provider = _runtime_value(runtime_config, "provider")
    runtime_model = _runtime_value(runtime_config, "model")
    has_explicit_node_model = bool(config.get("modelConfigId") or config.get("modelConfigName")) or (
        bool(node_model) and node_model != default_model
    )
    if has_explicit_node_model:
        return node_provider or runtime_provider or default_provider, node_model or runtime_model or default_model
    return runtime_provider or node_provider or default_provider, runtime_model or node_model or default_model


def _read_api_key(api_key_env: str) -> str:
    if not api_key_env:
        return ""
    return os.getenv(api_key_env, "").strip()


def _safe_api_key_env(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or "") else ""


def _normalize_provider(provider: str) -> str:
    return provider.strip().lower().replace("-", "_") or "openai"


def render_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        return _state_value_to_text(_get_path(state, match.group(1), ""))

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
    if node.type in {NodeType.JSON_EXTRACTOR, NodeType.JSON_VALIDATOR}:
        validation = state.get(str(config.get("validationField", "validation_result")))
        if isinstance(validation, dict) and validation.get("valid") is True:
            return "valid"
        return "invalid"
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


def _parse_router_scenarios(value: str) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        scenario_id, label, keywords = (line.split(":", 2) + ["", ""])[:3]
        scenario_id = scenario_id.strip()
        if not scenario_id:
            continue
        scenarios.append(
            {
                "id": scenario_id,
                "label": label.strip() or scenario_id,
                "keywords": [item.strip() for item in keywords.split(",") if item.strip()],
            }
        )
    return scenarios


def _router_prompt(instruction: str, text: str, scenarios: list[dict[str, Any]], fallback: str) -> str:
    lines = [instruction.strip() or "请判断输入属于哪个路由场景，只输出 route key。"]
    lines.append("可选场景：")
    for scenario in scenarios:
        lines.append(f"- {scenario['id']}: {scenario.get('label') or scenario['id']}")
    lines.append(f"fallback: {fallback}")
    lines.append("输入：")
    lines.append(text)
    return "\n".join(lines)


def _normalize_route_key(value: str, config: dict[str, Any], fallback: str) -> str:
    allowed = {fallback}
    allowed.update(scenario["id"] for scenario in _parse_router_scenarios(str(config.get("scenarios", ""))))
    text = value.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            text = str(parsed.get("route") or parsed.get("route_key") or parsed.get("key") or "")
    except json.JSONDecodeError:
        pass
    for key in sorted(allowed, key=len, reverse=True):
        if key and key in text:
            return key
    return fallback


def _agent_state_prompt(state: dict[str, Any]) -> str:
    user_text = _state_value_to_text(state.get("messages", ""))
    compact = json.dumps(_compact_state(state), ensure_ascii=False, indent=2)
    return f"用户输入：\n{user_text}\n\n当前流程 state：\n{compact}"


def _render_mock_response(raw: str, state: dict[str, Any]) -> Any:
    rendered = render_template(raw.strip() or "{}", state)
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _bool_config(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _node_runtime_policy(config: dict[str, Any]) -> dict[str, Any]:
    retry = _parse_json_object(str(config.get("retryPolicyJson") or "{}"))
    error_policy = str(config.get("errorPolicy") or "default").strip().lower() or "default"
    if error_policy not in {"default", "fail_fast", "route_error", "continue", "fallback"}:
        error_policy = "default"
    timeout_sec = _optional_positive_float(config.get("nodeTimeoutSec"))
    max_retries = min(_non_negative_int(retry.get("maxRetries"), 0), 5)
    return {
        "retryEnabled": _truthy(retry.get("enabled")) and max_retries > 0,
        "maxRetries": max_retries,
        "backoffMs": min(_non_negative_int(retry.get("backoffMs"), 0), 30_000),
        "retryOnErrorTypes": [str(item).strip() for item in retry.get("retryOnErrorTypes", []) if str(item).strip()] if isinstance(retry.get("retryOnErrorTypes"), list) else [],
        "timeoutSec": timeout_sec,
        "errorPolicy": error_policy,
        "fallbackOutputJson": str(config.get("fallbackOutputJson") or "{}"),
        "errorOutputField": str(config.get("errorOutputField") or "").strip(),
    }


def _should_retry_error(policy: dict[str, Any], error_type: str, exc: Exception) -> bool:
    allowed = set(policy.get("retryOnErrorTypes") or [])
    if not allowed:
        return True
    return error_type in allowed or exc.__class__.__name__ in allowed


def _policy_error_type(exc: Exception) -> str:
    if isinstance(exc, NodeTimeoutError):
        return "timeout"
    if isinstance(exc, NodePolicyError):
        return str(exc.payload.get("errorType") or "node_error")
    return exc.__class__.__name__


def _fallback_policy_delta(node: NodeIR, state: dict[str, Any], policy: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        delta = _render_json_object(str(policy.get("fallbackOutputJson") or "{}"), state, "fallbackOutputJson")
    except RuntimeError as exc:
        raise NodePolicyError(node, exc, _runtime_error_payload(node, exc), [], policy) from exc
    if policy.get("errorOutputField"):
        delta[str(policy["errorOutputField"])] = payload
    return delta


def _successful_policy_trace_meta(node: NodeIR, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    policy = _node_runtime_policy(node.config)
    meta: dict[str, Any] = {}
    if attempts and (len(attempts) > 1 or attempts[0].get("status") != "ok"):
        meta["attempts"] = attempts
    if policy["timeoutSec"]:
        meta["timeoutSec"] = policy["timeoutSec"]
    if policy["errorPolicy"] != "default":
        meta["errorPolicy"] = policy["errorPolicy"]
    if node.type == NodeType.FOR_EACH:
        meta["parallel"] = str(node.config.get("executionMode") or "sequential").strip().lower() == "parallel"
        meta["itemFailurePolicy"] = str(node.config.get("itemFailurePolicy") or "fail_fast").strip().lower()
    return meta


def _data_shaping_trace_meta(node: NodeIR, state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    if node.type not in {NodeType.VARIABLE_ASSIGN, NodeType.TEMPLATE, NodeType.JSON_EXTRACTOR, NodeType.JSON_VALIDATOR}:
        return {}
    config = node.config
    kind = {
        NodeType.VARIABLE_ASSIGN: "variable_assign",
        NodeType.TEMPLATE: "template",
        NodeType.JSON_EXTRACTOR: "json_extractor",
        NodeType.JSON_VALIDATOR: "json_validator",
    }[node.type]
    meta: dict[str, Any] = {
        "kind": kind,
        "inputMappings": _trace_input_mappings(config.get("inputMappingsJson")),
    }
    resolved_inputs = _trace_resolved_inputs(config, state)
    if resolved_inputs:
        meta["resolvedInputs"] = resolved_inputs

    if node.type == NodeType.VARIABLE_ASSIGN:
        result_field = str(config.get("resultField", "assignment_result")).strip() or "assignment_result"
        result = delta.get(result_field)
        meta.update(
            {
                "resultField": result_field,
                "assignments": _trace_assignments(config.get("assignmentsJson")),
                "changedFields": result.get("changedFields", []) if isinstance(result, dict) else [],
            }
        )
    elif node.type == NodeType.TEMPLATE:
        output_field = str(config.get("outputField", "template_result")).strip() or "template_result"
        meta.update(
            {
                "outputField": output_field,
                "outputType": str(config.get("outputType", "text")).strip().lower() or "text",
            }
        )
        if output_field in delta:
            meta["outputPreview"] = _compact_value(delta.get(output_field), string_limit=500, list_limit=5)
    else:
        output_field = str(config.get("outputField") or ("extracted_json" if node.type == NodeType.JSON_EXTRACTOR else "validated_json")).strip()
        validation_field = str(config.get("validationField", "validation_result")).strip() or "validation_result"
        repair_field = str(config.get("repairResultField", "repair_result")).strip() or "repair_result"
        validation = _trace_validation(delta.get(validation_field))
        meta.update(
            {
                "outputField": output_field,
                "validationField": validation_field,
                "repairResultField": repair_field,
                "schemaPreset": str(config.get("schemaPreset") or ""),
                "schemaFieldCount": len(_json_object_list(config.get("schemaFieldsJson"))),
                "repairEnabled": _truthy(config.get("repairEnabled")),
                "validation": validation,
            }
        )
        if validation:
            meta["branch"] = "valid" if validation.get("valid") else "invalid"
        if repair_field in delta:
            meta["repair"] = _trace_repair(delta.get(repair_field))
    return {"dataShaping": meta}


def _trace_input_mappings(value: Any) -> list[dict[str, Any]]:
    mappings = []
    for item in _json_object_list(value):
        mappings.append(
            {
                "name": str(item.get("name") or ""),
                "sourceType": str(item.get("sourceType") or item.get("source_type") or "state"),
                "source": str(item.get("source") or ""),
                "valueType": str(item.get("valueType") or item.get("value_type") or "auto"),
                "transform": str(item.get("transform") or "none"),
            }
        )
    return mappings


def _trace_assignments(value: Any) -> list[dict[str, Any]]:
    assignments = []
    for item in _json_object_list(value):
        assignments.append(
            {
                "target": str(item.get("target") or item.get("field") or item.get("name") or ""),
                "operation": str(item.get("operation") or "overwrite"),
                "sourceType": str(item.get("sourceType") or item.get("source_type") or "template"),
                "source": str(item.get("source") if item.get("source") is not None else item.get("value") or ""),
                "valueType": str(item.get("valueType") or item.get("value_type") or "auto"),
                "transform": str(item.get("transform") or "none"),
            }
        )
    return assignments


def _trace_resolved_inputs(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if not _json_object_list(config.get("inputMappingsJson")):
        return {}
    try:
        return _compact_value(_resolve_input_mappings(config, state), string_limit=500, list_limit=5)
    except Exception:
        return {}


def _trace_validation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "valid": bool(value.get("valid")),
        "errors": _compact_value(value.get("errors") or [], string_limit=500, list_limit=5),
    }


def _trace_repair(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        "ok": bool(value.get("ok")),
        "errors": _compact_value(value.get("errors") or [], string_limit=500, list_limit=5),
    }
    validation = value.get("validation")
    if isinstance(validation, dict):
        result["validation"] = _trace_validation(validation)
    return result


def _failed_policy_trace_meta(node: NodeIR, attempts: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    meta = _successful_policy_trace_meta(node, attempts)
    if attempts:
        meta["attempts"] = attempts
    if policy.get("errorPolicy"):
        meta["errorPolicy"] = policy["errorPolicy"]
    return meta


def _trace_meta_from_exception(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, NodePolicyError):
        return _failed_policy_trace_meta(exc.node, exc.attempts, exc.policy)
    return {}


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


def _fallback_reply_content(state: dict[str, Any]) -> str:
    priority = ("final_answer", "tools_result", "agent_result", "llm_result", "http_response", "retrieved_context")
    for key in priority:
        text = _state_value_to_text(state.get(key)).strip()
        if text:
            return text
    for key in reversed(list(state.keys())):
        if key in priority or key.endswith(("_result", "_answer", "_output")):
            text = _state_value_to_text(state.get(key)).strip()
            if text:
                return text
    return ""


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: _compact_value(value) for key, value in state.items()}


def _compact_value(value: Any, string_limit: int = 1200, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(child, string_limit=string_limit, list_limit=list_limit) for key, child in value.items()}
    if isinstance(value, list):
        return [_compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + "...[truncated]"
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


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _non_negative_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _format_error(exc: Exception) -> str:
    if isinstance(exc, NodePolicyError):
        payload = exc.payload
        return f"{payload.get('errorType')}: {payload.get('message')}"
    if isinstance(exc, LiveRunUnsupportedError):
        return str(exc)
    return f"{exc.__class__.__name__}: {exc}"


def _first_target(edges: list) -> str | None:
    return edges[0].target if edges else None


def _first_execution_target(edges: list) -> str | None:
    executable = [edge for edge in edges if edge.kind not in {EdgeKind.WORKER, EdgeKind.ERROR}]
    return _first_target(executable)


def _next_execution_target(node: NodeIR, nodes: dict[str, NodeIR], outgoing: dict[str, list], state: dict[str, Any]) -> str | None:
    edges = outgoing.get(node.id, [])
    if not edges:
        return None
    conditional_edges = [edge for edge in edges if edge.kind == EdgeKind.CONDITIONAL]
    if conditional_edges:
        handle = _choose_handle(node, state)
        return _target_for_handle(conditional_edges, handle) or _first_target(conditional_edges)
    normal_edges = [edge for edge in edges if edge.kind == EdgeKind.NORMAL]
    if normal_edges:
        if node.type == NodeType.FOR_EACH:
            return _for_each_exit_target(node.id, nodes, outgoing)
        return _first_target(normal_edges)
    if node.type == NodeType.PARALLEL_TOOLS:
        return _parallel_worker_output_target(node.id, nodes, outgoing)
    return None


def _error_execution_target(node: NodeIR, outgoing: dict[str, list]) -> str | None:
    error_edges = [edge for edge in outgoing.get(node.id, []) if edge.kind == EdgeKind.ERROR or edge.sourceHandle == "error"]
    return _target_for_handle(error_edges, "error") or _first_target(error_edges)


def _runtime_error_payload(node: NodeIR, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, NodePolicyError):
        return dict(exc.payload)
    return {
        "ok": False,
        "nodeId": node.id,
        "nodeType": str(node.type),
        "nodeLabel": node.label,
        "errorType": _policy_error_type(exc),
        "message": str(exc),
    }


def _for_each_exit_target(parent_node_id: str, nodes: dict[str, NodeIR], outgoing: dict[str, list]) -> str | None:
    item_target = _target_for_handle([edge for edge in outgoing.get(parent_node_id, []) if edge.kind != EdgeKind.ERROR], "item")
    if not item_target:
        return None
    merge_node = _find_for_each_merge_node(item_target, nodes, outgoing)
    if not merge_node:
        return None
    normal_edges = [edge for edge in outgoing.get(merge_node.id, []) if edge.kind == EdgeKind.NORMAL]
    return _first_target(normal_edges)


def _find_for_each_merge_node(start_node_id: str, nodes: dict[str, NodeIR], outgoing: dict[str, list]) -> NodeIR | None:
    seen: set[str] = set()
    queue: list[str] = [start_node_id]
    while queue:
        node_id = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not node:
            continue
        if node.type == NodeType.MERGE:
            return node
        for edge in outgoing.get(node_id, []):
            if edge.kind == EdgeKind.WORKER:
                continue
            queue.append(edge.target)
    return None


def _parallel_worker_output_target(parent_node_id: str, nodes: dict[str, NodeIR], outgoing: dict[str, list]) -> str | None:
    worker_ids = {
        node.id
        for node in nodes.values()
        if node.type == NodeType.PARALLEL_WORKER and str(node.config.get("parentNodeId") or "") == parent_node_id
    }
    for worker_id in sorted(worker_ids):
        for edge in outgoing.get(worker_id, []):
            if edge.kind == EdgeKind.WORKER and edge.target not in worker_ids:
                return edge.target
    return None


def _target_for_handle(edges: list, handle: str) -> str | None:
    for edge in edges:
        if edge.sourceHandle == handle:
            return edge.target
    return None
