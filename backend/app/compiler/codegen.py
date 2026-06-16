from __future__ import annotations

import json
import inspect
import re
import textwrap
from collections import defaultdict
from typing import Any

from app.builtin_tools import builtin_tool_config_by_id
from app import code_intelligence
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
        "pyproject.toml": _pyproject_toml(package, project),
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


def _pyproject_toml(package: str, project: ProjectIR) -> str:
    dependencies = [
        "langgraph>=0.2.70",
        "langchain>=0.3.0",
        "langchain-core>=0.3.0",
        "langchain-openai>=0.2.0",
        "httpx>=0.27.0",
    ]
    used_builtin_tool_ids = _used_builtin_tool_ids(project)
    if used_builtin_tool_ids & {"extract_html", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references"}:
        dependencies.append("beautifulsoup4>=4.12.0")
    if used_builtin_tool_ids & {"list_code_symbols", "extract_code_symbol", "chunk_code_semantic"}:
        dependencies.append("tree-sitter>=0.25.0")
        dependencies.append("tree-sitter-language-pack>=1.8.0")
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
    if _used_builtin_tool_ids(project) & {"read_file", "list_directory", "read_file_chunk", "search_code", "list_code_symbols", "extract_html", "extract_css_rules", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references", "extract_code_symbol", "chunk_code_semantic"}:
        keys.setdefault("GLG_FILE_TOOL_ROOTS", "./")
        keys.setdefault("GLG_TOOL_MAX_FILE_BYTES", "1048576")
    if _used_builtin_tool_ids(project) & {"web_search", "fetch_url"}:
        keys.setdefault("GLG_TOOL_NETWORK_ENABLED", "true")
        keys.setdefault("GLG_TOOL_ALLOWED_HOSTS", "api.duckduckgo.com,html.duckduckgo.com,duckduckgo.com")
        keys.setdefault("GLG_TOOL_MAX_HTTP_BYTES", "262144")
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
    file_tool_note = ""
    if _used_builtin_tool_ids(project) & {"read_file", "list_directory", "read_file_chunk", "search_code", "list_code_symbols", "extract_html", "extract_css_rules", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references", "extract_code_symbol", "chunk_code_semantic"}:
        file_tool_note = """
## Local file tools

File, code, HTML, and CSS tools read files from the machine running this exported project. Configure `GLG_FILE_TOOL_ROOTS` in `.env` to restrict allowed local roots.
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
    configs = _tool_config_dicts(project)
    if not configs:
        return "from __future__ import annotations\n\n\nTOOL_REGISTRY = {}\n"

    lines = [
        "from __future__ import annotations",
        "",
        "import ast",
        "import fnmatch",
        "import html as html_lib",
        "import json",
        "import os",
        "import re",
        "from html.parser import HTMLParser",
        "from pathlib import Path",
        "from typing import Any",
        "from urllib.parse import parse_qs, unquote, urlencode, urlparse",
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
        if source == "builtin" and builtin_id in {"web_search", "read_file", "list_directory", "read_file_chunk", "search_code", "list_code_symbols", "extract_html", "extract_css_rules", "extract_html_by_text", "extract_css_for_html", "summarize_page_structure", "resolve_asset_references", "extract_code_symbol", "chunk_code_semantic", "fetch_url"}:
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
    return []


def _builtin_tool_helper_lines() -> list[str]:
    return [
        "CODE_TOOL_EXCLUDED_DIRS = {'.git', '.hg', '.svn', 'node_modules', 'dist', 'build', '.venv', 'venv', '__pycache__', '.next', '.turbo', 'coverage'}",
        "CODE_TOOL_BINARY_CHECK_BYTES = 4096",
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
        "import re",
        "import time",
        "from concurrent.futures import ThreadPoolExecutor, as_completed",
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
    return [item for item in _json_list(value) if isinstance(item, dict)]


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _indent(code: str) -> str:
    lines = code.splitlines() or ["return {}"]
    return "\n".join(f"    {line}" if line.strip() else "" for line in lines)
