import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, botApi, type AiDay, type Bot, type Order, type World } from '../api'
import { activeOf } from '../basket'
import { useDemo } from '../demo'
import { money, percent } from '../format'
import { isMeBot } from '../strategies'
import { Chart } from './Parallel'

/* AI 봇 (마일스톤 4 A3): 오늘의 AI 판단·참고한 것, 세 봇 비교, 판단 기록.
   AI는 고른 종목과 현금 사이의 비중만 정하고, 사고파는 금액은 엔진이 맞춘다 (project.md 14절).
   점수·판정 문장은 붙이지 않는다 (project.md 1절). */

const CASH = 'CASH'

/** '2026-10-01' → '10월 1일' (미국 장 날짜라 시간대 변환 없이 그대로 읽는다). */
function md(date: string | null | undefined) {
  if (!date) return '—'
  const [y, m, d] = date.split('-')
  const year = Number(y) === new Date().getFullYear() ? '' : `${y}년 `
  return `${year}${Number(m)}월 ${Number(d)}일`
}

const label = (symbol: string) => (symbol === CASH ? '현금' : symbol)
const pct = (v: number) => `${Math.round(v)}%`

/** 판단하지 못한 날의 쉬운 말. */
const MISSED: Record<Exclude<AiDay['status'], 'OK'>, string> = {
  FAILED: 'AI가 이날 판단하지 못해서 지금 그대로 뒀어요.',
  INVALID: 'AI 답이 규칙(고른 종목만, 합 100%)에 맞지 않아 지금 그대로 뒀어요.',
  OVER_BUDGET: '이번 달 AI 비용 상한에 닿아서 지금 그대로 뒀어요.',
}

function useAi(bot: Bot) {
  return useQuery({ queryKey: ['ai', bot.id], queryFn: () => botApi.ai(bot.id), staleTime: 60_000 })
}

/** 내일 시가에 낼 모의 주문 한 줄: "$405 사요", "$120어치 팔아요", "모두 팔아요". */
function orderText(o: Order | undefined) {
  if (!o) return null
  if (o.side === 'BUY') return { text: `${money(o.budget)} 사요`, tone: 'rise' }
  return { text: o.budget ? `${money(o.budget)}어치 팔아요` : '모두 팔아요', tone: 'fall' }
}

type Row = { symbol: string; before: number; target: number; reason: string; order: ReturnType<typeof orderText> }

function rowsOf(day: AiDay, bot: Bot): Row[] {
  const symbols = [...bot.symbols.map((s) => s.symbol), CASH]
  const target = day.weights ?? {}
  return symbols
    .map((symbol) => ({
      symbol,
      before: Number(day.weights_before[symbol] ?? 0),
      target: target[symbol] ?? 0,
      reason: day.reasons?.[symbol] ?? '',
      order: orderText(bot.pending_orders.find((o) => o.symbol === symbol)),
    }))
    .sort((a, b) => Number(a.symbol === CASH) - Number(b.symbol === CASH) || b.target - a.target || b.before - a.before)
}

function Weight({ row }: { row: Row }) {
  const changed = Math.round(row.before) !== row.target
  return (
    <div className="ai-row">
      <div className="ai-row-head">
        <span className="title">{label(row.symbol)}</span>
        <span className="ai-weights tnum">
          {changed && <span className="faint">{pct(row.before)} → </span>}
          <b>{pct(row.target)}</b>
        </span>
        {row.order && <span className={`ai-order ${row.order.tone}`}>내일 {row.order.text}</span>}
      </div>
      <div className="ai-bar" aria-hidden="true">
        <i className="ai-bar-before" style={{ width: `${Math.min(100, row.before)}%` }} />
        <i className="ai-bar-target" style={{ left: `${Math.min(100, row.target)}%` }} />
      </div>
      {row.reason && <div className="muted small">{row.reason}</div>}
    </div>
  )
}

function SourceList({ items }: { items: AiDay['sources'] }) {
  return (
    <ul className="ai-links">
      {items.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noopener noreferrer">
            {s.title || s.url}
          </a>
          <span className="faint small"> · {new URL(s.url).hostname.replace(/^www\./, '')}</span>
        </li>
      ))}
    </ul>
  )
}

