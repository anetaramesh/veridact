import { useState, useCallback } from 'react'

const ACTION_TYPES = [
  'wire_transfer', 'ach_payment', 'internal_transfer',
  'check_issuance', 'equity_trade', 'loan_decision',
  'account_open',
]

// Toggle rule IDs used in toggle scenarios
const TOGGLE_RULE_IDS = {
  kyc:       'finra_kyc_2090',
  ofac:      'finra_ofac_sanctions',
  threshold: 'finra_wire_threshold',
  freeze:    'finra_account_freeze',
}

// KYC 2090 scenarios + toggle demos + existing ones
const SCENARIOS = [
  {
    label: 'KYC pass — full details',
    tag: 'PASS',
    description: 'Rule 2090: all required fields present',
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 5000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC block — no customer_id',
    tag: 'BLOCK',
    description: 'Rule 2090: customer_id missing → hard block',
    payload: {
      action_type: 'wire_transfer',
      parameters: { account_id: 'ACC-001', amount: 5000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC block — no account_id',
    tag: 'BLOCK',
    description: 'Rule 2090: account_id missing → hard block',
    payload: {
      action_type: 'equity_trade',
      parameters: { customer_id: 'CUST-001', ticker: 'AAPL', amount: 10000 },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC block — empty fields',
    tag: 'BLOCK',
    description: 'Rule 2090: empty strings count as missing',
    payload: {
      action_type: 'ach_payment',
      parameters: { customer_id: '', account_id: '', amount: 200, recipient_id: 'PAYEE-001' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC pass — fields in context',
    tag: 'PASS',
    description: 'Rule 2090: KYC fields supplied via context',
    payload: {
      action_type: 'wire_transfer',
      parameters: { amount: 500, recipient_id: 'BANK-ABC' },
      context: { customer_id: 'CUST-CTX', account_id: 'ACC-CTX' },
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC + OFAC double block',
    tag: 'BLOCK',
    description: 'Rule 2090 + 3310: missing KYC fields AND sanctioned recipient',
    payload: {
      action_type: 'wire_transfer',
      parameters: { amount: 500, recipient_id: 'SDN-001' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC + threshold double block',
    tag: 'BLOCK',
    description: 'Rule 2090 + 3110: missing KYC fields AND over $1M threshold',
    payload: {
      action_type: 'wire_transfer',
      parameters: { amount: 2_000_000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'KYC pass — uncovered action',
    tag: 'PASS',
    description: 'Rule 2090 does not apply to account_open',
    payload: {
      action_type: 'account_open',
      parameters: { amount: 100 },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'OFAC block — SDN recipient',
    tag: 'BLOCK',
    description: 'Rule 3310: wire to sanctioned entity',
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 1000, recipient_id: 'SDN-001' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Wire threshold block',
    tag: 'HOLD',
    description: 'Rule 3110: $2M wire exceeds autonomous limit',
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 2_000_000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
]

// Toggle test scenarios — demonstrate rule on/off effect
const TOGGLE_SCENARIOS = [
  {
    label: 'Toggle KYC off → SDN passes',
    tag: 'DEMO',
    description: 'Disable finra_kyc_2090, then fire SDN wire — KYC no longer blocks',
    ruleToToggle: TOGGLE_RULE_IDS.kyc,
    toggleOff: true,
    payload: {
      action_type: 'wire_transfer',
      parameters: { account_id: 'ACC-001', amount: 1000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Toggle OFAC off → SDN passes',
    tag: 'DEMO',
    description: 'Disable OFAC rule, then send to SDN-001 — no sanctions block',
    ruleToToggle: TOGGLE_RULE_IDS.ofac,
    toggleOff: true,
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 500, recipient_id: 'SDN-001' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Toggle threshold off → $2M passes',
    tag: 'DEMO',
    description: 'Disable wire threshold rule — $2M wire now approved',
    ruleToToggle: TOGGLE_RULE_IDS.threshold,
    toggleOff: true,
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 2_000_000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Toggle freeze off → frozen acct passes',
    tag: 'DEMO',
    description: 'Disable account freeze rule — frozen account transacts freely',
    ruleToToggle: TOGGLE_RULE_IDS.freeze,
    toggleOff: true,
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'FROZEN-ACC-001', amount: 500, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Re-enable KYC → missing fields blocked',
    tag: 'RESTORE',
    description: 'Re-enable finra_kyc_2090 — KYC enforcement resumes',
    ruleToToggle: TOGGLE_RULE_IDS.kyc,
    toggleOff: false,
    payload: {
      action_type: 'wire_transfer',
      parameters: { account_id: 'ACC-001', amount: 1000, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Re-enable OFAC → SDN blocked again',
    tag: 'RESTORE',
    description: 'Re-enable OFAC sanctions — SDN-001 is blocked again',
    ruleToToggle: TOGGLE_RULE_IDS.ofac,
    toggleOff: false,
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 500, recipient_id: 'SDN-001' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
  {
    label: 'Re-enable all rules',
    tag: 'RESTORE',
    description: 'Re-enable wire threshold and account freeze',
    ruleToToggle: [TOGGLE_RULE_IDS.threshold, TOGGLE_RULE_IDS.freeze],
    toggleOff: false,
    payload: {
      action_type: 'wire_transfer',
      parameters: { customer_id: 'CUST-001', account_id: 'ACC-001', amount: 500, recipient_id: 'LEGIT-BANK' },
      context: {},
      agent_id: 'demo-agent-01',
    },
  },
]

const TAG_STYLES = {
  PASS:  'bg-emerald-100 text-emerald-700',
  BLOCK: 'bg-red-100 text-red-700',
  HOLD:  'bg-amber-100 text-amber-700',
}

const TOGGLE_TAG_STYLES = {
  DEMO:    'bg-purple-100 text-purple-700',
  RESTORE: 'bg-sky-100 text-sky-700',
}

export default function ControlBar({ apiBase, onNewEntry }) {
  const [mode, setMode] = useState('manual') // 'manual' | 'scenario' | 'toggle'
  const [actionType, setActionType] = useState('wire_transfer')
  const [amount, setAmount] = useState('')
  const [recipientId, setRecipientId] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [accountId, setAccountId] = useState('')
  const [agentId, setAgentId] = useState('demo-agent-01')
  const [firing, setFiring] = useState(false)
  const [fireResult, setFireResult] = useState(null)

  const [verifying, setVerifying] = useState(false)
  const [chainStatus, setChainStatus] = useState(null)
  const [clearConfirm, setClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)

  const [toggleStatus, setToggleStatus] = useState(null)

  const fireToggleScenario = useCallback(async (scenario) => {
    setFiring(true)
    setFireResult(null)
    setToggleStatus(null)

    const ruleIds = Array.isArray(scenario.ruleToToggle)
      ? scenario.ruleToToggle
      : [scenario.ruleToToggle]

    // Step 1: get current status
    try {
      const statusRes = await fetch(`${apiBase}/rules/active/status`)
      const status = statusRes.ok ? await statusRes.json() : {}

      // Step 2: toggle rules to desired state
      for (const ruleId of ruleIds) {
        const currentlyOn = status[ruleId] !== false
        const shouldBeOn = !scenario.toggleOff
        if (currentlyOn !== shouldBeOn) {
          await fetch(`${apiBase}/rules/${ruleId}/toggle`, { method: 'POST' })
        }
      }
      setToggleStatus({
        rules: ruleIds,
        state: scenario.toggleOff ? 'disabled' : 're-enabled',
      })
    } catch { /* ignore toggle errors */ }

    // Step 3: fire the payload
    await firePayload(scenario.payload)
  }, [apiBase])

  async function firePayload(payload) {
    setFiring(true)
    setFireResult(null)
    try {
      const res = await fetch(`${apiBase}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      setFireResult({ outcome: data.outcome, rationale: data.rationale, violations: data.violations ?? [] })
      onNewEntry()
    } catch {
      setFireResult({ outcome: 'error', rationale: 'Failed to reach API. Is it running?', violations: [] })
    } finally {
      setFiring(false)
    }
  }

  function fireManual() {
    firePayload({
      action_type: actionType,
      parameters: {
        ...(amount       ? { amount: parseFloat(amount) }  : {}),
        ...(recipientId  ? { recipient_id: recipientId }   : {}),
        ...(customerId   ? { customer_id: customerId }     : {}),
        ...(accountId    ? { account_id: accountId }       : {}),
      },
      context: {},
      agent_id: agentId || 'demo-agent-01',
    })
  }

  async function clearLog() {
    setClearing(true)
    try {
      await fetch(`${apiBase}/audit/reset`, { method: 'POST' })
      setClearConfirm(false)
      setChainStatus(null)
      setFireResult(null)
      onNewEntry()
    } catch { /* server offline */ }
    finally { setClearing(false) }
  }

  async function verifyChain() {
    setVerifying(true)
    setChainStatus(null)
    try {
      const res = await fetch(`${apiBase}/audit/verify`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setChainStatus(await res.json())
    } catch {
      setChainStatus({ valid: false, entry_count: 0, error: 'Unable to reach API' })
    } finally { setVerifying(false) }
  }

  return (
    <div
      className="fixed bottom-0 border-t border-slate-200 bg-white px-6 py-4 flex items-start gap-8 z-30"
      style={{ left: 240, right: 0 }}
    >
      {/* Simulator */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 mb-2">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Test Simulator</p>
          <div className="flex text-xs border border-slate-200">
            <button
              onClick={() => { setMode('manual'); setFireResult(null); setToggleStatus(null) }}
              className={`px-2.5 py-0.5 transition-colors ${mode === 'manual' ? 'bg-sky-600 text-white' : 'text-slate-500 hover:bg-slate-50'}`}
            >Manual</button>
            <button
              onClick={() => { setMode('scenario'); setFireResult(null); setToggleStatus(null) }}
              className={`px-2.5 py-0.5 transition-colors ${mode === 'scenario' ? 'bg-sky-600 text-white' : 'text-slate-500 hover:bg-slate-50'}`}
            >KYC Scenarios</button>
            <button
              onClick={() => { setMode('toggle'); setFireResult(null); setToggleStatus(null) }}
              className={`px-2.5 py-0.5 transition-colors ${mode === 'toggle' ? 'bg-purple-600 text-white' : 'text-slate-500 hover:bg-slate-50'}`}
            >Toggle Tests</button>
          </div>
        </div>

        {mode === 'manual' ? (
          <div className="flex items-end gap-2 flex-wrap">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Action type</label>
              <select value={actionType} onChange={e => setActionType(e.target.value)}
                className="border border-slate-300 text-sm px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400">
                {ACTION_TYPES.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Customer ID</label>
              <input type="text" placeholder="CUST-001" value={customerId}
                onChange={e => setCustomerId(e.target.value)}
                className="border border-slate-300 text-sm px-2 py-1.5 w-28 text-slate-700 focus:outline-none focus:border-sky-400" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Account ID</label>
              <input type="text" placeholder="ACC-001" value={accountId}
                onChange={e => setAccountId(e.target.value)}
                className="border border-slate-300 text-sm px-2 py-1.5 w-28 text-slate-700 focus:outline-none focus:border-sky-400" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Amount</label>
              <input type="number" placeholder="0.00" value={amount}
                onChange={e => setAmount(e.target.value)}
                className="border border-slate-300 text-sm px-2 py-1.5 w-24 text-slate-700 focus:outline-none focus:border-sky-400" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Recipient ID</label>
              <input type="text" placeholder="recipient-001" value={recipientId}
                onChange={e => setRecipientId(e.target.value)}
                className="border border-slate-300 text-sm px-2 py-1.5 w-28 text-slate-700 focus:outline-none focus:border-sky-400" />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1">Agent ID</label>
              <input type="text" placeholder="demo-agent-01" value={agentId}
                onChange={e => setAgentId(e.target.value)}
                className="border border-slate-300 text-sm px-2 py-1.5 w-28 text-slate-700 focus:outline-none focus:border-sky-400" />
            </div>
            <button onClick={fireManual} disabled={firing}
              className="px-4 py-1.5 text-sm font-medium text-white bg-sky-600 hover:bg-sky-700 disabled:opacity-50 transition-colors">
              {firing ? 'Firing…' : 'Fire'}
            </button>
          </div>
        ) : mode === 'scenario' ? (
          <div className="flex gap-2 flex-wrap">
            {SCENARIOS.map((s, i) => (
              <button key={i} onClick={() => firePayload(s.payload)} disabled={firing}
                title={s.description}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs border border-slate-200 hover:border-sky-400 hover:bg-sky-50 disabled:opacity-40 transition-colors text-left">
                <span className={`px-1 py-0.5 text-xs font-bold ${TAG_STYLES[s.tag]}`}>{s.tag}</span>
                <span className="text-slate-700">{s.label}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-1">
            <p className="text-xs text-slate-400 mb-2">
              Each button toggles a rule on/off then fires a transaction — watch the outcome change.
            </p>
            <div className="flex gap-2 flex-wrap">
              {TOGGLE_SCENARIOS.map((s, i) => (
                <button key={i} onClick={() => fireToggleScenario(s)} disabled={firing}
                  title={s.description}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-xs border border-slate-200 hover:border-purple-400 hover:bg-purple-50 disabled:opacity-40 transition-colors text-left">
                  <span className={`px-1 py-0.5 text-xs font-bold ${TOGGLE_TAG_STYLES[s.tag] ?? 'bg-slate-100 text-slate-600'}`}>{s.tag}</span>
                  <span className="text-slate-700">{s.label}</span>
                </button>
              ))}
            </div>
            {toggleStatus && (
              <p className="text-xs text-purple-600 font-medium mt-1">
                ⟳ {toggleStatus.state} {toggleStatus.rules.join(', ')}
              </p>
            )}
          </div>
        )}

        {fireResult && (
          <div className={`mt-2 text-xs px-3 py-1.5 border font-medium flex items-center gap-2 ${
            fireResult.outcome === 'approved'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
              : fireResult.outcome === 'error'
              ? 'bg-slate-50 border-slate-200 text-slate-600'
              : 'bg-red-50 border-red-200 text-red-700'
          }`}>
            <span className="font-bold uppercase">{fireResult.outcome}</span>
            {fireResult.violations?.length > 0 && (
              <span className="font-mono">[{fireResult.violations.join(', ')}]</span>
            )}
            <span className="text-slate-500 font-normal truncate">{fireResult.rationale}</span>
          </div>
        )}
      </div>

      {/* Clear log */}
      <div className="shrink-0">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Reset</p>
        {!clearConfirm ? (
          <button onClick={() => setClearConfirm(true)}
            className="px-4 py-1.5 text-sm font-medium border border-red-200 text-red-600 hover:bg-red-50 transition-colors">
            Clear audit log
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-red-600 font-medium">Delete all entries?</span>
            <button onClick={clearLog} disabled={clearing}
              className="px-3 py-1.5 text-xs font-semibold text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 transition-colors">
              {clearing ? 'Clearing…' : 'Yes, clear'}
            </button>
            <button onClick={() => setClearConfirm(false)}
              className="px-3 py-1.5 text-xs font-medium border border-slate-300 text-slate-600 hover:bg-slate-50 transition-colors">
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Chain verifier */}
      <div className="shrink-0">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Audit Chain</p>
        <div className="flex items-center gap-3">
          <button onClick={verifyChain} disabled={verifying}
            className="px-4 py-1.5 text-sm font-medium border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors">
            {verifying ? 'Verifying…' : 'Verify chain integrity'}
          </button>
          {chainStatus && (
            <div className={`flex items-center gap-2 text-sm font-medium ${chainStatus.valid ? 'text-emerald-700' : 'text-red-700'}`}>
              {chainStatus.valid ? (
                <><ShieldOkIcon />Chain intact ({chainStatus.entry_count} entries)</>
              ) : (
                <><ShieldBrokenIcon />{chainStatus.error ?? `Chain broken at entry ${chainStatus.broken_at ?? 'unknown'}`}</>
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
