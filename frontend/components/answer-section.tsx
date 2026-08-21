import { SourceList } from "./source-list";
import type { AskResponse } from "./types";

function AnswerText({ text }: { text: string }) {
  return <div className="answer-text">{text.split("\n").filter(Boolean).map((line, index) => <p key={index}>{line}</p>)}</div>;
}

export function AnswerSection({ result }: { result: AskResponse }) {
  return (
    <section className="result" aria-live="polite">
      <p className="section-label">الإجابة</p>
      {result.has_unverified_citation && (
        <p className="notice notice-warning">تعذر التحقق من أحد المراجع المذكورة في الإجابة. يرجى مراجعة المصادر أدناه.</p>
      )}
      <article className="answer-card"><AnswerText text={result.answer} /></article>
      <SourceList sources={result.sources} />
    </section>
  );
}
