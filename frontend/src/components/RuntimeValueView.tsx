export function RuntimeValueView({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (typeof value === "string") {
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
    return (
      <div className="runtime-value__list">
        {value.slice(0, 10).map((item, index) => (
          <div key={index} className="runtime-value__list-item">
            <span>{index + 1}</span>
            {depth >= 3 ? <RuntimeStructuredValue value={item} /> : <RuntimeValueView value={item} depth={depth + 1} />}
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
    return (
      <div className="runtime-value__fields">
        {entries.slice(0, 16).map(([key, fieldValue]) => (
          <div key={key} className="runtime-value__field">
            <div className="runtime-value__field-key">{key}</div>
            <div className="runtime-value__field-value">
              {depth >= 3 ? <RuntimeStructuredValue value={fieldValue} /> : <RuntimeValueView value={fieldValue} depth={depth + 1} />}
            </div>
          </div>
        ))}
        {entries.length > 16 ? <div className="runtime-value__empty">还有 {entries.length - 16} 个字段未显示</div> : null}
      </div>
    );
  }

  return <div className="runtime-value__scalar">{String(value)}</div>;
}

function RuntimeStructuredValue({ value }: { value: unknown }) {
  const textValue = JSON.stringify(value, null, 2);
  return <pre className="runtime-value__code">{textValue.length > 900 ? `${textValue.slice(0, 900)}...` : textValue}</pre>;
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
