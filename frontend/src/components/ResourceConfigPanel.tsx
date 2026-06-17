import { useState } from "react";
import { Bot, Cable, Link2, Plug, Server, Wrench } from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { AgentLinkConfig, ImportedAgentConfig, MCPServerConfig, SkillConfig, ToolConfig } from "../types";

type TabKey = "tools" | "skills" | "mcp" | "agents" | "links";

export function ResourceConfigPanel() {
  const project = useProjectStore((state) => state.project);
  const projects = useProjectStore((state) => state.projects);
  const workspaceSkills = useProjectStore((state) => state.workspaceSkills);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const updateTools = useProjectStore((state) => state.updateTools);
  const updateSkills = useProjectStore((state) => state.updateSkills);
  const updateMcpServers = useProjectStore((state) => state.updateMcpServers);
  const updateImportedAgents = useProjectStore((state) => state.updateImportedAgents);
  const updateAgentLinks = useProjectStore((state) => state.updateAgentLinks);
  const [tab, setTab] = useState<TabKey>("tools");
  const [selectedSkillId, setSelectedSkillId] = useState("");
  const [selectedMcpId, setSelectedMcpId] = useState("");

  if (!project) return null;
  const projectSkills = project.skills ?? [];
  const projectMcpServers = project.mcpServers ?? [];

  return (
    <aside className="resource-panel glass-panel">
      <div className="panel-title">
        <span>初始化配置</span>
        <small>{tabLabel(tab)}</small>
      </div>
      <div className="resource-tabs">
        <TabButton active={tab === "tools"} icon={<Wrench size={15} />} label="Tools" onClick={() => setTab("tools")} />
        <TabButton active={tab === "skills"} icon={<Plug size={15} />} label="Skills" onClick={() => setTab("skills")} />
        <TabButton active={tab === "mcp"} icon={<Server size={15} />} label="MCP" onClick={() => setTab("mcp")} />
        <TabButton active={tab === "agents"} icon={<Bot size={15} />} label="Agents" onClick={() => setTab("agents")} />
        <TabButton active={tab === "links"} icon={<Cable size={15} />} label="通信" onClick={() => setTab("links")} />
      </div>

      {tab === "tools" && (
        <ResourceList
          emptyText="还没有导入工具。"
          items={project.tools}
          onAdd={() => updateTools([...project.tools, newTool()])}
          onRemove={(id) => updateTools(project.tools.filter((item) => item.id !== id))}
          render={(tool) => (
            <>
              <Field label="名称">
                <input value={tool.name} onChange={(event) => updateTools(updateItem(project.tools, tool.id, { name: event.target.value }))} />
              </Field>
              <Field label="来源">
                <select value={tool.source} onChange={(event) => updateTools(updateItem(project.tools, tool.id, { source: event.target.value }))}>
                  <option value="python">Python</option>
                  <option value="http">HTTP</option>
                  <option value="openapi">OpenAPI</option>
                </select>
              </Field>
              <Field label="描述">
                <textarea rows={2} value={tool.description} onChange={(event) => updateTools(updateItem(project.tools, tool.id, { description: event.target.value }))} />
              </Field>
              <Field label="参数 Schema JSON">
                <textarea rows={3} value={tool.schemaJson} onChange={(event) => updateTools(updateItem(project.tools, tool.id, { schemaJson: event.target.value }))} />
              </Field>
            </>
          )}
        />
      )}

      {tab === "skills" && (
        <SkillProjectList
          items={projectSkills}
          workspaceSkills={workspaceSkills}
          selectedSkillId={selectedSkillId}
          onSelectSkill={setSelectedSkillId}
          onAdd={(skill) => {
            if (!skill || projectSkills.some((item) => item.id === skill.id)) return;
            updateSkills([...projectSkills, skill]);
            setSelectedSkillId("");
          }}
          onToggle={(id, enabled) => updateSkills(updateItem(projectSkills, id, { enabled }))}
          onRemove={(id) => updateSkills(projectSkills.filter((item) => item.id !== id))}
        />
      )}

      {tab === "mcp" && (
        <McpProjectList
          items={projectMcpServers}
          workspaceMcpServers={workspaceMcpServers}
          selectedMcpId={selectedMcpId}
          onSelectMcp={setSelectedMcpId}
          onAdd={(server) => {
            if (!server || projectMcpServers.some((item) => item.id === server.id)) return;
            updateMcpServers([...projectMcpServers, { ...server }]);
            setSelectedMcpId("");
          }}
          onAddManual={() => updateMcpServers([...projectMcpServers, newMcpServer()])}
          onChange={(id, patch) => updateMcpServers(updateItem(projectMcpServers, id, patch))}
          onRemove={(id) => updateMcpServers(projectMcpServers.filter((item) => item.id !== id))}
        />
      )}

      {tab === "agents" && (
        <ResourceList
          emptyText="还没有导入其他 Agent。"
          items={project.importedAgents}
          onAdd={() => updateImportedAgents([...project.importedAgents, newImportedAgent(projects, project.project.id)])}
          onRemove={(id) => updateImportedAgents(project.importedAgents.filter((item) => item.id !== id))}
          render={(agent) => (
            <>
              <Field label="名称">
                <input value={agent.name} onChange={(event) => updateImportedAgents(updateItem(project.importedAgents, agent.id, { name: event.target.value }))} />
              </Field>
              <Field label="历史 Agent">
                <select value={agent.projectId} onChange={(event) => updateImportedAgents(updateItem(project.importedAgents, agent.id, { projectId: event.target.value }))}>
                  <option value="">手动配置</option>
                  {projects.filter((item) => item.id !== project.project.id).map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </Field>
              <Field label="角色">
                <select value={agent.role} onChange={(event) => updateImportedAgents(updateItem(project.importedAgents, agent.id, { role: event.target.value }))}>
                  <option value="sub_agent">子 Agent</option>
                  <option value="peer">协作 Agent</option>
                  <option value="supervisor">监督 Agent</option>
                </select>
              </Field>
            </>
          )}
        />
      )}

      {tab === "links" && (
        <ResourceList
          emptyText="还没有 Agent 通信关系。"
          items={project.agentLinks}
          onAdd={() => updateAgentLinks([...project.agentLinks, newAgentLink(project.importedAgents)])}
          onRemove={(id) => updateAgentLinks(project.agentLinks.filter((item) => item.id !== id))}
          render={(link) => (
            <>
              <Field label="From">
                <input value={link.fromAgent} onChange={(event) => updateAgentLinks(updateItem(project.agentLinks, link.id, { fromAgent: event.target.value }))} />
              </Field>
              <Field label="To">
                <input value={link.toAgent} onChange={(event) => updateAgentLinks(updateItem(project.agentLinks, link.id, { toAgent: event.target.value }))} />
              </Field>
              <Field label="协议">
                <select value={link.protocol} onChange={(event) => updateAgentLinks(updateItem(project.agentLinks, link.id, { protocol: event.target.value }))}>
                  <option value="handoff">handoff</option>
                  <option value="delegate">delegate</option>
                  <option value="broadcast">broadcast</option>
                  <option value="review">review</option>
                </select>
              </Field>
              <Field label="通信说明">
                <textarea rows={2} value={link.instruction} onChange={(event) => updateAgentLinks(updateItem(project.agentLinks, link.id, { instruction: event.target.value }))} />
              </Field>
            </>
          )}
        />
      )}
    </aside>
  );
}

function TabButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={active ? "is-active" : ""} onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  );
}

