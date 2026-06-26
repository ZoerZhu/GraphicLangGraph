import { z } from "zod";

export const NodeTypeSchema = z.enum([
  "start",
  "llm",
  "agent",
  "tool",
  "task_splitter",
  "parallel_tools",
  "parallel_worker",
  "variable_assign",
  "template",
  "json_extractor",
  "json_validator",
  "for_each",
  "merge",
  "error_handler",
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
      runtimeEnvironmentId: z.string().default(""),
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
      kind: z.enum(["normal", "conditional", "error", "worker"]),
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
  skills: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      description: z.string(),
      sourceType: z.string().default("manual"),
      sourcePath: z.string().default(""),
      filePath: z.string().default(""),
      content: z.string().default(""),
      metadataJson: z.string().default("{}"),
      enabled: z.boolean().default(true),
    }),
  ).default([]),
  mcpServers: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      transport: z.string(),
      command: z.string(),
      argsJson: z.string().default("[]"),
      envJson: z.string().default("{}"),
      envVarsJson: z.string().default("[]"),
      cwd: z.string().default(""),
      url: z.string(),
      apiKey: z.string().default(""),
      apiKeyEnv: z.string().default(""),
      apiKeyMode: z.string().default("env"),
      apiKeyHeader: z.string().default("Authorization"),
      apiKeyPrefix: z.string().default("Bearer"),
      bearerTokenEnvVar: z.string().default(""),
      httpHeadersJson: z.string().default("{}"),
      envHttpHeadersJson: z.string().default("{}"),
      enabled: z.boolean().default(true),
      startupTimeoutSec: z.number().default(10),
      toolTimeoutSec: z.number().default(60),
      enabledToolsJson: z.string().default("[]"),
      disabledToolsJson: z.string().default("[]"),
      defaultToolsApprovalMode: z.string().default(""),
      sourceType: z.string().default("manual"),
      sourcePath: z.string().default(""),
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
  apiKeyMode: z.string().default("env"),
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

export const RuntimeEnvironmentConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  description: z.string(),
  allowedRootsJson: z.string(),
  networkEnabled: z.boolean(),
  allowAllHosts: z.boolean().default(false),
  allowedHostsJson: z.string(),
  maxFileBytes: z.number(),
  maxHttpBytes: z.number(),
  allowDirectEdits: z.boolean().default(false),
  allowedCommandProfilesJson: z.string().default("[]"),
  maxPatchBytes: z.number().default(524288),
  maxCommandOutputBytes: z.number().default(262144),
});

export const RuntimeEnvironmentConfigListSchema = z.array(RuntimeEnvironmentConfigSchema);

export const CommandRunResultSchema = z.object({
  command: z.array(z.string()),
  cwd: z.string(),
  exitCode: z.number(),
  stdout: z.string(),
  stderr: z.string(),
  durationMs: z.number(),
  timedOut: z.boolean(),
  truncated: z.boolean(),
});

export const EditSessionSchema = z.object({
  patchId: z.string(),
  projectId: z.string(),
  runId: z.string(),
  status: z.string(),
  files: z.array(
    z.object({
      path: z.string(),
      absolutePath: z.string(),
      exists: z.boolean(),
      baseHash: z.string(),
      changeKind: z.string(),
      hunkCount: z.number(),
      summary: z.string(),
    }),
  ),
  diff: z.string(),
  conflicts: z.array(z.string()),
  rollbackId: z.string(),
  createdAt: z.string(),
  appliedAt: z.string(),
  discardedAt: z.string(),
  rolledBackAt: z.string().optional(),
  commandResults: z.array(CommandRunResultSchema),
});

export const EnvVarCheckSchema = z.object({
  valid: z.boolean(),
  exists: z.boolean(),
  name: z.string(),
  length: z.number(),
  message: z.string(),
});

export const ToolConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  source: z.string(),
  schemaJson: z.string(),
});

export const ToolConfigListSchema = z.array(ToolConfigSchema);

export const ToolImportResultSchema = z.object({
  imported: ToolConfigListSchema,
  allConfigs: ToolConfigListSchema,
  importPath: z.string(),
  detectedFiles: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const SkillConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  sourceType: z.string().default("manual"),
  sourcePath: z.string().default(""),
  filePath: z.string().default(""),
  content: z.string().default(""),
  metadataJson: z.string().default("{}"),
  enabled: z.boolean().default(true),
});

