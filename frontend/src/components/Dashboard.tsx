import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, type ActivityItem, type Bot, type BotState, type CommandKind, type EquityPoint, type Order } from '../api'
import { ago, kstTime, money, percent, signedMoney, tone } from '../format'
import { leverageOf, useInstruments } from '../instruments'
import { sourceLabel } from '../source'
import { useStrategies } from '../strategies'
import { Term } from './Help'
import { PriceChart } from './PriceChart'
import { LeverageNotice } from './SymbolPicker'

const STATE: Record<BotState, { label: string; dot: string }> = {
  RUNNING: { label: '실행 중', dot: 'ok pulse' },
  PAUSED: { label: '잠시 멈춤', dot: 'warn' },
  STOPPED: { label: '멈춤', dot: '' },
  ERROR: { label: '문제 발생', dot: 'bad' },
}

const RANGES = [
  { key: '1W', label: '1주', days: 5 },
  { key: '1M', label: '1개월', days: 21 },
  { key: '3M', label: '3개월', days: 63 },
  { key: '1Y', label: '1년', days: 252 },
  { key: 'ALL', label: '전체', days: Infinity },
] as const
type Range = (typeof RANGES)[number]

const kstShort = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})
const kstDay = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' })
const kstHm = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false })

/** '2026-10-01' → '10월 1일', 올해가 아니면 '2025년 12월 1일' (미국 장 날짜라 시간대 변환 없이 그대로 읽는다). */
function md(date: string | null | undefined) {
  if (!date) return '—'
  const [y, m, d] = date.split('-')
  const year = Number(y) === new Date().getFullYear() ? '' : `${y}년 `
  return `${year}${Number(m)}월 ${Number(d)}일`
}

function currentEquity(bot: Bot): string | null {
  return bot.account.live_equity ?? bot.account.equity
}

function botReturn(bot: Bot): string | null {
  const a = bot.account
  return a.live_equity != null && Number(a.initial_cash)
    ? String(Number(a.live_equity) / Number(a.initial_cash) - 1)
    : a.total_return
}

function useEquity(botId: number) {
  return useQuery({ queryKey: ['equity', botId], queryFn: () => api.equity(botId) })
}

function useOrders(botId: number) {
  return useQuery({ queryKey: ['orders', botId], queryFn: () => api.orders(botId) })
}

/** 바깥을 누르거나 Esc를 누르면 닫히는 메뉴·서랍. */
function useDismiss(open: boolean, close: () => void, ref?: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    const onDown = (e: MouseEvent) => ref?.current && !ref.current.contains(e.target as Node) && close()
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open, close, ref])
}

/* ---------- 봇 제어: 주 동작 하나 + 나머지는 ⋯ 메뉴 ---------- */

type Action = { kind: CommandKind; label: string; danger?: boolean }
const RUN_ONCE: Action = { kind: 'RUN_ONCE', label: '지금 판단해 보기' }
const PAUSE: Action = { kind: 'PAUSE', label: '잠시 멈춤' }
const STOP: Action = { kind: 'STOP', label: '매매 중단', danger: true }

function actionsFor(state: BotState): { main: Action; primary: boolean; more: Action[] } {
  if (state === 'RUNNING') return { main: RUN_ONCE, primary: false, more: [PAUSE, STOP] }
  if (state === 'STOPPED') return { main: { kind: 'START', label: '매매 시작' }, primary: true, more: [RUN_ONCE] }
  return { main: { kind: 'START', label: '다시 시작' }, primary: true, more: [RUN_ONCE, STOP] }
}

