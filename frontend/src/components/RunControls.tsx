import { useLayoutEffect, useRef } from "react";
import { LoaderCircle, Play, Square } from "lucide-react";
import type { ModelConfig, ProjectIR, StateField } from "../types";

export interface RunInputField {
  name: string;
  type: string;
  label: string;
  multiline?: boolean;
}

export function RunModelPicker({
  models,
  selectedModelId,
  onChange,
}: {
  models: ModelConfig[];
  selectedModelId: string | null;
  onChange: (id: string | null) => void;
}) {
  const enabledModels = models.filter((config) => config.enabled);
  const selectedModel = pickSelectedModel(enabledModels, selectedModelId);
  return (
    <div className="run-model-picker">
      <select
        aria-label="运行模型"
        disabled={enabledModels.length === 0}
        value={selectedModel?.id ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        {enabledModels.length === 0 ? <option value="">未配置启用模型</option> : null}
        {enabledModels.map((config) => (
          <option key={config.id} value={config.id}>
            {formatModelOption(config)}
          </option>
        ))}
      </select>
    </div>
  );
}

export function RunInputEditor({
  project,
  runInput,
  setRunInput,
}: {
  project: ProjectIR | null;
  runInput: string;
  setRunInput: (value: string) => void;
}) {
  const inputFields = buildRunInputFields(project);
  const inputState = parseRunInput(runInput);

  function updateInputField(field: RunInputField, rawValue: string | boolean) {
    const nextState: Record<string, unknown> = {};
    for (const item of inputFields) {
      if (item.name === field.name) {
        nextState[item.name] = coerceRunInputValue(item.type, rawValue);
      } else {
        nextState[item.name] = coerceRunInputValue(item.type, readInputValue(inputState[item.name], item.type));
      }
    }
    setRunInput(JSON.stringify(nextState, null, 2));
  }

  return (
    <div className="run-input-form">
      {inputFields.map((field) => (
        <RunInputControl
          key={field.name}
          field={field}
          value={inputState[field.name]}
          onChange={(value) => updateInputField(field, value)}
        />
      ))}
    </div>
  );
}

export function RunStartButton({
  disabled = false,
  running = false,
  onRun,
  onStop,
}: {
  disabled?: boolean;
  running?: boolean;
  onRun: () => void;
  onStop?: () => void;
}) {
  if (running && onStop) {
    return (
      <button
        aria-label="中断运行"
        className="run-button run-button--icon is-stop"
        onClick={onStop}
        title="中断当前运行"
        type="button"
      >
        <Square size={15} />
      </button>
    );
  }

  return (
    <button
      aria-label={running ? "运行中" : "开始真实运行"}
      className="run-button run-button--icon"
      disabled={disabled || running}
      onClick={onRun}
      title={running ? "运行中" : "开始真实运行"}
      type="button"
    >
      {running ? <LoaderCircle className="spin-icon" size={16} /> : <Play size={16} />}
    </button>
  );
}

export function buildRunInputFields(project: ProjectIR | null): RunInputField[] {
  const startNode = project?.nodes.find((node) => node.type === "start");
  const inputMode = String(startNode?.config.inputMode ?? "chat");
  if (!project || inputMode !== "form") {
    return [{ name: "messages", type: "str", label: "用户消息", multiline: true }];
  }
  const outputFields = collectOutputFields(project);
  const fields = project.state.fields
    .filter((field) => field.name && !outputFields.has(field.name))
    .map((field) => toRunInputField(field));
  return fields.length ? fields : [{ name: "messages", type: "str", label: "用户消息", multiline: true }];
}

export function parseRunInput(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

export function pickSelectedModel(models: ModelConfig[], selectedId: string | null): ModelConfig | null {
  return models.find((config) => config.id === selectedId) ?? models.find((config) => config.isDefault) ?? models[0] ?? null;
}

export function formatModelOption(config: ModelConfig) {
  return config.model || config.name || "未设置模型";
}

export function formatModelHint(config: ModelConfig) {
  const apiKeyText = config.apiKey ? "API Key 已配置" : config.apiKeyEnv ? `环境变量 ${config.apiKeyEnv}` : "无需或自定义密钥";
  const providerText = config.provider ? `供应商 ${config.provider}` : "自定义供应商";
  const baseUrlText = config.baseUrl ? ` · ${config.baseUrl}` : "";
  return `${providerText} · ${apiKeyText}${baseUrlText}`;
}

function collectOutputFields(project: ProjectIR) {
  const fields = new Set<string>();
  for (const node of project.nodes) {
    for (const key of ["outputField", "routeField", "reasonField"]) {
      const value = node.config[key];
      if (typeof value === "string" && value.trim()) fields.add(value.trim());
    }
  }
  return fields;
}

function toRunInputField(field: StateField): RunInputField {
  return {
    name: field.name,
    type: field.type || "str",
    label: field.description ? `${field.name} · ${field.description}` : field.name,
    multiline: ["str", "string", "text"].includes((field.type || "str").toLowerCase()),
  };
}

function RunInputControl({
  field,
  value,
  onChange,
}: {
  field: RunInputField;
  value: unknown;
  onChange: (value: string | boolean) => void;
}) {
  const type = field.type.toLowerCase();
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const textValue = readInputValue(value, field.type);
  const showLabel = field.name !== "messages";

  useLayoutEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    const maxHeight = 152;
    element.style.height = "auto";
    const nextHeight = Math.min(element.scrollHeight, maxHeight);
    element.style.height = `${nextHeight}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [textValue]);

  if (type === "bool" || type === "boolean") {
    return (
      <label className="run-input-control run-input-control--checkbox">
        <input checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
        <span>{field.label}</span>
      </label>
    );
  }

  return (
    <label className="run-input-control">
      {showLabel ? <span>{field.label}</span> : null}
      {field.multiline ? (
        <textarea
          ref={textareaRef}
          rows={3}
          value={textValue}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.label || "用户输入"}
        />
      ) : (
        <input
          placeholder={field.label || "用户输入"}
          type={isNumberType(type) ? "number" : "text"}
          value={textValue}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

function readInputValue(value: unknown, type: string): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const normalized = type.toLowerCase();
  if (["dict", "object", "json", "list", "array"].includes(normalized)) {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function coerceRunInputValue(type: string, value: string | boolean): unknown {
  const normalized = type.toLowerCase();
  if (normalized === "bool" || normalized === "boolean") return Boolean(value);
  if (isNumberType(normalized)) {
    if (typeof value === "boolean") return value ? 1 : 0;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (["dict", "object", "json", "list", "array"].includes(normalized) && typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  return typeof value === "boolean" ? String(value) : value;
}

function isNumberType(type: string) {
  return ["int", "integer", "float", "number"].includes(type);
}
