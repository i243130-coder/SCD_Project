import type { Verdict } from "../src/api";
import { DIMENSIONS } from "../src/api";

export const verdict = (over: Partial<Verdict> = {}): Verdict => ({
  idea_id: "idea_1", version: 1, run_id: "run_1", verdict: "GO", stability: "BORDERLINE", score: 70.5, confidence: 0.86,
  gates: { evidence: "pass", feasibility: "pass", risk: "pass", duplicate: "pass" }, gate_details: {},
  weights: { demand_pain: 15, competition: 15, differentiation: 15, feasibility: 25, risk: 10, learning: 20 },
  thresholds: { T_go: 70, T_no: 50, floor: 1.5 },
  scores: DIMENSIONS.map((d) => ({ dimension: d, score: 3.5, confidence: 0.8, evidence_ids: [`card_${d}#c0`], reason: `${d} reason`,
    rubric_version: `${d}@v1`, model: "rule", abstained: false })),
  weakest_dimension: "competition", missing: [],
  what_would_make_go: [{ change: "Narrow to one segment", dimension: "competition", delta: 1, new_score: 73.5, new_verdict: "GO", new_stability: "STABLE" }],
  sensitivity: { runs: 14, flipped: 1, flips: [{ perturbation: "weight feasibility -20%", verdict: "PIVOT", score: 69.87 }] },
  versions: { engine: "m11@v1", rubrics: "r1", profile_weights: "w1" }, ...over,
});
