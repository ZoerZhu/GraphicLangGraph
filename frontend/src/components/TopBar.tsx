import {
  ArrowLeft,
  BotMessageSquare,
  CopyPlus,
  Download,
  History,
  LayoutTemplate,
  Map,
  Play,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { ProjectHistoryRecord } from "../types";

export function TopBar() {
  const project = useProjectStore((state) => state.project);
  const status = useProjectStore((state) => state.status);
  const historyOpen = useProjectStore((state) => state.historyOpen);
  const templatesOpen = useProjectStore((state) => state.templatesOpen);
  const assistantOpen = useProjectStore((state) => state.assistantOpen);
  const runOpen = useProjectStore((state) => state.runOpen);
  const miniMapOpen = useProjectStore((state) => state.miniMapOpen);
  const backToManager = useProjectStore((state) => state.backToManager);
  const updateProjectMeta = useProjectStore((state) => state.updateProjectMeta);
  const save = useProjectStore((state) => state.save);
  const validate = useProjectStore((state) => state.validate);
  const exportZip = useProjectStore((state) => state.exportZip);
  const toggleHistory = useProjectStore((state) => state.toggleHistory);
  const toggleTemplates = useProjectStore((state) => state.toggleTemplates);
  const toggleAssistant = useProjectStore((state) => state.toggleAssistant);
  const toggleRunPanel = useProjectStore((state) => state.toggleRunPanel);
  const toggleMiniMap = useProjectStore((state) => state.toggleMiniMap);

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
              value={project?.project.name ?? "GraphicLangGraph"}
              onChange={(event) => updateProjectMeta({ name: event.target.value })}
              onBlur={() => void save()}
            />
            <input
              className="description-input"
              aria-label="Agent 描述"
              value={project?.project.description ?? ""}
              onChange={(event) => updateProjectMeta({ description: event.target.value })}
              onBlur={() => void save()}
              placeholder="Agent 描述..."
            />
          </div>
        </div>
        <div className="topbar-actions">
          <span className="topbar-status">{status}</span>
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
          <button className={runOpen ? "is-active" : ""} onClick={toggleRunPanel} title="运行预览">
            <Play size={16} />
            <span>运行</span>
          </button>
          <button className={miniMapOpen ? "is-active" : ""} onClick={toggleMiniMap} title="显示或隐藏小地图">
            <Map size={16} />
            <span>地图</span>
          </button>
          <button className={templatesOpen ? "is-active" : ""} onClick={toggleTemplates} title="模板库">
            <LayoutTemplate size={16} />
            <span>模板</span>
          </button>
          <button className={assistantOpen ? "is-active" : ""} onClick={toggleAssistant} title="搭建助手">
            <BotMessageSquare size={16} />
            <span>助手</span>
          </button>
          <button className={historyOpen ? "is-active" : ""} onClick={toggleHistory} title="历史记录">
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
    </>
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

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleString("zh-CN", { hour12: false });
}
