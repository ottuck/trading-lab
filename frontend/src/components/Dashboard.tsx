import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useRef, useState } from 'react'
import {
  api,
  type ActivityItem,
  type Bot,
  type BotState,
  type CommandKind,
  type Decision as DecisionT,
  type EquityPoint,
  type Order,
} from '../api'
import { ago, isPast, kstTime, money, percent, shares, signedMoney, tone } from '../format'
import { leverageOf, useInstruments } from '../instruments'
import { sourceLabel } from '../source'
import { useStrategies } from '../strategies'
import { Term } from './Help'
import { selectBot, startNewBot, useSelectedBot } from '../selectedBot'
import { PriceChart } from './PriceChart'
import { useDismiss } from '../useDismiss'
import { activeOf, basketLabel } from '../basket'
import { LeverageNotice } from './SymbolPicker'

const STATE: Record<BotState, { label: string; dot: string }> = {
  RUNNING: { label: '실행 중', dot: 'ok pulse' },
  PAUSED: { label: '멈춤', dot: 'warn' },
  STOPPED: { label: '멈춤', dot: 'warn' },
  ERROR: { label: '문제 발생', dot: 'bad' },
}

const RANGES = [
  { key: '1W', label: '1주', days: 5 },
  { key: '1M', label: '1개월', days: 21 },
  { key: '3M', label: '3개월', days: 63 },
  { key: '1Y', label: '1년', days: 252 },
  { key: 'ALL', label: '전체', days: Infinity },
] as const

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

/** 넣은 돈 대비 수익률 (실시간 가격이 있으면 그것으로). */
function botReturn(bot: Bot): string | null {
  const a = bot.account
  return a.live_equity != null && Number(a.contributed)
    ? String(Number(a.live_equity) / Number(a.contributed) - 1)
    : a.total_return
}

function useEquity(botId: number) {
  return useQuery({ queryKey: ['equity', botId], queryFn: () => api.equity(botId) })
}

function useOrders(botId: number) {
  return useQuery({ queryKey: ['orders', botId], queryFn: () => api.orders(botId) })
}

/* ---------- 봇 제어: 멈추기·시작 하나 + 설정 ---------- */

// 일반 사용자에게는 "멈추기 / 시작" 두 가지만 보여준다.
// 판단은 하루 한 번 자동으로 하므로 "지금 판단해 보기"(RUN_ONCE)와 "중단"(STOP)은 화면에서 뺐다 (API·CLI에는 남김).
type Action = { kind: CommandKind; label: string }

function actionFor(state: BotState): { main: Action; primary: boolean } {
  if (state === 'RUNNING') return { main: { kind: 'PAUSE', label: '멈추기' }, primary: false }
  if (state === 'STOPPED') return { main: { kind: 'START', label: '매매 시작' }, primary: true }
  return { main: { kind: 'START', label: '다시 시작' }, primary: true }
}

function Controls({ bot, onSent }: { bot: Bot; onSent: (msg: string) => void }) {
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: (kind: CommandKind) => api.command(bot.id, kind),
    onSuccess: () => {
      onSent('요청했어요. 15초 안에 반영돼요.')
      void qc.invalidateQueries({ queryKey: ['bots'] })
    },
    onError: (e) => onSent(`요청하지 못했어요: ${e.message}`),
  })
  const send = (a: Action) => {
    if (a.kind === 'PAUSE') {
      const pending = bot.pending_order
        ? `

예약된 ${bot.pending_order.side === 'BUY' ? '매수' : '매도'}는 다시 시작할 때 원래 날짜의 가격으로 처리돼요.`
        : ''
      const ok = window.confirm(
        `${bot.name}을(를) 멈출까요?
멈춘 동안에는 새로 판단하지 않아요. 다시 시작하면 그날 판단부터 이어가요.${pending}`,
      )
      if (!ok) return
    }
    mutation.mutate(a.kind)
  }
  const { main, primary } = actionFor(bot.state)
  return (
    <div className="hero-actions">
      <button className={primary ? 'primary' : ''} disabled={mutation.isPending} onClick={() => send(main)}>
        {main.label}
      </button>
      <button className="ghost" onClick={() => (location.hash = 'settings')}>
        설정
      </button>
    </div>
  )
}

/* ---------- 자산 차트 (마우스를 올리면 큰 숫자가 그날 값으로 바뀐다) ---------- */

/** 한 시점의 자산(eq), 넣은 돈(c), 같은 돈으로 그냥 들고 있었다면(b). */
type Snap = { eq: number; c: number; b: number }

const snap = (p: EquityPoint): Snap => ({ eq: Number(p.equity), c: Number(p.contributed), b: Number(p.benchmark) })

