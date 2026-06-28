from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app.code_intelligence import (
    glg_asset_references,
    glg_extract_css_for_html,
    glg_extract_html_by_text,
    glg_summarize_page_structure,
)

from .. import engine


def extract_html(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    selector = str(args.get("selector") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_html 需要 path 参数。")
    if not selector:
        raise RuntimeError("extract_html 需要 selector 参数。")
    path = engine._resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 HTML 的文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"extract_html 只读取文本 HTML 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    mode = str(args.get("mode") or "html").strip().lower()
    if mode not in {"html", "text", "attributes"}:
        mode = "html"
    max_results = min(engine._positive_int(args.get("max_results", args.get("limit")), 20), 100)
    max_chars = min(engine._positive_int(args.get("max_chars"), 4000), engine._runtime_max_file_bytes(runtime))
    text, source_truncated = engine._read_text_limited(path, runtime, encoding)
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("后端缺少 beautifulsoup4，请安装 requirements.txt 后重试。") from exc

    soup = BeautifulSoup(text, "html.parser")
    try:
        selected = soup.select(selector)
    except Exception as exc:
        raise RuntimeError(f"extract_html selector 无效：{exc}") from exc

    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
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
        item: dict[str, Any] = {
            "index": index,
            "selector": selector,
            "startLine": start_line,
            "endLine": end_line,
        }
        if mode == "text":
            value = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            clipped, was_truncated = _clip_text(value, max_chars)
            item["text"] = clipped
        elif mode == "attributes":
            item["attributes"] = {
                str(key): (" ".join(value) if isinstance(value, list) else str(value))
                for key, value in element.attrs.items()
            }
            was_truncated = False
        else:
            clipped, was_truncated = _clip_text(outer_html, max_chars)
            item["html"] = clipped
        if was_truncated:
            item["truncated"] = True
            truncated = True
        matches.append(item)
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，HTML 抽取结果可能不完整。")
    return {
        "path": str(path),
        "selector": selector,
        "mode": mode,
        "matches": matches,
        "count": len(matches),
        "totalMatched": len(selected),
        "truncated": truncated,
        "warnings": warnings,
    }


def extract_css_rules(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    selector = str(args.get("selector") or "").strip()
    property_name = str(args.get("property") or args.get("property_name") or args.get("propertyName") or "").strip()
    query = str(args.get("query") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_css_rules 需要 path 参数。")
    if not selector and not property_name and not query:
        raise RuntimeError("extract_css_rules 需要 selector、property 或 query 至少一个参数。")
    path = engine._resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 CSS 的文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"extract_css_rules 只读取文本 CSS 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_results = min(engine._positive_int(args.get("max_results", args.get("limit")), 50), 200)
    text, source_truncated = engine._read_text_limited(path, runtime, encoding)
    rules, parse_warnings = _parse_css_rules(text)
    matched: list[dict[str, Any]] = []
    total_matched = 0
    selector_key = _normalize_css_selector(selector) if selector else ""
    property_key = property_name.lower()
    query_key = query.lower()
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
    return {
        "path": str(path),
        "selector": selector,
        "property": property_name,
        "query": query,
        "rules": matched,
        "count": len(matched),
        "totalMatched": total_matched,
        "truncated": source_truncated or total_matched > max_results,
        "warnings": warnings,
    }


def extract_html_by_text(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    query = str(args.get("query") or args.get("text") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_html_by_text 需要 path 参数。")
    if not query:
        raise RuntimeError("extract_html_by_text 需要 query 参数。")
    path = engine._resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 HTML 的文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"extract_html_by_text 只读取文本 HTML 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_results = min(engine._positive_int(args.get("max_results", args.get("limit")), 20), 100)
    max_chars = min(engine._positive_int(args.get("max_chars"), 4000), engine._runtime_max_file_bytes(runtime))
    text, source_truncated = engine._read_text_limited(path, runtime, encoding)
    result = glg_extract_html_by_text(
        text=text,
        query=query,
        regex=engine._truthy(args.get("regex")),
        mode=str(args.get("mode") or "html"),
        max_results=max_results,
        max_chars=max_chars,
        case_sensitive=engine._truthy(args.get("case_sensitive", args.get("caseSensitive"))),
    )
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，HTML 文本抽取结果可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["truncated"] = bool(result.get("truncated") or source_truncated)
    result["warnings"] = warnings
    return result


def extract_css_for_html(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("css_path") or args.get("cssPath") or "").strip()
    selector = str(args.get("selector") or args.get("html_selector") or args.get("htmlSelector") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_css_for_html 需要 path 参数。")
    if not selector:
        raise RuntimeError("extract_css_for_html 需要 selector 参数。")
    path = engine._resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可抽取 CSS 的文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"extract_css_for_html 只读取文本 CSS 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_results = min(engine._positive_int(args.get("max_results", args.get("limit")), 50), 200)
    css_text, css_truncated = engine._read_text_limited(path, runtime, encoding)
    html_text = ""
    html_path_text = str(args.get("html_path") or args.get("htmlPath") or "").strip()
    html_path: Path | None = None
    html_truncated = False
    if html_path_text:
        html_path = engine._resolve_runtime_path(html_path_text, runtime)
        if not html_path.is_file():
            raise RuntimeError(f"不是可分析 HTML 的文件：{html_path}")
        if engine._is_binary_file(html_path):
            raise RuntimeError(f"extract_css_for_html 只读取文本 HTML 文件，疑似二进制文件：{html_path}")
        html_text, html_truncated = engine._read_text_limited(html_path, runtime, encoding)
    result = glg_extract_css_for_html(css_text=css_text, selector=selector, html_text=html_text, max_results=max_results)
    warnings = list(result.get("warnings") or [])
    if css_truncated:
        warnings.append("CSS 文件内容超过当前运行环境单次读取大小，样式匹配可能不完整。")
    if html_truncated:
        warnings.append("HTML 文件内容超过当前运行环境单次读取大小，元素 token 推导可能不完整。")
    result["path"] = str(path)
    result["htmlPath"] = str(html_path) if html_path else ""
    result["encoding"] = encoding
    result["truncated"] = bool(result.get("truncated") or css_truncated or html_truncated)
    result["warnings"] = warnings
    return result


def summarize_page_structure(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("summarize_page_structure 需要 path 参数。")
    path = engine._resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析 HTML 的文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"summarize_page_structure 只读取文本 HTML 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_items = min(engine._positive_int(args.get("max_items", args.get("limit")), 50), 200)
    text, source_truncated = engine._read_text_limited(path, runtime, encoding)
    result = glg_summarize_page_structure(text, max_items)
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，页面结构摘要可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["truncated"] = source_truncated
    result["warnings"] = warnings
    return result


def resolve_asset_references(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("resolve_asset_references 需要 path 参数。")
    path = engine._resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可扫描资源引用的文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"resolve_asset_references 只读取文本 HTML/CSS 文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    language = engine._detect_code_language(path, str(args.get("language") or ""))
    max_results = min(engine._positive_int(args.get("max_results", args.get("limit")), 200), 500)
    text, source_truncated = engine._read_text_limited(path, runtime, encoding)
    result = glg_asset_references(text, language, max_results)
    references = [_enrich_asset_reference(item, path, runtime) for item in result.get("references", []) if isinstance(item, dict)]
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，资源引用可能不完整。")
    return {
        "path": str(path),
        "language": language,
        "references": references,
        "count": len(references),
        "totalMatched": result.get("totalMatched", len(references)),
        "truncated": bool(result.get("truncated") or source_truncated),
        "warnings": warnings,
    }


def _clip_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _best_effort_html_lines(source: str, fragment: str, start_offset: int) -> tuple[int | None, int | None, int]:
    if not fragment:
        return None, None, start_offset
    index = source.find(fragment, start_offset)
    if index < 0:
        index = source.find(fragment)
    if index < 0:
        return None, None, start_offset
    start_line = source.count("\n", 0, index) + 1
    end_line = start_line + fragment.count("\n")
    return start_line, end_line, index + len(fragment)


def _strip_css_comments_preserve_lines(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        return "".join("\n" if char == "\n" else " " for char in value)

    return re.sub(r"/\*.*?\*/", replace, text, flags=re.DOTALL)


def _parse_css_rules(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if re.search(r"@[A-Za-z-]+\s+[^{]*{[^{}]*{", text, re.DOTALL):
        warnings.append("检测到可能的嵌套 at-rule，CSS 解析按普通规则 best-effort 处理。")
    clean = _strip_css_comments_preserve_lines(text)
    rules: list[dict[str, Any]] = []
    for match in re.finditer(r"(?s)([^{}]+)\{([^{}]*)\}", clean):
        selector_text = match.group(1).strip()
        body = match.group(2).strip()
        if not selector_text or not body or selector_text.startswith("@"):
            continue
        selectors = [part.strip() for part in selector_text.split(",") if part.strip()]
        declarations: dict[str, str] = {}
        for declaration in body.split(";"):
            if ":" not in declaration:
                continue
            name, value = declaration.split(":", 1)
            name = name.strip()
            if not name:
                continue
            declarations[name] = value.strip()
        if not declarations:
            continue
        selector_start = match.start(1) + (len(match.group(1)) - len(match.group(1).lstrip()))
        start_line = clean.count("\n", 0, selector_start) + 1
        end_line = clean.count("\n", 0, match.end()) + 1
        css = text[selector_start : match.end()].strip()
        rules.append(
            {
                "selector": selector_text,
                "selectors": selectors,
                "declarations": declarations,
                "startLine": start_line,
                "endLine": end_line,
                "css": css,
            }
        )
    return rules, warnings


def _normalize_css_selector(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _enrich_asset_reference(reference: dict[str, Any], base_file: Path, runtime: dict[str, Any]) -> dict[str, Any]:
    item = dict(reference)
    raw_url = str(item.get("url") or "").strip()
    item["url"] = raw_url
    parsed = urlparse(raw_url)
    if not raw_url:
        item.update({"external": False, "allowed": False, "exists": False, "resolvedPath": ""})
        return item
    if parsed.scheme in {"http", "https", "data", "blob", "mailto", "tel"} or raw_url.startswith(("#", "//")):
        item.update({"external": True, "allowed": None, "exists": None, "resolvedPath": ""})
        return item
    relative_part = unquote(raw_url.split("?", 1)[0].split("#", 1)[0])
    if not relative_part:
        item.update({"external": False, "allowed": False, "exists": False, "resolvedPath": ""})
        return item
    candidate = (base_file.parent / relative_part).resolve()
    allowed = any(engine._is_relative_to(candidate, root) for root in engine._runtime_allowed_roots(runtime))
    item.update(
        {
            "external": False,
            "allowed": allowed,
            "exists": candidate.exists() if allowed else False,
            "resolvedPath": str(candidate) if allowed else "",
        }
    )
    return item
