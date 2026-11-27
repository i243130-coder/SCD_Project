import { useState } from "react";

export interface IdeaRow { id: string; title: string; versions: number; latest_verdict: { verdict: string; score: number | null } | null }

export function History({ ideas, onCompare, onOpen }: { ideas: IdeaRow[]; onCompare: (a: string, b: string) => void; onOpen: (id: string, v: number) => void }) {
  const [sel, setSel] = useState<string[]>([]);
  const refs = ideas.flatMap((i) => Array.from({ length: i.versions }, (_, k) => ({ ref: `${i.id}@${k + 1}`, label: `${i.title} v${k + 1}`, id: i.id, v: k + 1 })));
  const toggle = (r: string) => setSel((s) => (s.includes(r) ? s.filter((x) => x !== r) : [...s, r].slice(-2)));
  return (
    <section aria-label="history" className="bg-white p-4 rounded shadow">
      <ul>{refs.map((r) => (
        <li key={r.ref} className="flex gap-2 text-sm">
          <input type="checkbox" aria-label={`select ${r.ref}`} checked={sel.includes(r.ref)} onChange={() => toggle(r.ref)} />
          <button className="underline" onClick={() => onOpen(r.id, r.v)}>{r.label}</button>
        </li>))}
      </ul>
      <button disabled={sel.length !== 2} className="mt-2 text-sm border px-2 rounded disabled:opacity-40" onClick={() => onCompare(sel[0], sel[1])}>Compare</button>
    </section>
  );
}
