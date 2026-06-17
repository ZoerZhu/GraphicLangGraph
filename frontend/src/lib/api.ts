import type {
  CommandRunResult,
  EditSession,
  EnvVarCheckResult,
  ExportResponse,
  MCPServerConfig,
  McpImportResult,
  ModelConfig,
  ProjectIR,
  ProjectListItem,
  RagKnowledgeBaseInspection,
  RagKnowledgeBaseConfig,
  ResourceGroupConfig,
  RuntimeEnvironmentConfig,
  RunMode,
  RunPreviewResult,
  RunStreamEvent,
  SkillConfig,
  SkillImportResult,
  ToolConfig,
  ToolImportResult,
  ValidationResult,
} from "../types";
import {
  CommandRunResultSchema,
  EditSessionSchema,
  ExportResponseSchema,
  EnvVarCheckSchema,
  McpImportResultSchema,
  McpServerConfigListSchema,
  ModelConfigListSchema,
  ProjectListSchema,
  ProjectSchema,
  RagKnowledgeBaseInspectionSchema,
  RagKnowledgeBaseListSchema,
  ResourceGroupConfigListSchema,
  RuntimeEnvironmentConfigListSchema,
  RunPreviewResultSchema,
  SkillConfigListSchema,
  SkillImportResultSchema,
  ToolConfigListSchema,
  ToolImportResultSchema,
  ValidationResultSchema,
} from "./schemas";

const API_BASE = "";

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json();
}

async function parseResponseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return response.statusText;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // Keep the raw response body below.
  }
  return text;
}

export async function createProject(name = "Untitled Agent", kind: "agent" | "agents" = "agent"): Promise<ProjectIR> {
  const data = await request("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name, kind }),
  });
  return ProjectSchema.parse(data) as ProjectIR;
}

export async function listProjects(): Promise<ProjectListItem[]> {
  const data = await request("/api/projects");
  return ProjectListSchema.parse(data) as ProjectListItem[];
}

export async function getProject(projectId: string): Promise<ProjectIR> {
  const data = await request(`/api/projects/${projectId}`);
  return ProjectSchema.parse(data) as ProjectIR;
}

export async function deleteProject(projectId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/projects/${projectId}`, { method: "DELETE" });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
}

export async function saveProject(project: ProjectIR): Promise<ProjectIR> {
  const data = await request(`/api/projects/${project.project.id}`, {
    method: "PUT",
    body: JSON.stringify(project),
  });
  return ProjectSchema.parse(data) as ProjectIR;
}

export function autosaveProject(project: ProjectIR): void {
  const body = JSON.stringify(project);
  void fetch(`${API_BASE}/api/projects/${project.project.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => undefined);
}

export async function validateProject(projectId: string): Promise<ValidationResult> {
  const data = await request(`/api/projects/${projectId}/validate`, { method: "POST" });
  return ValidationResultSchema.parse(data) as ValidationResult;
}

export async function exportProject(projectId: string): Promise<ExportResponse> {
  const data = await request(`/api/projects/${projectId}/export`, { method: "POST" });
  return ExportResponseSchema.parse(data) as ExportResponse;
}

export async function listWorkspaceTools(): Promise<ToolConfig[]> {
  const data = await request("/api/workspace/tools");
  return ToolConfigListSchema.parse(data) as ToolConfig[];
}

export async function saveWorkspaceTools(configs: ToolConfig[]): Promise<ToolConfig[]> {
  const data = await request("/api/workspace/tools", {
    method: "PUT",
    body: JSON.stringify(configs),
  });
  return ToolConfigListSchema.parse(data) as ToolConfig[];
}

export async function importWorkspaceToolsFromSource(sourceType: "local" | "github", source: string, useMirror = true): Promise<ToolImportResult> {
  const data = await request("/api/workspace/tools/import", {
    method: "POST",
    body: JSON.stringify({ sourceType, source, useMirror }),
  });
  return ToolImportResultSchema.parse(data) as ToolImportResult;
}

