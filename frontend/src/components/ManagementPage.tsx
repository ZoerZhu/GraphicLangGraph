import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Bot, Clock, Edit3, Network, Plus, Save, Server, Trash2, Wrench } from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { MCPServerConfig, ProjectListItem, ToolConfig } from "../types";

type ResourceTab = "tools" | "mcp";

export function ManagementPage() {
  const projects = useProjectStore((state) => state.projects);
  const managerView = useProjectStore((state) => state.managerView);
  const workspaceTools = useProjectStore((state) => state.workspaceTools);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const status = useProjectStore((state) => state.status);
  const loading = useProjectStore((state) => state.loading);
  const loadProjectList = useProjectStore((state) => state.loadProjectList);
  const setManagerView = useProjectStore((state) => state.setManagerView);
  const createNewProject = useProjectStore((state) => state.createNewProject);
  const openProject = useProjectStore((state) => state.openProject);
  const deleteProjectById = useProjectStore((state) => state.deleteProjectById);
  const renameProjectById = useProjectStore((state) => state.renameProjectById);
  const updateWorkspaceTools = useProjectStore((state) => state.updateWorkspaceTools);
  const updateWorkspaceMcpServers = useProjectStore((state) => state.updateWorkspaceMcpServers);
  const [name, setName] = useState(defaultName(managerView));
  const [resourceTab, setResourceTab] = useState<ResourceTab>("tools");

  useEffect(() => {
    void loadProjectList();
  }, [loadProjectList]);

  useEffect(() => {
    setName(defaultName(managerView));
  }, [managerView]);

  const filteredProjects = useMemo(
    () => projects.filter((project) => project.kind === managerView),
    [managerView, projects],
  );

  return (
    <div className="manager-shell">
      <header className="manager-topbar glass-panel">
        <div className="brand">
          <div className="brand-mark">GL</div>
          <div>
            <h1>GraphicLangGraph</h1>
            <p>中文可视化搭建 LangGraph Agent 与多 Agent 通信画布</p>
          </div>
        </div>
        <div className="manager-topbar__status">{status}</div>
      </header>

      <div className="manager-layout">
        <aside className="manager-sidebar glass-panel">
          <div className="manager-nav">
            <NavButton
              active={managerView === "agent"}
              icon={<Bot size={17} />}
              title="Agent"
              text="管理单个已实现 Agent"
              onClick={() => setManagerView("agent")}
            />
            <NavButton
              active={managerView === "agents"}
              icon={<Network size={17} />}
              title="Agents"
              text="管理多 Agent 通信画布"
              onClick={() => setManagerView("agents")}
            />
          </div>

          <div className="manager-sidebar__section">
            <div className="panel-title">
              <span>节点资源</span>
              <small>全局</small>
            </div>
            <div className="resource-tabs manager-resource-tabs">
              <TabButton active={resourceTab === "tools"} icon={<Wrench size={15} />} label="Tools" onClick={() => setResourceTab("tools")} />
              <TabButton active={resourceTab === "mcp"} icon={<Server size={15} />} label="MCP" onClick={() => setResourceTab("mcp")} />
            </div>
            {resourceTab === "tools" ? (
              <WorkspaceResourceList
                emptyText="还没有导入 Tool。导入后会出现在编辑器节点库的 Skill Node 分组。"
                items={workspaceTools}
                onAdd={() => updateWorkspaceTools([...workspaceTools, newTool()])}
                onRemove={(id) => updateWorkspaceTools(workspaceTools.filter((item) => item.id !== id))}
                render={(tool) => (
                  <>
                    <Field label="名称">
                      <input value={tool.name} onChange={(event) => updateWorkspaceTools(updateItem(workspaceTools, tool.id, { name: event.target.value }))} />
                    </Field>
                    <Field label="来源">
                      <select value={tool.source} onChange={(event) => updateWorkspaceTools(updateItem(workspaceTools, tool.id, { source: event.target.value }))}>
                        <option value="python">Python</option>
                        <option value="http">HTTP</option>
                        <option value="openapi">OpenAPI</option>
                      </select>
                    </Field>
                    <Field label="描述">
                      <textarea rows={2} value={tool.description} onChange={(event) => updateWorkspaceTools(updateItem(workspaceTools, tool.id, { description: event.target.value }))} />
                    </Field>
                    <Field label="参数 Schema JSON">
                      <textarea rows={3} value={tool.schemaJson} onChange={(event) => updateWorkspaceTools(updateItem(workspaceTools, tool.id, { schemaJson: event.target.value }))} />
                    </Field>
                  </>
                )}
              />
            ) : (
              <WorkspaceResourceList
                emptyText="还没有配置 MCP。配置后会出现在编辑器节点库的 MCP Node 分组。"
                items={workspaceMcpServers}
                onAdd={() => updateWorkspaceMcpServers([...workspaceMcpServers, newMcpServer()])}
                onRemove={(id) => updateWorkspaceMcpServers(workspaceMcpServers.filter((item) => item.id !== id))}
                render={(server) => (
                  <>
                    <Field label="名称">
                      <input value={server.name} onChange={(event) => updateWorkspaceMcpServers(updateItem(workspaceMcpServers, server.id, { name: event.target.value }))} />
                    </Field>
                    <Field label="Transport">
                      <select value={server.transport} onChange={(event) => updateWorkspaceMcpServers(updateItem(workspaceMcpServers, server.id, { transport: event.target.value }))}>
                        <option value="stdio">stdio</option>
                        <option value="http">http</option>
                      </select>
                    </Field>
                    <Field label="Command">
                      <input value={server.command} onChange={(event) => updateWorkspaceMcpServers(updateItem(workspaceMcpServers, server.id, { command: event.target.value }))} />
                    </Field>
                    <Field label="URL">
                      <input value={server.url} onChange={(event) => updateWorkspaceMcpServers(updateItem(workspaceMcpServers, server.id, { url: event.target.value }))} />
                    </Field>
                  </>
                )}
              />
            )}
          </div>
        </aside>

        <main className="manager-main glass-panel">
          <div className="manager-main__head">
            <div>
              <h2>{managerView === "agents" ? "Agents 管理" : "Agent 管理"}</h2>
              <p>{managerView === "agents" ? "创建多 Agent 通信画布，可把已实现 Agent 作为节点连接。" : "管理历史创建的 Agent，点击后可继续编辑。"}</p>
            </div>
            <form
              className="manager-create"
              onSubmit={(event) => {
                event.preventDefault();
                void createNewProject(name, managerView);
              }}
            >
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder={defaultName(managerView)} />
              <button className="primary" disabled={loading} type="submit">
                <Plus size={16} />
                <span>{managerView === "agents" ? "新建 Agents" : "新建 Agent"}</span>
              </button>
            </form>
          </div>

          {filteredProjects.length === 0 ? (
            <div className="manager-empty">
              {managerView === "agents" ? "还没有多 Agent 画布。创建后可以引用已有 Agent 进行通信编排。" : "还没有历史 Agent。输入名称后创建第一个 Agent。"}
            </div>
          ) : (
            <div className="agent-grid">
              {filteredProjects.map((project) => (
                <AgentCard
                  key={project.id}
                  project={project}
                  onOpen={() => void openProject(project.id)}
                  onRename={(patch) => void renameProjectById(project.id, patch)}
                  onDelete={() => {
                    if (window.confirm(`删除「${project.name}」？`)) {
                      void deleteProjectById(project.id);
                    }
                  }}
                />
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function NavButton({
  active,
  icon,
  title,
  text,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  title: string;
  text: string;
  onClick: () => void;
}) {
  return (
    <button className={`manager-nav__item ${active ? "is-active" : ""}`} onClick={onClick} type="button">
      <span>{icon}</span>
      <strong>{title}</strong>
      <small>{text}</small>
    </button>
  );
}

function AgentCard({
  project,
  onOpen,
  onRename,
  onDelete,
}: {
  project: ProjectListItem;
  onOpen: () => void;
  onRename: (patch: { name?: string; description?: string }) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);

  useEffect(() => {
    setName(project.name);
    setDescription(project.description);
  }, [project.description, project.name]);

  function saveMeta() {
    const nextName = name.trim() || project.name;
    if (nextName !== project.name || description !== project.description) {
      onRename({ name: nextName, description });
    }
  }

  return (
    <article className="agent-card">
      <div className="agent-card__head">
        <div className="agent-card__meta">
          <input
            className="agent-card__name-input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={saveMeta}
            aria-label="修改 Agent 名称"
          />
          <input
            className="agent-card__description-input"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            onBlur={saveMeta}
            placeholder={project.id}
            aria-label="修改 Agent 描述"
          />
        </div>
        {project.kind === "agents" ? <Network size={20} /> : <Bot size={20} />}
      </div>
      <div className="agent-card__stats">
        <span>{project.kind === "agents" ? "Agents" : "Agent"}</span>
        <span>{project.nodeCount} 节点</span>
        <span>{project.edgeCount} 连线</span>
        <span>{project.toolCount} Tools</span>
        <span>{project.mcpCount} MCP</span>
        <span>{project.importedAgentCount} Agent</span>
      </div>
      <div className="agent-card__time">
        <Clock size={14} />
        <span>{formatTime(project.updatedAt)}</span>
      </div>
      <div className="agent-card__actions">
        <button onClick={onOpen} type="button">
          <Edit3 size={15} />
          <span>进入编辑</span>
        </button>
        <button onClick={saveMeta} type="button" title="保存名称和描述">
          <Save size={15} />
        </button>
        <button className="danger" onClick={onDelete} type="button">
          <Trash2 size={15} />
        </button>
      </div>
    </article>
  );
}

function TabButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={active ? "is-active" : ""} onClick={onClick} type="button">
      {icon}
      <span>{label}</span>
    </button>
  );
}

function WorkspaceResourceList<T extends { id: string }>({
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
  render: (item: T) => ReactNode;
}) {
  return (
    <div className="resource-list">
      <button className="resource-add" onClick={onAdd} type="button">
        <Plus size={15} />
        <span>添加配置</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">{emptyText}</div> : null}
      {items.map((item) => (
        <section key={item.id} className="resource-card">
          {render(item)}
          <button className="danger resource-remove" onClick={() => onRemove(item.id)} type="button">删除</button>
        </section>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
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
  return { id: createId("mcp"), name: "新 MCP", transport: "stdio", command: "", url: "", description: "" };
}

function createId(prefix: string) {
  return `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
}

function defaultName(kind: "agent" | "agents") {
  return kind === "agents" ? "新建 Agents" : "新建 Agent";
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleString("zh-CN", { hour12: false });
}
