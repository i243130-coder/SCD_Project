export interface Approval { action: string; estimated_cost_usd: number; current_spend: number; budget_usd: number }

export function ApprovalModal({ approval, onDecide }: { approval: Approval; onDecide: (approve: boolean) => void }) {
  return (
    <div role="dialog" aria-label="approval" className="fixed inset-0 bg-black/30 flex items-center justify-center">
      <div className="bg-white p-6 rounded shadow max-w-md space-y-3">
        <p>This {approval.action.replace("_", " ")} will cost &asymp; ${approval.estimated_cost_usd.toFixed(3)} (spent ${approval.current_spend.toFixed(3)} of ${approval.budget_usd.toFixed(2)} budget).</p>
        <div className="flex gap-2 justify-end">
          <button className="px-3 py-1 border rounded" onClick={() => onDecide(false)}>Decline</button>
          <button className="px-3 py-1 bg-indigo-600 text-white rounded" onClick={() => onDecide(true)}>Approve</button>
        </div>
      </div>
    </div>
  );
}
