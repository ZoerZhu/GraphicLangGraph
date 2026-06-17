from __future__ import annotations

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

from app.config import ROOT_DIR
from app.runtime_environment import default_command_profiles


MCP_RESULT_STRING_LIMIT = 12_000


class McpRuntimeError(RuntimeError):
    pass


def inspect_mcp_server(server_config: dict[str, Any], runtime_environment: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    server = normalize_mcp_server_config(server_config)
    tools = list_mcp_tools(server, runtime_environment, require_enabled=False)
    return {
        "ok": True,
        "serverId": server.get("id", ""),
        "serverName": server.get("name", "未命名 MCP"),
        "transport": server.get("transport", "stdio"),
        "tools": tools,
        "warnings": [],
        "durationMs": round((time.perf_counter() - started) * 1000, 2),
    }


def list_mcp_tools(
    server_config: dict[str, Any],
    runtime_environment: dict[str, Any] | None = None,
    require_enabled: bool = True,
) -> list[dict[str, Any]]:
    server = normalize_mcp_server_config(server_config)
    _ensure_server_enabled(server, require_enabled)
    _ensure_server_execution_allowed(server, runtime_environment)
    timeout = _positive_float(server.get("startupTimeoutSec"), 10)
    raw_tools = _run_async(_list_mcp_tools_async(server, timeout))
    return _filter_tools(raw_tools, server)


def invoke_mcp_tool(
    server_config: dict[str, Any],
    tool_name: str,
    args: dict[str, Any],
    runtime_environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    server = normalize_mcp_server_config(server_config)
    _ensure_server_enabled(server, require_enabled=True)
    _ensure_tool_approval(server, tool_name)
    _ensure_server_execution_allowed(server, runtime_environment)
    _ensure_tool_name_allowed(server, tool_name)
    if not isinstance(args, dict):
        raise McpRuntimeError("MCP 工具参数必须是 JSON object。")
    startup_timeout = _positive_float(server.get("startupTimeoutSec"), 10)
    tool_timeout = _positive_float(server.get("toolTimeoutSec"), 60)
    result = _run_async(_call_mcp_tool_async(server, tool_name, args, startup_timeout, tool_timeout))
    return _normalize_tool_result(server, tool_name, args, result)


def normalize_mcp_server_config(value: dict[str, Any] | Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(by_alias=True)
    if not isinstance(value, dict):
        value = {}
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


def make_mcp_agent_tool_config(server_config: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    server = normalize_mcp_server_config(server_config)
    server_id = str(server.get("id") or "")
    tool_name = str(tool.get("name") or "").strip()
    exposed_name = f"mcp_{_slugify(server_id or server.get('name') or 'server')}__{tool_name}"
    input_schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    schema = dict(input_schema or {})
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {}, **schema}
    schema["x-graphic"] = {
        "kind": "mcp_tool",
        "server": server,
        "serverId": server_id,
        "serverName": server.get("name", "未命名 MCP"),
        "toolName": tool_name,
    }
    return {
        "id": f"mcp::{server_id}::{tool_name}",
        "name": exposed_name,
        "description": str(tool.get("description") or tool.get("title") or f"{server.get('name')} MCP 工具"),
        "source": "mcp",
        "schemaJson": json.dumps(schema, ensure_ascii=False),
    }


def redact_mcp_config_for_trace(server_config: dict[str, Any]) -> dict[str, Any]:
    server = normalize_mcp_server_config(server_config)
    if server.get("apiKey"):
        server["apiKey"] = "<redacted>"
    if server.get("httpHeadersJson"):
        headers = _json_object(server.get("httpHeadersJson"))
        server["httpHeadersJson"] = json.dumps(_redact_secret_mapping(headers), ensure_ascii=False)
    if server.get("envJson"):
        env = _json_object(server.get("envJson"))
        server["envJson"] = json.dumps(_redact_secret_mapping(env), ensure_ascii=False)
    return server


async def _list_mcp_tools_async(server: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    async with _open_mcp_session(server, timeout=timeout) as session:
        response = await asyncio.wait_for(session.list_tools(), timeout=timeout)
        tools = getattr(response, "tools", []) or []
        return [_tool_to_dict(tool) for tool in tools]


async def _call_mcp_tool_async(
    server: dict[str, Any],
    tool_name: str,
    args: dict[str, Any],
    startup_timeout: float,
    tool_timeout: float,
) -> Any:
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
        read_stream, write_stream = streams[0], streams[1]
        session = await stack.enter_async_context(client_session_cls(read_stream, write_stream))
        await asyncio.wait_for(session.initialize(), timeout=timeout)
        yield session


async def _open_transport(server: dict[str, Any], stack: AsyncExitStack, timeout: float) -> tuple[Any, tuple[Any, ...]]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise McpRuntimeError("缺少 Python MCP SDK。请安装 backend 依赖中的 mcp 包。") from exc

    transport = str(server.get("transport") or "stdio").lower()
    if transport == "http":
        url = str(server.get("url") or "").strip()
        if not url:
            raise McpRuntimeError("HTTP MCP 缺少 URL。")
        headers = _build_http_headers(server)
        read_timeout = max(timeout, _positive_float(server.get("toolTimeoutSec"), 60))
        if "http_client" in inspect_lib.signature(streamable_http_client).parameters:
            http_client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(timeout, read=read_timeout),
                follow_redirects=True,
            )
            await stack.enter_async_context(http_client)
            streams = await stack.enter_async_context(streamable_http_client(url, http_client=http_client))
        else:
            streams = await stack.enter_async_context(
                streamable_http_client(url=url, headers=headers, timeout=timeout, sse_read_timeout=read_timeout)
            )
        return ClientSession, tuple(streams)

    if transport != "stdio":
        raise McpRuntimeError(f"暂不支持 MCP transport：{transport}")
    command = str(server.get("command") or "").strip()
    if not command:
        raise McpRuntimeError("STDIO MCP 缺少启动命令。")
    params = StdioServerParameters(
        command=command,
        args=_json_string_list(server.get("argsJson")),
        env=_build_stdio_env(server),
        cwd=_resolve_cwd(server.get("cwd")),
    )
    streams = await stack.enter_async_context(stdio_client(params))
    return ClientSession, tuple(streams)


def _normalize_tool_result(server: dict[str, Any], tool_name: str, args: dict[str, Any], result: Any) -> dict[str, Any]:
    raw = _model_dump(result)
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False) or raw.get("isError") or raw.get("is_error"))
    content_text = _result_content_text(result, raw)
    if is_error:
        raise McpRuntimeError(f"MCP 工具 {tool_name} 执行失败：{content_text or raw}")
    return {
        "ok": True,
        "serverId": server.get("id", ""),
        "serverName": server.get("name", "未命名 MCP"),
        "tool": tool_name,
        "args": args,
        "content": content_text,
        "raw": _compact_value(raw, string_limit=MCP_RESULT_STRING_LIMIT, list_limit=20),
    }


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
            continue
        if isinstance(data.get("text"), str):
            parts.append(data["text"])
        elif isinstance(data.get("resource"), dict) and isinstance(data["resource"].get("text"), str):
            parts.append(data["resource"]["text"])
        elif data.get("type") == "image":
            parts.append(f"[image {data.get('mimeType') or data.get('mime_type') or ''}]")
        elif data:
            parts.append(json.dumps(_compact_value(data, string_limit=2000, list_limit=8), ensure_ascii=False))
    structured = (
        getattr(result, "structuredContent", None)
        or getattr(result, "structured_content", None)
        or raw.get("structuredContent")
        or raw.get("structured_content")
    )
    if structured and not parts:
        parts.append(json.dumps(_compact_value(structured, string_limit=4000, list_limit=12), ensure_ascii=False))
    text = "\n".join(part for part in parts if part).strip()
    if len(text) > MCP_RESULT_STRING_LIMIT:
        return text[:MCP_RESULT_STRING_LIMIT] + "...[truncated]"
    return text


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    data = _model_dump(tool)
    input_schema = data.get("inputSchema") or data.get("input_schema") or getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    return {
        "name": str(data.get("name") or getattr(tool, "name", "") or ""),
        "title": str(data.get("title") or getattr(tool, "title", "") or ""),
        "description": str(data.get("description") or getattr(tool, "description", "") or ""),
        "inputSchema": input_schema if isinstance(input_schema, dict) else {},
    }


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(by_alias=True, mode="json")
        except TypeError:
            dumped = value.model_dump(by_alias=True)
        return dumped if isinstance(dumped, dict) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _filter_tools(tools: list[dict[str, Any]], server: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = set(_json_string_list(server.get("enabledToolsJson")))
    disabled = set(_json_string_list(server.get("disabledToolsJson")))
    result: list[dict[str, Any]] = []
    for tool in tools:
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        if allowed and name not in allowed:
            continue
        if name in disabled:
            continue
        result.append(tool)
    return result


def _ensure_server_enabled(server: dict[str, Any], require_enabled: bool) -> None:
    if require_enabled and server.get("enabled") is False:
        raise McpRuntimeError(f"MCP Server 已停用：{server.get('name') or server.get('id')}")


def _ensure_tool_approval(server: dict[str, Any], tool_name: str) -> None:
    mode = str(server.get("defaultToolsApprovalMode") or "").strip().lower()
    if mode == "prompt":
        raise McpRuntimeError(f"MCP 工具 {tool_name} 需要人工审批，live-run v1 暂不支持交互式审批。")


def _ensure_tool_name_allowed(server: dict[str, Any], tool_name: str) -> None:
    allowed = set(_json_string_list(server.get("enabledToolsJson")))
    disabled = set(_json_string_list(server.get("disabledToolsJson")))
    if allowed and tool_name not in allowed:
        raise McpRuntimeError(f"MCP 工具不在白名单内：{tool_name}")
    if tool_name in disabled:
        raise McpRuntimeError(f"MCP 工具已被黑名单禁用：{tool_name}")


def _ensure_server_execution_allowed(server: dict[str, Any], runtime: dict[str, Any] | None) -> None:
    if runtime is None:
        return
    transport = str(server.get("transport") or "stdio").lower()
    if transport == "http":
        _assert_network_allowed(str(server.get("url") or ""), runtime)
        return
    command = [str(server.get("command") or "").strip(), *_json_string_list(server.get("argsJson"))]
    _ensure_command_allowed([item for item in command if item], runtime)


def _assert_network_allowed(url: str, runtime: dict[str, Any]) -> None:
    if runtime.get("networkEnabled") is False:
        raise McpRuntimeError("当前运行环境已关闭网络访问。")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise McpRuntimeError("只允许访问 http/https MCP URL。")
    host = parsed.hostname or ""
    if runtime.get("allowAllHosts") is True:
        return
    allowed_hosts = {item.lower() for item in _json_string_list(runtime.get("allowedHostsJson"))}
    if allowed_hosts and not _host_allowed(host, allowed_hosts):
        raise McpRuntimeError(f"当前运行环境不允许访问 MCP 域名：{host}")


def _ensure_command_allowed(command: list[str], runtime: dict[str, Any]) -> None:
    profiles = _json_string_list(runtime.get("allowedCommandProfilesJson")) or default_command_profiles()
    normalized = " ".join(command).lower()
    for profile in profiles:
        allowed = str(profile).strip().lower()
        if allowed and (normalized == allowed or normalized.startswith(allowed + " ")):
            return
    raise McpRuntimeError(f"MCP STDIO 命令不在白名单内：{' '.join(command)}")


def _host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    normalized = host.lower()
    for allowed in allowed_hosts:
        if not allowed:
            continue
        if allowed.startswith("*.") and normalized.endswith(allowed[1:]):
            return True
        if normalized == allowed:
            return True
    return False


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


def _resolve_cwd(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return str(path)


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


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
            except json.JSONDecodeError:
                break
            return text
    return json.dumps(fallback, ensure_ascii=False)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
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
    except json.JSONDecodeError:
        return shlex.split(text) if " " in text else [item.strip() for item in re.split(r"[,，;\n]+", text) if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _compact_value(value: Any, string_limit: int = 1200, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_value(child, string_limit=string_limit, list_limit=list_limit) for key, child in value.items()}
    if isinstance(value, list):
        return [_compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + "...[truncated]"
    return value


def _redact_secret_mapping(values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        key_text = str(key)
        if re.search(r"(key|token|secret|authorization|password)", key_text, re.IGNORECASE):
            result[key_text] = "***"
        else:
            result[key_text] = value
    return result


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
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return text.strip("_") or "server"