function Controls({ bot, onSent }: { bot: Bot; onSent: (msg: string) => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(open, () => setOpen(false), ref)
  const mutation = useMutation({
    mutationFn: (kind: CommandKind) => api.command(bot.id, kind),
    onSuccess: () => {
      onSent('요청했어요. 15초 안에 반영돼요.')
      void qc.invalidateQueries({ queryKey: ['bots'] })
    },
    onError: (e) => onSent(`요청하지 못했어요: ${e.message}`),
  })
  const send = (a: Action) => {
    setOpen(false)
    if (a.kind === 'STOP' && !window.confirm('매매를 중단할까요? 예정된 거래는 그대로 남아요.')) return
    mutation.mutate(a.kind)
  }
  const { main, primary, more } = actionsFor(bot.state)
  return (
    <div className="hero-actions" ref={ref}>
      <button className={primary ? 'primary' : ''} disabled={mutation.isPending} onClick={() => send(main)}>
        {main.label}
      </button>
      <button className="more" aria-label="다른 동작" aria-expanded={open} onClick={() => setOpen(!open)}>
        ⋯
      </button>
      {open && (
        <div className="menu" role="menu">
          {more.map((a) => (
            <button key={a.kind} role="menuitem" className={a.danger ? 'danger' : ''} onClick={() => send(a)}>
              {a.label}
            </button>
          ))}
          <hr />
          <button role="menuitem" onClick={() => (location.hash = 'settings')}>
            설정 바꾸기
          </button>
        </div>
      )}
    </div>
  )
}

/* ---------- 자산 차트 (마우스를 올리면 큰 숫자가 그날 값으로 바뀐다) ---------- */

type Hover = { value: number; date: string } | null

function useSize() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setSize({ width: e.contentRect.width, height: e.contentRect.height }))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

function EquityChart({
  points,
  base,
  fills,
  rising,
  onHover,
}: {
  points: EquityPoint[]
  base: number
  fills: Order[]
  rising: boolean
  onHover: (h: Hover) => void
}) {
  const [ref, { width, height: H }] = useSize()
  const [idx, setIdx] = useState<number | null>(null)
  const ys = points.map((p) => Number(p.equity))
  const min = Math.min(base, ...ys)
  const span = Math.max(base, ...ys) - min || 1
  const pad = 8
  const x = (i: number) => (points.length > 1 ? (i / (points.length - 1)) * width : 0)
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - pad * 2)
  const color = rising ? 'var(--rise)' : 'var(--fall)'
  const d = ys.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const byDate = new Map(points.map((p, i) => [p.date, i]))
  const marks = fills.flatMap((o) => {
    const i = o.fill_date ? byDate.get(o.fill_date) : undefined
    return i == null ? [] : [{ i, o }]
  })

  const pick = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    const i = Math.round(Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * (points.length - 1))
    setIdx(i)
    onHover({ value: ys[i], date: points[i].date })
  }
  const leave = () => {
    setIdx(null)
    onHover(null)
  }
  const fillAt = idx == null ? undefined : marks.find((m) => m.i === idx)?.o

  return (
    <div
      ref={ref}
      className="eq-chart"
      onPointerMove={(e) => pick(e.clientX)}
      onPointerDown={(e) => pick(e.clientX)}
      onPointerLeave={leave}
      aria-label="모의 자산 그래프"
      role="img"
    >
      {width > 0 && (
        <svg viewBox={`0 0 ${width} ${H}`} preserveAspectRatio="none">
          <line x1={0} x2={width} y1={y(base)} y2={y(base)} stroke="var(--faint)" strokeDasharray="2 4" />
          <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {marks.map(({ i, o }) => (
            <circle
              key={o.id}
              cx={x(i)}
              cy={y(ys[i])}
              r={4.5}
              fill={o.side === 'BUY' ? 'var(--rise)' : 'var(--fall)'}
              stroke="var(--bg)"
              strokeWidth={2}
            />
          ))}
          {idx != null && (
            <g>
              <line x1={x(idx)} x2={x(idx)} y1={0} y2={H} stroke="var(--border-strong)" />
              <circle cx={x(idx)} cy={y(ys[idx])} r={5} fill={color} stroke="var(--bg)" strokeWidth={2} />
            </g>
          )}
        </svg>
      )}
      {idx != null && (
        <div className="date" style={{ left: Math.min(Math.max(x(idx), 64), width - 64) }}>
          {md(points[idx].date)}
          {points[idx].live && ' · 지금'}
          {fillAt && ` · ${fillAt.side === 'BUY' ? '샀어요' : '팔았어요'} ${fillAt.qty}주`}
        </div>
      )}
    </div>
  )
}

