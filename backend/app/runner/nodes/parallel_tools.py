from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.ir.schemas import NodeIR, NodeType

from ..common import compact_state, compact_value, format_error, positive_int, render_template, state_value_to_text, truthy
from ..context import ExecutionContext
from ..model_runtime import effective_model_config, resolve_node_model
from ..nodes.task_splitter import normalize_worker_tasks
from ..tool_runtime.registry import run_tools_agent_session, selected_tool_configs


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    delta, detail, _events = run_parallel_tools_node(ctx, node, state, emit_worker_events=False)
    return delta, detail


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    field = str(config.get("outputField", "worker_results"))
    selected_tools = selected_tool_configs(config, ctx.tools)
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


def execute_events(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return (yield from execute_parallel_tools_events(ctx, node, state))


def _parallel_tools_plan(ctx: ExecutionContext, node: NodeIR, state: dict[str, Any]):
    config = node.config
    tasks_field = str(config.get("tasksField", "worker_tasks")).strip() or "worker_tasks"
    output_field = str(config.get("outputField", "worker_results")).strip() or "worker_results"
    tasks = normalize_worker_tasks(state.get(tasks_field), max_tasks=10, fallback_goal=state_value_to_text(state.get("messages")))
    if not tasks:
        raise RuntimeError(f"Parallel Tools 未能从 state.{tasks_field} 获取任务列表。")
    selected_tools = selected_tool_configs(config, ctx.tools)
    if not selected_tools:
        raise RuntimeError("Parallel Tools 节点没有选择任何已配置 Tool。")

    effective_config = effective_model_config(config, ctx.model_config)
    provider, model = resolve_node_model(config, ctx.model_config, "openai", "gpt-4.1-mini")
    max_iterations = min(positive_int(config.get("maxIterationsPerTask"), 6), 12)
    max_workers = min(positive_int(config.get("maxConcurrentWorkers"), 3), 6, len(tasks))
    store_tool_calls = truthy(config.get("storeToolCalls", False))
    system_prompt = render_template(str(config.get("systemPrompt", "")), state).strip() or "你是代码阅读 Worker，只完成分配给你的子任务。"
    worker_nodes = parallel_worker_nodes(ctx.project, node.id)
    slots = parallel_worker_task_slots(worker_nodes, tasks, max_workers)
    return {
        "outputField": output_field,
        "tasks": tasks,
        "selectedTools": selected_tools,
        "provider": provider,
        "model": model,
        "effectiveModelConfig": effective_config,
        "maxIterations": max_iterations,
        "maxWorkers": max_workers,
        "storeToolCalls": store_tool_calls,
        "systemPrompt": system_prompt,
        "slots": slots,
    }


def _run_parallel_slot(ctx: ExecutionContext, plan: dict[str, Any], state: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    slot_results: list[dict[str, Any]] = []
    try:
        for task_item in slot["tasks"]:
            result = run_parallel_worker_task(
                task_item["task"],
                int(task_item["taskIndex"]),
                state,
                plan["provider"],
                plan["model"],
                plan["effectiveModelConfig"],
                plan["selectedTools"],
                plan["systemPrompt"],
                plan["maxIterations"],
                ctx.runtime_environment,
                plan["storeToolCalls"],
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
                    "error": format_error(exc),
                }
            ],
        }


def execute_parallel_tools_events(ctx: ExecutionContext, node: NodeIR, state: dict[str, Any]):
    plan = _parallel_tools_plan(ctx, node, state)
    slots = plan["slots"]
    child_trace_items: list[dict[str, Any]] = []
    for slot in slots:
        if slot.get("nodeId"):
            yield {
                "event": "node_start",
                "nodeId": slot["nodeId"],
                "type": "parallel_worker",
                "label": slot["label"],
                "inputState": {"tasks": [item["task"] for item in slot["tasks"]]},
            }

    ordered: list[dict[str, Any] | None] = [None] * len(plan["tasks"])
    with ThreadPoolExecutor(max_workers=max(1, min(len(slots), plan["maxWorkers"]))) as executor:
        future_to_slot = {executor.submit(_run_parallel_slot, ctx, plan, state, slot): slot for slot in slots}
        for future in as_completed(future_to_slot):
            slot = future_to_slot[future]
            slot_result = future.result()
            for result in slot_result.get("results") or []:
                task_index = int(result.get("taskIndex", -1))
                if 0 <= task_index < len(ordered):
                    ordered[task_index] = result
            if slot.get("nodeId"):
                event = parallel_worker_end_event(slot, slot_result, state)
                trace_item = event.get("traceItem")
                if isinstance(trace_item, dict):
                    child_trace_items.append(trace_item)
                yield event

    results = [item for item in ordered if isinstance(item, dict)]
    if results and all(item.get("status") == "error" for item in results):
        raise RuntimeError("Parallel Tools 所有 Worker 均执行失败。")
    return {plan["outputField"]: results}, f"Parallel Tools 并行执行 {len(slots)} 个 Worker 槽位，完成 {len(results)} 个任务，输出到 state.{plan['outputField']}", child_trace_items


