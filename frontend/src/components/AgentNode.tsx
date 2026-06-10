import { Handle, Position } from "@xyflow/react";
import {
  Braces,
  GitBranch,
  Globe,
  MessageSquareReply,
  Play,
  Sparkles
} from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { NodeType, Port } from "../types";

interface AgentNodeData {
  id: string;
  label: string;
  nodeType: NodeType;
  config: Record<string, unknown>;
  inputs: Port[];
  outputs: Port[];
}

const ICONS = {
  start: Play,
  llm: Sparkles,
  condition: GitBranch,
  http: Globe,
  direct_reply: MessageSquareReply,
  custom_function: Braces,
};

export function AgentNode({ id, data, selected }: { id: string; data: AgentNodeData; selected: boolean }) {
  const Icon = ICONS[data.nodeType];
  const hasManyOutputs = data.outputs.length > 1;
  const handlePortClick = useProjectStore((state) => state.handlePortClick);
  const selectNode = useProjectStore((state) => state.selectNode);
  const summary = nodeSummary(data.nodeType, data.config);
  return (
    <div
      className={`agent-node ${hasManyOutputs ? "has-ports" : ""} ${selected ? "is-selected" : ""}`}
      data-node-type={data.nodeType}
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
            handlePortClick(id, "source", port.id);
          }}
          style={{ top: hasManyOutputs ? `${154 + index * 24}px` : "50%" }}
        />
      ))}
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
    case "condition":
      return [
        { label: "字段", value: text(config.field, "intent") },
        { label: "规则", value: `${operatorLabel(text(config.operator, "equals"))} ${text(config.value, "")}`.trim() },
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
  }
}

function text(value: unknown, fallback: string) {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
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
    case "condition":
      return "CONDITION";
    case "http":
      return "HTTP";
    case "direct_reply":
      return "REPLY";
    case "custom_function":
      return "FUNCTION";
  }
}
