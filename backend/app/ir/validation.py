from __future__ import annotations

import ast
import json
import re
from collections import defaultdict, deque
from typing import Any

from .schemas import EdgeKind, NodeType, ProjectIR, ValidationIssue, ValidationResult


ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
PLAIN_SECRET_KEYS = {"apikey", "secret", "password", "token"}


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
        _validate_edge_handles(edge, nodes_by_id, issues)

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
                    suggestion="删除普通出边，或改为 Condition / AI Router 的条件分支。",
                )
            )
        normal_edges = [edge for edge in edges if edge.kind == EdgeKind.NORMAL]
        node = nodes_by_id.get(node_id)
        if node and len(normal_edges) > 1 and not bool(node.config.get("allowParallel", False)):
            issues.append(
                _issue(
                    "MULTIPLE_NORMAL_OUT_EDGES",
                    "同一个节点有多条普通出边，会触发并行执行；请改用条件分支或显式开启并行。",
                    nodeId=node_id,
                    suggestion="保留一条普通出边，或在节点配置中设置 allowParallel=true 并声明 reducer。",
                )
            )

    if start_nodes:
        reachable = _reachable_from(start_nodes[0].id, outgoing)
        for node in project.nodes:
            if node.id not in reachable:
                issues.append(
                    _issue(
                        "UNREACHABLE_NODE",
                        "节点无法从 Start 到达。",
                        nodeId=node.id,
                        suggestion="把节点连接到 Start 可达路径，或删除暂不使用的节点。",
                    )
                )
        if not any(node.type == NodeType.DIRECT_REPLY and node.id in reachable for node in project.nodes):
            issues.append(_issue("NO_REACHABLE_REPLY", "至少一条路径必须到达 Direct Reply。"))
        _validate_terminal_reachability(project, reachable, incoming, issues)

    _validate_state_writes(project, issues)

    for node in project.nodes:
        _validate_plain_secrets(node.id, node.config, issues)
        if node.type == NodeType.CONDITION:
            _validate_condition(node.id, node.config, outgoing[node.id], issues)
        if node.type == NodeType.AI_ROUTER:
            _validate_ai_router(node.id, node.config, outgoing[node.id], issues)
        if node.type == NodeType.HUMAN_APPROVAL:
            _validate_human_approval(node.id, node.config, outgoing[node.id], issues)
        if node.type == NodeType.AGENT:
            _validate_agent(node.id, node.config, issues)
        if node.type == NodeType.TOOL:
            _validate_tool(node.id, node.config, issues)
        if node.type == NodeType.TASK_SPLITTER:
            _validate_task_splitter(node.id, node.config, issues)
        if node.type == NodeType.PARALLEL_TOOLS:
            _validate_parallel_tools(node.id, node.config, issues)
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


def _reverse_reachable_from(target_ids: set[str], incoming: dict[str, list]) -> set[str]:
    seen = set(target_ids)
    queue: deque[str] = deque(target_ids)
    while queue:
        node_id = queue.popleft()
        for edge in incoming[node_id]:
            if edge.source not in seen:
                seen.add(edge.source)
                queue.append(edge.source)
    return seen


def _validate_terminal_reachability(
    project: ProjectIR,
    reachable_from_start: set[str],
    incoming: dict[str, list],
    issues: list[ValidationIssue],
) -> None:
    terminal_ids = {node.id for node in project.nodes if node.type == NodeType.DIRECT_REPLY}
    if not terminal_ids:
        return
    can_reach_terminal = _reverse_reachable_from(terminal_ids, incoming)
    for node in project.nodes:
        if node.id not in reachable_from_start or node.id in terminal_ids:
            continue
        if node.id not in can_reach_terminal:
            issues.append(
                _issue(
                    "NO_TERMINAL_PATH",
                    "启用节点必须能到达 Direct Reply 终止节点。",
                    nodeId=node.id,
                    suggestion="为该节点补一条到 Direct Reply 的路径，或把它移出当前执行流。",
                )
            )


