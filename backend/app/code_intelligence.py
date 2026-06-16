import ast
import html as html_lib
import json
import re
from html.parser import HTMLParser
from typing import Any


GLG_SUPPORTED_STRUCTURED_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "html",
    "css",
    "scss",
    "less",
    "vue",
    "svelte",
    "json",
    "yaml",
    "markdown",
}


def glg_semantic_symbols(text: str, language: str, max_symbols: int = 1000) -> tuple[list[dict[str, Any]], list[str]]:
    language = _glg_normalize_language(language)
    max_symbols = max(1, int(max_symbols or 1000))
    warnings: list[str] = []
    try:
        if language == "python":
            return _glg_python_symbols(text, max_symbols), warnings
        if language in {"javascript", "typescript"}:
            symbols, ts_warnings = _glg_tree_sitter_js_symbols(text, language, max_symbols)
            warnings.extend(ts_warnings)
            if symbols:
                return symbols[:max_symbols], warnings
            fallback = _glg_javascript_symbols(text, max_symbols)
            if fallback:
                warnings.append("Tree-sitter 不可用或未识别到结构，已使用 JS/TS 启发式解析。")
            return fallback[:max_symbols], warnings
        if language == "html":
            symbols, ts_warnings = _glg_tree_sitter_html_symbols(text, max_symbols)
            warnings.extend(ts_warnings)
            if symbols:
                return symbols[:max_symbols], warnings
            return _glg_html_symbols(text, max_symbols), warnings
        if language == "css":
            return _glg_css_symbols(text, max_symbols), warnings
        if language in {"scss", "less"}:
            return _glg_style_symbols(text, max_symbols, language), warnings
        if language in {"vue", "svelte"}:
            return _glg_single_file_component_symbols(text, language, max_symbols), warnings
        if language == "markdown":
            return _glg_markdown_symbols(text, max_symbols), warnings
        if language == "json":
            return _glg_json_symbols(text, max_symbols), warnings
        if language == "yaml":
            return _glg_yaml_symbols(text, max_symbols), warnings
        return [], [f"暂不支持的语言：{language or 'unknown'}。"]
    except Exception as exc:
        return [], [f"结构化解析失败：{exc.__class__.__name__}: {exc}"]


def glg_extract_code_symbol(
    text: str,
    language: str,
    symbol: str,
    kind: str = "any",
    max_chars: int = 4000,
    include_context: bool = False,
) -> dict[str, Any]:
    query = str(symbol or "").strip()
    if not query:
        return {"found": False, "warnings": ["extract_code_symbol 需要 symbol。"]}
    max_chars = max(1, int(max_chars or 4000))
    kind = _glg_normalize_kind(kind)
    symbols, warnings = glg_semantic_symbols(text, language, 2000)
    matches = [item for item in symbols if _glg_symbol_matches(item, query, kind)]
    if not matches:
        return {
            "found": False,
            "symbol": query,
            "kind": kind,
            "language": _glg_normalize_language(language),
            "warnings": warnings,
            "alternatives": [_glg_symbol_alternative(item) for item in symbols[:20]],
        }
    selected = sorted(matches, key=lambda item: (int(item.get("startLine") or 1), str(item.get("name") or "")))[0]
    content = _glg_symbol_content(text, selected)
    clipped, truncated = _glg_clip_text(content, max_chars)
    alternatives = [_glg_symbol_alternative(item) for item in matches[1:21]]
    result: dict[str, Any] = {
        "found": True,
        "symbol": str(selected.get("name") or query),
        "requestedSymbol": query,
        "kind": str(selected.get("kind") or kind),
        "language": _glg_normalize_language(language),
        "startLine": selected.get("startLine"),
        "endLine": selected.get("endLine"),
        "content": clipped,
        "ambiguous": len(matches) > 1,
        "alternatives": alternatives,
        "truncated": truncated,
        "warnings": warnings,
    }
    if include_context:
        result["context"] = _glg_context_lines(text, int(selected.get("startLine") or 1), int(selected.get("endLine") or selected.get("startLine") or 1))
    return result


def glg_chunk_code_semantic(
    text: str,
    language: str,
    max_chars: int = 4000,
    max_chunks: int = 80,
    include_content: bool = False,
) -> dict[str, Any]:
    language = _glg_normalize_language(language)
    max_chars = max(1, int(max_chars or 4000))
    max_chunks = max(1, min(int(max_chunks or 80), 500))
    symbols, warnings = glg_semantic_symbols(text, language, max_chunks * 4)
    chunks: list[dict[str, Any]] = []
    truncated = False

    if symbols:
        for symbol in sorted(symbols, key=lambda item: (int(item.get("startLine") or 1), str(item.get("name") or ""))):
            content = _glg_symbol_content(text, symbol)
            if not content:
                continue
            pieces = _glg_split_text(content, max_chars)
            for part_index, piece in enumerate(pieces, start=1):
                if len(chunks) >= max_chunks:
                    truncated = True
                    break
                chunk: dict[str, Any] = {
                    "index": len(chunks) + 1,
                    "kind": symbol.get("kind") or "symbol",
                    "name": symbol.get("name") or "",
                    "startLine": symbol.get("startLine"),
                    "endLine": symbol.get("endLine"),
                    "size": len(piece),
                    "preview": _glg_preview(piece, 320),
                    "truncated": len(pieces) > 1 and part_index < len(pieces),
                }
                if len(pieces) > 1:
                    chunk["part"] = part_index
                    chunk["parts"] = len(pieces)
                if include_content:
                    chunk["content"] = piece
                chunks.append(chunk)
            if truncated:
                break
    else:
        warnings.append("未识别到语义符号，已按字符范围分片。")
        for part_index, piece in enumerate(_glg_split_text(text, max_chars), start=1):
            if len(chunks) >= max_chunks:
                truncated = True
                break
            start_offset = (part_index - 1) * max_chars
            chunk = {
                "index": len(chunks) + 1,
                "kind": "text_chunk",
                "name": f"chunk_{part_index}",
                "startLine": text[:start_offset].count("\n") + 1,
                "endLine": text[: start_offset + len(piece)].count("\n") + 1,
                "size": len(piece),
                "preview": _glg_preview(piece, 320),
                "truncated": part_index * max_chars < len(text),
            }
            if include_content:
                chunk["content"] = piece
            chunks.append(chunk)

    return {
        "language": language,
        "chunks": chunks,
        "count": len(chunks),
        "truncated": truncated,
        "warnings": warnings,
    }


