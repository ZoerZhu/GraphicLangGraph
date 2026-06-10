# 中文可视化 LangGraph Agent 生成器计划书

日期：2026-06-09

## 1. 项目目标

打造一款面向中文用户的可视化交互式 LangGraph Agent 生成工具。用户可以通过拖拽节点、填写中文表单、与项目内置搭建助手对话，完成 Agent 设计、调试、验证和导出。最终产物必须是可移植的 LangGraph 工程文件或 ZIP 包，可以放入其他 Python 项目、LangSmith Deployment、私有服务器或容器环境中运行。

核心目标：

- 降低 LangGraph Agent 搭建门槛，避免用户从 `StateGraph`、状态 schema、边、条件路由、工具循环、记忆和部署配置开始手写。
- 保留 LangGraph 的可控性，导出的是清晰源码，不只是平台私有 JSON。
- 支持中文交互，内置 Agent 可以根据自然语言需求自动生成流程草图、补全节点配置、修复错误并生成导出包。
- 兼顾普通业务用户的简单路径和开发者的深度可编辑性。

非目标：

- 不做一个通用 RPA/n8n 替代品。
- 不把所有 LangChain/LangGraph 底层能力一次性暴露给用户。
- 不依赖某个 SaaS 才能运行导出的 Agent。
- 不直接复制 Flowise、Langflow、LangSmith Fleet 的私有实现。

## 2. 现有工具调研与可借鉴点

### 2.1 LangSmith Fleet

LangSmith Fleet 是 LangChain 官方的 no-code agent builder，原 Agent Builder 已更名为 Fleet。它的交互方式更像“围绕一个主 Agent 配置能力”，而不是任意拖拽底层图。官方说明 Fleet 支持模板、自然语言创建、工具集成、channels、schedules、skills、sub-agents、人类审批、memory 和下载 ZIP。

从截图和官方文档可以抽象出 Fleet 的编辑模型：

- 中央节点：Agent。
- Agent 内部配置：名称、描述、instructions/system prompt、模型、身份、memory。
- 左侧触发节点：Schedules、Channels。
- 右侧能力节点：Toolbox/MCP、Sub-agents、Skills。
- 顶部动作：设置身份、分享、设置、上传/下载、创建 Agent。
- 交互倾向：业务用户先配置“这个 Agent 是谁、什么时候触发、能用什么工具、有没有子 Agent、有没有技能”，而不是先接复杂图边。

可借鉴点：

- 面向非技术用户的“Agent 中心画布”。
- Create with AI：用自然语言描述目标，让系统生成初始配置。
- 模板优先：Email assistant、daily brief、social monitor 等。
- 人类审批是工具级配置，不一定需要用户理解 interrupt 机制。
- Skills 作为可复用能力文件，避免把所有细节塞进 system prompt。
- 支持下载 ZIP，这与本项目“导出可移植工程”的目标一致。

局限：

- 不是通用 LangGraph 图编辑器。
- 用户不能自由构造复杂 LangGraph state machine。
- 导出物偏 Fleet/Deep Agents 配置，不等于通用源码生成器。
- 深度图级控制能力有限。

### 2.2 Flowise Agentflow V2

Flowise Agentflow V2 是最接近“拖拽节点编排 Agent 流程”的参考。官方文档描述了 V2 的核心：每个节点是独立执行单元，画布连线显式定义工作流路径，节点之间可以通过前置节点输出或 `$flow.state` 共享数据，执行系统尊重节点依赖和队列，支持条件分支、循环、human-in-the-loop、共享状态和 MCP 工具。

Flowise Agentflow V2 的 14 类节点非常适合作为本项目 MVP 节点目录的基础：

| Flowise 节点 | 作用 | 对本项目的启发 |
| --- | --- | --- |
| Start | 入口，接收 chat/form 输入，初始化 Flow State | 对应 LangGraph `START`，同时生成输入 schema 和初始 state |
| LLM | 调用模型，支持 messages、memory、结构化 JSON、更新 state | 对应普通 LangGraph 节点函数 |
| Agent | 自主推理，可用 tools、knowledge、memory | 对应 `create_agent` 或自定义 `StateGraph + ToolNode` |
| Tool | 确定性执行某个工具 | 对应 LangChain `@tool` 或 `ToolNode` 包装 |
| Retriever | 查询 Document Store | 对应 RAG/retriever 节点或 retriever tool |
| HTTP | 请求外部 API | 对应 HTTP 工具或普通执行节点 |
| Condition | 规则分支 | 对应 `add_conditional_edges` |
| Condition Agent | LLM 意图路由 | 对应 AI router 节点 + 条件边 |
| Iteration | 对数组执行子流程 | 对应循环/批处理子图 |
| Loop | 回跳到之前节点，带最大次数 | 对应带计数器的条件边或 Command |
| Human Input | 暂停等待用户输入/审批 | 对应 LangGraph interrupt + checkpointer |
| Direct Reply | 给用户最终回复并结束路径 | 对应终止节点 + `END` |
| Custom Function | 执行自定义 JS | 本项目建议优先 Python，受控沙箱执行 |
| Execute Flow | 调用另一个 flow | 对应 subgraph 或子 Agent |

可借鉴点：

