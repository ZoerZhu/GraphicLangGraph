export type NodeType =
  | "start"
  | "llm"
  | "agent"
  | "tool"
  | "retriever"
  | "condition"
  | "ai_router"
  | "human_approval"
  | "http"
  | "direct_reply"
  | "custom_function"
  | "skill_node"
  | "mcp_node"
  | "agent_ref";

export type EdgeKind = "normal" | "conditional" | "error";
export type RunMode = "dry" | "live";
export type ModelProvider =
  | "openai"
  | "anthropic"
  | "azure_openai"
  | "google"
  | "deepseek"
  | "moonshot"
  | "qwen"
  | "zhipu"
  | "minimax"
  | "baichuan"
  | "mistral"
  | "cohere"
  | "groq"
  | "ollama"
  | "doubao"
  | "hunyuan"
  | "baidu_qianfan"
  | "openai_compatible"
  | "custom";

export interface Position {
  x: number;
  y: number;
}

export interface Port {
  id: string;
  type: string;
  label?: string | null;
}

export interface StateField {
  name: string;
  type: string;
  default?: unknown;
  description?: string;
}

export interface NodeIR {
  id: string;
  type: NodeType;
  label: string;
  position: Position;
  config: Record<string, unknown>;
  inputs: Port[];
  outputs: Port[];
}

export interface EdgeIR {
  id: string;
  source: string;
  sourceHandle?: string | null;
  target: string;
  targetHandle?: string | null;
  kind: EdgeKind;
  label?: string | null;
}

export interface ToolConfig {
  id: string;
  name: string;
  description: string;
  source: string;
  schemaJson: string;
}

export interface ToolImportResult {
  imported: ToolConfig[];
  allConfigs: ToolConfig[];
  importPath: string;
  detectedFiles: string[];
  warnings: string[];
}

export interface SkillConfig {
  id: string;
  name: string;
  description: string;
  sourceType: string;
  sourcePath: string;
  filePath: string;
  content: string;
  metadataJson: string;
  enabled: boolean;
}

export interface SkillImportResult {
  imported: SkillConfig[];
  allConfigs: SkillConfig[];
  importPath: string;
  detectedFiles: string[];
  warnings: string[];
}

export interface MCPServerConfig {
  id: string;
  name: string;
  transport: string;
  command: string;
  argsJson: string;
  envJson: string;
  envVarsJson: string;
  cwd: string;
  url: string;
  bearerTokenEnvVar: string;
  httpHeadersJson: string;
  envHttpHeadersJson: string;
  enabled: boolean;
  startupTimeoutSec: number;
  toolTimeoutSec: number;
  enabledToolsJson: string;
  disabledToolsJson: string;
  defaultToolsApprovalMode: string;
  sourceType: string;
  sourcePath: string;
  description: string;
}

export interface McpImportResult {
  imported: MCPServerConfig[];
  allConfigs: MCPServerConfig[];
  importPath: string;
  detectedFiles: string[];
  warnings: string[];
}

export interface ModelConfig {
  id: string;
  name: string;
  provider: ModelProvider | string;
  model: string;
  baseUrl: string;
  apiKey: string;
  apiKeyEnv: string;
  apiKeyMode: "env" | "direct" | string;
  apiVersion: string;
  organization: string;
  homepage: string;
  apiFormat: string;
  extraOptionsJson: string;
  modelRowsJson: string;
  modelsJson: string;
  enabled: boolean;
  isDefault: boolean;
  notes: string;
}

export interface EnvVarCheckResult {
  valid: boolean;
  exists: boolean;
  name: string;
  length: number;
  message: string;
}

export interface RagKnowledgeBaseConfig {
  id: string;
  name: string;
  sourceType: string;
  path: string;
  url: string;
  collection: string;
  description: string;
  embeddingModel: string;
  topK: number;
  metadataJson: string;
  enabled: boolean;
}

export interface RagKnowledgeBaseInspection {
  exists: boolean;
  sourceType: string;
  path: string;
  url: string;
  collection: string;
  description: string;
  embeddingModel: string;
  topK: number;
  metadataJson: string;
  detectedFiles: string[];
  warnings: string[];
}

export interface ImportedAgentConfig {
  id: string;
  name: string;
  projectId: string;
  role: string;
  description: string;
}

export interface AgentLinkConfig {
  id: string;
  fromAgent: string;
  toAgent: string;
  protocol: string;
  instruction: string;
}