function Overview({ bot }: { bot: Bot }) {
  const { byName } = useStrategies()
  const lev = leverageOf(useInstruments().data, bot.symbol)
  const equity = useEquity(bot.id)
  const orders = useOrders(bot.id)
  const [range, setRange] = useState<Range>(RANGES[2])
  const [hover, setHover] = useState<Hover>(null)
  const [sent, setSent] = useState<string | null>(null)

  const all = equity.data ?? []
  const points = range.days === Infinity ? all : all.slice(-(range.days + 1))
  const base = range.days === Infinity || points.length < 2 ? Number(bot.account.initial_cash) : Number(points[0].equity)
  const now = Number(currentEquity(bot) ?? bot.account.initial_cash)
  const value = hover?.value ?? now
  const diff = value - base
  const rising = (points.length ? Number(points.at(-1)!.equity) : now) >= base
  const when = hover ? md(hover.date) : range.days === Infinity ? '시작 이후' : `지난 ${range.label}`
  const a = bot.account
  const state = STATE[bot.state]

  return (
    <>
      <div className="hero-head">
        <div>
          <div className="bot-line">
            <span className="name">
              {bot.name}
              {lev > 1 && <span className="lev">{lev}×</span>}
            </span>
            <span className={`dot ${state.dot}`}>{state.label}</span>
            <span>· {byName[bot.strategy]?.nickname ?? bot.strategy}</span>
          </div>
          <div className="hero-value">{money(String(value))}</div>
          <div className="hero-delta">
            <span className={tone(String(diff))}>
              {signedMoney(String(diff))} ({percent(base ? String(diff / base) : null)})
            </span>
            <span className="when">{when}</span>
          </div>
        </div>
        <Controls bot={bot} onSent={setSent} />
      </div>
      {sent && <div className="hero-note">{sent}</div>}
      {bot.state_reason && (
        <div className={bot.state === 'ERROR' ? 'alert' : 'notice'}>
          {bot.state === 'PAUSED' ? '잠시 멈춰 있어요. [다시 시작]을 누르면 바로 판단해요.' : bot.state_reason}
        </div>
      )}

      {points.length > 1 ? (
        <EquityChart
          points={points}
          base={base}
          fills={(orders.data ?? []).filter((o) => o.status === 'FILLED')}
          rising={rising}
          onHover={setHover}
        />
      ) : (
        <div className="eq-chart">
          <div className="eq-empty">{equity.isLoading ? '불러오는 중…' : '판단이 쌓이면 여기에 자산 그래프가 그려져요.'}</div>
        </div>
      )}
      <div className="eq-foot">
        <div className={`ranges ${rising ? 'up' : 'down'}`} role="group" aria-label="기간">
          {RANGES.map((r) => (
            <button key={r.key} className={r.key === range.key ? 'active' : ''} aria-pressed={r.key === range.key} onClick={() => setRange(r)}>
              {r.label}
            </button>
          ))}
        </div>
        <span className="paper">
          <Term k="모의 투자" /> · {a.live_at ? `실시간 ${ago(a.live_at)}` : `${md(a.last_close_date)} 장 마감 기준`}
        </span>
      </div>
      {lev > 1 && <LeverageNotice symbol={bot.symbol} factor={lev} />}
      <Facts bot={bot} />
    </>
  )
}

