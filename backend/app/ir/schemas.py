from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class NodeType(StrEnum):
    START = "start"
    LLM = "llm"
    AGENT = "agent"
    TOOL = "tool"
    TASK_SPLITTER = "task_splitter"
    PARALLEL_TOOLS = "parallel_tools"
    PARALLEL_WORKER = "parallel_worker"
    VARIABLE_ASSIGN = "variable_assign"
    TEMPLATE = "template"
    JSON_EXTRACTOR = "json_extractor"
    JSON_VALIDATOR = "json_validator"
    FOR_EACH = "for_each"
    MERGE = "merge"
    ERROR_HANDLER = "error_handler"
    RETRIEVER = "retriever"
    CONDITION = "condition"
    AI_ROUTER = "ai_router"
    HUMAN_APPROVAL = "human_approval"
    HTTP = "http"
    DIRECT_REPLY = "direct_reply"
    CUSTOM_FUNCTION = "custom_function"
    SKILL_NODE = "skill_node"
    MCP_NODE = "mcp_node"
    AGENT_REF = "agent_ref"


class EdgeKind(StrEnum):
    NORMAL = "normal"
    CONDITIONAL = "conditional"
    ERROR = "error"
    WORKER = "worker"


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
    kind: str = "agent"
    runtime_environment_id: str = Field("", alias="runtimeEnvironmentId")
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


class ToolConfig(BaseModel):
    id: str = Field(default_factory=lambda: f"tool_{uuid4().hex[:8]}")
    name: str = "未命名工具"
    description: str = ""
    source: str = "python"
    tool_schema: str = Field("{}", alias="schemaJson")


class SkillConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"skill_{uuid4().hex[:8]}")
    name: str = "未命名 Skill"
    description: str = ""
    source_type: str = Field("manual", alias="sourceType")
    source_path: str = Field("", alias="sourcePath")
    file_path: str = Field("", alias="filePath")
    content: str = ""
    metadata_json: str = Field("{}", alias="metadataJson")
    enabled: bool = True


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(default_factory=lambda: f"mcp_{uuid4().hex[:8]}")
    name: str = "未命名 MCP"
    transport: str = "stdio"
    command: str = ""
    args_json: str = Field("[]", alias="argsJson")
    env_json: str = Field("{}", alias="envJson")
    env_vars_json: str = Field("[]", alias="envVarsJson")
    cwd: str = ""
    url: str = ""
    api_key: str = Field("", alias="apiKey")
    api_key_env: str = Field("", alias="apiKeyEnv")
    api_key_mode: str = Field("env", alias="apiKeyMode")
    api_key_header: str = Field("Authorization", alias="apiKeyHeader")
    api_key_prefix: str = Field("Bearer", alias="apiKeyPrefix")
    bearer_token_env_var: str = Field("", alias="bearerTokenEnvVar")
    http_headers_json: str = Field("{}", alias="httpHeadersJson")
    env_http_headers_json: str = Field("{}", alias="envHttpHeadersJson")
    enabled: bool = True
    startup_timeout_sec: int = Field(10, alias="startupTimeoutSec")
    tool_timeout_sec: int = Field(60, alias="toolTimeoutSec")
    enabled_tools_json: str = Field("[]", alias="enabledToolsJson")
    disabled_tools_json: str = Field("[]", alias="disabledToolsJson")
    default_tools_approval_mode: str = Field("", alias="defaultToolsApprovalMode")
    source_type: str = Field("manual", alias="sourceType")
    source_path: str = Field("", alias="sourcePath")
    description: str = ""


class ImportedAgentConfig(BaseModel):
    id: str = Field(default_factory=lambda: f"agent_ref_{uuid4().hex[:8]}")
    name: str = "导入的 Agent"
    project_id: str = Field("", alias="projectId")
    role: str = "sub_agent"
    description: str = ""


class AgentLinkConfig(BaseModel):
    id: str = Field(default_factory=lambda: f"agent_link_{uuid4().hex[:8]}")
    from_agent: str = Field("", alias="fromAgent")
    to_agent: str = Field("", alias="toAgent")
    protocol: str = "handoff"
    instruction: str = ""


class ProjectIR(BaseModel):
    project: ProjectMeta = Field(default_factory=ProjectMeta)
    state: StateSpec = Field(default_factory=StateSpec)
    nodes: list[NodeIR] = Field(default_factory=list)
    edges: list[EdgeIR] = Field(default_factory=list)
    secrets: list[SecretRef] = Field(default_factory=list)
    tools: list[ToolConfig] = Field(default_factory=list)
    skills: list[SkillConfig] = Field(default_factory=list)
    mcpServers: list[MCPServerConfig] = Field(default_factory=list)
    importedAgents: list[ImportedAgentConfig] = Field(default_factory=list)
    agentLinks: list[AgentLinkConfig] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"] = "error"
    code: str
    message: str
    nodeId: str | None = None
    edgeId: str | None = None
    field: str | None = None
    suggestion: str | None = None


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


def create_default_project(name: str = "Untitled Agent", kind: str = "agent") -> ProjectIR:
    project = ProjectIR(project=ProjectMeta(name=name, kind=kind))
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