- 节点目录明确，用户认知成本低。
- `$flow.state` 类似 LangGraph state，适合在 UI 中做“变量中心”。
- `{{ variable }}` 变量引用体验非常适合低代码表单。
- 条件分支和 AI 分支都应支持。
- Human Input 节点是 Agent 产品必须品。

需要调整的点：

- Flowise V2 当前重点是 Flowise 自身运行时，不是直接导出 LangGraph 源码。
- 本项目应以 LangGraph 为编译目标，而不是把 Flowise JSON 当最终运行格式。
- Custom Function 不能开放任意服务器执行，必须有沙箱和权限边界。

### 2.3 Langflow

Langflow 是成熟的可视化 LLM/Agent flow builder。它的优势在于组件体系和编辑器体验：从 Core components 或 Bundles 拖入组件，选中组件后在右侧 inspection panel 配置参数，组件具有输入、输出、参数、controls 和底层 Python code，可导出 JSON，也可通过 API 运行 flow。

可借鉴点：

- “组件库 + 画布 + 右侧检查器”的通用编辑体验。
- 组件端口类型明确：LLM、Prompt、Data、Tool、Message 等。
- Agent 组件可以连接工具端口，也可以把其他 Agent 或 MCP Tools 当工具。
- 支持查看/编辑组件底层代码，对开发者友好。
- JSON 导入导出便于二次编辑和分享。

局限：

- 不是 LangGraph 原生图编译器。
- 导出 JSON 通常仍依赖 Langflow 运行时，不是干净 Python LangGraph 工程。

### 2.4 LangGraph 官方能力

本项目必须以 LangGraph 官方抽象为最终编译目标：

- `StateGraph`：图定义。
- `START` / `END`：入口和终止。
- `add_node`：注册节点。
- `add_edge`：普通静态边。
- `add_conditional_edges`：条件路由。
- `MessagesState` 或自定义 `TypedDict` state：状态定义。
- `ToolNode`：工具调用执行节点。
- `create_agent`：快速创建带工具循环的生产级 Agent。
- `interrupt` / checkpointer：human-in-the-loop 和持久执行。
- `langgraph.json`：LangGraph 应用结构和部署配置。

重要设计约束：

- 同一个节点不要同时混用普通出边和动态路由，否则可能出现并行执行和难以解释的行为。
- 多个普通出边在 LangGraph 中可能表示并行 superstep，需要为写入同一 state 字段配置 reducer。
- 条件边必须有明确的路由函数和可枚举分支，UI 上需要强制显示分支 handle。
- 可移植导出包必须包含 `langgraph.json`、依赖文件、源码、`.env.example` 和 README。

## 3. 产品定位

产品名称暂定：GraphicLangGraph。

一句话定位：

> 用中文对话和拖拽节点生成可移植 LangGraph Agent 工程。

目标用户：

- 业务自动化工程师：希望搭建客服、销售、知识库、报表、监控 Agent。
- AI 应用开发者：懂 Python，但不想从零手写所有 LangGraph 编排。
- 企业内部平台团队：希望给业务人员一个受控的 Agent 搭建入口。
- 教学/培训用户：通过可视化理解 LangGraph 节点、状态和边。

典型场景：

- 客服工单分类、查知识库、调用订单 API、需要人工审批退款。
- 每日自动读取数据源、生成总结、发 Slack/企微/邮件。
- 研发助手读取 GitHub issue、查询文档、输出修复建议。
- 多 Agent 协作：主控 Agent 分配给调研、分析、写作、审核子 Agent。
- RAG Agent：接入文档、检索、重写问题、生成答案、返回引用。

## 4. 总体交互设计

### 4.1 三种创建路径

1. 模板创建

用户选择中文模板，例如：

- 企业知识库问答 Agent
- 客服工单处理 Agent
- 邮件/日程助理 Agent
- 数据监控日报 Agent
- 多 Agent 研究写作流

系统生成初始图、说明、节点配置和测试样例。

2. 对话创建

用户输入：

> 我想做一个客服 Agent，先判断用户问题类型，如果是订单问题就查订单 API，如果是退款就需要人工审批，最后回复用户。

内置搭建助手生成：

- 节点清单
- 状态字段
- 工具定义
- 分支逻辑
- 初始 prompt
- 测试用例

用户确认后自动落到画布。

3. 手动创建

用户从左侧节点库拖入节点，连线，右侧配置参数。

### 4.2 页面布局

推荐布局：

- 顶部栏：项目名、保存、验证、运行、导出、设置、版本历史。
- 左侧栏：节点库、模板库、变量/状态管理、工具库。
- 中央画布：React Flow 节点图，支持拖拽、缩放、框选、自动布局。
- 右侧检查器：选中节点/边/项目后的配置面板。
- 底部运行面板：输入测试、流式输出、节点执行日志、错误、trace。
- 右侧或可折叠聊天栏：内置 Agent 搭建助手。

### 4.3 简化交互原则

- 所有字段默认中文说明，保留高级模式显示源码字段。
- 用户优先选择“意图”，系统自动补齐技术参数。
- 变量通过下拉选择插入，显示中文别名，同时保存机器表达式。
- 节点出错时，不只显示异常，还给出修复按钮。
- 导出前自动验证，失败项定位到节点和字段。

