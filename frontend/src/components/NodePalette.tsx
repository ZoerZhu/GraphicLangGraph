import { useRef } from "react";
import { NODE_CATALOG } from "../lib/nodeCatalog";
import { useProjectStore } from "../store/projectStore";
import type { NodeType } from "../types";

export function NodePalette() {
  const addNode = useProjectStore((state) => state.addNode);
  const hasStart = useProjectStore((state) => state.project?.nodes.some((node) => node.type === "start") ?? false);
  const pointerStart = useRef<Record<string, { x: number; y: number }>>({});

  function handleDragStart(event: React.DragEvent, type: NodeType) {
    event.dataTransfer.setData("application/graphic-langgraph-node", type);
    event.dataTransfer.effectAllowed = "move";
  }

  function handlePointerUp(event: React.PointerEvent, type: NodeType) {
    const start = pointerStart.current[type];
    if (!start || event.button !== 0) return;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (moved < 6) {
      addNode(type);
    }
  }

  return (
    <aside className="left-panel glass-panel">
      <div className="panel-title">
        <span>节点库</span>
        <small>P0</small>
      </div>
      <div className="node-list">
        {NODE_CATALOG.map((item) => {
          const Icon = item.icon;
          const disabled = item.type === "start" && hasStart;
          return (
            <button
              key={item.type}
              className="node-palette-item"
              draggable={!disabled}
              disabled={disabled}
              title={disabled ? "当前项目已有 Start 节点" : "点击添加，或拖拽到画布"}
              onPointerDown={(event) => {
                pointerStart.current[item.type] = { x: event.clientX, y: event.clientY };
              }}
              onPointerUp={(event) => handlePointerUp(event, item.type)}
              onKeyDown={(event) => {
                if ((event.key === "Enter" || event.key === " ") && !disabled) {
                  event.preventDefault();
                  addNode(item.type);
                }
              }}
              onDragStart={(event) => handleDragStart(event, item.type)}
            >
              <span className="node-palette-item__icon">
                <Icon size={18} />
              </span>
              <span>
                <strong>{item.title}</strong>
                <small>{item.description}</small>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
