import type { Source } from "./types";

function sourceName(sourceType: string | null) {
  return sourceType === "لائحة" ? "لائحة تنفيذية" : "نظام";
}

export function SourceCard({ source }: { source: Source }) {
  const metadata = [source.bab, source.fasl].filter(Boolean).join(" · ");
  const title = source.article_number ? `المادة ${source.article_number}` : source.label;

  return (
    <details className={`source-card ${source.cited ? "source-card-cited" : ""}`}>
      <summary>
        <span className="source-badges">
          <span className={`source-badge ${source.source_type === "لائحة" ? "source-badge-regulation" : ""}`}>{sourceName(source.source_type)}</span>
          {source.cited && <span className="source-badge source-badge-cited">مستشهد به</span>}
        </span>
        <span className="source-title">{title}</span>
        {metadata && <span className="source-meta">{metadata}</span>}
        <span className="source-toggle">عرض نص المادة</span>
      </summary>
      <div className="source-text">{source.text}</div>
    </details>
  );
}