def glg_extract_html_by_text(
    text: str,
    query: str,
    regex: bool = False,
    mode: str = "html",
    max_results: int = 20,
    max_chars: int = 4000,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"matches": [], "count": 0, "totalMatched": 0, "truncated": False, "warnings": ["extract_html_by_text 需要 query。"]}
    mode = str(mode or "html").strip().lower()
    if mode not in {"html", "text", "attributes"}:
        mode = "html"
    max_results = max(1, min(int(max_results or 20), 100))
    max_chars = max(1, int(max_chars or 4000))
    warnings: list[str] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"matches": [], "count": 0, "totalMatched": 0, "truncated": False, "warnings": ["缺少 beautifulsoup4，无法按文本抽取 HTML。"]}

    soup = BeautifulSoup(text, "html.parser")
    pattern = None
    if regex:
        try:
            pattern = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
        except re.error as exc:
            return {"matches": [], "count": 0, "totalMatched": 0, "truncated": False, "warnings": [f"正则表达式无效：{exc}"]}
    needle = query if case_sensitive else query.lower()
    candidates: list[Any] = []
    for element in soup.find_all(True):
        visible_text = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
        if not visible_text:
            continue
        matched = bool(pattern.search(visible_text)) if pattern else (needle in (visible_text if case_sensitive else visible_text.lower()))
        if matched and not _glg_descendant_matches_text(element, needle, pattern, case_sensitive):
            candidates.append(element)

    matches: list[dict[str, Any]] = []
    search_from = 0
    truncated = len(candidates) > max_results
    for index, element in enumerate(candidates[:max_results], start=1):
        outer_html = str(element)
        start_line, end_line, search_from = _glg_best_effort_html_lines(text, outer_html, search_from)
        item: dict[str, Any] = {
            "index": index,
            "query": query,
            "tag": getattr(element, "name", ""),
            "selectorHint": _glg_element_selector_hint(element),
            "startLine": start_line,
            "endLine": end_line,
        }
        if mode == "text":
            value = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            item["text"], item_truncated = _glg_clip_text(value, max_chars)
        elif mode == "attributes":
            item["attributes"] = _glg_bs4_attrs(element)
            item_truncated = False
        else:
            item["html"], item_truncated = _glg_clip_text(outer_html, max_chars)
        if item_truncated:
            item["truncated"] = True
            truncated = True
        matches.append(item)
    return {"matches": matches, "count": len(matches), "totalMatched": len(candidates), "truncated": truncated, "warnings": warnings}


def glg_summarize_page_structure(text: str, max_items: int = 50) -> dict[str, Any]:
    max_items = max(1, min(int(max_items or 50), 200))
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"warnings": ["缺少 beautifulsoup4，无法分析页面结构。"]}
    soup = BeautifulSoup(text, "html.parser")
    title_node = soup.find("title")
    warnings: list[str] = []
    summary = {
        "title": title_node.get_text(" ", strip=True) if title_node else "",
        "headings": [],
        "landmarks": [],
        "forms": [],
        "buttons": [],
        "links": [],
        "images": [],
        "scripts": [],
        "stylesheets": [],
        "inlineStyles": [],
        "warnings": warnings,
    }

    for heading in soup.find_all(re.compile(r"^h[1-6]$"), limit=max_items):
        summary["headings"].append({"level": heading.name, "text": heading.get_text(" ", strip=True), "selectorHint": _glg_element_selector_hint(heading)})
    for element in soup.find_all(["header", "nav", "main", "section", "article", "aside", "footer"], limit=max_items):
        summary["landmarks"].append({"tag": element.name, "selectorHint": _glg_element_selector_hint(element), "text": _glg_preview(element.get_text(" ", strip=True), 160)})
    for form in soup.find_all("form", limit=max_items):
        controls = []
        for control in form.find_all(["input", "select", "textarea", "button"], limit=40):
            controls.append({"tag": control.name, "type": control.get("type", ""), "name": control.get("name", ""), "text": control.get_text(" ", strip=True)})
        summary["forms"].append({"selectorHint": _glg_element_selector_hint(form), "action": form.get("action", ""), "method": form.get("method", ""), "controls": controls})
    for button in soup.find_all(["button"], limit=max_items):
        summary["buttons"].append({"text": button.get_text(" ", strip=True), "selectorHint": _glg_element_selector_hint(button), "type": button.get("type", "")})
    for link in soup.find_all("a", limit=max_items):
        summary["links"].append({"text": link.get_text(" ", strip=True), "href": link.get("href", ""), "selectorHint": _glg_element_selector_hint(link)})
    for image in soup.find_all("img", limit=max_items):
        summary["images"].append({"src": image.get("src", ""), "alt": image.get("alt", ""), "selectorHint": _glg_element_selector_hint(image)})
    for script in soup.find_all("script", limit=max_items):
        summary["scripts"].append({"src": script.get("src", ""), "type": script.get("type", ""), "inline": not bool(script.get("src"))})
    for link in soup.find_all("link", limit=max_items):
        rel = " ".join(link.get("rel", [])) if isinstance(link.get("rel"), list) else str(link.get("rel") or "")
        if "stylesheet" in rel.lower() or str(link.get("href") or "").lower().endswith(".css"):
            summary["stylesheets"].append({"href": link.get("href", ""), "rel": rel, "media": link.get("media", "")})
    for style in soup.find_all("style", limit=max_items):
        summary["inlineStyles"].append({"selectorHint": _glg_element_selector_hint(style), "chars": len(style.get_text() or ""), "preview": _glg_preview(style.get_text() or "", 160)})
    for key in ("headings", "landmarks", "forms", "buttons", "links", "images", "scripts", "stylesheets", "inlineStyles"):
        if len(summary[key]) >= max_items:
            warnings.append(f"{key} 达到 max_items 限制，结果可能被截断。")
    return summary


