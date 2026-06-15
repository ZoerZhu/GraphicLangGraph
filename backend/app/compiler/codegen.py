from __future__ import annotations

import json
import re
import textwrap
from collections import defaultdict
from typing import Any

from app.ir.sanitization import sanitize_project_payload
from app.ir.schemas import EdgeKind, NodeIR, NodeType, ProjectIR


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


def generate_project_files(project: ProjectIR) -> dict[str, str]:
    package = package_name(project)
    files = {
        "langgraph.json": _langgraph_json(package),
        "pyproject.toml": _pyproject_toml(package),
        ".env.example": _env_example(project),
        "README.md": _readme(project, package),
        f"src/{package}/__init__.py": "",
        f"src/{package}/config.py": _config_py(),
        f"src/{package}/state.py": _state_py(project),
        f"src/{package}/tools.py": _tools_py(project),
        f"src/{package}/skills.py": _skills_py(project),
        f"src/{package}/nodes.py": _nodes_py(project),
        f"src/{package}/routers.py": _routers_py(project),
        f"src/{package}/graph.py": _graph_py(project),
        "tests/test_graph_smoke.py": _smoke_test(package),
        "flow/project.graph.json": json.dumps(sanitize_project_payload(project), ensure_ascii=False, indent=2),
    }
    return files


def package_name(project: ProjectIR) -> str:
    source = project.project.id or project.project.name or "generated_agent"
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", source).strip("_").lower()
    if not name:
        name = "generated_agent"
    if name[0].isdigit():
        name = f"agent_{name}"
    return name


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


def _pyproject_toml(package: str) -> str:
    return f"""[project]
name = "{package}"
version = "0.1.0"
description = "Generated LangGraph agent from GraphicLangGraph"
requires-python = ">=3.12"
dependencies = [
  "langgraph>=0.2.70",
  "langchain>=0.3.0",
  "langchain-core>=0.3.0",
  "langchain-openai>=0.2.0",
  "httpx>=0.27.0"
]

[tool.pytest.ini_options]
pythonpath = ["src"]
"""


def _env_example(project: ProjectIR) -> str:
    keys: dict[str, str] = {}
    for node in project.nodes:
        provider = str(node.config.get("provider", "")).strip()
        if node.type in {NodeType.LLM, NodeType.AGENT, NodeType.AI_ROUTER}:
            env_key = str(node.config.get("apiKeyEnv", "")).strip() or _provider_env_key(provider)
            if env_key:
                keys[env_key] = "replace_me"
        if node.type == NodeType.HTTP:
            secret = str(node.config.get("authSecret", "")).strip()
            if secret:
                keys[secret] = "replace_me"
        if node.type == NodeType.RETRIEVER:
            for env_key in _retriever_env_keys(node.config):
                keys[env_key] = "replace_me"
    if not keys:
        keys["OPENAI_API_KEY"] = "replace_me"
    return "\n".join(f"{key}={value}" for key, value in sorted(keys.items())) + "\n"


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


def _readme(project: ProjectIR, package: str) -> str:
    sample_input = _readme_sample_input(project)
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


TEMPLATE_RE = re.compile(r"{{\\s*state\\.([a-zA-Z_][a-zA-Z0-9_]*)\\s*}}")


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def render_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = state.get(match.group(1), "")
        return "" if value is None else str(value)

    return TEMPLATE_RE.sub(replace, template)
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
    if not project.state.fields:
        lines.append("    pass")
    else:
        for field in project.state.fields:
            type_name = TYPE_MAP.get(field.type.lower(), "Any")
            lines.append(f"    {py_name(field.name)}: NotRequired[{type_name}]")
    return "\n".join(lines) + "\n"


def _tools_py(project: ProjectIR) -> str:
    specs = _tool_specs(project)
    if not specs:
        return "from __future__ import annotations\n\n\nTOOL_REGISTRY = {}\n"

    lines = [
        "from __future__ import annotations",
        "",
        "from langchain_core.tools import tool",
        "",
    ]
    registry: dict[str, str] = {}
    for name, description in specs.items():
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

    lines.append("TOOL_REGISTRY = {")
    for key, function_name in sorted(registry.items()):
        lines.append(f"    {json.dumps(key)}: {function_name},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


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
        "from .skills import SKILL_REGISTRY",
        "from .tools import TOOL_REGISTRY",
        "",
    ]
    for node in project.nodes:
        if node.type == NodeType.START:
            continue
        body.append(_node_function(node))
        body.append("")
    body.append(_nodes_helpers())
    body.append("")
    return "\n".join(body)


