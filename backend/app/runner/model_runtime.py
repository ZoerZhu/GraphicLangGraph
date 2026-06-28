from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError


ModelRuntimeConfig = dict[str, Any] | None

OPENAI_COMPATIBLE_PROVIDERS = {
    "custom",
    "openai_compatible",
    "deepseek",
    "moonshot",
    "qwen",
    "zhipu",
    "minimax",
    "baichuan",
    "groq",
    "ollama",
}
OPENAI_COMPATIBLE_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "moonshot": "https://api.moonshot.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax": "https://api.minimax.chat/v1",
    "baichuan": "https://api.baichuan-ai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
}
PROVIDER_ALIASES = {
    "google": "google_genai",
}


def call_chat_model(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    runtime_config: ModelRuntimeConfig = None,
) -> Any:
    provider_key = normalize_provider(provider)
    base_url = runtime_value(runtime_config, "baseUrl", "base_url")
    api_format = normalize_provider(runtime_value(runtime_config, "apiFormat", "api_format"))
    api_key_env = safe_api_key_env(runtime_value(runtime_config, "apiKeyEnv", "api_key_env"))
    api_key = runtime_value(runtime_config, "apiKey", "api_key") or read_api_key(api_key_env)
    organization = runtime_value(runtime_config, "organization")
    api_version = runtime_value(runtime_config, "apiVersion", "api_version")

    try:
        if provider_key == "azure_openai":
            return call_azure_openai(model, messages, base_url, api_key, api_key_env, api_version)
        if api_format == "openai_compatible" or provider_key in OPENAI_COMPATIBLE_PROVIDERS or base_url:
            return call_openai_compatible(provider_key, model, messages, base_url, api_key, api_key_env, organization)

        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError("后端缺少 LangChain 模型运行依赖，请安装 requirements-dev.txt 后重试。") from exc

    try:
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        chat_model = init_chat_model(model, model_provider=PROVIDER_ALIASES.get(provider_key, provider_key), **kwargs)
        return chat_model.invoke(messages)
    except Exception as exc:
        raise RuntimeError(f"模型调用失败：{exc}") from exc


def call_openai_compatible(
    provider: str,
    model: str,
    messages: list[tuple[str, str]],
    base_url: str = "",
    api_key: str = "",
    api_key_env: str = "",
    organization: str = "",
) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("后端缺少 langchain-openai，请安装 requirements-dev.txt 后重试。") from exc

    resolved_base_url = base_url or OPENAI_COMPATIBLE_BASE_URLS.get(provider, "")
    resolved_api_key = api_key or ("ollama" if provider == "ollama" else "")
    if not resolved_api_key and resolved_base_url and not api_key_env:
        resolved_api_key = "not-needed"
    if not resolved_api_key and api_key_env:
        raise RuntimeError(f"模型配置引用的环境变量 {api_key_env} 未设置。")

    kwargs: dict[str, Any] = {"model": model}
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url
    if resolved_api_key:
        kwargs["api_key"] = resolved_api_key
    if organization:
        kwargs["organization"] = organization
    chat_model = ChatOpenAI(**kwargs)
    return chat_model.invoke(messages)


def call_azure_openai(
    model: str,
    messages: list[tuple[str, str]],
    azure_endpoint: str = "",
    api_key: str = "",
    api_key_env: str = "",
    api_version: str = "",
) -> Any:
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:
        raise RuntimeError("后端缺少 langchain-openai，请安装 requirements-dev.txt 后重试。") from exc

    if not azure_endpoint:
        raise RuntimeError("Azure OpenAI 运行配置需要填写 Base URL/Azure Endpoint。")
    if not api_version:
        raise RuntimeError("Azure OpenAI 运行配置需要填写 API Version。")
    if not api_key and api_key_env:
        raise RuntimeError(f"模型配置引用的环境变量 {api_key_env} 未设置。")

    kwargs: dict[str, Any] = {
        "azure_deployment": model,
        "azure_endpoint": azure_endpoint,
        "api_version": api_version,
    }
    if api_key:
        kwargs["api_key"] = api_key
    chat_model = AzureChatOpenAI(**kwargs)
    return chat_model.invoke(messages)


def normalize_model_config(config: ModelRuntimeConfig) -> ModelRuntimeConfig:
    if not config:
        return None
    if hasattr(config, "model_dump"):
        config = config.model_dump(by_alias=True)
    if not isinstance(config, dict):
        return None
    if config.get("enabled") is False:
        return None
    return {str(key): value for key, value in config.items() if value is not None}


def effective_model_config(node_config: dict[str, Any], runtime_config: ModelRuntimeConfig) -> ModelRuntimeConfig:
    base = normalize_model_config(runtime_config) or {}
    node_fields: dict[str, Any] = {}
    for key in (
        "id",
        "name",
        "provider",
        "model",
        "baseUrl",
        "base_url",
        "apiKey",
        "api_key",
        "apiKeyEnv",
        "api_key_env",
        "apiVersion",
        "api_version",
        "organization",
        "apiFormat",
        "api_format",
    ):
        value = node_config.get(key)
        if value is not None and str(value).strip():
            node_fields[key] = value
    return {**base, **node_fields} if base or node_fields else None


def runtime_value(config: ModelRuntimeConfig, *keys: str) -> str:
    if not config:
        return ""
    for key in keys:
        value = config.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def resolve_node_model(
    config: dict[str, Any],
    runtime_config: ModelRuntimeConfig,
    default_provider: str,
    default_model: str,
) -> tuple[str, str]:
    node_provider = str(config.get("provider", "")).strip()
    node_model = str(config.get("model", "")).strip()
    runtime_provider = runtime_value(runtime_config, "provider")
    runtime_model = runtime_value(runtime_config, "model")
    has_explicit_node_model = bool(config.get("modelConfigId") or config.get("modelConfigName")) or (
        bool(node_model) and node_model != default_model
    )
    if has_explicit_node_model:
        return node_provider or runtime_provider or default_provider, node_model or runtime_model or default_model
    return runtime_provider or node_provider or default_provider, runtime_model or node_model or default_model


def read_api_key(api_key_env: str) -> str:
    if not api_key_env:
        return ""
    return os.getenv(api_key_env, "").strip()


def safe_api_key_env(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value or "") else ""


def normalize_provider(provider: str) -> str:
    return provider.strip().lower().replace("-", "_") or "openai"


def call_openai_compatible_embedding(model: str, base_url: str, api_key: str, query: str) -> list[float]:
    url = base_url.rstrip("/")
    if not url.endswith("/embeddings"):
        url = f"{url}/embeddings"
    payload = json.dumps({"model": model, "input": query}, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Embedding 接口调用失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Embedding 接口返回了无法解析的 JSON。") from exc

    try:
        embedding = body["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Embedding 接口响应缺少 data[0].embedding。") from exc
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Embedding 接口返回的 embedding 为空。")
    return [float(value) for value in embedding]