export const SkillConfigListSchema = z.array(SkillConfigSchema);

export const SkillImportResultSchema = z.object({
  imported: z.array(SkillConfigSchema),
  allConfigs: z.array(SkillConfigSchema),
  importPath: z.string(),
  detectedFiles: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const ResourceGroupConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().default(""),
  resourceType: z.string().default("tool"),
  itemIds: z.array(z.string()).default([]),
});

export const ResourceGroupConfigListSchema = z.array(ResourceGroupConfigSchema);

export const McpServerConfigSchema = z.object({
  id: z.string(),
  name: z.string(),
  transport: z.string(),
  command: z.string(),
  argsJson: z.string().default("[]"),
  envJson: z.string().default("{}"),
  envVarsJson: z.string().default("[]"),
  cwd: z.string().default(""),
  url: z.string(),
  apiKey: z.string().default(""),
  apiKeyEnv: z.string().default(""),
  apiKeyMode: z.string().default("env"),
  apiKeyHeader: z.string().default("Authorization"),
  apiKeyPrefix: z.string().default("Bearer"),
  bearerTokenEnvVar: z.string().default(""),
  httpHeadersJson: z.string().default("{}"),
  envHttpHeadersJson: z.string().default("{}"),
  enabled: z.boolean().default(true),
  startupTimeoutSec: z.number().default(10),
  toolTimeoutSec: z.number().default(60),
  enabledToolsJson: z.string().default("[]"),
  disabledToolsJson: z.string().default("[]"),
  defaultToolsApprovalMode: z.string().default(""),
  sourceType: z.string().default("manual"),
  sourcePath: z.string().default(""),
  description: z.string(),
});

export const McpServerConfigListSchema = z.array(McpServerConfigSchema);

export const McpImportResultSchema = z.object({
  imported: z.array(McpServerConfigSchema),
  allConfigs: z.array(McpServerConfigSchema),
  importPath: z.string(),
  detectedFiles: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const McpToolInspectionSchema = z.object({
  name: z.string(),
  title: z.string().default(""),
  description: z.string().default(""),
  inputSchema: z.record(z.unknown()).default({}),
});

export const McpInspectResultSchema = z.object({
  ok: z.boolean(),
  serverId: z.string().default(""),
  serverName: z.string().default(""),
  transport: z.string().default(""),
  tools: z.array(McpToolInspectionSchema).default([]),
  warnings: z.array(z.string()).default([]),
  durationMs: z.number().default(0),
  error: z.string().default(""),
});

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
      virtual: z.boolean().optional().default(false),
      parentNodeId: z.string().nullable().optional(),
      position: z.object({ x: z.number(), y: z.number() }).nullable().optional(),
    }).passthrough(),
  ),
  outputState: z.record(z.unknown()),
});

export const RunHistoryRecordSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  projectName: z.string(),
  createdAt: z.string(),
  modelConfigId: z.string().nullable(),
  modelConfigName: z.string(),
  inputState: z.record(z.unknown()),
  graphFingerprint: z.string().optional(),
  graphSnapshot: z.unknown().optional(),
  result: RunPreviewResultSchema,
  runtimeNodes: z.record(z.unknown()),
});

export const RunHistoryRecordListSchema = z.array(RunHistoryRecordSchema);

export const DataShapingPathSchema = z.object({
  path: z.string(),
  type: z.string(),
  source: z.string(),
  label: z.string(),
  value: z.unknown().optional(),
});

export const DataShapingPathsResultSchema = z.object({
  paths: z.array(DataShapingPathSchema),
});

export const DataShapingPreviewResultSchema = z.object({
  ok: z.boolean(),
  nodeId: z.string(),
  nodeType: z.string(),
  inputs: z.record(z.unknown()),
  delta: z.record(z.unknown()),
  validation: z.unknown().optional().nullable(),
  repair: z.unknown().optional().nullable(),
  detail: z.string(),
  errors: z.array(z.string()),
  paths: z.array(DataShapingPathSchema).optional(),
});
