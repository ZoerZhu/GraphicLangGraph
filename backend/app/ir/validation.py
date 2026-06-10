from __future__ import annotations

import ast
import re
from collections import defaultdict, deque

from .schemas import EdgeKind, NodeType, ProjectIR, ValidationIssue, ValidationResult


ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def validate_project(project: ProjectIR) -> ValidationResult:
    issues: list[ValidationIssue] = []
    nodes_by_id = {node.id: node for node in project.nodes}

    if len(nodes_by_id) != len(project.nodes):
        issues.append(_issue("DUPLICATE_NODE_ID", "节点 ID 不能重复。"))

    start_nodes = [node for node in project.nodes if node.type == NodeType.START]
    if len(start_nodes) != 1:
        issues.append(_issue("START_COUNT", "必须有且只有一个 Start 节点。"))

    direct_replies = [node for node in project.nodes if node.type == NodeType.DIRECT_REPLY]
    if not direct_replies:
        issues.append(_issue("NO_DIRECT_REPLY", "至少需要一个 Direct Reply 终止节点。"))

    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for edge in project.edges:
        if edge.source not in nodes_by_id:
            issues.append(_issue("EDGE_SOURCE_MISSING", "连线的源节点不存在。", edgeId=edge.id))
        if edge.target not in nodes_by_id:
            issues.append(_issue("EDGE_TARGET_MISSING", "连线的目标节点不存在。", edgeId=edge.id))
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    for node in start_nodes:
        if incoming[node.id]:
            issues.append(_issue("START_HAS_INCOMING", "Start 节点不允许有入边。", nodeId=node.id))

    for node_id, edges in outgoing.items():
        kinds = {edge.kind for edge in edges}
        if EdgeKind.CONDITIONAL in kinds and any(kind != EdgeKind.CONDITIONAL for kind in kinds):
            issues.append(
                _issue(
                    "MIXED_EDGE_KINDS",
                    "同一个节点不能同时存在普通出边和条件出边。",
                    nodeId=node_id,
                )
            )

    if start_nodes:
        reachable = _reachable_from(start_nodes[0].id, outgoing)
        for node in project.nodes:
            if node.id not in reachable:
                issues.append(_issue("UNREACHABLE_NODE", "节点无法从 Start 到达。", nodeId=node.id))
        if not any(node.type == NodeType.DIRECT_REPLY and node.id in reachable for node in project.nodes):
            issues.append(_issue("NO_REACHABLE_REPLY", "至少一条路径必须到达 Direct Reply。"))

    for node in project.nodes:
        if node.type == NodeType.CONDITION:
            _validate_condition(node.id, node.config, outgoing[node.id], issues)
        if node.type == NodeType.HTTP:
            _validate_http(node.id, node.config, issues)
        if node.type == NodeType.CUSTOM_FUNCTION:
            _validate_custom_function(node.id, node.config, issues)

    return ValidationResult(valid=not any(issue.severity == "error" for issue in issues), issues=issues)


def _reachable_from(start_id: str, outgoing: dict[str, list]) -> set[str]:
    seen = {start_id}
    queue: deque[str] = deque([start_id])
    while queue:
        node_id = queue.popleft()
        for edge in outgoing[node_id]:
            if edge.target not in seen:
                seen.add(edge.target)
                queue.append(edge.target)
    return seen


def _validate_condition(
    node_id: str,
    config: dict,
    outgoing_edges: list,
    issues: list[ValidationIssue],
) -> None:
    fallback = str(config.get("fallback", "")).strip()
    if not fallback:
        issues.append(_issue("CONDITION_FALLBACK", "Condition 节点必须配置 fallback。", nodeId=node_id))
        return

    handles = {edge.sourceHandle for edge in outgoing_edges}
    if fallback not in handles:
        issues.append(
            _issue(
                "CONDITION_FALLBACK_EDGE",
                "Condition 的 fallback 分支必须连接到后续节点。",
                nodeId=node_id,
                field="fallback",
            )
        )


def _validate_http(node_id: str, config: dict, issues: list[ValidationIssue]) -> None:
    auth_secret = str(config.get("authSecret", "")).strip()
    if auth_secret and not ENV_KEY_RE.match(auth_secret):
        issues.append(
            _issue(
                "HTTP_SECRET_ENV",
                "HTTP 密钥只能引用 .env key，例如 ORDER_API_TOKEN。",
                nodeId=node_id,
                field="authSecret",
            )
        )


def _validate_custom_function(node_id: str, config: dict, issues: list[ValidationIssue]) -> None:
    code = str(config.get("code", "return {}"))
    try:
        ast.parse("def __custom__(state):\n" + _indent(code))
    except SyntaxError as exc:
        issues.append(
            _issue(
                "CUSTOM_FUNCTION_SYNTAX",
                f"Custom Function Python 语法错误：{exc.msg}。",
                nodeId=node_id,
                field="code",
            )
        )


def _indent(code: str) -> str:
    lines = code.splitlines() or ["return {}"]
    return "\n".join(f"    {line}" if line.strip() else "" for line in lines)


def _issue(
    code: str,
    message: str,
    *,
    nodeId: str | None = None,
    edgeId: str | None = None,
    field: str | None = None,
    severity: str = "error",
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        nodeId=nodeId,
        edgeId=edgeId,
        field=field,
    )

