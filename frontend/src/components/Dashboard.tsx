import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useRef, useState } from 'react'
import {
  api,
  botApi,
  type ActivityItem,
  type World,
  type Bot,
  type BotState,
  type CommandKind,
  type Decision as DecisionT,
  type EquityPoint,
  type Order,
} from '../api'
import { ago, isPast, kstTime, money, percent, roundMoney, shares, signedMoney, tone } from '../format'
import { FALLBACK, leverageOf, useInstruments } from '../instruments'
import { sourceLabel } from '../source'
import { realKeepNote } from '../live'
import { AI_KINDS, isAiBot, isMeBot, useStrategies, type AiKind } from '../strategies'
import { useDemo } from '../demo'
import { FxNote } from './Currency'
import { AccountCard, LiveApprovals } from './Live'
import { Term } from './Help'
import { goTo, openBot, selectBot, startMeEdit, startMeQuestions, startNewBot, useSelectedBot } from '../selectedBot'
import { PriceChart } from './PriceChart'
import { useDismiss } from '../useDismiss'
import { activeOf, basketLabel, evenSplit } from '../basket'
import { LeverageNotice } from './SymbolPicker'
import { ParallelWorlds } from './Parallel'
import { NextPlan } from './NextPlan'
import { toConfig, toDraft } from '../botConfig'
import { AiCompare, AiHistory, AiToday } from './AiBot'

const STATE: Record<BotState, { label: string; dot: string }> = {
  RUNNING: { label: '실행 중', dot: 'ok pulse' },
  PAUSED: { label: '멈춤', dot: 'warn' },
  STOPPED: { label: '멈춤', dot: 'warn' },
  ERROR: { label: '문제 발생', dot: 'bad' },
}

/** 화면에 보일 상태. 시작·멈추기를 누른 뒤 Worker가 반영하기 전(15초 안)에는 "시작하는 중"처럼 보인다. */
function stateOf(bot: Bot) {
  if (bot.pending_command === 'START') return { label: '시작하는 중', dot: 'ok pulse' }
  if (bot.pending_command === 'PAUSE' || bot.pending_command === 'STOP') return { label: '멈추는 중', dot: 'warn' }
  return STATE[bot.state]
}

