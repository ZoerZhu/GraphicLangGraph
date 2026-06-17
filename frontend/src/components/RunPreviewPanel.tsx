import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, Eye, Layers, Maximize2, Minimize2, RotateCcw, ShieldCheck, Trash2, X } from "lucide-react";
import { applyEditSession, discardEditSession, getEditSession, rollbackEditSession, runEditCommand } from "../lib/api";
import { useProjectStore } from "../store/projectStore";
import type { CommandRunResult, EditSession, RunHistoryGraphMismatch, RunHistoryRecord, RunHistoryReplayMode, RunPreviewResult, RunTraceItem, RuntimeEnvironmentConfig, ValidationIssue } from "../types";
import { FloatingPanel } from "./FloatingPanel";
import { RunInputEditor, RunModelPicker, RunStartButton } from "./RunControls";
import { RuntimeValueView } from "./RuntimeValueView";

export function RunPreviewPanel() {
  const open = useProjectStore((state) => state.runOpen);
  const collapsed = useProjectStore((state) => state.runCollapsed);
  const project = useProjectStore((state) => state.project);
  const status = useProjectStore((state) => state.status);
  const runInput = useProjectStore((state) => state.runInput);
  const runRunning = useProjectStore((state) => state.runRunning);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const selectedRunModelConfigId = useProjectStore((state) => state.selectedRunModelConfigId);
  const runResult = useProjectStore((state) => state.runResult);
  const runHistoryRecords = useProjectStore((state) => state.runHistoryRecords);
  const selectedRunHistoryId = useProjectStore((state) => state.selectedRunHistoryId);
  const runHistoryReplayMode = useProjectStore((state) => state.runHistoryReplayMode);
  const runHistoryMismatch = useProjectStore((state) => state.runHistoryMismatch);
  const closeRunPanel = useProjectStore((state) => state.closeRunPanel);
  const expandRunPanel = useProjectStore((state) => state.expandRunPanel);
  const collapseRunPanel = useProjectStore((state) => state.collapseRunPanel);
  const setRunInput = useProjectStore((state) => state.setRunInput);
  const setSelectedRunModelConfigId = useProjectStore((state) => state.setSelectedRunModelConfigId);
  const runPreview = useProjectStore((state) => state.runPreview);
  const cancelRun = useProjectStore((state) => state.cancelRun);
  const selectNode = useProjectStore((state) => state.selectNode);
  const selectRunHistoryRecord = useProjectStore((state) => state.selectRunHistoryRecord);
  const setRunHistoryReplayMode = useProjectStore((state) => state.setRunHistoryReplayMode);
  const clearRunHistory = useProjectStore((state) => state.clearRunHistory);
  const enabledModels = workspaceModelConfigs.filter((config) => config.enabled);
  const selectableNodeIds = runHistoryMismatch && runHistoryReplayMode === "details"
    ? new Set<string>()
    : new Set(project?.nodes.map((node) => node.id) ?? []);

  if (!open) return null;

  if (collapsed) {
    return (
      <FloatingPanel
        key="run-collapsed"
        title="运行浏览"
        className="run-panel run-panel--collapsed"
        initialRect={runPanelCollapsedRect}
        minWidth={230}
        minHeight={74}
        maxWidth={360}
        maxHeight={120}
        actions={
          <>
            <button className="icon-only panel-close" onClick={expandRunPanel} title="展开运行预览" type="button">
              <Maximize2 size={15} />
            </button>
            <button className="icon-only panel-close" onClick={closeRunPanel} title="关闭运行预览" type="button">
              <X size={15} />
            </button>
          </>
        }
      >
        <div className="run-panel__collapsed-text">
          {runResult ? `${runResult.trace.length} 个节点 · ${runResult.valid ? "校验通过" : "有校验问题"}` : status}
        </div>
      </FloatingPanel>
    );
  }

  return (
    <FloatingPanel
      key="run-expanded"
      title="运行预览"
      subtitle="运行模式"
      className="run-panel"
      initialRect={runPanelInitialRect}
      minWidth={380}
      minHeight={420}
      maxWidth={720}
      actions={
        <>
          <button className="icon-only panel-close" onClick={collapseRunPanel} title="缩小运行预览" type="button">
            <Minimize2 size={15} />
          </button>
          <button className="icon-only panel-close" onClick={closeRunPanel} title="关闭运行预览" type="button">
            <X size={15} />
          </button>
        </>
      }
    >
      <div className="run-panel__scroll">
        <section className="run-section">
          <RunInputEditor project={project} runInput={runInput} setRunInput={setRunInput} />
          <div className="run-inline-controls">
            <RunModelPicker
              models={workspaceModelConfigs}
              selectedModelId={selectedRunModelConfigId}
              onChange={setSelectedRunModelConfigId}
            />
            <RunStartButton
              disabled={enabledModels.length === 0}
              running={runRunning}
              onRun={() => void runPreview()}
              onStop={cancelRun}
            />
          </div>
        </section>

        <RunHistoryList
          records={runHistoryRecords}
          selectedId={selectedRunHistoryId}
          onClear={clearRunHistory}
          onSelect={selectRunHistoryRecord}
        />

        {runHistoryMismatch ? (
          <RunHistoryMismatchNotice
            mismatch={runHistoryMismatch}
            mode={runHistoryReplayMode}
            onModeChange={setRunHistoryReplayMode}
          />
        ) : null}

        {runResult ? (
          <>
            <PatchApplicationPanel result={runResult} />
            <RunResultView result={runResult} selectableNodeIds={selectableNodeIds} onSelectNode={selectNode} />
          </>
        ) : (
          <div className="run-empty">
            进入运行模式后，可在本面板或 Start 节点下方选择模型、填写输入并开始真实运行。
          </div>
        )}
      </div>
    </FloatingPanel>
  );
}

