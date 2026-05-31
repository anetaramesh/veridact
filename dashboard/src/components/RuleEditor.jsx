import { useState, useEffect, useCallback } from 'react'

const FINRA_FILES = [
  'finra_kyc_2090.yaml',
  'finra_rule_0140.yaml',
  'finra_rule_1210.yaml',
  'finra_rule_1220.yaml',
  'finra_rule_1230.yaml',
  'finra_rule_1240.yaml',
  'finra_rule_2010.yaml',
  'finra_rule_2070.yaml',
  'finra_rule_2121.yaml',
  'finra_rule_2165.yaml',
  'finra_rule_2210.yaml',
  'finra_rule_2214.yaml',
  'finra_rule_2241.yaml',
  'finra_rule_2242.yaml',
  'finra_rule_2268.yaml',
  'finra_rule_2310.yaml',
  'finra_rule_2320.yaml',
  'finra_rule_2341.yaml',
  'finra_rule_2360.yaml',
  'finra_rule_2370.yaml',
  'finra_rule_3110.yaml',
  'finra_rule_3120.yaml',
  'finra_rule_3130.yaml',
  'finra_rule_3170.yaml',
  'finra_rule_3210.yaml',
  'finra_rule_3260.yaml',
  'finra_rule_3280.yaml',
  'finra_rule_3310.yaml',
  'finra_rule_4110.yaml',
  'finra_rule_4120.yaml',
  'finra_rule_4210.yaml',
  'finra_rule_4511.yaml',
  'finra_rule_4512.yaml',
  'finra_rule_4517.yaml',
  'finra_rule_5110.yaml',
  'finra_rule_5121.yaml',
  'finra_rule_5122.yaml',
  'finra_rule_5130.yaml',
  'finra_rule_5340.yaml',
  'finra_rule_6710.yaml',
  'finra_rule_8310.yaml',
  'finra_rule_9551.yaml',
  'finra_account_freeze.yaml',
  'finra_ofac_sanctions.yaml',
  'finra_wire_threshold.yaml',
]

const GATEWAY_FILES = [
  'gateway_fraud_decline.yaml',
  'gateway_card_restriction.yaml',
  'gateway_limit_exceeded.yaml',
  'gateway_insufficient_funds.yaml',
  'gateway_invalid_data.yaml',
  'gateway_system_error.yaml',
]

const ALL_RULE_FILES = [...FINRA_FILES, ...GATEWAY_FILES]

const EMPTY_RULE = {
  id: '',
  name: '',
  regulation_ref: '',
  description: '',
  check_type: '',
  action_types: [],
  params: {},
  violation_code: '',
  severity: '',
  rationale_template: '',
}

const CHECK_TYPES = ['sanctions_list', 'threshold', 'account_status', 'pattern_match', 'required_fields']
const SEVERITIES = ['hard_block', 'soft_hold', 'flag']
const ACTION_TYPE_OPTIONS = [
  'wire_transfer', 'ach_payment', 'internal_transfer', 'check_issuance',
  'equity_trade', 'loan_decision', 'account_open', 'account_close', '*',
]

