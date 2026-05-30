export default function Sidebar({ apiOnline, activePage, onNavigate }) {
  return (
    <aside
      className="flex flex-col justify-between py-8 px-6 text-slate-300 shrink-0"
      style={{ width: 240, backgroundColor: '#0f172a' }}
    >
      <div>
        <div className="mb-10">
          <div className="flex items-center gap-2 mb-1">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7v10l10 5 10-5V7L12 2z" stroke="#38bdf8" strokeWidth="2" strokeLinejoin="round" />
              <path d="M12 22V12M2 7l10 5 10-5" stroke="#38bdf8" strokeWidth="2" strokeLinejoin="round" />
            </svg>
            <span className="text-white font-semibold text-lg tracking-tight">Veridact</span>
          </div>
          <p className="text-xs text-slate-500 pl-7">Compliance Monitor</p>
        </div>

        <nav className="space-y-1">
          <NavItem icon={ActivityIcon} label="Live Feed"    page="feed"     activePage={activePage} onNavigate={onNavigate} />
          <NavItem icon={ShieldIcon}   label="Audit Chain"  page="chain"    activePage={activePage} onNavigate={onNavigate} />
          <NavItem icon={FileIcon}     label="Reports"      href reportApiBase />
          <NavItem icon={YamlIcon}     label="Rule Editor"  page="rules"    activePage={activePage} onNavigate={onNavigate} />
          <NavItem icon={FinraIcon}    label="FINRA API"    page="finra"    activePage={activePage} onNavigate={onNavigate} />
          <NavItem icon={SettingsIcon} label="Settings"     page="settings" activePage={activePage} onNavigate={onNavigate} />
        </nav>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{
            backgroundColor: apiOnline === null ? '#94a3b8' : apiOnline ? '#22c55e' : '#ef4444',
          }}
        />
        <span className="text-slate-400">
          {apiOnline === null ? 'Connecting…' : apiOnline ? 'API connected' : 'API offline'}
        </span>
      </div>
    </aside>
  )
}

function NavItem({ icon: Icon, label, page, activePage, onNavigate, href }) {
  const active = page && activePage === page
  const cls = `flex items-center gap-3 w-full px-3 py-2 text-sm transition-colors text-left ${
    active
      ? 'text-white bg-slate-700/60'
      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
  }`

  if (href) {
    const today = new Date()
    const from = new Date(today)
    from.setDate(from.getDate() - 30)
    const fmt = d => d.toISOString().slice(0, 10)
    const url = `/report/pdf?from=${fmt(from)}&to=${fmt(today)}`
    return (
      <a href={url} target="_blank" rel="noreferrer" className={cls} style={{ borderRadius: 0, textDecoration: 'none' }}>
        <Icon />
        {label}
      </a>
    )
  }

  return (
    <button className={cls} style={{ borderRadius: 0 }} onClick={() => onNavigate(page)}>
      <Icon />
      {label}
    </button>
  )
}

function ActivityIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  )
}
function ShieldIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  )
}
function FileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  )
}
function YamlIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="12" y2="17" />
    </svg>
  )
}
function FinraIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </svg>
  )
}
function SettingsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}