## 5. 核心中间模型 IR

本项目不应把前端画布 JSON 直接编译为源码。应设计稳定的中间表示 IR，作为 UI、内置助手、编译器、导出器、测试器之间的共同协议。

### 5.1 Project IR

```json
{
  "schemaVersion": "0.1.0",
  "project": {
    "id": "customer_support_agent",
    "name": "客服工单 Agent",
    "description": "分类、查询订单、审批退款并回复用户",
    "language": "python",
    "runtime": "langgraph",
    "createdAt": "2026-06-09T00:00:00Z"
  },
  "state": {
    "base": "MessagesState",
    "fields": []
  },
  "nodes": [],
  "edges": [],
  "tools": [],
  "subgraphs": [],
  "triggers": [],
  "secrets": [],
  "tests": []
}
```

### 5.2 Node IR

```json
{
  "id": "route_intent",
  "type": "ai_router",
  "label": "识别问题类型",
  "position": { "x": 420, "y": 180 },
  "config": {},
  "inputs": [
    { "id": "in", "type": "control" }
  ],
  "outputs": [
    { "id": "order", "type": "control", "label": "订单问题" },
    { "id": "refund", "type": "control", "label": "退款问题" },
    { "id": "other", "type": "control", "label": "其他问题" }
  ],
  "stateReads": ["messages"],
  "stateWrites": ["intent"],
  "validation": {
    "status": "valid",
    "issues": []
  }
}
```

### 5.3 Edge IR

```json
{
  "id": "edge_route_to_order",
  "source": "route_intent",
  "sourceHandle": "order",
  "target": "order_agent",
  "targetHandle": "in",
  "kind": "conditional",
  "label": "订单问题"
}
```

### 5.4 变量表达式

UI 中使用中文变量选择器，底层保存表达式：

- `{{ input.message }}`：入口用户输入。
- `{{ state.intent }}`：LangGraph state 字段。
- `{{ node.route_intent.output }}`：指定节点输出。
- `{{ tool.get_order.result }}`：工具结果。
- `{{ env.ORDER_API_BASE_URL }}`：环境变量引用，只允许引用，不保存真实值。

编译器将表达式转换为 Python 代码中的 state 访问、节点输出规范或参数映射。

## 6. MVP 节点目录与配置规范

### 6.1 Start 节点

用途：

- 定义图入口。
- 定义输入类型。
- 初始化 state。
- 配置是否使用历史消息。

配置项：

- 输入模式：聊天输入 / 表单输入 / Webhook 输入 / 手动测试输入。
- 表单字段：字段名、中文标签、类型、必填、默认值、校验规则。
- 初始 state：字段名、类型、默认值、中文说明。
- memory 策略：无 / thread memory / checkpointer / long-term store。
- 入口说明：生成 README 和 API schema 时使用。

连线规则：

- 一个 graph 只能有一个 Start。
- Start 必须至少连接一个可执行节点。
- Start 不允许有入边。

LangGraph 映射：

- `builder.add_edge(START, "first_node")`
- 输入 schema 映射到 graph invoke input。
- state 字段生成到 `state.py`。

### 6.2 LLM 节点

用途：

- 一次性调用模型，完成分类、总结、抽取、改写、生成等任务。

配置项：

- 模型供应商：OpenAI / Anthropic / Azure OpenAI / 本地 OpenAI-compatible / 自定义。
- 模型 ID。
- messages：system、developer、user、assistant，多条可排序。
- 输入变量：从 state 或前置节点引用。
- 输出格式：文本 / JSON schema / Pydantic schema。
- temperature、max tokens、timeout、retry。
- 是否读取 thread messages。
- state 更新：将输出写入哪些 state 字段。

输出：

- `text`
- `json`
- `message`
- `raw_response`

连线规则：

- 支持普通出边。
- 如果配置了 JSON schema，可接 Condition 节点或 Transform 节点。

LangGraph 映射：

- 生成普通节点函数，内部调用 `init_chat_model(...).invoke(...)`。

### 6.3 Agent 节点

用途：

- 用模型进行多步推理，可调用工具、检索知识库或委派子 Agent。

配置项：

- Agent 名称：导出为 snake_case。
- 指令：system prompt / developer instruction。
- 模型。
- 可用工具列表。
- 工具审批策略：不审批 / 指定工具审批 / 所有写操作审批。
- 知识库：retriever 或 vector store。
- 子 Agent：可委派的 subgraph/agent。
- 最大迭代次数。
- memory 策略。
- 输出字段：最终回答、结构化结果、工具轨迹。

连线规则：

- Agent 可作为流程中的普通节点。
- Agent 内部工具循环对普通用户隐藏，高级模式可展开为 `LLM -> ToolNode -> LLM`。
- 如果 Agent 有多条出边，必须通过 Condition 或 AI Router 决定。

LangGraph 映射：

- 简单 Agent：`create_agent(model=..., tools=..., system_prompt=...)`
- 可视化展开 Agent：`StateGraph + model node + ToolNode + tools_condition`

### 6.4 Tool 执行节点

用途：

- 确定性执行一个工具，不让 Agent 自主选择。

配置项：

