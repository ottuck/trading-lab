import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type Bot, type BotState, type CommandKind } from '../api'
import { ago, kstTime, money, percent, signedMoney, tone } from '../format'
import { strategyTitle, useStrategies } from '../strategies'
import { Term } from './Help'
import { PriceChart } from './PriceChart'

const STATE_LABEL: Record<BotState, string> = {
  RUNNING: '돌아가는 중',
  PAUSED: '잠시 멈춤',
  STOPPED: '멈춤',
  ERROR: '문제 발생',
}

const COMMANDS: { kind: CommandKind; label: string; style: string; enabled: (s: BotState) => boolean }[] = [
  { kind: 'START', label: '매매 시작', style: 'go', enabled: (s) => s !== 'RUNNING' },
  { kind: 'PAUSE', label: '잠시 멈춤', style: '', enabled: (s) => s === 'RUNNING' },
  { kind: 'STOP', label: '매매 중단', style: 'danger', enabled: (s) => s !== 'STOPPED' },
  { kind: 'RUN_ONCE', label: '지금 판단해 보기', style: 'primary', enabled: () => true },
]

function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function clock(d: Date, timeZone: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone,
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d)
}

function KV({ label, children, className }: { label: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className="kv">
      <span className="label">{label}</span>
      <span className={`value md ${className ?? ''}`}>{children}</span>
    </div>
  )
}

function Controls({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const [sent, setSent] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: (kind: CommandKind) => api.command(bot.id, kind),
    onSuccess: () => {
      setSent('요청했어요. 15초 안에 반영돼요.')
      void qc.invalidateQueries({ queryKey: ['bots'] })
    },
    onError: (e) => setSent(`요청하지 못했어요: ${e.message}`),
  })
  const send = (kind: CommandKind) => {
    if (kind === 'STOP' && !window.confirm('매매를 중단할까요? 예정된 거래는 그대로 남아요.')) return
    mutation.mutate(kind)
  }
  return (
    <>
      <div className="controls">
        {COMMANDS.map((c) => (
          <button key={c.kind} className={c.style} disabled={!c.enabled(bot.state) || mutation.isPending} onClick={() => send(c.kind)}>
            {c.label}
          </button>
        ))}
      </div>
      {sent && <div className="muted small">{sent}</div>}
    </>
  )
}

function StatusCard({ bot }: { bot: Bot }) {
  const now = useNow()
  const run = bot.last_run
  const runOk = run?.status === 'OK'
  return (
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        내 봇
      </div>
      <div className="controls">
        <span className="badge dry">
          <Term k="모의 투자" />
        </span>
        <span className={`badge state-${bot.state}`}>{STATE_LABEL[bot.state]}</span>
      </div>
      {bot.state_reason && (
        <div className={bot.state === 'ERROR' ? 'alert' : 'notice'}>
          {bot.state === 'PAUSED' ? '잠시 멈춰 있어요. [매매 시작]을 누르면 다시 판단해요.' : bot.state_reason}
        </div>
      )}
      <div className="kv-grid">
        <KV label="한국 시각">{clock(now, 'Asia/Seoul')}</KV>
        <KV label="뉴욕 시각">{clock(now, 'America/New_York')}</KV>
        <KV label="다음 판단">
          {bot.state === 'RUNNING' ? (
            <>
              {kstTime(bot.next_evaluation_at).replace(' KST', '')}{' '}
              <span className="muted small">{ago(bot.next_evaluation_at)}</span>
            </>
          ) : (
            <span className="muted">멈춘 상태예요</span>
          )}
        </KV>
        <KV label="마지막 판단" className={runOk ? 'ok' : run?.status === 'ERROR' ? 'bad' : run ? 'warn' : ''}>
          {run ? (
            <>
              {runOk ? '정상' : run.status === 'ERROR' ? '실패' : '미룸'} <span className="muted small">{ago(run.started_at)}</span>
            </>
          ) : (
            '—'
          )}
        </KV>
      </div>
      <Controls bot={bot} />
    </section>
  )
}

function AccountCard({ bot }: { bot: Bot }) {
  const a = bot.account
  return (
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        내 모의 투자금 <span className="sub">실제 계좌와 무관해요</span>
      </div>
      <div className="kv">
        <span className="label">
          <Term k="지금 가치" />
        </span>
        <span className="value big">{money(a.equity)}</span>
        <span className={`small ${tone(a.total_return)}`} style={{ fontWeight: 700 }}>
          {percent(a.total_return)} <span className="muted">· 시작 {money(a.initial_cash)}</span>
        </span>
      </div>
      <div className="kv-grid">
        <KV label="남은 현금">{money(a.cash)}</KV>
        <KV label={<Term k="평가 손익" />} className={tone(a.unrealized_pnl)}>
          {signedMoney(a.unrealized_pnl)}
        </KV>
        <KV label={<Term k="확정 손익" />} className={tone(a.realized_pnl)}>
          {signedMoney(a.realized_pnl)}
        </KV>
      </div>
    </section>
  )
}

