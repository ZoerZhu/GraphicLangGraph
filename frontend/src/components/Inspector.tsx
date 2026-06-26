import { useMemo, useState, type ReactNode } from "react";
import { Plus, RefreshCw, Trash2, X } from "lucide-react";
import { inspectWorkspaceMcpServer, listDataShapingPaths, previewDataShapingNode } from "../lib/api";
import { useProjectStore } from "../store/projectStore";
import type { DataShapingPath, DataShapingPreviewResult, ImportedAgentConfig, MCPServerConfig, McpInspectResult, McpToolInspection, ModelConfig, NodeIR, ProjectListItem, RagKnowledgeBaseConfig, ResourceGroupConfig, SkillConfig, StateField, ToolConfig } from "../types";
import { FloatingPanel } from "./FloatingPanel";

export function Inspector() {
  const project = useProjectStore((state) => state.project);
  const selectedNodeId = useProjectStore((state) => state.selectedNodeId);
  const runActive = useProjectStore((state) => state.runActive);
  const selectNode = useProjectStore((state) => state.selectNode);
  const projects = useProjectStore((state) => state.projects);
  const workspaceTools = useProjectStore((state) => state.workspaceTools);
  const workspaceSkills = useProjectStore((state) => state.workspaceSkills);
  const workspaceMcpServers = useProjectStore((state) => state.workspaceMcpServers);
  const workspaceModelConfigs = useProjectStore((state) => state.workspaceModelConfigs);
  const workspaceRagKnowledgeBases = useProjectStore((state) => state.workspaceRagKnowledgeBases);
  const workspaceResourceGroups = useProjectStore((state) => state.workspaceResourceGroups);
  const runInput = useProjectStore((state) => state.runInput);
  const runHistoryRecords = useProjectStore((state) => state.runHistoryRecords);
  const selectedRunHistoryId = useProjectStore((state) => state.selectedRunHistoryId);
  const selectedRunModelConfigId = useProjectStore((state) => state.selectedRunModelConfigId);
  const updateNode = useProjectStore((state) => state.updateNode);
  const updateNodeConfig = useProjectStore((state) => state.updateNodeConfig);
  const updateSkills = useProjectStore((state) => state.updateSkills);
  const updateImportedAgents = useProjectStore((state) => state.updateImportedAgents);
  const setStateFields = useProjectStore((state) => state.setStateFields);
  const [mcpInspecting, setMcpInspecting] = useState(false);
  const [mcpInspectResult, setMcpInspectResult] = useState<McpInspectResult | null>(null);
  const [dataPaths, setDataPaths] = useState<DataShapingPath[]>([]);
  const [dataPreview, setDataPreview] = useState<DataShapingPreviewResult | null>(null);
  const [dataPreviewing, setDataPreviewing] = useState(false);

  const node = useMemo(
    () => project?.nodes.find((item) => item.id === selectedNodeId) ?? null,
    [project?.nodes, selectedNodeId],
  );
  const availableTools = useMemo(() => mergeById([...(project?.tools ?? []), ...workspaceTools]), [project?.tools, workspaceTools]);
  const availableSkills = useMemo(
    () => mergeById([...(project?.skills ?? []), ...workspaceSkills]).filter((skill) => skill.enabled),
    [project?.skills, workspaceSkills],
  );
  const availableToolGroups = useMemo(
    () => workspaceResourceGroups.filter((group) => group.resourceType === "tool"),
    [workspaceResourceGroups],
  );
  const availableSkillGroups = useMemo(
    () => workspaceResourceGroups.filter((group) => group.resourceType === "skill"),
    [workspaceResourceGroups],
  );
  const availableMcpServers = useMemo(
    () => mergeById([...(project?.mcpServers ?? []), ...workspaceMcpServers]),
    [project?.mcpServers, workspaceMcpServers],
  );
  const availableAgents = useMemo(
    () => projects.filter((item) => item.kind === "agent" && item.id !== project?.project.id),
    [project?.project.id, projects],
  );
  const availableImportedAgents = useMemo(() => project?.importedAgents ?? [], [project?.importedAgents]);
  const availableAgentResources = useMemo(
    () => mergeAgentResources(availableImportedAgents, availableAgents),
    [availableAgents, availableImportedAgents],
  );
  const availableModelConfigs = useMemo(() => buildModelConfigOptions(workspaceModelConfigs), [workspaceModelConfigs]);
  const selectedRunModelConfig = useMemo(
    () => workspaceModelConfigs.find((config) => config.id === selectedRunModelConfigId && config.enabled),
    [selectedRunModelConfigId, workspaceModelConfigs],
  );
  const availableRagKnowledgeBases = useMemo(() => workspaceRagKnowledgeBases.filter((item) => item.enabled), [workspaceRagKnowledgeBases]);
  const detectedStateFields = useMemo(() => detectStateFieldsFromNodes(project?.nodes ?? []), [project?.nodes]);
  const resourceInspector = Boolean(node && ["agent", "tool", "parallel_tools", "mcp_node"].includes(node.type));

  function updateToolSelection(targetNode: NodeIR, directIds: string[], groupIds: string[]) {
    const availableIds = new Set(availableTools.map((tool) => tool.id));
    const groupIdsSet = new Set(groupIds);
    const groupedToolIds = availableToolGroups
      .filter((group) => groupIdsSet.has(group.id))
      .flatMap((group) => group.itemIds);
    const ids = uniqueStrings([...groupedToolIds, ...directIds]).filter((id) => availableIds.has(id));
    const selectedTools = availableTools.filter((tool) => ids.includes(tool.id));
    updateNodeConfig(targetNode.id, {
      toolDirectIdsJson: JSON.stringify(directIds.filter((id) => availableIds.has(id))),
      toolGroupIdsJson: JSON.stringify(groupIds),
      toolIdsJson: JSON.stringify(ids),
      toolRegistryJson: JSON.stringify(selectedTools),
      tools: selectedTools.map((tool) => tool.name).join(","),
    });
  }

  function updateSkillSelection(targetNode: NodeIR, directIds: string[], groupIds: string[]) {
    const availableIds = new Set(availableSkills.map((skill) => skill.id));
    const groupIdsSet = new Set(groupIds);
    const groupedSkillIds = availableSkillGroups
      .filter((group) => groupIdsSet.has(group.id))
      .flatMap((group) => group.itemIds);
    const ids = uniqueStrings([...groupedSkillIds, ...directIds]).filter((id) => availableIds.has(id));
    if (project) {
      const selectedSkillConfigs = availableSkills.filter((skill) => ids.includes(skill.id));
      updateSkills(mergeById([...(project.skills ?? []), ...selectedSkillConfigs]));
    }
    updateNodeConfig(targetNode.id, {
      skillDirectIdsJson: JSON.stringify(directIds.filter((id) => availableIds.has(id))),
      skillGroupIdsJson: JSON.stringify(groupIds),
      skillIdsJson: JSON.stringify(ids),
    });
  }

  function updateMcpSelection(targetNode: NodeIR, directIds: string[]) {
    const availableIds = new Set(availableMcpServers.map((server) => server.id));
    const ids = uniqueStrings(directIds).filter((id) => availableIds.has(id));
    const selectedServers = availableMcpServers.filter((server) => ids.includes(server.id));
    updateNodeConfig(targetNode.id, {
      mcpServerIdsJson: JSON.stringify(ids),
      mcpServerRegistryJson: JSON.stringify(selectedServers),
    });
  }

  function updateAgentSelection(targetNode: NodeIR, directIds: string[]) {
    const availableIds = new Set(availableAgentResources.map((agent) => agent.id));
    const ids = uniqueStrings(directIds).filter((id) => availableIds.has(id));
    const selectedAgents = availableAgentResources.filter((agent) => ids.includes(agent.id));
    if (project) {
      updateImportedAgents(mergeAgentResources(project.importedAgents ?? [], selectedAgents));
    }
    updateNodeConfig(targetNode.id, {
      agentIdsJson: JSON.stringify(ids),
      agentRegistryJson: JSON.stringify(selectedAgents),
    });
  }

  async function refreshMcpToolsForNode(targetNode: NodeIR) {
    const server = mcpServerForNode(targetNode, availableMcpServers);
    if (!server) {
      setMcpInspectResult({
        ok: false,
        serverId: "",
        serverName: "",
        transport: "",
        tools: [],
        warnings: [],
        durationMs: 0,
        error: "请先绑定 MCP Server。",
      });
      return;
    }
    setMcpInspecting(true);
    setMcpInspectResult(null);
    try {
      const result = await inspectWorkspaceMcpServer(server);
      setMcpInspectResult(result);
      if (result.ok) {
        const selectedTool = result.tools.find((tool) => tool.name === targetNode.config.toolName);
        updateNodeConfig(targetNode.id, {
          mcpToolsJson: JSON.stringify(result.tools),
          toolInputSchemaJson: JSON.stringify(selectedTool?.inputSchema ?? {}),
        });
      }
    } catch (error) {
      setMcpInspectResult({
        ok: false,
        serverId: server.id,
        serverName: server.name,
        transport: server.transport,
        tools: [],
        warnings: [],
        durationMs: 0,
        error: error instanceof Error ? error.message : "MCP 工具刷新失败。",
      });
    } finally {
      setMcpInspecting(false);
    }
  }

  async function refreshDataShapingPaths() {
    if (!project) return;
    const runId = selectedRunHistoryId ?? runHistoryRecords[0]?.id ?? "";
    const result = await listDataShapingPaths(project.project.id, parseJsonRecord(runInput), runId);
    setDataPaths(result.paths);
  }

  async function previewDataShaping(targetNode: NodeIR) {
    if (!project) return;
    setDataPreviewing(true);
    try {
      const runId = selectedRunHistoryId ?? runHistoryRecords[0]?.id ?? "";
      const result = await previewDataShapingNode(project.project.id, targetNode.id, parseJsonRecord(runInput), runId, selectedRunModelConfig);
      setDataPreview(result);
      if (result.paths) setDataPaths(result.paths);
    } catch (error) {
      setDataPreview({
        ok: false,
        nodeId: targetNode.id,
        nodeType: targetNode.type,
        inputs: {},
        delta: {},
        detail: "",
        errors: [error instanceof Error ? error.message : "预览失败"],
      });
    } finally {
      setDataPreviewing(false);
    }
  }

  if (!project || !node || runActive) {
    return null;
  }

  return (
    <FloatingPanel
      title="检查器"
      subtitle={node.type}
      className="inspector-panel"
      initialRect={resourceInspector ? resourceInspectorInitialRect : inspectorInitialRect}
      minWidth={resourceInspector ? 560 : 320}
      minHeight={320}
      maxWidth={resourceInspector ? 820 : 560}
      actions={
        <button className="icon-only panel-close" onClick={() => selectNode(null)} title="关闭检查器" type="button">
          <X size={15} />
        </button>
      }
    >
      <div className="inspector-panel__scroll">
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
          <StateFieldEditor
            fields={project.state.fields}
            detectedFields={detectedStateFields}
            onChange={setStateFields}
          />
        </>
      )}
      {node.type === "llm" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            updateNodeConfig={updateNodeConfig}
          />
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
      {node.type === "agent" && (
        <InspectorSplit
          left={
            <>
              <ResourceSelectionRail
                title="Skill 配置"
                itemLabel="Skill"
                groups={availableSkillGroups}
                items={availableSkills}
                selectedGroupIds={parseStringList(node.config.skillGroupIdsJson)}
                selectedDirectIds={directResourceIdsFromConfig(node.config, "skillIdsJson", "skillDirectIdsJson", "skillGroupIdsJson", availableSkillGroups)}
                emptyText="还没有可用 Skill。请先在管理页 Skills 中新增或导入。"
                onChange={(directIds, groupIds) => updateSkillSelection(node, directIds, groupIds)}
                renderItemMeta={(skill) => skill.description || skill.filePath || "未填写描述"}
              />
              <ResourceSelectionRail
                title="MCP Server"
                itemLabel="MCP"
                groups={[]}
                items={availableMcpServers.filter((server) => server.enabled)}
                selectedGroupIds={[]}
                selectedDirectIds={parseStringList(node.config.mcpServerIdsJson)}
                emptyText="还没有可用 MCP。请先在管理页 MCP 中新增或导入。"
                onChange={(directIds) => updateMcpSelection(node, directIds)}
                renderItemMeta={(server) => `${server.transport || "stdio"} · ${server.command || server.url || "未配置入口"}`}
              />
              <ResourceSelectionRail
                title="Agent 接入"
                itemLabel="Agent"
                groups={[]}
                items={availableAgentResources}
                selectedGroupIds={[]}
                selectedDirectIds={parseStringList(node.config.agentIdsJson)}
                emptyText="还没有可接入 Agent。请先在 Agent 管理中创建 Agent。"
                onChange={(directIds) => updateAgentSelection(node, directIds)}
                renderItemMeta={(agent) => `${agent.role || "sub_agent"} · ${agent.projectId || "未绑定项目"}`}
              />
            </>
          }
        >
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="Agent 指令">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="可用工具 ID（逗号分隔）">
            <input
              value={String(node.config.tools ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { tools: event.target.value })}
              placeholder="get_order,refund_policy"
            />
          </Field>
          <Field label="用户输入">
            <textarea
              rows={4}
              value={String(node.config.userPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { userPrompt: event.target.value })}
              placeholder="{{ state.messages }}"
            />
          </Field>
          <div className="inline-grid">
            <Field label="最大迭代">
              <input
                type="number"
                min={1}
                value={String(node.config.maxIterations ?? 4)}
                onChange={(event) => updateNodeConfig(node.id, { maxIterations: Number(event.target.value) })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "agent_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </InspectorSplit>
      )}
      {node.type === "tool" && (
        <InspectorSplit
          left={
            <ResourceSelectionRail
              title="Tool 配置"
              itemLabel="Tool"
              groups={availableToolGroups}
              items={availableTools}
              selectedGroupIds={parseStringList(node.config.toolGroupIdsJson)}
              selectedDirectIds={directResourceIdsFromConfig(node.config, "toolIdsJson", "toolDirectIdsJson", "toolGroupIdsJson", availableToolGroups)}
              emptyText="还没有可用 Tool。请先在管理页 Tools 中导入、安装或新增。"
              onChange={(directIds, groupIds) => updateToolSelection(node, directIds, groupIds)}
              renderItemMeta={(tool) => `${tool.source || "tool"} · ${tool.description || "未填写描述"}`}
              renderItemExtra={(tool) => <ToolUsageTags tool={tool} />}
            />
          }
        >
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            providerLabel="决策模型配置"
            providerManualLabel="决策模型供应商标识"
            providerNote="这是 Tools Agent 用来判断、规划并反复调用工具的模型，不是 Tool 的供应商。"
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="Tools Agent 指令">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <Field label="用户输入">
            <textarea
              rows={4}
              value={String(node.config.userPrompt ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { userPrompt: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="最大调用轮次">
              <input
                type="number"
                min={1}
                value={String(node.config.maxIterations ?? 4)}
                onChange={(event) => updateNodeConfig(node.id, { maxIterations: Number(event.target.value) })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "tools_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </InspectorSplit>
      )}
      {node.type === "task_splitter" && (
        <>
          <Field label="规划输入字段">
            <input
              value={String(node.config.inputField ?? "task_plan")}
              onChange={(event) => updateNodeConfig(node.id, { inputField: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="任务输出字段">
              <input
                value={String(node.config.outputField ?? "worker_tasks")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
            <Field label="最大任务数">
              <input
                type="number"
                min={1}
                max={10}
                value={String(node.config.maxTasks ?? 5)}
                onChange={(event) => updateNodeConfig(node.id, { maxTasks: Number(event.target.value) })}
              />
            </Field>
          </div>
          <Field label="解析失败兜底">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={node.config.fallbackToSingleTask !== false}
                onChange={(event) => updateNodeConfig(node.id, { fallbackToSingleTask: event.target.checked })}
              />
              <span>无法解析任务 JSON 时，用用户问题生成一个单任务</span>
            </label>
          </Field>
        </>
      )}
      {node.type === "parallel_tools" && (
        <InspectorSplit
          left={
            <ResourceSelectionRail
              title="Tool 配置"
              itemLabel="Tool"
              groups={availableToolGroups}
              items={availableTools}
              selectedGroupIds={parseStringList(node.config.toolGroupIdsJson)}
              selectedDirectIds={directResourceIdsFromConfig(node.config, "toolIdsJson", "toolDirectIdsJson", "toolGroupIdsJson", availableToolGroups)}
              emptyText="还没有可用 Tool。请先在管理页 Tools 中导入、安装或新增。"
              onChange={(directIds, groupIds) => updateToolSelection(node, directIds, groupIds)}
              renderItemMeta={(tool) => `${tool.source || "tool"} · ${tool.description || "未填写描述"}`}
              renderItemExtra={(tool) => <ToolUsageTags tool={tool} />}
            />
          }
        >
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            providerLabel="Worker 模型配置"
            providerManualLabel="Worker 模型供应商标识"
            providerNote="每个并行 Worker 都会使用这个模型自主选择并调用已选 Tools。"
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="Worker 指令">
            <textarea
              rows={5}
              value={String(node.config.systemPrompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { systemPrompt: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="任务字段">
              <input
                value={String(node.config.tasksField ?? "worker_tasks")}
                onChange={(event) => updateNodeConfig(node.id, { tasksField: event.target.value })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "worker_results")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
          <div className="inline-grid">
            <Field label="每任务轮次">
              <input
                type="number"
                min={1}
                max={12}
                value={String(node.config.maxIterationsPerTask ?? 6)}
                onChange={(event) => updateNodeConfig(node.id, { maxIterationsPerTask: Number(event.target.value) })}
              />
            </Field>
            <Field label="并发 Worker">
              <input
                type="number"
                min={1}
                max={6}
                value={String(node.config.maxConcurrentWorkers ?? 3)}
                onChange={(event) => updateNodeConfig(node.id, { maxConcurrentWorkers: Number(event.target.value) })}
              />
            </Field>
          </div>
          <Field label="保存调用记录">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(node.config.storeToolCalls)}
                onChange={(event) => updateNodeConfig(node.id, { storeToolCalls: event.target.checked })}
              />
              <span>仅调试时开启，会增加 worker_results 的体积</span>
            </label>
          </Field>
        </InspectorSplit>
      )}
      {isDataShapingNode(node.type) && (
        <DataShapingPreviewControls
          paths={dataPaths}
          preview={dataPreview?.nodeId === node.id ? dataPreview : null}
          previewing={dataPreviewing}
          onRefresh={() => void refreshDataShapingPaths()}
          onPreview={() => void previewDataShaping(node)}
        />
      )}
      {node.type === "variable_assign" && (
        <>
          <InputMappingsEditor
            value={node.config.inputMappingsJson}
            onChange={(value) => updateNodeConfig(node.id, { inputMappingsJson: value })}
            paths={dataPaths}
          />
          <AssignmentsEditor
            value={node.config.assignmentsJson}
            onChange={(value) => updateNodeConfig(node.id, { assignmentsJson: value })}
            paths={dataPaths}
          />
          <Field label="赋值摘要字段">
            <input
              value={String(node.config.resultField ?? "assignment_result")}
              onChange={(event) => updateNodeConfig(node.id, { resultField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "template" && (
        <>
          <InputMappingsEditor
            value={node.config.inputMappingsJson}
            onChange={(value) => updateNodeConfig(node.id, { inputMappingsJson: value })}
            paths={dataPaths}
          />
          <Field label="模板">
            <textarea
              rows={8}
              value={String(node.config.template ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { template: event.target.value })}
              placeholder="{{ state.messages }}"
            />
          </Field>
          <div className="inline-grid">
            <Field label="输出类型">
              <select value={String(node.config.outputType ?? "text")} onChange={(event) => updateNodeConfig(node.id, { outputType: event.target.value })}>
                <option value="text">text</option>
                <option value="json">json</option>
              </select>
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "template_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "json_extractor" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            providerLabel="抽取模型配置"
            providerManualLabel="抽取模型供应商"
            providerNote="该模型只负责把输入内容抽取成符合 Schema 的 JSON object。"
            updateNodeConfig={updateNodeConfig}
          />
          <InputMappingsEditor
            value={node.config.inputMappingsJson}
            onChange={(value) => updateNodeConfig(node.id, { inputMappingsJson: value })}
            paths={dataPaths}
          />
          <Field label="Schema 预设">
            <select value={String(node.config.schemaPreset ?? "")} onChange={(event) => updateNodeConfig(node.id, { schemaPreset: event.target.value })}>
              <option value="">自定义 Schema</option>
              <option value="task_plan_v1">Task Plan v1</option>
            </select>
          </Field>
          <Field label="输入文本模板">
            <textarea
              rows={3}
              value={String(node.config.inputText ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { inputText: event.target.value })}
            />
          </Field>
          <Field label="抽取说明">
            <textarea
              rows={3}
              value={String(node.config.instruction ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { instruction: event.target.value })}
            />
          </Field>
          <SchemaFieldsEditor
            value={node.config.schemaFieldsJson}
            onChange={(value) => updateNodeConfig(node.id, { schemaFieldsJson: value })}
          />
          <RepairFields node={node} updateNodeConfig={updateNodeConfig} />
          <div className="inline-grid">
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "extracted_json")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
            <Field label="校验结果字段">
              <input
                value={String(node.config.validationField ?? "validation_result")}
                onChange={(event) => updateNodeConfig(node.id, { validationField: event.target.value })}
              />
            </Field>
            <Field label="修复结果字段">
              <input
                value={String(node.config.repairResultField ?? "repair_result")}
                onChange={(event) => updateNodeConfig(node.id, { repairResultField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "json_validator" && (
        <>
          <Field label="输入字段">
            <input
              value={String(node.config.inputField ?? "extracted_json")}
              onChange={(event) => updateNodeConfig(node.id, { inputField: event.target.value })}
            />
          </Field>
          <Field label="Schema 预设">
            <select value={String(node.config.schemaPreset ?? "")} onChange={(event) => updateNodeConfig(node.id, { schemaPreset: event.target.value })}>
              <option value="">自定义 Schema</option>
              <option value="task_plan_v1">Task Plan v1</option>
            </select>
          </Field>
          <SchemaFieldsEditor
            value={node.config.schemaFieldsJson}
            onChange={(value) => updateNodeConfig(node.id, { schemaFieldsJson: value })}
          />
          {Boolean(node.config.repairEnabled) ? (
            <ModelSelectionFields
              config={node.config}
              defaultModel="gpt-4.1-mini"
              defaultProvider="openai"
              modelConfigs={availableModelConfigs}
              nodeId={node.id}
              providerLabel="修复模型配置"
              providerManualLabel="修复模型供应商"
              providerNote="仅在校验失败且开启修复时调用模型。"
              updateNodeConfig={updateNodeConfig}
            />
          ) : null}
          <RepairFields node={node} updateNodeConfig={updateNodeConfig} />
          <div className="inline-grid">
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "validated_json")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
            <Field label="校验结果字段">
              <input
                value={String(node.config.validationField ?? "validation_result")}
                onChange={(event) => updateNodeConfig(node.id, { validationField: event.target.value })}
              />
            </Field>
            <Field label="修复结果字段">
              <input
                value={String(node.config.repairResultField ?? "repair_result")}
                onChange={(event) => updateNodeConfig(node.id, { repairResultField: event.target.value })}
              />
            </Field>
          </div>
        </>
      )}
      {node.type === "for_each" && (
        <>
          <Field label="迭代数组字段">
            <input
              value={String(node.config.itemsField ?? "worker_tasks")}
              onChange={(event) => updateNodeConfig(node.id, { itemsField: event.target.value })}
            />
            <small className="model-config-note">读取 state 中的数组字段；也支持形如 {"{ tasks: [] }"} 的任务规划对象。</small>
          </Field>
          <div className="inline-grid">
            <Field label="Item 字段">
              <input
                value={String(node.config.itemField ?? "current_item")}
                onChange={(event) => updateNodeConfig(node.id, { itemField: event.target.value })}
              />
            </Field>
            <Field label="Index 字段">
              <input
                value={String(node.config.indexField ?? "current_index")}
                onChange={(event) => updateNodeConfig(node.id, { indexField: event.target.value })}
              />
            </Field>
          </div>
          <div className="inline-grid">
            <Field label="最大迭代项">
              <input
                type="number"
                min={1}
                max={100}
                value={String(node.config.maxItems ?? 50)}
                onChange={(event) => updateNodeConfig(node.id, { maxItems: Number(event.target.value) })}
              />
            </Field>
            <Field label="迭代摘要字段">
              <input
                value={String(node.config.resultField ?? "")}
                onChange={(event) => updateNodeConfig(node.id, { resultField: event.target.value })}
                placeholder="留空则不写入"
              />
            </Field>
          </div>
          <small className="model-config-note">从 item 端口连接循环体首节点，循环体末尾连接 Merge；error 端口用于整体异常兜底。</small>
        </>
      )}
      {node.type === "merge" && (
        <>
          <ReducersEditor
            value={node.config.reducersJson}
            onChange={(value) => updateNodeConfig(node.id, { reducersJson: value })}
          />
          <Field label="聚合摘要字段">
            <input
              value={String(node.config.resultField ?? "merge_result")}
              onChange={(event) => updateNodeConfig(node.id, { resultField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "error_handler" && (
        <>
          <Field label="错误字段">
            <input
              value={String(node.config.errorField ?? "last_error")}
              onChange={(event) => updateNodeConfig(node.id, { errorField: event.target.value })}
            />
          </Field>
          <Field label="错误模板">
            <textarea
              rows={5}
              value={String(node.config.template ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { template: event.target.value })}
              placeholder="流程执行失败：{{ state.last_error }}"
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "error_result")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "retriever" && (
        <>
          <Field label="绑定 RAG 知识库">
            <select
              value={String(node.config.knowledgeBaseId ?? "")}
              onChange={(event) => {
                const knowledgeBase = availableRagKnowledgeBases.find((item) => item.id === event.target.value);
                if (!knowledgeBase) {
                  updateNodeConfig(node.id, { knowledgeBaseId: "", knowledgeBaseName: "" });
                  return;
                }
                updateNodeConfig(node.id, {
                  knowledgeBaseId: knowledgeBase.id,
                  knowledgeBaseName: knowledgeBase.name,
                  source: retrieverSourceFromKnowledgeBase(knowledgeBase),
                  path: retrieverPathFromKnowledgeBase(knowledgeBase),
                  endpoint: knowledgeBase.url,
                  collection: knowledgeBase.collection,
                  topK: knowledgeBase.topK,
                  knowledgeBaseDescription: knowledgeBase.description,
                  embeddingModel: knowledgeBase.embeddingModel,
                  metadataJson: knowledgeBase.metadataJson,
                });
                updateNode(node.id, { label: knowledgeBase.name });
              }}
            >
              <option value="">未绑定，手动配置</option>
              {availableRagKnowledgeBases.map((knowledgeBase) => (
                <option key={knowledgeBase.id} value={knowledgeBase.id}>
                  {knowledgeBase.name} · {ragSourceLabel(knowledgeBase.sourceType)}
                </option>
              ))}
            </select>
            <small className="model-config-note">从管理页「RAG」中已配置的知识库选择。</small>
          </Field>
          <Field label="数据源类型">
            <select value={String(node.config.source ?? "local")} onChange={(event) => updateNodeConfig(node.id, { source: event.target.value })}>
              <option value="local">本地目录</option>
              <option value="files">本地文件集合</option>
              <option value="vectorstore">已有向量库</option>
              <option value="http">HTTP 检索 API</option>
              <option value="database">数据库 / 表</option>
            </select>
          </Field>
          <Field label="知识库路径 / Endpoint">
            <input
              value={String(node.config.path ?? "./knowledge")}
              onChange={(event) => updateNodeConfig(node.id, { path: event.target.value })}
            />
          </Field>
          <Field label="Query 来源">
            <textarea
              rows={3}
              value={String(node.config.query ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { query: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="Top K">
              <input
                type="number"
                min={1}
                value={String(node.config.topK ?? 4)}
                onChange={(event) => updateNodeConfig(node.id, { topK: Number(event.target.value) })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "retrieved_context")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
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
      {node.type === "ai_router" && (
        <>
          <ModelSelectionFields
            config={node.config}
            defaultModel="gpt-4.1-mini"
            defaultProvider="openai"
            modelConfigs={availableModelConfigs}
            nodeId={node.id}
            updateNodeConfig={updateNodeConfig}
          />
          <Field label="路由模式">
            <select
              value={String(node.config.routeMode ?? "keyword")}
              onChange={(event) => updateNodeConfig(node.id, { routeMode: event.target.value })}
            >
              <option value="keyword">关键词 fallback</option>
              <option value="llm">LLM 路由</option>
            </select>
          </Field>
          <Field label="路由说明">
            <textarea
              rows={4}
              value={String(node.config.instruction ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { instruction: event.target.value })}
            />
          </Field>
          <Field label="输入文本">
            <textarea
              rows={3}
              value={String(node.config.inputText ?? "{{ state.messages }}")}
              onChange={(event) => updateNodeConfig(node.id, { inputText: event.target.value })}
            />
          </Field>
          <Field label="场景列表（key:中文名:关键词逗号分隔）">
            <textarea
              rows={6}
              value={String(node.config.scenarios ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { scenarios: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="路由字段">
              <input
                value={String(node.config.routeField ?? "route_key")}
                onChange={(event) => updateNodeConfig(node.id, { routeField: event.target.value })}
              />
            </Field>
            <Field label="Fallback">
              <input
                value={String(node.config.fallback ?? "other")}
                onChange={(event) => updateNodeConfig(node.id, { fallback: event.target.value })}
              />
            </Field>
          </div>
          <Field label="Reason 字段">
            <input
              value={String(node.config.reasonField ?? "route_reason")}
              onChange={(event) => updateNodeConfig(node.id, { reasonField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "human_approval" && (
        <>
          <Field label="审批提示">
            <textarea
              rows={4}
              value={String(node.config.prompt ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { prompt: event.target.value })}
            />
          </Field>
          <div className="inline-grid">
            <Field label="默认动作">
              <select
                value={String(node.config.defaultAction ?? "approved")}
                onChange={(event) => updateNodeConfig(node.id, { defaultAction: event.target.value })}
              >
                <option value="approved">通过</option>
                <option value="rejected">拒绝</option>
                <option value="edit">修改</option>
              </select>
            </Field>
            <Field label="Fallback">
              <input
                value={String(node.config.fallback ?? "rejected")}
                onChange={(event) => updateNodeConfig(node.id, { fallback: event.target.value })}
              />
            </Field>
          </div>
          <div className="inline-grid">
            <Field label="动作字段">
              <input
                value={String(node.config.actionField ?? "approval_action")}
                onChange={(event) => updateNodeConfig(node.id, { actionField: event.target.value })}
              />
            </Field>
            <Field label="输出字段">
              <input
                value={String(node.config.outputField ?? "approval_result")}
                onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
              />
            </Field>
          </div>
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
          <Field label="预览 Mock 响应">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(node.config.mockEnabled)}
                onChange={(event) => updateNodeConfig(node.id, { mockEnabled: event.target.checked })}
              />
              <span>启用 mock，live preview 和导出样板会使用下方 JSON，不请求真实接口</span>
            </label>
          </Field>
          <Field label="Mock JSON">
            <textarea
              className="code-area"
              rows={6}
              value={String(node.config.mockResponseJson ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { mockResponseJson: event.target.value })}
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
      {node.type === "skill_node" && (
        <>
          <Field label="绑定 Skill">
            <select
              value={String(node.config.skillId ?? node.config.toolId ?? "")}
              onChange={(event) => {
                const skill = availableSkills.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  skillId: skill?.id ?? "",
                  skillName: skill?.name ?? "未选择 Skill",
                  skillContent: skill?.content ?? "",
                  sourcePath: skill?.sourcePath ?? "",
                  filePath: skill?.filePath ?? "",
                });
                if (skill) updateNode(node.id, { label: skill.name });
              }}
            >
              <option value="">未选择</option>
              {availableSkills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="来源">
            <input value={String(node.config.sourcePath ?? "")} onChange={(event) => updateNodeConfig(node.id, { sourcePath: event.target.value })} />
          </Field>
          <Field label="内容">
            <textarea
              rows={8}
              value={String(node.config.skillContent ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { skillContent: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "skill_result")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      {node.type === "mcp_node" && (() => {
        const mcpTools = parseMcpToolList(node.config.mcpToolsJson);
        const toolSelectionMode = String(node.config.toolSelectionMode ?? "heuristic");
        return (
        <>
          <Field label="绑定 MCP Server">
            <select
              value={String(node.config.serverId ?? "")}
              onChange={(event) => {
                const server = availableMcpServers.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  serverId: server?.id ?? "",
                  serverName: server?.name ?? "未选择 MCP",
                  transport: server?.transport ?? "stdio",
                  command: server?.command ?? "",
                  url: server?.url ?? "",
                  mcpServerSnapshotJson: server ? JSON.stringify([server]) : "[]",
                  mcpToolsJson: "[]",
                  toolName: "",
                  toolInputSchemaJson: "{}",
                });
                if (server) updateNode(node.id, { label: server.name });
              }}
            >
              <option value="">未选择</option>
              {availableMcpServers.map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Transport">
            <select value={String(node.config.transport ?? "stdio")} onChange={(event) => updateNodeConfig(node.id, { transport: event.target.value })}>
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
          </Field>
          <Field label="Command">
            <input value={String(node.config.command ?? "")} onChange={(event) => updateNodeConfig(node.id, { command: event.target.value })} />
          </Field>
          <Field label="URL">
            <input value={String(node.config.url ?? "")} onChange={(event) => updateNodeConfig(node.id, { url: event.target.value })} />
          </Field>
          <Field label="工具选择方式">
            <select
              value={toolSelectionMode}
              onChange={(event) => updateNodeConfig(node.id, { toolSelectionMode: event.target.value })}
            >
              <option value="model">模型选择</option>
              <option value="heuristic">启发式自动</option>
              <option value="manual">手动选择</option>
            </select>
            <small className="model-config-note">已选择 MCP Tool 时会直接调用；未选择时按这里的模式选择工具。</small>
          </Field>
          {toolSelectionMode === "model" ? (
            <>
              <ModelSelectionFields
                config={node.config}
                defaultModel="gpt-4.1-mini"
                defaultProvider="openai"
                fieldNames={{
                  provider: "toolSelectionModelProvider",
                  model: "toolSelectionModel",
                  modelConfigId: "toolSelectionModelConfigId",
                  modelConfigName: "toolSelectionModelConfigName",
                  modelDisplayName: "toolSelectionModelDisplayName",
                  baseUrl: "toolSelectionBaseUrl",
                  apiKeyEnv: "toolSelectionApiKeyEnv",
                  apiVersion: "toolSelectionApiVersion",
                  organization: "toolSelectionOrganization",
                  apiFormat: "toolSelectionApiFormat",
                }}
                modelConfigs={availableModelConfigs}
                nodeId={node.id}
                providerLabel="选择模型配置"
                providerManualLabel="选择模型供应商"
                providerNote="该模型只负责从 MCP Server 暴露的工具中选择一个工具并生成参数。"
                updateNodeConfig={updateNodeConfig}
              />
              <Field label="选择指令">
                <textarea
                  rows={3}
                  value={String(node.config.toolSelectionInstruction ?? "")}
                  onChange={(event) => updateNodeConfig(node.id, { toolSelectionInstruction: event.target.value })}
                  placeholder="搜索网页时优先 web_search_exa，抓取 URL 时使用 web_fetch_exa"
                />
              </Field>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={Boolean(node.config.fallbackToHeuristic)}
                  onChange={(event) => updateNodeConfig(node.id, { fallbackToHeuristic: event.target.checked })}
                />
                <span>模型选择失败时回退到启发式自动选择</span>
              </label>
            </>
          ) : null}
          <div className="mcp-inspector-actions">
            <button disabled={mcpInspecting} onClick={() => void refreshMcpToolsForNode(node)} type="button">
              <RefreshCw size={15} />
              <span>{mcpInspecting ? "刷新中" : "刷新工具"}</span>
            </button>
          </div>
          {mcpInspectResult ? (
            <small className={`rag-inspect-status ${mcpInspectResult.ok ? "" : "is-error"}`}>
              {mcpInspectResult.ok ? `发现 ${mcpInspectResult.tools.length} 个 MCP Tool` : mcpInspectResult.error || "MCP 工具刷新失败"}
            </small>
          ) : null}
          <Field label="MCP Tool">
            <select
              value={String(node.config.toolName ?? "")}
              onChange={(event) => {
                const tool = mcpTools.find((item) => item.name === event.target.value);
                updateNodeConfig(node.id, {
                  toolName: tool?.name ?? "",
                  toolInputSchemaJson: JSON.stringify(tool?.inputSchema ?? {}),
                });
              }}
            >
              <option value="">未选择</option>
              {mcpTools.map((tool) => (
                <option key={tool.name} value={tool.name}>
                  {tool.name}
                </option>
              ))}
            </select>
            <small className="model-config-note">
              {mcpTools.length
                ? "可选择要调用的 MCP Tool；不选择时运行时按工具选择方式处理。"
                : "先点击刷新工具读取 MCP Server 暴露的工具；不选择时运行时会自动读取并按工具选择方式处理。"}
            </small>
          </Field>
          <Field label="参数 JSON">
            <textarea
              className="code-area"
              rows={6}
              value={String(node.config.toolArgsJson ?? "{}")}
              onChange={(event) => updateNodeConfig(node.id, { toolArgsJson: event.target.value })}
              placeholder={'{ "query": "{{ state.messages }}" }'}
            />
          </Field>
          <Field label="输入 Schema">
            <textarea className="code-area" rows={5} readOnly value={String(node.config.toolInputSchemaJson ?? "{}")} />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "mcp_result")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
        );
      })()}
      {node.type === "agent_ref" && (
        <>
          <Field label="绑定 Agent">
            <select
              value={String(node.config.agentProjectId ?? "")}
              onChange={(event) => {
                const agent = availableAgents.find((item) => item.id === event.target.value);
                updateNodeConfig(node.id, {
                  agentProjectId: agent?.id ?? "",
                  agentName: agent?.name ?? "未选择 Agent",
                });
                if (agent) updateNode(node.id, { label: agent.name });
              }}
            >
              <option value="">未选择</option>
              {availableAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="通信协议">
            <select value={String(node.config.protocol ?? "handoff")} onChange={(event) => updateNodeConfig(node.id, { protocol: event.target.value })}>
              <option value="handoff">handoff</option>
              <option value="delegate">delegate</option>
              <option value="broadcast">broadcast</option>
              <option value="review">review</option>
            </select>
          </Field>
          <Field label="通信说明">
            <textarea
              rows={4}
              value={String(node.config.instruction ?? "")}
              onChange={(event) => updateNodeConfig(node.id, { instruction: event.target.value })}
            />
          </Field>
          <Field label="输出字段">
            <input
              value={String(node.config.outputField ?? "agent_ref_result")}
              onChange={(event) => updateNodeConfig(node.id, { outputField: event.target.value })}
            />
          </Field>
        </>
      )}
      </div>
    </FloatingPanel>
  );
}

function DataShapingPreviewControls({
  paths,
  preview,
  previewing,
  onRefresh,
  onPreview,
}: {
  paths: DataShapingPath[];
  preview: DataShapingPreviewResult | null;
  previewing: boolean;
  onRefresh: () => void;
  onPreview: () => void;
}) {
  return (
    <section className="config-preview">
      <div className="config-table__head">
        <span>数据预览</span>
        <span className="history-record__actions">
          <button type="button" onClick={onRefresh}>
            <RefreshCw size={14} />
            刷新字段
          </button>
          <button type="button" disabled={previewing} onClick={onPreview}>
            <RefreshCw size={14} />
            {previewing ? "预览中" : "预览节点"}
          </button>
        </span>
      </div>
      <small className="model-config-note">字段来源：State 声明、节点输出、当前或选中运行历史。已发现 {paths.length} 个路径。</small>
      {preview ? (
        <RuntimePreviewBlock value={preview} />
      ) : null}
    </section>
  );
}

function RuntimePreviewBlock({ value }: { value: DataShapingPreviewResult }) {
  const shown = {
    ok: value.ok,
    detail: value.detail,
    errors: value.errors,
    inputs: value.inputs,
    delta: value.delta,
    validation: value.validation,
    repair: value.repair,
  };
  return <pre className="code-preview">{JSON.stringify(shown, null, 2)}</pre>;
}

function RepairFields({ node, updateNodeConfig }: { node: NodeIR; updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void }) {
  return (
    <>
      <Field label="校验失败自动修复">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={Boolean(node.config.repairEnabled)}
            onChange={(event) => updateNodeConfig(node.id, { repairEnabled: event.target.checked })}
          />
          <span>失败时调用模型尝试修复一次</span>
        </label>
      </Field>
      <Field label="修复说明">
        <textarea
          rows={3}
          value={String(node.config.repairInstruction ?? "")}
          onChange={(event) => updateNodeConfig(node.id, { repairInstruction: event.target.value })}
        />
      </Field>
    </>
  );
}

function PathDatalist({ id, paths }: { id: string; paths: DataShapingPath[] }) {
  return (
    <datalist id={id}>
      {paths.slice(0, 200).map((item) => (
        <option key={`${item.source}:${item.path}`} value={item.path}>
          {item.type} · {item.source}
        </option>
      ))}
    </datalist>
  );
}

function isDataShapingNode(type: string) {
  return ["variable_assign", "template", "json_extractor", "json_validator"].includes(type);
}

function InputMappingsEditor({ value, onChange, paths = [] }: { value: unknown; onChange: (value: string) => void; paths?: DataShapingPath[] }) {
  const rows = parseObjectList(value);
  const updateRow = (index: number, patch: Record<string, unknown>) => onChange(stringifyObjectList(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row))));
  const addRow = () => onChange(stringifyObjectList([...rows, { name: "input", sourceType: "state", source: "messages", valueType: "string" }]));
  const removeRow = (index: number) => onChange(stringifyObjectList(rows.filter((_row, rowIndex) => rowIndex !== index)));
  const listId = "data-shaping-paths";
  return (
    <div className="config-table">
      <div className="config-table__head">
        <span>输入映射</span>
        <button type="button" onClick={addRow}>
          <Plus size={14} />
          <span>添加</span>
        </button>
      </div>
      {rows.map((row, index) => (
        <div className="config-table__row" key={index}>
          <input value={String(row.name ?? "")} onChange={(event) => updateRow(index, { name: event.target.value })} placeholder="name" />
          <select value={String(row.sourceType ?? "state")} onChange={(event) => updateRow(index, { sourceType: event.target.value })}>
            <option value="state">state</option>
            <option value="template">template</option>
            <option value="literal">literal</option>
            <option value="json">json</option>
          </select>
          <input list={listId} value={String(row.source ?? "")} onChange={(event) => updateRow(index, { source: event.target.value })} placeholder="messages 或 {{ state.messages }}" />
          <select value={String(row.valueType ?? "auto")} onChange={(event) => updateRow(index, { valueType: event.target.value })}>
            <option value="auto">auto</option>
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="integer">integer</option>
            <option value="boolean">boolean</option>
            <option value="json">json</option>
          </select>
          <select value={String(row.transform ?? "none")} onChange={(event) => updateRow(index, { transform: event.target.value })}>
            <option value="none">none</option>
            <option value="default">default</option>
            <option value="coalesce">coalesce</option>
            <option value="split">split</option>
            <option value="join">join</option>
            <option value="pick">pick</option>
            <option value="omit">omit</option>
          </select>
          <input value={String(row.transformArgsJson ?? "")} onChange={(event) => updateRow(index, { transformArgsJson: event.target.value })} placeholder='{"separator":"\\n"}' />
          <button className="icon-only" type="button" onClick={() => removeRow(index)} title="删除映射">
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <PathDatalist id={listId} paths={paths} />
      {rows.length === 0 ? <small className="model-config-note">未配置时节点仍可直接读取 state。</small> : null}
    </div>
  );
}

function AssignmentsEditor({ value, onChange, paths = [] }: { value: unknown; onChange: (value: string) => void; paths?: DataShapingPath[] }) {
  const rows = parseObjectList(value);
  const updateRow = (index: number, patch: Record<string, unknown>) => onChange(stringifyObjectList(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row))));
  const addRow = () => onChange(stringifyObjectList([...rows, { target: "assigned_value", operation: "overwrite", sourceType: "template", source: "{{ state.messages }}", valueType: "string" }]));
  const removeRow = (index: number) => onChange(stringifyObjectList(rows.filter((_row, rowIndex) => rowIndex !== index)));
  const listId = "data-shaping-paths";
  return (
    <div className="config-table">
      <div className="config-table__head">
        <span>赋值规则</span>
        <button type="button" onClick={addRow}>
          <Plus size={14} />
          <span>添加</span>
        </button>
      </div>
      {rows.map((row, index) => (
        <div className="config-table__row config-table__row--assignment" key={index}>
          <input value={String(row.target ?? "")} onChange={(event) => updateRow(index, { target: event.target.value })} placeholder="target field" />
          <select value={String(row.operation ?? "overwrite")} onChange={(event) => updateRow(index, { operation: event.target.value })}>
            <option value="overwrite">overwrite</option>
            <option value="append">append</option>
            <option value="merge">merge</option>
            <option value="clear">clear</option>
          </select>
          <select value={String(row.sourceType ?? "template")} onChange={(event) => updateRow(index, { sourceType: event.target.value })}>
            <option value="state">state</option>
            <option value="template">template</option>
            <option value="literal">literal</option>
            <option value="json">json</option>
            <option value="input">input</option>
          </select>
          <input list={listId} value={String(row.source ?? "")} onChange={(event) => updateRow(index, { source: event.target.value })} placeholder="source" />
          <select value={String(row.valueType ?? "auto")} onChange={(event) => updateRow(index, { valueType: event.target.value })}>
            <option value="auto">auto</option>
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="integer">integer</option>
            <option value="boolean">boolean</option>
            <option value="json">json</option>
          </select>
          <select value={String(row.transform ?? "none")} onChange={(event) => updateRow(index, { transform: event.target.value })}>
            <option value="none">none</option>
            <option value="default">default</option>
            <option value="coalesce">coalesce</option>
            <option value="split">split</option>
            <option value="join">join</option>
            <option value="pick">pick</option>
            <option value="omit">omit</option>
          </select>
          <input value={String(row.transformArgsJson ?? "")} onChange={(event) => updateRow(index, { transformArgsJson: event.target.value })} placeholder='{"paths":["a.b"]}' />
          <button className="icon-only" type="button" onClick={() => removeRow(index)} title="删除赋值">
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <PathDatalist id={listId} paths={paths} />
    </div>
  );
}

function ReducersEditor({ value, onChange }: { value: unknown; onChange: (value: string) => void }) {
  const rows = parseObjectList(value);
  const updateRow = (index: number, patch: Record<string, unknown>) => onChange(stringifyObjectList(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row))));
  const addRow = () => onChange(stringifyObjectList([...rows, { target: "merged_results", source: "item_result", reducer: "append" }]));
  const removeRow = (index: number) => onChange(stringifyObjectList(rows.filter((_row, rowIndex) => rowIndex !== index)));
  return (
    <div className="config-table">
      <div className="config-table__head">
        <span>Merge Reducers</span>
        <button type="button" onClick={addRow}>
          <Plus size={14} />
          <span>添加</span>
        </button>
      </div>
      {rows.map((row, index) => (
        <div className="config-table__row config-table__row--assignment" key={index}>
          <input value={String(row.target ?? "")} onChange={(event) => updateRow(index, { target: event.target.value })} placeholder="target field" />
          <input value={String(row.source ?? "")} onChange={(event) => updateRow(index, { source: event.target.value })} placeholder="itemState source" />
          <select value={String(row.reducer ?? "append")} onChange={(event) => updateRow(index, { reducer: event.target.value })}>
            <option value="append">append</option>
            <option value="concat">concat</option>
            <option value="merge">merge</option>
            <option value="overwrite">overwrite</option>
            <option value="first">first</option>
            <option value="last">last</option>
          </select>
          <button className="icon-only" type="button" onClick={() => removeRow(index)} title="删除 Reducer">
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {rows.length === 0 ? <small className="model-config-note">至少添加一个 Reducer 才能把 itemState 聚合回全局 state。</small> : null}
    </div>
  );
}

function SchemaFieldsEditor({ value, onChange }: { value: unknown; onChange: (value: string) => void }) {
  const rows = parseObjectList(value);
  const updateRow = (index: number, patch: Record<string, unknown>) => onChange(stringifyObjectList(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row))));
  const addRow = () => onChange(stringifyObjectList([...rows, { name: "field", type: "string", required: false, description: "" }]));
  const removeRow = (index: number) => onChange(stringifyObjectList(rows.filter((_row, rowIndex) => rowIndex !== index)));
  return (
    <div className="config-table">
      <div className="config-table__head">
        <span>Schema 字段</span>
        <button type="button" onClick={addRow}>
          <Plus size={14} />
          <span>添加</span>
        </button>
      </div>
      {rows.map((row, index) => (
        <div className="config-table__schema-row" key={index}>
          <div className="config-table__row config-table__row--schema">
            <input value={String(row.name ?? "")} onChange={(event) => updateRow(index, { name: event.target.value })} placeholder="字段名" />
            <select value={String(row.type ?? "string")} onChange={(event) => updateRow(index, { type: event.target.value })}>
              <option value="string">string</option>
              <option value="number">number</option>
              <option value="integer">integer</option>
              <option value="boolean">boolean</option>
              <option value="object">object</option>
              <option value="array">array</option>
            </select>
            <label className="checkbox-row config-table__checkbox">
              <input type="checkbox" checked={Boolean(row.required)} onChange={(event) => updateRow(index, { required: event.target.checked })} />
              <span>必填</span>
            </label>
            <input value={String(row.description ?? "")} onChange={(event) => updateRow(index, { description: event.target.value })} placeholder="描述" />
            <input value={String(row.enumValues ?? "")} onChange={(event) => updateRow(index, { enumValues: event.target.value })} placeholder="枚举，可选" />
            <button className="icon-only" type="button" onClick={() => removeRow(index)} title="删除字段">
              <Trash2 size={14} />
            </button>
          </div>
          {String(row.type ?? "") === "array" ? (
            <div className="inline-grid">
              <Field label="数组元素类型">
                <select value={String(row.itemType ?? "")} onChange={(event) => updateRow(index, { itemType: event.target.value })}>
                  <option value="">自动</option>
                  <option value="string">string</option>
                  <option value="number">number</option>
                  <option value="integer">integer</option>
                  <option value="boolean">boolean</option>
                  <option value="object">object</option>
                </select>
              </Field>
              <Field label="数组对象字段 JSON">
                <textarea
                  rows={3}
                  value={stringifyNestedFields(row.itemFields)}
                  onChange={(event) => updateRow(index, { itemFields: parseNestedFields(event.target.value) })}
                  placeholder='[{"name":"title","type":"string","required":true}]'
                />
              </Field>
            </div>
          ) : null}
          {String(row.type ?? "") === "object" ? (
            <Field label="对象子字段 JSON">
              <textarea
                rows={3}
                value={stringifyNestedFields(row.children)}
                onChange={(event) => updateRow(index, { children: parseNestedFields(event.target.value) })}
                placeholder='[{"name":"name","type":"string"}]'
              />
            </Field>
          ) : null}
        </div>
      ))}
      {rows.length === 0 ? <small className="model-config-note">至少添加一个字段，Extractor/Validator 才能校验输出。</small> : null}
    </div>
  );
}

function stringifyObjectList(rows: Array<Record<string, unknown>>): string {
  return JSON.stringify(rows, null, 2);
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

interface DetectedStateField extends StateField {
  sourceNodeId: string;
  sourceLabel: string;
}

const STATE_TYPE_OPTIONS = ["str", "int", "float", "bool", "dict", "list", "Any"];

function StateFieldEditor({
  fields,
  detectedFields,
  onChange,
}: {
  fields: StateField[];
  detectedFields: DetectedStateField[];
  onChange: (fields: StateField[]) => void;
}) {
  const [query, setQuery] = useState("");
  const existingNames = new Set(fields.map((field) => field.name).filter(Boolean));
  const normalizedQuery = query.trim().toLowerCase();
  const filteredDetected = normalizedQuery
    ? detectedFields.filter((field) =>
        `${field.name} ${field.type} ${field.sourceLabel} ${field.description ?? ""}`.toLowerCase().includes(normalizedQuery),
      )
    : detectedFields;

  const updateField = (index: number, patch: Partial<StateField>) => {
    onChange(fields.map((field, fieldIndex) => (fieldIndex === index ? { ...field, ...patch } : field)));
  };

  const addField = (field?: StateField) => {
    const next = field ?? { name: nextManualStateFieldName(fields), type: "str", description: "" };
    onChange(mergeInspectorStateFields(fields, [next]));
  };

  return (
    <div className="state-field-editor">
      <div className="state-field-editor__header">
        <span>State 字段</span>
        <div className="state-field-editor__actions">
          <button type="button" onClick={() => addField()}>
            <Plus size={14} />
            添加字段
          </button>
          <button type="button" onClick={() => onChange(mergeInspectorStateFields(fields, detectedFields))}>
            <RefreshCw size={14} />
            同步识别字段
          </button>
        </div>
      </div>

      <div className="state-field-editor__rows">
        {fields.length === 0 ? (
          <div className="state-field-editor__empty">当前还没有声明 State 字段。</div>
        ) : (
          fields.map((field, index) => (
            <div key={`${field.name}-${index}`} className="state-field-row">
              <input
                value={field.name}
                onChange={(event) => updateField(index, { name: normalizeStateFieldName(event.target.value) })}
                placeholder="字段名"
              />
              <select value={field.type || "str"} onChange={(event) => updateField(index, { type: event.target.value })}>
                {STATE_TYPE_OPTIONS.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <button
                className="icon-only state-field-row__delete"
                type="button"
                title="删除字段"
                onClick={() => onChange(fields.filter((_field, fieldIndex) => fieldIndex !== index))}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="state-detected">
        <div className="state-detected__title">
          <span>可识别字段</span>
          <small>{detectedFields.length} 个</small>
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索字段、类型或节点"
        />
        <div className="state-detected__list">
          {filteredDetected.length === 0 ? (
            <div className="state-field-editor__empty">没有匹配字段</div>
          ) : (
            filteredDetected.map((field) => {
              const exists = existingNames.has(field.name);
              return (
                <button
                  key={`${field.sourceNodeId}-${field.name}`}
                  className={exists ? "is-added" : ""}
                  type="button"
                  disabled={exists}
                  onClick={() => addField(field)}
                >
                  <span>
                    <strong>{field.name}</strong>
                    <small>{field.sourceLabel}</small>
                  </span>
                  <em>{exists ? "已添加" : field.type || "str"}</em>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

function InspectorSplit({ left, children }: { left: ReactNode; children: ReactNode }) {
  return (
    <div className="inspector-split">
      <aside className="inspector-resource-rail">{left}</aside>
      <div className="inspector-main-fields">{children}</div>
    </div>
  );
}

function ResourceSelectionRail<T extends { id: string; name: string; description?: string }>({
  title,
  itemLabel,
  groups,
  items,
  selectedGroupIds,
  selectedDirectIds,
  emptyText,
  onChange,
  renderItemMeta,
  renderItemExtra,
}: {
  title: string;
  itemLabel: string;
  groups: ResourceGroupConfig[];
  items: T[];
  selectedGroupIds: string[];
  selectedDirectIds: string[];
  emptyText: string;
  onChange: (directIds: string[], groupIds: string[]) => void;
  renderItemMeta: (item: T) => string;
  renderItemExtra?: (item: T) => ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const selectedGroups = new Set(selectedGroupIds);
  const selectedDirect = new Set(selectedDirectIds);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredItems = normalizedQuery
    ? items.filter((item) => `${item.name} ${item.description ?? ""} ${renderItemMeta(item)}`.toLowerCase().includes(normalizedQuery))
    : items;
  const itemById = new Map(items.map((item) => [item.id, item]));

  function toggleGroup(groupId: string, checked: boolean) {
    const next = checked ? [...selectedGroupIds, groupId] : selectedGroupIds.filter((id) => id !== groupId);
    onChange(selectedDirectIds, uniqueStrings(next));
  }

  function toggleItem(itemId: string, checked: boolean) {
    const next = checked ? [...selectedDirectIds, itemId] : selectedDirectIds.filter((id) => id !== itemId);
    onChange(uniqueStrings(next), selectedGroupIds);
  }

  function toggleExpanded(groupId: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }

  return (
    <div className="inspector-resource-picker">
      <div className="inspector-resource-picker__head">
        <strong>{title}</strong>
        <small>{selectedGroupIds.length} 组 · {selectedDirectIds.length} 个单选</small>
      </div>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`搜索 ${itemLabel}`} />
      <div className="inspector-resource-section">
        <div className="inspector-resource-section__title">
          <span>预设组</span>
          <small>{groups.length}</small>
        </div>
        {groups.length === 0 ? (
          <div className="inspector-resource-empty">管理页还没有配置预设组。</div>
        ) : (
          groups.map((group) => {
            const expanded = expandedIds.has(group.id);
            const includedItems = group.itemIds.map((id) => itemById.get(id)).filter(Boolean) as T[];
            return (
              <div key={group.id} className="inspector-resource-group">
                <label className="inspector-resource-row">
                  <input type="checkbox" checked={selectedGroups.has(group.id)} onChange={(event) => toggleGroup(group.id, event.target.checked)} />
                  <span>
                    <strong>{group.name}</strong>
                    <small>{includedItems.length} 个{itemLabel}{group.description ? ` · ${group.description}` : ""}</small>
                  </span>
                </label>
                <button className="inspector-resource-expand" type="button" onClick={() => toggleExpanded(group.id)}>
                  {expanded ? "收起组内容" : "展开组内容"}
                </button>
                {expanded ? (
                  <div className="inspector-resource-group__items">
                    {includedItems.length === 0 ? (
                      <span>组内没有可用{itemLabel}</span>
                    ) : (
                      includedItems.map((item) => <span key={item.id}>{item.name}</span>)
                    )}
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>
      <div className="inspector-resource-section">
        <div className="inspector-resource-section__title">
          <span>单个{itemLabel}</span>
          <small>{items.length}</small>
        </div>
        {items.length === 0 ? (
          <div className="inspector-resource-empty">{emptyText}</div>
        ) : filteredItems.length === 0 ? (
          <div className="inspector-resource-empty">没有匹配的{itemLabel}</div>
        ) : (
          <div className="inspector-resource-list">
            {filteredItems.map((item) => (
              <label key={item.id} className="inspector-resource-row">
                <input type="checkbox" checked={selectedDirect.has(item.id)} onChange={(event) => toggleItem(item.id, event.target.checked)} />
                <span>
                  <strong>{item.name}</strong>
                  <small>{renderItemMeta(item)}</small>
                  {renderItemExtra?.(item)}
                </span>
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SkillMultiSelect({
  skills,
  selectedIds,
  onChange,
}: {
  skills: SkillConfig[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  if (skills.length === 0) {
    return <small className="model-config-note">当前项目还没有可用 Skill。先在初始化配置的 Skills tab 添加。</small>;
  }
  const selected = new Set(selectedIds);
  return (
    <div className="inspector-check-list">
      {skills.map((skill) => (
        <label key={skill.id} className="checkbox-row">
          <input
            type="checkbox"
            checked={selected.has(skill.id)}
            onChange={(event) => {
              const next = event.target.checked
                ? [...selectedIds, skill.id]
                : selectedIds.filter((id) => id !== skill.id);
              onChange(Array.from(new Set(next)));
            }}
          />
          <span>{skill.name}</span>
        </label>
      ))}
    </div>
  );
}

function ToolMultiSelect({
  tools,
  selectedIds,
  onChange,
}: {
  tools: ToolConfig[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  if (tools.length === 0) {
    return <small className="model-config-note">当前还没有可用 Tool。先在主页面「Tools」管理区导入或新增工具。</small>;
  }
  const selected = new Set(selectedIds);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredTools = normalizedQuery
    ? tools.filter((tool) => `${tool.name} ${tool.source} ${tool.description}`.toLowerCase().includes(normalizedQuery))
    : tools;
  return (
    <div className="tool-picker">
      <input
        className="tool-picker__search"
        value={query}
        placeholder="搜索 Tool 名称、来源或描述"
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="tool-picker__list">
        {filteredTools.length === 0 ? (
          <div className="tool-picker__empty">没有匹配的 Tool</div>
        ) : (
          filteredTools.map((tool) => (
            <label key={tool.id} className="tool-picker__item">
              <input
                type="checkbox"
                checked={selected.has(tool.id)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...selectedIds, tool.id]
                    : selectedIds.filter((id) => id !== tool.id);
                  onChange(Array.from(new Set(next)));
                }}
              />
              <span>
                <strong>{tool.name}</strong>
                <small>{tool.source || "tool"} · {tool.description || "未填写描述"}</small>
                <ToolUsageTags tool={tool} />
              </span>
            </label>
          ))
        )}
      </div>
    </div>
  );
}

function ToolUsageTags({ tool }: { tool: ToolConfig }) {
  const tags = toolUsageTags(tool);
  if (!tags.length) return null;
  return (
    <div className="tool-usage-tags">
      {tags.map((tag) => (
        <em key={tag}>{tag}</em>
      ))}
    </div>
  );
}

function parseStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.map((item) => String(item).trim()).filter(Boolean) : [];
  } catch {
    return text.split(/[,，\n]+/).map((item) => item.trim()).filter(Boolean);
  }
}

function parseObjectList(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
  }
  if (value && typeof value === "object") return [value as Record<string, unknown>];
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
    }
    return parsed && typeof parsed === "object" ? [parsed as Record<string, unknown>] : [];
  } catch {
    return [];
  }
}

function stringifyNestedFields(value: unknown): string {
  const rows = parseObjectList(value);
  return rows.length ? JSON.stringify(rows, null, 2) : "";
}

function parseNestedFields(value: string): Array<Record<string, unknown>> {
  return parseObjectList(value);
}

function parseJsonRecord(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function parseMcpToolList(value: unknown): McpToolInspection[] {
  if (Array.isArray(value)) {
    return value.filter(isMcpToolInspection);
  }
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.filter(isMcpToolInspection) : [];
  } catch {
    return [];
  }
}

function isMcpToolInspection(value: unknown): value is McpToolInspection {
  return Boolean(value && typeof value === "object" && "name" in value && String((value as { name?: unknown }).name ?? "").trim());
}

function mcpServerForNode(node: NodeIR, availableMcpServers: MCPServerConfig[]): MCPServerConfig | null {
  const serverId = String(node.config.serverId ?? "").trim();
  const configured = availableMcpServers.find((server) => server.id === serverId);
  if (configured) return configured;
  const snapshots = parseMcpServerSnapshots(node.config.mcpServerSnapshotJson);
  if (snapshots.length) return snapshots[0];
  const transport = String(node.config.transport ?? "").trim();
  const command = String(node.config.command ?? "").trim();
  const url = String(node.config.url ?? "").trim();
  if (!transport && !command && !url) return null;
  return {
    id: serverId,
    name: String(node.config.serverName ?? "未命名 MCP"),
    transport: transport || "stdio",
    command,
    argsJson: "[]",
    envJson: "{}",
    envVarsJson: "[]",
    cwd: "",
    url,
    apiKey: "",
    apiKeyEnv: "",
    apiKeyMode: "env",
    apiKeyHeader: "Authorization",
    apiKeyPrefix: "Bearer",
    bearerTokenEnvVar: "",
    httpHeadersJson: "{}",
    envHttpHeadersJson: "{}",
    enabled: true,
    startupTimeoutSec: 10,
    toolTimeoutSec: 60,
    enabledToolsJson: "[]",
    disabledToolsJson: "[]",
    defaultToolsApprovalMode: "",
    sourceType: "manual",
    sourcePath: "",
    description: "",
  };
}

function parseMcpServerSnapshots(value: unknown): MCPServerConfig[] {
  if (Array.isArray(value)) return value.filter(isMcpServerConfig);
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.filter(isMcpServerConfig) : [];
  } catch {
    return [];
  }
}

function isMcpServerConfig(value: unknown): value is MCPServerConfig {
  return Boolean(value && typeof value === "object" && "id" in value && "name" in value);
}

function directResourceIdsFromConfig(
  config: Record<string, unknown>,
  finalKey: string,
  directKey: string,
  groupKey: string,
  groups: ResourceGroupConfig[],
): string[] {
  if (Object.prototype.hasOwnProperty.call(config, directKey)) {
    return parseStringList(config[directKey]);
  }
  const finalIds = parseStringList(config[finalKey]);
  const groupIds = new Set(parseStringList(config[groupKey]));
  if (groupIds.size === 0) return finalIds;
  const groupedIds = new Set(groups.filter((group) => groupIds.has(group.id)).flatMap((group) => group.itemIds));
  return finalIds.filter((id) => !groupedIds.has(id));
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function toolUsageTags(tool: ToolConfig): string[] {
  const builtinId = toolBuiltinId(tool);
  const text = `${builtinId} ${tool.name} ${tool.description} ${tool.source}`.toLowerCase();
  const tags: string[] = [];
  if (/(read_file|list_directory|file|directory|asset|resolve_asset|文件|目录|资源)/.test(text)) tags.push("文件");
  if (/(code|symbol|chunk|search_code|python|javascript|typescript|代码|符号)/.test(text)) tags.push("代码");
  if (/(html|page|selector|页面)/.test(text)) tags.push("HTML");
  if (/(css|style|scss|less|样式)/.test(text)) tags.push("CSS");
  if (/(web_search|fetch_url|duckduckgo|http|network|搜索|网络)/.test(text)) tags.push("网络");
  if (/(propose_patch|replace_in_file|write_file|apply_patch|rollback_patch|patch|编辑|补丁|回滚|写入|替换)/.test(text)) tags.push("编辑");
  if (/(run_whitelisted_command|command|pytest|npm|git diff|命令|验证)/.test(text)) tags.push("命令");
  if (/(replace_in_file|write_file|apply_patch|rollback_patch|高风险|直接写入|覆盖)/.test(text)) tags.push("高风险");
  return Array.from(new Set(tags));
}

function toolBuiltinId(tool: ToolConfig): string {
  try {
    const schema = JSON.parse(tool.schemaJson || "{}");
    const metadata = schema && typeof schema === "object" && !Array.isArray(schema) ? schema["x-graphic"] : null;
    return metadata && typeof metadata === "object" && "builtinId" in metadata ? String((metadata as { builtinId?: unknown }).builtinId || "") : "";
  } catch {
    return "";
  }
}

function detectStateFieldsFromNodes(nodes: NodeIR[]): DetectedStateField[] {
  const fields: DetectedStateField[] = [];
  for (const node of nodes) {
    switch (node.type) {
      case "start":
        fields.push(detectedField(node, "messages", "str", "聊天输入"));
        break;
      case "llm":
        fields.push(detectedFieldFromConfig(node, "outputField", "final_answer", "str", "模型输出"));
        break;
      case "agent":
        {
          const output = detectedFieldFromConfig(node, "outputField", "agent_result", "str", "Agent 输出");
          fields.push(output);
          if (parseStringList(node.config.mcpServerIdsJson).length) {
            fields.push(detectedField(node, `${output.name}_mcp_tool_calls`, "list", "MCP 调用记录"));
          }
        }
        break;
      case "tool": {
        const output = detectedFieldFromConfig(node, "outputField", "tools_result", "str", "Tools 输出");
        fields.push(output);
        fields.push(detectedField(node, `${output.name}_tool_calls`, "list", "工具调用记录"));
        break;
      }
      case "retriever":
        fields.push(detectedFieldFromConfig(node, "outputField", "retrieved_context", "str", "检索结果"));
        break;
      case "variable_assign":
        fields.push(detectedFieldFromConfig(node, "resultField", "assignment_result", "dict", "赋值摘要"));
        for (const assignment of parseObjectList(node.config.assignmentsJson)) {
          const target = normalizeStateFieldName(assignment.target ?? assignment.field ?? assignment.name);
          if (target) fields.push(detectedField(node, target.split(".")[0], "Any", "赋值写入字段"));
        }
        break;
      case "template":
        fields.push(detectedFieldFromConfig(node, "outputField", "template_result", String(node.config.outputType ?? "text") === "json" ? "dict" : "str", "模板输出"));
        break;
      case "json_extractor":
        fields.push(detectedFieldFromConfig(node, "outputField", "extracted_json", "dict", "JSON 抽取结果"));
        fields.push(detectedFieldFromConfig(node, "validationField", "validation_result", "dict", "JSON 校验结果"));
        fields.push(detectedFieldFromConfig(node, "repairResultField", "repair_result", "dict", "JSON 修复结果"));
        break;
      case "json_validator":
        fields.push(detectedFieldFromConfig(node, "outputField", "validated_json", "dict", "JSON 校验输出"));
        fields.push(detectedFieldFromConfig(node, "validationField", "validation_result", "dict", "JSON 校验结果"));
        fields.push(detectedFieldFromConfig(node, "repairResultField", "repair_result", "dict", "JSON 修复结果"));
        break;
      case "for_each":
        if (normalizeStateFieldName(node.config.resultField)) {
          fields.push(detectedFieldFromConfig(node, "resultField", "for_each_result", "dict", "ForEach 迭代摘要"));
        }
        break;
      case "merge":
        fields.push(detectedFieldFromConfig(node, "resultField", "merge_result", "dict", "Merge 聚合摘要"));
        for (const reducer of parseObjectList(node.config.reducersJson)) {
          const target = normalizeStateFieldName(reducer.target ?? reducer.field ?? reducer.name);
          if (target) fields.push(detectedField(node, target.split(".")[0], "Any", "Merge 聚合字段"));
        }
        break;
      case "error_handler":
        fields.push(detectedFieldFromConfig(node, "outputField", "error_result", "dict", "错误处理输出"));
        break;
      case "task_splitter":
        fields.push(detectedFieldFromConfig(node, "outputField", "worker_tasks", "list", "任务列表"));
        break;
      case "parallel_tools":
        fields.push(detectedFieldFromConfig(node, "outputField", "worker_results", "list", "Worker 结果"));
        break;
      case "ai_router":
        fields.push(detectedFieldFromConfig(node, "routeField", "route_key", "str", "路由结果"));
        fields.push(detectedFieldFromConfig(node, "reasonField", "route_reason", "str", "路由理由"));
        break;
      case "human_approval":
        fields.push(detectedFieldFromConfig(node, "actionField", "approval_action", "str", "审批动作"));
        fields.push(detectedFieldFromConfig(node, "outputField", "approval_result", "dict", "审批结果"));
        break;
      case "http":
        fields.push(detectedFieldFromConfig(node, "outputField", "http_response", "dict", "HTTP 响应"));
        break;
      case "direct_reply":
        fields.push(detectedFieldFromConfig(node, "outputField", "final_answer", "str", "最终回复"));
        break;
      case "custom_function":
        fields.push(detectedFieldFromConfig(node, "outputField", "custom_output", "dict", "函数输出"));
        break;
      case "skill_node":
        fields.push(detectedFieldFromConfig(node, "outputField", "skill_result", "str", "Skill 输出"));
        break;
      case "mcp_node":
        fields.push(detectedFieldFromConfig(node, "outputField", "mcp_result", "dict", "MCP 输出"));
        break;
      default:
        break;
    }
  }
  return fields.filter((field) => Boolean(field.name));
}

function detectedFieldFromConfig(
  node: NodeIR,
  configKey: string,
  fallback: string,
  type: string,
  description: string,
): DetectedStateField {
  return detectedField(node, normalizeStateFieldName(node.config[configKey]) || fallback, type, description);
}

function detectedField(node: NodeIR, name: string, type: string, description: string): DetectedStateField {
  return {
    name: normalizeStateFieldName(name),
    type,
    description,
    sourceNodeId: node.id,
    sourceLabel: node.label || node.type,
  };
}

function mergeInspectorStateFields(existing: StateField[], additions: StateField[]): StateField[] {
  const result = [...existing];
  const names = new Set(result.map((field) => field.name).filter(Boolean));
  for (const addition of additions) {
    const name = normalizeStateFieldName(addition.name);
    if (!name || names.has(name)) continue;
    result.push({
      name,
      type: addition.type || "str",
      description: addition.description || "",
    });
    names.add(name);
  }
  return result;
}

function nextManualStateFieldName(fields: StateField[]): string {
  const used = new Set(fields.map((field) => field.name));
  for (let index = 1; index < 10000; index += 1) {
    const candidate = `field_${index}`;
    if (!used.has(candidate)) return candidate;
  }
  return `field_${Date.now()}`;
}

function normalizeStateFieldName(value: unknown): string {
  return String(value ?? "").trim().replace(/[^a-zA-Z0-9_]/g, "_").replace(/^([^a-zA-Z_])/, "_$1");
}

function inspectorInitialRect() {
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: Math.max(16, viewportWidth - 380),
    y: 98,
    width: 360,
    height: Math.min(720, Math.max(420, viewportHeight - 118)),
  };
}

function resourceInspectorInitialRect() {
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: Math.max(16, viewportWidth - 680),
    y: 98,
    width: 640,
    height: Math.min(760, Math.max(480, viewportHeight - 118)),
  };
}

interface ModelOption {
  id: string;
  name: string;
}

interface ModelConfigOption {
  id: string;
  name: string;
  provider: string;
  model: string;
  baseUrl: string;
  apiKeyEnv: string;
  apiVersion: string;
  organization: string;
  apiFormat: string;
  enabled: boolean;
  models: ModelOption[];
}

function ModelSelectionFields({
  config,
  defaultProvider,
  defaultModel,
  fieldNames,
  modelConfigs,
  nodeId,
  providerLabel = "供应商",
  providerManualLabel = "供应商",
  providerNote = "从管理页已保存的模型配置中选择；保存后会写入节点的供应商和模型。",
  updateNodeConfig,
}: {
  config: Record<string, unknown>;
  defaultProvider: string;
  defaultModel: string;
  fieldNames?: {
    provider: string;
    model: string;
    modelConfigId: string;
    modelConfigName: string;
    modelDisplayName: string;
    baseUrl: string;
    apiKeyEnv: string;
    apiVersion: string;
    organization: string;
    apiFormat: string;
  };
  modelConfigs: ModelConfigOption[];
  nodeId: string;
  providerLabel?: string;
  providerManualLabel?: string;
  providerNote?: string;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
}) {
  const keys = fieldNames ?? {
    provider: "provider",
    model: "model",
    modelConfigId: "modelConfigId",
    modelConfigName: "modelConfigName",
    modelDisplayName: "modelDisplayName",
    baseUrl: "baseUrl",
    apiKeyEnv: "apiKeyEnv",
    apiVersion: "apiVersion",
    organization: "organization",
    apiFormat: "apiFormat",
  };
  const provider = String(config[keys.provider] ?? defaultProvider);
  const model = String(config[keys.model] ?? defaultModel);
  const modelConfigId = String(config[keys.modelConfigId] ?? "");
  const selectedConfig =
    modelConfigs.find((item) => item.id === modelConfigId) ??
    modelConfigs.find((item) => item.provider === provider && item.models.some((option) => option.id === model)) ??
    modelConfigs.find((item) => item.provider === provider) ??
    null;
  const modelOptions = selectedConfig ? ensureModelOption(selectedConfig.models, model) : [];

  if (modelConfigs.length === 0) {
    return (
      <>
        <Field label={providerManualLabel}>
          <input
            value={provider}
            onChange={(event) => updateNodeConfig(nodeId, { [keys.provider]: event.target.value, [keys.modelConfigId]: "", [keys.modelConfigName]: "" })}
          />
          <small className="model-config-note">还没有本地模型配置，暂时使用手动输入。可在管理页「模型」中添加。{providerNote}</small>
        </Field>
        <Field label="模型">
          <input value={model} onChange={(event) => updateNodeConfig(nodeId, { [keys.model]: event.target.value })} />
        </Field>
      </>
    );
  }

  return (
    <>
      <Field label={providerLabel}>
        <select
          value={selectedConfig?.id ?? ""}
          onChange={(event) => {
            const nextConfig = modelConfigs.find((item) => item.id === event.target.value);
            if (!nextConfig) {
              updateNodeConfig(nodeId, { [keys.modelConfigId]: "", [keys.modelConfigName]: "" });
              return;
            }
            const nextModel = nextConfig.models.find((option) => option.id === model)?.id ?? nextConfig.model ?? nextConfig.models[0]?.id ?? model;
            updateNodeConfig(nodeId, {
              [keys.provider]: nextConfig.provider,
              [keys.model]: nextModel,
              [keys.modelConfigId]: nextConfig.id,
              [keys.modelConfigName]: nextConfig.name,
              [keys.baseUrl]: nextConfig.baseUrl,
              [keys.apiKeyEnv]: nextConfig.apiKeyEnv,
              [keys.apiVersion]: nextConfig.apiVersion,
              [keys.organization]: nextConfig.organization,
              [keys.apiFormat]: nextConfig.apiFormat,
            });
          }}
        >
          <option value="">手动输入 / 未绑定</option>
          {modelConfigs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} · {item.provider}{item.enabled ? "" : "（已停用）"}
            </option>
          ))}
        </select>
        <small className="model-config-note">{providerNote}</small>
      </Field>
      {selectedConfig ? (
        <Field label="模型">
          <select
            value={model}
            onChange={(event) => {
              const option = modelOptions.find((item) => item.id === event.target.value);
              updateNodeConfig(nodeId, {
                [keys.model]: event.target.value,
                [keys.modelDisplayName]: option?.name ?? "",
                [keys.modelConfigId]: selectedConfig.id,
                [keys.modelConfigName]: selectedConfig.name,
                [keys.provider]: selectedConfig.provider,
                [keys.baseUrl]: selectedConfig.baseUrl,
                [keys.apiKeyEnv]: selectedConfig.apiKeyEnv,
                [keys.apiVersion]: selectedConfig.apiVersion,
                [keys.organization]: selectedConfig.organization,
                [keys.apiFormat]: selectedConfig.apiFormat,
              });
            }}
          >
            {modelOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name === option.id ? option.id : `${option.name} · ${option.id}`}
              </option>
            ))}
          </select>
        </Field>
      ) : (
        <div className="inline-grid">
          <Field label="供应商标识">
            <input value={provider} onChange={(event) => updateNodeConfig(nodeId, { [keys.provider]: event.target.value })} />
          </Field>
          <Field label="模型">
            <input value={model} onChange={(event) => updateNodeConfig(nodeId, { [keys.model]: event.target.value })} />
          </Field>
        </div>
      )}
    </>
  );
}

function mergeById<T extends { id: string }>(items: T[]): T[] {
  const map = new Map<string, T>();
  for (const item of items) {
    map.set(item.id, item);
  }
  return Array.from(map.values());
}

function mergeAgentResources(importedAgents: ImportedAgentConfig[], globalAgents: ProjectListItem[] | ImportedAgentConfig[]): ImportedAgentConfig[] {
  const byProjectId = new Map<string, ImportedAgentConfig>();
  const byId = new Map<string, ImportedAgentConfig>();

  function add(agent: ImportedAgentConfig) {
    const projectId = String(agent.projectId ?? "").trim();
    const id = String(agent.id ?? "").trim();
    if (projectId && byProjectId.has(projectId)) return;
    if (!projectId && id && byId.has(id)) return;
    const normalized: ImportedAgentConfig = {
      id: id || projectId,
      name: agent.name || "导入的 Agent",
      projectId,
      role: agent.role || "sub_agent",
      description: agent.description || "",
    };
    if (projectId) byProjectId.set(projectId, normalized);
    if (normalized.id) byId.set(normalized.id, normalized);
  }

  for (const agent of importedAgents) {
    add(agent);
  }
  for (const item of globalAgents) {
    if ("projectId" in item) {
      add(item);
    } else {
      add({
        id: item.id,
        name: item.name,
        projectId: item.id,
        role: "sub_agent",
        description: item.description || `${item.nodeCount} 节点 · ${item.edgeCount} 连线`,
      });
    }
  }
  return Array.from(byProjectId.values()).concat(Array.from(byId.values()).filter((agent) => !agent.projectId));
}

function buildModelConfigOptions(configs: ModelConfig[]): ModelConfigOption[] {
  return configs
    .filter((config) => config && config.id)
    .map((config) => {
      const models = readConfiguredModels(config);
      return {
        id: config.id,
        name: config.name || "未命名模型配置",
        provider: String(config.provider || "openai"),
        model: config.model || models[0]?.id || "",
        baseUrl: config.baseUrl,
        apiKeyEnv: config.apiKeyEnv,
        apiVersion: config.apiVersion,
        organization: config.organization,
        apiFormat: config.apiFormat,
        enabled: config.enabled !== false,
        models: ensureModelOption(models, config.model),
      };
    });
}

function readConfiguredModels(config: Pick<ModelConfig, "modelRowsJson" | "modelsJson" | "model">): ModelOption[] {
  const rows = parseModelRows(config.modelRowsJson);
  if (rows.length > 0) return rows;
  const modelsJson = parseJsonObject(config.modelsJson);
  const migrated = Object.entries(modelsJson)
    .map(([id, value]) => ({
      id: id.trim(),
      name: value && typeof value === "object" && "name" in value ? String((value as { name?: unknown }).name || id).trim() : id.trim(),
    }))
    .filter((item) => item.id && item.name);
  if (migrated.length > 0) return migrated;
  const model = config.model.trim();
  return model ? [{ id: model, name: model }] : [];
}

function parseModelRows(value: string): ModelOption[] {
  try {
    const parsed = JSON.parse(value || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((row) => ({
        id: String(row?.id || "").trim(),
        name: String(row?.name || "").trim(),
      }))
      .filter((row) => row.id && row.name);
  } catch {
    return [];
  }
}

function parseJsonObject(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function ensureModelOption(models: ModelOption[], currentModel: string): ModelOption[] {
  const normalized = currentModel.trim();
  if (!normalized || models.some((item) => item.id === normalized)) return models;
  return [{ id: normalized, name: `${normalized}（当前值）` }, ...models];
}

function retrieverSourceFromKnowledgeBase(knowledgeBase: RagKnowledgeBaseConfig) {
  switch (knowledgeBase.sourceType) {
    case "local_files":
      return "files";
    case "vectorstore":
      return "vectorstore";
    case "http_api":
      return "http";
    case "database":
      return "database";
    case "local_directory":
    default:
      return "local";
  }
}

function retrieverPathFromKnowledgeBase(knowledgeBase: RagKnowledgeBaseConfig) {
  return knowledgeBase.path || knowledgeBase.url || knowledgeBase.collection || "./knowledge";
}

function ragSourceLabel(sourceType: string) {
  switch (sourceType) {
    case "local_files":
      return "本地文件";
    case "vectorstore":
      return "向量库";
    case "http_api":
      return "HTTP API";
    case "database":
      return "数据库";
    case "local_directory":
    default:
      return "本地目录";
  }
}
