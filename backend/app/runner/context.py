from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Literal

from app.ir.schemas import NodeIR, ProjectIR

RunMode = Literal["dry", "live"]
ModelRuntimeConfig = dict[str, Any] | None
RuntimeEnvironment = dict[str, Any] | None
SkillRuntimeConfig = dict[str, dict[str, Any]]
ToolRuntimeConfig = dict[str, dict[str, Any]]
McpRuntimeConfig = dict[str, dict[str, Any]]
AgentRuntimeConfig = dict[str, dict[str, Any]]


@dataclass
class NodeExecutionResult:
    delta: dict[str, Any]
    detail: str


@dataclass
class ExecutionServices:
    execute_node: Callable[..., tuple[dict[str, Any], str]] | None = None
    execute_node_events: Callable[..., Iterator[dict[str, Any]]] | None = None
    next_execution_target: Callable[..., str | None] | None = None
    error_execution_target: Callable[..., str | None] | None = None
    compact_state: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    compact_value: Callable[[Any], Any] | None = None


@dataclass
class ExecutionContext:
    project: ProjectIR
    mode: RunMode
    model_config: ModelRuntimeConfig
    runtime_environment: RuntimeEnvironment
    skills: SkillRuntimeConfig
    tools: ToolRuntimeConfig
    mcp_servers: McpRuntimeConfig
    agents: AgentRuntimeConfig
    agent_depth: int = 0
    services: ExecutionServices | None = None


def node_result(value: tuple[dict[str, Any], str] | NodeExecutionResult) -> NodeExecutionResult:
    if isinstance(value, NodeExecutionResult):
        return value
    delta, detail = value
    return NodeExecutionResult(delta=delta, detail=detail)


def result_tuple(value: tuple[dict[str, Any], str] | NodeExecutionResult) -> tuple[dict[str, Any], str]:
    if isinstance(value, NodeExecutionResult):
        return value.delta, value.detail
    return value
