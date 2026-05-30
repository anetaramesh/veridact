import { useState } from 'react'

const POLL_OPTIONS = [
  { value: 1000, label: '1 second' },
  { value: 3000, label: '3 seconds' },
  { value: 5000, label: '5 seconds' },
  { value: 10000, label: '10 seconds' },
  { value: 30000, label: '30 seconds' },
]

export default function Settings({ settings, onChange }) {
  const [apiUrlDraft, setApiUrlDraft] = useState(settings.apiBase)
  const [saved, setSaved] = useState(false)

  function save() {
    const trimmed = apiUrlDraft.replace(/\/$/, '')
    onChange({ ...settings, apiBase: trimmed })
    setApiUrlDraft(trimmed)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function handlePollChange(e) {
    onChange({ ...settings, pollInterval: Number(e.target.value) })
  }

  function handleToggle(key) {
    onChange({ ...settings, [key]: !settings[key] })
  }

  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500 mt-0.5">Dashboard configuration — stored in browser local storage</p>
      </div>

      {/* API Connection */}
      <Section title="API Connection">
        <Field label="API base URL" description="Veridact server endpoint used for all dashboard requests.">
          <div className="flex gap-2">
            <input
              type="url"
              value={apiUrlDraft}
              onChange={e => { setApiUrlDraft(e.target.value); setSaved(false) }}
              className="flex-1 border border-slate-300 text-sm px-3 py-1.5 text-slate-700 focus:outline-none focus:border-sky-400 font-mono"
            />
            <button
              onClick={save}
              className="px-4 py-1.5 text-sm font-medium text-white bg-sky-600 hover:bg-sky-700 transition-colors"
            >
              {saved ? '✓ Saved' : 'Save'}
            </button>
          </div>
        </Field>
      </Section>

      {/* Live Feed */}
      <Section title="Live Feed">
        <Field label="Poll interval" description="How often the live feed refreshes from the API.">
          <select
            value={settings.pollInterval}
            onChange={handlePollChange}
            className="border border-slate-300 text-sm px-3 py-1.5 text-slate-700 bg-white focus:outline-none focus:border-sky-400"
          >
            {POLL_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </Field>

        <Field label="Show amounts" description="Display monetary amounts in the action feed table.">
          <Toggle value={settings.showAmounts} onChange={() => handleToggle('showAmounts')} />
        </Field>
      </Section>

      {/* About */}
      <Section title="About">
        <div className="space-y-2 text-sm text-slate-600">
          <Row label="Product" value="Veridact Compliance Monitor" />
          <Row label="Version" value="0.1.0" />
          <Row label="Audit log" value="Append-only SQLite with SHA-256 hash chain" />
          <Row label="Rule engine" value="YAML rule packs + Microsoft AGT (when available)" />
          <Row
            label="API docs"
            value={
              <a
                href={`${settings.apiBase}/docs`}
                target="_blank"
                rel="noreferrer"
                className="text-sky-600 hover:underline"
              >
                {settings.apiBase}/docs ↗
              </a>
            }
          />
        </div>
      </Section>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="mb-8">
      <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3 pb-2 border-b border-slate-200">
        {title}
      </h2>
      <div className="space-y-5">{children}</div>
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

function Row({ label, value }) {
  return (
    <div className="flex gap-4">
      <span className="w-44 text-slate-400 shrink-0">{label}</span>
      <span className="text-slate-700">{value}</span>
    </div>
  )
}

function Toggle({ value, onChange }) {
  return (
    <button
      onClick={onChange}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
        value ? 'bg-sky-500' : 'bg-slate-300'
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${
          value ? 'translate-x-4' : 'translate-x-1'
        }`}
      />
    </button>
  )
}
