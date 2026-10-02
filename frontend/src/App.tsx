import { useIsFetching, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import { BacktestView } from './components/BacktestView'
import { Brand, ThemeMenu } from './components/Brand'
import { Dashboard } from './components/Dashboard'
import { HelpButton } from './components/Help'
import { SettingsView } from './components/SettingsView'
import { ago } from './format'

const TABS = {
  dashboard: '🏠 홈',
  backtest: '🧪 시험해 보기',
  settings: '⚙️ 설정',
} as const
type Tab = keyof typeof TABS
const REFRESH_MS = 10_000

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
  if (error) return <span className="dot bad">API 연결 실패</span>
  if (!data) return null
  const w = data.worker
  return (
    <>
      <span
        className={`dot ${data.db === 'ok' && w?.alive ? 'ok' : 'bad'}`}
        title={`DB ${data.db} · Worker ${w?.alive ? '정상' : '정지'} · v${data.version}`}
      >
        {data.db === 'ok' && w?.alive ? '정상 작동' : `프로그램 멈춤${w?.last_seen_at ? ` (${ago(w.last_seen_at)})` : ''}`}
      </span>
    </>
  )
}

function RefreshControls() {
  const qc = useQueryClient()
  const fetching = useIsFetching()
  const [auto, setAuto] = useState(true)
  useEffect(() => {
    qc.setDefaultOptions({ queries: { ...qc.getDefaultOptions().queries, refetchInterval: auto ? REFRESH_MS : false } })
    // 기본값은 새로 만드는 쿼리에만 적용되므로 지금 화면의 쿼리도 갱신한다.
    qc.getQueryCache()
      .getAll()
      .forEach((q) => q.observers.forEach((o) => o.setOptions({ ...o.options, refetchInterval: auto ? REFRESH_MS : false })))
  }, [auto, qc])
  return (
    <>
      <label className="toggle">
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
        자동 새로고침
      </label>
      <button className="primary" disabled={fetching > 0} onClick={() => void qc.invalidateQueries()}>
        새로고침
      </button>
    </>
  )
}

export default function App() {
  const [tab, setTab] = useHashTab()
  const bots = useQuery({ queryKey: ['bots'], queryFn: api.bots })

  return (
    <>
      <header className="topbar">
        <Brand />
        <div className="topbar-right">
          <SystemStatus />
          <RefreshControls />
          <HelpButton />
          <ThemeMenu />
        </div>
      </header>
      <nav className="tabs">
        {(Object.keys(TABS) as Tab[]).map((t) => (
          <button key={t} className={`tab ${t === tab ? 'active' : ''}`} onClick={() => setTab(t)}>
            {TABS[t]}
          </button>
        ))}
      </nav>
      <main>
        {bots.error && <div className="alert">봇 정보를 불러오지 못했습니다: {bots.error.message}</div>}
        {tab === 'dashboard' && bots.data && !bots.data.length && (
          <section className="card muted">아직 봇이 없어요. 설정 탭에서 만들어 주세요.</section>
        )}
        {tab === 'dashboard' && bots.data?.map((b) => <Dashboard key={b.id} bot={b} />)}
        {tab === 'backtest' && <BacktestView />}
        {tab === 'settings' && bots.data && <SettingsView bots={bots.data} />}
      </main>
    </>
  )
}
