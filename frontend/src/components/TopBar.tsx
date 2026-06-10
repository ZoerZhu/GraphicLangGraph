import { Download, Save, Settings, ShieldCheck } from "lucide-react";
import { useProjectStore } from "../store/projectStore";

export function TopBar() {
  const project = useProjectStore((state) => state.project);
  const save = useProjectStore((state) => state.save);
  const validate = useProjectStore((state) => state.validate);
  const exportZip = useProjectStore((state) => state.exportZip);

  return (
    <header className="topbar glass-panel">
      <div className="brand">
        <div className="brand-mark">GL</div>
        <div>
          <h1>{project?.project.name ?? "GraphicLangGraph"}</h1>
          <p>中文可视化 LangGraph Agent 生成器</p>
        </div>
      </div>
      <div className="topbar-actions">
        <button onClick={() => void save()} title="保存">
          <Save size={16} />
          <span>保存</span>
        </button>
        <button onClick={() => void validate()} title="校验">
          <ShieldCheck size={16} />
          <span>校验</span>
        </button>
        <button className="primary" onClick={() => void exportZip()} title="导出 ZIP">
          <Download size={16} />
          <span>导出</span>
        </button>
        <button className="icon-only" title="设置">
          <Settings size={16} />
        </button>
      </div>
    </header>
  );
}

