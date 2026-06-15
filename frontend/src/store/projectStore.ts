import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";
import { nanoid } from "nanoid";
import {
  autosaveProject,
  createProject,
  deleteProject,
  exportProject,
  getProject,
  listWorkspaceMcpServers,
  listWorkspaceRagKnowledgeBases,
  listWorkspaceModelConfigs,
  listWorkspaceSkills,
  listWorkspaceTools,
  listProjects,
  saveWorkspaceMcpServers,
  saveWorkspaceRagKnowledgeBases,
  saveWorkspaceModelConfigs,
  saveWorkspaceSkills,
  saveWorkspaceTools,
  saveProject,
  streamProjectPreview,
  validateProject,
} from "../lib/api";
import { createNode, defaultOutputs } from "../lib/nodeCatalog";
import { applyTemplateToProject, PROJECT_TEMPLATES } from "../lib/templates";
import type {
  AgentLinkConfig,
  EdgeIR,
  ExportResponse,
  ImportedAgentConfig,
  MCPServerConfig,
  ModelConfig,
  NodeRuntimeState,
  NodeIR,
  NodeType,
  ProjectHistoryRecord,
  ProjectIR,
  ProjectListItem,
  RagKnowledgeBaseConfig,
  RunHistoryGraphMismatch,
  RunHistoryGraphSnapshot,
  RunHistoryRecord,
  RunHistoryReplayMode,
  RunMode,
  RunPreviewResult,
  RunStreamEvent,
  RunTraceItem,
  SkillConfig,
  StateField,
  ToolConfig,
  ValidationResult,
} from "../types";

interface PendingConnection {
  source: string;
  sourceHandle: string | null;
}

type ManagerView = "agent" | "agents" | "tools" | "skills" | "mcp" | "rag" | "models";

