// The browser only ever talks to the gateway. Its address is read at RUNTIME from /config.js.
declare global {
  interface Window {
    __CONFIG__?: { API_BASE_URL: string };
  }
}

export const apiBase = (): string => window.__CONFIG__?.API_BASE_URL ?? "/api";

export type Dimension = "demand_pain" | "competition" | "differentiation" | "feasibility" | "risk" | "learning";
export const DIMENSIONS: Dimension[] = ["demand_pain", "competition", "differentiation", "feasibility", "risk", "learning"];
export type VerdictLabel = "GO" | "PIVOT" | "NO-GO" | "INSUFFICIENT_EVIDENCE";

export interface DimensionScore {
  dimension: Dimension;
  score: number | null;
  confidence: number;
  evidence_ids: string[];
  reason: string;
  rubric_version: string;
  model: string;
  abstained: boolean;
  cache_hit?: boolean;
  extra?: Record<string, unknown>;
}
export interface WhatIfOption {
  change: string;
  dimension: Dimension | null;
  delta: number;
  new_score: number;
  new_verdict: VerdictLabel;
  new_stability: "STABLE" | "BORDERLINE";
}
export interface Verdict {
  idea_id: string;
  version: number;
  run_id: string;
  verdict: VerdictLabel;
  stability: "STABLE" | "BORDERLINE";
  score: number | null;
  confidence: number;
  gates: Record<"evidence" | "feasibility" | "risk" | "duplicate", "pass" | "fail" | "not_run">;
  gate_details: Record<string, string>;
  weights: Record<Dimension, number>;
  thresholds: Record<string, number>;
  scores: DimensionScore[];
  weakest_dimension: Dimension | null;
  missing: string[];
  what_would_make_go: WhatIfOption[];
  sensitivity: { runs: number; flipped: number; flips: { perturbation: string; verdict: VerdictLabel; score: number | null }[] };
  versions: Record<string, string>;
  cache_hit?: boolean;
}
export interface Profile {
  skills: string[];
  hours_per_week: number;
  weeks_available: number;
  team_size: number;
  compute: "laptop" | "free_gpu" | "paid";
  goal: "startup" | "portfolio" | "course_project";
  interests: string[];
  profile_version?: number;
}
export interface RunEvent {
  type: "state" | "agent_start" | "agent_end" | "tool_call" | "spend" | "question" | "approval_required" | "result" | "error";
  run_id: string;
  ts: string;
  payload: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public retryAfter?: string | null) {
    super(message);
  }
}

let token: string | null = null;
export const setToken = (t: string | null) => {
  token = t;
};
export const getToken = () => token;

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json", ...(init.headers as Record<string, string>) };
  if (token) headers.authorization = `Bearer ${token}`;
  const r = await fetch(`${apiBase()}${path}`, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    if (r.status === 429) detail = `Too many requests, retry in ${r.headers.get("retry-after") ?? "a few"} s`;
    throw new ApiError(r.status, detail, r.headers.get("retry-after"));
  }
  return (await r.json()) as T;
}

export const post = <T,>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

/** SSE with reconnect; the token goes in the query string because EventSource cannot set headers. */
export function subscribe(runId: string, onEvent: (e: RunEvent) => void, factory = (u: string) => new EventSource(u)): () => void {
  let closed = false;
  let es: EventSource;
  const open = () => {
    es = factory(`${apiBase()}/runs/${runId}/events?token=${encodeURIComponent(token ?? "")}`);
    es.onmessage = (m) => onEvent(JSON.parse(m.data) as RunEvent);
    es.onerror = () => {
      es.close();
      if (!closed) setTimeout(open, 2000);
    };
  };
  open();
  return () => {
    closed = true;
    es.close();
  };
}
