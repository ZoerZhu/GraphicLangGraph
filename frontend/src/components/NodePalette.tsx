import { useMemo, useRef, useState } from "react";
import { Bot, ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen, Plug, Server } from "lucide-react";
import { NODE_CATALOG } from "../lib/nodeCatalog";
import { useProjectStore } from "../store/projectStore";
import type { NodeType } from "../types";

interface DragPayload {
  type: NodeType;
  configPatch?: Record<string, unknown>;
  label?: string;
}

type GroupKey = "skills" | "mcp" | "agents";

export function NodePalette() {
  const addNode = useProjectStore((state) => state.addNode);
  const project = useProjectStore((state) => state.project);
  const projects = useProjectStore((state) => state.projects);
  const workspaceTools = useProjectStore((state) => state.workspaceTools);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const hasStart = project?.nodes.some((node) => node.type === "start") ?? false;
  const pointerStart = useRef<Record<string, { x: number; y: number }>>({});
  const [openGroups, setOpenGroups] = useState<Record<GroupKey, boolean>>({
    skills: false,
    mcp: false,
    agents: true,
  });
  const [collapsed, setCollapsed] = useState(false);

  const tools = useMemo(() => mergeById([...(project?.tools ?? []), ...workspaceTools]), [project?.tools, workspaceTools]);
  const mcpServers = useMemo(
    () => mergeById([...(project?.mcpServers ?? []), ...workspaceMcpServers]),
    [project?.mcpServers, workspaceMcpServers],
  );
  const availableAgents = useMemo(
    () => projects.filter((item) => item.kind === "agent" && item.id !== project?.project.id),
    [project?.project.id, projects],
  );

  function toggleGroup(key: GroupKey) {
    setOpenGroups((current) => ({ ...current, [key]: !current[key] }));
  }

  function handleDragStart(event: React.DragEvent, payload: DragPayload) {
    event.dataTransfer.setData("application/graphic-langgraph-node", payload.type);
    event.dataTransfer.setData("application/graphic-langgraph-node-config", JSON.stringify(payload));
    event.dataTransfer.effectAllowed = "move";
  }

  function handlePointerUp(event: React.PointerEvent, key: string, payload: DragPayload) {
    const start = pointerStart.current[key];
    if (!start || event.button !== 0) return;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (moved < 6) {
      addNode(payload.type, undefined, payload.configPatch, payload.label);
    }
  }

  const baseNodes = NODE_CATALOG.filter((item) => !["skill_node", "mcp_node", "agent_ref"].includes(item.type));

  if (collapsed) {
    return (
      <aside className="left-panel left-panel--collapsed glass-panel">
        <button className="palette-collapse-button" onClick={() => setCollapsed(false)} title="展开节点库" type="button">
          <PanelLeftOpen size={17} />
          <span>节点库</span>
        </button>
      </aside>
    );
  }

  return (
    <aside className="left-panel glass-panel">
      <div className="panel-title">
        <span>节点库</span>
        <span className="panel-title__actions">
          <small>{project?.project.kind === "agents" ? "AGENTS" : "AGENT"}</small>
          <button className="icon-only panel-collapse" onClick={() => setCollapsed(true)} title="收起节点库" type="button">
            <PanelLeftClose size={15} />
          </button>
        </span>
      </div>
      <div className="node-list">
        {baseNodes.map((item) => {
          const Icon = item.icon;
          const disabled = item.type === "start" && hasStart;
          const payload = { type: item.type };
          return (
            <PaletteButton
              key={item.type}
              id={item.type}
              disabled={disabled}
              title={disabled ? "当前项目已有 Start 节点" : "点击添加，或拖拽到画布"}
              onPointerDown={(event) => {
                pointerStart.current[item.type] = { x: event.clientX, y: event.clientY };
              }}
              onPointerUp={(event) => handlePointerUp(event, item.type, payload)}
              onDragStart={(event) => handleDragStart(event, payload)}
              onKeyAdd={() => addNode(item.type)}
            >
              <span className="node-palette-item__icon">
                <Icon size={18} />
              </span>
              <span>
                <strong>{item.title}</strong>
                <small>{item.description}</small>
              </span>
            </PaletteButton>
          );
        })}

        <PaletteGroup
          title="Skill Node"
          description="展开选择已导入 Tool/Skill"
          icon={<Plug size={18} />}
          count={tools.length}
          open={openGroups.skills}
          onClick={() => toggleGroup("skills")}
        />
        {openGroups.skills && (
          <ConfiguredList
            emptyText="先在管理页侧边栏导入 Tool。"
            items={tools}
            render={(tool) => {
              const key = `skill_${tool.id}`;
              const payload: DragPayload = {
                type: "skill_node",
                label: tool.name,
                configPatch: {
                  toolId: tool.id,
                  toolName: tool.name,
                  toolSource: tool.source,
                  toolDescription: tool.description,
                  outputField: `${toFieldName(tool.name)}_result`,
                },
              };
              return (
                <PaletteButton
                  key={key}
                  id={key}
                  className="configured-node"
                  title="点击添加，或拖拽到画布"
                  onPointerDown={(event) => {
                    pointerStart.current[key] = { x: event.clientX, y: event.clientY };
                  }}
                  onPointerUp={(event) => handlePointerUp(event, key, payload)}
                  onDragStart={(event) => handleDragStart(event, payload)}
                  onKeyAdd={() => addNode(payload.type, undefined, payload.configPatch, payload.label)}
                >
                  <span className="node-palette-item__icon">
                    <Plug size={16} />
                  </span>
                  <span>
                    <strong>{tool.name}</strong>
                    <small>{tool.source || "tool"} · {tool.description || "未填写描述"}</small>
                  </span>
                </PaletteButton>
              );
            }}
          />
        )}

        <PaletteGroup
          title="MCP Node"
          description="展开选择已配置 MCP Server"
          icon={<Server size={18} />}
          count={mcpServers.length}
          open={openGroups.mcp}
          onClick={() => toggleGroup("mcp")}
        />
        {openGroups.mcp && (
          <ConfiguredList
            emptyText="先在管理页侧边栏配置 MCP。"
            items={mcpServers}
            render={(server) => {
              const key = `mcp_${server.id}`;
              const payload: DragPayload = {
                type: "mcp_node",
                label: server.name,
                configPatch: {
                  serverId: server.id,
                  serverName: server.name,
                  transport: server.transport,
                  command: server.command,
                  url: server.url,
                  outputField: `${toFieldName(server.name)}_result`,
                },
              };
              return (
                <PaletteButton
                  key={key}
                  id={key}
                  className="configured-node"
                  title="点击添加，或拖拽到画布"
                  onPointerDown={(event) => {
                    pointerStart.current[key] = { x: event.clientX, y: event.clientY };
                  }}
                  onPointerUp={(event) => handlePointerUp(event, key, payload)}
                  onDragStart={(event) => handleDragStart(event, payload)}
                  onKeyAdd={() => addNode(payload.type, undefined, payload.configPatch, payload.label)}
                >
                  <span className="node-palette-item__icon">
                    <Server size={16} />
                  </span>
                  <span>
                    <strong>{server.name}</strong>
                    <small>{server.transport} · {server.command || server.url || "未配置入口"}</small>
                  </span>
                </PaletteButton>
              );
            }}
          />
        )}

        {project?.project.kind === "agents" && (
          <>
            <PaletteGroup
              title="Agent Ref"
              description="展开选择历史 Agent 作为通信节点"
              icon={<Bot size={18} />}
              count={availableAgents.length}
              open={openGroups.agents}
              onClick={() => toggleGroup("agents")}
            />
            {openGroups.agents && (
              <ConfiguredList
                emptyText="还没有可引用的单 Agent。先在管理页 Agent 视图创建。"
                items={availableAgents}
                render={(agent) => {
                  const key = `agent_${agent.id}`;
                  const payload: DragPayload = {
                    type: "agent_ref",
                    label: agent.name,
                    configPatch: {
                      agentProjectId: agent.id,
                      agentName: agent.name,
                      protocol: "handoff",
                    },
                  };
                  return (
                    <PaletteButton
                      key={key}
                      id={key}
                      className="configured-node"
                      title="点击添加；Shift + 左键点击画布中的该节点可分屏编辑"
                      onPointerDown={(event) => {
                        pointerStart.current[key] = { x: event.clientX, y: event.clientY };
                      }}
                      onPointerUp={(event) => handlePointerUp(event, key, payload)}
                      onDragStart={(event) => handleDragStart(event, payload)}
                      onKeyAdd={() => addNode(payload.type, undefined, payload.configPatch, payload.label)}
                    >
                      <span className="node-palette-item__icon">
                        <Bot size={16} />
                      </span>
                      <span>
                        <strong>{agent.name}</strong>
                        <small>{agent.nodeCount} 节点 · {agent.edgeCount} 连线</small>
                      </span>
                    </PaletteButton>
                  );
                }}
              />
            )}
          </>
        )}
      </div>
    </aside>
  );
}

