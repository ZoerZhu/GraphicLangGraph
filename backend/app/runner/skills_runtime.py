from __future__ import annotations

import json
from typing import Any

SKILL_CORE_RUNTIME_LIMIT = 60_000
SKILL_REFERENCES_RUNTIME_LIMIT = 30_000
SKILL_SUPPORT_FILES_RUNTIME_LIMIT = 12_000


def append_selected_skills(system_prompt: str, selected_skills: list[dict[str, Any]]) -> str:
    if not selected_skills:
        return system_prompt
    sections = ["可用 Skills:"]
    for skill in selected_skills:
        name = str(skill.get("name") or skill.get("id") or "Skill").strip()
        content = skill_runtime_content(skill).strip()
        if content:
            sections.append(f"### {name}\n{content}")
        else:
            sections.append(f"### {name}\n（该 Skill 暂无内容）")
    skill_prompt = "\n\n".join(sections)
    return f"{system_prompt}\n\n{skill_prompt}".strip() if system_prompt else skill_prompt


def skill_runtime_content(skill: dict[str, Any]) -> str:
    content = str(skill.get("content") or "").strip()
    metadata = skill_metadata(skill)
    sections: list[str] = []
    if content:
        sections.append(limit_text(content, SKILL_CORE_RUNTIME_LIMIT, "SKILL.md 内容已截断"))

    package_metadata = metadata.get("packageMetadata") if isinstance(metadata.get("packageMetadata"), dict) else {}
    if package_metadata:
        summary = skill_package_metadata_summary(package_metadata)
        if summary:
            sections.append(f"#### Package Metadata\n{summary}")

    references = metadata.get("relatedMarkdown")
    if isinstance(references, list) and references:
        reference_text = skill_references_runtime_text(references)
        if reference_text:
            sections.append(f"#### Related References\n{reference_text}")

    support_files = metadata.get("supportFiles")
    if isinstance(support_files, list) and support_files:
        support_text = skill_support_files_runtime_text(support_files)
        if support_text:
            sections.append(f"#### Support Files\n{support_text}")

    if metadata.get("relatedMarkdownTruncated"):
        sections.append("注意：部分 reference 文件因数量或长度限制已截断。需要更精确内容时，请使用文件读取工具读取对应路径。")
    return "\n\n".join(sections)


def skill_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    raw = skill.get("metadataJson")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def skill_package_metadata_summary(metadata: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("version", "organization", "technology", "category", "abstract"):
        value = metadata.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    references = metadata.get("references")
    if isinstance(references, list) and references:
        compact = ", ".join(str(item) for item in references[:8] if str(item).strip())
        if compact:
            lines.append(f"- references: {compact}")
    return limit_text("\n".join(lines), 4000, "package metadata 已截断")


def skill_references_runtime_text(references: list[Any]) -> str:
    lines: list[str] = []
    used = 0
    for raw_item in references:
        if not isinstance(raw_item, dict):
            continue
        path = str(raw_item.get("path") or "reference.md")
        title = str(raw_item.get("title") or path)
        content = str(raw_item.get("content") or "").strip()
        if not content:
            continue
        header = f"##### {title} ({path})"
        block = f"{header}\n{content}"
        remaining = SKILL_REFERENCES_RUNTIME_LIMIT - used
        if remaining <= 0:
            break
        block = limit_text(block, remaining, "reference 内容已截断")
        used += len(block)
        lines.append(block)
    return "\n\n".join(lines)


def skill_support_files_runtime_text(files: list[Any]) -> str:
    lines: list[str] = []
    used = 0
    for raw_item in files:
        if not isinstance(raw_item, dict):
            continue
        path = str(raw_item.get("path") or "").strip()
        if not path:
            continue
        kind = str(raw_item.get("kind") or "file")
        size = raw_item.get("size", 0)
        preview = str(raw_item.get("preview") or "").strip()
        line = f"- {kind}: {path} ({size} bytes)"
        if preview:
            line = f"{line}\n  preview:\n{indent_text(limit_text(preview, 1800, 'preview 已截断'), '  ')}"
        remaining = SKILL_SUPPORT_FILES_RUNTIME_LIMIT - used
        if remaining <= 0:
            break
        line = limit_text(line, remaining, "support files 清单已截断")
        used += len(line)
        lines.append(line)
    return "\n".join(lines)


def limit_text(value: str, max_chars: int, note: str) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\n\n[{note}]"


def indent_text(value: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in value.splitlines())