interface ProjectStore {
  mode: "manager" | "editor";
  managerView: ManagerView;
  project: ProjectIR | null;
  projects: ProjectListItem[];
  workspaceTools: ToolConfig[];
  workspaceSkills: SkillConfig[];
  workspaceMcpServers: MCPServerConfig[];
  workspaceModelConfigs: ModelConfig[];
  workspaceRagKnowledgeBases: RagKnowledgeBaseConfig[];
  selectedNodeId: string | null;
  pendingConnection: PendingConnection | null;
  splitAgentProject: ProjectIR | null;
  splitRatio: number;
  validation: ValidationResult | null;
  exportResult: ExportResponse | null;
  historyOpen: boolean;
  miniMapOpen: boolean;
  historyRecords: ProjectHistoryRecord[];
  selectedHistoryId: string | null;
  templatesOpen: boolean;
  assistantOpen: boolean;
  runOpen: boolean;
  runActive: boolean;
  runCollapsed: boolean;
  runMode: RunMode;
  runInput: string;
  runRunning: boolean;
  selectedRunModelConfigId: string | null;
  runResult: RunPreviewResult | null;
  runHistoryRecords: RunHistoryRecord[];
  selectedRunHistoryId: string | null;
  runHistoryReplayMode: RunHistoryReplayMode;
  runHistoryMismatch: RunHistoryGraphMismatch | null;
  runtimeNodes: Record<string, NodeRuntimeState>;
  status: string;
  loading: boolean;
  initialize: () => Promise<void>;
  loadProjectList: () => Promise<void>;
  setManagerView: (view: ManagerView) => void;
  openProject: (projectId: string) => Promise<void>;
  createNewProject: (name: string, kind?: "agent" | "agents") => Promise<void>;
  renameProjectById: (projectId: string, patch: Partial<ProjectIR["project"]>) => Promise<void>;
  deleteProjectById: (projectId: string) => Promise<void>;
  backToManager: () => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  updateProjectMeta: (patch: Partial<ProjectIR["project"]>) => void;
  updateWorkspaceTools: (tools: ToolConfig[]) => Promise<void>;
  updateWorkspaceSkills: (skills: SkillConfig[]) => Promise<void>;
  updateWorkspaceMcpServers: (servers: MCPServerConfig[]) => Promise<void>;
  updateWorkspaceModelConfigs: (configs: ModelConfig[]) => Promise<void>;
  updateWorkspaceRagKnowledgeBases: (configs: RagKnowledgeBaseConfig[]) => Promise<void>;
  updateTools: (tools: ToolConfig[]) => void;
  updateSkills: (skills: SkillConfig[]) => void;
  updateMcpServers: (servers: MCPServerConfig[]) => void;
  updateImportedAgents: (agents: ImportedAgentConfig[]) => void;
  updateAgentLinks: (links: AgentLinkConfig[]) => void;
  addNode: (
    type: NodeType,
    position?: { x: number; y: number },
    configPatch?: Record<string, unknown>,
    label?: string,
  ) => void;
  updateNode: (nodeId: string, patch: Partial<NodeIR>) => void;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
  setStateFields: (fields: StateField[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  handlePortClick: (nodeId: string, direction: "source" | "target", handleId: string | null) => void;
  save: () => Promise<void>;
  saveBeforeUnload: () => void;
  toggleHistory: () => void;
  toggleMiniMap: () => void;
  closeHistory: () => void;
  selectHistoryRecord: (recordId: string) => void;
  restoreHistoryRecord: (recordId: string) => Promise<void>;
  exportHistoryAsProject: (recordId: string) => Promise<void>;
  deleteHistoryRecord: (recordId: string) => void;
  toggleTemplates: () => void;
  closeTemplates: () => void;
  applyTemplate: (templateId: string) => Promise<void>;
  toggleAssistant: () => void;
  closeAssistant: () => void;
  applyAssistantPrompt: (prompt: string) => Promise<void>;
  toggleRunPanel: () => void;
  closeRunPanel: () => void;
  expandRunPanel: () => void;
  collapseRunPanel: () => void;
  exitRunMode: () => void;
  setRunMode: (mode: RunMode) => void;
  setRunInput: (value: string) => void;
  setSelectedRunModelConfigId: (id: string | null) => void;
  selectRunHistoryRecord: (recordId: string) => void;
  setRunHistoryReplayMode: (mode: RunHistoryReplayMode) => void;
  clearRunHistory: () => void;
  runPreview: () => Promise<void>;
  openSplitAgent: (projectId: string) => Promise<void>;
  closeSplitAgent: () => void;
  setSplitRatio: (ratio: number) => void;
  updateSplitAgentProject: (project: ProjectIR) => void;
  updateSplitAgentMeta: (patch: Partial<ProjectIR["project"]>) => void;
  saveSplitAgent: () => Promise<void>;
  validate: () => Promise<void>;
  exportZip: () => Promise<void>;
}

const PROJECT_KEY = "graphic-langgraph-project-id";
const WORKSPACE_TOOLS_KEY = "graphic-langgraph-workspace-tools";
const WORKSPACE_SKILLS_KEY = "graphic-langgraph-workspace-skills";
const WORKSPACE_MCP_KEY = "graphic-langgraph-workspace-mcp";
const WORKSPACE_MODELS_KEY = "graphic-langgraph-workspace-models";
const HISTORY_LIMIT = 80;
const RUN_HISTORY_LIMIT = 30;

export const useProjectStore = create<ProjectStore>((set, get) => ({
  mode: "manager",
  managerView: "agent",
  project: null,
  projects: [],
  workspaceTools: [],
  workspaceSkills: [],
  workspaceMcpServers: [],
  workspaceModelConfigs: [],
  workspaceRagKnowledgeBases: [],
  selectedNodeId: null,
  pendingConnection: null,
  splitAgentProject: null,
  splitRatio: 0.56,
  validation: null,
  exportResult: null,
  historyOpen: false,
  miniMapOpen: true,
  historyRecords: [],
  selectedHistoryId: null,
  templatesOpen: false,
  assistantOpen: false,
  runOpen: false,
  runActive: false,
  runCollapsed: false,
  runMode: "live",
  runInput: "{\n  \"messages\": \"请在这里输入测试问题\"\n}",
  runRunning: false,
  selectedRunModelConfigId: null,
  runResult: null,
  runHistoryRecords: [],
  selectedRunHistoryId: null,
  runHistoryReplayMode: "overlay",
  runHistoryMismatch: null,
  runtimeNodes: {},
  status: "未连接后端",
  loading: false,

  async initialize() {
    set({ loading: true, status: "正在加载历史 Agent" });
    try {
      const [projects, storedTools, storedSkills, storedMcpServers, storedModelConfigs, storedRagKnowledgeBases] = await Promise.all([
        listProjects(),
        listWorkspaceTools(),
        listWorkspaceSkills(),
        listWorkspaceMcpServers(),
        listWorkspaceModelConfigs(),
        listWorkspaceRagKnowledgeBases(),
      ]);
      let workspaceTools = normalizeTools(storedTools);
      let workspaceSkills = normalizeSkills(storedSkills);
      let workspaceMcpServers = normalizeMcpServers(storedMcpServers);
      let workspaceModelConfigs = normalizeModelConfigs(storedModelConfigs);
      const workspaceRagKnowledgeBases = normalizeRagKnowledgeBases(storedRagKnowledgeBases);
      let migratedResources = false;
      if (workspaceTools.length === 0) {
        const localTools = normalizeTools(readLocalArray<ToolConfig>(WORKSPACE_TOOLS_KEY));
        if (localTools.length > 0) {
          try {
            workspaceTools = normalizeTools(await saveWorkspaceTools(localTools));
            removeLocalItem(WORKSPACE_TOOLS_KEY);
            migratedResources = true;
          } catch {
            workspaceTools = localTools;
          }
        }
      }
      if (workspaceSkills.length === 0) {
        const localSkills = normalizeSkills(readLocalArray<SkillConfig>(WORKSPACE_SKILLS_KEY));
        if (localSkills.length > 0) {
          try {
            workspaceSkills = normalizeSkills(await saveWorkspaceSkills(localSkills));
            removeLocalItem(WORKSPACE_SKILLS_KEY);
            migratedResources = true;
          } catch {
            workspaceSkills = localSkills;
          }
        }
      }
      if (workspaceMcpServers.length === 0) {
        const localMcpServers = normalizeMcpServers(readLocalArray<MCPServerConfig>(WORKSPACE_MCP_KEY));
        if (localMcpServers.length > 0) {
          try {
            workspaceMcpServers = normalizeMcpServers(await saveWorkspaceMcpServers(localMcpServers));
            removeLocalItem(WORKSPACE_MCP_KEY);
            migratedResources = true;
          } catch {
            workspaceMcpServers = localMcpServers;
          }
        }
      }
      let migratedModels = false;
      if (workspaceModelConfigs.length === 0) {
        const localModelConfigs = readLocalModelConfigs();
        if (localModelConfigs.length > 0) {
          workspaceModelConfigs = localModelConfigs;
          try {
            workspaceModelConfigs = normalizeModelConfigs(await saveWorkspaceModelConfigs(workspaceModelConfigs));
            removeLocalItem(WORKSPACE_MODELS_KEY);
            migratedModels = true;
          } catch {
            // Keep loading the app even if the compatibility migration fails.
          }
        }
      }
      set({
        projects,
        mode: "manager",
        project: null,
        workspaceTools,
        workspaceSkills,
        workspaceMcpServers,
        workspaceModelConfigs,
        workspaceRagKnowledgeBases,
        selectedRunModelConfigId: pickModelConfigId(workspaceModelConfigs, null),
        status: migratedModels || migratedResources ? "历史 Agent 已加载，资源配置已迁移到后端" : "历史 Agent 已加载",
        loading: false,
      });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "加载失败", loading: false });
    }
  },

  async loadProjectList() {
    const projects = await listProjects();
    set({ projects });
  },

  setManagerView(managerView) {
    set({ managerView });
  },

  async openProject(projectId) {
    set({ loading: true, status: "正在打开 Agent" });
    const project = await getProject(projectId);
    localStorage.setItem(PROJECT_KEY, project.project.id);
    set({
      mode: "editor",
      project,
      selectedNodeId: null,
      pendingConnection: null,
      splitAgentProject: null,
      validation: null,
      exportResult: null,
      historyRecords: readHistory(project.project.id),
      selectedHistoryId: null,
      historyOpen: false,
      miniMapOpen: true,
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runActive: false,
      runCollapsed: false,
      runResult: null,
      runRunning: false,
      runHistoryRecords: readRunHistory(project.project.id),
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      runtimeNodes: {},
      status: "项目已加载",
      loading: false,
    });
  },

  async createNewProject(name, kind) {
    set({ loading: true, status: "正在创建 Agent" });
    const projectKind = kind ?? (get().managerView === "agents" ? "agents" : "agent");
    const fallbackName = projectKind === "agents" ? "新建 Agents" : "新建 Agent";
    const project = await createProject(name.trim() || fallbackName, projectKind);
    localStorage.setItem(PROJECT_KEY, project.project.id);
    const projects = await listProjects();
    set({
      mode: "editor",
      projects,
      project,
      selectedNodeId: null,
      pendingConnection: null,
      splitAgentProject: null,
      validation: null,
      exportResult: null,
      historyRecords: recordProjectHistory(project, "创建项目"),
      selectedHistoryId: null,
      historyOpen: false,
      miniMapOpen: true,
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runActive: false,
      runCollapsed: false,
      runResult: null,
      runRunning: false,
      runHistoryRecords: [],
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      runtimeNodes: {},
      status: "已创建 Agent",
      loading: false,
    });
  },

  async deleteProjectById(projectId) {
    const current = get().project;
    await deleteProject(projectId);
    const projects = await listProjects();
    set({
      projects,
      project: current?.project.id === projectId ? null : current,
      mode: current?.project.id === projectId ? "manager" : get().mode,
      status: "已删除 Agent",
    });
  },

  async renameProjectById(projectId, patch) {
    set({ status: "正在更新名称" });
    const project = await getProject(projectId);
    const saved = await saveProject({ ...project, project: { ...project.project, ...patch } });
    recordProjectHistory(saved, "管理页重命名");
    const projects = await listProjects();
    set({ projects, status: "名称已更新" });
  },

  async backToManager() {
    const project = get().project;
    if (project) {
      await get().save();
    }
    const projects = await listProjects();
    set({
      mode: "manager",
      projects,
      project: null,
      selectedNodeId: null,
      pendingConnection: null,
      splitAgentProject: null,
      validation: null,
      exportResult: null,
      historyOpen: false,
      miniMapOpen: true,
      historyRecords: [],
      selectedHistoryId: null,
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runActive: false,
      runCollapsed: false,
      runResult: null,
      runRunning: false,
      runHistoryRecords: [],
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      runtimeNodes: {},
      status: "返回管理界面",
    });
  },

  selectNode(nodeId) {
    set({ selectedNodeId: nodeId, status: nodeId ? "正在编辑节点" : "未选中节点" });
  },

  updateProjectMeta(patch) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑 Agent 信息" });
      return;
    }
    set({ project: { ...project, project: { ...project.project, ...patch } }, status: "已更新 Agent 信息" });
  },

