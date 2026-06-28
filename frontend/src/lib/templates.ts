import type { EdgeIR, MCPServerConfig, NodeIR, ProjectIR, StateField } from "../types";

export type ProjectTemplateCategory = "knowledge" | "coding" | "workflow" | "data" | "support";
export type ProjectTemplateRunMode = "dry" | "live";
export type ProjectTemplateSceneId =
  | "knowledge_search"
  | "web_research"
  | "workflow_automation"
  | "data_api"
  | "code_work"
  | "support_ops"
  | "agent_collaboration";

export interface ProjectTemplateSceneGroup {
  id: ProjectTemplateSceneId;
  name: string;
  description: string;
}

export interface ProjectTemplate {
  id: string;
  version: string;
  name: string;
  description: string;
  kind: "agent" | "agents";
  category: ProjectTemplateCategory;
  sceneId: ProjectTemplateSceneId;
  useCase: string;
  recommendedFor: string[];
  acceptanceSummary: string;
  recommendedRunMode: ProjectTemplateRunMode;
  requiresModel: boolean;
  requiresNetwork: boolean;
  expectedOutputFields: string[];
  expectedTraceTypes: NodeIR["type"][];
  requiredMcpServers?: MCPServerConfig[];
  requiredRuntimeHosts?: string[];
  requiredEnvVars?: string[];
  setupNotes?: string[];
  sampleInput?: Record<string, unknown>;
  fields: StateField[];
  nodes: NodeIR[];
  edges: EdgeIR[];
}

export const PROJECT_TEMPLATE_SCENES: ProjectTemplateSceneGroup[] = [
  {
    id: "knowledge_search",
    name: "知识检索",
    description: "面向 RAG、文档问答和企业知识库的检索增强流程。",
  },
  {
    id: "web_research",
    name: "联网研究",
    description: "通过 MCP 或网络工具获取外部信息，再汇总成可追踪回答。",
  },
  {
    id: "workflow_automation",
    name: "流程自动化",
    description: "结构化任务、并发执行、分支校验和结果聚合。",
  },
  {
    id: "data_api",
    name: "API 与数据",
    description: "API 调用、JSON 清洗、结构校验和数据回复。",
  },
  {
    id: "code_work",
    name: "代码工作",
    description: "代码读取、修改规划、补丁生成和验证建议。",
  },
  {
    id: "support_ops",
    name: "客服运营",
    description: "意图路由、订单查询、人工审批和客服回复。",
  },
  {
    id: "agent_collaboration",
    name: "多 Agent",
    description: "接入历史 Agent 作为子能力，完成主控编排与协作。",
  },
];

export const EXA_WEBSEARCH_MCP_SERVER: MCPServerConfig = {
  id: "exa_search_mcp",
  name: "Exa Search MCP",
  transport: "http",
  command: "",
  argsJson: "[]",
  envJson: "{}",
  envVarsJson: "[]",
  cwd: "",
  url: "https://mcp.exa.ai/mcp",
  apiKey: "",
  apiKeyEnv: "EXA_API_KEY",
  apiKeyMode: "env",
  apiKeyHeader: "x-api-key",
  apiKeyPrefix: "",
  bearerTokenEnvVar: "",
  httpHeadersJson: "{}",
  envHttpHeadersJson: "{\"x-api-key\":\"EXA_API_KEY\"}",
  enabled: true,
  startupTimeoutSec: 10,
  toolTimeoutSec: 60,
  enabledToolsJson: "[]",
  disabledToolsJson: "[]",
  defaultToolsApprovalMode: "auto",
  sourceType: "template",
  sourcePath: "https://mcp.exa.ai/mcp",
  description: "Exa remote MCP web search server",
};

const TASK_PLAN_SCHEMA_FIELDS_JSON = JSON.stringify(
  [
    { name: "tasks", type: "array", required: true, description: "任务数组" },
  ],
  null,
  2,
);

