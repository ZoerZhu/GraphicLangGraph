from __future__ import annotations

import json
import re
from typing import Any

from app.ir.schemas import NodeIR, NodeType
from app.runner.trace import compact_value


TEMPLATE_RE = re.compile(r"{{\s*state\.([a-zA-Z_][a-zA-Z0-9_\.\[\]]*)\s*}}")
_MISSING = object()


def render_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        return state_value_to_text(get_path(state, match.group(1), ""))

    return TEMPLATE_RE.sub(replace, template)


def state_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and "content" in item:
                parts.append(str(item["content"]))
            else:
                parts.append(state_value_to_text(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def json_object_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return _flatten_json_object_list(value)
    if isinstance(value, dict):
        return [value]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    return _flatten_json_object_list(parsed) if isinstance(parsed, list) else []


def _flatten_json_object_list(value: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, list):
            result.extend(_flatten_json_object_list(item))
    return result


def declared_output_fields_for_node(node: NodeIR) -> list[tuple[str, str]]:
    config = node.config
    if node.type == NodeType.VARIABLE_ASSIGN:
        fields = [(str(config.get("resultField") or "assignment_result"), "dict")]
        for assignment in json_object_list(config.get("assignmentsJson")):
            target = str(assignment.get("target") or assignment.get("field") or assignment.get("name") or "").strip()
            if target:
                fields.append((target, "Any"))
        return fields
    if node.type == NodeType.TEMPLATE:
        output_type = str(config.get("outputType") or "text")
        return [(str(config.get("outputField") or "template_result"), "dict" if output_type == "json" else "str")]
    if node.type == NodeType.JSON_EXTRACTOR:
        return [
            (str(config.get("outputField") or "extracted_json"), "dict"),
            (str(config.get("validationField") or "validation_result"), "dict"),
            (str(config.get("repairResultField") or "repair_result"), "dict"),
        ]
    if node.type == NodeType.JSON_VALIDATOR:
        return [
            (str(config.get("outputField") or "validated_json"), "dict"),
            (str(config.get("validationField") or "validation_result"), "dict"),
            (str(config.get("repairResultField") or "repair_result"), "dict"),
        ]
    output_field = str(config.get("outputField") or "").strip()
    return [(output_field, "Any")] if output_field else []


def collect_value_paths(value: Any, prefix: str = "", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 6:
        return []
    result: list[dict[str, Any]] = []
    if prefix:
        result.append({"path": prefix, "type": _value_type_name(value), "label": prefix, "value": compact_value(value)})
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            result.extend(collect_value_paths(child, child_path, depth + 1))
    elif isinstance(value, list) and value:
        result.extend(collect_value_paths(value[0], f"{prefix}.0" if prefix else "0", depth + 1))
        if prefix:
            wildcard_base = f"{prefix}[]"
            result.append({"path": wildcard_base, "type": "list", "label": wildcard_base, "value": compact_value(value)})
            sample = value[0]
            if isinstance(sample, dict):
                for key, child in sample.items():
                    result.extend(collect_value_paths(child, f"{wildcard_base}.{key}", depth + 1))
            else:
                result.extend(collect_value_paths(sample, wildcard_base, depth + 1))
    return result


def _value_type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "None"
    return "str"


def resolve_input_mappings(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for mapping in json_object_list(config.get("inputMappingsJson")):
        name = str(mapping.get("name") or "").strip()
        if not name:
            continue
        result[name] = _resolve_mapping_entry(mapping, state)
    return result


def _resolve_mapping_entry(mapping: dict[str, Any], state: dict[str, Any]) -> Any:
    source_type = str(mapping.get("sourceType") or mapping.get("source_type") or "state").strip().lower()
    source = str(mapping.get("source") or "")
    value_type = str(mapping.get("valueType") or mapping.get("value_type") or "auto")
    transform = str(mapping.get("transform") or "none").strip().lower()
    transform_args = render_transform_args(mapping.get("transformArgsJson") or mapping.get("transform_args_json"), state)
    return resolve_mapping_value(source_type, source, value_type, state, transform, transform_args)


def resolve_mapping_value(
    source_type: str,
    source: str,
    value_type: str,
    state: dict[str, Any],
    transform: str = "none",
    transform_args: dict[str, Any] | None = None,
) -> Any:
    if source_type == "state":
        value = get_path(state, source)
    elif source_type == "literal":
        value = source
    elif source_type == "json":
        rendered = render_template(source, state)
        try:
            value = json.loads(rendered)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"输入映射 JSON 解析失败：{exc}") from exc
    else:
        value = render_template(source, state)
    value = apply_mapping_transform(value, transform, transform_args or {}, state)
    return coerce_mapped_value(value, value_type)


def render_transform_args(value: Any, state: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    rendered = render_template(text, state)
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Transform 参数 JSON 解析失败：{exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Transform 参数必须是 JSON object。")
    return parsed


def apply_mapping_transform(value: Any, transform: str, args: dict[str, Any], state: dict[str, Any]) -> Any:
    kind = str(transform or "none").strip().lower()
    if kind in {"", "none"}:
        return value
    if kind == "default":
        return _resolve_transform_value(args.get("value", args.get("default")), state) if _is_empty_value(value) else value
    if kind == "coalesce":
        candidates = [value]
        raw_candidates = args.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raw_candidates = [raw_candidates]
        candidates.extend(_resolve_transform_value(candidate, state) for candidate in raw_candidates)
        for candidate in candidates:
            if not _is_empty_value(candidate):
                return candidate
        return None
    if kind == "split":
        separator = str(args.get("separator", "\n"))
        text = state_value_to_text(value)
        parts = text.split(separator) if separator else list(text)
        if truthy(args.get("trim", True)):
            parts = [part.strip() for part in parts]
        if truthy(args.get("dropEmpty", args.get("drop_empty", True))):
            parts = [part for part in parts if part != ""]
        return parts
    if kind == "join":
        separator = str(args.get("separator", "\n"))
        values = value if isinstance(value, list) else ([] if value is None else [value])
        return separator.join(state_value_to_text(item) for item in values)
    if kind == "pick":
        from app.runner.nodes.task_splitter import normalize_string_list

        paths = normalize_string_list(args.get("paths") or args.get("fields"))
        return _pick_paths(value, paths)
    if kind == "omit":
        from app.runner.nodes.task_splitter import normalize_string_list

        paths = normalize_string_list(args.get("paths") or args.get("fields"))
        return _omit_paths(value, paths)
    raise RuntimeError(f"不支持的 Transform：{transform}")


def _resolve_transform_value(value: Any, state: dict[str, Any]) -> Any:
    if isinstance(value, dict) and ("sourceType" in value or "source" in value):
        return _resolve_mapping_entry(value, state)
    if isinstance(value, str):
        return render_template(value, state)
    return value


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def coerce_mapped_value(value: Any, value_type: str) -> Any:
    kind = str(value_type or "auto").strip().lower()
    if kind in {"", "auto", "any"}:
        return value
    if kind == "string":
        return state_value_to_text(value)
    if kind == "number":
        return float(value)
    if kind == "integer":
        return int(value)
    if kind == "boolean":
        return truthy(value)
    if kind == "json":
        if isinstance(value, (dict, list)):
            return value
        return json.loads(str(value or "null"))
    return value


def get_path(value: Any, path: str, default: Any = None) -> Any:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return value
    resolved = _get_path_parts(value, parts)
    return default if resolved is _MISSING else resolved


def _get_path_parts(value: Any, parts: list[str]) -> Any:
    if not parts:
        return value
    part = parts[0]
    if part.endswith("[]"):
        key = part[:-2]
        collection = _get_path_part(value, key) if key else value
        if not isinstance(collection, list):
            return []
        values: list[Any] = []
        for item in collection:
            child = _get_path_parts(item, parts[1:])
            if child is _MISSING:
                continue
            if isinstance(child, list):
                values.extend(child)
            else:
                values.append(child)
        return values
    next_value = _get_path_part(value, part)
    if next_value is _MISSING:
        return _MISSING
    return _get_path_parts(next_value, parts[1:])


def _get_path_part(value: Any, part: str) -> Any:
    if part == "":
        return value
    if isinstance(value, dict):
        return value.get(part, _MISSING)
    if isinstance(value, list) and part.isdigit():
        index = int(part)
        return value[index] if 0 <= index < len(value) else _MISSING
    return _MISSING


def set_path(target: dict[str, Any], path: str, value: Any, base: dict[str, Any] | None = None) -> None:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return
    if any(part.endswith("[]") for part in parts):
        raise RuntimeError(f"写入路径不支持数组通配：{path}")
    if len(parts) == 1:
        target[parts[0]] = value
        return
    first = parts[0]
    if first not in target:
        existing = (base or {}).get(first)
        target[first] = dict(existing) if isinstance(existing, dict) else {}
    current = target[first]
    if not isinstance(current, dict):
        current = {}
        target[first] = current
    for part in parts[1:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _pick_paths(value: Any, paths: list[str]) -> Any:
    if not paths:
        return value
    result: dict[str, Any] = {}
    for path in paths:
        picked = get_path(value, path, _MISSING)
        if picked is _MISSING:
            continue
        set_path(result, path.replace("[].", "."), picked)
    return result


def _omit_paths(value: Any, paths: list[str]) -> Any:
    try:
        result = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return value
    for path in paths:
        _delete_path(result, path)
    return result


def _delete_path(value: Any, path: str) -> None:
    parts = [item for item in str(path or "").split(".") if item]
    if not parts:
        return
    current = value
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return
    leaf = parts[-1]
    if isinstance(current, dict):
        current.pop(leaf, None)
    elif isinstance(current, list) and leaf.isdigit():
        index = int(leaf)
        if 0 <= index < len(current):
            current.pop(index)


def json_schema_from_config(config: dict[str, Any]) -> dict[str, Any]:
    preset = str(config.get("schemaPreset") or "").strip()
    if preset == "task_plan_v1":
        return _task_plan_json_schema()
    return json_schema_from_fields(config.get("schemaFieldsJson"))


def _task_plan_json_schema() -> dict[str, Any]:
    task_item = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "可选任务 ID；不填时自动生成 task_1、task_2。"},
            "title": {"type": "string", "description": "任务标题，简短可扫描。"},
            "goal": {"type": "string", "description": "Worker 需要完成的具体目标。"},
            "description": {"type": "string", "description": "goal 的别名；仅在 goal 为空时使用。"},
            "targetFiles": {"type": "array", "items": {"type": "string"}, "description": "建议优先读取的文件路径。"},
            "suggestedTools": {"type": "array", "items": {"type": "string"}, "description": "建议 Worker 使用的工具名。"},
        },
        "anyOf": [{"required": ["title"]}, {"required": ["goal"]}],
        "additionalProperties": True,
    }
    return {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": task_item,
                "description": "Task Splitter 可直接解析的任务数组。",
            }
        },
        "required": ["tasks"],
        "additionalProperties": True,
        "x-graphic-preset": "task_plan_v1",
    }


def json_schema_from_fields(value: Any) -> dict[str, Any]:
    fields = json_object_list(value)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        schema = _json_schema_for_field(field)
        properties[name] = schema
        if truthy(field.get("required")):
            required.append(name)
    schema = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    return schema


def _json_schema_for_field(field: dict[str, Any]) -> dict[str, Any]:
    field_type = str(field.get("type") or "string").strip().lower()
    if field_type not in {"string", "number", "integer", "boolean", "object", "array"}:
        field_type = "string"
    schema: dict[str, Any] = {"type": field_type}
    description = str(field.get("description") or "").strip()
    if description:
        schema["description"] = description
    enum_values = _enum_values(field.get("enumValues") or field.get("enum_values"))
    if enum_values:
        schema["enum"] = enum_values
    default_value = _field_default_value(field.get("defaultValue"))
    if default_value is not None:
        schema["default"] = default_value
    if field_type == "object":
        children = json_object_list(field.get("children") or field.get("fields"))
        child_schema = json_schema_from_fields(children)
        schema["properties"] = child_schema.get("properties", {})
        if child_schema.get("required"):
            schema["required"] = child_schema["required"]
        schema["additionalProperties"] = True
    if field_type == "array":
        item_type = str(field.get("itemType") or field.get("item_type") or "").strip().lower()
        item_fields = json_object_list(field.get("itemFields") or field.get("item_fields"))
        if item_fields:
            schema["items"] = json_schema_from_fields(item_fields)
        elif item_type in {"string", "number", "integer", "boolean", "object", "array"}:
            schema["items"] = {"type": item_type}
        else:
            schema["items"] = {}
    return schema


def _enum_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，\n;；]+", text) if item.strip()]


