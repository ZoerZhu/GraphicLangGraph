from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from typing import Any

from app.ir.schemas import EdgeKind, NodeIR, NodeType

from .. import engine
from ..common import bool_config, compact_state, compact_value, error_execution_target, format_error, get_path, next_execution_target, positive_int, runtime_error_payload, target_for_handle
from ..context import ExecutionContext


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_for_each_node(node, state, ctx, "live")


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_for_each_node(node, state, ctx, "dry")


def execute_events(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return (yield from execute_for_each_node_events(node, state, ctx))


def _for_each_setup(node: NodeIR, ctx: ExecutionContext):
    nodes = {item.id: item for item in ctx.project.nodes}
    outgoing: dict[str, list] = {}
    for edge in ctx.project.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    item_start = target_for_handle([edge for edge in outgoing.get(node.id, []) if edge.kind != EdgeKind.ERROR], "item")
    if not item_start:
        raise RuntimeError("ForEach 未连接 item 循环体。")
    merge_node = find_for_each_merge_node(item_start, nodes, outgoing)
    if merge_node is None:
        raise RuntimeError("ForEach 循环体必须连接到 Merge 节点。")
    return nodes, outgoing, item_start, merge_node


def _for_each_items(node: NodeIR, state: dict[str, Any]) -> tuple[str, str, str, list[Any]]:
    config = node.config
    items_field = str(config.get("itemsField", "worker_tasks")).strip() or "worker_tasks"
    item_field = str(config.get("itemField", "current_item")).strip() or "current_item"
    index_field = str(config.get("indexField", "current_index")).strip() or "current_index"
    max_items = min(positive_int(config.get("maxItems"), 50), 100)
    items_value = get_path(state, items_field)
    if isinstance(items_value, dict) and isinstance(items_value.get("tasks"), list):
        items = items_value.get("tasks") or []
    elif isinstance(items_value, list):
        items = items_value
    else:
        raise RuntimeError(f"ForEach 需要 state.{items_field} 是 array。")
    return items_field, item_field, index_field, list(items)[:max_items]


def execute_for_each_node(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext, mode: str):
    config = node.config
    nodes, outgoing, item_start, merge_node = _for_each_setup(node, ctx)
    items_field, item_field, index_field, items = _for_each_items(node, state)
    item_states: list[dict[str, Any]] = []
    iterations: list[dict[str, Any]] = []
    execution_mode = str(config.get("executionMode") or "sequential").strip().lower()
    item_failure_policy = str(config.get("itemFailurePolicy") or "fail_fast").strip().lower()
    preserve_order = bool_config(config.get("preserveOrder"), True)
    parallel = mode == "live" and execution_mode == "parallel" and len(items) > 1
    if parallel:
        max_concurrency = min(positive_int(config.get("maxConcurrency"), 3), 12)
        futures = {}
        with ThreadPoolExecutor(max_workers=min(max_concurrency, len(items))) as executor:
            for index, item in enumerate(items):
                futures[
                    executor.submit(
                        run_for_each_item_job,
                        index,
                        item,
                        state,
                        item_field,
                        index_field,
                        item_start,
                        merge_node.id,
                        ctx.project,
                        nodes,
                        outgoing,
                        mode,
                        ctx.model_config,
                        ctx.runtime_environment,
                        ctx.skills,
                        ctx.tools,
                        ctx.mcp_servers,
                        ctx.agents,
                        ctx.agent_depth,
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
                    error_payload = runtime_error_payload(node, exc)
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
            iteration = {"index": result["index"], "item": compact_value(result["item"]), "output": compact_state(item_state)}
            if result.get("error"):
                iteration["error"] = compact_value(result["error"])
            iterations.append(iteration)
    else:
        for index, item in enumerate(items):
            item_state = dict(state)
            item_state[item_field] = item
            item_state[index_field] = index
            try:
                reached_merge = run_for_each_item_chain(
                    item_start,
                    merge_node.id,
                    item_state,
                    ctx.project,
                    nodes,
                    outgoing,
                    mode,
                    ctx.model_config,
                    ctx.runtime_environment,
                    ctx.skills,
                    ctx.tools,
                    ctx.mcp_servers,
                    ctx.agents,
                    ctx.agent_depth,
                )
            except Exception as exc:
                if item_failure_policy != "collect_errors":
                    raise
                error_payload = runtime_error_payload(node, exc)
                item_state["last_error"] = error_payload
                item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                reached_merge = True
            if not reached_merge:
                raise RuntimeError(f"ForEach 第 {index + 1} 项没有到达 Merge 节点。")
            item_states.append(item_state)
            iterations.append({"index": index, "item": compact_value(item), "output": compact_state(item_state)})

    from app.runner.nodes.merge import execute_merge

    merge_delta, detail = execute_merge(merge_node, state, item_states)
    merge_result_field = str(merge_node.config.get("resultField", "merge_result")).strip() or "merge_result"
    if isinstance(merge_delta.get(merge_result_field), dict):
        merge_delta[merge_result_field]["iterations"] = iterations
    delta = dict(merge_delta)
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


def execute_for_each_node_events(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    nodes, outgoing, item_start, merge_node = _for_each_setup(node, ctx)
    items_field, item_field, index_field, items = _for_each_items(node, state)
    item_states: list[dict[str, Any]] = []
    iterations: list[dict[str, Any]] = []
    child_trace_items: list[dict[str, Any]] = []
    execution_mode = str(config.get("executionMode") or "sequential").strip().lower()
    item_failure_policy = str(config.get("itemFailurePolicy") or "fail_fast").strip().lower()
    preserve_order = bool_config(config.get("preserveOrder"), True)
    parallel = execution_mode == "parallel" and len(items) > 1
    if parallel:
        max_concurrency = min(positive_int(config.get("maxConcurrency"), 3), 12)
        futures = {}
        event_queue: Queue[dict[str, Any]] = Queue()
        with ThreadPoolExecutor(max_workers=min(max_concurrency, len(items))) as executor:
            for index, item in enumerate(items):
                futures[
                    executor.submit(
                        collect_for_each_item_events,
                        item_start,
                        merge_node.id,
                        dict(state),
                        item_field,
                        index_field,
                        item,
                        index,
                        ctx.project,
                        nodes,
                        outgoing,
                        ctx.model_config,
                        ctx.runtime_environment,
                        ctx.skills,
                        ctx.tools,
                        ctx.mcp_servers,
                        ctx.agents,
                        ctx.agent_depth,
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
                        error_payload = runtime_error_payload(node, exc)
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
            iteration = {"index": result["index"], "item": compact_value(result["item"]), "output": compact_state(item_state)}
            if result.get("error"):
                iteration["error"] = compact_value(result["error"])
            iterations.append(iteration)
    else:
        for index, item in enumerate(items):
            item_state = dict(state)
            item_state[item_field] = item
            item_state[index_field] = index
            try:
                reached_merge = yield from run_for_each_item_chain_events(
                    item_start,
                    merge_node.id,
                    item_state,
                    ctx.project,
                    nodes,
                    outgoing,
                    ctx.model_config,
                    ctx.runtime_environment,
                    ctx.skills,
                    ctx.tools,
                    ctx.mcp_servers,
                    ctx.agents,
                    ctx.agent_depth,
                    node,
                    index,
                    item,
                    child_trace_items,
                )
            except Exception as exc:
                if item_failure_policy != "collect_errors":
                    raise
                error_payload = runtime_error_payload(node, exc)
                item_state["last_error"] = error_payload
                item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                reached_merge = True
            if not reached_merge:
                raise RuntimeError(f"ForEach 第 {index + 1} 项没有到达 Merge 节点。")
            item_states.append(item_state)
            iterations.append({"index": index, "item": compact_value(item), "output": compact_state(item_state)})

    merge_before = dict(state)
    merge_event_meta = {"forEachNodeId": node.id, "sourceNodeId": merge_node.id}
    yield {
        "event": "node_start",
        "nodeId": merge_node.id,
        "type": str(merge_node.type),
        "label": merge_node.label,
        "inputState": compact_state(merge_before),
        **merge_event_meta,
    }
    merge_started = time.perf_counter()
    from app.runner.nodes.merge import execute_merge

    merge_delta, detail = execute_merge(merge_node, state, item_states)
    merge_result_field = str(merge_node.config.get("resultField", "merge_result")).strip() or "merge_result"
    if isinstance(merge_delta.get(merge_result_field), dict):
        merge_delta[merge_result_field]["iterations"] = iterations
    merge_trace_item = {
        "nodeId": merge_node.id,
        "type": str(merge_node.type),
        "label": merge_node.label,
        "status": "ok",
        "detail": detail,
        "durationMs": round((time.perf_counter() - merge_started) * 1000, 2),
        "inputState": compact_state(merge_before),
        "outputDelta": compact_state(merge_delta),
        **merge_event_meta,
    }
    child_trace_items.append(merge_trace_item)
    yield {
        "event": "node_end",
        "traceItem": merge_trace_item,
        "outputState": compact_state({**state, **merge_delta}),
    }
    delta = dict(merge_delta)
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


def run_for_each_item_job(
    index: int,
    item: Any,
    base_state: dict[str, Any],
    item_field: str,
    index_field: str,
    item_start: str,
    merge_node_id: str,
    project: Any,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    mode: str,
    model_config: dict[str, Any] | None,
    runtime_environment: dict[str, Any] | None,
    skills: dict[str, dict[str, Any]],
    tools: dict[str, dict[str, Any]],
    mcp_servers: dict[str, dict[str, Any]],
    agents: dict[str, dict[str, Any]],
    agent_depth: int,
) -> dict[str, Any]:
    item_state = dict(base_state)
    item_state[item_field] = item
    item_state[index_field] = index
    reached_merge = run_for_each_item_chain(
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


def collect_for_each_item_events(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    item_field: str,
    index_field: str,
    item: Any,
    index: int,
    project: Any,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    model_config: dict[str, Any] | None,
    runtime_environment: dict[str, Any] | None,
    skills: dict[str, dict[str, Any]],
    tools: dict[str, dict[str, Any]],
    mcp_servers: dict[str, dict[str, Any]],
    agents: dict[str, dict[str, Any]],
    agent_depth: int,
    parent_node: NodeIR,
    event_queue: Queue[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item_state[item_field] = item
    item_state[index_field] = index
    child_trace: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    generator = run_for_each_item_chain_events(
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


def run_for_each_item_chain(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    project: Any,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    mode: str,
    model_config: dict[str, Any] | None,
    runtime_environment: dict[str, Any] | None,
    skills: dict[str, dict[str, Any]],
    tools: dict[str, dict[str, Any]],
    mcp_servers: dict[str, dict[str, Any]],
    agents: dict[str, dict[str, Any]],
    agent_depth: int,
) -> bool:
    current = start_node_id
    visited = 0
    while current and current in nodes and visited < engine.MAX_STEPS:
        if current == merge_node_id:
            return True
        visited += 1
        child = nodes[current]
        if child.type in {NodeType.FOR_EACH, NodeType.MERGE}:
            raise RuntimeError(f"ForEach v1 不支持嵌套或提前执行 {child.type} 节点。")
        try:
            delta, _detail, _trace_meta = engine._execute_node_with_policy(child, project, item_state, mode, model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            item_state.update(delta)
        except Exception as exc:
            error_target = error_execution_target(child, outgoing)
            if not error_target:
                raise
            item_state["last_error"] = runtime_error_payload(child, exc)
            current = error_target
            continue
        if child.type == NodeType.DIRECT_REPLY:
            return False
        current = next_execution_target(child, nodes, outgoing, item_state)
    if visited >= engine.MAX_STEPS:
        raise RuntimeError(f"ForEach 子链路超过 {engine.MAX_STEPS} 步，可能存在循环。")
    return False


def run_for_each_item_chain_events(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    project: Any,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    model_config: dict[str, Any] | None,
    runtime_environment: dict[str, Any] | None,
    skills: dict[str, dict[str, Any]],
    tools: dict[str, dict[str, Any]],
    mcp_servers: dict[str, dict[str, Any]],
    agents: dict[str, dict[str, Any]],
    agent_depth: int,
    parent_node: NodeIR,
    iteration_index: int,
    iteration_item: Any,
    child_trace_items: list[dict[str, Any]],
) -> bool:
    current = start_node_id
    visited = 0
    while current and current in nodes and visited < engine.MAX_STEPS:
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
            "iterationItem": compact_value(iteration_item),
            "sourceNodeId": child.id,
        }
        yield {
            "event": "node_start",
            "nodeId": child.id,
            "type": str(child.type),
            "label": child.label,
            "inputState": compact_state(before),
            **event_meta,
        }
        started = time.perf_counter()
        handled_error_target: str | None = None
        trace_meta: dict[str, Any] = {}
        try:
            delta, detail, trace_meta = engine._execute_node_with_policy(child, project, item_state, "live", model_config, runtime_environment, skills, tools, mcp_servers, agents, agent_depth)
            item_state.update(delta)
            status = "ok"
        except Exception as exc:
            handled_error_target = error_execution_target(child, outgoing)
            trace_meta = engine._trace_meta_from_exception(exc)
            delta = {"last_error": runtime_error_payload(child, exc)}
            item_state.update(delta)
            detail = f"{format_error(exc)}；已转入 error 分支。" if handled_error_target else format_error(exc)
            status = "error"
        trace_item = {
            "nodeId": child.id,
            "type": str(child.type),
            "label": child.label,
            "status": status,
            "detail": detail,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
            "inputState": compact_state(before),
            "outputDelta": compact_state(delta),
            **trace_meta,
            **event_meta,
        }
        child_trace_items.append(trace_item)
        yield {
            "event": "node_end",
            "traceItem": trace_item,
            "outputState": compact_state(item_state),
        }
        if status == "error" and not handled_error_target:
            raise RuntimeError(detail)
        if child.type == NodeType.DIRECT_REPLY:
            return False
        current = handled_error_target or next_execution_target(child, nodes, outgoing, item_state)
    if visited >= engine.MAX_STEPS:
        raise RuntimeError(f"ForEach 子链路超过 {engine.MAX_STEPS} 步，可能存在循环。")
    return False


def find_for_each_merge_node(start_node_id: str, nodes: dict[str, NodeIR], outgoing: dict[str, list]) -> NodeIR | None:
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
