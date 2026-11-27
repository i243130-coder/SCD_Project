import { useCallback, useEffect, useState } from "react";
import { api, ApiError, post, put, setToken, type DimensionScore, type Profile, type RunEvent, type Verdict } from "./api";
import { ApprovalModal, type Approval } from "./components/ApprovalModal";
import { AuthForm } from "./components/AuthForm";
import { CompareTable, type CompareData } from "./components/CompareTable";
import { DiscoverResults, type Ranked } from "./components/DiscoverResults";
import { History, type IdeaRow } from "./components/History";
import { LiveRunPanel } from "./components/LiveRunPanel";
import { ProfileForm } from "./components/ProfileForm";
import { VerdictCard, type ChallengeResult } from "./components/VerdictCard";

interface Question { id: string; question: string; why: string }

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [mode, setMode] = useState<"validate" | "discover">("validate");
  const [text, setText] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [ranked, setRanked] = useState<Ranked[]>([]);
  const [ideas, setIdeas] = useState<IdeaRow[]>([]);
  const [compare, setCompare] = useState<CompareData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const login = async (m: "login" | "register", email: string, password: string) => {
    const r = await post<{ token: string }>(`/auth/${m}`, { email, password });
    setToken(r.token);
    setAuthed(true);
    api<Profile>("/profile").then(setProfile).catch(() => setProfile(null));
  };

  const refreshHistory = useCallback(() => api<IdeaRow[]>("/ideas").then(setIdeas).catch(() => undefined), []);
  useEffect(() => { if (authed) refreshHistory(); }, [authed, refreshHistory]);

  const onEvent = useCallback((e: RunEvent) => {
    if (e.payload.child) return; // child validate runs inside Discover
    if (e.type === "question") setQuestions((q) => [...q, e.payload as unknown as Question]);
    if (e.type === "approval_required") setApproval(e.payload as unknown as Approval);
    if (e.type === "error") setError(String(e.payload.reason ?? e.payload.error));
    if (e.type === "result") {
      if (e.payload.verdict) setVerdict(e.payload.verdict as Verdict);
      if (e.payload.ranked) setRanked(e.payload.ranked as Ranked[]);
      refreshHistory();
    }
  }, [refreshHistory]);

  const start = async () => {
    setError(null); setVerdict(null); setRanked([]); setQuestions([]);
    try {
      const r = mode === "validate" ? await post<{ run_id: string }>("/validate", { idea_text: text })
        : await post<{ run_id: string }>("/discover", { niche: text || null, count: 8 });
      setRunId(r.run_id);
    } catch (err) { setError(err instanceof ApiError ? err.message : String(err)); }
  };

  const answer = async (q: Question, a: string) => {
    await post(`/runs/${runId}/answer`, { question_id: q.id, answer: a });
    setQuestions((qs) => qs.filter((x) => x.id !== q.id));
  };

  const applyWhatIf = async (i: number) => {
    if (!verdict) return;
    const r = await post<{ run_id: string }>(`/ideas/${verdict.idea_id}/whatif`, { from_version: verdict.version, option_index: i });
    setVerdict(null);
    setRunId(r.run_id);
  };

  const challenge = (s: DimensionScore) => post<ChallengeResult>(`/ideas/${verdict!.idea_id}/challenge`, {
    version: verdict!.version, dimension: s.dimension, claim_text: s.reason, evidence_ids: s.evidence_ids,
  }).then((r) => { if (r.verdict) setVerdict(r.verdict); return r; });

  if (!authed) return <AuthForm onSubmit={login} />;
  return (
    <main className="max-w-5xl mx-auto p-4 grid gap-4 md:grid-cols-3">
      <div className="space-y-4">
        <ProfileForm key={profile?.profile_version ?? 0} initial={profile} onSave={async (p) => { const s = await put<Profile>("/profile", p); setProfile(s); return s; }} />
        <History ideas={ideas} onOpen={async (id, v) => { const vs = await api<{ version: number; verdict: Verdict | null }[]>(`/ideas/${id}/versions`); setVerdict(vs.find((x) => x.version === v)?.verdict ?? null); }}
          onCompare={async (a, b) => setCompare(await api<CompareData>(`/compare?a=${a}&b=${b}`))} />
      </div>
      <div className="md:col-span-2 space-y-4">
        <section className="bg-white p-4 rounded shadow space-y-2">
          <div className="flex gap-2">{(["validate", "discover"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={`px-3 py-1 rounded ${mode === m ? "bg-indigo-600 text-white" : "border"}`}>{m === "validate" ? "Validate" : "Discover"}</button>))}
          </div>
          <textarea aria-label="idea" maxLength={2000} className="border w-full p-2" rows={3} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={mode === "validate" ? "Describe your idea" : "Optional niche, e.g. campus events"} />
          <button onClick={start} className="bg-indigo-600 text-white px-4 py-1 rounded">Start</button>
          {error && <p role="alert" className="text-red-600 text-sm">{error}</p>}
        </section>
        {runId && <LiveRunPanel key={runId} runId={runId} onEvent={onEvent} />}
        {questions.map((q) => <QuestionBox key={q.id} q={q} onAnswer={answer} />)}
        {approval && runId && <ApprovalModal approval={approval} onDecide={async (ok) => { await post(`/runs/${runId}/approve`, { approve: ok }); setApproval(null); }} />}
        {ranked.length > 0 && <DiscoverResults rows={ranked} onOpen={async (r) => { const vs = await api<{ version: number; verdict: Verdict | null }[]>(`/ideas/${r.idea_id}/versions`); setVerdict(vs.find((x) => x.version === r.version)?.verdict ?? null); }} />}
        {verdict && <VerdictCard v={verdict} onApply={applyWhatIf} onChallenge={challenge} />}
        {compare && <CompareTable data={compare} />}
        <p className="text-xs text-slate-500">Decision support, not a prediction of success.</p>
      </div>
    </main>
  );
}

function QuestionBox({ q, onAnswer }: { q: Question; onAnswer: (q: Question, a: string) => void }) {
  const [a, setA] = useState("");
  return (
    <div className="bg-amber-50 p-3 rounded text-sm space-y-1">
      <p>{q.question} <span className="text-xs text-slate-500">({q.why})</span></p>
      <input aria-label={`answer ${q.id}`} className="border p-1 w-full" value={a} onChange={(e) => setA(e.target.value)} />
      <button className="text-xs border px-2 rounded" onClick={() => onAnswer(q, a)}>Answer</button>
    </div>
  );
}
