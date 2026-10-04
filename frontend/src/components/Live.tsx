import { useMutation, useQueryClient } from '@tanstack/react-query'
import { liveApi, type LiveOrder } from '../api'
import { ago, dollars, shares } from '../format'
import { dayLabel, liveStatus, useLive } from '../live'

/* 실제로 따라 사기 (실거래 R2). 실제 계좌 금액은 원화로 바꿔 보지 않고 늘 달러로 보여준다. */

/** 홈 맨 위: 승인을 기다리는 실제 주문. 처음 몇 번과 한도를 넘는 주문은 사람이 눌러야 나간다. */
export function LiveApprovals() {
  const qc = useQueryClient()
  const { data } = useLive()
  const act = useMutation({
    mutationFn: ({ id, ok }: { id: number; ok: boolean }) => (ok ? liveApi.approve(id) : liveApi.decline(id)),
    onSuccess: (live) => qc.setQueryData(['live'], live),
  })
  const waiting = data?.orders.filter((o) => o.state === 'WAITING_APPROVAL') ?? []
  if (!data?.trader || !waiting.length) return null
  return (
    <section className="block live-ask">
      <div className="block-head">
        <h2>실제로 살까요?</h2>
      </div>
      {data.halted && <div className="notice">실제 주문을 멈춰 둔 상태예요. 설정에서 다시 시작해야 승인할 수 있어요.</div>}
      {waiting.map((o) => (
        <div key={o.id} className="live-ask-row">
          <div>
            <div className="title">
              {o.symbol} <b className="tnum">{dollars(o.amount)}</b>어치
            </div>
            <div className="faint small">
              {dayLabel(o.trade_date)} 장이 열리면 실제 계좌에서 사요 · {o.bot_name ?? '봇'}
            </div>
          </div>
          <div className="controls">
            <button className="primary" disabled={act.isPending || data.halted} onClick={() => act.mutate({ id: o.id, ok: true })}>
              승인
            </button>
            <button className="ghost" disabled={act.isPending} onClick={() => act.mutate({ id: o.id, ok: false })}>
              이번엔 안 사기
            </button>
          </div>
        </div>
      ))}
      {act.error && <span className="bad small">{act.error.message}</span>}
    </section>
  )
}

/** 봇이 낸 실제 주문 목록 (최근 것부터). */
export function LiveOrderList({ orders, limit = 5 }: { orders: LiveOrder[]; limit?: number }) {
  if (!orders.length) return <div className="muted">아직 없어요</div>
  return (
    <>
      {orders.slice(0, limit).map((o) => (
        <div key={o.id} className="log-item">
          <span className={`pip ${o.state === 'FILLED' ? 'rise' : ['REJECTED', 'CANCELED', 'UNKNOWN'].includes(o.state) ? 'warn' : ''}`} />
          <div>
            <div className="title">
              {o.symbol} {dollars(o.filled_amount ?? o.amount)}
              {o.filled_qty && Number(o.filled_qty) > 0 ? ` · ${shares(o.filled_qty)}주` : ''}
            </div>
            <div className="body">
              {liveStatus(o)} · {dayLabel(o.trade_date)}
            </div>
          </div>
          <time dateTime={o.updated_at}>{ago(o.updated_at)}</time>
        </div>
      ))}
    </>
  )
}
