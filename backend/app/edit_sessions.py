from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import EDIT_SESSIONS_DIR, ROOT_DIR, ensure_runtime_dirs
from app.runtime_environment import default_command_profiles


TEXT_BINARY_CHECK_BYTES = 4096


class EditSessionError(RuntimeError):
    pass


def propose_patch(args: dict[str, Any], runtime: dict[str, Any], project_id: str = "") -> dict[str, Any]:
    ensure_runtime_dirs()
    max_patch_bytes = _runtime_int(runtime, "maxPatchBytes", 524_288)
    raw_patch = _first_text(args.get("diff"), args.get("unifiedDiff"), args.get("patch"))
    if raw_patch:
        raw_patch = _strip_code_fence(raw_patch)
        if len(raw_patch.encode("utf-8")) > max_patch_bytes:
            raise EditSessionError(f"patch 超过运行环境限制：{max_patch_bytes} bytes。")
        changes = _parse_unified_diff(raw_patch, runtime)
        diff_text = raw_patch
    else:
        changes = _normalize_structured_changes(args, runtime)
        diff_text = _structured_changes_preview(changes)
        if len(diff_text.encode("utf-8")) > max_patch_bytes:
            raise EditSessionError(f"patch 超过运行环境限制：{max_patch_bytes} bytes。")
    if not changes:
        raise EditSessionError("propose_patch 需要 unified diff，或 path/original/replacement 结构化修改。")

    patch_id = str(args.get("patchId") or f"patch_{uuid4().hex[:12]}")
    project_id = str(args.get("projectId") or project_id or "").strip()
    run_id = str(args.get("runId") or "").strip()
    now = _now()
    files: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for change in changes:
        resolved = _resolve_runtime_path(str(change["path"]), runtime, must_exist=False)
        exists = resolved.exists()
        if exists:
            _ensure_text_file(resolved)
            current_text = _read_text(resolved, str(change.get("encoding") or "utf-8"))
            conflict = _change_conflict(change, current_text)
            if conflict:
                conflicts.append(f"{_display_path(resolved, runtime)}: {conflict}")
        files.append(
            {
                "path": _display_path(resolved, runtime),
                "absolutePath": str(resolved),
                "exists": exists,
                "baseHash": _file_hash(resolved) if exists else "",
                "changeKind": change["kind"],
                "hunkCount": len(change.get("hunks") or []),
                "summary": _change_summary(change),
            }
        )

    session = {
        "patchId": patch_id,
        "projectId": project_id,
        "runId": run_id,
        "status": "blocked" if conflicts else "proposed",
        "files": files,
        "changes": changes,
        "diff": diff_text,
        "conflicts": conflicts,
        "rollbackId": "",
        "createdAt": now,
        "appliedAt": "",
        "discardedAt": "",
        "backups": [],
        "commandResults": [],
    }
    _write_session(session)
    return _session_public(session)


def get_patch_session(patch_id: str) -> dict[str, Any]:
    return _session_public(_read_session(patch_id))


def discard_patch_set(patch_id: str) -> dict[str, Any]:
    session = _read_session(patch_id)
    if session.get("status") == "applied":
        raise EditSessionError("已应用的 patch 不能丢弃，请使用回滚。")
    session["status"] = "discarded"
    session["discardedAt"] = _now()
    _write_session(session)
    return _session_public(session)


