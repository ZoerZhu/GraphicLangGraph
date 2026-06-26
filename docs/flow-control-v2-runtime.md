# Flow Control v2 Runtime Notes

## 目标

Flow Control v2 让真实业务流在节点失败、超时、批量任务并发处理和多分支汇合时仍然可控。当前版本覆盖 Workspace live-run 与导出工程，核心能力包括节点运行策略、Parallel ForEach 和 Branch Merge。

## 节点运行策略

所有普通可执行节点支持以下高级配置：

- `retryPolicyJson`：`enabled/maxRetries/backoffMs/retryOnErrorTypes`。`maxRetries` 上限为 5；`retryOnErrorTypes` 为空时对所有异常重试。
- `nodeTimeoutSec`：节点级超时秒数，`0` 或空值表示不启用。
- `errorPolicy`：`default/fail_fast/route_error/continue/fallback`。
- `fallbackOutputJson`：`errorPolicy=fallback` 时合并到 state 的 JSON object。
- `errorOutputField`：`continue/fallback` 时可把错误写入指定字段；留空使用 `last_error`。

默认行为保持兼容：没有高级策略时，节点失败且有 error 边会进入 error 分支；没有 error 边则 fail-fast。`continue` 会记录错误并沿普通输出继续，`fallback` 会合并默认输出后继续。

## Parallel ForEach

ForEach 新增：

- `executionMode`：`sequential` 或 `parallel`，默认 `sequential`。
- `maxConcurrency`：并发上限，建议从 2-4 开始，最大 12。
- `preserveOrder`：默认 true，Merge 结果按输入顺序聚合。
- `itemFailurePolicy`：`fail_fast` 或 `collect_errors`。

并发模式下，每个 item 子链路独立运行。live-run stream 会带上 `parentNodeId/iterationIndex/iterationItem`，前端可以实时显示每轮子节点 running/done/error。`collect_errors` 会把失败项写入迭代摘要并继续处理其他 item。

## Branch Merge

Merge 新增 `mergeMode`：

- `auto`：兼容旧流程，根据上下文作为 ForEach Merge 或普通 Branch Merge。
- `for_each`：用于 ForEach 子链路终点，按 reducer 聚合每轮 `itemState`。
- `branch`：用于 Condition/AI Router 等多分支汇合，只聚合当前实际执行分支，不等待未执行分支。

Reducer 仍支持 `append/concat/merge/overwrite/first/last`。Branch Merge 的常用配置是 `overwrite branch_result` 或 `merge branch_context`，把不同分支标准化写回统一字段。

## 验收模板

模板库提供“并发任务处理 Flow Control v2”：

`Start -> JSON Extractor -> JSON Validator -> Task Splitter -> ForEach(parallel, collect_errors) -> Template Worker -> Merge -> Direct Reply`

该模板不依赖 HTTP/MCP/外部工具，Worker Placeholder 可替换为 Tool、MCP、Agent 或 Agent Ref。推荐用它验收：

- Task Plan 校验成功后进入并发 ForEach。
- 每个 item 的 Worker 节点在画布上实时显示 running/done。
- 单项失败时 error 分支写入 `item_result`，其他 item 继续执行。
- Merge 写入 `merged_results` 和 `merge_result.iterations`。
- Direct Reply 输出最终汇总。

## 排障要点

- ForEach 没有 item 端口连线或循环体没有到达 Merge，会直接报校验/运行错误。
- 并发 item 内不要写同一个全局字段；需要聚合的字段应写入 itemState，再由 Merge reducer 收集。
- `nodeTimeoutSec` 是运行层 deadline；底层不可中断调用可能稍后结束，但当前流程会忽略其结果。
- `fallbackOutputJson` 必须是 JSON object，且不要写入密钥或大体积内容。
- Branch Merge 不等待未执行分支；如果需要等待多个真实并发分支，需要后续独立的并行分支调度能力。
