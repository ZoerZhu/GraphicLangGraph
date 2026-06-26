from __future__ import annotations

import json
import inspect
import re
import textwrap
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from app.builtin_tools import builtin_tool_config_by_id
from app import code_intelligence
from app.ir.sanitization import sanitize_project_payload
from app.ir.schemas import EdgeIR, EdgeKind, NodeIR, NodeType, ProjectIR
from app.project_store import read_project


TYPE_MAP = {
    "str": "str",
    "string": "str",
    "int": "int",
    "integer": "int",
    "float": "float",
    "bool": "bool",
    "boolean": "bool",
    "dict": "dict[str, Any]",
    "object": "dict[str, Any]",
    "list": "list[Any]",
    "array": "list[Any]",
    "any": "Any",
}

PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "baichuan": "BAICHUAN_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "groq": "GROQ_API_KEY",
    "doubao": "DOUBAO_API_KEY",
    "hunyuan": "HUNYUAN_API_KEY",
    "baidu_qianfan": "QIANFAN_API_KEY",
}
MAX_EMBEDDED_AGENT_DEPTH = 3


def generate_project_files(project: ProjectIR) -> dict[str, str]:
    package = package_name(project)
    embedded_projects = _collect_embedded_agent_projects(project)
    embedded_registry = _embedded_agent_registry(project, package, embedded_projects)
    all_projects = [project, *embedded_projects.values()]
    files = {
        "langgraph.json": _langgraph_json(package),
        "pyproject.toml": _pyproject_toml(package, project, all_projects),
        ".env.example": _env_example_for_projects(all_projects),
        "README.md": _readme(project, package, embedded_registry),
        f"src/{package}/__init__.py": "",
        f"src/{package}/config.py": _config_py(),
        f"src/{package}/state.py": _state_py(project),
        f"src/{package}/tools.py": _tools_py(project),
        f"src/{package}/skills.py": _skills_py(project),
        f"src/{package}/mcp_servers.py": _mcp_servers_py(project),
        f"src/{package}/mcp_runtime.py": _mcp_runtime_py(),
        f"src/{package}/embedded_agents.py": _embedded_agents_py(embedded_registry),
        f"src/{package}/nodes.py": _nodes_py(project),
        f"src/{package}/routers.py": _routers_py(project),
        f"src/{package}/graph.py": _graph_py(project),
        "tests/test_graph_smoke.py": _smoke_test(package),
        "flow/project.graph.json": json.dumps(sanitize_project_payload(project), ensure_ascii=False, indent=2),
    }
    for project_id, embedded_project in embedded_projects.items():
        embedded_package = embedded_registry[project_id]["package"]
        files.update(_embedded_project_files(embedded_project, embedded_package, embedded_registry))
    return files


def package_name(project: ProjectIR) -> str:
    source = project.project.id or project.project.name or "generated_agent"
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", source).strip("_").lower()
    if not name:
        name = "generated_agent"
    if name[0].isdigit():
        name = f"agent_{name}"
    return name


def _embedded_project_files(project: ProjectIR, package: str, embedded_registry: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        f"src/{package}/__init__.py": "",
        f"src/{package}/config.py": _config_py(),
        f"src/{package}/state.py": _state_py(project),
        f"src/{package}/tools.py": _tools_py(project),
        f"src/{package}/skills.py": _skills_py(project),
        f"src/{package}/mcp_servers.py": _mcp_servers_py(project),
        f"src/{package}/mcp_runtime.py": _mcp_runtime_py(),
        f"src/{package}/embedded_agents.py": _embedded_agents_py(embedded_registry),
        f"src/{package}/nodes.py": _nodes_py(project),
        f"src/{package}/routers.py": _routers_py(project),
        f"src/{package}/graph.py": _graph_py(project),
        f"flow/embedded/{project.project.id}.graph.json": json.dumps(sanitize_project_payload(project), ensure_ascii=False, indent=2),
    }


def _collect_embedded_agent_projects(project: ProjectIR) -> dict[str, ProjectIR]:
    collected: dict[str, ProjectIR] = {}

    def visit(current: ProjectIR, path: list[str]) -> None:
        current_id = current.project.id
        for project_id in _referenced_agent_project_ids(current):
            if not project_id:
                continue
            if project_id == current_id:
                raise RuntimeError(f"导出工程发现 Agent 自调用：{current.project.name}({current_id})")
            if project_id in path:
                chain = " -> ".join([*path, project_id])
                raise RuntimeError(f"导出工程发现 Agent 循环引用：{chain}")
            if len(path) - 1 >= MAX_EMBEDDED_AGENT_DEPTH:
                chain = " -> ".join([*path, project_id])
                raise RuntimeError(f"内嵌 Agent 依赖深度超过 {MAX_EMBEDDED_AGENT_DEPTH}：{chain}")
            if project_id in collected:
                continue
            child = read_project(project_id)
            collected[project_id] = child
            visit(child, [*path, project_id])

    visit(project, [project.project.id])
    return collected


def _referenced_agent_project_ids(project: ProjectIR) -> list[str]:
    registry = _project_agent_registry(project)
    result: list[str] = []

    def add(project_id: Any) -> None:
        text = str(project_id or "").strip()
        if text and text not in result:
            result.append(text)

    for node in project.nodes:
        if node.type == NodeType.AGENT_REF:
            add(node.config.get("agentProjectId"))
        if node.type == NodeType.AGENT:
            selected_ids = _json_string_list(node.config.get("agentIdsJson"))
            snapshots = _json_object_list(node.config.get("agentRegistryJson"))
            if not selected_ids and snapshots:
                selected_ids = [str(agent.get("id") or agent.get("projectId") or "").strip() for agent in snapshots]
            for agent_id in selected_ids:
                agent = registry.get(agent_id)
                if agent:
                    add(agent.get("projectId") or agent.get("project_id"))
    return result


def _project_agent_registry(project: ProjectIR) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}

    def add(value: Any) -> None:
        if hasattr(value, "model_dump"):
            agent = value.model_dump(by_alias=True)
        elif isinstance(value, dict):
            agent = dict(value)
        else:
            return
        agent_id = str(agent.get("id") or "").strip()
        project_id = str(agent.get("projectId") or agent.get("project_id") or "").strip()
        name = str(agent.get("name") or "").strip()
        if agent_id:
            registry[agent_id] = agent
        if project_id:
            registry.setdefault(project_id, agent)
        if name:
            registry.setdefault(name, agent)

    for agent in getattr(project, "importedAgents", []) or []:
        add(agent)
    for node in project.nodes:
        for agent in _json_object_list(node.config.get("agentRegistryJson")):
            add(agent)
    return registry


def _embedded_agent_registry(root_project: ProjectIR, root_package: str, embedded_projects: dict[str, ProjectIR]) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    used_packages = {root_package}
    for index, (project_id, project) in enumerate(embedded_projects.items(), start=1):
        base = f"{root_package}_embedded_{package_name(project)}"
        package = base
        suffix = 2
        while package in used_packages:
            package = f"{base}_{suffix}"
            suffix += 1
        used_packages.add(package)
        registry[project_id] = {
            "projectId": project_id,
            "name": project.project.name or project_id,
            "package": package,
            "index": index,
        }
    return registry


def py_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not name:
        name = "node"
    if name[0].isdigit():
        name = f"node_{name}"
    return name


def _langgraph_json(package: str) -> str:
    return json.dumps(
        {
            "dependencies": ["."],
            "graphs": {"agent": f"./src/{package}/graph.py:graph"},
            "env": "./.env",
        },
        indent=2,
    )