def _validate_edge_handles(edge, nodes_by_id: dict[str, Any], issues: list[ValidationIssue]) -> None:
    source = nodes_by_id.get(edge.source)
    target = nodes_by_id.get(edge.target)
    if not source or not target:
        return

    if edge.kind == EdgeKind.CONDITIONAL and not edge.sourceHandle:
        issues.append(
            _issue(
                "CONDITIONAL_EDGE_HANDLE",
                "条件连线必须绑定源分支 handle。",
                nodeId=edge.source,
                edgeId=edge.id,
                field="sourceHandle",
                suggestion="从条件节点的具体分支端口重新连线。",
            )
        )

    source_handles = {port.id for port in source.outputs}
    target_handles = {port.id for port in target.inputs}
    if edge.sourceHandle and source_handles and edge.sourceHandle not in source_handles:
        issues.append(
            _issue(
                "EDGE_SOURCE_HANDLE_MISSING",
                "连线的源端口不存在。",
                nodeId=edge.source,
                edgeId=edge.id,
                field="sourceHandle",
                suggestion="删除该连线后从有效输出端口重新连接。",
            )
        )
    if edge.targetHandle and target_handles and edge.targetHandle not in target_handles:
        issues.append(
            _issue(
                "EDGE_TARGET_HANDLE_MISSING",
                "连线的目标端口不存在。",
                nodeId=edge.target,
                edgeId=edge.id,
                field="targetHandle",
                suggestion="删除该连线后连接到有效输入端口。",
            )
        )
    if not edge.sourceHandle and len(source_handles) > 1:
        issues.append(
            _issue(
                "EDGE_SOURCE_HANDLE_REQUIRED",
                "多输出节点的连线必须指定源端口。",
                nodeId=edge.source,
                edgeId=edge.id,
                field="sourceHandle",
                suggestion="从具体输出端口重新连线。",
            )
        )
    if not edge.targetHandle and len(target_handles) > 1:
        issues.append(
            _issue(
                "EDGE_TARGET_HANDLE_REQUIRED",
                "多输入节点的连线必须指定目标端口。",
                nodeId=edge.target,
                edgeId=edge.id,
                field="targetHandle",
                suggestion="连接到目标节点的具体输入端口。",
            )
        )


