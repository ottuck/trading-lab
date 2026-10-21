import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import { BacktestView } from './components/BacktestView'
import { Brand, ThemeMenu } from './components/Brand'
import { CurrencyToggle } from './components/Currency'
import { Home, MeHome } from './components/Dashboard'
import { HelpButton } from './components/Help'
import { JournalView } from './components/Journal'
import { MeView } from './components/MeView'
import { SettingsView } from './components/SettingsView'
import { LiveApprovals } from './components/Live'
import { ago } from './format'
import { useDemo } from './demo'
import { useCurrency, useFxSync } from './currency'

const TABS = {
  dashboard: '홈',
  backtest: '시험해 보기',
  settings: '설정',
} as const
type Tab = keyof typeof TABS

// 탭 밖의 화면: 나 카피하기 (#me), 봇 하나 자세히 보기 (#bot/3, 홈 탭), 매매일지 (#journal/3, 홈 탭)
type Page = Tab | 'me' | 'bot' | 'journal'

function useHashTab(): [Page, (t: Tab) => void] {
  const read = (): Page => {
    const h = location.hash.slice(1)
    if (h === 'bot' || h.startsWith('bot/')) return 'bot'
    if (h.startsWith('journal/')) return 'journal'
    return h === 'me' || h in TABS ? (h as Page) : 'dashboard'
  }
  const [tab, setTab] = useState<Page>(read)
  useEffect(() => {
    const onHash = () => {
      setTab(read())
      // 다른 화면(다른 봇 포함)으로 넘어가면 맨 위부터 보여준다
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return [tab, (t) => (location.hash = t)]
}

function SystemStatus() {
  const { data, error } = useQuery({ queryKey: ['health'], queryFn: api.health })
  if (data?.demo)
    return (
      <span className="dot demo" title="예시 데이터로 보는 데모">
        <span className="status-text">데모</span>
      </span>
    )
  if (error)
    return (
      <span className="dot bad">
        <span className="status-text">연결 안 됨</span>
      </span>
    )
  if (!data) return null
  const w = data.worker
  const ok = data.db === 'ok' && w?.alive
  // 잘 돌 때는 보이지 않는다. 뒤에서 도는 Worker가 멈췄을 때만 알린다 (판단·주문이 조용히 멈추므로)
  if (ok) return null
  return (
    <span className={`dot ${ok ? 'ok' : 'bad'}`} title={`DB ${data.db} · Worker ${w?.alive ? '정상' : '정지'} · v${data.version}`}>
      <span className="status-text">{ok ? '정상 작동' : `프로그램 멈춤${w?.last_seen_at ? ` (${ago(w.last_seen_at)})` : ''}`}</span>
    </span>
  )
}

/** Worker가 멈췄거나 서버에 닿지 않을 때 화면 위에 한 줄로 (폰에서는 위 점의 글자가 숨으므로). */
function WorkerAlert() {
  const { data, error } = useQuery({ queryKey: ['health'], queryFn: api.health })
  if (data?.demo) return null
  if (error) return <div className="alert-bar">서버에 연결되지 않아요. 잠시 뒤 다시 확인해요.</div>
  if (!data || (data.db === 'ok' && data.worker?.alive)) return null
  const since = data.worker?.last_seen_at ? ` (${ago(data.worker.last_seen_at)})` : ''
  return (
    <div className="alert-bar">
      <b>프로그램이 멈췄어요{since}.</b> 다시 켜질 때까지 판단과 주문이 멈춰 있어요. 켜지면 밀린 판단부터 바로 해요.
    </div>
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
  const demo = useDemo()
  useFxSync()
  useCurrency() // $ / ₩를 바꾸면 화면 전체를 다시 그린다 (금액은 format.ts가 바꿔 보여준다)

  return (
    <>
      <div className="topbar-wrap">
        <header className="topbar">
          <Brand />
          <nav className="tabs">
            {(Object.keys(TABS) as Tab[]).map((t) => {
              // 봇 자세히 보기(#bot)와 매매일지(#journal)는 홈 탭 안의 화면이다.
              const on = t === tab || (t === 'dashboard' && (tab === 'bot' || tab === 'journal'))
              return (
              <button
                key={t}
                className={`tab ${on ? 'active' : ''}`}
                aria-current={on ? 'page' : undefined}
                onClick={() => setTab(t)}
              >
                {TABS[t]}
              </button>
              )
            })}
          </nav>
          <div className="topbar-right">
            <NewYorkClock />
            <SystemStatus />
            <HelpButton />
            <CurrencyToggle />
            <ThemeMenu />
          </div>
        </header>
      </div>
      {demo && (
        <div className="demo-bar">
          <b>예시 데이터로 보는 데모예요.</b> 가격은 실제가 아니고, 봇을 만들거나 설정을 바꿀 수는 없어요(설정은 보기만 돼요). 나 카피하기와 시험해 보기는
          마음껏 해 보세요. <b>나 카피 봇</b>은 내 투자 습관을 복사해서 매일 모의 투자를 대신 해 보는 봇이에요.
        </div>
      )}
      <WorkerAlert />
      <main>
        <LiveApprovals />
        {bots.error && <div className="alert">봇 정보를 불러오지 못했습니다: {bots.error.message}</div>}
        {tab === 'dashboard' && bots.data && <MeHome bots={bots.data} />}
        {tab === 'bot' && !!bots.data?.length && <Home bots={bots.data} />}
        {tab === 'journal' && bots.data && <JournalView bots={bots.data} />}
        {tab === 'backtest' && <BacktestView />}
        {tab === 'me' && bots.data && <MeView bots={bots.data} />}
        {tab === 'settings' && bots.data && <SettingsView bots={bots.data} />}
      </main>
    </>
  )
}
