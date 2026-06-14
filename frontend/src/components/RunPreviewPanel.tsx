import { Play, X } from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { ModelConfig, RunMode } from "../types";

export function RunPreviewPanel() {
  const open = useProjectStore((state) => state.runOpen);
  const runMode = useProjectStore((state) => state.runMode);
  const runInput = useProjectStore((state) => state.runInput);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const selectedRunModelConfigId = useProjectStore((state) => state.selectedRunModelConfigId);
  const runResult = useProjectStore((state) => state.runResult);
  const closeRunPanel = useProjectStore((state) => state.closeRunPanel);
  const setRunMode = useProjectStore((state) => state.setRunMode);
  const setRunInput = useProjectStore((state) => state.setRunInput);
  const setSelectedRunModelConfigId = useProjectStore((state) => state.setSelectedRunModelConfigId);
  const runPreview = useProjectStore((state) => state.runPreview);
  const enabledModels = workspaceModelConfigs.filter((config) => config.enabled);
  const selectedModel = pickSelectedModel(enabledModels, selectedRunModelConfigId);

  if (!open) return null;

  return (
    <aside className="mvp-panel run-panel glass-panel">
      <div className="panel-title">
        <span>运行预览</span>
        <button className="icon-only panel-close" onClick={closeRunPanel} title="关闭运行预览" type="button">
          <X size={15} />
        </button>
      </div>
      <div className="run-mode-toggle" role="group" aria-label="运行模式">
        <ModeButton active={runMode === "dry"} mode="dry" onClick={setRunMode} />
        <ModeButton active={runMode === "live"} mode="live" onClick={setRunMode} />
      </div>
      <label className="field compact-field">
        <span>真实运行模型</span>
        <select
          disabled={enabledModels.length === 0}
          value={selectedModel?.id ?? ""}
          onChange={(event) => setSelectedRunModelConfigId(event.target.value || null)}
        >
          {enabledModels.length === 0 ? <option value="">未配置启用模型</option> : null}
          {enabledModels.map((config) => (
            <option key={config.id} value={config.id}>
              {config.name} · {config.provider}/{config.model || "未填写模型"}
            </option>
          ))}
        </select>
        <small className="run-model-hint">
          {selectedModel ? formatModelHint(selectedModel) : "在管理页左侧「模型」中添加配置；这里只保存环境变量名，不保存密钥。"}
        </small>
      </label>
      <label className="field compact-field">
        <span>输入 JSON</span>
        <textarea className="code-area" rows={7} value={runInput} onChange={(event) => setRunInput(event.target.value)} />
      </label>
      <button className="primary run-button" onClick={() => void runPreview()} type="button">
        <Play size={15} />
        <span>{runMode === "live" ? "开始真实运行" : "开始模拟运行"}</span>
      </button>

      {runResult ? (
        <div className="run-result">
          <div className={`run-valid ${runResult.valid ? "is-valid" : "is-invalid"}`}>
            {runResult.valid ? `${runResult.mode === "live" ? "真实运行" : "模拟运行"} · 图校验通过` : `图校验发现 ${runResult.issues.length} 个问题`}
          </div>
          {runResult.issues.length ? (
            <div className="run-issues">
              {runResult.issues.slice(0, 4).map((issue) => (
                <span key={`${issue.code}-${issue.nodeId ?? issue.edgeId ?? ""}`}>{issue.message}</span>
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
          {runMode === "live"
            ? "真实运行会调用模型，并实际读取本地知识库文件；v1 只支持 LLM、Retriever、分支和 Direct Reply。"
            : "模拟运行不会调用真实模型或外部 HTTP，会模拟路径、state 写入和分支选择。"}
        </div>
      )}
    </aside>
  );
}

function ModeButton({ active, mode, onClick }: { active: boolean; mode: RunMode; onClick: (mode: RunMode) => void }) {
  return (
    <button className={active ? "is-active" : ""} onClick={() => onClick(mode)} type="button">
      {mode === "live" ? "真实运行" : "模拟运行"}
    </button>
  );
}

function formatJson(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2);
}

function pickSelectedModel(models: ModelConfig[], selectedId: string | null): ModelConfig | null {
  return models.find((config) => config.id === selectedId) ?? models.find((config) => config.isDefault) ?? models[0] ?? null;
}

function formatModelHint(config: ModelConfig) {
  const apiKeyText = config.apiKey ? "API Key 已配置" : config.apiKeyEnv ? `环境变量 ${config.apiKeyEnv}` : "无需或自定义密钥";
  const baseUrlText = config.baseUrl ? ` · ${config.baseUrl}` : "";
  return `${apiKeyText}${baseUrlText}`;
}