def _pyproject_toml(package: str, project: ProjectIR, all_projects: list[ProjectIR] | None = None) -> str:
    projects = all_projects or [project]
    dependencies = [
        "langgraph>=0.2.70",
        "langchain>=0.3.0",
        "langchain-core>=0.3.0",
        "langchain-openai>=0.2.0",
        "httpx>=0.27.0",
    ]
    used_builtin_tool_ids: set[str] = set()
    for item in projects:
        used_builtin_tool_ids.update(_used_builtin_tool_ids(item))
    if used_builtin_tool_ids & {"extract_html", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references"}:
        dependencies.append("beautifulsoup4>=4.12.0")
    if used_builtin_tool_ids & {"list_code_symbols", "extract_code_symbol", "chunk_code_semantic"}:
        dependencies.append("tree-sitter>=0.25.0")
        dependencies.append("tree-sitter-language-pack>=1.8.0")
    if any(_uses_mcp(item) for item in projects):
        dependencies.append("mcp>=1.12.4")
    dependency_lines = "\n".join(f'  "{item}",' for item in dependencies)
    return f"""[project]
name = "{package}"
version = "0.1.0"
description = "Generated LangGraph agent from GraphicLangGraph"
requires-python = ">=3.12"
dependencies = [
{dependency_lines}
]

[tool.pytest.ini_options]
pythonpath = ["src"]
"""


def _env_example_for_projects(projects: list[ProjectIR]) -> str:
    keys: dict[str, str] = {}
    used_builtin_tool_ids: set[str] = set()
    for project in projects:
        used_builtin_tool_ids.update(_used_builtin_tool_ids(project))
        for node in project.nodes:
            provider = str(node.config.get("provider", "")).strip()
            if node.type in {NodeType.LLM, NodeType.AGENT, NodeType.AI_ROUTER}:
                env_key = str(node.config.get("apiKeyEnv", "")).strip() or _provider_env_key(provider)
                if env_key:
                    keys[env_key] = "replace_me"
            if node.type == NodeType.MCP_NODE and str(node.config.get("toolSelectionMode") or "").strip().lower() == "model":
                provider = str(node.config.get("toolSelectionModelProvider") or node.config.get("provider") or "").strip()
                env_key = str(node.config.get("toolSelectionApiKeyEnv") or node.config.get("apiKeyEnv") or "").strip() or _provider_env_key(provider)
                if env_key:
                    keys[env_key] = "replace_me"
            if node.type == NodeType.HTTP:
                secret = str(node.config.get("authSecret", "")).strip()
                if secret:
                    keys[secret] = "replace_me"
            if node.type == NodeType.RETRIEVER:
                for env_key in _retriever_env_keys(node.config):
                    keys[env_key] = "replace_me"
    if used_builtin_tool_ids & {"read_file", "list_directory", "read_file_chunk", "search_code", "list_code_symbols", "extract_html", "extract_css_rules", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references", "extract_code_symbol", "chunk_code_semantic"}:
        keys.setdefault("GLG_FILE_TOOL_ROOTS", "./")
        keys.setdefault("GLG_TOOL_MAX_FILE_BYTES", "1048576")
    if used_builtin_tool_ids & {"web_search", "fetch_url"}:
        keys.setdefault("GLG_TOOL_NETWORK_ENABLED", "true")
        keys.setdefault("GLG_TOOL_ALLOWED_HOSTS", "api.duckduckgo.com,html.duckduckgo.com,duckduckgo.com")
        keys.setdefault("GLG_TOOL_MAX_HTTP_BYTES", "262144")
    if used_builtin_tool_ids & {"propose_patch", "apply_patch_set", "rollback_patch_set", "replace_in_file", "write_file", "run_whitelisted_command"}:
        keys.setdefault("GLG_FILE_TOOL_ROOTS", "./")
        keys.setdefault("GLG_TOOL_MAX_FILE_BYTES", "1048576")
        keys.setdefault("GLG_ALLOW_DIRECT_EDITS", "false")
        keys.setdefault("GLG_MAX_PATCH_BYTES", "524288")
        keys.setdefault("GLG_MAX_COMMAND_OUTPUT_BYTES", "262144")
        keys.setdefault("GLG_ALLOWED_COMMANDS", "git status;git diff;git diff --check;npm run build;npm test;npm run lint;python -m pytest;pytest;python -m compileall")
    all_servers = [server for project in projects for server in _mcp_server_dicts(project)]
    for server in all_servers:
        for env_key in _mcp_server_env_keys(server):
            keys[env_key] = "replace_me"
    if any(_uses_mcp(project) for project in projects):
        keys.setdefault("GLG_MCP_NETWORK_ENABLED", "true")
        hosts = sorted({host for server in all_servers for host in [_mcp_server_host(server)] if host})
        if hosts:
            keys.setdefault("GLG_MCP_ALLOWED_HOSTS", ",".join(hosts))
        commands = sorted({command for server in all_servers for command in [_mcp_server_command_profile(server)] if command})
        if commands:
            keys.setdefault("GLG_MCP_ALLOWED_COMMANDS", ";".join(commands))
    if not keys:
        keys["OPENAI_API_KEY"] = "replace_me"
    return "\n".join(f"{key}={value}" for key, value in sorted(keys.items())) + "\n"


def _env_example(project: ProjectIR) -> str:
    return _env_example_for_projects([project])


def _provider_env_key(provider: str) -> str:
    key = provider.strip().lower().replace("-", "_")
    if key in {"", "ollama"}:
        return ""
    if key in PROVIDER_ENV_KEYS:
        return PROVIDER_ENV_KEYS[key]
    return f"{re.sub(r'[^A-Z0-9]+', '_', key.upper()).strip('_')}_API_KEY"


def _retriever_env_keys(config: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    metadata = _parse_json_object(str(config.get("metadataJson", "") or "{}"))
    for candidate in (
        config.get("embeddingApiKeyEnv"),
        metadata.get("embeddingApiKeyEnv"),
        metadata.get("apiKeyEnv"),
        metadata.get("EMBEDDING_API_KEY_ENV"),
    ):
        if candidate and str(candidate).strip():
            keys.add(str(candidate).strip())
    if (config.get("embeddingModel") or metadata.get("embeddingModel") or metadata.get("EMBEDDING_MODEL")) and not keys:
        keys.add("EMBEDDING_API_KEY")
    return keys


def _readme(project: ProjectIR, package: str, embedded_registry: dict[str, dict[str, Any]] | None = None) -> str:
    sample_input = _readme_sample_input(project)
    file_tool_note = ""
    if _used_builtin_tool_ids(project) & {"read_file", "list_directory", "read_file_chunk", "search_code", "list_code_symbols", "extract_html", "extract_css_rules", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references", "extract_code_symbol", "chunk_code_semantic"}:
        file_tool_note = """
## Local file tools

File, code, HTML, and CSS tools read files from the machine running this exported project. Configure `GLG_FILE_TOOL_ROOTS` in `.env` to restrict allowed local roots.
"""
    edit_tool_note = ""
    if _used_builtin_tool_ids(project) & {"propose_patch", "apply_patch_set", "rollback_patch_set", "replace_in_file", "write_file", "run_whitelisted_command"}:
        edit_tool_note = """
## Code editing tools

Editing tools save patch sessions under `.glg_edit_sessions`. Direct writing, patch application, and rollback are disabled unless `GLG_ALLOW_DIRECT_EDITS=true` is set in `.env`. Command execution is limited by `GLG_ALLOWED_COMMANDS`.
"""
    mcp_note = ""
    if _uses_mcp(project):
        mcp_note = """
## MCP servers

MCP nodes and MCP-enabled Agents use the generated MCP runtime. Remote HTTP MCP servers are controlled by `GLG_MCP_NETWORK_ENABLED` and `GLG_MCP_ALLOWED_HOSTS`; local stdio MCP commands are controlled by `GLG_MCP_ALLOWED_COMMANDS`. Secrets are read from environment variables only.
"""
    embedded_note = ""
    if embedded_registry:
        names = ", ".join(str(item.get("name") or item.get("projectId")) for item in embedded_registry.values())
        embedded_note = f"""
## Embedded agents

This export includes snapshot copies of referenced Agent projects: {names}. These snapshots do not sync with later Workspace edits.
"""
    return f"""# {project.project.name}

Generated by GraphicLangGraph.

## Install

```bash
python -m pip install -e .
```

## Run smoke test

```bash
python -m pytest
```

## LangGraph dev

```bash
langgraph dev
```

Graph entry: `{package}.graph:graph`

## Local invoke sample

```bash
python - <<'PY'
from {package}.graph import graph

result = graph.invoke({sample_input})
print(result)
PY
```
{file_tool_note}
{edit_tool_note}
{mcp_note}
{embedded_note}
"""


def _readme_sample_input(project: ProjectIR) -> str:
    field_names = {field.name for field in project.state.fields}
    if "order_id" in field_names:
        return json.dumps(
            {
                "messages": "我想查询订单物流，订单号是 A20260614001",
                "order_id": "A20260614001",
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps({"messages": "你好，请帮我处理这个请求。"}, ensure_ascii=False, indent=2)


def _config_py() -> str:
    return '''from __future__ import annotations

import os
import re
from typing import Any


TEMPLATE_RE = re.compile(r"{{\\s*state\\.([a-zA-Z_][a-zA-Z0-9_\\.\\[\\]]*)\\s*}}")
_MISSING = object()


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def render_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _get_path(state, match.group(1), "")
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            import json
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TEMPLATE_RE.sub(replace, template)


def _get_path(value: Any, path: str, default: Any = None) -> Any:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return value
    resolved = _get_path_parts(value, parts)
    return default if resolved is _MISSING else resolved


def _get_path_parts(value: Any, parts: list[str]) -> Any:
    if not parts:
        return value
    part = parts[0]
    if part.endswith("[]"):
        key = part[:-2]
        collection = _get_path_part(value, key) if key else value
        if not isinstance(collection, list):
            return []
        values: list[Any] = []
        for item in collection:
            child = _get_path_parts(item, parts[1:])
            if child is _MISSING:
                continue
            if isinstance(child, list):
                values.extend(child)
            else:
                values.append(child)
        return values
    next_value = _get_path_part(value, part)
    if next_value is _MISSING:
        return _MISSING
    return _get_path_parts(next_value, parts[1:])


def _get_path_part(value: Any, part: str) -> Any:
    if part == "":
        return value
    if isinstance(value, dict):
        return value.get(part, _MISSING)
    if isinstance(value, list) and part.isdigit():
        index = int(part)
        return value[index] if 0 <= index < len(value) else _MISSING
    return _MISSING
'''


def _state_py(project: ProjectIR) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "from typing_extensions import NotRequired",
        "from langgraph.graph import MessagesState",
        "",
        "",
        "class AgentState(MessagesState):",
    ]
    emitted_fields: set[str] = set()
    for field in project.state.fields:
        field_name = py_name(field.name)
        emitted_fields.add(field_name)
        type_name = TYPE_MAP.get(field.type.lower(), "Any")
        lines.append(f"    {field_name}: NotRequired[{type_name}]")
    if "last_error" not in emitted_fields:
        lines.append("    last_error: NotRequired[dict[str, Any]]")
    if "_glg_error_from" not in emitted_fields:
        lines.append("    _glg_error_from: NotRequired[str]")
    return "\n".join(lines) + "\n"


def _tools_py(project: ProjectIR) -> str:
    configs = _tool_config_dicts(project)
    if not configs:
        return "from __future__ import annotations\n\n\nTOOL_REGISTRY = {}\n"

    lines = [
        "from __future__ import annotations",
        "",
        "import ast",
        "import fnmatch",
        "import hashlib",
        "import html as html_lib",
        "import json",
        "import os",
        "import re",
        "import shlex",
        "import subprocess",
        "import time",
        "from html.parser import HTMLParser",
        "from pathlib import Path",
        "from typing import Any",
        "from urllib.parse import parse_qs, unquote, urlencode, urlparse",
        "from uuid import uuid4",
        "",
        "import httpx",
        "from langchain_core.tools import tool",
        "",
    ]
    registry: dict[str, str] = {}
    emitted_builtins: set[str] = set()
    for config in configs:
        name = str(config.get("name") or config.get("id") or "").strip()
        if not name:
            continue
        schema = _parse_json_object(str(config.get("schemaJson", "{}")))
        metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
        builtin_id = str(metadata.get("builtinId") or "").strip()
        source = str(config.get("source") or "").strip().lower()
        if source == "builtin" and builtin_id in {"web_search", "read_file", "list_directory", "task_plan", "read_file_chunk", "search_code", "list_code_symbols", "extract_html", "extract_css_rules", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references", "extract_code_symbol", "chunk_code_semantic", "fetch_url", "propose_patch", "apply_patch_set", "rollback_patch_set", "replace_in_file", "write_file", "run_whitelisted_command"}:
            for dependency_id in _builtin_export_dependencies(builtin_id):
                if dependency_id not in emitted_builtins:
                    lines.extend(_builtin_tool_function_lines(dependency_id))
                    emitted_builtins.add(dependency_id)
            if builtin_id not in emitted_builtins:
                lines.extend(_builtin_tool_function_lines(builtin_id))
                emitted_builtins.add(builtin_id)
            registry[name] = builtin_id
            registry[builtin_id] = builtin_id
            continue
        description = str(config.get("description") or "").strip()
        function_name = py_name(name)
        description_text = description.strip() or f"Generated tool placeholder for {name}."
        lines.extend(
            [
                "@tool",
                f"def {function_name}(query: str = \"\") -> str:",
                f"    {json.dumps(description_text)}",
                f"    return {json.dumps(name)} + \" called with query=\" + query",
                "",
            ]
        )
        registry[name] = function_name
        registry[function_name] = function_name

    if emitted_builtins:
        lines.extend(_builtin_tool_helper_lines())
    lines.append("TOOL_REGISTRY = {")
    for key, function_name in sorted(registry.items()):
        lines.append(f"    {json.dumps(key)}: {function_name},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _tool_config_dicts(project: ProjectIR) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(config: Any) -> None:
        if hasattr(config, "model_dump"):
            item = config.model_dump(by_alias=True)
        elif isinstance(config, dict):
            item = dict(config)
        else:
            return
        item = _fresh_builtin_tool_config(item) or item
        key = str(item.get("id") or item.get("name") or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        configs.append(item)

    for tool_config in project.tools:
        add(tool_config)
    for node in project.nodes:
        if node.type == NodeType.TOOL:
            for tool_config in _json_object_list(node.config.get("toolRegistryJson")):
                add(tool_config)
            legacy_name = str(node.config.get("toolName", "")).strip()
            if legacy_name:
                add(
                    {
                        "id": legacy_name,
                        "name": legacy_name,
                        "description": str(node.config.get("description", "")),
                        "source": str(node.config.get("source", "json")),
                        "schemaJson": "{}",
                    }
                )
        if node.type == NodeType.AGENT:
            for name in _csv_tool_names(str(node.config.get("tools", ""))):
                add({"id": name, "name": name, "description": f"Declared tool used by Agent node {node.id}.", "source": "json", "schemaJson": "{}"})
    return configs


def _uses_mcp(project: ProjectIR) -> bool:
    if _mcp_server_dicts(project):
        return True
    return any(node.type == NodeType.MCP_NODE for node in project.nodes)


def _mcp_server_dicts(project: ProjectIR) -> list[dict[str, Any]]:
    servers: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        item = _normalize_mcp_server_export_dict(value)
        if not item:
            return
        key = str(item.get("id") or item.get("name") or item.get("url") or item.get("command") or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        servers.append(item)

    for server in getattr(project, "mcpServers", []) or []:
        add(server)

    for node in project.nodes:
        if node.type == NodeType.MCP_NODE:
            for server in _json_object_list(node.config.get("mcpServerSnapshotJson")):
                add(server)
            add(
                {
                    "id": node.config.get("serverId"),
                    "name": node.config.get("serverName") or node.label,
                    "transport": node.config.get("transport"),
                    "command": node.config.get("command"),
                    "url": node.config.get("url"),
                    "enabled": True,
                }
            )
        if node.type == NodeType.AGENT:
            for server in _json_object_list(node.config.get("mcpServerRegistryJson")):
                add(server)
    return servers


def _normalize_mcp_server_export_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        item = value.model_dump(by_alias=True)
    elif isinstance(value, dict):
        item = dict(value)
    else:
        return {}

    transport = str(item.get("transport") or "stdio").strip().lower()
    if transport in {"streamable_http", "sse"}:
        transport = "http"
    normalized = {
        "id": str(item.get("id") or "").strip(),
        "name": str(item.get("name") or item.get("id") or "未命名 MCP").strip(),
        "transport": transport or "stdio",
        "command": str(item.get("command") or "").strip(),
        "argsJson": _json_text_for_export(item.get("argsJson"), item.get("args_json"), fallback=[]),
        "envJson": _json_text_for_export(item.get("envJson"), item.get("env_json"), fallback={}),
        "envVarsJson": _json_text_for_export(item.get("envVarsJson"), item.get("env_vars_json"), fallback=[]),
        "cwd": str(item.get("cwd") or "").strip(),
        "url": str(item.get("url") or "").strip(),
        "apiKey": str(item.get("apiKey") or item.get("api_key") or "").strip(),
        "apiKeyEnv": _safe_env_key(str(item.get("apiKeyEnv") or item.get("api_key_env") or "").strip()),
        "apiKeyMode": str(item.get("apiKeyMode") or item.get("api_key_mode") or "env").strip() or "env",
        "apiKeyHeader": str(item.get("apiKeyHeader") or item.get("api_key_header") or "Authorization").strip(),
        "apiKeyPrefix": str(item.get("apiKeyPrefix") or item.get("api_key_prefix") or "Bearer").strip(),
        "bearerTokenEnvVar": _safe_env_key(str(item.get("bearerTokenEnvVar") or item.get("bearer_token_env_var") or "").strip()),
        "httpHeadersJson": _json_text_for_export(item.get("httpHeadersJson"), item.get("http_headers_json"), fallback={}),
        "envHttpHeadersJson": _json_text_for_export(item.get("envHttpHeadersJson"), item.get("env_http_headers_json"), fallback={}),
        "enabled": item.get("enabled") is not False,
        "startupTimeoutSec": _positive_int(item.get("startupTimeoutSec") or item.get("startup_timeout_sec"), 10),
        "toolTimeoutSec": _positive_int(item.get("toolTimeoutSec") or item.get("tool_timeout_sec"), 60),
        "enabledToolsJson": _json_text_for_export(item.get("enabledToolsJson"), item.get("enabled_tools_json"), fallback=[]),
        "disabledToolsJson": _json_text_for_export(item.get("disabledToolsJson"), item.get("disabled_tools_json"), fallback=[]),
        "defaultToolsApprovalMode": str(item.get("defaultToolsApprovalMode") or item.get("default_tools_approval_mode") or "").strip(),
        "sourceType": str(item.get("sourceType") or item.get("source_type") or "manual").strip() or "manual",
        "sourcePath": str(item.get("sourcePath") or item.get("source_path") or "").strip(),
        "description": str(item.get("description") or "").strip(),
    }
    if normalized["transport"] == "http" and not normalized["url"]:
        return {}
    if normalized["transport"] != "http" and not normalized["command"]:
        return {}
    if normalized["apiKeyMode"] == "direct" and normalized["apiKey"]:
        normalized["apiKeyMode"] = "env"
        normalized["apiKeyEnv"] = normalized["apiKeyEnv"] or _mcp_api_key_env_name(normalized)
        normalized["apiKey"] = ""
    else:
        normalized["apiKey"] = ""
        if not normalized["apiKeyEnv"] and normalized["bearerTokenEnvVar"]:
            normalized["apiKeyEnv"] = normalized["bearerTokenEnvVar"]
            normalized["apiKeyHeader"] = normalized["apiKeyHeader"] or "Authorization"
            normalized["apiKeyPrefix"] = normalized["apiKeyPrefix"] or "Bearer"
    return normalized


def _json_text_for_export(*values: Any, fallback: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        if not text:
            continue
        try:
            json.loads(text)
        except ValueError:
            break
        return text
    return json.dumps(fallback, ensure_ascii=False)


def _mcp_server_env_keys(server: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    bearer = _safe_env_key(str(server.get("bearerTokenEnvVar") or ""))
    if bearer:
        keys.add(bearer)
    api_key_env = _safe_env_key(str(server.get("apiKeyEnv") or ""))
    if api_key_env:
        keys.add(api_key_env)
    for value in _parse_json_object(str(server.get("envHttpHeadersJson") or "{}")).values():
        env_key = _safe_env_key(str(value or "").strip())
        if env_key:
            keys.add(env_key)
    for env_key in _json_string_list(server.get("envVarsJson")):
        safe_key = _safe_env_key(env_key)
        if safe_key:
            keys.add(safe_key)
    return keys


def _mcp_server_host(server: dict[str, Any]) -> str:
    if str(server.get("transport") or "").lower() != "http":
        return ""
    return urlparse(str(server.get("url") or "")).hostname or ""


def _mcp_server_command_profile(server: dict[str, Any]) -> str:
    if str(server.get("transport") or "").lower() == "http":
        return ""
    command = str(server.get("command") or "").strip()
    args = _json_string_list(server.get("argsJson"))
    return " ".join([command, *args]).strip()


def _safe_env_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or "") else ""


def _mcp_api_key_env_name(server: dict[str, Any]) -> str:
    source = str(server.get("id") or server.get("name") or "MCP").upper()
    normalized = re.sub(r"[^A-Z0-9]+", "_", source).strip("_") or "MCP"
    if normalized.endswith("_MCP"):
        return f"{normalized}_API_KEY"
    return f"{normalized}_MCP_API_KEY"


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _fresh_builtin_tool_config(config: dict[str, Any]) -> dict[str, Any] | None:
    schema = _parse_json_object(str(config.get("schemaJson") or config.get("tool_schema") or "{}"))
    metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
    source = str(config.get("source") or "").strip().lower()
    builtin_id = str(metadata.get("builtinId") or "").strip()
    candidate_ids: list[str] = []
    existing_id = str(config.get("id") or "").strip()
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


def _used_builtin_tool_ids(project: ProjectIR) -> set[str]:
    result: set[str] = set()
    for config in _tool_config_dicts(project):
        schema = _parse_json_object(str(config.get("schemaJson", "{}")))
        metadata = schema.get("x-graphic") if isinstance(schema.get("x-graphic"), dict) else {}
        if str(config.get("source") or "").lower() == "builtin" or metadata.get("kind") == "builtin_tool":
            builtin_id = str(metadata.get("builtinId") or "").strip()
            if builtin_id:
                result.add(builtin_id)
    return result


def _builtin_export_dependencies(builtin_id: str) -> list[str]:
    if builtin_id in {"replace_in_file", "write_file"}:
        return ["propose_patch", "apply_patch_set"]
    return []


def _builtin_tool_function_lines(builtin_id: str) -> list[str]:
    if builtin_id == "web_search":
        return [
            "@tool",
            'def web_search(query: str, max_results: int = 5, mode: str = "serp", serp_fallback: bool = True) -> dict[str, Any]:',
            '    """DuckDuckGo 搜索工具；默认解析 HTML SERP，可用 mode=auto 启用 Instant Answer fallback。"""',
            '    if not query.strip():',
            '        raise RuntimeError("web_search 需要 query。")',
            '    mode = (mode or "serp").strip().lower()',
            '    if mode not in {"auto", "instant", "serp"}:',
            '        mode = "serp"',
            "    max_results = max(1, min(int(max_results or 5), 12))",
            "    data: dict[str, Any] = {}",
            "    related_topics: list[dict[str, str]] = []",
            '    if mode != "serp":',
            '        _assert_network_allowed("https://api.duckduckgo.com/", {"api.duckduckgo.com"})',
            '        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1", "skip_disambig": "1"}',
            '        response = httpx.get("https://api.duckduckgo.com/?" + urlencode(params), timeout=12, follow_redirects=True, headers={"Accept": "application/json"})',
            "        response.raise_for_status()",
            "        data = response.json()",
            "        related_topics = _duckduckgo_related_topics(data.get('RelatedTopics'), max_results)",
            "    has_instant = _duckduckgo_has_instant_answer(data, related_topics)",
            "    run_serp = mode == 'serp' or (mode == 'auto' and serp_fallback and not has_instant)",
            "    serp_results = _duckduckgo_serp_results(query, max_results) if run_serp else []",
            '    source = "duckduckgo_serp" if mode == "serp" else "duckduckgo_serp_fallback" if serp_results and not has_instant else "duckduckgo_instant_answer"',
            "    return {",
            '        "query": query,',
            '        "source": source,',
            '        "searchMode": mode,',
            '        "serpFallbackUsed": bool(serp_results and mode != "serp" and not has_instant),',
            '        "answer": data.get("Answer") or "",',
            '        "abstract": data.get("AbstractText") or data.get("Abstract") or "",',
            '        "abstractUrl": data.get("AbstractURL") or "",',
            '        "definition": data.get("Definition") or "",',
            '        "relatedTopics": related_topics,',
            '        "serpResults": serp_results,',
            '        "rawLimited": _compact_value(data),',
            "    }",
            "",
        ]
    if builtin_id == "read_file":
        return [
            "@tool",
            'def read_file(path: str, encoding: str = "utf-8", max_chars: int = 0) -> dict[str, Any]:',
            '    """读取 GLG_FILE_TOOL_ROOTS 白名单目录内的文本文件。"""',
            "    file_path = _resolve_allowed_path(path)",
            '    if not file_path.is_file():',
            '        raise RuntimeError(f"不是可读取文件：{file_path}")',
            "    max_bytes = _max_file_bytes()",
            '    content = file_path.read_bytes()[: max_bytes + 1]',
            "    truncated = len(content) > max_bytes",
            "    if truncated:",
            "        content = content[:max_bytes]",
            '    text = content.decode(encoding or "utf-8", errors="replace")',
            "    if max_chars and max_chars > 0 and len(text) > max_chars:",
            "        text = text[:max_chars]",
            "        truncated = True",
            '    return {"path": str(file_path), "size": file_path.stat().st_size, "encoding": encoding, "truncated": truncated, "content": text}',
            "",
        ]
    if builtin_id == "list_directory":
        return [
            "@tool",
            'def list_directory(path: str, pattern: str = "*", recursive: bool = False, max_entries: int = 100) -> dict[str, Any]:',
            '    """列出 GLG_FILE_TOOL_ROOTS 白名单目录内的文件和文件夹。"""',
            "    directory = _resolve_allowed_path(path)",
            '    if not directory.is_dir():',
            '        raise RuntimeError(f"不是可列出的目录：{directory}")',
            "    entries = []",
            "    iterator = directory.rglob(pattern or '*') if recursive else directory.glob(pattern or '*')",
            "    for item in iterator:",
            "        resolved = item.resolve()",
            "        if not _is_relative_to(resolved, directory):",
            "            continue",
            "        stat = resolved.stat()",
            '        entries.append({"name": resolved.name, "path": str(resolved), "relativePath": resolved.relative_to(directory).as_posix(), "type": "directory" if resolved.is_dir() else "file", "size": stat.st_size if resolved.is_file() else 0})',
            "        if len(entries) >= max(1, min(int(max_entries or 100), 500)):",
            "            break",
            '    return {"path": str(directory), "pattern": pattern or "*", "recursive": recursive, "entries": entries, "truncated": len(entries) >= max(1, min(int(max_entries or 100), 500))}',
            "",
        ]
    if builtin_id == "task_plan":
        return textwrap.dedent(
            '''
            @tool
            def task_plan(tasks: list[dict[str, Any]], sourceGoal: str = "", maxTasks: int = 6) -> dict[str, Any]:
                """提交 Task Splitter 可解析的结构化任务计划。"""
                if not isinstance(tasks, list):
                    raise RuntimeError("task_plan 需要 tasks 数组。")
                limit = max(1, min(int(maxTasks or 6), 10))
                normalized: list[dict[str, Any]] = []
                for index, item in enumerate(tasks[:limit], start=1):
                    if isinstance(item, str):
                        task = {"goal": item}
                    elif isinstance(item, dict):
                        task = dict(item)
                    else:
                        continue
                    goal = str(task.get("goal") or task.get("description") or task.get("task") or sourceGoal or "").strip()
                    title = str(task.get("title") or task.get("name") or goal or f"任务 {index}").strip()
                    target_files = task.get("targetFiles") if "targetFiles" in task else task.get("target_files")
                    suggested_tools = task.get("suggestedTools") if "suggestedTools" in task else task.get("suggested_tools")
                    if isinstance(target_files, str):
                        target_files = [part.strip() for part in re.split(r"[,，\\n]+", target_files) if part.strip()]
                    elif isinstance(target_files, list):
                        target_files = [str(part).strip() for part in target_files if str(part).strip()]
                    else:
                        target_files = []
                    if isinstance(suggested_tools, str):
                        suggested_tools = [part.strip() for part in re.split(r"[,，\\n]+", suggested_tools) if part.strip()]
                    elif isinstance(suggested_tools, list):
                        suggested_tools = [str(part).strip() for part in suggested_tools if str(part).strip()]
                    else:
                        suggested_tools = []
                    if not goal and not title:
                        continue
                    normalized.append({"id": str(task.get("id") or f"task_{index}"), "title": title[:160] or f"任务 {index}", "goal": goal or title, "targetFiles": target_files, "suggestedTools": suggested_tools, "status": "pending"})
                if not normalized:
                    raise RuntimeError("task_plan 至少需要一个包含 goal 或 title 的任务。")
                return {"format": "task_splitter_v1", "taskCount": len(normalized), "tasks": normalized}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "read_file_chunk":
        return textwrap.dedent(
            '''
            @tool
            def read_file_chunk(path: str, start_line: int = 0, end_line: int = 0, offset: int = 0, max_chars: int = 4000, encoding: str = "utf-8") -> dict[str, Any]:
                """按行号或字符 offset 分片读取 GLG_FILE_TOOL_ROOTS 白名单目录内的文本文件。"""
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可读取文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"read_file_chunk 只读取文本文件，疑似二进制文件：{file_path}")
                max_chars = max(1, min(int(max_chars or 4000), _max_file_bytes()))
                if start_line and start_line > 0:
                    return _read_file_chunk_by_lines(file_path, int(start_line), int(end_line or 0) or None, max_chars, encoding or "utf-8")
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                total_lines = _count_file_lines(file_path, encoding or "utf-8")
                offset = max(0, int(offset or 0))
                end = min(len(text), offset + max_chars)
                content = text[offset:end] if offset < len(text) else ""
                truncated = source_truncated or end < len(text)
                start_line_for_offset = text[:offset].count("\\n") + 1 if text else 1
                end_line_for_offset = start_line_for_offset + content.count("\\n") if content else start_line_for_offset
                return {"path": str(file_path), "size": file_path.stat().st_size, "encoding": encoding, "startLine": start_line_for_offset, "endLine": end_line_for_offset, "totalLines": total_lines, "offset": offset, "nextOffset": end if truncated and end > offset else None, "truncated": truncated, "content": content}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "search_code":
        return textwrap.dedent(
            '''
            @tool
            def search_code(query: str, root: str = ".", regex: bool = False, file_glob: str = "*", context_lines: int = 0, max_results: int = 50, case_sensitive: bool = False, encoding: str = "utf-8") -> dict[str, Any]:
                """在 GLG_FILE_TOOL_ROOTS 白名单目录内按关键词或正则搜索代码文本。"""
                if not query.strip():
                    raise RuntimeError("search_code 需要 query。")
                root_path = _resolve_allowed_path(root or ".")
                context_lines = max(0, min(int(context_lines or 0), 8))
                max_results = max(1, min(int(max_results or 50), 200))
                pattern = None
                if regex:
                    pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
                matches: list[dict[str, Any]] = []
                scanned_files = 0
                skipped_binary = 0
                needle = query if case_sensitive else query.lower()
                for file_path in _iter_search_files(root_path, file_glob or "*"):
                    if len(matches) >= max_results:
                        break
                    if _is_binary_file(file_path):
                        skipped_binary += 1
                        continue
                    scanned_files += 1
                    text, file_truncated = _read_text_limited(file_path, encoding or "utf-8")
                    lines = text.splitlines()
                    for index, line in enumerate(lines):
                        if pattern:
                            match = pattern.search(line)
                            if not match:
                                continue
                            column = match.start() + 1
                        else:
                            haystack = line if case_sensitive else line.lower()
                            found = haystack.find(needle)
                            if found < 0:
                                continue
                            column = found + 1
                        matches.append({"path": str(file_path), "relativePath": _safe_relative_path(file_path, root_path), "line": index + 1, "column": column, "text": line, "before": lines[max(0, index - context_lines):index] if context_lines else [], "after": lines[index + 1:index + 1 + context_lines] if context_lines else [], "fileTruncated": file_truncated})
                        if len(matches) >= max_results:
                            break
                return {"root": str(root_path), "query": query, "regex": regex, "fileGlob": file_glob or "*", "matches": matches, "scannedFiles": scanned_files, "skippedBinaryFiles": skipped_binary, "truncated": len(matches) >= max_results}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "list_code_symbols":
        return textwrap.dedent(
            '''
            @tool
            def list_code_symbols(path: str, language: str = "", max_symbols: int = 100, encoding: str = "utf-8") -> dict[str, Any]:
                """列出代码或 HTML 文件中的函数、类、方法、组件、标签等符号摘要。"""
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可分析文件：{file_path}")
                if _is_binary_file(file_path):
                    return {"path": str(file_path), "language": "binary", "symbols": [], "warnings": ["疑似二进制文件，已跳过。"]}
                max_symbols = max(1, min(int(max_symbols or 100), 500))
                detected = _detect_code_language(file_path, language or "")
                text, truncated = _read_text_limited(file_path, encoding or "utf-8")
                symbols, warnings = glg_semantic_symbols(text, detected, max_symbols)
                warnings = list(warnings or [])
                if truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，符号列表可能不完整。")
                return {"path": str(file_path), "language": detected, "symbols": symbols[:max_symbols], "truncated": truncated or len(symbols) > max_symbols, "warnings": warnings}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "extract_html":
        return textwrap.dedent(
            '''
            @tool
            def extract_html(path: str, selector: str, mode: str = "html", max_results: int = 20, max_chars: int = 4000, encoding: str = "utf-8") -> dict[str, Any]:
                """按 CSS selector 从 GLG_FILE_TOOL_ROOTS 白名单目录内的 HTML 文件抽取局部内容。"""
                if not selector.strip():
                    raise RuntimeError("extract_html 需要 selector。")
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可抽取 HTML 的文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"extract_html 只读取文本 HTML 文件，疑似二进制文件：{file_path}")
                try:
                    from bs4 import BeautifulSoup
                except ImportError as exc:
                    raise RuntimeError("缺少 beautifulsoup4，请安装导出项目依赖后重试。") from exc
                mode = (mode or "html").strip().lower()
                if mode not in {"html", "text", "attributes"}:
                    mode = "html"
                max_results = max(1, min(int(max_results or 20), 100))
                max_chars = max(1, min(int(max_chars or 4000), _max_file_bytes()))
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                soup = BeautifulSoup(text, "html.parser")
                selected = soup.select(selector)
                matches = []
                warnings = []
                search_from = 0
                truncated = source_truncated or len(selected) > max_results
                for index, element in enumerate(selected[:max_results], start=1):
                    outer_html = str(element)
                    start_line, end_line, search_from = _best_effort_html_lines(text, outer_html, search_from)
                    if start_line is None:
                        sourceline = getattr(element, "sourceline", None)
                        if isinstance(sourceline, int):
                            start_line = sourceline
                            end_line = sourceline
                    item: dict[str, Any] = {"index": index, "selector": selector, "startLine": start_line, "endLine": end_line}
                    if mode == "text":
                        value = re.sub(r"\\s+", " ", element.get_text(" ", strip=True)).strip()
                        item["text"], was_truncated = _clip_text(value, max_chars)
                    elif mode == "attributes":
                        item["attributes"] = {str(key): (" ".join(value) if isinstance(value, list) else str(value)) for key, value in element.attrs.items()}
                        was_truncated = False
                    else:
                        item["html"], was_truncated = _clip_text(outer_html, max_chars)
                    if was_truncated:
                        item["truncated"] = True
                        truncated = True
                    matches.append(item)
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，HTML 抽取结果可能不完整。")
                return {"path": str(file_path), "selector": selector, "mode": mode, "matches": matches, "count": len(matches), "totalMatched": len(selected), "truncated": truncated, "warnings": warnings}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "extract_css_rules":
        return textwrap.dedent(
            '''
            @tool
            def extract_css_rules(path: str, selector: str = "", property: str = "", query: str = "", max_results: int = 50, encoding: str = "utf-8") -> dict[str, Any]:
                """从 GLG_FILE_TOOL_ROOTS 白名单目录内的 CSS 文件按 selector、property 或 query 抽取规则。"""
                selector = (selector or "").strip()
                property_name = (property or "").strip()
                query = (query or "").strip()
                if not selector and not property_name and not query:
                    raise RuntimeError("extract_css_rules 需要 selector、property 或 query 至少一个参数。")
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可抽取 CSS 的文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"extract_css_rules 只读取文本 CSS 文件，疑似二进制文件：{file_path}")
                max_results = max(1, min(int(max_results or 50), 200))
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                rules, parse_warnings = _parse_css_rules(text)
                selector_key = _normalize_css_selector(selector) if selector else ""
                property_key = property_name.lower()
                query_key = query.lower()
                matched = []
                total_matched = 0
                for rule in rules:
                    if selector_key and selector_key not in {_normalize_css_selector(item) for item in rule["selectors"]}:
                        continue
                    if property_key and not any(str(name).lower() == property_key for name in rule["declarations"].keys()):
                        continue
                    if query_key and query_key not in str(rule["css"]).lower():
                        continue
                    total_matched += 1
                    if len(matched) < max_results:
                        matched.append(rule)
                warnings = list(parse_warnings)
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，CSS 抽取结果可能不完整。")
                return {"path": str(file_path), "selector": selector, "property": property_name, "query": query, "rules": matched, "count": len(matched), "totalMatched": total_matched, "truncated": source_truncated or total_matched > max_results, "warnings": warnings}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "extract_html_by_text":
        return textwrap.dedent(
            '''
            @tool
            def extract_html_by_text(path: str, query: str, regex: bool = False, mode: str = "html", case_sensitive: bool = False, max_results: int = 20, max_chars: int = 4000, encoding: str = "utf-8") -> dict[str, Any]:
                """按可见文本、关键词或正则从 GLG_FILE_TOOL_ROOTS 白名单目录内的 HTML 文件定位并抽取局部节点。"""
                if not query.strip():
                    raise RuntimeError("extract_html_by_text 需要 query。")
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可抽取 HTML 的文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"extract_html_by_text 只读取文本 HTML 文件，疑似二进制文件：{file_path}")
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                result = glg_extract_html_by_text(text, query, regex, mode, max(1, min(int(max_results or 20), 100)), max(1, min(int(max_chars or 4000), _max_file_bytes())), case_sensitive)
                warnings = list(result.get("warnings") or [])
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，HTML 文本抽取结果可能不完整。")
                result["path"] = str(file_path)
                result["encoding"] = encoding
                result["truncated"] = bool(result.get("truncated") or source_truncated)
                result["warnings"] = warnings
                return result

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "extract_css_for_html":
        return textwrap.dedent(
            '''
            @tool
            def extract_css_for_html(path: str, selector: str, html_path: str = "", max_results: int = 50, encoding: str = "utf-8") -> dict[str, Any]:
                """按 HTML selector、id 或 class 从 CSS 文件中查找相关样式规则。"""
                if not selector.strip():
                    raise RuntimeError("extract_css_for_html 需要 selector。")
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可抽取 CSS 的文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"extract_css_for_html 只读取文本 CSS 文件，疑似二进制文件：{file_path}")
                css_text, css_truncated = _read_text_limited(file_path, encoding or "utf-8")
                html_text = ""
                resolved_html_path = None
                html_truncated = False
                if html_path.strip():
                    resolved_html_path = _resolve_allowed_path(html_path)
                    if not resolved_html_path.is_file():
                        raise RuntimeError(f"不是可分析 HTML 的文件：{resolved_html_path}")
                    if _is_binary_file(resolved_html_path):
                        raise RuntimeError(f"extract_css_for_html 只读取文本 HTML 文件，疑似二进制文件：{resolved_html_path}")
                    html_text, html_truncated = _read_text_limited(resolved_html_path, encoding or "utf-8")
                result = glg_extract_css_for_html(css_text, selector, html_text, max(1, min(int(max_results or 50), 200)))
                warnings = list(result.get("warnings") or [])
                if css_truncated:
                    warnings.append("CSS 文件内容超过当前运行环境单次读取大小，样式匹配可能不完整。")
                if html_truncated:
                    warnings.append("HTML 文件内容超过当前运行环境单次读取大小，元素 token 推导可能不完整。")
                result["path"] = str(file_path)
                result["htmlPath"] = str(resolved_html_path) if resolved_html_path else ""
                result["encoding"] = encoding
                result["truncated"] = bool(result.get("truncated") or css_truncated or html_truncated)
                result["warnings"] = warnings
                return result

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "summarize_page_structure":
        return textwrap.dedent(
            '''
            @tool
            def summarize_page_structure(path: str, max_items: int = 50, encoding: str = "utf-8") -> dict[str, Any]:
                """摘要 HTML 页面结构，包括标题、区域、表单、按钮、链接、图片、脚本和样式引用。"""
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可分析 HTML 的文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"summarize_page_structure 只读取文本 HTML 文件，疑似二进制文件：{file_path}")
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                result = glg_summarize_page_structure(text, max(1, min(int(max_items or 50), 200)))
                warnings = list(result.get("warnings") or [])
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，页面结构摘要可能不完整。")
                result["path"] = str(file_path)
                result["encoding"] = encoding
                result["truncated"] = source_truncated
                result["warnings"] = warnings
                return result

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "resolve_asset_references":
        return textwrap.dedent(
            '''
            @tool
            def resolve_asset_references(path: str, language: str = "", max_results: int = 200, encoding: str = "utf-8") -> dict[str, Any]:
                """从 HTML/CSS 文件中提取本地资源引用和外链，并解析相对路径是否位于 GLG_FILE_TOOL_ROOTS 白名单目录内。"""
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可扫描资源引用的文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"resolve_asset_references 只读取文本 HTML/CSS 文件，疑似二进制文件：{file_path}")
                detected = _detect_code_language(file_path, language or "")
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                result = glg_asset_references(text, detected, max(1, min(int(max_results or 200), 500)))
                references = [_enrich_asset_reference(item, file_path) for item in result.get("references", []) if isinstance(item, dict)]
                warnings = list(result.get("warnings") or [])
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，资源引用可能不完整。")
                return {"path": str(file_path), "language": detected, "references": references, "count": len(references), "totalMatched": result.get("totalMatched", len(references)), "truncated": bool(result.get("truncated") or source_truncated), "warnings": warnings}

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "extract_code_symbol":
        return textwrap.dedent(
            '''
            @tool
            def extract_code_symbol(path: str, symbol: str, kind: str = "any", include_context: bool = False, max_chars: int = 4000, language: str = "", encoding: str = "utf-8") -> dict[str, Any]:
                """按函数、类、方法、组件、HTML 节点或 CSS selector 精确抽取 GLG_FILE_TOOL_ROOTS 白名单目录内的代码块。"""
                if not symbol.strip():
                    raise RuntimeError("extract_code_symbol 需要 symbol。")
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可分析文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"extract_code_symbol 只读取文本代码文件，疑似二进制文件：{file_path}")
                detected = _detect_code_language(file_path, language or "")
                max_chars = max(1, min(int(max_chars or 4000), _max_file_bytes()))
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                result = glg_extract_code_symbol(text, detected, symbol, kind or "any", max_chars, bool(include_context))
                if not result.get("found"):
                    alternatives = result.get("alternatives")
                    hint = ""
                    if isinstance(alternatives, list) and alternatives:
                        names = ", ".join(str(item.get("name") or "") for item in alternatives[:8] if isinstance(item, dict))
                        hint = f"。候选符号：{names}" if names else ""
                    raise RuntimeError(f"未找到符号：{symbol}{hint}")
                warnings = list(result.get("warnings") or [])
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，符号抽取结果可能不完整。")
                result["path"] = str(file_path)
                result["encoding"] = encoding
                result["warnings"] = warnings
                result["truncated"] = bool(result.get("truncated") or source_truncated)
                result.pop("found", None)
                return result

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "chunk_code_semantic":
        return textwrap.dedent(
            '''
            @tool
            def chunk_code_semantic(path: str, language: str = "", max_chars: int = 4000, max_chunks: int = 80, include_content: bool = False, encoding: str = "utf-8") -> dict[str, Any]:
                """按函数、类、方法、组件、HTML 节点或 CSS 规则把大代码文件拆成语义片段。"""
                file_path = _resolve_allowed_path(path)
                if not file_path.is_file():
                    raise RuntimeError(f"不是可分析文件：{file_path}")
                if _is_binary_file(file_path):
                    raise RuntimeError(f"chunk_code_semantic 只读取文本代码文件，疑似二进制文件：{file_path}")
                detected = _detect_code_language(file_path, language or "")
                max_chars = max(1, min(int(max_chars or 4000), _max_file_bytes()))
                max_chunks = max(1, min(int(max_chunks or 80), 500))
                text, source_truncated = _read_text_limited(file_path, encoding or "utf-8")
                result = glg_chunk_code_semantic(text, detected, max_chars, max_chunks, bool(include_content))
                warnings = list(result.get("warnings") or [])
                if source_truncated:
                    warnings.append("文件内容超过当前运行环境单次读取大小，语义分片可能不完整。")
                result["path"] = str(file_path)
                result["encoding"] = encoding
                result["truncated"] = bool(result.get("truncated") or source_truncated)
                result["warnings"] = warnings
                return result

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "fetch_url":
        return [
            "@tool",
            "def fetch_url(url: str, max_chars: int = 0) -> dict[str, Any]:",
            '    """在 GLG_TOOL_NETWORK_ENABLED=true 时发起 HTTP GET 并返回文本内容。"""',
            "    _assert_network_allowed(url)",
            "    max_bytes = _max_http_bytes()",
            "    response = httpx.get(url, timeout=15, follow_redirects=True)",
            "    response.raise_for_status()",
            "    body = response.content[: max_bytes + 1]",
            "    truncated = len(body) > max_bytes",
            "    if truncated:",
            "        body = body[:max_bytes]",
            '    text = body.decode(response.encoding or "utf-8", errors="replace")',
            "    if max_chars and max_chars > 0 and len(text) > max_chars:",
            "        text = text[:max_chars]",
            "        truncated = True",
            '    return {"url": str(response.url), "statusCode": response.status_code, "contentType": response.headers.get("content-type", ""), "truncated": truncated, "text": text}',
            "",
        ]
    if builtin_id == "propose_patch":
        return textwrap.dedent(
            '''
            @tool
            def propose_patch(diff: str = "", path: str = "", original: str = "", replacement: str = "", content: str = "", overwrite: bool = False, changes_json: str = "", project_id: str = "", run_id: str = "") -> dict[str, Any]:
                """生成待审批代码补丁，不直接写入源码。支持 unified diff 或 path/original/replacement 结构化修改。"""
                raw_diff = _strip_code_fence(diff or "")
                if len(raw_diff.encode("utf-8")) > _max_patch_bytes():
                    raise RuntimeError(f"patch 超过限制：{_max_patch_bytes()} bytes")
                if raw_diff.strip():
                    changes = _edit_parse_unified_diff(raw_diff)
                    diff_text = raw_diff
                else:
                    changes = _edit_structured_changes(path, original, replacement, content, bool(overwrite), changes_json)
                    diff_text = json.dumps([{key: value for key, value in item.items() if key != "content"} for item in changes], ensure_ascii=False, indent=2)
                    if len(diff_text.encode("utf-8")) > _max_patch_bytes():
                        raise RuntimeError(f"patch 超过限制：{_max_patch_bytes()} bytes")
                if not changes:
                    raise RuntimeError("propose_patch 需要 diff，或 path/original/replacement，或 changes_json。")
                patch_id = "patch_" + uuid4().hex[:12]
                files = []
                conflicts = []
                for change in changes:
                    resolved = _resolve_allowed_path(str(change["path"]))
                    exists = resolved.exists()
                    if exists:
                        _ensure_edit_text_file(resolved)
                        current = resolved.read_text(encoding=str(change.get("encoding") or "utf-8"), errors="replace")
                        conflict = _edit_change_conflict(change, current)
                        if conflict:
                            conflicts.append(f"{_safe_display_path(resolved)}: {conflict}")
                    files.append({"path": _safe_display_path(resolved), "absolutePath": str(resolved), "exists": exists, "baseHash": _edit_file_hash(resolved) if exists else "", "changeKind": str(change.get("kind") or ""), "hunkCount": len(change.get("hunks") or []), "summary": _edit_change_summary(change)})
                session = {"patchId": patch_id, "projectId": project_id, "runId": run_id, "status": "blocked" if conflicts else "proposed", "files": files, "changes": changes, "diff": diff_text, "conflicts": conflicts, "rollbackId": "", "createdAt": time.time(), "appliedAt": "", "backups": []}
                _edit_write_session(session)
                return _edit_public_session(session)

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "apply_patch_set":
        return textwrap.dedent(
            '''
            @tool
            def apply_patch_set(patch_id: str) -> dict[str, Any]:
                """应用 propose_patch 生成的补丁。导出项目默认禁用，需 GLG_ALLOW_DIRECT_EDITS=true。"""
                _require_export_direct_edits()
                session = _edit_read_session(patch_id)
                if session.get("status") == "applied":
                    return _edit_public_session(session)
                if session.get("status") not in {"proposed", "blocked"}:
                    raise RuntimeError(f"当前 patch 状态不能应用：{session.get('status')}")
                changes = session.get("changes") if isinstance(session.get("changes"), list) else []
                files = session.get("files") if isinstance(session.get("files"), list) else []
                planned = []
                for change, file_info in zip(changes, files):
                    target = _resolve_allowed_path(str(change["path"]))
                    exists_before = target.exists()
                    current_hash = _edit_file_hash(target) if exists_before else ""
                    if current_hash != str(file_info.get("baseHash") or ""):
                        raise RuntimeError(f"文件已变化，拒绝应用过期 patch：{_safe_display_path(target)}")
                    before_text = target.read_text(encoding=str(change.get("encoding") or "utf-8"), errors="replace") if exists_before else ""
                    after_text = _edit_apply_change(change, before_text, exists_before)
                    planned.append({"path": target, "beforeExists": exists_before, "beforeText": before_text, "afterText": after_text})
                rollback_id = "rollback_" + uuid4().hex[:12]
                backup_dir = _edit_session_dir() / "backups" / rollback_id
                backup_dir.mkdir(parents=True, exist_ok=True)
                backups = []
                try:
                    for index, item in enumerate(planned):
                        backup_path = backup_dir / f"{index}.bak"
                        if item["beforeExists"]:
                            backup_path.write_text(item["beforeText"], encoding="utf-8")
                        backups.append({"path": _safe_display_path(item["path"]), "absolutePath": str(item["path"]), "existed": bool(item["beforeExists"]), "backupPath": str(backup_path) if item["beforeExists"] else ""})
                    for item in planned:
                        item["path"].parent.mkdir(parents=True, exist_ok=True)
                        item["path"].write_text(item["afterText"], encoding="utf-8")
                except Exception:
                    for item in planned:
                        if item["beforeExists"]:
                            item["path"].write_text(item["beforeText"], encoding="utf-8")
                        elif item["path"].exists():
                            item["path"].unlink()
                    raise
                session["status"] = "applied"
                session["rollbackId"] = rollback_id
                session["appliedAt"] = time.time()
                session["backups"] = backups
                _edit_write_session(session)
                return _edit_public_session(session)

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "rollback_patch_set":
        return textwrap.dedent(
            '''
            @tool
            def rollback_patch_set(rollback_id: str) -> dict[str, Any]:
                """回滚本工具生成的已应用补丁。导出项目默认禁用，需 GLG_ALLOW_DIRECT_EDITS=true。"""
                _require_export_direct_edits()
                session = _edit_read_session_by_rollback(rollback_id)
                if session.get("status") != "applied":
                    raise RuntimeError("只有已应用的 patch 可以回滚。")
                for backup in session.get("backups") or []:
                    target = Path(str(backup.get("absolutePath") or ""))
                    if backup.get("existed"):
                        backup_path = Path(str(backup.get("backupPath") or ""))
                        if not backup_path.exists():
                            raise RuntimeError(f"回滚备份不存在：{backup_path}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
                    elif target.exists():
                        target.unlink()
                session["status"] = "rolled_back"
                session["rolledBackAt"] = time.time()
                _edit_write_session(session)
                return _edit_public_session(session)

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "replace_in_file":
        return textwrap.dedent(
            '''
            @tool
            def replace_in_file(path: str, search: str, replace: str = "", expected_occurrences: int = 1) -> dict[str, Any]:
                """高级直接写入工具：替换白名单目录内文本文件内容。需 GLG_ALLOW_DIRECT_EDITS=true。"""
                _require_export_direct_edits()
                if not path or not search:
                    raise RuntimeError("replace_in_file 需要 path 和 search。")
                patch = propose_patch.invoke({"path": path, "original": search, "replacement": replace})
                if patch.get("conflicts"):
                    raise RuntimeError("替换内容校验失败：" + "；".join(str(item) for item in patch["conflicts"]))
                session = _edit_read_session(str(patch["patchId"]))
                for change in session.get("changes") or []:
                    if change.get("kind") == "replace":
                        change["expectedOccurrences"] = int(expected_occurrences)
                _edit_write_session(session)
                return apply_patch_set.invoke({"patch_id": str(patch["patchId"])})

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "write_file":
        return textwrap.dedent(
            '''
            @tool
            def write_file(path: str, content: str = "", overwrite: bool = False) -> dict[str, Any]:
                """高级直接写入工具：创建或覆盖白名单目录内文本文件。需 GLG_ALLOW_DIRECT_EDITS=true。"""
                _require_export_direct_edits()
                patch = propose_patch.invoke({"path": path, "content": content, "overwrite": overwrite})
                if patch.get("conflicts"):
                    raise RuntimeError("写入内容校验失败：" + "；".join(str(item) for item in patch["conflicts"]))
                return apply_patch_set.invoke({"patch_id": str(patch["patchId"])})

            '''
        ).strip("\n").splitlines() + [""]
    if builtin_id == "run_whitelisted_command":
        return textwrap.dedent(
            '''
            @tool
            def run_whitelisted_command(command: str, cwd: str = ".", timeout_seconds: int = 60) -> dict[str, Any]:
                """在允许目录内运行白名单验证命令。"""
                args = shlex.split(command or "")
                if not args:
                    raise RuntimeError("run_whitelisted_command 需要 command。")
                _ensure_export_command_allowed(args)
                workdir = _resolve_allowed_path(cwd or ".")
                if not workdir.is_dir():
                    workdir = workdir.parent
                timeout = max(1, min(int(timeout_seconds or 60), 300))
                started = time.perf_counter()
                try:
                    completed = subprocess.run(args, cwd=str(workdir), capture_output=True, text=True, timeout=timeout, shell=False)
                    timed_out = False
                    exit_code = completed.returncode
                    stdout_source = completed.stdout
                    stderr_source = completed.stderr
                except subprocess.TimeoutExpired as exc:
                    timed_out = True
                    exit_code = -1
                    stdout_source = exc.stdout or ""
                    stderr_source = exc.stderr or f"命令超时：{timeout}s"
                duration = round((time.perf_counter() - started) * 1000, 2)
                stdout, stdout_truncated = _clip_command_output(stdout_source)
                stderr, stderr_truncated = _clip_command_output(stderr_source)
                return {"command": args, "cwd": str(workdir), "exitCode": exit_code, "stdout": stdout, "stderr": stderr, "durationMs": duration, "timedOut": timed_out, "truncated": stdout_truncated or stderr_truncated}

            '''
        ).strip("\n").splitlines() + [""]
    return []


def _builtin_tool_helper_lines() -> list[str]:
    return [
        "CODE_TOOL_EXCLUDED_DIRS = {'.git', '.hg', '.svn', 'node_modules', 'dist', 'build', '.venv', 'venv', '__pycache__', '.next', '.turbo', 'coverage'}",
        "CODE_TOOL_BINARY_CHECK_BYTES = 4096",
        "",
        "def _edit_session_dir() -> Path:",
        "    path = Path(os.getenv('GLG_EDIT_SESSIONS_DIR', '.glg_edit_sessions')).expanduser().resolve()",
        "    path.mkdir(parents=True, exist_ok=True)",
        "    return path",
        "",
        "def _max_patch_bytes() -> int:",
        "    return max(1, min(int(os.getenv('GLG_MAX_PATCH_BYTES', '524288')), 8 * 1024 * 1024))",
        "",
        "def _edit_safe_id(value: str) -> str:",
        "    safe = re.sub(r'[^A-Za-z0-9_-]+', '_', value or '').strip('_')",
        "    if not safe:",
        "        raise RuntimeError('patchId 无效。')",
        "    return safe",
        "",
        "def _edit_write_session(session: dict[str, Any]) -> None:",
        "    (_edit_session_dir() / f\"{_edit_safe_id(str(session['patchId']))}.json\").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding='utf-8')",
        "",
        "def _edit_read_session(patch_id: str) -> dict[str, Any]:",
        "    path = _edit_session_dir() / f'{_edit_safe_id(patch_id)}.json'",
        "    if not path.exists():",
        "        raise RuntimeError(f'patch session 不存在：{patch_id}')",
        "    return json.loads(path.read_text(encoding='utf-8'))",
        "",
        "def _edit_read_session_by_rollback(rollback_id: str) -> dict[str, Any]:",
        "    for path in _edit_session_dir().glob('patch_*.json'):",
        "        try:",
        "            session = json.loads(path.read_text(encoding='utf-8'))",
        "        except Exception:",
        "            continue",
        "        if session.get('rollbackId') == rollback_id:",
        "            return session",
        "    raise RuntimeError(f'rollback session 不存在：{rollback_id}')",
        "",
        "def _edit_public_session(session: dict[str, Any]) -> dict[str, Any]:",
        "    return {'patchId': session.get('patchId', ''), 'projectId': session.get('projectId', ''), 'runId': session.get('runId', ''), 'status': session.get('status', ''), 'files': session.get('files', []), 'diff': session.get('diff', ''), 'conflicts': session.get('conflicts', []), 'rollbackId': session.get('rollbackId', ''), 'createdAt': session.get('createdAt', ''), 'appliedAt': session.get('appliedAt', ''), 'rolledBackAt': session.get('rolledBackAt', '')}",
        "",
        "def _edit_structured_changes(path: str, original: str, replacement: str, content: str, overwrite: bool, changes_json: str) -> list[dict[str, Any]]:",
        "    raw: Any = []",
        "    if changes_json.strip():",
        "        raw = json.loads(changes_json)",
        "    elif path.strip() and (original or replacement):",
        "        raw = [{'path': path, 'original': original, 'replacement': replacement}]",
        "    elif path.strip():",
        "        raw = [{'path': path, 'content': content, 'overwrite': overwrite, 'kind': 'write'}]",
        "    if isinstance(raw, dict):",
        "        raw = [raw]",
        "    if not isinstance(raw, list):",
        "        return []",
        "    changes: list[dict[str, Any]] = []",
        "    for item in raw:",
        "        if not isinstance(item, dict):",
        "            continue",
        "        item_path = str(item.get('path') or '').strip()",
        "        if not item_path:",
        "            continue",
        "        if item.get('kind') == 'write' or 'content' in item:",
        "            resolved = _resolve_allowed_path(item_path)",
        "            changes.append({'kind': 'write', 'path': _safe_display_path(resolved), 'content': str(item.get('content') if 'content' in item else ''), 'overwrite': bool(item.get('overwrite', False)), 'encoding': str(item.get('encoding') or 'utf-8')})",
        "            continue",
        "        search = str(item.get('original') if 'original' in item else item.get('search') or '')",
        "        replace = str(item.get('replacement') if 'replacement' in item else item.get('replace') or '')",
        "        if not search:",
        "            continue",
        "        resolved = _resolve_allowed_path(item_path)",
        "        changes.append({'kind': 'replace', 'path': _safe_display_path(resolved), 'original': search, 'replacement': replace, 'expectedOccurrences': item.get('expectedOccurrences'), 'encoding': str(item.get('encoding') or 'utf-8')})",
        "    return changes",
        "",
        "def _edit_parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:",
        "    lines = diff_text.replace('\\r\\n', '\\n').split('\\n')",
        "    changes: list[dict[str, Any]] = []",
        "    index = 0",
        "    current_old = ''",
        "    while index < len(lines):",
        "        line = lines[index]",
        "        if line.startswith('--- '):",
        "            current_old = _edit_diff_path(line[4:].strip())",
        "            index += 1",
        "            if index >= len(lines) or not lines[index].startswith('+++ '):",
        "                continue",
        "            new_path = _edit_diff_path(lines[index][4:].strip())",
        "            target_path = new_path if new_path != '/dev/null' else current_old",
        "            if not target_path or target_path == '/dev/null':",
        "                index += 1",
        "                continue",
        "            resolved = _resolve_allowed_path(target_path)",
        "            hunks: list[dict[str, Any]] = []",
        "            index += 1",
        "            while index < len(lines):",
        "                header = lines[index]",
        "                if header.startswith('--- ') or header.startswith('diff --git '):",
        "                    break",
        "                if not header.startswith('@@'):",
        "                    index += 1",
        "                    continue",
        "                match = re.match(r'@@\\s+-(\\d+)(?:,(\\d+))?\\s+\\+(\\d+)(?:,(\\d+))?\\s+@@', header)",
        "                if not match:",
        "                    raise RuntimeError(f'无法解析 unified diff hunk：{header}')",
        "                hunk_lines: list[str] = []",
        "                index += 1",
        "                while index < len(lines):",
        "                    item = lines[index]",
        "                    if item.startswith('@@') or item.startswith('--- ') or item.startswith('diff --git '):",
        "                        break",
        "                    if item.startswith('\\\\ No newline'):",
        "                        index += 1",
        "                        continue",
        "                    if item == '':",
        "                        hunk_lines.append(' ')",
        "                    elif item[0] in {' ', '-', '+'}:",
        "                        hunk_lines.append(item)",
        "                    else:",
        "                        hunk_lines.append(' ' + item)",
        "                    index += 1",
        "                hunks.append({'oldStart': int(match.group(1)), 'oldCount': int(match.group(2) or '1'), 'newStart': int(match.group(3)), 'newCount': int(match.group(4) or '1'), 'lines': hunk_lines})",
        "            changes.append({'kind': 'unified', 'path': _safe_display_path(resolved), 'hunks': hunks, 'encoding': 'utf-8'})",
        "            continue",
        "        index += 1",
        "    return changes",
        "",
        "def _edit_diff_path(value: str) -> str:",
        "    text = value.split('\\t', 1)[0].split(' ', 1)[0].strip()",
        "    if text in {'', '/dev/null'}:",
        "        return '/dev/null'",
        "    return text[2:] if text.startswith(('a/', 'b/')) else text",
        "",
        "def _strip_code_fence(value: str) -> str:",
        "    text = (value or '').strip()",
        "    match = re.search(r'```(?:diff|patch)?\\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)",
        "    return match.group(1).strip() if match else text",
        "",
        "def _edit_apply_change(change: dict[str, Any], current_text: str, exists_before: bool) -> str:",
        "    kind = str(change.get('kind') or '')",
        "    if kind == 'replace':",
        "        original = str(change.get('original') or '')",
        "        expected = change.get('expectedOccurrences')",
        "        count = current_text.count(original)",
        "        if expected is not None and count != int(expected):",
        "            raise RuntimeError(f'替换命中次数不符合预期：expected={expected}, actual={count}')",
        "        if expected is None and count != 1:",
        "            raise RuntimeError(f'替换默认要求唯一命中，实际命中 {count} 次。')",
        "        return current_text.replace(original, str(change.get('replacement') or ''))",
        "    if kind == 'write':",
        "        if exists_before and not bool(change.get('overwrite', False)):",
        "            raise RuntimeError('write_file 默认不覆盖已有文件，请设置 overwrite=true。')",
        "        return str(change.get('content') if 'content' in change else '')",
        "    if kind == 'unified':",
        "        return _edit_apply_unified_hunks(current_text, change.get('hunks') if isinstance(change.get('hunks'), list) else [])",
        "    raise RuntimeError(f'未知变更类型：{kind}')",
        "",
        "def _edit_apply_unified_hunks(current_text: str, hunks: list[dict[str, Any]]) -> str:",
        "    had_final_newline = current_text.endswith('\\n')",
        "    source = current_text.splitlines()",
        "    output: list[str] = []",
        "    source_index = 0",
        "    line_offset = 0",
        "    for hunk in hunks:",
        "        old_start = int(hunk.get('oldStart') or 1)",
        "        old_count = int(hunk.get('oldCount') or 0)",
        "        target = 0 if old_count == 0 and old_start == 0 else max(0, old_start - 1 + line_offset)",
        "        if target < source_index:",
        "            raise RuntimeError('patch hunk 顺序冲突。')",
        "        output.extend(source[source_index:target])",
        "        cursor = target",
        "        for raw_line in hunk.get('lines') or []:",
        "            line = str(raw_line)",
        "            prefix = line[:1]",
        "            text = line[1:] if line else ''",
        "            if prefix == ' ':",
        "                if cursor >= len(source) or source[cursor] != text:",
        "                    raise RuntimeError(f'patch 上下文不匹配：{text[:80]}')",
        "                output.append(source[cursor])",
        "                cursor += 1",
        "            elif prefix == '-':",
        "                if cursor >= len(source) or source[cursor] != text:",
        "                    raise RuntimeError(f'patch 删除行不匹配：{text[:80]}')",
        "                cursor += 1",
        "                line_offset -= 1",
        "            elif prefix == '+':",
        "                output.append(text)",
        "                line_offset += 1",
        "        source_index = cursor",
        "    output.extend(source[source_index:])",
        "    result = '\\n'.join(output)",
        "    if had_final_newline or result:",
        "        result += '\\n'",
        "    return result",
        "",
        "def _edit_change_conflict(change: dict[str, Any], current_text: str) -> str:",
        "    if str(change.get('kind') or '') == 'write' and not bool(change.get('overwrite', False)):",
        "        return '目标文件已存在，write_file 默认不覆盖'",
        "    try:",
        "        _edit_apply_change(change, current_text, True)",
        "    except Exception as exc:",
        "        return str(exc)",
        "    return ''",
        "",
        "def _edit_change_summary(change: dict[str, Any]) -> str:",
        "    kind = str(change.get('kind') or '')",
        "    if kind == 'replace':",
        "        return f\"替换 {len(str(change.get('original') or ''))} 字符为 {len(str(change.get('replacement') or ''))} 字符\"",
        "    if kind == 'write':",
        "        return f\"写入 {len(str(change.get('content') or ''))} 字符\"",
        "    if kind == 'unified':",
        "        return f\"{len(change.get('hunks') or [])} 个 diff hunk\"",
        "    return kind",
        "",
        "def _edit_file_hash(path: Path) -> str:",
        "    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''",
        "",
        "def _ensure_edit_text_file(path: Path) -> None:",
        "    if path.exists() and _is_binary_file(path):",
        "        raise RuntimeError(f'拒绝编辑疑似二进制文件：{path}')",
        "",
        "def _safe_display_path(path: Path) -> str:",
        "    for root in _allowed_roots():",
        "        if _is_relative_to(path, root):",
        "            try:",
        "                return path.relative_to(root).as_posix() or '.'",
        "            except ValueError:",
        "                continue",
        "    return str(path)",
        "",
        "def _require_export_direct_edits() -> None:",
        "    if os.getenv('GLG_ALLOW_DIRECT_EDITS', '').lower() in {'1', 'true', 'yes'}:",
        "        return",
        "    raise RuntimeError('导出项目默认禁用直接写入和补丁应用，请设置 GLG_ALLOW_DIRECT_EDITS=true。')",
        "",
        "def _ensure_export_command_allowed(command: list[str]) -> None:",
        "    defaults = 'git status;git diff;git diff --check;npm run build;npm test;npm run lint;python -m pytest;pytest;python -m compileall'",
        "    allowed_items = [item.strip().lower() for item in re.split(r'[;\\n]+', os.getenv('GLG_ALLOWED_COMMANDS', defaults)) if item.strip()]",
        "    normalized = ' '.join(command).lower()",
        "    if any(normalized == item or normalized.startswith(item + ' ') for item in allowed_items):",
        "        return",
        "    raise RuntimeError(f\"命令不在白名单内：{' '.join(command)}\")",
        "",
        "def _clip_command_output(value: Any) -> tuple[str, bool]:",
        "    text = value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value or '')",
        "    max_bytes = max(1, min(int(os.getenv('GLG_MAX_COMMAND_OUTPUT_BYTES', '262144')), 4 * 1024 * 1024))",
        "    raw = text.encode('utf-8')",
        "    if len(raw) <= max_bytes:",
        "        return text, False",
        "    return raw[:max_bytes].decode('utf-8', errors='replace'), True",
        "",
        "def _allowed_roots() -> list[Path]:",
        '    raw = os.getenv("GLG_FILE_TOOL_ROOTS", "./")',
        '    parts = [item.strip() for item in re.split(r"[;\\n]+", raw) if item.strip()] or ["./"]',
        "    return [Path(item).expanduser().resolve() for item in parts]",
        "",
        "def _resolve_allowed_path(value: str) -> Path:",
        "    candidate = Path(value).expanduser()",
        "    roots = _allowed_roots()",
        "    candidates = [candidate] if candidate.is_absolute() else [Path.cwd() / candidate, *(root / candidate for root in roots)]",
        "    allowed: list[Path] = []",
        "    seen: set[str] = set()",
        "    for item in candidates:",
        "        resolved = item.resolve()",
        "        key = str(resolved).lower()",
        "        if key in seen:",
        "            continue",
        "        seen.add(key)",
        "        if any(_is_relative_to(resolved, root) for root in roots):",
        "            allowed.append(resolved)",
        "    if allowed:",
        "        return next((path for path in allowed if path.exists()), allowed[0])",
        '    raise RuntimeError(f"路径不在允许目录内：{candidates[0].resolve()}")',
        "",
        "def _enrich_asset_reference(reference: dict[str, Any], base_file: Path) -> dict[str, Any]:",
        "    item = dict(reference)",
        "    raw_url = str(item.get('url') or '').strip()",
        "    item['url'] = raw_url",
        "    parsed = urlparse(raw_url)",
        "    if not raw_url:",
        "        item.update({'external': False, 'allowed': False, 'exists': False, 'resolvedPath': ''})",
        "        return item",
        "    if parsed.scheme in {'http', 'https', 'data', 'blob', 'mailto', 'tel'} or raw_url.startswith(('#', '//')):",
        "        item.update({'external': True, 'allowed': None, 'exists': None, 'resolvedPath': ''})",
        "        return item",
        "    relative_part = unquote(raw_url.split('?', 1)[0].split('#', 1)[0])",
        "    if not relative_part:",
        "        item.update({'external': False, 'allowed': False, 'exists': False, 'resolvedPath': ''})",
        "        return item",
        "    candidate = (base_file.parent / relative_part).resolve()",
        "    allowed = any(_is_relative_to(candidate, root) for root in _allowed_roots())",
        "    item.update({'external': False, 'allowed': allowed, 'exists': candidate.exists() if allowed else False, 'resolvedPath': str(candidate) if allowed else ''})",
        "    return item",
        "",
        "def _read_text_limited(path: Path, encoding: str) -> tuple[str, bool]:",
        "    max_bytes = _max_file_bytes()",
        "    with path.open('rb') as handle:",
        "        content = handle.read(max_bytes + 1)",
        "    truncated = len(content) > max_bytes",
        "    if truncated:",
        "        content = content[:max_bytes]",
        "    return content.decode(encoding or 'utf-8', errors='replace'), truncated",
        "",
        "def _read_file_chunk_by_lines(path: Path, start_line: int, end_line: int | None, max_chars: int, encoding: str) -> dict[str, Any]:",
        "    if end_line is not None and end_line < start_line:",
        "        raise RuntimeError('read_file_chunk 的 end_line 不能小于 start_line。')",
        "    content_parts: list[str] = []",
        "    total_lines = 0",
        "    last_returned_line: int | None = None",
        "    truncated = False",
        "    with path.open('r', encoding=encoding or 'utf-8', errors='replace', newline='') as handle:",
        "        for line_no, line in enumerate(handle, start=1):",
        "            total_lines = line_no",
        "            if line_no < start_line:",
        "                continue",
        "            if end_line is not None and line_no > end_line:",
        "                continue",
        "            current_len = sum(len(part) for part in content_parts)",
        "            if current_len + len(line) > max_chars:",
        "                remaining = max_chars - current_len",
        "                if remaining > 0:",
        "                    content_parts.append(line[:remaining])",
        "                    last_returned_line = line_no",
        "                truncated = True",
        "                continue",
        "            content_parts.append(line)",
        "            last_returned_line = line_no",
        "    content = ''.join(content_parts)",
        "    if truncated and last_returned_line is not None and last_returned_line < total_lines:",
        "        next_start_line = last_returned_line + 1",
        "    elif end_line is not None and end_line < total_lines:",
        "        next_start_line = end_line + 1",
        "    else:",
        "        next_start_line = None",
        "    return {'path': str(path), 'size': path.stat().st_size, 'encoding': encoding, 'startLine': start_line, 'endLine': last_returned_line, 'totalLines': total_lines, 'offset': None, 'nextOffset': None, 'nextStartLine': next_start_line, 'truncated': truncated, 'content': content}",
        "",
        "def _count_file_lines(path: Path, encoding: str) -> int:",
        "    count = 0",
        "    with path.open('r', encoding=encoding or 'utf-8', errors='replace', newline='') as handle:",
        "        for count, _line in enumerate(handle, start=1):",
        "            pass",
        "    return count",
        "",
        "def _is_binary_file(path: Path) -> bool:",
        "    try:",
        "        with path.open('rb') as handle:",
        "            sample = handle.read(CODE_TOOL_BINARY_CHECK_BYTES)",
        "    except OSError:",
        "        return True",
        "    return b'\\x00' in sample",
        "",
        "def _iter_search_files(root: Path, file_glob: str):",
        "    if root.is_file():",
        "        if fnmatch.fnmatch(root.name, file_glob) or fnmatch.fnmatch(root.as_posix(), file_glob):",
        "            yield root",
        "        return",
        "    if not root.is_dir():",
        "        raise RuntimeError(f'搜索根路径不存在或不是目录：{root}')",
        "    for dirpath, dirnames, filenames in os.walk(root):",
        "        dirnames[:] = [name for name in dirnames if name not in CODE_TOOL_EXCLUDED_DIRS and not name.startswith('.')]",
        "        current = Path(dirpath)",
        "        for filename in filenames:",
        "            path = current / filename",
        "            rel = _safe_relative_path(path, root)",
        "            if fnmatch.fnmatch(filename, file_glob) or fnmatch.fnmatch(rel, file_glob):",
        "                yield path",
        "",
        "def _safe_relative_path(path: Path, root: Path) -> str:",
        "    try:",
        "        return path.relative_to(root if root.is_dir() else root.parent).as_posix()",
        "    except ValueError:",
        "        return path.name",
        "",
        "def _detect_code_language(path: Path, language_hint: str) -> str:",
        "    normalized = language_hint.strip().lower().replace('-', '_')",
        "    aliases = {'py': 'python', 'python': 'python', 'html': 'html', 'htm': 'html', 'js': 'javascript', 'mjs': 'javascript', 'cjs': 'javascript', 'jsx': 'javascript', 'javascript': 'javascript', 'ts': 'typescript', 'tsx': 'typescript', 'typescript': 'typescript', 'css': 'css', 'scss': 'scss', 'sass': 'scss', 'less': 'less', 'vue': 'vue', 'svelte': 'svelte', 'json': 'json', 'jsonc': 'json', 'yaml': 'yaml', 'yml': 'yaml', 'md': 'markdown', 'markdown': 'markdown'}",
        "    if normalized in aliases:",
        "        return aliases[normalized]",
        "    return aliases.get(path.suffix.lower().lstrip('.'), path.suffix.lower().lstrip('.') or 'unknown')",
        "",
        "def _python_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:",
        "    tree = ast.parse(text)",
        "    lines = text.splitlines()",
        "    symbols: list[dict[str, Any]] = []",
        "    for item in tree.body:",
        "        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):",
        "            symbols.append(_python_symbol_dict(item.name, 'function', item, lines))",
        "        elif isinstance(item, ast.ClassDef):",
        "            symbols.append(_python_symbol_dict(item.name, 'class', item, lines))",
        "            for child in item.body:",
        "                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):",
        "                    symbols.append(_python_symbol_dict(f'{item.name}.{child.name}', 'method', child, lines))",
        "        if len(symbols) >= max_symbols:",
        "            break",
        "    return sorted(symbols, key=lambda symbol: (symbol['startLine'], symbol['name']))[:max_symbols]",
        "",
        "def _python_symbol_dict(name: str, kind: str, node: Any, lines: list[str]) -> dict[str, Any]:",
        "    start = int(getattr(node, 'lineno', 1) or 1)",
        "    end = int(getattr(node, 'end_lineno', start) or start)",
        "    preview = lines[start - 1].strip() if 0 <= start - 1 < len(lines) else name",
        "    return {'name': name, 'kind': kind, 'startLine': start, 'endLine': end, 'preview': preview}",
        "",
        "class HtmlSymbolParser(HTMLParser):",
        "    def __init__(self, max_symbols: int) -> None:",
        "        super().__init__(convert_charrefs=True)",
        "        self.max_symbols = max_symbols",
        "        self.symbols: list[dict[str, Any]] = []",
        "",
        "    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:",
        "        if len(self.symbols) >= self.max_symbols:",
        "            return",
        "        attr = {key: value or '' for key, value in attrs}",
        "        line, _column = self.getpos()",
        "        name_parts = [tag]",
        "        if attr.get('id'):",
        "            name_parts.append(f\"#{attr['id']}\")",
        "        if attr.get('class'):",
        "            classes = '.'.join(part for part in attr['class'].split() if part)",
        "            if classes:",
        "                name_parts.append(f'.{classes}')",
        "        preview_attrs = ' '.join(f'{key}=\"{value}\"' for key, value in attr.items() if key in {'id', 'class', 'name', 'src', 'href'} and value)",
        "        self.symbols.append({'name': ''.join(name_parts), 'kind': 'tag', 'startLine': line, 'endLine': line, 'preview': f\"<{tag}{(' ' + preview_attrs) if preview_attrs else ''}>\"})",
        "",
        "def _html_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:",
        "    parser = HtmlSymbolParser(max_symbols)",
        "    parser.feed(text)",
        "    parser.close()",
        "    return parser.symbols[:max_symbols]",
        "",
        "def _javascript_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:",
        "    patterns = [('class', re.compile(r'\\bclass\\s+([A-Za-z_$][\\w$]*)')), ('function', re.compile(r'\\bfunction\\s+([A-Za-z_$][\\w$]*)\\s*\\(')), ('function', re.compile(r'\\b(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*(?:async\\s*)?(?:\\([^)]*\\)|[A-Za-z_$][\\w$]*)\\s*=>')), ('function', re.compile(r'\\b([A-Za-z_$][\\w$]*)\\s*:\\s*(?:async\\s*)?function\\s*\\('))]",
        "    symbols: list[dict[str, Any]] = []",
        "    for line_no, line in enumerate(text.splitlines(), start=1):",
        "        for kind, pattern in patterns:",
        "            match = pattern.search(line)",
        "            if not match:",
        "                continue",
        "            symbols.append({'name': match.group(1), 'kind': kind, 'startLine': line_no, 'endLine': line_no, 'preview': line.strip()})",
        "            break",
        "        if len(symbols) >= max_symbols:",
        "            break",
        "    return symbols",
        "",
        "def _css_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:",
        "    symbols: list[dict[str, Any]] = []",
        "    pending: list[str] = []",
        "    start_line = 1",
        "    for line_no, line in enumerate(text.splitlines(), start=1):",
        "        stripped = line.strip()",
        "        if not stripped or stripped.startswith(('/*', '*', '@')):",
        "            continue",
        "        if '{' in stripped:",
        "            before = stripped.split('{', 1)[0].strip() or ' '.join(pending).strip()",
        "            pending = []",
        "            if before:",
        "                symbols.append({'name': before, 'kind': 'css_rule', 'startLine': start_line, 'endLine': line_no, 'preview': before + ' {'})",
        "        elif not pending:",
        "            pending = [stripped]",
        "            start_line = line_no",
        "        else:",
        "            pending.append(stripped)",
        "        if len(symbols) >= max_symbols:",
        "            break",
        "    return symbols",
        "",
        "def _clip_text(value: str, max_chars: int) -> tuple[str, bool]:",
        "    if len(value) <= max_chars:",
        "        return value, False",
        "    return value[:max_chars], True",
        "",
        "def _best_effort_html_lines(source: str, fragment: str, start_offset: int) -> tuple[int | None, int | None, int]:",
        "    if not fragment:",
        "        return None, None, start_offset",
        "    index = source.find(fragment, start_offset)",
        "    if index < 0:",
        "        index = source.find(fragment)",
        "    if index < 0:",
        "        return None, None, start_offset",
        "    start_line = source.count('\\n', 0, index) + 1",
        "    end_line = start_line + fragment.count('\\n')",
        "    return start_line, end_line, index + len(fragment)",
        "",
        "def _strip_css_comments_preserve_lines(text: str) -> str:",
        "    def replace(match: re.Match[str]) -> str:",
        "        value = match.group(0)",
        "        return ''.join('\\n' if char == '\\n' else ' ' for char in value)",
        "    return re.sub(r'/\\*.*?\\*/', replace, text, flags=re.DOTALL)",
        "",
        "def _parse_css_rules(text: str) -> tuple[list[dict[str, Any]], list[str]]:",
        "    warnings: list[str] = []",
        "    if re.search(r'@[A-Za-z-]+\\s+[^{}]*{[^{}]*{', text, re.DOTALL):",
        "        warnings.append('检测到可能的嵌套 at-rule，CSS 解析按普通规则 best-effort 处理。')",
        "    clean = _strip_css_comments_preserve_lines(text)",
        "    rules: list[dict[str, Any]] = []",
        "    for match in re.finditer(r'(?s)([^{}]+)\\{([^{}]*)\\}', clean):",
        "        selector_text = match.group(1).strip()",
        "        body = match.group(2).strip()",
        "        if not selector_text or not body or selector_text.startswith('@'):",
        "            continue",
        "        selectors = [part.strip() for part in selector_text.split(',') if part.strip()]",
        "        declarations: dict[str, str] = {}",
        "        for declaration in body.split(';'):",
        "            if ':' not in declaration:",
        "                continue",
        "            name, value = declaration.split(':', 1)",
        "            name = name.strip()",
        "            if not name:",
        "                continue",
        "            declarations[name] = value.strip()",
        "        if not declarations:",
        "            continue",
        "        selector_start = match.start(1) + (len(match.group(1)) - len(match.group(1).lstrip()))",
        "        start_line = clean.count('\\n', 0, selector_start) + 1",
        "        end_line = clean.count('\\n', 0, match.end()) + 1",
        "        css = text[selector_start:match.end()].strip()",
        "        rules.append({'selector': selector_text, 'selectors': selectors, 'declarations': declarations, 'startLine': start_line, 'endLine': end_line, 'css': css})",
        "    return rules, warnings",
        "",
        "def _normalize_css_selector(value: str) -> str:",
        "    return re.sub(r'\\s+', ' ', value or '').strip().lower()",
        "",
        "def _assert_network_allowed(url: str, extra_allowed_hosts: set[str] | None = None) -> None:",
        '    if os.getenv("GLG_TOOL_NETWORK_ENABLED", "true").lower() in {"0", "false", "no", "off"}:',
        '        raise RuntimeError("当前运行环境已关闭网络访问。")',
        "    parsed = urlparse(url)",
        '    if parsed.scheme not in {"http", "https"} or not parsed.netloc:',
        '        raise RuntimeError("只允许访问 http/https URL。")',
        '    raw_hosts = os.getenv("GLG_TOOL_ALLOWED_HOSTS", "")',
        '    allowed = {item.strip().lower() for item in re.split(r"[,;\\n]+", raw_hosts) if item.strip()}',
        "    allowed.update(item.lower() for item in (extra_allowed_hosts or set()))",
        "    host = (parsed.hostname or '').lower()",
        "    if allowed and host not in allowed and not any(item.startswith('*.') and host.endswith(item[1:]) for item in allowed):",
        '        raise RuntimeError(f"当前运行环境不允许访问域名：{host}")',
        "",
        "def _duckduckgo_has_instant_answer(data: dict[str, Any], related_topics: list[dict[str, str]]) -> bool:",
        "    return bool(str(data.get('Answer') or '').strip() or str(data.get('AbstractText') or data.get('Abstract') or '').strip() or str(data.get('Definition') or '').strip() or related_topics)",
        "",
        "def _duckduckgo_serp_results(query: str, limit: int) -> list[dict[str, str]]:",
        '    _assert_network_allowed("https://html.duckduckgo.com/html/", {"duckduckgo.com", "html.duckduckgo.com"})',
        '    response = httpx.get("https://html.duckduckgo.com/html/?" + urlencode({"q": query}), timeout=15, follow_redirects=True, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "GraphicLangGraph/0.1 (+https://local)"})',
        "    response.raise_for_status()",
        "    parser = DuckDuckGoHtmlResultsParser(limit)",
        "    parser.feed(response.text)",
        "    parser.close()",
        "    return parser.results[:limit]",
        "",
        "class DuckDuckGoHtmlResultsParser(HTMLParser):",
        "    def __init__(self, limit: int) -> None:",
        "        super().__init__(convert_charrefs=True)",
        "        self.limit = limit",
        "        self.results: list[dict[str, str]] = []",
        "        self._active_title: dict[str, Any] | None = None",
        "        self._active_snippet_index: int | None = None",
        "        self._snippet_depth = 0",
        "",
        "    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:",
        "        if len(self.results) >= self.limit:",
        "            return",
        "        attr = {key: value or '' for key, value in attrs}",
        "        class_name = attr.get('class', '')",
        "        if tag == 'a' and 'result__a' in class_name:",
        "            self._active_title = {'href': attr.get('href', ''), 'parts': []}",
        "            return",
        "        if tag in {'a', 'div'} and 'result__snippet' in class_name and self.results:",
        "            self._active_snippet_index = len(self.results) - 1",
        "            self._snippet_depth = 1",
        "            return",
        "        if self._active_snippet_index is not None:",
        "            self._snippet_depth += 1",
        "",
        "    def handle_endtag(self, tag: str) -> None:",
        "        if tag == 'a' and self._active_title is not None:",
        "            title = _clean_search_text(' '.join(self._active_title['parts']))",
        "            url = _duckduckgo_result_url(str(self._active_title.get('href') or ''))",
        "            if title and url and not any(item['url'] == url for item in self.results):",
        "                self.results.append({'title': title, 'url': url, 'snippet': ''})",
        "            self._active_title = None",
        "            return",
        "        if self._active_snippet_index is not None:",
        "            self._snippet_depth -= 1",
        "            if self._snippet_depth <= 0:",
        "                self._active_snippet_index = None",
        "",
        "    def handle_data(self, data: str) -> None:",
        "        if self._active_title is not None:",
        "            self._active_title['parts'].append(data)",
        "            return",
        "        if self._active_snippet_index is not None and 0 <= self._active_snippet_index < len(self.results):",
        "            current = self.results[self._active_snippet_index].get('snippet', '')",
        "            self.results[self._active_snippet_index]['snippet'] = _clean_search_text(f'{current} {data}')",
        "",
        "def _duckduckgo_result_url(raw_url: str) -> str:",
        "    url = html_lib.unescape(raw_url or '').strip()",
        "    if not url:",
        "        return ''",
        "    if url.startswith('//'):",
        "        url = f'https:{url}'",
        "    if url.startswith('/'):",
        "        url = f'https://duckduckgo.com{url}'",
        "    parsed = urlparse(url)",
        "    if parsed.netloc.endswith('duckduckgo.com') and parsed.path.startswith('/l/'):",
        "        return parse_qs(parsed.query).get('uddg', [''])[0].strip()",
        "    if parsed.scheme in {'http', 'https'} and parsed.netloc:",
        "        return url",
        "    return ''",
        "",
        "def _clean_search_text(value: str) -> str:",
        "    return re.sub(r'\\s+', ' ', html_lib.unescape(value or '')).strip()",
        "",
        "def _duckduckgo_related_topics(value: Any, limit: int) -> list[dict[str, str]]:",
        "    results: list[dict[str, str]] = []",
        "    def visit(items: Any) -> None:",
        "        if len(results) >= limit or not isinstance(items, list):",
        "            return",
        "        for item in items:",
        "            if len(results) >= limit:",
        "                break",
        "            if not isinstance(item, dict):",
        "                continue",
        "            if isinstance(item.get('Topics'), list):",
        "                visit(item['Topics'])",
        "                continue",
        "            text = str(item.get('Text') or '').strip()",
        "            url = str(item.get('FirstURL') or '').strip()",
        "            if text or url:",
        '                results.append({"title": text[:180], "url": url, "snippet": text})',
        "    visit(value)",
        "    return results",
        "",
        "def _compact_value(value: Any) -> Any:",
        "    if isinstance(value, str):",
        "        return value if len(value) <= 1200 else value[:1200] + '...[truncated]'",
        "    if isinstance(value, list):",
        "        return [_compact_value(item) for item in value[:12]]",
        "    if isinstance(value, dict):",
        "        return {str(key): _compact_value(item) for key, item in list(value.items())[:24]}",
        "    return value",
        "",
        "def _is_relative_to(path: Path, parent: Path) -> bool:",
        "    try:",
        "        path.relative_to(parent)",
        "        return True",
        "    except ValueError:",
        "        return False",
        "",
        "def _max_file_bytes() -> int:",
        '    return max(1, min(int(os.getenv("GLG_TOOL_MAX_FILE_BYTES", "1048576")), 16 * 1024 * 1024))',
        "",
        "def _max_http_bytes() -> int:",
        '    return max(1, min(int(os.getenv("GLG_TOOL_MAX_HTTP_BYTES", "262144")), 4 * 1024 * 1024))',
        "",
    ] + _code_intelligence_helper_lines()


def _code_intelligence_helper_lines() -> list[str]:
    source = inspect.getsource(code_intelligence)
    lines = []
    for line in source.splitlines():
        if line.startswith("from __future__"):
            continue
        lines.append(line)
    return lines + [""]


def _skills_py(project: ProjectIR) -> str:
    skills = [skill for skill in project.skills if getattr(skill, "enabled", True) is not False]
    if not skills:
        return "from __future__ import annotations\n\n\nSKILL_REGISTRY = {}\n"

    registry: dict[str, dict[str, str]] = {}
    for skill in skills:
        payload = {
            "id": str(skill.id),
            "name": str(skill.name or skill.id),
            "description": str(skill.description or ""),
            "sourcePath": str(skill.source_path or ""),
            "filePath": str(skill.file_path or ""),
            "content": str(skill.content or ""),
            "metadataJson": str(skill.metadata_json or "{}"),
        }
        if payload["id"]:
            registry[payload["id"]] = payload
        if payload["name"] and payload["name"] not in registry:
            registry[payload["name"]] = payload

    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "",
            f"SKILL_REGISTRY = {json.dumps(registry, ensure_ascii=False, indent=2)}",
            "",
        ]
    )


def _mcp_servers_py(project: ProjectIR) -> str:
    registry: dict[str, dict[str, Any]] = {}
    for server in _mcp_server_dicts(project):
        server_id = str(server.get("id") or "").strip()
        server_name = str(server.get("name") or "").strip()
        if server_id:
            registry[server_id] = server
        if server_name and server_name not in registry:
            registry[server_name] = server
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "",
            f"MCP_SERVER_REGISTRY = {json.dumps(registry, ensure_ascii=False, indent=2)}",
            "",
        ]
    )


def _embedded_agents_py(registry: dict[str, dict[str, Any]]) -> str:
    return f'''from __future__ import annotations

import importlib
import json
import re
import time
from typing import Any


MAX_EMBEDDED_AGENT_DEPTH = {MAX_EMBEDDED_AGENT_DEPTH}
EMBEDDED_AGENT_REGISTRY = {json.dumps(registry, ensure_ascii=False, indent=2)}


def run_embedded_agent(project_id: str, input_text: str = "", state_patch: dict[str, Any] | None = None, parent_state: dict[str, Any] | None = None) -> dict[str, Any]:
    parent = parent_state if isinstance(parent_state, dict) else {{}}
    depth = _positive_int(parent.get("__agent_depth"), 0)
    if depth >= MAX_EMBEDDED_AGENT_DEPTH:
        raise RuntimeError(f"内嵌 Agent 调用深度超过限制：{{MAX_EMBEDDED_AGENT_DEPTH}}")
    entry = EMBEDDED_AGENT_REGISTRY.get(str(project_id or "").strip())
    if not entry:
        raise RuntimeError(f"导出包未内嵌 Agent 项目：{{project_id}}")
    patch = state_patch if isinstance(state_patch, dict) else {{}}
    text = str(input_text or parent.get("messages") or parent.get("chat") or "").strip()
    child_state = {{
        **patch,
        "messages": text,
        "chat": text,
        "parent_state": _compact_state(parent),
        "__agent_depth": depth + 1,
    }}
    started = time.perf_counter()
    module = importlib.import_module(f"{{entry['package']}}.graph")
    output_state = module.graph.invoke(child_state)
    return {{
        "ok": True,
        "agentId": str(entry.get("agentId") or project_id),
        "agentName": str(entry.get("name") or project_id),
        "projectId": str(project_id),
        "finalAnswer": _agent_final_answer(output_state),
        "outputState": _compact_state(output_state if isinstance(output_state, dict) else {{}}),
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
    }}


def selected_embedded_agent_tool_configs(agent_ids: list[str], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshot_by_id = {{str(agent.get("id") or ""): agent for agent in snapshots if isinstance(agent, dict)}}
    snapshot_by_project = {{str(agent.get("projectId") or agent.get("project_id") or ""): agent for agent in snapshots if isinstance(agent, dict)}}
    if not agent_ids and snapshots:
        agent_ids = [str(agent.get("id") or agent.get("projectId") or agent.get("project_id") or "").strip() for agent in snapshots if isinstance(agent, dict)]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id in agent_ids:
        agent = snapshot_by_id.get(agent_id) or snapshot_by_project.get(agent_id)
        project_id = str((agent or {{}}).get("projectId") or (agent or {{}}).get("project_id") or agent_id).strip()
        entry = EMBEDDED_AGENT_REGISTRY.get(project_id)
        if not entry or project_id in seen:
            continue
        seen.add(project_id)
        raw_agent_id = str((agent or {{}}).get("id") or project_id).strip()
        agent_name = str((agent or {{}}).get("name") or entry.get("name") or project_id)
        tool_name = f"agent_{{_slugify(raw_agent_id or agent_name)}}"
        result.append({{
            "id": f"agent::{{raw_agent_id}}",
            "name": tool_name,
            "description": str((agent or {{}}).get("description") or f"调用内嵌 Agent：{{agent_name}}"),
            "source": "agent",
            "inputSchema": {{
                "type": "object",
                "properties": {{
                    "input": {{"type": "string", "description": "要交给子 Agent 处理的任务内容。"}},
                    "statePatch": {{"type": "object", "description": "可选，传给子 Agent 的额外 state。"}},
                }},
                "required": ["input"],
            }},
            "agentId": raw_agent_id,
            "agentName": agent_name,
            "projectId": project_id,
        }})
    return result


def _agent_final_answer(output_state: Any) -> str:
    state = output_state if isinstance(output_state, dict) else {{}}
    for key in ("final_answer", "answer", "agent_result", "tools_result", "llm_result"):
        text = _state_value_to_text(state.get(key)).strip()
        if text:
            return text
    for key in reversed(list(state.keys())):
        if key.endswith(("_result", "_answer", "_output")):
            text = _state_value_to_text(state.get(key)).strip()
            if text:
                return text
    return _state_value_to_text(output_state)


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {{str(key): _compact_value(value, string_limit=3000, list_limit=12) for key, value in dict(state).items() if str(key) != "messages"}}


def _compact_value(value: Any, string_limit: int = 1200, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        return {{str(key): _compact_value(child, string_limit=string_limit, list_limit=list_limit) for key, child in value.items()}}
    if isinstance(value, list):
        return [_compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + "...[truncated]"
    return value


def _state_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\\n".join(_state_value_to_text(item) for item in value if _state_value_to_text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    content = getattr(value, "content", None)
    return str(content) if content is not None else str(value)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_") or "agent"
'''


def _mcp_runtime_py() -> str:
    return r'''from __future__ import annotations

import asyncio
import inspect as inspect_lib
import json
import os
import re
import shlex
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import render_template


MCP_RESULT_STRING_LIMIT = 12000


class McpRuntimeError(RuntimeError):
    pass


def list_mcp_tools(server_config: dict[str, Any]) -> list[dict[str, Any]]:
    server = normalize_mcp_server_config(server_config)
    _ensure_server_enabled(server)
    _ensure_server_execution_allowed(server)
    timeout = _positive_float(server.get("startupTimeoutSec"), 10)
    tools = _run_async(_list_mcp_tools_async(server, timeout))
    return _filter_tools(tools, server)


def invoke_mcp_tool(server_config: dict[str, Any], tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    server = normalize_mcp_server_config(server_config)
    _ensure_server_enabled(server)
    _ensure_tool_approval(server, tool_name)
    _ensure_server_execution_allowed(server)
    _ensure_tool_name_allowed(server, tool_name)
    if not isinstance(args, dict):
        raise McpRuntimeError("MCP 工具参数必须是 JSON object。")
    startup_timeout = _positive_float(server.get("startupTimeoutSec"), 10)
    tool_timeout = _positive_float(server.get("toolTimeoutSec"), 60)
    result = _run_async(_call_mcp_tool_async(server, tool_name, args, startup_timeout, tool_timeout))
    return _normalize_tool_result(server, tool_name, args, result)


def make_mcp_agent_tool_config(server_config: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    server = normalize_mcp_server_config(server_config)
    tool_name = str(tool.get("name") or "").strip()
    exposed_name = f"mcp_{_slugify(server.get('id') or server.get('name') or 'server')}__{tool_name}"
    input_schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    return {
        "id": f"mcp::{server.get('id') or server.get('name')}::{tool_name}",
        "name": exposed_name,
        "description": str(tool.get("description") or tool.get("title") or f"{server.get('name')} MCP 工具"),
        "inputSchema": input_schema,
        "server": server,
        "toolName": tool_name,
    }


def run_mcp_agent_session(
    model_ref: Any,
    mcp_tools: list[dict[str, Any]],
    system_prompt: str,
    user_prompt: str,
    max_iterations: int,
) -> tuple[str, list[dict[str, Any]]]:
    messages: list[tuple[str, str]] = [
        ("system", _mcp_agent_system_prompt(system_prompt, mcp_tools, max_iterations)),
        ("user", user_prompt),
    ]
    calls: list[dict[str, Any]] = []
    final_answer = ""
    for iteration in range(max(1, min(int(max_iterations or 4), 12))):
        response = model_ref.invoke(messages)
        content = getattr(response, "content", str(response))
        decision = _parse_tool_agent_decision(content)
        tool_calls = _normalize_tool_calls(decision.get("tool_calls"))
        if not tool_calls:
            final_answer = str(decision.get("final_answer") or content or "")
            break
        observations: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls, start=1):
            started = time.perf_counter()
            tool_name = str(tool_call.get("tool") or tool_call.get("name") or "").strip()
            args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
            tool_config = _find_mcp_tool(mcp_tools, tool_name)
            if not tool_config:
                observation = {"ok": False, "error": f"未知 MCP Tool：{tool_name}", "errorType": "tool_args"}
                server_name = ""
                raw_tool_name = tool_name
            else:
                server = tool_config["server"]
                raw_tool_name = str(tool_config["toolName"])
                server_name = str(server.get("name") or server.get("id") or "")
                try:
                    observation = {"ok": True, "result": invoke_mcp_tool(server, raw_tool_name, args)}
                    error_type = None
                except Exception as exc:
                    error_type = _classify_mcp_error(exc)
                    observation = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}", "errorType": error_type}
            calls.append(
                {
                    "iteration": iteration + 1,
                    "index": index,
                    "tool": tool_name,
                    "serverName": server_name,
                    "toolName": raw_tool_name,
                    "args": args,
                    "observation": _compact_value(observation, string_limit=6000, list_limit=12),
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                    "errorType": observation.get("errorType") if isinstance(observation, dict) else None,
                }
            )
            observations.append({"tool": tool_name, "observation": observation})
        messages.append(("assistant", content))
        messages.append(("user", "MCP 工具执行结果：\n" + json.dumps(observations, ensure_ascii=False, indent=2) + "\n请继续；如果已经足够，请返回 final_answer。"))
    return final_answer or "MCP Agent 已停止，但模型没有给出 final_answer。", calls


def render_json_object(template: str, state: dict[str, Any]) -> dict[str, Any]:
    rendered = render_template(template.strip() or "{}", state)
    try:
        parsed = json.loads(rendered)
    except ValueError as exc:
        raise McpRuntimeError(f"toolArgsJson 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise McpRuntimeError("toolArgsJson 必须是 JSON object。")
    return parsed


def normalize_mcp_server_config(value: dict[str, Any] | Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    transport = _first_text(value.get("transport"), "stdio").lower()
    if transport in {"streamable_http", "sse"}:
        transport = "http"
    return {
        "id": _first_text(value.get("id")),
        "name": _first_text(value.get("name"), "未命名 MCP"),
        "transport": transport or "stdio",
        "command": _first_text(value.get("command")),
        "argsJson": _json_text(value.get("argsJson"), value.get("args_json"), fallback=[]),
        "envJson": _json_text(value.get("envJson"), value.get("env_json"), fallback={}),
        "envVarsJson": _json_text(value.get("envVarsJson"), value.get("env_vars_json"), fallback=[]),
        "cwd": _first_text(value.get("cwd")),
        "url": _first_text(value.get("url")),
        "apiKey": _first_text(value.get("apiKey"), value.get("api_key")),
        "apiKeyEnv": _safe_env_name(_first_text(value.get("apiKeyEnv"), value.get("api_key_env"))),
        "apiKeyMode": _first_text(value.get("apiKeyMode"), value.get("api_key_mode"), "env"),
        "apiKeyHeader": _first_text(value.get("apiKeyHeader"), value.get("api_key_header"), "Authorization"),
        "apiKeyPrefix": _first_text(value.get("apiKeyPrefix"), value.get("api_key_prefix"), "Bearer"),
        "bearerTokenEnvVar": _safe_env_name(_first_text(value.get("bearerTokenEnvVar"), value.get("bearer_token_env_var"))),
        "httpHeadersJson": _json_text(value.get("httpHeadersJson"), value.get("http_headers_json"), fallback={}),
        "envHttpHeadersJson": _json_text(value.get("envHttpHeadersJson"), value.get("env_http_headers_json"), fallback={}),
        "enabled": value.get("enabled") is not False,
        "startupTimeoutSec": _positive_int(value.get("startupTimeoutSec", value.get("startup_timeout_sec")), 10),
        "toolTimeoutSec": _positive_int(value.get("toolTimeoutSec", value.get("tool_timeout_sec")), 60),
        "enabledToolsJson": _json_text(value.get("enabledToolsJson"), value.get("enabled_tools_json"), fallback=[]),
        "disabledToolsJson": _json_text(value.get("disabledToolsJson"), value.get("disabled_tools_json"), fallback=[]),
        "defaultToolsApprovalMode": _first_text(value.get("defaultToolsApprovalMode"), value.get("default_tools_approval_mode")),
        "sourceType": _first_text(value.get("sourceType"), value.get("source_type"), "manual"),
        "sourcePath": _first_text(value.get("sourcePath"), value.get("source_path")),
        "description": _first_text(value.get("description")),
    }


async def _list_mcp_tools_async(server: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    async with _open_mcp_session(server, timeout=timeout) as session:
        response = await asyncio.wait_for(session.list_tools(), timeout=timeout)
        return [_tool_to_dict(tool) for tool in getattr(response, "tools", []) or []]


async def _call_mcp_tool_async(server: dict[str, Any], tool_name: str, args: dict[str, Any], startup_timeout: float, tool_timeout: float) -> Any:
    async with _open_mcp_session(server, timeout=max(startup_timeout, tool_timeout)) as session:
        tools = await asyncio.wait_for(session.list_tools(), timeout=startup_timeout)
        tool_names = {str(getattr(tool, "name", "") or _model_dump(tool).get("name") or "") for tool in getattr(tools, "tools", []) or []}
        if tool_names and tool_name not in tool_names:
            raise McpRuntimeError(f"MCP Server 未暴露工具：{tool_name}")
        return await asyncio.wait_for(session.call_tool(tool_name, arguments=args), timeout=tool_timeout)


@asynccontextmanager
async def _open_mcp_session(server: dict[str, Any], timeout: float):
    async with AsyncExitStack() as stack:
        client_session_cls, streams = await _open_transport(server, stack, timeout)
        session = await stack.enter_async_context(client_session_cls(streams[0], streams[1]))
        await asyncio.wait_for(session.initialize(), timeout=timeout)
        yield session


async def _open_transport(server: dict[str, Any], stack: AsyncExitStack, timeout: float) -> tuple[Any, tuple[Any, ...]]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise McpRuntimeError("缺少 Python MCP SDK。请运行 python -m pip install -e . 安装导出工程依赖。") from exc
    if str(server.get("transport") or "stdio").lower() == "http":
        url = str(server.get("url") or "").strip()
        if not url:
            raise McpRuntimeError("HTTP MCP 缺少 URL。")
        headers = _build_http_headers(server)
        read_timeout = max(timeout, _positive_float(server.get("toolTimeoutSec"), 60))
        if "http_client" in inspect_lib.signature(streamable_http_client).parameters:
            http_client = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(timeout, read=read_timeout), follow_redirects=True)
            await stack.enter_async_context(http_client)
            streams = await stack.enter_async_context(streamable_http_client(url, http_client=http_client))
        else:
            streams = await stack.enter_async_context(streamable_http_client(url=url, headers=headers, timeout=timeout, sse_read_timeout=read_timeout))
        return ClientSession, tuple(streams)
    command = str(server.get("command") or "").strip()
    if not command:
        raise McpRuntimeError("STDIO MCP 缺少启动命令。")
    params = StdioServerParameters(command=command, args=_json_string_list(server.get("argsJson")), env=_build_stdio_env(server), cwd=_resolve_cwd(server.get("cwd")))
    streams = await stack.enter_async_context(stdio_client(params))
    return ClientSession, tuple(streams)


def _normalize_tool_result(server: dict[str, Any], tool_name: str, args: dict[str, Any], result: Any) -> dict[str, Any]:
    raw = _model_dump(result)
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False) or raw.get("isError") or raw.get("is_error"))
    content = _result_content_text(result, raw)
    if is_error:
        raise McpRuntimeError(f"MCP 工具 {tool_name} 执行失败：{content or raw}")
    return {"ok": True, "serverId": server.get("id", ""), "serverName": server.get("name", "未命名 MCP"), "tool": tool_name, "args": args, "content": content, "raw": _compact_value(raw, string_limit=MCP_RESULT_STRING_LIMIT, list_limit=20)}


def _result_content_text(result: Any, raw: dict[str, Any]) -> str:
    parts: list[str] = []
    content = getattr(result, "content", None) or raw.get("content") or []
    if not isinstance(content, list):
        content = [content]
    for item in content:
        data = _model_dump(item)
        text = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text")
        if text is not None:
            parts.append(str(text))
        elif isinstance(data.get("text"), str):
            parts.append(data["text"])
        elif data:
            parts.append(json.dumps(_compact_value(data, string_limit=2000, list_limit=8), ensure_ascii=False))
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None) or raw.get("structuredContent") or raw.get("structured_content")
    if structured and not parts:
        parts.append(json.dumps(_compact_value(structured, string_limit=4000, list_limit=12), ensure_ascii=False))
    text = "\n".join(part for part in parts if part).strip()
    return text if len(text) <= MCP_RESULT_STRING_LIMIT else text[:MCP_RESULT_STRING_LIMIT] + "...[truncated]"


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    data = _model_dump(tool)
    input_schema = data.get("inputSchema") or data.get("input_schema") or getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    return {"name": str(data.get("name") or getattr(tool, "name", "") or ""), "title": str(data.get("title") or getattr(tool, "title", "") or ""), "description": str(data.get("description") or getattr(tool, "description", "") or ""), "inputSchema": input_schema if isinstance(input_schema, dict) else {}}


def _filter_tools(tools: list[dict[str, Any]], server: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = set(_json_string_list(server.get("enabledToolsJson")))
    disabled = set(_json_string_list(server.get("disabledToolsJson")))
    result = []
    for tool in tools:
        name = str(tool.get("name") or "").strip()
        if name and (not allowed or name in allowed) and name not in disabled:
            result.append(tool)
    return result


def _mcp_agent_system_prompt(system_prompt: str, mcp_tools: list[dict[str, Any]], max_iterations: int) -> str:
    tool_lines = [{"name": tool.get("name"), "description": tool.get("description"), "args": (tool.get("inputSchema") or {}).get("properties", {}), "required": (tool.get("inputSchema") or {}).get("required", [])} for tool in mcp_tools]
    instructions = ("你是一个可以自主调用 MCP 工具的 Agent。"
                    f"最多进行 {max_iterations} 轮工具调用。"
                    "每次回复必须是 JSON，格式为："
                    '{"tool_calls":[{"tool":"工具名称","args":{}}],"final_answer":""}。'
                    "如果还需要工具，填写 tool_calls；如果已经完成，tool_calls 为空数组，并填写 final_answer。不要输出 Markdown。")
    return "\n\n".join(part for part in (system_prompt, instructions, "可用 MCP 工具：\n" + json.dumps(tool_lines, ensure_ascii=False, indent=2)) if part).strip()


def _parse_tool_agent_decision(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {"tool_calls": [], "final_answer": ""}
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, list):
            return {"tool_calls": parsed, "final_answer": ""}
        if isinstance(parsed, dict):
            return parsed
    return {"tool_calls": [], "final_answer": text}


def _normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _find_mcp_tool(tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    normalized = name.strip().lower()
    for tool in tools:
        if normalized in {str(tool.get("id") or "").lower(), str(tool.get("name") or "").lower()}:
            return tool
    return None


def _ensure_server_enabled(server: dict[str, Any]) -> None:
    if server.get("enabled") is False:
        raise McpRuntimeError(f"MCP Server 已停用：{server.get('name') or server.get('id')}")


def _ensure_tool_approval(server: dict[str, Any], tool_name: str) -> None:
    if str(server.get("defaultToolsApprovalMode") or "").strip().lower() == "prompt":
        raise McpRuntimeError(f"MCP 工具 {tool_name} 需要人工审批，导出工程 v1 暂不支持交互式审批。")


def _ensure_tool_name_allowed(server: dict[str, Any], tool_name: str) -> None:
    allowed = set(_json_string_list(server.get("enabledToolsJson")))
    disabled = set(_json_string_list(server.get("disabledToolsJson")))
    if allowed and tool_name not in allowed:
        raise McpRuntimeError(f"MCP 工具不在白名单内：{tool_name}")
    if tool_name in disabled:
        raise McpRuntimeError(f"MCP 工具已被黑名单禁用：{tool_name}")


def _ensure_server_execution_allowed(server: dict[str, Any]) -> None:
    if str(server.get("transport") or "stdio").lower() == "http":
        _assert_network_allowed(str(server.get("url") or ""))
    else:
        _ensure_command_allowed([str(server.get("command") or ""), *_json_string_list(server.get("argsJson"))])


def _assert_network_allowed(url: str) -> None:
    if os.getenv("GLG_MCP_NETWORK_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        raise McpRuntimeError("当前导出工程已关闭 MCP 网络访问。")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise McpRuntimeError("只允许访问 http/https MCP URL。")
    allowed_hosts = {item.lower() for item in _split_env_list(os.getenv("GLG_MCP_ALLOWED_HOSTS", ""))}
    host = parsed.hostname or ""
    if "*" in allowed_hosts:
        return
    if allowed_hosts and not _host_allowed(host, allowed_hosts):
        raise McpRuntimeError(f"当前导出工程不允许访问 MCP 域名：{host}")


def _ensure_command_allowed(command: list[str]) -> None:
    command = [item for item in command if item]
    allowed_commands = _split_env_list(os.getenv("GLG_MCP_ALLOWED_COMMANDS", ""))
    if not allowed_commands:
        return
    normalized = " ".join(command).lower()
    for allowed in allowed_commands:
        allowed_text = allowed.lower()
        if normalized == allowed_text or normalized.startswith(allowed_text + " "):
            return
    raise McpRuntimeError(f"MCP STDIO 命令不在白名单内：{' '.join(command)}")


def _host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    normalized = host.lower()
    return any((allowed.startswith("*.") and normalized.endswith(allowed[1:])) or normalized == allowed for allowed in allowed_hosts if allowed)


def _build_http_headers(server: dict[str, Any]) -> dict[str, str]:
    headers = {str(key): str(value) for key, value in _json_object(server.get("httpHeadersJson")).items() if str(value)}
    for header, env_name in _json_object(server.get("envHttpHeadersJson")).items():
        env_key = _safe_env_name(str(env_name))
        if not env_key:
            continue
        value = os.getenv(env_key, "").strip()
        if not value:
            raise McpRuntimeError(f"MCP HTTP Header {header} 引用的环境变量 {env_key} 未设置。")
        headers[str(header)] = value
    bearer_env = _safe_env_name(str(server.get("bearerTokenEnvVar") or ""))
    if bearer_env:
        token = os.getenv(bearer_env, "").strip()
        if not token:
            raise McpRuntimeError(f"MCP Bearer Token 环境变量 {bearer_env} 未设置。")
        headers["Authorization"] = f"Bearer {token}"
    api_key_header = str(server.get("apiKeyHeader") or "").strip()
    if api_key_header:
        api_key_mode = str(server.get("apiKeyMode") or "env").strip().lower()
        if api_key_mode == "direct":
            token = str(server.get("apiKey") or "").strip()
            if not token:
                raise McpRuntimeError("MCP API Key 直接写入模式下 token 为空。")
        else:
            env_key = _safe_env_name(str(server.get("apiKeyEnv") or ""))
            if not env_key:
                token = ""
            else:
                token = os.getenv(env_key, "").strip()
                if not token:
                    raise McpRuntimeError(f"MCP API Key 环境变量 {env_key} 未设置。")
        if token:
            prefix = str(server.get("apiKeyPrefix") or "").strip()
            headers[api_key_header] = f"{prefix} {token}" if prefix else token
    return headers


def _build_stdio_env(server: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in _json_object(server.get("envJson")).items():
        safe_key = _safe_env_name(str(key))
        if safe_key and str(value):
            env[safe_key] = str(value)
    for key in _json_string_list(server.get("envVarsJson")):
        safe_key = _safe_env_name(key)
        if not safe_key:
            continue
        value = os.getenv(safe_key, "")
        if not value:
            raise McpRuntimeError(f"MCP STDIO 环境变量 {safe_key} 未设置。")
        env[safe_key] = value
    return env


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def _resolve_cwd(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return str(path)


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(by_alias=True, mode="json")
        except TypeError:
            dumped = value.model_dump(by_alias=True)
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _json_text(*values: Any, fallback: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        text = str(value).strip()
        if text:
            try:
                json.loads(text)
            except ValueError:
                break
            return text
    return json.dumps(fallback, ensure_ascii=False)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return shlex.split(text) if " " in text else [item.strip() for item in re.split(r"[,，;\n]+", text) if item.strip()]
    return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def _split_env_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;\n,]+", value or "") if item.strip()]


def _compact_value(value: Any, string_limit: int = 1200, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(child, string_limit=string_limit, list_limit=list_limit) for key, child in value.items()}
    if isinstance(value, list):
        return [_compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + "...[truncated]"
    return value


def _classify_mcp_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "network" in text or "域名" in text or "http" in text or "connect" in text:
        return "network_permission"
    if "白名单" in text or "黑名单" in text or "approval" in text or "审批" in text:
        return "permission"
    if "json" in text or "参数" in text or "arguments" in text:
        return "tool_args"
    return "mcp_runtime"


def _safe_env_name(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or "") else ""


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", text).strip("_") or "server"
'''


def _tool_specs(project: ProjectIR) -> dict[str, str]:
    specs: dict[str, str] = {}
    for tool_config in project.tools:
        name = str(tool_config.name or tool_config.id).strip()
        if name:
            specs[name] = tool_config.description
            specs.setdefault(py_name(name), tool_config.description)
    for node in project.nodes:
        if node.type == NodeType.TOOL:
            name = str(node.config.get("toolName", node.label or node.id)).strip()
            if name:
                specs[name] = str(node.config.get("description", node.label or ""))
        if node.type == NodeType.AGENT:
            for name in _csv_tool_names(str(node.config.get("tools", ""))):
                specs.setdefault(name, f"Declared tool used by Agent node {node.id}.")
    return specs


def _nodes_py(project: ProjectIR) -> str:
    body = [
        "from __future__ import annotations",
        "",
        "import json",
        "import re",
        "import time",
        "from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed",
        "from typing import Any",
        "from pathlib import Path",
        "import httpx",
        "from langchain.agents import create_agent",
        "from langchain.chat_models import init_chat_model",
        "from langchain_core.messages import AIMessage",
        "from langgraph.types import interrupt",
        "",
        "from .config import env, render_template",
        "from .state import AgentState",
        "from .mcp_runtime import invoke_mcp_tool, list_mcp_tools, make_mcp_agent_tool_config, run_mcp_agent_session, render_json_object",
        "from .mcp_servers import MCP_SERVER_REGISTRY",
        "from .embedded_agents import run_embedded_agent, selected_embedded_agent_tool_configs",
        "from .skills import SKILL_REGISTRY",
        "from .tools import TOOL_REGISTRY",
        "",
    ]
    top_level_error_targets = _top_level_error_targets(project)
    for node in project.nodes:
        if node.type in {NodeType.START, NodeType.PARALLEL_WORKER}:
            continue
        source = _node_function(node, project)
        if node.id in top_level_error_targets or _node_has_runtime_policy(node):
            source = _wrap_policy_node_function(source, py_name(node.id), node, has_error_edge=node.id in top_level_error_targets)
        body.append(source)
        body.append("")
    body.append(_nodes_helpers())
    body.append("")
    return "\n".join(body)


def _top_level_error_targets(project: ProjectIR) -> dict[str, str]:
    internal_ids = _for_each_internal_node_ids(project)
    return {
        edge.source: edge.target
        for edge in project.edges
        if edge.kind == EdgeKind.ERROR and edge.source not in internal_ids and edge.target not in internal_ids
    }


def _node_has_runtime_policy(node: NodeIR) -> bool:
    config = node.config
    retry = str(config.get("retryPolicyJson") or "").strip()
    error_policy = str(config.get("errorPolicy") or "").strip().lower()
    return bool(
        retry
        or _positive_int(config.get("nodeTimeoutSec"), 0)
        or error_policy not in {"", "default"}
        or str(config.get("fallbackOutputJson") or "").strip()
        or str(config.get("errorOutputField") or "").strip()
    )


def _wrap_policy_node_function(source: str, function_name: str, node: NodeIR, has_error_edge: bool = False) -> str:
    impl_name = f"_glg_{function_name}_body"
    wrapped_source = source.replace(f"def {function_name}(", f"def {impl_name}(", 1)
    node_meta = repr({"type": str(node.type), "label": node.label})
    config = repr(node.config)
    return wrapped_source + f'''


def {function_name}(state: AgentState) -> dict[str, Any]:
    try:
        result = _run_node_with_policy(state, {impl_name}, {config}, {node.id!r}, {node_meta})
        if isinstance(result, dict):
            result["_glg_error_from"] = ""
            return result
        return {{"_glg_error_from": ""}}
    except Exception as exc:
        if not {has_error_edge!r}:
            raise
        return {{
            "last_error": _runtime_error_payload({node.id!r}, {node_meta}, exc),
            "_glg_error_from": {node.id!r},
        }}
'''


def _for_each_codegen_maps(project: ProjectIR, node: NodeIR) -> dict[str, Any]:
    nodes_by_id = {item.id: item for item in project.nodes}
    outgoing: dict[str, list[EdgeIR]] = defaultdict(list)
    for edge in project.edges:
        outgoing[edge.source].append(edge)
    item_start = _target_for_handle_codegen([edge for edge in outgoing[node.id] if edge.kind != EdgeKind.ERROR], "item")
    merge_id = _find_for_each_merge_id_codegen(item_start, nodes_by_id, outgoing) if item_start else ""
    internal_ids: set[str] = set()
    if item_start and merge_id:
        queue = [item_start]
        while queue:
            node_id = queue.pop(0)
            if node_id in internal_ids:
                continue
            internal_ids.add(node_id)
            if node_id == merge_id:
                continue
            for edge in outgoing[node_id]:
                if edge.kind != EdgeKind.WORKER:
                    queue.append(edge.target)
    normal_map: dict[str, str] = {}
    conditional_map: dict[str, dict[str, str]] = defaultdict(dict)
    error_map: dict[str, str] = {}
    for internal_id in internal_ids:
        for edge in outgoing[internal_id]:
            if edge.kind == EdgeKind.NORMAL:
                normal_map[internal_id] = edge.target
            elif edge.kind == EdgeKind.CONDITIONAL:
                conditional_map[internal_id][edge.sourceHandle or edge.label or "default"] = edge.target
            elif edge.kind == EdgeKind.ERROR:
                error_map[internal_id] = edge.target
    node_meta = {
        internal_id: {
            "type": str(nodes_by_id[internal_id].type),
            "config": nodes_by_id[internal_id].config,
            "label": nodes_by_id[internal_id].label,
        }
        for internal_id in internal_ids
        if internal_id in nodes_by_id
    }
    function_names = {internal_id: py_name(internal_id) for internal_id in internal_ids if internal_id != merge_id}
    merge_node = nodes_by_id.get(merge_id)
    return {
        "itemStart": item_start,
        "mergeId": merge_id,
        "nodeMeta": node_meta,
        "functionNames": function_names,
        "normalMap": normal_map,
        "conditionalMap": dict(conditional_map),
        "errorMap": error_map,
        "mergeReducers": _json_object_list((merge_node.config if merge_node else {}).get("reducersJson")),
        "mergeResultField": str((merge_node.config if merge_node else {}).get("resultField", "merge_result")),
    }


def _node_function(node: NodeIR, project: ProjectIR) -> str:
    function_name = py_name(node.id)
    if node.type == NodeType.LLM:
        provider = json.dumps(str(node.config.get("provider", "openai")))
        model = json.dumps(str(node.config.get("model", "gpt-4.1-mini")))
        base_url = json.dumps(str(node.config.get("baseUrl", "")))
        api_key_env = json.dumps(str(node.config.get("apiKeyEnv", "")))
        api_version = json.dumps(str(node.config.get("apiVersion", "")))
        organization = json.dumps(str(node.config.get("organization", "")))
        system_prompt = json.dumps(str(node.config.get("systemPrompt", "")))
        user_prompt = json.dumps(str(node.config.get("userPrompt", "{{ state.messages }}")))
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_output")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    model = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization})
    messages = [
        ("system", render_template({system_prompt}, state)),
        ("user", render_template({user_prompt}, state)),
    ]
    response = model.invoke(messages)
    return {{"{output_field}": getattr(response, "content", str(response))}}
'''
    if node.type == NodeType.AGENT:
        provider = json.dumps(str(node.config.get("provider", "openai")))
        model = json.dumps(str(node.config.get("model", "gpt-4.1-mini")))
        base_url = json.dumps(str(node.config.get("baseUrl", "")))
        api_key_env = json.dumps(str(node.config.get("apiKeyEnv", "")))
        api_version = json.dumps(str(node.config.get("apiVersion", "")))
        organization = json.dumps(str(node.config.get("organization", "")))
        system_prompt = json.dumps(str(node.config.get("systemPrompt", "")))
        user_prompt = json.dumps(str(node.config.get("userPrompt", "")))
        max_iterations = int(node.config.get("maxIterations", 4) or 4)
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_result")))
        tool_names = json.dumps(_csv_tool_names(str(node.config.get("tools", ""))), ensure_ascii=False)
        skill_ids = json.dumps(_json_string_list(node.config.get("skillIdsJson")), ensure_ascii=False)
        mcp_server_ids = json.dumps(_json_string_list(node.config.get("mcpServerIdsJson")), ensure_ascii=False)
        mcp_server_registry = json.dumps(_json_object_list(node.config.get("mcpServerRegistryJson")), ensure_ascii=False)
        agent_ids = json.dumps(_json_string_list(node.config.get("agentIdsJson")), ensure_ascii=False)
        agent_registry = json.dumps(_json_object_list(node.config.get("agentRegistryJson")), ensure_ascii=False)
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    model_ref = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization})
    tool_names = {tool_names}
    skill_ids = {skill_ids}
    mcp_server_ids = {mcp_server_ids}
    mcp_server_registry = {mcp_server_registry}
    agent_ids = {agent_ids}
    agent_registry = {agent_registry}
    tools = [TOOL_REGISTRY[name] for name in tool_names if name in TOOL_REGISTRY]
    user_content = _agent_user_content(state, {user_prompt})
    messages = []
    system_content = _system_with_skills(render_template({system_prompt}, state), skill_ids)
    if system_content:
        messages.append(("system", system_content))
    messages.append(("user", user_content))
    mcp_servers = _selected_mcp_servers(mcp_server_ids, mcp_server_registry)
    agent_tools = selected_embedded_agent_tool_configs(agent_ids, agent_registry)
    if mcp_servers or agent_tools:
        mcp_tools = []
        for server in mcp_servers:
            for mcp_tool in list_mcp_tools(server):
                mcp_tools.append(make_mcp_agent_tool_config(server, mcp_tool))
        registered_tools = [*mcp_tools, *agent_tools]
        if mcp_servers and not mcp_tools:
            raise RuntimeError("Agent 已选择 MCP Server，但没有可用 MCP Tool。")
        if agent_ids and not agent_tools:
            raise RuntimeError("Agent 已选择子 Agent，但导出包没有可用内嵌 Agent。")
        response, calls = _run_export_tool_agent_session(model_ref, registered_tools, system_content, user_content, {max_iterations}, state)
        result = {{
            "{output_field}": response,
            "{py_name(function_name)}_max_iterations": {max_iterations},
        }}
        if mcp_tools:
            result["{output_field}_mcp_tool_calls"] = [call for call in calls if call.get("source") == "mcp"]
        if agent_tools:
            result["{output_field}_agent_tool_calls"] = [call for call in calls if call.get("source") == "agent"]
        return result
    if tools:
        agent = create_agent(model=model_ref, tools=tools, system_prompt=system_content)
        response_state = agent.invoke({{"messages": [("user", user_content)]}}, config={{"recursion_limit": {max_iterations}}})
        response = _last_message_content(response_state)
    else:
        response = getattr(model_ref.invoke(messages), "content", "")
    return {{
        "{output_field}": response,
        "{py_name(function_name)}_max_iterations": {max_iterations},
    }}
'''
    if node.type == NodeType.TOOL:
        tool_ids = json.dumps(_json_list(node.config.get("toolIdsJson")), ensure_ascii=False)
        tool_registry = json.dumps(_json_list(node.config.get("toolRegistryJson")), ensure_ascii=False)
        max_iterations = int(node.config.get("maxIterations", 4) or 4)
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_result")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    return {{
        "{output_field}": {{
            "registered_tool_ids": {tool_ids},
            "registered_tools": {tool_registry},
            "max_iterations": {max_iterations},
            "status": "tools_agent_configured",
        }}
    }}
'''
    if node.type == NodeType.TASK_SPLITTER:
        input_field = py_name(str(node.config.get("inputField", "task_plan")))
        output_field = py_name(str(node.config.get("outputField", "worker_tasks")))
        max_tasks = max(1, min(int(node.config.get("maxTasks", 5) or 5), 10))
        fallback = bool(node.config.get("fallbackToSingleTask", True))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    tasks = _normalize_worker_tasks(state.get("{input_field}"), {max_tasks}, "")
    if not tasks and {fallback!r}:
        fallback_goal = _state_value_to_text(state.get("messages")).strip() or _state_value_to_text(state.get("{input_field}")).strip() or "阅读代码并回答用户问题"
        tasks = _normalize_worker_tasks([{{"goal": fallback_goal}}], 1, fallback_goal)
    if not tasks:
        raise RuntimeError("Task Splitter 无法解析任务计划。")
    return {{"{output_field}": tasks}}
'''
    if node.type == NodeType.PARALLEL_TOOLS:
        tasks_field = py_name(str(node.config.get("tasksField", "worker_tasks")))
        output_field = py_name(str(node.config.get("outputField", "worker_results")))
        provider = json.dumps(str(node.config.get("provider", "openai")))
        model = json.dumps(str(node.config.get("model", "gpt-4.1-mini")))
        base_url = json.dumps(str(node.config.get("baseUrl", "")))
        api_key_env = json.dumps(str(node.config.get("apiKeyEnv", "")))
        api_version = json.dumps(str(node.config.get("apiVersion", "")))
        organization = json.dumps(str(node.config.get("organization", "")))
        system_prompt = json.dumps(str(node.config.get("systemPrompt", "你是代码阅读 Worker，只完成分配给你的子任务。")))
        tool_ids = _json_string_list(node.config.get("toolIdsJson"))
        tool_names = [str(item.get("name") or item.get("id") or "") for item in _json_object_list(node.config.get("toolRegistryJson"))]
        if not tool_names:
            tool_names = [item.removeprefix("builtin_") for item in tool_ids]
        max_iterations = max(1, min(int(node.config.get("maxIterationsPerTask", 6) or 6), 12))
        max_workers = max(1, min(int(node.config.get("maxConcurrentWorkers", 3) or 3), 6))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    tasks = _normalize_worker_tasks(state.get("{tasks_field}"), 10, _state_value_to_text(state.get("messages")))
    if not tasks:
        raise RuntimeError("Parallel Tools 没有可执行任务。")
    model_ref = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization})
    tool_names = {json.dumps(tool_names, ensure_ascii=False)}
    tools = [TOOL_REGISTRY[name] for name in tool_names if name in TOOL_REGISTRY]
    if not tools:
        raise RuntimeError("Parallel Tools 没有可用 Tool。")
    results: list[dict[str, Any] | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=min({max_workers}, len(tasks))) as executor:
        futures = {{executor.submit(_run_export_worker_task, model_ref, tools, {system_prompt}, task, state, {max_iterations}): index for index, task in enumerate(tasks)}}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    final_results = [item for item in results if isinstance(item, dict)]
    if final_results and all(item.get("status") == "error" for item in final_results):
        raise RuntimeError("Parallel Tools 所有 Worker 均执行失败。")
    return {{"{output_field}": final_results}}
'''
    if node.type == NodeType.VARIABLE_ASSIGN:
        assignments = json.dumps(_json_object_list(node.config.get("assignmentsJson")), ensure_ascii=False)
        input_mappings = json.dumps(_json_object_list(node.config.get("inputMappingsJson")), ensure_ascii=False)
        result_field = json.dumps(str(node.config.get("resultField", "assignment_result")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    inputs = _resolve_input_mappings({input_mappings}, state)
    return _run_variable_assign({assignments}, inputs, state, {result_field})
'''
    if node.type == NodeType.TEMPLATE:
        input_mappings = json.dumps(_json_object_list(node.config.get("inputMappingsJson")), ensure_ascii=False)
        template = json.dumps(str(node.config.get("template", "")))
        output_type = json.dumps(str(node.config.get("outputType", "text")))
        output_field = json.dumps(str(node.config.get("outputField", "template_result")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    inputs = _resolve_input_mappings({input_mappings}, state)
    render_state = {{**dict(state), **inputs}}
    rendered = render_template({template}, render_state)
    if {output_type}.strip().lower() == "json":
        try:
            value = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Template JSON 输出解析失败：{{exc}}") from exc
    else:
        value = rendered
    return {{{output_field}: value}}
'''
    if node.type == NodeType.JSON_EXTRACTOR:
        provider = json.dumps(str(node.config.get("provider", "openai")))
        model = json.dumps(str(node.config.get("model", "gpt-4.1-mini")))
        base_url = json.dumps(str(node.config.get("baseUrl", "")))
        api_key_env = json.dumps(str(node.config.get("apiKeyEnv", "")))
        api_version = json.dumps(str(node.config.get("apiVersion", "")))
        organization = json.dumps(str(node.config.get("organization", "")))
        input_mappings = json.dumps(_json_object_list(node.config.get("inputMappingsJson")), ensure_ascii=False)
        input_text = json.dumps(str(node.config.get("inputText", "")))
        instruction = json.dumps(str(node.config.get("instruction", "")))
        repair_instruction = json.dumps(str(node.config.get("repairInstruction", "")))
        repair_enabled = "True" if _truthy(node.config.get("repairEnabled")) else "False"
        schema = json.dumps(_json_schema_from_config(node.config), ensure_ascii=False)
        output_field = json.dumps(str(node.config.get("outputField", "extracted_json")))
        validation_field = json.dumps(str(node.config.get("validationField", "validation_result")))
        repair_field = json.dumps(str(node.config.get("repairResultField", "repair_result")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    model_ref = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization})
    inputs = _resolve_input_mappings({input_mappings}, state)
    render_state = {{**dict(state), **inputs}}
    source_text = render_template({input_text}, render_state) if {input_text}.strip() else _state_value_to_text(inputs.get("input") if "input" in inputs else state.get("messages", ""))
    schema = {schema}
    response = model_ref.invoke([
        ("system", _json_extractor_system_prompt({instruction}, schema)),
        ("user", "请从以下输入中抽取结构化 JSON：\\n" + source_text),
    ])
    raw_content = getattr(response, "content", str(response))
    parse_error = ""
    try:
        output = _parse_json_object_from_text(raw_content)
    except RuntimeError as exc:
        output = {{}}
        parse_error = str(exc)
    validation = _validation_result(output, schema)
    if parse_error:
        validation["errors"].insert(0, parse_error)
        validation["valid"] = False
    repair_result = None
    if {repair_enabled} and not validation["valid"]:
        repair_result = _repair_json_output(model_ref, {repair_instruction}, output, schema, validation["errors"], source_text, raw_content)
        if repair_result.get("ok") and isinstance(repair_result.get("output"), dict):
            output = repair_result["output"]
            validation = repair_result["validation"]
    delta = {{{output_field}: output, {validation_field}: validation}}
    if repair_result is not None:
        delta[{repair_field}] = repair_result
    return delta
'''
    if node.type == NodeType.JSON_VALIDATOR:
        provider = json.dumps(str(node.config.get("provider", "openai")))
        model = json.dumps(str(node.config.get("model", "gpt-4.1-mini")))
        base_url = json.dumps(str(node.config.get("baseUrl", "")))
        api_key_env = json.dumps(str(node.config.get("apiKeyEnv", "")))
        api_version = json.dumps(str(node.config.get("apiVersion", "")))
        organization = json.dumps(str(node.config.get("organization", "")))
        input_field = json.dumps(str(node.config.get("inputField", "extracted_json")))
        output_field = json.dumps(str(node.config.get("outputField", "validated_json")))
        validation_field = json.dumps(str(node.config.get("validationField", "validation_result")))
        repair_instruction = json.dumps(str(node.config.get("repairInstruction", "")))
        repair_enabled = "True" if _truthy(node.config.get("repairEnabled")) else "False"
        repair_field = json.dumps(str(node.config.get("repairResultField", "repair_result")))
        schema = json.dumps(_json_schema_from_config(node.config), ensure_ascii=False)
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    schema = {schema}
    value = _get_path(state, {input_field})
    validation = _validation_result(value, schema)
    repair_result = None
    if {repair_enabled} and not validation["valid"]:
        model_ref = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization})
        repair_result = _repair_json_output(model_ref, {repair_instruction}, value, schema, validation["errors"], _state_value_to_text(state.get("messages", "")), "")
        if repair_result.get("ok") and isinstance(repair_result.get("output"), dict):
            value = repair_result["output"]
            validation = repair_result["validation"]
    delta = {{{output_field}: value, {validation_field}: validation}}
    if repair_result is not None:
        delta[{repair_field}] = repair_result
    return delta
'''
    if node.type == NodeType.FOR_EACH:
        maps = _for_each_codegen_maps(project, node)
        items_field = json.dumps(str(node.config.get("itemsField", "worker_tasks")))
        item_field = json.dumps(str(node.config.get("itemField", "current_item")))
        index_field = json.dumps(str(node.config.get("indexField", "current_index")))
        max_items = min(_positive_int(node.config.get("maxItems"), 50), 100)
        result_field = json.dumps(str(node.config.get("resultField") or ""))
        execution_mode = json.dumps(str(node.config.get("executionMode") or "sequential"))
        max_concurrency = min(_positive_int(node.config.get("maxConcurrency"), 3), 12)
        preserve_order = "False" if node.config.get("preserveOrder") is False else "True"
        item_failure_policy = json.dumps(str(node.config.get("itemFailurePolicy") or "fail_fast"))
        function_entries = ", ".join(f"{key!r}: {value}" for key, value in maps["functionNames"].items())
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    node_functions = {{{function_entries}}}
    return _run_for_each_node(
        state,
        {items_field},
        {item_field},
        {index_field},
        {max_items},
        {json.dumps(maps["itemStart"])},
        {json.dumps(maps["mergeId"])},
        node_functions,
        {json.dumps(maps["nodeMeta"], ensure_ascii=False)},
        {json.dumps(maps["normalMap"], ensure_ascii=False)},
        {json.dumps(maps["conditionalMap"], ensure_ascii=False)},
        {json.dumps(maps["errorMap"], ensure_ascii=False)},
        {json.dumps(maps["mergeReducers"], ensure_ascii=False)},
        {json.dumps(maps["mergeResultField"])},
        {result_field},
        {execution_mode},
        {max_concurrency},
        {preserve_order},
        {item_failure_policy},
    )
'''
    if node.type == NodeType.MERGE:
        reducers = json.dumps(_json_object_list(node.config.get("reducersJson")), ensure_ascii=False)
        result_field = json.dumps(str(node.config.get("resultField", "merge_result")))
        merge_mode = json.dumps(str(node.config.get("mergeMode") or "auto"))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    return _apply_merge_reducers(dict(state), [dict(state)], {reducers}, {result_field}, {merge_mode})
'''
    if node.type == NodeType.ERROR_HANDLER:
        error_field = json.dumps(str(node.config.get("errorField", "last_error")))
        output_field = json.dumps(str(node.config.get("outputField", "error_result")))
        template = json.dumps(str(node.config.get("template", "流程执行失败：{{ state.last_error }}")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    error_value = _get_path(state, {error_field}, {{}})
    message = render_template({template}, {{**dict(state), "error": error_value}})
    return {{{output_field}: {{"ok": False, "error": error_value, "message": message}}}}
'''
    if node.type == NodeType.RETRIEVER:
        path = json.dumps(str(node.config.get("path", "./knowledge")))
        query = json.dumps(str(node.config.get("query", "{{ state.messages }}")))
        top_k = int(node.config.get("topK", 4) or 4)
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_context")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    query = render_template({query}, state).lower()
    root = Path({path})
    documents: list[str] = []
    if root.exists():
        for file_path in list(root.rglob("*.md")) + list(root.rglob("*.txt")):
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if not query or any(part and part in text.lower() for part in query.split()):
                documents.append(text[:1600])
            if len(documents) >= {top_k}:
                break
    return {{"{output_field}": "\\n\\n---\\n\\n".join(documents)}}
'''
    if node.type == NodeType.HTTP:
        method = json.dumps(str(node.config.get("method", "GET")).upper())
        url = json.dumps(str(node.config.get("url", "")))
        body = json.dumps(str(node.config.get("body", "")))
        auth_secret = json.dumps(str(node.config.get("authSecret", "")))
        mock_enabled = bool(node.config.get("mockEnabled", False))
        mock_response = json.dumps(str(node.config.get("mockResponseJson", "")))
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_response")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    if {mock_enabled!r} or {mock_response}.strip():
        return {{"{output_field}": _render_json_template({mock_response}, state)}}
    headers = {{}}
    token_key = {auth_secret}
    if token_key:
        headers["Authorization"] = f"Bearer {{env(token_key)}}"
    response = httpx.request(
        {method},
        render_template({url}, state),
        headers=headers,
        content=render_template({body}, state) if {body} else None,
        timeout=30,
    )
    response.raise_for_status()
    try:
        value = response.json()
    except ValueError:
        value = response.text
    return {{"{output_field}": value}}
'''
    if node.type == NodeType.CONDITION:
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    return {{}}
'''
    if node.type == NodeType.AI_ROUTER:
        provider = json.dumps(str(node.config.get("provider", "openai")))
        model = json.dumps(str(node.config.get("model", "gpt-4.1-mini")))
        base_url = json.dumps(str(node.config.get("baseUrl", "")))
        api_key_env = json.dumps(str(node.config.get("apiKeyEnv", "")))
        api_version = json.dumps(str(node.config.get("apiVersion", "")))
        organization = json.dumps(str(node.config.get("organization", "")))
        route_mode = json.dumps(str(node.config.get("routeMode", "keyword")))
        instruction = json.dumps(str(node.config.get("instruction", "")))
        input_text = json.dumps(str(node.config.get("inputText", "{{ state.messages }}")))
        route_field = py_name(str(node.config.get("routeField", "route_key")))
        reason_field = py_name(str(node.config.get("reasonField", "route_reason")))
        fallback = json.dumps(str(node.config.get("fallback", "other")))
        scenarios = json.dumps(_parse_scenarios(str(node.config.get("scenarios", ""))), ensure_ascii=False, indent=8)
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    text = render_template({input_text}, state).lower()
    scenarios = {scenarios}
    selected, reason = _keyword_route(text, scenarios, {fallback})
    if {route_mode} == "llm":
        try:
            prompt = _router_prompt({instruction}, text, scenarios, {fallback})
            response = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization}).invoke([("user", prompt)])
            selected = _normalize_route_key(getattr(response, "content", str(response)), scenarios, {fallback})
            reason = "llm route"
        except Exception as exc:
            reason = f"llm route failed, fallback to keyword: {{exc}}"
    return {{"{route_field}": selected, "{reason_field}": reason}}
'''
    if node.type == NodeType.HUMAN_APPROVAL:
        action_field = py_name(str(node.config.get("actionField", "approval_action")))
        output_field = py_name(str(node.config.get("outputField", "approval_result")))
        default_action = json.dumps(str(node.config.get("defaultAction", "approved")))
        prompt = json.dumps(str(node.config.get("prompt", "")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    payload = {{
        "type": "human_approval",
        "prompt": render_template({prompt}, state),
        "actions": ["approved", "rejected", "edit"],
        "defaultAction": {default_action},
    }}
    resume = interrupt(payload)
    if isinstance(resume, dict):
        action = str(resume.get("action") or resume.get("{action_field}") or {default_action})
        value = resume
    else:
        action = str(resume or state.get("{action_field}") or {default_action})
        value = {{"action": action, "prompt": payload["prompt"]}}
    return {{
        "{action_field}": action,
        "{output_field}": value,
    }}
'''
    if node.type == NodeType.DIRECT_REPLY:
        template = json.dumps(str(node.config.get("template", "{{ state.final_answer }}")))
        output_field = py_name(str(node.config.get("outputField", "final_answer")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    content = render_template({template}, state)
    if not content.strip():
        content = _fallback_reply_content(state)
    return {{
        "{output_field}": content,
        "messages": [AIMessage(content=content)],
    }}
'''
    if node.type == NodeType.SKILL_NODE:
        skill_id = json.dumps(str(node.config.get("skillId") or node.config.get("toolId") or ""))
        skill_name = json.dumps(str(node.config.get("skillName") or node.config.get("toolName") or node.label or "Skill"))
        skill_content = json.dumps(str(node.config.get("skillContent") or node.config.get("content") or ""))
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_skill")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    skill = SKILL_REGISTRY.get({skill_id}) or SKILL_REGISTRY.get({skill_name}) or {{}}
    content = str(skill.get("content") or {skill_content})
    return {{"{output_field}": content}}
'''
    if node.type == NodeType.MCP_NODE:
        server_id = json.dumps(str(node.config.get("serverId") or ""))
        server_name = json.dumps(str(node.config.get("serverName") or node.label or "MCP"))
        tool_name = json.dumps(str(node.config.get("toolName") or ""))
        tool_args_json = json.dumps(str(node.config.get("toolArgsJson") or "{}"))
        selection_mode = json.dumps(str(node.config.get("toolSelectionMode") or "heuristic"))
        selection_instruction = json.dumps(str(node.config.get("toolSelectionInstruction") or ""))
        fallback_to_heuristic = bool(node.config.get("fallbackToHeuristic", False))
        selection_provider = json.dumps(str(node.config.get("toolSelectionModelProvider") or node.config.get("provider") or "openai"))
        selection_model = json.dumps(str(node.config.get("toolSelectionModel") or node.config.get("model") or "gpt-4.1-mini"))
        selection_base_url = json.dumps(str(node.config.get("toolSelectionBaseUrl") or node.config.get("baseUrl") or ""))
        selection_api_key_env = json.dumps(str(node.config.get("toolSelectionApiKeyEnv") or node.config.get("apiKeyEnv") or ""))
        selection_api_version = json.dumps(str(node.config.get("toolSelectionApiVersion") or node.config.get("apiVersion") or ""))
        selection_organization = json.dumps(str(node.config.get("toolSelectionOrganization") or node.config.get("organization") or ""))
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_mcp")))
        snapshot = json.dumps(_json_object_list(node.config.get("mcpServerSnapshotJson")), ensure_ascii=False)
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    server = MCP_SERVER_REGISTRY.get({server_id}) or MCP_SERVER_REGISTRY.get({server_name})
    if not server:
        snapshots = {snapshot}
        server = snapshots[0] if snapshots else {{}}
    if not server:
        raise RuntimeError("MCP Node 未绑定有效 MCP Server。")
    tool_name = {tool_name}
    args = render_json_object({tool_args_json}, state)
    if tool_name:
        result = invoke_mcp_tool(server, tool_name, args)
        result["autoSelectedTool"] = False
        result["selectionMode"] = "manual"
        result["selectedByModel"] = False
        result["selectionReason"] = ""
    else:
        model_ref = None
        if {selection_mode}.strip().lower() == "model":
            model_ref = _chat_model({selection_provider}, {selection_model}, {selection_base_url}, {selection_api_key_env}, {selection_api_version}, {selection_organization})
        result = _run_mcp_node_auto_call(server, args, state, {selection_mode}, {selection_instruction}, {fallback_to_heuristic!r}, model_ref)
    return {{"{output_field}": result}}
'''
    if node.type == NodeType.AGENT_REF:
        output_field = py_name(str(node.config.get("outputField", "agent_ref_result")))
        project_id = json.dumps(str(node.config.get("agentProjectId") or ""))
        agent_name = json.dumps(str(node.config.get("agentName") or node.label or "Agent Ref"), ensure_ascii=False)
        instruction = json.dumps(str(node.config.get("instruction") or ""))
        protocol = json.dumps(str(node.config.get("protocol") or "handoff"))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    project_id = {project_id}
    if not project_id:
        raise RuntimeError("Agent Ref 未绑定 Agent。")
    input_text = render_template({instruction}, state).strip() or _state_value_to_text(state.get("messages") or state.get("chat")) or _agent_user_content(state, "")
    result = run_embedded_agent(project_id, input_text, {{}}, state)
    result["protocol"] = {protocol}
    result["agentName"] = result.get("agentName") or {agent_name}
    return {{"{output_field}": result}}
'''
    if node.type == NodeType.CUSTOM_FUNCTION:
        code = str(node.config.get("code", "return {}"))
        output_field = py_name(str(node.config.get("outputField", f"{function_name}_output")))
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    result = _{function_name}_impl(state)
    if isinstance(result, dict):
        return result
    return {{"{output_field}": result}}


def _{function_name}_impl(state: AgentState):
{_indent(code)}
'''
    return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    return {{}}
'''


def _routers_py(project: ProjectIR) -> str:
    top_level_error_targets = _top_level_error_targets(project)
    condition_nodes = [
        node
        for node in project.nodes
        if node.type in {NodeType.CONDITION, NodeType.AI_ROUTER, NodeType.HUMAN_APPROVAL, NodeType.JSON_EXTRACTOR, NodeType.JSON_VALIDATOR}
        or node.id in top_level_error_targets
    ]
    if not condition_nodes:
        return "from __future__ import annotations\n\n"

    body = [
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from .state import AgentState",
        "",
    ]
    for node in condition_nodes:
        body.append(_route_function(node, has_error_edge=node.id in top_level_error_targets))
        body.append("")
    return "\n".join(body)


def _route_function(node: NodeIR, has_error_edge: bool = False) -> str:
    name = py_name(node.id)
    error_check = f'    if state.get("_glg_error_from") == {node.id!r}:\n        return "error"\n' if has_error_edge else ""
    if node.type in {NodeType.JSON_EXTRACTOR, NodeType.JSON_VALIDATOR}:
        validation_field = str(node.config.get("validationField", "validation_result"))
        return f'''def route_{name}(state: AgentState) -> str:
{error_check}    validation = state.get({validation_field!r})
    if isinstance(validation, dict) and validation.get("valid") is True:
        return "valid"
    return "invalid"
'''
    if node.type == NodeType.AI_ROUTER:
        route_field = py_name(str(node.config.get("routeField", "route_key")))
        fallback = str(node.config.get("fallback", "other"))
        return f'''def route_{name}(state: AgentState) -> str:
{error_check}    return str(state.get("{route_field}") or {fallback!r})
'''
    if node.type == NodeType.HUMAN_APPROVAL:
        action_field = py_name(str(node.config.get("actionField", "approval_action")))
        fallback = str(node.config.get("fallback", "rejected"))
        return f'''def route_{name}(state: AgentState) -> str:
{error_check}    return str(state.get("{action_field}") or {fallback!r})
'''
    if node.type != NodeType.CONDITION:
        return f'''def route_{name}(state: AgentState) -> str:
{error_check}    return "__success__"
'''
    field = py_name(str(node.config.get("field", "")))
    operator = str(node.config.get("operator", "equals"))
    value = str(node.config.get("value", ""))
    true_branch = str(node.config.get("trueBranch", "true"))
    false_branch = str(node.config.get("falseBranch", "false"))
    fallback = str(node.config.get("fallback", "fallback"))
    return f'''def route_{name}(state: AgentState) -> str:
{error_check}    current = state.get("{field}")
    expected = {value!r}
    if _compare(current, expected, "{operator}"):
        return {true_branch!r}
    if {false_branch!r}:
        return {false_branch!r}
    return {fallback!r}


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
'''


def _graph_py(project: ProjectIR) -> str:
    for_each_internal_ids = _for_each_internal_node_ids(project)
    nodes_by_id = {node.id: node for node in project.nodes}
    top_level_error_targets = _top_level_error_targets(project)
    normal_edges = [
        edge
        for edge in project.edges
        if edge.kind not in {EdgeKind.CONDITIONAL, EdgeKind.WORKER, EdgeKind.ERROR}
        and edge.source not in for_each_internal_ids
        and edge.target not in for_each_internal_ids
        and edge.sourceHandle != "item"
    ]
    conditional_edges = [
        edge
        for edge in project.edges
        if edge.kind == EdgeKind.CONDITIONAL and edge.source not in for_each_internal_ids and edge.target not in for_each_internal_ids
    ]
    condition_edge_map: dict[str, dict[str, str]] = defaultdict(dict)
    for edge in conditional_edges:
        condition_edge_map[edge.source][edge.sourceHandle or edge.label or "default"] = edge.target

    worker_bridge_edges = _parallel_worker_bridge_edges(project)
    for_each_bridge_edges = _for_each_bridge_edges(project)
    success_edges = [*normal_edges, *worker_bridge_edges, *for_each_bridge_edges]
    non_start_nodes = [node for node in project.nodes if node.type not in {NodeType.START, NodeType.PARALLEL_WORKER} and node.id not in for_each_internal_ids]
    condition_ids = {
        node.id
        for node in project.nodes
        if node.type in {NodeType.CONDITION, NodeType.AI_ROUTER, NodeType.HUMAN_APPROVAL, NodeType.JSON_EXTRACTOR, NodeType.JSON_VALIDATOR}
    }
    condition_ids.update(top_level_error_targets)
    has_human_approval = any(node.type == NodeType.HUMAN_APPROVAL for node in project.nodes)

    imports = ["from .nodes import " + ", ".join(py_name(node.id) for node in non_start_nodes)]
    condition_nodes = [node for node in non_start_nodes if node.id in condition_ids]
    if condition_nodes:
        imports.append("from .routers import " + ", ".join(f"route_{py_name(node.id)}" for node in condition_nodes))

    lines = [
        "from __future__ import annotations",
        "",
        *(["from langgraph.checkpoint.memory import InMemorySaver"] if has_human_approval else []),
        "from langgraph.graph import START, END, StateGraph",
        "",
        "from .state import AgentState",
        *imports,
        "",
        "",
        "builder = StateGraph(AgentState)",
        "",
    ]

    for node in non_start_nodes:
        lines.append(f'builder.add_node("{node.id}", {py_name(node.id)})')
    lines.append("")

    start_ids = {node.id for node in project.nodes if node.type == NodeType.START}
    direct_reply_ids = {node.id for node in project.nodes if node.type == NodeType.DIRECT_REPLY}
    for source, target in top_level_error_targets.items():
        condition_edge_map[source]["error"] = target
        source_node = nodes_by_id.get(source)
        source_has_condition_branches = source_node is not None and source_node.type in {
            NodeType.CONDITION,
            NodeType.AI_ROUTER,
            NodeType.HUMAN_APPROVAL,
            NodeType.JSON_EXTRACTOR,
            NodeType.JSON_VALIDATOR,
        }
        if not source_has_condition_branches:
            success_target = next((edge.target for edge in success_edges if edge.source == source), "")
            if not success_target and source in direct_reply_ids:
                success_target = "__end__"
            if success_target:
                condition_edge_map[source]["__success__"] = success_target

    for edge in success_edges:
        if edge.source in top_level_error_targets:
            continue
        if edge.source in start_ids:
            lines.append(f'builder.add_edge(START, "{edge.target}")')
        elif edge.source not in direct_reply_ids:
            lines.append(f'builder.add_edge("{edge.source}", "{edge.target}")')

    for source, mapping in condition_edge_map.items():
        lines.append(
            textwrap.dedent(
                f'''
                builder.add_conditional_edges(
                    "{source}",
                    route_{py_name(source)},
                    {json.dumps(mapping, indent=4)},
                )
                '''
            ).strip()
        )

    for reply_id in direct_reply_ids:
        if reply_id in top_level_error_targets:
            continue
        lines.append(f'builder.add_edge("{reply_id}", END)')

    if has_human_approval:
        lines.extend(["", "checkpointer = InMemorySaver()", "graph = builder.compile(checkpointer=checkpointer)", ""])
    else:
        lines.extend(["", "graph = builder.compile()", ""])
    return "\n".join(lines)


def _parallel_worker_bridge_edges(project: ProjectIR) -> list[EdgeIR]:
    nodes_by_id = {node.id: node for node in project.nodes}
    workers_by_parent: dict[str, list[str]] = defaultdict(list)
    for node in project.nodes:
        if node.type == NodeType.PARALLEL_WORKER:
            parent_id = str(node.config.get("parentNodeId") or "").strip()
            if parent_id:
                workers_by_parent[parent_id].append(node.id)
    result: list[EdgeIR] = []
    for parent_id, worker_ids in workers_by_parent.items():
        if parent_id not in nodes_by_id:
            continue
        worker_id_set = set(worker_ids)
        target = ""
        for edge in project.edges:
            if edge.kind == EdgeKind.WORKER and edge.source in worker_id_set and edge.target not in worker_id_set:
                target = edge.target
                break
        if target:
            result.append(EdgeIR(id=f"bridge_{parent_id}_{target}", source=parent_id, target=target, kind=EdgeKind.NORMAL))
    return result


def _for_each_internal_node_ids(project: ProjectIR) -> set[str]:
    nodes_by_id = {node.id: node for node in project.nodes}
    outgoing: dict[str, list[EdgeIR]] = defaultdict(list)
    for edge in project.edges:
        outgoing[edge.source].append(edge)
    internal: set[str] = set()
    for node in project.nodes:
        if node.type != NodeType.FOR_EACH:
            continue
        item_target = _target_for_handle_codegen([edge for edge in outgoing[node.id] if edge.kind != EdgeKind.ERROR], "item")
        merge_id = _find_for_each_merge_id_codegen(item_target, nodes_by_id, outgoing) if item_target else ""
        if not item_target or not merge_id:
            continue
        queue: list[str] = [item_target]
        seen: set[str] = set()
        while queue:
            node_id = queue.pop(0)
            if node_id in seen:
                continue
            seen.add(node_id)
            internal.add(node_id)
            if node_id == merge_id:
                continue
            for edge in outgoing[node_id]:
                if edge.kind != EdgeKind.WORKER:
                    queue.append(edge.target)
    return internal


def _for_each_bridge_edges(project: ProjectIR) -> list[EdgeIR]:
    nodes_by_id = {node.id: node for node in project.nodes}
    outgoing: dict[str, list[EdgeIR]] = defaultdict(list)
    for edge in project.edges:
        outgoing[edge.source].append(edge)
    result: list[EdgeIR] = []
    for node in project.nodes:
        if node.type != NodeType.FOR_EACH:
            continue
        item_target = _target_for_handle_codegen([edge for edge in outgoing[node.id] if edge.kind != EdgeKind.ERROR], "item")
        merge_id = _find_for_each_merge_id_codegen(item_target, nodes_by_id, outgoing) if item_target else ""
        if not merge_id:
            continue
        exit_target = _first_target_codegen([edge for edge in outgoing[merge_id] if edge.kind == EdgeKind.NORMAL])
        if exit_target:
            result.append(EdgeIR(id=f"bridge_{node.id}_{exit_target}", source=node.id, target=exit_target, kind=EdgeKind.NORMAL))
    return result


def _find_for_each_merge_id_codegen(start_id: str, nodes_by_id: dict[str, NodeIR], outgoing: dict[str, list[EdgeIR]]) -> str:
    seen: set[str] = set()
    queue: list[str] = [start_id]
    while queue:
        node_id = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes_by_id.get(node_id)
        if not node:
            continue
        if node.type == NodeType.MERGE:
            return node_id
        for edge in outgoing[node_id]:
            if edge.kind != EdgeKind.WORKER:
                queue.append(edge.target)
    return ""


def _target_for_handle_codegen(edges: list[EdgeIR], handle: str) -> str:
    for edge in edges:
        if edge.sourceHandle == handle:
            return edge.target
    return _first_target_codegen(edges)


def _first_target_codegen(edges: list[EdgeIR]) -> str:
    return edges[0].target if edges else ""


def _nodes_helpers() -> str:
    return '''def _run_node_with_policy(state: AgentState, fn: Any, config: dict[str, Any], node_id: str, node_meta: dict[str, Any]) -> dict[str, Any]:
    policy = _node_runtime_policy(config)
    max_attempts = 1 + (policy["maxRetries"] if policy["retryEnabled"] else 0)
    attempts: list[dict[str, Any]] = []
    last_exc: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            result = _call_node_with_timeout(lambda: fn(state), policy["timeoutSec"])
            attempts.append({"attempt": attempt_index, "status": "ok", "durationMs": round((time.perf_counter() - started) * 1000, 2)})
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            last_exc = exc
            error_type = _policy_error_type(exc)
            attempts.append({"attempt": attempt_index, "status": "error", "durationMs": round((time.perf_counter() - started) * 1000, 2), "errorType": error_type, "message": str(exc)})
            if attempt_index < max_attempts and _should_retry_error(policy, error_type, exc):
                backoff_ms = min(max(policy["backoffMs"], 0) * attempt_index, 5000)
                if backoff_ms:
                    time.sleep(backoff_ms / 1000)
                continue
            break
    assert last_exc is not None
    payload = _runtime_error_payload(node_id, node_meta, last_exc)
    payload["attempts"] = attempts
    payload["errorPolicy"] = policy["errorPolicy"]
    if policy["timeoutSec"]:
        payload["timeoutSec"] = policy["timeoutSec"]
    if policy["errorPolicy"] == "fallback":
        delta = render_json_object(str(policy.get("fallbackOutputJson") or "{}"), state)
        if policy.get("errorOutputField"):
            delta[str(policy["errorOutputField"])] = payload
        return delta
    if policy["errorPolicy"] == "continue":
        return {str(policy.get("errorOutputField") or "last_error"): payload}
    raise RuntimeError(json.dumps(payload, ensure_ascii=False, default=str))


def _call_node_with_timeout(fn: Any, timeout_sec: float | None) -> dict[str, Any]:
    if not timeout_sec:
        return fn()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FutureTimeoutError as exc:
        future.cancel()
        raise RuntimeError(f"timeout: 节点执行超过 {timeout_sec}s。") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _node_runtime_policy(config: dict[str, Any]) -> dict[str, Any]:
    retry = _parse_json_object(str(config.get("retryPolicyJson") or "{}"))
    error_policy = str(config.get("errorPolicy") or "default").strip().lower() or "default"
    if error_policy not in {"default", "fail_fast", "route_error", "continue", "fallback"}:
        error_policy = "default"
    max_retries = min(_positive_int(retry.get("maxRetries"), 0), 5)
    retry_types = retry.get("retryOnErrorTypes")
    return {
        "retryEnabled": _truthy(retry.get("enabled")) and max_retries > 0,
        "maxRetries": max_retries,
        "backoffMs": min(_positive_int(retry.get("backoffMs"), 0), 30000),
        "retryOnErrorTypes": [str(item).strip() for item in retry_types if str(item).strip()] if isinstance(retry_types, list) else [],
        "timeoutSec": _positive_float(config.get("nodeTimeoutSec"), 0) or None,
        "errorPolicy": error_policy,
        "fallbackOutputJson": str(config.get("fallbackOutputJson") or "{}"),
        "errorOutputField": str(config.get("errorOutputField") or "").strip(),
    }


def _should_retry_error(policy: dict[str, Any], error_type: str, exc: Exception) -> bool:
    allowed = set(policy.get("retryOnErrorTypes") or [])
    if not allowed:
        return True
    return error_type in allowed or exc.__class__.__name__ in allowed


def _policy_error_type(exc: Exception) -> str:
    text = str(exc).lower()
    if "timeout" in text or "超时" in text:
        return "timeout"
    return exc.__class__.__name__


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _chat_model(provider: str, model: str, base_url: str = "", api_key_env: str = "", api_version: str = "", organization: str = ""):
    provider_key = provider.strip().lower().replace("-", "_") or "openai"
    api_key = env(api_key_env) if api_key_env else None
    if provider_key == "azure_openai":
        from langchain_openai import AzureChatOpenAI

        kwargs: dict[str, Any] = {
            "azure_deployment": model,
            "azure_endpoint": base_url,
            "api_version": api_version,
        }
        if api_key:
            kwargs["api_key"] = api_key
        return AzureChatOpenAI(**kwargs)
    if base_url or provider_key in {"custom", "openai_compatible", "deepseek", "moonshot", "qwen", "zhipu", "minimax", "baichuan", "groq", "ollama"}:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": model}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        elif provider_key == "ollama":
            kwargs["api_key"] = "ollama"
        if organization:
            kwargs["organization"] = organization
        return ChatOpenAI(**kwargs)
    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    return init_chat_model(model, model_provider=provider_key, **kwargs)


def _system_with_skills(system_prompt: str, skill_ids: list[str]) -> str:
    selected = [SKILL_REGISTRY[skill_id] for skill_id in skill_ids if skill_id in SKILL_REGISTRY]
    if not selected:
        return system_prompt.strip()
    sections = ["可用 Skills:"]
    for skill in selected:
        name = str(skill.get("name") or skill.get("id") or "Skill")
        content = _skill_runtime_content(skill).strip() or "（该 Skill 暂无内容）"
        sections.append(f"### {name}\\n{content}")
    skill_prompt = "\\n\\n".join(sections)
    return f"{system_prompt.strip()}\\n\\n{skill_prompt}".strip() if system_prompt.strip() else skill_prompt


def _skill_runtime_content(skill: dict[str, Any]) -> str:
    content = str(skill.get("content") or "").strip()
    metadata = _skill_metadata(skill)
    sections: list[str] = []
    if content:
        sections.append(_limit_text(content, 60000, "SKILL.md 内容已截断"))
    package_metadata = metadata.get("packageMetadata") if isinstance(metadata.get("packageMetadata"), dict) else {}
    if package_metadata:
        summary = _skill_package_metadata_summary(package_metadata)
        if summary:
            sections.append(f"#### Package Metadata\\n{summary}")
    references = metadata.get("relatedMarkdown")
    if isinstance(references, list) and references:
        reference_text = _skill_references_runtime_text(references)
        if reference_text:
            sections.append(f"#### Related References\\n{reference_text}")
    support_files = metadata.get("supportFiles")
    if isinstance(support_files, list) and support_files:
        support_text = _skill_support_files_runtime_text(support_files)
        if support_text:
            sections.append(f"#### Support Files\\n{support_text}")
    if metadata.get("relatedMarkdownTruncated"):
        sections.append("注意：部分 reference 文件因数量或长度限制已截断。需要更精确内容时，请使用文件读取工具读取对应路径。")
    return "\\n\\n".join(sections)


def _skill_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    raw = skill.get("metadataJson")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _skill_package_metadata_summary(metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("version", "organization", "technology", "category", "abstract"):
        value = metadata.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    references = metadata.get("references")
    if isinstance(references, list) and references:
        compact = ", ".join(str(item) for item in references[:8] if str(item).strip())
        if compact:
            lines.append(f"- references: {compact}")
    return _limit_text("\\n".join(lines), 4000, "package metadata 已截断")


def _skill_references_runtime_text(references: list[Any]) -> str:
    lines: list[str] = []
    used = 0
    for raw_item in references:
        if not isinstance(raw_item, dict):
            continue
        path = str(raw_item.get("path") or "reference.md")
        title = str(raw_item.get("title") or path)
        content = str(raw_item.get("content") or "").strip()
        if not content:
            continue
        block = f"##### {title} ({path})\\n{content}"
        remaining = 30000 - used
        if remaining <= 0:
            break
        block = _limit_text(block, remaining, "reference 内容已截断")
        used += len(block)
        lines.append(block)
    return "\\n\\n".join(lines)


def _skill_support_files_runtime_text(files: list[Any]) -> str:
    lines: list[str] = []
    used = 0
    for raw_item in files:
        if not isinstance(raw_item, dict):
            continue
        path = str(raw_item.get("path") or "").strip()
        if not path:
            continue
        kind = str(raw_item.get("kind") or "file")
        size = raw_item.get("size", 0)
        preview = str(raw_item.get("preview") or "").strip()
        line = f"- {kind}: {path} ({size} bytes)"
        if preview:
            line = f"{line}\\n  preview:\\n{_indent_text(_limit_text(preview, 1800, 'preview 已截断'), '  ')}"
        remaining = 12000 - used
        if remaining <= 0:
            break
        line = _limit_text(line, remaining, "support files 清单已截断")
        used += len(line)
        lines.append(line)
    return "\\n".join(lines)


def _limit_text(value: str, max_chars: int, note: str) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\\n\\n[{note}]"


def _indent_text(value: str, prefix: str) -> str:
    return "\\n".join(f"{prefix}{line}" for line in value.splitlines())


def _messages_from_state(state: AgentState, system_prompt: str = "") -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    if system_prompt:
        messages.append(("system", system_prompt))
    value = state.get("messages", "")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                role = str(item.get("role") or "user")
                content = str(item.get("content") or "")
                if content:
                    messages.append((role, content))
            else:
                content = getattr(item, "content", None)
                if content:
                    messages.append(("user", str(content)))
    elif value:
        messages.append(("user", str(value)))
    if not messages or all(role == "system" for role, _content in messages):
        messages.append(("user", ""))
    return messages


def _agent_user_content(state: AgentState, user_prompt: str = "") -> str:
    if user_prompt.strip():
        return render_template(user_prompt, state)
    user_text = ""
    value = state.get("messages", "")
    if isinstance(value, list):
        user_text = "\\n".join(str(getattr(item, "content", item.get("content", item) if isinstance(item, dict) else item)) for item in value)
    elif value:
        user_text = str(value)
    return "用户输入：\\n" + user_text + "\\n\\n当前流程 state：\\n" + json.dumps(dict(state), ensure_ascii=False, default=str, indent=2)


_MISSING = object()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "approve", "auto"}


def _resolve_input_mappings(mappings: list[dict[str, Any]], state: AgentState) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        name = str(mapping.get("name") or "").strip()
        if not name:
            continue
        result[name] = _resolve_mapping_entry(mapping, state)
    return result


def _resolve_mapping_entry(mapping: dict[str, Any], state: AgentState) -> Any:
    source_type = str(mapping.get("sourceType") or mapping.get("source_type") or "state").strip().lower()
    source = str(mapping.get("source") or "")
    value_type = str(mapping.get("valueType") or mapping.get("value_type") or "auto")
    transform = str(mapping.get("transform") or "none").strip().lower()
    transform_args = _render_transform_args(mapping.get("transformArgsJson") or mapping.get("transform_args_json"), state)
    return _resolve_mapping_value(source_type, source, value_type, state, transform, transform_args)


def _resolve_mapping_value(source_type: str, source: str, value_type: str, state: AgentState, transform: str = "none", transform_args: dict[str, Any] | None = None) -> Any:
    if source_type == "state":
        value = _get_path(state, source)
    elif source_type == "literal":
        value = source
    elif source_type == "json":
        value = json.loads(render_template(source, state))
    else:
        value = render_template(source, state)
    value = _apply_mapping_transform(value, transform, transform_args or {}, state)
    return _coerce_mapped_value(value, value_type)


def _render_transform_args(value: Any, state: AgentState) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    parsed = json.loads(render_template(text, state))
    if not isinstance(parsed, dict):
        raise RuntimeError("Transform 参数必须是 JSON object。")
    return parsed


def _apply_mapping_transform(value: Any, transform: str, args: dict[str, Any], state: AgentState) -> Any:
    kind = str(transform or "none").strip().lower()
    if kind in {"", "none"}:
        return value
    if kind == "default":
        return _resolve_transform_value(args.get("value", args.get("default")), state) if _is_empty_value(value) else value
    if kind == "coalesce":
        candidates = [value]
        raw_candidates = args.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raw_candidates = [raw_candidates]
        candidates.extend(_resolve_transform_value(candidate, state) for candidate in raw_candidates)
        for candidate in candidates:
            if not _is_empty_value(candidate):
                return candidate
        return None
    if kind == "split":
        separator = str(args.get("separator", "\\n"))
        text = _state_value_to_text(value)
        parts = text.split(separator) if separator else list(text)
        if _truthy(args.get("trim", True)):
            parts = [part.strip() for part in parts]
        if _truthy(args.get("dropEmpty", args.get("drop_empty", True))):
            parts = [part for part in parts if part != ""]
        return parts
    if kind == "join":
        separator = str(args.get("separator", "\\n"))
        values = value if isinstance(value, list) else ([] if value is None else [value])
        return separator.join(_state_value_to_text(item) for item in values)
    if kind == "pick":
        return _pick_paths(value, _normalize_string_list(args.get("paths") or args.get("fields")))
    if kind == "omit":
        return _omit_paths(value, _normalize_string_list(args.get("paths") or args.get("fields")))
    raise RuntimeError(f"不支持的 Transform：{transform}")


def _resolve_transform_value(value: Any, state: AgentState) -> Any:
    if isinstance(value, dict) and ("sourceType" in value or "source" in value):
        return _resolve_mapping_entry(value, state)
    if isinstance(value, str):
        return render_template(value, state)
    return value


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _coerce_mapped_value(value: Any, value_type: str) -> Any:
    kind = str(value_type or "auto").strip().lower()
    if kind in {"", "auto", "any"}:
        return value
    if kind == "string":
        return _state_value_to_text(value)
    if kind == "number":
        return float(value)
    if kind == "integer":
        return int(value)
    if kind == "boolean":
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"} if not isinstance(value, bool) else value
    if kind == "json":
        return value if isinstance(value, (dict, list)) else json.loads(str(value or "null"))
    return value


def _get_path(value: Any, path: str, default: Any = None) -> Any:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return value
    resolved = _get_path_parts(value, parts)
    return default if resolved is _MISSING else resolved


def _get_path_parts(value: Any, parts: list[str]) -> Any:
    if not parts:
        return value
    part = parts[0]
    if part.endswith("[]"):
        key = part[:-2]
        collection = _get_path_part(value, key) if key else value
        if not isinstance(collection, list):
            return []
        values: list[Any] = []
        for item in collection:
            child = _get_path_parts(item, parts[1:])
            if child is _MISSING:
                continue
            if isinstance(child, list):
                values.extend(child)
            else:
                values.append(child)
        return values
    next_value = _get_path_part(value, part)
    if next_value is _MISSING:
        return _MISSING
    return _get_path_parts(next_value, parts[1:])


def _get_path_part(value: Any, part: str) -> Any:
    if part == "":
        return value
    if isinstance(value, dict):
        return value.get(part, _MISSING)
    if isinstance(value, list) and part.isdigit():
        index = int(part)
        return value[index] if 0 <= index < len(value) else _MISSING
    return _MISSING


def _set_path(target: dict[str, Any], path: str, value: Any, base: dict[str, Any] | None = None) -> None:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return
    if any(part.endswith("[]") for part in parts):
        raise RuntimeError(f"写入路径不支持数组通配：{path}")
    if len(parts) == 1:
        target[parts[0]] = value
        return
    first = parts[0]
    if first not in target:
        existing = (base or {}).get(first)
        target[first] = dict(existing) if isinstance(existing, dict) else {}
    current = target[first]
    if not isinstance(current, dict):
        current = {}
        target[first] = current
    for part in parts[1:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _pick_paths(value: Any, paths: list[str]) -> Any:
    if not paths:
        return value
    result: dict[str, Any] = {}
    for path in paths:
        picked = _get_path(value, path, _MISSING)
        if picked is _MISSING:
            continue
        _set_path(result, path.replace("[].", "."), picked)
    return result


def _omit_paths(value: Any, paths: list[str]) -> Any:
    try:
        result = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return value
    for path in paths:
        _delete_path(result, path)
    return result


def _delete_path(value: Any, path: str) -> None:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return
    current = value
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return
    leaf = parts[-1]
    if isinstance(current, dict):
        current.pop(leaf, None)
    elif isinstance(current, list) and leaf.isdigit():
        index = int(leaf)
        if 0 <= index < len(current):
            current.pop(index)


def _run_for_each_node(
    state: AgentState,
    items_field: str,
    item_field: str,
    index_field: str,
    max_items: int,
    item_start: str,
    merge_id: str,
    node_functions: dict[str, Any],
    node_meta: dict[str, dict[str, Any]],
    normal_map: dict[str, str],
    conditional_map: dict[str, dict[str, str]],
    error_map: dict[str, str],
    merge_reducers: list[dict[str, Any]],
    merge_result_field: str,
    result_field: str = "",
    execution_mode: str = "sequential",
    max_concurrency: int = 3,
    preserve_order: bool = True,
    item_failure_policy: str = "fail_fast",
) -> dict[str, Any]:
    if not item_start or not merge_id:
        raise RuntimeError("ForEach 导出缺少循环体或 Merge 节点。")
    items_value = _get_path(state, items_field)
    if isinstance(items_value, dict) and isinstance(items_value.get("tasks"), list):
        items = items_value.get("tasks") or []
    elif isinstance(items_value, list):
        items = items_value
    else:
        raise RuntimeError(f"ForEach 需要 state.{items_field} 是 array。")
    selected_items = list(items)[:max_items]

    def run_item(index: int, item: Any) -> dict[str, Any]:
        item_state = dict(state)
        item_state[item_field] = item
        item_state[index_field] = index
        current = item_start
        visited = 0
        reached_merge = False
        while current and visited < 80:
            if current == merge_id:
                reached_merge = True
                break
            visited += 1
            meta = node_meta.get(current, {})
            node_type = str(meta.get("type") or "")
            if node_type in {"for_each", "merge"}:
                raise RuntimeError(f"ForEach v1 不支持嵌套或提前执行 {node_type} 节点。")
            fn = node_functions.get(current)
            if fn is None:
                raise RuntimeError(f"ForEach 子链路缺少节点函数：{current}")
            try:
                item_state.update(fn(item_state))
            except Exception as exc:
                error_target = error_map.get(current)
                if not error_target:
                    raise
                item_state["last_error"] = _runtime_error_payload(current, meta, exc)
                current = error_target
                continue
            branch_map = conditional_map.get(current) or {}
            if branch_map:
                handle = _choose_for_each_handle(meta, item_state)
                current = branch_map.get(handle) or next(iter(branch_map.values()), "")
            else:
                current = normal_map.get(current, "")
        if visited >= 80:
            raise RuntimeError("ForEach 子链路超过 80 步，可能存在循环。")
        if not reached_merge:
            raise RuntimeError(f"ForEach 第 {index + 1} 项没有到达 Merge 节点。")
        return {"index": index, "item": item, "itemState": item_state, "reachedMerge": reached_merge}

    parallel = str(execution_mode or "sequential").strip().lower() == "parallel" and len(selected_items) > 1
    results: list[dict[str, Any]] = []
    if parallel:
        with ThreadPoolExecutor(max_workers=min(max(1, int(max_concurrency or 3)), len(selected_items))) as executor:
            futures = {executor.submit(run_item, index, item): (index, item) for index, item in enumerate(selected_items)}
            for future in as_completed(futures):
                index, item = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    if str(item_failure_policy or "fail_fast") != "collect_errors":
                        raise
                    error_payload = _runtime_error_payload("__for_each_item__", {"type": "for_each", "label": "ForEach item"}, exc)
                    item_state = dict(state)
                    item_state[item_field] = item
                    item_state[index_field] = index
                    item_state["last_error"] = error_payload
                    item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                    results.append({"index": index, "item": item, "itemState": item_state, "error": error_payload})
        if preserve_order:
            results.sort(key=lambda row: int(row["index"]))
    else:
        for index, item in enumerate(selected_items):
            try:
                results.append(run_item(index, item))
            except Exception as exc:
                if str(item_failure_policy or "fail_fast") != "collect_errors":
                    raise
                error_payload = _runtime_error_payload("__for_each_item__", {"type": "for_each", "label": "ForEach item"}, exc)
                item_state = dict(state)
                item_state[item_field] = item
                item_state[index_field] = index
                item_state["last_error"] = error_payload
                item_state.setdefault("item_result", {"ok": False, "error": error_payload})
                results.append({"index": index, "item": item, "itemState": item_state, "error": error_payload})
    item_states = [result["itemState"] for result in results]
    iterations = []
    for result in results:
        iteration = {"index": result["index"], "item": _compact_value(result["item"]), "output": _compact_value(result["itemState"])}
        if result.get("error"):
            iteration["error"] = _compact_value(result["error"])
        iterations.append(iteration)
    delta = _apply_merge_reducers(dict(state), item_states, merge_reducers, merge_result_field, "for_each")
    if merge_result_field and isinstance(delta.get(merge_result_field), dict):
        delta[merge_result_field]["iterations"] = iterations
    if result_field:
        delta[result_field] = {"ok": True, "itemsField": items_field, "count": len(item_states), "mergeNodeId": merge_id, "iterations": iterations, "parallel": parallel, "itemFailurePolicy": item_failure_policy}
    return delta


def _apply_merge_reducers(state: dict[str, Any], item_states: list[dict[str, Any]], reducers: list[dict[str, Any]], result_field: str = "merge_result", merge_mode: str = "auto") -> dict[str, Any]:
    if not reducers:
        reducers = [{"target": "merged_results", "source": "item_result", "reducer": "append"}]
    delta: dict[str, Any] = {}
    summaries: list[dict[str, Any]] = []
    for reducer in reducers:
        target = str(reducer.get("target") or reducer.get("field") or reducer.get("name") or "").strip()
        source = str(reducer.get("source") or reducer.get("sourceField") or "").strip()
        operation = str(reducer.get("reducer") or reducer.get("operation") or "append").strip().lower()
        if not target or not source:
            continue
        values = [_get_path(item_state, source) for item_state in item_states]
        previous = _get_path({**state, **delta}, target)
        next_value = _reduce_values(operation, values, previous, target)
        _set_path(delta, target, next_value, {**state, **delta})
        summaries.append({"target": target, "source": source, "reducer": operation, "count": len(values), "value": _compact_value(next_value)})
    if result_field:
        delta[result_field] = {"ok": True, "mergeMode": merge_mode, "itemCount": len(item_states), "reducers": summaries}
    return delta


def _reduce_values(operation: str, values: list[Any], previous: Any, target: str) -> Any:
    if operation == "concat":
        result: list[Any] = []
        for value in values:
            if value is None:
                continue
            result.extend(value if isinstance(value, list) else [value])
        return result
    if operation == "merge":
        result = dict(previous) if isinstance(previous, dict) else {}
        for value in values:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise RuntimeError(f"Merge reducer merge 需要 object 值：{target}")
            result.update(value)
        return result
    if operation in {"overwrite", "last"}:
        return values[-1] if values else previous
    if operation == "first":
        for value in values:
            if value is not None:
                return value
        return previous
    return list(values)


def _choose_for_each_handle(meta: dict[str, Any], state: dict[str, Any]) -> str:
    node_type = str(meta.get("type") or "")
    config = meta.get("config") if isinstance(meta.get("config"), dict) else {}
    if node_type == "condition":
        field = str(config.get("field", ""))
        current = state.get(field)
        expected = str(config.get("value", ""))
        matched = _compare(current, expected, str(config.get("operator", "equals")))
        return str(config.get("trueBranch" if matched else "falseBranch", config.get("fallback", "fallback")))
    if node_type == "ai_router":
        return str(state.get(str(config.get("routeField", "route_key"))) or config.get("fallback", "other"))
    if node_type == "human_approval":
        return str(state.get(str(config.get("actionField", "approval_action"))) or config.get("fallback", "rejected"))
    if node_type in {"json_extractor", "json_validator"}:
        validation = state.get(str(config.get("validationField", "validation_result")))
        return "valid" if isinstance(validation, dict) and validation.get("valid") is True else "invalid"
    return str(config.get("fallback", "fallback"))


def _runtime_error_payload(node_id: str, meta: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "nodeId": node_id,
        "nodeType": str(meta.get("type") or ""),
        "nodeLabel": str(meta.get("label") or node_id),
        "errorType": exc.__class__.__name__,
        "message": str(exc),
    }


def _run_variable_assign(assignments: list[dict[str, Any]], inputs: dict[str, Any], state: AgentState, result_field: str = "assignment_result") -> dict[str, Any]:
    delta: dict[str, Any] = {}
    operations: list[dict[str, Any]] = []
    for raw in assignments:
        if not isinstance(raw, dict):
            continue
        target = str(raw.get("target") or raw.get("field") or raw.get("name") or "").strip()
        if not target:
            continue
        operation = str(raw.get("operation") or "overwrite").strip().lower()
        source_type = str(raw.get("sourceType") or raw.get("source_type") or "template").strip().lower()
        source = str(raw.get("source") if raw.get("source") is not None else raw.get("value") if raw.get("value") is not None else "")
        value_type = str(raw.get("valueType") or raw.get("value_type") or "auto")
        transform = str(raw.get("transform") or "none").strip().lower()
        transform_args = _render_transform_args(raw.get("transformArgsJson") or raw.get("transform_args_json"), {**dict(state), **delta})
        if source_type == "input":
            value = inputs.get(source)
            value = _apply_mapping_transform(value, transform, transform_args, {**dict(state), **delta})
            value = _coerce_mapped_value(value, value_type)
        else:
            value = _resolve_mapping_value(source_type, source, value_type, {**dict(state), **delta}, transform, transform_args)
        previous = _get_path({**dict(state), **delta}, target)
        if operation == "clear":
            next_value = None
        elif operation == "append":
            current = previous if isinstance(previous, list) else ([] if previous in (None, "") else [previous])
            next_value = [*current, *(value if isinstance(value, list) else [value])]
        elif operation == "merge":
            if not isinstance(value, dict):
                raise RuntimeError(f"Variable Assign merge 需要 object 值：{target}")
            next_value = {**(previous if isinstance(previous, dict) else {}), **value}
        else:
            operation = "overwrite"
            next_value = value
        _set_path(delta, target, next_value, {**dict(state), **delta})
        operations.append({"target": target, "operation": operation, "previous": _compact_value(previous), "value": _compact_value(next_value)})
    if result_field:
        delta[result_field] = {"ok": True, "changedFields": [item["target"] for item in operations], "operations": operations}
    return delta


def _validation_result(value: Any, schema: dict[str, Any]) -> dict[str, Any]:
    errors = _validate_json_value(value, schema, "$")
    return {"valid": not errors, "errors": errors, "schema": schema, "output": value}


def _validate_json_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = str(schema.get("type") or "object")
    if not _json_type_matches(value, expected_type):
        return [f"{path} expected {expected_type}, got {type(value).__name__}"]
    if "enum" in schema and isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']}")
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        if not any(_schema_condition_matches(value, item) for item in any_of if isinstance(item, dict)):
            errors.append(f"{path} must satisfy at least one anyOf condition")
    if expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and item_schema:
            for index, item in enumerate(value):
                errors.extend(_validate_json_value(item, item_schema, f"{path}[{index}]"))
        return errors
    if expected_type != "object" or not isinstance(value, dict):
        return errors
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = {str(item) for item in schema.get("required", []) if str(item)}
    for key in sorted(required):
        if key not in value or value.get(key) is None:
            errors.append(f"{path}.{key} is required")
    for key, property_schema in properties.items():
        if key not in value or value.get(key) is None:
            continue
        if isinstance(property_schema, dict):
            errors.extend(_validate_json_value(value.get(key), property_schema, f"{path}.{key}"))
    return errors


def _schema_condition_matches(value: Any, schema: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    required = {str(item) for item in schema.get("required", []) if str(item)}
    for key in required:
        if key not in value or value.get(key) in (None, ""):
            return False
    if schema.get("properties") or schema.get("type"):
        return not _validate_json_value(value, {**schema, "anyOf": []}, "$")
    return True


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _json_extractor_system_prompt(instruction: str, schema: dict[str, Any]) -> str:
    prompt = "你是 JSON Extractor。请严格根据 JSON Schema 从用户输入中抽取一个 JSON object。只输出 JSON object，不要输出 Markdown 或解释。缺失且非必填的字段可以省略。"
    if instruction.strip():
        prompt += "\\n\\n抽取说明：\\n" + instruction.strip()
    return prompt + "\\n\\nJSON Schema：\\n" + json.dumps(schema, ensure_ascii=False, indent=2)


def _repair_json_output(model_ref: Any, instruction: str, value: Any, schema: dict[str, Any], errors: list[str], source_text: str, raw_content: str = "") -> dict[str, Any]:
    system_prompt = "你是 JSON Repair。请把候选内容修复为严格符合 JSON Schema 的 JSON object。只输出 JSON object，不要输出 Markdown 或解释。不要编造与输入无关的信息。"
    if instruction.strip():
        system_prompt += "\\n\\n修复说明：\\n" + instruction.strip()
    system_prompt += "\\n\\nJSON Schema：\\n" + json.dumps(schema, ensure_ascii=False, indent=2)
    payload = {"validationErrors": errors, "candidate": value, "rawContent": raw_content, "sourceText": source_text}
    response = model_ref.invoke([
        ("system", system_prompt),
        ("user", "请修复以下 JSON 候选内容：\\n" + json.dumps(payload, ensure_ascii=False, default=str, indent=2)),
    ])
    response_content = getattr(response, "content", str(response))
    result: dict[str, Any] = {"attempted": True, "ok": False, "errors": list(errors), "before": _compact_value(value), "raw": _compact_value(response_content)}
    try:
        repaired = _parse_json_object_from_text(response_content)
    except RuntimeError as exc:
        result["errors"] = [*list(errors), str(exc)]
        return result
    validation = _validation_result(repaired, schema)
    result.update({"ok": validation["valid"], "output": repaired, "validation": validation, "after": _compact_value(repaired)})
    if not validation["valid"]:
        result["errors"] = validation["errors"]
    return result


def _last_message_content(value: Any) -> str:
    if isinstance(value, dict):
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            return _last_message_content(messages[-1])
        for key in ("output", "content", "final_answer"):
            if key in value:
                return str(value[key])
    content = getattr(value, "content", None)
    if content is not None:
        return str(content)
    return str(value)


def _selected_mcp_servers(server_ids: list[str], snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshot_by_id = {str(server.get("id") or ""): server for server in snapshots if isinstance(server, dict)}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for server_id in server_ids:
        server = MCP_SERVER_REGISTRY.get(server_id) or snapshot_by_id.get(server_id)
        if not server:
            continue
        key = str(server.get("id") or server.get("name") or server_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(server)
    return result


def _run_mcp_node_auto_call(server: dict[str, Any], args: dict[str, Any], state: AgentState, selection_mode: str, selection_instruction: str, fallback_to_heuristic: bool, model_ref: Any = None) -> dict[str, Any]:
    mode = (selection_mode or "heuristic").strip().lower()
    if mode not in {"manual", "heuristic", "model"}:
        mode = "heuristic"
    tools = list_mcp_tools(server)
    if mode == "manual":
        candidates = ", ".join(str(tool.get("name") or "") for tool in tools)
        raise RuntimeError(f"MCP Node 未选择 MCP Tool。可选工具：{candidates}" if candidates else "MCP Node 未选择 MCP Tool。")
    selected_by_model = False
    selection_reason = ""
    selected_tool: dict[str, Any] | None = None
    if mode == "model":
        try:
            if model_ref is None:
                raise RuntimeError("MCP Node 模型选择需要配置选择模型。")
            selection = _select_mcp_tool_with_model(model_ref, tools, args, state, selection_instruction)
            tool_name = str(selection.get("tool") or "").strip()
            selected_tool = next((tool for tool in tools if str(tool.get("name") or "") == tool_name), None)
            if not selected_tool:
                raise RuntimeError(f"模型选择了不存在或不可用的 MCP Tool：{tool_name}")
            selected_args = selection.get("args")
            if not isinstance(selected_args, dict):
                raise RuntimeError("模型选择 MCP Tool 时返回的 args 必须是 JSON object。")
            args = {**args, **selected_args}
            selected_by_model = True
            selection_reason = str(selection.get("reason") or "")
        except Exception:
            if not fallback_to_heuristic:
                raise
            selected_tool = _select_default_mcp_tool(tools, args, state)
            selection_reason = "model_selection_failed_fallback_to_heuristic"
    else:
        selected_tool = _select_default_mcp_tool(tools, args, state)
    tool_name = str((selected_tool or {}).get("name") or "").strip()
    if not tool_name:
        raise RuntimeError("MCP Node 未选择 MCP Tool，且无法自动选择。")
    args = _ensure_mcp_default_args(args, selected_tool, state)
    result = invoke_mcp_tool(server, tool_name, args)
    result["autoSelectedTool"] = True
    result["selectionMode"] = mode
    result["selectedByModel"] = selected_by_model
    result["selectionReason"] = selection_reason
    result["availableTools"] = [_mcp_tool_summary(tool) for tool in tools]
    return result


def _select_mcp_tool_with_model(model_ref: Any, tools: list[dict[str, Any]], base_args: dict[str, Any], state: AgentState, instruction: str) -> dict[str, Any]:
    tool_specs = [
        {
            "name": str(tool.get("name") or ""),
            "title": str(tool.get("title") or ""),
            "description": str(tool.get("description") or ""),
            "inputSchema": _compact_value(tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}, string_limit=1800, list_limit=10),
        }
        for tool in tools
        if str(tool.get("name") or "").strip()
    ]
    if not tool_specs:
        raise RuntimeError("MCP Server 未暴露可调用 Tool。")
    system_prompt = (
        "你负责为 MCP Node 选择一个 MCP Tool 并生成调用参数。"
        "只能从可用工具列表中选择一个工具；不要编造工具名。"
        "只输出 JSON object，格式固定为：{\\"tool\\":\\"工具名\\",\\"args\\":{},\\"reason\\":\\"选择原因\\"}。"
        "args 必须是 JSON object。"
    )
    if instruction.strip():
        system_prompt += "\\n\\n额外选择要求：\\n" + instruction.strip()
    system_prompt += "\\n\\n可用 MCP Tools：\\n" + json.dumps(tool_specs, ensure_ascii=False, indent=2)
    payload = {"state": _compact_value(dict(state), string_limit=3000, list_limit=12), "baseArgs": base_args, "queryText": _first_text(state.get("chat"), state.get("messages"), state.get("query"))}
    response = model_ref.invoke([("system", system_prompt), ("user", "请根据当前流程 state 和基础参数选择 MCP Tool：\\n" + json.dumps(payload, ensure_ascii=False, default=str, indent=2))])
    parsed = _parse_json_object_from_text(getattr(response, "content", str(response)))
    tool_name = str(parsed.get("tool") or parsed.get("toolName") or parsed.get("name") or "").strip()
    if not tool_name:
        raise RuntimeError("模型没有返回要调用的 MCP Tool。")
    args = parsed.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RuntimeError("模型选择 MCP Tool 时返回的 args 必须是 JSON object。")
    return {"tool": tool_name, "args": args, "reason": str(parsed.get("reason") or "")}


def _select_default_mcp_tool(tools: list[dict[str, Any]], args: dict[str, Any], state: AgentState) -> dict[str, Any]:
    available = [tool for tool in tools if str(tool.get("name") or "").strip()]
    if not available:
        raise RuntimeError("MCP Server 未暴露可调用 Tool。")
    if len(available) == 1:
        return available[0]
    by_name = {str(tool.get("name") or "").strip(): tool for tool in available}
    query_text = str(args.get("query") or "").strip() or _first_text(state.get("chat"), state.get("messages"), state.get("message"), state.get("input"), state.get("query"))
    if query_text and "web_search_exa" in by_name:
        return by_name["web_search_exa"]
    search_tools = [tool for tool in available if "search" in str(tool.get("name") or "").lower()]
    if len(search_tools) == 1:
        return search_tools[0]
    candidates = ", ".join(str(tool.get("name") or "") for tool in available)
    raise RuntimeError(f"MCP Node 未选择 Tool，且无法自动判断。可选工具：{candidates}")


def _ensure_mcp_default_args(args: dict[str, Any], selected_tool: dict[str, Any] | None, state: AgentState) -> dict[str, Any]:
    if args or not selected_tool:
        return args
    schema = selected_tool.get("inputSchema") if isinstance(selected_tool.get("inputSchema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    needs_query = "query" in properties or "query" in {str(item) for item in required}
    query = _first_text(state.get("chat"), state.get("messages"), state.get("message"), state.get("input"), state.get("query"))
    return {"query": query} if needs_query and query else args


def _mcp_tool_summary(tool: dict[str, Any]) -> dict[str, str]:
    return {"name": str(tool.get("name") or ""), "title": str(tool.get("title") or ""), "description": str(tool.get("description") or "")}


def _run_export_tool_agent_session(model_ref: Any, registered_tools: list[dict[str, Any]], system_prompt: str, user_prompt: str, max_iterations: int, state: AgentState) -> tuple[str, list[dict[str, Any]]]:
    messages: list[tuple[str, str]] = [
        ("system", _export_tool_agent_system_prompt(system_prompt, registered_tools, max_iterations)),
        ("user", user_prompt),
    ]
    calls: list[dict[str, Any]] = []
    final_answer = ""
    for iteration in range(max(1, min(int(max_iterations or 4), 12))):
        response = model_ref.invoke(messages)
        content = getattr(response, "content", str(response))
        decision = _parse_json_object_from_text(content, fallback={"tool_calls": [], "final_answer": content})
        tool_calls = [item for item in decision.get("tool_calls", []) if isinstance(item, dict)] if isinstance(decision.get("tool_calls"), list) else []
        if not tool_calls:
            final_answer = str(decision.get("final_answer") or content or "")
            break
        observations: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls, start=1):
            started = time.perf_counter()
            tool_name = str(tool_call.get("tool") or tool_call.get("name") or "").strip()
            args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
            tool_config = _find_export_tool_config(registered_tools, tool_name)
            if not tool_config:
                observation = {"ok": False, "error": f"未知 Tool：{tool_name}", "errorType": "tool_args"}
                source = ""
                server_name = ""
                agent_name = ""
                raw_tool_name = tool_name
            else:
                source = str(tool_config.get("source") or ("mcp" if tool_config.get("server") else "agent"))
                server_name = str((tool_config.get("server") or {}).get("name") or "")
                agent_name = str(tool_config.get("agentName") or "")
                raw_tool_name = str(tool_config.get("toolName") or tool_config.get("name") or tool_name)
                observation = _invoke_export_registered_tool(tool_config, args, state)
            calls.append({
                "iteration": iteration + 1,
                "index": index,
                "tool": tool_name,
                "args": args,
                "observation": _compact_value(observation, string_limit=6000, list_limit=12),
                "source": source,
                "serverName": server_name,
                "agentName": agent_name,
                "toolName": raw_tool_name,
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
                "errorType": observation.get("errorType") if isinstance(observation, dict) else None,
            })
            observations.append({"tool": tool_name, "observation": observation})
        messages.append(("assistant", content))
        messages.append(("user", "工具执行结果：\\n" + json.dumps(observations, ensure_ascii=False, indent=2) + "\\n请继续；如果已经足够，请返回 final_answer。"))
    return final_answer or "Agent 已停止，但模型没有给出 final_answer。", calls


def _export_tool_agent_system_prompt(system_prompt: str, registered_tools: list[dict[str, Any]], max_iterations: int) -> str:
    tool_lines = [
        {
            "name": tool.get("name"),
            "description": tool.get("description"),
            "args": (tool.get("inputSchema") or {}).get("properties", {}),
            "required": (tool.get("inputSchema") or {}).get("required", []),
        }
        for tool in registered_tools
    ]
    instructions = (
        "你是一个可以自主调用工具的 Agent。"
        f"最多进行 {max_iterations} 轮工具调用。"
        "每次回复必须是 JSON，格式为："
        "{\\"tool_calls\\":[{\\"tool\\":\\"工具名称\\",\\"args\\":{}}],\\"final_answer\\":\\"\\"}。"
        "如果还需要工具，填写 tool_calls；如果已经完成，tool_calls 为空数组，并填写 final_answer。不要输出 Markdown。"
    )
    return "\\n\\n".join(part for part in (system_prompt, instructions, "可用工具：\\n" + json.dumps(tool_lines, ensure_ascii=False, indent=2)) if part).strip()


def _find_export_tool_config(tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    normalized = name.strip().lower()
    for tool in tools:
        if normalized in {str(tool.get("id") or "").lower(), str(tool.get("name") or "").lower()}:
            return tool
    return None


def _invoke_export_registered_tool(tool_config: dict[str, Any], args: dict[str, Any], state: AgentState) -> dict[str, Any]:
    try:
        if tool_config.get("server"):
            result = invoke_mcp_tool(tool_config["server"], str(tool_config.get("toolName") or tool_config.get("name") or ""), args)
            return {"ok": True, "result": _compact_value(result)}
        if tool_config.get("source") == "agent" or tool_config.get("projectId"):
            input_text = _first_text(args.get("input"), args.get("query"), args.get("task"), args.get("message"))
            state_patch = args.get("statePatch") if isinstance(args.get("statePatch"), dict) else {}
            result = run_embedded_agent(str(tool_config.get("projectId") or ""), input_text, state_patch, state)
            return {"ok": bool(result.get("ok", True)), "result": _compact_value(result), "errorType": result.get("errorType")}
        return {"ok": False, "error": f"未知导出工具类型：{tool_config.get('name')}", "errorType": "tool_runtime"}
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}", "errorType": "tool_runtime"}


def _parse_json_object_from_text(content: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(content or "").strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    if fallback is not None:
        return fallback
    raise RuntimeError("模型响应不是合法 JSON object。")


def _compact_value(value: Any, string_limit: int = 1200, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(child, string_limit=string_limit, list_limit=list_limit) for key, child in value.items()}
    if isinstance(value, list):
        return [_compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + "...[truncated]"
    return value


def _state_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\\n".join(_state_value_to_text(item) for item in value if _state_value_to_text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, default=str)
    content = getattr(value, "content", None)
    return str(content) if content is not None else str(value)


def _fallback_reply_content(state: AgentState) -> str:
    priority = ("final_answer", "tools_result", "agent_result", "llm_result", "http_response", "retrieved_context")
    for key in priority:
        text = _state_value_to_text(state.get(key)).strip()
        if text:
            return text
    for key in reversed(list(state.keys())):
        if key in priority or key.endswith(("_result", "_answer", "_output")):
            text = _state_value_to_text(state.get(key)).strip()
            if text:
                return text
    return ""


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


def _keyword_route(text: str, scenarios: list[dict[str, Any]], fallback: str) -> tuple[str, str]:
    selected = fallback
    reason = "fallback"
    for scenario in scenarios:
        keywords = [item.strip().lower() for item in scenario.get("keywords", []) if item.strip()]
        if keywords and any(keyword in text for keyword in keywords):
            selected = str(scenario["id"])
            reason = f"matched keywords for {scenario.get('label') or scenario['id']}"
            break
    return selected, reason


def _router_prompt(instruction: str, text: str, scenarios: list[dict[str, Any]], fallback: str) -> str:
    lines = [instruction.strip() or "请判断输入属于哪个路由场景，只输出 route key。"]
    lines.append("可选场景：")
    for scenario in scenarios:
        lines.append(f"- {scenario['id']}: {scenario.get('label') or scenario['id']}")
    lines.append(f"fallback: {fallback}")
    lines.append("输入：")
    lines.append(text)
    return "\\n".join(lines)


def _normalize_route_key(value: str, scenarios: list[dict[str, Any]], fallback: str) -> str:
    allowed = {str(scenario["id"]) for scenario in scenarios}
    allowed.add(fallback)
    text = value.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            text = str(parsed.get("route") or parsed.get("route_key") or parsed.get("key") or "")
    except ValueError:
        pass
    for key in sorted(allowed, key=len, reverse=True):
        if key and key in text:
            return key
    return fallback


def _normalize_worker_tasks(value: Any, max_tasks: int, fallback_goal: str = "") -> list[dict[str, Any]]:
    parsed = _parse_task_payload(value)
    raw_tasks = parsed.get("tasks") if isinstance(parsed, dict) else parsed
    if isinstance(raw_tasks, dict):
        raw_tasks = [raw_tasks]
    if not isinstance(raw_tasks, list):
        return []
    result: list[dict[str, Any]] = []
    max_tasks = max(1, min(int(max_tasks or 5), 10))
    for index, item in enumerate(raw_tasks[:max_tasks], start=1):
        task = {"goal": item} if isinstance(item, str) else dict(item) if isinstance(item, dict) else {}
        goal = _first_text(task.get("goal"), task.get("description"), task.get("task"), fallback_goal)
        title = _first_text(task.get("title"), task.get("name"), goal, f"任务 {index}")
        if not goal and not title:
            continue
        result.append({
            "id": str(task.get("id") or f"task_{index}"),
            "title": title[:160] or f"任务 {index}",
            "goal": goal or title,
            "targetFiles": _normalize_string_list(task.get("targetFiles") if "targetFiles" in task else task.get("target_files")),
            "suggestedTools": _normalize_string_list(task.get("suggestedTools") if "suggestedTools" in task else task.get("suggested_tools")),
            "status": "pending",
        })
    return result


def _parse_task_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = _state_value_to_text(value).strip()
    if not text:
        return None
    candidates = [text]
    fenced = re.search(r"```(?:json)?\\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    list_start = text.find("[")
    list_end = text.rfind("]")
    if 0 <= list_start < list_end:
        candidates.append(text[list_start:list_end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，\\n]+", text) if item.strip()]


def _first_text(*values: Any) -> str:
    for value in values:
        text = _state_value_to_text(value).strip()
        if text:
            return text
    return ""


def _run_export_worker_task(model_ref: Any, tools: list[Any], system_prompt: str, task: dict[str, Any], state: AgentState, max_iterations: int) -> dict[str, Any]:
    started = time.perf_counter()
    task_id = str(task.get("id") or "task")
    title = str(task.get("title") or task.get("goal") or task_id)[:120]
    try:
        worker_prompt = (
            f"{system_prompt}\\n"
            "你是并行代码阅读 Worker，只完成分配给你的子任务。"
            "最终返回 JSON：{\\"summary\\":\\"结论\\",\\"evidence\\":[{\\"path\\":\\"文件\\",\\"symbol\\":\\"符号\\",\\"startLine\\":1,\\"endLine\\":1,\\"note\\":\\"说明\\"}],\\"warnings\\":[]}。"
            "不要输出完整工具调用 JSON。"
        )
        user_content = json.dumps({"userQuestion": _state_value_to_text(state.get("messages")), "task": task}, ensure_ascii=False, indent=2)
        agent = create_agent(model=model_ref, tools=tools, system_prompt=worker_prompt)
        response_state = agent.invoke({"messages": [("user", user_content)]}, config={"recursion_limit": max_iterations})
        final_answer = _last_message_content(response_state)
        parsed = _parse_task_payload(final_answer)
        if isinstance(parsed, dict):
            summary = _state_value_to_text(parsed.get("summary") or parsed.get("answer") or final_answer)
            evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
            warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
        else:
            summary = final_answer
            evidence = []
            warnings = []
        return {"taskId": task_id, "title": title, "status": "ok", "durationMs": round((time.perf_counter() - started) * 1000, 2), "summary": summary, "evidence": evidence[:12], "warnings": [str(item) for item in warnings[:8]]}
    except Exception as exc:
        return {"taskId": task_id, "title": title, "status": "error", "durationMs": round((time.perf_counter() - started) * 1000, 2), "summary": "", "evidence": [], "warnings": [], "error": f"{exc.__class__.__name__}: {exc}"}


def _render_json_template(template: str, state: AgentState) -> Any:
    rendered = render_template(template.strip() or "{}", state)
    try:
        return json.loads(rendered)
    except ValueError:
        return rendered
'''


def _smoke_test(package: str) -> str:
    return f'''def test_graph_compiles():
    from {package}.graph import graph

    assert graph is not None
'''


def _parse_scenarios(value: str) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        scenario_id, label, keywords = (line.split(":", 2) + ["", ""])[:3]
        scenario_id = scenario_id.strip()
        if not scenario_id:
            continue
        scenarios.append(
            {
                "id": scenario_id,
                "label": label.strip() or scenario_id,
                "keywords": [item.strip() for item in keywords.split(",") if item.strip()],
            }
        )
    return scenarios


def _csv_tool_names(value: str) -> list[str]:
    names: list[str] = []
    for item in re.split(r"[,，\n]+", value):
        name = item.strip()
        if name and name not in names:
            names.append(name)
    return names


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return _csv_tool_names(text)
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return _csv_tool_names(text)
    return parsed if isinstance(parsed, list) else []


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [item for item in _json_list(value) if isinstance(item, dict)]


def _json_schema_from_config(config: dict[str, Any]) -> dict[str, Any]:
    if str(config.get("schemaPreset") or "").strip() == "task_plan_v1":
        return _task_plan_json_schema()
    return _json_schema_from_fields(config.get("schemaFieldsJson"))


def _task_plan_json_schema() -> dict[str, Any]:
    task_item = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "可选任务 ID；不填时自动生成 task_1、task_2。"},
            "title": {"type": "string", "description": "任务标题，简短可扫描。"},
            "goal": {"type": "string", "description": "Worker 需要完成的具体目标。"},
            "description": {"type": "string", "description": "goal 的别名；仅在 goal 为空时使用。"},
            "targetFiles": {"type": "array", "items": {"type": "string"}, "description": "建议优先读取的文件路径。"},
            "suggestedTools": {"type": "array", "items": {"type": "string"}, "description": "建议 Worker 使用的工具名。"},
        },
        "anyOf": [{"required": ["title"]}, {"required": ["goal"]}],
        "additionalProperties": True,
    }
    return {
        "type": "object",
        "properties": {"tasks": {"type": "array", "items": task_item, "description": "Task Splitter 可直接解析的任务数组。"}},
        "required": ["tasks"],
        "additionalProperties": True,
        "x-graphic-preset": "task_plan_v1",
    }


def _json_schema_from_fields(value: Any) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in _json_object_list(value):
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        schema = _json_schema_for_field(field)
        properties[name] = schema
        if str(field.get("required") or "").strip().lower() in {"1", "true", "yes", "on"} or field.get("required") is True:
            required.append(name)
    result: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        result["required"] = required
    return result


def _json_schema_for_field(field: dict[str, Any]) -> dict[str, Any]:
    field_type = str(field.get("type") or "string").strip().lower()
    if field_type not in {"string", "number", "integer", "boolean", "object", "array"}:
        field_type = "string"
    schema: dict[str, Any] = {"type": field_type}
    description = str(field.get("description") or "").strip()
    if description:
        schema["description"] = description
    enum_values = _enum_values(field.get("enumValues") or field.get("enum_values"))
    if enum_values:
        schema["enum"] = enum_values
    default_value = _field_default_value(field.get("defaultValue"))
    if default_value is not None:
        schema["default"] = default_value
    if field_type == "object":
        child_schema = _json_schema_from_fields(field.get("children") or field.get("fields"))
        schema["properties"] = child_schema.get("properties", {})
        if child_schema.get("required"):
            schema["required"] = child_schema["required"]
        schema["additionalProperties"] = True
    if field_type == "array":
        item_fields = _json_object_list(field.get("itemFields") or field.get("item_fields"))
        item_type = str(field.get("itemType") or field.get("item_type") or "").strip().lower()
        if item_fields:
            schema["items"] = _json_schema_from_fields(item_fields)
        elif item_type in {"string", "number", "integer", "boolean", "object", "array"}:
            schema["items"] = {"type": item_type}
        else:
            schema["items"] = {}
    return schema


def _enum_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，\n;；]+", text) if item.strip()]


def _field_default_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "approve", "auto"}


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _indent(code: str) -> str:
    lines = code.splitlines() or ["return {}"]
    return "\n".join(f"    {line}" if line.strip() else "" for line in lines)
