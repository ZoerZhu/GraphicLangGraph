import { useMemo } from "react";
import { useProjectStore } from "../store/projectStore";
import type { StateField } from "../types";

export function Inspector() {
  const project = useProjectStore((state) => state.project);
  const selectedNodeId = useProjectStore((state) => state.selectedNodeId);
  const updateNode = useProjectStore((state) => state.updateNode);
  const updateNodeConfig = useProjectStore((state) => state.updateNodeConfig);
  const setStateFields = useProjectStore((state) => state.setStateFields);

  const node = useMemo(
    () => project?.nodes.find((item) => item.id === selectedNodeId) ?? null,
    [project?.nodes, selectedNodeId],
  );

  if (!project) {
    return null;
  }

  if (!node) {
    return (
      <aside className="right-panel glass-panel">
        <div className="panel-title">
          <span>检查器</span>
          <small>未选中</small>
        </div>
        <div className="empty-state">选择一个节点后编辑配置。</div>
      </aside>
    );
  }

  return (
    <aside className="right-panel glass-panel">
      <div className="panel-title">
        <span>检查器</span>
        <small>{node.type}</small>
      </div>
      <Field label="节点名称">
        <input value={node.label} onChange={(event) => updateNode(node.id, { label: event.target.value })} />
      </Field>
      {node.type === "start" && (
        <>
          <Field label="输入模式">
            <select
              value={String(node.config.inputMode ?? "chat")}
              onChange={(event) => updateNodeConfig(node.id, { inputMode: event.target.value })}
            >
              <option value="chat">聊天输入</option>
              <option value="form">表单输入</option>
              <option value="webhook">Webhook</option>
            </select>
          </Field>
          <Field label="State 字段">
            <textarea
              rows={6}
              value={stateFieldsToText(project.state.fields)}
              onChange={(event) => setStateFields(parseStateFields(event.target.value))}
              placeholder="final_answer:str&#10;intent:str&#10;order_info:dict"
            />
          </Field>
        </>
      )}
      {node.type === "llm" && (
        <>
          <Field label="供应商">
            <input
              value={String(node.config.provider ?? "openai")}
              onChange={(event) => updateNodeConfig(node.id, { provider: event.target.value })}
            />
          </Field>
          <Field label="模型">
            <input
              value={String(node.config.model ?? "gpt-4.1-mini")}
              onChange={(event) => updateNodeConfig(node.id, { model: event.target.value })}
            />
          </Field>
          <Field label="System Prompt">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="User Prompt">
            <textarea
              rows={5}
              value={String(node.config.userPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { userPrompt: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "final_answer")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "condition" && (
        <>
          <Field label="判断字段">
            <input
              value={String(node.config.field ?? "intent")}
              onChange={(event) => updateNodeConfig(node.id, { field: event.target.value })}
            />
          </Field>
          <Field label="操作符">
            <select
              value={String(node.config.operator ?? "equals")}
              onChange={(event) => updateNodeConfig(node.id, { operator: event.target.value })}
            >
              <option value="equals">等于</option>
              <option value="not_equals">不等于</option>
              <option value="contains">包含</option>
              <option value="not_contains">不包含</option>
              <option value="is_empty">为空</option>
              <option value="is_not_empty">不为空</option>
            </select>
          </Field>
          <Field label="比较值">
            <input
              value={String(node.config.value ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { value: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="True 分支">
              <input
                value={String(node.config.trueBranch ?? "true")}
                onChange={(event) => updateNodeConfig(node.id, { trueBranch: event.target.value })}
              />
            </Field>
            <Field label="False 分支">
              <input
                value={String(node.config.falseBranch ?? "false")}
                onChange={(event) => updateNodeConfig(node.id, { falseBranch: event.target.value })}
              />
            </Field>
          </div>
          <Field label="Fallback">
            <input
              value={String(node.config.fallback ?? "fallback")}
              onChange={(event) => updateNodeConfig(node.id, { fallback: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "http" && (
        <>
          <Field label="Method">
            <select
              value={String(node.config.method ?? "GET")}
              onChange={(event) => updateNodeConfig(node.id, { method: event.target.value })}
            >
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((method) => (
                <option key={method} value={method}>{method}</option>
              ))}
            </select>
          </Field>
          <Field label="URL">
            <input
              value={String(node.config.url ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { url: event.target.value })}
            />
          </Field>
          <Field label="Auth Secret (.env key)">
            <input
              value={String(node.config.authSecret ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { authSecret: event.target.value })}
              placeholder="ORDER_API_TOKEN"
            />
          </Field>
          <Field label="Body">
            <textarea
              rows={5}
              value={String(node.config.body ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { body: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "http_response")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "direct_reply" && (
        <>
          <Field label="回复模板">
            <textarea
              rows={7}
              value={String(node.config.template ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { template: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "final_answer")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "custom_function" && (
        <>
          <Field label="Python 函数体">
            <textarea
              className="code-area"
              rows={12}
              value={String(node.config.code ?? "return {}")}
              onChange={(event) => updateNodeConfig(node.id, { code: event.target.value })}
            />
          </Field>
          <Field label="非 dict 返回时写入">
            <input
              value={String(node.config.outputField ?? "custom_output")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
    </aside>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function stateFieldsToText(fields: StateField[]): string {
  return fields.map((field) => `${field.name}:${field.type}`).join("\n");
}

function parseStateFields(value: string): StateField[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, type = "str"] = line.split(":");
      return { name: name.trim(), type: type.trim(), description: "" };
    })
    .filter((field) => Boolean(field.name));
}

