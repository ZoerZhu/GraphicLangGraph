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
  clearProjectRunHistory,
  deleteProjectRunHistory,
  exportProject,
  getProject,
  listProjectRunHistory,
  listWorkspaceMcpServers,
  listWorkspaceRagKnowledgeBases,
  listWorkspaceResourceGroups,
  listWorkspaceModelConfigs,
  listWorkspaceRuntimeEnvironments,
  listWorkspaceSkills,
  listWorkspaceTools,
  listProjects,
  saveWorkspaceMcpServers,
  saveWorkspaceRagKnowledgeBases,
  saveWorkspaceResourceGroups,
  saveWorkspaceModelConfigs,
  saveWorkspaceRuntimeEnvironments,
  saveWorkspaceSkills,
  saveWorkspaceTools,
  saveProject,
  saveProjectRunHistory,
  resumeProjectRun,
  streamProjectPreview,
  validateProject,
} from "../lib/api";
import { createNode, defaultOutputs } from "../lib/nodeCatalog";
import { applyTemplateToProject, getProjectTemplateForProject, PROJECT_TEMPLATES, type ProjectTemplate } from "../lib/templates";
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
  Position,
  ProjectHistoryRecord,
  ProjectIR,
  ProjectListItem,
  RagKnowledgeBaseConfig,
  ResourceGroupConfig,
  RuntimeEnvironmentConfig,
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

