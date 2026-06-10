import type { ExportResponse, ProjectIR, ValidationResult } from "../types";
import { ExportResponseSchema, ProjectSchema, ValidationResultSchema } from "./schemas";

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

export async function createProject(name = "Untitled Agent"): Promise<ProjectIR> {
  const data = await request("/api/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  return ProjectSchema.parse(data) as ProjectIR;
}

export async function getProject(projectId: string): Promise<ProjectIR> {
  const data = await request(`/api/projects/${projectId}`);
  return ProjectSchema.parse(data) as ProjectIR;
}

export async function saveProject(project: ProjectIR): Promise<ProjectIR> {
  const data = await request(`/api/projects/${project.project.id}`, {
    method: "PUT",
    body: JSON.stringify(project),
  });
  return ProjectSchema.parse(data) as ProjectIR;
}

export async function validateProject(projectId: string): Promise<ValidationResult> {
  const data = await request(`/api/projects/${projectId}/validate`, { method: "POST" });
  return ValidationResultSchema.parse(data) as ValidationResult;
}

export async function exportProject(projectId: string): Promise<ExportResponse> {
  const data = await request(`/api/projects/${projectId}/export`, { method: "POST" });
  return ExportResponseSchema.parse(data) as ExportResponse;
}
