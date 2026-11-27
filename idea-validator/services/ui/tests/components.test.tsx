import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApprovalModal } from "../src/components/ApprovalModal";
import { CompareTable } from "../src/components/CompareTable";
import { LiveRunPanel } from "../src/components/LiveRunPanel";
import { ProfileForm } from "../src/components/ProfileForm";
import { VerdictCard } from "../src/components/VerdictCard";
import { apiBase } from "../src/api";
import { verdict } from "./fixtures";

describe("ProfileForm", () => {
  it("validates and submits", async () => {
    const onSave = vi.fn().mockResolvedValue({ profile_version: 2 });
    render(<ProfileForm onSave={onSave} />);
    await userEvent.click(screen.getByText("Save"));
    expect(screen.getByRole("alert")).toHaveTextContent("Add at least one skill");
    expect(onSave).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("skills"), "python, react");
    await userEvent.clear(screen.getByLabelText("team"));
    await userEvent.type(screen.getByLabelText("team"), "9");
    await userEvent.click(screen.getByText("Save"));
    expect(screen.getByRole("alert")).toHaveTextContent("Team size must be 1-6");
    await userEvent.clear(screen.getByLabelText("team"));
    await userEvent.type(screen.getByLabelText("team"), "2");
    await userEvent.click(screen.getByText("Save"));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ skills: ["python", "react"], team_size: 2 }));
    expect(await screen.findByText("profile v2")).toBeInTheDocument();
  });
});

describe("VerdictCard", () => {
  it("renders gates, six scores, evidence links, stability, weights", () => {
    render(<VerdictCard v={verdict()} evidenceUrls={{ "card_risk#c0": { url: "https://news.ycombinator.com/item?id=1", source: "hackernews" } }} />);
    expect(screen.getByText("GO")).toBeInTheDocument();
    expect(screen.getByTestId("stability")).toHaveTextContent("BORDERLINE");
    for (const g of ["evidence", "feasibility", "risk", "duplicate"]) expect(screen.getByTestId(`gate-${g}`)).toHaveTextContent("pass");
    expect(screen.getAllByTestId(/^row-/)).toHaveLength(6);
    expect(screen.getByText("[HN] card_risk#c0").closest("a")).toHaveAttribute("href", "https://news.ycombinator.com/item?id=1");
    expect(screen.getByTestId("row-feasibility")).toHaveTextContent("25.0");
    expect(screen.getByText(/weight feasibility -20%/)).toBeInTheDocument();
    expect(screen.getByText(/Decision support, not a prediction of success/)).toBeInTheDocument();
  });

  it("INSUFFICIENT EVIDENCE shows the missing list and no score", () => {
    render(<VerdictCard v={verdict({ verdict: "INSUFFICIENT_EVIDENCE", score: null, missing: ["need >=3 independent sources on >=2 platforms, have 1 on 1"], what_would_make_go: [] })} />);
    expect(screen.getByLabelText("what was missing")).toHaveTextContent("have 1 on 1");
    expect(screen.queryByTestId("score")).toBeNull();
    expect(screen.queryByLabelText("scores")).toBeNull();
  });

  it("What-if Apply calls the API handler", async () => {
    const onApply = vi.fn();
    render(<VerdictCard v={verdict({ verdict: "PIVOT" })} onApply={onApply} />);
    await userEvent.click(screen.getByText("Apply"));
    expect(onApply).toHaveBeenCalledWith(0);
  });

  it("renders the challenge result", async () => {
    const onChallenge = vi.fn().mockResolvedValue({ result: "removed", check: { reason: "evidence not similar enough" } });
    render(<VerdictCard v={verdict()} onChallenge={onChallenge} />);
    await userEvent.click(screen.getAllByText("Challenge")[1]);
    expect(await screen.findByTestId("challenge-competition")).toHaveTextContent("Removed: evidence not similar enough");
  });
});

describe("ApprovalModal", () => {
  it("calls approve and decline", async () => {
    const onDecide = vi.fn();
    render(<ApprovalModal approval={{ action: "deep_search", estimated_cost_usd: 0.03, current_spend: 0.04, budget_usd: 0.05 }} onDecide={onDecide} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("$0.030");
    await userEvent.click(screen.getByText("Approve"));
    await userEvent.click(screen.getByText("Decline"));
    expect(onDecide.mock.calls).toEqual([[true], [false]]);
  });
});

describe("LiveRunPanel", () => {
  it("renders events from a mocked EventSource", async () => {
    let es: { onmessage: ((m: { data: string }) => void) | null; onerror: (() => void) | null; close: () => void } | null = null;
    const factory = (url: string) => {
      expect(url).toContain("/runs/run_1/events");
      es = { onmessage: null, onerror: null, close: vi.fn() };
      return es as unknown as EventSource;
    };
    render(<LiveRunPanel runId="run_1" factory={factory} />);
    const send = (type: string, payload: object) => es!.onmessage!({ data: JSON.stringify({ type, run_id: "run_1", ts: "", payload }) });
    send("state", { to: "SCORING" });
    send("agent_start", { agent: "risk_scorer" });
    send("tool_call", { agent: "kb_search", latency_ms: 12, cache_hit: true });
    send("spend", { cost_usd: 0.01, max_cost_usd: 0.05, tokens: 900 });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("SCORING"));
    expect(screen.getByTestId("agent")).toHaveTextContent("risk_scorer");
    expect(screen.getByLabelText("tool calls")).toHaveTextContent("kb_search · 12 ms");
    expect(screen.getByText("cache hit")).toBeInTheDocument();
    expect(screen.getByLabelText("spend")).toHaveTextContent("$0.0100 of $0.05");
  });
});

describe("CompareTable", () => {
  it("shows 6 rows", () => {
    render(<CompareTable data={{ a: { ref: "i1@1", verdict: "GO", score: 72 }, b: { ref: "i2@1", verdict: "PIVOT", score: 60 },
      dimensions: [{ dimension: "risk", a: 4, b: 2 }] }} />);
    expect(screen.getAllByTestId("compare-row")).toHaveLength(6);
  });
});

describe("runtime config", () => {
  it("reads the API address at runtime", () => {
    window.__CONFIG__ = { API_BASE_URL: "/api-from-config" };
    expect(apiBase()).toBe("/api-from-config");
  });
});