type Gain = { gain: number; base: number }

/** 기간 손익. 그사이 넣은 돈(정기 입금)은 수익이 아니므로 뺀다. "전체"는 넣은 돈 합계와 비교한다. */
function gainOf(startValue: number, endValue: number, start: Snap, end: Snap, whole: boolean): Gain {
  if (whole) return { gain: endValue - end.c, base: end.c }
  const added = end.c - start.c
  return { gain: endValue - startValue - added, base: startValue + added }
}

const ratio = (g: Gain) => (g.base ? String(g.gain / g.base) : null)

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

/** SVG 선 경로. step이면 계단(입금처럼 하루에 한 번 바뀌는 값). */
function path(values: number[], x: (i: number) => number, y: (v: number) => number, step = false) {
  return values
    .map((v, i) => {
      if (!i) return 'M' + x(i).toFixed(1) + ',' + y(v).toFixed(1)
      return step ? 'H' + x(i).toFixed(1) + 'V' + y(v).toFixed(1) : 'L' + x(i).toFixed(1) + ',' + y(v).toFixed(1)
    })
    .join('')
}

function EquityChart({
  points,
  fills,
  rising,
  onHover,
}: {
  points: EquityPoint[]
  fills: Order[]
  rising: boolean
  onHover: (i: number | null) => void
}) {
  const [ref, { width, height: H }] = useSize()
  const [idx, setIdx] = useState<number | null>(null)
  const s = points.map(snap)
  const ys = s.map((p) => p.eq)
  const every = s.flatMap((p) => [p.eq, p.c, p.b])
  const min = Math.min(...every)
  const span = Math.max(...every) - min || 1
  const pad = 8
  const x = (i: number) => (points.length > 1 ? (i / (points.length - 1)) * width : 0)
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - pad * 2)
  const color = rising ? 'var(--rise)' : 'var(--fall)'
  const byDate = new Map(points.map((p, i) => [p.date, i]))
  const marks = fills.flatMap((o) => {
    const i = o.fill_date ? byDate.get(o.fill_date) : undefined
    return i == null ? [] : [{ i, o }]
  })

  const pick = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    const i = Math.round(Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * (points.length - 1))
    setIdx(i)
    onHover(i)
  }
  const leave = () => {
    setIdx(null)
    onHover(null)
  }
  const fillsAt = idx == null ? [] : marks.filter((m) => m.i === idx).map((m) => m.o)

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
          <path d={path(s.map((p) => p.c), x, y, true)} fill="none" stroke="var(--faint)" strokeDasharray="2 4" />
          <path d={path(s.map((p) => p.b), x, y)} fill="none" stroke="var(--faint)" strokeWidth={1.25} strokeLinejoin="round" />
          <path d={path(ys, x, y)} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
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
              <circle cx={x(idx)} cy={y(s[idx].b)} r={3.5} fill="var(--faint)" stroke="var(--bg)" strokeWidth={1.5} />
              <circle cx={x(idx)} cy={y(ys[idx])} r={5} fill={color} stroke="var(--bg)" strokeWidth={2} />
            </g>
          )}
        </svg>
      )}
      {idx != null && (
        <div className="date" style={{ left: Math.min(Math.max(x(idx), 110), width - 110) }}>
          {md(points[idx].date)}
          {points[idx].live && ' · 지금'}
          {fillsAt.map((o) => ` · ${o.side === 'BUY' ? '샀어요' : '팔았어요'} ${shares(o.qty)}주`)}
          {` · 그냥 보유 ${money(points[idx].benchmark)}`}
        </div>
      )}
    </div>
  )
}

