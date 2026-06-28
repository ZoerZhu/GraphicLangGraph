from __future__ import annotations

import json
import re
from typing import Any

from app.ir.schemas import EdgeKind, NodeIR, NodeType


def choose_handle(node: NodeIR, state: dict[str, Any]) -> str:
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


def first_target(edges: list) -> str | None:
    return edges[0].target if edges else None


def first_execution_target(edges: list) -> str | None:
    executable = [edge for edge in edges if edge.kind not in {EdgeKind.WORKER, EdgeKind.ERROR}]
    return first_target(executable)


def human_approval_actions(node: NodeIR, outgoing: dict[str, list] | None = None) -> list[str]:
    actions: list[str] = []
    for action in approval_action_items(node.config.get("actions", "")):
        if action and action not in actions:
            actions.append(action)
    if outgoing:
        for edge in outgoing.get(node.id, []):
            handle = str(getattr(edge, "sourceHandle", "") or "").strip()
            if edge.kind == EdgeKind.CONDITIONAL and handle and handle not in actions:
                actions.append(handle)
    if not actions:
        actions = ["approved", "rejected"]
    return actions


def approval_action_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in re.split(r"[,，\n;；]+", text) if item.strip()]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def next_execution_target(node: NodeIR, nodes: dict[str, NodeIR], outgoing: dict[str, list], state: dict[str, Any]) -> str | None:
    edges = outgoing.get(node.id, [])
    if not edges:
        return None
    conditional_edges = [edge for edge in edges if edge.kind == EdgeKind.CONDITIONAL]
    if conditional_edges:
        handle = choose_handle(node, state)
        return target_for_handle(conditional_edges, handle) or first_target(conditional_edges)
    normal_edges = [edge for edge in edges if edge.kind == EdgeKind.NORMAL]
    if normal_edges:
        if node.type == NodeType.FOR_EACH:
            return for_each_exit_target(node.id, nodes, outgoing)
        return first_target(normal_edges)
    if node.type == NodeType.PARALLEL_TOOLS:
        return parallel_worker_output_target(node.id, nodes, outgoing)
    return None


def error_execution_target(node: NodeIR, outgoing: dict[str, list]) -> str | None:
    error_edges = [edge for edge in outgoing.get(node.id, []) if edge.kind == EdgeKind.ERROR or edge.sourceHandle == "error"]
    return target_for_handle(error_edges, "error") or first_target(error_edges)


def for_each_exit_target(parent_node_id: str, nodes: dict[str, NodeIR], outgoing: dict[str, list]) -> str | None:
    item_target = target_for_handle([edge for edge in outgoing.get(parent_node_id, []) if edge.kind != EdgeKind.ERROR], "item")
    if not item_target:
        return None
    merge_node = find_for_each_merge_node(item_target, nodes, outgoing)
    if not merge_node:
        return None
    normal_edges = [edge for edge in outgoing.get(merge_node.id, []) if edge.kind == EdgeKind.NORMAL]
    return first_target(normal_edges)


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


def parallel_worker_output_target(parent_node_id: str, nodes: dict[str, NodeIR], outgoing: dict[str, list]) -> str | None:
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


def target_for_handle(edges: list, handle: str) -> str | None:
    for edge in edges:
        if edge.sourceHandle == handle:
            return edge.target
    return None


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
