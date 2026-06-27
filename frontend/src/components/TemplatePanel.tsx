import { CheckCircle2, LayoutTemplate, X } from "lucide-react";
import { useMemo, useState } from "react";
import {
  getProjectTemplateDependencyLabels,
  getProjectTemplateScene,
  PROJECT_TEMPLATE_SCENES,
  PROJECT_TEMPLATES,
  type ProjectTemplateSceneId,
} from "../lib/templates";
import { useProjectStore } from "../store/projectStore";

export function TemplatePanel() {
  const open = useProjectStore((state) => state.templatesOpen);
  const closeTemplates = useProjectStore((state) => state.closeTemplates);
  const applyTemplate = useProjectStore((state) => state.applyTemplate);
  const [selectedScene, setSelectedScene] = useState<ProjectTemplateSceneId | "all">("all");
  const sceneGroups = useMemo(
    () => PROJECT_TEMPLATE_SCENES.map((scene) => ({
      scene,
      templates: PROJECT_TEMPLATES.filter((template) => template.sceneId === scene.id),
    })).filter((group) => selectedScene === "all" || group.scene.id === selectedScene),
    [selectedScene],
  );

  if (!open) return null;

  return (
    <aside className="mvp-panel template-panel glass-panel">
      <div className="panel-title">
        <span>场景库</span>
        <button className="icon-only panel-close" onClick={closeTemplates} title="关闭模板库" type="button">
          <X size={15} />
        </button>
      </div>
      <p className="template-panel__subtitle">按真实业务场景套用可运行 Workflow，保留依赖、样例输入和 trace 验收口径。</p>
      <div className="scene-filter" role="tablist" aria-label="场景筛选">
        <button
          className={selectedScene === "all" ? "active" : ""}
          onClick={() => setSelectedScene("all")}
          role="tab"
          type="button"
        >
          全部
        </button>
        {PROJECT_TEMPLATE_SCENES.map((scene) => (
          <button
            key={scene.id}
            className={selectedScene === scene.id ? "active" : ""}
            onClick={() => setSelectedScene(scene.id)}
            role="tab"
            type="button"
          >
            {scene.name}
          </button>
        ))}
      </div>
      <div className="template-list template-list--scenes">
        {sceneGroups.map(({ scene, templates }) => (
          <section key={scene.id} className="scene-section">
            <div className="scene-section__head">
              <strong>{scene.name}</strong>
              <span>{scene.description}</span>
            </div>
            {templates.map((template) => {
              const templateScene = getProjectTemplateScene(template);
              const dependencyLabels = getProjectTemplateDependencyLabels(template);
              return (
                <article key={template.id} className="template-card">
                  <span className="template-card__icon">
                    <LayoutTemplate size={17} />
                  </span>
                  <div>
                    <div className="template-card__heading">
                      <strong>{template.name}</strong>
                      <span>{templateScene.name}</span>
                    </div>
                    <p>{template.description}</p>
                    <p className="template-card__usecase">{template.useCase}</p>
                    <small>{template.nodes.length} 节点 · {template.edges.length} 连线{template.sampleInput ? " · 含样例输入" : ""}</small>
                    <div className="template-card__recommend">
                      {template.recommendedFor.map((item) => <span key={item}>{item}</span>)}
                    </div>
                    <div className="template-card__tags">
                      {dependencyLabels.map((label) => <span key={label}>{label}</span>)}
                    </div>
                    <div className="template-card__acceptance">
                      <CheckCircle2 size={13} />
                      <span>{template.acceptanceSummary}</span>
                    </div>
                    <div className="template-card__outputs">
                      {template.expectedOutputFields.slice(0, 5).map((field) => <span key={field}>{field}</span>)}
                    </div>
                    <div className="template-card__trace">
                      {template.expectedTraceTypes.slice(0, 6).map((type) => <span key={type}>{type}</span>)}
                    </div>
                    {template.setupNotes?.length ? (
                      <ul className="template-card__notes">
                        {template.setupNotes.map((note) => <li key={note}>{note}</li>)}
                      </ul>
                    ) : null}
                    {template.sampleInput ? (
                      <details className="template-card__sample">
                        <summary>样例输入</summary>
                        <pre>{JSON.stringify(template.sampleInput, null, 2)}</pre>
                      </details>
                    ) : null}
                  </div>
                  <button className="primary" onClick={() => void applyTemplate(template.id)} type="button">
                    套用
                  </button>
                </article>
              );
            })}
          </section>
        ))}
      </div>
    </aside>
  );
}