const FLOW_CONTROL_WORKER_TOOL_IDS = [
  "builtin_list_directory",
  "builtin_search_code",
  "builtin_read_file_chunk",
  "builtin_read_file",
  "builtin_list_code_symbols",
  "builtin_run_whitelisted_command",
];

const FLOW_CONTROL_WORKER_TOOLS = [
  builtinToolSnapshot("builtin_list_directory", "list_directory", "列出运行环境允许目录内的文件和文件夹。"),
  builtinToolSnapshot("builtin_search_code", "search_code", "在运行环境允许目录内按关键词或正则搜索代码文本。"),
  builtinToolSnapshot("builtin_read_file_chunk", "read_file_chunk", "按行号或字符 offset 分片读取文本文件。"),
  builtinToolSnapshot("builtin_read_file", "read_file", "读取运行环境允许目录内的文本文件。"),
  builtinToolSnapshot("builtin_list_code_symbols", "list_code_symbols", "列出代码文件中的函数、类、方法、组件等符号。"),
  builtinToolSnapshot("builtin_run_whitelisted_command", "run_whitelisted_command", "运行运行环境命令白名单允许的验证命令。"),
];

const FLOW_CONTROL_WORKER_SYSTEM_PROMPT = [
  "你是真实项目验收 Worker，只处理 state.current_item 指定的一个子任务。",
  "必须至少调用一次可用工具读取、搜索、分析项目或运行白名单验证命令，不能只复述任务。",
  "从 state.messages 中识别项目路径；如果没有明确路径，使用 . 作为根目录。",
  "优先使用 list_directory 了解目录，再用 search_code/read_file_chunk/list_code_symbols 定位证据。",
  "验收 Workflow 节点时优先搜索精确代码锚点：NodeType.MERGE、_execute_merge_node、reducersJson、DIRECT_REPLY、_execute_live_task_splitter、json_extractor、data-shaping。",
  "如果普通关键词没有命中，必须换用精确锚点继续搜索；不能仅凭第一次搜索失败就判定未实现。",
  "结论必须区分工作流 runtime/codegen 的 Merge 节点与 workspace 配置导入里的同名 merge helper。",
  "只有需要验证构建或测试时才调用 run_whitelisted_command，命令必须属于运行环境白名单。",
  "最终回答用中文，包含：检查项、已执行工具、关键证据、结论、风险或后续建议。",
].join("\n");

const FLOW_CONTROL_WORKER_USER_PROMPT = [
  "原始验收目标：{{ state.messages }}",
  "当前任务索引：{{ state.current_index }}",
  "当前任务 JSON：{{ state.current_item }}",
  "请真实完成当前任务并返回可被 Merge 聚合的简洁验收结果。",
].join("\n");

