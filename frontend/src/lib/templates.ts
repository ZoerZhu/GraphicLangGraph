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
    id: "coder_editor",
    name: "Coder Editor Agent",
    description: "读取代码、生成修改计划、提出可审批 patch，并给出验证建议。",
    kind: "agent",
    fields: [
      { name: "code_context", type: "dict", description: "目录、搜索和代码定位结果" },
      { name: "edit_plan", type: "str", description: "修改计划和补丁生成指令" },
      { name: "patch_result", type: "dict", description: "propose_patch 生成的变更集" },
      { name: "final_answer", type: "str", description: "最终说明" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 280, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("scan_code", "tool", "读取与定位代码", 370, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是代码阅读助手。先使用 list_directory、search_code、list_code_symbols、read_file_chunk、extract_code_symbol 等读取工具定位相关文件和符号；不要一次读取大文件。",
        userPrompt: "用户修改需求：{{ state.messages }}\n\n请只收集完成修改所需的最小代码上下文，输出关键文件、符号、行号和风险点。",
        toolIdsJson: "[]",
        toolRegistryJson: "[]",
        maxIterations: 6,
        outputField: "code_context",
      }),
      node("plan_edit", "llm", "生成修改计划", 670, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是资深代码修改规划助手。根据用户需求和代码上下文，输出精确修改方案、目标文件、验证命令和 patch 生成指令。不要输出无关大段代码。",
        userPrompt: "用户需求：{{ state.messages }}\n\n代码上下文：{{ state.code_context }}\n\n请生成修改计划，并说明需要 propose_patch 的文件和替换内容。",
        outputField: "edit_plan",
      }),
      node("propose_patch", "tool", "生成待审批 Patch", 970, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是安全代码编辑 Agent。默认只能调用 propose_patch 生成待审批补丁，不要调用 apply_patch_set、replace_in_file 或 write_file。补丁必须尽量小，并说明验证建议。",
        userPrompt: "用户需求：{{ state.messages }}\n\n修改计划：{{ state.edit_plan }}\n\n请调用 propose_patch 生成待审批变更集；如果信息不足，说明还需要读取哪些文件。",
        toolIdsJson: "[]",
        toolRegistryJson: "[]",
        maxIterations: 4,
        outputField: "patch_result",
      }),
      node("reply_editor", "direct_reply", "回复用户", 1270, 220, {
        template: "已生成修改方案和待审批变更集。\n\n{{ state.patch_result }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_start_scan_code", "start", "out", "scan_code"),
      edge("edge_scan_plan_edit", "scan_code", "out", "plan_edit"),
      edge("edge_plan_propose_patch", "plan_edit", "out", "propose_patch"),
      edge("edge_patch_reply_editor", "propose_patch", "out", "reply_editor"),
    ],
  },
  {
    id: "task_plan_parallel",
    name: "结构化任务并行 Worker",
    description: "把用户目标抽取为 Task Plan JSON，校验后拆分并交给并行 Worker 处理。",
    kind: "agent",
    fields: [
      { name: "task_plan", type: "dict", description: "结构化任务规划" },
      { name: "task_plan_validation", type: "dict", description: "任务规划校验结果" },
      { name: "task_plan_repair", type: "dict", description: "任务规划修复记录" },
      { name: "worker_tasks", type: "list", description: "Task Splitter 标准化任务列表" },
      { name: "worker_results", type: "list", description: "并行 Worker 结果" },
      { name: "final_answer", type: "str", description: "最终回答" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 280, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("extract_task_plan", "json_extractor", "抽取 Task Plan", 380, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        inputMappingsJson: JSON.stringify([{ name: "input", sourceType: "state", source: "messages", valueType: "string" }], null, 2),
        inputText: "{{ state.messages }}",
        instruction: "把用户目标拆成 2-6 个可并行执行的子任务。每个任务至少提供 title 或 goal；如涉及代码，补充 targetFiles 和 suggestedTools。",
        schemaPreset: "task_plan_v1",
        schemaFieldsJson: "[]",
        repairEnabled: true,
        repairInstruction: "修复为 {\"tasks\":[...]}，每个任务至少包含 title 或 goal。",
        outputField: "task_plan",
        validationField: "task_plan_validation",
        repairResultField: "task_plan_repair",
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "valid", type: "condition", label: "valid" },
        { id: "invalid", type: "condition", label: "invalid" },
      ]),
      node("split_tasks", "task_splitter", "标准化任务", 660, 220, {
        inputField: "task_plan",
        outputField: "worker_tasks",
        maxTasks: 6,
        fallbackToSingleTask: false,
      }),
      node("parallel_workers", "parallel_tools", "并行 Worker", 940, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是任务 Worker，只完成分配给你的子任务，并给出简洁结论、证据和风险。",
        tasksField: "worker_tasks",
        toolIdsJson: "[]",
        toolRegistryJson: "[]",
        maxIterationsPerTask: 6,
        maxConcurrentWorkers: 3,
        outputField: "worker_results",
      }),
      node("reply_parallel", "direct_reply", "汇总回复", 1220, 220, {
        template: "{{ state.worker_results }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
      node("reply_invalid_plan", "direct_reply", "规划无效", 660, 420, {
        template: "任务规划 JSON 校验失败：{{ state.task_plan_validation }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_start_extract_task_plan", "start", "out", "extract_task_plan"),
      edge("edge_extract_valid_split", "extract_task_plan", "valid", "split_tasks", "conditional", "valid"),
      edge("edge_extract_invalid_reply", "extract_task_plan", "invalid", "reply_invalid_plan", "conditional", "invalid"),
      edge("edge_split_parallel", "split_tasks", "out", "parallel_workers"),
      edge("edge_parallel_reply", "parallel_workers", "out", "reply_parallel"),
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
      { name: "order_id", type: "str", description: "订单号，可从运行输入中提供" },
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
        routeMode: "keyword",
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
        mockEnabled: true,
        mockResponseJson: "{\n  \"order_id\": \"{{ state.order_id }}\",\n  \"status\": \"已发货\",\n  \"shipping_company\": \"顺丰速运\",\n  \"tracking_no\": \"SF1234567890\",\n  \"estimated_delivery\": \"明天 18:00 前\",\n  \"refundable\": true\n}",
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
        userPrompt: "用户输入：{{ state.messages }}\n\n意图：{{ state.route_key }}\n路由原因：{{ state.route_reason }}\n订单信息：{{ state.order_info }}\n审批结果：{{ state.approval_result }}\n\n请给出最终客服回复。",
        tools: "",
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
