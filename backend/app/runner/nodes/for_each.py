from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Empty, Queue
from typing import Any

from app.ir.schemas import EdgeKind, NodeIR, NodeType

from ..common import bool_config, compact_state, compact_value, error_execution_target, format_error, get_path, next_execution_target, positive_int, runtime_error_payload, target_for_handle
from ..context import ExecutionContext


class _ForEachItemError(RuntimeError):
    def __init__(
        self,
        original: Exception,
        item_state: dict[str, Any],
        child_trace: list[dict[str, Any]],
        events: list[dict[str, Any]],
        error_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(str(original))
        self.original = original
        self.item_state = item_state
        self.child_trace = child_trace
        self.events = events
        self.error_payload = error_payload


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


def _execute_child_with_policy(ctx: ExecutionContext, child: NodeIR, item_state: dict[str, Any], mode: str):
    if not ctx.services or not ctx.services.execute_node_with_policy:
        raise RuntimeError("ForEach 缺少子节点执行服务。")
    return ctx.services.execute_node_with_policy(child, item_state, mode)  # type: ignore[arg-type]


def _trace_meta_from_exception(ctx: ExecutionContext, exc: Exception) -> dict[str, Any]:
    if ctx.services and ctx.services.trace_meta_from_exception:
        return ctx.services.trace_meta_from_exception(exc)
    return {}


def _max_steps(ctx: ExecutionContext) -> int:
    return int(ctx.services.max_steps) if ctx.services else 80


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
                        ctx,
                        nodes,
                        outgoing,
                        mode,
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
                    ctx,
                    nodes,
                    outgoing,
                    mode,
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
        emitted_event_keys: set[tuple[Any, ...]] = set()
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
                        ctx,
                        nodes,
                        outgoing,
                        node,
                        event_queue,
                    )
                ] = (index, item)
            results: list[dict[str, Any]] = []
            pending = set(futures)
            while pending:
                try:
                    queued_event = event_queue.get(timeout=0.05)
                    emitted_event_keys.add(_for_each_event_identity(queued_event))
                    yield queued_event
                except Empty:
                    pass
                for future in [item for item in pending if item.done()]:
                    pending.remove(future)
                    index, item = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        if item_failure_policy != "collect_errors":
                            if isinstance(exc, _ForEachItemError):
                                for event in exc.events:
                                    event_key = _for_each_event_identity(event)
                                    if event_key not in emitted_event_keys:
                                        emitted_event_keys.add(event_key)
                                        yield event
                            raise
                        if isinstance(exc, _ForEachItemError):
                            original_exc = exc.original
                            item_state = dict(exc.item_state)
                            child_trace = list(exc.child_trace)
                            events = list(exc.events)
                            error_payload = dict(exc.error_payload) if isinstance(exc.error_payload, dict) else _collected_item_error_payload(node, original_exc, item_state, child_trace)
                        else:
                            original_exc = exc
                            item_state = dict(state)
                            item_state[item_field] = item
                            item_state[index_field] = index
                            child_trace = []
                            events = []
                            error_payload = runtime_error_payload(node, original_exc)
                        item_state["last_error"] = error_payload
                        item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                        result = {"index": index, "item": item, "itemState": item_state, "reachedMerge": True, "events": events, "childTrace": child_trace, "error": error_payload}
                    results.append(result)
                    child_trace_items.extend(result.get("childTrace", []))
            while True:
                try:
                    queued_event = event_queue.get_nowait()
                    event_key = _for_each_event_identity(queued_event)
                    if event_key not in emitted_event_keys:
                        emitted_event_keys.add(event_key)
                        yield queued_event
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
                    ctx,
                    nodes,
                    outgoing,
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
    ctx: ExecutionContext,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    mode: str,
) -> dict[str, Any]:
    item_state = dict(base_state)
    item_state[item_field] = item
    item_state[index_field] = index
    reached_merge = run_for_each_item_chain(
        item_start,
        merge_node_id,
        item_state,
        ctx,
        nodes,
        outgoing,
        mode,
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
    ctx: ExecutionContext,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
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
        ctx,
        nodes,
        outgoing,
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
        except Exception as exc:
            error_payload = _collected_item_error_payload(parent_node, exc, item_state, child_trace)
            raise _ForEachItemError(exc, item_state, child_trace, events, error_payload) from exc
    return {"index": index, "item": item, "itemState": item_state, "reachedMerge": reached_merge, "events": events, "childTrace": child_trace}


def _collected_item_error_payload(parent_node: NodeIR, exc: Exception, item_state: dict[str, Any], child_trace: list[dict[str, Any]]) -> dict[str, Any]:
    state_error = item_state.get("last_error")
    if isinstance(state_error, dict):
        return dict(state_error)
    for trace_item in reversed(child_trace):
        output_delta = trace_item.get("outputDelta") if isinstance(trace_item, dict) else None
        if isinstance(output_delta, dict) and isinstance(output_delta.get("last_error"), dict):
            return dict(output_delta["last_error"])
    return runtime_error_payload(parent_node, exc)


def _for_each_event_identity(event: dict[str, Any]) -> tuple[Any, ...]:
    trace_item = event.get("traceItem")
    if isinstance(trace_item, dict):
        return (
            event.get("event"),
            trace_item.get("nodeId"),
            trace_item.get("parentNodeId"),
            trace_item.get("iterationIndex"),
            trace_item.get("sourceNodeId"),
        )
    return (
        event.get("event"),
        event.get("nodeId"),
        event.get("parentNodeId"),
        event.get("iterationIndex"),
        event.get("sourceNodeId"),
    )


def run_for_each_item_chain(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    ctx: ExecutionContext,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    mode: str,
) -> bool:
    current = start_node_id
    visited = 0
    max_steps = _max_steps(ctx)
    while current and current in nodes and visited < max_steps:
        if current == merge_node_id:
            return True
        visited += 1
        child = nodes[current]
        if child.type in {NodeType.FOR_EACH, NodeType.MERGE}:
            raise RuntimeError(f"ForEach v1 不支持嵌套或提前执行 {child.type} 节点。")
        try:
            delta, _detail, _trace_meta = _execute_child_with_policy(ctx, child, item_state, mode)
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
    if visited >= max_steps:
        raise RuntimeError(f"ForEach 子链路超过 {max_steps} 步，可能存在循环。")
    return False


def run_for_each_item_chain_events(
    start_node_id: str,
    merge_node_id: str,
    item_state: dict[str, Any],
    ctx: ExecutionContext,
    nodes: dict[str, NodeIR],
    outgoing: dict[str, list],
    parent_node: NodeIR,
    iteration_index: int,
    iteration_item: Any,
    child_trace_items: list[dict[str, Any]],
) -> bool:
    current = start_node_id
    visited = 0
    max_steps = _max_steps(ctx)
    while current and current in nodes and visited < max_steps:
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
            delta, detail, trace_meta = _execute_child_with_policy(ctx, child, item_state, "live")
            item_state.update(delta)
            status = "ok"
        except Exception as exc:
            handled_error_target = error_execution_target(child, outgoing)
            trace_meta = _trace_meta_from_exception(ctx, exc)
            delta = {"last_error": runtime_error_payload(child, exc)}
            item_state.update(delta)
            detail = f"{format_error(exc)}；已转入 error 分支。" if handled_error_target else format_error(exc)
            status = "ok" if handled_error_target else "error"
            if handled_error_target:
                trace_meta["handledError"] = True
                trace_meta["errorTarget"] = handled_error_target
            elif str(parent_node.config.get("itemFailurePolicy") or "fail_fast").strip().lower() == "collect_errors":
                trace_meta["nonFatal"] = True
                trace_meta["handledByParent"] = "for_each_collect_errors"
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
    if visited >= max_steps:
        raise RuntimeError(f"ForEach 子链路超过 {max_steps} 步，可能存在循环。")
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
