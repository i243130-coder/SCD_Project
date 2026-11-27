export interface Ranked { rank: number; title: string; verdict: string; stability: string; score: number | null; reason: string; idea_id: string; version: number }

export function DiscoverResults({ rows, onOpen }: { rows: Ranked[]; onOpen: (r: Ranked) => void }) {
  return (
    <ol aria-label="discover results" className="bg-white p-4 rounded shadow space-y-2">
      {rows.map((r) => (
        <li key={r.rank} className="flex gap-2 items-center">
          <b>{r.rank}.</b><span className="font-medium">{r.title}</span>
          <span className="text-xs border px-1 rounded">{r.verdict}{r.stability === "BORDERLINE" ? " · BORDERLINE" : ""}</span>
          <span className="text-xs">{r.score?.toFixed(1) ?? "–"}</span>
          <span className="text-sm text-slate-600 flex-1">{r.reason}</span>
          <button className="text-xs underline" onClick={() => onOpen(r)}>Open card</button>
        </li>
      ))}
    </ol>
  );
}