function Facts({ bot }: { bot: Bot }) {
  const a = bot.account
  const run = bot.last_run
  const unrealized = a.live_unrealized_pnl ?? a.unrealized_pnl
  const runText = !run ? '—' : run.status === 'OK' ? '정상' : run.status === 'ERROR' ? '실패' : run.status === 'RUNNING' ? '판단 중' : '미룸'
  const runTone = !run ? '' : run.status === 'OK' ? 'ok' : run.status === 'ERROR' ? 'bad' : 'warn'
  return (
    <div className="facts">
      <div className="fact">
        <div className="label">다음 판단</div>
        <div className="value">
          {bot.state === 'RUNNING' && bot.next_evaluation_at ? kstShort.format(new Date(bot.next_evaluation_at)) : '멈춰 있어요'}
        </div>
        <div className="sub">{bot.state === 'RUNNING' ? ago(bot.next_evaluation_at) : '시작하면 바로 판단해요'}</div>
      </div>
      <div className="fact">
        <div className="label">마지막 판단</div>
        <div className={`value ${runTone}`}>{runText}</div>
        <div className="sub" title={kstTime(run?.started_at)}>
          {run ? ago(run.started_at) : '아직 없어요'}
        </div>
      </div>
      <div className="fact">
        <div className="label">
          <Term k="평가 손익" />
        </div>
        <div className={`value ${tone(unrealized)}`}>{a.qty ? signedMoney(unrealized) : '—'}</div>
        <div className="sub">{a.qty ? '팔기 전 손익' : '들고 있는 주식 없음'}</div>
      </div>
      <div className="fact">
        <div className="label">
          <Term k="확정 손익" />
        </div>
        <div className={`value ${tone(a.realized_pnl)}`}>{signedMoney(a.realized_pnl)}</div>
        <div className="sub">판 주식에서</div>
      </div>
    </div>
  )
}

/* ---------- 세부 ---------- */

function Decision({ bot }: { bot: Bot }) {
  const d = bot.last_decision
  const [more, setMore] = useState(false)
  const mark = d?.action === 'BUY' ? 'rise' : d?.action === 'SELL' ? 'fall' : ''
  const head = d?.action === 'BUY' ? '매수 신호' : d?.action === 'SELL' ? '매도 신호' : d?.holding ? '그대로 들고 있기' : '기다리기'
  const pending = bot.pending_order
  return (
    <section className="block">
      <div className="block-head">
        <h2>
          <Term k="오늘의 판단" />
        </h2>
        {d && <span className="sub">{md(d.session_date)} 장 마감 기준</span>}
        {d && (
          <button className="link" aria-expanded={more} onClick={() => setMore(!more)}>
            {more ? '숨기기' : '숫자 보기'}
          </button>
        )}
      </div>
      {d ? (
        <>
          <div className="decision-head">
            <span className={`mark ${mark}`} />
            {d.plain_action || head}
          </div>
          {d.plain_reason && <p className="decision-why">{d.plain_reason}</p>}
          {pending && (
            <p className="decision-why">
              다음 장이 열리면 {pending.side === 'BUY' ? '사요' : '팔아요'}. 지금은 예정만 잡혀 있어요.
            </p>
          )}
          {d.blocked && <div className="alert">사지 못했어요: {d.blocked}</div>}
          {more && (
            <div className="decision-nums">
              {d.reason} ·{' '}
              {Object.entries(d.indicators)
                .map(([k, v]) => `${k} ${Number(v).toFixed(2)}`)
                .join(' · ')}
            </div>
          )}
        </>
      ) : (
        <p className="decision-why">아직 판단이 없어요. [매매 시작]을 누르면 가장 최근 가격으로 바로 판단해요.</p>
      )}
    </section>
  )
}

