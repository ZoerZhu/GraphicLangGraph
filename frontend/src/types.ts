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

export interface MCPServerConfig {
  id: string;
  name: string;
  transport: string;
  command: string;
  url: string;
  description: string;
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

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  nodeId?: string | null;
  edgeId?: string | null;
  field?: string | null;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
}

export interface ExportResponse {
  exportId: string;
  downloadUrl: string;
  files: string[];
}

export interface RunTraceItem {
  nodeId: string;
  type: NodeType;
  label: string;
  status: "ok" | "skipped" | "error";
  detail: string;
}

export interface RunPreviewResult {
  valid: boolean;
  issues: ValidationIssue[];
  trace: RunTraceItem[];
  outputState: Record<string, unknown>;
}