export interface ProjectIR {
  project: {
    id: string;
    name: string;
    description: string;
    kind: "agent" | "agents";
    schemaVersion: string;
  };
  state: {
    base: string;
    fields: StateField[];
  };
  nodes: NodeIR[];
  edges: EdgeIR[];
  secrets: Array<{ name: string; env: string }>;
  tools: ToolConfig[];
  skills: SkillConfig[];
  mcpServers: MCPServerConfig[];
  importedAgents: ImportedAgentConfig[];
  agentLinks: AgentLinkConfig[];
}

export interface ProjectListItem {
  id: string;
  name: string;
  description: string;
  kind: "agent" | "agents";
  nodeCount: number;
  edgeCount: number;
  toolCount: number;
  mcpCount: number;
  importedAgentCount: number;
  updatedAt: string;
}

export interface ProjectHistoryRecord {
  id: string;
  projectId: string;
  name: string;
  description: string;
  kind: "agent" | "agents";
  createdAt: string;
  nodeCount: number;
  edgeCount: number;
  snapshot: ProjectIR;
}

export interface RunHistoryRecord {
  id: string;
  projectId: string;
  projectName: string;
  createdAt: string;
  modelConfigId: string | null;
  modelConfigName: string;
  inputState: Record<string, unknown>;
  graphFingerprint?: string;
  graphSnapshot?: RunHistoryGraphSnapshot;
  result: RunPreviewResult;
  runtimeNodes: Record<string, NodeRuntimeState>;
}

export type RunHistoryReplayMode = "details" | "overlay";

export interface RunHistoryGraphSnapshot {
  nodeCount: number;
  edgeCount: number;
  stateFields: Array<{
    name: string;
    type: string;
  }>;
  nodes: Array<{
    id: string;
    type: NodeType;
    label: string;
    inputs: Array<{ id: string; type: string }>;
    outputs: Array<{ id: string; type: string }>;
  }>;
  edges: Array<{
    source: string;
    sourceHandle: string | null;
    target: string;
    targetHandle: string | null;
    kind: EdgeKind;
  }>;
}

export interface RunHistoryGraphMismatch {
  reason: "changed" | "legacy";
  historyFingerprint: string | null;
  currentFingerprint: string;
  historyNodeCount: number;
  currentNodeCount: number;
  historyEdgeCount: number;
  currentEdgeCount: number;
  matchedNodeIds: string[];
  missingNodeIds: string[];
  incompatibleNodeIds: string[];
  addedNodeIds: string[];
}

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  nodeId?: string | null;
  edgeId?: string | null;
  field?: string | null;
  suggestion?: string | null;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
}

export interface ExportResponse {
  exportId: string;
  downloadUrl: string;
  files: string[];
  smokeTest: SmokeTestResult;
}

export interface SmokeTestResult {
  passed: boolean;
  command: string[];
  exitCode: number;
  durationMs: number;
  stdout: string;
  stderr: string;
}

export interface RunTraceItem {
  nodeId: string;
  type: NodeType;
  label: string;
  status: RunTraceStatus;
  detail: string;
  durationMs: number;
  inputState: Record<string, unknown>;
  outputDelta: Record<string, unknown>;
}

export type RunTraceStatus = "ok" | "skipped" | "error";
export type NodeRuntimeStatus = "idle" | "queued" | "running" | RunTraceStatus;

export interface NodeRuntimeState {
  status: NodeRuntimeStatus;
  label: string;
  detail: string;
  durationMs: number;
  inputState: Record<string, unknown>;
  outputDelta: Record<string, unknown>;
  updatedAt: string;
}

export interface RunPreviewResult {
  mode: RunMode;
  valid: boolean;
  issues: ValidationIssue[];
  trace: RunTraceItem[];
  outputState: Record<string, unknown>;
}

export type RunStreamEvent =
  | {
      event: "run_start";
      mode: RunMode;
      valid: boolean;
      issues: ValidationIssue[];
      inputState: Record<string, unknown>;
    }
  | {
      event: "node_start";
      mode: RunMode;
      valid: boolean;
      issues: ValidationIssue[];
      nodeId: string;
      type: NodeType;
      label: string;
      inputState: Record<string, unknown>;
    }
  | {
      event: "node_end";
      mode: RunMode;
      valid: boolean;
      issues: ValidationIssue[];
      traceItem: RunTraceItem;
      outputState: Record<string, unknown>;
    }
  | {
      event: "run_end";
      mode: RunMode;
      valid: boolean;
      issues: ValidationIssue[];
      trace: RunTraceItem[];
      outputState: Record<string, unknown>;
    };
