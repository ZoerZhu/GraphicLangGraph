from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from queue import Empty, Queue
from typing import Any

from app.ir.schemas import NodeIR, NodeType


class NodePolicyError(RuntimeError):
    def __init__(self, node: NodeIR, original: Exception, payload: dict[str, Any], attempts: list[dict[str, Any]], policy: dict[str, Any]):
        super().__init__(str(payload.get("message") or original))
        self.node = node
        self.original = original
        self.payload = payload
        self.attempts = attempts
        self.policy = policy


class NodeTimeoutError(RuntimeError):
    pass


class HumanApprovalPause(RuntimeError):
    def __init__(self, node: NodeIR, state: dict[str, Any], approval: dict[str, Any]):
        super().__init__("Human Approval 等待人工审批。")
        self.node = node
        self.state = state
        self.approval = approval


class LiveRunUnsupportedError(RuntimeError):
    pass


def node_runtime_policy(config: dict[str, Any]) -> dict[str, Any]:
    retry = _parse_json_object(str(config.get("retryPolicyJson") or "{}"))
    error_policy = str(config.get("errorPolicy") or "default").strip().lower() or "default"
    if error_policy not in {"default", "fail_fast", "route_error", "continue", "fallback"}:
        error_policy = "default"
    timeout_sec = _optional_positive_float(config.get("nodeTimeoutSec"))
    max_retries = min(_non_negative_int(retry.get("maxRetries"), 0), 5)
    return {
        "retryEnabled": _truthy(retry.get("enabled")) and max_retries > 0,
        "maxRetries": max_retries,
        "backoffMs": min(_non_negative_int(retry.get("backoffMs"), 0), 30_000),
        "retryOnErrorTypes": [str(item).strip() for item in retry.get("retryOnErrorTypes", []) if str(item).strip()] if isinstance(retry.get("retryOnErrorTypes"), list) else [],
        "timeoutSec": timeout_sec,
        "errorPolicy": error_policy,
        "fallbackOutputJson": str(config.get("fallbackOutputJson") or "{}"),
        "errorOutputField": str(config.get("errorOutputField") or "").strip(),
    }


def should_retry_error(policy: dict[str, Any], error_type: str, exc: Exception) -> bool:
    allowed = set(policy.get("retryOnErrorTypes") or [])
    if not allowed:
        return True
    return error_type in allowed or exc.__class__.__name__ in allowed


def policy_error_type(exc: Exception) -> str:
    if isinstance(exc, NodeTimeoutError):
        return "timeout"
    if isinstance(exc, NodePolicyError):
        return str(exc.payload.get("errorType") or "node_error")
    return exc.__class__.__name__


def format_error(exc: Exception) -> str:
    if isinstance(exc, NodePolicyError):
        payload = exc.payload
        return f"{payload.get('errorType')}: {payload.get('message')}"
    if isinstance(exc, LiveRunUnsupportedError):
        return str(exc)
    return f"{exc.__class__.__name__}: {exc}"


def runtime_error_payload(node: NodeIR, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, NodePolicyError):
        return dict(exc.payload)
    return {
        "ok": False,
        "nodeId": node.id,
        "nodeType": str(node.type),
        "nodeLabel": node.label,
        "errorType": policy_error_type(exc),
        "message": str(exc),
    }