export async function uploadWorkspaceToolFolder(files: File[], rootName: string): Promise<ToolImportResult> {
  const form = new FormData();
  form.append("rootName", rootName);
  for (const file of files) {
    const relativePath = "webkitRelativePath" in file && typeof file.webkitRelativePath === "string" && file.webkitRelativePath
      ? file.webkitRelativePath
      : file.name;
    form.append("files", file, relativePath);
  }
  const response = await fetch(`${API_BASE}/api/workspace/tools/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(await parseResponseError(response));
  }
  const data = await response.json();
  return ToolImportResultSchema.parse(data) as ToolImportResult;
}

export async function listBuiltinToolPresets(): Promise<ToolConfig[]> {
  const data = await request("/api/workspace/tools/presets");
  return ToolConfigListSchema.parse(data) as ToolConfig[];
}

export async function installBuiltinToolPresets(ids: string[]): Promise<ToolImportResult> {
  const data = await request("/api/workspace/tools/presets/install", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
  return ToolImportResultSchema.parse(data) as ToolImportResult;
}

export async function listWorkspaceSkills(): Promise<SkillConfig[]> {
  const data = await request("/api/workspace/skills");
  return SkillConfigListSchema.parse(data) as SkillConfig[];
}

export async function saveWorkspaceSkills(configs: SkillConfig[]): Promise<SkillConfig[]> {
  const data = await request("/api/workspace/skills", {
    method: "PUT",
    body: JSON.stringify(configs),
  });
  return SkillConfigListSchema.parse(data) as SkillConfig[];
}

export async function importWorkspaceSkillsFromSource(sourceType: "local" | "github", source: string, useMirror = true): Promise<SkillImportResult> {
  const data = await request("/api/workspace/skills/import", {
    method: "POST",
    body: JSON.stringify({ sourceType, source, useMirror }),
  });
  return SkillImportResultSchema.parse(data) as SkillImportResult;
}

export async function uploadWorkspaceSkillFolder(files: File[], rootName: string): Promise<SkillImportResult> {
  const form = new FormData();
  form.append("rootName", rootName);
  for (const file of files) {
    const relativePath = "webkitRelativePath" in file && typeof file.webkitRelativePath === "string" && file.webkitRelativePath
      ? file.webkitRelativePath
      : file.name;
    form.append("files", file, relativePath);
  }
  const response = await fetch(`${API_BASE}/api/workspace/skills/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(await parseResponseError(response));
  }
  const data = await response.json();
  return SkillImportResultSchema.parse(data) as SkillImportResult;
}

export async function listWorkspaceResourceGroups(): Promise<ResourceGroupConfig[]> {
  const data = await request("/api/workspace/resource-groups");
  return ResourceGroupConfigListSchema.parse(data) as ResourceGroupConfig[];
}

export async function saveWorkspaceResourceGroups(groups: ResourceGroupConfig[]): Promise<ResourceGroupConfig[]> {
  const data = await request("/api/workspace/resource-groups", {
    method: "PUT",
    body: JSON.stringify(groups),
  });
  return ResourceGroupConfigListSchema.parse(data) as ResourceGroupConfig[];
}

export async function listWorkspaceMcpServers(): Promise<MCPServerConfig[]> {
  const data = await request("/api/workspace/mcp");
  return McpServerConfigListSchema.parse(data) as MCPServerConfig[];
}

export async function saveWorkspaceMcpServers(configs: MCPServerConfig[]): Promise<MCPServerConfig[]> {
  const data = await request("/api/workspace/mcp", {
    method: "PUT",
    body: JSON.stringify(configs),
  });
  return McpServerConfigListSchema.parse(data) as MCPServerConfig[];
}

