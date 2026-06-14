import { useMemo } from "react";
import { Play, X } from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { ModelConfig, ProjectIR, StateField, ValidationIssue } from "../types";
import { FloatingPanel } from "./FloatingPanel";

export function RunPreviewPanel() {
  const open = useProjectStore((state) => state.runOpen);
  const project = useProjectStore((state) => state.project);
  const runInput = useProjectStore((state) => state.runInput);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const selectedRunModelConfigId = useProjectStore((state) => state.selectedRunModelConfigId);
  const runResult = useProjectStore((state) => state.runResult);
  const closeRunPanel = useProjectStore((state) => state.closeRunPanel);
  const setRunInput = useProjectStore((state) => state.setRunInput);
  const setSelectedRunModelConfigId = useProjectStore((state) => state.setSelectedRunModelConfigId);
  const runPreview = useProjectStore((state) => state.runPreview);
  const selectNode = useProjectStore((state) => state.selectNode);
  const enabledModels = workspaceModelConfigs.filter((config) => config.enabled);
  const selectedModel = pickSelectedModel(enabledModels, selectedRunModelConfigId);
  const inputFields = useMemo(() => buildRunInputFields(project), [project]);
  const inputState = useMemo(() => parseRunInput(runInput), [runInput]);

  if (!open) return null;

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
    <FloatingPanel
      title="运行预览"
      className="run-panel"
      initialRect={runPanelInitialRect}
      minWidth={360}
      minHeight={360}
      maxWidth={620}
      actions={
        <button className="icon-only panel-close" onClick={closeRunPanel} title="关闭运行预览" type="button">
          <X size={15} />
        </button>
      }
    >
      <div className="run-panel__scroll">
      <label className="field compact-field">
        <span>运行模型</span>
        <select
          disabled={enabledModels.length === 0}
          value={selectedModel?.id ?? ""}
          onChange={(event) => setSelectedRunModelConfigId(event.target.value || null)}
        >
          {enabledModels.length === 0 ? <option value="">未配置启用模型</option> : null}
          {enabledModels.map((config) => (
            <option key={config.id} value={config.id}>
              {formatModelOption(config)}
            </option>
          ))}
        </select>
        <small className="run-model-hint">
          {selectedModel ? formatModelHint(selectedModel) : "在管理页左侧「模型」中添加配置；这里只保存环境变量名，不保存密钥。"}
        </small>
      </label>
      <div className="field compact-field">
        <span>运行输入</span>
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
        <small className="run-model-hint">{inputFields.length === 1 && inputFields[0].name === "messages" ? "聊天输入会写入 state.messages。" : "表单值会按字段名写入运行 state。"}</small>
      </div>
      <button className="primary run-button" onClick={() => void runPreview()} type="button">
        <Play size={15} />
        <span>开始真实运行</span>
      </button>

      {runResult ? (
        <div className="run-result">
          <div className={`run-valid ${runResult.valid ? "is-valid" : "is-invalid"}`}>
            {runResult.valid ? "真实运行 · 图校验通过" : `图校验发现 ${runResult.issues.length} 个问题`}
          </div>
          {runResult.issues.length ? (
            <div className="run-issues">
              {runResult.issues.slice(0, 4).map((issue) => (
                <button
                  key={`${issue.code}-${issue.nodeId ?? issue.edgeId ?? ""}`}
                  disabled={!issue.nodeId}
                  onClick={() => issue.nodeId && selectNode(issue.nodeId)}
                  title={issue.suggestion ?? issue.message}
                  type="button"
                >
                  {formatIssue(issue)}
                </button>
              ))}
            </div>
          ) : null}
          <div className="run-trace">
            {runResult.trace.map((item, index) => (
              <div key={`${item.nodeId}-${index}`} className={`run-trace-item is-${item.status}`}>
                <strong>{index + 1}. {item.label}</strong>
                <span>{item.type} · {item.status} · {item.durationMs}ms</span>
                <span>{item.detail}</span>
                {Object.keys(item.outputDelta).length ? (
                  <pre className="run-trace-delta">{formatJson(item.outputDelta)}</pre>
                ) : null}
              </div>
            ))}
          </div>
          <label className="field compact-field">
            <span>输出 State</span>
            <textarea className="code-area" rows={7} readOnly value={JSON.stringify(runResult.outputState, null, 2)} />
          </label>
        </div>
      ) : (
        <div className="run-empty">
          真实运行会调用模型，执行 HTTP/Mock、Retriever、AI Router、审批预览、Agent 和 Direct Reply。
        </div>
      )}
      </div>
    </FloatingPanel>
  );
}

function formatJson(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2);
}

function formatIssue(issue: ValidationIssue) {
  const location = issue.nodeId ? `${issue.nodeId}: ` : "";
  const suggestion = issue.suggestion ? ` · ${issue.suggestion}` : "";
  return `${location}${issue.message}${suggestion}`;
}

function pickSelectedModel(models: ModelConfig[], selectedId: string | null): ModelConfig | null {
  return models.find((config) => config.id === selectedId) ?? models.find((config) => config.isDefault) ?? models[0] ?? null;
}

function formatModelOption(config: ModelConfig) {
  const modelText = config.model ? ` · ${config.model}` : "";
  return `${config.name}${modelText}`;
}

function formatModelHint(config: ModelConfig) {
  const apiKeyText = config.apiKey ? "API Key 已配置" : config.apiKeyEnv ? `环境变量 ${config.apiKeyEnv}` : "无需或自定义密钥";
  const providerText = config.provider ? `供应商 ${config.provider}` : "自定义供应商";
  const baseUrlText = config.baseUrl ? ` · ${config.baseUrl}` : "";
  return `${providerText} · ${apiKeyText}${baseUrlText}`;
}

function runPanelInitialRect() {
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: 318,
    y: 98,
    width: 430,
    height: Math.min(720, Math.max(420, viewportHeight - 118)),
  };
}

interface RunInputField {
  name: string;
  type: string;
  label: string;
  multiline?: boolean;
}

function buildRunInputFields(project: ProjectIR | null): RunInputField[] {
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

function parseRunInput(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
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
  if (type === "bool" || type === "boolean") {
    return (
      <label className="run-input-control run-input-control--checkbox">
        <input checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
        <span>{field.label}</span>
      </label>
    );
  }
  const textValue = readInputValue(value, field.type);
  return (
    <label className="run-input-control">
      <span>{field.label}</span>
      {field.multiline ? (
        <textarea rows={4} value={textValue} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input type={isNumberType(type) ? "number" : "text"} value={textValue} onChange={(event) => onChange(event.target.value)} />
      )}
      <small>state.{field.name}</small>
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
