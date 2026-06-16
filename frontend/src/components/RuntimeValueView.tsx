import type { MouseEvent } from "react";

interface RuntimeValueViewProps {
  value: unknown;
  depth?: number;
  fieldKey?: string;
  context?: RuntimeContext;
}

interface RuntimeContext {
  path?: string;
}

const STRUCTURED_LIST_KEYS = new Set(["matches", "chunks", "symbols", "rules", "recommendedNextTools"]);
const LONG_COLLAPSED_KEYS = new Set(["content", "html", "css"]);

export function RuntimeValueView({ value, depth = 0, fieldKey = "", context = {} }: RuntimeValueViewProps) {
  if (typeof value === "string") {
    if (shouldCollapseString(fieldKey, value)) {
      return <RuntimeFoldedText fieldKey={fieldKey} text={value} />;
    }
    return <RuntimeMarkdown text={value} />;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return <div className="runtime-value__scalar">{String(value)}</div>;
  }

  if (value === null || value === undefined) {
    return <div className="runtime-value__empty">空值</div>;
  }

  if (Array.isArray(value)) {
    if (!value.length) {
      return <div className="runtime-value__empty">空列表</div>;
    }
    if (STRUCTURED_LIST_KEYS.has(fieldKey) && value.every(isRecord)) {
      return <RuntimeStructuredList items={value as Record<string, unknown>[]} kind={fieldKey} context={context} />;
    }
    return (
      <div className="runtime-value__list">
        {value.slice(0, 10).map((item, index) => (
          <div key={index} className="runtime-value__list-item">
            <span>{index + 1}</span>
            {depth >= 3 ? <RuntimeStructuredValue value={item} /> : <RuntimeValueView value={item} depth={depth + 1} fieldKey={fieldKey} context={context} />}
          </div>
        ))}
        {value.length > 10 ? <div className="runtime-value__empty">还有 {value.length - 10} 项未显示</div> : null}
      </div>
    );
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (!entries.length) {
      return <div className="runtime-value__empty">空对象</div>;
    }
    const nextContext = { ...context, path: typeof value.path === "string" ? value.path : context.path };
    const badges = runtimeBadges(value);
    return (
      <div className="runtime-value__fields">
        {badges.length ? (
          <div className="runtime-value__badges">
            {badges.map((badge) => (
              <span key={badge.label} className={`runtime-value__badge is-${badge.tone}`}>
                {badge.label}
              </span>
            ))}
          </div>
        ) : null}
        {entries.slice(0, 16).map(([key, fieldValue]) => (
          <div key={key} className="runtime-value__field">
            <div className="runtime-value__field-key">{key}</div>
            <div className="runtime-value__field-value">
              {depth >= 3 && !STRUCTURED_LIST_KEYS.has(key) ? (
                <RuntimeStructuredValue value={fieldValue} />
              ) : (
                <RuntimeValueView value={fieldValue} depth={depth + 1} fieldKey={key} context={nextContext} />
              )}
            </div>
          </div>
        ))}
        {entries.length > 16 ? <div className="runtime-value__empty">还有 {entries.length - 16} 个字段未显示</div> : null}
      </div>
    );
  }

  return <div className="runtime-value__scalar">{String(value)}</div>;
}

function RuntimeFoldedText({ fieldKey, text }: { fieldKey: string; text: string }) {
  const preview = text.slice(0, 260);
  return (
    <details className="runtime-value__fold">
      <summary>
        <span>{fieldKey || "长文本"} · {text.length} 字符</span>
        <button type="button" onClick={(event) => copyRuntimeText(event, text)}>复制</button>
      </summary>
      <pre className="runtime-value__code">{text}</pre>
      <div className="runtime-value__fold-preview">{preview}{text.length > preview.length ? "..." : ""}</div>
    </details>
  );
}

function RuntimeStructuredValue({ value }: { value: unknown }) {
  const textValue = JSON.stringify(value, null, 2);
  return <pre className="runtime-value__code">{textValue.length > 900 ? `${textValue.slice(0, 900)}...` : textValue}</pre>;
}

