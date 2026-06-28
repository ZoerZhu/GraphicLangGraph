from __future__ import annotations

from . import engine
from .tool_runtime.registry import selected_tool_configs

tool_configs_by_id = engine._tool_configs_by_id
mcp_configs_by_id = engine._mcp_configs_by_id
agent_configs_by_id = engine._agent_configs_by_id
enabled_skills_by_id = engine._enabled_skills_by_id
workspace_tool_dicts = engine._workspace_tool_dicts
workspace_mcp_dicts = engine._workspace_mcp_dicts
selected_mcp_server_configs = engine._selected_mcp_server_configs
selected_agent_configs = engine._selected_agent_configs
mcp_server_for_node = engine._mcp_server_for_node
mcp_agent_tool_configs = engine._mcp_agent_tool_configs
agent_tool_configs = engine._agent_tool_configs