type ManagerView = "agent" | "agents" | "tools" | "toolGroups" | "skills" | "skillGroups" | "mcp" | "rag" | "models";

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
  workspaceResourceGroups: ResourceGroupConfig[];
  workspaceRuntimeEnvironments: RuntimeEnvironmentConfig[];
  selectedNodeId: string | null;
  pendingConnection: PendingConnection | null;
  splitAgentProject: ProjectIR | null;
  splitRatio: number;
  validation: ValidationResult | null;
  validationOpen: boolean;
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
  canvasCenter: Position | null;
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
  updateWorkspaceResourceGroups: (groups: ResourceGroupConfig[]) => Promise<void>;
  updateWorkspaceRuntimeEnvironments: (configs: RuntimeEnvironmentConfig[]) => Promise<void>;
  setProjectRuntimeEnvironmentId: (id: string) => void;
  updateTools: (tools: ToolConfig[]) => void;
  updateSkills: (skills: SkillConfig[]) => void;
  updateMcpServers: (servers: MCPServerConfig[]) => void;
  updateImportedAgents: (agents: ImportedAgentConfig[]) => void;
  updateAgentLinks: (links: AgentLinkConfig[]) => void;
  setCanvasCenter: (position: Position) => void;
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
  closeValidationPanel: () => void;
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
  deleteRunHistoryRecord: (recordId: string) => Promise<void>;
  clearRunHistory: () => Promise<void>;
  cancelRun: () => void;
  runPreview: () => Promise<void>;
  resumePausedRun: (recordId: string, action: string, comment: string) => Promise<void>;
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
let activeRunAbortController: AbortController | null = null;
let activeRunToken: string | null = null;

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
  workspaceResourceGroups: [],
  workspaceRuntimeEnvironments: [],
  selectedNodeId: null,
  pendingConnection: null,
  splitAgentProject: null,
  splitRatio: 0.56,
  validation: null,
  validationOpen: false,
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
  canvasCenter: null,
  status: "未连接后端",
  loading: false,

  async initialize() {
    set({ loading: true, status: "正在加载历史 Agent" });
    try {
      const [projects, storedTools, storedSkills, storedMcpServers, storedModelConfigs, storedRagKnowledgeBases, storedResourceGroups, storedRuntimeEnvironments] = await Promise.all([
        listProjects(),
        listWorkspaceTools(),
        listWorkspaceSkills(),
        listWorkspaceMcpServers(),
        listWorkspaceModelConfigs(),
        listWorkspaceRagKnowledgeBases(),
        listWorkspaceResourceGroups(),
        listWorkspaceRuntimeEnvironments(),
      ]);
      let workspaceTools = normalizeTools(storedTools);
      let workspaceSkills = normalizeSkills(storedSkills);
      let workspaceMcpServers = normalizeMcpServers(storedMcpServers);
      let workspaceModelConfigs = normalizeModelConfigs(storedModelConfigs);
      const workspaceRagKnowledgeBases = normalizeRagKnowledgeBases(storedRagKnowledgeBases);
      const workspaceResourceGroups = normalizeResourceGroups(storedResourceGroups);
      const workspaceRuntimeEnvironments = normalizeRuntimeEnvironments(storedRuntimeEnvironments);
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
        workspaceResourceGroups,
        workspaceRuntimeEnvironments,
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
    const project = syncAllParallelWorkers(ensureProjectRuntimeEnvironment(await getProject(projectId), get().workspaceRuntimeEnvironments));
    const runHistoryRecords = await loadRunHistoryRecords(project.project.id);
    localStorage.setItem(PROJECT_KEY, project.project.id);
    set({
      mode: "editor",
      project,
      selectedNodeId: null,
      pendingConnection: null,
      splitAgentProject: null,
      validation: null,
      validationOpen: false,
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
      runHistoryRecords,
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
    const project = ensureProjectRuntimeEnvironment(await createProject(name.trim() || fallbackName, projectKind), get().workspaceRuntimeEnvironments);
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
      validationOpen: false,
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
    abortActiveRun();
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
      validationOpen: false,
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

  async updateWorkspaceResourceGroups(groups) {
    const workspaceResourceGroups = normalizeResourceGroups(groups);
    set({ workspaceResourceGroups, status: "正在保存资源预设组" });
    try {
      const savedGroups = normalizeResourceGroups(await saveWorkspaceResourceGroups(workspaceResourceGroups));
      set({ workspaceResourceGroups: savedGroups, status: "资源预设组已保存到后端" });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "资源预设组保存失败" });
    }
  },

  async updateWorkspaceRuntimeEnvironments(configs) {
    const workspaceRuntimeEnvironments = normalizeRuntimeEnvironments(configs);
    const project = get().project;
    const projectPatch = project ? ensureProjectRuntimeEnvironment(project, workspaceRuntimeEnvironments) : null;
    set({
      workspaceRuntimeEnvironments,
      project: projectPatch,
      status: "正在保存运行环境",
    });
    try {
      const savedRuntimeEnvironments = normalizeRuntimeEnvironments(await saveWorkspaceRuntimeEnvironments(workspaceRuntimeEnvironments));
      set({
        workspaceRuntimeEnvironments: savedRuntimeEnvironments,
        project: projectPatch ? ensureProjectRuntimeEnvironment(projectPatch, savedRuntimeEnvironments) : null,
        status: "运行环境已保存到后端",
      });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "运行环境保存失败" });
    }
  },

  setProjectRuntimeEnvironmentId(id) {
    const project = get().project;
    if (!project) return;
    set({
      project: { ...project, project: { ...project.project, runtimeEnvironmentId: id } },
      status: "已切换运行环境",
    });
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

  setCanvasCenter(position) {
    const current = get().canvasCenter;
    if (current && Math.abs(current.x - position.x) < 1 && Math.abs(current.y - position.y) < 1) return;
    set({ canvasCenter: position });
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
    const basePosition = position ?? get().canvasCenter ?? defaultPosition;
    const node = createNode(
      type,
      count,
      findAvailableNodePosition(project, basePosition),
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
    const existingNames = collectStateFieldNames(project);
    const reservedNodeFields = collectNodeWriteFieldNames(project.nodes);
    const suggestedConfig = uniqueNodeOutputConfig(type, node.config, existingNames, reservedNodeFields);
    node.config = { ...node.config, ...suggestedConfig };
    const nextFields = mergeStateFields(project.state.fields, stateFieldsForNode(node));
    let nextProject: ProjectIR = { ...project, nodes: [...project.nodes, node], state: { ...project.state, fields: nextFields } };
    if (type === "parallel_tools") {
      nextProject = syncParallelWorkers(nextProject, node.id);
    }
    set({
      project: nextProject,
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
    const beforeNode = project.nodes.find((node) => node.id === nodeId) ?? null;
    let updatedNode: NodeIR | null = null;
    const nodes = project.nodes.map((node) => {
      if (node.id !== nodeId) return node;
      const config = sanitizeNodeWriteConfig(node.type, { ...node.config, ...patch });
      updatedNode = {
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
      return updatedNode;
    });
    const nextFields =
      beforeNode && updatedNode
        ? syncStateFieldsForNodeUpdate(project.state.fields, beforeNode, updatedNode, nodes)
        : project.state.fields;
    let nextProject: ProjectIR = {
      ...project,
      nodes,
      state: { ...project.state, fields: nextFields },
    };
    const changedNode = nodes.find((node) => node.id === nodeId);
    if (changedNode?.type === "parallel_tools") {
      nextProject = syncParallelWorkers(nextProject, changedNode.id);
    }
    set({ project: nextProject });
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
    const nextProject = syncAllParallelWorkers({
      ...project,
      nodes: project.nodes
        .filter((node) => !removedIds.has(node.id))
        .map((node) => {
          const changedNode = changedById.get(node.id);
          return changedNode ? { ...node, position: changedNode.position } : node;
        }),
      edges: project.edges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target)),
    });
    set({ project: nextProject });
  },

  onEdgesChange(changes) {
    const project = get().project;
    if (!project) return;
    if (get().runActive) return;
    const changed = applyEdgeChanges(changes, toReactFlowEdges(project));
    set({ project: syncAllParallelWorkers({ ...project, edges: changed.map(fromReactFlowEdge) }) });
  },

  onConnect(connection) {
    const project = get().project;
    if (!project || !connection.source || !connection.target) return;
    if (get().runActive) {
      set({ status: "运行模式下不能连线" });
      return;
    }
    const sourceNode = project.nodes.find((node) => node.id === connection.source);
    const targetNode = project.nodes.find((node) => node.id === connection.target);
    if (targetNode?.type === "parallel_worker") {
      set({ status: "Worker 节点只能由所属 Parallel Tools 自动连接" });
      return;
    }
    if (sourceNode?.type === "parallel_tools" || sourceNode?.type === "parallel_worker") {
      const connectedProject = connectParallelWorkerOutput(project, sourceNode, connection.target, connection.targetHandle ?? null);
      set({ project: connectedProject, pendingConnection: null, status: "已连接 Parallel Workers 输出" });
      return;
    }
    const edge = buildReactFlowEdge(project, connection.source, connection.sourceHandle, connection.target, connection.targetHandle);
    const next = addEdge(edge, toReactFlowEdges(project));
    const connectedProject = applyConnectionInputDefaults(
      { ...project, edges: next.map(fromReactFlowEdge) },
      connection.source,
      connection.target,
    );
    set({ project: connectedProject, pendingConnection: null, status: "已连接节点" });
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
    const sourceNode = project.nodes.find((node) => node.id === pending.source);
    const targetNode = project.nodes.find((node) => node.id === nodeId);
    if (targetNode?.type === "parallel_worker") {
      set({ pendingConnection: null, status: "Worker 节点只能由所属 Parallel Tools 自动连接" });
      return;
    }
    if (sourceNode?.type === "parallel_tools" || sourceNode?.type === "parallel_worker") {
      const connectedProject = connectParallelWorkerOutput(project, sourceNode, nodeId, handleId);
      set({
        project: connectedProject,
        pendingConnection: null,
        status: "已连接 Parallel Workers 输出",
      });
      return;
    }

    const edge = buildReactFlowEdge(project, pending.source, pending.sourceHandle, nodeId, handleId);
    const next = addEdge(edge, toReactFlowEdges(project));
    const connectedProject = applyConnectionInputDefaults(
      { ...project, edges: next.map(fromReactFlowEdge) },
      pending.source,
      nodeId,
    );
    set({
      project: connectedProject,
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

  closeValidationPanel() {
    set({ validationOpen: false });
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
    const snapshot = syncAllParallelWorkers(cloneProject(record.snapshot));
    const saved = await saveProject(snapshot);
    set({
      project: saved,
      selectedNodeId: null,
      pendingConnection: null,
      validation: null,
      validationOpen: false,
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
    const snapshot = syncAllParallelWorkers(cloneProject(record.snapshot));
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
      validationOpen: false,
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
    const runtimeEnvironments = normalizeRuntimeEnvironments(get().workspaceRuntimeEnvironments);
    const projectWithRuntime = ensureProjectRuntimeEnvironment(project, runtimeEnvironments);
    const nextProject = syncAllParallelWorkers(applyTemplateRuntimeDependencies(applyTemplateToProject(projectWithRuntime, template), template));
    const saved = await saveProject(nextProject);
    const runtimeDependencyUpdate = ensureTemplateRuntimeHosts(runtimeEnvironments, saved.project.runtimeEnvironmentId, template.requiredRuntimeHosts ?? []);
    const savedRuntimeEnvironments = runtimeDependencyUpdate.changed
      ? normalizeRuntimeEnvironments(await saveWorkspaceRuntimeEnvironments(runtimeDependencyUpdate.configs))
      : get().workspaceRuntimeEnvironments;
    const historyRecords = recordProjectHistory(saved, `应用模板：${template.name}`);
    const sampleHint = template.sampleInput ? "，已填入样例输入" : "";
    const modelHint = template.requiresModel ? "，请选择模型后运行" : "，可直接真实运行";
    const mcpHint = template.requiredMcpServers?.length ? `，已加入 ${template.requiredMcpServers.length} 个 MCP` : "";
    const hostHint = runtimeDependencyUpdate.addedHosts.length ? `，已允许域名 ${runtimeDependencyUpdate.addedHosts.join(", ")}` : "";
    const envHint = template.requiredEnvVars?.length ? `，需配置环境变量 ${template.requiredEnvVars.join(", ")}` : "";
    set({
      project: saved,
      workspaceRuntimeEnvironments: savedRuntimeEnvironments,
      runInput: template.sampleInput ? JSON.stringify(template.sampleInput, null, 2) : get().runInput,
      selectedNodeId: null,
      pendingConnection: null,
      validation: null,
      validationOpen: false,
      exportResult: null,
      historyRecords,
      runResult: null,
      runtimeNodes: {},
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      templatesOpen: false,
      status: `已应用模板：${template.name}${sampleHint}${mcpHint}${hostHint}${modelHint}${envHint}`,
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
    const templateId = pickAssistantTemplateId(normalized);
    await get().applyTemplate(templateId);
    set({ assistantOpen: false });
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
    void loadRunHistoryRecords(project.project.id).then((records) => {
      const current = get().project;
      if (current?.project.id === project.project.id && get().runActive) {
        set({ runHistoryRecords: records });
      }
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
    abortActiveRun();
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
    const records = get().runHistoryRecords.length ? get().runHistoryRecords : readRunHistory(project.project.id);
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
    const records = get().runHistoryRecords.length ? get().runHistoryRecords : readRunHistory(project.project.id);
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

  async deleteRunHistoryRecord(recordId) {
    const project = get().project;
    if (!project) return;
    const previous = get().runHistoryRecords;
    const next = previous.filter((record) => record.id !== recordId);
    writeRunHistory(project.project.id, next);
    set({
      runHistoryRecords: next,
      selectedRunHistoryId: get().selectedRunHistoryId === recordId ? null : get().selectedRunHistoryId,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      runtimeNodes: get().selectedRunHistoryId === recordId ? {} : get().runtimeNodes,
      status: "正在删除运行历史",
    });
    try {
      await deleteProjectRunHistory(project.project.id, recordId);
      set({ status: "已删除运行历史" });
    } catch (error) {
      set({ runHistoryRecords: previous, status: error instanceof Error ? error.message : "删除运行历史失败" });
    }
  },

  async clearRunHistory() {
    const project = get().project;
    if (!project) return;
    const previous = get().runHistoryRecords;
    writeRunHistory(project.project.id, []);
    set({
      runHistoryRecords: [],
      selectedRunHistoryId: null,
      runHistoryReplayMode: "overlay",
      runHistoryMismatch: null,
      runtimeNodes: {},
      status: "正在清空运行历史",
    });
    try {
      await clearProjectRunHistory(project.project.id);
      set({ status: "已清空运行历史" });
    } catch (error) {
      set({ runHistoryRecords: previous, status: error instanceof Error ? error.message : "清空运行历史失败" });
    }
  },

  cancelRun() {
    if (!get().runRunning) {
      set({ status: "当前没有正在运行的任务" });
      return;
    }
    abortActiveRun();
    set((state) => ({
      runRunning: false,
      runtimeNodes: markRuntimeNodesInterrupted(state.runtimeNodes),
      status: "正在中断运行",
    }));
  },

  async runPreview() {
    const project = get().project;
    if (!project) return;
    if (get().runRunning) {
      set({ status: "已有运行任务正在执行" });
      return;
    }
    let input: Record<string, unknown>;
    try {
      input = JSON.parse(get().runInput || "{}") as Record<string, unknown>;
    } catch {
      set({ status: "运行输入必须是合法 JSON" });
      return;
    }
    const runMode: RunMode = "live";
    const template = getProjectTemplateForProject(project);
    const requiresModel = template?.requiresModel ?? true;
    const workspaceModelConfigs = normalizeModelConfigs(get().workspaceModelConfigs);
    const selectedRunModelConfigId = pickModelConfigId(workspaceModelConfigs, get().selectedRunModelConfigId);
    const selectedModelConfig = workspaceModelConfigs.find((config) => config.id === selectedRunModelConfigId && config.enabled);
    if (requiresModel && !selectedModelConfig) {
      set({ status: "请先在管理页添加并启用一个模型配置" });
      return;
    }
    const runtimeEnvironments = normalizeRuntimeEnvironments(get().workspaceRuntimeEnvironments);
    const selectedRuntimeEnvironment = pickRuntimeEnvironment(runtimeEnvironments, project.project.runtimeEnvironmentId);
    abortActiveRun();
    const runToken = nanoid();
    const abortController = new AbortController();
    activeRunToken = runToken;
    activeRunAbortController = abortController;
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
      await streamProjectPreview(saved.project.id, input, runMode, selectedModelConfig, selectedRuntimeEnvironment ?? undefined, (event) => {
        if (activeRunToken !== runToken) return;
        set((state) => applyRunStreamEvent(state, event));
      }, abortController.signal);
      if (activeRunToken === runToken) {
        const current = get();
        const record = current.runHistoryRecords.find((item) => item.id === current.selectedRunHistoryId) ?? current.runHistoryRecords[0];
        if (record) await persistRunHistoryRecord(saved.project.id, record);
      }
    } catch (error) {
      if (activeRunToken !== runToken) return;
      if (isAbortError(error)) {
        set((state) => ({
          runRunning: false,
          runtimeNodes: markRuntimeNodesInterrupted(state.runtimeNodes),
          status: "运行已中断",
        }));
        return;
      }
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
        if (runHistoryRecords[0]) await persistRunHistoryRecord(failedState.project.project.id, runHistoryRecords[0]);
      }
      set({
        runRunning: false,
        status: error instanceof Error ? error.message : "真实运行失败",
      });
    } finally {
      if (activeRunToken === runToken) {
        activeRunToken = null;
        activeRunAbortController = null;
      }
    }
  },

  async resumePausedRun(recordId, action, comment) {
    const project = get().project;
    if (!project) return;
    const record = get().runHistoryRecords.find((item) => item.id === recordId);
    if (!record || record.result.status !== "paused") {
      set({ status: "当前运行记录不是待审批状态" });
      return;
    }
    const template = getProjectTemplateForProject(project);
    const requiresModel = template?.requiresModel ?? true;
    const workspaceModelConfigs = normalizeModelConfigs(get().workspaceModelConfigs);
    const selectedRunModelConfigId = pickModelConfigId(workspaceModelConfigs, get().selectedRunModelConfigId);
    const selectedModelConfig = workspaceModelConfigs.find((config) => config.id === selectedRunModelConfigId && config.enabled);
    if (requiresModel && !selectedModelConfig) {
      set({ status: "请先在管理页添加并启用一个模型配置" });
      return;
    }
    const runtimeEnvironments = normalizeRuntimeEnvironments(get().workspaceRuntimeEnvironments);
    const selectedRuntimeEnvironment = pickRuntimeEnvironment(runtimeEnvironments, project.project.runtimeEnvironmentId);
    set({ runRunning: true, runOpen: true, runCollapsed: false, status: "正在恢复审批后的运行" });
    try {
      const result = await resumeProjectRun(
        project.project.id,
        recordId,
        action,
        comment,
        selectedModelConfig,
        selectedRuntimeEnvironment ?? undefined,
      );
      const runtimeNodes = runtimeNodesFromTrace(project, result.trace);
      const nextRecord: RunHistoryRecord = {
        ...record,
        result: cloneRecord(result) as RunPreviewResult,
        runtimeNodes,
      };
      const runHistoryRecords = get().runHistoryRecords.map((item) => (item.id === recordId ? nextRecord : item));
      writeRunHistory(project.project.id, runHistoryRecords);
      set({
        runRunning: false,
        runResult: result,
        runtimeNodes,
        runHistoryRecords,
        selectedRunHistoryId: recordId,
        runHistoryReplayMode: "overlay",
        runHistoryMismatch: null,
        status: result.status === "paused" ? "运行再次暂停，等待人工审批" : result.status === "failed" ? "审批后运行失败" : "审批后运行完成",
      });
    } catch (error) {
      set({
        runRunning: false,
        status: error instanceof Error ? error.message : "恢复运行失败",
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
      validationOpen: true,
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
  const targetNode = project.nodes.find((node) => node.id === target);
  const kind =
    sourceNode?.type === "parallel_worker" || targetNode?.type === "parallel_worker"
      ? "worker"
      : sourceHandle === "error"
        ? "error"
      : sourceNode && ["condition", "ai_router", "human_approval", "json_extractor", "json_validator"].includes(sourceNode.type)
        ? "conditional"
        : "normal";
  return {
    id: nanoid(),
    source,
    sourceHandle,
    target,
    targetHandle,
    type: "smoothstep",
    label: kind === "conditional" || kind === "error" ? sourceHandle ?? kind : undefined,
    data: { kind },
  };
}

function syncAllParallelWorkers(project: ProjectIR): ProjectIR {
  const parentIds = new Set(project.nodes.filter((node) => node.type === "parallel_tools").map((node) => node.id));
  let next: ProjectIR = {
    ...project,
    nodes: project.nodes.filter((node) => node.type !== "parallel_worker" || parentIds.has(String(node.config.parentNodeId ?? ""))),
  };
  for (const parentId of parentIds) {
    next = syncParallelWorkers(next, parentId);
  }
  return next;
}

function syncParallelWorkers(project: ProjectIR, parentNodeId: string): ProjectIR {
  const parent = project.nodes.find((node) => node.id === parentNodeId && node.type === "parallel_tools");
  if (!parent) return project;
  const desiredCount = clampParallelWorkerCount(parent.config.maxConcurrentWorkers);
  const existingWorkers = parallelWorkersFor(project, parentNodeId);
  const outputTarget = findParallelWorkerOutputTarget(project, parentNodeId, existingWorkers);
  const kept = existingWorkers.slice(0, desiredCount);
  const removedIds = new Set(existingWorkers.slice(desiredCount).map((node) => node.id));
  const nodes = project.nodes
    .filter((node) => !removedIds.has(node.id))
    .map((node) => {
      if (node.type !== "parallel_worker" || String(node.config.parentNodeId ?? "") !== parentNodeId) return node;
      const index = kept.findIndex((worker) => worker.id === node.id);
      if (index < 0) return node;
      return normalizeParallelWorkerNode(node, parent, index);
    });
  const currentWorkers = nodes.filter((node) => node.type === "parallel_worker" && String(node.config.parentNodeId ?? "") === parentNodeId);
  const nextWorkers = [...currentWorkers];
  const usedNodeIds = new Set(nextNodesIds(project.nodes));
  for (let index = currentWorkers.length; index < desiredCount; index += 1) {
    const worker = createParallelWorkerNode(parent, index, usedNodeIds);
    usedNodeIds.add(worker.id);
    nextWorkers.push(worker);
  }
  const nextWorkerIds = new Set(nextWorkers.map((worker) => worker.id));
  const nextNodes = [...nodes.filter((node) => node.type !== "parallel_worker" || String(node.config.parentNodeId ?? "") !== parentNodeId), ...nextWorkers];
  let edges = project.edges.filter((edge) => !removedIds.has(edge.source) && !removedIds.has(edge.target));
  edges = edges.filter((edge) => {
    if (edge.source === parentNodeId && edge.kind === "normal") return false;
    if (edge.kind !== "worker") return true;
    if (edge.source === parentNodeId) return false;
    if (nextWorkerIds.has(edge.source) || nextWorkerIds.has(edge.target)) return false;
    return true;
  });
  const workerEdges: EdgeIR[] = [];
  for (const worker of nextWorkers) {
    workerEdges.push(makeWorkerEdge(parentNodeId, worker.id, "parent"));
  }
  if (outputTarget && outputTarget.target !== parentNodeId && !nextWorkerIds.has(outputTarget.target)) {
    for (const worker of nextWorkers) {
      workerEdges.push(makeWorkerEdge(worker.id, outputTarget.target, "output", outputTarget.targetHandle));
    }
  }
  return { ...project, nodes: nextNodes, edges: [...edges, ...workerEdges] };
}

function connectParallelWorkerOutput(project: ProjectIR, sourceNode: NodeIR, target: string, targetHandle: string | null): ProjectIR {
  const parentNodeId = sourceNode.type === "parallel_tools" ? sourceNode.id : String(sourceNode.config.parentNodeId ?? "");
  if (!parentNodeId) return project;
  let next = syncParallelWorkers(project, parentNodeId);
  const workers = parallelWorkersFor(next, parentNodeId);
  const workerIds = new Set(workers.map((worker) => worker.id));
  if (workerIds.has(target)) return next;
  next = {
    ...next,
    edges: next.edges.filter((edge) => !(edge.kind === "worker" && workerIds.has(edge.source) && edge.target !== parentNodeId)),
  };
  return {
    ...next,
    edges: [
      ...next.edges,
      ...workers.map((worker) => makeWorkerEdge(worker.id, target, "output", targetHandle)),
    ],
  };
}

function parallelWorkersFor(project: ProjectIR, parentNodeId: string): NodeIR[] {
  return project.nodes
    .filter((node) => node.type === "parallel_worker" && String(node.config.parentNodeId ?? "") === parentNodeId)
    .sort((a, b) => Number(a.config.workerIndex ?? 0) - Number(b.config.workerIndex ?? 0) || a.id.localeCompare(b.id));
}

function createParallelWorkerNode(parent: NodeIR, index: number, usedNodeIds: Set<string>): NodeIR {
  const baseId = `${parent.id}_worker_${index + 1}`;
  let id = baseId;
  let suffix = 2;
  while (usedNodeIds.has(id)) {
    id = `${baseId}_${suffix}`;
    suffix += 1;
  }
  return {
    ...createNode("parallel_worker", index, {
      x: parent.position.x + 330,
      y: parent.position.y + index * 210,
    }),
    id,
    label: `Worker ${index + 1}`,
    config: {
      parentNodeId: parent.id,
      workerIndex: index + 1,
    },
  };
}

function nextNodesIds(nodes: NodeIR[]): string[] {
  return nodes.map((node) => node.id);
}

function normalizeParallelWorkerNode(worker: NodeIR, parent: NodeIR, index: number): NodeIR {
  const defaultLabel = /^Worker\s+\d+$/i.test(worker.label) || worker.label === "parallel_worker";
  return {
    ...worker,
    label: defaultLabel ? `Worker ${index + 1}` : worker.label,
    config: {
      ...worker.config,
      parentNodeId: parent.id,
      workerIndex: index + 1,
    },
  };
}

function makeWorkerEdge(source: string, target: string, role: "parent" | "output", targetHandle?: string | null): EdgeIR {
  return {
    id: `worker_${role}_${source}_${target}`,
    source,
    sourceHandle: "out",
    target,
    targetHandle: targetHandle ?? "in",
    kind: "worker",
    label: role === "parent" ? "worker" : null,
  };
}

function findParallelWorkerOutputTarget(project: ProjectIR, parentNodeId: string, workers: NodeIR[]): { target: string; targetHandle: string | null } | null {
  const workerIds = new Set(workers.map((worker) => worker.id));
  const workerOutput = project.edges.find((edge) => edge.kind === "worker" && workerIds.has(edge.source) && !workerIds.has(edge.target));
  if (workerOutput) return { target: workerOutput.target, targetHandle: workerOutput.targetHandle ?? null };
  const legacyOutput = project.edges.find((edge) => edge.source === parentNodeId && edge.kind === "normal");
  if (legacyOutput) return { target: legacyOutput.target, targetHandle: legacyOutput.targetHandle ?? null };
  return null;
}

function clampParallelWorkerCount(value: unknown): number {
  const parsed = Number(value ?? 3);
  if (!Number.isFinite(parsed)) return 3;
  return Math.max(1, Math.min(Math.round(parsed), 6));
}

const NODE_PLACEMENT_WIDTH = 270;
const NODE_PLACEMENT_HEIGHT = 190;
const NODE_PLACEMENT_STEP_X = 310;
const NODE_PLACEMENT_STEP_Y = 230;

function findAvailableNodePosition(project: ProjectIR, basePosition: Position): Position {
  const candidates = placementCandidates(basePosition);
  for (const candidate of candidates) {
    if (!hasLargeNodeOverlap(project, candidate)) {
      return roundPosition(candidate);
    }
  }
  return roundPosition(candidates[candidates.length - 1] ?? basePosition);
}

function placementCandidates(basePosition: Position): Position[] {
  const origin = {
    x: basePosition.x - NODE_PLACEMENT_WIDTH / 2,
    y: basePosition.y - NODE_PLACEMENT_HEIGHT / 2,
  };
  const candidates: Position[] = [origin];
  for (let radius = 1; radius <= 8; radius += 1) {
    const points: Position[] = [
      { x: origin.x + radius * NODE_PLACEMENT_STEP_X, y: origin.y },
      { x: origin.x, y: origin.y + radius * NODE_PLACEMENT_STEP_Y },
      { x: origin.x - radius * NODE_PLACEMENT_STEP_X, y: origin.y },
      { x: origin.x, y: origin.y - radius * NODE_PLACEMENT_STEP_Y },
      { x: origin.x + radius * NODE_PLACEMENT_STEP_X, y: origin.y + radius * NODE_PLACEMENT_STEP_Y },
      { x: origin.x - radius * NODE_PLACEMENT_STEP_X, y: origin.y + radius * NODE_PLACEMENT_STEP_Y },
      { x: origin.x + radius * NODE_PLACEMENT_STEP_X, y: origin.y - radius * NODE_PLACEMENT_STEP_Y },
      { x: origin.x - radius * NODE_PLACEMENT_STEP_X, y: origin.y - radius * NODE_PLACEMENT_STEP_Y },
    ];
    candidates.push(...points);
  }
  return candidates;
}

function hasLargeNodeOverlap(project: ProjectIR, position: Position): boolean {
  const rect = nodePlacementRect(position);
  const maxAllowedOverlap = NODE_PLACEMENT_WIDTH * NODE_PLACEMENT_HEIGHT * 0.18;
  return project.nodes.some((node) => rectOverlapArea(rect, nodePlacementRect(node.position)) > maxAllowedOverlap);
}

function nodePlacementRect(position: Position) {
  return {
    left: position.x,
    top: position.y,
    right: position.x + NODE_PLACEMENT_WIDTH,
    bottom: position.y + NODE_PLACEMENT_HEIGHT,
  };
}

function rectOverlapArea(
  a: { left: number; top: number; right: number; bottom: number },
  b: { left: number; top: number; right: number; bottom: number },
) {
  const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  return width * height;
}

function roundPosition(position: Position): Position {
  return { x: Math.round(position.x), y: Math.round(position.y) };
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

function pickAssistantTemplateId(prompt: string): string {
  if (/exa|websearch|web search|联网|搜索网页|网页搜索|mcp/i.test(prompt)) return "websearch_exa_mcp";
  if (/多.?agent|子.?agent|协作|编排|handoff|agent tool|历史 Agent/i.test(prompt)) return "multi_agent_orchestration";
  if (/api|json|清洗|校验|订单接口|订单 API/i.test(prompt)) return "api_json_cleanup";
  if (/并发|foreach|for each|任务处理|task plan|结构化任务|错误兜底|merge|worker/i.test(prompt)) return "flow_control_task_processing";
  if (/客服|售后|订单|退款/.test(prompt)) return "customer_support";
  if (/知识库|问答|文档|rag|检索/i.test(prompt)) return "knowledge_qa";
  return "knowledge_qa";
}

function applyTemplateRuntimeDependencies(project: ProjectIR, template: ProjectTemplate): ProjectIR {
  const requiredMcpServers = template.requiredMcpServers ?? [];
  if (!requiredMcpServers.length) return project;
  return {
    ...project,
    mcpServers: mergeTemplateMcpServers(project.mcpServers ?? [], requiredMcpServers),
  };
}

function mergeTemplateMcpServers(existing: MCPServerConfig[], required: MCPServerConfig[]): MCPServerConfig[] {
  const byId = new Map(existing.map((server) => [server.id, server]));
  const orderedIds = existing.map((server) => server.id);
  required.forEach((server) => {
    const current = byId.get(server.id);
    if (!current) {
      byId.set(server.id, { ...server });
      orderedIds.push(server.id);
      return;
    }
    byId.set(server.id, mergeTemplateMcpServer(current, server));
  });
  return orderedIds
    .map((id) => byId.get(id))
    .filter((server): server is MCPServerConfig => Boolean(server));
}

function mergeTemplateMcpServer(current: MCPServerConfig, required: MCPServerConfig): MCPServerConfig {
  const merged = { ...required, ...current, enabled: true } as MCPServerConfig;
  const currentRecord = merged as unknown as Record<string, unknown>;
  const requiredRecord = required as unknown as Record<string, unknown>;
  Object.entries(requiredRecord).forEach(([key, value]) => {
    const currentValue = currentRecord[key];
    if (typeof value === "string" && value.trim() && typeof currentValue === "string" && !currentValue.trim()) {
      if (key === "apiKeyEnv" && merged.apiKeyMode === "direct" && merged.apiKey.trim()) return;
      currentRecord[key] = value;
    }
    if (typeof value === "number" && (!Number.isFinite(Number(currentValue)) || Number(currentValue) <= 0)) {
      currentRecord[key] = value;
    }
  });
  return merged;
}

function normalizeMcpServers(servers: MCPServerConfig[]): MCPServerConfig[] {
  return servers
    .filter((server) => server && typeof server.id === "string")
    .map((server) => {
      const legacyBearerEnv = String(server.bearerTokenEnvVar || "");
      const apiKeyMode = String(server.apiKeyMode || (server.apiKey && !server.apiKeyEnv ? "direct" : "env"));
      const apiKeyHeader = String(server.apiKeyHeader || (legacyBearerEnv ? "Authorization" : "Authorization"));
      const apiKeyPrefix = String(server.apiKeyPrefix || (apiKeyHeader.toLowerCase() === "authorization" ? "Bearer" : ""));
      return {
        id: server.id,
        name: String(server.name || "未命名 MCP"),
        transport: String(server.transport || "stdio"),
        command: String(server.command || ""),
        argsJson: String(server.argsJson || "[]"),
        envJson: String(server.envJson || "{}"),
        envVarsJson: String(server.envVarsJson || "[]"),
        cwd: String(server.cwd || ""),
        url: String(server.url || ""),
        apiKey: apiKeyMode === "direct" ? String(server.apiKey || "") : "",
        apiKeyEnv: apiKeyMode === "env" ? String(server.apiKeyEnv || legacyBearerEnv) : "",
        apiKeyMode,
        apiKeyHeader,
        apiKeyPrefix,
        bearerTokenEnvVar: legacyBearerEnv,
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
      };
    });
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

function normalizeResourceGroups(groups: ResourceGroupConfig[]): ResourceGroupConfig[] {
  const seenIds = new Set<string>();
  return groups
    .filter((group) => group && typeof group === "object")
    .map((group) => {
      let id = typeof group.id === "string" && group.id.trim() ? group.id.trim() : `group_${nanoid(8)}`;
      if (seenIds.has(id)) id = `group_${nanoid(8)}`;
      seenIds.add(id);
      const resourceType = group.resourceType === "skill" ? "skill" : "tool";
      const itemIds = Array.from(
        new Set((group.itemIds ?? []).map((item) => String(item).trim()).filter(Boolean)),
      );
      return {
        id,
        name: String(group.name || "").trim() || (resourceType === "skill" ? "预设技能组" : "预设工具组"),
        description: String(group.description || "").trim(),
        resourceType,
        itemIds,
      };
    });
}

function normalizeRuntimeEnvironments(configs: RuntimeEnvironmentConfig[]): RuntimeEnvironmentConfig[] {
  const normalized = configs
    .filter((config) => config && typeof config.id === "string")
    .map((config) => ({
      id: config.id,
      name: String(config.name || "本地后端"),
      kind: "local_backend",
      description: String(config.description || "由当前 FastAPI 后端所在机器执行工具。"),
      allowedRootsJson: safeJsonList(config.allowedRootsJson, ["./"]),
      networkEnabled: config.networkEnabled !== false,
      allowAllHosts: config.allowAllHosts === true,
      allowedHostsJson: config.allowAllHosts === true ? "[]" : safeJsonList(config.allowedHostsJson, ["api.duckduckgo.com"]),
      maxFileBytes: Math.max(1, Number(config.maxFileBytes || 1048576)),
      maxHttpBytes: Math.max(1, Number(config.maxHttpBytes || 262144)),
      allowDirectEdits: config.allowDirectEdits === true,
      allowedCommandProfilesJson: safeJsonList(config.allowedCommandProfilesJson, defaultCommandProfiles()),
      maxPatchBytes: Math.max(1, Number(config.maxPatchBytes || 524288)),
      maxCommandOutputBytes: Math.max(1, Number(config.maxCommandOutputBytes || 262144)),
    }));
  return normalized.length ? normalized : [newDefaultRuntimeEnvironment()];
}

function ensureTemplateRuntimeHosts(
  configs: RuntimeEnvironmentConfig[],
  runtimeEnvironmentId: string | null,
  requiredHosts: string[],
): { configs: RuntimeEnvironmentConfig[]; changed: boolean; addedHosts: string[] } {
  const hosts = Array.from(new Set(requiredHosts.map((host) => host.trim()).filter(Boolean)));
  const normalized = normalizeRuntimeEnvironments(configs);
  if (!hosts.length) return { configs: normalized, changed: false, addedHosts: [] };
  const selected = pickRuntimeEnvironment(normalized, runtimeEnvironmentId);
  if (!selected || selected.allowAllHosts === true) return { configs: normalized, changed: false, addedHosts: [] };
  const currentHosts = parseStringList(selected.allowedHostsJson);
  const addedHosts = hosts.filter((host) => !isHostAllowedByList(host, currentHosts));
  const shouldEnableNetwork = selected.networkEnabled === false;
  if (!addedHosts.length && !shouldEnableNetwork) return { configs: normalized, changed: false, addedHosts: [] };
  const mergedHosts = Array.from(new Set([...currentHosts, ...addedHosts]));
  return {
    configs: normalized.map((config) => config.id === selected.id
      ? {
          ...config,
          networkEnabled: true,
          allowedHostsJson: JSON.stringify(mergedHosts, null, 2),
        }
      : config),
    changed: true,
    addedHosts,
  };
}

function safeJsonList(value: unknown, fallback: string[]): string {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item).trim()).filter(Boolean);
    return JSON.stringify(items.length ? items : fallback, null, 2);
  }
  const text = String(value ?? "").trim();
  if (!text) return JSON.stringify(fallback, null, 2);
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      const items = parsed.map((item) => String(item).trim()).filter(Boolean);
      return JSON.stringify(items.length ? items : fallback, null, 2);
    }
  } catch {
    const items = text.split(/[;,\n]+/).map((item) => item.trim()).filter(Boolean);
    return JSON.stringify(items.length ? items : fallback, null, 2);
  }
  return JSON.stringify(fallback, null, 2);
}

function parseStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parsed.map((item) => String(item).trim()).filter(Boolean);
  } catch {
    return text.split(/[;,\n]+/).map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function isHostAllowedByList(host: string, allowedHosts: string[]): boolean {
  const normalizedHost = host.trim().toLowerCase();
  return allowedHosts.some((item) => {
    const candidate = item.trim().toLowerCase();
    if (!candidate) return false;
    if (candidate === "*" || candidate === normalizedHost) return true;
    if (candidate.startsWith("*.")) return normalizedHost.endsWith(candidate.slice(1));
    return false;
  });
}

function newDefaultRuntimeEnvironment(): RuntimeEnvironmentConfig {
  return {
    id: "runtime_local_backend",
    name: "本地后端",
    kind: "local_backend",
    description: "由当前 FastAPI 后端所在机器执行工具。",
    allowedRootsJson: JSON.stringify(["./"], null, 2),
    networkEnabled: true,
    allowAllHosts: false,
    allowedHostsJson: JSON.stringify(["api.duckduckgo.com"], null, 2),
    maxFileBytes: 1048576,
    maxHttpBytes: 262144,
    allowDirectEdits: false,
    allowedCommandProfilesJson: JSON.stringify(defaultCommandProfiles(), null, 2),
    maxPatchBytes: 524288,
    maxCommandOutputBytes: 262144,
  };
}

function defaultCommandProfiles(): string[] {
  return [
    "git status",
    "git diff",
    "git diff --check",
    "npm run build",
    "npm test",
    "npm run lint",
    "python -m pytest",
    "pytest",
    "python -m compileall",
  ];
}

function pickRuntimeEnvironment(configs: RuntimeEnvironmentConfig[], currentId: string | null): RuntimeEnvironmentConfig | null {
  if (currentId) {
    const selected = configs.find((config) => config.id === currentId);
    if (selected) return selected;
  }
  return configs[0] ?? null;
}

function ensureProjectRuntimeEnvironment(project: ProjectIR, configs: RuntimeEnvironmentConfig[]): ProjectIR {
  const selected = pickRuntimeEnvironment(configs, project.project.runtimeEnvironmentId);
  const runtimeEnvironmentId = project.project.runtimeEnvironmentId || selected?.id || "";
  return {
    ...project,
    project: {
      ...project.project,
      runtimeEnvironmentId,
    },
  };
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

function collectStateFieldNames(project: ProjectIR): Set<string> {
  return new Set(project.state.fields.map((field) => field.name).filter(Boolean));
}

function collectNodeWriteFieldNames(nodes: NodeIR[]): Set<string> {
  const names = new Set<string>();
  for (const node of nodes) {
    for (const field of stateFieldsForNode(node)) {
      names.add(field.name);
    }
  }
  return names;
}

function uniqueNodeOutputConfig(
  type: NodeType,
  config: Record<string, unknown>,
  existingStateNames: Set<string>,
  reservedNodeFieldNames: Set<string>,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  const keys = stateWriteKeysForNodeType(type);
  for (const key of keys) {
    const current = normalizeFieldName(config[key]) || defaultWriteFieldName(type, key);
    if (!current) continue;
    if (!existingStateNames.has(current) && !reservedNodeFieldNames.has(current)) {
      reservedNodeFieldNames.add(current);
      patch[key] = current;
      continue;
    }
    const unique = nextAvailableFieldName(current, new Set([...existingStateNames, ...reservedNodeFieldNames]));
    reservedNodeFieldNames.add(unique);
    patch[key] = unique;
  }
  return patch;
}

function sanitizeNodeWriteConfig(type: NodeType, config: Record<string, unknown>): Record<string, unknown> {
  const next = { ...config };
  for (const key of stateWriteKeysForNodeType(type)) {
    const normalized = normalizeFieldName(next[key]) || defaultWriteFieldName(type, key);
    if (normalized) {
      next[key] = normalized;
    }
  }
  return next;
}

function stateWriteKeysForNodeType(type: NodeType): string[] {
  switch (type) {
    case "ai_router":
      return ["routeField", "reasonField"];
    case "human_approval":
      return ["actionField", "outputField"];
    case "llm":
    case "agent":
    case "tool":
    case "task_splitter":
    case "parallel_tools":
    case "template":
    case "retriever":
    case "http":
    case "direct_reply":
    case "custom_function":
    case "skill_node":
    case "mcp_node":
    case "error_handler":
      return ["outputField"];
    case "variable_assign":
      return ["resultField"];
    case "json_extractor":
    case "json_validator":
      return ["outputField", "validationField"];
    case "for_each":
      return ["resultField"];
    case "merge":
      return ["resultField"];
    default:
      return [];
  }
}

function defaultWriteFieldName(type: NodeType, key: string): string {
  if (type === "ai_router" && key === "routeField") return "route_key";
  if (type === "ai_router" && key === "reasonField") return "route_reason";
  if (type === "human_approval" && key === "actionField") return "approval_action";
  if (type === "human_approval" && key === "outputField") return "approval_result";
  switch (type) {
    case "llm":
    case "direct_reply":
      return "final_answer";
    case "agent":
      return "agent_result";
    case "tool":
      return "tools_result";
    case "task_splitter":
      return "worker_tasks";
    case "parallel_tools":
      return "worker_results";
    case "variable_assign":
      return "assignment_result";
    case "template":
      return "template_result";
    case "json_extractor":
      return key === "validationField" ? "validation_result" : "extracted_json";
    case "json_validator":
      return key === "validationField" ? "validation_result" : "validated_json";
    case "for_each":
      return "for_each_result";
    case "merge":
      return "merge_result";
    case "error_handler":
      return "error_result";
    case "retriever":
      return "retrieved_context";
    case "http":
      return "http_response";
    case "custom_function":
      return "custom_output";
    case "skill_node":
      return "skill_result";
    case "mcp_node":
      return "mcp_result";
    default:
      return "";
  }
}

function parseJsonStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.map((item) => String(item).trim()).filter(Boolean) : [];
  } catch {
    return text.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean);
  }
}

function parseJsonObjectList(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
  }
  if (value && typeof value === "object") return [value as Record<string, unknown>];
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
    }
    return parsed && typeof parsed === "object" ? [parsed as Record<string, unknown>] : [];
  } catch {
    return [];
  }
}

function stateFieldsForNode(node: NodeIR): StateField[] {
  const config = node.config;
  switch (node.type) {
    case "start":
      return [{ name: "messages", type: "str", description: `${node.label} 输入` }];
    case "llm":
      return [stateFieldFromConfig(config, "outputField", "final_answer", "str", `${node.label} 输出`)];
    case "agent": {
      const output = stateFieldFromConfig(config, "outputField", "agent_result", "str", `${node.label} 输出`);
      const mcpIds = parseJsonStringList(config.mcpServerIdsJson);
      return mcpIds.length
        ? [
            output,
            {
              name: `${output.name}_mcp_tool_calls`,
              type: "list",
              description: "MCP 调用记录",
            },
          ]
        : [output];
    }
    case "tool": {
      const output = stateFieldFromConfig(config, "outputField", "tools_result", "str", `${node.label} 输出`);
      return [
        output,
        {
          name: `${output.name}_tool_calls`,
          type: "list",
          description: `${node.label} 工具调用记录`,
        },
      ];
    }
    case "task_splitter":
      return [stateFieldFromConfig(config, "outputField", "worker_tasks", "list", `${node.label} 任务列表`)];
    case "parallel_tools":
      return [stateFieldFromConfig(config, "outputField", "worker_results", "list", `${node.label} Worker 结果`)];
    case "variable_assign": {
      const fields = [stateFieldFromConfig(config, "resultField", "assignment_result", "dict", `${node.label} 赋值摘要`)];
      for (const assignment of parseJsonObjectList(config.assignmentsJson)) {
        const target = normalizeFieldName(assignment.target ?? assignment.field ?? assignment.name);
        if (target) fields.push({ name: target.split(".")[0], type: "Any", description: `${node.label} 写入字段` });
      }
      return fields;
    }
    case "template":
      return [stateFieldFromConfig(config, "outputField", "template_result", String(config.outputType ?? "text") === "json" ? "dict" : "str", `${node.label} 输出`)];
    case "json_extractor":
      return [
        stateFieldFromConfig(config, "outputField", "extracted_json", "dict", `${node.label} 抽取结果`),
        stateFieldFromConfig(config, "validationField", "validation_result", "dict", `${node.label} 校验结果`),
        stateFieldFromConfig(config, "repairResultField", "repair_result", "dict", `${node.label} 修复结果`),
      ];
    case "json_validator":
      return [
        stateFieldFromConfig(config, "outputField", "validated_json", "dict", `${node.label} 校验输出`),
        stateFieldFromConfig(config, "validationField", "validation_result", "dict", `${node.label} 校验结果`),
        stateFieldFromConfig(config, "repairResultField", "repair_result", "dict", `${node.label} 修复结果`),
      ];
    case "for_each":
      return normalizeFieldName(config.resultField)
        ? [stateFieldFromConfig(config, "resultField", "for_each_result", "dict", `${node.label} 迭代摘要`)]
        : [];
    case "merge": {
      const fields = [stateFieldFromConfig(config, "resultField", "merge_result", "dict", `${node.label} 聚合摘要`)];
      for (const reducer of parseJsonObjectList(config.reducersJson)) {
        const target = normalizeFieldName(reducer.target ?? reducer.field ?? reducer.name);
        if (target) fields.push({ name: target.split(".")[0], type: "Any", description: `${node.label} 聚合字段` });
      }
      return fields;
    }
    case "retriever":
      return [stateFieldFromConfig(config, "outputField", "retrieved_context", "str", `${node.label} 检索结果`)];
    case "ai_router":
      return [
        stateFieldFromConfig(config, "routeField", "route_key", "str", `${node.label} 路由结果`),
        stateFieldFromConfig(config, "reasonField", "route_reason", "str", `${node.label} 路由理由`),
      ];
    case "human_approval":
      return [
        stateFieldFromConfig(config, "actionField", "approval_action", "str", `${node.label} 审批动作`),
        stateFieldFromConfig(config, "outputField", "approval_result", "dict", `${node.label} 审批结果`),
      ];
    case "http":
      return [stateFieldFromConfig(config, "outputField", "http_response", "dict", `${node.label} 响应`)];
    case "direct_reply":
      return [stateFieldFromConfig(config, "outputField", "final_answer", "str", `${node.label} 最终回复`)];
    case "custom_function":
      return [stateFieldFromConfig(config, "outputField", "custom_output", "dict", `${node.label} 输出`)];
    case "skill_node":
      return [stateFieldFromConfig(config, "outputField", "skill_result", "str", `${node.label} 输出`)];
    case "mcp_node":
      return [stateFieldFromConfig(config, "outputField", "mcp_result", "dict", `${node.label} 输出`)];
    case "error_handler":
      return [stateFieldFromConfig(config, "outputField", "error_result", "dict", `${node.label} 输出`)];
    default:
      return [];
  }
}

function stateFieldFromConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: string,
  type: string,
  description: string,
): StateField {
  return {
    name: normalizeFieldName(config[key]) || fallback,
    type,
    description,
  };
}

function mergeStateFields(existing: StateField[], additions: StateField[]): StateField[] {
  const result = [...existing];
  const names = new Set(result.map((field) => field.name));
  for (const addition of additions) {
    if (!addition.name || names.has(addition.name)) continue;
    result.push(addition);
    names.add(addition.name);
  }
  return result;
}

function syncStateFieldsForNodeUpdate(
  existing: StateField[],
  beforeNode: NodeIR,
  afterNode: NodeIR,
  nodesAfterUpdate: NodeIR[],
): StateField[] {
  const beforeFields = stateFieldsForNode(beforeNode);
  const afterFields = stateFieldsForNode(afterNode);
  let result = [...existing];
  for (let index = 0; index < afterFields.length; index += 1) {
    const beforeField = beforeFields[index];
    const afterField = afterFields[index];
    if (!afterField?.name) continue;
    if (!beforeField?.name || beforeField.name === afterField.name) {
      result = ensureStateField(result, afterField);
      continue;
    }

    const oldIndex = result.findIndex((field) => field.name === beforeField.name);
    const newExists = result.some((field) => field.name === afterField.name);
    const oldNameStillUsed = isStateFieldUsedByOtherNodes(beforeField.name, nodesAfterUpdate, afterNode.id);
    if (oldIndex >= 0 && !newExists && !oldNameStillUsed) {
      result = result.map((field, fieldIndex) =>
        fieldIndex === oldIndex
          ? {
              ...field,
              name: afterField.name,
              type: field.type || afterField.type,
              description: field.description || afterField.description,
            }
          : field,
      );
      continue;
    }
    result = ensureStateField(result, afterField);
  }
  return result;
}

function ensureStateField(fields: StateField[], field: StateField): StateField[] {
  if (!field.name) return fields;
  if (fields.some((item) => item.name === field.name)) return fields;
  return [...fields, field];
}

function isStateFieldUsedByOtherNodes(fieldName: string, nodes: NodeIR[], nodeId: string): boolean {
  return nodes.some((node) => node.id !== nodeId && stateFieldsForNode(node).some((field) => field.name === fieldName));
}

function nextAvailableFieldName(baseName: string, used: Set<string>): string {
  const normalized = normalizeFieldName(baseName) || "field";
  if (!used.has(normalized)) return normalized;
  for (let index = 1; index < 10000; index += 1) {
    const candidate = `${normalized}_${index}`;
    if (!used.has(candidate)) return candidate;
  }
  return `${normalized}_${Date.now()}`;
}

function normalizeFieldName(value: unknown): string {
  return String(value ?? "").trim().replace(/[^a-zA-Z0-9_]/g, "_").replace(/^([^a-zA-Z_])/, "_$1");
}

function applyConnectionInputDefaults(project: ProjectIR, sourceId: string, targetId: string): ProjectIR {
  const source = project.nodes.find((node) => node.id === sourceId);
  const target = project.nodes.find((node) => node.id === targetId);
  if (!source || !target) return project;
  const sourceField = primaryOutputField(source);
  if (!sourceField) return project;
  const token = `{{ state.${sourceField} }}`;
  const nodes = project.nodes.map((node) => {
    if (node.id !== target.id) return node;
    const patch = inputPatchForConnectedNode(node, token, sourceField);
    return Object.keys(patch).length ? { ...node, config: { ...node.config, ...patch } } : node;
  });
  return { ...project, nodes };
}

function primaryOutputField(node: NodeIR): string {
  if (node.type === "start") return "messages";
  if (node.type === "ai_router") return normalizeFieldName(node.config.routeField) || "";
  if (node.type === "human_approval") return normalizeFieldName(node.config.outputField) || "";
  if (node.type === "condition") return "";
  return normalizeFieldName(node.config.outputField) || "";
}

function inputPatchForConnectedNode(node: NodeIR, token: string, sourceField: string): Record<string, unknown> {
  switch (node.type) {
    case "llm":
    case "agent":
    case "tool":
      return shouldReplaceStateTemplate(node.config.userPrompt) ? { userPrompt: token } : {};
    case "retriever":
      return shouldReplaceStateTemplate(node.config.query) ? { query: token } : {};
    case "condition":
      return shouldReplaceStateFieldName(node.config.field) ? { field: sourceField } : {};
    case "ai_router":
      return shouldReplaceStateTemplate(node.config.inputText) ? { inputText: token } : {};
    case "direct_reply":
      return shouldReplaceStateTemplate(node.config.template) ? { template: token } : {};
    case "http":
      return shouldReplaceStateTemplate(node.config.body) ? { body: token } : {};
    default:
      return {};
  }
}

function shouldReplaceStateTemplate(value: unknown): boolean {
  const text = String(value ?? "").trim();
  if (!text) return true;
  return /^{{\s*state\.[a-zA-Z_][a-zA-Z0-9_]*\s*}}$/.test(text);
}

function shouldReplaceStateFieldName(value: unknown): boolean {
  const text = String(value ?? "").trim();
  return !text || text === "intent";
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

async function loadRunHistoryRecords(projectId: string): Promise<RunHistoryRecord[]> {
  const localRecords = readRunHistory(projectId);
  try {
    const remoteRecords = await listProjectRunHistory(projectId);
    if (remoteRecords.length > 0) {
      writeRunHistory(projectId, remoteRecords);
      return remoteRecords;
    }
    if (localRecords.length > 0) {
      void Promise.all(localRecords.map((record) => saveProjectRunHistory(projectId, record))).catch(() => undefined);
    }
  } catch {
    return localRecords;
  }
  return localRecords;
}

async function persistRunHistoryRecord(projectId: string, record: RunHistoryRecord): Promise<void> {
  try {
    const saved = await saveProjectRunHistory(projectId, record);
    const records = readRunHistory(projectId);
    const next = [saved, ...records.filter((item) => item.id !== saved.id)].slice(0, RUN_HISTORY_LIMIT);
    writeRunHistory(projectId, next);
  } catch {
    // The UI already has the run result. Keep the local fallback if backend persistence fails.
  }
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

function runtimeNodesFromTrace(project: ProjectIR, trace: RunTraceItem[]): Record<string, NodeRuntimeState> {
  const nodes = initializeRuntimeNodes(project);
  const now = new Date().toISOString();
  for (const item of trace) {
    nodes[item.nodeId] = {
      status: item.status,
      label: item.label,
      detail: item.detail,
      durationMs: item.durationMs,
      inputState: item.inputState,
      outputDelta: item.outputDelta,
      updatedAt: now,
      virtual: item.virtual,
      parentNodeId: item.parentNodeId ?? null,
      iterationIndex: item.iterationIndex ?? null,
      iterationItem: item.iterationItem,
      sourceNodeId: item.sourceNodeId ?? null,
      attempts: item.attempts,
      errorPolicy: item.errorPolicy ?? null,
      timeoutSec: item.timeoutSec ?? null,
      parallel: item.parallel ?? null,
      itemFailurePolicy: item.itemFailurePolicy ?? null,
      nodeType: item.type,
      position: item.position ?? null,
    };
  }
  return nodes;
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

function abortActiveRun() {
  if (activeRunAbortController && !activeRunAbortController.signal.aborted) {
    activeRunAbortController.abort();
  }
}

function markRuntimeNodesInterrupted(nodes: Record<string, NodeRuntimeState>): Record<string, NodeRuntimeState> {
  const now = new Date().toISOString();
  const next: Record<string, NodeRuntimeState> = {};
  for (const [nodeId, runtime] of Object.entries(nodes)) {
    if (runtime.status === "running" || runtime.status === "queued") {
      next[nodeId] = {
        ...runtime,
        status: "skipped",
        detail: runtime.status === "running" ? "运行已中断" : "未执行，运行已中断",
        updatedAt: now,
      };
    } else {
      next[nodeId] = runtime;
    }
  }
  return next;
}

function isAbortError(error: unknown) {
  return Boolean(error && typeof error === "object" && "name" in error && error.name === "AbortError");
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
        status: "completed",
        pendingApproval: null,
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
          parentNodeId: event.parentNodeId ?? null,
          iterationIndex: event.iterationIndex ?? null,
          iterationItem: event.iterationItem,
          sourceNodeId: event.sourceNodeId ?? null,
        },
      },
      runResult: state.runResult
        ? { ...state.runResult, valid: event.valid, issues: event.issues }
        : { mode: event.mode, valid: event.valid, issues: event.issues, trace: [], outputState: event.inputState, status: "completed", pendingApproval: null },
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
      parentNodeId: event.traceItem.parentNodeId ?? null,
      iterationIndex: event.traceItem.iterationIndex ?? null,
      iterationItem: event.traceItem.iterationItem,
      sourceNodeId: event.traceItem.sourceNodeId ?? null,
      attempts: event.traceItem.attempts,
      errorPolicy: event.traceItem.errorPolicy ?? null,
      timeoutSec: event.traceItem.timeoutSec ?? null,
      parallel: event.traceItem.parallel ?? null,
      itemFailurePolicy: event.traceItem.itemFailurePolicy ?? null,
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
        status: event.traceItem.pause ? "paused" : state.runResult?.status ?? "completed",
        pendingApproval: event.traceItem.pause && event.traceItem.approval ? event.traceItem.approval as NonNullable<RunPreviewResult["pendingApproval"]> : state.runResult?.pendingApproval ?? null,
      },
      status: event.traceItem.status === "error" ? `运行失败：${event.traceItem.label}` : `节点完成：${event.traceItem.label}`,
      selectedNodeId: event.traceItem.nodeId,
    };
  }
  if (event.event === "virtual_node_start") {
    return {
      runRunning: true,
      runtimeNodes: {
        ...state.runtimeNodes,
        [event.nodeId]: {
          status: "running",
          label: event.label,
          detail: "Worker 运行中",
          durationMs: 0,
          inputState: event.inputState,
          outputDelta: {},
          updatedAt: now,
          virtual: true,
          parentNodeId: event.parentNodeId,
          nodeType: event.type,
          position: event.position ?? null,
        },
      },
      runResult: state.runResult
        ? { ...state.runResult, valid: event.valid, issues: event.issues }
        : { mode: event.mode, valid: event.valid, issues: event.issues, trace: [], outputState: event.inputState, status: "completed", pendingApproval: null },
      status: `正在运行：${event.label}`,
      selectedNodeId: event.nodeId,
    };
  }
  if (event.event === "virtual_node_end") {
    const trace = upsertTraceItem(state.runResult?.trace ?? [], event.traceItem);
    const nodeRuntime: NodeRuntimeState = {
      status: event.traceItem.status,
      label: event.traceItem.label,
      detail: event.traceItem.detail,
      durationMs: event.traceItem.durationMs,
      inputState: event.traceItem.inputState,
      outputDelta: event.traceItem.outputDelta,
      updatedAt: now,
      virtual: true,
      parentNodeId: event.traceItem.parentNodeId ?? null,
      nodeType: event.traceItem.type,
      position: event.traceItem.position ?? null,
    };
    return {
      runRunning: true,
      runtimeNodes: {
        ...state.runtimeNodes,
        [event.traceItem.nodeId]: nodeRuntime,
      },
      runResult: state.runResult
        ? { ...state.runResult, valid: event.valid, issues: event.issues, trace }
        : { mode: event.mode, valid: event.valid, issues: event.issues, trace, outputState: {}, status: "completed", pendingApproval: null },
      status: event.traceItem.status === "error" ? `Worker 失败：${event.traceItem.label}` : `Worker 完成：${event.traceItem.label}`,
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
      status: event.status ?? "completed",
      pendingApproval: event.pendingApproval ?? null,
    }),
    runRunning: false,
    status: event.status === "paused" ? "运行已暂停，等待人工审批" : event.status === "failed" ? "真实运行失败" : event.valid ? "真实运行完成" : "运行预览完成，但图校验未通过",
  };
}

function upsertTraceItem(trace: RunTraceItem[], item: RunTraceItem): RunTraceItem[] {
  const identity = traceItemIdentity(item);
  const index = trace.findIndex((current) => traceItemIdentity(current) === identity);
  if (index === -1) return [...trace, item];
  return trace.map((current, currentIndex) => (currentIndex === index ? item : current));
}

function traceItemIdentity(item: RunTraceItem): string {
  return [
    item.nodeId,
    item.parentNodeId ?? "",
    item.iterationIndex ?? "",
    item.sourceNodeId ?? "",
  ].join("::");
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
  const realNodes = project.nodes.map((node) => ({
    id: node.id,
    type: "agentNode",
    position: node.position,
    zIndex: 2,
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
  const virtualEntries = Object.entries(runtimeNodes).filter(([, runtime]) => runtime.virtual);
  const virtualPositions = layoutVirtualRuntimeNodes(project, virtualEntries);
  const virtualNodes = virtualEntries
    .map(([id, runtime], index) => ({
      id,
      type: "agentNode",
      position: virtualPositions.get(id) ?? runtime.position ?? fallbackVirtualPosition(project, runtime.parentNodeId ?? "", index),
      zIndex: 1,
      data: {
        id,
        label: runtime.label,
        nodeType: runtime.nodeType ?? "tool",
        config: {},
        inputs: [{ id: "in", type: "control", label: "任务" }],
        outputs: [{ id: "out", type: "control", label: "结果" }],
        runtime,
      },
    }));
  return [...realNodes, ...virtualNodes];
}

export function toReactFlowEdges(project: ProjectIR, runtimeNodes: Record<string, NodeRuntimeState> = {}): Edge[] {
  const realEdges = project.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    sourceHandle: edge.sourceHandle ?? undefined,
    target: edge.target,
    targetHandle: edge.targetHandle ?? undefined,
    type: "smoothstep",
    label: edge.label ?? undefined,
    style: edge.kind === "worker" ? { stroke: "#0a0a0a", strokeDasharray: "5 5", strokeWidth: 1.4 } : undefined,
    data: {
      kind: edge.kind,
      sourceHandle: edge.sourceHandle ?? null,
      targetHandle: edge.targetHandle ?? null,
    },
  }));
  const nextTargets = new Map<string, string>();
  for (const edge of project.edges) {
    if (!nextTargets.has(edge.source)) nextTargets.set(edge.source, edge.target);
  }
  const virtualEdges: Edge[] = [];
  for (const [id, runtime] of Object.entries(runtimeNodes)) {
    if (!runtime.virtual || !runtime.parentNodeId) continue;
    virtualEdges.push({
      id: `${runtime.parentNodeId}->${id}`,
      source: runtime.parentNodeId,
      target: id,
      type: "smoothstep",
      style: { stroke: "#0a0a0a", strokeDasharray: "5 5", strokeWidth: 1.4 },
    });
    const target = nextTargets.get(runtime.parentNodeId);
    if (target) {
      virtualEdges.push({
        id: `${id}->${target}`,
        source: id,
        target,
        type: "smoothstep",
        style: { stroke: "#0a0a0a", strokeDasharray: "5 5", strokeWidth: 1.4 },
      });
    }
  }
  return [...realEdges, ...virtualEdges];
}

function fallbackVirtualPosition(project: ProjectIR, parentNodeId: string, index: number) {
  const parent = project.nodes.find((node) => node.id === parentNodeId);
  return {
    x: (parent?.position.x ?? 360) + 120,
    y: (parent?.position.y ?? 220) + 280 + index * 240,
  };
}

const REAL_NODE_WIDTH = 300;
const REAL_NODE_HEIGHT = 230;
const VIRTUAL_NODE_WIDTH = 310;
const VIRTUAL_NODE_HEIGHT = 230;
const VIRTUAL_NODE_GAP = 28;
const VIRTUAL_SAFE_PADDING = 88;

function layoutVirtualRuntimeNodes(project: ProjectIR, entries: Array<[string, NodeRuntimeState]>): Map<string, Position> {
  const positions = new Map<string, Position>();
  const occupied = project.nodes.map((node) => rectFromPosition(node.position, REAL_NODE_WIDTH, REAL_NODE_HEIGHT, VIRTUAL_SAFE_PADDING));
  const groups = new Map<string, Array<[string, NodeRuntimeState]>>();
  for (const entry of entries) {
    const parentId = entry[1].parentNodeId ?? "";
    if (!groups.has(parentId)) groups.set(parentId, []);
    groups.get(parentId)?.push(entry);
  }
  for (const [parentId, group] of groups) {
    const parent = project.nodes.find((node) => node.id === parentId);
    const ordered = [...group].sort(([left], [right]) => left.localeCompare(right));
    const chosen = chooseVirtualGroupPositions(project, parent?.position ?? { x: 360, y: 220 }, ordered.length, occupied);
    ordered.forEach(([id], index) => {
      const position = chosen[index] ?? fallbackVirtualPosition(project, parentId, index);
      positions.set(id, position);
      occupied.push(rectFromPosition(position, VIRTUAL_NODE_WIDTH, VIRTUAL_NODE_HEIGHT, VIRTUAL_SAFE_PADDING));
    });
  }
  return positions;
}

function chooseVirtualGroupPositions(project: ProjectIR, parent: Position, count: number, occupied: Rect[]): Position[] {
  const totalHeight = count * VIRTUAL_NODE_HEIGHT + Math.max(0, count - 1) * VIRTUAL_NODE_GAP;
  const maxRealX = Math.max(...project.nodes.map((node) => node.position.x), parent.x);
  const maxRealY = Math.max(...project.nodes.map((node) => node.position.y), parent.y);
  const minRealY = Math.min(...project.nodes.map((node) => node.position.y), parent.y);
  const candidates = [
    stackCandidate(parent.x + 360, parent.y - (totalHeight - VIRTUAL_NODE_HEIGHT) / 2, count),
    stackCandidate(parent.x + 80, parent.y + REAL_NODE_HEIGHT + 150, count),
    stackCandidate(parent.x + 80, parent.y - totalHeight - 150, count),
    stackCandidate(maxRealX + 360, parent.y - (totalHeight - VIRTUAL_NODE_HEIGHT) / 2, count),
    stackCandidate(parent.x + 80, maxRealY + REAL_NODE_HEIGHT + 160, count),
    stackCandidate(parent.x + 80, minRealY - totalHeight - 160, count),
  ];
  return candidates.find((candidate) => !candidateCollides(candidate, occupied)) ?? candidates[1];
}

function stackCandidate(x: number, y: number, count: number): Position[] {
  return Array.from({ length: count }, (_item, index) => ({
    x,
    y: y + index * (VIRTUAL_NODE_HEIGHT + VIRTUAL_NODE_GAP),
  }));
}

function candidateCollides(candidate: Position[], occupied: Rect[]) {
  return candidate.some((position) => {
    const rect = rectFromPosition(position, VIRTUAL_NODE_WIDTH, VIRTUAL_NODE_HEIGHT, VIRTUAL_SAFE_PADDING);
    return occupied.some((item) => rectsOverlap(rect, item));
  });
}

interface Rect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function rectFromPosition(position: Position, width: number, height: number, padding = 0): Rect {
  return {
    left: position.x - padding,
    right: position.x + width + padding,
    top: position.y - padding,
    bottom: position.y + height + padding,
  };
}

function rectsOverlap(a: Rect, b: Rect) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
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
