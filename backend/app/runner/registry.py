from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.ir.schemas import NodeIR, NodeType

from .context import ExecutionContext, NodeExecutionResult, node_result
from .nodes import (
    agent,
    agent_ref,
    ai_router,
    condition,
    direct_reply,
    error_handler,
    for_each,
    http,
    human_approval,
    json_extractor,
    json_validator,
    llm,
    mcp_node,
    merge,
    parallel_tools,
    retriever,
    skill_node,
    task_splitter,
    template,
    tool,
    variable_assign,
)

LIVE_EXECUTORS = {
    NodeType.LLM: llm,
    NodeType.AGENT: agent,
    NodeType.AGENT_REF: agent_ref,
    NodeType.SKILL_NODE: skill_node,
    NodeType.MCP_NODE: mcp_node,
    NodeType.TOOL: tool,
    NodeType.TASK_SPLITTER: task_splitter,
    NodeType.PARALLEL_TOOLS: parallel_tools,
    NodeType.VARIABLE_ASSIGN: variable_assign,
    NodeType.TEMPLATE: template,
    NodeType.JSON_EXTRACTOR: json_extractor,
    NodeType.JSON_VALIDATOR: json_validator,
    NodeType.FOR_EACH: for_each,
    NodeType.MERGE: merge,
    NodeType.ERROR_HANDLER: error_handler,
    NodeType.RETRIEVER: retriever,
    NodeType.CONDITION: condition,
    NodeType.AI_ROUTER: ai_router,
    NodeType.HUMAN_APPROVAL: human_approval,
    NodeType.HTTP: http,
    NodeType.DIRECT_REPLY: direct_reply,
}

DRY_EXECUTORS = LIVE_EXECUTORS
STREAM_EXECUTORS = {
    NodeType.FOR_EACH: for_each,
    NodeType.PARALLEL_TOOLS: parallel_tools,
}


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
    module = LIVE_EXECUTORS.get(node.type)
    if module is None or not hasattr(module, "execute_live"):
        raise RuntimeError(f"暂不支持的节点类型：{node.type}")
    return node_result(module.execute_live(node, state, ctx))


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
    module = DRY_EXECUTORS.get(node.type)
    if module is None or not hasattr(module, "execute_dry"):
        raise RuntimeError(f"暂不支持的节点类型：{node.type}")
    return node_result(module.execute_dry(node, state, ctx))


def execute_events(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext) -> Iterator[dict[str, Any]]:
    module = STREAM_EXECUTORS.get(node.type)
    if module is None or not hasattr(module, "execute_events"):
        raise RuntimeError(f"节点不支持流式执行：{node.type}")
    return (yield from module.execute_events(node, state, ctx))


def covered_node_types() -> set[NodeType]:
    return set(LIVE_EXECUTORS)