function PaletteGroup({
  title,
  description,
  icon,
  count,
  open,
  onClick,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
  count: number;
  open: boolean;
  onClick: () => void;
}) {
  return (
    <button className="node-palette-group" onClick={onClick} type="button">
      <span className="node-palette-item__icon">{icon}</span>
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span className="node-palette-group__meta">
        {count}
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </span>
    </button>
  );
}

function ConfiguredList<T>({
  items,
  emptyText,
  render,
}: {
  items: T[];
  emptyText: string;
  render: (item: T) => React.ReactNode;
}) {
  if (items.length === 0) {
    return <div className="node-palette-empty">{emptyText}</div>;
  }
  return <div className="configured-node-list">{items.map(render)}</div>;
}

function PaletteButton({
  id,
  className = "",
  children,
  disabled,
  title,
  onPointerDown,
  onPointerUp,
  onDragStart,
  onKeyAdd,
}: {
  id: string;
  className?: string;
  children: React.ReactNode;
  disabled?: boolean;
  title: string;
  onPointerDown: (event: React.PointerEvent) => void;
  onPointerUp: (event: React.PointerEvent) => void;
  onDragStart: (event: React.DragEvent) => void;
  onKeyAdd: () => void;
}) {
  return (
    <button
      className={`node-palette-item ${className}`}
      draggable={!disabled}
      disabled={disabled}
      title={title}
      data-palette-id={id}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onKeyDown={(event) => {
        if ((event.key === "Enter" || event.key === " ") && !disabled) {
          event.preventDefault();
          onKeyAdd();
        }
      }}
      onDragStart={onDragStart}
      type="button"
    >
      {children}
    </button>
  );
}

function mergeById<T extends { id: string }>(items: T[]): T[] {
  const map = new Map<string, T>();
  for (const item of items) {
    map.set(item.id, item);
  }
  return Array.from(map.values());
}

function toFieldName(value: string) {
  const cleaned = value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned || "node";
}
