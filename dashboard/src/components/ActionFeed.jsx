function OutcomeBadge({ outcome }) {
  const map = {
    approved: { label: 'PASS', bg: 'bg-emerald-100', text: 'text-emerald-700' },
    hard_block: { label: 'BLOCK', bg: 'bg-red-100', text: 'text-red-700' },
    soft_hold: { label: 'HOLD', bg: 'bg-amber-100', text: 'text-amber-700' },
    flagged: { label: 'FLAG', bg: 'bg-blue-100', text: 'text-blue-700' },
  }
  const style = map[outcome] ?? { label: outcome.toUpperCase(), bg: 'bg-slate-100', text: 'text-slate-600' }
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs font-semibold tracking-wide ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  )
}

function formatTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function formatAmount(parameters) {
  try {
    const p = JSON.parse(parameters)
    if (p.amount != null) return `$${Number(p.amount).toLocaleString()}`
  } catch {}
  return '—'
}

export default function ActionFeed({ entries, error, onSelect, selectedId }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Live Action Feed</h1>
          <p className="text-sm text-slate-500 mt-0.5">Real-time compliance decisions — refreshes every 3 seconds</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          {entries.length} entries
        </div>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      <div className="bg-white border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Time</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Agent</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Action Type</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Amount</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Outcome</th>
              <th className="text-right px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Latency</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 && !error && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-slate-400 text-sm">
                  No audit entries yet. Fire a test action below to get started.
                </td>
              </tr>
            )}
            {entries.map((entry) => (
              <tr
                key={entry.entry_id}
                onClick={() => onSelect(entry)}
                className={`border-b border-slate-100 cursor-pointer transition-colors ${
                  selectedId === entry.entry_id
                    ? 'bg-sky-50'
                    : 'hover:bg-slate-50'
                }`}
              >
                <td className="px-4 py-3 text-slate-500 font-mono text-xs whitespace-nowrap">
                  {formatTime(entry.timestamp)}
                </td>
                <td className="px-4 py-3 text-slate-700 font-medium max-w-[160px] truncate">
                  {entry.agent_id}
                </td>
                <td className="px-4 py-3 text-slate-600">
                  {entry.action_type.replace(/_/g, ' ')}
                </td>
                <td className="px-4 py-3 text-slate-600 font-mono">
                  {formatAmount(entry.parameters)}
                </td>
                <td className="px-4 py-3">
                  <OutcomeBadge outcome={entry.outcome} />
                </td>
                <td className="px-4 py-3 text-right text-slate-500 font-mono text-xs">
                  {entry.latency_ms}ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
