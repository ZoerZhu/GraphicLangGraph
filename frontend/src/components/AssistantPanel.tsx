import { Send, WandSparkles, X } from "lucide-react";
import { useState } from "react";
import { getProjectTemplateDependencyLabels, getProjectTemplateScene, PROJECT_TEMPLATES } from "../lib/templates";
import { useProjectStore } from "../store/projectStore";

export function AssistantPanel() {
  const open = useProjectStore((state) => state.assistantOpen);
  const closeAssistant = useProjectStore((state) => state.closeAssistant);
  const applyAssistantPrompt = useProjectStore((state) => state.applyAssistantPrompt);
  const [prompt, setPrompt] = useState("帮我做一个客服 Agent，先识别订单/退款/其他问题，再处理并回复用户。");
  const [previewTemplateId, setPreviewTemplateId] = useState<string | null>(null);
  const previewTemplate = PROJECT_TEMPLATES.find((template) => template.id === previewTemplateId) ?? null;
  const previewScene = previewTemplate ? getProjectTemplateScene(previewTemplate) : null;
  const previewDependencies = previewTemplate ? getProjectTemplateDependencyLabels(previewTemplate) : [];

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
        <p>助手会根据中文需求匹配场景方案，并生成带样例输入、依赖提示和验收口径的初始画布。</p>
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
        <button onClick={() => {
          setPrompt("帮我做一个 API JSON 清洗流程，读取订单接口返回，统一字段结构，校验 JSON 后回复用户。");
          setPreviewTemplateId(null);
        }} type="button">
          API 清洗
        </button>
        <button onClick={() => {
          setPrompt("帮我做一个 Exa WebSearch Agent，使用 MCP 搜索网页，再汇总回答。");
          setPreviewTemplateId(null);
        }} type="button">
          联网搜索
        </button>
        <button onClick={() => {
          setPrompt("帮我做一个多 Agent 协作流程，主 Agent 可以接入历史 Agent 作为子 Agent 工具调用。");
          setPreviewTemplateId(null);
        }} type="button">
          多 Agent
        </button>
        <button onClick={() => {
          setPrompt("帮我做一个并发任务处理流程，先校验结构化任务 JSON，再并发处理每个任务并汇总结果。");
          setPreviewTemplateId(null);
        }} type="button">
          并发任务
        </button>
        <button className="primary" onClick={() => setPreviewTemplateId(pickTemplateId(prompt))} type="button">
          <Send size={15} />
          <span>匹配场景</span>
        </button>
      </div>
      {previewTemplate ? (
        <div className="assistant-preview">
          <strong>{previewTemplate.name}</strong>
          <span>{previewTemplate.description}</span>
          {previewScene ? (
            <div className="assistant-preview__scene">
              <small>{previewScene.name}</small>
              <span>{previewTemplate.useCase}</span>
            </div>
          ) : null}
          <div>
            <small>{previewTemplate.nodes.length} 节点</small>
            <small>{previewTemplate.edges.length} 连线</small>
            <small>{previewTemplate.fields.length} State 字段</small>
            {previewDependencies.map((label) => <small key={label}>{label}</small>)}
          </div>
          <div className="assistant-preview__recommend">
            {previewTemplate.recommendedFor.map((item) => <span key={item}>{item}</span>)}
          </div>
          <div className="assistant-preview__acceptance">
            验收：{previewTemplate.acceptanceSummary}
          </div>
          {previewTemplate.setupNotes?.length ? (
            <ul className="assistant-preview__notes">
              {previewTemplate.setupNotes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          ) : null}
          <div className="assistant-preview__outputs">
            {previewTemplate.expectedOutputFields.slice(0, 5).map((field) => <span key={field}>{field}</span>)}
          </div>
          {previewTemplate.sampleInput ? (
            <pre className="assistant-preview__sample">{JSON.stringify(previewTemplate.sampleInput, null, 2)}</pre>
          ) : null}
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
  if (/exa|websearch|web search|联网|搜索|网页|mcp/i.test(normalized)) return "websearch_exa_mcp";
  if (/多.?agent|子.?agent|协作|编排|handoff|agent tool|历史 Agent/i.test(normalized)) return "multi_agent_orchestration";
  if (/api|json|清洗|校验|订单接口|订单 API/i.test(normalized)) return "api_json_cleanup";
  if (/并发|foreach|for each|任务处理|task plan|结构化任务|错误兜底|merge/i.test(normalized)) return "flow_control_task_processing";
  if (/客服|售后|订单|退款/.test(normalized)) return "customer_support";
  if (/知识库|问答|文档|rag|检索/i.test(normalized)) return "knowledge_qa";
  return "knowledge_qa";
}
