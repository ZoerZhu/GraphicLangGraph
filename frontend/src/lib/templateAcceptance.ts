import type { NodeType, ProjectIR, RunPreviewResult, TemplateAcceptanceResult } from "../types";
import { getProjectTemplateForProject, type ProjectTemplate } from "./templates";

export function evaluateTemplateAcceptance(project: ProjectIR | null, result: RunPreviewResult | null): TemplateAcceptanceResult | null {
  const template = getProjectTemplateForProject(project);
  if (!template || !result) return null;
  const missingFields = template.expectedOutputFields.filter((field) => !hasMeaningfulValue(result.outputState, field));
  const traceTypes = new Set(result.trace.map((item) => item.type));
  const missingTraceTypes = template.expectedTraceTypes.filter((type) => !traceTypes.has(type));
  const errorTraceCount = result.trace.filter((item) => item.status === "error").length;
  const finalAnswerPresent = hasMeaningfulValue(result.outputState, "final_answer");
  const warnings = templateAcceptanceWarnings(template, result, missingFields, missingTraceTypes, errorTraceCount, finalAnswerPresent);
  return {
    ok: warnings.length === 0,
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
  result: RunPreviewResult,
  missingFields: string[],
  missingTraceTypes: NodeType[],
  errorTraceCount: number,
  finalAnswerPresent: boolean,
) {
  const warnings: string[] = [];
  if (!result.valid) warnings.push("图校验未通过");
  if (!finalAnswerPresent) warnings.push("缺少 final_answer");
  if (missingFields.length) warnings.push(`缺少输出字段：${missingFields.join(", ")}`);
  if (missingTraceTypes.length) warnings.push(`缺少 trace 类型：${missingTraceTypes.join(", ")}`);
  if (errorTraceCount > 0) warnings.push(`存在 ${errorTraceCount} 个错误 trace`);
  if (template.id === "api_json_cleanup" && getPath(result.outputState, "order_validation.valid") !== true) {
    warnings.push("order_validation.valid 未通过");
  }
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
