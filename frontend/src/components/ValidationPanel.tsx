import { AlertTriangle, CheckCircle2, LocateFixed, X } from "lucide-react";
import { useProjectStore } from "../store/projectStore";
import type { ValidationIssue } from "../types";
import { FloatingPanel } from "./FloatingPanel";

export function ValidationPanel() {
  const validation = useProjectStore((state) => state.validation);
  const open = useProjectStore((state) => state.validationOpen);
  const selectNode = useProjectStore((state) => state.selectNode);
  const closeValidationPanel = useProjectStore((state) => state.closeValidationPanel);

  if (!open || !validation) return null;

  const errorCount = validation.issues.filter((issue) => issue.severity === "error").length;
  const warningCount = validation.issues.filter((issue) => issue.severity === "warning").length;

  return (
    <FloatingPanel
      title="图校验"
      subtitle={validation.valid ? "校验通过" : `${errorCount} 错误 · ${warningCount} 警告`}
      className="validation-panel"
      initialRect={validationPanelInitialRect}
      minWidth={360}
      minHeight={260}
      maxWidth={620}
      maxHeight={720}
      actions={
        <button className="icon-only panel-close" onClick={closeValidationPanel} title="关闭校验结果" type="button">
          <X size={15} />
        </button>
      }
    >
      <div className="validation-panel__body">
        <div className={`run-valid ${validation.valid ? "is-valid" : "is-invalid"}`}>
          {validation.valid ? "图校验通过，可以继续运行或导出" : `图校验发现 ${validation.issues.length} 个问题`}
        </div>

        {validation.issues.length ? (
          <div className="validation-issues">
            {validation.issues.map((issue, index) => (
              <button
                key={`${issue.code}-${issue.nodeId ?? issue.edgeId ?? issue.field ?? index}`}
                className={`validation-issue is-${issue.severity}`}
                disabled={!issue.nodeId}
                onClick={() => issue.nodeId && selectNode(issue.nodeId)}
                title={issue.nodeId ? "定位到对应节点" : "该问题没有关联节点"}
                type="button"
              >
                <span className="validation-issue__icon">
                  {issue.severity === "error" ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
                </span>
                <span className="validation-issue__content">
                  <strong>{formatIssueTitle(issue)}</strong>
                  <small>{formatIssueDetail(issue)}</small>
                </span>
                {issue.nodeId ? <LocateFixed size={15} /> : null}
              </button>
            ))}
          </div>
        ) : (
          <div className="validation-empty">
            当前画布没有发现结构问题。
          </div>
        )}
      </div>
    </FloatingPanel>
  );
}

function validationPanelInitialRect() {
  const viewportWidth = typeof window === "undefined" ? 1440 : window.innerWidth;
  const viewportHeight = typeof window === "undefined" ? 900 : window.innerHeight;
  return {
    x: Math.max(18, viewportWidth - 456),
    y: 104,
    width: 420,
    height: Math.min(560, Math.max(320, viewportHeight - 140)),
  };
}

function formatIssueTitle(issue: ValidationIssue) {
  const location = issue.nodeId || issue.edgeId || issue.field || issue.code;
  return location ? `${location}` : issue.code;
}

function formatIssueDetail(issue: ValidationIssue) {
  const field = issue.field ? `字段：${issue.field} · ` : "";
  const suggestion = issue.suggestion ? ` · ${issue.suggestion}` : "";
  return `${field}${issue.message}${suggestion}`;
}
