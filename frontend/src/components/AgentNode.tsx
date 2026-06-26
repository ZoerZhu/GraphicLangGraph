import { useState } from "react";
import { Handle, Position } from "@xyflow/react";
import {
  Bot,
  Braces,
  BrainCircuit,
  ChevronDown,
  ChevronUp,
  Database,
  GitBranch,
  GitMerge,
  Globe,
  LoaderCircle,
  MessageSquareReply,
  Play,
  Plug,
  Repeat,
  Route,
  Server,
  Sparkles,
  TriangleAlert,
  UserCheck,
  Wrench
} from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { NodeRuntimeState, NodeType, Port } from "../types";
import { RunInputEditor, RunModelPicker, RunStartButton } from "./RunControls";
import { RuntimeValueView } from "./RuntimeValueView";

interface AgentNodeData {
  id: string;
  label: string;
  nodeType: NodeType;
  config: Record<string, unknown>;
  inputs: Port[];
  outputs: Port[];
  runtime?: NodeRuntimeState | null;
}

const ICONS = {
  start: Play,
  llm: Sparkles,
  agent: BrainCircuit,
  tool: Wrench,
  task_splitter: Route,
  parallel_tools: Wrench,
  parallel_worker: Wrench,
  variable_assign: Braces,
  template: Braces,
  json_extractor: Braces,
  json_validator: GitBranch,
  for_each: Repeat,
  merge: GitMerge,
  error_handler: TriangleAlert,
  retriever: Database,
  condition: GitBranch,
  ai_router: Route,
  human_approval: UserCheck,
  http: Globe,
  direct_reply: MessageSquareReply,
  custom_function: Braces,
  skill_node: Plug,
  mcp_node: Server,
  agent_ref: Bot,
};