function PatchApplicationPanel({ result }: { result: RunPreviewResult }) {
  const project = useProjectStore((state) => state.project);
  const runtimeEnvironments = useProjectStore((state) => state.workspaceRuntimeEnvironments);
  const runtimeEnvironment = pickRuntimeEnvironment(runtimeEnvironments, project?.project.runtimeEnvironmentId ?? "");
  const patchIds = useMemo(() => collectPatchIds(result), [result]);
  const [sessions, setSessions] = useState<Record<string, EditSession>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [command, setCommand] = useState("git diff --check");
  const [commandResult, setCommandResult] = useState<CommandRunResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadSessions() {
      const next: Record<string, EditSession> = {};
      for (const patchId of patchIds) {
        try {
          next[patchId] = await getEditSession(patchId);
        } catch {
          // Runtime output may still contain a partial object; ignore missing sessions.
        }
      }
      if (!cancelled) setSessions(next);
    }
    void loadSessions();
    return () => {
      cancelled = true;
    };
  }, [patchIds]);

  const sessionList = patchIds.map((id) => sessions[id]).filter(Boolean);
  if (!patchIds.length) return null;

  async function applyPatch(session: EditSession) {
    setBusyId(session.patchId);
    setMessage("正在应用补丁...");
    try {
      const updated = await applyEditSession(session.patchId, runtimeEnvironment ?? undefined);
      setSessions((current) => ({ ...current, [updated.patchId]: updated }));
      setMessage("补丁已应用");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "补丁应用失败");
    } finally {
      setBusyId(null);
    }
  }

  async function discardPatch(session: EditSession) {
    setBusyId(session.patchId);
    setMessage("正在丢弃补丁...");
    try {
      const updated = await discardEditSession(session.patchId);
      setSessions((current) => ({ ...current, [updated.patchId]: updated }));
      setMessage("补丁已丢弃");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "补丁丢弃失败");
    } finally {
      setBusyId(null);
    }
  }

  async function rollbackPatch(session: EditSession) {
    if (!session.rollbackId) return;
    setBusyId(session.patchId);
    setMessage("正在回滚补丁...");
    try {
      const updated = await rollbackEditSession(session.rollbackId);
      setSessions((current) => ({ ...current, [updated.patchId]: updated }));
      setMessage("补丁已回滚");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "补丁回滚失败");
    } finally {
      setBusyId(null);
    }
  }

  async function runCommand() {
    setBusyId("__command__");
    setCommandResult(null);
    setMessage("正在运行验证命令...");
    try {
      const result = await runEditCommand(command, ".", runtimeEnvironment ?? undefined);
      setCommandResult(result);
      setMessage(result.exitCode === 0 ? "验证命令通过" : `验证命令失败：exit ${result.exitCode}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "验证命令执行失败");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="patch-panel">
      <div className="run-section-title">
        <strong>变更集应用</strong>
        <span>{patchIds.length} 个 patch</span>
      </div>
      {sessionList.length ? (
        <div className="patch-panel__list">
          {sessionList.map((session) => (
            <article key={session.patchId} className={`patch-card is-${session.status}`}>
              <div className="patch-card__head">
                <span>
                  <strong>{session.patchId}</strong>
                  <small>{session.status} · {session.files.length} 文件</small>
                </span>
                <span className="patch-card__actions">
                  <button disabled={busyId === session.patchId || !["proposed", "blocked"].includes(session.status)} onClick={() => void applyPatch(session)} type="button">
                    <ShieldCheck size={14} />
                    应用
                  </button>
                  <button disabled={busyId === session.patchId || session.status === "applied"} onClick={() => void discardPatch(session)} type="button">
                    <Trash2 size={14} />
                    丢弃
                  </button>
                  <button disabled={busyId === session.patchId || !session.rollbackId || session.status !== "applied"} onClick={() => void rollbackPatch(session)} type="button">
                    <RotateCcw size={14} />
                    回滚
                  </button>
                </span>
              </div>
              {session.conflicts.length ? (
                <div className="patch-card__conflicts">
                  {session.conflicts.map((conflict) => <span key={conflict}>{conflict}</span>)}
                </div>
              ) : null}
              <div className="patch-card__files">
                {session.files.map((file) => (
                  <span key={file.path}>{file.path} · {file.summary}</span>
                ))}
              </div>
              <details className="runtime-value__fold">
                <summary>
                  <span>Diff · {session.diff.length} 字符</span>
                </summary>
                <pre className="runtime-value__code">{session.diff}</pre>
              </details>
            </article>
          ))}
        </div>
      ) : (
        <div className="run-empty">正在读取 patch 详情...</div>
      )}
      <div className="patch-command">
        <input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="git diff --check" />
        <button disabled={busyId === "__command__"} onClick={() => void runCommand()} type="button">
          运行验证命令
        </button>
      </div>
      {message ? <small className="patch-panel__message">{message}</small> : null}
      {commandResult ? (
        <div className={`patch-command-result ${commandResult.exitCode === 0 ? "is-ok" : "is-error"}`}>
          <strong>exit {commandResult.exitCode} · {commandResult.durationMs}ms</strong>
          {commandResult.stdout ? <pre>{commandResult.stdout}</pre> : null}
          {commandResult.stderr ? <pre>{commandResult.stderr}</pre> : null}
        </div>
      ) : null}
    </section>
  );
}

function RunHistoryList({
  records,
  selectedId,
  onSelect,
  onClear,
}: {
  records: RunHistoryRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClear: () => void;
}) {
  return (
    <section className="run-history-section">
      <div className="run-section-title">
        <strong>运行历史</strong>
        <button className="icon-only" disabled={records.length === 0} onClick={onClear} title="清空运行历史" type="button">
          <Trash2 size={14} />
        </button>
      </div>
      {records.length ? (
        <div className="run-history-list">
          {records.map((record) => (
            <button
              key={record.id}
              className={`run-history-record ${record.id === selectedId ? "is-selected" : ""}`}
              onClick={() => onSelect(record.id)}
              type="button"
            >
              <strong>{formatTime(record.createdAt)}</strong>
              <span>{record.modelConfigName}</span>
              <small>
                {record.result.trace.length} 节点 · {record.result.valid ? "校验通过" : `${record.result.issues.length} 个问题`}
              </small>
            </button>
          ))}
        </div>
      ) : (
        <div className="run-history-empty">暂无运行历史。每次真实运行结束后会自动保存。</div>
      )}
    </section>
  );
}

function RunHistoryMismatchNotice({
  mismatch,
  mode,
  onModeChange,
}: {
  mismatch: RunHistoryGraphMismatch;
  mode: RunHistoryReplayMode;
  onModeChange: (mode: RunHistoryReplayMode) => void;
}) {
  const blockedCount = mismatch.missingNodeIds.length + mismatch.incompatibleNodeIds.length;
  const title = mismatch.reason === "legacy"
    ? "该历史缺少结构快照，无法确认是否匹配"
    : "该历史与当前 Agent 结构不一致";
  return (
    <section className="run-history-mismatch">
      <div className="run-history-mismatch__head">
        <AlertTriangle size={15} />
        <strong>{title}</strong>
      </div>
      <p>
        历史结构 {mismatch.historyNodeCount} 节点 / {mismatch.historyEdgeCount} 边，当前结构 {mismatch.currentNodeCount} 节点 / {mismatch.currentEdgeCount} 边。
        可匹配 {mismatch.matchedNodeIds.length} 个节点，缺失或类型变化 {blockedCount} 个节点，当前新增 {mismatch.addedNodeIds.length} 个节点。
      </p>
      <div className="run-history-mismatch__actions">
        <button
          className={mode === "details" ? "is-active" : ""}
          onClick={() => onModeChange("details")}
          type="button"
        >
          <Eye size={14} />
          只看历史详情
        </button>
        <button
          className={mode === "overlay" ? "is-active" : ""}
          disabled={mismatch.matchedNodeIds.length === 0}
          onClick={() => onModeChange("overlay")}
          type="button"
        >
          <Layers size={14} />
          叠加到可匹配节点
        </button>
      </div>
    </section>
  );
}

function RunResultView({
  result,
  selectableNodeIds,
  onSelectNode,
}: {
  result: RunPreviewResult;
  selectableNodeIds: Set<string>;
  onSelectNode: (nodeId: string | null) => void;
}) {
  return (
    <div className="run-result">
      <div className={`run-valid ${result.valid ? "is-valid" : "is-invalid"}`}>
        {result.valid ? "真实运行 · 图校验通过" : `图校验发现 ${result.issues.length} 个问题`}
      </div>
      {result.issues.length ? (
        <div className="run-issues">
          {result.issues.slice(0, 6).map((issue) => (
            <button
              key={`${issue.code}-${issue.nodeId ?? issue.edgeId ?? ""}`}
              disabled={!issue.nodeId}
              onClick={() => issue.nodeId && onSelectNode(issue.nodeId)}
              title={issue.suggestion ?? issue.message}
              type="button"
            >
              {formatIssue(issue)}
            </button>
          ))}
        </div>
      ) : null}

      <section className="run-trace-section">
        <div className="run-section-title">
          <strong>节点追踪</strong>
          <span>{result.trace.length} 个节点</span>
        </div>
        <div className="run-trace">
          {result.trace.map((item, index) => (
            <RunTraceCard
              key={`${item.nodeId}-${index}`}
              index={index}
              item={item}
              selectable={selectableNodeIds.has(item.nodeId)}
              onSelectNode={onSelectNode}
            />
          ))}
        </div>
      </section>

      <section className="run-output-state">
        <div className="run-section-title">
          <strong>输出 State</strong>
          <ChevronDown size={14} />
        </div>
        <div className="run-output-state__body">
          <RuntimeValueView value={result.outputState} />
        </div>
      </section>
    </div>
  );
}

function RunTraceCard({
  index,
  item,
  selectable,
  onSelectNode,
}: {
  index: number;
  item: RunTraceItem;
  selectable: boolean;
  onSelectNode: (nodeId: string | null) => void;
}) {
  const outputs = Object.entries(item.outputDelta);
  return (
    <article className={`run-trace-item is-${item.status}`}>
      <button
        className="run-trace-item__head"
        disabled={!selectable}
        onClick={() => selectable && onSelectNode(item.nodeId)}
        title={selectable ? "定位到当前画布节点" : "该节点不在当前可叠加画布中"}
        type="button"
      >
        <strong>{index + 1}. {item.label}</strong>
        <span>{item.type} · {statusLabel(item.status)} · {item.durationMs}ms</span>
      </button>
      {item.detail ? <p>{item.detail}</p> : null}
      {outputs.length ? (
        <div className="run-output-vars">
          {outputs.map(([name, value]) => (
            <section key={name} className="run-output-var">
              <div className="run-output-var__name">state.{name}</div>
              <RuntimeValueView value={value} />
            </section>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function formatIssue(issue: ValidationIssue) {
  const location = issue.nodeId ? `${issue.nodeId}: ` : "";
  const suggestion = issue.suggestion ? ` · ${issue.suggestion}` : "";
  return `${location}${issue.message}${suggestion}`;
}

function statusLabel(status: RunTraceItem["status"]) {
  switch (status) {
    case "ok":
      return "完成";
    case "error":
      return "失败";
    case "skipped":
      return "跳过";
    default:
      return status;
  }
}

function collectPatchIds(result: RunPreviewResult): string[] {
  const ids = new Set<string>();
  const visit = (value: unknown) => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    const record = value as Record<string, unknown>;
    if (typeof record.patchId === "string" && record.patchId.startsWith("patch_")) {
      ids.add(record.patchId);
    }
    Object.values(record).forEach(visit);
  };
  visit(result.outputState);
  result.trace.forEach((item) => visit(item.outputDelta));
  return [...ids];
}

function pickRuntimeEnvironment(environments: RuntimeEnvironmentConfig[], selectedId: string) {
  return environments.find((environment) => environment.id === selectedId) ?? environments[0] ?? null;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function runPanelInitialRect() {
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: 318,
    y: 98,
    width: 500,
    height: Math.min(760, Math.max(460, viewportHeight - 118)),
  };
}

function runPanelCollapsedRect() {
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  return {
    x: Math.max(16, viewportWidth - 286),
    y: 98,
    width: 266,
    height: 82,
  };
}
