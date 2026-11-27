import { useState } from "react";
import type { DimensionScore, Verdict } from "../api";

const COLORS: Record<string, string> = { GO: "bg-green-600", PIVOT: "bg-amber-500", "NO-GO": "bg-red-600", INSUFFICIENT_EVIDENCE: "bg-slate-500" };
const ICON: Record<string, string> = { hackernews: "HN", github: "GH", producthunt: "PH", yc: "YC", reddit: "R" };

export interface ChallengeResult { result: "defended" | "removed"; check: { reason: string }; verdict?: Verdict }

export function VerdictCard({ v, evidenceUrls = {}, onApply, onChallenge }: {
  v: Verdict;
  evidenceUrls?: Record<string, { url: string; source: string }>;
  onApply?: (optionIndex: number) => void;
  onChallenge?: (s: DimensionScore) => Promise<ChallengeResult>;
}) {
  const [challenges, setChallenges] = useState<Record<string, ChallengeResult>>({});
  const ie = v.verdict === "INSUFFICIENT_EVIDENCE";
  return (
    <article aria-label="verdict card" className="bg-white p-4 rounded shadow space-y-3">
      <header className="flex items-center gap-3">
        <span className={`text-white text-2xl font-bold px-3 py-1 rounded ${COLORS[v.verdict]}`}>{v.verdict.replace("_", " ")}</span>
        <span data-testid="stability" className="text-sm border px-2 rounded">{v.stability}</span>
        {!ie && v.score !== null && <span data-testid="score">score {v.score.toFixed(1)}</span>}
        <span data-testid="confidence" className="text-sm">confidence {v.confidence.toFixed(2)}</span>
        {v.cache_hit && <span className="text-xs bg-green-100 px-1 rounded">cache hit</span>}
        <span className="ml-auto text-xs">v{v.version}</span>
      </header>
      <div className="flex gap-2 flex-wrap" aria-label="gates">
        {Object.entries(v.gates).map(([g, s]) => (
          <span key={g} data-testid={`gate-${g}`} className={`text-xs px-2 py-1 rounded ${s === "pass" ? "bg-green-100" : s === "fail" ? "bg-red-100" : "bg-slate-100"}`}>
            {g}: {s}{v.gate_details[g] ? ` — ${v.gate_details[g]}` : ""}
          </span>
        ))}
      </div>
      {ie ? (
        <section aria-label="what was missing">
          <h3 className="font-semibold">What was missing</h3>
          <ul className="list-disc ml-5">{v.missing.map((m) => <li key={m}>{m}</li>)}</ul>
        </section>
      ) : (
        <table className="w-full text-sm" aria-label="scores">
          <thead><tr><th className="text-left">Dimension</th><th>Score</th><th>Weight</th><th>Conf.</th><th className="text-left">Reason &amp; evidence</th></tr></thead>
          <tbody>
            {v.scores.map((s) => (
              <tr key={s.dimension} data-testid={`row-${s.dimension}`} className="align-top border-t">
                <td>{s.dimension}{v.weakest_dimension === s.dimension && <span className="text-xs text-red-600"> (weakest)</span>}</td>
                <td><div className="w-24 h-2 bg-slate-200 rounded"><div className="h-2 bg-indigo-500 rounded" style={{ width: `${((s.score ?? 0) / 5) * 100}%` }} /></div>{s.score ?? "–"}</td>
                <td className="text-center">{v.weights[s.dimension]?.toFixed(1)}</td>
                <td className="text-center">{s.confidence.toFixed(2)}</td>
                <td>
                  {challenges[s.dimension]?.result === "removed" ? <s>{s.reason}</s> : s.reason}{" "}
                  {s.cache_hit && <span className="text-xs bg-green-100 px-1 rounded">cache hit</span>}
                  <div className="flex gap-1 flex-wrap">
                    {s.evidence_ids.map((id) => (
                      <a key={id} href={evidenceUrls[id]?.url ?? "#"} target="_blank" rel="noreferrer" className="text-xs underline">
                        [{ICON[evidenceUrls[id]?.source ?? ""] ?? "src"}] {id}
                      </a>
                    ))}
                  </div>
                  {onChallenge && (
                    <button className="text-xs border px-1 rounded" onClick={async () => {
                      const r = await onChallenge(s);
                      setChallenges((c) => ({ ...c, [s.dimension]: r }));
                    }}>Challenge</button>
                  )}
                  {challenges[s.dimension] && (
                    <span data-testid={`challenge-${s.dimension}`} className="text-xs ml-1">
                      {challenges[s.dimension].result === "defended" ? "Defended" : "Removed"}: {challenges[s.dimension].check.reason}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {v.sensitivity.flips.length > 0 && (
        <p className="text-xs">Flips: {v.sensitivity.flips.map((f) => `${f.perturbation} → ${f.verdict}`).join("; ")}</p>
      )}
      {v.what_would_make_go.length > 0 && (
        <section aria-label="what would make this go">
          <h3 className="font-semibold">What would make this GO?</h3>
          <ul>{v.what_would_make_go.map((o, i) => (
            <li key={i} className="flex gap-2 items-center text-sm">
              <span>{o.change} → {o.new_verdict} ({o.new_score.toFixed(1)}, {o.new_stability})</span>
              {onApply && <button className="text-xs bg-indigo-600 text-white px-2 rounded" onClick={() => onApply(i)}>Apply</button>}
            </li>))}
          </ul>
        </section>
      )}
      <footer className="text-xs text-slate-500">
        Thresholds GO≥{v.thresholds.T_go}, NO-GO&lt;{v.thresholds.T_no}, floor {v.thresholds.floor} · engine {v.versions.engine} · rubrics {v.versions.rubrics} · weights {v.versions.profile_weights}
        <br />Decision support, not a prediction of success.
      </footer>
    </article>
  );
}
