import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bot,
  BrainCircuit,
  Check,
  Clock,
  Database,
  Edit3,
  Eye,
  EyeOff,
  Network,
  Plus,
  Save,
  Server,
  Trash2,
  Wrench,
} from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { MCPServerConfig, ModelConfig, ProjectListItem, RagKnowledgeBaseConfig, ToolConfig } from "../types";

type ResourceTab = "tools" | "mcp" | "rag" | "models";
type ManagerView = "agent" | "agents" | "tools" | "mcp" | "rag" | "models";
type ResourceEditorMode = "empty" | "create" | "edit";
type DialogState =
  | {
      kind: "alert";
      title: string;
      message: string;
      confirmText?: string;
    }
  | {
      kind: "confirm";
      title: string;
      message: string;
      confirmText?: string;
      cancelText?: string;
      danger?: boolean;
      onConfirm: () => void | Promise<void>;
    };

export function ManagementPage() {
  const projects = useProjectStore((state) => state.projects);
  const managerView = useProjectStore((state) => state.managerView);
  const workspaceTools = useProjectStore((state) => state.workspaceTools);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const workspaceRagKnowledgeBases = useProjectStore((state) => state.workspaceRagKnowledgeBases);
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
  const updateWorkspaceModelConfigs = useProjectStore((state) => state.updateWorkspaceModelConfigs);
  const updateWorkspaceRagKnowledgeBases = useProjectStore((state) => state.updateWorkspaceRagKnowledgeBases);
  const [name, setName] = useState(defaultName("agent"));
  const [resourceTab, setResourceTab] = useState<ResourceTab>("tools");
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [toolDraft, setToolDraft] = useState<ToolConfig>(() => newTool());
  const [toolEditorMode, setToolEditorMode] = useState<ResourceEditorMode>("empty");
  const [selectedMcpId, setSelectedMcpId] = useState<string | null>(null);
  const [mcpDraft, setMcpDraft] = useState<MCPServerConfig>(() => newMcpServer());
  const [mcpEditorMode, setMcpEditorMode] = useState<ResourceEditorMode>("empty");
  const [selectedRagId, setSelectedRagId] = useState<string | null>(null);
  const [ragDraft, setRagDraft] = useState<RagKnowledgeBaseConfig>(() => newRagKnowledgeBase());
  const [ragEditorMode, setRagEditorMode] = useState<ResourceEditorMode>("empty");
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [modelDraft, setModelDraft] = useState<ModelConfig>(() => newModelConfig(true, MODEL_PROVIDER_PRESETS[0]));
  const [modelEditorMode, setModelEditorMode] = useState<ResourceEditorMode>("empty");
  const [showApiKey, setShowApiKey] = useState(false);
  const [dialog, setDialog] = useState<DialogState | null>(null);

  useEffect(() => {
    void loadProjectList();
  }, [loadProjectList]);

  useEffect(() => {
    if (managerView === "agent" || managerView === "agents") {
      setName(defaultName(managerView));
    }
  }, [managerView]);

  useEffect(() => {
    if (managerView !== "tools") return;
    if (!selectedToolId) {
      if (toolEditorMode === "edit") setToolEditorMode("empty");
      return;
    }
    const selected = workspaceTools.find((tool) => tool.id === selectedToolId);
    if (selected) {
      setToolDraft(selected);
      return;
    }
    setSelectedToolId(null);
    setToolEditorMode("empty");
  }, [managerView, selectedToolId, toolEditorMode, workspaceTools]);

  useEffect(() => {
    if (managerView !== "mcp") return;
    if (!selectedMcpId) {
      if (mcpEditorMode === "edit") setMcpEditorMode("empty");
      return;
    }
    const selected = workspaceMcpServers.find((server) => server.id === selectedMcpId);
    if (selected) {
      setMcpDraft(selected);
      return;
    }
    setSelectedMcpId(null);
    setMcpEditorMode("empty");
  }, [managerView, mcpEditorMode, selectedMcpId, workspaceMcpServers]);

  useEffect(() => {
    if (managerView !== "rag") return;
    if (!selectedRagId) {
      if (ragEditorMode === "edit") setRagEditorMode("empty");
      return;
    }
    const selected = workspaceRagKnowledgeBases.find((item) => item.id === selectedRagId);
    if (selected) {
      setRagDraft(selected);
      return;
    }
    setSelectedRagId(null);
    setRagEditorMode("empty");
  }, [managerView, ragEditorMode, selectedRagId, workspaceRagKnowledgeBases]);

  useEffect(() => {
    if (managerView !== "models") return;
    if (!selectedModelId) {
      if (modelEditorMode === "edit") {
        setModelEditorMode("empty");
      }
      return;
    }
    const selected = workspaceModelConfigs.find((config) => config.id === selectedModelId);
    if (selected) {
      setModelDraft(selected);
      return;
    }
    setSelectedModelId(null);
    setModelEditorMode("empty");
  }, [managerView, modelEditorMode, selectedModelId, workspaceModelConfigs]);

  const filteredProjects = useMemo(
    () => (managerView === "agent" || managerView === "agents" ? projects.filter((project) => project.kind === managerView) : []),
    [managerView, projects],
  );

  const modelError = useMemo(
    () => (modelEditorMode === "empty" ? "" : getModelConfigError(modelDraft, workspaceModelConfigs)),
    [modelDraft, modelEditorMode, workspaceModelConfigs],
  );

  function updateModelDraft(patch: Partial<ModelConfig>) {
    setModelDraft((current) => ({ ...current, ...patch }));
  }

  function openToolManager(toolId?: string) {
    if (toolId) {
      const selected = workspaceTools.find((tool) => tool.id === toolId);
      setSelectedToolId(toolId);
      if (selected) setToolDraft(selected);
      setToolEditorMode("edit");
    } else {
      setSelectedToolId(null);
      setToolEditorMode("empty");
    }
    setManagerView("tools");
  }

  function createToolDraft() {
    setSelectedToolId(null);
    setToolDraft(newTool());
    setToolEditorMode("create");
    setManagerView("tools");
  }

  function saveToolDraft() {
    if (toolEditorMode === "empty") return;
    const normalized = { ...toolDraft, name: toolDraft.name.trim() || "未命名工具", schemaJson: toolDraft.schemaJson.trim() || "{}" };
    const exists = workspaceTools.some((tool) => tool.id === normalized.id);
    const next = exists ? workspaceTools.map((tool) => (tool.id === normalized.id ? normalized : tool)) : [...workspaceTools, normalized];
    void updateWorkspaceTools(next);
    setSelectedToolId(normalized.id);
    setToolEditorMode("edit");
  }

  function deleteToolDraft() {
    if (toolEditorMode === "empty") return;
    const exists = workspaceTools.some((tool) => tool.id === toolDraft.id);
    if (!exists) {
      setSelectedToolId(null);
      setToolEditorMode("empty");
      setToolDraft(newTool());
      return;
    }
    setDialog({
      kind: "confirm",
      title: "删除 Tool",
      message: `确定删除「${toolDraft.name}」？删除后节点库将不再显示该 Tool。`,
      confirmText: "删除",
      cancelText: "取消",
      danger: true,
      onConfirm: () => {
        void updateWorkspaceTools(workspaceTools.filter((tool) => tool.id !== toolDraft.id));
        setSelectedToolId(null);
        setToolEditorMode("empty");
        setToolDraft(newTool());
      },
    });
  }

  function openMcpManager(serverId?: string) {
    if (serverId) {
      const selected = workspaceMcpServers.find((server) => server.id === serverId);
      setSelectedMcpId(serverId);
      if (selected) setMcpDraft(selected);
      setMcpEditorMode("edit");
    } else {
      setSelectedMcpId(null);
      setMcpEditorMode("empty");
    }
    setManagerView("mcp");
  }

  function createMcpDraft() {
    setSelectedMcpId(null);
    setMcpDraft(newMcpServer());
    setMcpEditorMode("create");
    setManagerView("mcp");
  }

  function saveMcpDraft() {
    if (mcpEditorMode === "empty") return;
    const normalized = { ...mcpDraft, name: mcpDraft.name.trim() || "未命名 MCP", transport: mcpDraft.transport.trim() || "stdio" };
    const exists = workspaceMcpServers.some((server) => server.id === normalized.id);
    const next = exists ? workspaceMcpServers.map((server) => (server.id === normalized.id ? normalized : server)) : [...workspaceMcpServers, normalized];
    void updateWorkspaceMcpServers(next);
    setSelectedMcpId(normalized.id);
    setMcpEditorMode("edit");
  }

  function deleteMcpDraft() {
    if (mcpEditorMode === "empty") return;
    const exists = workspaceMcpServers.some((server) => server.id === mcpDraft.id);
    if (!exists) {
      setSelectedMcpId(null);
      setMcpEditorMode("empty");
      setMcpDraft(newMcpServer());
      return;
    }
    setDialog({
      kind: "confirm",
      title: "删除 MCP",
      message: `确定删除「${mcpDraft.name}」？删除后节点库将不再显示该 MCP Server。`,
      confirmText: "删除",
      cancelText: "取消",
      danger: true,
      onConfirm: () => {
        void updateWorkspaceMcpServers(workspaceMcpServers.filter((server) => server.id !== mcpDraft.id));
        setSelectedMcpId(null);
        setMcpEditorMode("empty");
        setMcpDraft(newMcpServer());
      },
    });
  }

  function openRagManager(knowledgeBaseId?: string) {
    if (knowledgeBaseId) {
      const selected = workspaceRagKnowledgeBases.find((item) => item.id === knowledgeBaseId);
      setSelectedRagId(knowledgeBaseId);
      if (selected) setRagDraft(selected);
      setRagEditorMode("edit");
    } else {
      setSelectedRagId(null);
      setRagEditorMode("empty");
    }
    setManagerView("rag");
  }

  function createRagDraft() {
    setSelectedRagId(null);
    setRagDraft(newRagKnowledgeBase());
    setRagEditorMode("create");
    setManagerView("rag");
  }

  function saveRagDraft() {
    if (ragEditorMode === "empty") return;
    const normalized = normalizeRagDraft(ragDraft);
    const exists = workspaceRagKnowledgeBases.some((item) => item.id === normalized.id);
    const next = exists
      ? workspaceRagKnowledgeBases.map((item) => (item.id === normalized.id ? normalized : item))
      : [...workspaceRagKnowledgeBases, normalized];
    void updateWorkspaceRagKnowledgeBases(next);
    setSelectedRagId(normalized.id);
    setRagEditorMode("edit");
  }

  function deleteRagDraft() {
    if (ragEditorMode === "empty") return;
    const exists = workspaceRagKnowledgeBases.some((item) => item.id === ragDraft.id);
    if (!exists) {
      setSelectedRagId(null);
      setRagEditorMode("empty");
      setRagDraft(newRagKnowledgeBase());
      return;
    }
    setDialog({
      kind: "confirm",
      title: "删除 RAG 知识库",
      message: `确定删除「${ragDraft.name}」？删除后 Retriever 节点将无法再选择该知识库。`,
      confirmText: "删除",
      cancelText: "取消",
      danger: true,
      onConfirm: () => {
        void updateWorkspaceRagKnowledgeBases(workspaceRagKnowledgeBases.filter((item) => item.id !== ragDraft.id));
        setSelectedRagId(null);
        setRagEditorMode("empty");
        setRagDraft(newRagKnowledgeBase());
      },
    });
  }

  function openModelManager(modelId?: string) {
    if (modelId) {
      setSelectedModelId(modelId);
      setModelEditorMode("edit");
    } else {
      setSelectedModelId(null);
      setModelEditorMode("empty");
    }
    setManagerView("models");
  }

  function createModelDraft(preset = MODEL_PROVIDER_PRESETS[0]) {
    const draft = newModelConfig(workspaceModelConfigs.length === 0, preset);
    setSelectedModelId(null);
    setModelDraft(ensureUniqueCustomName(draft, workspaceModelConfigs));
    setModelEditorMode("create");
    setManagerView("models");
  }

  function saveModelDraft() {
    if (modelEditorMode === "empty") return;
    const error = getModelConfigError(modelDraft, workspaceModelConfigs);
    if (error) {
      setDialog({
        kind: "alert",
        title: "无法保存模型配置",
        message: error,
        confirmText: "知道了",
      });
      return;
    }
    const normalized = normalizeModelDraft(modelDraft);
    const exists = workspaceModelConfigs.some((config) => config.id === normalized.id);
    const next = exists
      ? workspaceModelConfigs.map((config) => (config.id === normalized.id ? normalized : config))
      : [...workspaceModelConfigs, normalized];
    void updateWorkspaceModelConfigs(normalized.isDefault ? setDefaultModelConfig(next, normalized.id) : next);
    setSelectedModelId(normalized.id);
    setModelEditorMode("edit");
  }

  function deleteModelDraft() {
    if (modelEditorMode === "empty") return;
    const exists = workspaceModelConfigs.some((config) => config.id === modelDraft.id);
    if (!exists) {
      setSelectedModelId(null);
      setModelEditorMode("empty");
      setModelDraft(newModelConfig(workspaceModelConfigs.length === 0, MODEL_PROVIDER_PRESETS[0]));
      return;
    }
    setDialog({
      kind: "confirm",
      title: "删除模型配置",
      message: `确定删除「${modelDraft.name}」？删除后运行预览将不能再选择这个模型配置。`,
      confirmText: "删除",
      cancelText: "取消",
      danger: true,
      onConfirm: () => {
        const next = workspaceModelConfigs.filter((config) => config.id !== modelDraft.id);
        void updateWorkspaceModelConfigs(next);
        setSelectedModelId(null);
        setModelEditorMode("empty");
        setModelDraft(newModelConfig(next.length === 0, MODEL_PROVIDER_PRESETS[0]));
      },
    });
  }

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
            <NavButton
              active={managerView === "tools"}
              icon={<Wrench size={17} />}
              title="Tools"
              text="管理可作为节点调用的工具"
              onClick={() => openToolManager()}
            />
            <NavButton
              active={managerView === "mcp"}
              icon={<Server size={17} />}
              title="MCP"
              text="管理 MCP Server 连接"
              onClick={() => openMcpManager()}
            />
            <NavButton
              active={managerView === "rag"}
              icon={<Database size={17} />}
              title="RAG"
              text="管理可检索知识库"
              onClick={() => openRagManager()}
            />
            <NavButton
              active={managerView === "models"}
              icon={<BrainCircuit size={17} />}
              title="模型"
              text="配置运行测试模型服务商"
              onClick={() => openModelManager()}
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
              <TabButton active={resourceTab === "rag"} icon={<Database size={15} />} label="RAG" onClick={() => setResourceTab("rag")} />
              <TabButton active={resourceTab === "models"} icon={<BrainCircuit size={15} />} label="模型" onClick={() => setResourceTab("models")} />
            </div>
            {resourceTab === "tools" ? (
              <ReadonlyToolResourceList
                items={workspaceTools}
                onCreate={createToolDraft}
                onOpen={openToolManager}
              />
            ) : resourceTab === "mcp" ? (
              <ReadonlyMcpResourceList
                items={workspaceMcpServers}
                onCreate={createMcpDraft}
                onOpen={openMcpManager}
              />
            ) : resourceTab === "rag" ? (
              <ReadonlyRagResourceList
                items={workspaceRagKnowledgeBases}
                onCreate={createRagDraft}
                onOpen={openRagManager}
              />
            ) : (
              <ReadonlyModelResourceList
                items={workspaceModelConfigs}
                onCreate={() => createModelDraft()}
                onOpen={openModelManager}
              />
            )}
          </div>
        </aside>

        <main className="manager-main glass-panel">
          {managerView === "tools" ? (
            <ToolManagerContent
              items={workspaceTools}
              draft={toolDraft}
              editorMode={toolEditorMode}
              selectedId={selectedToolId}
              onSelect={(tool) => {
                setSelectedToolId(tool.id);
                setToolDraft(tool);
                setToolEditorMode("edit");
              }}
              onNew={createToolDraft}
              onChange={(patch) => setToolDraft((current) => ({ ...current, ...patch }))}
              onSave={saveToolDraft}
              onDelete={deleteToolDraft}
              onCancel={() => {
                setSelectedToolId(null);
                setToolEditorMode("empty");
                setToolDraft(newTool());
              }}
            />
          ) : managerView === "mcp" ? (
            <McpManagerContent
              items={workspaceMcpServers}
              draft={mcpDraft}
              editorMode={mcpEditorMode}
              selectedId={selectedMcpId}
              onSelect={(server) => {
                setSelectedMcpId(server.id);
                setMcpDraft(server);
                setMcpEditorMode("edit");
              }}
              onNew={createMcpDraft}
              onChange={(patch) => setMcpDraft((current) => ({ ...current, ...patch }))}
              onSave={saveMcpDraft}
              onDelete={deleteMcpDraft}
              onCancel={() => {
                setSelectedMcpId(null);
                setMcpEditorMode("empty");
                setMcpDraft(newMcpServer());
              }}
            />
          ) : managerView === "rag" ? (
            <RagManagerContent
              items={workspaceRagKnowledgeBases}
              draft={ragDraft}
              editorMode={ragEditorMode}
              selectedId={selectedRagId}
              onSelect={(knowledgeBase) => {
                setSelectedRagId(knowledgeBase.id);
                setRagDraft(knowledgeBase);
                setRagEditorMode("edit");
              }}
              onNew={createRagDraft}
              onChange={(patch) => setRagDraft((current) => ({ ...current, ...patch }))}
              onSave={saveRagDraft}
              onDelete={deleteRagDraft}
              onCancel={() => {
                setSelectedRagId(null);
                setRagEditorMode("empty");
                setRagDraft(newRagKnowledgeBase());
              }}
            />
          ) : managerView === "models" ? (
            <ModelManagerContent
              configs={workspaceModelConfigs}
              draft={modelDraft}
              error={modelError}
              editorMode={modelEditorMode}
              selectedModelId={selectedModelId}
              onSelect={(config) => {
                setSelectedModelId(config.id);
                setModelDraft(config);
                setModelEditorMode("edit");
              }}
              onNew={() => createModelDraft()}
              onPreset={(preset) => setModelDraft((current) => applyProviderPreset(current, preset))}
              onChange={updateModelDraft}
              showApiKey={showApiKey}
              onToggleApiKey={() => setShowApiKey((value) => !value)}
              onSave={saveModelDraft}
              onDelete={deleteModelDraft}
              onCancel={() => {
                setSelectedModelId(null);
                setModelEditorMode("empty");
                setModelDraft(newModelConfig(workspaceModelConfigs.length === 0, MODEL_PROVIDER_PRESETS[0]));
              }}
            />
          ) : (
            <ProjectManagerContent
              kind={managerView}
              name={name}
              loading={loading}
              projects={filteredProjects}
              onNameChange={setName}
              onCreate={() => void createNewProject(name, managerView)}
              onOpen={(projectId) => void openProject(projectId)}
              onRename={(projectId, patch) => void renameProjectById(projectId, patch)}
              onDelete={(project) =>
                setDialog({
                  kind: "confirm",
                  title: "删除 Agent",
                  message: `确定删除「${project.name}」？该操作会移除这个历史项目。`,
                  confirmText: "删除",
                  cancelText: "取消",
                  danger: true,
                  onConfirm: () => void deleteProjectById(project.id),
                })
              }
            />
          )}
        </main>
      </div>
      <AppDialog dialog={dialog} onClose={() => setDialog(null)} />
    </div>
  );
}

