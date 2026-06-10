import {
  Braces,
  GitBranch,
  Globe,
  type LucideIcon,
  MessageSquareReply,
  Play,
  Sparkles
} from "lucide-react";
import type { NodeIR, NodeType, Port } from "../types";

export interface NodeCatalogItem {
  type: NodeType;
  title: string;
  description: string;
  icon: LucideIcon;
}

export const NODE_CATALOG: NodeCatalogItem[] = [
  { type: "start", title: "Start", description: "入口与初始状态", icon: Play },
  { type: "llm", title: "LLM", description: "调用模型生成或抽取", icon: Sparkles },
  { type: "condition", title: "Condition", description: "规则分支路由", icon: GitBranch },
  { type: "http", title: "HTTP", description: "请求外部接口", icon: Globe },
  { type: "direct_reply", title: "Direct Reply", description: "返回最终回复", icon: MessageSquareReply },
  { type: "custom_function", title: "Custom Function", description: "导出 Python 函数", icon: Braces }
];

export function createNode(type: NodeType, index: number, position = { x: 180, y: 180 }): NodeIR {
  const id = `${type}_${Math.random().toString(16).slice(2, 8)}`;
  const base = NODE_CATALOG.find((item) => item.type === type);
  return {
    id,
    type,
    label: base?.title ?? type,
    position,
    config: defaultConfig(type),
    inputs: defaultInputs(type),
    outputs: defaultOutputs(type),
  };
}

export function defaultConfig(type: NodeType): Record<string, unknown> {
  switch (type) {
    case "start":
      return { inputMode: "chat" };
    case "llm":
      return {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是一个严谨的中文助手。",
        userPrompt: "{{ state.messages }}",
        outputField: "final_answer",
      };
    case "condition":
      return {
        field: "intent",
        operator: "equals",
        value: "order",
        trueBranch: "true",
        falseBranch: "false",
        fallback: "fallback",
      };
    case "http":
      return {
        method: "GET",
        url: "https://api.example.com/items/{{ state.item_id }}",
        body: "",
        authSecret: "",
        outputField: "http_response",
      };
    case "direct_reply":
      return {
        template: "{{ state.final_answer }}",
        outputField: "final_answer",
        format: "chat",
      };
    case "custom_function":
      return {
        code: "return {}",
        outputField: "custom_output",
      };
  }
}

export function defaultInputs(type: NodeType): Port[] {
  return type === "start" ? [] : [{ id: "in", type: "control", label: "输入" }];
}

export function defaultOutputs(type: NodeType): Port[] {
  if (type === "direct_reply") {
    return [];
  }
  if (type === "condition") {
    return [
      { id: "true", type: "condition", label: "true" },
      { id: "false", type: "condition", label: "false" },
      { id: "fallback", type: "condition", label: "fallback" },
    ];
  }
  return [{ id: "out", type: "control", label: "输出" }];
}
