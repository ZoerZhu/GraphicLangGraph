import { useMemo } from "react";
import { useProjectStore } from "../store/projectStore";
import type { MCPServerConfig, StateField, ToolConfig } from "../types";

export function Inspector() {
  const project = useProjectStore((state) => state.project);
  const selectedNodeId = useProjectStore((state) => state.selectedNodeId);
  const projects = useProjectStore((state) => state.projects);
  const workspaceTools = useProjectStore((state) => state.workspaceTools);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const updateNode = useProjectStore((state) => state.updateNode);
  const updateNodeConfig = useProjectStore((state) => state.updateNodeConfig);
  const setStateFields = useProjectStore((state) => state.setStateFields);

  const node = useMemo(
    () => project?.nodes.find((item) => item.id === selectedNodeId) ?? null,
    [project?.nodes, selectedNodeId],
  );
  const availableTools = useMemo(() => mergeById([...(project?.tools ?? []), ...workspaceTools]), [project?.tools, workspaceTools]);
  const availableMcpServers = useMemo(
    () => mergeById([...(project?.mcpServers ?? []), ...workspaceMcpServers]),
    [project?.mcpServers, workspaceMcpServers],
  );
  const availableAgents = useMemo(
    () => projects.filter((item) => item.kind === "agent" && item.id !== project?.project.id),
    [project?.project.id, projects],
  );

  if (!project) {
    return null;
  }

  if (!node) {
    return (
      <aside className="right-panel glass-panel">
        <div className="panel-title">
          <span>检查器</span>
          <small>未选中</small>
        </div>
        <div className="empty-state">选择一个节点后编辑配置。</div>
      </aside>
    );
  }

  return (
    <aside className="right-panel glass-panel">
      <div className="panel-title">
        <span>检查器</span>
        <small>{node.type}</small>
      </div>
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
          <Field label="State 字段">
            <textarea
              rows={6}
              value={stateFieldsToText(project.state.fields)}
              onChange={(event) => setStateFields(parseStateFields(event.target.value))}
              placeholder="final_answer:str&#10;intent:str&#10;order_info:dict"
            />
          </Field>
        </>
      )}
      {node.type === "llm" && (
        <>
          <Field label="供应商">
            <input
              value={String(node.config.provider ?? "openai")}
              onChange={(event) => updateNodeConfig(node.id, { provider: event.target.value })}
            />
          </Field>
          <Field label="模型">
            <input
              value={String(node.config.model ?? "gpt-4.1-mini")}
              onChange={(event) => updateNodeConfig(node.id, { model: event.target.value })}
            />
          </Field>
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
          <Field label="供应商">
            <input
              value={String(node.config.provider ?? "openai")}
              onChange={(event) => updateNodeConfig(node.id, { provider: event.target.value })}
            />
          </Field>
          <Field label="模型">
            <input
              value={String(node.config.model ?? "gpt-4.1-mini")}
              onChange={(event) => updateNodeConfig(node.id, { model: event.target.value })}
            />
          </Field>
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
          <Field label="工具名称">
            <input
              value={String(node.config.toolName ?? "business_tool")}
              onChange={(event) => updateNodeConfig(node.id, { toolName: event.target.value })}
            />
          </Field>
          <Field label="来源">
            <select value={String(node.config.source ?? "python")} onChange={(event) => updateNodeConfig(node.id, { source: event.target.value })}>
              <option value="python">Python</option>
              <option value="http">HTTP</option>
              <option value="mcp">MCP</option>
              <option value="openapi">OpenAPI</option>
            </select>
          </Field>
          <Field label="描述">
            <textarea rows={3} value={String(node.config.description ?? "")} onChange={(event) => updateNodeConfig(node.id, { description: event.target.value })} />
          </Field>
          <Field label="参数 Schema JSON">
            <textarea
              className="code-area"
              rows={5}
              value={String(node.config.paramsJson ?? "{}")}
              onChange={(event) => updateNodeConfig(node.id, { paramsJson: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="需要审批">
              <select
                value={String(Boolean(node.config.requiresApproval ?? false))}
                onChange={(event) => updateNodeConfig(node.id, { requiresApproval: event.target.value === "true" })}
              >
                <option value="false">否</option>
                <option value="true">是</option>
              </select>
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "tool_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "retriever" && (
        <>
          <Field label="数据源类型">
            <select value={String(node.config.source ?? "local")} onChange={(event) => updateNodeConfig(node.id, { source: event.target.value })}>
              <option value="local">本地目录</option>
              <option value="vectorstore">已有向量库</option>
              <option value="http">HTTP 检索 API</option>
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
          <Field label="模型">
            <input
              value={String(node.config.model ?? "gpt-4.1-mini")}
              onChange={(event) => updateNodeConfig(node.id, { model: event.target.value })}
            />
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
          <Field label="绑定 Skill/Tool">
            <select
              value={String(node.config.toolId ?? "")}
              onChange={(event) => {
                const tool = availableTools.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  toolId: tool?.id ?? "",
                  toolName: tool?.name ?? "未选择 Skill",
                  toolSource: tool?.source ?? "",
                  toolDescription: tool?.description ?? "",
                });
                if (tool) updateNode(node.id, { label: tool.name });
              }}
            >
              <option value="">未选择</option>
              {availableTools.map((tool) => (
                <option key={tool.id} value={tool.id}>
                  {tool.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="来源">
            <input value={String(node.config.toolSource ?? "")} onChange={(event) => updateNodeConfig(node.id, { toolSource: event.target.value })} />
          </Field>
          <Field label="说明">
            <textarea
              rows={3}
              value={String(node.config.toolDescription ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { toolDescription: event.target.value })}
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
    </aside>
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

function stateFieldsToText(fields: StateField[]): string {
  return fields.map((field) => `${field.name}:${field.type}`).join("\n");
}

function parseStateFields(value: string): StateField[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, type = "str"] = line.split(":");
      return { name: name.trim(), type: type.trim(), description: "" };
    })
    .filter((field) => Boolean(field.name));
}

function mergeById<T extends ToolConfig | MCPServerConfig>(items: T[]): T[] {
  const map = new Map<string, T>();
  for (const item of items) {
    map.set(item.id, item);
  }
  return Array.from(map.values());
}