def run_parallel_tools_node(ctx: ExecutionContext, node: NodeIR, state: dict[str, Any], emit_worker_events: bool):
    plan = _parallel_tools_plan(ctx, node, state)
    events: list[dict[str, Any]] = []
    slots = plan["slots"]
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

    ordered: list[dict[str, Any] | None] = [None] * len(plan["tasks"])
    with ThreadPoolExecutor(max_workers=max(1, min(len(slots), plan["maxWorkers"]))) as executor:
        future_to_slot = {executor.submit(_run_parallel_slot, ctx, plan, state, slot): slot for slot in slots}
        for future in as_completed(future_to_slot):
            slot = future_to_slot[future]
            slot_result = future.result()
            for result in slot_result.get("results") or []:
                task_index = int(result.get("taskIndex", -1))
                if 0 <= task_index < len(ordered):
                    ordered[task_index] = result
            if emit_worker_events and slot.get("nodeId"):
                events.append(parallel_worker_end_event(slot, slot_result, state))

    results = [item for item in ordered if isinstance(item, dict)]
    if results and all(item.get("status") == "error" for item in results):
        raise RuntimeError("Parallel Tools 所有 Worker 均执行失败。")
    return {plan["outputField"]: results}, f"Parallel Tools 并行执行 {len(slots)} 个 Worker 槽位，完成 {len(results)} 个任务，输出到 state.{plan['outputField']}", events


def parallel_worker_nodes(project: Any, parent_node_id: str) -> list[NodeIR]:
    return sorted(
        [
            node
            for node in project.nodes
            if node.type == NodeType.PARALLEL_WORKER and str(node.config.get("parentNodeId") or "") == parent_node_id
        ],
        key=lambda item: (int(item.config.get("workerIndex") or 0), item.id),
    )


def parallel_worker_task_slots(worker_nodes: list[NodeIR], tasks: list[dict[str, Any]], fallback_worker_count: int) -> list[dict[str, Any]]:
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


def run_parallel_worker_task(
    task: dict[str, Any],
    task_index: int,
    state: dict[str, Any],
    provider: str,
    model: str,
    effective_model_config: dict[str, Any] | None,
    selected_tools: list[dict[str, Any]],
    system_prompt: str,
    max_iterations: int,
    runtime_environment: dict[str, Any] | None,
    store_tool_calls: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        final_answer, calls = run_tools_agent_session(
            provider,
            model,
            effective_model_config,
            selected_tools,
            parallel_worker_system_prompt(system_prompt),
            parallel_worker_user_prompt(state, task),
            max_iterations,
            runtime_environment,
        )
        result = normalize_worker_final_answer(task, final_answer)
        result["durationMs"] = round((time.perf_counter() - started) * 1000, 2)
        result["taskIndex"] = task_index
        if store_tool_calls:
            result["toolCalls"] = compact_value(calls, string_limit=3000, list_limit=12)
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
            "error": format_error(exc),
        }


def parallel_worker_end_event(slot: dict[str, Any], slot_result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    results = slot_result.get("results") if isinstance(slot_result.get("results"), list) else []
    status = "error" if slot_result.get("status") == "error" else "ok"
    first_error = str((results[0] or {}).get("error") or "") if results else ""
    detail = first_error or f"完成 {len(results)} 个任务"
    trace_meta: dict[str, Any] = {}
    if status == "error":
        trace_meta["nonFatal"] = True
        trace_meta["handledByParent"] = "parallel_tools"
    return {
        "event": "node_end",
        "traceItem": {
            "nodeId": str(slot.get("nodeId") or ""),
            "type": "parallel_worker",
            "label": str(slot.get("label") or "Worker"),
            "status": status,
            "detail": detail[:300] if detail else f"完成 {len(results)} 个任务",
            "durationMs": float(slot_result.get("durationMs") or 0),
            "inputState": compact_state({"tasks": [item["task"] for item in slot.get("tasks", [])]}),
            "outputDelta": compact_state({"workerResults": results}),
            **trace_meta,
        },
        "outputState": compact_state(state),
    }


def parallel_worker_system_prompt(base_prompt: str) -> str:
    return (
        f"{base_prompt}\n"
        "你是并行代码阅读 Worker，只完成分配给你的子任务。"
        "严格控制上下文：先定位，再读取小片段；不要读取完整大文件。"
        "最终请返回 JSON，格式为："
        '{"summary":"结论","evidence":[{"path":"文件路径","symbol":"符号或 selector","startLine":1,"endLine":1,"note":"证据说明"}],"warnings":[]}'
        "。不要输出完整工具调用 JSON。"
    )


def parallel_worker_user_prompt(state: dict[str, Any], task: dict[str, Any]) -> str:
    payload = {
        "userQuestion": state_value_to_text(state.get("messages")),
        "task": task,
    }
    return "请完成以下代码阅读子任务：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def normalize_worker_final_answer(task: dict[str, Any], final_answer: str) -> dict[str, Any]:
    from app.runner.nodes.task_splitter import parse_task_payload

    parsed = parse_task_payload(final_answer)
    task_id = str(task.get("id") or "")
    title = str(task.get("title") or task.get("goal") or task_id)
    if isinstance(parsed, dict):
        evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
        warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
        summary = state_value_to_text(parsed.get("summary") or parsed.get("final_answer") or parsed.get("answer") or final_answer).strip()
        return {
            "taskId": task_id,
            "title": title[:120],
            "status": "ok",
            "durationMs": 0,
            "summary": summary,
            "evidence": compact_value(evidence, string_limit=1200, list_limit=12),
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
