import type { EdgeIR, NodeIR, ProjectIR, StateField } from "../types";

export interface ProjectTemplate {
  id: string;
  name: string;
  description: string;
  kind: "agent" | "agents";
  fields: StateField[];
  nodes: NodeIR[];
  edges: EdgeIR[];
}

export const PROJECT_TEMPLATES: ProjectTemplate[] = [
  {
    id: "knowledge_qa",
    name: "知识库问答 Agent",
    description: "改写问题、检索知识库、生成带上下文的回答。",
    kind: "agent",
    fields: [
      { name: "rewritten_query", type: "str", description: "改写后的检索问题" },
      { name: "retrieved_context", type: "str", description: "检索上下文" },
      { name: "final_answer", type: "str", description: "最终回答" },
    ],
    nodes: [
      node("start", "start", "开始", 120, 260, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("llm_rewrite", "llm", "改写检索问题", 390, 190, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是知识库问答系统的问题改写器，请把用户问题改写为适合检索的短查询。",
        userPrompt: "{{ state.messages }}",
        outputField: "rewritten_query",
      }),
      node("retriever_context", "retriever", "检索知识库", 660, 190, {
        source: "local",
        path: "./knowledge",
        query: "{{ state.rewritten_query }}",
        topK: 4,
        outputField: "retrieved_context",
      }),
      node("llm_answer", "llm", "生成回答", 930, 190, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是严谨的中文知识库问答助手，只基于检索上下文回答；如果上下文不足，请说明缺失信息。",
        userPrompt: "问题：{{ state.rewritten_query }}\n\n上下文：{{ state.retrieved_context }}",
        outputField: "final_answer",
      }),
      node("reply_final", "direct_reply", "回复用户", 1200, 190, {
        template: "{{ state.final_answer }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_start_rewrite", "start", "out", "llm_rewrite"),
      edge("edge_rewrite_retriever", "llm_rewrite", "out", "retriever_context"),
      edge("edge_retriever_answer", "retriever_context", "out", "llm_answer"),
      edge("edge_answer_reply", "llm_answer", "out", "reply_final"),
    ],
  },
  {
    id: "customer_support",
    name: "客服工单 Agent",
    description: "识别订单/退款/其他问题，查询订单、审批退款并组织回复。",
    kind: "agent",
    fields: [
      { name: "route_key", type: "str", description: "意图路由" },
      { name: "route_reason", type: "str", description: "路由原因" },
      { name: "order_info", type: "dict", description: "订单查询结果" },
      { name: "approval_action", type: "str", description: "审批动作" },
      { name: "approval_result", type: "dict", description: "审批结果" },
      { name: "agent_result", type: "str", description: "客服 Agent 输出" },
      { name: "final_answer", type: "str", description: "最终回复" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 330, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("route_intent", "ai_router", "识别问题类型", 360, 300, {
        provider: "openai",
        model: "gpt-4.1-mini",
        instruction: "判断用户问题属于订单、退款还是其他。",
        inputText: "{{ state.messages }}",
        scenarios: "order:订单问题:订单,物流,发货,快递\nrefund:退款问题:退款,退货,赔付,取消\nother:其他问题:",
        routeField: "route_key",
        reasonField: "route_reason",
        fallback: "other",
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "order", type: "condition", label: "订单问题" },
        { id: "refund", type: "condition", label: "退款问题" },
        { id: "other", type: "condition", label: "其他问题" },
      ]),
      node("query_order", "http", "查询订单 API", 650, 180, {
        method: "GET",
        url: "https://api.example.com/orders/{{ state.order_id }}",
        body: "",
        authSecret: "ORDER_API_TOKEN",
        outputField: "order_info",
      }),
      node("refund_approval", "human_approval", "退款人工审批", 650, 390, {
        prompt: "用户请求退款，请人工确认是否批准。",
        actionField: "approval_action",
        outputField: "approval_result",
        defaultAction: "approved",
        fallback: "rejected",
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "approved", type: "condition", label: "通过" },
        { id: "rejected", type: "condition", label: "拒绝" },
        { id: "edit", type: "condition", label: "修改" },
      ]),
      node("support_agent", "agent", "组织客服回复", 940, 300, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是售后客服 Agent，请结合意图、订单信息和审批结果，生成专业、明确、友好的中文回复。",
        tools: "query_order,refund_policy",
        maxIterations: 4,
        outputField: "agent_result",
      }),
      node("reply_support", "direct_reply", "回复用户", 1210, 300, {
        template: "{{ state.agent_result }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_start_route", "start", "out", "route_intent"),
      edge("edge_route_order", "route_intent", "order", "query_order", "conditional", "订单问题"),
      edge("edge_route_refund", "route_intent", "refund", "refund_approval", "conditional", "退款问题"),
      edge("edge_route_other", "route_intent", "other", "support_agent", "conditional", "其他问题"),
      edge("edge_order_agent", "query_order", "out", "support_agent"),
      edge("edge_refund_ok", "refund_approval", "approved", "support_agent", "conditional", "通过"),
      edge("edge_refund_rejected", "refund_approval", "rejected", "support_agent", "conditional", "拒绝"),
      edge("edge_refund_edit", "refund_approval", "edit", "support_agent", "conditional", "修改"),
      edge("edge_agent_reply", "support_agent", "out", "reply_support"),
    ],
  },
];

export function applyTemplateToProject(project: ProjectIR, template: ProjectTemplate): ProjectIR {
  return {
    ...project,
    project: {
      ...project.project,
      name: template.name,
      description: template.description,
      kind: template.kind,
    },
    state: {
      ...project.state,
      fields: template.fields,
    },
    nodes: template.nodes,
    edges: template.edges,
  };
}

function node(
  id: string,
  type: NodeIR["type"],
  label: string,
  x: number,
  y: number,
  config: Record<string, unknown>,
  inputs = [{ id: "in", type: "control", label: "输入" }],
  outputs = [{ id: "out", type: "control", label: "输出" }],
): NodeIR {
  return { id, type, label, position: { x, y }, config, inputs, outputs };
}

function edge(
  id: string,
  source: string,
  sourceHandle: string,
  target: string,
  kind: EdgeIR["kind"] = "normal",
  label?: string,
): EdgeIR {
  return { id, source, sourceHandle, target, targetHandle: "in", kind, label };
}
