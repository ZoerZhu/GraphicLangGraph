import {
  Braces,
  Bot,
  BrainCircuit,
  Database,
  GitBranch,
  GitMerge,
  Globe,
  type LucideIcon,
  MessageSquareReply,
  Plug,
  Play,
  Repeat,
  Route,
  Sparkles,
  TriangleAlert,
  UserCheck,
  Wrench
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
  { type: "agent", title: "Agent", description: "可用工具的推理节点", icon: BrainCircuit },
  { type: "tool", title: "Tools", description: "Agent 自主选择并调用工具", icon: Wrench },
  { type: "task_splitter", title: "Task Splitter", description: "解析规划并生成任务列表", icon: Route },
  { type: "parallel_tools", title: "Parallel Tools", description: "并行启动多个工具 Worker", icon: Wrench },
  { type: "variable_assign", title: "Variable Assign", description: "写入、追加、合并或清空 state", icon: Braces },
  { type: "template", title: "Template", description: "渲染文本或 JSON 到 state", icon: Braces },
  { type: "json_extractor", title: "JSON Extractor", description: "按 Schema 抽取结构化 JSON", icon: Braces },
  { type: "json_validator", title: "JSON Validator", description: "校验 JSON 并输出分支", icon: GitBranch },
  { type: "for_each", title: "ForEach", description: "顺序迭代数组并执行子链路", icon: Repeat },
  { type: "merge", title: "Merge", description: "按 Reducer 聚合迭代结果", icon: GitMerge },
  { type: "error_handler", title: "Error Handler", description: "处理 error 分支并格式化错误", icon: TriangleAlert },
  { type: "retriever", title: "Retriever", description: "检索知识库上下文", icon: Database },
  { type: "condition", title: "Condition", description: "规则分支路由", icon: GitBranch },
  { type: "ai_router", title: "AI Router", description: "按意图进行智能路由", icon: Route },
  { type: "human_approval", title: "Human Approval", description: "人工审批与确认", icon: UserCheck },
  { type: "http", title: "HTTP", description: "请求外部接口", icon: Globe },
  { type: "direct_reply", title: "Direct Reply", description: "返回最终回复", icon: MessageSquareReply },
  { type: "custom_function", title: "Custom Function", description: "导出 Python 函数", icon: Braces },
  { type: "skill_node", title: "Skill Node", description: "读取已配置 Skill", icon: Plug },
  { type: "mcp_node", title: "MCP Node", description: "调用已配置 MCP Server", icon: Plug },
  { type: "agent_ref", title: "Agent Ref", description: "引用已实现 Agent 通信", icon: Bot }
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
    case "agent":
      return {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是一个可靠的业务 Agent，请基于上下文完成任务。",
        userPrompt: "",
        tools: "",
        skillIdsJson: "[]",
        agentIdsJson: "[]",
        agentRegistryJson: "[]",
        mcpServerIdsJson: "[]",
        mcpServerRegistryJson: "[]",
        maxIterations: 4,
        outputField: "agent_result",
      };
    case "tool":
      return {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是一个可以根据任务自主选择工具的 Agent。",
        userPrompt: "{{ state.messages }}",
        toolIdsJson: "[]",
        toolRegistryJson: "[]",
        maxIterations: 4,
        outputField: "tools_result",
      };
    case "task_splitter":
      return {
        inputField: "task_plan",
        outputField: "worker_tasks",
        maxTasks: 5,
        fallbackToSingleTask: true,
      };
    case "parallel_tools":
      return {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是代码阅读 Worker，只完成分配给你的子任务。",
        tasksField: "worker_tasks",
        toolIdsJson: "[]",
        toolRegistryJson: "[]",
        maxIterationsPerTask: 6,
        maxConcurrentWorkers: 3,
        storeToolCalls: false,
        outputField: "worker_results",
      };
    case "parallel_worker":
      return {
        parentNodeId: "",
        workerIndex: 1,
      };
    case "variable_assign":
      return {
        inputMappingsJson: "[]",
        assignmentsJson: JSON.stringify(
          [
            {
              target: "assigned_value",
              operation: "overwrite",
              sourceType: "template",
              source: "{{ state.messages }}",
              valueType: "string",
            },
          ],
          null,
          2,
        ),
        resultField: "assignment_result",
      };
    case "template":
      return {
        inputMappingsJson: "[]",
        template: "{{ state.messages }}",
        outputType: "text",
        outputField: "template_result",
      };
    case "json_extractor":
      return {
        provider: "openai",
        model: "gpt-4.1-mini",
        inputMappingsJson: JSON.stringify([{ name: "input", sourceType: "state", source: "messages", valueType: "string" }], null, 2),
        inputText: "{{ state.messages }}",
        instruction: "抽取可供后续节点消费的结构化 JSON。",
        schemaFieldsJson: JSON.stringify(
          [
            { name: "tasks", type: "array", required: true, description: "任务数组" },
          ],
          null,
          2,
        ),
        outputField: "extracted_json",
        validationField: "validation_result",
      };
    case "json_validator":
      return {
        inputField: "extracted_json",
        schemaFieldsJson: JSON.stringify(
          [
            { name: "tasks", type: "array", required: true, description: "任务数组" },
          ],
          null,
          2,
        ),
        outputField: "validated_json",
        validationField: "validation_result",
      };
    case "for_each":
      return {
        itemsField: "worker_tasks",
        itemField: "current_item",
        indexField: "current_index",
        maxItems: 50,
        resultField: "",
      };
    case "merge":
      return {
        reducersJson: JSON.stringify(
          [
            { target: "merged_results", source: "item_result", reducer: "append" },
          ],
          null,
          2,
        ),
        resultField: "merge_result",
      };
    case "error_handler":
      return {
        errorField: "last_error",
        template: "流程执行失败：{{ state.last_error }}",
        outputField: "error_result",
      };
    case "retriever":
      return {
        source: "local",
        path: "./knowledge",
        query: "{{ state.messages }}",
        topK: 4,
        outputField: "retrieved_context",
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
    case "ai_router":
      return {
        provider: "openai",
        model: "gpt-4.1-mini",
        routeMode: "keyword",
        instruction: "判断用户需求属于哪个场景，只输出路由 key。",
        inputText: "{{ state.messages }}",
        scenarios: "order:订单问题:订单,物流,发货\nrefund:退款问题:退款,退货,赔付\nother:其他问题:",
        routeField: "route_key",
        reasonField: "route_reason",
        fallback: "other",
      };
    case "human_approval":
      return {
        prompt: "请审批本次操作是否可以继续。",
        actionField: "approval_action",
        outputField: "approval_result",
        defaultAction: "approved",
        fallback: "rejected",
      };
    case "http":
      return {
        method: "GET",
        url: "https://api.example.com/items/{{ state.item_id }}",
        body: "",
        authSecret: "",
        mockEnabled: false,
        mockResponseJson: "{\n  \"status\": \"ok\"\n}",
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
    case "skill_node":
      return {
        skillId: "",
        skillName: "未选择 Skill",
        skillContent: "",
        sourcePath: "",
        filePath: "",
        outputField: "skill_result",
      };
    case "mcp_node":
      return {
        serverId: "",
        serverName: "未选择 MCP",
        mcpServerSnapshotJson: "[]",
        mcpToolsJson: "[]",
        toolName: "",
        toolSelectionMode: "model",
        toolSelectionInstruction: "",
        toolSelectionModelProvider: "openai",
        toolSelectionModel: "gpt-4.1-mini",
        toolSelectionModelConfigId: "",
        toolSelectionModelConfigName: "",
        fallbackToHeuristic: false,
        toolArgsJson: "{}",
        toolInputSchemaJson: "{}",
        outputField: "mcp_result",
      };
    case "agent_ref":
      return {
        agentProjectId: "",
        agentName: "未选择 Agent",
        protocol: "handoff",
        instruction: "",
        outputField: "agent_ref_result",
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
  if (type === "ai_router") {
    return [
      { id: "order", type: "condition", label: "订单问题" },
      { id: "refund", type: "condition", label: "退款问题" },
      { id: "other", type: "condition", label: "其他问题" },
    ];
  }
  if (type === "human_approval") {
    return [
      { id: "approved", type: "condition", label: "通过" },
      { id: "rejected", type: "condition", label: "拒绝" },
      { id: "edit", type: "condition", label: "修改" },
    ];
  }
  if (type === "json_extractor" || type === "json_validator") {
    return [
      { id: "valid", type: "condition", label: "valid" },
      { id: "invalid", type: "condition", label: "invalid" },
    ];
  }
  if (type === "for_each") {
    return [
      { id: "item", type: "control", label: "item" },
      { id: "error", type: "error", label: "error" },
    ];
  }
  if (type === "error_handler") {
    return [{ id: "out", type: "control", label: "恢复" }];
  }
  if (type === "parallel_tools") {
    return [{ id: "out", type: "control", label: "汇总" }];
  }
  if (type === "parallel_worker") {
    return [{ id: "out", type: "control", label: "结果" }];
  }
  return [{ id: "out", type: "control", label: "输出" }];
}