export async function importWorkspaceMcpServers(payload: { sourceType: "local" | "github"; source: string; useMirror: boolean }): Promise<McpImportResult> {
  const data = await request("/api/workspace/mcp/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return McpImportResultSchema.parse(data) as McpImportResult;
}

export async function listWorkspaceModelConfigs(): Promise<ModelConfig[]> {
  const data = await request("/api/workspace/models");
  return ModelConfigListSchema.parse(data) as ModelConfig[];
}

export async function saveWorkspaceModelConfigs(configs: ModelConfig[]): Promise<ModelConfig[]> {
  const data = await request("/api/workspace/models", {
    method: "PUT",
    body: JSON.stringify(configs),
  });
  return ModelConfigListSchema.parse(data) as ModelConfig[];
}

export async function listWorkspaceRuntimeEnvironments(): Promise<RuntimeEnvironmentConfig[]> {
  const data = await request("/api/workspace/runtime-environments");
  return RuntimeEnvironmentConfigListSchema.parse(data) as RuntimeEnvironmentConfig[];
}

export async function saveWorkspaceRuntimeEnvironments(configs: RuntimeEnvironmentConfig[]): Promise<RuntimeEnvironmentConfig[]> {
  const data = await request("/api/workspace/runtime-environments", {
    method: "PUT",
    body: JSON.stringify(configs),
  });
  return RuntimeEnvironmentConfigListSchema.parse(data) as RuntimeEnvironmentConfig[];
}

export async function getEditSession(patchId: string): Promise<EditSession> {
  const data = await request(`/api/edit-sessions/${patchId}`);
  return EditSessionSchema.parse(data) as EditSession;
}

export async function applyEditSession(patchId: string, runtimeEnvironment?: RuntimeEnvironmentConfig): Promise<EditSession> {
  const data = await request(`/api/edit-sessions/${patchId}/apply`, {
    method: "POST",
    body: JSON.stringify({ runtimeEnvironment }),
  });
  return EditSessionSchema.parse(data) as EditSession;
}

export async function discardEditSession(patchId: string): Promise<EditSession> {
  const data = await request(`/api/edit-sessions/${patchId}/discard`, { method: "POST" });
  return EditSessionSchema.parse(data) as EditSession;
}

export async function rollbackEditSession(rollbackId: string): Promise<EditSession> {
  const data = await request(`/api/edit-sessions/rollback/${rollbackId}`, { method: "POST" });
  return EditSessionSchema.parse(data) as EditSession;
}

export async function runEditCommand(command: string, cwd: string, runtimeEnvironment?: RuntimeEnvironmentConfig, timeoutSeconds = 60): Promise<CommandRunResult> {
  const data = await request("/api/edit-sessions/commands/run", {
    method: "POST",
    body: JSON.stringify({ command, cwd, timeoutSeconds, runtimeEnvironment }),
  });
  return CommandRunResultSchema.parse(data) as CommandRunResult;
}

export async function checkWorkspaceEnvVar(name: string): Promise<EnvVarCheckResult> {
  const data = await request("/api/workspace/env/check", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  return EnvVarCheckSchema.parse(data) as EnvVarCheckResult;
}

export async function listWorkspaceRagKnowledgeBases(): Promise<RagKnowledgeBaseConfig[]> {
  const data = await request("/api/workspace/rag");
  return RagKnowledgeBaseListSchema.parse(data) as RagKnowledgeBaseConfig[];
}

export async function saveWorkspaceRagKnowledgeBases(configs: RagKnowledgeBaseConfig[]): Promise<RagKnowledgeBaseConfig[]> {
  const data = await request("/api/workspace/rag", {
    method: "PUT",
    body: JSON.stringify(configs),
  });
  return RagKnowledgeBaseListSchema.parse(data) as RagKnowledgeBaseConfig[];
}

export async function inspectRagKnowledgeBasePath(path: string): Promise<RagKnowledgeBaseInspection> {
  const data = await request("/api/workspace/rag/inspect", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  return RagKnowledgeBaseInspectionSchema.parse(data) as RagKnowledgeBaseInspection;
}

export async function runProjectPreview(
  projectId: string,
  input: Record<string, unknown>,
  mode: RunMode,
  modelConfig?: ModelConfig,
  runtimeEnvironment?: RuntimeEnvironmentConfig,
): Promise<RunPreviewResult> {
  const data = await request(`/api/projects/${projectId}/run`, {
    method: "POST",
    body: JSON.stringify({ input, mode, modelConfig, runtimeEnvironment }),
  });
  return RunPreviewResultSchema.parse(data) as RunPreviewResult;
}

export async function streamProjectPreview(
  projectId: string,
  input: Record<string, unknown>,
  mode: RunMode,
  modelConfig: ModelConfig | undefined,
  runtimeEnvironment: RuntimeEnvironmentConfig | undefined,
  onEvent: (event: RunStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/projects/${projectId}/run/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input, mode, modelConfig, runtimeEnvironment }),
    signal,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  if (!response.body) {
    throw new Error("运行流响应为空。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      onEvent(JSON.parse(trimmed) as RunStreamEvent);
    }
    if (done) break;
  }
  if (buffer.trim()) {
    onEvent(JSON.parse(buffer) as RunStreamEvent);
  }
}
