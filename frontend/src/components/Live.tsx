import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, liveApi, type LiveOrder } from '../api'
import { useDemo } from '../demo'
import { ago, dollars, percent, shares, signedDollars, tone, won } from '../format'
import { dayLabel, liveStatus, toggleBalanceHidden, useBalanceHidden, useLive } from '../live'
import { sourceLabel } from '../source'

/* 실제로 따라 사기 (실거래 R2). 실제 계좌 금액은 원화로 바꿔 보지 않고 늘 달러로 보여준다. */

/** 홈 맨 위: 승인을 기다리는 실제 주문. 한도를 넘는 주문은 사람이 눌러야 나간다. */
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
        <h2>{waiting.some((o) => o.side === 'SELL') ? '실제로 주문할까요?' : '실제로 살까요?'}</h2>
      </div>
      {data.halted && <div className="notice">실제 주문을 멈춰 둔 상태예요. 설정에서 다시 시작해야 승인할 수 있어요.</div>}
      {waiting.map((o) => (
        <div key={o.id} className="live-ask-row">
          <div>
            <div className="title">
              {o.side === 'SELL' ? (
                <>
                  {o.symbol} <b className="tnum">{shares(o.quantity)}주</b> 모두 팔기{' '}
                  <span className="muted">(약 {dollars(o.amount)})</span>
                </>
              ) : (
                <>
                  {o.symbol} <b className="tnum">{dollars(o.amount)}</b>어치 사기
                </>
              )}
            </div>
            <div className="faint small">
              {dayLabel(o.trade_date)} 장이 열리면 실제 계좌에서 {o.side === 'SELL' ? '팔아요' : '사요'} · {o.bot_name ?? '봇'}
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
              {o.side === 'SELL' ? '팔기 · ' : ''}
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

/** 홈 오른쪽: 실제 증권사 계좌 잔액과 이번 달 실제로 산 금액. 누르면 금액을 가린다. */
export function AccountCard() {
  const demo = useDemo()
  const { data: account } = useQuery({
    queryKey: ['broker-account'],
    queryFn: api.brokerAccount,
    refetchInterval: 60_000,
    enabled: !demo,
  })
  const { data: live } = useLive()
  const hidden = useBalanceHidden()
  if (!account?.fetched_at) return null
  const bought = Number(live?.bought_this_month ?? 0) // 서버가 이번 달 산(체결된) 금액을 모두 더한다
  const sold = Number(live?.sold_this_month ?? 0)
  // 봇이 산 주식의 평가 손익, 팔아서 확정된 손익 (봇이 낸 주문만, 수수료 제외 어림값)
  const heldCost = Number(live?.held_cost ?? 0)
  const unrealized = Number(live?.held_value ?? 0) - heldCost
  const realized = Number(live?.realized_total ?? 0)
  const everSold = Number(live?.sold_total ?? 0) > 0
  const waiting = (live?.orders ?? []).filter((o) => o.state === 'WAITING_APPROVAL').length
  // 가릴 때는 숫자 자리를 같은 높이의 둥근 막대로 바꿔 레이아웃이 흔들리지 않게 한다.
  const amount = (text: string, width: string) =>
    hidden ? <span className="redact" style={{ width }} aria-label="가린 금액" /> : text
  return (
    <button
      className="account-card"
      onClick={toggleBalanceHidden}
      aria-pressed={hidden}
      aria-label={hidden ? '금액 보기' : '금액 가리기'}
      title={hidden ? '금액 보기' : '금액 가리기'}
    >
      <span className="account-card-head">
        <span className="label">{account.source ? sourceLabel(account.source) : '증권사'} 계좌</span>
        <EyeIcon off={hidden} />
      </span>
      <span className="value tnum">{amount(dollars(account.cash_usd), '4.2em')}</span>
      <span className="account-rows">
        <span className="account-row">
          <span>원화</span>
          <span className="tnum">{amount(won(account.cash_krw), '3em')}</span>
        </span>
        {live?.trader && (
          <>
            <span className="account-row">
              <span>이번 달 산 금액</span>
              <span className="tnum">{amount(dollars(String(bought)), '3.2em')}</span>
            </span>
            {sold > 0 && (
              <span className="account-row">
                <span>이번 달 판 금액</span>
                <span className="tnum">{amount(dollars(String(sold)), '3.2em')}</span>
              </span>
            )}
            {heldCost > 0 && (
              <span className="account-row">
                <span>안 판 주식 손익</span>
                {hidden ? (
                  amount('', '4.5em')
                ) : (
                  <span className={`tnum ${tone(String(unrealized))}`}>
                    {signedDollars(unrealized)} <small>{percent(String(unrealized / heldCost))}</small>
                  </span>
                )}
              </span>
            )}
            {everSold && (
              <span className="account-row">
                <span>판 주식 손익</span>
                {hidden ? amount('', '3.5em') : <span className={`tnum ${tone(String(realized))}`}>{signedDollars(realized)}</span>}
              </span>
            )}
            {waiting > 0 && (
              <span className="account-row">
                <span>승인 기다림</span>
                <span className="tnum">{waiting}건</span>
              </span>
            )}
          </>
        )}
      </span>
      <span className="faint small">{ago(account.fetched_at)}에 읽었어요</span>
    </button>
  )
}

function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg className="eye" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="2.8" fill="none" stroke="currentColor" strokeWidth="1.6" />
      {off && <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />}
    </svg>
  )
}