- 工具来源：内置 / 自定义 Python / HTTP / MCP / OpenAPI / 子流程。
- 工具名称和描述。
- 参数 schema。
- 参数映射：静态值、state、前置节点输出、环境变量。
- 认证：secret 引用。
- 超时、重试、错误处理。
- 是否需要人工审批。
- 输出写入 state。

连线规则：

- 入边来自任意可执行节点。
- 出边连接 LLM、Agent、Condition、Direct Reply 等。
- 参数缺失时禁止运行。

LangGraph 映射：

- 对 Agent 工具：生成 `@tool` 函数。
- 对确定性流程工具：生成普通节点函数。
- 对模型 tool call：使用 `ToolNode([...])`。

### 6.5 Retriever/RAG 节点

用途：

- 查询知识库，输出上下文或引用。

配置项：

- 数据源：本地文档目录 / 已建向量库 / 外部 retriever / HTTP 检索 API。
- embedding 模型。
- top_k。
- metadata filters。
- query 来源。
- 返回格式：纯文本 / 文档列表 / 带 metadata / 带引用。
- 是否写入 state。

连线规则：

- 通常接在 LLM 改写 query 之后，或接在 Agent 之前。
- 输出可被 LLM/Agent 消费。

LangGraph 映射：

- 普通 retriever 节点。
- 或包装成 retriever tool 给 Agent 使用。

### 6.6 HTTP 节点

用途：

- 调用外部 REST API。

配置项：

- Method：GET / POST / PUT / PATCH / DELETE。
- URL，支持变量。
- Query params。
- Headers。
- Body 类型：JSON / form / raw。
- Auth：None / API Key / Bearer / Basic / OAuth/MCP 代理。
- Response 类型：JSON / text / bytes。
- JSONPath/JMESPath 提取。
- 超时、重试、错误分支。
- 输出写入 state。

连线规则：

- 可接普通成功出边和错误出边。
- 如果 HTTP 是写操作，默认建议开启人工审批。

LangGraph 映射：

- 普通节点函数，或生成 `@tool`。

### 6.7 Condition 规则分支节点

用途：

- 用确定性规则进行分支。

配置项：

- 条件组：all / any。
- 条件类型：字符串、数字、布尔、列表、JSONPath。
- 操作符：等于、不等于、包含、不包含、大于、小于、为空、不为空、正则匹配。
- 分支：true / false / 多条件命名分支。
- fallback 分支。

连线规则：

- 出边必须连接到分支 handle。
- Condition 节点不允许再配置普通默认出边，避免混合路由。

LangGraph 映射：

- 生成 route 函数。
- `builder.add_conditional_edges("condition_node", route_fn, mapping)`

### 6.8 AI Router / Condition Agent 节点

用途：

- 用 LLM 做意图识别、场景分类、复杂路由。

配置项：

- 模型。
- 路由说明。
- 输入文本/上下文。
- 场景列表：分支 ID、中文名称、判定标准、示例。
- 输出模式：只输出路由 key / 路由 key + reason。
- 置信度阈值。
- fallback 分支。
- 是否记录 reason 到 state。

连线规则：

- 每个 scenario 自动生成一个 source handle。
- 必须有 fallback。

LangGraph 映射：

- LLM 节点生成结构化输出。
- route 函数读取 `state["route_key"]`。
- `add_conditional_edges` 映射到不同节点。

### 6.9 Iteration 迭代节点

用途：

- 对数组中的每个元素执行子流程。

配置项：

- 数组来源：state 字段或前置节点输出。
- 当前元素变量名。
- 最大条数。
- 并发数：1 / N。
- 子流程：画布中的嵌套节点组。
- 聚合方式：append / merge / reduce 自定义。
- 出错策略：停止 / 跳过 / 收集错误。

连线规则：

- Iteration 是容器节点，内部有子节点。
- 只有子流程结束后才走外部出边。

LangGraph 映射：

- 简单版：普通 Python 循环节点。
- 高级版：Send API / map-reduce 模式 / 子图。

### 6.10 Loop 循环节点

用途：

- 回跳到之前节点，执行重试、反思、改写、再检索等循环。

配置项：

- 回跳目标节点。
- 最大循环次数。
- 循环计数字段。
- 继续条件。
- 超限后的分支。

连线规则：

- 只能回跳到已执行路径上的节点。
- 必须配置最大次数。
- UI 上应醒目标识循环边。

LangGraph 映射：

- 条件边回到目标节点。
- state 中维护 loop count。

### 6.11 Human Input / Approval 节点

用途：

- 暂停流程，等待人工确认、编辑、拒绝或补充信息。

配置项：

- 类型：审批 / 文本输入 / 多选 / 文件上传 / 参数编辑。
- 提示内容：固定文本或 LLM 动态生成。
- 动作按钮：通过、拒绝、修改、重新生成。
- 是否允许编辑工具参数。
- 超时策略。
- 审批人/角色。
- 输出写入 state。

连线规则：

- 每个动作按钮对应一个分支 handle。
- 拒绝分支必须连接到 Direct Reply、修复节点或 End。

LangGraph 映射：

- 使用 interrupt。
- 导出时自动配置 checkpointer。

### 6.12 Direct Reply / End 节点

