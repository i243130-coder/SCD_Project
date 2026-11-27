import { useEffect, useState } from "react";
import { subscribe, type RunEvent } from "../api";

interface ToolCall { agent: string; latency_ms?: number; cache_hit?: boolean; input?: string; retries?: number }

export function LiveRunPanel({ runId, onEvent, factory }: { runId: string; onEvent?: (e: RunEvent) => void; factory?: (u: string) => EventSource }) {
  const [state, setState] = useState("starting");
  const [agent, setAgent] = useState<string | null>(null);
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [spend, setSpend] = useState<{ cost_usd: number; max_cost_usd: number; tokens: number } | null>(null);
  useEffect(() => {
    return subscribe(runId, (e) => {
      if (e.type === "state") setState(String(e.payload.to));
      if (e.type === "agent_start") setAgent(String(e.payload.agent));
      if (e.type === "tool_call") setCalls((c) => [...c, e.payload as unknown as ToolCall]);
      if (e.type === "spend") setSpend(e.payload as unknown as { cost_usd: number; max_cost_usd: number; tokens: number });
      onEvent?.(e);
    }, factory);
  }, [runId, onEvent, factory]);
  const pct = spend ? Math.min(100, (100 * spend.cost_usd) / (spend.max_cost_usd || 1)) : 0;
  return (
    <section aria-label="live run" className="bg-white p-4 rounded shadow space-y-2">
      <div className="flex gap-4 text-sm"><span>State: <b data-testid="state">{state}</b></span><span>Running agent: <b data-testid="agent">{agent ?? "-"}</b></span></div>
      {spend && (
        <div aria-label="spend">
          <div className="text-xs">${spend.cost_usd.toFixed(4)} of ${spend.max_cost_usd.toFixed(2)} &middot; {spend.tokens} tokens</div>
          <div className="h-2 bg-slate-200 rounded"><div className="h-2 bg-indigo-500 rounded" style={{ width: `${pct}%` }} /></div>
        </div>
      )}
      <ul className="text-xs max-h-48 overflow-auto" aria-label="tool calls">
        {calls.map((c, i) => (
          <li key={i}>{c.agent} &middot; {c.latency_ms ?? 0} ms{c.retries ? ` · ${c.retries} retries` : ""} {c.cache_hit && <span className="bg-green-100 px-1 rounded">cache hit</span>}</li>
        ))}
      </ul>
    </section>
  );
}
