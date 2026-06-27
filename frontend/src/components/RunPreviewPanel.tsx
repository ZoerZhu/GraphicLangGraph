import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, Copy, Eye, Layers, Maximize2, Minimize2, RotateCcw, ShieldCheck, Trash2, X } from "lucide-react";
import { applyEditSession, discardEditSession, getEditSession, rollbackEditSession, runEditCommand } from "../lib/api";
import { evaluateTemplateAcceptance } from "../lib/templateAcceptance";
import { getProjectTemplateForProject } from "../lib/templates";
import { useProjectStore } from "../store/projectStore";
import type { CommandRunResult, EditSession, RunHistoryGraphMismatch, RunHistoryRecord, RunHistoryReplayMode, RunPreviewResult, RunTraceItem, RuntimeEnvironmentConfig, TemplateAcceptanceResult, ValidationIssue } from "../types";
import { FloatingPanel } from "./FloatingPanel";
import { RunInputEditor, RunModelPicker, RunStartButton } from "./RunControls";
import { RuntimeValueView } from "./RuntimeValueView";

type TraceFilter = "all" | "errors" | "slow" | "tools" | "mcp" | "agent" | "human" | "flow" | "policy" | "data";

const TRACE_FILTERS: Array<{ id: TraceFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "errors", label: "错误" },
  { id: "slow", label: "慢节点" },
  { id: "tools", label: "Tool" },
  { id: "mcp", label: "MCP" },
  { id: "agent", label: "Agent" },
  { id: "human", label: "Human" },
  { id: "flow", label: "Flow" },
  { id: "policy", label: "策略" },
  { id: "data", label: "数据" },
];

export function RunPreviewPanel() {
  const open = useProjectStore((state) => state.runOpen);
  const collapsed = useProjectStore((state) => state.runCollapsed);
  const project = useProjectStore((state) => state.project);
  const status = useProjectStore((state) => state.status);
  const runInput = useProjectStore((state) => state.runInput);
  const runRunning = useProjectStore((state) => state.runRunning);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const workspaceRuntimeEnvironments = useProjectStore((state) => state.workspaceRuntimeEnvironments);
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
  const deleteRunHistoryRecord = useProjectStore((state) => state.deleteRunHistoryRecord);
  const clearRunHistory = useProjectStore((state) => state.clearRunHistory);
  const resumePausedRun = useProjectStore((state) => state.resumePausedRun);
  const enabledModels = workspaceModelConfigs.filter((config) => config.enabled);
  const projectTemplate = getProjectTemplateForProject(project);
  const requiresModel = projectTemplate?.requiresModel ?? true;
  const selectedRuntimeEnvironment = useMemo(
    () => pickRuntimeEnvironment(workspaceRuntimeEnvironments, project?.project.runtimeEnvironmentId ?? ""),
    [workspaceRuntimeEnvironments, project?.project.runtimeEnvironmentId],
  );
  const templateAcceptance = useMemo(
    () => evaluateTemplateAcceptance(project, runResult, selectedRuntimeEnvironment),
    [project, runResult, selectedRuntimeEnvironment],
  );
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
              disabled={requiresModel && enabledModels.length === 0}
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
          onDelete={deleteRunHistoryRecord}
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
            <PendingApprovalPanel
              result={runResult}
              recordId={selectedRunHistoryId}
              running={runRunning}
              onResume={resumePausedRun}
            />
            <RunResultView result={runResult} templateAcceptance={templateAcceptance} selectableNodeIds={selectableNodeIds} onSelectNode={selectNode} />
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

function PendingApprovalPanel({
  result,
  recordId,
  running,
  onResume,
}: {
  result: RunPreviewResult;
  recordId: string | null;
  running: boolean;
  onResume: (recordId: string, action: string, comment: string) => Promise<void>;
}) {
  const [comment, setComment] = useState("");
  const [copyMessage, setCopyMessage] = useState("");
  const approval = result.pendingApproval;
  if (result.status !== "paused" || !approval) return null;
  const disabled = running || !recordId;
  const actions = approvalActions(approval);
  const defaultAction = approvalDefaultAction(approval, actions);
  const stateText = approval.state ? JSON.stringify(approval.state, null, 2) : "";
  async function copyApprovalText(label: string, value: string) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopyMessage(`${label}已复制`);
    } catch {
      setCopyMessage("当前浏览器不允许写入剪贴板");
    }
  }
  async function submitApproval(action: string) {
    if (!recordId || disabled) return;
    await onResume(recordId, action, comment);
    setComment("");
  }
  return (
    <section className="approval-panel">
      <div className="run-section-title">
        <strong>等待人工审批</strong>
        <span>{approval.nodeLabel ?? approval.nodeId} · {recordId ?? "未保存运行"}</span>
      </div>
      <div className="approval-panel__meta">
        <span>默认：{approvalActionLabel(defaultAction)}</span>
        <span>动作：{actions.map(approvalActionLabel).join(" / ")}</span>
        <span>输出：{approval.outputField ?? "approval_result"}</span>
      </div>
      {approval.prompt ? <p className="approval-panel__prompt">{approval.prompt}</p> : null}
      <div className="approval-panel__tools">
        <button disabled={!approval.prompt} onClick={() => void copyApprovalText("审批提示", approval.prompt ?? "")} type="button">
          <Copy size={13} />
          复制提示
        </button>
        <button disabled={!stateText} onClick={() => void copyApprovalText("State 摘要", stateText)} type="button">
          <Copy size={13} />
          复制 State
        </button>
        {copyMessage ? <small>{copyMessage}</small> : null}
      </div>
      <label className="field">
        <span>审批备注</span>
        <textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          placeholder="可填写拒绝原因、审批依据或处理说明"
          rows={3}
        />
      </label>
      <div className="approval-panel__actions">
        <button className="primary" disabled={disabled} onClick={() => void submitApproval(defaultAction)} type="button">
          <RotateCcw size={14} />
          使用默认动作继续
        </button>
        {actions.map((action) => (
          <button key={action} disabled={disabled} onClick={() => void submitApproval(action)} type="button">
            {approvalActionIcon(action)}
            {approvalActionLabel(action)}并继续
          </button>
        ))}
      </div>
      {approval.state ? (
        <details className="runtime-value__fold">
          <summary>
            <span>当前 State 摘要</span>
          </summary>
          <RuntimeValueView value={approval.state} />
        </details>
      ) : null}
    </section>
  );
}