def apply_patch_set(patch_id: str, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime = runtime or {}
    session = _read_session(patch_id)
    if session.get("status") == "applied":
        return _session_public(session)
    if session.get("status") not in {"proposed", "blocked"}:
        raise EditSessionError(f"当前 patch 状态不能应用：{session.get('status')}")
    changes = session.get("changes")
    files = session.get("files")
    if not isinstance(changes, list) or not isinstance(files, list):
        raise EditSessionError("patch session 缺少变更内容。")

    planned: list[dict[str, Any]] = []
    for change, file_info in zip(changes, files):
        path = _resolve_runtime_path(str(change["path"]), runtime, must_exist=False)
        expected_hash = str(file_info.get("baseHash") or "")
        exists_before = path.exists()
        current_hash = _file_hash(path) if exists_before else ""
        if current_hash != expected_hash:
            raise EditSessionError(f"文件已变化，拒绝应用过期 patch：{_display_path(path, runtime)}")
        if exists_before:
            _ensure_text_file(path)
            current_text = _read_text(path, str(change.get("encoding") or "utf-8"))
        else:
            current_text = ""
        next_text = _apply_change(change, current_text, exists_before)
        planned.append({"path": path, "beforeExists": exists_before, "beforeText": current_text, "afterText": next_text})

    rollback_id = f"rollback_{uuid4().hex[:12]}"
    backup_dir = EDIT_SESSIONS_DIR / "backups" / rollback_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups: list[dict[str, Any]] = []
    try:
        for index, item in enumerate(planned):
            path: Path = item["path"]
            backup_file = backup_dir / f"{index}.bak"
            if item["beforeExists"]:
                backup_file.write_text(str(item["beforeText"]), encoding="utf-8")
            backups.append(
                {
                    "path": _display_path(path, runtime),
                    "absolutePath": str(path),
                    "existed": bool(item["beforeExists"]),
                    "backupPath": str(backup_file) if item["beforeExists"] else "",
                    "beforeHash": hashlib.sha256(str(item["beforeText"]).encode("utf-8")).hexdigest() if item["beforeExists"] else "",
                }
            )
        for item in planned:
            path = item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(item["afterText"]), encoding="utf-8")
    except Exception:
        _restore_planned(planned)
        raise

    session["status"] = "applied"
    session["rollbackId"] = rollback_id
    session["appliedAt"] = _now()
    session["backups"] = backups
    _write_session(session)
    return _session_public(session)


