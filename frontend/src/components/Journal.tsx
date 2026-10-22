import { useQuery } from '@tanstack/react-query'
import { useState, useSyncExternalStore } from 'react'
import { botApi, type Bot, type Journal, type JournalArchive, type JournalDay, type JournalLine, type JournalTrade } from '../api'
import { money, shares, signedMoney, tone } from '../format'
import { openArchive, openBot, openJournal, useSelectedBot } from '../selectedBot'
import { isAiBot } from '../strategies'
import { demoAiNote, useDemo } from '../demo'
import { BasisList } from './AiBot'
import { BotSide, BotTabs } from './Dashboard'

/* 매매일지 (#journal/3): 판단일마다 무엇을 근거로 어떻게 했고 주문이 어떻게 체결됐는지.
   기록은 모두 모의 투자다. 조용한 날(주문·입금·비중 변화 없음)은 이어진 만큼 한 줄로 묶는다.
   처음부터 다시 시작하거나 지운 봇의 일지는 보관본으로 본다 (#journal/archive/7). */

const CASH = 'CASH'
const WEEK = '일월화수목금토'

/** '2026-10-21' → { y, m, d, w: '화' } (미국 장 날짜라 시간대 변환 없이 그대로 읽는다). */
function parts(date: string) {
  const [y, m, d] = date.split('-').map(Number)
  return { y, m, d, w: WEEK[new Date(y, m - 1, d).getDay()] }
}

function md(date: string | null) {
  if (!date) return '—'
  const { y, m, d } = parts(date)
  return `${y === new Date().getFullYear() ? '' : `${y}년 `}${m}월 ${d}일`
}

/** '2026-10' → '10월', 올해가 아니면 '2025년 12월'. */
function monthTitle(key: string) {
  const [y, m] = key.split('-').map(Number)
  return `${y === new Date().getFullYear() ? '' : `${y}년 `}${m}월`
}

const label = (symbol: string) => (symbol === CASH ? '현금' : symbol)

function markOf(day: JournalDay) {
  if (day.trades.some((t) => t.side === 'SELL')) return day.trades.some((t) => t.side === 'BUY') ? 'both' : 'fall'
  return day.trades.length ? 'rise' : ''
}

type Group = { quiet: false; day: JournalDay } | { quiet: true; days: JournalDay[] }

/** 이어진 조용한 날 중 한 일이 같은 날들을 한 묶음으로 (최근 날부터). */
function grouped(days: JournalDay[]): Group[] {
  const out: Group[] = []
  for (const day of days) {
    const last = out.at(-1)
    if (!day.quiet) out.push({ quiet: false, day })
    else if (last?.quiet && last.days[0].headline === day.headline) last.days.push(day)
    else out.push({ quiet: true, days: [day] })
  }
  return out
}

/** 달마다 나눈다: [['2026-10', groups], ...] */
function byMonth(days: JournalDay[]): [string, JournalDay[]][] {
  const months = new Map<string, JournalDay[]>()
  for (const d of days) {
    const key = d.date.slice(0, 7)
    months.set(key, [...(months.get(key) ?? []), d])
  }
  return [...months]
}

// 주문 상태마다 동사: 체결됐으면 "샀어요", 다음 장을 기다리면 "살 예정", 체결되지 않았으면 "못 샀어요"
const VERB: Record<JournalTrade['status'], [string, string]> = {
  FILLED: ['샀어요', '팔았어요'],
  PENDING: ['살 예정', '팔 예정'],
  UNFILLED: ['못 샀어요', '못 팔았어요'],
}
const STATUS: Record<JournalTrade['status'], string> = { PENDING: '다음 날 장이 열릴 때 체결돼요', FILLED: '', UNFILLED: '체결할 때 현금이나 한도가 모자랐어요' }

function Trade({ t }: { t: JournalTrade }) {
  const buy = t.side === 'BUY'
  return (
    <div className="jr-trade">
      <span className={`side-tag ${buy ? 'rise' : 'fall'}`}>
        {t.symbol} {VERB[t.status][buy ? 0 : 1]}
      </span>
      {t.status === 'FILLED' ? (
        <span className="muted tnum">
          {md(t.fill_date)} 장이 열릴 때 · {shares(t.qty)}주 × {money(t.price)} = <b>{money(t.amount)}</b>
          {t.realized_pnl != null && <span className={tone(t.realized_pnl)}> · 확정 손익 {signedMoney(t.realized_pnl)}</span>}
        </span>
      ) : (
        <span className="faint">{STATUS[t.status]}</span>
      )}
    </div>
  )
}

function Weight({ line }: { line: JournalLine }) {
  const before = Math.round(Number(line.before ?? 0))
  const target = line.target ?? before
  return (
    <div className="jr-line">
      <div className="jr-line-head">
        <span className="title">{label(line.symbol)}</span>
        <span className="tnum">
          {before !== target && <span className="faint">{before}% → </span>}
          <b>{target}%</b>
        </span>
      </div>
      {line.reason && <div className="muted">{line.reason}</div>}
      {line.blocked && <div className="bad small">사지 못했어요: {line.blocked}</div>}
    </div>
  )
}

