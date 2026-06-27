import { LayoutTemplate, X } from "lucide-react";
import { PROJECT_TEMPLATES } from "../lib/templates";
import { useProjectStore } from "../store/projectStore";

export function TemplatePanel() {
  const open = useProjectStore((state) => state.templatesOpen);
  const closeTemplates = useProjectStore((state) => state.closeTemplates);
  const applyTemplate = useProjectStore((state) => state.applyTemplate);

  if (!open) return null;

  return (
    <aside className="mvp-panel template-panel glass-panel">
      <div className="panel-title">
        <span>模板库</span>
        <button className="icon-only panel-close" onClick={closeTemplates} title="关闭模板库" type="button">
          <X size={15} />
        </button>
      </div>
      <div className="template-list">
        {PROJECT_TEMPLATES.map((template) => (
          <article key={template.id} className="template-card">
            <span className="template-card__icon">
              <LayoutTemplate size={17} />
            </span>
            <div>
              <strong>{template.name}</strong>
              <p>{template.description}</p>
              <small>{template.nodes.length} 节点 · {template.edges.length} 连线{template.sampleInput ? " · 含样例输入" : ""}</small>
              <div className="template-card__tags">
                <span>{template.requiresModel ? "需要模型" : "无需模型"}</span>
                <span>{template.requiresNetwork ? "需要网络" : "本地/mock"}</span>
                <span>{template.recommendedRunMode === "live" ? "推荐真实运行" : "推荐 dry-run"}</span>
              </div>
              <div className="template-card__outputs">
                {template.expectedOutputFields.slice(0, 4).map((field) => <span key={field}>{field}</span>)}
              </div>
              <div className="template-card__trace">
                {template.expectedTraceTypes.slice(0, 6).map((type) => <span key={type}>{type}</span>)}
              </div>
              {template.sampleInput ? (
                <details className="template-card__sample">
                  <summary>样例输入</summary>
                  <pre>{JSON.stringify(template.sampleInput, null, 2)}</pre>
                </details>
              ) : null}
            </div>
            <button className="primary" onClick={() => void applyTemplate(template.id)} type="button">
              应用
            </button>
          </article>
        ))}
      </div>
    </aside>
  );
}