function RuntimeStructuredList({
  items,
  kind,
  context,
}: {
  items: Record<string, unknown>[];
  kind: string;
  context: RuntimeContext;
}) {
  return (
    <div className={`runtime-structured-list runtime-structured-list--${kind}`}>
      {items.slice(0, 20).map((item, index) => (
        <RuntimeStructuredCard key={index} item={item} kind={kind} context={context} />
      ))}
      {items.length > 20 ? <div className="runtime-value__empty">还有 {items.length - 20} 项未显示</div> : null}
    </div>
  );
}

function RuntimeStructuredCard({
  item,
  kind,
  context,
}: {
  item: Record<string, unknown>;
  kind: string;
  context: RuntimeContext;
}) {
  const title = structuredTitle(item, kind);
  const meta = structuredMeta(item);
  const preview = structuredPreview(item);
  const nextArgs = nextToolArgs(item, kind, context);
  const badges = runtimeBadges(item);
  return (
    <article className="runtime-structured-card">
      <div className="runtime-structured-card__head">
        <span>
          <strong>{title}</strong>
          {meta ? <small>{meta}</small> : null}
        </span>
        {nextArgs ? (
          <button type="button" title={`复制 ${nextArgs.tool} 参数`} onClick={(event) => copyRuntimeJson(event, nextArgs)}>
            复制参数
          </button>
        ) : null}
      </div>
      {badges.length ? (
        <div className="runtime-value__badges">
          {badges.map((badge) => (
            <span key={badge.label} className={`runtime-value__badge is-${badge.tone}`}>
              {badge.label}
            </span>
          ))}
        </div>
      ) : null}
      {preview ? <p>{preview}</p> : null}
    </article>
  );
}