function approvalActions(approval: NonNullable<RunPreviewResult["pendingApproval"]>): string[] {
  const values = Array.isArray(approval.actions) ? approval.actions : [];
  const actions = values.map((item) => String(item).trim()).filter(Boolean);
  return actions.length ? Array.from(new Set(actions)) : ["approved", "rejected"];
}

function approvalDefaultAction(approval: NonNullable<RunPreviewResult["pendingApproval"]>, actions: string[]) {
  const configured = String(approval.defaultAction ?? "").trim();
  if (configured && actions.includes(configured)) return configured;
  return actions[0] ?? "approved";
}

function approvalActionLabel(action: string) {
  switch (action) {
    case "approved":
      return "通过";
    case "rejected":
      return "拒绝";
    case "edit":
      return "修改";
    default:
      return action || "继续";
  }
}

function approvalActionIcon(action: string) {
  if (action === "approved") return <ShieldCheck size={14} />;
  if (action === "rejected") return <X size={14} />;
  return <RotateCcw size={14} />;
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
  onDelete,
  onClear,
}: {
  records: RunHistoryRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
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
            <div key={record.id} className={`run-history-record ${record.id === selectedId ? "is-selected" : ""}`}>
              <button className="run-history-record__main" onClick={() => onSelect(record.id)} type="button">
                <span className="run-history-record__top">
                  <strong>{formatTime(record.createdAt)}</strong>
                  <span className={`run-history-status is-${record.result.status ?? "completed"}`}>
                    {runStatusLabel(record.result.status)}
                  </span>
                </span>
                <span>{record.modelConfigName}</span>
                <small>
                  {record.result.trace.length} 节点 · {record.result.valid ? "校验通过" : `${record.result.issues.length} 个问题`}
                </small>
              </button>
              <button className="icon-only run-history-record__delete" onClick={() => onDelete(record.id)} title="删除该运行历史" type="button">
                <Trash2 size={13} />
              </button>
            </div>
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
  templateAcceptance,
  selectableNodeIds,
  onSelectNode,
}: {
  result: RunPreviewResult;
  templateAcceptance: TemplateAcceptanceResult | null;
  selectableNodeIds: Set<string>;
  onSelectNode: (nodeId: string | null) => void;
}) {
  const [traceFilter, setTraceFilter] = useState<TraceFilter>("all");
  const [traceSearch, setTraceSearch] = useState("");
  const observability = useMemo(() => buildRunObservability(result), [result]);
  const filteredTrace = useMemo(
    () => filterTraceItems(result.trace, traceFilter, traceSearch, observability.slowest?.nodeId ?? ""),
    [result.trace, traceFilter, traceSearch, observability.slowest?.nodeId],
  );
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

      {templateAcceptance ? <TemplateAcceptanceSummary result={templateAcceptance} /> : null}
      <RunObservabilitySummary summary={observability} />
      <RuntimeCallSummary calls={observability.calls} groups={observability.callGroups} />

      <section className="run-trace-section">
        <div className="run-section-title">
          <strong>节点追踪</strong>
          <span>{filteredTrace.length}/{result.trace.length} 个节点</span>
        </div>
        <div className="trace-filter-bar">
          <div className="trace-filter-bar__buttons">
            {TRACE_FILTERS.map((filter) => (
              <button
                key={filter.id}
                className={traceFilter === filter.id ? "is-active" : ""}
                onClick={() => setTraceFilter(filter.id)}
                type="button"
              >
                {filter.label}
              </button>
            ))}
          </div>
          <input
            value={traceSearch}
            onChange={(event) => setTraceSearch(event.target.value)}
            placeholder="搜索节点、类型、ID、detail"
          />
        </div>
        <div className="run-trace">
          {filteredTrace.length ? (
            filteredTrace.map((item, index) => (
              <RunTraceCard
                key={`${item.nodeId}-${index}`}
                index={result.trace.indexOf(item)}
                item={item}
                selectable={selectableNodeIds.has(item.nodeId)}
                onSelectNode={onSelectNode}
              />
            ))
          ) : (
            <div className="run-empty">没有匹配当前筛选条件的 trace。</div>
          )}
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

function RunObservabilitySummary({ summary }: { summary: RunObservabilitySummaryData }) {
  const hints = observabilityHints(summary);
  return (
    <section className="observability-panel">
      <div className="run-section-title">
        <strong>运行观测</strong>
        <span>{summary.statusLabel}</span>
      </div>
      <div className="observability-grid">
        <ObservabilityMetric label="节点" value={`${summary.nodeCount}`} detail={`${summary.okCount} 成功 / ${summary.errorCount} 失败`} tone={summary.errorCount ? "error" : "ok"} />
        <ObservabilityMetric label="总耗时" value={`${formatDuration(summary.totalDurationMs)}`} detail={summary.slowest ? `最慢 ${summary.slowest.label}` : "无节点耗时"} />
        <ObservabilityMetric label="策略" value={`${summary.policyNodeCount}`} detail={`${summary.retryNodeCount} 重试 / ${summary.timeoutNodeCount} 超时`} tone={summary.policyNodeCount ? "warning" : "ok"} />
        <ObservabilityMetric label="子链路" value={`${summary.childTraceCount}`} detail={`${summary.parallelTraceCount} 并发 trace`} />
        <ObservabilityMetric label="调用" value={`${summary.calls.length}`} detail={callSummaryLabel(summary.calls)} tone={summary.calls.some((call) => call.ok === false) ? "error" : "neutral"} />
        <ObservabilityMetric label="状态" value={summary.paused ? "待审批" : summary.failed ? "失败" : "完成"} detail={summary.skippedCount ? `${summary.skippedCount} 跳过` : "无跳过节点"} tone={summary.paused ? "warning" : summary.failed ? "error" : "ok"} />
      </div>
      <ObservabilityDetails summary={summary} />
      {hints.length ? (
        <div className="observability-hints">
          {hints.map((hint) => <span key={hint}>{hint}</span>)}
        </div>
      ) : null}
    </section>
  );
}

function ObservabilityDetails({ summary }: { summary: RunObservabilitySummaryData }) {
  return (
    <div className="observability-details">
      <ObservabilityList
        title="错误分类"
        empty="无错误"
        items={summary.errorGroups.map((group) => ({
          key: group.errorType,
          title: `${group.errorType} · ${group.count}`,
          detail: group.nodes.slice(0, 3).join(" / "),
          tone: "error" as const,
        }))}
      />
      <ObservabilityList
        title="慢节点 Top"
        empty="无耗时数据"
        items={summary.slowNodes.map((item) => ({
          key: item.nodeId,
          title: `${item.label} · ${formatDuration(item.durationMs)}`,
          detail: `${item.type} · ${item.status}`,
          tone: item.status === "error" ? "error" as const : "neutral" as const,
        }))}
      />
      <ObservabilityList
        title="State 写入热点"
        empty="无输出字段"
        items={summary.stateDeltaFields.map((field) => ({
          key: field.field,
          title: `${field.field} · ${field.count}`,
          detail: field.nodes.slice(0, 3).join(" / "),
          tone: "neutral" as const,
        }))}
      />
    </div>
  );
}

function ObservabilityList({
  title,
  empty,
  items,
}: {
  title: string;
  empty: string;
  items: Array<{ key: string; title: string; detail: string; tone: "neutral" | "error" }>;
}) {
  return (
    <div className="observability-list">
      <strong>{title}</strong>
      {items.length ? (
        items.slice(0, 5).map((item) => (
          <span key={item.key} className={item.tone === "error" ? "is-error" : ""}>
            <b>{item.title}</b>
            <small>{item.detail || "无详情"}</small>
          </span>
        ))
      ) : (
        <em>{empty}</em>
      )}
    </div>
  );
}

function ObservabilityMetric({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "ok" | "warning" | "error";
}) {
  return (
    <div className={`observability-metric is-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function RuntimeCallSummary({ calls, groups }: { calls: RuntimeCallRecord[]; groups: RuntimeCallGroup[] }) {
  if (!calls.length) return null;
  return (
    <section className="runtime-call-summary">
      <div className="run-section-title">
        <strong>调用链</strong>
        <span>{calls.length} 次 Tool/MCP/Agent 调用</span>
      </div>
      <div className="runtime-call-groups">
        {groups.map((group) => (
          <div key={group.source} className={`runtime-call-group ${group.errorCount ? "is-error" : ""}`}>
            <strong>{group.source}</strong>
            <small>{group.okCount} 成功 / {group.errorCount} 失败 · {formatDuration(group.totalDurationMs)}</small>
            {group.errorTypes.length ? <em>{group.errorTypes.join(", ")}</em> : null}
          </div>
        ))}
      </div>
      <div className="runtime-call-list">
        {calls.slice(0, 10).map((call, index) => (
          <div key={`${call.field}-${index}`} className={`runtime-call-item ${call.ok === false ? "is-error" : ""}`}>
            <span>{call.source}</span>
            <strong>{call.name}</strong>
            <small>
              {call.durationMs != null ? `${formatDuration(call.durationMs)}` : "无耗时"}
              {call.errorType ? ` · ${call.errorType}` : ""}
              {call.field ? ` · ${call.field}` : ""}
            </small>
          </div>
        ))}
      </div>
      {calls.length > 10 ? <small className="runtime-call-summary__more">还有 {calls.length - 10} 次调用未展开。</small> : null}
    </section>
  );
}

function TemplateAcceptanceSummary({ result }: { result: TemplateAcceptanceResult }) {
  return (
    <section className={`template-acceptance ${result.ok ? "is-ok" : "is-warning"}`}>
      <div className="run-section-title">
        <strong>模板验收</strong>
        <span>{result.templateName}</span>
      </div>
      <div className="template-acceptance__status">
        {result.ok ? "通过" : "需检查"}
        <small>{result.finalAnswerPresent ? "final_answer 已生成" : "缺少 final_answer"}</small>
      </div>
      {result.warnings.length ? (
        <div className="template-acceptance__warnings">
          {result.warnings.map((warning) => <span key={warning}>{warning}</span>)}
        </div>
      ) : (
        <p>关键输出字段和 trace 类型均已命中。</p>
      )}
    </section>
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
  const dataShaping = traceRecord(item.dataShaping);
  const approval = traceRecord(item.approval);
  const badges = traceDiagnosticBadges(item);
  const changedFields = outputDeltaFields(item.outputDelta);
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
      {badges.length ? (
        <div className="run-trace-badges">
          {badges.map((badge) => <span key={badge}>{badge}</span>)}
        </div>
      ) : null}
      {changedFields.length ? (
        <div className="run-trace-delta-fields">
          {changedFields.slice(0, 8).map((field) => <span key={field}>state.{field}</span>)}
          {changedFields.length > 8 ? <span>+{changedFields.length - 8}</span> : null}
        </div>
      ) : null}
      {item.detail ? <p>{item.detail}</p> : null}
      <RuntimeDiagnosticsSummary item={item} />
      {approval ? <ApprovalTraceSummary data={approval} paused={item.pause === true} /> : null}
      {dataShaping ? <DataShapingTraceSummary data={dataShaping} /> : null}
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

function ApprovalTraceSummary({ data, paused }: { data: Record<string, unknown>; paused: boolean }) {
  const action = traceText(data.action);
  const comment = traceText(data.comment);
  const prompt = traceText(data.prompt);
  const resumedAt = traceText(data.resumedAt);
  const defaultAction = traceText(data.defaultAction);
  const actions = traceList(data.actions) || traceList(data.availableActions);
  const details = [
    paused ? "状态 等待审批" : action ? `动作 ${action}` : "",
    defaultAction ? `默认 ${defaultAction}` : "",
    actions ? `可选 ${actions}` : "",
    comment ? `备注 ${comment}` : "",
    resumedAt ? `恢复 ${formatTime(resumedAt)}` : "",
    prompt ? `提示 ${prompt}` : "",
  ].filter(Boolean);
  return (
    <div className={`run-trace-meta approval-trace-meta ${paused ? "is-paused" : "is-resumed"}`}>
      <div className="run-trace-meta__title">{paused ? "Human Approval · Paused" : "Human Approval · Resumed"}</div>
      {details.length ? <div className="run-trace-meta__body">{details.join(" · ")}</div> : null}
    </div>
  );
}

function RuntimeDiagnosticsSummary({ item }: { item: RunTraceItem }) {
  const attempts = item.attempts ?? [];
  const errorPayload = traceRecord(item.outputDelta.last_error);
  const details = [
    attempts.length ? `尝试 ${attempts.map(formatAttempt).join(" / ")}` : "",
    item.timeoutSec ? `超时 ${item.timeoutSec}s` : "",
    item.errorPolicy && item.errorPolicy !== "default" ? `错误策略 ${item.errorPolicy}` : "",
    item.itemFailurePolicy ? `Item 失败策略 ${item.itemFailurePolicy}` : "",
    errorPayload ? `错误 ${traceText(errorPayload.errorType) || "runtime"}: ${traceText(errorPayload.message)}` : "",
  ].filter(Boolean);
  if (!details.length) return null;
  return (
    <div className="run-trace-meta diagnostics-trace-meta">
      <div className="run-trace-meta__title">Runtime Diagnostics</div>
      <div className="run-trace-meta__body">{details.join(" · ")}</div>
    </div>
  );
}

function DataShapingTraceSummary({ data }: { data: Record<string, unknown> }) {
  const validation = traceRecord(data.validation);
  const repair = traceRecord(data.repair);
  const changedFields = traceList(data.changedFields);
  const details = [
    traceText(data.outputField) ? `输出 ${traceText(data.outputField)}` : "",
    traceText(data.resultField) ? `结果 ${traceText(data.resultField)}` : "",
    changedFields ? `变更 ${changedFields}` : "",
    validation ? `校验 ${traceBool(validation.valid) ? "valid" : "invalid"}` : "",
    traceText(data.branch) ? `分支 ${traceText(data.branch)}` : "",
    repair ? `修复 ${traceBool(repair.ok) ? "ok" : "failed"}` : "",
  ].filter(Boolean);
  return (
    <div className="run-trace-meta">
      <div className="run-trace-meta__title">Data Shaping · {dataShapingKindLabel(traceText(data.kind))}</div>
      {details.length ? <div className="run-trace-meta__body">{details.join(" · ")}</div> : null}
    </div>
  );
}

function dataShapingKindLabel(kind: string) {
  switch (kind) {
    case "variable_assign":
      return "Variable Assign";
    case "template":
      return "Template";
    case "json_extractor":
      return "JSON Extractor";
    case "json_validator":
      return "JSON Validator";
    default:
      return kind || "Unknown";
  }
}

function traceRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function traceText(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function traceBool(value: unknown) {
  return value === true || value === "true";
}

function traceList(value: unknown) {
  if (!Array.isArray(value)) return "";
  return value.map(traceText).filter(Boolean).join(", ");
}

interface RuntimeCallRecord {
  source: "tool" | "mcp" | "agent" | "unknown";
  name: string;
  field: string;
  durationMs: number | null;
  ok: boolean | null;
  errorType: string;
}

interface RuntimeCallGroup {
  source: RuntimeCallRecord["source"];
  count: number;
  okCount: number;
  errorCount: number;
  totalDurationMs: number;
  errorTypes: string[];
}

interface ErrorGroup {
  errorType: string;
  count: number;
  nodes: string[];
}

interface StateDeltaField {
  field: string;
  count: number;
  nodes: string[];
}

interface RunObservabilitySummaryData {
  statusLabel: string;
  nodeCount: number;
  okCount: number;
  errorCount: number;
  skippedCount: number;
  totalDurationMs: number;
  slowest: RunTraceItem | null;
  retryNodeCount: number;
  timeoutNodeCount: number;
  policyNodeCount: number;
  childTraceCount: number;
  parallelTraceCount: number;
  paused: boolean;
  failed: boolean;
  calls: RuntimeCallRecord[];
  callGroups: RuntimeCallGroup[];
  errorGroups: ErrorGroup[];
  slowNodes: RunTraceItem[];
  stateDeltaFields: StateDeltaField[];
}

function buildRunObservability(result: RunPreviewResult): RunObservabilitySummaryData {
  const trace = result.trace;
  const errorCount = trace.filter((item) => traceHasError(item)).length;
  const skippedCount = trace.filter((item) => item.status === "skipped").length;
  const slowest = trace.reduce<RunTraceItem | null>((current, item) => (!current || item.durationMs > current.durationMs ? item : current), null);
  const status = result.status ?? (errorCount ? "failed" : "completed");
  const calls = collectRuntimeCalls(result);
  return {
    statusLabel: runStatusLabel(status),
    nodeCount: trace.length,
    okCount: trace.filter((item) => item.status === "ok").length,
    errorCount,
    skippedCount,
    totalDurationMs: trace.reduce((sum, item) => sum + item.durationMs, 0),
    slowest,
    retryNodeCount: trace.filter((item) => (item.attempts?.length ?? 0) > 1).length,
    timeoutNodeCount: trace.filter((item) => Boolean(item.timeoutSec) || (item.attempts ?? []).some((attempt) => traceText(attempt.errorType) === "timeout")).length,
    policyNodeCount: trace.filter(traceHasPolicy).length,
    childTraceCount: trace.filter((item) => Boolean(item.parentNodeId)).length,
    parallelTraceCount: trace.filter((item) => item.parallel === true || item.type === "parallel_worker").length,
    paused: status === "paused",
    failed: status === "failed" || errorCount > 0,
    calls,
    callGroups: groupRuntimeCalls(calls),
    errorGroups: collectErrorGroups(trace, calls),
    slowNodes: trace
      .filter((item) => Number.isFinite(item.durationMs) && item.durationMs > 0)
      .slice()
      .sort((a, b) => b.durationMs - a.durationMs)
      .slice(0, 5),
    stateDeltaFields: collectStateDeltaFields(trace),
  };
}

function filterTraceItems(items: RunTraceItem[], filter: TraceFilter, search: string, slowestNodeId: string): RunTraceItem[] {
  const query = search.trim().toLowerCase();
  return items.filter((item) => traceMatchesFilter(item, filter, slowestNodeId) && traceMatchesSearch(item, query));
}

function traceMatchesFilter(item: RunTraceItem, filter: TraceFilter, slowestNodeId: string): boolean {
  switch (filter) {
    case "errors":
      return traceHasError(item);
    case "slow":
      return item.nodeId === slowestNodeId || item.durationMs >= 1000;
    case "tools":
      return ["tool", "http", "parallel_tools", "parallel_worker"].includes(item.type);
    case "mcp":
      return item.type === "mcp_node" || traceContainsRuntimeCall(item, "mcp");
    case "agent":
      return ["agent", "agent_ref", "llm"].includes(item.type) || traceContainsRuntimeCall(item, "agent");
    case "human":
      return item.type === "human_approval" || Boolean(item.approval);
    case "flow":
      return ["condition", "ai_router", "for_each", "merge", "error_handler", "task_splitter"].includes(item.type);
    case "policy":
      return traceHasPolicy(item);
    case "data":
      return Boolean(item.dataShaping) || ["variable_assign", "template", "json_extractor", "json_validator"].includes(item.type);
    case "all":
    default:
      return true;
  }
}

function traceMatchesSearch(item: RunTraceItem, query: string): boolean {
  if (!query) return true;
  return [item.nodeId, item.label, item.type, item.detail, item.parentNodeId ?? "", item.sourceNodeId ?? ""]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

function traceHasError(item: RunTraceItem): boolean {
  return item.status === "error" || Boolean(traceRecord(item.outputDelta.last_error)) || (item.attempts ?? []).some((attempt) => traceText(attempt.status) === "error");
}

function traceHasPolicy(item: RunTraceItem): boolean {
  return Boolean(item.timeoutSec) || Boolean(item.errorPolicy && item.errorPolicy !== "default") || (item.attempts?.length ?? 0) > 1;
}

function traceContainsRuntimeCall(item: RunTraceItem, source: "mcp" | "agent" | "tool"): boolean {
  return collectRuntimeCalls({ mode: "live", valid: true, issues: [], trace: [item], outputState: item.outputDelta }).some((call) => call.source === source);
}

function collectRuntimeCalls(result: RunPreviewResult): RuntimeCallRecord[] {
  const calls: RuntimeCallRecord[] = [];
  const seen = new Set<string>();
  const addCall = (record: Record<string, unknown>, field: string) => {
    const call = runtimeCallFromRecord(record, field);
    const key = `${call.source}:${call.name}:${call.durationMs ?? ""}:${call.errorType}:${stableRuntimeCallKey(record)}`;
    if (!seen.has(key)) {
      seen.add(key);
      calls.push(call);
    }
  };
  const visit = (value: unknown, path: string) => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      if (path.endsWith("_tool_calls") || path.endsWith("_mcp_tool_calls") || path.endsWith("_agent_tool_calls")) {
        value.forEach((item, index) => {
          const record = traceRecord(item);
          if (!record) return;
          addCall(record, `${path}[${index}]`);
        });
      }
      value.forEach((item, index) => visit(item, `${path}[${index}]`));
      return;
    }
    const record = value as Record<string, unknown>;
    if (looksLikeRuntimeCall(record, path)) addCall(record, path);
    for (const [key, nested] of Object.entries(record)) {
      visit(nested, path ? `${path}.${key}` : key);
    }
  };
  visit(result.outputState, "state");
  result.trace.forEach((item, index) => visit(item.outputDelta, `trace[${index}].outputDelta`));
  return calls;
}

function stableRuntimeCallKey(record: Record<string, unknown>): string {
  try {
    return JSON.stringify(record).slice(0, 1200);
  } catch {
    return Object.keys(record).sort().join(",");
  }
}

function looksLikeRuntimeCall(record: Record<string, unknown>, path: string): boolean {
  if (path.endsWith("_tool_calls") || path.endsWith("_mcp_tool_calls") || path.endsWith("_agent_tool_calls")) return false;
  const source = traceText(record.source).toLowerCase();
  if (["tool", "mcp", "agent"].includes(source)) return true;
  if (record.serverName && (record.tool || record.toolName || record.raw || record.content)) return true;
  if (record.agentName && (record.projectId || record.finalAnswer || record.outputState)) return true;
  if (record.toolName && (record.args || record.result || record.durationMs)) return true;
  return false;
}

function runtimeCallFromRecord(record: Record<string, unknown>, field: string): RuntimeCallRecord {
  const source = inferRuntimeCallSource(record, field);
  const name = traceText(record.tool) || traceText(record.toolName) || traceText(record.agentName) || traceText(record.serverName) || traceText(record.name) || "未命名调用";
  return {
    source,
    name,
    field,
    durationMs: typeof record.durationMs === "number" ? record.durationMs : null,
    ok: typeof record.ok === "boolean" ? record.ok : traceText(record.errorType) ? false : null,
    errorType: traceText(record.errorType),
  };
}

function inferRuntimeCallSource(record: Record<string, unknown>, field: string): RuntimeCallRecord["source"] {
  const source = traceText(record.source).toLowerCase();
  if (source === "mcp" || field.includes("_mcp_tool_calls") || record.serverName) return "mcp";
  if (source === "agent" || field.includes("_agent_tool_calls") || record.agentName || record.projectId) return "agent";
  if (source === "tool" || field.includes("_tool_calls")) return "tool";
  return "unknown";
}

function groupRuntimeCalls(calls: RuntimeCallRecord[]): RuntimeCallGroup[] {
  const order: RuntimeCallRecord["source"][] = ["tool", "mcp", "agent", "unknown"];
  const groups = new Map<RuntimeCallRecord["source"], RuntimeCallGroup>();
  calls.forEach((call) => {
    const group = groups.get(call.source) ?? {
      source: call.source,
      count: 0,
      okCount: 0,
      errorCount: 0,
      totalDurationMs: 0,
      errorTypes: [],
    };
    group.count += 1;
    if (call.ok === false) group.errorCount += 1;
    else if (call.ok === true) group.okCount += 1;
    if (call.durationMs != null) group.totalDurationMs += call.durationMs;
    if (call.errorType && !group.errorTypes.includes(call.errorType)) group.errorTypes.push(call.errorType);
    groups.set(call.source, group);
  });
  return order.map((source) => groups.get(source)).filter((group): group is RuntimeCallGroup => Boolean(group));
}

function collectErrorGroups(trace: RunTraceItem[], calls: RuntimeCallRecord[]): ErrorGroup[] {
  const groups = new Map<string, ErrorGroup>();
  const add = (errorType: string, nodeLabel: string) => {
    const key = errorType || "runtime_error";
    const group = groups.get(key) ?? { errorType: key, count: 0, nodes: [] };
    group.count += 1;
    if (nodeLabel && !group.nodes.includes(nodeLabel)) group.nodes.push(nodeLabel);
    groups.set(key, group);
  };
  trace.forEach((item) => {
    const lastError = traceRecord(item.outputDelta.last_error);
    if (item.status === "error" || lastError) add(traceText(lastError?.errorType) || "node_error", item.label);
    (item.attempts ?? []).forEach((attempt) => {
      if (traceText(attempt.status) === "error") add(traceText(attempt.errorType) || "attempt_error", item.label);
    });
  });
  calls.forEach((call) => {
    if (call.ok === false) add(call.errorType || "call_error", call.name);
  });
  return [...groups.values()].sort((a, b) => b.count - a.count).slice(0, 6);
}

function collectStateDeltaFields(trace: RunTraceItem[]): StateDeltaField[] {
  const fields = new Map<string, StateDeltaField>();
  trace.forEach((item) => {
    outputDeltaFields(item.outputDelta).forEach((field) => {
      const current = fields.get(field) ?? { field, count: 0, nodes: [] };
      current.count += 1;
      if (!current.nodes.includes(item.label)) current.nodes.push(item.label);
      fields.set(field, current);
    });
  });
  return [...fields.values()].sort((a, b) => b.count - a.count || a.field.localeCompare(b.field)).slice(0, 8);
}

function outputDeltaFields(delta: Record<string, unknown>): string[] {
  return Object.keys(delta).filter((field) => field !== "_glg_error_from" && !field.startsWith("__"));
}

function traceDiagnosticBadges(item: RunTraceItem): string[] {
  const badges = [
    item.parentNodeId ? `Parent ${item.parentNodeId}` : "",
    item.iterationIndex != null ? `Item #${item.iterationIndex}` : "",
    (item.attempts?.length ?? 0) > 1 ? `Retry x${item.attempts?.length}` : "",
    item.timeoutSec ? `Timeout ${item.timeoutSec}s` : "",
    item.errorPolicy && item.errorPolicy !== "default" ? `Policy ${item.errorPolicy}` : "",
    item.parallel ? "Parallel" : "",
    item.itemFailurePolicy ? `Item ${item.itemFailurePolicy}` : "",
    item.pause ? "Pause" : "",
    item.dataShaping ? "Data" : "",
  ].filter(Boolean);
  return badges.slice(0, 8);
}

function formatAttempt(value: Record<string, unknown>, index: number) {
  const status = traceText(value.status) || "unknown";
  const duration = typeof value.durationMs === "number" ? formatDuration(value.durationMs) : "无耗时";
  const error = traceText(value.errorType);
  return `#${index + 1} ${status} ${duration}${error ? ` ${error}` : ""}`;
}

function observabilityHints(summary: RunObservabilitySummaryData): string[] {
  const hints: string[] = [];
  if (summary.paused) hints.push("运行已暂停：先处理 Human Approval 卡片再恢复后续流程。");
  if (summary.errorCount) hints.push("存在失败节点：切到“错误”筛选查看 last_error 和 attempts。");
  if (summary.retryNodeCount) hints.push("存在重试节点：检查 Runtime Diagnostics 中每次尝试的错误类型。");
  if (summary.slowest && summary.slowest.durationMs >= 1000) hints.push(`最慢节点是 ${summary.slowest.label}，耗时 ${formatDuration(summary.slowest.durationMs)}。`);
  if (summary.calls.some((call) => call.ok === false)) hints.push("调用链中存在失败的 Tool/MCP/Agent 调用。");
  return hints.slice(0, 4);
}

function callSummaryLabel(calls: RuntimeCallRecord[]) {
  const mcp = calls.filter((call) => call.source === "mcp").length;
  const agent = calls.filter((call) => call.source === "agent").length;
  const tool = calls.filter((call) => call.source === "tool").length;
  return [`${tool} Tool`, `${mcp} MCP`, `${agent} Agent`].join(" / ");
}

function formatDuration(value: number) {
  if (!Number.isFinite(value)) return "0ms";
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)}s`;
  return `${Math.round(value)}ms`;
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

function runStatusLabel(status: RunPreviewResult["status"]) {
  switch (status) {
    case "paused":
      return "待审批";
    case "failed":
      return "失败";
    case "completed":
    default:
      return "完成";
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
