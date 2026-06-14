import { Send, WandSparkles, X } from "lucide-react";
import { useState } from "react";
import { PROJECT_TEMPLATES } from "../lib/templates";
import { useProjectStore } from "../store/projectStore";

export function AssistantPanel() {
  const open = useProjectStore((state) => state.assistantOpen);
  const closeAssistant = useProjectStore((state) => state.closeAssistant);
  const applyAssistantPrompt = useProjectStore((state) => state.applyAssistantPrompt);
  const [prompt, setPrompt] = useState("帮我做一个客服 Agent，先识别订单/退款/其他问题，再处理并回复用户。");
  const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null);
  const previewTemplate = PROJECT_TEMPLATES.find((template) => template.id === previewTemplateId) ?? null;

  if (!open) return null;

  return (
    <aside className="mvp-panel assistant-panel glass-panel">
      <div className="panel-title">
        <span>搭建助手</span>
        <button className="icon-only panel-close" onClick={closeAssistant} title="关闭搭建助手" type="button">
          <X size={15} />
        </button>
      </div>
      <div className="assistant-intro">
        <WandSparkles size={18} />
        <p>第一版助手会根据中文需求选择合适模板并生成初始画布，后续再接入多轮澄清和局部修复。</p>
      </div>
      <textarea
        rows={7}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder="例如：帮我做一个知识库问答 Agent，先改写问题，再检索文档，最后回答。"
      />
      <div className="assistant-actions">
        <button onClick={() => {
          setPrompt("帮我做一个知识库问答 Agent，先改写问题，再检索文档，最后回答。");
          setPreviewTemplateId(null);
        }} type="button">
          知识库问答
        </button>
        <button onClick={() => {
          setPrompt("帮我做一个售后客服 Agent，识别订单/退款/其他问题，退款需要人工审批。");
          setPreviewTemplateId(null);
        }} type="button">
          客服工单
        </button>
        <button className="primary" onClick={() => setPreviewTemplateId(pickTemplateId(prompt))} type="button">
          <Send size={15} />
          <span>生成预览</span>
        </button>
      </div>
      {previewTemplate ? (
        <div className="assistant-preview">
          <strong>{previewTemplate.name}</strong>
          <span>{previewTemplate.description}</span>
          <div>
            <small>{previewTemplate.nodes.length} 节点</small>
            <small>{previewTemplate.edges.length} 连线</small>
            <small>{previewTemplate.fields.length} State 字段</small>
          </div>
          <ul>
            {previewTemplate.fields.slice(0, 6).map((field) => (
              <li key={field.name}>{field.name}: {field.type}</li>
            ))}
          </ul>
          <button className="primary" onClick={() => void applyAssistantPrompt(prompt)} type="button">
            应用到画布
          </button>
        </div>
      ) : null}
    </aside>
  );
}

function pickTemplateId(prompt: string) {
  const normalized = prompt.trim();
  if (/客服|售后|订单|退款/.test(normalized)) return "customer_support";
  if (/知识库|问答|文档|rag|检索/i.test(normalized)) return "knowledge_qa";
  return "knowledge_qa";
}
