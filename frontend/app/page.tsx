"use client";

import { FormEvent, useState } from "react";
import { AnswerSection } from "../components/answer-section";
import { Disclaimer } from "../components/disclaimer";
import { QuestionForm } from "../components/question-form";
import type { AskResponse } from "../components/types";

export default function Home() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    setError("");

    if (!trimmedQuestion) {
      setResult(null);
      setError("يرجى كتابة سؤال قبل الإرسال.");
      return;
    }

    setLoading(true);
    setResult(null);

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmedQuestion }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "تعذر معالجة السؤال. حاول مرة أخرى.");
      }

      setResult(data as AskResponse);
    } catch (cause) {
      if (cause instanceof TypeError) {
        setError("تعذر الاتصال بالخدمة حاليًا. حاول مرة أخرى.");
      } else {
        setError(cause instanceof Error ? cause.message : "تعذر معالجة السؤال. حاول مرة أخرى.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="hero">
        <p className="eyebrow">مساعد بحثي قانوني</p>
        <h2>المساعد القانوني للمنافسات والمشتريات</h2>
        <p className="hero-copy">ابحث واسأل في نظام المنافسات والمشتريات الحكومية ولائحته التنفيذية، مع إظهار المواد والمراجع ذات الصلة.</p>
      </header>

      <QuestionForm
        loading={loading}
        onSubmit={ask}
        question={question}
        setQuestion={setQuestion}
      />

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {loading && <p className="loading-status" role="status"><span className="spinner" aria-hidden="true" />جارٍ البحث في النظام واللائحة التنفيذية…</p>}
      {result && <AnswerSection result={result} />}

      <Disclaimer />
    </main>
  );
}
