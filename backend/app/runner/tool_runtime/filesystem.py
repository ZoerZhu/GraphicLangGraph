from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import engine
from ..common import non_negative_int, optional_positive_int, positive_int, truthy


def read_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("read_file 需要 path 参数。")
    path = resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可读取文件：{path}")
    max_bytes = min(positive_int(args.get("max_bytes", runtime.get("maxFileBytes")), engine._runtime_max_file_bytes(runtime)), engine._runtime_max_file_bytes(runtime))
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    with path.open("rb") as handle:
        content = handle.read(max_bytes + 1)
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes]
    text = content.decode(encoding, errors="replace")
    max_chars = positive_int(args.get("max_chars"), len(text))
    if max_chars < len(text):
        text = text[:max_chars]
        truncated = True
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "truncated": truncated,
        "content": text,
    }


def list_directory(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or ".").strip() or "."
    directory = resolve_runtime_path(raw_path, runtime)
    if not directory.is_dir():
        raise RuntimeError(f"不是可列出的目录：{directory}")
    pattern = str(args.get("pattern") or "*").strip() or "*"
    recursive = truthy(args.get("recursive"))
    max_entries = min(positive_int(args.get("max_entries"), 100), 500)
    iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
    entries: list[dict[str, Any]] = []
    for item in iterator:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if not engine._is_relative_to(resolved, directory):
            continue
        stat = resolved.stat()
        entries.append(
            {
                "name": resolved.name,
                "path": str(resolved),
                "relativePath": resolved.relative_to(directory).as_posix(),
                "type": "directory" if resolved.is_dir() else "file",
                "size": stat.st_size if resolved.is_file() else 0,
            }
        )
        if len(entries) >= max_entries:
            break
    return {
        "path": str(directory),
        "pattern": pattern,
        "recursive": recursive,
        "entries": entries,
        "truncated": len(entries) >= max_entries,
    }


def task_plan(args: dict[str, Any]) -> dict[str, Any]:
    max_tasks = min(positive_int(args.get("maxTasks", args.get("max_tasks", 6)), 6), 10)
    payload = {"tasks": args.get("tasks")}
    from app.runner.nodes.task_splitter import normalize_worker_tasks

    tasks = normalize_worker_tasks(payload, max_tasks=max_tasks, fallback_goal=str(args.get("sourceGoal") or args.get("source_goal") or ""))
    if not tasks:
        raise RuntimeError("task_plan 需要 tasks 数组，且每个任务至少包含 goal、description、task、title 或 name。")
    return {
        "format": "task_splitter_v1",
        "taskCount": len(tasks),
        "tasks": tasks,
    }


def read_file_chunk(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("read_file_chunk 需要 path 参数。")
    path = resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可读取文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"read_file_chunk 只读取文本文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_chars = min(positive_int(args.get("max_chars"), 4000), engine._runtime_max_file_bytes(runtime))
    start_line = optional_positive_int(args.get("start_line", args.get("startLine")))
    end_line = optional_positive_int(args.get("end_line", args.get("endLine")))

    if start_line is not None:
        return read_file_chunk_by_lines(path, start_line, end_line, max_chars, encoding)

    offset = non_negative_int(args.get("offset"), 0)
    text, source_truncated = read_text_limited(path, runtime, encoding)
    total_lines = engine._count_file_lines(path, encoding)
    end = min(len(text), offset + max_chars)
    content = text[offset:end] if offset < len(text) else ""
    truncated = source_truncated or end < len(text)
    start_line_for_offset = text[:offset].count("\n") + 1 if text else 1
    end_line_for_offset = start_line_for_offset + content.count("\n") if content else start_line_for_offset
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "startLine": start_line_for_offset,
        "endLine": end_line_for_offset,
        "totalLines": total_lines,
        "offset": offset,
        "nextOffset": end if truncated and end > offset else None,
        "truncated": truncated,
        "content": content,
    }


def read_file_chunk_by_lines(path: Path, start_line: int, end_line: int | None, max_chars: int, encoding: str) -> dict[str, Any]:
    if end_line is not None and end_line < start_line:
        raise RuntimeError("read_file_chunk 的 end_line 不能小于 start_line。")
    content_parts: list[str] = []
    total_lines = 0
    last_returned_line: int | None = None
    truncated = False
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        for line_no, line in enumerate(handle, start=1):
            total_lines = line_no
            if line_no < start_line:
                continue
            if end_line is not None and line_no > end_line:
                continue
            current_len = sum(len(part) for part in content_parts)
            if current_len + len(line) > max_chars:
                remaining = max_chars - current_len
                if remaining > 0:
                    content_parts.append(line[:remaining])
                    last_returned_line = line_no
                truncated = True
                continue
            content_parts.append(line)
            last_returned_line = line_no
    content = "".join(content_parts)
    if truncated and last_returned_line is not None and last_returned_line < total_lines:
        next_start_line = last_returned_line + 1
    elif end_line is not None and end_line < total_lines:
        next_start_line = end_line + 1
    else:
        next_start_line = None
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "encoding": encoding,
        "startLine": start_line,
        "endLine": last_returned_line,
        "totalLines": total_lines,
        "offset": None,
        "nextOffset": None,
        "nextStartLine": next_start_line,
        "truncated": truncated,
        "content": content,
    }


