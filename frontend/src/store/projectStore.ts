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
  listProjects,
  runProjectPreview,
  saveProject,
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
  NodeIR,
  NodeType,
  ProjectHistoryRecord,
  ProjectIR,
  ProjectListItem,
  RunPreviewResult,
  StateField,
  ToolConfig,
  ValidationResult,
} from "../types";

interface PendingConnection {
  source: string;
  sourceHandle: string | null;
}

interface ProjectStore {
  mode: "manager" | "editor";
  managerView: "agent" | "agents";
  project: ProjectIR | null;
  projects: ProjectListItem[];
  workspaceTools: ToolConfig[];
  workspaceMcpServers: MCPServerConfig[];
  selectedNodeId: string | null;
  pendingConnection: PendingConnection | null;
  splitAgentProject: ProjectIR | null;
  splitRatio: number;
  validation: ValidationResult | null;
  exportResult: ExportResponse | null;
  historyOpen: boolean;
  historyRecords: ProjectHistoryRecord[];
  selectedHistoryId: string | null;
  templatesOpen: boolean;
  assistantOpen: boolean;
  runOpen: boolean;
  runInput: string;
  runResult: RunPreviewResult | null;
  status: string;
  loading: boolean;
  initialize: () => Promise<void>;
  loadProjectList: () => Promise<void>;
  setManagerView: (view: "agent" | "agents") => void;
  openProject: (projectId: string) => Promise<void>;
  createNewProject: (name: string, kind?: "agent" | "agents") => Promise<void>;
  renameProjectById: (projectId: string, patch: Partial<ProjectIR["project"]>) => Promise<void>;
  deleteProjectById: (projectId: string) => Promise<void>;
  backToManager: () => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  updateProjectMeta: (patch: Partial<ProjectIR["project"]>) => void;
  updateWorkspaceTools: (tools: ToolConfig[]) => void;
  updateWorkspaceMcpServers: (servers: MCPServerConfig[]) => void;
  updateTools: (tools: ToolConfig[]) => void;
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
  setRunInput: (value: string) => void;
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
const WORKSPACE_MCP_KEY = "graphic-langgraph-workspace-mcp";
const HISTORY_LIMIT = 80;

export const useProjectStore = create<ProjectStore>((set, get) => ({
  mode: "manager",
  managerView: "agent",
  project: null,
  projects: [],
  workspaceTools: [],
  workspaceMcpServers: [],
  selectedNodeId: null,
  pendingConnection: null,
  splitAgentProject: null,
  splitRatio: 0.56,
  validation: null,
  exportResult: null,
  historyOpen: false,
  historyRecords: [],
  selectedHistoryId: null,
  templatesOpen: false,
  assistantOpen: false,
  runOpen: false,
  runInput: "{\n  \"messages\": \"我想查询订单物流\"\n}",
  runResult: null,
  status: "未连接后端",
  loading: false,

  async initialize() {
    set({ loading: true, status: "正在加载历史 Agent" });
    try {
      const projects = await listProjects();
      set({
        projects,
        mode: "manager",
        project: null,
        workspaceTools: readLocalArray<ToolConfig>(WORKSPACE_TOOLS_KEY),
        workspaceMcpServers: readLocalArray<MCPServerConfig>(WORKSPACE_MCP_KEY),
        status: "历史 Agent 已加载",
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
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runResult: null,
      status: "项目已加载",
      loading: false,
    });
  },

  async createNewProject(name, kind = get().managerView) {
    set({ loading: true, status: "正在创建 Agent" });
    const fallbackName = kind === "agents" ? "新建 Agents" : "新建 Agent";
    const project = await createProject(name.trim() || fallbackName, kind);
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
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runResult: null,
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
      historyRecords: [],
      selectedHistoryId: null,
      templatesOpen: false,
      assistantOpen: false,
      runOpen: false,
      runResult: null,
      status: "返回管理界面",
    });
  },

  selectNode(nodeId) {
    set({ selectedNodeId: nodeId, status: nodeId ? "正在编辑节点" : "未选中节点" });
  },

  updateProjectMeta(patch) {
    const project = get().project;
    if (!project) return;
    set({ project: { ...project, project: { ...project.project, ...patch } }, status: "已更新 Agent 信息" });
  },

  updateWorkspaceTools(tools) {
    writeLocalArray(WORKSPACE_TOOLS_KEY, tools);
    set({ workspaceTools: tools, status: "已更新全局 Tools" });
  },

  updateWorkspaceMcpServers(workspaceMcpServers) {
    writeLocalArray(WORKSPACE_MCP_KEY, workspaceMcpServers);
    set({ workspaceMcpServers, status: "已更新全局 MCP" });
  },

  updateTools(tools) {
    const project = get().project;
    if (!project) return;
    set({ project: { ...project, tools }, status: "已更新 Tools 配置" });
  },

  updateMcpServers(mcpServers) {
    const project = get().project;
    if (!project) return;
    set({ project: { ...project, mcpServers }, status: "已更新 MCP 配置" });
  },

  updateImportedAgents(importedAgents) {
    const project = get().project;
    if (!project) return;
    set({ project: { ...project, importedAgents }, status: "已更新导入 Agent" });
  },

  updateAgentLinks(agentLinks) {
    const project = get().project;
    if (!project) return;
    set({ project: { ...project, agentLinks }, status: "已更新 Agent 通信配置" });
  },

  addNode(type, position, configPatch, label) {
    const project = get().project;
    if (!project) return;
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
    set({ project: { ...project, state: { ...project.state, fields } } });
  },

  onNodesChange(changes) {
    const project = get().project;
    if (!project) return;
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
    const changed = applyEdgeChanges(changes, toReactFlowEdges(project));
    set({ project: { ...project, edges: changed.map(fromReactFlowEdge) } });
  },

  onConnect(connection) {
    const project = get().project;
    if (!project || !connection.source || !connection.target) return;
    const edge = buildReactFlowEdge(project, connection.source, connection.sourceHandle, connection.target, connection.targetHandle);
    const next = addEdge(edge, toReactFlowEdges(project));
    set({ project: { ...project, edges: next.map(fromReactFlowEdge) }, pendingConnection: null, status: "已连接节点" });
  },

  handlePortClick(nodeId, direction, handleId) {
    const project = get().project;
    if (!project) return;

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
    set((state) => ({ runOpen: !state.runOpen, historyOpen: false }));
  },

  closeRunPanel() {
    set({ runOpen: false });
  },

  setRunInput(runInput) {
    set({ runInput });
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
    set({ status: "正在运行预览", runResult: null });
    const saved = await saveProject(project);
    const historyRecords = recordProjectHistory(saved, "运行预览前保存");
    const runResult = await runProjectPreview(saved.project.id, input);
    set({
      project: saved,
      historyRecords,
      runResult,
      runOpen: true,
      status: runResult.valid ? "运行预览完成" : "运行预览完成，但图校验未通过",
    });
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
    set({ project: saved, historyRecords, exportResult: result, status: "ZIP 已导出" });
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

function createHistoryId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `history_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  }
  return `history_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

export function toReactFlowNodes(project: ProjectIR): Node[] {
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
