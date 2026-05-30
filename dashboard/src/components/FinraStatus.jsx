import { useState, useEffect, useCallback } from 'react'

export default function FinraStatus({ apiBase }) {
  const [status, setStatus] = useState(null)
  const [otcData, setOtcData] = useState(null)
  const [otcError, setOtcError] = useState(null)
  const [loadingOtc, setLoadingOtc] = useState(false)
  const [statusError, setStatusError] = useState(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/finra/status`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setStatus(await res.json())
      setStatusError(null)
    } catch (e) {
      setStatusError('Could not reach API.')
    }
  }, [apiBase])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  async function fetchOtc() {
    setLoadingOtc(true)
    setOtcError(null)
    try {
      const res = await fetch(`${apiBase}/finra/data/otc-summary?limit=10`)
      const json = await res.json()
      if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`)
      setOtcData(json)
    } catch (e) {
      setOtcError(e.message)
    } finally {
      setLoadingOtc(false)
    }
  }

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-900">FINRA API Integration</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Live connection status and data source availability
        </p>
      </div>

      {/* Connection banner */}
      {statusError ? (
        <Banner type="error">{statusError}</Banner>
      ) : status === null ? (
        <Banner type="loading">Checking connection…</Banner>
      ) : status.connected ? (
        <Banner type="success">
          Connected — {status.credential_type === 'firm' ? 'Firm' : 'Public'} credential active
        </Banner>
      ) : (
        <Banner type="warning">
          Not connected — set <code className="font-mono text-xs bg-amber-100 px-1">FINRA_CLIENT_ID</code> and{' '}
          <code className="font-mono text-xs bg-amber-100 px-1">FINRA_CLIENT_SECRET</code> in <code className="font-mono text-xs bg-amber-100 px-1">.env</code>
        </Banner>
      )}

      {/* Data sources */}
      {status && (
        <Section title="Data Sources">
          <div className="space-y-3">
            {Object.entries(status.data_sources).map(([key, src]) => (
              <DataSourceRow key={key} name={key} source={src} />
            ))}
          </div>
        </Section>
      )}

      {/* Credential info */}
      {status && (
        <Section title="Credential">
          <div className="space-y-2 text-sm text-slate-600">
            <InfoRow label="Type" value={
              status.credential_type
                ? <CredentialBadge type={status.credential_type} />
                : <span className="text-slate-400 italic">not configured</span>
            } />
            <InfoRow label="Register / manage" value={
              <a
                href="https://developer.finra.org/APICredentials"
                target="_blank"
                rel="noreferrer"
                className="text-sky-600 hover:underline"
              >
                developer.finra.org/APICredentials ↗
              </a>
            } />
            <InfoRow label="BrokerCheck access" value={
              status.credential_type === 'firm'
                ? <span className="text-emerald-600 font-medium">Enabled</span>
                : <span className="text-slate-500">
                    Requires Firm credential —{' '}
                    <code className="font-mono text-xs bg-slate-100 px-1">FINRA_CREDENTIAL_TYPE=firm</code>
                  </span>
            } />
          </div>
        </Section>
      )}

      {/* Live OTC market data */}
      <Section title="Live OTC Market Data">
        <p className="text-sm text-slate-500 mb-3">
          Sample from FINRA OTC market weekly summary — available with any Public credential.
        </p>
        <button
          onClick={fetchOtc}
          disabled={loadingOtc || !status?.connected}
          className="mb-4 px-4 py-1.5 text-sm font-medium text-white bg-sky-600 hover:bg-sky-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loadingOtc ? 'Loading…' : 'Fetch live data'}
        </button>

        {otcError && <Banner type="error">{otcError}</Banner>}

        {otcData && (
          <div>
            <p className="text-xs text-slate-400 mb-2">{otcData.count} records returned</p>
            <div className="overflow-x-auto border border-slate-200">
              <OtcTable rows={otcData.data} />
            </div>
          </div>
        )}
      </Section>

      {/* How it works */}
      <Section title="How It Works">
        <div className="text-sm text-slate-600 space-y-2">
          <p>
            Rules that previously used hardcoded YAML stub lists now delegate to live API lookups
            when credentials are configured:
          </p>
          <ul className="list-none space-y-1.5 mt-2">
            <FlowItem
              rule="finra_ofac_sanctions"
              check="sanctions_list"
              source="OFAC SDN API (US Treasury)"
              live={status?.data_sources?.ofac_sanctions?.status === 'live'}
            />
            <FlowItem
              rule="finra_account_freeze"
              check="account_status"
              source="FINRA BrokerCheck (Firm credential)"
              live={status?.data_sources?.brokercheck?.status === 'live'}
            />
            <FlowItem
              rule="finra_wire_threshold"
              check="threshold"
              source="Configured threshold ($1,000,000)"
              live={status?.connected}
            />
          </ul>
        </div>
      </Section>
    </div>
  )
}