  async updateWorkspaceTools(tools) {
    const workspaceTools = normalizeTools(tools);
    set({ workspaceTools, status: "正在保存全局 Tools" });
    try {
      const savedTools = normalizeTools(await saveWorkspaceTools(workspaceTools));
      set({ workspaceTools: savedTools, status: "全局 Tools 已保存到后端" });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "全局 Tools 保存失败" });
    }
  },

  async updateWorkspaceSkills(skills) {
    const workspaceSkills = normalizeSkills(skills);
    set({ workspaceSkills, status: "正在保存全局 Skills" });
    try {
      const savedSkills = normalizeSkills(await saveWorkspaceSkills(workspaceSkills));
      set({ workspaceSkills: savedSkills, status: "全局 Skills 已保存到后端" });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "全局 Skills 保存失败" });
    }
  },

  async updateWorkspaceMcpServers(workspaceMcpServers) {
    const normalizedMcpServers = normalizeMcpServers(workspaceMcpServers);
    set({ workspaceMcpServers: normalizedMcpServers, status: "正在保存全局 MCP" });
    try {
      const savedMcpServers = normalizeMcpServers(await saveWorkspaceMcpServers(normalizedMcpServers));
      set({ workspaceMcpServers: savedMcpServers, status: "全局 MCP 已保存到后端" });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "全局 MCP 保存失败" });
    }
  },

  async updateWorkspaceModelConfigs(configs) {
    const workspaceModelConfigs = normalizeModelConfigs(configs);
    const selectedRunModelConfigId = pickModelConfigId(workspaceModelConfigs, get().selectedRunModelConfigId);
    set({
      workspaceModelConfigs,
      selectedRunModelConfigId,
      status: "正在保存运行模型配置",
    });
    try {
      const savedModelConfigs = normalizeModelConfigs(await saveWorkspaceModelConfigs(workspaceModelConfigs));
      set({
        workspaceModelConfigs: savedModelConfigs,
        selectedRunModelConfigId: pickModelConfigId(savedModelConfigs, selectedRunModelConfigId),
        status: "运行模型配置已保存到后端",
      });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "运行模型配置保存失败" });
    }
  },

  async updateWorkspaceRagKnowledgeBases(configs) {
    const workspaceRagKnowledgeBases = normalizeRagKnowledgeBases(configs);
    set({
      workspaceRagKnowledgeBases,
      status: "正在保存 RAG 知识库配置",
    });
    try {
      const savedRagKnowledgeBases = normalizeRagKnowledgeBases(await saveWorkspaceRagKnowledgeBases(workspaceRagKnowledgeBases));
      set({
        workspaceRagKnowledgeBases: savedRagKnowledgeBases,
        status: "RAG 知识库配置已保存到后端",
      });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "RAG 知识库配置保存失败" });
    }
  },

  updateTools(tools) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑 Tools 配置" });
      return;
    }
    set({ project: { ...project, tools }, status: "已更新 Tools 配置" });
  },

  updateSkills(skills) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑 Skills 配置" });
      return;
    }
    set({ project: { ...project, skills: normalizeSkills(skills) }, status: "已更新 Skills 配置" });
  },

  updateMcpServers(mcpServers) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑 MCP 配置" });
      return;
    }
    set({ project: { ...project, mcpServers }, status: "已更新 MCP 配置" });
  },

  updateImportedAgents(importedAgents) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑导入 Agent" });
      return;
    }
    set({ project: { ...project, importedAgents }, status: "已更新导入 Agent" });
  },

  updateAgentLinks(agentLinks) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑 Agent 通信配置" });
      return;
    }
    set({ project: { ...project, agentLinks }, status: "已更新 Agent 通信配置" });
  },

  addNode(type, position, configPatch, label) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能添加节点" });
      return;
    }
    const count = project.nodes.length;
    const defaultPosition =
      typeof window !== "undefined" && window.innerWidth <= 900
        ? { x: 282, y: 170 + count * 210 }
        : { x: 340 + (count % 2) * 300, y: 150 + Math.floor(count / 2) * 230 };
    const node = createNode(
      type,
      count,
      position ?? defaultPosition,
    );
    if (configPatch) {
      node.config = { ...node.config, ...configPatch };
    }
    if (label) {
      node.label = label;
    }
    if (type === "start" && project.nodes.some((item) => item.type === "start")) {
      set({ status: "一个项目只能有一个 Start 节点" });
      return;
    }
    set({
      project: { ...project, nodes: [...project.nodes, node] },
      selectedNodeId: node.id,
      status: `已添加 ${node.label}`,
    });
  },

  updateNode(nodeId, patch) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑节点" });
      return;
    }
    set({
      project: {
        ...project,
        nodes: project.nodes.map((node) => (node.id === nodeId ? { ...node, ...patch } : node)),
      },
    });
  },

  updateNodeConfig(nodeId, patch) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑节点配置" });
      return;
    }
    set({
      project: {
        ...project,
        nodes: project.nodes.map((node) => {
          if (node.id !== nodeId) return node;
          const config = { ...node.config, ...patch };
          return {
            ...node,
            config,
            outputs:
              node.type === "condition"
                ? defaultOutputs("condition")
                : node.type === "ai_router"
                  ? routerOutputsFromConfig(config)
                  : node.type === "human_approval"
                    ? defaultOutputs("human_approval")
                    : node.outputs,
          };
        }),
      },
    });
  },

  setStateFields(fields) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能编辑 State 字段" });
      return;
    }
    set({ project: { ...project, state: { ...project.state, fields } } });
  },

  onNodesChange(changes) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) return;
    const rfNodes = toReactFlowNodes(project);
    const changed = applyNodeChanges(changes, rfNodes);
    const changedById = new Map(changed.map((node) => [node.id, node]));
    const removedIds = new Set(changes.filter((change) => change.type === "remove").map((change) => change.id));
    set({
      project: {
        ...project,
        nodes: project.nodes
          .filter((node) => !removedIds.has(node.id))
          .map((node) => {
            const changedNode = changedById.get(node.id);
            return changedNode ? { ...node, position: changedNode.position } : node;
          }),
        edges: project.edges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)),
      },
    });
  },

  onEdgesChange(changes) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) return;
    const changed = applyEdgeChanges(changes, toReactFlowEdges(project));
    set({ project: { ...project, edges: changed.map(fromReactFlowEdge) } });
  },

  onConnect(connection) {
    const project = get().project;
    if (!project || !connection.source || !connection.target) return;
    if (get().runActive) {
      set({ status: "运行模式下不能连线" });
      return;
    }
    const edge = buildReactFlowEdge(project, connection.source, connection.sourceHandle, connection.target, connection.targetHandle);
    const next = addEdge(edge, toReactFlowEdges(project));
    set({ project: { ...project, edges: next.map(fromReactFlowEdge) }, pendingConnection: null, status: "已连接节点" });
  },

  handlePortClick(nodeId, direction, handleId) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) {
      set({ status: "运行模式下不能连线" });
      return;
    }

    if (direction === "source") {
      set({
        pendingConnection: { source: nodeId, sourceHandle: handleId },
        status: "已选择输出端口，请点击目标节点的输入端口完成连线",
      });
      return;
    }

    const pending = get().pendingConnection;
    if (!pending) {
      set({ status: "请先点击一个输出端口，再点击输入端口" });
      return;
    }
    if (pending.source === nodeId) {
      set({ pendingConnection: null, status: "不能连接到同一个节点" });
      return;
    }

    const edge = buildReactFlowEdge(project, pending.source, pending.sourceHandle, nodeId, handleId);
    const next = addEdge(edge, toReactFlowEdges(project));
    set({
      project: { ...project, edges: next.map(fromReactFlowEdge) },
      pendingConnection: null,
      status: "已连接节点",
    });
  },

  async save() {
    const project = get().project;
    if (!project) return;
    set({ status: "正在保存" });
    const saved = await saveProject(project);
    const splitAgentProject = get().splitAgentProject;
    const historyRecords = recordProjectHistory(saved, "手动保存");
    set({
      project: saved,
      splitAgentProject: splitAgentProject?.project.id === saved.project.id ? saved : splitAgentProject,
      historyRecords,
      status: "已保存",
    });
  },

  saveBeforeUnload() {
    const project = get().project;
    if (!project) return;
    recordProjectHistory(project, "退出自动保存");
    autosaveProject(project);
  },

  toggleHistory() {
    const project = get().project;
    if (!project) return;
    const historyRecords = readHistory(project.project.id);
    set((state) => ({
      historyOpen: !state.historyOpen,
      historyRecords,
      selectedHistoryId: state.selectedHistoryId ?? historyRecords[0]?.id ?? null,
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
    }));
  },

  toggleMiniMap() {
    set((state) => ({ miniMapOpen: !state.miniMapOpen }));
  },

  closeHistory() {
    set({ historyOpen: false });
  },

  selectHistoryRecord(selectedHistoryId) {
    set({ selectedHistoryId });
  },

  async restoreHistoryRecord(recordId) {
    const project = get().project;
    if (!project) return;
    const record = readHistory(project.project.id).find((item) => item.id === recordId);
    if (!record) {
      set({ status: "历史记录不存在" });
      return;
    }
    set({ status: "正在回退到历史记录" });
    const snapshot = cloneProject(record.snapshot);
    const saved = await saveProject(snapshot);
    set({
      project: saved,
      selectedNodeId: null,
      pendingConnection: null,
      validation: null,
      exportResult: null,
      historyRecords: readHistory(saved.project.id),
      selectedHistoryId: recordId,
      status: "已回退，历史记录未删除",
    });
  },

  async exportHistoryAsProject(recordId) {
    const project = get().project;
    if (!project) return;
    const record = readHistory(project.project.id).find((item) => item.id === recordId);
    if (!record) {
      set({ status: "历史记录不存在" });
      return;
    }
    set({ status: "正在从历史记录导出新项目" });
    const created = await createProject(`${record.snapshot.project.name} 历史副本`, record.snapshot.project.kind);
    const snapshot = cloneProject(record.snapshot);
    const clone: ProjectIR = {
      ...snapshot,
      project: {
        ...snapshot.project,
        id: created.project.id,
        name: `${snapshot.project.name} 历史副本`,
        description: snapshot.project.description,
      },
    };
    const saved = await saveProject(clone);
    const projects = await listProjects();
    const historyRecords = recordProjectHistory(saved, "从历史记录导出");
    localStorage.setItem(PROJECT_KEY, saved.project.id);
    set({
      mode: "editor",
      projects,
      project: saved,
      selectedNodeId: null,
      pendingConnection: null,
      splitAgentProject: null,
      validation: null,
      exportResult: null,
      historyOpen: false,
      historyRecords,
      selectedHistoryId: null,
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runResult: null,
      status: "已从历史记录导出新项目",
    });
  },

  deleteHistoryRecord(recordId) {
    const project = get().project;
    if (!project) return;
    const historyRecords = readHistory(project.project.id).filter((record) => record.id !== recordId);
    writeHistory(project.project.id, historyRecords);
    set({
      historyRecords,
      selectedHistoryId: historyRecords[0]?.id ?? null,
      status: "已删除选中的历史记录",
    });
  },

  toggleTemplates() {
    set((state) => ({ templatesOpen: !state.templatesOpen, assistantOpen: false, historyOpen: false }));
  },

  closeTemplates() {
    set({ templatesOpen: false });
  },

  async applyTemplate(templateId) {
    const project = get().project;
    if (!project) return;
    const template = PROJECT_TEMPLATES.find((item) => item.id === templateId);
    if (!template) {
      set({ status: "模板不存在" });
      return;
    }
    const nextProject = applyTemplateToProject(project, template);
    const saved = await saveProject(nextProject);
    const historyRecords = recordProjectHistory(saved, `应用模板：${template.name}`);
    set({
      project: saved,
      selectedNodeId: null,
      pendingConnection: null,
      validation: null,
      exportResult: null,
      historyRecords,
      templatesOpen: false,
      status: `已应用模板：${template.name}`,
    });
  },

  toggleAssistant() {
    set((state) => ({ assistantOpen: !state.assistantOpen, templatesOpen: false, historyOpen: false }));
  },

  closeAssistant() {
    set({ assistantOpen: false });
  },

  async applyAssistantPrompt(prompt) {
    const normalized = prompt.trim();
    if (!normalized) {
      set({ status: "请输入搭建需求" });
      return;
    }
    const templateId = /客服|售后|订单|退款/.test(normalized)
      ? "customer_support"
      : /知识库|问答|文档|rag|检索/i.test(normalized)
        ? "knowledge_qa"
        : "knowledge_qa";
    await get().applyTemplate(templateId);
    set({ assistantOpen: false, status: "搭建助手已根据需求生成初始画布" });
  },

  toggleRunPanel() {
    const project = get().project;
    if (!project) return;
    const state = get();
    if (state.runActive) {
      get().exitRunMode();
      return;
    }
    set({
      runActive: true,
      runOpen: true,
      runCollapsed: false,
      runResult: null,
      runRunning: false,
      runtimeNodes: {},
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      selectedNodeId: null,
      historyOpen: false,
      templatesOpen: false,
      assistantOpen: false,
      runHistoryRecords: readRunHistory(project.project.id),
      status: "已进入运行模式",
    });
  },

  closeRunPanel() {
    set({ runOpen: false });
  },

  expandRunPanel() {
    set({ runOpen: true, runCollapsed: false });
  },

  collapseRunPanel() {
    set({ runOpen: true, runCollapsed: true });
  },

  exitRunMode() {
    set({
      runActive: false,
      runOpen: false,
      runCollapsed: false,
      runResult: null,
      runRunning: false,
      runtimeNodes: {},
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      status: "已退出运行模式",
    });
  },

  setRunMode(runMode) {
    set({
      runMode,
      runResult: null,
      runtimeNodes: {},
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
    });
  },

  setRunInput(runInput) {
    set({ runInput });
  },

  setSelectedRunModelConfigId(selectedRunModelConfigId) {
    set({
      selectedRunModelConfigId,
      runResult: null,
      runtimeNodes: {},
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      status: "已切换运行模型",
    });
  },

  selectRunHistoryRecord(recordId) {
    const project = get().project;
    if (!project) return;
    const records = readRunHistory(project.project.id);
    const record = records.find((item) => item.id === recordId);
    if (!record) {
      set({ status: "运行历史不存在" });
      return;
    }
    const mismatch = detectRunHistoryGraphMismatch(record, project);
    const replayMode: RunHistoryReplayMode = mismatch ? "details" : "overlay";
    set({
      runActive: true,
      runOpen: true,
      runCollapsed: false,
      runResult: record.result,
      runRunning: false,
      runtimeNodes: replayMode === "overlay" ? getCompatibleRuntimeNodes(project, record) : {},
      selectedRunHistoryId: record.id,
      runHistoryReplayMode: replayMode,
      runHistoryMismatch: mismatch,
      runHistoryRecords: records,
      runInput: JSON.stringify(record.inputState, null, 2),
      selectedRunModelConfigId: record.modelConfigId,
      status: mismatch
        ? `该历史与当前 Agent 结构不一致：${formatShortTime(record.createdAt)}`
        : `已载入运行历史：${formatShortTime(record.createdAt)}`,
    });
  },

  setRunHistoryReplayMode(runHistoryReplayMode) {
    const project = get().project;
    const selectedRunHistoryId = get().selectedRunHistoryId;
    if (!project || !selectedRunHistoryId) return;
    const records = readRunHistory(project.project.id);
    const record = records.find((item) => item.id === selectedRunHistoryId);
    if (!record) {
      set({ status: "运行历史不存在" });
      return;
    }
    const mismatch = detectRunHistoryGraphMismatch(record, project);
    const runtimeNodes = runHistoryReplayMode === "overlay" ? getCompatibleRuntimeNodes(project, record) : {};
    const overlayCount = Object.keys(runtimeNodes).length;
    set({
      runtimeNodes,
      runHistoryReplayMode,
      runHistoryMismatch: mismatch,
      status: runHistoryReplayMode === "overlay"
        ? `已按可匹配节点叠加历史结果：${overlayCount} 个节点`
        : "已切换为只看历史详情",
    });
  },

  clearRunHistory() {
    const project = get().project;
    if (!project) return;
    writeRunHistory(project.project.id, []);
    set({
      runHistoryRecords: [],
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      runtimeNodes: {},
      status: "已清空运行历史",
    });
  },

  async runPreview() {
    const project = get().project;
    if (!project) return;
    let input: Record<string, unknown>;
    try {
      input = JSON.parse(get().runInput || "{}") as Record<string, unknown>;
    } catch {
      set({ status: "运行输入必须是合法 JSON" });
      return;
    }
    const runMode: RunMode = "live";
    const workspaceModelConfigs = normalizeModelConfigs(get().workspaceModelConfigs);
    const selectedRunModelConfigId = pickModelConfigId(workspaceModelConfigs, get().selectedRunModelConfigId);
    const selectedModelConfig = workspaceModelConfigs.find((config) => config.id === selectedRunModelConfigId && config.enabled);
    if (!selectedModelConfig) {
      set({ status: "请先在管理页添加并启用一个模型配置" });
      return;
    }
    set({
      runMode,
      runActive: true,
      runOpen: true,
      runCollapsed: false,
      status: "正在真实运行",
      runResult: null,
      runRunning: true,
      runtimeNodes: initializeRuntimeNodes(project),
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
    });
    const saved = await saveProject(project);
    const historyRecords = recordProjectHistory(saved, "运行预览前保存");
    set({
      project: saved,
      historyRecords,
      selectedRunModelConfigId,
    });
    try {
      await streamProjectPreview(saved.project.id, input, runMode, selectedModelConfig, (event) => {
        set((state) => applyRunStreamEvent(state, event));
      });
    } catch (error) {
      const failedState = get();
      if (failedState.project && failedState.runResult) {
        const runHistoryRecords = recordRunHistory(
          failedState.project,
          failedState.runResult,
          failedState.runtimeNodes,
          input,
          selectedModelConfig,
        );
        set({
          runHistoryRecords,
          selectedRunHistoryId: runHistoryRecords[0]?.id ?? null,
          runHistoryReplayMode: "overlay",
          runHistoryMismatch: null,
        });
      }
      set({
        runRunning: false,
        status: error instanceof Error ? error.message : "真实运行失败",
      });
    }
  },

  async openSplitAgent(projectId) {
    if (!projectId) {
      set({ status: "该 Agent 节点尚未绑定历史 Agent" });
      return;
    }
    try {
      const splitAgentProject = await getProject(projectId);
      set({ splitAgentProject, status: `已打开右侧 Agent：${splitAgentProject.project.name}` });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "打开右侧 Agent 失败" });
    }
  },

  closeSplitAgent() {
    set({ splitAgentProject: null, status: "已关闭分屏" });
  },

  setSplitRatio(ratio) {
    const bounded = Math.min(0.76, Math.max(0.32, ratio));
    set({ splitRatio: bounded });
  },

  updateSplitAgentProject(splitAgentProject) {
    set({ splitAgentProject, status: "已更新右侧 Agent" });
  },

  updateSplitAgentMeta(patch) {
    const splitAgentProject = get().splitAgentProject;
    if (!splitAgentProject) return;
    set({
      splitAgentProject: {
        ...splitAgentProject,
        project: { ...splitAgentProject.project, ...patch },
      },
      status: "已更新右侧 Agent 信息",
    });
  },

  async saveSplitAgent() {
    const splitAgentProject = get().splitAgentProject;
    if (!splitAgentProject) return;
    set({ status: "正在保存右侧 Agent" });
    const saved = await saveProject(splitAgentProject);
    recordProjectHistory(saved, "右侧 Agent 保存");
    const projects = await listProjects();
    set({ splitAgentProject: saved, projects, status: "右侧 Agent 已保存" });
  },

  async validate() {
    const project = get().project;
    if (!project) return;
    set({ status: "正在校验" });
    const saved = await saveProject(project);
    const historyRecords = recordProjectHistory(saved, "校验前保存");
    const validation = await validateProject(saved.project.id);
    set({
      project: saved,
      historyRecords,
      validation,
      status: validation.valid ? "校验通过" : `校验发现 ${validation.issues.length} 个问题`,
    });
  },

  async exportZip() {
    const project = get().project;
    if (!project) return;
    set({ status: "正在导出 ZIP", exportResult: null });
    const saved = await saveProject(project);
    const historyRecords = recordProjectHistory(saved, "导出前保存");
    const result = await exportProject(saved.project.id);
    if (typeof window !== "undefined") {
      const link = document.createElement("a");
      link.href = result.downloadUrl;
      link.download = `${saved.project.name || saved.project.id}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
    set({
      project: saved,
      historyRecords,
      exportResult: result,
      status: result.smokeTest.passed ? `ZIP 已导出，smoke test 通过（${result.smokeTest.durationMs}ms）` : "ZIP 已导出，但 smoke test 未通过",
    });
  },
}));

function buildReactFlowEdge(
  project: ProjectIR,
  source: string,
  sourceHandle: string | null | undefined,
  target: string,
  targetHandle: string | null | undefined,
): Edge {
  const sourceNode = project.nodes.find((node) => node.id === source);
  const kind = sourceNode && ["condition", "ai_router", "human_approval"].includes(sourceNode.type) ? "conditional" : "normal";
  return {
    id: nanoid(),
    source,
    sourceHandle,
    target,
    targetHandle,
    type: "smoothstep",
    label: kind === "conditional" ? sourceHandle ?? "branch" : undefined,
    data: { kind },
  };
}

function readLocalArray<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function writeLocalArray<T>(key: string, value: T[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function removeLocalItem(key: string) {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(key);
}

function readLocalModelConfigs(): ModelConfig[] {
  return normalizeModelConfigs(readLocalArray<ModelConfig>(WORKSPACE_MODELS_KEY));
}

function normalizeTools(tools: ToolConfig[]): ToolConfig[] {
  return tools
    .filter((tool) => tool && typeof tool.id === "string")
    .map((tool) => ({
      id: tool.id,
      name: String(tool.name || "未命名工具"),
      description: String(tool.description || ""),
      source: String(tool.source || "python"),
      schemaJson: String(tool.schemaJson || "{}"),
    }));
}

function normalizeSkills(skills: SkillConfig[]): SkillConfig[] {
  return skills
    .filter((skill) => skill && typeof skill.id === "string")
    .map((skill) => ({
      id: skill.id,
      name: String(skill.name || "未命名 Skill"),
      description: String(skill.description || ""),
      sourceType: String(skill.sourceType || "manual"),
      sourcePath: String(skill.sourcePath || ""),
      filePath: String(skill.filePath || ""),
      content: String(skill.content || ""),
      metadataJson: String(skill.metadataJson || "{}"),
      enabled: skill.enabled !== false,
    }));
}

function normalizeMcpServers(servers: MCPServerConfig[]): MCPServerConfig[] {
  return servers
    .filter((server) => server && typeof server.id === "string")
    .map((server) => ({
      id: server.id,
      name: String(server.name || "未命名 MCP"),
      transport: String(server.transport || "stdio"),
      command: String(server.command || ""),
      argsJson: String(server.argsJson || "[]"),
      envJson: String(server.envJson || "{}"),
      envVarsJson: String(server.envVarsJson || "[]"),
      cwd: String(server.cwd || ""),
      url: String(server.url || ""),
      bearerTokenEnvVar: String(server.bearerTokenEnvVar || ""),
      httpHeadersJson: String(server.httpHeadersJson || "{}"),
      envHttpHeadersJson: String(server.envHttpHeadersJson || "{}"),
      enabled: server.enabled !== false,
      startupTimeoutSec: Math.max(1, Number(server.startupTimeoutSec || 10)),
      toolTimeoutSec: Math.max(1, Number(server.toolTimeoutSec || 60)),
      enabledToolsJson: String(server.enabledToolsJson || "[]"),
      disabledToolsJson: String(server.disabledToolsJson || "[]"),
      defaultToolsApprovalMode: String(server.defaultToolsApprovalMode || ""),
      sourceType: String(server.sourceType || "manual"),
      sourcePath: String(server.sourcePath || ""),
      description: String(server.description || ""),
    }));
}

function normalizeRagKnowledgeBases(configs: RagKnowledgeBaseConfig[]): RagKnowledgeBaseConfig[] {
  return configs
    .filter((config) => config && typeof config.id === "string")
    .map((config) => ({
      id: config.id,
      name: String(config.name || "未命名知识库"),
      sourceType: String(config.sourceType || "local_directory"),
      path: String(config.path || ""),
      url: String(config.url || ""),
      collection: String(config.collection || ""),
      description: String(config.description || ""),
      embeddingModel: String(config.embeddingModel || ""),
      topK: Math.max(1, Number(config.topK || 4)),
      metadataJson: String(config.metadataJson || "{}"),
      enabled: config.enabled !== false,
    }));
}

function normalizeModelConfigs(configs: ModelConfig[]): ModelConfig[] {
  const normalized = configs
    .filter((config) => config && typeof config.id === "string")
    .map((config) => ({
      id: config.id,
      name: String(config.name || "未命名模型配置"),
      provider: String(config.provider || "openai"),
      model: String(config.model || "gpt-4.1-mini"),
      baseUrl: String(config.baseUrl || ""),
      apiKey: String(config.apiKey || ""),
      apiKeyEnv: String(config.apiKeyEnv || ""),
      apiKeyMode: String(config.apiKeyMode || (config.apiKey ? "direct" : "env")),
      apiVersion: String(config.apiVersion || ""),
      organization: String(config.organization || ""),
      homepage: String(config.homepage || ""),
      apiFormat: String(config.apiFormat || inferApiFormat(String(config.provider || "openai"))),
      extraOptionsJson: String(config.extraOptionsJson || "{}"),
      modelRowsJson: String(config.modelRowsJson || migrateModelRows(config.modelsJson, config.model)),
      modelsJson: String(config.modelsJson || "{}"),
      enabled: config.enabled !== false,
      isDefault: Boolean(config.isDefault),
      notes: String(config.notes || ""),
    }));
  if (normalized.length === 0) return normalized;

  let defaultAssigned = false;
  const withSingleDefault = normalized.map((config, index) => {
    const shouldBeDefault = !defaultAssigned && (config.isDefault || !normalized.some((item) => item.isDefault) && index === 0);
    if (shouldBeDefault) {
      defaultAssigned = true;
    }
    return { ...config, isDefault: shouldBeDefault };
  });
  return withSingleDefault;
}

function migrateModelRows(modelsJson: unknown, defaultModel: unknown) {
  const rows: Array<{ id: string; name: string }> = [];
  try {
    const parsed = JSON.parse(String(modelsJson || "{}"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
        const name = value && typeof value === "object" && "name" in value ? String((value as { name?: unknown }).name || "") : "";
        rows.push({ id, name });
      }
    }
  } catch {
    // Fall through to the default model row.
  }
  if (rows.length === 0 && defaultModel) {
    const model = String(defaultModel);
    rows.push({ id: model, name: model });
  }
  return JSON.stringify(rows.length > 0 ? rows : [{ id: "", name: "" }]);
}

function inferApiFormat(provider: string) {
  if (provider === "anthropic") return "anthropic";
  if (provider === "google") return "google";
  if (provider === "azure_openai") return "azure_openai";
  if (provider === "ollama") return "ollama";
  return "openai_compatible";
}

function pickModelConfigId(configs: ModelConfig[], currentId: string | null): string | null {
  const enabledConfigs = configs.filter((config) => config.enabled);
  if (currentId && enabledConfigs.some((config) => config.id === currentId)) {
    return currentId;
  }
  return enabledConfigs.find((config) => config.isDefault)?.id ?? enabledConfigs[0]?.id ?? configs[0]?.id ?? null;
}

function routerOutputsFromConfig(config: Record<string, unknown>) {
  const scenarios = parseScenarioLines(String(config.scenarios ?? ""));
  const outputs = scenarios.map((scenario) => ({
    id: scenario.id,
    type: "condition",
    label: scenario.label,
  }));
  const fallback = String(config.fallback ?? "").trim();
  if (fallback && !outputs.some((output) => output.id === fallback)) {
    outputs.push({ id: fallback, type: "condition", label: "fallback" });
  }
  return outputs.length > 0 ? outputs : defaultOutputs("ai_router");
}

function parseScenarioLines(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [id, label = id] = line.split(":");
      return {
        id: id.trim(),
        label: label.trim() || id.trim(),
      };
    })
    .filter((scenario) => scenario.id);
}

function historyKey(projectId: string) {
  return `graphic-langgraph-history-${projectId}`;
}

function runHistoryKey(projectId: string) {
  return `graphic-langgraph-run-history-${projectId}`;
}

function readHistory(projectId: string): ProjectHistoryRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(historyKey(projectId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as ProjectHistoryRecord[]) : [];
  } catch {
    return [];
  }
}

function writeHistory(projectId: string, records: ProjectHistoryRecord[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(historyKey(projectId), JSON.stringify(records.slice(0, HISTORY_LIMIT)));
}

function readRunHistory(projectId: string): RunHistoryRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(runHistoryKey(projectId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as RunHistoryRecord[]) : [];
  } catch {
    return [];
  }
}

function writeRunHistory(projectId: string, records: RunHistoryRecord[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(runHistoryKey(projectId), JSON.stringify(records.slice(0, RUN_HISTORY_LIMIT)));
}

function recordProjectHistory(project: ProjectIR, description: string): ProjectHistoryRecord[] {
  const snapshot = cloneProject(project);
  const records = readHistory(project.project.id);
  const latest = records[0];
  if (latest && projectSnapshotKey(latest.snapshot) === projectSnapshotKey(snapshot)) {
    return records;
  }
  const record: ProjectHistoryRecord = {
    id: createHistoryId(),
    projectId: project.project.id,
    name: project.project.name || "未命名",
    description,
    kind: project.project.kind,
    createdAt: new Date().toISOString(),
    nodeCount: project.nodes.length,
    edgeCount: project.edges.length,
    snapshot,
  };
  const next = [record, ...records].slice(0, HISTORY_LIMIT);
  writeHistory(project.project.id, next);
  return next;
}

function projectSnapshotKey(project: ProjectIR) {
  return JSON.stringify(project);
}

function cloneProject(project: ProjectIR): ProjectIR {
  return JSON.parse(JSON.stringify(project)) as ProjectIR;
}

function recordRunHistory(
  project: ProjectIR,
  result: RunPreviewResult,
  runtimeNodes: Record<string, NodeRuntimeState>,
  inputState: Record<string, unknown>,
  modelConfig: ModelConfig | null | undefined,
): RunHistoryRecord[] {
  const records = readRunHistory(project.project.id);
  const graphSnapshot = createRunHistoryGraphSnapshot(project);
  const record: RunHistoryRecord = {
    id: createHistoryId(),
    projectId: project.project.id,
    projectName: project.project.name || "未命名",
    createdAt: new Date().toISOString(),
    modelConfigId: modelConfig?.id ?? null,
    modelConfigName: modelConfig?.name || "未选择模型",
    inputState: cloneRecord(inputState),
    graphFingerprint: createRunHistoryGraphFingerprint(graphSnapshot),
    graphSnapshot,
    result: cloneRecord(result) as RunPreviewResult,
    runtimeNodes: cloneRecord(runtimeNodes) as Record<string, NodeRuntimeState>,
  };
  const next = [record, ...records].slice(0, RUN_HISTORY_LIMIT);
  writeRunHistory(project.project.id, next);
  return next;
}

function finalizeRunHistory(state: ProjectStore, result: RunPreviewResult): Partial<ProjectStore> {
  if (!state.project) {
    return { runResult: result };
  }
  const workspaceModelConfigs = normalizeModelConfigs(state.workspaceModelConfigs);
  const selectedRunModelConfigId = pickModelConfigId(workspaceModelConfigs, state.selectedRunModelConfigId);
  const selectedModelConfig = workspaceModelConfigs.find((config) => config.id === selectedRunModelConfigId) ?? null;
  const runHistoryRecords = recordRunHistory(
    state.project,
    result,
    state.runtimeNodes,
    parseRecord(state.runInput),
    selectedModelConfig,
  );
  return {
    runResult: result,
    runHistoryRecords,
    selectedRunHistoryId: runHistoryRecords[0]?.id ?? null,
    runHistoryReplayMode: "overlay",
    runHistoryMismatch: null,
  };
}

function parseRecord(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function cloneRecord<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function createRunHistoryGraphSnapshot(project: ProjectIR): RunHistoryGraphSnapshot {
  return {
    nodeCount: project.nodes.length,
    edgeCount: project.edges.length,
    stateFields: [...project.state.fields]
      .map((field) => ({ name: field.name, type: field.type || "str" }))
      .sort((left, right) => compareText(left.name, right.name)),
    nodes: [...project.nodes]
      .map((node) => ({
        id: node.id,
        type: node.type,
        label: node.label,
        inputs: [...node.inputs]
          .map((port) => ({ id: port.id, type: port.type }))
          .sort((left, right) => compareText(left.id, right.id)),
        outputs: [...node.outputs]
          .map((port) => ({ id: port.id, type: port.type }))
          .sort((left, right) => compareText(left.id, right.id)),
      }))
      .sort((left, right) => compareText(left.id, right.id)),
    edges: [...project.edges]
      .map((edge) => ({
        source: edge.source,
        sourceHandle: edge.sourceHandle ?? null,
        target: edge.target,
        targetHandle: edge.targetHandle ?? null,
        kind: edge.kind,
      }))
      .sort((left, right) =>
        compareText(
          `${left.source}:${left.sourceHandle ?? ""}:${left.target}:${left.targetHandle ?? ""}:${left.kind}`,
          `${right.source}:${right.sourceHandle ?? ""}:${right.target}:${right.targetHandle ?? ""}:${right.kind}`,
        ),
      ),
  };
}

function createRunHistoryGraphFingerprint(snapshot: RunHistoryGraphSnapshot): string {
  const structuralSnapshot = {
    stateFields: snapshot.stateFields,
    nodes: snapshot.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      inputs: node.inputs,
      outputs: node.outputs,
    })),
    edges: snapshot.edges,
  };
  return `glg_${hashString(JSON.stringify(structuralSnapshot))}`;
}

function detectRunHistoryGraphMismatch(record: RunHistoryRecord, project: ProjectIR): RunHistoryGraphMismatch | null {
  const currentSnapshot = createRunHistoryGraphSnapshot(project);
  const currentFingerprint = createRunHistoryGraphFingerprint(currentSnapshot);
  const historyFingerprint = record.graphFingerprint ?? (record.graphSnapshot ? createRunHistoryGraphFingerprint(record.graphSnapshot) : null);
  if (historyFingerprint && historyFingerprint === currentFingerprint) return null;

  const historyNodes = getHistoryComparableNodes(record);
  const currentNodesById = new Map(currentSnapshot.nodes.map((node) => [node.id, node]));
  const historyNodeIds = new Set(historyNodes.map((node) => node.id));
  const matchedNodeIds = historyNodes
    .filter((node) => {
      const current = currentNodesById.get(node.id);
      return Boolean(current && (!node.type || current.type === node.type));
    })
    .map((node) => node.id);
  const missingNodeIds = historyNodes.filter((node) => !currentNodesById.has(node.id)).map((node) => node.id);
  const incompatibleNodeIds = historyNodes
    .filter((node) => {
      const current = currentNodesById.get(node.id);
      return Boolean(current && node.type && current.type !== node.type);
    })
    .map((node) => node.id);
  const addedNodeIds = currentSnapshot.nodes.filter((node) => !historyNodeIds.has(node.id)).map((node) => node.id);

  return {
    reason: historyFingerprint ? "changed" : "legacy",
    historyFingerprint,
    currentFingerprint,
    historyNodeCount: record.graphSnapshot?.nodeCount ?? historyNodes.length,
    currentNodeCount: currentSnapshot.nodeCount,
    historyEdgeCount: record.graphSnapshot?.edgeCount ?? 0,
    currentEdgeCount: currentSnapshot.edgeCount,
    matchedNodeIds,
    missingNodeIds,
    incompatibleNodeIds,
    addedNodeIds,
  };
}

function getCompatibleRuntimeNodes(project: ProjectIR, record: RunHistoryRecord): Record<string, NodeRuntimeState> {
  const compatibleNodeIds = new Set(getHistoryComparableNodes(record)
    .filter((historyNode) => {
      const currentNode = project.nodes.find((node) => node.id === historyNode.id);
      return Boolean(currentNode && (!historyNode.type || currentNode.type === historyNode.type));
    })
    .map((node) => node.id));
  const runtimeNodes: Record<string, NodeRuntimeState> = {};
  for (const [nodeId, runtime] of Object.entries(record.runtimeNodes)) {
    if (compatibleNodeIds.has(nodeId)) {
      runtimeNodes[nodeId] = runtime;
    }
  }
  return runtimeNodes;
}

function getHistoryComparableNodes(record: RunHistoryRecord): Array<{ id: string; type?: NodeType; label: string }> {
  if (record.graphSnapshot?.nodes.length) {
    return record.graphSnapshot.nodes.map((node) => ({ id: node.id, type: node.type, label: node.label }));
  }
  const nodes = new Map<string, { id: string; type?: NodeType; label: string }>();
  for (const item of record.result.trace) {
    nodes.set(item.nodeId, { id: item.nodeId, type: item.type, label: item.label });
  }
  for (const [nodeId, runtime] of Object.entries(record.runtimeNodes)) {
    if (!nodes.has(nodeId)) {
      nodes.set(nodeId, { id: nodeId, label: runtime.label });
    }
  }
  return [...nodes.values()];
}

function compareText(left: string, right: string) {
  return left.localeCompare(right, "en");
}

function hashString(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function initializeRuntimeNodes(project: ProjectIR): Record<string, NodeRuntimeState> {
  const now = new Date().toISOString();
  const nodes: Record<string, NodeRuntimeState> = {};
  for (const node of project.nodes) {
    if (node.type === "start") continue;
    nodes[node.id] = {
      status: "queued",
      label: node.label,
      detail: "等待运行",
      durationMs: 0,
      inputState: {},
      outputDelta: {},
      updatedAt: now,
    };
  }
  return nodes;
}

function applyRunStreamEvent(state: ProjectStore, event: RunStreamEvent): Partial<ProjectStore> {
  const now = new Date().toISOString();
  if (event.event === "run_start") {
    return {
      runResult: {
        mode: event.mode,
        valid: event.valid,
        issues: event.issues,
        trace: [],
        outputState: event.inputState,
      },
      runRunning: event.valid,
      status: event.valid ? "真实运行开始" : "图校验未通过，未开始真实运行",
    };
  }
  if (event.event === "node_start") {
    return {
      runRunning: true,
      runtimeNodes: {
        ...state.runtimeNodes,
        [event.nodeId]: {
          status: "running",
          label: event.label,
          detail: "运行中",
          durationMs: 0,
          inputState: event.inputState,
          outputDelta: {},
          updatedAt: now,
        },
      },
      runResult: state.runResult
        ? { ...state.runResult, valid: event.valid, issues: event.issues }
        : { mode: event.mode, valid: event.valid, issues: event.issues, trace: [], outputState: event.inputState },
      status: `正在运行：${event.label}`,
      selectedNodeId: event.nodeId,
    };
  }
  if (event.event === "node_end") {
    const trace = upsertTraceItem(state.runResult?.trace ?? [], event.traceItem);
    const nodeRuntime: NodeRuntimeState = {
      status: event.traceItem.status,
      label: event.traceItem.label,
      detail: event.traceItem.detail,
      durationMs: event.traceItem.durationMs,
      inputState: event.traceItem.inputState,
      outputDelta: event.traceItem.outputDelta,
      updatedAt: now,
    };
    return {
      runRunning: true,
      runtimeNodes: {
        ...state.runtimeNodes,
        [event.traceItem.nodeId]: nodeRuntime,
      },
      runResult: {
        mode: event.mode,
        valid: event.valid,
        issues: event.issues,
        trace,
        outputState: event.outputState,
      },
      status: event.traceItem.status === "error" ? `运行失败：${event.traceItem.label}` : `节点完成：${event.traceItem.label}`,
      selectedNodeId: event.traceItem.nodeId,
    };
  }
  return {
    ...finalizeRunHistory(state, {
      mode: event.mode,
      valid: event.valid,
      issues: event.issues,
      trace: event.trace,
      outputState: event.outputState,
    }),
    runRunning: false,
    status: event.valid ? "真实运行完成" : "运行预览完成，但图校验未通过",
  };
}

function upsertTraceItem(trace: RunTraceItem[], item: RunTraceItem): RunTraceItem[] {
  const index = trace.findIndex((current) => current.nodeId === item.nodeId);
  if (index === -1) return [...trace, item];
  return trace.map((current, currentIndex) => (currentIndex === index ? item : current));
}

function createHistoryId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `history_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  }
  return `history_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function formatShortTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未知时间";
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function toReactFlowNodes(project: ProjectIR, runtimeNodes: Record<string, NodeRuntimeState> = {}): Node[] {
  return project.nodes.map((node) => ({
    id: node.id,
    type: "agentNode",
    position: node.position,
    data: {
      id: node.id,
      label: node.label,
      nodeType: node.type,
      config: node.config,
      inputs: node.inputs,
      outputs: node.outputs,
      runtime: runtimeNodes[node.id] ?? null,
    },
  }));
}

export function toReactFlowEdges(project: ProjectIR): Edge[] {
  return project.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    sourceHandle: edge.sourceHandle ?? undefined,
    target: edge.target,
    targetHandle: edge.targetHandle ?? undefined,
    type: "smoothstep",
    label: edge.label ?? undefined,
    data: {
      kind: edge.kind,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    },
  }));
}

function fromReactFlowEdge(edge: Edge): EdgeIR {
  return {
    id: edge.id,
    source: edge.source,
    sourceHandle: (edge.data?.sourceHandle as string | null | undefined) ?? edge.sourceHandle ?? null,
    target: edge.target,
    targetHandle: (edge.data?.targetHandle as string | null | undefined) ?? edge.targetHandle ?? null,
    kind: (edge.data?.kind as EdgeIR["kind"]) ?? "normal",
    label: typeof edge.label === "string" ? edge.label : null,
  };
}