用途：

- 返回最终消息并结束路径。

配置项：

- 回复内容：文本模板或变量。
- 是否附加引用。
- 输出格式：chat message / JSON / API response。
- 是否保存到 memory。

连线规则：

- 无出边。
- 至少一条路径必须到达 Direct Reply 或 END。

LangGraph 映射：

- 返回 `messages` 更新。
- `builder.add_edge("reply_node", END)`

### 6.13 Custom Function 节点

用途：

- 执行无法用标准节点表达的数据转换或业务逻辑。

配置项：

- 语言：Python MVP 优先；JS 后续。
- 输入变量 schema。
- 输出 schema。
- 代码编辑器。
- 允许依赖白名单。
- 沙箱权限：无网络 / 允许 HTTP / 允许文件读写。
- 超时和资源限制。

连线规则：

- 高风险节点，导出前需要安全提示。
- 如果代码写 state，必须声明写入字段。

LangGraph 映射：

- 生成 `nodes.py` 中的函数。

### 6.14 Execute Flow / Subgraph 节点

用途：

- 调用另一个可视化 flow、子 Agent 或子图。

配置项：

- 目标 flow。
- 输入映射。
- 输出映射。
- 是否共享 state。
- 错误处理。

连线规则：

- 可作为普通节点。
- 子图内部必须独立验证通过。

LangGraph 映射：

- 编译为 subgraph。
- 或导入另一个 `graph` 对象作为节点。

### 6.15 Schedule / Channel 触发器

用途：

- 定义 Agent 什么时候被触发。

配置项：

- Schedule：cron、interval、timezone、prompt。
- Webhook：path、method、auth、payload schema。
- Chat：默认入口。
- Email/Slack/企微/飞书：后续作为插件。

连线规则：

- 不直接编译为 LangGraph 节点，而是运行适配层。
- 每个 trigger 绑定一个 graph entry。

导出映射：

- `triggers.yaml`
- FastAPI route 示例。
- cron/APScheduler 示例。

## 7. 连线与执行语义

### 7.1 控制边与数据引用分离

画布边主要表达控制流，不强制表达所有数据流。数据通过 state 和变量表达式引用：

- 控制边：决定谁执行后到谁。
- 条件边：决定进入哪个分支。
- 数据引用：节点配置里的 `{{ state.xxx }}` 或 `{{ node.xxx.output }}`。

这样可以避免画布过度复杂，也更接近 LangGraph 的 state 模型。

### 7.2 端口类型

基础端口类型：

- `control`：执行流。
- `condition`：条件分支。
- `tool`：Agent 可用工具。
- `data`：显式数据传递，高级模式使用。
- `error`：错误分支。
- `approval`：人工动作分支。

端口兼容规则：

- `control -> control` 可连。
- `condition -> control` 可连。
- `tool -> agent.tools` 可连。
- `data -> data/input` 高级模式可连。
- `error -> control` 可连。
- 终止节点无输出。

### 7.3 图验证规则

硬性规则：

- 必须有且只有一个 Start。
- 至少有一个终止路径。
- 所有节点必须可从 Start 到达，孤立节点只允许处于草稿禁用状态。
- 所有启用节点必须能到达终止节点，除非被受控 Loop 包裹。
- Loop 必须有最大次数。
- 条件节点必须每个分支都有连接或配置 fallback。
- AI Router 必须有 fallback。
- 同一个节点不能同时存在普通出边和条件出边。
- 多个普通出边造成并行执行时，写入同一 state 字段必须配置 reducer。
- 所有 state 字段必须先声明后写入。
- 所有 secret 只能引用 key，不能保存明文。
- 所有工具参数必须满足 schema。

软性规则：

- HTTP 写操作建议开启审批。
- Agent 工具过多时建议拆成子 Agent。
- LLM 节点没有结构化输出却连接复杂 Condition 时给出提示。
- Prompt 过长时建议转成 Skill 或文件。
- Retriever 输出未接入 LLM/Agent 时提示可能无效。

## 8. 内置 Agent 搭建助手

### 8.1 角色定位

内置 Agent 不是普通聊天助手，而是“Agent 架构师 + 画布操作员 + 编译错误修复器”。

它能做：

- 需求澄清。
- 生成初始流程。
- 推荐节点。
- 自动补全配置。
- 生成 prompt。
- 生成工具 schema。
- 生成测试用例。
- 修复验证错误。
- 解释节点执行 trace。
- 优化流程结构。
- 生成导出包。

它不能直接做：

- 保存明文密钥。
- 未经用户确认删除大量节点。
- 未经审批启用高风险工具。
- 绕过图验证强行导出。

### 8.2 搭建助手可调用工具

内部工具建议：

```text
create_node(type, label, position, config)
update_node(node_id, patch)
delete_node(node_id)
connect_nodes(source, source_handle, target, target_handle)
disconnect_edge(edge_id)
declare_state_field(name, type, default, description)
create_tool(name, description, schema, implementation_type)
validate_graph()
generate_prompt(node_id, goal)
generate_tests(project_id)
run_test(test_id)
compile_project()
export_zip()
explain_error(error_id)
```

### 8.3 交互流程

示例：

