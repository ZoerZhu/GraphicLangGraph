from __future__ import annotations

import json
import re
from typing import Any

from app.ir.schemas import NodeIR

from ..common import positive_int, state_value_to_text, truthy
from ..context import ExecutionContext


def execute_live_task_splitter(node: NodeIR, state: dict[str, Any]):
    config = node.config
    input_field = str(config.get("inputField", "task_plan")).strip() or "task_plan"
    output_field = str(config.get("outputField", "worker_tasks")).strip() or "worker_tasks"
    max_tasks = min(positive_int(config.get("maxTasks"), 5), 10)
    fallback_enabled = truthy(config.get("fallbackToSingleTask", True))
    value = state.get(input_field)
    tasks = normalize_worker_tasks(value, max_tasks=max_tasks, fallback_goal="")
    if not tasks and fallback_enabled:
        fallback_goal = state_value_to_text(state.get("messages")).strip() or state_value_to_text(value).strip() or "阅读代码并回答用户问题"
        tasks = normalize_worker_tasks([{"goal": fallback_goal}], max_tasks=1, fallback_goal=fallback_goal)
    if not tasks:
        raise RuntimeError(f"Task Splitter 无法从 state.{input_field} 解析出 tasks。")
    return {output_field: tasks}, f"解析并标准化 {len(tasks)} 个 Worker 任务，输出到 state.{output_field}"


def normalize_worker_tasks(value: Any, max_tasks: int, fallback_goal: str = "") -> list[dict[str, Any]]:
    parsed = parse_task_payload(value)
    raw_tasks: Any
    if isinstance(parsed, dict):
        raw_tasks = parsed.get("tasks")
    else:
        raw_tasks = parsed
    if isinstance(raw_tasks, dict):
        raw_tasks = [raw_tasks]
    if not isinstance(raw_tasks, list):
        return []
    tasks: list[dict[str, Any]] = []
    max_tasks = max(1, min(int(max_tasks or 5), 10))
    for index, item in enumerate(raw_tasks[:max_tasks], start=1):
        if isinstance(item, str):
            task = {"goal": item}
        elif isinstance(item, dict):
            task = dict(item)
        else:
            continue
        goal = first_text(task.get("goal"), task.get("description"), task.get("task"), fallback_goal).strip()
        title = first_text(task.get("title"), task.get("name"), goal, f"任务 {index}").strip()
        target_files = normalize_string_list(task.get("targetFiles") if "targetFiles" in task else task.get("target_files"))
        suggested_tools = normalize_string_list(task.get("suggestedTools") if "suggestedTools" in task else task.get("suggested_tools"))
        if not goal and not title:
            continue
        tasks.append(
            {
                "id": str(task.get("id") or f"task_{index}").strip() or f"task_{index}",
                "title": title[:160] or f"任务 {index}",
                "goal": goal or title,
                "targetFiles": target_files,
                "suggestedTools": suggested_tools,
                "status": "pending",
            }
        )
    return tasks


def parse_task_payload(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = state_value_to_text(value).strip()
    if not text:
        return None
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    list_start = text.find("[")
    list_end = text.rfind("]")
    if 0 <= list_start < list_end:
        candidates.append(text[list_start : list_end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in re.split(r"[,，\n]+", text) if item.strip()]


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_live_task_splitter(node, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    field = str(config.get("outputField", "worker_tasks"))
    max_tasks = min(positive_int(config.get("maxTasks"), 5), 10)
    return {
        field: [
            {
                "id": f"task_{index}",
                "title": f"示例子任务 {index}",
                "goal": f"[dry-run] 根据规划结果拆分的第 {index} 个代码阅读任务",
                "targetFiles": [],
                "suggestedTools": [],
                "status": "pending",
            }
            for index in range(1, min(max_tasks, 3) + 1)
        ]
    }, f"模拟拆分 {min(max_tasks, 3)} 个 Worker 任务，输出到 state.{field}"
