from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from ..common import get_path, state_value_to_text, truthy
from ..context import ExecutionContext
from ..data_runtime import json_schema_from_config, repair_json_output, validation_result
from ..model_runtime import effective_model_config, resolve_node_model


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_json_validator(node, state, ctx.model_config, allow_repair=True)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    delta, detail = execute_json_validator(node, state)
    return delta, f"[dry-run] {detail}"


def execute_json_validator(
    node: NodeIR,
    state: dict[str, Any],
    model_config: dict[str, Any] | None = None,
    allow_repair: bool = False,
):
    config = node.config
    input_field = str(config.get("inputField", "extracted_json")).strip() or "extracted_json"
    output_field = str(config.get("outputField", "validated_json")).strip() or "validated_json"
    validation_field = str(config.get("validationField", "validation_result")).strip() or "validation_result"
    repair_field = str(config.get("repairResultField", "repair_result")).strip() or "repair_result"
    schema = json_schema_from_config(config)
    value = get_path(state, input_field)
    validation = validation_result(value, schema)
    repair_result: dict[str, Any] | None = None
    if allow_repair and not validation["valid"] and truthy(config.get("repairEnabled")):
        effective_config = effective_model_config(config, model_config)
        provider, model = resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
        repair_result = repair_json_output(
            config,
            value,
            schema,
            validation["errors"],
            state_value_to_text(state.get("messages", "")),
            provider,
            model,
            effective_config,
        )
        if repair_result.get("ok") and isinstance(repair_result.get("output"), dict):
            value = repair_result["output"]
            validation = repair_result["validation"]
    delta = {
        output_field: value,
        validation_field: validation,
    }
    if repair_result is not None:
        delta[repair_field] = repair_result
    repair_detail = "，已尝试修复" if repair_result is not None else ""
    return delta, f"JSON Validator 校验 state.{input_field}，结果 {'valid' if validation['valid'] else 'invalid'}{repair_detail}"