def _field_default_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def validation_result(value: Any, schema: dict[str, Any]) -> dict[str, Any]:
    errors = validate_json_value(value, schema, "$")
    return {
        "valid": not errors,
        "errors": errors,
        "schema": schema,
        "output": value,
    }


def validate_json_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = str(schema.get("type") or "object")
    if not _json_type_matches(value, expected_type):
        return [f"{path} expected {expected_type}, got {type(value).__name__}"]
    if "enum" in schema and isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']}")
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        if not any(_schema_condition_matches(value, item) for item in any_of if isinstance(item, dict)):
            errors.append(f"{path} must satisfy at least one anyOf condition")
    if expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and item_schema:
            for index, item in enumerate(value):
                errors.extend(validate_json_value(item, item_schema, f"{path}[{index}]"))
        return errors
    if expected_type != "object" or not isinstance(value, dict):
        return errors
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = {str(item) for item in schema.get("required", []) if str(item)}
    for key in sorted(required):
        if key not in value or value.get(key) is None:
            errors.append(f"{path}.{key} is required")
    for key, property_schema in properties.items():
        if key not in value or value.get(key) is None:
            continue
        if isinstance(property_schema, dict):
            errors.extend(validate_json_value(value.get(key), property_schema, f"{path}.{key}"))
    return errors