function Holding({ bot }: { bot: Bot }) {
  const a = bot.account
  const price = a.live_price ?? a.last_close
  const value = a.qty && price ? String(a.qty * Number(price)) : a.market_value
  const pnl = a.live_unrealized_pnl ?? a.unrealized_pnl
  const ret = a.qty && Number(a.avg_cost) ? String(Number(price) / Number(a.avg_cost) - 1) : null
  return (
    <section className="block">
      <div className="block-head">
        <h2>들고 있는 주식</h2>
        <span className="sub">남은 현금 {money(a.cash)}</span>
      </div>
      {a.qty ? (
        <div className="lines">
          <div className="line">
            <div>
              <div className="title">{bot.symbol}</div>
              <div className="muted small tnum">
                {a.qty}주 · 산 가격 {money(a.avg_cost)} · 지금 {money(price)}
                {a.live_change != null && <span className={tone(a.live_change)}> ({percent(a.live_change)})</span>}
              </div>
            </div>
            <div className="r">
              <div className="value md">{money(value)}</div>
              <div className={`small ${tone(pnl)}`} style={{ fontWeight: 500 }}>
                {signedMoney(pnl)} ({percent(ret)})
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="line-empty">들고 있는 주식이 없어요. 현금으로 기다리는 중이에요.</div>
      )}
    </section>
  )
}

const ORDER_STATUS: Record<Order['status'], string> = { PENDING: '다음 장에 예정', FILLED: '', UNFILLED: '체결 안 됨' }

