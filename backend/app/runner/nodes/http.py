from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.ir.schemas import NodeIR

from ..common import positive_float, render_mock_response, render_template, truthy
from ..context import ExecutionContext


def execute_http_node(node: NodeIR, state: dict[str, Any]):
    config = node.config
    output_field = str(config.get("outputField", f"{node.id}_response"))
    if truthy(config.get("mockEnabled")) or str(config.get("mockResponseJson", "")).strip():
        value = render_mock_response(str(config.get("mockResponseJson", "")), state)
        return {output_field: value}, f"使用 HTTP mock 响应写入 state.{output_field}"

    method = str(config.get("method", "GET")).upper()
    url = render_template(str(config.get("url", "")), state).strip()
    if not url:
        raise RuntimeError("HTTP 节点缺少 URL。")
    headers = render_headers(config.get("headersJson"), state)
    auth_secret = str(config.get("authSecret", "")).strip()
    if auth_secret:
        token = os.getenv(auth_secret, "").strip()
        if not token:
            raise RuntimeError(f"HTTP 节点引用的环境变量 {auth_secret} 未设置。")
        headers["Authorization"] = f"Bearer {token}"
    body = str(config.get("body", ""))
    response = httpx.request(
        method,
        url,
        headers=headers,
        content=render_template(body, state) if body else None,
        timeout=positive_float(config.get("timeoutSeconds", 30), 30),
    )
    response.raise_for_status()
    try:
        value = response.json()
    except ValueError:
        value = response.text
    return {output_field: value}, f"真实 HTTP {method} {url}，写入 state.{output_field}"


def render_headers(value: Any, state: dict[str, Any]) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HTTP Headers JSON 格式错误：{exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("HTTP Headers JSON 必须是 JSON object。")
    headers: dict[str, str] = {}
    for key, raw in parsed.items():
        name = str(key).strip()
        rendered = render_template(str(raw), state).strip()
        if name and rendered:
            headers[name] = rendered
    return headers


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_http_node(node, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    field = str(node.config.get("outputField", "http_response"))
    return {field: {"url": node.config.get("url", ""), "status": "dry-run"}}, f"模拟 HTTP 输出到 state.{field}"
