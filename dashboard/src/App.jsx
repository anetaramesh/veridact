import { useState, useEffect, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import ActionFeed from './components/ActionFeed'
import AuditChain from './components/AuditChain'
import Settings from './components/Settings'
import RuleEditor from './components/RuleEditor'
import ViolationDetail from './components/ViolationDetail'
import ControlBar from './components/ControlBar'
import FinraStatus from './components/FinraStatus'

const SETTINGS_KEY = 'veridact_settings'
const DEFAULT_SETTINGS = {
  apiBase: 'http://localhost:8000',
  pollInterval: 3000,
  showAmounts: true,
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS
  } catch {
    return DEFAULT_SETTINGS
  }
}

export default function App() {
  const [page, setPage] = useState('feed')
  const [settings, setSettings] = useState(loadSettings)
  const [entries, setEntries] = useState([])
  const [selectedEntry, setSelectedEntry] = useState(null)
  const [apiOnline, setApiOnline] = useState(null)
  const [feedError, setFeedError] = useState(null)

  function handleSettingsChange(next) {
    setSettings(next)
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(next))
  }

  const { apiBase, pollInterval } = settings

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/health`)
      setApiOnline(res.ok)
    } catch {
      setApiOnline(false)
    }
  }, [apiBase])

  const fetchEntries = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/audit/recent?limit=50`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setEntries(await res.json())
      setFeedError(null)
    } catch {
      setFeedError('Unable to load audit feed. Check API connection.')
    }
  }, [apiBase])

  useEffect(() => {
    checkHealth()
    fetchEntries()
    const healthTimer = setInterval(checkHealth, 10000)
    const feedTimer = setInterval(fetchEntries, pollInterval)
    return () => {
      clearInterval(healthTimer)
      clearInterval(feedTimer)
    }
  }, [checkHealth, fetchEntries, pollInterval])

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar apiOnline={apiOnline} activePage={page} onNavigate={setPage} />

      <div className="flex flex-col flex-1 overflow-hidden">
        <main className="flex-1 overflow-y-auto p-6 pb-36">
          {page === 'feed' && (
            <ActionFeed
              entries={entries}
              error={feedError}
              onSelect={setSelectedEntry}
              selectedId={selectedEntry?.entry_id}
              showAmounts={settings.showAmounts}
            />
          )}
          {page === 'chain' && <AuditChain apiBase={apiBase} />}
          {page === 'settings' && (
            <Settings settings={settings} onChange={handleSettingsChange} />
          )}
          {page === 'rules' && (
            <RuleEditor apiBase={apiBase} />
          )}
          {page === 'finra' && (
            <FinraStatus apiBase={apiBase} />
          )}
        </main>

        {page === 'feed' && (
          <ControlBar apiBase={apiBase} onNewEntry={fetchEntries} />
        )}
      </div>

      {selectedEntry && (
        <ViolationDetail
          entry={selectedEntry}
          onClose={() => setSelectedEntry(null)}
        />
      )}
    </div>
  )
}
