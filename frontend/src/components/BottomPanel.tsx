import { AlertCircle, CheckCircle2, Download, FileArchive } from "lucide-react";
import { useProjectStore } from "../store/projectStore";

export function BottomPanel() {
  const validation = useProjectStore((state) => state.validation);
  const exportResult = useProjectStore((state) => state.exportResult);
  const status = useProjectStore((state) => state.status);

  return (
    <section className="bottom-panel glass-panel">
      <div className="bottom-panel__status">
        {validation?.valid ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
        <span>{status}</span>
      </div>
      <div className="issues">
        {validation?.issues.slice(0, 4).map((issue) => (
          <span key={`${issue.code}-${issue.nodeId ?? issue.edgeId ?? issue.field}`} className={`issue ${issue.severity}`}>
            {issue.nodeId ? `${issue.nodeId}: ` : ""}
            {issue.message}
          </span>
        ))}
      </div>
      {exportResult && (
        <a className="download-link" href={exportResult.downloadUrl}>
          <FileArchive size={16} />
          <span>{exportResult.exportId}.zip</span>
          <Download size={15} />
        </a>
      )}
    </section>
  );
}

