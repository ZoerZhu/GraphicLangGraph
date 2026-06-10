from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class NodeType(StrEnum):
    START = "start"
    LLM = "llm"
    CONDITION = "condition"
    HTTP = "http"
    DIRECT_REPLY = "direct_reply"
    CUSTOM_FUNCTION = "custom_function"


class EdgeKind(StrEnum):
    NORMAL = "normal"
    CONDITIONAL = "conditional"
    ERROR = "error"


class Position(BaseModel):
    x: float = 0
    y: float = 0


class Port(BaseModel):
    id: str
    type: str = "control"
    label: str | None = None


class StateField(BaseModel):
    name: str
    type: str = "str"
    default: Any = None
    description: str = ""


class StateSpec(BaseModel):
    base: str = "MessagesState"
    fields: list[StateField] = Field(default_factory=list)


class ProjectMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: f"agent_{uuid4().hex[:8]}")
    name: str = "Untitled Agent"
    description: str = ""
    schema_version: str = Field("0.1.0", alias="schemaVersion")


class NodeIR(BaseModel):
    id: str
    type: NodeType
    label: str
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)
    inputs: list[Port] = Field(default_factory=list)
    outputs: list[Port] = Field(default_factory=list)


class EdgeIR(BaseModel):
    id: str
    source: str
    sourceHandle: str | None = None
    target: str
    targetHandle: str | None = None
    kind: EdgeKind = EdgeKind.NORMAL
    label: str | None = None


class SecretRef(BaseModel):
    name: str
    env: str


class ProjectIR(BaseModel):
    project: ProjectMeta = Field(default_factory=ProjectMeta)
    state: StateSpec = Field(default_factory=StateSpec)
    nodes: list[NodeIR] = Field(default_factory=list)
    edges: list[EdgeIR] = Field(default_factory=list)
    secrets: list[SecretRef] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"] = "error"
    code: str
    message: str
    nodeId: str | None = None
    edgeId: str | None = None
    field: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


def create_default_project(name: str = "Untitled Agent") -> ProjectIR:
    project = ProjectIR(project=ProjectMeta(name=name))
    project.nodes.append(
        NodeIR(
            id="start",
            type=NodeType.START,
            label="开始",
            position=Position(x=120, y=220),
            config={"inputMode": "chat"},
            outputs=[Port(id="out", label="输出")],
        )
    )
    return project