def _schema_condition_matches(value: Any, schema: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    required = {str(item) for item in schema.get("required", []) if str(item)}
    for key in required:
        if key not in value or value.get(key) in (None, ""):
            return False
    if schema.get("properties") or schema.get("type"):
        return not validate_json_value(value, {**schema, "anyOf": []}, "$")
    return True


def _json_type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def sample_json_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    result: dict[str, Any] = {}
    for key, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            result[key] = ""
            continue
        result[key] = _sample_value_from_schema(field_schema)
    return result


def _sample_value_from_schema(schema: dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    field_type = str(schema.get("type") or "string")
    if field_type == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return [_sample_value_from_schema(item_schema)] if item_schema else []
    if field_type == "object":
        return sample_json_from_schema(schema)
    if field_type == "boolean":
        return False
    if field_type in {"number", "integer"}:
        return 0
    return ""


def json_extractor_system_prompt(config: dict[str, Any], schema: dict[str, Any]) -> str:
    instruction = str(config.get("instruction") or "").strip()
    prompt = (
        "你是 JSON Extractor。请严格根据 JSON Schema 从用户输入中抽取一个 JSON object。"
        "只输出 JSON object，不要输出 Markdown 或解释。缺失且非必填的字段可以省略。"
    )
    if instruction:
        prompt += "\n\n抽取说明：\n" + instruction
    prompt += "\n\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False, indent=2)
    return prompt


def repair_json_output(
    config: dict[str, Any],
    value: Any,
    schema: dict[str, Any],
    errors: list[str],
    source_text: str,
    provider: str,
    model: str,
    runtime_config: dict[str, Any] | None,
    raw_content: str = "",
) -> dict[str, Any]:
    instruction = str(config.get("repairInstruction") or "").strip()
    system_prompt = (
        "你是 JSON Repair。请把候选内容修复为严格符合 JSON Schema 的 JSON object。"
        "只输出 JSON object，不要输出 Markdown 或解释。不要编造与输入无关的信息。"
    )
    if instruction:
        system_prompt += "\n\n修复说明：\n" + instruction
    system_prompt += "\n\nJSON Schema：\n" + json.dumps(schema, ensure_ascii=False, indent=2)
    payload = {
        "validationErrors": errors,
        "candidate": value,
        "rawContent": raw_content,
        "sourceText": source_text,
    }

    from app.runner.model_runtime import call_chat_model

    response = call_chat_model(
        provider,
        model,
        [
            ("system", system_prompt),
            ("user", "请修复以下 JSON 候选内容：\n" + json.dumps(payload, ensure_ascii=False, default=str, indent=2)),
        ],
        runtime_config,
    )
    response_content = getattr(response, "content", str(response))
    result: dict[str, Any] = {
        "attempted": True,
        "ok": False,
        "errors": list(errors),
        "before": compact_value(value),
        "raw": compact_value(response_content),
    }
    try:
        repaired = parse_json_object_from_text(response_content)
    except RuntimeError as exc:
        result["errors"] = [*list(errors), str(exc)]
        return result
    validation = validation_result(repaired, schema)
    result.update(
        {
            "ok": validation["valid"],
            "output": repaired,
            "validation": validation,
            "after": compact_value(repaired),
        }
    )
    if not validation["valid"]:
        result["errors"] = validation["errors"]
    return result


def parse_json_object_from_text(content: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(content or "").strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    if fallback is not None:
        return fallback
    raise RuntimeError("模型响应不是合法 JSON object。")
