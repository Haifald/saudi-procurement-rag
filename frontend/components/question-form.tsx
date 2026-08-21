import type { FormEvent } from "react";

const examples = ["ما أهداف النظام؟", "ماذا تنص المادة 15؟", "ما الأحكام المتعلقة بالتأخير؟"];

type QuestionFormProps = {
  loading: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  question: string;
  setQuestion: (question: string) => void;
};

export function QuestionForm({ loading, onSubmit, question, setQuestion }: QuestionFormProps) {
  return (
    <section className="question-panel" aria-label="طرح سؤال قانوني">
      <div className="example-row" aria-label="أسئلة مقترحة">
        {examples.map((example) => (
          <button className="example-button" key={example} onClick={() => setQuestion(example)} type="button">
            {example}
          </button>
        ))}
      </div>
      <form onSubmit={onSubmit}>
        <label className="sr-only" htmlFor="question">اكتب سؤالك القانوني</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="اكتب سؤالك عن نظام المنافسات والمشتريات الحكومية…"
          rows={5}
        />
        <div className="form-footer">
          <span className="form-note">تُعرض المراجع الداعمة أسفل الإجابة</span>
          <button className="submit" type="submit" disabled={loading}>
            {loading ? <span className="spinner" aria-label="جارٍ التحميل" /> : "اسأل الآن"}
          </button>
        </div>
      </form>
    </section>
  );
}