function RuntimeMarkdown({ text }: { text: string }) {
  const blocks = parseMarkdownBlocks(text);
  return (
    <div className="runtime-value__md">
      {blocks.map((block, index) => {
        if (block.type === "code") {
          return (
            <pre key={index} className="runtime-value__code">
              {block.text}
            </pre>
          );
        }
        if (block.type === "heading") {
          const Tag = `h${block.level}` as "h1" | "h2" | "h3";
          return (
            <Tag key={index} className="runtime-value__md-heading">
              {renderInlineMarkdown(block.text)}
            </Tag>
          );
        }
        if (block.type === "list") {
          return (
            <ul key={index} className="runtime-value__md-list">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={index} className="runtime-value__md-paragraph">
            {renderInlineMarkdown(block.text)}
          </p>
        );
      })}
    </div>
  );
}

function shouldCollapseString(fieldKey: string, text: string) {
  return LONG_COLLAPSED_KEYS.has(fieldKey) && text.length > 360;
}

function runtimeBadges(value: Record<string, unknown>) {
  const badges: Array<{ label: string; tone: "warning" | "error" | "info" }> = [];
  if (value.truncated === true) badges.push({ label: "已截断", tone: "warning" });
  if (value.ambiguous === true) badges.push({ label: "有歧义", tone: "warning" });
  if (Array.isArray(value.warnings) && value.warnings.length > 0) badges.push({ label: `${value.warnings.length} 条警告`, tone: "warning" });
  if (typeof value.errorType === "string" && value.errorType) badges.push({ label: errorTypeLabel(value.errorType), tone: "error" });
  if (value.ok === false) badges.push({ label: "调用失败", tone: "error" });
  return badges;
}

function errorTypeLabel(value: string) {
  switch (value) {
    case "path_permission":
      return "路径权限";
    case "file_too_large":
      return "文件过大";
    case "parse_error":
      return "解析失败";
    case "tool_args":
      return "参数错误";
    case "network_permission":
      return "网络权限";
    default:
      return "工具错误";
  }
}

function structuredTitle(item: Record<string, unknown>, kind: string) {
  if (kind === "recommendedNextTools") return String(item.tool || "下一步工具");
  return String(item.name || item.symbol || item.selector || item.selectorHint || item.tool || item.path || `${kind} item`);
}

function structuredMeta(item: Record<string, unknown>) {
  const parts = [
    valuePart("kind", item.kind),
    valuePart("line", lineRange(item)),
    valuePart("size", item.size),
    valuePart("count", item.count),
  ].filter(Boolean);
  return parts.join(" · ");
}

function structuredPreview(item: Record<string, unknown>) {
  const value = firstString(item.reason, item.preview, item.text, item.css, item.html, item.content, item.error);
  return value ? value.replace(/\s+/g, " ").slice(0, 260) : "";
}

function nextToolArgs(item: Record<string, unknown>, kind: string, context: RuntimeContext) {
  const path = firstString(item.path, context.path);
  if (kind === "recommendedNextTools" && typeof item.tool === "string") {
    return { tool: item.tool, args: isRecord(item.args) ? item.args : {} };
  }
  if (!path) return null;
  if (kind === "symbols") {
    return {
      tool: "extract_code_symbol",
      args: {
        path,
        symbol: String(item.name || ""),
        kind: String(item.kind || "any"),
      },
    };
  }
  if (kind === "chunks") {
    return {
      tool: "read_file_chunk",
      args: {
        path,
        start_line: numberOrUndefined(item.startLine),
        end_line: numberOrUndefined(item.endLine),
        max_chars: 6000,
      },
    };
  }
  if (kind === "matches") {
    const selector = firstString(item.selectorHint, item.selector);
    return selector
      ? { tool: "extract_html", args: { path, selector, mode: "html" } }
      : { tool: "read_file_chunk", args: { path, start_line: numberOrUndefined(item.startLine), end_line: numberOrUndefined(item.endLine), max_chars: 6000 } };
  }
  if (kind === "rules") {
    return { tool: "extract_css_rules", args: { path, selector: firstString(item.selector, item.name) } };
  }
  return null;
}

function copyRuntimeText(event: MouseEvent<HTMLButtonElement>, text: string) {
  event.preventDefault();
  event.stopPropagation();
  void navigator.clipboard?.writeText(text);
}

function copyRuntimeJson(event: MouseEvent<HTMLButtonElement>, value: unknown) {
  event.preventDefault();
  event.stopPropagation();
  void navigator.clipboard?.writeText(JSON.stringify(value, null, 2));
}

function lineRange(item: Record<string, unknown>) {
  const start = numberOrUndefined(item.startLine);
  const end = numberOrUndefined(item.endLine);
  if (!start && !end) return "";
  return start === end || !end ? String(start) : `${start}-${end}`;
}

function valuePart(label: string, value: unknown) {
  const text = String(value ?? "").trim();
  return text ? `${label}: ${text}` : "";
}

function numberOrUndefined(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : undefined;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) return text;
  }
  return "";
}

type MarkdownBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: 1 | 2 | 3; text: string }
  | { type: "list"; items: string[] }
  | { type: "code"; text: string };

function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let codeLines: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join("\n") });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (listItems.length) {
      blocks.push({ type: "list", items: listItems });
      listItems = [];
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      flushParagraph();
      flushList();
      if (inCode) {
        blocks.push({ type: "code", text: codeLines.join("\n") });
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: heading[1].length as 1 | 2 | 3, text: heading[2] });
      continue;
    }

    const listItem = /^(?:[-*+]\s+|\d+\.\s+)(.+)$/.exec(trimmed);
    if (listItem) {
      flushParagraph();
      listItems.push(listItem[1]);
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  if (inCode && codeLines.length) {
    blocks.push({ type: "code", text: codeLines.join("\n") });
  }
  flushParagraph();
  flushList();

  return blocks.length ? blocks : [{ type: "paragraph", text }];
}

function renderInlineMarkdown(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={index} className="runtime-value__inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
