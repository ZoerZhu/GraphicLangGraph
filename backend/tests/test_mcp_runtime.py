import json

import pytest

from app import mcp_runtime


def test_http_headers_merge_static_env_and_bearer(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa-key")
    monkeypatch.setenv("MCP_BEARER", "bearer-token")

    headers = mcp_runtime._build_http_headers(
        {
            "httpHeadersJson": json.dumps({"X-Static": "yes"}),
            "envHttpHeadersJson": json.dumps({"x-api-key": "EXA_API_KEY"}),
            "bearerTokenEnvVar": "MCP_BEARER",
        }
    )

    assert headers == {
        "X-Static": "yes",
        "x-api-key": "exa-key",
        "Authorization": "Bearer bearer-token",
    }


def test_http_headers_support_mcp_api_key_env_and_direct(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "exa-key")

    env_headers = mcp_runtime._build_http_headers(
        {
            "apiKeyMode": "env",
            "apiKeyEnv": "EXA_API_KEY",
            "apiKeyHeader": "x-api-key",
            "apiKeyPrefix": "",
        }
    )
    direct_headers = mcp_runtime._build_http_headers(
        {
            "apiKeyMode": "direct",
            "apiKey": "direct-token",
            "apiKeyHeader": "Authorization",
            "apiKeyPrefix": "Bearer",
        }
    )

    assert env_headers["x-api-key"] == "exa-key"
    assert direct_headers["Authorization"] == "Bearer direct-token"


def test_http_mcp_respects_runtime_network_controls():
    server = {
        "id": "mcp_exa",
        "name": "Exa",
        "transport": "http",
        "url": "https://mcp.exa.ai/mcp",
        "enabled": True,
    }

    with pytest.raises(mcp_runtime.McpRuntimeError, match="关闭网络"):
        mcp_runtime.invoke_mcp_tool(server, "web_search_exa", {}, {"networkEnabled": False})

    with pytest.raises(mcp_runtime.McpRuntimeError, match="不允许访问 MCP 域名"):
        mcp_runtime.invoke_mcp_tool(
            server,
            "web_search_exa",
            {},
            {"networkEnabled": True, "allowedHostsJson": '["example.com"]'},
        )


def test_http_mcp_all_hosts_bypass_allowlist():
    mcp_runtime._assert_network_allowed(
        "https://mcp.exa.ai/mcp",
        {"networkEnabled": True, "allowAllHosts": True, "allowedHostsJson": '["example.com"]'},
    )


def test_stdio_mcp_respects_command_whitelist():
    server = {
        "id": "mcp_local_exa",
        "name": "Exa Local",
        "transport": "stdio",
        "command": "npx",
        "argsJson": '["-y","exa-mcp-server"]',
        "enabled": True,
    }

    with pytest.raises(mcp_runtime.McpRuntimeError, match="不在白名单"):
        mcp_runtime.invoke_mcp_tool(
            server,
            "web_search_exa",
            {},
            {"allowedCommandProfilesJson": '["git status"]'},
        )


def test_mcp_tool_allow_deny_and_prompt_approval():
    base = {
        "id": "mcp_exa",
        "name": "Exa",
        "transport": "http",
        "url": "https://mcp.exa.ai/mcp",
        "enabled": True,
    }

    with pytest.raises(mcp_runtime.McpRuntimeError, match="白名单"):
        mcp_runtime.invoke_mcp_tool(
            {**base, "enabledToolsJson": '["web_fetch_exa"]'},
            "web_search_exa",
            {},
            None,
        )

    with pytest.raises(mcp_runtime.McpRuntimeError, match="黑名单"):
        mcp_runtime.invoke_mcp_tool(
            {**base, "disabledToolsJson": '["web_search_exa"]'},
            "web_search_exa",
            {},
            None,
        )

    with pytest.raises(mcp_runtime.McpRuntimeError, match="人工审批"):
        mcp_runtime.invoke_mcp_tool(
            {**base, "defaultToolsApprovalMode": "prompt"},
            "web_search_exa",
            {},
            None,
        )