def _validate_condition(
    node_id: str,
    config: dict,
    outgoing_edges: list,
    issues: list[ValidationIssue],
) -> None:
    expected = {
        str(config.get("trueBranch", "true")).strip() or "true",
        str(config.get("falseBranch", "false")).strip() or "false",
    }
    fallback = str(config.get("fallback", "")).strip()
    if fallback:
        expected.add(fallback)
    else:
        issues.append(
            _issue(
                "CONDITION_FALLBACK",
                "Condition 节点必须配置 fallback。",
                nodeId=node_id,
                field="fallback",
                suggestion="填写 fallback 分支并连接到后续节点。",
            )
        )
    handles = {edge.sourceHandle for edge in outgoing_edges}
    missing = sorted(branch for branch in expected if branch not in handles)
    if missing:
        issues.append(
            _issue(
                "CONDITION_BRANCH_EDGE",
                f"Condition 分支缺少连线：{', '.join(missing)}。",
                nodeId=node_id,
                field="outputs",
                suggestion="为每个 Condition 分支连接后续节点。",
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


def _validate_ai_router(
    node_id: str,
    config: dict,
    outgoing_edges: list,
    issues: list[ValidationIssue],
) -> None:
    fallback = str(config.get("fallback", "")).strip()
    if not fallback:
        issues.append(
            _issue(
                "ROUTER_FALLBACK",
                "AI Router 节点必须配置 fallback。",
                nodeId=node_id,
                field="fallback",
                suggestion="填写 fallback 分支，例如 other，并连接到兜底处理节点。",
            )
        )
        return
    expected = {fallback}
    expected.update(scenario_id for scenario_id, _label, _keywords in _parse_scenarios(str(config.get("scenarios", ""))))
    handles = {edge.sourceHandle for edge in outgoing_edges}
    missing = sorted(branch for branch in expected if branch and branch not in handles)
    if missing:
        issues.append(
            _issue(
                "ROUTER_BRANCH_EDGE",
                f"AI Router 分支缺少连线：{', '.join(missing)}。",
                nodeId=node_id,
                field="outputs",
                suggestion="为每个场景分支和 fallback 分支连接后续节点。",
            )
        )


def _validate_human_approval(
    node_id: str,
    config: dict,
    outgoing_edges: list,
    issues: list[ValidationIssue],
) -> None:
    fallback = str(config.get("fallback", "")).strip()
    if not fallback:
        issues.append(
            _issue(
                "ROUTER_FALLBACK",
                "Human Approval 节点必须配置 fallback。",
                nodeId=node_id,
                field="fallback",
                suggestion="填写拒绝或超时后的 fallback 动作。",
            )
        )
        return
    expected = {fallback, "approved", "rejected"}
    handles = {edge.sourceHandle for edge in outgoing_edges}
    missing = sorted(branch for branch in expected if branch not in handles)
    if missing:
        issues.append(
            _issue(
                "ROUTER_BRANCH_EDGE",
                f"Human Approval 动作分支缺少连线：{', '.join(missing)}。",
                nodeId=node_id,
                field="outputs",
                suggestion="至少连接通过、拒绝和 fallback 动作分支。",
            )
        )


def _validate_agent(node_id: str, config: dict, issues: list[ValidationIssue]) -> None:
    try:
        max_iterations = int(config.get("maxIterations", 1))
    except (TypeError, ValueError):
        max_iterations = 0
    if max_iterations < 1:
        issues.append(_issue("AGENT_MAX_ITERATIONS", "Agent 最大迭代次数必须大于 0。", nodeId=node_id, field="maxIterations"))


def _validate_tool(node_id: str, config: dict, issues: list[ValidationIssue]) -> None:
    params_json = str(config.get("paramsJson", "{}")).strip() or "{}"
    try:
        parsed = json.loads(params_json)
    except ValueError as exc:
        issues.append(_issue("TOOL_PARAMS_JSON", f"Tool 参数 Schema JSON 格式错误：{exc}。", nodeId=node_id, field="paramsJson"))
        return
    if not isinstance(parsed, dict):
        issues.append(_issue("TOOL_PARAMS_OBJECT", "Tool 参数 Schema 必须是 JSON object。", nodeId=node_id, field="paramsJson"))


def _validate_task_splitter(node_id: str, config: dict, issues: list[ValidationIssue]) -> None:
    if not _clean_field(config.get("inputField")):
        issues.append(_issue("TASK_SPLITTER_INPUT_FIELD", "Task Splitter 必须配置输入字段。", nodeId=node_id, field="inputField"))
    if not _clean_field(config.get("outputField")):
        issues.append(_issue("TASK_SPLITTER_OUTPUT_FIELD", "Task Splitter 必须配置输出字段。", nodeId=node_id, field="outputField"))
    try:
        max_tasks = int(config.get("maxTasks", 5))
    except (TypeError, ValueError):
        max_tasks = 0
    if max_tasks < 1 or max_tasks > 10:
        issues.append(_issue("TASK_SPLITTER_MAX_TASKS", "Task Splitter 最大任务数必须在 1-10 之间。", nodeId=node_id, field="maxTasks"))


def _validate_parallel_tools(node_id: str, config: dict, issues: list[ValidationIssue]) -> None:
    if not _clean_field(config.get("tasksField")):
        issues.append(_issue("PARALLEL_TOOLS_TASKS_FIELD", "Parallel Tools 必须配置任务字段。", nodeId=node_id, field="tasksField"))
    if not _clean_field(config.get("outputField")):
        issues.append(_issue("PARALLEL_TOOLS_OUTPUT_FIELD", "Parallel Tools 必须配置输出字段。", nodeId=node_id, field="outputField"))
    try:
        max_iterations = int(config.get("maxIterationsPerTask", 6))
    except (TypeError, ValueError):
        max_iterations = 0
    if max_iterations < 1:
        issues.append(_issue("PARALLEL_TOOLS_MAX_ITERATIONS", "Parallel Tools 每个任务最大调用轮次必须大于 0。", nodeId=node_id, field="maxIterationsPerTask"))
    try:
        max_concurrent = int(config.get("maxConcurrentWorkers", 3))
    except (TypeError, ValueError):
        max_concurrent = 0
    if max_concurrent < 1 or max_concurrent > 6:
        issues.append(_issue("PARALLEL_TOOLS_CONCURRENCY", "Parallel Tools 并发数必须在 1-6 之间。", nodeId=node_id, field="maxConcurrentWorkers"))
    if not _has_selected_tools(config):
        issues.append(_issue("PARALLEL_TOOLS_REQUIRED", "Parallel Tools 至少需要选择一个 Tool。", nodeId=node_id, field="toolIdsJson"))


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
                suggestion="修正 Python 代码，确保函数体能被 def __custom__(state) 包裹后解析。",
            )
        )