export function AgentNode({ id, data, selected }: { id: string; data: AgentNodeData; selected: boolean }) {
  const Icon = ICONS[data.nodeType];
  const hasManyOutputs = data.outputs.length > 1;
  const handlePortClick = useProjectStore((state) => state.handlePortClick);
  const selectNode = useProjectStore((state) => state.selectNode);
  const runActive = useProjectStore((state) => state.runActive);
  const summary = nodeSummary(data.nodeType, data.config);
  const selectedTools = data.nodeType === "tool" || data.nodeType === "parallel_tools" ? selectedToolNames(data.config) : [];
  const runtime = data.runtime ?? null;
  const [runtimeOpen, setRuntimeOpen] = useState(false);
  const hasRuntimeOutput = Boolean(runtime && Object.keys(runtime.outputDelta).length);
  const runtimeClass = runtime ? `is-runtime-${runtime.status}` : "";
  const virtualClass = runtime?.virtual ? "is-virtual-worker" : "";
  const nodeRunning = runtime?.status === "running";
  return (
    <div
      className={`agent-node-frame ${runtimeClass} ${virtualClass}`}
    >
      <div
        className={`agent-node ${hasManyOutputs ? "has-ports" : ""} ${selected ? "is-selected" : ""} ${runtimeClass} ${virtualClass}`}
        data-node-type={data.nodeType}
        data-virtual={runtime?.virtual ? "true" : "false"}
        onClick={() => selectNode(id)}
      >
        {data.inputs.map((port, index) => (
          <Handle
            key={port.id}
            id={port.id}
            type="target"
            position={Position.Left}
            className="node-handle node-handle--target"
            title={port.label ?? port.id}
            onClick={(event) => {
              event.stopPropagation();
              if (runActive) return;
              handlePortClick(id, "target", port.id);
            }}
            style={{ top: `${62 + index * 22}px` }}
          />
        ))}
        <div className="agent-node__head">
          <span className="agent-node__head-left">
            <span className="agent-node__icon">
              <Icon size={15} />
            </span>
            <span className="agent-node__type">{nodeTypeLabel(data.nodeType)}</span>
          </span>
          <span className="agent-node__head-actions">
            {nodeRunning ? (
              <span className="agent-node__running-indicator" title="节点运行中">
                <LoaderCircle className="spin-icon" size={15} />
              </span>
            ) : null}
            {!runActive ? (
              <button
                className="agent-node__edit nodrag nopan"
                title="查看详情并编辑"
                onClick={(event) => {
                  event.stopPropagation();
                  selectNode(id);
                }}
              >
                编辑
              </button>
            ) : null}
          </span>
        </div>
        <div className="agent-node__label">{data.label}</div>
        <div className="agent-node__id">{id}</div>
        <div className="agent-node__summary">
          {summary.map((item) => (
            <div key={item.label} className="agent-node__summary-row">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
        {selectedTools.length > 0 ? (
          <div className="agent-node__tool-list nodrag nopan" title="该节点可用 Tools">
            {selectedTools.map((tool, index) => (
              <span key={`${tool}-${index}`}>{tool}</span>
            ))}
          </div>
        ) : null}
        {data.outputs.length > 1 && (
          <div className="agent-node__ports">
            {data.outputs.map((port) => (
              <span key={port.id}>{port.label ?? port.id}</span>
            ))}
          </div>
        )}
        {data.outputs.map((port, index) => (
          <Handle
            key={port.id}
            id={port.id}
            type="source"
            position={Position.Right}
            className="node-handle node-handle--source"
            title={port.label ?? port.id}
            onClick={(event) => {
              event.stopPropagation();
              if (runActive) return;
              handlePortClick(id, "source", port.id);
            }}
            style={{ top: hasManyOutputs ? `${154 + index * 24}px` : "50%" }}
          />
        ))}
      </div>
      {runActive && data.nodeType === "start" ? <StartNodeRunControls /> : null}
      {runtime ? (
        <div className={`agent-node__runtime nodrag nopan ${runtimeOpen ? "is-open" : ""}`}>
          <div className="agent-node__runtime-head">
            <span className="agent-node__runtime-status">{runtimeStatusLabel(runtime.status)}</span>
            <span className="agent-node__runtime-actions">
              {runtime.durationMs ? <small>{runtime.durationMs}ms</small> : null}
              <button
                type="button"
                className="agent-node__runtime-toggle nodrag nopan"
                title={runtimeOpen ? "收起运行结果" : "展开运行结果"}
                aria-label={runtimeOpen ? "收起运行结果" : "展开运行结果"}
                aria-expanded={runtimeOpen}
                onClick={(event) => {
                  event.stopPropagation();
                  setRuntimeOpen((open) => !open);
                }}
              >
                {runtimeOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
            </span>
          </div>
          {runtimeOpen ? <RuntimeResult runtime={runtime} hasOutput={hasRuntimeOutput} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function runtimeStatusLabel(status: NodeRuntimeState["status"]) {
  switch (status) {
    case "queued":
      return "等待运行";
    case "running":
      return "运行中";
    case "ok":
      return "运行完成";
    case "error":
      return "运行失败";
    case "skipped":
      return "已跳过";
    default:
      return "未运行";
  }
}

function RuntimeResult({ runtime, hasOutput }: { runtime: NodeRuntimeState; hasOutput: boolean }) {
  const entries = Object.entries(runtime.outputDelta);
  return (
    <div className="agent-node__runtime-body nodrag nopan">
      {runtime.detail ? <div className="agent-node__runtime-detail">{runtime.detail}</div> : null}
      {hasOutput ? (
        <div className="agent-node__runtime-vars">
          {entries.map(([name, value]) => (
            <section key={name} className="agent-node__runtime-var">
              <div className="agent-node__runtime-var-name">state.{name}</div>
              <RuntimeValueView value={value} />
            </section>
          ))}
        </div>
      ) : (
        <div className="agent-node__runtime-empty">暂无输出内容</div>
      )}
    </div>
  );
}

function StartNodeRunControls() {
  const [open, setOpen] = useState(true);
  const project = useProjectStore((state) => state.project);
  const runInput = useProjectStore((state) => state.runInput);
  const runRunning = useProjectStore((state) => state.runRunning);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const selectedRunModelConfigId = useProjectStore((state) => state.selectedRunModelConfigId);
  const setRunInput = useProjectStore((state) => state.setRunInput);
  const setSelectedRunModelConfigId = useProjectStore((state) => state.setSelectedRunModelConfigId);
  const runPreview = useProjectStore((state) => state.runPreview);
  const cancelRun = useProjectStore((state) => state.cancelRun);

  return (
    <div className={`agent-node__start-run nodrag nopan ${open ? "is-open" : "is-collapsed"}`} onClick={(event) => event.stopPropagation()}>
      <button
        aria-label={open ? "收起开始节点运行控件" : "展开开始节点运行控件"}
        className="agent-node__start-run-toggle nodrag nopan"
        data-no-drag
        onClick={(event) => {
          event.stopPropagation();
          setOpen((current) => !current);
        }}
        onPointerDown={(event) => event.stopPropagation()}
        title={open ? "收起" : "展开"}
        type="button"
      >
        {open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
      </button>
      {open ? <RunInputEditor project={project} runInput={runInput} setRunInput={setRunInput} /> : null}
      <div className="run-inline-controls">
        <RunModelPicker
          models={workspaceModelConfigs}
          selectedModelId={selectedRunModelConfigId}
          onChange={setSelectedRunModelConfigId}
        />
        <RunStartButton running={runRunning} onRun={() => void runPreview()} onStop={cancelRun} />
      </div>
    </div>
  );
}

function nodeSummary(type: NodeType, config: Record<string, unknown>) {
  switch (type) {
    case "start":
      return [
        { label: "输入", value: text(config.inputMode, "chat") },
        { label: "作用", value: "初始化流程" },
      ];
    case "llm":
      return [
        { label: "模型", value: text(config.model, "gpt-4.1-mini") },
        { label: "输出", value: text(config.outputField, "final_answer") },
      ];
    case "agent":
      return [
        { label: "模型", value: text(config.model, "gpt-4.1-mini") },
        { label: "工具", value: text(config.tools, "未绑定") },
        { label: "Skills", value: skillSummary(config.skillIdsJson) },
      ];
    case "tool":
      return [
        { label: "Tools", value: selectedToolNames(config).length ? `${selectedToolNames(config).length} 个` : "未绑定" },
        { label: "轮次", value: text(config.maxIterations, "4") },
        { label: "输出", value: text(config.outputField, "tools_result") },
      ];
    case "task_splitter":
      return [
        { label: "输入", value: text(config.inputField, "task_plan") },
        { label: "任务", value: `最多 ${text(config.maxTasks, "5")} 个` },
        { label: "输出", value: text(config.outputField, "worker_tasks") },
      ];
    case "parallel_tools":
      return [
        { label: "任务", value: text(config.tasksField, "worker_tasks") },
        { label: "并发", value: text(config.maxConcurrentWorkers, "3") },
        { label: "输出", value: text(config.outputField, "worker_results") },
      ];
    case "parallel_worker":
      return [
        { label: "槽位", value: text(config.workerIndex, "1") },
        { label: "来源", value: "Parallel Tools" },
      ];
    case "variable_assign":
      return [
        { label: "规则", value: `${parseObjectList(config.assignmentsJson).length} 个` },
        { label: "结果", value: text(config.resultField, "assignment_result") },
      ];
    case "template":
      return [
        { label: "类型", value: text(config.outputType, "text") },
        { label: "输出", value: text(config.outputField, "template_result") },
      ];
    case "json_extractor":
      return [
        { label: "模型", value: text(config.model, "gpt-4.1-mini") },
        { label: "Schema", value: `${parseObjectList(config.schemaFieldsJson).length} 字段` },
        { label: "输出", value: text(config.outputField, "extracted_json") },
      ];
    case "json_validator":
      return [
        { label: "输入", value: text(config.inputField, "extracted_json") },
        { label: "Schema", value: `${parseObjectList(config.schemaFieldsJson).length} 字段` },
        { label: "结果", value: text(config.validationField, "validation_result") },
      ];
    case "for_each":
      return [
        { label: "数组", value: text(config.itemsField, "worker_tasks") },
        { label: "Item", value: text(config.itemField, "current_item") },
        { label: "上限", value: text(config.maxItems, "50") },
      ];
    case "merge":
      return [
        { label: "Reducer", value: `${parseObjectList(config.reducersJson).length} 个` },
        { label: "结果", value: text(config.resultField, "merge_result") },
      ];
    case "error_handler":
      return [
        { label: "错误", value: text(config.errorField, "last_error") },
        { label: "输出", value: text(config.outputField, "error_result") },
      ];
    case "retriever":
      return [
        { label: "来源", value: text(config.path, "./knowledge") },
        { label: "TopK", value: text(config.topK, "4") },
      ];
    case "condition":
      return [
        { label: "字段", value: text(config.field, "intent") },
        { label: "规则", value: `${operatorLabel(text(config.operator, "equals"))} ${text(config.value, "")}`.trim() },
      ];
    case "ai_router":
      return [
        { label: "模式", value: text(config.routeMode, "keyword") },
        { label: "路由", value: text(config.routeField, "route_key") },
      ];
    case "human_approval":
      return [
        { label: "动作", value: text(config.defaultAction, "approved") },
        { label: "输出", value: text(config.outputField, "approval_result") },
      ];
    case "http":
      return [
        { label: "方法", value: text(config.method, "GET") },
        { label: "输出", value: text(config.outputField, "http_response") },
      ];
    case "direct_reply":
      return [
        { label: "格式", value: text(config.format, "chat") },
        { label: "输出", value: text(config.outputField, "final_answer") },
      ];
    case "custom_function":
      return [
        { label: "语言", value: "Python" },
        { label: "输出", value: text(config.outputField, "custom_output") },
      ];
    case "skill_node":
      return [
        { label: "Skill", value: text(config.skillName ?? config.toolName, "未选择 Skill") },
        { label: "输出", value: text(config.outputField, "skill_result") },
      ];
    case "mcp_node":
      return [
        { label: "MCP", value: text(config.serverName, "未选择 MCP") },
        { label: "输出", value: text(config.outputField, "mcp_result") },
      ];
    case "agent_ref":
      return [
        { label: "Agent", value: text(config.agentName, "未选择 Agent") },
        { label: "协议", value: text(config.protocol, "handoff") },
        { label: "输出", value: text(config.outputField, "agent_ref_result") },
      ];
  }
}

function text(value: unknown, fallback: string) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function skillSummary(value: unknown) {
  const ids = parseStringList(value);
  return ids.length ? `${ids.length} 个` : "未绑定";
}

function selectedToolNames(config: Record<string, unknown>): string[] {
  const registry = parseObjectList(config.toolRegistryJson);
  const names = registry
    .map((item) => text(item.name ?? item.id, ""))
    .filter(Boolean);
  if (names.length) return uniqueStrings(names);
  const toolsText = text(config.tools, "");
  if (toolsText) return uniqueStrings(toolsText.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean));
  return uniqueStrings(parseStringList(config.toolIdsJson));
}

function parseObjectList(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
  }
  const textValue = String(value ?? "").trim();
  if (!textValue) return [];
  try {
    const parsed = JSON.parse(textValue);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
      : [];
  } catch {
    return [];
  }
}

function uniqueStrings(items: string[]) {
  return Array.from(new Set(items.map((item) => item.trim()).filter(Boolean)));
}

function parseStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  const textValue = String(value ?? "").trim();
  if (!textValue) return [];
  try {
    const parsed = JSON.parse(textValue);
    return Array.isArray(parsed) ? parsed.map((item) => String(item).trim()).filter(Boolean) : [];
  } catch {
    return textValue.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean);
  }
}

function operatorLabel(operator: string) {
  switch (operator) {
    case "not_equals":
      return "不等于";
    case "contains":
      return "包含";
    case "not_contains":
      return "不包含";
    case "is_empty":
      return "为空";
    case "is_not_empty":
      return "不为空";
    default:
      return "等于";
  }
}

function nodeTypeLabel(type: NodeType): string {
  switch (type) {
    case "start":
      return "START";
    case "llm":
      return "LLM";
    case "agent":
      return "AGENT";
    case "tool":
      return "TOOL";
    case "task_splitter":
      return "TASKS";
    case "parallel_tools":
      return "PARALLEL";
    case "parallel_worker":
      return "WORKER";
    case "variable_assign":
      return "ASSIGN";
    case "template":
      return "TEMPLATE";
    case "json_extractor":
      return "EXTRACT";
    case "json_validator":
      return "VALIDATE";
    case "for_each":
      return "FOREACH";
    case "merge":
      return "MERGE";
    case "error_handler":
      return "ERROR";
    case "retriever":
      return "RAG";
    case "condition":
      return "CONDITION";
    case "ai_router":
      return "ROUTER";
    case "human_approval":
      return "APPROVAL";
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
  }
}