function SkillProjectList({
  items,
  workspaceSkills,
  selectedSkillId,
  onSelectSkill,
  onAdd,
  onToggle,
  onRemove,
}: {
  items: SkillConfig[];
  workspaceSkills: SkillConfig[];
  selectedSkillId: string;
  onSelectSkill: (id: string) => void;
  onAdd: (skill: SkillConfig | undefined) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onRemove: (id: string) => void;
}) {
  const available = workspaceSkills.filter((skill) => !items.some((item) => item.id === skill.id));
  const selected = available.find((skill) => skill.id === selectedSkillId);
  return (
    <div className="resource-list">
      <div className="resource-add resource-add--picker">
        <select value={selectedSkillId} onChange={(event) => onSelectSkill(event.target.value)}>
          <option value="">从全局 Skills 选择</option>
          {available.map((skill) => (
            <option key={skill.id} value={skill.id}>
              {skill.name}
            </option>
          ))}
        </select>
        <button onClick={() => onAdd(selected)} disabled={!selected} type="button">
          <Link2 size={15} />
          <span>添加 Skill</span>
        </button>
      </div>
      {items.length === 0 ? <div className="resource-empty">还没有添加项目 Skill。先在管理页导入全局 Skills，再从上方选择。</div> : null}
      {items.map((skill) => (
        <section key={skill.id} className="resource-card">
          <Field label="名称">
            <input readOnly value={skill.name} />
          </Field>
          <Field label="说明">
            <textarea readOnly rows={2} value={skill.description || skill.content.slice(0, 160)} />
          </Field>
          <Field label="来源">
            <input readOnly value={skill.filePath || skill.sourcePath || skill.sourceType} />
          </Field>
          <label className="checkbox-row">
            <input checked={skill.enabled} onChange={(event) => onToggle(skill.id, event.target.checked)} type="checkbox" />
            <span>启用该项目 Skill</span>
          </label>
          <button className="danger resource-remove" onClick={() => onRemove(skill.id)} type="button">移除</button>
        </section>
      ))}
    </div>
  );
}

