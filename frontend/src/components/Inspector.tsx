import { useMemo, useState } from "react";
import { Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { MCPServerConfig, ModelConfig, NodeIR, RagKnowledgeBaseConfig, SkillConfig, StateField, ToolConfig } from "../types";
import { FloatingPanel } from "./FloatingPanel";

export function Inspector() {
  const project = useProjectStore((state) => state.project);
  const selectedNodeId = useProjectStore((state) => state.selectedNodeId);
  const runActive = useProjectStore((state) => state.runActive);
  const selectNode = useProjectStore((state) => state.selectNode);
  const projects = useProjectStore((state) => state.projects);
  const workspaceTools = useProjectStore((state) => state.workspaceTools);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const workspaceRagKnowledgeBases = useProjectStore((state) => state.workspaceRagKnowledgeBases);
  const updateNode = useProjectStore((state) => state.updateNode);
  const updateNodeConfig = useProjectStore((state) => state.updateNodeConfig);
  const setStateFields = useProjectStore((state) => state.setStateFields);

  const node = useMemo(
    () => project?.nodes.find((item) => item.id === selectedNodeId) ?? null,
    [project?.nodes, selectedNodeId],
  );
  const availableTools = useMemo(() => mergeById([...(project?.tools ?? []), ...workspaceTools]), [project?.tools, workspaceTools]);
  const availableSkills = useMemo(() => (project?.skills ?? []).filter((skill) => skill.enabled), [project?.skills]);
  const availableMcpServers = useMemo(
    () => mergeById([...(project?.mcpServers ?? []), ...workspaceMcpServers]),
    [project?.mcpServers, workspaceMcpServers],
  );
  const availableAgents = useMemo(
    () => projects.filter((item) => item.kind === "agent" && item.id !== project?.project.id),
    [project?.project.id, projects],
  );
  const availableModelConfigs = useMemo(() => buildModelConfigOptions(workspaceModelConfigs), [workspaceModelConfigs]);
  const availableRagKnowledgeBases = useMemo(() => workspaceRagKnowledgeBases.filter((item) => item.enabled), [workspaceRagKnowledgeBases]);
  const detectedStateFields = useMemo(() => detectStateFieldsFromNodes(project?.nodes ?? []), [project?.nodes]);

  if (!project || !node || runActive) {
    return null;
  }

  return (
    <FloatingPanel
      title="检查器"
      subtitle={node.type}
      className="inspector-panel"
      initialRect={inspectorInitialRect}
      minWidth={320}
      minHeight={320}
      maxWidth={560}
      actions={
        <button className="icon-only panel-close" onClick={() => selectNode(null)} title="关闭检查器" type="button">
          <X size={15} />
        </button>
      }
    >
      <div className="inspector-panel__scroll">
      <Field label="节点名称">
        <input value={node.label} onChange={(event) => updateNode(node.id, { label: event.target.value })} />
      </Field>
      {node.type === "start" && (
        <>
          <Field label="输入模式">
            <select
              value={String(node.config.inputMode ?? "chat")}
              onChange={(event) => updateNodeConfig(node.id, { inputMode: event.target.value })}
            >
              <option value="chat">聊天输入</option>
              <option value="form">表单输入</option>
              <option value="webhook">Webhook</option>
            </select>
          </Field>
          <StateFieldEditor
            fields={project.state.fields}
            detectedFields={detectedStateFields}
            onChange={setStateFields}
          />
        </>
      )}
      {node.type === "llm" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="System Prompt">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="User Prompt">
            <textarea
              rows={5}
              value={String(node.config.userPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { userPrompt: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "final_answer")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "agent" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="Agent 指令">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="可用工具 ID（逗号分隔）">
            <input
              value={String(node.config.tools ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { tools: event.target.value })}
              placeholder="get_order,refund_policy"
            />
          </Field>
          <Field label="注入 Skills">
            <SkillMultiSelect
              skills={availableSkills}
              selectedIds={parseStringList(node.config.skillIdsJson)}
              onChange={(ids) => updateNodeConfig(node.id, { skillIdsJson: JSON.stringify(ids) })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="最大迭代">
              <input
                type="number"
                min={1}
                value={String(node.config.maxIterations ?? 4)}
                onChange={(event) => updateNodeConfig(node.id, { maxIterations: Number(event.target.value) })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "agent_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "tool" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            providerLabel="决策模型配置"
            providerManualLabel="决策模型供应商标识"
            providerNote="这是 Tools Agent 用来判断、规划并反复调用工具的模型，不是 Tool 的供应商。"
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="Tools Agent 指令">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="用户输入">
            <textarea
              rows={4}
              value={String(node.config.userPrompt ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { userPrompt: event.target.value })}
            />
          </Field>
          <Field label="可用 Tools">
            <ToolMultiSelect
              tools={availableTools}
              selectedIds={parseStringList(node.config.toolIdsJson)}
              onChange={(ids) => {
                const selectedTools = availableTools.filter((tool) => ids.includes(tool.id));
                updateNodeConfig(node.id, {
                  toolIdsJson: JSON.stringify(ids),
                  toolRegistryJson: JSON.stringify(selectedTools),
                  tools: selectedTools.map((tool) => tool.name).join(","),
                });
              }}
            />
          </Field>
          <div className="inline-grid">
            <Field label="最大调用轮次">
              <input
                type="number"
                min={1}
                value={String(node.config.maxIterations ?? 4)}
                onChange={(event) => updateNodeConfig(node.id, { maxIterations: Number(event.target.value) })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "tools_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "task_splitter" && (
        <>
          <Field label="规划输入字段">
            <input
              value={String(node.config.inputField ?? "task_plan")}
              onChange={(event) => updateNodeConfig(node.id, { inputField: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="任务输出字段">
              <input
                value={String(node.config.outputField ?? "worker_tasks")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
            <Field label="最大任务数">
              <input
                type="number"
                min={1}
                max={10}
                value={String(node.config.maxTasks ?? 5)}
                onChange={(event) => updateNodeConfig(node.id, { maxTasks: Number(event.target.value) })}
              />
            </Field>
          </div>
          <Field label="解析失败兜底">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={node.config.fallbackToSingleTask !== false}
                onChange={(event) => updateNodeConfig(node.id, { fallbackToSingleTask: event.target.checked })}
              />
              <span>无法解析任务 JSON 时，用用户问题生成一个单任务</span>
            </label>
          </Field>
        </>
      )}
      {node.type === "parallel_tools" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            providerLabel="Worker 模型配置"
            providerManualLabel="Worker 模型供应商标识"
            providerNote="每个并行 Worker 都会使用这个模型自主选择并调用已选 Tools。"
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="Worker 指令">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="可用 Tools">
            <ToolMultiSelect
              tools={availableTools}
              selectedIds={parseStringList(node.config.toolIdsJson)}
              onChange={(ids) => {
                const selectedTools = availableTools.filter((tool) => ids.includes(tool.id));
                updateNodeConfig(node.id, {
                  toolIdsJson: JSON.stringify(ids),
                  toolRegistryJson: JSON.stringify(selectedTools),
                  tools: selectedTools.map((tool) => tool.name).join(","),
                });
              }}
            />
          </Field>
          <div className="inline-grid">
            <Field label="任务字段">
              <input
                value={String(node.config.tasksField ?? "worker_tasks")}
                onChange={(event) => updateNodeConfig(node.id, { tasksField: event.target.value })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "worker_results")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
          <div className="inline-grid">
            <Field label="每任务轮次">
              <input
                type="number"
                min={1}
                max={12}
                value={String(node.config.maxIterationsPerTask ?? 6)}
                onChange={(event) => updateNodeConfig(node.id, { maxIterationsPerTask: Number(event.target.value) })}
              />
            </Field>
            <Field label="并发 Worker">
              <input
                type="number"
                min={1}
                max={6}
                value={String(node.config.maxConcurrentWorkers ?? 3)}
                onChange={(event) => updateNodeConfig(node.id, { maxConcurrentWorkers: Number(event.target.value) })}
              />
            </Field>
          </div>
          <Field label="保存调用记录">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(node.config.storeToolCalls)}
                onChange={(event) => updateNodeConfig(node.id, { storeToolCalls: event.target.checked })}
              />
              <span>仅调试时开启，会增加 worker_results 的体积</span>
            </label>
          </Field>
        </>
      )}
      {node.type === "retriever" && (
        <>
          <Field label="绑定 RAG 知识库">
            <select
              value={String(node.config.knowledgeBaseId ?? "")}
              onChange={(event) => {
                const knowledgeBase = availableRagKnowledgeBases.find((item) => item.id === event.target.value);
                if (!knowledgeBase) {
                  updateNodeConfig(node.id, { knowledgeBaseId: "", knowledgeBaseName: "" });
                  return;
                }
                updateNodeConfig(node.id, {
                  knowledgeBaseId: knowledgeBase.id,
                  knowledgeBaseName: knowledgeBase.name,
                  source: retrieverSourceFromKnowledgeBase(knowledgeBase),
                  path: retrieverPathFromKnowledgeBase(knowledgeBase),
                  endpoint: knowledgeBase.url,
                  collection: knowledgeBase.collection,
                  topK: knowledgeBase.topK,
                  knowledgeBaseDescription: knowledgeBase.description,
                  embeddingModel: knowledgeBase.embeddingModel,
                  metadataJson: knowledgeBase.metadataJson,
                });
                updateNode(node.id, { label: knowledgeBase.name });
              }}
            >
              <option value="">未绑定，手动配置</option>
              {availableRagKnowledgeBases.map((knowledgeBase) => (
                <option key={knowledgeBase.id} value={knowledgeBase.id}>
                  {knowledgeBase.name} · {ragSourceLabel(knowledgeBase.sourceType)}
                </option>
              ))}
            </select>
            <small className="model-config-note">从管理页「节点资源 / RAG」导入的知识库中选择。</small>
          </Field>
          <Field label="数据源类型">
            <select value={String(node.config.source ?? "local")} onChange={(event) => updateNodeConfig(node.id, { source: event.target.value })}>
              <option value="local">本地目录</option>
              <option value="files">本地文件集合</option>
              <option value="vectorstore">已有向量库</option>
              <option value="http">HTTP 检索 API</option>
              <option value="database">数据库 / 表</option>
            </select>
          </Field>
          <Field label="知识库路径 / Endpoint">
            <input
              value={String(node.config.path ?? "./knowledge")}
              onChange={(event) => updateNodeConfig(node.id, { path: event.target.value })}
            />
          </Field>
          <Field label="Query 来源">
            <textarea
              rows={3}
              value={String(node.config.query ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { query: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="Top K">
              <input
                type="number"
                min={1}
                value={String(node.config.topK ?? 4)}
                onChange={(event) => updateNodeConfig(node.id, { topK: Number(event.target.value) })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "retrieved_context")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "condition" && (
        <>
          <Field label="判断字段">
            <input
              value={String(node.config.field ?? "intent")}
              onChange={(event) => updateNodeConfig(node.id, { field: event.target.value })}
            />
          </Field>
          <Field label="操作符">
            <select
              value={String(node.config.operator ?? "equals")}
              onChange={(event) => updateNodeConfig(node.id, { operator: event.target.value })}
            >
              <option value="equals">等于</option>
              <option value="not_equals">不等于</option>
              <option value="contains">包含</option>
              <option value="not_contains">不包含</option>
              <option value="is_empty">为空</option>
              <option value="is_not_empty">不为空</option>
            </select>
          </Field>
          <Field label="比较值">
            <input
              value={String(node.config.value ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { value: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="True 分支">
              <input
                value={String(node.config.trueBranch ?? "true")}
                onChange={(event) => updateNodeConfig(node.id, { trueBranch: event.target.value })}
              />
            </Field>
            <Field label="False 分支">
              <input
                value={String(node.config.falseBranch ?? "false")}
                onChange={(event) => updateNodeConfig(node.id, { falseBranch: event.target.value })}
              />
            </Field>
          </div>
          <Field label="Fallback">
            <input
              value={String(node.config.fallback ?? "fallback")}
              onChange={(event) => updateNodeConfig(node.id, { fallback: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "ai_router" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="路由模式">
            <select
              value={String(node.config.routeMode ?? "keyword")}
              onChange={(event) => updateNodeConfig(node.id, { routeMode: event.target.value })}
            >
              <option value="keyword">关键词 fallback</option>
              <option value="llm">LLM 路由</option>
            </select>
          </Field>
          <Field label="路由说明">
            <textarea
              rows={4}
              value={String(node.config.instruction ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { instruction: event.target.value })}
            />
          </Field>
          <Field label="输入文本">
            <textarea
              rows={3}
              value={String(node.config.inputText ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { inputText: event.target.value })}
            />
          </Field>
          <Field label="场景列表（key:中文名:关键词逗号分隔）">
            <textarea
              rows={6}
              value={String(node.config.scenarios ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { scenarios: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="路由字段">
              <input
                value={String(node.config.routeField ?? "route_key")}
                onChange={(event) => updateNodeConfig(node.id, { routeField: event.target.value })}
              />
            </Field>
            <Field label="Fallback">
              <input
                value={String(node.config.fallback ?? "other")}
                onChange={(event) => updateNodeConfig(node.id, { fallback: event.target.value })}
              />
            </Field>
          </div>
          <Field label="Reason 字段">
            <input
              value={String(node.config.reasonField ?? "route_reason")}
              onChange={(event) => updateNodeConfig(node.id, { reasonField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "human_approval" && (
        <>
          <Field label="审批提示">
            <textarea
              rows={4}
              value={String(node.config.prompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { prompt: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="默认动作">
              <select
                value={String(node.config.defaultAction ?? "approved")}
                onChange={(event) => updateNodeConfig(node.id, { defaultAction: event.target.value })}
              >
                <option value="approved">通过</option>
                <option value="rejected">拒绝</option>
                <option value="edit">修改</option>
              </select>
            </Field>
            <Field label="Fallback">
              <input
                value={String(node.config.fallback ?? "rejected")}
                onChange={(event) => updateNodeConfig(node.id, { fallback: event.target.value })}
              />
            </Field>
          </div>
          <div className="inline-grid">
            <Field label="动作字段">
              <input
                value={String(node.config.actionField ?? "approval_action")}
                onChange={(event) => updateNodeConfig(node.id, { actionField: event.target.value })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "approval_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "http" && (
        <>
          <Field label="Method">
            <select
              value={String(node.config.method ?? "GET")}
              onChange={(event) => updateNodeConfig(node.id, { method: event.target.value })}
            >
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => (
                <option key={method} value={method}>{method}</option>
              ))}
            </select>
          </Field>
          <Field label="URL">
            <input
              value={String(node.config.url ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { url: event.target.value })}
            />
          </Field>
          <Field label="Auth Secret (.env key)">
            <input
              value={String(node.config.authSecret ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { authSecret: event.target.value })}
              placeholder="ORDER_API_TOKEN"
            />
          </Field>
          <Field label="预览 Mock 响应">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(node.config.mockEnabled)}
                onChange={(event) => updateNodeConfig(node.id, { mockEnabled: event.target.checked })}
              />
              <span>启用 mock，live preview 和导出样板会使用下方 JSON，不请求真实接口</span>
            </label>
          </Field>
          <Field label="Mock JSON">
            <textarea
              className="code-area"
              rows={6}
              value={String(node.config.mockResponseJson ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { mockResponseJson: event.target.value })}
            />
          </Field>
          <Field label="Body">
            <textarea
              rows={5}
              value={String(node.config.body ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { body: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "http_response")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "direct_reply" && (
        <>
          <Field label="回复模板">
            <textarea
              rows={7}
              value={String(node.config.template ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { template: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "final_answer")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "custom_function" && (
        <>
          <Field label="Python 函数体">
            <textarea
              className="code-area"
              rows={12}
              value={String(node.config.code ?? "return {}")}
              onChange={(event) => updateNodeConfig(node.id, { code: event.target.value })}
            />
          </Field>
          <Field label="非 dict 返回时写入">
            <input
              value={String(node.config.outputField ?? "custom_output")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "skill_node" && (
        <>
          <Field label="绑定 Skill">
            <select
              value={String(node.config.skillId ?? node.config.toolId ?? "")}
              onChange={(event) => {
                const skill = availableSkills.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  skillId: skill?.id ?? "",
                  skillName: skill?.name ?? "未选择 Skill",
                  skillContent: skill?.content ?? "",
                  sourcePath: skill?.sourcePath ?? "",
                  filePath: skill?.filePath ?? "",
                });
                if (skill) updateNode(node.id, { label: skill.name });
              }}
            >
              <option value="">未选择</option>
              {availableSkills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="来源">
            <input value={String(node.config.sourcePath ?? "")} onChange={(event) => updateNodeConfig(node.id, { sourcePath: event.target.value })} />
          </Field>
          <Field label="内容">
            <textarea
              rows={8}
              value={String(node.config.skillContent ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { skillContent: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "skill_result")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "mcp_node" && (
        <>
          <Field label="绑定 MCP Server">
            <select
              value={String(node.config.serverId ?? "")}
              onChange={(event) => {
                const server = availableMcpServers.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  serverId: server?.id ?? "",
                  serverName: server?.name ?? "未选择 MCP",
                  transport: server?.transport ?? "stdio",
                  command: server?.command ?? "",
                  url: server?.url ?? "",
                });
                if (server) updateNode(node.id, { label: server.name });
              }}
            >
              <option value="">未选择</option>
              {availableMcpServers.map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Transport">
            <select value={String(node.config.transport ?? "stdio")} onChange={(event) => updateNodeConfig(node.id, { transport: event.target.value })}>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
          </Field>
          <Field label="Command">
            <input value={String(node.config.command ?? "")} onChange={(event) => updateNodeConfig(node.id, { command: event.target.value })} />
          </Field>
          <Field label="URL">
            <input value={String(node.config.url ?? "")} onChange={(event) => updateNodeConfig(node.id, { url: event.target.value })} />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "mcp_result")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "agent_ref" && (
        <>
          <Field label="绑定 Agent">
            <select
              value={String(node.config.agentProjectId ?? "")}
              onChange={(event) => {
                const agent = availableAgents.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  agentProjectId: agent?.id ?? "",
                  agentName: agent?.name ?? "未选择 Agent",
                });
                if (agent) updateNode(node.id, { label: agent.name });
              }}
            >
              <option value="">未选择</option>
              {availableAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="通信协议">
            <select value={String(node.config.protocol ?? "handoff")} onChange={(event) => updateNodeConfig(node.id, { protocol: event.target.value })}>
              <option value="handoff">handoff</option>
              <option value="delegate">delegate</option>
              <option value="broadcast">broadcast</option>
              <option value="review">review</option>
            </select>
          </Field>
          <Field label="通信说明">
            <textarea
              rows={4}
              value={String(node.config.instruction ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { instruction: event.target.value })}
            />
          </Field>
        </>
      )}
      </div>
    </FloatingPanel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

interface DetectedStateField extends StateField {
  sourceNodeId: string;
  sourceLabel: string;
}

const STATE_TYPE_OPTIONS = ["str", "int", "float", "bool", "dict", "list", "Any"];

function StateFieldEditor({
  fields,
  detectedFields,
  onChange,
}: {
  fields: StateField[];
  detectedFields: DetectedStateField[];
  onChange: (fields: StateField[]) => void;
}) {
  const [query, setQuery] = useState("");
  const existingNames = new Set(fields.map((field) => field.name).filter(Boolean));
  const normalizedQuery = query.trim().toLowerCase();
  const filteredDetected = normalizedQuery
    ? detectedFields.filter((field) =>
        `${field.name} ${field.type} ${field.sourceLabel} ${field.description ?? ""}`.toLowerCase().includes(normalizedQuery),
      )
    : detectedFields;

  const updateField = (index: number, patch: Partial<StateField>) => {
    onChange(fields.map((field, fieldIndex) => (fieldIndex === index ? { ...field, ...patch } : field)));
  };

  const addField = (field?: StateField) => {
    const next = field ?? { name: nextManualStateFieldName(fields), type: "str", description: "" };
    onChange(mergeInspectorStateFields(fields, [next]));
  };

  return (
    <div className="state-field-editor">
      <div className="state-field-editor__header">
        <span>State 字段</span>
        <div className="state-field-editor__actions">
          <button type="button" onClick={() => addField()}>
            <Plus size={14} />
            添加字段
          </button>
          <button type="button" onClick={() => onChange(mergeInspectorStateFields(fields, detectedFields))}>
            <RefreshCw size={14} />
            同步识别字段
          </button>
        </div>
      </div>

      <div className="state-field-editor__rows">
        {fields.length === 0 ? (
          <div className="state-field-editor__empty">当前还没有声明 State 字段。</div>
        ) : (
          fields.map((field, index) => (
            <div key={`${field.name}-${index}`} className="state-field-row">
              <input
                value={field.name}
                onChange={(event) => updateField(index, { name: normalizeStateFieldName(event.target.value) })}
                placeholder="字段名"
              />
              <select value={field.type || "str"} onChange={(event) => updateField(index, { type: event.target.value })}>
                {STATE_TYPE_OPTIONS.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <button
                className="icon-only state-field-row__delete"
                type="button"
                title="删除字段"
                onClick={() => onChange(fields.filter((_field, fieldIndex) => fieldIndex !== index))}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="state-detected">
        <div className="state-detected__title">
          <span>可识别字段</span>
          <small>{detectedFields.length} 个</small>
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索字段、类型或节点"
        />
        <div className="state-detected__list">
          {filteredDetected.length === 0 ? (
            <div className="state-field-editor__empty">没有匹配字段</div>
          ) : (
            filteredDetected.map((field) => {
              const exists = existingNames.has(field.name);
              return (
                <button
                  key={`${field.sourceNodeId}-${field.name}`}
                  className={exists ? "is-added" : ""}
                  type="button"
                  disabled={exists}
                  onClick={() => addField(field)}
                >
                  <span>
                    <strong>{field.name}</strong>
                    <small>{field.sourceLabel}</small>
                  </span>
                  <em>{exists ? "已添加" : field.type || "str"}</em>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

function SkillMultiSelect({
  skills,
  selectedIds,
  onChange,
}: {
  skills: SkillConfig[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  if (skills.length === 0) {
    return <small className="model-config-note">当前项目还没有可用 Skill。先在初始化配置的 Skills tab 添加。</small>;
  }
  const selected = new Set(selectedIds);
  return (
    <div className="inspector-check-list">
      {skills.map((skill) => (
        <label key={skill.id} className="checkbox-row">
          <input
            type="checkbox"
            checked={selected.has(skill.id)}
            onChange={(event) => {
              const next = event.target.checked
                ? [...selectedIds, skill.id]
                : selectedIds.filter((id) => id !== skill.id);
              onChange(Array.from(new Set(next)));
            }}
          />
          <span>{skill.name}</span>
        </label>
      ))}
    </div>
  );
}

function ToolMultiSelect({
  tools,
  selectedIds,
  onChange,
}: {
  tools: ToolConfig[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  if (tools.length === 0) {
    return <small className="model-config-note">当前还没有可用 Tool。先在主页面「Tools」管理区导入或新增工具。</small>;
  }
  const selected = new Set(selectedIds);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredTools = normalizedQuery
    ? tools.filter((tool) => `${tool.name} ${tool.source} ${tool.description}`.toLowerCase().includes(normalizedQuery))
    : tools;
  return (
    <div className="tool-picker">
      <input
        className="tool-picker__search"
        value={query}
        placeholder="搜索 Tool 名称、来源或描述"
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="tool-picker__list">
        {filteredTools.length === 0 ? (
          <div className="tool-picker__empty">没有匹配的 Tool</div>
        ) : (
          filteredTools.map((tool) => (
            <label key={tool.id} className="tool-picker__item">
              <input
                type="checkbox"
                checked={selected.has(tool.id)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...selectedIds, tool.id]
                    : selectedIds.filter((id) => id !== tool.id);
                  onChange(Array.from(new Set(next)));
                }}
              />
              <span>
                <strong>{tool.name}</strong>
                <small>{tool.source || "tool"} · {tool.description || "未填写描述"}</small>
                <ToolUsageTags tool={tool} />
              </span>
            </label>
          ))
        )}
      </div>
    </div>
  );
}

function ToolUsageTags({ tool }: { tool: ToolConfig }) {
  const tags = toolUsageTags(tool);
  if (!tags.length) return null;
  return (
    <div className="tool-usage-tags">
      {tags.map((tag) => (
        <em key={tag}>{tag}</em>
      ))}
    </div>
  );
}

function parseStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.map((item) => String(item).trim()).filter(Boolean) : [];
  } catch {
    return text.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean);
  }
}

function toolUsageTags(tool: ToolConfig): string[] {
  const builtinId = toolBuiltinId(tool);
  const text = `${builtinId} ${tool.name} ${tool.description} ${tool.source}`.toLowerCase();
  const tags: string[] = [];
  if (/(read_file|list_directory|file|directory|asset|resolve_asset|文件|目录|资源)/.test(text)) tags.push("文件");
  if (/(code|symbol|chunk|search_code|python|javascript|typescript|代码|符号)/.test(text)) tags.push("代码");
  if (/(html|page|selector|页面)/.test(text)) tags.push("HTML");
  if (/(css|style|scss|less|样式)/.test(text)) tags.push("CSS");
  if (/(web_search|fetch_url|duckduckgo|http|network|搜索|网络)/.test(text)) tags.push("网络");
  return Array.from(new Set(tags));
}

function toolBuiltinId(tool: ToolConfig): string {
  try {
    const schema = JSON.parse(tool.schemaJson || "{}");
    const metadata = schema && typeof schema === "object" && !Array.isArray(schema) ? schema["x-graphic"] : null;
    return metadata && typeof metadata === "object" && "builtinId" in metadata ? String((metadata as { builtinId?: unknown }).builtinId || "") : "";
  } catch {
    return "";
  }
}

function detectStateFieldsFromNodes(nodes: NodeIR[]): DetectedStateField[] {
  const fields: DetectedStateField[] = [];
  for (const node of nodes) {
    switch (node.type) {
      case "start":
        fields.push(detectedField(node, "messages", "str", "聊天输入"));
        break;
      case "llm":
        fields.push(detectedFieldFromConfig(node, "outputField", "final_answer", "str", "模型输出"));
        break;
      case "agent":
        fields.push(detectedFieldFromConfig(node, "outputField", "agent_result", "str", "Agent 输出"));
        break;
      case "tool": {
        const output = detectedFieldFromConfig(node, "outputField", "tools_result", "str", "Tools 输出");
        fields.push(output);
        fields.push(detectedField(node, `${output.name}_tool_calls`, "list", "工具调用记录"));
        break;
      }
      case "retriever":
        fields.push(detectedFieldFromConfig(node, "outputField", "retrieved_context", "str", "检索结果"));
        break;
      case "ai_router":
        fields.push(detectedFieldFromConfig(node, "routeField", "route_key", "str", "路由结果"));
        fields.push(detectedFieldFromConfig(node, "reasonField", "route_reason", "str", "路由理由"));
        break;
      case "human_approval":
        fields.push(detectedFieldFromConfig(node, "actionField", "approval_action", "str", "审批动作"));
        fields.push(detectedFieldFromConfig(node, "outputField", "approval_result", "dict", "审批结果"));
        break;
      case "http":
        fields.push(detectedFieldFromConfig(node, "outputField", "http_response", "dict", "HTTP 响应"));
        break;
      case "direct_reply":
        fields.push(detectedFieldFromConfig(node, "outputField", "final_answer", "str", "最终回复"));
        break;
      case "custom_function":
        fields.push(detectedFieldFromConfig(node, "outputField", "custom_output", "dict", "函数输出"));
        break;
      case "skill_node":
        fields.push(detectedFieldFromConfig(node, "outputField", "skill_result", "str", "Skill 输出"));
        break;
      case "mcp_node":
        fields.push(detectedFieldFromConfig(node, "outputField", "mcp_result", "dict", "MCP 输出"));
        break;
      default:
        break;
    }
  }
  return fields.filter((field) => Boolean(field.name));
}

function detectedFieldFromConfig(
  node: NodeIR,
  configKey: string,
  fallback: string,
  type: string,
  description: string,
): DetectedStateField {
  return detectedField(node, normalizeStateFieldName(node.config[configKey]) || fallback, type, description);
}

function detectedField(node: NodeIR, name: string, type: string, description: string): DetectedStateField {
  return {
    name: normalizeStateFieldName(name),
    type,
    description,
    sourceNodeId: node.id,
    sourceLabel: node.label || node.type,
  };
}

function mergeInspectorStateFields(existing: StateField[], additions: StateField[]): StateField[] {
  const result = [...existing];
  const names = new Set(result.map((field) => field.name).filter(Boolean));
  for (const addition of additions) {
    const name = normalizeStateFieldName(addition.name);
    if (!name || names.has(name)) continue;
    result.push({
      name,
      type: addition.type || "str",
      description: addition.description || "",
    });
    names.add(name);
  }
  return result;
}

function nextManualStateFieldName(fields: StateField[]): string {
  const used = new Set(fields.map((field) => field.name));
  for (let index = 1; index < 10000; index += 1) {
    const candidate = `field_${index}`;
    if (!used.has(candidate)) return candidate;
  }
  return `field_${Date.now()}`;
}

function normalizeStateFieldName(value: unknown): string {
  return String(value ?? "").trim().replace(/[^a-zA-Z0-9_]/g, "_").replace(/^([^a-zA-Z_])/, "_$1");
}

function inspectorInitialRect() {
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: Math.max(16, viewportWidth - 380),
    y: 98,
    width: 360,
    height: Math.min(720, Math.max(420, viewportHeight - 118)),
  };
}

interface ModelOption {
  id: string;
  name: string;
}

interface ModelConfigOption {
  id: string;
  name: string;
  provider: string;
  model: string;
  baseUrl: string;
  apiKeyEnv: string;
  apiVersion: string;
  organization: string;
  apiFormat: string;
  enabled: boolean;
  models: ModelOption[];
}

function ModelSelectionFields({
  config,
  defaultProvider,
  defaultModel,
  modelConfigs,
  nodeId,
  providerLabel = "供应商",
  providerManualLabel = "供应商",
  providerNote = "从管理页已保存的模型配置中选择；保存后会写入节点的供应商和模型。",
  updateNodeConfig,
}: {
  config: Record<string, unknown>;
  defaultProvider: string;
  defaultModel: string;
  modelConfigs: ModelConfigOption[];
  nodeId: string;
  providerLabel?: string;
  providerManualLabel?: string;
  providerNote?: string;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const provider = String(config.provider ?? defaultProvider);
  const model = String(config.model ?? defaultModel);
  const modelConfigId = String(config.modelConfigId ?? "");
  const selectedConfig =
    modelConfigs.find((item) => item.id === modelConfigId) ??
    modelConfigs.find((item) => item.provider === provider && item.models.some((option) => option.id === model)) ??
    modelConfigs.find((item) => item.provider === provider) ??
    null;
  const modelOptions = selectedConfig ? ensureModelOption(selectedConfig.models, model) : [];

  if (modelConfigs.length === 0) {
    return (
      <>
        <Field label={providerManualLabel}>
          <input value={provider} onChange={(event) => updateNodeConfig(nodeId, { provider: event.target.value, modelConfigId: "", modelConfigName: "" })} />
          <small className="model-config-note">还没有本地模型配置，暂时使用手动输入。可在管理页「模型」中添加。{providerNote}</small>
        </Field>
        <Field label="模型">
          <input value={model} onChange={(event) => updateNodeConfig(nodeId, { model: event.target.value })} />
        </Field>
      </>
    );
  }

  return (
    <>
      <Field label={providerLabel}>
        <select
          value={selectedConfig?.id ?? ""}
          onChange={(event) => {
            const nextConfig = modelConfigs.find((item) => item.id === event.target.value);
            if (!nextConfig) {
              updateNodeConfig(nodeId, { modelConfigId: "", modelConfigName: "" });
              return;
            }
            const nextModel = nextConfig.models.find((option) => option.id === model)?.id ?? nextConfig.model ?? nextConfig.models[0]?.id ?? model;
            updateNodeConfig(nodeId, {
              provider: nextConfig.provider,
              model: nextModel,
              modelConfigId: nextConfig.id,
              modelConfigName: nextConfig.name,
              baseUrl: nextConfig.baseUrl,
              apiKeyEnv: nextConfig.apiKeyEnv,
              apiVersion: nextConfig.apiVersion,
              organization: nextConfig.organization,
              apiFormat: nextConfig.apiFormat,
            });
          }}
        >
          <option value="">手动输入 / 未绑定</option>
          {modelConfigs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.provider}{item.enabled ? "" : "（已停用）"}
            </option>
          ))}
        </select>
        <small className="model-config-note">{providerNote}</small>
      </Field>
      {selectedConfig ? (
        <Field label="模型">
          <select
            value={model}
            onChange={(event) => {
              const option = modelOptions.find((item) => item.id === event.target.value);
              updateNodeConfig(nodeId, {
                model: event.target.value,
                modelDisplayName: option?.name ?? "",
                modelConfigId: selectedConfig.id,
                modelConfigName: selectedConfig.name,
                provider: selectedConfig.provider,
                baseUrl: selectedConfig.baseUrl,
                apiKeyEnv: selectedConfig.apiKeyEnv,
                apiVersion: selectedConfig.apiVersion,
                organization: selectedConfig.organization,
                apiFormat: selectedConfig.apiFormat,
              });
            }}
          >
            {modelOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name === option.id ? option.id : `${option.name} · ${option.id}`}
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <div className="inline-grid">
          <Field label="供应商标识">
            <input value={provider} onChange={(event) => updateNodeConfig(nodeId, { provider: event.target.value })} />
          </Field>
          <Field label="模型">
            <input value={model} onChange={(event) => updateNodeConfig(nodeId, { model: event.target.value })} />
          </Field>
        </div>
      )}
    </>
  );
}

function mergeById<T extends ToolConfig | MCPServerConfig>(items: T[]): T[] {
  const map = new Map<string, T>();
  for (const item of items) {
    map.set(item.id, item);
  }
  return Array.from(map.values());
}

function buildModelConfigOptions(configs: ModelConfig[]): ModelConfigOption[] {
  return configs
    .filter((config) => config && config.id)
    .map((config) => {
      const models = readConfiguredModels(config);
      return {
        id: config.id,
        name: config.name || "未命名模型配置",
        provider: String(config.provider || "openai"),
        model: config.model || models[0]?.id || "",
        baseUrl: config.baseUrl,
        apiKeyEnv: config.apiKeyEnv,
        apiVersion: config.apiVersion,
        organization: config.organization,
        apiFormat: config.apiFormat,
        enabled: config.enabled !== false,
        models: ensureModelOption(models, config.model),
      };
    });
}

function readConfiguredModels(config: Pick<ModelConfig, "modelRowsJson" | "modelsJson" | "model">): ModelOption[] {
  const rows = parseModelRows(config.modelRowsJson);
  if (rows.length > 0) return rows;
  const modelsJson = parseJsonObject(config.modelsJson);
  const migrated = Object.entries(modelsJson)
    .map(([id, value]) => ({
      id: id.trim(),
      name: value && typeof value === "object" && "name" in value ? String((value as { name?: unknown }).name || id).trim() : id.trim(),
    }))
    .filter((item) => item.id && item.name);
  if (migrated.length > 0) return migrated;
  const model = config.model.trim();
  return model ? [{ id: model, name: model }] : [];
}

function parseModelRows(value: string): ModelOption[] {
  try {
    const parsed = JSON.parse(value || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((row) => ({
        id: String(row?.id || "").trim(),
        name: String(row?.name || "").trim(),
      }))
      .filter((row) => row.id && row.name);
  } catch {
    return [];
  }
}

function parseJsonObject(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function ensureModelOption(models: ModelOption[], currentModel: string): ModelOption[] {
  const normalized = currentModel.trim();
  if (!normalized || models.some((item) => item.id === normalized)) return models;
  return [{ id: normalized, name: `${normalized}（当前值）` }, ...models];
}

function retrieverSourceFromKnowledgeBase(knowledgeBase: RagKnowledgeBaseConfig) {
  switch (knowledgeBase.sourceType) {
    case "local_files":
      return "files";
    case "vectorstore":
      return "vectorstore";
    case "http_api":
      return "http";
    case "database":
      return "database";
    case "local_directory":
    default:
      return "local";
  }
}

function retrieverPathFromKnowledgeBase(knowledgeBase: RagKnowledgeBaseConfig) {
  return knowledgeBase.path || knowledgeBase.url || knowledgeBase.collection || "./knowledge";
}

function ragSourceLabel(sourceType: string) {
  switch (sourceType) {
    case "local_files":
      return "本地文件";
    case "vectorstore":
      return "向量库";
    case "http_api":
      return "HTTP API";
    case "database":
      return "数据库";
    case "local_directory":
    default:
      return "本地目录";
  }
}