def successful_policy_trace_meta(node: NodeIR, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    policy = node_runtime_policy(node.config)
    meta: dict[str, Any] = {}
    if attempts and (len(attempts) > 1 or attempts[0].get("status") != "ok"):
        meta["attempts"] = attempts
    if policy["timeoutSec"]:
        meta["timeoutSec"] = policy["timeoutSec"]
    if policy["errorPolicy"] != "default":
        meta["errorPolicy"] = policy["errorPolicy"]
    if node.type == NodeType.FOR_EACH:
        meta["parallel"] = str(node.config.get("executionMode") or "sequential").strip().lower() == "parallel"
        meta["itemFailurePolicy"] = str(node.config.get("itemFailurePolicy") or "fail_fast").strip().lower()
    return meta


def failed_policy_trace_meta(node: NodeIR, attempts: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    meta = successful_policy_trace_meta(node, attempts)
    if attempts:
        meta["attempts"] = attempts
    if policy.get("errorPolicy"):
        meta["errorPolicy"] = policy["errorPolicy"]
    return meta


def trace_meta_from_exception(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, NodePolicyError):
        return failed_policy_trace_meta(exc.node, exc.attempts, exc.policy)
    return {}


def run_node_with_policy(
    node: NodeIR,
    state: dict[str, Any],
    call_node,
    *,
    runtime_error_payload,
    fallback_policy_delta,
    data_shaping_trace_meta,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    policy = node_runtime_policy(node.config)
    attempts: list[dict[str, Any]] = []
    max_attempts = 1 + (policy["maxRetries"] if policy["retryEnabled"] else 0)
    last_exc: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            delta, detail = call_node_with_timeout(call_node, policy["timeoutSec"])
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "ok",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            if attempt_index > 1:
                detail = f"{detail}；重试第 {attempt_index} 次后成功。"
            trace_meta = successful_policy_trace_meta(node, attempts)
            trace_meta.update(data_shaping_trace_meta(node, state, delta))
            return delta, detail, trace_meta
        except Exception as exc:
            if isinstance(exc, HumanApprovalPause):
                raise
            last_exc = exc
            error_type = policy_error_type(exc)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "error",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                    "errorType": error_type,
                    "message": str(exc),
                }
            )
            if attempt_index < max_attempts and should_retry_error(policy, error_type, exc):
                backoff_ms = min(max(policy["backoffMs"], 0) * attempt_index, 5000)
                if backoff_ms:
                    time.sleep(backoff_ms / 1000)
                continue
            break
    assert last_exc is not None
    payload = runtime_error_payload(node, last_exc)
    payload["attempts"] = attempts
    payload["errorPolicy"] = policy["errorPolicy"]
    if policy["timeoutSec"]:
        payload["timeoutSec"] = policy["timeoutSec"]
    policy_name = policy["errorPolicy"]
    if policy_name == "fallback":
        delta = fallback_policy_delta(node, state, policy, payload)
        return delta, f"{payload['errorType']}: {payload['message']}；已按 fallback 策略继续。", failed_policy_trace_meta(node, attempts, policy)
    if policy_name == "continue":
        field = policy["errorOutputField"] or "last_error"
        return {field: payload}, f"{payload['errorType']}: {payload['message']}；已按 continue 策略继续。", failed_policy_trace_meta(node, attempts, policy)
    raise NodePolicyError(node, last_exc, payload, attempts, policy)


def run_stream_node_with_policy(
    node: NodeIR,
    state: dict[str, Any],
    stream_factory,
    *,
    runtime_error_payload,
    fallback_policy_delta,
):
    policy = node_runtime_policy(node.config)
    attempts: list[dict[str, Any]] = []
    max_attempts = 1 + (policy["maxRetries"] if policy["retryEnabled"] else 0)
    last_exc: Exception | None = None
    for attempt_index in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            delta, detail, child_trace_items = yield from call_stream_with_timeout(stream_factory, policy["timeoutSec"])
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "ok",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            if attempt_index > 1:
                detail = f"{detail}；重试第 {attempt_index} 次后成功。"
            return delta, detail, child_trace_items or [], successful_policy_trace_meta(node, attempts)
        except Exception as exc:
            if isinstance(exc, HumanApprovalPause):
                raise
            last_exc = exc
            error_type = policy_error_type(exc)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "error",
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                    "errorType": error_type,
                    "message": str(exc),
                }
            )
            if attempt_index < max_attempts and should_retry_error(policy, error_type, exc):
                backoff_ms = min(max(policy["backoffMs"], 0) * attempt_index, 5000)
                if backoff_ms:
                    time.sleep(backoff_ms / 1000)
                continue
            break
    assert last_exc is not None
    payload = runtime_error_payload(node, last_exc)
    payload["attempts"] = attempts
    payload["errorPolicy"] = policy["errorPolicy"]
    if policy["timeoutSec"]:
        payload["timeoutSec"] = policy["timeoutSec"]
    if policy["errorPolicy"] == "fallback":
        delta = fallback_policy_delta(node, state, policy, payload)
        return delta, f"{payload['errorType']}: {payload['message']}；已按 fallback 策略继续。", [], failed_policy_trace_meta(node, attempts, policy)
    if policy["errorPolicy"] == "continue":
        field = policy["errorOutputField"] or "last_error"
        return {field: payload}, f"{payload['errorType']}: {payload['message']}；已按 continue 策略继续。", [], failed_policy_trace_meta(node, attempts, policy)
    raise NodePolicyError(node, last_exc, payload, attempts, policy)


def call_node_with_timeout(fn, timeout_sec: float | None) -> tuple[dict[str, Any], str]:
    if not timeout_sec:
        return fn()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FutureTimeoutError as exc:
        future.cancel()
        raise NodeTimeoutError(f"节点执行超过 {timeout_sec}s。") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def call_stream_with_timeout(stream_factory, timeout_sec: float | None):
    if not timeout_sec:
        return (yield from stream_factory())
    event_queue: Queue[tuple[str, Any]] = Queue()

    def pump() -> None:
        try:
            generator = stream_factory()
            while True:
                try:
                    event_queue.put(("event", next(generator)))
                except StopIteration as stop:
                    event_queue.put(("result", stop.value))
                    return
        except Exception as exc:
            event_queue.put(("error", exc))

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(pump)
    deadline = time.perf_counter() + timeout_sec
    try:
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                future.cancel()
                raise NodeTimeoutError(f"节点执行超过 {timeout_sec}s。")
            try:
                kind, payload = event_queue.get(timeout=min(0.05, remaining))
            except Empty:
                continue
            if kind == "event":
                yield payload
                continue
            if kind == "result":
                return payload
            if kind == "error":
                raise payload
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _optional_positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _non_negative_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback
