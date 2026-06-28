from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..common import compact_value, get_path, json_object_list, set_path
from ..context import ExecutionContext
from ..data_runtime import apply_mapping_transform, coerce_mapped_value, render_transform_args, resolve_input_mappings, resolve_mapping_value


def execute_variable_assign(node: NodeIR, state: dict[str, Any]):
    config = node.config
    assignments = json_object_list(config.get("assignmentsJson"))
    if not assignments:
        assignments = [
            {
                "target": str(config.get("targetField") or "assigned_value"),
                "operation": "overwrite",
                "sourceType": "template",
                "source": str(config.get("value") or "{{ state.messages }}"),
                "valueType": "auto",
            }
        ]
    input_values = resolve_input_mappings(config, state)
    delta: dict[str, Any] = {}
    operations: list[dict[str, Any]] = []
    working = {**state}
    for raw in assignments:
        if not isinstance(raw, dict):
            continue
        target = str(raw.get("target") or raw.get("field") or raw.get("name") or "").strip()
        if not target:
            continue
        operation = str(raw.get("operation") or "overwrite").strip().lower()
        source_type = str(raw.get("sourceType") or raw.get("source_type") or "template").strip().lower()
        source = str(raw.get("source") if raw.get("source") is not None else raw.get("value") if raw.get("value") is not None else "")
        value_type = str(raw.get("valueType") or raw.get("value_type") or "auto")
        transform = str(raw.get("transform") or "none").strip().lower()
        transform_args = render_transform_args(raw.get("transformArgsJson") or raw.get("transform_args_json"), {**working, **delta})
        if source_type == "input":
            value = input_values.get(source)
            value = apply_mapping_transform(value, transform, transform_args, {**working, **delta})
            value = coerce_mapped_value(value, value_type)
        else:
            value = resolve_mapping_value(source_type, source, value_type, {**working, **delta}, transform, transform_args)
        previous = get_path({**working, **delta}, target)
        if operation == "clear":
            next_value = None
        elif operation == "append":
            current = previous if isinstance(previous, list) else ([] if previous in (None, "") else [previous])
            next_value = [*current, *(value if isinstance(value, list) else [value])]
        elif operation == "merge":
            base = previous if isinstance(previous, dict) else {}
            if not isinstance(value, dict):
                raise RuntimeError(f"Variable Assign merge 需要 object 值：{target}")
            next_value = {**base, **value}
        else:
            operation = "overwrite"
            next_value = value
        set_path(delta, target, next_value, {**working, **delta})
        operations.append({"target": target, "operation": operation, "previous": compact_value(previous), "value": compact_value(next_value)})
    result_field = str(config.get("resultField", "assignment_result")).strip() or "assignment_result"
    if result_field:
        delta[result_field] = {
            "ok": True,
            "changedFields": [item["target"] for item in operations],
            "operations": operations,
        }
    return delta, f"Variable Assign 写入 {len(operations)} 个字段"


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_variable_assign(node, state)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_variable_assign(node, state)