1. 用户说：“帮我做一个售后客服 Agent。”
2. 搭建助手追问 2 到 3 个关键信息：数据源、是否调用订单 API、哪些动作需要审批。
3. 搭建助手生成流程草案：
   - Start
   - AI Router：订单 / 退款 / 其他
   - Retriever：售后政策知识库
   - HTTP Tool：查询订单
   - Human Approval：退款审批
   - Agent：组织回复
   - Direct Reply
4. 用户确认后自动创建节点和连线。
5. 搭建助手提示缺失配置：订单 API URL、认证 secret、知识库路径。
6. 用户填写或选择。
7. 搭建助手生成测试用例并运行。
8. 用户点击导出 ZIP。

### 8.4 UI 表达

搭建助手每次修改画布前显示变更预览：

```text
将要创建：
- 1 个 AI Router 节点
- 1 个 HTTP 工具节点
- 1 个人工审批节点
- 3 条条件边

将要声明 state：
- intent: str
- order_info: dict
- approval_result: str
```

用户确认后执行。

## 9. 代码生成与导出包设计

### 9.1 编译流程

1. 读取 Project IR。
2. 校验 schema version。
3. 规范化节点 ID，生成合法 Python 标识符。
4. 构建 state schema。
5. 解析变量表达式。
6. 生成节点函数。
7. 生成工具函数。
8. 生成 route 函数。
9. 生成 `StateGraph` 组装代码。
10. 生成 `langgraph.json`。
11. 生成 `pyproject.toml` 或 `requirements.txt`。
12. 生成 `.env.example`。
13. 生成 README。
14. 生成 tests。
15. 运行静态检查和 smoke test。
16. 打包 ZIP。

### 9.2 导出目录结构

```text
customer_support_agent/
├── langgraph.json
├── pyproject.toml
├── .env.example
├── README.md
├── src/
│   └── customer_support_agent/
│       ├── __init__.py
│       ├── graph.py
│       ├── state.py
│       ├── nodes.py
│       ├── tools.py
│       ├── routers.py
│       ├── prompts.py
│       ├── schemas.py
│       └── config.py
├── tests/
│   ├── test_graph_smoke.py
│   └── test_routes.py
└── flow/
    ├── project.graph.json
    └── README.md
```

### 9.3 `langgraph.json` 示例

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./src/customer_support_agent/graph.py:graph"
  },
  "env": "./.env"
}
```

### 9.4 `state.py` 示例

```python
from typing import Any
from typing_extensions import TypedDict
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    intent: str
    order_info: dict[str, Any]
    approval_result: str
    final_answer: str
```

### 9.5 `graph.py` 示例

```python
from langgraph.graph import START, END, StateGraph

from .state import AgentState
from .nodes import classify_intent, query_order, draft_reply, direct_reply
from .routers import route_intent


builder = StateGraph(AgentState)

builder.add_node("classify_intent", classify_intent)
builder.add_node("query_order", query_order)
builder.add_node("draft_reply", draft_reply)
builder.add_node("direct_reply", direct_reply)

builder.add_edge(START, "classify_intent")
builder.add_conditional_edges(
    "classify_intent",
    route_intent,
    {
        "order": "query_order",
        "other": "draft_reply",
    },
)
builder.add_edge("query_order", "draft_reply")
builder.add_edge("draft_reply", "direct_reply")
builder.add_edge("direct_reply", END)

graph = builder.compile()
```

### 9.6 导出模式

MVP 支持：

- 源码 ZIP：最重要，用户可直接移植。
- LangGraph dev 工程：包含 `langgraph.json`，可用 `langgraph dev`。
- JSON 设计文件：可重新导入本工具编辑。
- SDK 调用示例：Python、TypeScript、curl。

后续支持：

- Dockerfile。
- FastAPI wrapper。
- LangSmith Deployment 配置说明。
- GitHub repo 直接生成。
- MCP server 包装。

## 10. 技术架构建议

### 10.1 前端

推荐：

- React + TypeScript。
- `@xyflow/react` / React Flow 作为画布。
- Monaco Editor 作为代码/prompt 编辑器。
- Zod/JSON Schema 驱动配置表单。
- Zustand 或 Redux Toolkit 管理画布状态。
- TanStack Query 调用后端。
- i18n 先中文，预留英文。

React Flow 的关键能力：

- nodes/edges 受控渲染。
- 自定义节点。
- handles/ports 支持多分支连线。
- `sourceHandle` 和 `targetHandle` 区分具体端口。
- 自定义 edge 展示条件标签、错误分支、循环边。

### 10.2 后端

推荐：

- Python FastAPI。
- Pydantic 定义 Project IR。
- SQLite MVP，PostgreSQL Beta。
- 文件存储本地目录，后续对象存储。
- 编译器模块独立：`compiler/`。
- 运行预览用隔离子进程。
- 后台任务用 Celery/RQ/Arq，MVP 可用 FastAPI background task。

后端模块：

```text
backend/
├── app.py
├── api/
│   ├── projects.py
│   ├── nodes.py
│   ├── validate.py
│   ├── compile.py
│   ├── run.py
│   └── export.py
├── ir/
│   ├── schema.py
│   └── validators.py
├── compiler/
│   ├── python_codegen.py
│   ├── langgraph_codegen.py
│   ├── templates/
│   └── package.py
├── runner/
│   ├── sandbox.py
│   └── trace.py
└── assistant/
    ├── graph_builder_agent.py
    └── tools.py
