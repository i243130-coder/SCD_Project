import { DIMENSIONS } from "../api";

export interface CompareData {
  a: { ref: string; verdict: string; score: number | null };
  b: { ref: string; verdict: string; score: number | null };
  dimensions: { dimension: string; a: number | null; b: number | null }[];
}

export function CompareTable({ data }: { data: CompareData }) {
  const by = Object.fromEntries(data.dimensions.map((d) => [d.dimension, d]));
  return (
    <table aria-label="compare" className="bg-white text-sm w-full rounded shadow">
      <thead><tr><th className="text-left">Dimension</th><th>{data.a.ref} ({data.a.verdict})</th><th>{data.b.ref} ({data.b.verdict})</th></tr></thead>
      <tbody>
        {DIMENSIONS.map((d) => (
          <tr key={d} data-testid="compare-row" className="border-t"><td>{d}</td><td className="text-center">{by[d]?.a ?? "–"}</td><td className="text-center">{by[d]?.b ?? "–"}</td></tr>
        ))}
      </tbody>
    </table>
  );
}
