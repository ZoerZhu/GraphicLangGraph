from __future__ import annotations

from typing import Any

from . import engine


def call_chat_model(provider: str, model: str, messages: list[tuple[str, str]], runtime_config: dict[str, Any] | None = None):
    return engine._call_chat_model(provider, model, messages, runtime_config)


def call_openai_compatible(provider: str, model: str, messages: list[tuple[str, str]], runtime_config: dict[str, Any] | None = None):
    return engine._call_openai_compatible(provider, model, messages, runtime_config)


def call_azure_openai(model: str, messages: list[tuple[str, str]], runtime_config: dict[str, Any] | None = None):
    return engine._call_azure_openai(model, messages, runtime_config)


def normalize_model_config(config: dict[str, Any] | None):
    return engine._normalize_model_config(config)


def effective_model_config(node_config: dict[str, Any], runtime_config: dict[str, Any] | None):
    return engine._effective_model_config(node_config, runtime_config)


def resolve_node_model(node_config: dict[str, Any], runtime_config: dict[str, Any] | None, default_provider: str, default_model: str):
    return engine._resolve_node_model(node_config, runtime_config, default_provider, default_model)


def runtime_value(config: dict[str, Any] | None, *keys: str) -> str:
    return engine._runtime_value(config, *keys)


def safe_api_key_env(value: str) -> str:
    return engine._safe_api_key_env(value)


def normalize_provider(provider: str) -> str:
    return engine._normalize_provider(provider)


def call_openai_compatible_embedding(model: str, base_url: str, api_key: str, query: str):
    return engine._call_openai_compatible_embedding(model, base_url, api_key, query)