export const PROJECT_TEMPLATES: ProjectTemplate[] = [
  {
    id: "knowledge_qa",
    version: "1.0.0",
    name: "知识库问答 Agent",
    description: "改写问题、检索知识库、生成带上下文的回答。",
    kind: "agent",
    category: "knowledge",
    sceneId: "knowledge_search",
    useCase: "把用户问题改写成检索查询，读取知识库上下文，再生成有依据的回答。",
    recommendedFor: ["RAG 问答", "文档助手", "内部知识库检索"],
    acceptanceSummary: "运行后应产出 rewritten_query、retrieved_context 和 final_answer，并包含 LLM、Retriever、Reply trace。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: false,
    expectedOutputFields: ["rewritten_query", "retrieved_context", "final_answer"],
    expectedTraceTypes: ["llm", "retriever", "direct_reply"],
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
    version: "1.0.0",
    name: "Coder Editor Agent",
    description: "读取代码、生成修改计划、提出可审批 patch，并给出验证建议。",
    kind: "agent",
    category: "coding",
    sceneId: "code_work",
    useCase: "先读取最小代码上下文，再生成修改计划和待审批补丁。",
    recommendedFor: ["代码审查", "改动规划", "补丁草案"],
    acceptanceSummary: "运行后应产出 code_context、edit_plan、patch_result 和 final_answer，并保留 Tool、LLM trace。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: false,
    expectedOutputFields: ["code_context", "edit_plan", "patch_result", "final_answer"],
    expectedTraceTypes: ["tool", "llm", "direct_reply"],
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
    id: "websearch_exa_mcp",
    version: "1.0.0",
    name: "Exa WebSearch MCP Agent",
    description: "通过 Exa remote MCP 搜索网页，再由 LLM 汇总为带来源意识的回答。",
    kind: "agent",
    category: "knowledge",
    sceneId: "web_research",
    useCase: "用 Exa MCP 搜索外部网页信息，再由 LLM 汇总为中文回答。",
    recommendedFor: ["联网问答", "趋势调研", "资料搜索"],
    acceptanceSummary: "运行后应产出 exa_search_result、search_answer 和 final_answer，并看到 MCP、LLM、Reply trace。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: true,
    expectedOutputFields: ["exa_search_result", "search_answer", "final_answer"],
    expectedTraceTypes: ["mcp_node", "llm", "direct_reply"],
    requiredMcpServers: [EXA_WEBSEARCH_MCP_SERVER],
    requiredRuntimeHosts: ["mcp.exa.ai"],
    requiredEnvVars: ["EXA_API_KEY"],
    setupNotes: ["需要配置 Exa MCP API Key。", "运行环境需允许访问 mcp.exa.ai。"],
    sampleInput: {
      messages: "请搜索 2026 年 AI Agent 工作流编排工具的最新趋势，并用中文总结三点。",
    },
    fields: [
      { name: "exa_search_result", type: "dict", description: "Exa MCP 搜索结果" },
      { name: "search_answer", type: "str", description: "LLM 汇总回答" },
      { name: "final_answer", type: "str", description: "最终回复" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 260, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("exa_search_mcp", "mcp_node", "Exa Search MCP", 380, 220, {
        serverId: "exa_search_mcp",
        serverName: "Exa Search MCP",
        transport: "http",
        command: "",
        url: "https://mcp.exa.ai/mcp",
        mcpServerSnapshotJson: JSON.stringify([EXA_WEBSEARCH_MCP_SERVER], null, 2),
        mcpToolsJson: "[]",
        toolName: "",
        toolSelectionMode: "model",
        toolSelectionInstruction: "搜索网页时优先 web_search_exa；如果输入包含 URL 或要求抓取网页内容，使用 web_fetch_exa。",
        toolSelectionModelProvider: "openai",
        toolSelectionModel: "gpt-4.1-mini",
        toolSelectionModelConfigId: "",
        fallbackToHeuristic: true,
        toolArgsJson: "{\"query\":\"{{ state.messages }}\"}",
        toolInputSchemaJson: "{}",
        outputField: "exa_search_result",
      }),
      node("summarize_search", "llm", "汇总搜索结果", 680, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是联网搜索总结助手。请基于 MCP 搜索结果回答用户问题；如果结果不足，说明还需要进一步搜索。",
        userPrompt: "用户问题：{{ state.messages }}\n\n搜索结果：{{ state.exa_search_result }}\n\n请用中文总结，必要时列出来源线索。",
        outputField: "search_answer",
      }),
      node("reply_websearch", "direct_reply", "回复用户", 980, 220, {
        template: "{{ state.search_answer }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_web_start_mcp", "start", "out", "exa_search_mcp"),
      edge("edge_web_mcp_summarize", "exa_search_mcp", "out", "summarize_search"),
      edge("edge_web_summarize_reply", "summarize_search", "out", "reply_websearch"),
    ],
  },
  {
    id: "multi_agent_orchestration",
    version: "1.0.0",
    name: "多 Agent 协作编排",
    description: "主 Agent 可接入历史 Agent 作为工具调用，再用 Template 归一化协作结果并回复。",
    kind: "agent",
    category: "workflow",
    sceneId: "agent_collaboration",
    useCase: "把当前项目已完成的 Agent 接入为子 Agent 工具，由主 Agent 协调完成任务。",
    recommendedFor: ["子 Agent 调用", "专家协作", "历史 Agent 复用"],
    acceptanceSummary: "运行后应产出 orchestration_result、collaboration_summary 和 final_answer，并包含 Agent、Template trace。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: false,
    expectedOutputFields: ["orchestration_result", "collaboration_summary", "final_answer"],
    expectedTraceTypes: ["agent", "template", "direct_reply"],
    sampleInput: {
      messages: "请协调代码阅读 Agent 和测试建议 Agent，分析当前项目下一步应该优先补齐哪些运行验收能力。",
    },
    fields: [
      { name: "orchestration_result", type: "dict", description: "主 Agent 或子 Agent 协作结果" },
      { name: "collaboration_summary", type: "str", description: "协作结果归一化摘要" },
      { name: "final_answer", type: "str", description: "最终回复" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 260, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("orchestrator_agent", "agent", "主 Agent 编排", 390, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: "你是主控 Agent。若当前节点已接入历史 Agent，请把它们当作专长工具调用；若未接入，则直接基于用户输入给出协作计划和可执行结论。",
        userPrompt: "用户任务：{{ state.messages }}\n\n请协调可用子 Agent，输出：1. 子任务分工 2. 关键发现 3. 下一步建议。",
        tools: "",
        agentIdsJson: "[]",
        agentRegistryJson: "[]",
        maxIterations: 4,
        outputField: "orchestration_result",
      }),
      node("shape_collaboration", "template", "归一化协作摘要", 690, 220, {
        inputMappingsJson: JSON.stringify([{ name: "result", sourceType: "state", source: "orchestration_result", valueType: "auto" }], null, 2),
        template: "多 Agent 协作结果：\n{{ state.orchestration_result }}",
        outputType: "text",
        outputField: "collaboration_summary",
      }),
      node("reply_collaboration", "direct_reply", "回复用户", 990, 220, {
        template: "{{ state.collaboration_summary }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_multi_start_agent", "start", "out", "orchestrator_agent"),
      edge("edge_multi_agent_shape", "orchestrator_agent", "out", "shape_collaboration"),
      edge("edge_multi_shape_reply", "shape_collaboration", "out", "reply_collaboration"),
    ],
  },
  {
    id: "task_plan_parallel",
    version: "1.0.0",
    name: "结构化任务并行 Worker",
    description: "把用户目标抽取为 Task Plan JSON，校验后拆分并交给并行 Worker 处理。",
    kind: "agent",
    category: "workflow",
    sceneId: "workflow_automation",
    useCase: "让模型先产出结构化任务 JSON，再拆分给多个 Worker 并发处理。",
    recommendedFor: ["任务拆分", "并行 Worker", "结构化计划验收"],
    acceptanceSummary: "运行后应产出 task_plan、task_plan_validation、worker_tasks、worker_results 和 final_answer。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: false,
    expectedOutputFields: ["task_plan", "task_plan_validation", "worker_tasks", "worker_results", "final_answer"],
    expectedTraceTypes: ["json_extractor", "task_splitter", "parallel_tools", "direct_reply"],
    sampleInput: {
      messages: "请把这次代码审查拆成三个并行任务：检查后端运行逻辑、检查前端配置体验、汇总风险和验证建议。",
    },
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
        schemaFieldsJson: TASK_PLAN_SCHEMA_FIELDS_JSON,
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
    id: "flow_control_task_processing",
    version: "1.0.0",
    name: "并发任务处理 Flow Control v2",
    description: "校验 Task Plan，并发 ForEach 处理每个任务，收集单项错误，Merge 聚合结果后直接回复。",
    kind: "agent",
    category: "workflow",
    sceneId: "workflow_automation",
    useCase: "用 ForEach/Merge 表达并发任务处理、错误收集和结果聚合。",
    recommendedFor: ["并发处理", "Flow Control", "回放排障"],
    acceptanceSummary: "运行后应产出 task_plan、task_plan_validation、worker_tasks、merged_results 和 final_answer，并能回放 ForEach/Merge trace。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: false,
    expectedOutputFields: ["task_plan", "task_plan_validation", "worker_tasks", "merged_results", "final_answer"],
    expectedTraceTypes: ["json_extractor", "json_validator", "task_splitter", "for_each", "agent", "merge", "direct_reply"],
    sampleInput: {
      messages: "请把这次验收拆成三个任务：检查数据输入、处理每个任务、汇总结果。",
    },
    fields: [
      { name: "task_plan", type: "dict", description: "结构化任务规划" },
      { name: "extract_validation", type: "dict", description: "抽取阶段校验结果" },
      { name: "task_plan_validation", type: "dict", description: "任务规划校验结果" },
      { name: "worker_tasks", type: "list", description: "Task Splitter 标准化任务列表" },
      { name: "current_item", type: "dict", description: "ForEach 当前任务" },
      { name: "current_index", type: "int", description: "ForEach 当前索引" },
      { name: "item_result", type: "str", description: "单个任务处理结果" },
      { name: "merged_results", type: "list", description: "所有任务处理结果" },
      { name: "merge_result", type: "dict", description: "Merge 摘要" },
      { name: "final_answer", type: "str", description: "最终回复" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 300, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("extract_task_plan_fc", "json_extractor", "抽取 Task Plan", 360, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        inputMappingsJson: JSON.stringify([{ name: "input", sourceType: "state", source: "messages", valueType: "string" }], null, 2),
        inputText: "{{ state.messages }}",
        instruction: "把用户目标拆成 2-6 个顺序可处理的子任务。每个任务至少提供 title 或 goal；如涉及代码，补充 targetFiles 和 suggestedTools。",
        schemaPreset: "task_plan_v1",
        schemaFieldsJson: TASK_PLAN_SCHEMA_FIELDS_JSON,
        repairEnabled: true,
        repairInstruction: "修复为 {\"tasks\":[...]}，每个任务至少包含 title 或 goal。",
        outputField: "task_plan",
        validationField: "extract_validation",
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "valid", type: "condition", label: "valid" },
        { id: "invalid", type: "condition", label: "invalid" },
      ]),
      node("validate_task_plan_fc", "json_validator", "校验 Task Plan", 620, 220, {
        inputField: "task_plan",
        outputField: "task_plan",
        validationField: "task_plan_validation",
        schemaPreset: "task_plan_v1",
        schemaFieldsJson: TASK_PLAN_SCHEMA_FIELDS_JSON,
        repairEnabled: false,
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "valid", type: "condition", label: "valid" },
        { id: "invalid", type: "condition", label: "invalid" },
      ]),
      node("split_tasks_fc", "task_splitter", "标准化任务", 880, 220, {
        inputField: "task_plan",
        outputField: "worker_tasks",
        maxTasks: 6,
        fallbackToSingleTask: false,
      }),
      node("foreach_tasks_fc", "for_each", "并发处理任务", 1140, 220, {
        itemsField: "worker_tasks",
        itemField: "current_item",
        indexField: "current_index",
        maxItems: 20,
        executionMode: "parallel",
        maxConcurrency: 3,
        preserveOrder: true,
        itemFailurePolicy: "collect_errors",
        resultField: "foreach_result",
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "item", type: "control", label: "item" },
        { id: "error", type: "control", label: "error" },
      ]),
      node("worker_placeholder_fc", "agent", "真实 Agent Worker", 1400, 220, {
        provider: "openai",
        model: "gpt-4.1-mini",
        systemPrompt: FLOW_CONTROL_WORKER_SYSTEM_PROMPT,
        userPrompt: FLOW_CONTROL_WORKER_USER_PROMPT,
        toolIdsJson: JSON.stringify(FLOW_CONTROL_WORKER_TOOL_IDS),
        toolRegistryJson: JSON.stringify(FLOW_CONTROL_WORKER_TOOLS, null, 2),
        maxIterations: 8,
        outputField: "item_result",
        retryPolicyJson: JSON.stringify({ enabled: true, maxRetries: 1, backoffMs: 100, retryOnErrorTypes: [] }, null, 2),
        errorPolicy: "route_error",
        nodeTimeoutSec: 0,
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "out", type: "control", label: "输出" },
        { id: "error", type: "control", label: "error" },
      ]),
      node("item_error_handler_fc", "error_handler", "单项错误处理", 1400, 420, {
        errorField: "last_error",
        template: "任务 {{ state.current_index }} 处理失败：{{ state.last_error }}",
        outputField: "item_result",
      }),
      node("merge_results_fc", "merge", "聚合任务结果", 1660, 220, {
        mergeMode: "for_each",
        reducersJson: JSON.stringify([{ target: "merged_results", source: "item_result", reducer: "append" }], null, 2),
        resultField: "merge_result",
      }),
      node("reply_flow_control_fc", "direct_reply", "汇总回复", 1920, 220, {
        template: "任务处理结果：\n{{ state.merged_results }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
      node("reply_invalid_plan_fc", "direct_reply", "规划无效", 880, 440, {
        template: "任务规划 JSON 校验失败：{{ state.extract_validation }} {{ state.task_plan_validation }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_fc_start_extract", "start", "out", "extract_task_plan_fc"),
      edge("edge_fc_extract_valid_validate", "extract_task_plan_fc", "valid", "validate_task_plan_fc", "conditional", "valid"),
      edge("edge_fc_extract_invalid_reply", "extract_task_plan_fc", "invalid", "reply_invalid_plan_fc", "conditional", "invalid"),
      edge("edge_fc_validate_valid_split", "validate_task_plan_fc", "valid", "split_tasks_fc", "conditional", "valid"),
      edge("edge_fc_validate_invalid_reply", "validate_task_plan_fc", "invalid", "reply_invalid_plan_fc", "conditional", "invalid"),
      edge("edge_fc_split_foreach", "split_tasks_fc", "out", "foreach_tasks_fc"),
      edge("edge_fc_foreach_item_worker", "foreach_tasks_fc", "item", "worker_placeholder_fc"),
      edge("edge_fc_worker_merge", "worker_placeholder_fc", "out", "merge_results_fc"),
      edge("edge_fc_worker_error_handler", "worker_placeholder_fc", "error", "item_error_handler_fc", "error", "error"),
      edge("edge_fc_error_handler_merge", "item_error_handler_fc", "out", "merge_results_fc"),
      edge("edge_fc_merge_reply", "merge_results_fc", "out", "reply_flow_control_fc"),
    ],
  },
  {
    id: "api_json_cleanup",
    version: "1.0.0",
    name: "API JSON 清洗与校验",
    description: "读取订单 API 返回，用 Template 统一字段结构，再用 JSON Validator 校验并回复。",
    kind: "agent",
    category: "data",
    sceneId: "data_api",
    useCase: "使用 HTTP mock 模拟订单 API，清洗字段并用 JSON Validator 验证结构。",
    recommendedFor: ["API 数据清洗", "JSON 校验", "订单查询 mock"],
    acceptanceSummary: "运行后应产出 order_info、clean_order、order_validation 和 final_answer，且 order_validation.valid 为 true。",
    recommendedRunMode: "live",
    requiresModel: false,
    requiresNetwork: false,
    setupNotes: ["默认启用 HTTP mock，无需真实网络和模型。"],
    expectedOutputFields: ["order_info", "clean_order", "order_validation", "final_answer"],
    expectedTraceTypes: ["http", "template", "json_validator", "direct_reply"],
    sampleInput: {
      messages: "查询订单 O-10086 的配送状态",
      order_id: "O-10086",
    },
    fields: [
      { name: "order_id", type: "str", description: "订单号" },
      { name: "order_info", type: "dict", description: "原始订单 API 返回" },
      { name: "clean_order", type: "dict", description: "清洗后的订单结构" },
      { name: "order_validation", type: "dict", description: "订单结构校验结果" },
      { name: "final_answer", type: "str", description: "最终回复" },
    ],
    nodes: [
      node("start", "start", "开始", 100, 260, { inputMode: "chat" }, [], [{ id: "out", type: "control", label: "输出" }]),
      node("fetch_order", "http", "查询订单 API", 370, 220, {
        method: "GET",
        url: "https://api.example.com/orders/{{ state.order_id }}",
        body: "",
        authSecret: "ORDER_API_TOKEN",
        mockEnabled: true,
        mockResponseJson: "{\n  \"order_id\": \"{{ state.order_id }}\",\n  \"status\": \"已发货\",\n  \"shipping_company\": \"顺丰速运\",\n  \"tracking_no\": \"SF1234567890\",\n  \"estimated_delivery\": \"明天 18:00 前\",\n  \"refundable\": true\n}",
        outputField: "order_info",
      }),
      node("shape_order", "template", "统一订单结构", 640, 220, {
        inputMappingsJson: JSON.stringify([{ name: "order", sourceType: "state", source: "order_info", valueType: "json" }], null, 2),
        template: "{\n  \"orderId\": \"{{ state.order_info.order_id }}\",\n  \"status\": \"{{ state.order_info.status }}\",\n  \"shippingCompany\": \"{{ state.order_info.shipping_company }}\",\n  \"trackingNo\": \"{{ state.order_info.tracking_no }}\",\n  \"estimatedDelivery\": \"{{ state.order_info.estimated_delivery }}\",\n  \"refundPolicy\": \"{{ state.order_info.refundable }}\"\n}",
        outputType: "json",
        outputField: "clean_order",
      }),
      node("validate_order", "json_validator", "校验订单结构", 910, 220, {
        inputField: "clean_order",
        outputField: "clean_order",
        validationField: "order_validation",
        schemaFieldsJson: JSON.stringify(
          [
            { name: "orderId", type: "string", required: true, description: "订单号" },
            { name: "status", type: "string", required: true, description: "订单状态" },
            { name: "shippingCompany", type: "string", required: true, description: "物流公司" },
            { name: "trackingNo", type: "string", required: true, description: "物流单号" },
            { name: "estimatedDelivery", type: "string", required: false, description: "预计送达" },
            { name: "refundPolicy", type: "string", required: false, description: "退款可用性" },
          ],
          null,
          2,
        ),
        repairEnabled: false,
      }, [{ id: "in", type: "control", label: "输入" }], [
        { id: "valid", type: "condition", label: "valid" },
        { id: "invalid", type: "condition", label: "invalid" },
      ]),
      node("reply_order_valid", "direct_reply", "订单回复", 1180, 180, {
        template: "订单 {{ state.clean_order.orderId }} 当前状态：{{ state.clean_order.status }}。\n物流：{{ state.clean_order.shippingCompany }} {{ state.clean_order.trackingNo }}。\n预计送达：{{ state.clean_order.estimatedDelivery }}。",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
      node("reply_order_invalid", "direct_reply", "数据异常回复", 1180, 360, {
        template: "订单数据校验失败：{{ state.order_validation }}",
        outputField: "final_answer",
        format: "chat",
      }, [{ id: "in", type: "control", label: "输入" }], []),
    ],
    edges: [
      edge("edge_api_start_fetch", "start", "out", "fetch_order"),
      edge("edge_api_fetch_shape", "fetch_order", "out", "shape_order"),
      edge("edge_api_shape_validate", "shape_order", "out", "validate_order"),
      edge("edge_api_valid_reply", "validate_order", "valid", "reply_order_valid", "conditional", "valid"),
      edge("edge_api_invalid_reply", "validate_order", "invalid", "reply_order_invalid", "conditional", "invalid"),
    ],
  },
  {
    id: "customer_support",
    version: "1.0.0",
    name: "客服工单 Agent",
    description: "识别订单/退款/其他问题，查询订单、审批退款并组织回复。",
    kind: "agent",
    category: "support",
    sceneId: "support_ops",
    useCase: "把售后问题路由到订单查询、退款审批或通用客服回复。",
    recommendedFor: ["售后客服", "人工审批", "订单/退款工单"],
    acceptanceSummary: "运行后应产出 route_key、route_reason、approval_result 或 order_info，并生成 final_answer。",
    recommendedRunMode: "live",
    requiresModel: true,
    requiresNetwork: false,
    expectedOutputFields: ["route_key", "route_reason"],
    expectedTraceTypes: ["ai_router"],
    sampleInput: {
      messages: "我要申请退款，订单号是 A20260614001，原因是商品不符合预期。",
      order_id: "A20260614001",
    },
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
      templateId: template.id,
      templateVersion: template.version,
    },
    state: {
      ...project.state,
      fields: template.fields,
    },
    nodes: template.nodes,
    edges: template.edges,
  };
}

export function getProjectTemplate(templateId?: string | null): ProjectTemplate | null {
  if (!templateId) return null;
  return PROJECT_TEMPLATES.find((template) => template.id === templateId) ?? null;
}

export function getProjectTemplateForProject(project?: ProjectIR | null): ProjectTemplate | null {
  return getProjectTemplate(project?.project.templateId);
}

export function getProjectTemplateScene(template: ProjectTemplate): ProjectTemplateSceneGroup {
  return PROJECT_TEMPLATE_SCENES.find((scene) => scene.id === template.sceneId) ?? PROJECT_TEMPLATE_SCENES[0];
}

export function getProjectTemplateDependencyLabels(template: ProjectTemplate): string[] {
  return [
    template.requiresModel ? "需要模型" : "无需模型",
    template.requiresNetwork ? "需要网络" : "本地/mock",
    template.recommendedRunMode === "live" ? "推荐真实运行" : "推荐 dry-run",
    ...(template.requiredMcpServers?.length ? [`${template.requiredMcpServers.length} MCP`] : []),
    ...(template.requiredRuntimeHosts?.length ? [`Host: ${template.requiredRuntimeHosts.join(", ")}`] : []),
    ...(template.requiredEnvVars?.length ? [`Env: ${template.requiredEnvVars.join(", ")}`] : []),
  ];
}

export function pickAssistantTemplateId(prompt: string): string {
  const normalized = prompt.trim();
  if (/exa|websearch|web search|联网|搜索网页|网页搜索|网页|mcp/i.test(normalized)) return "websearch_exa_mcp";
  if (/多.?agent|子.?agent|协作|编排|handoff|agent tool|历史 Agent/i.test(normalized)) return "multi_agent_orchestration";
  if (/api|json|清洗|校验|订单接口|订单 API/i.test(normalized)) return "api_json_cleanup";
  if (/并发|foreach|for each|任务处理|task plan|结构化任务|错误兜底|merge|worker/i.test(normalized)) return "flow_control_task_processing";
  if (/客服|售后|订单|退款/.test(normalized)) return "customer_support";
  if (/知识库|问答|文档|rag|检索/i.test(normalized)) return "knowledge_qa";
  return "knowledge_qa";
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

function builtinToolSnapshot(id: string, name: string, description: string) {
  return {
    id,
    name,
    description,
    source: "builtin",
    schemaJson: "{}",
  };
}