def glg_extract_css_for_html(
    css_text: str,
    selector: str,
    html_text: str = "",
    max_results: int = 50,
) -> dict[str, Any]:
    selector = str(selector or "").strip()
    if not selector:
        return {"rules": [], "count": 0, "totalMatched": 0, "truncated": False, "warnings": ["extract_css_for_html 需要 selector。"], "queryTokens": []}
    max_results = max(1, min(int(max_results or 50), 200))
    warnings: list[str] = []
    tokens = _glg_selector_tokens(selector)
    if html_text:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_text, "html.parser")
            for element in soup.select(selector):
                tokens.extend(_glg_tokens_for_bs4_element(element))
        except Exception as exc:
            warnings.append(f"HTML selector 解析失败，已仅按 selector 文本匹配 CSS：{exc.__class__.__name__}: {exc}")
    tokens = _glg_unique_tokens(tokens)
    rules, parse_warnings = _glg_parse_css_rules(css_text)
    warnings.extend(parse_warnings)
    matched: list[dict[str, Any]] = []
    total_matched = 0
    for rule in rules:
        if _glg_css_rule_matches_tokens(rule, tokens):
            total_matched += 1
            if len(matched) < max_results:
                matched.append(rule)
    return {
        "selector": selector,
        "queryTokens": tokens,
        "rules": matched,
        "count": len(matched),
        "totalMatched": total_matched,
        "truncated": total_matched > max_results,
        "warnings": warnings,
    }


def glg_asset_references(text: str, language: str = "html", max_results: int = 200) -> dict[str, Any]:
    language = _glg_normalize_language(language)
    max_results = max(1, min(int(max_results or 200), 500))
    refs: list[dict[str, Any]] = []
    warnings: list[str] = []
    if language in {"css", "scss", "less"}:
        refs.extend(_glg_css_asset_references(text))
    else:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "html.parser")
            refs.extend(_glg_html_asset_references(soup))
            for style in soup.find_all("style"):
                refs.extend(_glg_css_asset_references(style.get_text() or "", context="style"))
        except ImportError:
            refs.extend(_glg_html_asset_references_fallback(text))
            warnings.append("缺少 beautifulsoup4，已使用轻量 HTML 资源扫描。")
    return {"references": refs[:max_results], "count": min(len(refs), max_results), "totalMatched": len(refs), "truncated": len(refs) > max_results, "warnings": warnings}


def _glg_normalize_language(language: str) -> str:
    normalized = str(language or "").strip().lower().replace("-", "_")
    aliases = {
        "py": "python",
        "python": "python",
        "js": "javascript",
        "mjs": "javascript",
        "cjs": "javascript",
        "jsx": "javascript",
        "javascript": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "typescript": "typescript",
        "html": "html",
        "htm": "html",
        "css": "css",
        "scss": "scss",
        "sass": "scss",
        "less": "less",
        "vue": "vue",
        "svelte": "svelte",
        "json": "json",
        "jsonc": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "md": "markdown",
        "markdown": "markdown",
    }
    return aliases.get(normalized, normalized or "unknown")


def _glg_normalize_kind(kind: str) -> str:
    normalized = str(kind or "any").strip().lower()
    aliases = {
        "tag": "html",
        "html_element": "html",
        "css_rule": "css",
        "rule": "css",
        "style_rule": "style_rule",
        "section": "section",
        "heading": "heading",
        "data": "data_key",
        "key": "data_key",
    }
    return aliases.get(normalized, normalized if normalized else "any")


def _glg_python_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    tree = ast.parse(text)
    lines = text.splitlines()
    symbols: list[dict[str, Any]] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_glg_python_symbol_dict(item.name, "function", item, lines))
        elif isinstance(item, ast.ClassDef):
            symbols.append(_glg_python_symbol_dict(item.name, "class", item, lines))
            for child in item.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(_glg_python_symbol_dict(f"{item.name}.{child.name}", "method", child, lines, child.name))
        if len(symbols) >= max_symbols:
            break
    return sorted(symbols, key=lambda symbol: (symbol["startLine"], symbol["name"]))[:max_symbols]


