import {
  Background,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import { X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { toReactFlowEdges, toReactFlowNodes, useProjectStore } from "../store/projectStore";
import type { NodeIR } from "../types";

const splitNodeTypes: NodeTypes = {
  splitAgentNode: SplitAgentNode,
};

export function SplitAgentWorkspace({ children }: { children: ReactNode }) {
  const splitRatio = useProjectStore((state) => state.splitRatio);
  const setSplitRatio = useProjectStore((state) => state.setSplitRatio);
  const shellRef = useRef<HTMLDivElement | null>(null);

  function startResize(event: React.PointerEvent) {
    event.preventDefault();
    const shellElement = shellRef.current;
    if (!shellElement) return;
    const shellNode: HTMLDivElement = shellElement;
    const pointerId = event.pointerId;
    event.currentTarget.setPointerCapture(pointerId);

    function move(pointerEvent: PointerEvent) {
      const rect = shellNode.getBoundingClientRect();
      setSplitRatio((pointerEvent.clientX - rect.left) / rect.width);
    }

    function stop() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    }

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  return (
    <div
      ref={shellRef}
      className="split-shell"
      style={{ "--split-left": `${splitRatio * 100}%` } as CSSProperties}
    >
      <div className="split-pane split-pane--left">{children}</div>
      <button className="split-divider" aria-label="拖动调节分屏宽度" onPointerDown={startResize} type="button" />
      <div className="split-pane split-pane--right">
        <SplitAgentEditor />
      </div>
    </div>
  );
}

function SplitAgentEditor() {
  const splitAgentProject = useProjectStore((state) => state.splitAgentProject);
  const closeSplitAgent = useProjectStore((state) => state.closeSplitAgent);
  const updateSplitAgentProject = useProjectStore((state) => state.updateSplitAgentProject);
  const updateSplitAgentMeta = useProjectStore((state) => state.updateSplitAgentMeta);
  const saveSplitAgent = useProjectStore((state) => state.saveSplitAgent);
  const openProject = useProjectStore((state) => state.openProject);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNode = useMemo(
    () => splitAgentProject?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [selectedNodeId, splitAgentProject?.nodes],
  );

  if (!splitAgentProject) return null;
  const activeProject = splitAgentProject;

  const nodes = toReactFlowNodes(activeProject).map((node) => ({
    ...node,
    type: "splitAgentNode",
    selected: node.id === selectedNodeId,
  }));

  function onNodesChange(changes: NodeChange[]) {
    const changed = applyNodeChanges(changes, nodes);
    const changedById = new Map(changed.map((node) => [node.id, node]));
    updateSplitAgentProject({
      ...activeProject,
      nodes: activeProject.nodes.map((node) => {
        const changedNode = changedById.get(node.id);
        return changedNode ? { ...node, position: changedNode.position } : node;
      }),
    });
  }

  function updateNode(nodeId: string, patch: Partial<NodeIR>) {
    updateSplitAgentProject({
      ...activeProject,
      nodes: activeProject.nodes.map((node) => (node.id === nodeId ? { ...node, ...patch } : node)),
    });
  }

  return (
    <section className="split-agent-editor">
      <header className="split-agent-editor__top glass-panel">
        <div>
          <strong>右侧 Agent</strong>
          <span>Shift 点击 Agent Ref 打开</span>
        </div>
        <button className="icon-only" onClick={closeSplitAgent} title="关闭分屏" type="button">
          <X size={16} />
        </button>
      </header>

      <div className="split-agent-editor__body">
        <div className="split-agent-canvas glass-panel">
          <ReactFlowProvider>
            <ReactFlow
              nodes={nodes}
              edges={toReactFlowEdges(activeProject)}
              nodeTypes={splitNodeTypes}
              onNodesChange={onNodesChange}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              onPaneClick={() => setSelectedNodeId(null)}
              onNodeDragStop={() => void saveSplitAgent()}
              fitView
              minZoom={0.2}
              maxZoom={1.7}
            >
              <Background gap={18} size={1} color="#d8d8dc" />
              <MiniMap pannable zoomable nodeColor="#ffffff" maskColor="rgba(255,255,255,0.58)" />
            </ReactFlow>
          </ReactFlowProvider>
        </div>

        <aside className="split-agent-inspector glass-panel">
          <div className="panel-title">
            <span>Agent 详情</span>
            <small>{activeProject.nodes.length} 节点</small>
          </div>
          <label className="field compact-field">
            <span>名称</span>
            <input value={activeProject.project.name} onChange={(event) => updateSplitAgentMeta({ name: event.target.value })} />
          </label>
          <label className="field compact-field">
            <span>描述</span>
            <textarea rows={2} value={activeProject.project.description} onChange={(event) => updateSplitAgentMeta({ description: event.target.value })} />
          </label>

          {selectedNode ? (
            <SplitNodeInspector node={selectedNode} onUpdate={(patch) => updateNode(selectedNode.id, patch)} />
          ) : (
            <div className="split-agent-empty">选择右侧画布中的节点后编辑名称和配置。</div>
          )}

          <div className="split-agent-actions">
            <button onClick={() => void saveSplitAgent()} type="button">保存右侧 Agent</button>
            <button
              className="primary"
              onClick={() => {
                const id = activeProject.project.id;
                void saveSplitAgent().then(() => openProject(id));
              }}
              type="button"
            >
              作为主画布编辑
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}

function SplitNode({ data, selected }: NodeProps) {
  const label = typeof data.label === "string" ? data.label : "Node";
  const nodeType = typeof data.nodeType === "string" ? data.nodeType : "node";
  return (
    <div className={`split-agent-node ${selected ? "is-selected" : ""}`}>
      <span>{nodeTypeLabel(nodeType)}</span>
      <strong>{label}</strong>
    </div>
  );
}

function SplitAgentNode(props: NodeProps) {
  return <SplitNode {...props} />;
}

function SplitNodeInspector({ node, onUpdate }: { node: NodeIR; onUpdate: (patch: Partial<NodeIR>) => void }) {
  const [configText, setConfigText] = useState(() => JSON.stringify(node.config, null, 2));
  const [error, setError] = useState("");

  useEffect(() => {
    setConfigText(JSON.stringify(node.config, null, 2));
    setError("");
  }, [node.id, node.config]);

  function applyConfig() {
    try {
      const parsed = JSON.parse(configText) as Record<string, unknown>;
      onUpdate({ config: parsed });
      setError("");
    } catch {
      setError("配置 JSON 格式不正确");
    }
  }

  return (
    <div className="split-node-edit">
      <label className="field compact-field">
        <span>节点名称</span>
        <input value={node.label} onChange={(event) => onUpdate({ label: event.target.value })} />
      </label>
      <label className="field compact-field">
        <span>配置 JSON</span>
        <textarea className="code-area" rows={8} value={configText} onChange={(event) => setConfigText(event.target.value)} onBlur={applyConfig} />
      </label>
      {error ? <div className="split-agent-error">{error}</div> : null}
    </div>
  );
}

function nodeTypeLabel(type: string) {
  switch (type) {
    case "start":
      return "START";
    case "llm":
      return "LLM";
    case "tool":
      return "TOOL";
    case "task_splitter":
      return "TASKS";
    case "parallel_tools":
      return "PARALLEL";
    case "condition":
      return "CONDITION";
    case "http":
      return "HTTP";
    case "direct_reply":
      return "REPLY";
    case "custom_function":
      return "FUNCTION";
    case "skill_node":
      return "SKILL";
    case "mcp_node":
      return "MCP";
    case "agent_ref":
      return "AGENT";
    default:
      return "NODE";
  }
}
