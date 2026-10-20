import { useEffect, useState } from "react";
import clsx from "clsx";
import { X } from "lucide-react";

export interface CritiqueQuestion {
  id: string;
  finding: string;
  question: string;
  options: { label: string; description: string }[];
}

export interface CritiqueAnswers {
  scope: "all" | "material" | "specified";
  answers: Record<string, string>;
  notes: string;
}

interface Props {
  questions: CritiqueQuestion[];
  submitting: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (answers: CritiqueAnswers) => void;
}

export default function CritiqueQuestionsDialog({ questions, submitting, error, onClose, onSubmit }: Props) {
  const [scope, setScope] = useState<CritiqueAnswers["scope"]>("all");
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [detail, setDetail] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");

  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape" && !submitting) onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, submitting]);

  const answer = (q: CritiqueQuestion) => {
    const choice = picked[q.id] ?? "";
    const explanation = (detail[q.id] ?? "").trim();
    return choice && explanation ? `${choice}. ${explanation}` : choice || explanation;
  };
  const ready = questions.every((q) => answer(q)) && (scope !== "specified" || notes.trim());
  const submit = () => onSubmit({
    scope,
    answers: Object.fromEntries(questions.map((q) => [q.id, answer(q)])),
    notes: notes.trim(),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="critique-questions-title" className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-surface shadow-2xl">
        <div className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="flex-1">
            <h2 id="critique-questions-title" className="text-[1rem] font-semibold">Before applying the critique</h2>
            <p className="mt-1 text-[0.7812rem] text-muted">Choose which findings to address and clarify the points only you can decide. The article changes after you submit.</p>
          </div>
          <button onClick={onClose} disabled={submitting} aria-label="Close" className="rounded p-1 text-muted hover:bg-panel disabled:opacity-40"><X size="1rem" /></button>
        </div>
        <div className="scroll-thin space-y-5 overflow-y-auto px-5 py-4 text-[0.8125rem]">
          <section>
            <h3 className="mb-2 font-medium">Which findings should be applied?</h3>
            <div className="grid gap-2 sm:grid-cols-3">
              {([
                ["all", "All findings", "Address blocking, material, and minor findings."],
                ["material", "Priority findings", "Address blocking and material findings."],
                ["specified", "My selection", "Describe the findings to address below."],
              ] as const).map(([value, label, description]) => (
                <button key={value} type="button" onClick={() => setScope(value)} className={clsx("rounded-lg border p-3 text-left", scope === value ? "border-accent bg-accent-bg" : "border-border hover:border-accent")}>
                  <span className="block font-medium">{label}</span>
                  <span className="mt-1 block text-[0.75rem] text-muted">{description}</span>
                </button>
              ))}
            </div>
          </section>
          {questions.map((q, index) => (
            <section key={q.id} className="rounded-lg border border-border p-3">
              <div className="text-[0.6875rem] font-medium uppercase tracking-wide text-faint">Question {index + 1}{q.finding ? ` · ${q.finding}` : ""}</div>
              <h3 className="mt-1 font-medium">{q.question}</h3>
              {q.options.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {q.options.map((option) => (
                  <button key={option.label} type="button" onClick={() => setPicked((current) => ({ ...current, [q.id]: option.label }))} className={clsx("rounded-md border px-3 py-2 text-left", picked[q.id] === option.label ? "border-accent bg-accent-bg" : "border-border hover:border-accent")}>
                    <span className="block font-medium">{option.label}</span>
                    {option.description && <span className="mt-0.5 block text-[0.75rem] text-muted">{option.description}</span>}
                  </button>
                ))}
              </div>}
              <textarea value={detail[q.id] ?? ""} onChange={(event) => setDetail((current) => ({ ...current, [q.id]: event.target.value }))} rows={2} placeholder="Or explain your answer in your own words. You can also add detail to a choice above." className="mt-3 w-full resize-y rounded-md border border-border bg-bg px-3 py-2 outline-none focus:border-accent" />
            </section>
          ))}
          {questions.length === 0 && <p className="text-muted">The critic did not flag a point that requires your decision. You can still give the repair agent directions below.</p>}
          <section>
            <label htmlFor="critique-notes" className="mb-2 block font-medium">Other direction for the article {scope === "specified" ? "(required)" : "(optional)"}</label>
            <textarea id="critique-notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} placeholder="For example, keep my personal interpretation, but clarify the factual basis around it." className="w-full resize-y rounded-md border border-border bg-bg px-3 py-2 outline-none focus:border-accent" />
          </section>
          {error && <p role="alert" className="text-bad">{error}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3 text-[0.7812rem]">
          <button onClick={onClose} disabled={submitting} className="rounded-md border border-border px-3 py-1.5 disabled:opacity-40">Cancel</button>
          <button onClick={submit} disabled={!ready || submitting} className="rounded-md bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-40">{submitting ? "Starting repair…" : "Apply feedback"}</button>
        </div>
      </div>
    </div>
  );
}
