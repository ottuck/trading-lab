import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, liveApi, type LiveOrder } from '../api'
import { useDemo } from '../demo'
import { ago, dollars, percent, shares, signedDollars, tone, won } from '../format'
import { dayLabel, liveStatus, toggleBalanceHidden, useBalanceHidden, useLive } from '../live'
import { sourceLabel } from '../source'

/* 실제로 따라 사기 (실거래 R2). 실제 계좌 금액은 원화로 바꿔 보지 않고 늘 달러로 보여준다. */

/** 화면 맨 위: 불명 주문 확인과 승인. 봇이 삭제돼도 불명 주문은 숨기지 않는다. */
export function LiveApprovals() {
  const qc = useQueryClient()
  const { data } = useLive()
  const act = useMutation({
    mutationFn: ({ id, ok }: { id: number; ok: boolean }) => (ok ? liveApi.approve(id) : liveApi.decline(id)),
    onSuccess: (live) => qc.setQueryData(['live'], live),
  })
  const resolve = useMutation({
    mutationFn: ({ id, brokerOrderId }: { id: number; brokerOrderId: string | null }) => liveApi.resolve(id, brokerOrderId),
    onSuccess: (live) => qc.setQueryData(['live'], live),
  })
  const unknown = data?.orders.filter((o) => o.state === 'UNKNOWN') ?? []
  const waiting = data?.orders.filter((o) => o.state === 'WAITING_APPROVAL') ?? []
  if (!data || (!unknown.length && (!data.trader || !waiting.length))) return null
  const specify = (o: LiveOrder) => {
    const id = window.prompt(`${o.symbol} ${dayLabel(o.trade_date)} 주문을 증권사 앱에서 확인하고 주문 번호를 입력해 주세요.\n프로그램이 종목·방향·금액 또는 수량·접수 시각을 다시 확인할 때까지 새 주문은 멈춰 있어요.`)?.trim()
    if (id) resolve.mutate({ id: o.id, brokerOrderId: id })
  }
  const notPlaced = (o: LiveOrder) => {
    if (window.confirm(`${o.symbol} ${dayLabel(o.trade_date)} 주문이 접수되지 않았고, 체결된 주식도 없는지 증권사 앱의 주문 내역과 보유를 모두 확인했나요?\n\n확인하면 이 주문은 다시 보내지 않고 넘겨요. 확인할 수 없다면 취소를 눌러 주세요. 다른 불명 주문이 없으면 이후 주문은 다시 진행돼요.`)) {
      resolve.mutate({ id: o.id, brokerOrderId: null })
    }
  }
  return (
    <section className="block live-ask">
      <div className="block-head">
        <h2>{unknown.length ? '실제 주문 결과를 확인해 주세요' : waiting.some((o) => o.side === 'SELL') ? '실제로 주문할까요?' : '실제로 살까요?'}</h2>
      </div>
      {unknown.length > 0 && <div className="notice">결과가 불명확한 주문이 있어 모든 봇의 새 실제 주문과 승인을 멈췄어요. 매수 금액은 월 한도에 계속 포함해요. 증권사에 조회해 주문을 찾으면 자동으로 이어가요.</div>}
      {unknown.map((o) => (
        <div key={o.id} className="live-ask-row">
          <div>
            <div className="title">{o.symbol} · {o.side === 'SELL' ? `${shares(o.quantity)}주 팔기` : `${dollars(o.amount)}어치 사기`}</div>
            <div className="faint small">{dayLabel(o.trade_date)} · {o.bot_name ?? '삭제한 봇'} · 확인 필요</div>
          </div>
          <div className="controls">
            <button className="ghost" disabled={resolve.isPending} onClick={() => specify(o)}>주문 번호 입력</button>
            <button className="ghost" disabled={resolve.isPending} onClick={() => notPlaced(o)}>미접수 확인</button>
          </div>
        </div>
      ))}
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
            <button className="primary" disabled={act.isPending || data.halted || data.unknown_order_ids.length > 0} onClick={() => act.mutate({ id: o.id, ok: true })}>
              승인
            </button>
            <button className="ghost" disabled={act.isPending} onClick={() => act.mutate({ id: o.id, ok: false })}>
              이번엔 안 사기
            </button>
          </div>
        </div>
      ))}
      {act.error && <span className="bad small">{act.error.message}</span>}
      {resolve.error && <span className="bad small">{resolve.error.message}</span>}
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