function AppDialog({ dialog, onClose }: { dialog: DialogState | null; onClose: () => void }) {
  if (!dialog) return null;

  async function handleConfirm() {
    if (!dialog) return;
    if (dialog.kind === "confirm") {
      await dialog.onConfirm();
    }
    onClose();
  }

  return (
    <div className="app-modal-backdrop" role="presentation">
      <section className="app-modal glass-panel" role="dialog" aria-modal="true" aria-labelledby="app-modal-title">
        <div className="app-modal__icon">{dialog.kind === "confirm" ? <Trash2 size={18} /> : <BrainCircuit size={18} />}</div>
        <div className="app-modal__body">
          <h2 id="app-modal-title">{dialog.title}</h2>
          <p>{dialog.message}</p>
        </div>
        <div className="app-modal__actions">
          {dialog.kind === "confirm" ? (
            <button onClick={onClose} type="button">
              {dialog.cancelText ?? "取消"}
            </button>
          ) : null}
          <button className={dialog.kind === "confirm" && dialog.danger ? "danger primary-danger" : "primary"} onClick={() => void handleConfirm()} type="button">
            {dialog.confirmText ?? "确定"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ProjectManagerContent({
  kind,
  name,
  loading,
  projects,
  onNameChange,
  onCreate,
  onOpen,
  onRename,
  onDelete,
}: {
  kind: "agent" | "agents";
  name: string;
  loading: boolean;
  projects: ProjectListItem[];
  onNameChange: (name: string) => void;
  onCreate: () => void;
  onOpen: (projectId: string) => void;
  onRename: (projectId: string, patch: { name?: string; description?: string }) => void;
  onDelete: (project: ProjectListItem) => void;
}) {
  return (
    <>
      <div className="manager-main__head">
        <div>
          <h2>{kind === "agents" ? "Agents 管理" : "Agent 管理"}</h2>
          <p>{kind === "agents" ? "创建多 Agent 通信画布，可把已实现 Agent 作为节点连接。" : "管理历史创建的 Agent，点击后可继续编辑。"}</p>
        </div>
        <form
          className="manager-create"
          onSubmit={(event) => {
            event.preventDefault();
            onCreate();
          }}
        >
          <input value={name} onChange={(event) => onNameChange(event.target.value)} placeholder={defaultName(kind)} />
          <button className="primary" disabled={loading} type="submit">
            <Plus size={16} />
            <span>{kind === "agents" ? "新建 Agents" : "新建 Agent"}</span>
          </button>
        </form>
      </div>

      {projects.length === 0 ? (
        <div className="manager-empty">
          {kind === "agents" ? "还没有多 Agent 画布。创建后可以引用已有 Agent 进行通信编排。" : "还没有历史 Agent。输入名称后创建第一个 Agent。"}
        </div>
      ) : (
        <div className="agent-grid">
          {projects.map((project) => (
            <AgentCard
              key={project.id}
              project={project}
              onOpen={() => onOpen(project.id)}
              onRename={(patch) => onRename(project.id, patch)}
              onDelete={() => onDelete(project)}
            />
          ))}
        </div>
      )}
    </>
  );
}

function ToolManagerContent({
  items,
  draft,
  editorMode,
  selectedId,
  onSelect,
  onNew,
  onChange,
  onSave,
  onDelete,
  onCancel,
}: {
  items: ToolConfig[];
  draft: ToolConfig;
  editorMode: ResourceEditorMode;
  selectedId: string | null;
  onSelect: (item: ToolConfig) => void;
  onNew: () => void;
  onChange: (patch: Partial<ToolConfig>) => void;
  onSave: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="model-manager">
      <ResourceManagerHead title="Tools 配置" text="管理可在节点库 Skill Node 分组中选择的工具资源。" actionText="新增 Tool" onNew={onNew} />
      <div className="model-manager__body">
        <ResourceListPanel
          title="已配置 Tools"
          emptyText="还没有 Tool。点击右上角新增 Tool 后保存。"
          items={items}
          selectedId={selectedId}
          onSelect={onSelect}
          renderMeta={(item) => `${item.source || "tool"} · ${item.description || "未填写描述"}`}
          renderMark={() => <Wrench size={16} />}
        />
        <section className="model-editor-panel">
          {editorMode === "empty" ? (
            <ResourceEditorEmpty icon={<Wrench size={24} />} title="未选择 Tool" text="从左侧选择一个已配置 Tool 进行编辑，或点击右上角新增 Tool。" />
          ) : (
            <div className="model-editor-card">
              <ResourceEditorHead title={editorMode === "create" ? "新增 Tool" : "编辑 Tool"} text="配置工具名称、来源、说明和参数 Schema。" mode={editorMode} onCancel={onCancel} onDelete={onDelete} onSave={onSave} />
              <Field label="名称">
                <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} />
              </Field>
              <Field label="来源">
                <select value={draft.source} onChange={(event) => onChange({ source: event.target.value })}>
                  <option value="python">Python</option>
                  <option value="http">HTTP</option>
                  <option value="openapi">OpenAPI</option>
                </select>
              </Field>
              <Field label="描述">
                <textarea rows={4} value={draft.description} onChange={(event) => onChange({ description: event.target.value })} />
              </Field>
              <Field label="参数 Schema JSON">
                <textarea className="code-area" rows={10} value={draft.schemaJson} onChange={(event) => onChange({ schemaJson: event.target.value })} />
              </Field>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function McpManagerContent({
  items,
  draft,
  editorMode,
  selectedId,
  onSelect,
  onNew,
  onChange,
  onSave,
  onDelete,
  onCancel,
}: {
  items: MCPServerConfig[];
  draft: MCPServerConfig;
  editorMode: ResourceEditorMode;
  selectedId: string | null;
  onSelect: (item: MCPServerConfig) => void;
  onNew: () => void;
  onChange: (patch: Partial<MCPServerConfig>) => void;
  onSave: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="model-manager">
      <ResourceManagerHead title="MCP 配置" text="管理可在节点库 MCP Node 分组中选择的 MCP Server。" actionText="新增 MCP" onNew={onNew} />
      <div className="model-manager__body">
        <ResourceListPanel
          title="已配置 MCP"
          emptyText="还没有 MCP Server。点击右上角新增 MCP 后保存。"
          items={items}
          selectedId={selectedId}
          onSelect={onSelect}
          renderMeta={(item) => `${item.transport || "stdio"} · ${item.command || item.url || "未配置入口"}`}
          renderMark={() => <Server size={16} />}
        />
        <section className="model-editor-panel">
          {editorMode === "empty" ? (
            <ResourceEditorEmpty icon={<Server size={24} />} title="未选择 MCP" text="从左侧选择一个已配置 MCP 进行编辑，或点击右上角新增 MCP。" />
          ) : (
            <div className="model-editor-card">
              <ResourceEditorHead title={editorMode === "create" ? "新增 MCP" : "编辑 MCP"} text="配置 MCP Server 的传输方式、启动命令或远程地址。" mode={editorMode} onCancel={onCancel} onDelete={onDelete} onSave={onSave} />
              <Field label="名称">
                <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} />
              </Field>
              <Field label="Transport">
                <select value={draft.transport} onChange={(event) => onChange({ transport: event.target.value })}>
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                </select>
              </Field>
              <Field label="Command">
                <input value={draft.command} onChange={(event) => onChange({ command: event.target.value })} />
              </Field>
              <Field label="URL">
                <input value={draft.url} onChange={(event) => onChange({ url: event.target.value })} />
              </Field>
              <Field label="描述">
                <textarea rows={4} value={draft.description} onChange={(event) => onChange({ description: event.target.value })} />
              </Field>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function RagManagerContent({
  items,
  draft,
  editorMode,
  selectedId,
  onSelect,
  onNew,
  onChange,
  onSave,
  onDelete,
  onCancel,
}: {
  items: RagKnowledgeBaseConfig[];
  draft: RagKnowledgeBaseConfig;
  editorMode: ResourceEditorMode;
  selectedId: string | null;
  onSelect: (item: RagKnowledgeBaseConfig) => void;
  onNew: () => void;
  onChange: (patch: Partial<RagKnowledgeBaseConfig>) => void;
  onSave: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="model-manager">
      <ResourceManagerHead title="RAG 配置" text="管理可在节点库 RAG 分组和 Retriever 节点中选择的知识库。" actionText="新增知识库" onNew={onNew} />
      <div className="model-manager__body">
        <ResourceListPanel
          title="已配置 RAG"
          emptyText="还没有 RAG 知识库。点击右上角新增知识库后保存。"
          items={items}
          selectedId={selectedId}
          onSelect={onSelect}
          renderMeta={(item) => `${ragSourceLabel(item.sourceType)} · ${item.path || item.url || item.collection || "未配置入口"}`}
          renderMark={() => <Database size={16} />}
          renderBadge={(item) => (item.enabled ? null : "停用")}
        />
        <section className="model-editor-panel">
          {editorMode === "empty" ? (
            <ResourceEditorEmpty icon={<Database size={24} />} title="未选择知识库" text="从左侧选择一个已配置知识库进行编辑，或点击右上角新增知识库。" />
          ) : (
            <div className="model-editor-card">
              <ResourceEditorHead title={editorMode === "create" ? "新增知识库" : "编辑知识库"} text="配置知识库来源、入口、集合信息和默认检索参数。" mode={editorMode} onCancel={onCancel} onDelete={onDelete} onSave={onSave} />
              <Field label="知识库名称">
                <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} />
              </Field>
              <Field label="导入类型">
                <select value={draft.sourceType} onChange={(event) => onChange({ sourceType: event.target.value })}>
                  <option value="local_directory">本地目录</option>
                  <option value="local_files">本地文件集合</option>
                  <option value="vectorstore">已有向量库</option>
                  <option value="http_api">HTTP 检索 API</option>
                  <option value="database">数据库 / 表</option>
                </select>
              </Field>
              <Field label="路径 / 文件 / 数据库表">
                <input value={draft.path} placeholder="./knowledge 或 docs/*.md" onChange={(event) => onChange({ path: event.target.value })} />
              </Field>
              <Field label="Endpoint / 连接地址">
                <input value={draft.url} placeholder="https://api.example.com/search" onChange={(event) => onChange({ url: event.target.value })} />
              </Field>
              <div className="inline-grid">
                <Field label="集合 / Index">
                  <input value={draft.collection} onChange={(event) => onChange({ collection: event.target.value })} />
                </Field>
                <Field label="Top K">
                  <input min={1} type="number" value={String(draft.topK)} onChange={(event) => onChange({ topK: Number(event.target.value) })} />
                </Field>
              </div>
              <Field label="Embedding 模型">
                <input value={draft.embeddingModel} placeholder="text-embedding-3-small / bge-m3" onChange={(event) => onChange({ embeddingModel: event.target.value })} />
              </Field>
              <Field label="描述">
                <textarea rows={4} value={draft.description} onChange={(event) => onChange({ description: event.target.value })} />
              </Field>
              <Field label="元数据 JSON">
                <textarea className="code-area" rows={8} value={draft.metadataJson} onChange={(event) => onChange({ metadataJson: event.target.value })} />
              </Field>
              <div className="model-flags">
                <label>
                  <input type="checkbox" checked={draft.enabled} onChange={(event) => onChange({ enabled: event.target.checked })} />
                  <span>启用</span>
                </label>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ResourceManagerHead({ title, text, actionText, onNew }: { title: string; text: string; actionText: string; onNew: () => void }) {
  return (
    <div className="manager-main__head">
      <div>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
      <button className="primary" onClick={onNew} type="button">
        <Plus size={16} />
        <span>{actionText}</span>
      </button>
    </div>
  );
}

function ResourceListPanel<T extends { id: string; name: string }>({
  title,
  emptyText,
  items,
  selectedId,
  onSelect,
  renderMeta,
  renderMark,
  renderBadge,
}: {
  title: string;
  emptyText: string;
  items: T[];
  selectedId: string | null;
  onSelect: (item: T) => void;
  renderMeta: (item: T) => string;
  renderMark: (item: T) => ReactNode;
  renderBadge?: (item: T) => string | null;
}) {
  return (
    <aside className="model-list-panel">
      <div className="panel-title">
        <span>{title}</span>
        <small>{items.length} 个</small>
      </div>
      {items.length === 0 ? (
        <div className="model-list-empty">{emptyText}</div>
      ) : (
        <div className="model-list">
          {items.map((item) => {
            const badge = renderBadge?.(item);
            return (
              <button key={item.id} className={`model-list-item ${selectedId === item.id ? "is-active" : ""}`} onClick={() => onSelect(item)} type="button">
                <span className="model-list-item__mark">{renderMark(item)}</span>
                <span>
                  <strong>{item.name}</strong>
                  <small>{renderMeta(item)}</small>
                </span>
                {badge ? <em>{badge}</em> : null}
              </button>
            );
          })}
        </div>
      )}
    </aside>
  );
}

function ResourceEditorEmpty({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div className="model-editor-empty">
      {icon}
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}

function ResourceEditorHead({
  title,
  text,
  mode,
  onCancel,
  onDelete,
  onSave,
}: {
  title: string;
  text: string;
  mode: ResourceEditorMode;
  onCancel: () => void;
  onDelete: () => void;
  onSave: () => void;
}) {
  return (
    <div className="model-editor-card__head">
      <div>
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
      <div className="model-editor-actions">
        {mode === "edit" ? (
          <button onClick={onDelete} type="button">
            <Trash2 size={15} />
            <span>删除</span>
          </button>
        ) : (
          <button onClick={onCancel} type="button">
            <span>取消</span>
          </button>
        )}
        <button className="primary" onClick={onSave} type="button">
          <Save size={15} />
          <span>保存</span>
        </button>
      </div>
    </div>
  );
}

function ModelManagerContent({
  configs,
  draft,
  error,
  editorMode,
  selectedModelId,
  onSelect,
  onNew,
  onPreset,
  onChange,
  showApiKey,
  onToggleApiKey,
  onSave,
  onDelete,
  onCancel,
}: {
  configs: ModelConfig[];
  draft: ModelConfig;
  error: string;
  editorMode: ResourceEditorMode;
  selectedModelId: string | null;
  onSelect: (config: ModelConfig) => void;
  onNew: () => void;
  onPreset: (preset: ModelProviderPreset) => void;
  onChange: (patch: Partial<ModelConfig>) => void;
  showApiKey: boolean;
  onToggleApiKey: () => void;
  onSave: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  const extraOptions = useMemo(() => readOptionRows(draft.extraOptionsJson), [draft.extraOptionsJson]);
  const modelRows = useMemo(() => readModelRows(draft), [draft]);
  const configJson = useMemo(() => buildConfigJson(draft), [draft]);

  return (
    <div className="model-manager">
      <div className="manager-main__head">
        <div>
          <h2>模型配置</h2>
          <p>维护运行测试 Agent 使用的模型服务商。节点资源中只能加载这些配置，不能直接管理。</p>
        </div>
        <button className="primary" onClick={onNew} type="button">
          <Plus size={16} />
          <span>新增模型配置</span>
        </button>
      </div>

      <div className="model-manager__body">
        <aside className="model-list-panel">
          <div className="panel-title">
            <span>已配置模型</span>
            <small>{configs.length} 个</small>
          </div>
          {configs.length === 0 ? (
            <div className="model-list-empty">还没有模型配置。点击右上角新增模型配置后保存。</div>
          ) : (
            <div className="model-list">
              {configs.map((config) => (
                <button
                  key={config.id}
                  className={`model-list-item ${selectedModelId === config.id ? "is-active" : ""}`}
                  onClick={() => onSelect(config)}
                  type="button"
                >
                  <span className="model-list-item__mark">{providerInitial(config)}</span>
                  <span>
                    <strong>{config.name}</strong>
                    <small>{config.provider} · {config.model || "未设置模型"}</small>
                  </span>
                  {config.isDefault ? <em>默认</em> : null}
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="model-editor-panel">
          {editorMode === "empty" ? (
            <div className="model-editor-empty">
              <BrainCircuit size={24} />
              <h3>未选择模型配置</h3>
              <p>从左侧选择一个已配置模型进行编辑，或点击右上角新增模型配置。</p>
            </div>
          ) : (
          <div className="model-editor-card">
            <div className="model-editor-card__head">
              <div>
                <h3>{editorMode === "create" ? "新增模型配置" : "编辑模型配置"}</h3>
                <p>{editorMode === "create" ? "选择预设后会自动填充接口格式、Base URL 和环境变量名；自定义配置允许多个，但名称不能重复。" : "维护已保存模型的基础信息、密钥、接口参数和可用模型列表。"}</p>
              </div>
              <div className="model-editor-actions">
                {editorMode === "edit" ? (
                  <button onClick={onDelete} type="button">
                    <Trash2 size={15} />
                    <span>删除</span>
                  </button>
                ) : (
                  <button onClick={onCancel} type="button">
                    <span>取消</span>
                  </button>
                )}
                <button className="primary" disabled={Boolean(error)} onClick={onSave} type="button">
                  <Save size={15} />
                  <span>保存</span>
                </button>
              </div>
            </div>

            {editorMode === "create" ? (
              <div className="provider-section">
                <span className="provider-section__label">预设供应商</span>
                <div className="provider-chip-grid">
                  {MODEL_PROVIDER_PRESETS.map((preset) => (
                    <button
                      key={preset.provider}
                      className={`provider-chip ${draft.provider === preset.provider ? "is-active" : ""}`}
                      onClick={() => onPreset(preset)}
                      type="button"
                    >
                      {draft.provider === preset.provider ? <Check size={13} /> : null}
                      <span>{preset.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="provider-avatar">{providerInitial(draft)}</div>

            <div className="inline-grid">
              <Field label="供应商标识 *">
                <input
                  value={draft.provider}
                  placeholder="my-provider"
                  onChange={(event) => onChange({ provider: normalizeProviderId(event.target.value) })}
                />
              </Field>
              <Field label="供应商名称 *">
                <input value={draft.name} placeholder="例如：DeepSeek 官方" onChange={(event) => onChange({ name: event.target.value })} />
              </Field>
            </div>
            <div className="inline-grid">
              <Field label="默认模型">
                <input value={draft.model} placeholder="例如：deepseek-chat" onChange={(event) => onChange({ model: event.target.value })} />
              </Field>
              <Field label="备注">
                <input value={draft.notes} placeholder="例如：公司专用账号" onChange={(event) => onChange({ notes: event.target.value })} />
              </Field>
            </div>

            <Field label="官网链接">
              <input value={draft.homepage} placeholder="https://example.com（可选）" onChange={(event) => onChange({ homepage: event.target.value })} />
            </Field>

            <Field label="接口格式">
              <select value={draft.apiFormat} onChange={(event) => onChange({ apiFormat: event.target.value })}>
                <option value="openai_compatible">OpenAI Compatible</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="google">Google Gemini</option>
                <option value="azure_openai">Azure OpenAI</option>
                <option value="ollama">Ollama Local</option>
              </select>
            </Field>

            <Field label="API Key">
              <div className="secret-input">
                <input
                  type={showApiKey ? "text" : "password"}
                  value={draft.apiKey}
                  placeholder="只需要填这里，下方配置会自动填充"
                  onChange={(event) => onChange({ apiKey: event.target.value })}
                />
                <button className="icon-only" onClick={onToggleApiKey} title={showApiKey ? "隐藏 API Key" : "显示 API Key"} type="button">
                  {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </Field>

            <Field label="Base URL">
              <input value={draft.baseUrl} placeholder="https://api.example.com/v1" onChange={(event) => onChange({ baseUrl: event.target.value })} />
            </Field>

            {draft.apiFormat === "azure_openai" || draft.provider === "azure_openai" ? (
              <Field label="Azure API Version">
                <input value={draft.apiVersion} placeholder="如 2024-10-21" onChange={(event) => onChange({ apiVersion: event.target.value })} />
              </Field>
            ) : null}

            <div className="model-extra-section">
              <div className="model-extra-section__head">
                <span>额外选项</span>
                <button
                  onClick={() => onChange({ extraOptionsJson: writeOptionRows([...extraOptions, { key: "setCacheKey", value: "true" }]) })}
                  type="button"
                >
                  <Plus size={14} />
                  <span>添加</span>
                </button>
              </div>
              {extraOptions.length === 0 ? (
                <div className="model-extra-empty">暂无额外选项。</div>
              ) : (
                <div className="model-extra-list">
                  {extraOptions.map((option, index) => (
                    <div key={`${option.key}-${index}`} className="model-extra-row">
                      <input
                        value={option.key}
                        placeholder="键名"
                        onChange={(event) => onChange({ extraOptionsJson: writeOptionRows(replaceOption(extraOptions, index, { ...option, key: event.target.value })) })}
                      />
                      <input
                        value={option.value}
                        placeholder="值"
                        onChange={(event) => onChange({ extraOptionsJson: writeOptionRows(replaceOption(extraOptions, index, { ...option, value: event.target.value })) })}
                      />
                      <button
                        className="icon-only"
                        onClick={() => onChange({ extraOptionsJson: writeOptionRows(extraOptions.filter((_, itemIndex) => itemIndex !== index)) })}
                        title="删除选项"
                        type="button"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="model-extra-section">
              <div className="model-extra-section__head">
                <span>模型配置</span>
                <div className="model-section-actions">
                  <button onClick={() => onChange({ modelRowsJson: writeModelRows(modelRows) })} type="button">
                    <span>获取模型列表</span>
                  </button>
                  <button onClick={() => onChange({ modelRowsJson: writeModelRows([...modelRows, newEmptyModelRow()]) })} type="button">
                    <Plus size={14} />
                    <span>添加模型</span>
                  </button>
                </div>
              </div>
              <div className="model-row-list">
                <div className="model-row model-row--head">
                  <span />
                  <span>模型 ID</span>
                  <span>显示名称</span>
                  <span />
                </div>
                {modelRows.map((row, index) => (
                  <div key={row.rowId} className="model-row">
                    <span className="model-row__chevron">›</span>
                    <input
                      value={row.id}
                      placeholder={`model-${Date.now()}`}
                      onChange={(event) => onChange({ modelRowsJson: writeModelRows(replaceModelRow(modelRows, index, { ...row, id: event.target.value })) })}
                    />
                    <input
                      value={row.name}
                      placeholder="显示名称"
                      onChange={(event) => onChange({ modelRowsJson: writeModelRows(replaceModelRow(modelRows, index, { ...row, name: event.target.value })) })}
                    />
                    <button
                      className="icon-only"
                      onClick={() => onChange({ modelRowsJson: writeModelRows(removeModelRow(modelRows, index)) })}
                      title="删除模型"
                      type="button"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
              <p className="model-section-note">配置可用的模型及其显示名称；只有模型 ID 和显示名称都填写的行会进入配置 JSON。</p>
            </div>

            <div className="model-flags">
              <label>
                <input type="checkbox" checked={draft.enabled} onChange={(event) => onChange({ enabled: event.target.checked })} />
                <span>启用</span>
              </label>
              <label>
                <input type="checkbox" checked={draft.isDefault} onChange={(event) => onChange({ isDefault: event.target.checked, enabled: event.target.checked ? true : draft.enabled })} />
                <span>设为默认运行模型</span>
              </label>
            </div>

            {error ? <div className="model-error">{error}</div> : null}

            <Field label="配置 JSON">
              <textarea className="code-area model-config-json" rows={10} readOnly value={configJson} />
            </Field>
          </div>
          )}
        </section>
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

function ReadonlyToolResourceList({
  items,
  onCreate,
  onOpen,
}: {
  items: ToolConfig[];
  onCreate: () => void;
  onOpen: (id?: string) => void;
}) {
  return (
    <div className="resource-list">
      <button className="resource-add" onClick={onCreate} type="button">
        <Plus size={15} />
        <span>去 Tools 管理添加</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">还没有 Tool。这里仅展示已配置资源，管理请进入右侧「Tools」区域。</div> : null}
      {items.map((item) => (
        <button key={item.id} className="resource-card resource-model-card" onClick={() => onOpen(item.id)} type="button">
          <span className="resource-model-card__icon">
            <Wrench size={15} />
          </span>
          <span>
            <strong>{item.name}</strong>
            <small>{item.source} · {item.description || "未填写描述"}</small>
          </span>
        </button>
      ))}
    </div>
  );
}

function ReadonlyMcpResourceList({
  items,
  onCreate,
  onOpen,
}: {
  items: MCPServerConfig[];
  onCreate: () => void;
  onOpen: (id?: string) => void;
}) {
  return (
    <div className="resource-list">
      <button className="resource-add" onClick={onCreate} type="button">
        <Plus size={15} />
        <span>去 MCP 管理添加</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">还没有 MCP Server。这里仅展示已配置资源，管理请进入右侧「MCP」区域。</div> : null}
      {items.map((item) => (
        <button key={item.id} className="resource-card resource-model-card" onClick={() => onOpen(item.id)} type="button">
          <span className="resource-model-card__icon">
            <Server size={15} />
          </span>
          <span>
            <strong>{item.name}</strong>
            <small>{item.transport} · {item.command || item.url || "未配置入口"}</small>
          </span>
        </button>
      ))}
    </div>
  );
}

function ReadonlyRagResourceList({
  items,
  onCreate,
  onOpen,
}: {
  items: RagKnowledgeBaseConfig[];
  onCreate: () => void;
  onOpen: (id?: string) => void;
}) {
  return (
    <div className="resource-list">
      <button className="resource-add" onClick={onCreate} type="button">
        <Plus size={15} />
        <span>去 RAG 管理添加</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">还没有 RAG 知识库。这里仅展示已配置资源，管理请进入右侧「RAG」区域。</div> : null}
      {items.map((item) => (
        <button key={item.id} className="resource-card resource-model-card" onClick={() => onOpen(item.id)} type="button">
          <span className="resource-model-card__icon">
            <Database size={15} />
          </span>
          <span>
            <strong>{item.name}</strong>
            <small>{ragSourceLabel(item.sourceType)} · {item.path || item.url || item.collection || "未配置入口"}</small>
          </span>
          {item.enabled ? null : <em>停用</em>}
        </button>
      ))}
    </div>
  );
}

function ReadonlyModelResourceList({
  items,
  onCreate,
  onOpen,
}: {
  items: ModelConfig[];
  onCreate: () => void;
  onOpen: (id?: string) => void;
}) {
  return (
    <div className="resource-list">
      <button className="resource-add" onClick={onCreate} type="button">
        <Plus size={15} />
        <span>去模型管理添加</span>
      </button>
      {items.length === 0 ? <div className="resource-empty">还没有模型配置。这里仅展示已配置模型，管理请进入右侧「模型」区域。</div> : null}
      {items.map((item) => (
        <button key={item.id} className="resource-card resource-model-card" onClick={() => onOpen(item.id)} type="button">
          <span className="resource-model-card__icon">
            <BrainCircuit size={15} />
          </span>
          <span>
            <strong>{item.name}</strong>
            <small>{item.provider} · {item.model || "未设置模型"}</small>
          </span>
          {item.isDefault ? <em>默认</em> : null}
        </button>
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

interface ModelProviderPreset {
  provider: string;
  label: string;
  defaultName: string;
  defaultModel: string;
  baseUrl: string;
  apiKeyEnv: string;
  apiFormat: string;
  homepage: string;
}

const MODEL_PROVIDER_PRESETS: ModelProviderPreset[] = [
  { provider: "custom", label: "自定义配置", defaultName: "自定义模型", defaultModel: "", baseUrl: "", apiKeyEnv: "", apiFormat: "openai_compatible", homepage: "" },
  { provider: "deepseek", label: "DeepSeek", defaultName: "DeepSeek", defaultModel: "deepseek-chat", baseUrl: "https://api.deepseek.com", apiKeyEnv: "DEEPSEEK_API_KEY", apiFormat: "openai_compatible", homepage: "https://www.deepseek.com" },
  { provider: "qwen", label: "阿里通义千问", defaultName: "Qwen", defaultModel: "qwen-plus", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", apiKeyEnv: "DASHSCOPE_API_KEY", apiFormat: "openai_compatible", homepage: "https://tongyi.aliyun.com" },
  { provider: "zhipu", label: "智谱 GLM", defaultName: "Zhipu GLM", defaultModel: "glm-4-flash", baseUrl: "https://open.bigmodel.cn/api/paas/v4/", apiKeyEnv: "ZHIPUAI_API_KEY", apiFormat: "openai_compatible", homepage: "https://open.bigmodel.cn" },
  { provider: "moonshot", label: "Kimi", defaultName: "Kimi", defaultModel: "moonshot-v1-8k", baseUrl: "https://api.moonshot.cn/v1", apiKeyEnv: "MOONSHOT_API_KEY", apiFormat: "openai_compatible", homepage: "https://platform.moonshot.cn" },
  { provider: "minimax", label: "MiniMax", defaultName: "MiniMax", defaultModel: "abab6.5s-chat", baseUrl: "https://api.minimax.chat/v1", apiKeyEnv: "MINIMAX_API_KEY", apiFormat: "openai_compatible", homepage: "https://www.minimaxi.com" },
  { provider: "doubao", label: "Doubao", defaultName: "Doubao", defaultModel: "doubao-pro-32k", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", apiKeyEnv: "ARK_API_KEY", apiFormat: "openai_compatible", homepage: "https://www.volcengine.com/product/doubao" },
  { provider: "hunyuan", label: "腾讯混元", defaultName: "Hunyuan", defaultModel: "hunyuan-lite", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1", apiKeyEnv: "HUNYUAN_API_KEY", apiFormat: "openai_compatible", homepage: "https://cloud.tencent.com/product/hunyuan" },
  { provider: "baidu_qianfan", label: "百度千帆", defaultName: "Qianfan", defaultModel: "ernie-4.0-turbo-8k", baseUrl: "https://qianfan.baidubce.com/v2", apiKeyEnv: "QIANFAN_API_KEY", apiFormat: "openai_compatible", homepage: "https://cloud.baidu.com/product/wenxinworkshop" },
  { provider: "openai", label: "OpenAI", defaultName: "OpenAI", defaultModel: "gpt-4.1-mini", baseUrl: "", apiKeyEnv: "OPENAI_API_KEY", apiFormat: "openai", homepage: "https://platform.openai.com" },
  { provider: "anthropic", label: "Claude", defaultName: "Claude", defaultModel: "claude-3-5-sonnet-latest", baseUrl: "", apiKeyEnv: "ANTHROPIC_API_KEY", apiFormat: "anthropic", homepage: "https://console.anthropic.com" },
  { provider: "google", label: "Gemini", defaultName: "Gemini", defaultModel: "gemini-1.5-pro", baseUrl: "", apiKeyEnv: "GOOGLE_API_KEY", apiFormat: "google", homepage: "https://ai.google.dev" },
  { provider: "azure_openai", label: "Azure OpenAI", defaultName: "Azure OpenAI", defaultModel: "gpt-4.1-mini", baseUrl: "", apiKeyEnv: "AZURE_OPENAI_API_KEY", apiFormat: "azure_openai", homepage: "https://azure.microsoft.com/products/ai-services/openai-service" },
  { provider: "openai_compatible", label: "OpenAI Compatible", defaultName: "OpenAI Compatible", defaultModel: "gpt-4.1-mini", baseUrl: "", apiKeyEnv: "OPENAI_API_KEY", apiFormat: "openai_compatible", homepage: "" },
  { provider: "ollama", label: "Ollama 本地", defaultName: "Ollama", defaultModel: "llama3.1", baseUrl: "http://localhost:11434/v1", apiKeyEnv: "", apiFormat: "ollama", homepage: "https://ollama.com" },
];

function newModelConfig(isDefault: boolean, preset: ModelProviderPreset): ModelConfig {
  const model = preset.defaultModel;
  return {
    id: createId("model"),
    name: preset.defaultName,
    provider: preset.provider,
    model,
    baseUrl: preset.baseUrl,
    apiKey: "",
    apiKeyEnv: preset.apiKeyEnv,
    apiVersion: "",
    organization: "",
    homepage: preset.homepage,
    apiFormat: preset.apiFormat,
    extraOptionsJson: "{}",
    modelRowsJson: writeModelRows([{ rowId: createId("model_row"), id: model, name: model }]),
    modelsJson: model ? JSON.stringify({ [model]: { name: model } }, null, 2) : "{}",
    enabled: true,
    isDefault,
    notes: "",
  };
}

function applyProviderPreset(config: ModelConfig, preset: ModelProviderPreset): ModelConfig {
  const next = {
    ...config,
    provider: preset.provider,
    name: preset.provider === "custom" ? config.name || preset.defaultName : preset.defaultName,
    model: preset.defaultModel || config.model,
    baseUrl: preset.baseUrl,
    apiKey: config.apiKey,
    apiKeyEnv: preset.apiKeyEnv,
    homepage: preset.homepage,
    apiFormat: preset.apiFormat,
    apiVersion: preset.provider === "azure_openai" ? config.apiVersion : "",
  };
  return {
    ...next,
    modelRowsJson: preset.defaultModel ? writeModelRows(ensureModelRow(readModelRows(next), preset.defaultModel, preset.defaultModel)) : next.modelRowsJson,
  };
}

function normalizeModelDraft(config: ModelConfig): ModelConfig {
  const modelRows = readModelRows(config);
  const models = modelsFromRows(modelRows);
  return {
    ...config,
    name: config.name.trim(),
    provider: normalizeProviderId(config.provider),
    model: config.model.trim(),
    baseUrl: config.baseUrl.trim(),
    apiKey: config.apiKey,
    apiKeyEnv: config.apiKeyEnv.trim(),
    homepage: config.homepage.trim(),
    apiFormat: config.apiFormat.trim() || "openai_compatible",
    notes: config.notes.trim(),
    extraOptionsJson: safeJson(config.extraOptionsJson),
    modelRowsJson: writeModelRows(modelRows),
    modelsJson: JSON.stringify(models, null, 2),
  };
}

function getModelConfigError(config: ModelConfig, configs: ModelConfig[]) {
  const provider = normalizeProviderId(config.provider);
  const name = config.name.trim();
  if (!provider) return "供应商标识不能为空。";
  if (!name) return "供应商名称不能为空。";
  if (provider === "custom") {
    const duplicate = configs.some((item) => item.id !== config.id && item.provider === "custom" && sameText(item.name, name));
    if (duplicate) return "自定义配置名称不能重复。";
  }
  return "";
}

function ensureUniqueCustomName(config: ModelConfig, configs: ModelConfig[]) {
  if (config.provider !== "custom") return config;
  let index = 1;
  let name = config.name;
  while (configs.some((item) => item.provider === "custom" && sameText(item.name, name))) {
    index += 1;
    name = `${config.name} ${index}`;
  }
  return { ...config, name };
}

function setDefaultModelConfig(items: ModelConfig[], id: string): ModelConfig[] {
  return items.map((item) => ({ ...item, enabled: item.id === id ? true : item.enabled, isDefault: item.id === id }));
}

function readOptionRows(json: string) {
  const parsed = parseJsonObject(json);
  return Object.entries(parsed).map(([key, value]) => ({ key, value: valueToInput(value) }));
}

function writeOptionRows(rows: Array<{ key: string; value: string }>) {
  const object = Object.fromEntries(rows.filter((row) => row.key.trim()).map((row) => [row.key.trim(), coerceOptionValue(row.value)]));
  return JSON.stringify(object, null, 2);
}

function replaceOption(rows: Array<{ key: string; value: string }>, index: number, next: { key: string; value: string }) {
  return rows.map((row, rowIndex) => (rowIndex === index ? next : row));
}

interface ModelRow {
  rowId: string;
  id: string;
  name: string;
}

function readModelRows(config: Pick<ModelConfig, "modelRowsJson" | "modelsJson" | "model">): ModelRow[] {
  const rows = parseModelRows(config.modelRowsJson);
  if (rows.length > 0) return rows;

  const migrated = Object.entries(parseJsonObject(config.modelsJson)).map(([id, value]) => ({
    rowId: createId("model_row"),
    id,
    name: value && typeof value === "object" && "name" in value ? String((value as { name?: unknown }).name || "") : "",
  }));
  if (migrated.length > 0) return migrated;

  const model = config.model.trim();
  return [{ rowId: createId("model_row"), id: model, name: model }];
}

function parseModelRows(json: string): ModelRow[] {
  try {
    const parsed = JSON.parse(json || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.map((row) => ({
      rowId: typeof row?.rowId === "string" && row.rowId ? row.rowId : createId("model_row"),
      id: typeof row?.id === "string" ? row.id : "",
      name: typeof row?.name === "string" ? row.name : "",
    }));
  } catch {
    return [];
  }
}

function writeModelRows(rows: ModelRow[]) {
  return JSON.stringify(
    rows.map((row) => ({
      rowId: row.rowId || createId("model_row"),
      id: row.id,
      name: row.name,
    })),
  );
}

function newEmptyModelRow(): ModelRow {
  return { rowId: createId("model_row"), id: `model-${Date.now()}`, name: "" };
}

function replaceModelRow(rows: ModelRow[], index: number, next: ModelRow) {
  return rows.map((row, rowIndex) => (rowIndex === index ? next : row));
}

function removeModelRow(rows: ModelRow[], index: number) {
  const next = rows.filter((_, rowIndex) => rowIndex !== index);
  return next.length > 0 ? next : [newEmptyModelRow()];
}

function ensureModelRow(rows: ModelRow[], id: string, name: string) {
  const modelId = id.trim();
  if (!modelId) return rows.length > 0 ? rows : [newEmptyModelRow()];
  if (rows.some((row) => row.id.trim() === modelId)) {
    return rows.map((row) => (row.id.trim() === modelId ? { ...row, name: row.name || name } : row));
  }
  return [...rows, { rowId: createId("model_row"), id: modelId, name }];
}

function modelsFromRows(rows: ModelRow[]) {
  return Object.fromEntries(
    rows
      .map((row) => ({ id: row.id.trim(), name: row.name.trim() }))
      .filter((row) => row.id && row.name)
      .map((row) => [row.id, { name: row.name }]),
  );
}

function buildConfigJson(config: ModelConfig) {
  const options: Record<string, unknown> = {
    baseURL: config.baseUrl,
    apiKey: config.apiKey,
    ...parseJsonObject(config.extraOptionsJson),
  };
  if (!config.apiKey && config.apiKeyEnv) options.apiKeyEnv = config.apiKeyEnv;
  if (config.apiVersion) options.apiVersion = config.apiVersion;
  return JSON.stringify(
    {
      npm: apiFormatPackage(config.apiFormat),
      options,
      models: modelsFromRows(readModelRows(config)),
    },
    null,
    2,
  );
}

function apiFormatPackage(format: string) {
  if (format === "anthropic") return "@ai-sdk/anthropic";
  if (format === "google") return "@ai-sdk/google";
  if (format === "azure_openai") return "@ai-sdk/azure";
  if (format === "ollama") return "@ai-sdk/openai-compatible";
  if (format === "openai") return "@ai-sdk/openai";
  return "@ai-sdk/openai-compatible";
}

function parseJsonObject(json: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(json || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function safeJson(json: string) {
  return JSON.stringify(parseJsonObject(json), null, 2);
}

function valueToInput(value: unknown) {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function coerceOptionValue(value: string): unknown {
  const trimmed = value.trim();
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (trimmed && !Number.isNaN(Number(trimmed))) return Number(trimmed);
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

function normalizeProviderId(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9_-]/g, "");
}

function providerInitial(config: Pick<ModelConfig, "name" | "provider">) {
  return (config.name || config.provider || "M").slice(0, 1).toUpperCase();
}

function sameText(left: string, right: string) {
  return left.trim().toLowerCase() === right.trim().toLowerCase();
}

function newTool(): ToolConfig {
  return { id: createId("tool"), name: "新工具", description: "", source: "python", schemaJson: "{}" };
}

function newMcpServer(): MCPServerConfig {
  return { id: createId("mcp"), name: "新 MCP", transport: "stdio", command: "", url: "", description: "" };
}

function newRagKnowledgeBase(): RagKnowledgeBaseConfig {
  return {
    id: createId("rag"),
    name: "新知识库",
    sourceType: "local_directory",
    path: "./knowledge",
    url: "",
    collection: "",
    description: "",
    embeddingModel: "",
    topK: 4,
    metadataJson: "{}",
    enabled: true,
  };
}

function normalizeRagDraft(draft: RagKnowledgeBaseConfig): RagKnowledgeBaseConfig {
  return {
    ...draft,
    name: draft.name.trim() || "未命名知识库",
    sourceType: draft.sourceType.trim() || "local_directory",
    path: draft.path.trim(),
    url: draft.url.trim(),
    collection: draft.collection.trim(),
    embeddingModel: draft.embeddingModel.trim(),
    topK: Math.max(1, Number(draft.topK || 4)),
    metadataJson: draft.metadataJson.trim() || "{}",
  };
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
