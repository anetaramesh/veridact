import { useState } from 'react'

const ACTION_TYPES = ['wire_transfer', 'trade_order', 'loan_approval', 'contract_sign']

export default function ControlBar({ apiBase, onNewEntry }) {
  const [actionType, setActionType] = useState('wire_transfer')
  const [amount, setAmount] = useState('')
  const [recipientId, setRecipientId] = useState('')
  const [agentId, setAgentId] = useState('demo-agent-01')
  const [firing, setFiring] = useState(false)
  const [fireResult, setFireResult] = useState(null)

  const [verifying, setVerifying] = useState(false)
  const [chainStatus, setChainStatus] = useState(null)

  async function fireAction() {
    setFiring(true)
    setFireResult(null)
    try {
      const res = await fetch(`${apiBase}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_type: actionType,
          parameters: {
            ...(amount ? { amount: parseFloat(amount) } : {}),
            ...(recipientId ? { recipient_id: recipientId } : {}),
          },
          context: {},
          agent_id: agentId || 'demo-agent-01',
        }),
      })
      const data = await res.json()
      setFireResult({ ok: data.approved, outcome: data.outcome, rationale: data.rationale })
      onNewEntry()
    } catch (e) {
      setFireResult({ ok: false, outcome: 'error', rationale: 'Failed to reach API. Is it running?' })
    } finally {
      setFiring(false)
    }
  }

  async function verifyChain() {
    setVerifying(true)
    setChainStatus(null)
    try {
      const res = await fetch(`${apiBase}/audit/verify`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setChainStatus(data)
    } catch {
      setChainStatus({ valid: false, entry_count: 0, error: 'Unable to reach API' })
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div
      className="fixed bottom-0 border-t border-slate-200 bg-white px-6 py-4 flex items-start gap-8 z-30"
      style={{ left: 240, right: 0 }}
    >
      {/* Test simulator */}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Test Simulator</p>
        <div className="flex items-end gap-2 flex-wrap">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Action type</label>
            <select
              value={actionType}
              onChange={e => setActionType(e.target.value)}
              className="border border-slate-300 text-sm px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
            >
              {ACTION_TYPES.map(t => (
                <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Amount</label>
            <input
              type="number"
              placeholder="0.00"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              className="border border-slate-300 text-sm px-2 py-1.5 w-28 text-slate-700 focus:outline-none focus:border-sky-400"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Recipient ID</label>
            <input
              type="text"
              placeholder="recipient-001"
              value={recipientId}
              onChange={e => setRecipientId(e.target.value)}
              className="border border-slate-300 text-sm px-2 py-1.5 w-32 text-slate-700 focus:outline-none focus:border-sky-400"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Agent ID</label>
            <input
              type="text"
              placeholder="demo-agent-01"
              value={agentId}
              onChange={e => setAgentId(e.target.value)}
              className="border border-slate-300 text-sm px-2 py-1.5 w-32 text-slate-700 focus:outline-none focus:border-sky-400"
            />
          </div>
          <button
            onClick={fireAction}
            disabled={firing}
            className="px-4 py-1.5 text-sm font-medium text-white bg-sky-600 hover:bg-sky-700 disabled:opacity-50 transition-colors"
          >
            {firing ? 'Firing…' : 'Fire test action'}
          </button>

          {fireResult && (
            <div className={`text-xs px-3 py-1.5 border font-medium ${
              fireResult.outcome === 'approved'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : fireResult.outcome === 'error'
                ? 'bg-slate-50 border-slate-200 text-slate-600'
                : 'bg-red-50 border-red-200 text-red-700'
            }`}>
              {fireResult.outcome.toUpperCase()}: {fireResult.rationale}
            </div>
          )}
        </div>
      </div>

      {/* Chain verifier */}
      <div className="shrink-0">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Audit Chain</p>
        <div className="flex items-center gap-3">
          <button
            onClick={verifyChain}
            disabled={verifying}
            className="px-4 py-1.5 text-sm font-medium border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
          >
            {verifying ? 'Verifying…' : 'Verify chain integrity'}
          </button>

          {chainStatus && (
            <div className={`flex items-center gap-2 text-sm font-medium ${
              chainStatus.valid ? 'text-emerald-700' : 'text-red-700'
            }`}>
              {chainStatus.valid ? (
                <>
                  <ShieldOkIcon />
                  Chain intact ({chainStatus.entry_count} entries)
                </>
              ) : (
                <>
                  <ShieldBrokenIcon />
                  {chainStatus.error
                    ? chainStatus.error
                    : `Chain broken at entry ${chainStatus.broken_at ?? 'unknown'}`}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ShieldOkIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <polyline points="9 12 11 14 15 10" />
    </svg>
  )
}

function ShieldBrokenIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <line x1="9" y1="9" x2="15" y2="15" /><line x1="15" y1="9" x2="9" y2="15" />
    </svg>
  )
}
