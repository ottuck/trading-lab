import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import { BotPanel } from './components/BotPanel'
import { EventLog } from './components/EventLog'
import { PriceChart } from './components/PriceChart'
import { ago } from './format'

const TABS = { dashboard: '대시보드', chart: '차트', logs: '로그' } as const
type Tab = keyof typeof TABS

function useHashTab(): [Tab, (t: Tab) => void] {
  const read = () => (location.hash.slice(1) in TABS ? (location.hash.slice(1) as Tab) : 'dashboard')
  const [tab, setTab] = useState<Tab>(read)
  useEffect(() => {
    const onHash = () => setTab(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return [tab, (t) => (location.hash = t)]
}

function SystemStatus() {
  const { data, error } = useQuery({ queryKey: ['health'], queryFn: api.health })
  if (error) return <span className="dot down">API 연결 실패</span>
  if (!data) return null
  const w = data.worker
  return (
    <span className="status">
      <span className={`dot ${data.db === 'ok' ? 'up' : 'down'}`}>DB</span>
      <span className={`dot ${w?.alive ? 'up' : 'down'}`} title={w?.last_seen_at ?? ''}>
        Worker {w?.alive ? '' : `정지${w?.last_seen_at ? ` (${ago(w.last_seen_at)})` : ''}`}
      </span>
      <span className="muted small">v{data.version}</span>
    </span>
  )
}

export default function App() {
  const [tab, setTab] = useHashTab()
  const bots = useQuery({ queryKey: ['bots'], queryFn: api.bots })

  return (
    <>
      <header>
        <div className="brand">
          <strong>Quant Lab</strong>
          <span className="badge dry">DRY RUN</span>
        </div>
        <nav>
          {(Object.keys(TABS) as Tab[]).map((t) => (
            <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>
              {TABS[t]}
            </button>
          ))}
        </nav>
        <SystemStatus />
      </header>
      <main>
        {bots.error && <p className="alert">봇 정보를 불러오지 못했습니다: {bots.error.message}</p>}
        {bots.data && !bots.data.length && tab !== 'logs' && (
          <p className="muted">봇이 없습니다. CLI로 만드세요: `python -m quant_lab.cli bot create ...`</p>
        )}
        {tab === 'dashboard' && bots.data?.map((b) => <BotPanel key={b.id} bot={b} />)}
        {tab === 'chart' && bots.data?.map((b) => <PriceChart key={b.id} bot={b} />)}
        {tab === 'logs' && <EventLog />}
      </main>
    </>
  )
}
