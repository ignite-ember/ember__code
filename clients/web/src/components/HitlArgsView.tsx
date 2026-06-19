import { FileTypeIcon } from "./FileTypeIcon";

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Render tool arguments as labeled, syntax-aware rows instead of a
 *  raw JSON dump. Common shapes get bespoke treatment:
 *
 *  - file_path / path / source_path → file pill with type icon
 *  - command / cmd                  → terminal-style block
 *  - old_string / new_string        → side-by-side diff strip
 *  - contents / content / body / text → fenced code block
 *  - anything else                  → mono code (string) or JSON (objects)
 */
export function HitlArgsView({ args }: { args: Record<string, any> | undefined }) {
  if (!args || typeof args !== "object" || !Object.keys(args).length) return null;
  const entries = Object.entries(args);

  // Special-case: Edit-style (old_string + new_string) → render as
  // an inline diff strip below the file path.
  const isEdit =
    typeof args.old_string === "string" &&
    typeof args.new_string === "string";

  return (
    <div className="hitl-args">
      {entries
        .filter(([k]) => !(isEdit && (k === "old_string" || k === "new_string")))
        .map(([key, raw]) => (
          <Row key={key} k={key} v={raw} />
        ))}
      {isEdit && <DiffPair oldStr={String(args.old_string)} newStr={String(args.new_string)} />}
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  const label = k.replace(/_/g, " ");
  return (
    <div className="hitl-arg-row">
      <div className="hitl-arg-key">{label}</div>
      <div className="hitl-arg-val">
        <Value k={k} v={v} />
      </div>
    </div>
  );
}

function Value({ k, v }: { k: string; v: any }) {
  if (v === null || v === undefined)
    return <span className="hitl-arg-null">—</span>;
  if (typeof v === "boolean") return <span className="hitl-arg-bool">{String(v)}</span>;
  if (typeof v === "number") return <span className="hitl-arg-num">{v}</span>;
  if (typeof v === "string") return <StringValue k={k} v={v} />;
  if (Array.isArray(v))
    return v.every((x) => typeof x === "string" || typeof x === "number") ? (
      <div className="hitl-arg-tags">
        {v.map((x, i) => (
          <span key={i} className="mini-tag">
            {String(x)}
          </span>
        ))}
      </div>
    ) : (
      <pre className="hitl-arg-pre">{JSON.stringify(v, null, 2)}</pre>
    );
  return <pre className="hitl-arg-pre">{JSON.stringify(v, null, 2)}</pre>;
}

function StringValue({ k, v }: { k: string; v: string }) {
  if (/(^|_)(file_)?path$|^file_?path$|^source_?path$/i.test(k)) {
    const name = v.split("/").pop() || v;
    return (
      <span className="hitl-file" title={v}>
        <span className="hitl-file-icon">
          <FileTypeIcon name={name} size={14} />
        </span>
        <span className="hitl-file-name">{name}</span>
        <span className="hitl-file-path">{v}</span>
      </span>
    );
  }
  if (/^(command|cmd)$/i.test(k)) {
    return <pre className="hitl-shell">{v}</pre>;
  }
  if (/^(contents?|body|text|code|prompt|instructions?|input|query)$/i.test(k)) {
    return <pre className="hitl-arg-pre">{v}</pre>;
  }
  if (v.length < 80 && !v.includes("\n")) {
    return <code className="hitl-arg-code">{v}</code>;
  }
  return <pre className="hitl-arg-pre">{v}</pre>;
}

function DiffPair({ oldStr, newStr }: { oldStr: string; newStr: string }) {
  return (
    <div className="hitl-arg-row">
      <div className="hitl-arg-key">change</div>
      <div className="hitl-arg-val">
        <pre className="hitl-diff hitl-diff-del">{oldStr || "(empty)"}</pre>
        <pre className="hitl-diff hitl-diff-add">{newStr || "(empty)"}</pre>
      </div>
    </div>
  );
}
