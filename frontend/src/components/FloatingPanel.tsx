import { useEffect, useRef, useState } from "react";

export interface FloatingRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface FloatingPanelRenderContext {
  width: number;
  height: number;
  rect: FloatingRect;
}

interface FloatingPanelProps {
  title: string;
  subtitle?: React.ReactNode;
  className?: string;
  initialRect: FloatingRect | (() => FloatingRect);
  minWidth?: number;
  minHeight?: number;
  maxWidth?: number;
  maxHeight?: number;
  actions?: React.ReactNode;
  bare?: boolean;
  dragSurface?: "titlebar" | "panel";
  dragDelayMs?: number;
  children: React.ReactNode | ((context: FloatingPanelRenderContext) => React.ReactNode);
}

type InteractionMode = "drag" | "resize";

interface InteractionState {
  mode: InteractionMode;
  pointerX: number;
  pointerY: number;
  rect: FloatingRect;
}

interface PendingDragState {
  pointerX: number;
  pointerY: number;
  timer: number;
}

const VIEWPORT_MARGIN = 10;
const PANEL_HORIZONTAL_CHROME = 24;
const PANEL_VERTICAL_CHROME = 58;
const PANEL_BARE_CHROME = 24;

export function FloatingPanel({
  title,
  subtitle,
  className = "",
  initialRect,
  minWidth = 260,
  minHeight = 220,
  maxWidth,
  maxHeight,
  actions,
  bare = false,
  dragSurface = "titlebar",
  dragDelayMs = 0,
  children,
}: FloatingPanelProps) {
  const interactionRef = useRef<InteractionState | null>(null);
  const pendingDragRef = useRef<PendingDragState | null>(null);
  const suppressClickRef = useRef(false);
  const [interacting, setInteracting] = useState<InteractionMode | null>(null);
  const [rect, setRect] = useState(() =>
    clampRect(resolveInitialRect(initialRect), { minWidth, minHeight, maxWidth, maxHeight }),
  );

  useEffect(() => {
    function updateInteraction(clientX: number, clientY: number) {
      const interaction = interactionRef.current;
      if (!interaction) return;

      const deltaX = clientX - interaction.pointerX;
      const deltaY = clientY - interaction.pointerY;
      const nextRect =
        interaction.mode === "drag"
          ? { ...interaction.rect, x: interaction.rect.x + deltaX, y: interaction.rect.y + deltaY }
          : {
              ...interaction.rect,
              width: interaction.rect.width + deltaX,
              height: interaction.rect.height + deltaY,
            };
      setRect(clampRect(nextRect, { minWidth, minHeight, maxWidth, maxHeight }));
    }

    function handlePointerMove(event: PointerEvent) {
      if (!interactionRef.current) return;
      event.preventDefault();
      updateInteraction(event.clientX, event.clientY);
    }

    function handleMouseMove(event: MouseEvent) {
      if (!interactionRef.current) return;
      event.preventDefault();
      updateInteraction(event.clientX, event.clientY);
    }

    function stopInteraction() {
      clearPendingDrag();
      interactionRef.current = null;
      setInteracting(null);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopInteraction);
    window.addEventListener("pointercancel", stopInteraction);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", stopInteraction);
    return () => {
      clearPendingDrag();
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopInteraction);
      window.removeEventListener("pointercancel", stopInteraction);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopInteraction);
    };
  }, [maxHeight, maxWidth, minHeight, minWidth]);

  useEffect(() => {
    function handleResize() {
      setRect((current) => clampRect(current, { minWidth, minHeight, maxWidth, maxHeight }));
    }

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [maxHeight, maxWidth, minHeight, minWidth]);

  function clearPendingDrag() {
    if (!pendingDragRef.current) return;
    window.clearTimeout(pendingDragRef.current.timer);
    pendingDragRef.current = null;
  }

  function startInteraction(mode: InteractionMode, event: React.PointerEvent | React.MouseEvent) {
    if (interactionRef.current) return;
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (mode === "drag" && target.closest("button, a, input, select, textarea, [data-no-drag]")) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    interactionRef.current = {
      mode,
      pointerX: event.clientX,
      pointerY: event.clientY,
      rect,
    };
    setInteracting(mode);
  }

  function beginPanelDrag(event: React.PointerEvent | React.MouseEvent) {
    if (dragSurface !== "panel" || interactionRef.current || pendingDragRef.current) return;
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, select, textarea, [data-no-drag]")) return;
    event.stopPropagation();
    const pointerX = event.clientX;
    const pointerY = event.clientY;
    const timer = window.setTimeout(() => {
      pendingDragRef.current = null;
      interactionRef.current = {
        mode: "drag",
        pointerX,
        pointerY,
        rect,
      };
      suppressClickRef.current = true;
      setInteracting("drag");
    }, dragDelayMs);
    pendingDragRef.current = { pointerX, pointerY, timer };
  }

  function handlePanelClickCapture(event: React.MouseEvent) {
    if (!suppressClickRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClickRef.current = false;
  }

  const contentWidth = Math.max(0, rect.width - PANEL_HORIZONTAL_CHROME);
  const contentHeight = Math.max(0, rect.height - (bare ? PANEL_BARE_CHROME : PANEL_VERTICAL_CHROME));
  const content =
    typeof children === "function"
      ? children({ width: contentWidth, height: contentHeight, rect })
      : children;

  return (
    <section
      className={`floating-panel glass-panel interactive-surface nodrag nopan ${bare ? "floating-panel--bare" : ""} ${className} ${interacting ? `is-${interacting}` : ""}`}
      onClickCapture={handlePanelClickCapture}
      onMouseDown={beginPanelDrag}
      onPointerDown={beginPanelDrag}
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.width,
        height: rect.height,
      }}
    >
      {bare ? (
        null
      ) : (
        <div
          className="floating-panel__titlebar"
          onMouseDown={(event) => startInteraction("drag", event)}
          onPointerDown={(event) => startInteraction("drag", event)}
        >
          <div className="floating-panel__title">
            <span>{title}</span>
            {subtitle ? <small>{subtitle}</small> : null}
          </div>
          {actions ? <div className="floating-panel__actions">{actions}</div> : null}
        </div>
      )}
      <div className="floating-panel__content">{content}</div>
      <button
        aria-label={`调整${title}大小`}
        className="floating-panel__resize"
        onMouseDown={(event) => startInteraction("resize", event)}
        onPointerDown={(event) => startInteraction("resize", event)}
        title="拖拽调整大小"
        type="button"
      />
    </section>
  );
}