/** AI가 참고한 것: 판단에 쓴 기사를 먼저, 검색해서 받아 보기만 한 결과는 접어 둔다. */
function Sources({ day }: { day: AiDay }) {
  const [open, setOpen] = useState(false)
  if (!day.queries.length && !day.sources.length) return null
  const used = day.sources.filter((s) => s.used)
  // 지침 .4(2026-10-07) 전 판단에는 근거 표시가 없다: 받아 본 결과 중 앞의 5개를 보여준다
  const lead = used.length ? used : day.sources.slice(0, 5)
  const rest = day.sources.filter((s) => !lead.includes(s))
  const queries = [...new Set(day.queries)]
  return (
    <details className="ai-sources">
      <summary>
        AI가 참고한 것 · {used.length ? `근거 기사 ${used.length}개 · ` : ''}검색 {queries.length}번, 결과 {day.sources.length}개
      </summary>
      {queries.length > 0 && (
        <div className="ai-queries small">
          {queries.map((q) => (
            <span key={q} className="chip">
              {q}
            </span>
          ))}
        </div>
      )}
      {used.length > 0 && <div className="faint small">판단에 쓴 기사</div>}
      <SourceList items={lead} />
      {rest.length > 0 &&
        (open ? (
          <>
            <div className="faint small">검색해서 받아 본 나머지 결과 (판단에 쓰지 않았을 수 있어요)</div>
            <SourceList items={rest} />
          </>
        ) : (
          <button className="link" onClick={() => setOpen(true)}>
            {used.length ? `검색 결과 ${rest.length}개 더 보기` : `${rest.length}개 더 보기`}
          </button>
        ))}
    </details>
  )
}

/** 오늘의 AI 판단: 시장 요약, 종목마다 지금 → 목표 비중과 이유, 내일 낼 주문. */
export function AiToday({ bot }: { bot: Bot }) {
  const { data, error } = useAi(bot)
  const demo = useDemo()
  const [all, setAll] = useState(false)
  const day = data?.latest
  const rows = day ? rowsOf(day, bot) : []
  const held = rows.filter((r) => r.target > 0 || r.before >= 0.5 || r.order)
  const rest = rows.filter((r) => !held.includes(r))
  return (
    <section className="block">
      <div className="block-head">
        <h2>오늘의 AI 판단</h2>
        {day && <span className="sub">{md(day.session_date)} 장 마감 기준</span>}
      </div>
      {error ? (
        <div className="line-empty">불러오지 못했어요: {error.message}</div>
      ) : !data ? (
        <div className="line-empty">불러오는 중…</div>
      ) : !day ? (
        <p className="decision-why">
          아직 판단이 없어요. [매매 시작]을 누르면 가장 최근 장 마감 가격과 뉴스로 바로 판단해요.
        </p>
      ) : day.status !== 'OK' ? (
        <p className="decision-why">{MISSED[day.status]}</p>
      ) : (
        <>
          {day.summary && <p className="decision-why">{day.summary}</p>}
          <div className="ai-rows">
            {(all ? rows : held).map((r) => (
              <Weight key={r.symbol} row={r} />
            ))}
          </div>
          {rest.length > 0 && (
            <button className="link" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? '접기' : `담지 않은 종목 ${rest.length}개 보기 (${rest.map((r) => r.symbol).join(' · ')})`}
            </button>
          )}
          <Sources day={day} />
        </>
      )}
      {data && demo && (
        <div className="strategy-meta">예시 판단이에요. 데모는 실제 AI가 아니라 정해진 규칙으로 판단을 만들어요 (비용 없음).</div>
      )}
      {data && !demo && (
        <div className="strategy-meta">
          {day?.model && `${day.model} · `}
          {day?.cost != null && `이 판단 ${money(day.cost)} · `}
          이번 달 AI 비용 {money(data.spent)} / 상한 {money(data.budget)}
        </div>
      )}
    </section>
  )
}

