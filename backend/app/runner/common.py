from __future__ import annotations

from . import engine

render_template = engine.render_template
compact_state = engine._compact_state
compact_value = engine._compact_value
get_path = engine._get_path
set_path = engine._set_path
json_object_list = engine._json_object_list
json_string_list = engine._json_string_list
parse_json_object = engine._parse_json_object
state_value_to_text = engine._state_value_to_text
fallback_reply_content = engine._fallback_reply_content
positive_int = engine._positive_int
optional_positive_int = engine._optional_positive_int
optional_positive_float = engine._optional_positive_float
non_negative_int = engine._non_negative_int
positive_float = engine._positive_float
bool_config = engine._bool_config
truthy = engine._truthy
format_error = engine._format_error
runtime_error_payload = engine._runtime_error_payload
choose_handle = engine._choose_handle
target_for_handle = engine._target_for_handle
first_target = engine._first_target
first_execution_target = engine._first_execution_target
next_execution_target = engine._next_execution_target
error_execution_target = engine._error_execution_target
