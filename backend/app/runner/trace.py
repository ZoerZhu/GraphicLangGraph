from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeType


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: compact_value(value) for key, value in state.items()}


def compact_value(value: Any, string_limit: int = 1200, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        return {str(key): compact_value(child, string_limit=string_limit, list_limit=list_limit) for key, child in value.items()}
    if isinstance(value, list):
        return [compact_value(item, string_limit=string_limit, list_limit=list_limit) for item in value[:list_limit]]
    if isinstance(value, str) and len(value) > string_limit:
        return value[:string_limit] + "...[truncated]"
    return value


def node_trace_item(
    node: Any,
    status: str,
    detail: str,
    duration_ms: float,
    input_state: dict[str, Any],
    output_delta: dict[str, Any],
    **meta: Any,
) -> dict[str, Any]:
    return {
        "nodeId": node.id,
        "type": str(node.type),
        "label": node.label,
        "status": status,
        "detail": detail,
        "durationMs": duration_ms,
        "inputState": compact_state(input_state),
        "outputDelta": compact_state(output_delta),
        **meta,
    }


def runtime_trace_item(label: str, detail: str, input_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodeId": "__runtime__",
        "type": "custom_function",
        "label": label,
        "status": "error",
        "detail": detail,
        "durationMs": 0,
        "inputState": compact_state(input_state),
        "outputDelta": {},
    }


def data_shaping_trace_meta(
    node: Any,
    state: dict[str, Any],
    delta: dict[str, Any],
    *,
    json_object_list,
    resolve_input_mappings,
    truthy,
) -> dict[str, Any]:
    if node.type not in {NodeType.VARIABLE_ASSIGN, NodeType.TEMPLATE, NodeType.JSON_EXTRACTOR, NodeType.JSON_VALIDATOR}:
        return {}
    config = node.config
    kind = {
        NodeType.VARIABLE_ASSIGN: "variable_assign",
        NodeType.TEMPLATE: "template",
        NodeType.JSON_EXTRACTOR: "json_extractor",
        NodeType.JSON_VALIDATOR: "json_validator",
    }[node.type]
    meta: dict[str, Any] = {
        "kind": kind,
        "inputMappings": _trace_input_mappings(config.get("inputMappingsJson"), json_object_list),
    }
    resolved_inputs = _trace_resolved_inputs(config, state, json_object_list, resolve_input_mappings)
    if resolved_inputs:
        meta["resolvedInputs"] = resolved_inputs

    if node.type == NodeType.VARIABLE_ASSIGN:
        result_field = str(config.get("resultField", "assignment_result")).strip() or "assignment_result"
        result = delta.get(result_field)
        meta.update(
            {
                "resultField": result_field,
                "assignments": _trace_assignments(config.get("assignmentsJson"), json_object_list),
                "changedFields": result.get("changedFields", []) if isinstance(result, dict) else [],
            }
        )
    elif node.type == NodeType.TEMPLATE:
        output_field = str(config.get("outputField", "template_result")).strip() or "template_result"
        meta.update(
            {
                "outputField": output_field,
                "outputType": str(config.get("outputType", "text")).strip().lower() or "text",
            }
        )
        if output_field in delta:
            meta["outputPreview"] = compact_value(delta.get(output_field), string_limit=500, list_limit=5)
    else:
        output_field = str(config.get("outputField") or ("extracted_json" if node.type == NodeType.JSON_EXTRACTOR else "validated_json")).strip()
        validation_field = str(config.get("validationField", "validation_result")).strip() or "validation_result"
        repair_field = str(config.get("repairResultField", "repair_result")).strip() or "repair_result"
        validation = _trace_validation(delta.get(validation_field))
        meta.update(
            {
                "outputField": output_field,
                "validationField": validation_field,
                "repairResultField": repair_field,
                "schemaPreset": str(config.get("schemaPreset") or ""),
                "schemaFieldCount": len(json_object_list(config.get("schemaFieldsJson"))),
                "repairEnabled": truthy(config.get("repairEnabled")),
                "validation": validation,
            }
        )
        if validation:
            meta["branch"] = "valid" if validation.get("valid") else "invalid"
        if repair_field in delta:
            meta["repair"] = _trace_repair(delta.get(repair_field))
    return {"dataShaping": meta}


def _trace_input_mappings(value: Any, json_object_list) -> list[dict[str, Any]]:
    mappings = []
    for item in json_object_list(value):
        mappings.append(
            {
                "name": str(item.get("name") or ""),
                "sourceType": str(item.get("sourceType") or item.get("source_type") or "state"),
                "source": str(item.get("source") or ""),
                "valueType": str(item.get("valueType") or item.get("value_type") or "auto"),
                "transform": str(item.get("transform") or "none"),
            }
        )
    return mappings


def _trace_assignments(value: Any, json_object_list) -> list[dict[str, Any]]:
    assignments = []
    for item in json_object_list(value):
        assignments.append(
            {
                "target": str(item.get("target") or item.get("field") or item.get("name") or ""),
                "operation": str(item.get("operation") or "overwrite"),
                "sourceType": str(item.get("sourceType") or item.get("source_type") or "template"),
                "source": str(item.get("source") if item.get("source") is not None else item.get("value") or ""),
                "valueType": str(item.get("valueType") or item.get("value_type") or "auto"),
                "transform": str(item.get("transform") or "none"),
            }
        )
    return assignments


def _trace_resolved_inputs(config: dict[str, Any], state: dict[str, Any], json_object_list, resolve_input_mappings) -> dict[str, Any]:
    if not json_object_list(config.get("inputMappingsJson")):
        return {}
    try:
        return compact_value(resolve_input_mappings(config, state), string_limit=500, list_limit=5)
    except Exception:
        return {}


def _trace_validation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "valid": bool(value.get("valid")),
        "errors": compact_value(value.get("errors") or [], string_limit=500, list_limit=5),
    }


def _trace_repair(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        "ok": bool(value.get("ok")),
        "errors": compact_value(value.get("errors") or [], string_limit=500, list_limit=5),
    }
    validation = value.get("validation")
    if isinstance(validation, dict):
        result["validation"] = _trace_validation(validation)
    return result


def run_status_from_state(trace: list[dict[str, Any]] | list[Any], output_state: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    pending_approval = output_state.get("_glg_pending_approval") if isinstance(output_state, dict) else None
    if output_state.get("_glg_run_status") == "paused" and isinstance(pending_approval, dict):
        return "paused", pending_approval
    if any(_is_fatal_trace_error(item) for item in trace):
        return "failed", None
    return "completed", None


def _is_fatal_trace_error(item: dict[str, Any] | Any) -> bool:
    status = item.get("status") if isinstance(item, dict) else getattr(item, "status", None)
    if status != "error":
        return False
    non_fatal = item.get("nonFatal") if isinstance(item, dict) else getattr(item, "nonFatal", False)
    fatal = item.get("fatal") if isinstance(item, dict) else getattr(item, "fatal", None)
    return not (non_fatal is True or fatal is False)
