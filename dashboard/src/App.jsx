import { useState, useEffect, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import ActionFeed from './components/ActionFeed'
import ViolationDetail from './components/ViolationDetail'
import ControlBar from './components/ControlBar'

const API_BASE = 'http://localhost:8000'

export default function App() {
  const [entries, setEntries] = useState([])
  const [selectedEntry, setSelectedEntry] = useState(null)
  const [apiOnline, setApiOnline] = useState(null)
  const [feedError, setFeedError] = useState(null)

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`)
      setApiOnline(res.ok)
    } catch {
      setApiOnline(false)
    }
  }, [])

  const fetchEntries = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/audit/recent?limit=50`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEntries(data)
      setFeedError(null)
    } catch (e) {
      setFeedError('Unable to load audit feed. Check API connection.')
    }
  }, [])

  useEffect(() => {
    checkHealth()
    fetchEntries()
    const healthTimer = setInterval(checkHealth, 10000)
    const feedTimer = setInterval(fetchEntries, 3000)
    return () => {
      clearInterval(healthTimer)
      clearInterval(feedTimer)
    }
  }, [checkHealth, fetchEntries])

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar apiOnline={apiOnline} />
      <div className="flex flex-col flex-1 overflow-hidden">
        <main className="flex-1 overflow-y-auto p-6 pb-36">
          <ActionFeed
            entries={entries}
            error={feedError}
            onSelect={setSelectedEntry}
            selectedId={selectedEntry?.entry_id}
          />
        </main>
        <ControlBar apiBase={API_BASE} onNewEntry={fetchEntries} />
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
