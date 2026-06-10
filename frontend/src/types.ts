export type NodeType =
  | "start"
  | "llm"
  | "condition"
  | "http"
  | "direct_reply"
  | "custom_function";

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

export interface ProjectIR {
  project: {
    id: string;
    name: string;
    description: string;
    schemaVersion: string;
  };
  state: {
    base: string;
    fields: StateField[];
  };
  nodes: NodeIR[];
  edges: EdgeIR[];
  secrets: Array<{ name: string; env: string }>;
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

