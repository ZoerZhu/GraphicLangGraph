from __future__ import annotations

import json
import re
from typing import Any

from app.builtin_tools import builtin_tool_config_by_id
from app.config import WORKSPACE_MCP_FILE, WORKSPACE_TOOLS_FILE
from app.ir.schemas import ProjectIR
from app import mcp_runtime
from app.runner.data_runtime import json_object_list


SkillRuntimeConfig = dict[str, dict[str, Any]]
ToolRuntimeConfig = dict[str, dict[str, Any]]
McpRuntimeConfig = dict[str, dict[str, Any]]
AgentRuntimeConfig = dict[str, dict[str, Any]]
RuntimeEnvironment = dict[str, Any] | None


def enabled_skills_by_id(project: ProjectIR) -> SkillRuntimeConfig:
    result: SkillRuntimeConfig = {}
    for skill in getattr(project, "skills", []) or []:
        if getattr(skill, "enabled", True) is False:
            continue
        skill_id = str(getattr(skill, "id", "")).strip()
        if not skill_id:
            continue
        result[skill_id] = {
            "id": skill_id,
            "name": str(getattr(skill, "name", "") or skill_id),
            "description": str(getattr(skill, "description", "") or ""),
            "sourcePath": str(getattr(skill, "source_path", "") or ""),
            "filePath": str(getattr(skill, "file_path", "") or ""),
            "content": str(getattr(skill, "content", "") or ""),
            "metadataJson": str(getattr(skill, "metadata_json", "") or "{}"),
        }
    return result


def selected_skill_configs(config: dict[str, Any], skills: SkillRuntimeConfig) -> list[dict[str, Any]]:
    ids = json_string_list(config.get("skillIdsJson"))
    fallback_id = str(config.get("skillId") or "").strip()
    if fallback_id and fallback_id not in ids:
        ids.append(fallback_id)
    return [skills[skill_id] for skill_id in ids if skill_id in skills]


def tool_configs_by_id(project: ProjectIR) -> ToolRuntimeConfig:
    result: ToolRuntimeConfig = {}
    for tool in workspace_tool_dicts():
        register_tool_config(result, tool)
    for tool in getattr(project, "tools", []) or []:
        register_tool_config(result, model_to_tool_dict(tool))
    for node in project.nodes:
        for tool in json_object_list(node.config.get("toolRegistryJson")):
            register_tool_config(result, tool)
    return result


def mcp_configs_by_id(project: ProjectIR) -> McpRuntimeConfig:
    result: McpRuntimeConfig = {}
    for server in workspace_mcp_dicts():
        register_mcp_config(result, server)
    for server in getattr(project, "mcpServers", []) or []:
        register_mcp_config(result, model_to_mcp_dict(server))
    for node in project.nodes:
        for server in json_object_list(node.config.get("mcpServerRegistryJson")):
            register_mcp_config(result, server)
        for server in json_object_list(node.config.get("mcpServerSnapshotJson")):
            register_mcp_config(result, server)
    return result


def agent_configs_by_id(project: ProjectIR) -> AgentRuntimeConfig:
    result: AgentRuntimeConfig = {}
    for agent in getattr(project, "importedAgents", []) or []:
        register_agent_config(result, model_to_agent_dict(agent))
    for node in project.nodes:
        for agent in json_object_list(node.config.get("agentRegistryJson")):
            register_agent_config(result, agent)
    return result


def model_to_agent_dict(agent: Any) -> dict[str, Any]:
    if isinstance(agent, dict):
        return dict(agent)
    if hasattr(agent, "model_dump"):
        return agent.model_dump(by_alias=True)
    return {
        "id": str(getattr(agent, "id", "") or ""),
        "name": str(getattr(agent, "name", "") or "导入的 Agent"),
        "projectId": str(getattr(agent, "project_id", "") or ""),
        "role": str(getattr(agent, "role", "") or "sub_agent"),
        "description": str(getattr(agent, "description", "") or ""),
    }


def register_agent_config(registry: AgentRuntimeConfig, agent: dict[str, Any]) -> None:
    if not isinstance(agent, dict):
        return
    agent_id = str(agent.get("id") or "").strip()
    project_id = str(agent.get("projectId") or agent.get("project_id") or "").strip()
    name = str(agent.get("name") or "").strip()
    if not agent_id and project_id:
        agent_id = project_id
        agent["id"] = agent_id
    if agent_id:
        registry[agent_id] = agent
    if project_id and project_id not in registry:
        registry[project_id] = agent
    if name and name not in registry:
        registry[name] = agent