def _validate_state_writes(project: ProjectIR, issues: list[ValidationIssue]) -> None:
    declared = {"messages"}
    declared.update(str(field.name).strip() for field in project.state.fields if str(field.name).strip())
    for node in project.nodes:
        for field in sorted(_state_writes_for_node(node.type, node.config)):
            if field and field not in declared:
                issues.append(
                    _issue(
                        "STATE_FIELD_UNDECLARED",
                        f"节点写入 state.{field}，但项目 State 字段未声明。",
                        nodeId=node.id,
                        field=field,
                        suggestion=f"在右侧项目 State 字段中添加 `{field}: str`，或修改节点输出字段。",
                    )
                )


def _state_writes_for_node(node_type: NodeType, config: dict[str, Any]) -> set[str]:
    if node_type == NodeType.LLM:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.AGENT:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.TOOL:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.TASK_SPLITTER:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.PARALLEL_TOOLS:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.RETRIEVER:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.HTTP:
        return {_clean_field(config.get("outputField", ""))}
    if node_type == NodeType.AI_ROUTER:
        return {_clean_field(config.get("routeField", "")), _clean_field(config.get("reasonField", ""))}
    if node_type == NodeType.HUMAN_APPROVAL:
        return {_clean_field(config.get("actionField", "")), _clean_field(config.get("outputField", ""))}
    if node_type == NodeType.DIRECT_REPLY:
        return {_clean_field(config.get("outputField", "")), "messages"}
    if node_type in {NodeType.CUSTOM_FUNCTION, NodeType.SKILL_NODE, NodeType.MCP_NODE}:
        return {_clean_field(config.get("outputField", ""))}
    return set()


def _has_selected_tools(config: dict[str, Any]) -> bool:
    for key in ("toolIdsJson", "toolRegistryJson"):
        value = config.get(key)
        if isinstance(value, list) and value:
            return True
        text = str(value or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, list) and parsed:
            return True
    return bool(str(config.get("tools", "")).strip())


def _clean_field(value: Any) -> str:
    return str(value or "").strip()


def _validate_plain_secrets(node_id: str, config: dict[str, Any], issues: list[ValidationIssue]) -> None:
    for path in _plain_secret_paths(config):
        issues.append(
            _issue(
                "PLAINTEXT_SECRET",
                "节点配置不能保存明文密钥，只能引用环境变量 key。",
                nodeId=node_id,
                field=path,
                suggestion="删除明文值，改用 apiKeyEnv、authSecret 或 .env key 引用。",
            )
        )


def _plain_secret_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_plain_secret_key(key_text) and str(child or "").strip():
                paths.append(path)
            else:
                paths.extend(_plain_secret_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_plain_secret_paths(child, f"{prefix}[{index}]"))
    return paths


def _is_plain_secret_key(key: str) -> bool:
    normalized = "".join(ch for ch in key.lower() if ch.isalnum())
    if normalized.endswith("env") or normalized in {"authsecret", "secretref"}:
        return False
    return normalized in PLAIN_SECRET_KEYS


def _parse_scenarios(value: str) -> list[tuple[str, str, str]]:
    scenarios: list[tuple[str, str, str]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        scenario_id, label, keywords = (line.split(":", 2) + ["", ""])[:3]
        scenario_id = scenario_id.strip()
        if scenario_id:
            scenarios.append((scenario_id, label.strip(), keywords.strip()))
    return scenarios


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
    suggestion: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        nodeId=nodeId,
        edgeId=edgeId,
        field=field,
        suggestion=suggestion,
    )