function Overview({ bot }: { bot: Bot }) {
  const { byName } = useStrategies()
  const instruments = useInstruments().data
  const lev = leverageOf(instruments, bot.symbol)
  const leveraged = bot.symbols.map((s) => [s.symbol, leverageOf(instruments, s.symbol)] as const).filter(([, x]) => x > 1)
  const equity = useEquity(bot.id)
  const orders = useOrders(bot.id)
  const [rangeKey, setRangeKey] = useState<string | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [sent, setSent] = useState<string | null>(null)

  const all = equity.data ?? []
  // 기본 기간: 3개월이 안 된 봇은 "전체" (며칠 된 봇에 "지난 3개월"이라고 쓰지 않게)
  const range = RANGES.find((r) => r.key === rangeKey) ?? (all.length <= RANGES[2].days + 1 ? RANGES[4] : RANGES[2])
  const whole = range.days === Infinity
  const points = whole ? all : all.slice(-(range.days + 1))
  const a = bot.account
  const nowEq = Number(currentEquity(bot) ?? a.contributed)
  const latest: Snap = { eq: nowEq, c: Number(a.contributed), b: points.length ? Number(points.at(-1)!.benchmark) : nowEq }
  const start = points.length ? snap(points[0]) : latest
  const end = hover != null && points[hover] ? snap(points[hover]) : latest
  const mine = gainOf(start.eq, end.eq, start, end, whole)
  const hold = gainOf(start.b, end.b, start, end, whole)
  const rising = gainOf(start.eq, latest.eq, start, latest, whole).gain >= 0
  const when = hover != null && points[hover] ? md(points[hover].date) : whole ? '시작 이후' : `지난 ${range.label}`
  const state = STATE[bot.state]
  const near = 0.005 * (mine.base || 1)

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
            <span>
              · {byName[bot.strategy]?.nickname ?? bot.strategy}
              {activeOf(bot.symbols).length > 1 && ` · ${basketLabel(bot.symbols, bot.symbol)}`}
            </span>
          </div>
          <div className="hero-value">{money(String(end.eq))}</div>
          <div className="hero-delta">
            <span className={tone(String(mine.gain))}>
              {signedMoney(String(mine.gain))} ({percent(ratio(mine))})
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
            <button key={r.key} className={r.key === range.key ? 'active' : ''} aria-pressed={r.key === range.key} onClick={() => setRangeKey(r.key)}>
              {r.label}
            </button>
          ))}
        </div>
        <span className="paper">
          <Term k="모의 투자" /> · {a.live_at ? `실시간 ${ago(a.live_at)}` : `${md(a.last_close_date)} 장 마감 기준`}
        </span>
      </div>
      {points.length > 1 && (
        <div className="eq-compare">
          <span className="legend">
            <i className={rising ? 'mine up' : 'mine down'} />이 봇 {percent(ratio(mine))}
          </span>
          <span className="legend">
            <i className="bench" />
            <Term k="그냥 들고 있었다면">그냥 보유</Term> {money(String(end.b))} ({percent(ratio(hold))})
          </span>
          <span className="legend">
            <i className="paid" />
            <Term k="넣은 돈" /> {money(String(end.c))}
          </span>
          <span className="compare-verdict">
            {mine.gain - hold.gain > near
              ? '그냥 들고 있을 때보다 나아요'
              : hold.gain - mine.gain > near
                ? '그냥 들고 있는 게 더 나았어요'
                : '그냥 들고 있을 때와 비슷해요'}
          </span>
        </div>
      )}
      {leveraged.map(([symbol, factor]) => (
        <LeverageNotice key={symbol} symbol={symbol} factor={factor} />
      ))}
      <Facts bot={bot} />
    </>
  )
}

function Facts({ bot }: { bot: Bot }) {
  const a = bot.account
  const accumulates = useStrategies().byName[bot.strategy]?.accumulates
  const holding = a.positions.some((p) => Number(p.qty) > 0)
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
        <div className="sub">
          {bot.state !== 'RUNNING'
            ? '시작하면 바로 판단해요'
            : isPast(bot.next_evaluation_at)
              ? '곧 판단해요' // 예정 시각이 지났으면 Worker가 처리하는 중이다
              : ago(bot.next_evaluation_at)}
        </div>
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
        <div className={`value ${tone(unrealized)}`}>{holding ? signedMoney(unrealized) : '—'}</div>
        <div className="sub">{holding ? '팔기 전 손익' : '들고 있는 주식 없음'}</div>
      </div>
      {accumulates ? (
        // 모으기 봇은 팔지 않으므로 확정 손익 대신 넣은 돈과 입금 일정을 보여준다.
        <div className="fact">
          <div className="label">
            <Term k="넣은 돈" />
          </div>
          <div className="value">{money(a.contributed)}</div>
          <div className="sub">
            매달 {bot.params.day}일 ${bot.params.deposit?.toLocaleString('en-US')}
          </div>
        </div>
      ) : (
        <div className="fact">
          <div className="label">
            <Term k="확정 손익" />
          </div>
          <div className={`value ${tone(a.realized_pnl)}`}>{signedMoney(a.realized_pnl)}</div>
          <div className="sub">판 주식에서</div>
        </div>
      )}
    </div>
  )
}

/* ---------- 세부 ---------- */

const markOf = (d: DecisionT) => (d.action === 'BUY' ? 'rise' : d.action === 'SELL' ? 'fall' : '')
const headOf = (d: DecisionT) =>
  d.action === 'BUY' ? '매수 신호' : d.action === 'SELL' ? '매도 신호' : d.holding ? '그대로 들고 있기' : '기다리기'