function HoldingsCard({ bot }: { bot: Bot }) {
  const a = bot.account
  const ret = a.qty && Number(a.avg_cost) ? String(Number(a.last_close) / Number(a.avg_cost) - 1) : null
  return (
    <section className="card">
      <div className="card-title">들고 있는 주식</div>
      {a.qty ? (
        <div className="holding">
          <div>
            <div className="value md">{bot.symbol}</div>
            <div className="muted small">
              {a.qty}주 · 산 가격 {money(a.avg_cost)}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="value md">{money(a.market_value)}</div>
            <div className={`small ${tone(a.unrealized_pnl)}`} style={{ fontWeight: 700 }}>
              {signedMoney(a.unrealized_pnl)} ({percent(ret)})
            </div>
          </div>
        </div>
      ) : (
        <div className="empty">아직 들고 있는 주식이 없어요. 현금으로 기다리는 중이에요.</div>
      )}
      {a.qty > 0 && <div className="chart-foot">지금 가격 {money(a.last_close)} ({a.last_close_date} 장 마감 기준)</div>}
    </section>
  )
}

function DecisionCard({ bot }: { bot: Bot }) {
  const d = bot.last_decision
  const [more, setMore] = useState(false)
  const head = d?.action === 'BUY' ? '🟢 매수 신호' : d?.action === 'SELL' ? '🔴 매도 신호' : d?.holding ? '✋ 그대로 들고 있기' : '⏳ 기다리기'
  return (
    <section className="card">
      <div className="card-title">
        <Term k="오늘의 판단" />
        {d && <span className="sub">{d.session_date} 장 마감 기준</span>}
      </div>
      {d ? (
        <>
          <div className="value md">{head}</div>
          <div className="reason">{d.plain_action || d.reason}</div>
          {d.plain_reason && <p className="muted" style={{ margin: '6px 0 0' }}>{d.plain_reason}</p>}
          {d.blocked && <div className="alert">사지 못했어요: {d.blocked}</div>}
          <button className="link" onClick={() => setMore(!more)}>
            {more ? '숨기기' : '자세한 숫자 보기'}
          </button>
          {more && (
            <div className="muted small mono">
              {d.reason} ·{' '}
              {Object.entries(d.indicators)
                .map(([k, v]) => `${k} ${Number(v).toFixed(2)}`)
                .join(' · ')}
            </div>
          )}
        </>
      ) : (
        <p className="muted">아직 판단이 없어요. [매매 시작]을 누르면 가장 최근 가격으로 바로 판단해요.</p>
      )}
    </section>
  )
}

function StrategyCard({ bot }: { bot: Bot }) {
  const { byName } = useStrategies()
  const info = byName[bot.strategy]
  return (
    <section className="card">
      <div className="card-title">전략</div>
      <div className="value md">{strategyTitle(info, bot.strategy)}</div>
      {info && <p className="muted" style={{ margin: '6px 0 10px' }}>{info.summary}</p>}
      {info && (
        <div className="controls">
          <span className="chip">위험 {info.risk}</span>
          <span className="chip">거래 {info.trades}</span>
          <span className="chip">{bot.symbol}</span>
        </div>
      )}
      <div className="chart-foot">
        가격 정보: {bot.data_latest_date ?? '—'} 장 마감까지 · {bot.data_fetched_at ? `${ago(bot.data_fetched_at)} 업데이트` : '—'}
      </div>
    </section>
  )
}

function ActivityCard({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['activity', botId], queryFn: () => api.activity(botId) })
  return (
    <section className="card">
      <div className="card-title">최근 활동</div>
      {!data?.length && <div className="empty">아직 활동이 없어요.</div>}
      <ul className="activity">
        {data?.map((a) => (
          <li key={a.id} className={`lvl-${a.level}`}>
            <span className="icon">{a.icon}</span>
            <div>
              <div className="title">{a.title}</div>
              {a.body && <div className="muted small body">{a.body}</div>}
              <div className="faint small">{ago(a.at)}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function OrdersCard({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['orders', botId], queryFn: () => api.orders(botId) })
  return (
    <section className="card">
      <div className="card-title">
        거래 내역 <span className="sub">모의 투자</span>
      </div>
      {!data?.length && <div className="empty">아직 거래가 없어요.</div>}
      <ul className="trades">
        {data?.map((o) => {
          const buy = o.side === 'BUY'
          const status = o.status === 'PENDING' ? '다음 장에 예정' : o.status === 'FILLED' ? '' : '사지 못함'
          return (
            <li key={o.id}>
              <span className={`side ${buy ? 'rise' : 'fall'}`}>{buy ? '샀어요' : '팔았어요'}</span>
              <div>
                <div>
                  {o.qty ? `${o.qty}주 · 한 주 ${money(o.price)}` : status}
                  {o.qty && status ? ` · ${status}` : ''}
                </div>
                <div className="faint small">
                  {o.fill_date ?? `${o.signal_date} 판단`} {o.commission ? `· 수수료 ${money(o.commission)}` : ''}
                </div>
              </div>
              {o.realized_pnl != null && <span className={`pnl ${tone(o.realized_pnl)}`}>{signedMoney(o.realized_pnl)}</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function Dashboard({ bot }: { bot: Bot }) {
  const { byName } = useStrategies()
  return (
    <>
      <div className="bot-heading">
        <h2>{bot.name}</h2>
        <span className="muted">
          {bot.symbol} · {strategyTitle(byName[bot.strategy], bot.strategy)}
        </span>
      </div>
      <div className="row">
        <StatusCard bot={bot} />
        <AccountCard bot={bot} />
      </div>
      <div className="row">
        <DecisionCard bot={bot} />
        <HoldingsCard bot={bot} />
      </div>
      <PriceChart bot={bot} />
      <div className="row">
        <ActivityCard botId={bot.id} />
        <OrdersCard botId={bot.id} />
      </div>
      <StrategyCard bot={bot} />
    </>
  )
}