```

### 10.3 编译器分层

- IR Validator：只关心结构正确性。
- Semantic Analyzer：分析 state、变量、分支、循环、并行 reducer。
- Code Planner：决定节点编译方式。
- Template Renderer：生成 Python 文件。
- Package Builder：生成 ZIP。
- Smoke Tester：导出前运行最小测试。

### 10.4 运行预览

MVP 运行方式：

- 后端在临时目录生成项目。
- 写入 `.env.runtime`。
- 使用子进程执行测试脚本。
- 捕获 stdout、stderr、节点日志。
- 返回节点级状态给前端。

后续：

- 使用 LangGraph SDK/Server 进行本地 Agent Server 预览。
- 集成 LangSmith tracing。
- 支持断点、time travel、人类审批恢复。

## 11. 安全设计

### 11.1 Secret 管理

- 画布 JSON 不保存明文密钥。
- 节点只保存 `secretRef`。
- 导出 `.env.example`，不导出 `.env`。
- 用户选择“包含本地密钥导出”时必须二次确认，默认禁用。

### 11.2 Custom Function 沙箱

- MVP 默认禁用文件写入和任意 shell。
- Python 代码执行使用独立进程、超时、资源限制。
- 依赖安装白名单。
- 网络访问按节点权限打开。
- 所有高风险节点在 UI 上标红。

### 11.3 MCP 和 HTTP 风险

- MCP server 配置必须显示命令、URL、权限范围。
- 禁止从导入的 JSON 自动启动本地 command 型 MCP。
- HTTP 写操作默认建议审批。
- 导入外部 flow 时进入隔离审查模式，不立即可运行。

### 11.4 导出代码审计

- 导出包包含 `SECURITY.md`。
- README 明确列出所需环境变量和外部访问权限。
- 编译器生成的代码和用户自定义代码分文件存放，便于审计。

## 12. 模板体系

MVP 内置模板：

### 12.1 知识库问答 Agent

节点：

- Start
- Query Rewrite LLM
- Retriever
- Answer LLM
- Direct Reply

适合演示 state、RAG、引用。

### 12.2 客服工单 Agent

节点：

- Start
- AI Router
- Retriever
- HTTP 查询订单
- Human Approval 退款审批
- Agent 组织回复
- Direct Reply

适合演示分支、工具、审批。

### 12.3 数据监控日报 Agent

节点：

- Schedule
- HTTP 拉取指标
- Condition 判断异常
- LLM 总结
- HTTP/Tool 发送通知

适合演示 schedule 和自动化。

### 12.4 多 Agent 研究写作流

节点：

- Start
- Research Agent
- Analysis Agent
- Writer Agent
- Reviewer Agent
- Direct Reply

适合演示 sub-agent 和 Execute Flow。

## 13. 版本路线

### 13.1 P0 原型，2 周

目标：

- 完成 IR schema。
- 完成 6 个节点：Start、LLM、Condition、HTTP、Direct Reply、Custom Function。
- 完成 React Flow 画布和右侧配置面板。
- 完成基础 Python LangGraph 源码导出。
- 完成 graph validation。

验收：

- 用户能拖出一个 `Start -> LLM -> Direct Reply` 流程。
- 能导出 ZIP。
- 导出的项目能通过 smoke test。

### 13.2 MVP，4 到 6 周

新增：

- Agent 节点。
- Tool 节点。
- Retriever 节点。
- AI Router 节点。
- Human Approval 节点。
- 内置搭建助手第一版。
- 模板库。
- 运行预览。
- `.env.example`、README、tests 自动生成。

验收：

- 能完成客服工单 Agent 模板。
- 能完成知识库问答 Agent 模板。
- 能通过中文对话生成初始画布。
- 能导出可运行 LangGraph 项目。

### 13.3 Beta，8 到 12 周

新增：

- Iteration。
- Loop。
- Subgraph/Execute Flow。
- Schedule/Webhook 触发器。
- MCP 工具接入。
- 版本历史。
- 导入导出 JSON。
- LangSmith trace 可选集成。
- Dockerfile 导出。

验收：

- 能构建多 Agent 流程。
- 能运行 human-in-the-loop 中断和恢复。
- 能以 webhook/API 方式调用导出 Agent。

### 13.4 1.0，12 到 16 周

新增：

- 权限和团队协作。
- 插件化节点 SDK。
- 工具市场。
- 企业审计日志。
- 更多中文行业模板。
- 私有部署文档。

验收：

- 支持团队内复用模板和工具。
- 支持从设计到导出再部署的完整闭环。

## 14. API 设计草案

### 14.1 项目 API

```text
POST   /api/projects
GET    /api/projects/{id}
PATCH  /api/projects/{id}
DELETE /api/projects/{id}
POST   /api/projects/{id}/duplicate
```

### 14.2 图编辑 API

```text
POST   /api/projects/{id}/nodes
PATCH  /api/projects/{id}/nodes/{node_id}
DELETE /api/projects/{id}/nodes/{node_id}
POST   /api/projects/{id}/edges
DELETE /api/projects/{id}/edges/{edge_id}
POST   /api/projects/{id}/auto-layout
```

### 14.3 验证、运行、导出 API

```text
POST /api/projects/{id}/validate
POST /api/projects/{id}/compile
POST /api/projects/{id}/run
GET  /api/projects/{id}/runs/{run_id}
POST /api/projects/{id}/export
GET  /api/projects/{id}/exports/{export_id}/download
```

### 14.4 搭建助手 API

```text
POST /api/projects/{id}/assistant/messages
POST /api/projects/{id}/assistant/apply-plan
GET  /api/projects/{id}/assistant/suggestions
```

## 15. 数据库表设计草案

```text
projects
- id
- name
- description
- owner_id
- schema_version
- created_at
- updated_at

