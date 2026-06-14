import { z } from "zod";

export const NodeTypeSchema = z.enum([
  "start",
  "llm",
  "agent",
  "tool",
  "retriever",
  "condition",
  "ai_router",
  "human_approval",
  "http",
  "direct_reply",
  "custom_function",
  "skill_node",
  "mcp_node",
  "agent_ref",
]);

export const ProjectSchema = z.object({
  project: z.object({
      id: z.string(),
      name: z.string(),
      description: z.string(),
      kind: z.enum(["agent", "agents"]).default("agent"),
      schemaVersion: z.string(),
  }),
  state: z.object({
    base: z.string(),
    fields: z.array(
      z.object({
        name: z.string(),
        type: z.string(),
        default: z.unknown().optional(),
        description: z.string().optional(),
      }),
    ),
  }),
  nodes: z.array(
    z.object({
      id: z.string(),
      type: NodeTypeSchema,
      label: z.string(),
      position: z.object({ x: z.number(), y: z.number() }),
      config: z.record(z.unknown()),
      inputs: z.array(z.object({ id: z.string(), type: z.string(), label: z.string().nullable().optional() })),
      outputs: z.array(z.object({ id: z.string(), type: z.string(), label: z.string().nullable().optional() })),
    }),
  ),
  edges: z.array(
    z.object({
      id: z.string(),
      source: z.string(),
      sourceHandle: z.string().nullable().optional(),
      target: z.string(),
      targetHandle: z.string().nullable().optional(),
      kind: z.enum(["normal", "conditional", "error"]),
      label: z.string().nullable().optional(),
    }),
  ),
  secrets: z.array(z.object({ name: z.string(), env: z.string() })),
  tools: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      description: z.string(),
      source: z.string(),
      schemaJson: z.string(),
    }),
  ).default([]),
  mcpServers: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      transport: z.string(),
      command: z.string(),
      url: z.string(),
      description: z.string(),
    }),
  ).default([]),
  importedAgents: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      projectId: z.string(),
      role: z.string(),
      description: z.string(),
    }),
  ).default([]),
  agentLinks: z.array(
    z.object({
      id: z.string(),
      fromAgent: z.string(),
      toAgent: z.string(),
      protocol: z.string(),
      instruction: z.string(),
    }),
  ).default([]),
});

export const ProjectListSchema = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
    description: z.string(),
    kind: z.enum(["agent", "agents"]).default("agent"),
    nodeCount: z.number(),
    edgeCount: z.number(),
    toolCount: z.number(),
    mcpCount: z.number(),
    importedAgentCount: z.number(),
    updatedAt: z.string(),
  }),
);

export const ValidationResultSchema = z.object({
  valid: z.boolean(),
  issues: z.array(
    z.object({
      severity: z.enum(["error", "warning"]),
      code: z.string(),
      message: z.string(),
      nodeId: z.string().nullable().optional(),
      edgeId: z.string().nullable().optional(),
      field: z.string().nullable().optional(),
      suggestion: z.string().nullable().optional(),
    }),
  ),
});

export const ExportResponseSchema = z.object({
  exportId: z.string(),
  downloadUrl: z.string(),
  files: z.array(z.string()),
  smokeTest: z.object({
    passed: z.boolean(),
    command: z.array(z.string()),
    exitCode: z.number(),
    durationMs: z.number(),
    stdout: z.string(),
    stderr: z.string(),
  }),
});

export const ModelConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  provider: z.string(),
  model: z.string(),
  baseUrl: z.string(),
  apiKey: z.string(),
  apiKeyEnv: z.string(),
  apiVersion: z.string(),
  organization: z.string(),
  homepage: z.string(),
  apiFormat: z.string(),
  extraOptionsJson: z.string(),
  modelRowsJson: z.string(),
  modelsJson: z.string(),
  enabled: z.boolean(),
  isDefault: z.boolean(),
  notes: z.string(),
});

export const ModelConfigListSchema = z.array(ModelConfigSchema);

export const ToolConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  source: z.string(),
  schemaJson: z.string(),
});

export const ToolConfigListSchema = z.array(ToolConfigSchema);

export const McpServerConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  transport: z.string(),
  command: z.string(),
  url: z.string(),
  description: z.string(),
});

export const McpServerConfigListSchema = z.array(McpServerConfigSchema);

export const RagKnowledgeBaseSchema = z.object({
  id: z.string(),
  name: z.string(),
  sourceType: z.string(),
  path: z.string(),
  url: z.string(),
  collection: z.string(),
  description: z.string(),
  embeddingModel: z.string(),
  topK: z.number(),
  metadataJson: z.string(),
  enabled: z.boolean(),
});

export const RagKnowledgeBaseListSchema = z.array(RagKnowledgeBaseSchema);

export const RagKnowledgeBaseInspectionSchema = z.object({
  exists: z.boolean(),
  sourceType: z.string(),
  path: z.string(),
  url: z.string(),
  collection: z.string(),
  description: z.string(),
  embeddingModel: z.string(),
  topK: z.number(),
  metadataJson: z.string(),
  detectedFiles: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const RunPreviewResultSchema = z.object({
  mode: z.enum(["dry", "live"]),
  valid: z.boolean(),
  issues: ValidationResultSchema.shape.issues,
  trace: z.array(
    z.object({
      nodeId: z.string(),
      type: NodeTypeSchema,
      label: z.string(),
      status: z.enum(["ok", "skipped", "error"]),
      detail: z.string(),
      durationMs: z.number(),
      inputState: z.record(z.unknown()),
      outputDelta: z.record(z.unknown()),
    }),
  ),
  outputState: z.record(z.unknown()),
});