function McpProjectList({
  items,
  workspaceMcpServers,
  selectedMcpId,
  onSelectMcp,
  onAdd,
  onAddManual,
  onChange,
  onRemove,
}: {
  items: MCPServerConfig[];
  workspaceMcpServers: MCPServerConfig[];
  selectedMcpId: string;
  onSelectMcp: (id: string) => void;
  onAdd: (server: MCPServerConfig | undefined) => void;
  onAddManual: () => void;
  onChange: (id: string, patch: Partial<MCPServerConfig>) => void;
  onRemove: (id: string) => void;
}) {
  const available = workspaceMcpServers.filter((server) => !items.some((item) => item.id === server.id));
  const selected = available.find((server) => server.id === selectedMcpId);
  return (
    <div className="resource-list">
      <div className="resource-add resource-add--picker">
        <select value={selectedMcpId} onChange={(event) => onSelectMcp(event.target.value)}>
          <option value="">从全局 MCP 选择</option>
          {available.map((server) => (
            <option key={server.id} value={server.id}>
              {server.name}
            </option>
          ))}
        </select>
        <button onClick={() => onAdd(selected)} disabled={!selected} type="button">
          <Link2 size={15} />
          <span>添加 MCP</span>
        </button>
      </div>
      <button className="resource-add" onClick={onAddManual} type="button">
        <Link2 size={15} />
        <span>手动新增 MCP</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">还没有添加项目 MCP。先在管理页配置全局 MCP，再从上方选择。</div> : null}
      {items.map((server) => (
        <section key={server.id} className="resource-card">
          <Field label="名称">
            <input value={server.name} onChange={(event) => onChange(server.id, { name: event.target.value })} />
          </Field>
          <div className="resource-summary">
            <strong>{server.transport}</strong>
            <span>{mcpEndpointSummary(server)}</span>
          </div>
          <Field label="Transport">
            <select value={server.transport} onChange={(event) => onChange(server.id, { transport: event.target.value })}>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
          </Field>
          <Field label="Command">
            <input value={server.command} onChange={(event) => onChange(server.id, { command: event.target.value })} />
          </Field>
          <Field label="URL">
            <input value={server.url} onChange={(event) => onChange(server.id, { url: event.target.value })} />
          </Field>
          <Field label="允许工具 JSON">
            <textarea rows={2} value={server.enabledToolsJson} onChange={(event) => onChange(server.id, { enabledToolsJson: event.target.value })} />
          </Field>
          <Field label="禁用工具 JSON">
            <textarea rows={2} value={server.disabledToolsJson} onChange={(event) => onChange(server.id, { disabledToolsJson: event.target.value })} />
          </Field>
          <label className="checkbox-row">
            <input checked={server.enabled} onChange={(event) => onChange(server.id, { enabled: event.target.checked })} type="checkbox" />
            <span>启用该项目 MCP Server</span>
          </label>
          {server.description ? (
            <Field label="描述">
              <textarea rows={2} value={server.description} onChange={(event) => onChange(server.id, { description: event.target.value })} />
            </Field>
          ) : null}
          <button className="danger resource-remove" onClick={() => onRemove(server.id)} type="button">移除</button>
        </section>
      ))}
    </div>
  );
}