def rollback_patch_set(rollback_id: str) -> dict[str, Any]:
    session = _read_session_by_rollback(rollback_id)
    if session.get("status") != "applied":
        raise EditSessionError("只有已应用的 patch 可以回滚。")
    backups = session.get("backups")
    if not isinstance(backups, list):
        raise EditSessionError("patch session 缺少回滚备份。")
    for backup in backups:
        path = Path(str(backup.get("absolutePath") or ""))
        if not path:
            continue
        if backup.get("existed"):
            backup_path = Path(str(backup.get("backupPath") or ""))
            if not backup_path.exists():
                raise EditSessionError(f"回滚备份不存在：{backup_path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        elif path.exists():
            path.unlink()
    session["status"] = "rolled_back"
    session["rolledBackAt"] = _now()
    _write_session(session)
    return _session_public(session)


def replace_in_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    _require_direct_edits(runtime)
    path = str(args.get("path") or "").strip()
    search = str(args.get("search") or "")
    replacement = str(args.get("replace") if "replace" in args else args.get("replacement") or "")
    if not path or not search:
        raise EditSessionError("replace_in_file 需要 path 和 search。")
    expected = args.get("expectedOccurrences")
    patch = propose_patch(
        {
            "projectId": args.get("projectId", ""),
            "path": path,
            "original": search,
            "replacement": replacement,
            "expectedOccurrences": expected if expected is not None else 1,
        },
        runtime,
    )
    if patch.get("conflicts"):
        raise EditSessionError("替换内容校验失败：" + "；".join(str(item) for item in patch["conflicts"]))
    return apply_patch_set(str(patch["patchId"]), runtime)


def write_file(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    _require_direct_edits(runtime)
    path = str(args.get("path") or "").strip()
    content = str(args.get("content") if "content" in args else "")
    overwrite = bool(args.get("overwrite", False))
    if not path:
        raise EditSessionError("write_file 需要 path。")
    patch = propose_patch(
        {
            "projectId": args.get("projectId", ""),
            "changes": [{"path": path, "content": content, "overwrite": overwrite, "kind": "write"}],
        },
        runtime,
    )
    if patch.get("conflicts"):
        raise EditSessionError("写入内容校验失败：" + "；".join(str(item) for item in patch["conflicts"]))
    return apply_patch_set(str(patch["patchId"]), runtime)


def run_whitelisted_command(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    command_value = args.get("command")
    command = _normalize_command(command_value)
    if not command:
        raise EditSessionError("run_whitelisted_command 需要 command。")
    _ensure_command_allowed(command, runtime)
    cwd_value = str(args.get("cwd") or ".")
    cwd = _resolve_runtime_path(cwd_value, runtime, must_exist=True)
    if not cwd.is_dir():
        cwd = cwd.parent
    timeout = max(1, min(int(args.get("timeoutSeconds") or 60), 300))
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        duration = round((time.perf_counter() - started) * 1000, 2)
        stdout, stdout_truncated = _clip_output(exc.stdout or "", runtime)
        stderr, stderr_truncated = _clip_output(exc.stderr or f"命令超时：{timeout}s", runtime)
        return {
            "command": command,
            "cwd": str(cwd),
            "exitCode": -1,
            "stdout": stdout,
            "stderr": stderr,
            "durationMs": duration,
            "timedOut": True,
            "truncated": stdout_truncated or stderr_truncated,
        }
    duration = round((time.perf_counter() - started) * 1000, 2)
    stdout, stdout_truncated = _clip_output(completed.stdout, runtime)
    stderr, stderr_truncated = _clip_output(completed.stderr, runtime)
    return {
        "command": command,
        "cwd": str(cwd),
        "exitCode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "durationMs": duration,
        "timedOut": timed_out,
        "truncated": stdout_truncated or stderr_truncated,
    }


def _normalize_structured_changes(args: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    raw_changes = args.get("changes")
    if raw_changes is None:
        raw_changes = [args] if args.get("path") else []
    if isinstance(raw_changes, dict):
        raw_changes = [raw_changes]
    if not isinstance(raw_changes, list):
        return []
    changes: list[dict[str, Any]] = []
    for item in raw_changes:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        if item.get("kind") == "write" or "content" in item:
            resolved = _resolve_runtime_path(path, runtime, must_exist=False)
            changes.append(
                {
                    "kind": "write",
                    "path": _display_path(resolved, runtime),
                    "content": str(item.get("content") if "content" in item else ""),
                    "overwrite": bool(item.get("overwrite", False)),
                    "encoding": str(item.get("encoding") or "utf-8"),
                }
            )
            continue
        original = str(item.get("original") if "original" in item else item.get("search") or "")
        replacement = str(item.get("replacement") if "replacement" in item else item.get("replace") or "")
        if not original:
            continue
        resolved = _resolve_runtime_path(path, runtime, must_exist=True)
        changes.append(
            {
                "kind": "replace",
                "path": _display_path(resolved, runtime),
                "original": original,
                "replacement": replacement,
                "expectedOccurrences": item.get("expectedOccurrences"),
                "encoding": str(item.get("encoding") or "utf-8"),
            }
        )
    return changes


def _parse_unified_diff(diff_text: str, runtime: dict[str, Any]) -> list[dict[str, Any]]:
    lines = diff_text.replace("\r\n", "\n").split("\n")
    changes: list[dict[str, Any]] = []
    index = 0
    current_old = ""
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            current_old = _diff_path(line[4:].strip())
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                continue
            new_path = _diff_path(lines[index][4:].strip())
            path = new_path if new_path != "/dev/null" else current_old
            if not path or path == "/dev/null":
                index += 1
                continue
            resolved = _resolve_runtime_path(path, runtime, must_exist=False)
            hunks: list[dict[str, Any]] = []
            index += 1
            while index < len(lines):
                header = lines[index]
                if header.startswith("--- ") or header.startswith("diff --git "):
                    break
                if not header.startswith("@@"):
                    index += 1
                    continue
                match = re.match(r"@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", header)
                if not match:
                    raise EditSessionError(f"无法解析 unified diff hunk：{header}")
                old_start = int(match.group(1))
                old_count = int(match.group(2) or "1")
                new_start = int(match.group(3))
                new_count = int(match.group(4) or "1")
                hunk_lines: list[str] = []
                index += 1
                while index < len(lines):
                    item = lines[index]
                    if item.startswith("@@") or item.startswith("--- ") or item.startswith("diff --git "):
                        break
                    if item.startswith("\\ No newline"):
                        index += 1
                        continue
                    if item == "":
                        hunk_lines.append(" ")
                    elif item[0] in {" ", "-", "+"}:
                        hunk_lines.append(item)
                    else:
                        hunk_lines.append(" " + item)
                    index += 1
                hunks.append(
                    {
                        "oldStart": old_start,
                        "oldCount": old_count,
                        "newStart": new_start,
                        "newCount": new_count,
                        "lines": hunk_lines,
                    }
                )
            changes.append({"kind": "unified", "path": _display_path(resolved, runtime), "hunks": hunks, "encoding": "utf-8"})
            continue
        index += 1
    return changes


def _apply_change(change: dict[str, Any], current_text: str, exists_before: bool) -> str:
    kind = str(change.get("kind") or "")
    if kind == "replace":
        original = str(change.get("original") or "")
        replacement = str(change.get("replacement") or "")
        expected = change.get("expectedOccurrences")
        count = current_text.count(original)
        if expected is not None and count != int(expected):
            raise EditSessionError(f"替换命中次数不符合预期：expected={expected}, actual={count}")
        if expected is None and count != 1:
            raise EditSessionError(f"替换默认要求唯一命中，实际命中 {count} 次。")
        return current_text.replace(original, replacement)
    if kind == "write":
        if exists_before and not bool(change.get("overwrite", False)):
            raise EditSessionError("write_file 默认不覆盖已有文件，请设置 overwrite=true。")
        return str(change.get("content") if "content" in change else "")
    if kind == "unified":
        return _apply_unified_hunks(current_text, change.get("hunks") if isinstance(change.get("hunks"), list) else [])
    raise EditSessionError(f"未知变更类型：{kind}")


def _apply_unified_hunks(current_text: str, hunks: list[dict[str, Any]]) -> str:
    had_final_newline = current_text.endswith("\n")
    source = current_text.splitlines()
    output: list[str] = []
    source_index = 0
    line_offset = 0
    for hunk in hunks:
        old_start = int(hunk.get("oldStart") or 1)
        old_count = int(hunk.get("oldCount") or 0)
        target = 0 if old_count == 0 and old_start == 0 else max(0, old_start - 1 + line_offset)
        if target < source_index:
            raise EditSessionError("patch hunk 顺序冲突。")
        output.extend(source[source_index:target])
        cursor = target
        for raw_line in hunk.get("lines") or []:
            line = str(raw_line)
            prefix = line[:1]
            text = line[1:] if line else ""
            if prefix == " ":
                if cursor >= len(source) or source[cursor] != text:
                    raise EditSessionError(f"patch 上下文不匹配：{text[:80]}")
                output.append(source[cursor])
                cursor += 1
            elif prefix == "-":
                if cursor >= len(source) or source[cursor] != text:
                    raise EditSessionError(f"patch 删除行不匹配：{text[:80]}")
                cursor += 1
                line_offset -= 1
            elif prefix == "+":
                output.append(text)
                line_offset += 1
        source_index = cursor
    output.extend(source[source_index:])
    result = "\n".join(output)
    if had_final_newline or result:
        result += "\n"
    return result


def _change_conflict(change: dict[str, Any], current_text: str) -> str:
    kind = str(change.get("kind") or "")
    if kind == "replace":
        original = str(change.get("original") or "")
        expected = change.get("expectedOccurrences")
        count = current_text.count(original)
        if expected is not None and count != int(expected):
            return f"替换命中次数不符合预期：expected={expected}, actual={count}"
        if expected is None and count != 1:
            return f"替换默认要求唯一命中，实际命中 {count} 次"
    if kind == "write" and not bool(change.get("overwrite", False)):
        return "目标文件已存在，write_file 默认不覆盖"
    if kind == "unified":
        try:
            _apply_unified_hunks(current_text, change.get("hunks") if isinstance(change.get("hunks"), list) else [])
        except Exception as exc:
            return str(exc)
    return ""


def _change_summary(change: dict[str, Any]) -> str:
    kind = str(change.get("kind") or "")
    if kind == "replace":
        return f"替换 {len(str(change.get('original') or ''))} 字符为 {len(str(change.get('replacement') or ''))} 字符"
    if kind == "write":
        return f"写入 {len(str(change.get('content') or ''))} 字符"
    if kind == "unified":
        return f"{len(change.get('hunks') or [])} 个 diff hunk"
    return kind


def _structured_changes_preview(changes: list[dict[str, Any]]) -> str:
    return json.dumps([{key: value for key, value in item.items() if key != "content"} for item in changes], ensure_ascii=False, indent=2)


def _write_session(session: dict[str, Any]) -> None:
    path = _session_path(str(session["patchId"]))
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_session(patch_id: str) -> dict[str, Any]:
    path = _session_path(patch_id)
    if not path.exists():
        raise EditSessionError(f"patch session 不存在：{patch_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_session_by_rollback(rollback_id: str) -> dict[str, Any]:
    for path in EDIT_SESSIONS_DIR.glob("patch_*.json"):
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if session.get("rollbackId") == rollback_id:
            return session
    raise EditSessionError(f"rollback session 不存在：{rollback_id}")


def _session_path(patch_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", patch_id).strip("_")
    if not safe:
        raise EditSessionError("patchId 无效。")
    return EDIT_SESSIONS_DIR / f"{safe}.json"


def _session_public(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "patchId": session.get("patchId", ""),
        "projectId": session.get("projectId", ""),
        "runId": session.get("runId", ""),
        "status": session.get("status", ""),
        "files": session.get("files", []),
        "diff": session.get("diff", ""),
        "conflicts": session.get("conflicts", []),
        "rollbackId": session.get("rollbackId", ""),
        "createdAt": session.get("createdAt", ""),
        "appliedAt": session.get("appliedAt", ""),
        "discardedAt": session.get("discardedAt", ""),
        "rolledBackAt": session.get("rolledBackAt", ""),
        "commandResults": session.get("commandResults", []),
    }


def _resolve_runtime_path(value: str, runtime: dict[str, Any], must_exist: bool = False) -> Path:
    raw_path = Path(value).expanduser()
    roots = _runtime_allowed_roots(runtime)
    candidates = [raw_path] if raw_path.is_absolute() else [ROOT_DIR / raw_path, *(root / raw_path for root in roots)]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if any(_is_relative_to(resolved, root) for root in roots):
            if must_exist and not resolved.exists():
                continue
            return resolved
    root_text = "；".join(str(root) for root in roots)
    raise EditSessionError(f"路径不在当前运行环境允许目录内：{value}。允许目录：{root_text}")


def _runtime_allowed_roots(runtime: dict[str, Any]) -> list[Path]:
    roots = _json_string_list(runtime.get("allowedRootsJson"))
    if not roots:
        env_roots = os.getenv("GLG_FILE_TOOL_ROOTS", "")
        roots = [item.strip() for item in re.split(r"[;\n]+", env_roots) if item.strip()]
    if not roots:
        roots = [str(ROOT_DIR)]
    result: list[Path] = []
    for item in roots:
        try:
            result.append(Path(item).expanduser().resolve())
        except OSError:
            continue
    return result or [ROOT_DIR.resolve()]


def _display_path(path: Path, runtime: dict[str, Any]) -> str:
    for root in _runtime_allowed_roots(runtime):
        if _is_relative_to(path, root):
            try:
                return str(path.relative_to(root)).replace("\\", "/") or "."
            except ValueError:
                continue
    return str(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _ensure_text_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    with path.open("rb") as handle:
        sample = handle.read(TEXT_BINARY_CHECK_BYTES)
    if b"\x00" in sample:
        raise EditSessionError(f"拒绝编辑疑似二进制文件：{path}")


def _read_text(path: Path, encoding: str = "utf-8") -> str:
    _ensure_text_file(path)
    return path.read_text(encoding=encoding or "utf-8", errors="replace")


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _restore_planned(planned: list[dict[str, Any]]) -> None:
    for item in planned:
        path: Path = item["path"]
        try:
            if item["beforeExists"]:
                path.write_text(str(item["beforeText"]), encoding="utf-8")
            elif path.exists():
                path.unlink()
        except Exception:
            continue


def _normalize_command(command_value: Any) -> list[str]:
    if isinstance(command_value, list):
        return [str(item) for item in command_value if str(item).strip()]
    text = str(command_value or "").strip()
    if not text:
        return []
    return shlex.split(text)


def _ensure_command_allowed(command: list[str], runtime: dict[str, Any]) -> None:
    profiles = _json_string_list(runtime.get("allowedCommandProfilesJson")) or default_command_profiles()
    normalized = _command_text(command).lower()
    for profile in profiles:
        allowed = str(profile).strip().lower()
        if not allowed:
            continue
        if normalized == allowed or normalized.startswith(allowed + " "):
            return
    raise EditSessionError(f"命令不在白名单内：{_command_text(command)}")


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _clip_output(value: Any, runtime: dict[str, Any]) -> tuple[str, bool]:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    max_bytes = _runtime_int(runtime, "maxCommandOutputBytes", 262_144)
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    clipped = raw[:max_bytes].decode("utf-8", errors="replace")
    return clipped, True


def _require_direct_edits(runtime: dict[str, Any]) -> None:
    if runtime.get("allowDirectEdits") is True or os.getenv("GLG_ALLOW_DIRECT_EDITS", "").lower() in {"1", "true", "yes"}:
        return
    raise EditSessionError("当前运行环境未开启 allowDirectEdits，拒绝直接写入。")


def _runtime_int(runtime: dict[str, Any], key: str, fallback: int) -> int:
    try:
        value = int(runtime.get(key) or fallback)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.replace(";", "\n").replace(",", "\n").splitlines() if item.strip()]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _diff_path(value: str) -> str:
    text = value.split("\t", 1)[0].split(" ", 1)[0].strip()
    if text in {"", "/dev/null"}:
        return "/dev/null"
    if text.startswith("a/") or text.startswith("b/"):
        return text[2:]
    return text


def _strip_code_fence(value: str) -> str:
    text = value.strip()
    match = re.search(r"```(?:diff|patch)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
