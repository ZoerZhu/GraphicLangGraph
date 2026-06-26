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