export default function RuleEditor({ apiBase }) {
  const [mode, setMode] = useState(null) // null | 'edit'
  const [files, setFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState('')
  const [rule, setRule] = useState(EMPTY_RULE)
  const [isNew, setIsNew] = useState(false)
  const [newFilename, setNewFilename] = useState('')
  const [status, setStatus] = useState(null) // {type: 'success'|'error', msg}
  const [loading, setLoading] = useState(false)
  const [paramsText, setParamsText] = useState('')
  const [paramsError, setParamsError] = useState('')
  // applied status: map ruleId → boolean
  const [appliedStatus, setAppliedStatus] = useState({})
  const [toggling, setToggling] = useState(null) // ruleId being toggled

  const fetchFiles = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/rules`)
      if (!res.ok) throw new Error()
      const all = await res.json()
      setFiles(ALL_RULE_FILES.filter(f => all.includes(f)))
    } catch {
      setFiles(ALL_RULE_FILES)
    }
  }, [apiBase])

  const fetchAppliedStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/rules/active/status`)
      if (!res.ok) return
      setAppliedStatus(await res.json())
    } catch { /* API offline */ }
  }, [apiBase])

  async function handleToggle(e, ruleId) {
    e.stopPropagation()
    setToggling(ruleId)
    try {
      const res = await fetch(`${apiBase}/rules/${ruleId}/toggle`, { method: 'POST' })
      if (!res.ok) return
      const data = await res.json()
      setAppliedStatus(prev => ({ ...prev, [ruleId]: data.applied }))
    } catch { /* API offline */ }
    finally { setToggling(null) }
  }

  useEffect(() => {
    fetchFiles()
    fetchAppliedStatus()
  }, [fetchFiles, fetchAppliedStatus])

  async function loadFile(filename) {
    setLoading(true)
    setStatus(null)
    try {
      const res = await fetch(`${apiBase}/rules/${filename}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const merged = { ...EMPTY_RULE, ...data }
      setRule(merged)
      setParamsText(jsonToPretty(merged.params ?? {}))
      setParamsError('')
    } catch {
      setStatus({ type: 'error', msg: 'Failed to load file from API.' })
    } finally {
      setLoading(false)
    }
  }

  function handleSelectFile(filename) {
    setSelectedFile(filename)
    setIsNew(false)
    setMode('edit')
    loadFile(filename)
  }

  function handleNewFile() {
    setSelectedFile('')
    setIsNew(true)
    setNewFilename('')
    setRule(EMPTY_RULE)
    setParamsText('{}')
    setParamsError('')
    setStatus(null)
    setMode('edit')
  }

  function setField(key, value) {
    setRule(r => ({ ...r, [key]: value }))
  }

  function toggleActionType(at) {
    setRule(r => {
      const cur = Array.isArray(r.action_types) ? r.action_types : []
      return {
        ...r,
        action_types: cur.includes(at) ? cur.filter(x => x !== at) : [...cur, at],
      }
    })
  }

  function handleParamsChange(text) {
    setParamsText(text)
    try {
      const parsed = JSON.parse(text)
      setRule(r => ({ ...r, params: parsed }))
      setParamsError('')
    } catch {
      setParamsError('Invalid JSON')
    }
  }

  async function handleSave() {
    const filename = isNew
      ? (newFilename.endsWith('.yaml') ? newFilename : `${newFilename}.yaml`)
      : selectedFile

    if (!filename || filename === '.yaml') {
      setStatus({ type: 'error', msg: 'Filename is required.' })
      return
    }
    if (paramsError) {
      setStatus({ type: 'error', msg: 'Fix params JSON before saving.' })
      return
    }

    setLoading(true)
    setStatus(null)
    try {
      const res = await fetch(`${apiBase}/rules/${filename}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content: rule }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      setStatus({ type: 'success', msg: `Saved ${filename} successfully.` })
      if (isNew) {
        setSelectedFile(filename)
        setIsNew(false)
        await fetchFiles()
      }
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setLoading(false)
    }
  }

  // Landing — choose pull or create
  if (mode === null) {
    const applied = Object.values(appliedStatus).filter(Boolean).length
    const total = Object.keys(appliedStatus).length

    const finraApplied = FINRA_FILES.filter(f => appliedStatus[f.replace('.yaml','')] !== false).length
    const gwApplied   = GATEWAY_FILES.filter(f => appliedStatus[f.replace('.yaml','')] !== false).length

    return (
      <div className="max-w-2xl">
        <PageHeader />

        <p className="text-sm text-slate-600 mb-5">
          Toggle rules on/off to include them in real-time compliance evaluation. Click a rule to edit it.
        </p>

        {total > 0 && (
          <div className="text-xs text-slate-400 mb-4">
            <span className="font-semibold text-emerald-600">{applied}</span> / {total} rules applied to live feed
          </div>
        )}

        {/* ── FINRA sub-section ── */}
        <RuleSection
          title="FINRA Compliance Rules"
          badge={`${finraApplied} / ${FINRA_FILES.length}`}
          files={FINRA_FILES}
          appliedStatus={appliedStatus}
          toggling={toggling}
          onSelect={handleSelectFile}
          onToggle={handleToggle}
          defaultOpen={true}
        />

        {/* ── Gateway sub-section ── */}
        <RuleSection
          title="Payment Gateway Rules"
          badge={`${gwApplied} / ${GATEWAY_FILES.length}`}
          files={GATEWAY_FILES}
          appliedStatus={appliedStatus}
          toggling={toggling}
          onSelect={handleSelectFile}
          onToggle={handleToggle}
          defaultOpen={true}
        />

        <div className="mt-6">
          <button
            onClick={handleNewFile}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-sky-600 hover:bg-sky-700 transition-colors"
          >
            <PlusIcon />
            Create new YAML rule file
          </button>
        </div>
      </div>
    )
  }

  // Editor
  const displayFilename = isNew
    ? (newFilename ? (newFilename.endsWith('.yaml') ? newFilename : `${newFilename}.yaml`) : 'new file')
    : selectedFile

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <PageHeader subtitle={displayFilename} />
        <button
          onClick={() => { setMode(null); setStatus(null) }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-slate-600 hover:text-slate-900 border border-slate-200 hover:border-slate-400 bg-white hover:bg-slate-50 transition-colors"
        >
          <ArrowLeftIcon />
          Back to rules
        </button>
      </div>

      {/* Section header: FINRA */}
      <div className="mb-6">
        <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3 pb-2 border-b border-slate-200">
          FINRA
        </h2>
      </div>

      {loading && (
        <div className="text-sm text-slate-400 mb-4">Loading…</div>
      )}

      {status && (
        <div className={`text-sm px-4 py-2 mb-5 ${
          status.type === 'success'
            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
            : 'bg-red-50 text-red-700 border border-red-200'
        }`}>
          {status.msg}
        </div>
      )}

      <div className="space-y-5">
        {/* Filename (new only) */}
        {isNew && (
          <Field label="Filename" description="Lowercase letters, digits, underscores, hyphens. The .yaml extension is added automatically.">
            <input
              type="text"
              value={newFilename}
              onChange={e => setNewFilename(e.target.value)}
              placeholder="finra_my_rule"
              className="w-full border border-slate-300 text-sm px-3 py-1.5 text-slate-700 font-mono focus:outline-none focus:border-sky-400"
            />
          </Field>
        )}

        {/* Pull from existing (new mode only) */}
        {isNew && (
          <Field label="Pull from existing file" description="Optionally load an existing file as a starting point.">
            <div className="flex gap-2">
              <select
                onChange={e => e.target.value && loadFile(e.target.value)}
                className="border border-slate-300 text-sm px-3 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
                defaultValue=""
              >
                <option value="">— choose template —</option>
                {ALL_RULE_FILES.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
          </Field>
        )}

        <Divider />

        {/* Core metadata */}
        <Field label="Rule ID" description="Unique machine-readable identifier (e.g. finra_wire_threshold).">
          <input
            type="text"
            value={rule.id ?? ''}
            onChange={e => setField('id', e.target.value)}
            className="w-full border border-slate-300 text-sm px-3 py-1.5 text-slate-700 font-mono focus:outline-none focus:border-sky-400"
          />
        </Field>

        <Field label="Name" description="Human-readable rule name shown in violation reports.">
          <input
            type="text"
            value={rule.name ?? ''}
            onChange={e => setField('name', e.target.value)}
            className="w-full border border-slate-300 text-sm px-3 py-1.5 text-slate-700 focus:outline-none focus:border-sky-400"
          />
        </Field>

        <Field label="Regulation reference" description="Exact citation (e.g. FINRA Rule 3310; BSA 31 U.S.C. § 5318(l)).">
          <input
            type="text"
            value={rule.regulation_ref ?? ''}
            onChange={e => setField('regulation_ref', e.target.value)}
            className="w-full border border-slate-300 text-sm px-3 py-1.5 text-slate-700 font-mono text-xs focus:outline-none focus:border-sky-400"
          />
        </Field>

        <Field label="Description" description="Full description including regulatory basis. Reviewable by legal counsel.">
          <textarea
            rows={4}
            value={rule.description ?? ''}
            onChange={e => setField('description', e.target.value)}
            className="w-full border border-slate-300 text-sm px-3 py-2 text-slate-700 focus:outline-none focus:border-sky-400 resize-y"
          />
        </Field>

        <Divider />

        {/* Engine fields */}
        <Field label="Check type" description="Evaluation strategy used by the rule engine.">
          <select
            value={rule.check_type ?? ''}
            onChange={e => setField('check_type', e.target.value)}
            className="border border-slate-300 text-sm px-3 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
          >
            <option value="">— select —</option>
            {CHECK_TYPES.map(ct => <option key={ct} value={ct}>{ct}</option>)}
          </select>
        </Field>

        <Field label="Action types" description="Transaction types this rule applies to. Select all that apply.">
          <div className="flex flex-wrap gap-2">
            {ACTION_TYPE_OPTIONS.map(at => {
              const checked = Array.isArray(rule.action_types) && rule.action_types.includes(at)
              return (
                <button
                  key={at}
                  onClick={() => toggleActionType(at)}
                  className={`px-2.5 py-1 text-xs font-mono transition-colors border ${
                    checked
                      ? 'bg-sky-600 text-white border-sky-600'
                      : 'bg-white text-slate-600 border-slate-300 hover:border-sky-400'
                  }`}
                >
                  {at}
                </button>
              )
            })}
          </div>
        </Field>

        <Field label="Severity" description="hard_block stops the action; soft_hold escalates for human review; warn logs only.">
          <select
            value={rule.severity ?? ''}
            onChange={e => setField('severity', e.target.value)}
            className="border border-slate-300 text-sm px-3 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
          >
            <option value="">— select —</option>
            {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>

        <Field label="Violation code" description="Short code emitted in audit log when rule is triggered (e.g. OFAC_SANCTIONS_MATCH).">
          <input
            type="text"
            value={rule.violation_code ?? ''}
            onChange={e => setField('violation_code', e.target.value)}
            className="w-full border border-slate-300 text-sm px-3 py-1.5 text-slate-700 font-mono focus:outline-none focus:border-sky-400"
          />
        </Field>

        <Divider />

        {/* Params — raw JSON editor */}
        <Field
          label="Params (JSON)"
          description="Strategy-specific parameters. For sanctions_list: {field, sanctions_list:[...]}. For threshold: {field, max_value:N}. For account_status: {field, frozen_accounts:[...]}."
        >
          <textarea
            rows={8}
            value={paramsText}
            onChange={e => handleParamsChange(e.target.value)}
            spellCheck={false}
            className={`w-full border text-sm px-3 py-2 text-slate-700 font-mono focus:outline-none resize-y ${
              paramsError ? 'border-red-400 bg-red-50' : 'border-slate-300 focus:border-sky-400'
            }`}
          />
          {paramsError && (
            <p className="text-xs text-red-500 mt-1">{paramsError}</p>
          )}
        </Field>

        <Field label="Rationale template" description="Human-readable explanation shown in violation reports. Use {field_name} for interpolation.">
          <textarea
            rows={3}
            value={rule.rationale_template ?? ''}
            onChange={e => setField('rationale_template', e.target.value)}
            className="w-full border border-slate-300 text-sm px-3 py-2 text-slate-700 focus:outline-none focus:border-sky-400 resize-y"
          />
        </Field>
      </div>

      {/* Save */}
      <div className="flex items-center gap-4 mt-8 pt-6 border-t border-slate-200">
        <button
          onClick={handleSave}
          disabled={loading}
          className="px-5 py-2 text-sm font-medium text-white bg-sky-600 hover:bg-sky-700 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Saving…' : isNew ? 'Create file' : 'Save changes'}
        </button>
        <p className="text-xs text-amber-600">
          ⚠ Regulatory counsel review required before deploying changes to production.
        </p>
      </div>
    </div>
  )
}

// ── helpers ──────────────────────────────────────────────────────────────────

function PageHeader({ subtitle }) {
  return (
    <div className="mb-6">
      <h1 className="text-xl font-semibold text-slate-900">
        YAML Rule Editor
        {subtitle && <span className="text-slate-400 font-normal text-base ml-2">/ {subtitle}</span>}
      </h1>
      <p className="text-sm text-slate-500 mt-0.5">
        Add, update, or create compliance rule files — changes are written directly to the rules directory.
      </p>
    </div>
  )
}

function RuleSection({ title, badge, files, appliedStatus, toggling, onSelect, onToggle, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="mb-4 border border-slate-200 rounded-sm overflow-hidden">
      {/* Section header — click to collapse/expand */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span className={`transition-transform text-slate-400 text-xs ${open ? 'rotate-90' : ''}`}>▶</span>
          <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">{title}</span>
        </div>
        <span className="text-xs text-slate-400 font-medium">{badge} applied</span>
      </button>

      {/* Rule list */}
      {open && (
        <div className="grid grid-cols-1 divide-y divide-slate-100">
          {files.map(f => {
            const ruleId = f.replace('.yaml', '')
            const isApplied = appliedStatus[ruleId] !== false
            return (
              <FileCard
                key={f}
                filename={f}
                applied={isApplied}
                toggling={toggling === ruleId}
                onSelect={() => onSelect(f)}
                onToggle={e => onToggle(e, ruleId)}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

function FileCard({ filename, applied, toggling, onSelect, onToggle }) {
  const ruleId = filename.replace('.yaml', '')
  const label = ruleId.replace(/_/g, ' ').replace(/\bfinra\b/i, 'FINRA').replace(/\brule\b/i, 'Rule')

  return (
    <div className={`flex items-center gap-3 border text-sm transition-colors ${
      applied ? 'border-slate-200 bg-white' : 'border-slate-100 bg-slate-50'
    }`}>
      {/* Applied toggle */}
      <button
        onClick={onToggle}
        disabled={toggling}
        title={applied ? 'Applied — click to disable' : 'Not applied — click to enable'}
        className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-3 border-r text-xs font-semibold transition-colors ${
          applied
            ? 'border-slate-200 text-emerald-600 hover:bg-emerald-50'
            : 'border-slate-100 text-slate-400 hover:bg-slate-100'
        } ${toggling ? 'opacity-50 cursor-wait' : 'cursor-pointer'}`}
      >
        <span className={`w-2 h-2 rounded-full ${applied ? 'bg-emerald-500' : 'bg-slate-300'}`} />
        {applied ? 'Applied' : 'Off'}
      </button>

      {/* Rule name — click to edit */}
      <button
        onClick={onSelect}
        className="flex-1 flex items-center justify-between px-3 py-3 text-left group hover:bg-sky-50 transition-colors"
      >
        <div>
          <span className={`font-medium capitalize ${applied ? 'text-slate-800' : 'text-slate-400'}`}>
            {label}
          </span>
          <span className="ml-2 text-xs text-slate-400 font-mono">{filename}</span>
        </div>
        <span className="text-sky-500 text-xs opacity-0 group-hover:opacity-100 transition-opacity">Edit →</span>
      </button>
    </div>
  )
}

function Field({ label, description, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-0.5">{label}</label>
      {description && <p className="text-xs text-slate-400 mb-2">{description}</p>}
      {children}
    </div>
  )
}

function Divider() {
  return <hr className="border-slate-200" />
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

function ArrowLeftIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 5 5 12 12 19" />
    </svg>
  )
}

function jsonToPretty(obj) {
  try { return JSON.stringify(obj, null, 2) }
  catch { return '{}' }
}
