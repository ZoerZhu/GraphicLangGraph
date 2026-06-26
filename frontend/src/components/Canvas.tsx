import {
  Background,
  ConnectionMode,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toReactFlowEdges, toReactFlowNodes, useProjectStore } from "../store/projectStore";
import type { EdgeIR, NodeType, ProjectIR } from "../types";
import { AgentNode } from "./AgentNode";
import { FloatingPanel } from "./FloatingPanel";

interface NodeDropPayload {
  type: NodeType;
  configPatch?: Record<string, unknown>;
  label?: string;
}

const nodeTypes: NodeTypes = {
  agentNode: AgentNode,
};

const MINI_NODE_WIDTH = 248;
const MINI_NODE_HEIGHT = 172;
const MINI_SELECTED_COLOR = "#18a957";
const MINI_LAYER_COLORS = [
  "rgba(82, 94, 112, 0.56)",
  "rgba(103, 115, 92, 0.56)",
  "rgba(122, 105, 89, 0.54)",
  "rgba(102, 93, 118, 0.54)",
  "rgba(88, 112, 116, 0.54)",
];

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
  const miniMapOpen = useProjectStore((state) => state.miniMapOpen);
  const runActive = useProjectStore((state) => state.runActive);
  const runtimeNodes = useProjectStore((state) => state.runtimeNodes);
  const selectNode = useProjectStore((state) => state.selectNode);
  const addNode = useProjectStore((state) => state.addNode);
  const setCanvasCenter = useProjectStore((state) => state.setCanvasCenter);
  const save = useProjectStore((state) => state.save);
  const openSplitAgent = useProjectStore((state) => state.openSplitAgent);
  const onNodesChange = useProjectStore((state) => state.onNodesChange);
  const onEdgesChange = useProjectStore((state) => state.onEdgesChange);
  const onConnect = useProjectStore((state) => state.onConnect);
  const { screenToFlowPosition } = useReactFlow();
  const viewport = useViewport();

  useEffect(() => {
    const canvas = document.querySelector(".canvas-shell");
    const rect = canvas?.getBoundingClientRect();
    const width = rect?.width || window.innerWidth || 1280;
    const height = rect?.height || window.innerHeight || 720;
    const zoom = viewport.zoom || 1;
    setCanvasCenter({
      x: (width / 2 - viewport.x) / zoom,
      y: (height / 2 - viewport.y) / zoom,
    });
  }, [setCanvasCenter, viewport.x, viewport.y, viewport.zoom]);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      if (runActive) return;
      const payload = readDropPayload(event);
      const type = payload?.type ?? (event.dataTransfer.getData("application/graphic-langgraph-node") as NodeType);
      if (!type) return;
      addNode(type, screenToFlowPosition({ x: event.clientX, y: event.clientY }), payload?.configPatch, payload?.label);
    },
    [addNode, runActive, screenToFlowPosition],
  );

  if (!project) {
    return <main className="canvas-shell">正在连接后端...</main>;
  }

  const nodes = toReactFlowNodes(project, runActive ? runtimeNodes : {}).map((node) => ({
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
        edges={toReactFlowEdges(project, runActive ? runtimeNodes : {})}
        nodeTypes={nodeTypes}
        onNodesChange={runActive ? undefined : onNodesChange}
        onEdgesChange={runActive ? undefined : onEdgesChange}
        onConnect={runActive ? undefined : onConnect}
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
        nodesDraggable={!runActive}
        nodesConnectable={!runActive}
        edgesFocusable={!runActive}
        edgesReconnectable={!runActive}
        connectionMode={ConnectionMode.Loose}
        connectOnClick={!runActive}
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
        {miniMapOpen ? <CanvasMiniMap project={project} selectedNodeId={selectedNodeId} /> : null}
      </ReactFlow>
      {!runActive ? <ConnectionOverlay edges={project.edges} /> : null}
    </main>
  );
}

function CanvasMiniMap({ project, selectedNodeId }: { project: ProjectIR; selectedNodeId: string | null }) {
  return (
    <FloatingPanel
      title="小地图"
      className="minimap-panel"
      initialRect={miniMapInitialRect}
      minWidth={220}
      minHeight={170}
      maxWidth={520}
      maxHeight={420}
      bare
      dragDelayMs={220}
      dragSurface="panel"
    >
      {({ width, height }) => (
        <div className="minimap-panel__body">
          <ProjectMiniMap width={width} height={height} project={project} selectedNodeId={selectedNodeId} />
        </div>
      )}
    </FloatingPanel>
  );
}

function ProjectMiniMap({
  width,
  height,
  project,
  selectedNodeId,
}: {
  width: number;
  height: number;
  project: ProjectIR;
  selectedNodeId: string | null;
}) {
  const viewport = useViewport();
  const { setCenter } = useReactFlow();
  const selectNode = useProjectStore((state) => state.selectNode);
  const geometry = useMemo(() => buildMiniMapGeometry(project, viewport, width, height), [height, project, viewport, width]);

  function handleDoubleClick(event: React.MouseEvent<SVGSVGElement>) {
    if (!geometry) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const flowX = (event.clientX - rect.left - geometry.offsetX) / geometry.scale + geometry.minX;
    const flowY = (event.clientY - rect.top - geometry.offsetY) / geometry.scale + geometry.minY;
    void setCenter(flowX, flowY, { duration: 220, zoom: Math.max(0.55, viewport.zoom) });
  }

  function focusNode(nodeId: string) {
    const node = project.nodes.find((item) => item.id === nodeId);
    if (!node) return;
    selectNode(node.id);
    void setCenter(node.position.x + MINI_NODE_WIDTH / 2, node.position.y + MINI_NODE_HEIGHT / 2, {
      duration: 260,
      zoom: Math.max(0.72, viewport.zoom),
    });
  }

  if (!geometry) {
    return <div className="project-minimap project-minimap--empty">暂无节点</div>;
  }

  return (
    <svg
      className="project-minimap"
      role="img"
      aria-label="画布小地图"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      onDoubleClick={handleDoubleClick}
    >
      <rect className="project-minimap__background" x="0" y="0" width={width} height={height} rx="14" />
      {project.edges.map((edge) => {
        const source = geometry.nodes.get(edge.source);
        const target = geometry.nodes.get(edge.target);
        if (!source || !target) return null;
        return (
          <path
            key={edge.id}
            className="project-minimap__edge"
            d={`M ${source.cx} ${source.cy} L ${target.cx} ${target.cy}`}
          />
        );
      })}
      {project.nodes.map((node) => {
        const rect = geometry.nodes.get(node.id);
        if (!rect) return null;
        const selected = node.id === selectedNodeId;
        const nodeFill = selected ? MINI_SELECTED_COLOR : MINI_LAYER_COLORS[rect.layer % MINI_LAYER_COLORS.length];
        return (
          <g
            key={node.id}
            className="project-minimap__node-group"
            onClick={(event) => {
              event.stopPropagation();
              focusNode(node.id);
            }}
          >
            <title>{`${node.label} · 第 ${rect.layer + 1} 层`}</title>
            {selected ? (
              <rect
                className="project-minimap__selection"
                x={rect.x - 4}
                y={rect.y - 4}
                width={rect.width + 8}
                height={rect.height + 8}
                rx="8"
              />
            ) : null}
            <rect
              className={`project-minimap__node ${selected ? "is-selected" : ""}`}
              x={rect.x}
              y={rect.y}
              width={rect.width}
              height={rect.height}
              rx="5"
              style={{ fill: nodeFill }}
            />
            <MiniMapNodeIcon
              selected={selected}
              size={Math.max(10, Math.min(18, rect.height * 0.42))}
              type={node.type}
              x={rect.cx}
              y={rect.cy}
            />
          </g>
        );
      })}
      <rect
        className="project-minimap__viewport"
        x={geometry.viewport.x}
        y={geometry.viewport.y}
        width={geometry.viewport.width}
        height={geometry.viewport.height}
        rx="4"
      />
    </svg>
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

function MiniMapNodeIcon({
  selected,
  size,
  type,
  x,
  y,
}: {
  selected: boolean;
  size: number;
  type: NodeType;
  x: number;
  y: number;
}) {
  const stroke = selected ? "#ffffff" : "rgba(255, 255, 255, 0.78)";
  const strokeWidth = Math.max(1.35, size * 0.11);
  const iconProps = {
    fill: "none",
    stroke,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth,
  };
  const fill = selected ? "#ffffff" : "rgba(255, 255, 255, 0.72)";

  return (
    <g className="project-minimap__icon" transform={`translate(${x} ${y}) scale(${size / 24})`}>
      {renderMiniMapIcon(type, iconProps, fill)}
    </g>
  );
}

function renderMiniMapIcon(
  type: NodeType,
  iconProps: {
    fill: string;
    stroke: string;
    strokeLinecap: "round";
    strokeLinejoin: "round";
    strokeWidth: number;
  },
  fill: string,
) {
  switch (type) {
    case "start":
      return <path d="M-5 -7 L8 0 L-5 7 Z" fill={fill} stroke="none" />;
    case "llm":
      return (
        <>
          <path d="M0 -10 L2.3 -2.3 L10 0 L2.3 2.3 L0 10 L-2.3 2.3 L-10 0 L-2.3 -2.3 Z" {...iconProps} />
          <path d="M8 -9 L9 -6 L12 -5 L9 -4 L8 -1 L7 -4 L4 -5 L7 -6 Z" {...iconProps} />
        </>
      );
    case "agent":
    case "agent_ref":
      return (
        <>
          <circle cx="0" cy="-4" r="4" {...iconProps} />
          <path d="M-8 9 C-6 3 6 3 8 9" {...iconProps} />
          <path d="M8 -7 L11 -4 M11 -7 L8 -4" {...iconProps} />
        </>
      );
    case "tool":
    case "skill_node":
      return (
        <>
          <path d="M6 -9 L10 -5 L-4 9 L-9 10 L-8 5 Z" {...iconProps} />
          <path d="M3 -6 L7 -2" {...iconProps} />
        </>
      );
    case "retriever":
      return (
        <>
          <ellipse cx="0" cy="-6" rx="9" ry="4" {...iconProps} />
          <path d="M-9 -6 V7 C-9 9 9 9 9 7 V-6" {...iconProps} />
          <path d="M-9 1 C-9 3 9 3 9 1" {...iconProps} />
        </>
      );
    case "condition":
      return (
        <>
          <circle cx="-8" cy="-6" r="3" {...iconProps} />
          <circle cx="8" cy="-8" r="3" {...iconProps} />
          <circle cx="8" cy="8" r="3" {...iconProps} />
          <path d="M-5 -5 C0 -5 1 -8 5 -8 M-5 -4 C0 -1 1 8 5 8" {...iconProps} />
        </>
      );
    case "ai_router":
      return (
        <>
          <circle cx="-8" cy="0" r="3" {...iconProps} />
          <circle cx="7" cy="-7" r="3" {...iconProps} />
          <circle cx="8" cy="8" r="3" {...iconProps} />
          <path d="M-5 -1 L4 -6 M-5 1 L5 7" {...iconProps} />
        </>
      );
    case "human_approval":
      return (
        <>
          <circle cx="-4" cy="-6" r="4" {...iconProps} />
          <path d="M-11 9 C-10 4 2 4 3 9" {...iconProps} />
          <path d="M5 2 L8 5 L13 -3" {...iconProps} />
        </>
      );
    case "http":
      return (
        <>
          <circle cx="0" cy="0" r="10" {...iconProps} />
          <path d="M-9 0 H9 M0 -10 C-4 -6 -4 6 0 10 M0 -10 C4 -6 4 6 0 10" {...iconProps} />
        </>
      );
    case "direct_reply":
      return (
        <>
          <path d="M-10 -7 H10 V5 H-2 L-8 10 V5 H-10 Z" {...iconProps} />
          <path d="M-5 -1 H5" {...iconProps} />
        </>
      );
    case "custom_function":
      return (
        <>
          <path d="M-6 -8 C-10 -6 -10 6 -6 8 M6 -8 C10 -6 10 6 6 8" {...iconProps} />
          <path d="M-2 6 L3 -6" {...iconProps} />
        </>
      );
    case "mcp_node":
      return (
        <>
          <rect x="-9" y="-8" width="18" height="16" rx="4" {...iconProps} />
          <path d="M-4 -2 H4 M-4 4 H2" {...iconProps} />
        </>
      );
    default:
      return (
        <>
          <rect x="-8" y="-8" width="16" height="16" rx="4" {...iconProps} />
          <circle cx="0" cy="0" r="2" fill={fill} stroke="none" />
        </>
      );
  }
}

interface OverlayLine {
  id: string;
  kind: EdgeIR["kind"];
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
            kind: edge.kind,
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
          className={`connection-overlay__path ${line.kind === "worker" ? "is-worker-edge" : ""}`}
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

function buildMiniMapGeometry(project: ProjectIR, viewport: { x: number; y: number; zoom: number }, width: number, height: number) {
  if (project.nodes.length === 0 || width <= 0 || height <= 0) return null;
  const nodeLayers = computeNodeLayers(project);
  const canvasWidth = typeof window === "undefined" ? 1280 : window.innerWidth;
  const canvasHeight = typeof window === "undefined" ? 720 : window.innerHeight;
  const zoom = viewport.zoom || 1;
  const viewportRect = {
    x: -viewport.x / zoom,
    y: -viewport.y / zoom,
    width: canvasWidth / zoom,
    height: canvasHeight / zoom,
  };
  const nodeRects = project.nodes.map((node) => ({
    id: node.id,
    x: node.position.x,
    y: node.position.y,
    width: MINI_NODE_WIDTH,
    height: MINI_NODE_HEIGHT,
    layer: nodeLayers.get(node.id) ?? 0,
  }));
  const minX = Math.min(viewportRect.x, ...nodeRects.map((node) => node.x)) - 80;
  const minY = Math.min(viewportRect.y, ...nodeRects.map((node) => node.y)) - 80;
  const maxX = Math.max(viewportRect.x + viewportRect.width, ...nodeRects.map((node) => node.x + node.width)) + 80;
  const maxY = Math.max(viewportRect.y + viewportRect.height, ...nodeRects.map((node) => node.y + node.height)) + 80;
  const boundsWidth = Math.max(1, maxX - minX);
  const boundsHeight = Math.max(1, maxY - minY);
  const padding = 10;
  const scale = Math.min((width - padding * 2) / boundsWidth, (height - padding * 2) / boundsHeight);
  const offsetX = (width - boundsWidth * scale) / 2;
  const offsetY = (height - boundsHeight * scale) / 2;
  const mapRect = (rect: { x: number; y: number; width: number; height: number }) => ({
    x: offsetX + (rect.x - minX) * scale,
    y: offsetY + (rect.y - minY) * scale,
    width: Math.max(4, rect.width * scale),
    height: Math.max(3, rect.height * scale),
  });
  const nodes = new Map(
    nodeRects.map((node) => {
      const rect = mapRect(node);
      return [
        node.id,
        {
          ...rect,
          cx: rect.x + rect.width / 2,
          cy: rect.y + rect.height / 2,
          layer: node.layer,
        },
      ];
    }),
  );
  return {
    minX,
    minY,
    offsetX,
    offsetY,
    scale,
    nodes,
    viewport: mapRect(viewportRect),
  };
}

function computeNodeLayers(project: ProjectIR) {
  const layers = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  for (const edge of project.edges) {
    const targets = outgoing.get(edge.source) ?? [];
    targets.push(edge.target);
    outgoing.set(edge.source, targets);
  }

  const starts = project.nodes.filter((node) => node.type === "start").map((node) => node.id);
  const queue = (starts.length > 0 ? starts : project.nodes[0] ? [project.nodes[0].id] : []).map((id) => ({ id, layer: 0 }));
  for (const item of queue) {
    layers.set(item.id, item.layer);
  }

  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    for (const target of outgoing.get(current.id) ?? []) {
      if (layers.has(target)) continue;
      const layer = current.layer + 1;
      layers.set(target, layer);
      queue.push({ id: target, layer });
    }
  }

  const fallbackLayer = Math.max(0, ...Array.from(layers.values())) + 1;
  for (const node of project.nodes) {
    if (!layers.has(node.id)) {
      layers.set(node.id, fallbackLayer);
    }
  }
  return layers;
}

function miniMapInitialRect() {
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: Math.max(16, viewportWidth - 316),
    y: Math.max(110, viewportHeight - 248),
    width: 292,
    height: 218,
  };
}

function cssEscape(value: string) {
  return window.CSS?.escape ? window.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}
