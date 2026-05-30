import { useState, useEffect, useCallback } from 'react'

function truncateHash(h) {
  if (!h || h === 'GENESIS') return h
  return h.slice(0, 10) + '…'
}

function formatTs(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString([], {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return ts }
}

function OutcomePip({ outcome }) {
  const map = {
    approved: 'bg-emerald-400',
    hard_block: 'bg-red-500',
    soft_hold: 'bg-amber-400',
    flagged: 'bg-blue-400',
  }
  return <span className={`inline-block w-2 h-2 rounded-full ${map[outcome] ?? 'bg-slate-400'}`} title={outcome} />
}

export default function AuditChain({ apiBase }) {
  const [chain, setChain] = useState(null)
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [verRes, entriesRes] = await Promise.all([
        fetch(`${apiBase}/audit/verify`),
        fetch(`${apiBase}/audit/recent?limit=200`),
      ])
      if (!verRes.ok || !entriesRes.ok) throw new Error('API error')
      const [chainData, entriesData] = await Promise.all([verRes.json(), entriesRes.json()])
      setChain(chainData)
      // Sort oldest-first for chain display
      setEntries([...entriesData].reverse())
    } catch {
      setError('Unable to load audit chain. Check API connection.')
    } finally {
      setLoading(false)
      setVerifying(false)
    }
  }, [apiBase])

  useEffect(() => { load() }, [load])

  function handleVerify() {
    setVerifying(true)
    load()
  }

  const firstTs = entries[0]?.timestamp
  const lastTs = entries[entries.length - 1]?.timestamp

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Audit Chain</h1>
          <p className="text-sm text-slate-500 mt-0.5">SHA-256 hash-chained immutable audit log</p>
        </div>
        <button
          onClick={handleVerify}
          disabled={verifying || loading}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
        >
          <ShieldIcon />
          {verifying ? 'Verifying…' : 'Re-verify chain'}
        </button>
      </div>

      {error && (
        <div className="mb-6 px-4 py-3 bg-red-50 border border-red-200 text-red-700 text-sm">{error}</div>
      )}

      {/* Integrity banner */}
      {chain && (
        <div className={`flex items-center gap-4 px-6 py-4 mb-6 border ${
          chain.valid
            ? 'bg-emerald-50 border-emerald-200'
            : 'bg-red-50 border-red-200'
        }`}>
          {chain.valid ? <ShieldOkIcon large /> : <ShieldBrokenIcon large />}
          <div>
            <p className={`font-semibold text-base ${chain.valid ? 'text-emerald-800' : 'text-red-800'}`}>
              {chain.valid ? 'Chain Integrity Verified' : 'Chain Integrity Compromised'}
            </p>
            <p className={`text-sm mt-0.5 ${chain.valid ? 'text-emerald-700' : 'text-red-700'}`}>
              {chain.valid
                ? `All ${chain.entry_count} entries verified — SHA-256 hash chain is intact`
                : `Chain broken at entry ${chain.broken_at ?? 'unknown'} — tamper detected`}
            </p>
          </div>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard label="Total entries" value={chain?.entry_count ?? '—'} />
        <StatCard label="Oldest entry" value={firstTs ? formatTs(firstTs) : '—'} small />
        <StatCard label="Latest entry" value={lastTs ? formatTs(lastTs) : '—'} small />
        <StatCard
          label="Chain status"
          value={chain == null ? '—' : chain.valid ? 'INTACT' : 'BROKEN'}
          valueClass={chain == null ? '' : chain.valid ? 'text-emerald-600' : 'text-red-600'}
        />
      </div>

      {/* Chain table */}
      <div className="bg-white border border-slate-200 overflow-hidden">
        <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            Hash chain (showing up to 200 entries, oldest first)
          </span>
          <span className="text-xs text-slate-400">{entries.length} entries loaded</span>
        </div>

        {loading ? (
          <div className="px-4 py-12 text-center text-slate-400 text-sm">Loading chain…</div>
        ) : entries.length === 0 ? (
          <div className="px-4 py-12 text-center text-slate-400 text-sm">
            No audit entries yet. Fire a test action to start the chain.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">#</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">Timestamp</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">Agent</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">Action</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">Out</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">Prev hash</th>
                  <th className="text-left px-4 py-2.5 font-medium text-slate-500 uppercase tracking-wide">Entry hash</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr key={e.entry_id} className="border-b border-slate-100 hover:bg-slate-50 font-mono">
                    <td className="px-4 py-2.5 text-slate-400">{i + 1}</td>
                    <td className="px-4 py-2.5 text-slate-500 whitespace-nowrap">{formatTs(e.timestamp)}</td>
                    <td className="px-4 py-2.5 text-slate-600 max-w-[120px] truncate font-sans">{e.agent_id}</td>
                    <td className="px-4 py-2.5 text-slate-600 font-sans">{e.action_type.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2.5"><OutcomePip outcome={e.outcome} /></td>
                    <td className="px-4 py-2.5 text-slate-400" title={e.prev_hash}>
                      {e.prev_hash === 'GENESIS'
                        ? <span className="text-sky-500 font-semibold">GENESIS</span>
                        : truncateHash(e.prev_hash)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700 font-semibold" title={e.entry_hash}>
                      {truncateHash(e.entry_hash)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function StatCard({ label, value, small, valueClass }) {
  return (
    <div className="bg-white border border-slate-200 px-4 py-3">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`font-semibold text-slate-900 ${small ? 'text-sm' : 'text-lg'} ${valueClass ?? ''}`}>{value}</p>
    </div>
  )
}

function ShieldIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  )
}

function ShieldOkIcon({ large }) {
  const s = large ? 28 : 16
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="#15803d" strokeWidth="2" className="shrink-0">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <polyline points="9 12 11 14 15 10" />
    </svg>
  )
}

function ShieldBrokenIcon({ large }) {
  const s = large ? 28 : 16
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="#b91c1c" strokeWidth="2" className="shrink-0">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <line x1="9" y1="9" x2="15" y2="15" /><line x1="15" y1="9" x2="9" y2="15" />
    </svg>
  )
}
