import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Bot, type BotState, type CommandKind } from '../api'
import { ago, kstTime, money, percent, signedMoney, tone } from '../format'
import { sourceLabel } from '../source'

const STATE_LABEL: Record<BotState, string> = {
  RUNNING: '실행 중',
  PAUSED: '일시정지',
  STOPPED: '중지',
  ERROR: '오류',
}

const COMMANDS: { kind: CommandKind; label: string; enabled: (s: BotState) => boolean }[] = [
  { kind: 'START', label: '시작', enabled: (s) => s !== 'RUNNING' },
  { kind: 'PAUSE', label: '일시정지', enabled: (s) => s === 'RUNNING' },
  { kind: 'STOP', label: '중지', enabled: (s) => s !== 'STOPPED' },
  { kind: 'RUN_ONCE', label: '수동 1회 실행', enabled: () => true },
]

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
    if (kind === 'STOP' && !window.confirm('봇을 중지할까요? 대기 중인 모의 주문은 남아 있습니다.')) return
    mutation.mutate(kind)
  }
  return (
    <div className="controls">
      {COMMANDS.map((c) => (
        <button
          key={c.kind}
          className={c.kind === 'STOP' ? 'danger' : ''}
          disabled={!c.enabled(bot.state) || mutation.isPending}
          onClick={() => send(c.kind)}
        >
          {c.label}
        </button>
      ))}
      {sent && <span className="muted small">{sent}</span>}
    </div>
  )
}

function Stat({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return (
    <div className="stat">
      <div className="muted small">{label}</div>
      <div className={`stat-value ${className ?? ''}`}>{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  )
}

function RecentOrders({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['orders', botId], queryFn: () => api.orders(botId) })
  if (!data?.length) return <p className="muted">아직 모의 주문이 없습니다.</p>
  return (
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
        {data.map((o) => (
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
  )
}

export function BotPanel({ bot }: { bot: Bot }) {
  const a = bot.account
  const d = bot.last_decision
  const run = bot.last_run
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>
            {bot.name} <span className="muted">· {bot.symbol}</span>
          </h2>
          <div className="muted small">
            {bot.strategy} {JSON.stringify(bot.params)} · 수수료 {Number(bot.commission_rate) * 100}% · 슬리피지{' '}
            {bot.slippage_bps}bp
          </div>
        </div>
        <span className={`badge state-${bot.state}`}>{STATE_LABEL[bot.state]}</span>
      </div>
      {bot.state_reason && <p className={bot.state === 'ERROR' ? 'alert' : 'notice'}>{bot.state_reason}</p>}
      <Controls bot={bot} />

      <h3>1. 정상 실행 여부</h3>
      <div className="grid">
        <Stat
          label="마지막 실행"
          value={run ? `${run.status}` : '—'}
          sub={run ? `${kstTime(run.started_at)} (${ago(run.started_at)})` : undefined}
          className={run?.status === 'OK' ? 'up' : run?.status === 'ERROR' ? 'down' : 'warn'}
        />
        <Stat
          label="다음 평가"
          value={bot.state === 'RUNNING' ? kstTime(bot.next_evaluation_at) : '봇이 실행 중이 아님'}
          sub={bot.state === 'RUNNING' ? ago(bot.next_evaluation_at) : undefined}
        />
        <Stat
          label="데이터 최신 거래일"
          value={bot.data_latest_date ?? '—'}
          sub={bot.data_fetched_at ? `${bot.data_source === 'toss' ? '토스 일봉' : sourceLabel(bot.data_source)} · 수신 ${ago(bot.data_fetched_at)}` : undefined}
        />
      </div>
      {run?.detail && run.status !== 'OK' && <p className="notice">{run.detail}</p>}

      <h3>2. 마지막 판단</h3>
      {d ? (
        <div className="decision">
          <div>
            <span className={`badge action-${d.action}`}>{d.action}</span> <strong>{d.session_date}</strong> 종가 기준
          </div>
          <p>{d.reason}</p>
          {d.blocked && <p className="alert">차단: {d.blocked}</p>}
          <div className="muted small">
            {Object.entries(d.indicators)
              .map(([k, v]) => `${k} ${Number(v).toFixed(2)}`)
              .join(' · ')}
          </div>
          {bot.pending_order && (
            <p className="notice">
              다음 거래일 시가에 {bot.pending_order.side === 'BUY' ? '매수' : '매도'} 체결 예정 (모의)
            </p>
          )}
        </div>
      ) : (
        <p className="muted">아직 판단이 없습니다. 시작하면 최근 완료 봉으로 바로 판단합니다.</p>
      )}

      <h3>3. 모의 잔고 (실제 토스 계좌 아님)</h3>
      <div className="grid">
        <Stat label="평가 자산" value={money(a.equity)} sub={`초기 ${money(a.initial_cash)}`} />
        <Stat label="총 수익률" value={percent(a.total_return)} className={tone(a.total_return)} />
        <Stat label="현금" value={money(a.cash)} />
        <Stat
          label="보유"
          value={`${a.qty}주`}
          sub={a.qty ? `평균 ${money(a.avg_cost)} · 종가 ${money(a.last_close)} (${a.last_close_date})` : undefined}
        />
        <Stat label="미실현 손익" value={signedMoney(a.unrealized_pnl)} className={tone(a.unrealized_pnl)} />
        <Stat label="실현 손익" value={signedMoney(a.realized_pnl)} className={tone(a.realized_pnl)} />
      </div>

      <h3>최근 모의 주문</h3>
      <RecentOrders botId={bot.id} />
    </section>
  )
}
