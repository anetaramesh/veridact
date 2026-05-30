import { useState, useMemo } from 'react'

const OUTCOME_MAP = {
  approved:   { label: 'PASS',  bg: 'bg-emerald-100', text: 'text-emerald-700' },
  hard_block: { label: 'BLOCK', bg: 'bg-red-100',     text: 'text-red-700' },
  soft_hold:  { label: 'HOLD',  bg: 'bg-amber-100',   text: 'text-amber-700' },
  flagged:    { label: 'FLAG',  bg: 'bg-blue-100',     text: 'text-blue-700' },
}

function OutcomeBadge({ outcome }) {
  const style = OUTCOME_MAP[outcome] ?? { label: outcome.toUpperCase(), bg: 'bg-slate-100', text: 'text-slate-600' }
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs font-semibold tracking-wide ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  )
}

function formatTimestamp(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    const date = d.toLocaleDateString([], { year: 'numeric', month: 'short', day: '2-digit' })
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    return `${date} ${time}`
  } catch {
    return ts
  }
}

// Returns "YYYY-MM-DD" in local time for a timestamp string
function toLocalDate(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  } catch {
    return ''
  }
}

function formatAmount(parameters) {
  try {
    const p = JSON.parse(parameters)
    if (p.amount != null) return `$${Number(p.amount).toLocaleString()}`
  } catch {}
  return '—'
}

function formatRecipient(parameters) {
  try {
    const p = JSON.parse(parameters)
    return p.recipient_id ?? p.applicant_id ?? p.ticker ?? '—'
  } catch {}
  return '—'
}

export default function ActionFeed({ entries, error, onSelect, selectedId, showAmounts }) {
  const [dateFilter, setDateFilter]         = useState('')
  const [actionFilter, setActionFilter]     = useState('')
  const [outcomeFilter, setOutcomeFilter]   = useState('')

  // Derive unique action types and outcomes from loaded entries
  const actionTypes = useMemo(
    () => [...new Set(entries.map(e => e.action_type))].sort(),
    [entries]
  )
  const outcomes = useMemo(
    () => [...new Set(entries.map(e => e.outcome))].sort(),
    [entries]
  )

  const filtered = useMemo(() => {
    return entries.filter(e => {
      if (dateFilter   && toLocalDate(e.timestamp) !== dateFilter) return false
      if (actionFilter && e.action_type !== actionFilter)          return false
      if (outcomeFilter && e.outcome !== outcomeFilter)            return false
      return true
    })
  }, [entries, dateFilter, actionFilter, outcomeFilter])

  const hasFilters = dateFilter || actionFilter || outcomeFilter

  function clearFilters() {
    setDateFilter('')
    setActionFilter('')
    setOutcomeFilter('')
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Live Action Feed</h1>
          <p className="text-sm text-slate-500 mt-0.5">Real-time compliance decisions — refreshes every 3 seconds</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          {filtered.length}{hasFilters ? ` / ${entries.length}` : ''} entries
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-end gap-3 mb-4 flex-wrap">
        <div>
          <label className="block text-xs text-slate-500 mb-1">Date</label>
          <input
            type="date"
            value={dateFilter}
            onChange={e => setDateFilter(e.target.value)}
            className="border border-slate-300 text-sm px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Action type</label>
          <select
            value={actionFilter}
            onChange={e => setActionFilter(e.target.value)}
            className="border border-slate-300 text-sm px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
          >
            <option value="">All actions</option>
            {actionTypes.map(t => (
              <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Outcome</label>
          <select
            value={outcomeFilter}
            onChange={e => setOutcomeFilter(e.target.value)}
            className="border border-slate-300 text-sm px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
          >
            <option value="">All outcomes</option>
            {outcomes.map(o => (
              <option key={o} value={o}>{OUTCOME_MAP[o]?.label ?? o.toUpperCase()}</option>
            ))}
          </select>
        </div>
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="text-xs text-slate-400 hover:text-slate-600 underline pb-1.5"
          >
            Clear filters
          </button>
        )}
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
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide whitespace-nowrap">Timestamp</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Agent</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Action Type</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Recipient</th>
              {showAmounts !== false && (
                <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Amount</th>
              )}
              <th className="text-left px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Outcome</th>
              <th className="text-right px-4 py-3 font-medium text-slate-600 text-xs uppercase tracking-wide">Latency</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !error && (
              <tr>
                <td colSpan={showAmounts !== false ? 7 : 6} className="px-4 py-12 text-center text-slate-400 text-sm">
                  {hasFilters
                    ? 'No entries match the current filters.'
                    : 'No audit entries yet. Fire a test action below to get started.'}
                </td>
              </tr>
            )}
            {filtered.map((entry) => (
              <tr
                key={entry.entry_id}
                onClick={() => onSelect(entry)}
                className={`border-b border-slate-100 cursor-pointer transition-colors ${
                  selectedId === entry.entry_id ? 'bg-sky-50' : 'hover:bg-slate-50'
                }`}
              >
                <td className="px-4 py-3 text-slate-500 font-mono text-xs whitespace-nowrap">
                  {formatTimestamp(entry.timestamp)}
                </td>
                <td className="px-4 py-3 text-slate-700 font-medium max-w-[160px] truncate">
                  {entry.agent_id}
                </td>
                <td className="px-4 py-3 text-slate-600">
                  {entry.action_type.replace(/_/g, ' ')}
                </td>
                <td className="px-4 py-3 text-slate-600 font-mono text-xs">
                  {formatRecipient(entry.parameters)}
                </td>
                {showAmounts !== false && (
                  <td className="px-4 py-3 text-slate-600 font-mono">
                    {formatAmount(entry.parameters)}
                  </td>
                )}
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