function resolveInitialRect(initialRect: FloatingRect | (() => FloatingRect)) {
  return typeof initialRect === "function" ? initialRect() : initialRect;
}

function clampRect(
  rect: FloatingRect,
  constraints: {
    minWidth: number;
    minHeight: number;
    maxWidth?: number;
    maxHeight?: number;
  },
): FloatingRect {
  const viewport = getViewport();
  const viewportMaxWidth = Math.max(180, viewport.width - VIEWPORT_MARGIN * 2);
  const viewportMaxHeight = Math.max(160, viewport.height - VIEWPORT_MARGIN * 2);
  const maxWidth = Math.min(constraints.maxWidth ?? viewportMaxWidth, viewportMaxWidth);
  const maxHeight = Math.min(constraints.maxHeight ?? viewportMaxHeight, viewportMaxHeight);
  const minWidth = Math.min(constraints.minWidth, maxWidth);
  const minHeight = Math.min(constraints.minHeight, maxHeight);
  const width = clamp(rect.width, minWidth, maxWidth);
  const height = clamp(rect.height, minHeight, maxHeight);
  const x = clamp(rect.x, VIEWPORT_MARGIN, Math.max(VIEWPORT_MARGIN, viewport.width - width - VIEWPORT_MARGIN));
  const y = clamp(rect.y, VIEWPORT_MARGIN, Math.max(VIEWPORT_MARGIN, viewport.height - height - VIEWPORT_MARGIN));
  return { x, y, width, height };
}

function getViewport() {
  if (typeof window === "undefined") {
    return { width: 1440, height: 900 };
  }
  return { width: window.innerWidth, height: window.innerHeight };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
