import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BotMessageSquare,
  CopyPlus,
  Download,
  HardDrive,
  History,
  LayoutTemplate,
  Map,
  Plus,
  Play,
  RotateCcw,
  Save,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { ProjectHistoryRecord, RuntimeEnvironmentConfig } from "../types";

export function TopBar() {
  const project = useProjectStore((state) => state.project);
  const status = useProjectStore((state) => state.status);
  const historyOpen = useProjectStore((state) => state.historyOpen);
  const templatesOpen = useProjectStore((state) => state.templatesOpen);
  const assistantOpen = useProjectStore((state) => state.assistantOpen);
  const runActive = useProjectStore((state) => state.runActive);
  const runRunning = useProjectStore((state) => state.runRunning);
  const miniMapOpen = useProjectStore((state) => state.miniMapOpen);
  const workspaceRuntimeEnvironments = useProjectStore((state) => state.workspaceRuntimeEnvironments);
  const backToManager = useProjectStore((state) => state.backToManager);
  const updateProjectMeta = useProjectStore((state) => state.updateProjectMeta);
  const updateWorkspaceRuntimeEnvironments = useProjectStore((state) => state.updateWorkspaceRuntimeEnvironments);
  const setProjectRuntimeEnvironmentId = useProjectStore((state) => state.setProjectRuntimeEnvironmentId);
  const save = useProjectStore((state) => state.save);
  const validate = useProjectStore((state) => state.validate);
  const exportZip = useProjectStore((state) => state.exportZip);
  const toggleHistory = useProjectStore((state) => state.toggleHistory);
  const toggleTemplates = useProjectStore((state) => state.toggleTemplates);
  const toggleAssistant = useProjectStore((state) => state.toggleAssistant);
  const toggleRunPanel = useProjectStore((state) => state.toggleRunPanel);
  const toggleMiniMap = useProjectStore((state) => state.toggleMiniMap);
  const cancelRun = useProjectStore((state) => state.cancelRun);
  const [runtimeModalOpen, setRuntimeModalOpen] = useState(false);
  const selectedRuntimeEnvironment = pickRuntimeEnvironment(workspaceRuntimeEnvironments, project?.project.runtimeEnvironmentId ?? "");

  function selectRuntimeEnvironment(id: string) {
    setProjectRuntimeEnvironmentId(id);
    void save();
  }

  return (
    <>
      <header className="topbar glass-panel interactive-surface">
        <div className="brand">
          <div className="brand-mark">GL</div>
          <div className="brand-fields">
            <input
              className="title-input"
              aria-label="Agent 名称"
              title="修改 Agent 名称"
              disabled={runActive}
              value={project?.project.name ?? "GraphicLangGraph"}
              onChange={(event) => updateProjectMeta({ name: event.target.value })}
              onBlur={() => void save()}
            />
            <input
              className="description-input"
              aria-label="Agent 描述"
              disabled={runActive}
              value={project?.project.description ?? ""}
              onChange={(event) => updateProjectMeta({ description: event.target.value })}
              onBlur={() => void save()}
              placeholder="Agent 描述..."
            />
          </div>
        </div>
        <div className="topbar-actions">
          <span className="topbar-status">{status}</span>
          <div className="runtime-selector">
            <HardDrive size={15} />
            <select
              aria-label="运行环境"
              disabled={runRunning || workspaceRuntimeEnvironments.length === 0}
              title="选择 Agent 运行环境"
              value={selectedRuntimeEnvironment?.id ?? ""}
              onChange={(event) => selectRuntimeEnvironment(event.target.value)}
            >
              {workspaceRuntimeEnvironments.map((environment) => (
                <option key={environment.id} value={environment.id}>
                  {environment.name}
                </option>
              ))}
            </select>
            <button className="icon-only" disabled={runRunning} onClick={() => setRuntimeModalOpen(true)} title="配置运行环境" type="button">
              <Settings2 size={15} />
            </button>
          </div>
          <button onClick={() => void backToManager()} title="返回管理">
            <ArrowLeft size={16} />
            <span>管理</span>
          </button>
          <button onClick={() => void save()} title="保存">
            <Save size={16} />
            <span>保存</span>
          </button>
          <button onClick={() => void validate()} title="校验">
            <ShieldCheck size={16} />
            <span>校验</span>
          </button>
          <button
            className={`run-toggle ${runActive ? "is-active" : ""} ${runRunning ? "is-running" : ""}`}
            onClick={runRunning ? cancelRun : toggleRunPanel}
            title={runRunning ? "中断当前运行" : runActive ? "退出运行模式" : "进入运行模式"}
          >
            {runRunning ? <Square size={16} /> : <Play size={16} />}
            <span>{runRunning ? "中断" : runActive ? "退出运行" : "运行"}</span>
          </button>
          <button className={miniMapOpen ? "is-active" : ""} onClick={toggleMiniMap} title="显示或隐藏小地图">
            <Map size={16} />
            <span>地图</span>
          </button>
          <button className={templatesOpen ? "is-active" : ""} disabled={runActive} onClick={toggleTemplates} title={runActive ? "运行模式下不可用" : "模板库"}>
            <LayoutTemplate size={16} />
            <span>模板</span>
          </button>
          <button className={assistantOpen ? "is-active" : ""} disabled={runActive} onClick={toggleAssistant} title={runActive ? "运行模式下不可用" : "搭建助手"}>
            <BotMessageSquare size={16} />
            <span>助手</span>
          </button>
          <button className={historyOpen ? "is-active" : ""} disabled={runActive} onClick={toggleHistory} title={runActive ? "运行模式下不可用" : "历史记录"}>
            <History size={16} />
            <span>历史</span>
          </button>
          <button className="primary" onClick={() => void exportZip()} title="导出 ZIP">
            <Download size={16} />
            <span>导出</span>
          </button>
        </div>
      </header>
      {historyOpen ? <HistoryPanel /> : null}
      {runtimeModalOpen ? (
        <RuntimeEnvironmentModal
          environments={workspaceRuntimeEnvironments}
          selectedId={selectedRuntimeEnvironment?.id ?? ""}
          onClose={() => setRuntimeModalOpen(false)}
          onSave={async (items, selectedId) => {
            await updateWorkspaceRuntimeEnvironments(items);
            setProjectRuntimeEnvironmentId(selectedId);
            await save();
            setRuntimeModalOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function RuntimeEnvironmentModal({
  environments,
  selectedId,
  onClose,
  onSave,
}: {
  environments: RuntimeEnvironmentConfig[];
  selectedId: string;
  onClose: () => void;
  onSave: (items: RuntimeEnvironmentConfig[], selectedId: string) => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<RuntimeEnvironmentConfig[]>(() => normalizeRuntimeEnvironments(environments));
  const [activeId, setActiveId] = useState(selectedId || drafts[0]?.id || "");
  const active = useMemo(() => drafts.find((item) => item.id === activeId) ?? drafts[0], [activeId, drafts]);

  useEffect(() => {
    const normalized = normalizeRuntimeEnvironments(environments);
    setDrafts(normalized);
    setActiveId(selectedId || normalized[0]?.id || "");
  }, [environments, selectedId]);

  function updateActive(patch: Partial<RuntimeEnvironmentConfig>) {
    if (!active) return;
    setDrafts((current) => current.map((item) => (item.id === active.id ? { ...item, ...patch } : item)));
  }

  function addEnvironment() {
    const next = newRuntimeEnvironment();
    setDrafts((current) => [...current, next]);
    setActiveId(next.id);
  }

  function deleteEnvironment() {
    if (!active || drafts.length <= 1) return;
    const next = drafts.filter((item) => item.id !== active.id);
    setDrafts(next);
    setActiveId(next[0]?.id ?? "");
  }

  if (!active) return null;

  return (
    <div className="app-modal-backdrop" role="presentation">
      <section className="app-modal runtime-modal glass-panel" role="dialog" aria-modal="true" aria-label="运行环境配置">
        <div className="runtime-modal__head">
          <div>
            <strong>运行环境</strong>
            <span>配置本地后端执行工具时可访问的文件目录和网络边界。</span>
          </div>
          <button className="icon-only panel-close" onClick={onClose} title="关闭" type="button">
            <X size={15} />
          </button>
        </div>
        <div className="runtime-modal__body">
          <aside className="runtime-modal__list">
            {drafts.map((environment) => (
              <button
                key={environment.id}
                className={environment.id === active.id ? "is-active" : ""}
                onClick={() => setActiveId(environment.id)}
                type="button"
              >
                <strong>{environment.name}</strong>
                <small>{environment.kind === "local_backend" ? "本地后端" : environment.kind}</small>
              </button>
            ))}
            <button onClick={addEnvironment} type="button">
              <Plus size={14} />
              <span>新增环境</span>
            </button>
          </aside>
          <div className="runtime-modal__form">
            <label className="field">
              <span>名称</span>
              <input value={active.name} onChange={(event) => updateActive({ name: event.target.value })} />
            </label>
            <label className="field">
              <span>允许文件根目录</span>
              <textarea
                rows={4}
                value={jsonListToLines(active.allowedRootsJson)}
                onChange={(event) => updateActive({ allowedRootsJson: event.target.value })}
                placeholder={"./\nE:\\data"}
              />
            </label>
            <label className="checkbox-row runtime-modal__toggle">
              <input checked={active.networkEnabled} onChange={(event) => updateActive({ networkEnabled: event.target.checked })} type="checkbox" />
              <span>允许网络访问</span>
            </label>
            <label className="checkbox-row runtime-modal__toggle">
              <input
                checked={active.allowAllHosts === true}
                disabled={!active.networkEnabled}
                onChange={(event) => updateActive({
                  allowAllHosts: event.target.checked,
                  allowedHostsJson: event.target.checked ? "[]" : JSON.stringify(["api.duckduckgo.com"], null, 2),
                })}
                type="checkbox"
              />
              <span>允许全部域名</span>
            </label>
            <label className="field">
              <span>允许访问域名</span>
              <textarea
                disabled={!active.networkEnabled || active.allowAllHosts === true}
                rows={3}
                value={jsonListToLines(active.allowedHostsJson)}
                onChange={(event) => updateActive({ allowedHostsJson: event.target.value })}
                placeholder={"mcp.exa.ai\napi.duckduckgo.com"}
              />
              <small>多个域名可用换行、逗号或分号分隔；支持 *.example.com。</small>
            </label>
            <div className="runtime-modal__grid">
              <label className="field">
                <span>单次文件最大字节</span>
                <input type="number" min={1} value={active.maxFileBytes} onChange={(event) => updateActive({ maxFileBytes: Number(event.target.value || 1) })} />
              </label>
              <label className="field">
                <span>单次 HTTP 最大字节</span>
                <input type="number" min={1} value={active.maxHttpBytes} onChange={(event) => updateActive({ maxHttpBytes: Number(event.target.value || 1) })} />
              </label>
            </div>
            <label className="checkbox-row runtime-modal__toggle">
              <input checked={active.allowDirectEdits} onChange={(event) => updateActive({ allowDirectEdits: event.target.checked })} type="checkbox" />
              <span>允许高级直接编辑</span>
            </label>
            <label className="field">
              <span>命令白名单</span>
              <textarea
                rows={5}
                value={jsonListToLines(active.allowedCommandProfilesJson)}
                onChange={(event) => updateActive({ allowedCommandProfilesJson: event.target.value })}
                placeholder="python -m pytest"
              />
            </label>
            <div className="runtime-modal__grid">
              <label className="field">
                <span>Patch 最大字节</span>
                <input type="number" min={1} value={active.maxPatchBytes} onChange={(event) => updateActive({ maxPatchBytes: Number(event.target.value || 1) })} />
              </label>
              <label className="field">
                <span>命令输出最大字节</span>
                <input type="number" min={1} value={active.maxCommandOutputBytes} onChange={(event) => updateActive({ maxCommandOutputBytes: Number(event.target.value || 1) })} />
              </label>
            </div>
            <label className="field">
              <span>说明</span>
              <textarea rows={2} value={active.description} onChange={(event) => updateActive({ description: event.target.value })} />
            </label>
          </div>
        </div>
        <div className="runtime-modal__actions">
          <button disabled={drafts.length <= 1} onClick={deleteEnvironment} type="button">
            <Trash2 size={15} />
            <span>删除当前</span>
          </button>
          <span />
          <button onClick={onClose} type="button">取消</button>
          <button className="primary" onClick={() => void onSave(normalizeRuntimeEnvironments(drafts), active.id)} type="button">
            <Save size={15} />
            <span>保存环境</span>
          </button>
        </div>
      </section>
    </div>
  );
}

function HistoryPanel() {
  const records = useProjectStore((state) => state.historyRecords);
  const selectedHistoryId = useProjectStore((state) => state.selectedHistoryId);
  const closeHistory = useProjectStore((state) => state.closeHistory);
  const selectHistoryRecord = useProjectStore((state) => state.selectHistoryRecord);
  const restoreHistoryRecord = useProjectStore((state) => state.restoreHistoryRecord);
  const exportHistoryAsProject = useProjectStore((state) => state.exportHistoryAsProject);
  const deleteHistoryRecord = useProjectStore((state) => state.deleteHistoryRecord);
  const selected = records.find((record) => record.id === selectedHistoryId) ?? records[0] ?? null;

  return (
    <aside className="history-panel glass-panel">
      <div className="panel-title">
        <span>历史记录</span>
        <button className="icon-only panel-close" onClick={closeHistory} title="关闭历史记录" type="button">
          <X size={15} />
        </button>
      </div>
      {records.length === 0 ? (
        <div className="history-empty">还没有保存记录。点击保存后会生成第一条历史快照。</div>
      ) : (
        <>
          <div className="history-actions">
            <button disabled={!selected} onClick={() => selected && void restoreHistoryRecord(selected.id)} type="button">
              <RotateCcw size={15} />
              <span>回退到选中记录</span>
            </button>
            <button className="primary" disabled={!selected} onClick={() => selected && void exportHistoryAsProject(selected.id)} type="button">
              <CopyPlus size={15} />
              <span>导出为新 {selected?.kind === "agents" ? "Agents" : "Agent"}</span>
            </button>
          </div>
          <div className="history-list">
            {records.map((record) => (
              <HistoryRecordRow
                key={record.id}
                record={record}
                selected={record.id === (selected?.id ?? selectedHistoryId)}
                onSelect={() => selectHistoryRecord(record.id)}
                onRestore={() => void restoreHistoryRecord(record.id)}
                onExport={() => void exportHistoryAsProject(record.id)}
                onDelete={() => deleteHistoryRecord(record.id)}
              />
            ))}
          </div>
        </>
      )}
    </aside>
  );
}

function HistoryRecordRow({
  record,
  selected,
  onSelect,
  onRestore,
  onExport,
  onDelete,
}: {
  record: ProjectHistoryRecord;
  selected: boolean;
  onSelect: () => void;
  onRestore: () => void;
  onExport: () => void;
  onDelete: () => void;
}) {
  return (
    <article className={`history-record ${selected ? "is-selected" : ""}`}>
      <button className="history-record__main" onClick={onSelect} type="button">
        <strong>{record.name}</strong>
        <span>{record.description}</span>
        <small>{formatTime(record.createdAt)} · {record.nodeCount} 节点 · {record.edgeCount} 连线</small>
      </button>
      {selected ? (
        <div className="history-record__actions">
          <button onClick={onRestore} title="回退到该记录" type="button">
            <RotateCcw size={14} />
          </button>
          <button onClick={onExport} title="导出为新项目" type="button">
            <CopyPlus size={14} />
          </button>
          <button className="danger" onClick={onDelete} title="删除该历史记录" type="button">
            <Trash2 size={14} />
          </button>
        </div>
      ) : null}
    </article>
  );
}

function pickRuntimeEnvironment(environments: RuntimeEnvironmentConfig[], selectedId: string) {
  return environments.find((environment) => environment.id === selectedId) ?? environments[0] ?? null;
}

function normalizeRuntimeEnvironments(environments: RuntimeEnvironmentConfig[]) {
  const normalized = environments.length ? environments : [newRuntimeEnvironment("runtime_local_backend", "本地后端")];
  return normalized.map((environment) => ({
    ...environment,
    id: environment.id || createRuntimeId(),
    name: environment.name.trim() || "本地后端",
    kind: "local_backend",
    description: environment.description || "由当前 FastAPI 后端所在机器执行工具。",
    allowedRootsJson: linesToJsonList(jsonListToLines(environment.allowedRootsJson), ["./"]),
    allowAllHosts: environment.allowAllHosts === true,
    allowedHostsJson: environment.allowAllHosts === true ? "[]" : linesToJsonList(jsonListToLines(environment.allowedHostsJson), ["api.duckduckgo.com"]),
    maxFileBytes: Math.max(1, Number(environment.maxFileBytes || 1048576)),
    maxHttpBytes: Math.max(1, Number(environment.maxHttpBytes || 262144)),
    networkEnabled: environment.networkEnabled !== false,
    allowDirectEdits: environment.allowDirectEdits === true,
    allowedCommandProfilesJson: linesToJsonList(jsonListToLines(environment.allowedCommandProfilesJson), defaultCommandProfiles()),
    maxPatchBytes: Math.max(1, Number(environment.maxPatchBytes || 524288)),
    maxCommandOutputBytes: Math.max(1, Number(environment.maxCommandOutputBytes || 262144)),
  }));
}

function newRuntimeEnvironment(id = createRuntimeId(), name = "本地后端"): RuntimeEnvironmentConfig {
  return {
    id,
    name,
    kind: "local_backend",
    description: "由当前 FastAPI 后端所在机器执行工具。",
    allowedRootsJson: JSON.stringify(["./"], null, 2),
    networkEnabled: true,
    allowAllHosts: false,
    allowedHostsJson: JSON.stringify(["api.duckduckgo.com"], null, 2),
    maxFileBytes: 1048576,
    maxHttpBytes: 262144,
    allowDirectEdits: false,
    allowedCommandProfilesJson: JSON.stringify(defaultCommandProfiles(), null, 2),
    maxPatchBytes: 524288,
    maxCommandOutputBytes: 262144,
  };
}

function defaultCommandProfiles(): string[] {
  return [
    "git status",
    "git diff",
    "git diff --check",
    "npm run build",
    "npm test",
    "npm run lint",
    "python -m pytest",
    "pytest",
    "python -m compileall",
  ];
}

function createRuntimeId() {
  return `runtime_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
}

function jsonListToLines(value: string) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.map((item) => String(item)).join("\n") : "";
  } catch {
    return value;
  }
}

function linesToJsonList(value: string, fallback: string[]) {
  const items = value.split(/[;,\n]+/).map((item) => item.trim()).filter(Boolean);
  return JSON.stringify(items.length ? items : fallback, null, 2);
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleString("zh-CN", { hour12: false });
}