function Trades({ bot, onOpenLog }: { bot: Bot; onOpenLog: () => void }) {
  const { data } = useOrders(bot.id)
  const rows = (data ?? []).slice(0, 5)
  return (
    <section className="block">
      <div className="block-head">
        <h2>거래 내역</h2>
        <button className="link" onClick={onOpenLog}>
          전체 기록 보기 →
        </button>
      </div>
      {rows.length ? (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th>날짜</th>
                <th>내용</th>
                <th className="qty">수량</th>
                <th className="num">한 주 가격</th>
                <th className="num">확정 손익</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => {
                const buy = o.side === 'BUY'
                const status = ORDER_STATUS[o.status]
                return (
                  <tr key={o.id}>
                    <td className="d">{md(o.fill_date ?? o.signal_date)}</td>
                    <td>
                      <span className={`side-tag ${buy ? 'rise' : 'fall'}`}>
                        {buy ? '샀어요' : '팔았어요'}
                        {status && <span className="faint small">{status}</span>}
                      </span>
                    </td>
                    <td className="qty">{o.qty ? `${o.qty}주` : '—'}</td>
                    <td className="num">{money(o.price)}</td>
                    <td className={`num ${tone(o.realized_pnl)}`}>{o.realized_pnl != null ? signedMoney(o.realized_pnl) : <span className="faint">—</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="line-empty">아직 거래가 없어요.</div>
      )}
    </section>
  )
}

function Strategy({ bot }: { bot: Bot }) {
  const info = useStrategies().byName[bot.strategy]
  return (
    <section className="block">
      <div className="block-head">
        <h2>전략</h2>
        <span className="sub">{info?.nickname ?? bot.strategy}</span>
      </div>
      {info && <p className="decision-why" style={{ marginTop: 0 }}>{info.summary}</p>}
      <div className="strategy-meta">
        {info && `위험 ${info.risk} · 거래 ${info.trades} · `}가격 정보 {md(bot.data_latest_date)} 장 마감까지
        {bot.data_fetched_at && `, ${ago(bot.data_fetched_at)} 업데이트`} · 출처 {sourceLabel(bot.data_source)}
      </div>
    </section>
  )
}

/* ---------- 기록 서랍 ---------- */

function pipOf(a: ActivityItem) {
  if (a.level === 'ERROR') return 'bad'
  if (a.level === 'WARN') return 'warn'
  if (a.title.includes('샀')) return 'rise'
  if (a.title.includes('팔았')) return 'fall'
  return ''
}

function LogDrawer({ bot, onClose }: { bot: Bot; onClose: () => void }) {
  const { data, isLoading } = useQuery({ queryKey: ['activity', bot.id, 'all'], queryFn: () => api.activity(bot.id, undefined, 60) })
  useDismiss(true, onClose)
  let prev = ''
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label={`${bot.name} 기록`}>
        <div className="drawer-head">
          <h2>{bot.name} 기록</h2>
          <button className="ghost" onClick={onClose}>
            닫기
          </button>
        </div>
        <div className="drawer-body">
          {isLoading && <div className="empty">불러오는 중…</div>}
          {data && !data.length && <div className="empty">아직 기록이 없어요.</div>}
          {data?.map((a) => {
            const day = kstDay.format(new Date(a.at))
            const header = day !== prev && <div className="log-day">{day}</div>
            prev = day
            return (
              <div key={a.id}>
                {header}
                <div className="log-item">
                  <span className={`pip ${pipOf(a)}`} />
                  <div>
                    <div className="title">{a.title}</div>
                    {a.body && <div className="body">{a.body}</div>}
                  </div>
                  <time dateTime={a.at}>{kstHm.format(new Date(a.at))}</time>
                </div>
              </div>
            )
          })}
        </div>
      </aside>
    </>
  )
}

/* ---------- 오른쪽 봇 목록 ---------- */

function Spark({ values, rising }: { values: number[]; rising: boolean }) {
  if (values.length < 2) return <svg aria-hidden="true" />
  const min = Math.min(...values)
  const span = Math.max(...values) - min || 1
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * 64).toFixed(1)},${(25 - ((v - min) / span) * 22).toFixed(1)}`).join(' ')
  return (
    <svg viewBox="0 0 64 28" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={rising ? 'var(--rise)' : 'var(--fall)'} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function BotItem({ bot, active, onPick }: { bot: Bot; active: boolean; onPick: () => void }) {
  const lev = leverageOf(useInstruments().data, bot.symbol)
  const values = (useEquity(bot.id).data ?? []).slice(-63).map((p) => Number(p.equity))
  const ret = botReturn(bot)
  const state = STATE[bot.state]
  return (
    <button className={`bot-item ${active ? 'active' : ''}`} aria-current={active} onClick={onPick}>
      <div>
        <div className="sym">
          {bot.name}
          {lev > 1 && <span className="lev">{lev}×</span>}
        </div>
        <span className={`dot ${state.dot.replace(' pulse', '')}`}>{state.label}</span>
      </div>
      <Spark values={values} rising={values.length < 2 || values.at(-1)! >= values[0]} />
      <div className={`ret ${tone(ret)}`}>{percent(ret)}</div>
    </button>
  )
}

const SELECTED_KEY = 'quant-lab:bot'

function readSelected(): number | null {
  try {
    return Number(localStorage.getItem(SELECTED_KEY)) || null
  } catch {
    return null
  }
}

/** 홈: 왼쪽에 고른 봇의 자산·판단·거래, 오른쪽에 봇 목록. 고른 봇은 이 브라우저에 기억한다. */
export function Home({ bots }: { bots: Bot[] }) {
  const [selected, setSelected] = useState(readSelected)
  const [logOpen, setLogOpen] = useState(false)
  const bot = bots.find((b) => b.id === selected) ?? bots[0]
  const pick = (id: number) => {
    setSelected(id)
    try {
      localStorage.setItem(SELECTED_KEY, String(id))
    } catch {
      // 저장이 막힌 브라우저에서는 이번 방문 동안만 기억한다.
    }
  }
  return (
    <div className="home">
      <div className="home-main" key={bot.id}>
        <Overview bot={bot} />
        <Decision bot={bot} />
        <Holding bot={bot} />
        <PriceChart bot={bot} />
        <Trades bot={bot} onOpenLog={() => setLogOpen(true)} />
        <Strategy bot={bot} />
      </div>
      <aside className="home-side">
        <div className="bot-list">
          <div className="bot-list-head">
            내 봇
            <button className="link" onClick={() => (location.hash = 'settings')}>
              + 새 봇
            </button>
          </div>
          {bots.map((b) => (
            <BotItem key={b.id} bot={b} active={b.id === bot.id} onPick={() => pick(b.id)} />
          ))}
        </div>
        <div className="side-note">10초마다 새로 불러와요.</div>
      </aside>
      {logOpen && <LogDrawer bot={bot} onClose={() => setLogOpen(false)} />}
    </div>
  )
}
