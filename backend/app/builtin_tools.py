from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


BUILTIN_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "builtin_web_search",
        "name": "web_search",
        "description": "DuckDuckGo 搜索工具。默认解析 DuckDuckGo HTML SERP；可用 mode=auto 先查 Instant Answer 并在为空时 fallback 到 SERP。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询。"},
                "max_results": {"type": "number", "description": "最多返回的 SERP 结果或 related topics 数量，默认 5。"},
                "mode": {"type": "string", "description": "搜索模式：serp、auto 或 instant。默认 serp。"},
                "serp_fallback": {"type": "boolean", "description": "mode=auto 且 Instant Answer 为空时是否自动走 SERP fallback，默认 true。"},
            },
            "required": ["query"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "web_search", "version": "0.3.0"},
        },
    },
    {
        "id": "builtin_read_file",
        "name": "read_file",
        "description": "读取当前运行环境白名单目录内的文本文件。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
                "max_chars": {"type": "number", "description": "最多返回字符数。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_list_directory",
        "name": "list_directory",
        "description": "列出当前运行环境白名单目录内的文件和文件夹。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要列出的目录路径。"},
                "pattern": {"type": "string", "description": "文件匹配模式，默认 *。"},
                "recursive": {"type": "boolean", "description": "是否递归列出。"},
                "max_entries": {"type": "number", "description": "最多返回条目数，默认 100。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "list_directory", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_task_plan",
        "name": "task_plan",
        "description": "把模型规划提交为 Task Splitter 可直接解析的结构化任务 JSON。用于产出 {\"tasks\":[...]}，供后续 Task Splitter 拆分 Worker 任务。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "任务数组，最多 10 个。每项必须包含 goal 或 title；推荐同时给出 title、goal、targetFiles、suggestedTools。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "可选任务 ID；不填时自动生成 task_1、task_2。"},
                            "title": {"type": "string", "description": "任务标题，简短可扫描。"},
                            "goal": {"type": "string", "description": "Worker 需要完成的具体目标。"},
                            "description": {"type": "string", "description": "goal 的别名；仅在 goal 为空时使用。"},
                            "targetFiles": {"type": "array", "description": "建议优先读取的文件路径。", "items": {"type": "string"}},
                            "suggestedTools": {"type": "array", "description": "建议 Worker 使用的工具名。", "items": {"type": "string"}},
                        },
                    },
                },
                "sourceGoal": {"type": "string", "description": "原始用户目标或规划依据，可选。"},
                "maxTasks": {"type": "number", "description": "最多保留任务数，默认 6，上限 10。"},
            },
            "required": ["tasks"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "task_plan", "version": "0.1.0", "usageTags": ["规划"]},
        },
    },
    {
        "id": "builtin_read_file_chunk",
        "name": "read_file_chunk",
        "description": "按行号或字符 offset 分片读取当前运行环境白名单目录内的文本文件。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径。"},
                "start_line": {"type": "number", "description": "起始行号，1 开始；传入后优先按行读取。"},
                "end_line": {"type": "number", "description": "结束行号，包含该行。"},
                "offset": {"type": "number", "description": "按字符分片读取时的起始 offset。"},
                "max_chars": {"type": "number", "description": "最多返回字符数，默认 4000。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "read_file_chunk", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_search_code",
        "name": "search_code",
        "description": "在当前运行环境白名单目录内按关键词或正则搜索代码文本，并返回匹配行与上下文。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "搜索根目录或单个文件，默认当前允许目录。"},
                "query": {"type": "string", "description": "搜索关键词或正则表达式。"},
                "regex": {"type": "boolean", "description": "是否按正则表达式搜索，默认 false。"},
                "file_glob": {"type": "string", "description": "文件匹配模式，例如 *.py、*.tsx，默认 *。"},
                "context_lines": {"type": "number", "description": "返回命中行前后文行数，默认 0。"},
                "max_results": {"type": "number", "description": "最多返回结果数，默认 50。"},
                "case_sensitive": {"type": "boolean", "description": "是否大小写敏感，默认 false。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["query"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "search_code", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_list_code_symbols",
        "name": "list_code_symbols",
        "description": "列出代码、前端单文件组件、Markdown、JSON/YAML、HTML/CSS 文件中的符号和结构摘要。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要分析的文件路径。"},
                "language": {"type": "string", "description": "可选语言提示，例如 python、html、javascript、typescript、css、scss、less、vue、svelte、markdown、json、yaml。"},
                "max_symbols": {"type": "number", "description": "最多返回符号数，默认 100。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "list_code_symbols", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_extract_html",
        "name": "extract_html",
        "description": "按 CSS selector 从当前运行环境白名单目录内的 HTML 文件抽取局部 HTML、文本或属性。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要抽取的 HTML 文件路径。"},
                "selector": {"type": "string", "description": "CSS selector，例如 #app、.card、main section。"},
                "mode": {"type": "string", "description": "返回模式：html、text 或 attributes，默认 html。"},
                "max_results": {"type": "number", "description": "最多返回匹配数，默认 20，上限 100。"},
                "max_chars": {"type": "number", "description": "每条匹配最多返回字符数，默认 4000。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path", "selector"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_html", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_extract_css_rules",
        "name": "extract_css_rules",
        "description": "从当前运行环境白名单目录内的 CSS 文件按 selector、property 或关键词抽取样式规则。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要抽取的 CSS 文件路径。"},
                "selector": {"type": "string", "description": "要匹配的 CSS selector，可选。"},
                "property": {"type": "string", "description": "要匹配的 CSS 属性名，可选。"},
                "query": {"type": "string", "description": "按规则文本关键词搜索，可选。"},
                "max_results": {"type": "number", "description": "最多返回规则数，默认 50，上限 200。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_css_rules", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_extract_html_by_text",
        "name": "extract_html_by_text",
        "description": "按可见文本、关键词或正则从当前运行环境白名单目录内的 HTML 文件定位并抽取局部节点。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要抽取的 HTML 文件路径。"},
                "query": {"type": "string", "description": "要匹配的可见文本关键词或正则表达式。"},
                "regex": {"type": "boolean", "description": "是否按正则表达式匹配，默认 false。"},
                "mode": {"type": "string", "description": "返回模式：html、text 或 attributes，默认 html。"},
                "case_sensitive": {"type": "boolean", "description": "是否大小写敏感，默认 false。"},
                "max_results": {"type": "number", "description": "最多返回匹配数，默认 20，上限 100。"},
                "max_chars": {"type": "number", "description": "每条匹配最多返回字符数，默认 4000。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path", "query"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_html_by_text", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_extract_css_for_html",
        "name": "extract_css_for_html",
        "description": "按 HTML selector、id 或 class 从 CSS 文件中查找相关样式规则，可结合 HTML 文件推导元素 tokens。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要搜索的 CSS 文件路径。"},
                "selector": {"type": "string", "description": "HTML selector、id、class 或标签名，例如 #hero、.card、main .hero。"},
                "html_path": {"type": "string", "description": "可选 HTML 文件路径，用于根据 selector 找到元素并扩展 id/class/tag tokens。"},
                "max_results": {"type": "number", "description": "最多返回规则数，默认 50，上限 200。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path", "selector"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_css_for_html", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_summarize_page_structure",
        "name": "summarize_page_structure",
        "description": "摘要当前运行环境白名单目录内 HTML 页面结构，包括标题、区域、表单、按钮、链接、图片、脚本和样式引用。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要分析的 HTML 文件路径。"},
                "max_items": {"type": "number", "description": "每类最多返回条目数，默认 50。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "summarize_page_structure", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_resolve_asset_references",
        "name": "resolve_asset_references",
        "description": "从 HTML/CSS 文件中提取本地资源引用和外链，并解析相对路径是否位于当前运行环境白名单目录内。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要扫描的 HTML 或 CSS 文件路径。"},
                "language": {"type": "string", "description": "可选语言提示：html 或 css；默认按扩展名识别。"},
                "max_results": {"type": "number", "description": "最多返回资源引用数，默认 200。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "resolve_asset_references", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_extract_code_symbol",
        "name": "extract_code_symbol",
        "description": "按函数、类、方法、组件、section、heading、data key、HTML 节点或 CSS/SCSS/LESS selector 精确抽取代码块。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要分析的文件路径。"},
                "symbol": {"type": "string", "description": "符号名，例如函数名、类名、Class.method、#id、.class 或 CSS selector。"},
                "kind": {"type": "string", "description": "符号类型：function、class、method、component、section、heading、data_key、html、css、style_rule 或 any，默认 any。"},
                "include_context": {"type": "boolean", "description": "是否返回符号前后上下文行，默认 false。"},
                "max_chars": {"type": "number", "description": "最多返回字符数，默认 4000。"},
                "language": {"type": "string", "description": "可选语言提示，例如 python、javascript、typescript、html、css、scss、less、vue、svelte、markdown、json、yaml。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path", "symbol"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "extract_code_symbol", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_chunk_code_semantic",
        "name": "chunk_code_semantic",
        "description": "按函数、类、方法、组件、SFC section、Markdown heading、data key、HTML 节点或样式规则拆分大文件。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要拆分的文件路径。"},
                "language": {"type": "string", "description": "可选语言提示，例如 python、javascript、typescript、html、css、scss、less、vue、svelte、markdown、json、yaml。"},
                "max_chars": {"type": "number", "description": "每个片段最多字符数，默认 4000。"},
                "max_chunks": {"type": "number", "description": "最多返回片段数，默认 80。"},
                "include_content": {"type": "boolean", "description": "是否返回完整片段内容；默认 false，仅返回 preview。"},
                "encoding": {"type": "string", "description": "文本编码，默认 utf-8。"},
            },
            "required": ["path"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "chunk_code_semantic", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_fetch_url",
        "name": "fetch_url",
        "description": "在当前运行环境允许网络访问时发起 HTTP GET 并返回文本内容。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要请求的 http/https URL。"},
                "max_chars": {"type": "number", "description": "最多返回字符数。"},
            },
            "required": ["url"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "fetch_url", "version": "0.1.0"},
        },
    },
    {
        "id": "builtin_propose_patch",
        "name": "propose_patch",
        "description": "生成并保存待审批代码补丁，不直接写入文件；支持 unified diff 或 path/original/replacement 结构化修改。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "unified diff，可选。"},
                "path": {"type": "string", "description": "结构化修改目标文件路径。"},
                "original": {"type": "string", "description": "待替换原文，结构化修改时使用。"},
                "replacement": {"type": "string", "description": "替换后的文本，结构化修改时使用。"},
                "expectedOccurrences": {"type": "number", "description": "期望命中次数，默认唯一命中。"},
                "changes": {"type": "array", "description": "多个结构化修改。"},
                "projectId": {"type": "string", "description": "可选项目 ID。"},
                "runId": {"type": "string", "description": "可选运行 ID。"},
            },
            "x-graphic": {"kind": "builtin_tool", "builtinId": "propose_patch", "version": "0.1.0", "usageTags": ["编辑"]},
        },
    },
    {
        "id": "builtin_apply_patch_set",
        "name": "apply_patch_set",
        "description": "应用已审批 patch；仅供前端应用面板调用，Agent 普通运行中会被拒绝。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {"patchId": {"type": "string", "description": "patch ID。"}},
            "required": ["patchId"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "apply_patch_set", "version": "0.1.0", "usageTags": ["编辑", "高风险"], "uiOnly": True},
        },
    },
    {
        "id": "builtin_rollback_patch_set",
        "name": "rollback_patch_set",
        "description": "回滚已应用 patch；仅恢复本工具生成的备份。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {"rollbackId": {"type": "string", "description": "rollback ID。"}},
            "required": ["rollbackId"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "rollback_patch_set", "version": "0.1.0", "usageTags": ["编辑", "高风险"], "uiOnly": True},
        },
    },
    {
        "id": "builtin_replace_in_file",
        "name": "replace_in_file",
        "description": "高级直接写入工具：在允许目录内替换文件文本；运行环境必须开启 allowDirectEdits。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径。"},
                "search": {"type": "string", "description": "要替换的原文。"},
                "replace": {"type": "string", "description": "替换后的文本。"},
                "expectedOccurrences": {"type": "number", "description": "期望命中次数，默认 1。"},
            },
            "required": ["path", "search", "replace"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "replace_in_file", "version": "0.1.0", "usageTags": ["编辑", "高风险"]},
        },
    },
    {
        "id": "builtin_write_file",
        "name": "write_file",
        "description": "高级直接写入工具：创建或覆盖文本文件；运行环境必须开启 allowDirectEdits。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径。"},
                "content": {"type": "string", "description": "写入内容。"},
                "overwrite": {"type": "boolean", "description": "是否允许覆盖已有文件，默认 false。"},
            },
            "required": ["path", "content"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "write_file", "version": "0.1.0", "usageTags": ["编辑", "高风险"]},
        },
    },
    {
        "id": "builtin_run_whitelisted_command",
        "name": "run_whitelisted_command",
        "description": "在运行环境允许目录内运行白名单验证命令，返回 stdout、stderr、exitCode 和耗时。",
        "source": "builtin",
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "命令，例如 git diff --check 或 python -m pytest。"},
                "cwd": {"type": "string", "description": "工作目录，默认当前允许目录。"},
                "timeoutSeconds": {"type": "number", "description": "超时秒数，默认 60，上限 300。"},
            },
            "required": ["command"],
            "x-graphic": {"kind": "builtin_tool", "builtinId": "run_whitelisted_command", "version": "0.1.0", "usageTags": ["命令"]},
        },
    },
]


def builtin_tool_config_dicts() -> list[dict[str, str]]:
    configs: list[dict[str, str]] = []
    for definition in BUILTIN_TOOL_DEFINITIONS:
        configs.append(
            {
                "id": str(definition["id"]),
                "name": str(definition["name"]),
                "description": str(definition["description"]),
                "source": "builtin",
                "schemaJson": json.dumps(deepcopy(definition["schema"]), ensure_ascii=False, indent=2),
            }
        )
    return configs


def builtin_tool_config_by_id(tool_id: str) -> dict[str, str] | None:
    for config in builtin_tool_config_dicts():
        if config["id"] == tool_id:
            return config
    return None