// ── sub-components ───────────────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div className="mb-8">
      <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3 pb-2 border-b border-slate-200">
        {title}
      </h2>
      {children}
    </div>
  )
}

function Banner({ type, children }) {
  const styles = {
    success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
    error:   'bg-red-50 border-red-200 text-red-800',
    warning: 'bg-amber-50 border-amber-200 text-amber-800',
    loading: 'bg-slate-50 border-slate-200 text-slate-500',
  }
  return (
    <div className={`text-sm px-4 py-2.5 mb-6 border ${styles[type]}`}>
      {children}
    </div>
  )
}

function DataSourceRow({ name, source }) {
  const statusColor = {
    live:        'bg-emerald-500',
    stub:        'bg-amber-400',
    unavailable: 'bg-slate-300',
  }
  const statusLabel = {
    live:        'Live',
    stub:        'Stub (YAML fallback)',
    unavailable: 'Unavailable',
  }
  const displayName = {
    ofac_sanctions: 'OFAC Sanctions',
    brokercheck:    'BrokerCheck',
    otc_market_data:'OTC Market Data',
  }

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-slate-100 last:border-0">
      <span
        className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${statusColor[source.status] ?? 'bg-slate-300'}`}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-slate-800">{displayName[name] ?? name}</span>
          <span className={`text-xs px-1.5 py-0.5 font-medium ${
            source.status === 'live' ? 'bg-emerald-100 text-emerald-700' :
            source.status === 'stub' ? 'bg-amber-100 text-amber-700' :
            'bg-slate-100 text-slate-500'
          }`}>
            {statusLabel[source.status] ?? source.status}
          </span>
        </div>
        <p className="text-xs text-slate-400 mt-0.5">{source.description}</p>
        <p className="text-xs text-slate-300 mt-0.5">Requires: {source.requires}</p>
      </div>
    </div>
  )
}

function InfoRow({ label, value }) {
  return (
    <div className="flex gap-4">
      <span className="w-44 text-slate-400 shrink-0">{label}</span>
      <span>{value}</span>
    </div>
  )
}

function CredentialBadge({ type }) {
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 uppercase tracking-wide ${
      type === 'firm' ? 'bg-sky-100 text-sky-700' : 'bg-slate-100 text-slate-600'
    }`}>
      {type}
    </span>
  )
}

function FlowItem({ rule, check, source, live }) {
  return (
    <li className="flex items-start gap-2">
      <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${live ? 'bg-emerald-500' : 'bg-amber-400'}`} />
      <span>
        <code className="font-mono text-xs bg-slate-100 px-1 text-slate-700">{rule}</code>
        <span className="text-slate-400 mx-1">·</span>
        <span className="text-slate-500 text-xs">{check}</span>
        <span className="text-slate-400 mx-1">→</span>
        <span className="text-slate-700 text-xs">{source}</span>
      </span>
    </li>
  )
}

const OTC_COLS = [
  { key: 'issueSymbolIdentifier', label: 'Symbol' },
  { key: 'issueName',             label: 'Name' },
  { key: 'MPID',                  label: 'MPID' },
  { key: 'marketParticipantName', label: 'Market Participant' },
  { key: 'tierDescription',       label: 'Tier' },
  { key: 'totalWeeklyTradeCount', label: 'Weekly Trades' },
]

function OtcTable({ rows }) {
  if (!rows?.length) return <p className="text-xs text-slate-400 p-3">No data.</p>

  // rows may be CSV strings or objects
  const parsed = rows.map(r => {
    if (typeof r === 'object') return r
    // CSV row — skip (data comes as objects from the API wrapper)
    return {}
  }).filter(r => Object.keys(r).length > 0)

  if (!parsed.length) {
    // Raw CSV — show as plain text
    return (
      <pre className="text-xs font-mono text-slate-600 p-3 overflow-x-auto whitespace-pre-wrap">
        {rows.join('\n')}
      </pre>
    )
  }

  return (
    <table className="w-full text-xs">
      <thead className="bg-slate-50 border-b border-slate-200">
        <tr>
          {OTC_COLS.map(c => (
            <th key={c.key} className="text-left px-3 py-2 text-slate-500 font-medium whitespace-nowrap">
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {parsed.map((row, i) => (
          <tr key={i} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
            {OTC_COLS.map(c => (
              <td key={c.key} className="px-3 py-2 text-slate-700 font-mono whitespace-nowrap">
                {row[c.key] ?? '—'}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