def search_code(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise RuntimeError("search_code 需要 query 参数。")
    root = resolve_runtime_path(str(args.get("root") or args.get("path") or ".").strip() or ".", runtime)
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    file_glob = str(args.get("file_glob") or args.get("glob") or "*").strip() or "*"
    regex = truthy(args.get("regex"))
    case_sensitive = truthy(args.get("case_sensitive", args.get("caseSensitive")))
    context_lines = min(positive_int(args.get("context_lines", args.get("contextLines")), 0), 8)
    max_results = min(positive_int(args.get("max_results", args.get("limit")), 50), 200)
    pattern = None
    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            raise RuntimeError(f"search_code 正则表达式无效：{exc}") from exc

    matches: list[dict[str, Any]] = []
    scanned_files = 0
    skipped_binary = 0
    for file_path in engine._iter_search_files(root, file_glob):
        if len(matches) >= max_results:
            break
        if engine._is_binary_file(file_path):
            skipped_binary += 1
            continue
        scanned_files += 1
        try:
            text, file_truncated = read_text_limited(file_path, runtime, encoding)
        except OSError:
            continue
        lines = text.splitlines()
        haystack_query = query if case_sensitive else query.lower()
        for index, line in enumerate(lines):
            if pattern:
                match = pattern.search(line)
                if not match:
                    continue
                column = match.start() + 1
            else:
                haystack_line = line if case_sensitive else line.lower()
                found = haystack_line.find(haystack_query)
                if found < 0:
                    continue
                column = found + 1
            matches.append(
                {
                    "path": str(file_path),
                    "relativePath": engine._safe_relative_path(file_path, root),
                    "line": index + 1,
                    "column": column,
                    "text": line,
                    "before": lines[max(0, index - context_lines) : index] if context_lines else [],
                    "after": lines[index + 1 : index + 1 + context_lines] if context_lines else [],
                    "fileTruncated": file_truncated,
                }
            )
            if len(matches) >= max_results:
                break
    return {
        "root": str(root),
        "query": query,
        "regex": regex,
        "fileGlob": file_glob,
        "matches": matches,
        "scannedFiles": scanned_files,
        "skippedBinaryFiles": skipped_binary,
        "truncated": len(matches) >= max_results,
    }


def list_code_symbols(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("list_code_symbols 需要 path 参数。")
    path = resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析文件：{path}")
    if engine._is_binary_file(path):
        return {"path": str(path), "language": "binary", "symbols": [], "warnings": ["疑似二进制文件，已跳过。"]}
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    max_symbols = min(positive_int(args.get("max_symbols", args.get("limit")), 100), 500)
    language = engine._detect_code_language(path, str(args.get("language") or ""))
    text, truncated = read_text_limited(path, runtime, encoding)
    symbols, warnings = engine.glg_semantic_symbols(text, language, max_symbols)
    if truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，符号列表可能不完整。")
    return {
        "path": str(path),
        "language": language,
        "symbols": symbols[:max_symbols],
        "truncated": truncated or len(symbols) > max_symbols,
        "warnings": warnings,
    }


def extract_code_symbol(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    symbol = str(args.get("symbol") or args.get("name") or "").strip()
    if not raw_path:
        raise RuntimeError("extract_code_symbol 需要 path 参数。")
    if not symbol:
        raise RuntimeError("extract_code_symbol 需要 symbol 参数。")
    path = resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"extract_code_symbol 只读取文本代码文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    language = engine._detect_code_language(path, str(args.get("language") or ""))
    max_chars = min(positive_int(args.get("max_chars"), 4000), engine._runtime_max_file_bytes(runtime))
    include_context = truthy(args.get("include_context", args.get("includeContext")))
    text, source_truncated = read_text_limited(path, runtime, encoding)
    result = engine.glg_extract_code_symbol(
        text=text,
        language=language,
        symbol=symbol,
        kind=str(args.get("kind") or "any"),
        max_chars=max_chars,
        include_context=include_context,
    )
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
    result["path"] = str(path)
    result["encoding"] = encoding
    result["warnings"] = warnings
    result["truncated"] = bool(result.get("truncated") or source_truncated)
    result.pop("found", None)
    return result


def chunk_code_semantic(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise RuntimeError("chunk_code_semantic 需要 path 参数。")
    path = resolve_runtime_path(raw_path, runtime)
    if not path.is_file():
        raise RuntimeError(f"不是可分析文件：{path}")
    if engine._is_binary_file(path):
        raise RuntimeError(f"chunk_code_semantic 只读取文本代码文件，疑似二进制文件：{path}")
    encoding = str(args.get("encoding") or "utf-8").strip() or "utf-8"
    language = engine._detect_code_language(path, str(args.get("language") or ""))
    max_chars = min(positive_int(args.get("max_chars"), 4000), engine._runtime_max_file_bytes(runtime))
    max_chunks = min(positive_int(args.get("max_chunks", args.get("limit")), 80), 500)
    include_content = truthy(args.get("include_content", args.get("includeContent")))
    text, source_truncated = read_text_limited(path, runtime, encoding)
    result = engine.glg_chunk_code_semantic(
        text=text,
        language=language,
        max_chars=max_chars,
        max_chunks=max_chunks,
        include_content=include_content,
    )
    warnings = list(result.get("warnings") or [])
    if source_truncated:
        warnings.append("文件内容超过当前运行环境单次读取大小，语义分片可能不完整。")
    result["path"] = str(path)
    result["encoding"] = encoding
    result["truncated"] = bool(result.get("truncated") or source_truncated)
    result["warnings"] = warnings
    return result


def resolve_runtime_path(value: str, runtime: dict[str, Any]) -> Path:
    return engine._resolve_runtime_path(value, runtime)


def read_text_limited(path: Path, runtime: dict[str, Any], encoding: str = "utf-8") -> tuple[str, bool]:
    return engine._read_text_limited(path, runtime, encoding)
