from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..common import compact_value, get_path, json_object_list, set_path
from ..context import ExecutionContext


def execute_merge(node: NodeIR, state: dict[str, Any], item_states: list[dict[str, Any]]):
    config = node.config
    merge_mode = str(config.get("mergeMode") or "auto").strip().lower() or "auto"
    reducers = json_object_list(config.get("reducersJson"))
    if not reducers:
        reducers = [{"target": "merged_results", "source": "item_result", "reducer": "append"}]
    delta: dict[str, Any] = {}
    summaries: list[dict[str, Any]] = []
    for reducer in reducers:
        target = str(reducer.get("target") or reducer.get("field") or reducer.get("name") or "").strip()
        source = str(reducer.get("source") or reducer.get("sourceField") or "").strip()
        operation = str(reducer.get("reducer") or reducer.get("operation") or "append").strip().lower()
        if not target or not source:
            continue
        values = [get_path(item_state, source) for item_state in item_states]
        previous = get_path({**state, **delta}, target)
        next_value = reduce_values(operation, values, previous, target)
        set_path(delta, target, next_value, {**state, **delta})
        summaries.append(
            {
                "target": target,
                "source": source,
                "reducer": operation,
                "count": len(values),
                "value": compact_value(next_value),
            }
        )
    result_field = str(config.get("resultField", "merge_result")).strip() or "merge_result"
    if result_field:
        delta[result_field] = {
            "ok": True,
            "mergeMode": merge_mode,
            "itemCount": len(item_states),
            "reducers": summaries,
        }
    mode_label = "Branch Merge" if merge_mode == "branch" else "Merge"
    return delta, f"{mode_label} 聚合 {len(item_states)} 项，写入 {len(summaries)} 个字段"


def reduce_values(operation: str, values: list[Any], previous: Any, target: str) -> Any:
    if operation == "concat":
        result: list[Any] = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return result
    if operation == "merge":
        result = dict(previous) if isinstance(previous, dict) else {}
        for value in values:
            if value is None:
                continue
            if not isinstance(value, dict):
                raise RuntimeError(f"Merge reducer merge 需要 object 值：{target}")
            result.update(value)
        return result
    if operation == "overwrite" or operation == "last":
        return values[-1] if values else previous
    if operation == "first":
        for value in values:
            if value is not None:
                return value
        return previous
    return list(values)


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_merge(node, state, [state])


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_merge(node, state, [state])