def workspace_mcp_dicts() -> list[dict[str, Any]]:
    if not WORKSPACE_MCP_FILE.exists():
        return []
    try:
        data = json.loads(WORKSPACE_MCP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return json_object_list(data) if isinstance(data, list) else []


def model_to_mcp_dict(server: Any) -> dict[str, Any]:
    if isinstance(server, dict):
        return server
    if isinstance(server, list):
        return {}
    if hasattr(server, "model_dump"):
        return server.model_dump(by_alias=True)
    return {
        "id": str(getattr(server, "id", "") or ""),
        "name": str(getattr(server, "name", "") or ""),
        "transport": str(getattr(server, "transport", "") or "stdio"),
        "command": str(getattr(server, "command", "") or ""),
        "argsJson": str(getattr(server, "args_json", "") or "[]"),
        "envJson": str(getattr(server, "env_json", "") or "{}"),
        "envVarsJson": str(getattr(server, "env_vars_json", "") or "[]"),
        "cwd": str(getattr(server, "cwd", "") or ""),
        "url": str(getattr(server, "url", "") or ""),
        "apiKey": str(getattr(server, "api_key", "") or ""),
        "apiKeyEnv": str(getattr(server, "api_key_env", "") or ""),
        "apiKeyMode": str(getattr(server, "api_key_mode", "") or "env"),
        "apiKeyHeader": str(getattr(server, "api_key_header", "") or "Authorization"),
        "apiKeyPrefix": str(getattr(server, "api_key_prefix", "") or "Bearer"),
        "bearerTokenEnvVar": str(getattr(server, "bearer_token_env_var", "") or ""),
        "httpHeadersJson": str(getattr(server, "http_headers_json", "") or "{}"),
        "envHttpHeadersJson": str(getattr(server, "env_http_headers_json", "") or "{}"),
        "enabled": getattr(server, "enabled", True) is not False,
        "startupTimeoutSec": int(getattr(server, "startup_timeout_sec", 10) or 10),
        "toolTimeoutSec": int(getattr(server, "tool_timeout_sec", 60) or 60),
        "enabledToolsJson": str(getattr(server, "enabled_tools_json", "") or "[]"),
        "disabledToolsJson": str(getattr(server, "disabled_tools_json", "") or "[]"),
        "defaultToolsApprovalMode": str(getattr(server, "default_tools_approval_mode", "") or ""),
        "sourceType": str(getattr(server, "source_type", "") or "manual"),
        "sourcePath": str(getattr(server, "source_path", "") or ""),
        "description": str(getattr(server, "description", "") or ""),
    }


def register_mcp_config(registry: McpRuntimeConfig, server: dict[str, Any]) -> None:
    if not isinstance(server, dict):
        return
    normalized = mcp_runtime.normalize_mcp_server_config(server)
    server_id = str(normalized.get("id") or "").strip()
    if server_id:
        registry[server_id] = normalized
    server_name = str(normalized.get("name") or "").strip()
    if server_name and server_name not in registry:
        registry[server_name] = normalized


def selected_mcp_server_configs(config: dict[str, Any], mcp_servers: McpRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = json_string_list(config.get("mcpServerIdsJson"))
    snapshots = json_object_list(config.get("mcpServerRegistryJson"))
    snapshot_by_id = {str(server.get("id") or "").strip(): server for server in snapshots if str(server.get("id") or "").strip()}
    if not selected_ids and snapshots:
        selected_ids = [str(server.get("id") or "").strip() for server in snapshots if str(server.get("id") or "").strip()]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for server_id in selected_ids:
        server = mcp_servers.get(server_id) or snapshot_by_id.get(server_id)
        if not server:
            server = next((item for item in mcp_servers.values() if str(item.get("name") or "") == server_id), None)
        if not server:
            continue
        normalized = mcp_runtime.normalize_mcp_server_config(server)
        key = str(normalized.get("id") or normalized.get("name") or server_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def selected_agent_configs(config: dict[str, Any], agents: AgentRuntimeConfig) -> list[dict[str, Any]]:
    selected_ids = json_string_list(config.get("agentIdsJson"))
    snapshots = json_object_list(config.get("agentRegistryJson"))
    snapshot_by_id = {str(agent.get("id") or "").strip(): agent for agent in snapshots if str(agent.get("id") or "").strip()}
    snapshot_by_project = {str(agent.get("projectId") or "").strip(): agent for agent in snapshots if str(agent.get("projectId") or "").strip()}
    if not selected_ids and snapshots:
        selected_ids = [str(agent.get("id") or agent.get("projectId") or "").strip() for agent in snapshots if str(agent.get("id") or agent.get("projectId") or "").strip()]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id in selected_ids:
        agent = agents.get(agent_id) or snapshot_by_id.get(agent_id) or snapshot_by_project.get(agent_id)
        if not agent:
            continue
        key = str(agent.get("projectId") or agent.get("id") or agent_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(agent)
    return result


def agent_tool_configs(agents: list[dict[str, Any]], project: ProjectIR) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for agent in agents:
        project_id = str(agent.get("projectId") or agent.get("project_id") or "").strip()
        if not project_id or project_id == project.project.id:
            continue
        agent_id = str(agent.get("id") or project_id).strip()
        agent_name = str(agent.get("name") or project_id).strip()
        tool_name = f"agent_{slugify(agent_id or agent_name)}"
        schema = {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "要交给子 Agent 处理的任务内容。"},
                "statePatch": {"type": "object", "description": "可选，传给子 Agent 的额外 state。"},
            },
            "required": ["input"],
            "x-graphic": {
                "kind": "agent_tool",
                "source": "agent",
                "agentId": agent_id,
                "agentName": agent_name,
                "projectId": project_id,
                "role": str(agent.get("role") or "sub_agent"),
            },
        }
        result.append(
            {
                "id": f"agent::{agent_id}",
                "name": tool_name,
                "description": str(agent.get("description") or f"调用子 Agent：{agent_name}"),
                "source": "agent",
                "schemaJson": json.dumps(schema, ensure_ascii=False),
            }
        )
    return result


def mcp_server_for_node(config: dict[str, Any], mcp_servers: McpRuntimeConfig) -> dict[str, Any] | None:
    server_id = str(config.get("serverId") or "").strip()
    server = mcp_servers.get(server_id) if server_id else None
    if not server:
        server_name = str(config.get("serverName") or "").strip()
        server = mcp_servers.get(server_name) if server_name else None
    if not server:
        snapshots = json_object_list(config.get("mcpServerSnapshotJson"))
        server = snapshots[0] if snapshots else None
    if not server:
        server = {
            "id": server_id,
            "name": str(config.get("serverName") or "未命名 MCP"),
            "transport": str(config.get("transport") or "stdio"),
            "command": str(config.get("command") or ""),
            "url": str(config.get("url") or ""),
        }
    normalized = mcp_runtime.normalize_mcp_server_config(server)
    if not normalized.get("id") and server_id:
        normalized["id"] = server_id
    return normalized


def mcp_agent_tool_configs(servers: list[dict[str, Any]], runtime_environment: RuntimeEnvironment) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for server in servers:
        for tool in mcp_runtime.list_mcp_tools(server, runtime_environment, require_enabled=True):
            tools.append(mcp_runtime.make_mcp_agent_tool_config(server, tool))
    return tools


def workspace_tool_dicts() -> list[dict[str, Any]]:
    if not WORKSPACE_TOOLS_FILE.exists():
        return []
    try:
        data = json.loads(WORKSPACE_TOOLS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return json_object_list(data) if isinstance(data, list) else []


def model_to_tool_dict(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return tool
    if isinstance(tool, list):
        return {}
    if hasattr(tool, "model_dump"):
        return tool.model_dump(by_alias=True)
    return {
        "id": str(getattr(tool, "id", "") or ""),
        "name": str(getattr(tool, "name", "") or ""),
        "description": str(getattr(tool, "description", "") or ""),
        "source": str(getattr(tool, "source", "") or ""),
        "schemaJson": str(getattr(tool, "tool_schema", "") or "{}"),
    }


def register_tool_config(registry: ToolRuntimeConfig, tool: dict[str, Any]) -> None:
    if not isinstance(tool, dict):
        return
    tool = _fresh_builtin_tool_config(tool) or tool
    tool_id = str(tool.get("id") or "").strip()
    name = str(tool.get("name") or "").strip()
    if not tool_id and not name:
        return
    normalized = {
        "id": tool_id or name,
        "name": name or tool_id,
        "description": str(tool.get("description") or ""),
        "source": str(tool.get("source") or "python"),
        "schemaJson": str(tool.get("schemaJson") or tool.get("tool_schema") or "{}"),
    }
    registry[normalized["id"]] = normalized
    registry[normalized["name"]] = normalized


def selected_tool_configs(config: dict[str, Any], tools: ToolRuntimeConfig) -> list[dict[str, Any]]:
    from app.runner.tool_runtime.registry import selected_tool_configs as _selected_tool_configs

    return _selected_tool_configs(config, tools)


def fresh_builtin_tool_config(tool: dict[str, Any]) -> dict[str, Any] | None:
    return _fresh_builtin_tool_config(tool)


def _fresh_builtin_tool_config(tool: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None
    schema = parse_json_object(str(tool.get("schemaJson") or tool.get("tool_schema") or "{}"))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    source = str(tool.get("source") or "").strip().lower()
    builtin_id = str(metadata.get("builtinId") or "").strip()
    candidate_ids: list[str] = []
    existing_id = str(tool.get("id") or "").strip()
    if existing_id:
        candidate_ids.append(existing_id)
    if builtin_id:
        candidate_ids.append(f"builtin_{builtin_id}")
    if source == "builtin" or metadata.get("kind") == "builtin_tool" or builtin_id:
        for candidate_id in candidate_ids:
            fresh = builtin_tool_config_by_id(candidate_id)
            if fresh:
                return fresh
    return None


def json_string_list(value: Any) -> list[str]:
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
    if isinstance(parsed, str) and parsed.strip():
        return [parsed.strip()]
    return []


def parse_json_object(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_") or "agent"
