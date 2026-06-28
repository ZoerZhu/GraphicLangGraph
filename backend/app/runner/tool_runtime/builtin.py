from __future__ import annotations

from typing import Any

from .. import engine
from . import edit, filesystem, html_css, web


def invoke_builtin_tool(metadata: dict[str, Any], args: dict[str, Any], runtime_environment: dict[str, Any] | None) -> Any:
    builtin_id = str(metadata.get("builtinId") or metadata.get("id") or "").strip()
    runtime = normalize_runtime_environment(runtime_environment)
    if builtin_id == "web_search":
        return web.web_search(args, runtime)
    if builtin_id == "read_file":
        return filesystem.read_file(args, runtime)
    if builtin_id == "list_directory":
        return filesystem.list_directory(args, runtime)
    if builtin_id == "task_plan":
        return filesystem.task_plan(args)
    if builtin_id == "read_file_chunk":
        return filesystem.read_file_chunk(args, runtime)
    if builtin_id == "search_code":
        return filesystem.search_code(args, runtime)
    if builtin_id == "list_code_symbols":
        return filesystem.list_code_symbols(args, runtime)
    if builtin_id == "extract_html":
        return html_css.extract_html(args, runtime)
    if builtin_id == "extract_css_rules":
        return html_css.extract_css_rules(args, runtime)
    if builtin_id == "extract_html_by_text":
        return html_css.extract_html_by_text(args, runtime)
    if builtin_id == "extract_css_for_html":
        return html_css.extract_css_for_html(args, runtime)
    if builtin_id == "summarize_page_structure":
        return html_css.summarize_page_structure(args, runtime)
    if builtin_id == "resolve_asset_references":
        return html_css.resolve_asset_references(args, runtime)
    if builtin_id == "extract_code_symbol":
        return filesystem.extract_code_symbol(args, runtime)
    if builtin_id == "chunk_code_semantic":
        return filesystem.chunk_code_semantic(args, runtime)
    if builtin_id == "fetch_url":
        return web.fetch_url(args, runtime)
    if builtin_id == "propose_patch":
        return edit.propose_patch(args, runtime)
    if builtin_id == "apply_patch_set":
        raise RuntimeError("apply_patch_set 只能通过前端变更集应用面板调用，Agent 运行中不能直接应用补丁。")
    if builtin_id == "rollback_patch_set":
        raise RuntimeError("rollback_patch_set 只能通过前端变更集应用面板调用。")
    if builtin_id == "replace_in_file":
        return edit.replace_in_file(args, runtime)
    if builtin_id == "write_file":
        return edit.write_file(args, runtime)
    if builtin_id == "run_whitelisted_command":
        return edit.run_whitelisted_command(args, runtime)
    raise RuntimeError(f"未知内置 Tool：{builtin_id or '未配置 builtinId'}")


def normalize_runtime_environment(runtime_environment: dict[str, Any] | None) -> dict[str, Any]:
    return engine._normalize_runtime_environment(runtime_environment)


def runtime_allowed_roots(runtime: dict[str, Any]):
    return engine._runtime_allowed_roots(runtime)


def resolve_runtime_path(value: str, runtime: dict[str, Any]):
    return engine._resolve_runtime_path(value, runtime)