def _node_function(node: NodeIR) -> str:
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
        return f'''def {function_name}(state: AgentState) -> dict[str, Any]:
    model_ref = _chat_model({provider}, {model}, {base_url}, {api_key_env}, {api_version}, {organization})
    tool_names = {tool_names}
    skill_ids = {skill_ids}
    tools = [TOOL_REGISTRY[name] for name in tool_names if name in TOOL_REGISTRY]
    user_content = _agent_user_content(state, {user_prompt})
    messages = []
    system_content = _system_with_skills(render_template({system_prompt}, state), skill_ids)
    if system_content:
        messages.append(("system", system_content))
    messages.append(("user", user_content))
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
    condition_nodes = [
        node
        for node in project.nodes
        if node.type in {NodeType.CONDITION, NodeType.AI_ROUTER, NodeType.HUMAN_APPROVAL}
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
        body.append(_route_function(node))
        body.append("")
    return "\n".join(body)


def _route_function(node: NodeIR) -> str:
    name = py_name(node.id)
    if node.type == NodeType.AI_ROUTER:
        route_field = py_name(str(node.config.get("routeField", "route_key")))
        fallback = str(node.config.get("fallback", "other"))
        return f'''def route_{name}(state: AgentState) -> str:
    return str(state.get("{route_field}") or {fallback!r})
'''
    if node.type == NodeType.HUMAN_APPROVAL:
        action_field = py_name(str(node.config.get("actionField", "approval_action")))
        fallback = str(node.config.get("fallback", "rejected"))
        return f'''def route_{name}(state: AgentState) -> str:
    return str(state.get("{action_field}") or {fallback!r})
'''
    field = py_name(str(node.config.get("field", "")))
    operator = str(node.config.get("operator", "equals"))
    value = str(node.config.get("value", ""))
    true_branch = str(node.config.get("trueBranch", "true"))
    false_branch = str(node.config.get("falseBranch", "false"))
    fallback = str(node.config.get("fallback", "fallback"))
    return f'''def route_{name}(state: AgentState) -> str:
    current = state.get("{field}")
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
    normal_edges = [edge for edge in project.edges if edge.kind != EdgeKind.CONDITIONAL]
    conditional_edges = [edge for edge in project.edges if edge.kind == EdgeKind.CONDITIONAL]
    condition_edge_map: dict[str, dict[str, str]] = defaultdict(dict)
    for edge in conditional_edges:
        condition_edge_map[edge.source][edge.sourceHandle or edge.label or "default"] = edge.target

    non_start_nodes = [node for node in project.nodes if node.type != NodeType.START]
    condition_ids = {
        node.id
        for node in project.nodes
        if node.type in {NodeType.CONDITION, NodeType.AI_ROUTER, NodeType.HUMAN_APPROVAL}
    }
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
    for edge in normal_edges:
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
        lines.append(f'builder.add_edge("{reply_id}", END)')

    if has_human_approval:
        lines.extend(["", "checkpointer = InMemorySaver()", "graph = builder.compile(checkpointer=checkpointer)", ""])
    else:
        lines.extend(["", "graph = builder.compile()", ""])
    return "\n".join(lines)


def _nodes_helpers() -> str:
    return '''def _chat_model(provider: str, model: str, base_url: str = "", api_key_env: str = "", api_version: str = "", organization: str = ""):
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
        content = str(skill.get("content") or "").strip() or "（该 Skill 暂无内容）"
        sections.append(f"### {name}\\n{content}")
    skill_prompt = "\\n\\n".join(sections)
    return f"{system_prompt.strip()}\\n\\n{skill_prompt}".strip() if system_prompt.strip() else skill_prompt


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


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _indent(code: str) -> str:
    lines = code.splitlines() or ["return {}"]
    return "\n".join(f"    {line}" if line.strip() else "" for line in lines)
