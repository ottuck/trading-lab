import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type Bot, type BotState, type CommandKind } from '../api'
import { ago, kstTime, money, percent, signedMoney, tone } from '../format'
import { sourceLabel } from '../source'
import { paramsText, STRATEGY_LABEL } from '../strategies'
import { PriceChart } from './PriceChart'

const STATE_LABEL: Record<BotState, string> = {
  RUNNING: '실행 중',
  PAUSED: '일시정지',
  STOPPED: '중지',
  ERROR: '오류',
}

const COMMANDS: { kind: CommandKind; label: string; style: string; enabled: (s: BotState) => boolean }[] = [
  { kind: 'START', label: '매매 시작', style: 'go', enabled: (s) => s !== 'RUNNING' },
  { kind: 'PAUSE', label: '일시정지', style: '', enabled: (s) => s === 'RUNNING' },
  { kind: 'STOP', label: '매매 중단', style: 'danger', enabled: (s) => s !== 'STOPPED' },
  { kind: 'RUN_ONCE', label: '수동 1회 실행', style: 'primary', enabled: () => true },
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
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(d)
}

function KV({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className="kv">
      <span className="label">{label}</span>
      <span className={`value ${className ?? ''}`}>{children}</span>
    </div>
  )
}

function Controls({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const [sent, setSent] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: (kind: CommandKind) => api.command(bot.id, kind),
    onSuccess: (_, kind) => {
      setSent(`${kind} 명령을 보냈습니다. Worker가 15초 안에 처리합니다.`)
      void qc.invalidateQueries({ queryKey: ['bots'] })
    },
    onError: (e) => setSent(`명령 실패: ${e.message}`),
  })
  const send = (kind: CommandKind) => {
    if (kind === 'STOP' && !window.confirm('봇을 중단할까요? 대기 중인 모의 주문은 남아 있습니다.')) return
    mutation.mutate(kind)
  }
  return (
    <>
      <div className="controls">
        {COMMANDS.map((c) => (
          <button
            key={c.kind}
            className={c.style}
            disabled={!c.enabled(bot.state) || mutation.isPending}
            onClick={() => send(c.kind)}
          >
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
  return (
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        봇 상태
      </div>
      <div className="controls">
        <span className="badge dry">DRY RUN</span>
        <span className={`badge state-${bot.state}`}>{STATE_LABEL[bot.state]}</span>
      </div>
      {bot.state_reason && <div className={bot.state === 'ERROR' ? 'alert' : 'notice'}>{bot.state_reason}</div>}
      <div className="kv-grid">
        <KV label="한국시간" className="md">{clock(now, 'Asia/Seoul')}</KV>
        <KV label="미국 동부시간" className="md">{clock(now, 'America/New_York')}</KV>
        <KV label="다음 평가" className="md">
          {bot.state === 'RUNNING' ? (
            <>
              {kstTime(bot.next_evaluation_at)} <span className="muted small">{ago(bot.next_evaluation_at)}</span>
            </>
          ) : (
            <span className="muted">실행 중 아님</span>
          )}
        </KV>
        <KV
          label="마지막 실행"
          className={run?.status === 'OK' ? 'up' : run?.status === 'ERROR' ? 'down' : run ? 'warn' : ''}
        >
          {run ? (
            <>
              {run.status} <span className="muted small">{ago(run.started_at)}</span>
            </>
          ) : (
            '—'
          )}
        </KV>
      </div>
      {run?.detail && run.status !== 'OK' && <div className="notice">{run.detail}</div>}
      <Controls bot={bot} />
    </section>
  )
}

function AccountCard({ bot }: { bot: Bot }) {
  const a = bot.account
  return (
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        모의 계좌 <span className="sub">실제 토스 계좌 아님</span>
      </div>
      <div className="kv">
        <span className="label">평가 자산</span>
        <span className="value big">{money(a.equity)}</span>
        <span className={`small ${tone(a.total_return)}`} style={{ fontWeight: 700 }}>
          {percent(a.total_return)} <span className="muted">· 초기 {money(a.initial_cash)}</span>
        </span>
      </div>
      <div className="kv-grid">
        <KV label="현금">{money(a.cash)}</KV>
        <KV label="미실현 손익" className={tone(a.unrealized_pnl)}>
          {signedMoney(a.unrealized_pnl)}
        </KV>
        <KV label="실현 손익" className={tone(a.realized_pnl)}>
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
      <div className="card-title">
        보유 종목 <span className="sub">({a.qty ? 1 : 0}개)</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>종목</th>
              <th className="num">수량</th>
              <th className="num">평균 단가</th>
              <th className="num">종가</th>
              <th className="num">평가금</th>
              <th className="num">손익</th>
              <th className="num">수익률</th>
            </tr>
          </thead>
          <tbody>
            {a.qty ? (
              <tr>
                <td>
                  <strong>{bot.symbol}</strong> <span className="muted small">{a.last_close_date}</span>
                </td>
                <td className="num">{a.qty}</td>
                <td className="num">{money(a.avg_cost)}</td>
                <td className="num">{money(a.last_close)}</td>
                <td className="num">{money(a.market_value)}</td>
                <td className={`num ${tone(a.unrealized_pnl)}`}>{signedMoney(a.unrealized_pnl)}</td>
                <td className={`num ${tone(ret)}`}>{percent(ret)}</td>
              </tr>
            ) : (
              <tr>
                <td colSpan={7} className="empty">
                  보유 종목 없음
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function DecisionCard({ bot }: { bot: Bot }) {
  const d = bot.last_decision
  return (
    <section className="card">
      <div className="card-title">
        마지막 판단 <span className="sub">{STRATEGY_LABEL[bot.strategy] ?? bot.strategy}</span>
      </div>
      {d ? (
        <>
          <div className="controls">
            <span className={`badge action-${d.action}`}>{d.action}</span>
            <span>
              <strong>{d.session_date}</strong> <span className="muted">종가 기준</span>
            </span>
          </div>
          <div className="reason">{d.reason}</div>
          <div className="muted small mono">
            {Object.entries(d.indicators)
              .map(([k, v]) => `${k} ${Number(v).toFixed(2)}`)
              .join('  ·  ')}
          </div>
          {d.blocked && <div className="alert">차단: {d.blocked}</div>}
          {bot.pending_order && (
            <div className="notice">
              다음 거래일 시가에 {bot.pending_order.side === 'BUY' ? '매수' : '매도'} 체결 예정 (모의)
            </div>
          )}
        </>
      ) : (
        <p className="muted">아직 판단이 없습니다. 시작하면 최근 완료 봉으로 바로 판단합니다.</p>
      )}
    </section>
  )
}

function SetupCard({ bot }: { bot: Bot }) {
  const risk = bot.risk
  return (
    <section className="card">
      <div className="card-title">전략·데이터</div>
      <div className="kv-grid">
        <KV label="전략" className="md">{STRATEGY_LABEL[bot.strategy] ?? bot.strategy}</KV>
        <KV label="파라미터">
          <span className="mono" style={{ fontSize: 14 }}>
            {paramsText(bot.params)}
          </span>
        </KV>
        <KV label="비용" className="md">
          {Number(bot.commission_rate) * 100}% · {bot.slippage_bps}bp
        </KV>
        <KV label="1회 주문 한도" className="md">{risk.max_order_value ? money(risk.max_order_value) : '없음'}</KV>
        <KV label="최신 거래일" className="md">{bot.data_latest_date ?? '—'}</KV>
        <KV label="데이터 수신">
          <span style={{ fontSize: 14 }}>{bot.data_fetched_at ? ago(bot.data_fetched_at) : '—'}</span>
        </KV>
      </div>
      <div className="chart-foot">{sourceLabel(bot.data_source)}</div>
    </section>
  )
}

function OrdersCard({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['orders', botId], queryFn: () => api.orders(botId) })
  return (
    <section className="card">
      <div className="card-title">
        모의 주문 <span className="sub">T 종가 판단 → T+1 시가 체결</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>판단일</th>
              <th>구분</th>
              <th>상태</th>
              <th>체결일</th>
              <th className="num">수량</th>
              <th className="num">가격</th>
              <th className="num">수수료</th>
              <th className="num">실현 손익</th>
            </tr>
          </thead>
          <tbody>
            {!data?.length && (
              <tr>
                <td colSpan={8} className="empty">
                  모의 주문 없음
                </td>
              </tr>
            )}
            {data?.map((o) => (
              <tr key={o.id}>
                <td>{o.signal_date}</td>
                <td className={o.side === 'BUY' ? 'up' : 'down'}>{o.side === 'BUY' ? '매수' : '매도'}</td>
                <td>{o.status === 'PENDING' ? '다음 시가 대기' : o.status === 'FILLED' ? '체결' : '미체결'}</td>
                <td>{o.fill_date ?? '—'}</td>
                <td className="num">{o.qty ?? '—'}</td>
                <td className="num">{money(o.price)}</td>
                <td className="num">{money(o.commission)}</td>
                <td className={`num ${tone(o.realized_pnl)}`}>{signedMoney(o.realized_pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function Dashboard({ bot }: { bot: Bot }) {
  return (
    <>
      <div className="bot-heading">
        <h2>{bot.name}</h2>
        <span className="muted">
          {bot.symbol} · {STRATEGY_LABEL[bot.strategy] ?? bot.strategy}
        </span>
      </div>
      <div className="row">
        <StatusCard bot={bot} />
        <AccountCard bot={bot} />
      </div>
      <HoldingsCard bot={bot} />
      <div className="row">
        <DecisionCard bot={bot} />
        <SetupCard bot={bot} />
      </div>
      <PriceChart bot={bot} />
      <OrdersCard botId={bot.id} />
    </>
  )
}
