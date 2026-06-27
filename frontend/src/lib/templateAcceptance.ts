import type { MCPServerConfig, NodeType, ProjectIR, RunPreviewResult, RuntimeEnvironmentConfig, TemplateAcceptanceResult } from "../types";
import { getProjectTemplateForProject, type ProjectTemplate } from "./templates";

export function evaluateTemplateAcceptance(
  project: ProjectIR | null,
  result: RunPreviewResult | null,
  runtimeEnvironment: RuntimeEnvironmentConfig | null = null,
): TemplateAcceptanceResult | null {
  const template = getProjectTemplateForProject(project);
  if (!template || !project || !result) return null;
  const missingFields = template.expectedOutputFields.filter((field) => !hasMeaningfulValue(result.outputState, field));
  const traceTypes = new Set(result.trace.map((item) => item.type));
  const missingTraceTypes = template.expectedTraceTypes.filter((type) => !traceTypes.has(type));
  const errorTraceCount = result.trace.filter((item) => item.status === "error").length;
  const finalAnswerPresent = hasMeaningfulValue(result.outputState, "final_answer");
  const pausedForApproval = result.status === "paused" && result.trace.some((item) => item.type === "human_approval" && item.pause === true);
  const warnings = templateAcceptanceWarnings(
    template,
    project,
    result,
    missingFields,
    missingTraceTypes,
    errorTraceCount,
    finalAnswerPresent,
    pausedForApproval,
    runtimeEnvironment,
  );
  return {
    ok: warnings.length === 0 || (pausedForApproval && errorTraceCount === 0 && !missingTraceTypes.length),
    templateId: template.id,
    templateName: template.name,
    missingFields,
    missingTraceTypes,
    warnings,
    errorTraceCount,
    finalAnswerPresent,
  };
}

function templateAcceptanceWarnings(
  template: ProjectTemplate,
  project: ProjectIR,
  result: RunPreviewResult,
  missingFields: string[],
  missingTraceTypes: NodeType[],
  errorTraceCount: number,
  finalAnswerPresent: boolean,
  pausedForApproval: boolean,
  runtimeEnvironment: RuntimeEnvironmentConfig | null,
) {
  const warnings: string[] = [];
  warnings.push(...templateDependencyWarnings(template, project, runtimeEnvironment));
  if (!result.valid) warnings.push("图校验未通过");
  if (!finalAnswerPresent && !pausedForApproval) warnings.push("缺少 final_answer");
  if (missingFields.length) warnings.push(`缺少输出字段：${missingFields.join(", ")}`);
  if (missingTraceTypes.length) warnings.push(`缺少 trace 类型：${missingTraceTypes.join(", ")}`);
  if (errorTraceCount > 0) warnings.push(`存在 ${errorTraceCount} 个错误 trace`);
  if (pausedForApproval) warnings.push("运行已在 Human Approval 暂停，审批后继续验收 final_answer");
  if (template.id === "api_json_cleanup" && getPath(result.outputState, "order_validation.valid") !== true) {
    warnings.push("order_validation.valid 未通过");
  }
  if (template.id === "websearch_exa_mcp") warnings.push(...exaWebSearchWarnings(result));
  return warnings;
}

function templateDependencyWarnings(
  template: ProjectTemplate,
  project: ProjectIR,
  runtimeEnvironment: RuntimeEnvironmentConfig | null,
): string[] {
  const warnings: string[] = [];
  for (const requiredServer of template.requiredMcpServers ?? []) {
    const server = (project.mcpServers ?? []).find((item) => item.id === requiredServer.id);
    if (!server) {
      warnings.push(`项目未包含 MCP：${requiredServer.name}`);
      continue;
    }
    if (server.enabled === false) warnings.push(`MCP 未启用：${server.name}`);
    for (const envVar of template.requiredEnvVars ?? []) {
      if (!hasMcpCredentialSource(server, envVar)) warnings.push(`${server.name} 未配置 ${envVar} 的密钥来源`);
    }
  }
  const requiredHosts = template.requiredRuntimeHosts ?? [];
  if (requiredHosts.length) {
    if (!runtimeEnvironment) {
      warnings.push(`缺少运行环境，无法确认允许域名：${requiredHosts.join(", ")}`);
    } else if (runtimeEnvironment.networkEnabled === false) {
      warnings.push("运行环境未开启网络访问");
    } else if (runtimeEnvironment.allowAllHosts !== true) {
      const allowedHosts = parseStringList(runtimeEnvironment.allowedHostsJson);
      const missingHosts = requiredHosts.filter((host) => !isHostAllowedByList(host, allowedHosts));
      if (missingHosts.length) warnings.push(`运行环境未允许域名：${missingHosts.join(", ")}`);
    }
  }
  return warnings;
}

function hasMcpCredentialSource(server: MCPServerConfig, envVar: string): boolean {
  if (server.apiKeyMode === "direct" && server.apiKey.trim()) return true;
  if (server.apiKeyEnv.trim() === envVar) return true;
  if (server.bearerTokenEnvVar.trim() === envVar) return true;
  if (server.envHttpHeadersJson.includes(envVar)) return true;
  if (server.httpHeadersJson.includes(envVar)) return true;
  return false;
}

function exaWebSearchWarnings(result: RunPreviewResult): string[] {
  const warnings: string[] = [];
  const searchResult = getPath(result.outputState, "exa_search_result");
  if (!isRecord(searchResult)) {
    warnings.push("exa_search_result 未写入 MCP 结果");
    return warnings;
  }
  if (searchResult.ok !== true) warnings.push("exa_search_result.ok 未通过");
  const serialized = JSON.stringify({ output: searchResult, trace: result.trace.filter((item) => item.type === "mcp_node") }).toLowerCase();
  const hasToolEvidence = serialized.includes("web_search_exa") || searchResult.selectedByModel === true || searchResult.autoSelectedTool === true;
  if (!hasToolEvidence) warnings.push("未看到 web_search_exa 或自动选择工具的记录");
  return warnings;
}

function hasMeaningfulValue(record: Record<string, unknown>, path: string) {
  const value = getPath(record, path);
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  return true;
}

function getPath(record: Record<string, unknown>, path: string): unknown {
  let current: unknown = record;
  for (const segment of path.split(".")) {
    if (!segment) continue;
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function parseStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  const text = String(value ?? "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parsed.map((item) => String(item).trim()).filter(Boolean);
  } catch {
    return text.split(/[;,\n]+/).map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function isHostAllowedByList(host: string, allowedHosts: string[]): boolean {
  const normalizedHost = host.trim().toLowerCase();
  return allowedHosts.some((item) => {
    const candidate = item.trim().toLowerCase();
    if (!candidate) return false;
    if (candidate === "*" || candidate === normalizedHost) return true;
    if (candidate.startsWith("*.")) return normalizedHost.endsWith(candidate.slice(1));
    return false;
  });
}
