import { useEffect } from "react";
import { Canvas } from "./components/Canvas";
import { AssistantPanel } from "./components/AssistantPanel";
import { Inspector } from "./components/Inspector";
import { ManagementPage } from "./components/ManagementPage";
import { NodePalette } from "./components/NodePalette";
import { RunPreviewPanel } from "./components/RunPreviewPanel";
import { SplitAgentWorkspace } from "./components/SplitAgentWorkspace";
import { TemplatePanel } from "./components/TemplatePanel";
import { TopBar } from "./components/TopBar";
import { ValidationPanel } from "./components/ValidationPanel";
import { useProjectStore } from "./store/projectStore";
import "./styles.css";

export default function App() {
  const initialize = useProjectStore((state) => state.initialize);
  const mode = useProjectStore((state) => state.mode);
  const splitAgentProject = useProjectStore((state) => state.splitAgentProject);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    function handlePageExit() {
      useProjectStore.getState().saveBeforeUnload();
    }

    window.addEventListener("pagehide", handlePageExit);
    window.addEventListener("beforeunload", handlePageExit);
    return () => {
      window.removeEventListener("pagehide", handlePageExit);
      window.removeEventListener("beforeunload", handlePageExit);
    };
  }, []);

  if (mode === "manager") {
    return <ManagementPage />;
  }

  const editor = (
    <div className="app-shell">
      <Canvas />
      <TopBar />
      <TemplatePanel />
      <AssistantPanel />
      <ValidationPanel />
      <RunPreviewPanel />
      <NodePalette />
      <Inspector />
    </div>
  );

  if (splitAgentProject) {
    return <SplitAgentWorkspace>{editor}</SplitAgentWorkspace>;
  }

  return editor;
}
