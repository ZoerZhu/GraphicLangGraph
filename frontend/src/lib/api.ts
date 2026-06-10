import type { ExportResponse, ProjectIR, ProjectListItem, RunPreviewResult, ValidationResult } from "../types";
import { ExportResponseSchema, ProjectListSchema, ProjectSchema, RunPreviewResultSchema, ValidationResultSchema } from "./schemas";

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

export async function runProjectPreview(projectId: string, input: Record<string, unknown>): Promise<RunPreviewResult> {
  const data = await request(`/api/projects/${projectId}/run`, {
    method: "POST",
    body: JSON.stringify({ input }),
  });
  return RunPreviewResultSchema.parse(data) as RunPreviewResult;
}