function Numbers({ d }: { d: DecisionT }) {
  return (
    <div className="decision-nums">
      {d.reason} ·{' '}
      {Object.entries(d.indicators)
        .map(([k, v]) => `${k} ${Number(v).toFixed(2)}`)
        .join(' · ')}
    </div>
  )
}

function Decision({ bot }: { bot: Bot }) {
  const list = bot.last_decisions.length ? bot.last_decisions : bot.last_decision ? [bot.last_decision] : []
  const d = list[0]
  const [more, setMore] = useState(false)
  const pending = bot.pending_orders
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
      {!d ? (
        <p className="decision-why">아직 판단이 없어요. [매매 시작]을 누르면 가장 최근 가격으로 바로 판단해요.</p>
      ) : list.length === 1 ? (
        <>
          <div className="decision-head">
            <span className={`mark ${markOf(d)}`} />
            {d.plain_action || headOf(d)}
          </div>
          {d.plain_reason && <p className="decision-why">{d.plain_reason}</p>}
          {pending.length > 0 && (
            <p className="decision-why">
              다음 장이 열리면 {pending[0].side === 'BUY' ? '사요' : '팔아요'}. 지금은 예정만 잡혀 있어요.
            </p>
          )}
          {d.blocked && <div className="alert">사지 못했어요: {d.blocked}</div>}
          {more && <Numbers d={d} />}
        </>
      ) : (
        // 여러 종목: 종목마다 한 줄 (같은 날 함께 판단한다)
        <div className="lines">
          {list.map((x) => (
            <div key={x.id} className="line">
              <div>
                <div className="title decision-line">
                  <span className={`mark ${markOf(x)}`} />
                  {x.plain_action || `${x.symbol} ${headOf(x)}`}
                </div>
                {x.plain_reason && <div className="muted small">{x.plain_reason}</div>}
                {x.blocked && <div className="bad small">사지 못했어요: {x.blocked}</div>}
                {more && <Numbers d={x} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Holding({ bot }: { bot: Bot }) {
  const a = bot.account
  const multi = bot.symbols.length > 1
  const held = a.positions.filter((p) => Number(p.qty) > 0)
  return (
    <section className="block">
      <div className="block-head">
        <h2>들고 있는 주식</h2>
        <span className="sub">
          남은 현금 {money(a.cash)}
          {Number(a.reserve) > 0 && ` · 그중 모아 둔 돈 ${money(a.reserve)}`}
        </span>
      </div>
      {held.length ? (
        <div className="lines">
          {held.map((p) => {
            const price = p.live_price ?? p.last_close
            const value = Number(p.qty) * Number(price)
            const pnl = String(value - Number(p.qty) * Number(p.avg_cost))
            const ret = Number(p.avg_cost) ? String(Number(price) / Number(p.avg_cost) - 1) : null
            return (
              <div key={p.symbol} className="line">
                <div>
                  <div className="title">
                    {p.symbol}
                    {multi && <span className="sub"> · {p.weight > 0 ? `비율 ${p.weight}%` : '더 사지 않고 들고만 있어요'}</span>}
                  </div>
                  <div className="muted small tnum">
                    {shares(p.qty)}주 · 산 가격 {money(p.avg_cost)} · 지금 {money(price)}
                    {p.live_change != null && <span className={tone(p.live_change)}> ({percent(p.live_change)})</span>}
                  </div>
                </div>
                <div className="r">
                  <div className="value md">{money(String(value))}</div>
                  <div className={`small ${tone(pnl)}`} style={{ fontWeight: 500 }}>
                    {signedMoney(pnl)} ({percent(ret)})
                  </div>
                </div>
              </div>
            )
          })}
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
  const multi = bot.symbols.length > 1
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
                {multi && <th>종목</th>}
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
                    {multi && <td>{o.symbol}</td>}
                    <td>
                      <span className={`side-tag ${buy ? 'rise' : 'fall'}`}>
                        {buy ? '샀어요' : '팔았어요'}
                        {status && <span className="faint small">{status}</span>}
                      </span>
                    </td>
                    <td className="qty">{Number(o.qty) > 0 ? `${shares(o.qty)}주` : '—'}</td>
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
  // 입금으로 늘어난 몫은 빼고 손익의 흐름만 그린다.
  const values = (useEquity(bot.id).data ?? []).slice(-63).map((p) => Number(p.equity) - Number(p.contributed))
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

/** 홈: 왼쪽에 고른 봇의 자산·판단·거래, 오른쪽에 봇 목록. 고른 봇은 이 브라우저에 기억한다. */
export function Home({ bots }: { bots: Bot[] }) {
  const [logOpen, setLogOpen] = useState(false)
  const bot = useSelectedBot(bots)
  const pick = selectBot
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
            <button className="link" onClick={() => startNewBot()}>
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