def _glg_python_symbol_dict(name: str, kind: str, node: Any, lines: list[str], short_name: str | None = None) -> dict[str, Any]:
    start = int(getattr(node, "lineno", 1) or 1)
    end = int(getattr(node, "end_lineno", start) or start)
    preview = lines[start - 1].strip() if 0 <= start - 1 < len(lines) else name
    item = {"name": name, "kind": kind, "startLine": start, "endLine": end, "preview": preview}
    if short_name:
        item["shortName"] = short_name
    return item


def _glg_tree_sitter_js_symbols(text: str, language: str, max_symbols: int) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return [], ["缺少 tree-sitter-language-pack，已降级为启发式解析。"]
    parser_name = "tsx" if language in {"javascript", "typescript"} else language
    try:
        tree = get_parser(parser_name).parse(text)
        root = _glg_tree_root(tree)
    except Exception as exc:
        return [], [f"Tree-sitter 解析失败：{exc.__class__.__name__}: {exc}"]
    symbols: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    for node in _glg_walk_ts(root):
        kind_name = _glg_ts_kind(node)
        name_node = None
        symbol_node = node
        symbol_kind = ""
        name = ""
        short_name = ""
        if kind_name in {"function_declaration", "generator_function_declaration"}:
            name_node = _glg_ts_child_by_field(node, "name")
            symbol_kind = "function"
        elif kind_name == "class_declaration":
            name_node = _glg_ts_child_by_field(node, "name")
            symbol_kind = "class"
        elif kind_name == "method_definition":
            name_node = _glg_ts_child_by_field(node, "name")
            symbol_kind = "method"
        elif kind_name == "variable_declarator":
            value_node = _glg_ts_child_by_field(node, "value")
            value_kind = _glg_ts_kind(value_node) if value_node is not None else ""
            if value_kind in {"arrow_function", "function_expression", "generator_function"}:
                name_node = _glg_ts_child_by_field(node, "name")
                short_name = _glg_node_text(text, name_node)
                symbol_kind = "component" if _glg_is_component_candidate(short_name, _glg_node_text(text, node)) else "function"
                parent = _glg_ts_parent(node)
                if _glg_ts_kind(parent) in {"lexical_declaration", "variable_declaration"}:
                    symbol_node = parent
        if name_node is None or not symbol_kind:
            continue
        if not short_name:
            short_name = _glg_node_text(text, name_node)
        if not short_name:
            continue
        if symbol_kind == "method":
            class_name = _glg_enclosing_class_name(text, node)
            name = f"{class_name}.{short_name}" if class_name else short_name
        else:
            name = short_name
        start_byte = _glg_ts_start_byte(symbol_node)
        end_byte = _glg_ts_end_byte(symbol_node)
        key = (name, symbol_kind, start_byte, end_byte)
        if key in seen:
            continue
        seen.add(key)
        content = _glg_slice_by_bytes(text, start_byte, end_byte)
        symbols.append(
            {
                "name": name,
                "shortName": short_name,
                "kind": symbol_kind,
                "startLine": _glg_ts_start_line(symbol_node),
                "endLine": _glg_ts_end_line(symbol_node),
                "startByte": start_byte,
                "endByte": end_byte,
                "preview": _glg_preview(content, 160),
            }
        )
        if len(symbols) >= max_symbols:
            break
    return sorted(symbols, key=lambda item: (int(item.get("startLine") or 1), str(item.get("name") or "")))[:max_symbols], []


def _glg_tree_sitter_html_symbols(text: str, max_symbols: int) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return [], ["缺少 tree-sitter-language-pack，已降级为 HTMLParser 解析。"]
    try:
        root = _glg_tree_root(get_parser("html").parse(text))
    except Exception as exc:
        return [], [f"Tree-sitter HTML 解析失败：{exc.__class__.__name__}: {exc}"]
    symbols: list[dict[str, Any]] = []
    for node in _glg_walk_ts(root):
        if _glg_ts_kind(node) != "element":
            continue
        content = _glg_node_text(text, node)
        start_tag = re.match(r"<\s*([A-Za-z][\w:-]*)([^>]*)>", content, re.DOTALL)
        if not start_tag:
            continue
        tag = start_tag.group(1)
        attrs = _glg_parse_html_attrs(start_tag.group(2))
        name = _glg_html_symbol_name(tag, attrs)
        symbols.append(
            {
                "name": name,
                "kind": "html",
                "tag": tag,
                "attributes": attrs,
                "startLine": _glg_ts_start_line(node),
                "endLine": _glg_ts_end_line(node),
                "startByte": _glg_ts_start_byte(node),
                "endByte": _glg_ts_end_byte(node),
                "preview": _glg_preview(start_tag.group(0), 160),
            }
        )
        if len(symbols) >= max_symbols:
            break
    return symbols[:max_symbols], []


class _GlgHtmlSymbolParser(HTMLParser):
    def __init__(self, max_symbols: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_symbols = max_symbols
        self.symbols: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.symbols) >= self.max_symbols:
            return
        attr = {key: value or "" for key, value in attrs}
        line, _column = self.getpos()
        self.symbols.append(
            {
                "name": _glg_html_symbol_name(tag, attr),
                "kind": "html",
                "tag": tag,
                "attributes": attr,
                "startLine": line,
                "endLine": line,
                "preview": f"<{tag}>",
            }
        )


def _glg_html_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    parser = _GlgHtmlSymbolParser(max_symbols)
    parser.feed(text)
    parser.close()
    return parser.symbols[:max_symbols]


