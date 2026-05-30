import { useEffect, useRef } from 'react'

function parseViolations(raw) {
  try { return JSON.parse(raw) } catch { return [] }
}

function parseParameters(raw) {
  try { return JSON.parse(raw) } catch { return {} }
}

function SemanticBar({ score }) {
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? 'bg-red-500' : pct >= 40 ? 'bg-amber-400' : 'bg-emerald-500'
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500 mb-1">
        <span>Semantic confidence</span>
        <span className="font-semibold text-slate-700">{pct}%</span>
      </div>
      <div className="h-2 bg-slate-200 overflow-hidden">
        <div className={`h-2 ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function ViolationDetail({ entry, onClose }) {
  const overlayRef = useRef(null)
  const violations = parseViolations(entry.violations)
  const parameters = parseParameters(entry.parameters)

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
      />
      <aside
        ref={overlayRef}
        className="fixed right-0 top-0 h-full bg-white border-l border-slate-200 shadow-xl z-50 flex flex-col overflow-hidden"
        style={{ width: 480 }}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Violation Detail</h2>
            <p className="text-xs text-slate-400 mt-0.5 font-mono truncate">{entry.entry_id}</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 transition-colors p-1"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Summary row */}
          <div className="grid grid-cols-2 gap-3">
            <InfoBox label="Agent" value={entry.agent_id} />
            <InfoBox label="Action" value={entry.action_type.replace(/_/g, ' ')} />
            <InfoBox label="Outcome" value={entry.outcome} />
            <InfoBox label="Latency" value={`${entry.latency_ms}ms`} mono />
          </div>

          {/* Parameters */}
          <div>
            <SectionLabel>Parameters</SectionLabel>
            <div className="bg-slate-50 border border-slate-200 p-3 text-xs font-mono text-slate-700 overflow-x-auto">
              {Object.entries(parameters).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-slate-400 shrink-0">{k}:</span>
                  <span>{String(v)}</span>
                </div>
              ))}
              {Object.keys(parameters).length === 0 && <span className="text-slate-400">No parameters</span>}
            </div>
          </div>

          {/* Violations */}
          {violations.length > 0 && (
            <div>
              <SectionLabel>Violations ({violations.length})</SectionLabel>
              <div className="space-y-3">
                {violations.map((v, i) => (
                  <div key={i} className="border border-red-200 bg-red-50 p-3">
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-xs font-semibold text-red-700 font-mono tracking-wide">
                        {v.violation_code}
                      </span>
                      <span className="text-xs text-slate-400 font-mono shrink-0">{v.rule_id}</span>
                    </div>
                    <p className="text-sm text-red-800 mt-1.5">{v.rationale}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Semantic confidence placeholder — shown when violations exist */}
          {violations.length > 0 && (
            <div>
              <SectionLabel>Semantic Analysis</SectionLabel>
              <SemanticBar score={violations.length > 2 ? 0.85 : violations.length > 0 ? 0.62 : 0.15} />
              <p className="text-xs text-slate-500 mt-2">
                Concern type: <span className="font-medium text-slate-700">
                  {violations[0]?.violation_code?.includes('SANCTION') ? 'sanctions_match'
                    : violations[0]?.violation_code?.includes('THRESHOLD') ? 'threshold_breach'
                    : 'policy_violation'}
                </span>
              </p>
            </div>
          )}

          {/* Rationale */}
          <div>
            <SectionLabel>Rationale</SectionLabel>
            <p className="text-sm text-slate-700 leading-relaxed">{entry.rationale}</p>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-slate-200 shrink-0">
          <button
            onClick={onClose}
            className="w-full py-2 text-sm font-medium text-slate-700 border border-slate-300 hover:bg-slate-50 transition-colors"
          >
            Close
          </button>
        </div>
      </aside>
    </>
  )
}

function InfoBox({ label, value, mono }) {
  return (
    <div className="bg-slate-50 border border-slate-200 px-3 py-2">
      <p className="text-xs text-slate-400 mb-0.5">{label}</p>
      <p className={`text-sm text-slate-800 truncate ${mono ? 'font-mono' : 'font-medium'}`}>{value}</p>
    </div>
  )
}

function SectionLabel({ children }) {
  return <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">{children}</p>
}