function ResourceList<T extends { id: string }>({
  items,
  emptyText,
  onAdd,
  onRemove,
  render,
}: {
  items: T[];
  emptyText: string;
  onAdd: () => void;
  onRemove: (id: string) => void;
  render: (item: T) => React.ReactNode;
}) {
  return (
    <div className="resource-list">
      <button className="resource-add" onClick={onAdd}>
        <Link2 size={15} />
        <span>添加配置</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">{emptyText}</div> : null}
      {items.map((item) => (
        <section key={item.id} className="resource-card">
          {render(item)}
          <button className="danger resource-remove" onClick={() => onRemove(item.id)}>删除</button>
        </section>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field compact-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function updateItem<T extends { id: string }>(items: T[], id: string, patch: Partial<T>): T[] {
  return items.map((item) => (item.id === id ? { ...item, ...patch } : item));
}

function newTool(): ToolConfig {
  return { id: createId("tool"), name: "新工具", description: "", source: "python", schemaJson: "{}" };
}

function newMcpServer(): MCPServerConfig {
  return {
    id: createId("mcp"),
    name: "新 MCP",
    transport: "stdio",
    command: "",
    argsJson: "[]",
    envJson: "{}",
    envVarsJson: "[]",
    cwd: "",
    url: "",
    apiKey: "",
    apiKeyEnv: "",
    apiKeyMode: "env",
    apiKeyHeader: "Authorization",
    apiKeyPrefix: "Bearer",
    bearerTokenEnvVar: "",
    httpHeadersJson: "{}",
    envHttpHeadersJson: "{}",
    enabled: true,
    startupTimeoutSec: 10,
    toolTimeoutSec: 60,
    enabledToolsJson: "[]",
    disabledToolsJson: "[]",
    defaultToolsApprovalMode: "",
    sourceType: "manual",
    sourcePath: "",
    description: "",
  };
}

function newImportedAgent(projects: { id: string; name: string }[], currentProjectId: string): ImportedAgentConfig {
  const target = projects.find((project) => project.id !== currentProjectId);
  return {
    id: createId("agent_ref"),
    name: target?.name ?? "导入 Agent",
    projectId: target?.id ?? "",
    role: "sub_agent",
    description: "",
  };
}

function newAgentLink(agents: ImportedAgentConfig[]): AgentLinkConfig {
  return {
    id: createId("agent_link"),
    fromAgent: "current",
    toAgent: agents[0]?.id ?? "",
    protocol: "handoff",
    instruction: "",
  };
}

function mcpEndpointSummary(server: MCPServerConfig) {
  if (server.transport === "http") return server.url || "未配置 URL";
  const args = parseJsonList(server.argsJson);
  return [server.command, ...args].filter(Boolean).join(" ") || "未配置 Command";
}

function parseJsonList(value: string) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

function createId(prefix: string) {
  return `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
}

function tabLabel(tab: TabKey) {
  if (tab === "tools") return "Tools";
  if (tab === "skills") return "Skills";
  if (tab === "mcp") return "MCP";
  if (tab === "agents") return "Agents";
  return "通信";
}