def _glg_javascript_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    patterns = [
        ("class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
        ("function", re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
        ("function", re.compile(r"\b([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?function\s*\(")),
    ]
    symbols: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            name = match.group(1)
            symbols.append({"name": name, "shortName": name, "kind": kind, "startLine": line_no, "endLine": line_no, "preview": line.strip()})
            break
        if len(symbols) >= max_symbols:
            break
    return symbols


def _glg_css_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    rules, _warnings = _glg_parse_css_rules(text)
    symbols: list[dict[str, Any]] = []
    for rule in rules[:max_symbols]:
        symbols.append(
            {
                "name": rule["selector"],
                "kind": "css",
                "selectors": rule["selectors"],
                "declarations": rule["declarations"],
                "startLine": rule["startLine"],
                "endLine": rule["endLine"],
                "content": rule["css"],
                "preview": _glg_preview(rule["css"], 160),
            }
        )
    return symbols


def _glg_style_symbols(text: str, max_symbols: int, language: str) -> list[dict[str, Any]]:
    symbols = _glg_css_symbols(text, max_symbols)
    if len(symbols) >= max_symbols:
        return symbols[:max_symbols]
    existing = {(str(item.get("name") or ""), int(item.get("startLine") or 0)) for item in symbols}
    nested = _glg_nested_style_symbols(text, max_symbols - len(symbols), language)
    for item in nested:
        key = (str(item.get("name") or ""), int(item.get("startLine") or 0))
        if key in existing:
            continue
        existing.add(key)
        symbols.append(item)
        if len(symbols) >= max_symbols:
            break
    return sorted(symbols, key=lambda item: (int(item.get("startLine") or 1), str(item.get("name") or "")))[:max_symbols]


def _glg_nested_style_symbols(text: str, max_symbols: int, language: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("/*", "//", "*")):
            continue
        if language in {"scss", "less"}:
            variable_match = re.match(r"([$@][\w-]+)\s*:", stripped)
            if variable_match:
                symbols.append({"name": variable_match.group(1), "kind": "style_variable", "startLine": line_no, "endLine": line_no, "preview": stripped, "content": line})
                if len(symbols) >= max_symbols:
                    break
            mixin_match = re.match(r"@(?:mixin|function)\s+([\w-]+)", stripped)
            if mixin_match:
                symbols.append({"name": mixin_match.group(1), "kind": "style_mixin", "startLine": line_no, "endLine": line_no, "preview": stripped, "content": _glg_style_block_content(lines, line_no)})
                if len(symbols) >= max_symbols:
                    break
        if "{" in stripped:
            selector_text = stripped.split("{", 1)[0].strip()
            if selector_text and not selector_text.startswith(("$", "@include")) and ":" not in selector_text:
                parent_selectors = stack[-1]["fullSelectors"] if stack else []
                full_selectors = _glg_expand_nested_selectors(parent_selectors, selector_text)
                if not selector_text.startswith("@"):
                    content = _glg_style_block_content(lines, line_no)
                    for selector in full_selectors:
                        symbols.append(
                            {
                                "name": selector,
                                "kind": "style_rule",
                                "selectors": full_selectors,
                                "startLine": line_no,
                                "endLine": line_no + content.count("\n"),
                                "content": content,
                                "preview": _glg_preview(content, 160),
                            }
                        )
                        if len(symbols) >= max_symbols:
                            return symbols
                stack.append({"selector": selector_text, "fullSelectors": full_selectors})
        close_count = stripped.count("}")
        for _ in range(close_count):
            if stack:
                stack.pop()
    return symbols[:max_symbols]


def _glg_expand_nested_selectors(parent_selectors: list[str], selector_text: str) -> list[str]:
    selectors = [part.strip() for part in selector_text.split(",") if part.strip()]
    if not selectors:
        return []
    if not parent_selectors:
        return selectors
    expanded: list[str] = []
    for parent in parent_selectors:
        for selector in selectors:
            if selector.startswith("@"):
                expanded.append(selector)
            elif "&" in selector:
                expanded.append(selector.replace("&", parent))
            else:
                expanded.append(f"{parent} {selector}")
    return expanded


def _glg_style_block_content(lines: list[str], start_line: int) -> str:
    depth = 0
    collected: list[str] = []
    for line in lines[start_line - 1 :]:
        collected.append(line)
        depth += line.count("{")
        depth -= line.count("}")
        if collected and depth <= 0 and "{" in "".join(collected):
            break
        if len(collected) >= 400:
            break
    return "\n".join(collected)


def _glg_single_file_component_symbols(text: str, language: str, max_symbols: int) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for match in re.finditer(r"(?is)<(template|script|style)\b([^>]*)>(.*?)</\1>", text):
        tag = match.group(1).lower()
        attrs_text = match.group(2) or ""
        body = match.group(3) or ""
        attrs = _glg_parse_html_attrs(attrs_text)
        name = tag
        if tag == "script" and "setup" in attrs_text.lower():
            name = "script setup"
        if tag == "style" and attrs.get("lang"):
            name = f"style:{attrs['lang']}"
        start_line = text.count("\n", 0, match.start()) + 1
        body_start_line = text.count("\n", 0, match.start(3)) + 1
        end_line = text.count("\n", 0, match.end()) + 1
        content = text[match.start() : match.end()]
        symbols.append(
            {
                "name": name,
                "kind": "section",
                "section": tag,
                "language": attrs.get("lang", _glg_component_section_language(tag, language, attrs)),
                "attributes": attrs,
                "startLine": start_line,
                "endLine": end_line,
                "content": content,
                "preview": _glg_preview(content, 160),
            }
        )
        if tag == "script":
            script_language = _glg_component_section_language(tag, language, attrs)
            nested, _warnings = glg_semantic_symbols(body, script_language, max(1, max_symbols - len(symbols)))
            symbols.extend(_glg_offset_nested_symbols(nested, body_start_line - 1, "script"))
        if tag == "template":
            nested, _warnings = glg_semantic_symbols(body, "html", max(1, max_symbols - len(symbols)))
            symbols.extend(_glg_offset_nested_symbols(nested, body_start_line - 1, "template"))
        if tag == "style":
            style_language = _glg_component_section_language(tag, language, attrs)
            nested, _warnings = glg_semantic_symbols(body, style_language, max(1, max_symbols - len(symbols)))
            symbols.extend(_glg_offset_nested_symbols(nested, body_start_line - 1, "style"))
        if len(symbols) >= max_symbols:
            break
    return sorted(symbols, key=lambda item: (int(item.get("startLine") or 1), str(item.get("name") or "")))[:max_symbols]


def _glg_component_section_language(tag: str, fallback_language: str, attrs: dict[str, str]) -> str:
    lang = str(attrs.get("lang") or "").lower()
    if tag == "template":
        return "html"
    if tag == "script":
        return "typescript" if lang in {"ts", "tsx", "typescript"} else "javascript"
    if tag == "style":
        return "scss" if lang in {"scss", "sass"} else "less" if lang == "less" else "css"
    return fallback_language


def _glg_offset_nested_symbols(symbols: list[dict[str, Any]], line_offset: int, section: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in symbols:
        nested = dict(item)
        nested["section"] = section
        if isinstance(nested.get("startLine"), int):
            nested["startLine"] = nested["startLine"] + line_offset
        if isinstance(nested.get("endLine"), int):
            nested["endLine"] = nested["endLine"] + line_offset
        result.append(nested)
    return result


def _glg_markdown_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    lines = text.splitlines()
    headings: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        headings.append({"level": len(match.group(1)), "name": match.group(2).strip(), "startLine": index})
    symbols: list[dict[str, Any]] = []
    for idx, heading in enumerate(headings):
        next_line = len(lines) + 1
        for later in headings[idx + 1 :]:
            if later["level"] <= heading["level"]:
                next_line = later["startLine"]
                break
        content = "\n".join(lines[heading["startLine"] - 1 : next_line - 1])
        symbols.append(
            {
                "name": heading["name"],
                "kind": "heading",
                "level": heading["level"],
                "startLine": heading["startLine"],
                "endLine": next_line - 1,
                "content": content,
                "preview": _glg_preview(content, 160),
            }
        )
        if len(symbols) >= max_symbols:
            break
    return symbols


def _glg_json_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    symbols: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            content = json.dumps(value, ensure_ascii=False, indent=2)
            line = _glg_find_json_key_line(text, str(key))
            symbols.append({"name": str(key), "kind": "data_key", "startLine": line, "endLine": line + content.count("\n"), "content": content, "preview": _glg_preview(content, 160)})
            if len(symbols) >= max_symbols:
                break
    elif isinstance(data, list):
        for index, value in enumerate(data[:max_symbols]):
            content = json.dumps(value, ensure_ascii=False, indent=2)
            symbols.append({"name": f"[{index}]", "kind": "data_item", "startLine": 1, "endLine": 1, "content": content, "preview": _glg_preview(content, 160)})
    return symbols


def _glg_find_json_key_line(text: str, key: str) -> int:
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:')
    for line_no, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            return line_no
    return 1


def _glg_yaml_symbols(text: str, max_symbols: int) -> list[dict[str, Any]]:
    lines = text.splitlines()
    entries: list[tuple[str, int]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:", line)
        if match:
            entries.append((match.group(1), line_no))
    symbols: list[dict[str, Any]] = []
    for index, (name, start_line) in enumerate(entries):
        end_line = (entries[index + 1][1] - 1) if index + 1 < len(entries) else len(lines)
        content = "\n".join(lines[start_line - 1 : end_line])
        symbols.append({"name": name, "kind": "data_key", "startLine": start_line, "endLine": end_line, "content": content, "preview": _glg_preview(content, 160)})
        if len(symbols) >= max_symbols:
            break
    return symbols


def _glg_symbol_matches(item: dict[str, Any], query: str, kind: str) -> bool:
    item_kind = _glg_normalize_kind(str(item.get("kind") or ""))
    if kind != "any":
        if kind == "html" and item_kind != "html":
            return False
        if kind == "css" and item_kind != "css":
            return False
        if kind not in {"html", "css"} and item_kind != kind:
            return False
    name = str(item.get("name") or "")
    short_name = str(item.get("shortName") or "")
    query_key = query.strip()
    query_lower = query_key.lower()
    if item_kind == "html":
        tag = str(item.get("tag") or "").lower()
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        class_tokens = str(attrs.get("class") or "").split()
        if query_key.startswith("#"):
            return str(attrs.get("id") or "").lower() == query_key[1:].lower() or query_lower in name.lower()
        if query_key.startswith("."):
            return query_key[1:].lower() in {item.lower() for item in class_tokens} or query_lower in name.lower()
        return tag == query_lower or name.lower() == query_lower
    if item_kind == "css":
        selectors = item.get("selectors") if isinstance(item.get("selectors"), list) else [name]
        normalized_query = _glg_normalize_css_selector(query_key)
        return normalized_query in {_glg_normalize_css_selector(str(selector)) for selector in selectors} or _glg_normalize_css_selector(name) == normalized_query
    candidates = {name, short_name}
    if "." in name:
        candidates.add(name.rsplit(".", 1)[-1])
    return query_lower in {candidate.lower() for candidate in candidates if candidate}


def _glg_symbol_content(text: str, symbol: dict[str, Any]) -> str:
    if isinstance(symbol.get("content"), str):
        return str(symbol["content"])
    start_byte = symbol.get("startByte")
    end_byte = symbol.get("endByte")
    if isinstance(start_byte, int) and isinstance(end_byte, int) and end_byte > start_byte:
        return _glg_slice_by_bytes(text, start_byte, end_byte)
    start = int(symbol.get("startLine") or 1)
    end = int(symbol.get("endLine") or start)
    lines = text.splitlines(keepends=True)
    return "".join(lines[max(0, start - 1) : min(len(lines), end)])


def _glg_symbol_alternative(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name"),
        "kind": item.get("kind"),
        "startLine": item.get("startLine"),
        "endLine": item.get("endLine"),
        "preview": item.get("preview"),
    }


def _glg_context_lines(text: str, start_line: int, end_line: int) -> dict[str, Any]:
    lines = text.splitlines()
    return {
        "before": lines[max(0, start_line - 3) : max(0, start_line - 1)],
        "after": lines[end_line : min(len(lines), end_line + 2)],
    }


def _glg_best_effort_html_lines(source: str, fragment: str, start_offset: int) -> tuple[int | None, int | None, int]:
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


def _glg_bs4_attrs(element: Any) -> dict[str, str]:
    attrs = getattr(element, "attrs", {}) if element is not None else {}
    result: dict[str, str] = {}
    for key, value in attrs.items():
        result[str(key)] = " ".join(value) if isinstance(value, list) else str(value)
    return result


def _glg_descendant_matches_text(element: Any, needle: str, pattern: Any, case_sensitive: bool) -> bool:
    for child in element.find_all(True, recursive=True):
        visible_text = re.sub(r"\s+", " ", child.get_text(" ", strip=True)).strip()
        if not visible_text:
            continue
        if pattern:
            if pattern.search(visible_text):
                return True
        else:
            haystack = visible_text if case_sensitive else visible_text.lower()
            if needle in haystack:
                return True
    return False


def _glg_element_selector_hint(element: Any) -> str:
    tag = str(getattr(element, "name", "") or "")
    attrs = _glg_bs4_attrs(element)
    if attrs.get("id"):
        return f"#{attrs['id']}"
    classes = [item for item in str(attrs.get("class") or "").split() if item]
    if classes:
        return f"{tag}." + ".".join(classes)
    name = attrs.get("name")
    if name:
        return f'{tag}[name="{name}"]'
    return tag


def _glg_selector_tokens(selector: str) -> list[str]:
    tokens: list[str] = []
    for item in re.findall(r"#[A-Za-z_][\w:-]*|\.[A-Za-z_][\w:-]*|\b[A-Za-z][\w:-]*\b", selector or ""):
        if item in {"not", "has", "is", "where", "nth", "child", "of"}:
            continue
        tokens.append(item)
    return tokens


def _glg_tokens_for_bs4_element(element: Any) -> list[str]:
    attrs = _glg_bs4_attrs(element)
    tokens = [str(getattr(element, "name", "") or "")]
    if attrs.get("id"):
        tokens.append(f"#{attrs['id']}")
    tokens.extend(f".{item}" for item in str(attrs.get("class") or "").split() if item)
    return [item for item in tokens if item]


def _glg_unique_tokens(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        normalized = token.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _glg_css_rule_matches_tokens(rule: dict[str, Any], tokens: list[str]) -> bool:
    if not tokens:
        return False
    selectors = rule.get("selectors") if isinstance(rule.get("selectors"), list) else [rule.get("selector", "")]
    selector_texts = [_glg_normalize_css_selector(str(item)) for item in selectors]
    for token in tokens:
        token_key = token.lower()
        if token.startswith(("#", ".")):
            pattern = re.compile(r"(^|[^A-Za-z0-9_-])" + re.escape(token_key) + r"($|[^A-Za-z0-9_-])")
            if any(pattern.search(selector) for selector in selector_texts):
                return True
        else:
            pattern = re.compile(r"(^|[\s>+~,(])" + re.escape(token_key) + r"($|[\s>+~).:#\[])")
            if any(pattern.search(selector) for selector in selector_texts):
                return True
    return False


def _glg_html_asset_references(soup: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    attr_map = {
        "img": ["src", "srcset"],
        "script": ["src"],
        "link": ["href"],
        "source": ["src", "srcset"],
        "video": ["src", "poster"],
        "audio": ["src"],
        "iframe": ["src"],
        "embed": ["src"],
        "object": ["data"],
        "a": ["href"],
    }
    for element in soup.find_all(True):
        tag = str(getattr(element, "name", "") or "")
        for attr in attr_map.get(tag, []):
            raw = element.get(attr)
            if not raw:
                continue
            for url in _glg_split_asset_value(str(raw), attr):
                refs.append({"source": "html", "tag": tag, "attribute": attr, "url": html_lib.unescape(url), "context": _glg_element_selector_hint(element)})
        style = element.get("style")
        if style:
            refs.extend(_glg_css_asset_references(str(style), context=_glg_element_selector_hint(element)))
    return refs


def _glg_html_asset_references_fallback(text: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for match in re.finditer(r"\b(src|href|poster|data)\s*=\s*['\"]([^'\"]+)['\"]", text, re.IGNORECASE):
        refs.append({"source": "html", "tag": "", "attribute": match.group(1).lower(), "url": html_lib.unescape(match.group(2)), "context": ""})
    refs.extend(_glg_css_asset_references(text, context="html"))
    return refs


def _glg_css_asset_references(text: str, context: str = "css") -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", text, re.IGNORECASE | re.DOTALL):
        value = (match.group(2) or "").strip()
        if value:
            refs.append({"source": "css", "tag": "", "attribute": "url", "url": html_lib.unescape(value), "context": context})
    for match in re.finditer(r"@import\s+(?:url\(\s*)?['\"]([^'\")]+)['\"]", text, re.IGNORECASE):
        refs.append({"source": "css", "tag": "", "attribute": "@import", "url": html_lib.unescape(match.group(1)), "context": context})
    return refs


def _glg_split_asset_value(value: str, attr: str) -> list[str]:
    if attr != "srcset":
        return [value.strip()]
    urls: list[str] = []
    for part in value.split(","):
        first = part.strip().split(" ", 1)[0].strip()
        if first:
            urls.append(first)
    return urls


def _glg_tree_root(tree: Any) -> Any:
    root = getattr(tree, "root_node", None)
    return root() if callable(root) else root


def _glg_ts_kind(node: Any) -> str:
    if node is None:
        return ""
    value = getattr(node, "kind", None)
    if callable(value):
        return str(value())
    value = getattr(node, "type", "")
    return str(value() if callable(value) else value)


def _glg_ts_child_count(node: Any) -> int:
    value = getattr(node, "child_count", 0)
    return int(value() if callable(value) else value)


def _glg_ts_child(node: Any, index: int) -> Any:
    child = getattr(node, "child", None)
    return child(index) if callable(child) else None


def _glg_ts_child_by_field(node: Any, field: str) -> Any:
    child = getattr(node, "child_by_field_name", None)
    return child(field) if callable(child) else None


def _glg_ts_parent(node: Any) -> Any:
    parent = getattr(node, "parent", None)
    return parent() if callable(parent) else parent


def _glg_ts_start_byte(node: Any) -> int:
    value = getattr(node, "start_byte", 0)
    return int(value() if callable(value) else value)


def _glg_ts_end_byte(node: Any) -> int:
    value = getattr(node, "end_byte", 0)
    return int(value() if callable(value) else value)


def _glg_ts_start_line(node: Any) -> int:
    point = getattr(node, "start_position", None)
    point = point() if callable(point) else point
    return int(getattr(point, "row", 0)) + 1


def _glg_ts_end_line(node: Any) -> int:
    point = getattr(node, "end_position", None)
    point = point() if callable(point) else point
    return int(getattr(point, "row", 0)) + 1


def _glg_walk_ts(node: Any):
    if node is None:
        return
    yield node
    for index in range(_glg_ts_child_count(node)):
        child = _glg_ts_child(node, index)
        if child is not None:
            yield from _glg_walk_ts(child)


def _glg_node_text(text: str, node: Any) -> str:
    if node is None:
        return ""
    return _glg_slice_by_bytes(text, _glg_ts_start_byte(node), _glg_ts_end_byte(node))


def _glg_slice_by_bytes(text: str, start_byte: int, end_byte: int) -> str:
    data = text.encode("utf-8")
    return data[max(0, start_byte) : max(0, end_byte)].decode("utf-8", errors="replace")


def _glg_enclosing_class_name(text: str, node: Any) -> str:
    current = _glg_ts_parent(node)
    while current is not None:
        if _glg_ts_kind(current) == "class_declaration":
            name_node = _glg_ts_child_by_field(current, "name")
            return _glg_node_text(text, name_node)
        current = _glg_ts_parent(current)
    return ""


def _glg_is_component_candidate(name: str, content: str) -> bool:
    return bool(name and name[0].isupper() and re.search(r"<[A-Za-z][\w.:-]*(\s|>|/>)", content))


def _glg_parse_html_attrs(value: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([:\w-]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>/]+)))?", value):
        key = match.group(1)
        attrs[key] = next((item for item in match.groups()[1:] if item is not None), "")
    return attrs


def _glg_html_symbol_name(tag: str, attrs: dict[str, str]) -> str:
    parts = [tag]
    if attrs.get("id"):
        parts.append(f"#{attrs['id']}")
    classes = ".".join(part for part in str(attrs.get("class") or "").split() if part)
    if classes:
        parts.append(f".{classes}")
    return "".join(parts)


def _glg_strip_css_comments_preserve_lines(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        return "".join("\n" if char == "\n" else " " for char in value)

    return re.sub(r"/\*.*?\*/", replace, text, flags=re.DOTALL)


def _glg_parse_css_rules(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if re.search(r"@[A-Za-z-]+\s+[^{}]*{[^{}]*{", text, re.DOTALL):
        warnings.append("检测到可能的嵌套 at-rule，CSS 解析按普通规则 best-effort 处理。")
    clean = _glg_strip_css_comments_preserve_lines(text)
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
            if name:
                declarations[name] = value.strip()
        if not declarations:
            continue
        selector_start = match.start(1) + (len(match.group(1)) - len(match.group(1).lstrip()))
        start_line = clean.count("\n", 0, selector_start) + 1
        end_line = clean.count("\n", 0, match.end()) + 1
        rules.append(
            {
                "selector": selector_text,
                "selectors": selectors,
                "declarations": declarations,
                "startLine": start_line,
                "endLine": end_line,
                "css": text[selector_start : match.end()].strip(),
            }
        )
    return rules, warnings


def _glg_normalize_css_selector(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _glg_split_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]


def _glg_clip_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _glg_preview(value: str, max_chars: int) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:max_chars]
