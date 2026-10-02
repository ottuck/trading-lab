import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import { BacktestView } from './components/BacktestView'
import { Brand, ThemeMenu } from './components/Brand'
import { Home } from './components/Dashboard'
import { HelpButton } from './components/Help'
import { MeView } from './components/MeView'
import { SettingsView } from './components/SettingsView'
import { ago } from './format'

const TABS = {
  dashboard: '홈',
  backtest: '시험해 보기',
  settings: '설정',
} as const
type Tab = keyof typeof TABS

// 탭 밖의 화면: 질문으로 나 만들기 (#me)
type Page = Tab | 'me'

function useHashTab(): [Page, (t: Tab) => void] {
  const read = (): Page => {
    const h = location.hash.slice(1)
    return h === 'me' || h in TABS ? (h as Page) : 'dashboard'
  }
  const [tab, setTab] = useState<Page>(read)
  useEffect(() => {
    const onHash = () => setTab(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return [tab, (t) => (location.hash = t)]
}

function SystemStatus() {
  const { data, error } = useQuery({ queryKey: ['health'], queryFn: api.health })
  if (error)
    return (
      <span className="dot bad">
        <span className="status-text">연결 안 됨</span>
      </span>
    )
  if (!data) return null
  const w = data.worker
  const ok = data.db === 'ok' && w?.alive
  return (
    <span className={`dot ${ok ? 'ok' : 'bad'}`} title={`DB ${data.db} · Worker ${w?.alive ? '정상' : '정지'} · v${data.version}`}>
      <span className="status-text">{ok ? '정상 작동' : `프로그램 멈춤${w?.last_seen_at ? ` (${ago(w.last_seen_at)})` : ''}`}</span>
    </span>
  )
}

const nyClock = new Intl.DateTimeFormat('ko-KR', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false })

/** 미국 장 기준으로 판단하므로 뉴욕 시각만 작게 보여준다. 화면의 다른 시각은 모두 한국 시각이다. */
function NewYorkClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(id)
  }, [])
  return <span className="clock tnum">뉴욕 {nyClock.format(now)}</span>
}

export default function App() {
  const [tab, setTab] = useHashTab()
  const bots = useQuery({ queryKey: ['bots'], queryFn: api.bots })

  return (
    <>
      <div className="topbar-wrap">
        <header className="topbar">
          <Brand />
          <nav className="tabs">
            {(Object.keys(TABS) as Tab[]).map((t) => (
              <button
                key={t}
                className={`tab ${t === tab ? 'active' : ''}`}
                aria-current={t === tab ? 'page' : undefined}
                onClick={() => setTab(t)}
              >
                {TABS[t]}
              </button>
            ))}
          </nav>
          <div className="topbar-right">
            <NewYorkClock />
            <SystemStatus />
            <HelpButton />
            <ThemeMenu />
          </div>
        </header>
      </div>
      <main>
        {bots.error && <div className="alert">봇 정보를 불러오지 못했습니다: {bots.error.message}</div>}
        {tab === 'dashboard' && bots.data && !bots.data.length && (
          <section className="card me-empty">
            <div>
              <b>나처럼 투자하는 봇을 만들어 볼까요?</b>
              <p className="muted">질문 몇 개에 답하면 내 투자 습관을 복사한 봇이 만들어져요.</p>
            </div>
            <button className="primary" onClick={() => (location.hash = 'me')}>
              질문으로 나 만들기
            </button>
          </section>
        )}
        {tab === 'dashboard' && !!bots.data?.length && <Home bots={bots.data} />}
        {tab === 'backtest' && <BacktestView />}
        {tab === 'me' && <MeView />}
        {tab === 'settings' && bots.data && <SettingsView bots={bots.data} />}
      </main>
    </>
  )
}