project_versions
- id
- project_id
- version
- ir_json
- message
- created_at

runs
- id
- project_id
- status
- input_json
- output_json
- trace_json
- error
- created_at

exports
- id
- project_id
- status
- artifact_path
- format
- created_at

secrets
- id
- owner_id
- name
- provider
- encrypted_value
- created_at
```

## 16. 成功指标

产品指标：

- 新用户 10 分钟内完成第一个 Agent。
- 模板创建后首次验证通过率大于 80%。
- 中文对话生成画布后，用户手动改动节点数小于 30%。
- 导出 ZIP 后本地 smoke test 通过率大于 90%。

工程指标：

- 编译错误定位到具体节点/字段。
- 导出项目不依赖平台运行时。
- 核心节点测试覆盖率大于 80%。
- 自定义代码节点默认沙箱开启。

用户体验指标：

- 关键配置字段都有中文说明和示例。
- 所有 validation issue 都有“一键修复”或明确操作建议。
- 复杂模板加载后画布自动布局可读。

## 17. 主要风险与应对

### 17.1 LangGraph 能力过强，低代码抽象容易失真

应对：

- 只抽象常见模式。
- 高级能力允许用户进入代码模式。
- 导出源码保持清晰，不隐藏复杂性。

### 17.2 图连线语义和 LangGraph 并行语义不一致

应对：

- 严格区分普通边、条件边、并行边。
- 默认不允许一个节点多个普通出边，除非用户显式选择“并行执行”。
- 并行写 state 时强制配置 reducer。

### 17.3 内置搭建助手生成不可运行流程

应对：

- 搭建助手不能直接写源码，只能操作 IR。
- 所有修改经过 validator。
- 每次应用前展示变更计划。

### 17.4 安全风险

应对：

- secret 不入导出 JSON。
- Custom Function 沙箱。
- 导入外部项目默认禁用高风险节点。
- MCP 本地命令需要人工确认。

### 17.5 导出后在其他项目不可用

应对：

- 导出包包含 README、依赖、`.env.example`、tests。
- 导出前自动创建临时环境跑 smoke test。
- 保留 `flow/project.graph.json` 以便回流编辑。

## 18. 推荐 MVP 实施顺序

1. 先做 IR 和 validator。
2. 再做画布节点和配置面板。
3. 同步做 LangGraph Python codegen。
4. 做导出 ZIP 和 smoke test。
5. 加入 LLM/Agent/Tool/Retriever 节点。
6. 加入中文搭建助手。
7. 加入模板和运行预览。
8. 最后做 Schedule、MCP、Subgraph、团队协作。

不要一开始就做：

- 任意第三方 SaaS 大集成。
- 复杂权限系统。
- 自研执行引擎。
- 直接兼容所有 Flowise/Langflow 节点。
- 可视化调试的所有 LangSmith Studio 能力。

## 19. 参考资料

- LangSmith Fleet overview: https://docs.langchain.com/langsmith/fleet/index
- LangSmith Fleet quickstart: https://docs.langchain.com/langsmith/fleet/quickstart
- LangSmith Fleet essentials: https://docs.langchain.com/langsmith/fleet/essentials
- LangSmith Fleet tools: https://docs.langchain.com/langsmith/fleet/tools
- LangSmith Fleet channels: https://docs.langchain.com/langsmith/fleet/channels
- LangSmith Fleet schedules: https://docs.langchain.com/langsmith/fleet/schedules
- LangSmith Fleet skills: https://docs.langchain.com/langsmith/fleet/skills
- LangSmith Fleet agent settings and ZIP export: https://docs.langchain.com/langsmith/fleet/manage-agent-settings
- Flowise Agentflow V2: https://docs.flowiseai.com/using-flowise/agentflowv2
- Flowise Sequential Agents: https://docs.flowiseai.com/using-flowise/agentflows/sequential-agents
- Langflow components overview: https://docs.langflow.org/1.8.0/concepts-components
- Langflow agents: https://docs.langflow.org/components-agents
- Langflow import/export: https://docs.langflow.org/concepts-flows-import
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph
- LangGraph Graph API: https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph application structure: https://docs.langchain.com/oss/python/langgraph/application-structure
- LangChain ToolNode docs: https://docs.langchain.com/oss/python/langchain/tools
- React Flow core concepts: https://reactflow.dev/learn/concepts/core-concepts
- React Flow handles: https://reactflow.dev/learn/customization/handles
