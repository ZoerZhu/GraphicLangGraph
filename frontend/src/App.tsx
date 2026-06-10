import { useEffect } from "react";
import { BottomPanel } from "./components/BottomPanel";
import { Canvas } from "./components/Canvas";
import { Inspector } from "./components/Inspector";
import { NodePalette } from "./components/NodePalette";
import { TopBar } from "./components/TopBar";
import { useProjectStore } from "./store/projectStore";
import "./styles.css";

export default function App() {
  const initialize = useProjectStore((state) => state.initialize);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  return (
    <div className="app-shell">
      <Canvas />
      <TopBar />
      <NodePalette />
      <Inspector />
      <BottomPanel />
    </div>
  );
}
