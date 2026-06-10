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
import { createProject, exportProject, getProject, saveProject, validateProject } from "../lib/api";
import { createNode, defaultOutputs } from "../lib/nodeCatalog";
import type { EdgeIR, ExportResponse, NodeIR, NodeType, ProjectIR, StateField, ValidationResult } from "../types";

interface PendingConnection {
  source: string;
  sourceHandle: string | null;
}

interface ProjectStore {
  project: ProjectIR | null;
  selectedNodeId: string | null;
  pendingConnection: PendingConnection | null;
  validation: ValidationResult | null;
  exportResult: ExportResponse | null;
  status: string;
  loading: boolean;
  initialize: () => Promise<void>;
  selectNode: (nodeId: string | null) => void;
  addNode: (type: NodeType, position?: { x: number; y: number }) => void;
  updateNode: (nodeId: string, patch: Partial<NodeIR>) => void;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
  setStateFields: (fields: StateField[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  handlePortClick: (nodeId: string, direction: "source" | "target", handleId: string | null) => void;
  save: () => Promise<void>;
  validate: () => Promise<void>;
  exportZip: () => Promise<void>;
}

const PROJECT_KEY = "graphic-langgraph-project-id";

export const useProjectStore = create<ProjectStore>((set, get) => ({
  project: null,
  selectedNodeId: null,
  pendingConnection: null,
  validation: null,
  exportResult: null,
  status: "未连接后端",
  loading: false,

  async initialize() {
    set({ loading: true, status: "正在加载项目" });
    try {
      const existingId = localStorage.getItem(PROJECT_KEY);
      let project: ProjectIR | null = null;
      if (existingId) {
        try {
          project = await getProject(existingId);
        } catch {
          localStorage.removeItem(PROJECT_KEY);
        }
      }
      if (!project) {
        project = await createProject("Untitled Agent");
        localStorage.setItem(PROJECT_KEY, project.project.id);
      }
      project = normalizeNodePositions(project);
      set({ project, status: "项目已加载", loading: false });
    } catch (error) {
      set({ status: error instanceof Error ? error.message : "加载失败", loading: false });
    }
  },

  selectNode(nodeId) {
    set({ selectedNodeId: nodeId, status: nodeId ? "正在编辑节点" : "未选中节点" });
  },

  addNode(type, position) {
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
        nodes: project.nodes.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                config: { ...node.config, ...patch },
                outputs: node.type === "condition" ? defaultOutputs("condition") : node.outputs,
              }
            : node,
        ),
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
    set({ project: saved, status: "已保存" });
  },

  async validate() {
    const project = get().project;
    if (!project) return;
    set({ status: "正在校验" });
    const saved = await saveProject(project);
    const validation = await validateProject(saved.project.id);
    set({
      project: saved,
      validation,
      status: validation.valid ? "校验通过" : `校验发现 ${validation.issues.length} 个问题`,
    });
  },

  async exportZip() {
    const project = get().project;
    if (!project) return;
    set({ status: "正在导出 ZIP", exportResult: null });
    const saved = await saveProject(project);
    const result = await exportProject(saved.project.id);
    set({ project: saved, exportResult: result, status: "ZIP 已导出" });
  },
}));

function normalizeNodePositions(project: ProjectIR): ProjectIR {
  if (typeof window === "undefined") return project;
  const narrow = window.innerWidth <= 900;
  const minVisibleX = narrow ? 260 : 318;
  const minVisibleY = narrow ? 150 : 122;
  const needsLayout = project.nodes.some((node) => node.position.x < minVisibleX || node.position.y < minVisibleY);
  if (!needsLayout) return project;

  return {
    ...project,
    nodes: project.nodes.map((node, index) => ({
      ...node,
      position: narrow
        ? { x: 282, y: 170 + index * 210 }
        : { x: 340 + (index % 2) * 300, y: 150 + Math.floor(index / 2) * 230 },
    })),
  };
}

function buildReactFlowEdge(
  project: ProjectIR,
  source: string,
  sourceHandle: string | null | undefined,
  target: string,
  targetHandle: string | null | undefined,
): Edge {
  const sourceNode = project.nodes.find((node) => node.id === source);
  const kind = sourceNode?.type === "condition" ? "conditional" : "normal";
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
    sourceHandle: undefined,
    target: edge.target,
    targetHandle: undefined,
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