function Rule({ line, multi }: { line: JournalLine; multi: boolean }) {
  return (
    <div className="jr-line">
      <div className="muted">
        {multi && <b className="jr-sym">{line.symbol}</b>}
        {line.reason}
      </div>
      {line.numbers && <div className="faint small">{line.numbers}</div>}
      {line.blocked && <div className="bad small">사지 못했어요: {line.blocked}</div>}
    </div>
  )
}

function Entry({ day, compact = false }: { day: JournalDay; compact?: boolean }) {
  const ai = day.ai
  const [more, setMore] = useState(false)
  const { m, d, w } = parts(day.date)
  const multi = day.lines.length > 1
  return (
    <article className={`jr-day ${compact ? 'compact' : ''}`}>
      <div className="jr-date">
        <span className="tnum">
          {m}.{d}
        </span>
        <span className="faint">{w}</span>
      </div>
      <div className="jr-body">
        <div className="jr-head">
          <span className={`mark ${markOf(day)}`} />
          {day.headline}
        </div>
        {day.deposit != null && <div className="faint small">입금 {money(day.deposit)}</div>}
        {day.basis.length > 0 && <BasisList items={day.basis} />}
        {/* 근거가 따로 없던 예전 AI 판단은 시장 요약이 근거다 */}
        {day.summary && !day.basis.length && <p className="jr-summary">{day.summary}</p>}
        {day.trades.length > 0 && (
          <div className="jr-trades">
            {day.trades.map((t, i) => (
              <Trade key={i} t={t} />
            ))}
          </div>
        )}
        {(ai ? day.lines.length > 0 || !!day.summary || day.sources.length > 0 : day.lines.length > 0) &&
          (more || (!ai && !compact) ? (
            <div className="jr-more">
              {ai && day.summary && day.basis.length > 0 && <p className="jr-summary">{day.summary}</p>}
              {day.lines.map((ln) => (ai ? <Weight key={ln.symbol} line={ln} /> : <Rule key={ln.symbol} line={ln} multi={multi} />))}
              {day.sources.length > 0 && (
                <ul className="ai-links">
                  {day.sources.map((s) => (
                    <li key={s.url}>
                      <a href={s.url} target="_blank" rel="noopener noreferrer">
                        {s.title}
                      </a>
                      <span className="faint small"> · {new URL(s.url).hostname.replace(/^www\./, '')}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <button className="link small" aria-expanded={false} onClick={() => setMore(true)}>
              {ai ? `종목별 비중과 이유${day.sources.length ? `, 근거 기사 ${day.sources.length}개` : ''}` : '이유 보기'}
            </button>
          ))}
      </div>
    </article>
  )
}

function Quiet({ days }: { days: JournalDay[] }) {
  const [open, setOpen] = useState(false)
  if (days.length === 1) return <Entry day={days[0]} compact />
  const last = parts(days[0].date)
  const first = parts(days.at(-1)!.date)
  const range = first.m === last.m ? `${first.m}.${first.d}–${last.d}` : `${first.m}.${first.d}–${last.m}.${last.d}`
  return (
    <div className="jr-quiet">
      <button className="jr-quiet-row" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="jr-date faint tnum">{range}</span>
        <span className="muted">
          {days.length}일 동안 {days[0].headline}
        </span>
        <span className="faint small">{open ? '접기' : '펼치기'}</span>
      </button>
      {open && days.map((d) => <Entry key={d.date} day={d} compact />)}
    </div>
  )
}

function Days({ journal }: { journal: Journal }) {
  if (!journal.days.length)
    return <div className="line-empty">아직 판단이 없어요. 첫 판단을 하면 이곳에 날마다 기록이 쌓여요.</div>
  return (
    <>
      {byMonth(journal.days).map(([key, days]) => {
        const trades = days.reduce((n, d) => n + d.trades.filter((t) => t.status === 'FILLED').length, 0)
        return (
          <section key={key} className="block jr-month">
            <div className="block-head">
              <h2>{monthTitle(key)}</h2>
              <span className="sub">
                판단 {days.length}일 · 거래 {trades}번
              </span>
            </div>
            <div className="jr-days">
              {grouped(days).map((g) =>
                g.quiet ? <Quiet key={g.days[0].date} days={g.days} /> : <Entry key={g.day.date} day={g.day} />,
              )}
            </div>
          </section>
        )
      })}
    </>
  )
}

function Archives({ items, title }: { items: JournalArchive[]; title: string }) {
  if (!items.length) return null
  return (
    <section className="block">
      <div className="block-head">
        <h2>{title}</h2>
      </div>
      <div className="lines">
        {items.map((a) => (
          <button key={a.id} className="line jr-archive" onClick={() => openArchive(a.id)}>
            <div>
              <div className="title">{a.bot_name}</div>
              <div className="muted small">
                {md(a.first_date)} ~ {md(a.last_date)} · {a.why} 보관
              </div>
            </div>
            <span className="faint">→</span>
          </button>
        ))}
      </div>
    </section>
  )
}

const NOTE = '모의 투자 기록이에요. 판단은 미국 장이 끝난 뒤 그날 가격으로 하고, 주문은 다음 날 장이 열릴 때 체결돼요.'

/** 지금 봇의 일지: 봇을 바꿔 가며 보고, 아래에 처음부터 다시 시작하며 보관한 일지와 지운 봇의 일지. */
function BotJournal({ bots }: { bots: Bot[] }) {
  const bot = useSelectedBot(bots)
  const { data, error } = useQuery({ queryKey: ['journal', bot.id], queryFn: () => botApi.journal(bot.id) })
  const deleted = useQuery({ queryKey: ['journal', 'deleted'], queryFn: botApi.deletedJournals })
  const pick = (b: Bot) => openJournal(b.id)
  const ai = isAiBot(bot)
  const demo = useDemo()
  return (
    <div className="home">
      <div className="home-main" key={bot.id}>
        <button className="link back" onClick={() => openBot(bot.id)}>
          ← {bot.name}
        </button>
        <BotTabs bots={bots} current={bot} onPick={pick} />
        <div className="jr-top">
          <h1>{bot.name} 매매일지</h1>
          <p className="decision-why">
            {ai
              ? 'AI가 날마다 무엇을 근거로 비중을 정했고, 그래서 무엇을 사고팔았는지 남겨요.'
              : '날마다 어떤 가격이라 사거나 기다렸는지, 그래서 무엇을 샀는지 남겨요.'}
          </p>
          <div className="strategy-meta">{NOTE}</div>
          {ai && demo && <div className="strategy-meta">{demoAiNote(bot.strategy === 'ai_candle')}</div>}
        </div>
        {error ? (
          <div className="line-empty">불러오지 못했어요: {error.message}</div>
        ) : !data ? (
          <div className="line-empty">불러오는 중…</div>
        ) : (
          <>
            <Days journal={data} />
            <Archives items={data.archives} title="처음부터 다시 시작하기 전 일지" />
          </>
        )}
        <Archives items={deleted.data ?? []} title="지운 봇의 일지" />
      </div>
      <BotSide bots={bots} current={bot} onPick={pick} />
    </div>
  )
}

/** 보관한 일지 한 권 (읽기만). */
function ArchivedJournal({ id, bots }: { id: number; bots: Bot[] }) {
  const { data, error } = useQuery({ queryKey: ['journal', 'archive', id], queryFn: () => botApi.archivedJournal(id) })
  const alive = bots.find((b) => b.id === data?.bot_id)
  return (
    <div className="home">
      <div className="home-main">
        <button className="link back" onClick={() => (alive ? openJournal(alive.id) : history.back())}>
          ← {alive ? `${alive.name} 매매일지` : '뒤로'}
        </button>
        {error ? (
          <div className="line-empty">불러오지 못했어요: {error.message}</div>
        ) : !data ? (
          <div className="line-empty">불러오는 중…</div>
        ) : (
          <>
            <div className="jr-top">
              <h1>{data.bot_name} 매매일지</h1>
              <p className="decision-why">
                {alive ? '처음부터 다시 시작하기 전까지의 기록이에요.' : '지운 봇의 기록이에요.'} 보관본이라 바뀌지 않아요.
              </p>
              <div className="strategy-meta">{NOTE}</div>
            </div>
            <Days journal={data} />
          </>
        )}
      </div>
    </div>
  )
}

function useHash() {
  return useSyncExternalStore(
    (l) => {
      window.addEventListener('hashchange', l)
      return () => window.removeEventListener('hashchange', l)
    },
    () => location.hash,
  )
}

/** 봇이 하나도 없을 때도 지운 봇의 일지는 볼 수 있다. */
function NoBots() {
  const deleted = useQuery({ queryKey: ['journal', 'deleted'], queryFn: botApi.deletedJournals })
  return (
    <div className="home">
      <div className="home-main">
        <div className="jr-top">
          <h1>매매일지</h1>
          <p className="decision-why">지금은 봇이 없어요. 봇을 만들면 날마다 기록이 이곳에 쌓여요.</p>
        </div>
        <Archives items={deleted.data ?? []} title="지운 봇의 일지" />
      </div>
    </div>
  )
}

export function JournalView({ bots }: { bots: Bot[] }) {
  const archive = /^#journal\/archive\/(\d+)$/.exec(useHash())
  if (archive) return <ArchivedJournal id={Number(archive[1])} bots={bots} />
  if (!bots.length) return <NoBots />
  return <BotJournal bots={bots} />
}