/** 실행 중이거나 시작하는 중이면 곧 첫 판단을 한다. */
const startingOrRunning = (bot: Bot) => bot.state === 'RUNNING' || bot.pending_command === 'START'

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
  const [menu, setMenu] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(menu, () => setMenu(false), ref)
  const reset = useMutation({
    mutationFn: () => botApi.reset(bot.id),
    onSuccess: () => {
      onSent('처음부터 다시 시작했어요. 곧 가장 최근 가격으로 첫 판단을 해요.')
      void qc.invalidateQueries()
    },
    onError: (e) => onSent(`다시 시작하지 못했어요: ${e.message}`),
  })
  const remove = useMutation({
    mutationFn: () => botApi.remove(bot.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['bots'] })
      goTo('dashboard')
    },
    onError: (e) => onSent(`지우지 못했어요: ${e.message}`),
  })
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
    <div className="hero-actions" ref={ref}>
      <button className={primary ? 'primary' : ''} disabled={mutation.isPending} onClick={() => send(main)}>
        {main.label}
      </button>
      <button className="ghost" onClick={() => (location.hash = 'settings')}>
        설정
      </button>
      <button className="ghost more" aria-label="더 보기" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
        ⋯
      </button>
      {menu && (
        <div className="menu" role="menu">
          <button
            role="menuitem"
            disabled={reset.isPending}
            onClick={() => {
              setMenu(false)
              const ok = window.confirm(
                `${bot.name}의 모의 잔고를 ${money(bot.account.initial_cash)}로 되돌리고 판단·거래 기록을 모두 지울까요?\n` +
                  '설정과 실행 상태는 그대로예요. 되돌릴 수 없어요.' +
                  realKeepNote(bot, 'reset'),
              )
              if (ok) reset.mutate()
            }}
          >
            처음부터 다시 시작
          </button>
          <hr />
          <button
            role="menuitem"
            className="danger"
            disabled={remove.isPending}
            onClick={() => {
              setMenu(false)
              if (window.confirm(`${bot.name}을(를) 지울까요? 이 봇의 모든 기록도 함께 지워져요. 되돌릴 수 없어요.${realKeepNote(bot, 'delete')}`))
                remove.mutate()
            }}
          >
            봇 삭제
          </button>
        </div>
      )}
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
  // AI 봇은 관심 종목을 모두 담아 두고 실제로 들고 있는 레버리지 종목만 안내한다
  const held = (symbol: string) => bot.account.positions.some((p) => p.symbol === symbol && Number(p.qty) > 0)
  const leveraged = bot.symbols
    .map((s) => [s.symbol, leverageOf(instruments, s.symbol)] as const)
    .filter(([symbol, x]) => x > 1 && (!isAiBot(bot) || held(symbol)))
  const equity = useEquity(bot.id)
  const orders = useOrders(bot.id)
  const [rangeKey, setRangeKey] = useState<string | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [sent, setSent] = useState<string | null>(null)

  const all = equity.data ?? []
  // 기본 기간은 "전체"(시작 이후, 넣은 돈 대비): 봇 목록의 수익률과 같은 숫자로 시작한다
  const range = RANGES.find((r) => r.key === rangeKey) ?? RANGES[4]
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
  const state = stateOf(bot)
  const near = 0.005 * (mine.base || 1)
  const demo = useDemo()
  const me = isMeBot(bot)
  const ai = isAiBot(bot)
  // 전략 목록을 불러오기 전에는 내부 이름(ai_judge) 대신 비워 둔다
  const nickname = byName[bot.strategy]?.nickname
  const scope = ai
    ? `관심 종목 ${bot.symbols.length}개 안에서`
    : activeOf(bot.symbols).length > 1
      ? basketLabel(bot.symbols, bot.symbol)
      : null

  return (
    <>
      <div className="hero-head">
        <div>
          <div className="bot-line lead">
            <h1 className="name">
              {bot.name}
              {lev > 1 && <span className="lev">{lev}×</span>}
            </h1>
            <span className={`dot ${state.dot}`}>{state.label}</span>
            {[nickname, scope].filter(Boolean).map((t) => (
              <span key={t}>· {t}</span>
            ))}
          </div>
          <div className="hero-value">{money(String(end.eq))}</div>
          <div className="hero-delta">
            <span className={tone(String(mine.gain))}>
              {signedMoney(String(mine.gain))} ({percent(ratio(mine))})
            </span>
            <span className="when">{when}</span>
          </div>
          <FxNote />
        </div>
        {!demo && <Controls bot={bot} onSent={setSent} />}
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
            <i className={rising ? 'mine up' : 'mine down'} />
            {me ? '나처럼' : '이 봇'} {percent(ratio(mine))}
          </span>
          <span className="legend">
            <i className="bench" />
            {me ? '매달 그냥 사기' : ai ? `관심 종목 ${bot.symbols.length}개 똑같이 나눠 매달 사기` : <Term k="그냥 들고 있었다면">그냥 보유</Term>}{' '}
            {money(String(end.b))} ({percent(ratio(hold))})
          </span>
          <span className="legend">
            <i className="paid" />
            <Term k="넣은 돈" /> {money(String(end.c))}
          </span>
          {/* 나 카피 봇·AI 봇은 판정하지 않는다 (평가가 아니라 구경, project.md 1절) */}
          {!me && !ai && <span className="compare-verdict">
            {mine.gain - hold.gain > near
              ? '그냥 들고 있을 때보다 나아요'
              : hold.gain - mine.gain > near
                ? '그냥 들고 있는 게 더 나았어요'
                : '그냥 들고 있을 때와 비슷해요'}
          </span>}
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
          <Term k="평가 손익">아직 안 판 주식의 손익</Term>
        </div>
        <div className={`value ${tone(unrealized)}`}>{holding ? signedMoney(unrealized) : '—'}</div>
        <div className="sub">{holding ? '산 가격과 지금 가격의 차이' : '들고 있는 주식 없음'}</div>
      </div>
      <div className="fact">
        <div className="label">
          <Term k="넣은 돈" />
        </div>
        <div className="value">{money(a.contributed)}</div>
        <div className="sub">
          매달 {bot.params.day}일 ${bot.params.deposit?.toLocaleString('en-US')}
        </div>
      </div>
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
        <p className="decision-why">
          {startingOrRunning(bot)
            ? '곧 첫 판단을 해요. 가장 최근 장 마감 가격으로 판단해요.'
            : '아직 판단이 없어요. [매매 시작]을 누르면 가장 최근 가격으로 바로 판단해요.'}
        </p>
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
  // 많이 든 종목부터 (가격 차트도 가장 많이 든 종목부터 보여준다)
  const worth = (p: (typeof a.positions)[number]) => Number(p.qty) * Number(p.live_price ?? p.last_close)
  const held = a.positions.filter((p) => Number(p.qty) > 0).sort((x, y) => worth(y) - worth(x))
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
                    {multi && !isAiBot(bot) && <span className="sub"> · {p.weight > 0 ? `비율 ${p.weight}%` : '더 사지 않고 들고만 있어요'}</span>}
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
      {!data ? (
        <div className="line-empty">불러오는 중…</div>
      ) : rows.length ? (
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
        <span className="sub">{info?.nickname}</span>
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
  const state = stateOf(bot)
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

// 첫 판단 전에는 비교할 것이 없으므로 판단하면 다시 계산한다
const parallelKey = (bot: Bot) => ['parallel', bot.id, JSON.stringify(bot.params), JSON.stringify(bot.symbols), bot.last_decision?.session_date]

/** 나처럼 투자 봇: 시작한 뒤로 규칙을 하나씩 바꿨다면 (고르면 다음 판단부터 그 규칙으로). */
function BotParallel({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const demo = useDemo()
  return (
    <ParallelWorlds
      queryKey={parallelKey(bot)}
      fetch={() => botApi.parallel(bot.id)}
      sub={(p) => (p.start ? `${md(p.start)}에 시작한 뒤로, 규칙을 하나씩 바꿨다면` : '')}
      chooseLabel="로 바꾸기"
      confirm="다음 판단부터 이 규칙으로 바꿀까요? 지금까지의 기록은 그대로예요."
      onChoose={demo ? undefined : async (params) => {
        await botApi.updateConfig(bot.id, { ...toConfig(toDraft(bot), bot), params })
        await qc.invalidateQueries({ queryKey: ['bots'] })
      }}
    />
  )
}

// 만들기 확인창에서 무엇을 보고 판단하는지
const AI_HOW: Record<AiKind, string> = {
  ai_judge: '시장을 조사해',
  ai_candle: '가격 차트만 보고(종목 이름·날짜는 가리고, 뉴스는 보지 않아요)',
}

/** AI 봇 만들기: 관심 종목 전부, 입금은 나 카피 봇과 같게 (같은 돈으로 비교하려고). 만들자마자 시작한다. */
function useCreateAiBot(bots: Bot[]) {
  const qc = useQueryClient()
  const watchlist = useInstruments().data?.map((i) => i.symbol)
  return useMutation({
    mutationFn: async (kind: AiKind) => {
      const me = bots.find(isMeBot)
      const deposit = me?.params.deposit ?? 1000
      const day = me?.params.day ?? 25
      const symbols = watchlist?.length ? watchlist : FALLBACK
      const info = AI_KINDS[kind]
      const ok = window.confirm(
        `${info.name}을 만들까요?
관심 종목 ${symbols.length}개(${symbols.join(' · ')}) 안에서 AI가 매일 장이 끝난 뒤 ${AI_HOW[kind]} 비중을 정해요.
매달 ${day}일 $${deposit.toLocaleString('en-US')}를 넣어요${me ? ' (나 카피 봇과 같게)' : ''}. 모의 투자예요.
AI 판단 비용은 하루 약 ${info.cost}이고, 이 봇의 한 달 상한을 넘으면 그달은 쉬어요.`,
      )
      if (!ok) return null
      const bot = await botApi.create({
        strategy: kind,
        params: { deposit, day },
        commission_rate: '0.001',
        slippage_bps: '5',
        max_position_value: null,
        max_order_value: null,
        name: info.name,
        symbol: symbols[0],
        symbols: evenSplit(symbols), // AI 봇은 비율을 쓰지 않는다 (AI가 정한다)
        initial_cash: String(deposit),
      })
      await api.command(bot.id, 'START')
      return bot
    },
    onSuccess: async (bot) => {
      if (!bot) return
      await qc.invalidateQueries({ queryKey: ['bots'] })
      openBot(bot.id)
    },
    onError: (e) => window.alert(`AI 봇을 만들지 못했어요: ${e.message}`),
  })
}

/** 폰에서 봇 바꾸기: 화면 맨 위의 가로 칩 (넓은 화면은 오른쪽 봇 목록을 쓴다). 순서는 봇 목록과 같다. */
function BotTabs({ bots, current, onPick }: { bots: Bot[]; current?: Bot; onPick: (b: Bot) => void }) {
  if (bots.length < 2) return null
  const ordered = [...bots.filter(isMeBot), ...bots.filter(isAiBot), ...bots.filter((b) => !isMeBot(b) && !isAiBot(b))]
  return (
    <nav className="bot-tabs" aria-label="봇 바꾸기">
      {ordered.map((b) => {
        const ret = botReturn(b)
        const on = b.id === current?.id
        return (
          <button key={b.id} className={on ? 'active' : ''} aria-current={on ? 'page' : undefined} onClick={() => onPick(b)}>
            {b.name}
            <span className={`tnum ${on ? '' : tone(ret)}`}>{percent(ret)}</span>
          </button>
        )
      })}
    </nav>
  )
}

/** 오른쪽 봇 목록: 나 카피 봇이 위, AI 봇, 다른 봇은 아래 묶음. */
function BotSide({ bots, current, onPick }: { bots: Bot[]; current?: Bot; onPick: (b: Bot) => void }) {
  const demo = useDemo()
  const mine = bots.filter(isMeBot)
  const ais = bots.filter(isAiBot)
  const others = bots.filter((b) => !isMeBot(b) && !isAiBot(b))
  const createAi = useCreateAiBot(bots)
  // 아직 없는 AI 봇 종류 (전략마다 하나)
  const missing = demo ? [] : (Object.keys(AI_KINDS) as AiKind[]).filter((k) => !ais.some((b) => b.strategy === k))
  const row = (b: Bot) => <BotItem key={b.id} bot={b} active={b.id === current?.id} onPick={() => onPick(b)} />
  return (
    <aside className="home-side">
      <div className="bot-list">
        <div className="bot-list-head">
          나 카피 봇
          <button className="link" onClick={() => (mine.length && !demo ? startMeEdit(mine[0].id) : goTo('me'))}>
            {mine.length && !demo ? '다시 카피하기' : '나 카피하기'}
          </button>
        </div>
        {mine.length ? mine.map(row) : <div className="bot-list-empty">아직 없어요</div>}
        {(ais.length > 0 || !demo) && <div className="bot-list-head sub">AI 봇</div>}
        {ais.map(row)}
        {missing.map((k) => (
          <div key={k} className="bot-list-empty bot-list-make">
            <span>
              {AI_KINDS[k].short}: {AI_KINDS[k].desc}
            </span>
            <button className="link" disabled={createAi.isPending} onClick={() => createAi.mutate(k)}>
              + 만들기
            </button>
          </div>
        ))}
        <div className="bot-list-head sub">
          다른 봇
          {!demo && (
            <button className="link" onClick={() => startNewBot()}>
              + 새 봇
            </button>
          )}
        </div>
        {others.length ? others.map(row) : <div className="bot-list-empty">유명한 투자법을 따라 하는 봇이에요</div>}
      </div>
      <AccountCard />
      <div className="side-note">10초마다 새로 불러와요.</div>
    </aside>
  )
}

/** 봇 하나 자세히 보기 (#bot/3, 나 카피 봇이 없으면 홈). 고른 봇은 이 브라우저에 기억한다. */
export function Home({ bots }: { bots: Bot[] }) {
  const [logOpen, setLogOpen] = useState(false)
  const bot = useSelectedBot(bots)
  const pick = (b: Bot) => openBot(b.id)
  return (
    <div className="home">
      <div className="home-main" key={bot.id}>
        <button className="link back" onClick={() => goTo('dashboard')}>
          ← 홈
        </button>
        <BotTabs bots={bots} current={bot} onPick={pick} />
        <Overview bot={bot} />
        {isAiBot(bot) ? (
          <>
            <AiToday bot={bot} />
            <AiCompare bot={bot} />
          </>
        ) : (
          <Decision bot={bot} />
        )}
        <Holding bot={bot} />
        <PriceChart bot={bot} />
        <Trades bot={bot} onOpenLog={() => setLogOpen(true)} />
        {isAiBot(bot) && <AiHistory bot={bot} />}
        <Strategy bot={bot} />
      </div>
      <BotSide bots={bots} current={bot} onPick={pick} />
      {logOpen && <LogDrawer bot={bot} onClose={() => setLogOpen(false)} />}
    </div>
  )
}

/* ── 나 카피 봇 홈 (N5): 첫 화면은 "나 vs 매달 그냥 사기"와 평행세계의 나. 점수·판정 문장은 붙이지 않는다. ── */

function MeHero({ bot }: { bot: Bot }) {
  const equity = useEquity(bot.id)
  const a = bot.account
  const paid = Number(a.contributed)
  const now = Number(currentEquity(bot) ?? a.contributed)
  const points = equity.data ?? []
  const bench = points.length ? Number(points.at(-1)!.benchmark) : paid
  const vsPaid = (v: number) => (paid ? String(v / paid - 1) : null)
  const state = stateOf(bot)
  return (
    <section className="me-hero">
      <div className="bot-line">
        <span className="name">{bot.name}</span>
        <span className={`dot ${state.dot}`}>{state.label}</span>
        <span>
          {bot.name.includes('나 카피') ? '' : ' · 나 카피 봇'} · {basketLabel(bot.symbols, bot.symbol)}
        </span>
      </div>
      <div className="me-vs">
        <div>
          <div className="label legend">
            <i className="pw-mine" />
            나처럼 했을 때
          </div>
          <div className="hero-value">{money(String(now))}</div>
          <div className={`hero-delta ${tone(vsPaid(now))}`}>넣은 돈보다 {percent(vsPaid(now))}</div>
          <FxNote />
        </div>
        <div className="vs-other">
          <div className="label legend">
            <i className="bench" />
            매달 그냥 샀다면
          </div>
          <div className="value tnum">{money(String(bench))}</div>
          <div className={`small ${tone(vsPaid(bench))}`}>넣은 돈보다 {percent(vsPaid(bench))}</div>
        </div>
      </div>
      <div className="faint small">
        넣은 돈 {money(a.contributed)}
        {points.length > 0 && ` · ${md(points[0].date)}부터`} · <Term k="모의 투자" /> ·{' '}
        {a.live_at ? `실시간 ${ago(a.live_at)}` : `${md(a.last_close_date)} 장 마감 기준`}
      </div>
    </section>
  )
}

/** 월간 정리: "9월에 나 카피 봇은 사지 않고 모아 뒀어요. 고점에도 안 쉬는 나는 $1,000어치 샀어요." */
function MonthDigest({ bot }: { bot: Bot }) {
  const { data } = useQuery({ queryKey: parallelKey(bot), queryFn: () => botApi.parallel(bot.id), staleTime: 10 * 60_000, retry: false })
  const worlds = data?.worlds ?? []
  const me = worlds.find((w) => w.key === 'me')
  if (!me || me.recent.length < 2) return null
  // 이번 달에 아직 아무도 안 샀으면(입금일 전) 지난달을 정리한다.
  const at = worlds.some((w) => Number(w.recent[1].bought) > 0) ? 1 : 0
  const amount = (w: World) => Number(w.recent[at].bought)
  const did = (w: World) => (amount(w) > 0 ? `${roundMoney(amount(w))}어치 샀어요` : '사지 않고 모아 뒀어요')
  const others = worlds.filter((w) => w.key !== 'me')
  // 나와 다르게 한 나: 사고 안 사고가 다른 나, 없으면 금액이 다른 나
  const other =
    others.find((w) => amount(w) > 0 !== amount(me) > 0) ?? others.find((w) => Math.abs(amount(w) - amount(me)) >= 1)
  const month = `${Number(me.recent[at].month.slice(5))}월`
  return (
    <section className="block me-digest">
      <div className="block-head">
        <h2>{month} 정리</h2>
      </div>
      <p>
        {month}에 나 카피 봇은 {did(me)}. {other ? `${other.title}는 ${did(other)}.` : '다른 나들도 모두 같았어요.'}
      </p>
    </section>
  )
}

/** 나 카피 봇이 아직 없을 때 홈 첫 화면: 무엇을 하는지 세 단계로 보여주고 나 카피하기로 이끈다. */
function MeStart() {
  return (
    <section className="me-start">
      <p className="me-eyebrow">나 카피 봇</p>
      <h1>내가 투자하는 방식 그대로, 봇이 대신 해 보면 어떨까요?</h1>
      <p className="lead">
        질문 몇 개로 내 투자 습관을 복사해요. 지난 10년을 &quot;나처럼 했다면&quot;과 &quot;매달 그냥 샀다면&quot;으로 나란히 보여주고,
        그다음부터는 봇이 매일 나 대신 모의 투자를 해요.
      </p>
      <ol className="me-start-steps">
        <li>
          <b>나 카피하기</b>
          <span>질문 4~6개, 1분이면 끝나요</span>
        </li>
        <li>
          <b>지난 10년 보기</b>
          <span>나처럼 했다면 vs 매달 그냥 샀다면</span>
        </li>
        <li>
          <b>평행세계의 나</b>
          <span>규칙을 하나씩 바꾼 다른 나들과 나란히</span>
        </li>
      </ol>
      <div className="me-start-go">
        <button className="primary" onClick={startMeQuestions}>
          나 카피하기
        </button>
        <span className="muted small">1분이면 끝나요. 다 만들면 이 아래가 내 화면으로 채워져요 · 실제 계좌는 연결하지 않아요</span>
      </div>
      <div className="me-limit">
        <b>아직 복사하기 어려운 투자도 있어요.</b> 그때그때 기분이나 뉴스를 보고 사고팔거나, 며칠·몇 주 단위로 자주 사고파는 투자는
        규칙으로 옮길 수 없어요. &quot;매달 얼마, 많이 오르면 쉬고, 떨어지면 몰아 사기&quot;처럼 말로 정할 수 있는 습관만 따라 해요.
        파는 습관도 아직 복사하지 않아요 (산 주식은 계속 들고 있어요).
      </div>
      <MePreview />
    </section>
  )
}

/** 나 카피 봇을 만들면 홈이 어떻게 바뀌는지 보여주는 예시 화면 (숫자는 예시, 누를 수 없음). */
function MePreview() {
  const worlds = [
    { title: '나', sub: '지금 규칙 그대로', value: '$12,480', rate: '+15.6%', me: true },
    { title: '매달 그냥 사는 나', sub: '규칙 없이 넣을 때마다 바로 사요', value: '$12,106', rate: '+12.1%' },
    { title: '떨어졌을 때만 사는 나', sub: '매달 사기 → 떨어졌을 때만 사기', value: '$12,931', rate: '+19.7%' },
  ]
  return (
    <div className="me-preview-wrap">
      <div className="me-preview-head">
        <span className="pill">예시</span>
        <span className="muted small">나 카피 봇을 만들면 홈이 이렇게 바뀌어요</span>
      </div>
      <div className="me-preview-card" aria-hidden="true">
        <div className="me-vs">
          <div>
            <div className="label legend">
              <i className="pw-mine" />
              나처럼 했을 때
            </div>
            <div className="hero-value">$12,480</div>
            <div className="hero-delta rise">넣은 돈보다 +15.6%</div>
          </div>
          <div className="vs-other">
            <div className="label legend">
              <i className="bench" />
              매달 그냥 샀다면
            </div>
            <div className="value tnum">$12,106</div>
            <div className="small rise">넣은 돈보다 +12.1%</div>
          </div>
        </div>
        <p className="me-preview-digest">9월에 나 카피 봇은 사지 않고 모아 뒀어요. 고점에도 안 쉬는 나는 $1,000어치 샀어요.</p>
        <svg className="me-preview-chart" viewBox="0 0 600 120" preserveAspectRatio="none">
          <path d="M0 112 C80 104 140 92 200 84 S300 76 340 58 S440 40 480 30 S560 14 600 8" fill="none" stroke="var(--accent)" strokeWidth="2" />
          <path d="M0 114 C80 106 140 96 200 88 S300 82 340 66 S440 48 480 36 S560 22 600 16" fill="none" stroke="var(--text)" strokeWidth="2" />
        </svg>
        <div className="pw-list">
          {worlds.map((w) => (
            <div key={w.title} className={`pw-item ${w.me ? 'pw-mine' : ''}`}>
              <div>
                <div className="title">{w.title}</div>
                <div className="sub">{w.sub}</div>
              </div>
              <div className="r">
                <div className="value tnum">{w.value}</div>
                <div className="sub">넣은 돈보다 {w.rate}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** 홈 첫 화면은 늘 나 카피 봇 자리다. 고른 봇이 나 카피 봇이 아니면 첫 나 카피 봇, 없으면 시작 화면. */
export function MeHome({ bots }: { bots: Bot[] }) {
  const demo = useDemo()
  const selected = useSelectedBot(bots) as Bot | undefined
  const bot = selected && isMeBot(selected) ? selected : bots.find(isMeBot)
  // 나 카피 봇은 이 화면에 그대로, 다른 봇은 그 봇 화면으로
  const pick = (b: Bot) => (isMeBot(b) ? selectBot(b.id) : openBot(b.id))
  return (
    <div className="home me-home">
      <div className="home-main" key={bot?.id ?? 'start'}>
        <BotTabs bots={bots} current={bot} onPick={pick} />
        {bot ? (
          <>
            <LiveApprovals />
            <MeHero bot={bot} />
            <NextPlan bot={bot} />
            <MonthDigest bot={bot} />
            <BotParallel bot={bot} />
            <Decision bot={bot} />
            <div className="me-more">
              <button onClick={() => openBot(bot.id)}>자세히 보기</button>
              <span className="faint small">들고 있는 주식, 거래, 가격 그래프{demo ? '' : ', 매매 시작·멈춤'}</span>
            </div>
          </>
        ) : (
          <MeStart />
        )}
      </div>
      {bots.length > 0 && (
        <BotSide bots={bots} current={bot} onPick={pick} />
      )}
    </div>
  )
}
