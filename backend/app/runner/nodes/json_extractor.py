from __future__ import annotations

from typing import Any

from app.ir.schemas import NodeIR

from .. import model_runtime
from ..common import render_template, state_value_to_text, truthy
from ..context import ExecutionContext
from ..data_runtime import (
    json_extractor_system_prompt,
    json_schema_from_config,
    parse_json_object_from_text,
    repair_json_output,
    resolve_input_mappings,
    sample_json_from_schema,
    validation_result,
)


def execute_live(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    return execute_json_extractor(node, state, ctx.model_config)


def execute_dry(node: NodeIR, state: dict[str, Any], ctx: ExecutionContext):
    config = node.config
    output_field = str(config.get("outputField", "extracted_json"))
    validation_field = str(config.get("validationField", "validation_result"))
    schema = json_schema_from_config(config)
    output = sample_json_from_schema(schema)
    validation = validation_result(output, schema)
    return {
        output_field: output,
        validation_field: validation,
    }, f"模拟 JSON Extractor 输出到 state.{output_field}"


def execute_json_extractor(node: NodeIR, state: dict[str, Any], model_config: dict[str, Any] | None):
    config = node.config
    output_field = str(config.get("outputField", "extracted_json")).strip() or "extracted_json"
    validation_field = str(config.get("validationField", "validation_result")).strip() or "validation_result"
    repair_field = str(config.get("repairResultField", "repair_result")).strip() or "repair_result"
    schema = json_schema_from_config(config)
    inputs = resolve_input_mappings(config, state)
    input_text = str(config.get("inputText") or "").strip()
    if input_text:
        source_text = render_template(input_text, {**state, **inputs})
    else:
        source_text = state_value_to_text(inputs.get("input") if "input" in inputs else state.get("messages", ""))
    effective_config = model_runtime.effective_model_config(config, model_config)
    provider, model = model_runtime.resolve_node_model(config, model_config, "openai", "gpt-4.1-mini")
    response = model_runtime.call_chat_model(
        provider,
        model,
        [
            ("system", json_extractor_system_prompt(config, schema)),
            ("user", "请从以下输入中抽取结构化 JSON：\n" + source_text),
        ],
        effective_config,
    )
    raw_content = getattr(response, "content", str(response))
    parse_error = ""
    try:
        output = parse_json_object_from_text(raw_content)
    except RuntimeError as exc:
        output = {}
        parse_error = str(exc)
    validation = validation_result(output, schema)
    repair_result: dict[str, Any] | None = None
    if parse_error:
        validation["errors"].insert(0, parse_error)
        validation["valid"] = False
    if not validation["valid"] and truthy(config.get("repairEnabled")):
        repair_result = repair_json_output(
            config,
            output,
            schema,
            validation["errors"],
            source_text,
            provider,
            model,
            effective_config,
            raw_content=raw_content,
        )
        if repair_result.get("ok") and isinstance(repair_result.get("output"), dict):
            output = repair_result["output"]
            validation = repair_result["validation"]
    delta = {
        output_field: output,
        validation_field: validation,
    }
    if repair_result is not None:
        delta[repair_field] = repair_result
    repair_detail = "，已尝试修复" if repair_result is not None else ""
    return delta, f"JSON Extractor 抽取到 state.{output_field}，校验 {'通过' if validation['valid'] else '未通过'}{repair_detail}"
