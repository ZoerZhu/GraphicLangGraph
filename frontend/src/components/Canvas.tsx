import {
  Background,
  ConnectionMode,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useState } from "react";
import { toReactFlowEdges, toReactFlowNodes, useProjectStore } from "../store/projectStore";
import type { EdgeIR, NodeType } from "../types";
import { AgentNode } from "./AgentNode";

interface NodeDropPayload {
  type: NodeType;
  configPatch?: Record<string, unknown>;
  label?: string;
}

const nodeTypes: NodeTypes = {
  agentNode: AgentNode,
};

export function Canvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}

function CanvasInner() {
  const project = useProjectStore((state) => state.project);
  const selectedNodeId = useProjectStore((state) => state.selectedNodeId);
  const selectNode = useProjectStore((state) => state.selectNode);
  const addNode = useProjectStore((state) => state.addNode);
  const save = useProjectStore((state) => state.save);
  const openSplitAgent = useProjectStore((state) => state.openSplitAgent);
  const onNodesChange = useProjectStore((state) => state.onNodesChange);
  const onEdgesChange = useProjectStore((state) => state.onEdgesChange);
  const onConnect = useProjectStore((state) => state.onConnect);
  const { screenToFlowPosition } = useReactFlow();

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const payload = readDropPayload(event);
      const type = payload?.type ?? (event.dataTransfer.getData("application/graphic-langgraph-node") as NodeType);
      if (!type) return;
      addNode(type, screenToFlowPosition({ x: event.clientX, y: event.clientY }), payload?.configPatch, payload?.label);
    },
    [addNode, screenToFlowPosition],
  );

  if (!project) {
    return <main className="canvas-shell">正在连接后端...</main>;
  }

  const nodes = toReactFlowNodes(project).map((node) => ({
    ...node,
    selected: node.id === selectedNodeId,
  }));

  return (
    <main
      className="canvas-shell"
      data-edge-count={project.edges.length}
      onDrop={handleDrop}
      onDragOver={(event) => event.preventDefault()}
    >
      <ReactFlow
        nodes={nodes}
        edges={toReactFlowEdges(project)}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(event, node) => {
          const config = node.data?.config as Record<string, unknown> | undefined;
          const nodeType = node.data?.nodeType as NodeType | undefined;
          if (event.shiftKey && project.project.kind === "agents" && nodeType === "agent_ref") {
            void openSplitAgent(String(config?.agentProjectId ?? ""));
            return;
          }
          selectNode(node.id);
        }}
        onNodeDragStop={() => void save()}
        onPaneClick={() => selectNode(null)}
        connectionMode={ConnectionMode.Loose}
        connectOnClick
        connectionRadius={34}
        defaultEdgeOptions={{
          type: "smoothstep",
          markerEnd: { type: MarkerType.ArrowClosed },
          style: { stroke: "#0a0a0a", strokeWidth: 1.8 },
        }}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }}
        minZoom={0.2}
        maxZoom={1.8}
      >
        <Background gap={18} size={1} color="#d8d8dc" />
        <MiniMap pannable zoomable nodeColor="#ffffff" maskColor="rgba(255,255,255,0.55)" />
      </ReactFlow>
      <ConnectionOverlay edges={project.edges} />
    </main>
  );
}

function readDropPayload(event: React.DragEvent): NodeDropPayload | null {
  const raw = event.dataTransfer.getData("application/graphic-langgraph-node-config");
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<NodeDropPayload>;
    if (!parsed.type) return null;
    return {
      type: parsed.type,
      configPatch: parsed.configPatch,
      label: parsed.label,
    };
  } catch {
    return null;
  }
}

interface OverlayLine {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function ConnectionOverlay({ edges }: { edges: EdgeIR[] }) {
  const [lines, setLines] = useState<OverlayLine[]>([]);

  useEffect(() => {
    let disposed = false;

    function updateLines() {
      if (disposed) return;
      const canvas = document.querySelector(".canvas-shell");
      const canvasRect = canvas?.getBoundingClientRect();
      if (!canvasRect) {
        setLines([]);
        return;
      }

      const nextLines = edges
        .map((edge) => {
          const source = findPoint(edge.source, "source", edge.sourceHandle);
          const target = findPoint(edge.target, "target", edge.targetHandle);
          if (!source || !target) return null;
          return {
            id: edge.id,
            x1: source.x - canvasRect.left,
            y1: source.y - canvasRect.top,
            x2: target.x - canvasRect.left,
            y2: target.y - canvasRect.top,
          };
        })
        .filter((line): line is OverlayLine => Boolean(line));
      setLines(nextLines);
    }

    const frame = window.requestAnimationFrame(updateLines);
    const interval = window.setInterval(updateLines, 180);
    window.addEventListener("resize", updateLines);
    return () => {
      disposed = true;
      window.cancelAnimationFrame(frame);
      window.clearInterval(interval);
      window.removeEventListener("resize", updateLines);
    };
  }, [edges]);

  return (
    <svg className="connection-overlay" aria-hidden="true">
      <defs>
        <marker id="connection-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L9,3 z" />
        </marker>
      </defs>
      {lines.map((line) => (
        <path
          key={line.id}
          className="connection-overlay__path"
          d={smoothPath(line.x1, line.y1, line.x2, line.y2)}
          markerEnd="url(#connection-arrow)"
        />
      ))}
    </svg>
  );
}

function findPoint(nodeId: string, direction: "source" | "target", handleId?: string | null) {
  const node = document.querySelector(`.react-flow__node[data-id="${cssEscape(nodeId)}"]`);
  if (!node) return null;
  const handleSelector = [
    ".node-handle",
    direction === "source" ? ".node-handle--source" : ".node-handle--target",
    handleId ? `[data-handleid="${cssEscape(handleId)}"]` : "",
  ].join("");
  const handle = node.querySelector(handleSelector);
  const rect = (handle ?? node).getBoundingClientRect();
  if (handle) {
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }
  return direction === "source"
    ? { x: rect.right, y: rect.top + rect.height / 2 }
    : { x: rect.left, y: rect.top + rect.height / 2 };
}

function smoothPath(x1: number, y1: number, x2: number, y2: number) {
  const distance = Math.max(48, Math.abs(x2 - x1) * 0.5);
  return `M ${x1} ${y1} C ${x1 + distance} ${y1}, ${x2 - distance} ${y2}, ${x2} ${y2}`;
}

function cssEscape(value: string) {
  return window.CSS?.escape ? window.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}
