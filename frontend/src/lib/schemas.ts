import { z } from "zod";

export const NodeTypeSchema = z.enum([
  "start",
  "llm",
  "condition",
  "http",
  "direct_reply",
  "custom_function",
]);

export const ProjectSchema = z.object({
  project: z.object({
    id: z.string(),
    name: z.string(),
    description: z.string(),
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
});

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
    }),
  ),
});

export const ExportResponseSchema = z.object({
  exportId: z.string(),
  downloadUrl: z.string(),
  files: z.array(z.string()),
});