/** AI 봇 vs 나 카피 봇 규칙 vs 매달 그냥 사기 (AI 봇이 처음 판단한 날부터, 같은 날 같은 돈). */
export function AiCompare({ bot }: { bot: Bot }) {
  const { data, error } = useQuery({
    queryKey: ['ai-compare', bot.id],
    queryFn: () => botApi.aiCompare(bot.id),
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  })
  const [picked, setPicked] = useState('copy')
  const { data: bots } = useQuery({ queryKey: ['bots'], queryFn: api.bots })
  const worlds = data?.worlds ?? []
  const ai = worlds.find((w) => w.key === 'me')
  const other = worlds.find((w) => w.key === picked) ?? worlds.find((w) => w.key !== 'me')
  // 1년이 안 되면 연 수익률이 부풀려 보이므로 넣은 돈 대비로 보여준다.
  const long = !!data?.start && !!data.end && Date.parse(data.end) - Date.parse(data.start) >= 365 * 86_400_000
  const rate = (w: World) =>
    long ? `해마다 평균 ${percent(w.cagr)}` : `넣은 돈보다 ${percent(String(Number(w.final_equity) / Number(w.contributed) - 1))}`
  // 매달 그냥 사기는 무엇을 샀는지 밝힌다 (위 그래프의 "관심 종목 똑같이 나눠 사기"와 다른 기준이다).
  // 나 카피 봇이 있으면 그 종목·비율, 없으면 AI 봇 종목을 똑같이 나눠 샀다.
  const meSymbols = activeOf(bots?.find(isMeBot)?.symbols ?? []).map((s) => s.symbol)
  const sub: Record<string, string> = {
    me: 'AI가 매일 비중을 정해요',
    copy: '지금 나 카피 봇 규칙으로 같은 돈을 넣었다면',
    dca: worlds.some((w) => w.key === 'copy') && meSymbols.length
      ? `나 카피 봇 종목(${meSymbols.join(' · ')})을 넣자마자 그냥 샀다면`
      : `관심 종목 ${bot.symbols.length}개를 똑같이 나눠 넣자마자 샀다면`,
  }
  return (
    <section className="block pw">
      <div className="block-head">
        <h2>AI 봇 vs 나 카피 봇</h2>
        {data?.start && <span className="sub">{md(data.start)}부터 같은 날 같은 돈으로</span>}
      </div>
      {error ? (
        <div className="line-empty">계산하지 못했어요: {error.message}</div>
      ) : !data ? (
        <div className="line-empty">계산하는 중…</div>
      ) : !ai || !other ? (
        <div className="line-empty">{data.note ?? '아직 비교할 수 없어요.'}</div>
      ) : (
        <>
          <Chart me={ai} other={other} />
          <div className="pw-legend">
            <span className="legend">
              <i className="pw-mine" />
              AI 봇
            </span>
            <span className="legend">
              <i className="other" />
              {other.title}
            </span>
          </div>
          <div className="pw-list" role="listbox" aria-label="비교">
            {worlds.map((w) => (
              <button
                key={w.key}
                role="option"
                aria-selected={w.key === other.key}
                className={`pw-item ${w.key === 'me' ? 'pw-mine' : ''}`}
                disabled={w.key === 'me'}
                onClick={() => setPicked(w.key)}
              >
                <div>
                  <div className="title">{w.title}</div>
                  <div className="sub">{sub[w.key] ?? ''}</div>
                </div>
                <div className="r">
                  <div className="value tnum">{money(w.final_equity)}</div>
                  <div className="sub">{rate(w)}</div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  )
}

const RECENT = 7

/** 판단 기록: 날마다 목표 비중(큰 것 4개)과 비용. 누르면 그날 시장 요약. 처음엔 최근 일주일만. */
export function AiHistory({ bot }: { bot: Bot }) {
  const { data } = useAi(bot)
  const demo = useDemo()
  const [open, setOpen] = useState<string | null>(null)
  const [all, setAll] = useState(false)
  const days = data?.history ?? []
  if (days.length < 2) return null // 하루뿐이면 오늘의 판단과 같다
  const shown = all ? days : days.slice(0, RECENT)
  const top = (w: Record<string, number>) =>
    Object.entries(w)
      .filter(([, v]) => v > 0)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([s, v]) => `${label(s)} ${v}`)
      .join(' · ')
  return (
    <section className="block">
      <div className="block-head">
        <h2>판단 기록</h2>
        <span className="sub">최근 {days.length}일</span>
      </div>
      <div className="lines">
        {shown.map((d) => (
          <button key={d.session_date} className="line ai-day" aria-expanded={open === d.session_date} onClick={() => setOpen(open === d.session_date ? null : d.session_date)}>
            <div>
              <div className="title">
                <span className={`dot ${d.status === 'OK' ? 'ok' : 'warn'}`} />
                {md(d.session_date)}
              </div>
              <div className="muted small">{d.weights ? top(d.weights) : MISSED[d.status as Exclude<AiDay['status'], 'OK'>]}</div>
              {open === d.session_date && d.summary && <div className="small ai-day-summary">{d.summary}</div>}
            </div>
            {/* 데모는 예시 판단이라 비용이 없다 */}
            <div className="r faint small tnum">{!demo && d.cost != null ? money(d.cost) : ''}</div>
          </button>
        ))}
      </div>
      {days.length > RECENT && (
        <button className="link" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? '접기' : `${days.length - RECENT}일 더 보기`}
        </button>
      )}
    </section>
  )
}
