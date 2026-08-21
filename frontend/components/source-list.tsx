import { SourceCard } from "./source-card";
import type { Source } from "./types";

export function SourceList({ sources }: { sources: Source[] }) {
  const citedSources = sources.filter((source) => source.cited);
  const relatedSources = sources.filter((source) => !source.cited);

  if (sources.length === 0) return null;

  return (
    <section className="sources" aria-label="المراجع والمصادر">
      {citedSources.length > 0 && (
        <div className="source-group source-group-primary">
          <h2>المراجع المستخدمة في الإجابة</h2>
          <div className="source-list">{citedSources.map((source, index) => <SourceCard key={`${source.label}-${index}`} source={source} />)}</div>
        </div>
      )}
      {relatedSources.length > 0 && (
        <div className="source-group">
          <h2>{citedSources.length > 0 ? "مصادر إضافية ذات صلة" : "مصادر ذات صلة"}</h2>
          <div className="source-list">{relatedSources.map((source, index) => <SourceCard key={`${source.label}-${index}`} source={source} />)}</div>
        </div>
      )}
    </section>
  );
}
