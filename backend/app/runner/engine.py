from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeType, ProjectIR
from app.runner.context import ModelRuntimeConfig, RunMode
from app.runner.data_runtime import collect_value_paths as _collect_value_paths
from app.runner.data_runtime import declared_output_fields_for_node as _declared_output_fields_for_node
from app.runner.data_runtime import resolve_input_mappings as _resolve_input_mappings
from app.runner.trace import compact_value as _compact_value
from app.runner.walk_runtime import (
    iter_project_preview_events,
    normalize_input as _normalize_input,
    resume_project_preview,
    run_project_preview,
)

_PATH_VALUE_MISSING = object()


def collect_data_shaping_paths(
    project: ProjectIR,
    state: dict[str, Any] | None = None,
    run_record: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    paths: dict[str, dict[str, Any]] = {}

    def add(path: str, value_type: str, source: str, label: str = "", value: Any = _PATH_VALUE_MISSING) -> None:
        if not path:
            return
        item = paths.setdefault(
            path,
            {
                "path": path,
                "type": value_type or "Any",
                "source": source,
                "label": label or path,
            },
        )
        if value is not _PATH_VALUE_MISSING and "value" not in item:
            item["value"] = _compact_value(value)

    for field in getattr(project.state, "fields", []) or []:
        add(field.name, field.type, "state", field.description or field.name)

    for node in project.nodes:
        for path, value_type in _declared_output_fields_for_node(node):
            add(path, value_type, "node", f"{node.label} 输出")

    runtime_states: list[tuple[str, dict[str, Any]]] = []
    if isinstance(state, dict):
        runtime_states.append(("input", state))
    if isinstance(run_record, dict):
        result = run_record.get("result") if isinstance(run_record.get("result"), dict) else {}
        output_state = result.get("outputState") if isinstance(result.get("outputState"), dict) else {}
        if output_state:
            runtime_states.append(("run_output", output_state))
        for trace_item in result.get("trace") or []:
            if not isinstance(trace_item, dict):
                continue
            output_delta = trace_item.get("outputDelta")
            if isinstance(output_delta, dict):
                runtime_states.append((f"trace:{trace_item.get('nodeId') or ''}", output_delta))

    for source, runtime_state in runtime_states:
        for item in _collect_value_paths(runtime_state):
            add(
                str(item["path"]),
                str(item["type"]),
                source,
                str(item.get("label") or item["path"]),
                item.get("value", _PATH_VALUE_MISSING),
            )

    return sorted(paths.values(), key=lambda item: (item["path"].count("."), item["path"]))


def preview_data_shaping_node(
    project: ProjectIR,
    node_id: str,
    state: dict[str, Any] | None = None,
    model_config: ModelRuntimeConfig = None,
) -> dict[str, Any]:
    node = next((item for item in project.nodes if item.id == node_id), None)
    if node is None:
        return {"ok": False, "nodeId": node_id, "errors": ["Node not found"]}
    working_state = _normalize_input(state or {})
    result: dict[str, Any] = {
        "ok": True,
        "nodeId": node.id,
        "nodeType": str(node.type),
        "inputs": {},
        "delta": {},
        "validation": None,
        "repair": None,
        "detail": "",
        "errors": [],
    }
    try:
        result["inputs"] = _resolve_input_mappings(node.config, working_state)
        if node.type == NodeType.VARIABLE_ASSIGN:
            from app.runner.nodes.variable_assign import execute_variable_assign

            delta, detail = execute_variable_assign(node, working_state)
        elif node.type == NodeType.TEMPLATE:
            from app.runner.nodes.template import execute_template_node

            delta, detail = execute_template_node(node, working_state)
        elif node.type == NodeType.JSON_EXTRACTOR:
            from app.runner.nodes.json_extractor import execute_json_extractor

            delta, detail = execute_json_extractor(node, working_state, model_config)
        elif node.type == NodeType.JSON_VALIDATOR:
            from app.runner.nodes.json_validator import execute_json_validator

            delta, detail = execute_json_validator(node, working_state, model_config, allow_repair=True)
        else:
            raise RuntimeError("只支持预览 Variable Assign、Template、JSON Extractor、JSON Validator。")
        validation_field = str(node.config.get("validationField", "validation_result"))
        repair_field = str(node.config.get("repairResultField", "repair_result"))
        result.update(
            {
                "delta": delta,
                "validation": delta.get(validation_field),
                "repair": delta.get(repair_field),
                "detail": detail,
            }
        )
    except Exception as exc:
        result["ok"] = False
        result["errors"] = [str(exc)]
    return result


__all__ = [
    "RunMode",
    "collect_data_shaping_paths",
    "iter_project_preview_events",
    "preview_data_shaping_node",
    "resume_project_preview",
    "run_project_preview",
]
