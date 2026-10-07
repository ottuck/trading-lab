import { useQuery } from '@tanstack/react-query'
import { botApi, type Bot, type Plan, type SymbolPlan } from '../api'
import { money, roundMoney, setAmount } from '../format'

/* 따라 하기 (F1~F3): 나 카피 봇이 다음에 할 일, 조건까지 거리, 모아 둔 돈의 내력.
   규칙은 바꾸지 않고 보여주기만 한다. 같은 날 같은 금액으로 실제 계좌에서 따라 하면 실제 투자가 된다. */

const day = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'UTC' })
const when = (iso: string) => day.format(new Date(`${iso}T00:00:00Z`))
const usd = (v: string | number) => roundMoney(Number(v))
const pct = (v: number) => `${Math.abs(v * 100).toFixed(1)}%`

function actionOf(s: SymbolPlan) {
  if (s.state === 'dip') return { text: `${usd(s.buy)} 몰아 사기`, why: '1년 최고가보다 크게 떨어져 모아 둔 돈까지 사요', tone: 'rise' }
  if (Number(s.buy) > 0) return { text: `${usd(s.buy)} 사기`, why: '적당한 가격이라 이번 달 몫을 사요', tone: 'rise' }
  if (s.state === 'wait') return { text: `${usd(s.save)} 모아 두기`, why: '크게 떨어질 때까지 사지 않고 모아 둬요', tone: '' }
  return { text: `${usd(s.save)} 모아 두기`, why: '200일 평균보다 많이 올라 이번 달 몫은 쉬어요', tone: '' }
}

/** 몰아 사는 가격 ─ 지금 ─ 쉬는 가격을 한 줄 막대로 */
function Distance({ s }: { s: SymbolPlan }) {
  const close = Number(s.close)
  const dip = Number(s.dip_price)
  const hot = s.hot_price ? Number(s.hot_price) : null
  const toDip = dip / close - 1
  const lo = Math.min(dip, close) * 0.98
  const hi = Math.max(hot ?? close, close) * 1.02
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  return (
    <div className="plan-dist">
      <div className="plan-track" aria-hidden="true">
        <span className="zone dip" style={{ left: 0, width: at(dip) }} />
        {hot && <span className="zone hot" style={{ left: at(hot), right: 0 }} />}
        <span className="now" style={{ left: at(close) }} />
      </div>
      <div className="plan-dist-text small">
        <span>
          <b>{money(s.dip_price)}</b> 아래면 몰아 사기 ·{' '}
          {s.state === 'dip' ? '지금 이 아래예요' : `지금보다 -${pct(toDip)}`}
        </span>
        {hot && (
          <span>
            <b>{money(s.hot_price)}</b> 위면 쉬기 · {close >= hot ? '지금 이 위예요' : `지금보다 +${pct(hot / close - 1)}`}
          </span>
        )}
      </div>
    </div>
  )
}

function Reserve({ plan }: { plan: Plan }) {
  if (Number(plan.reserve) < 1) return null
  return (
    <div className="plan-reserve">
      <div className="plan-reserve-head">
        <span>모아 둔 돈</span>
        <b className="tnum">{money(plan.reserve)}</b>
      </div>
      <ul>
        {plan.reserve_items.map((r, i) => (
          <li key={i}>
            {r.month ? `${Number(r.month.slice(5))}월 ${r.symbol} 몫` : "시작 금액·잔돈"} <span className="tnum">{money(r.amount)}</span>
          </li>
        ))}
      </ul>
      <p className="faint small">어느 종목이든 몰아 사는 가격 아래로 내려가면 그 종목에 모두 써요.</p>
    </div>
  )
}

export function NextPlan({ bot }: { bot: Bot }) {
  const { data: plan } = useQuery({
    // 판단하거나 예정 주문이 바뀌면 다시 계산한다 (내일 살 돈은 이미 쓴 것으로 본다)
    queryKey: [
      'plan',
      bot.id,
      JSON.stringify(bot.params),
      JSON.stringify(bot.symbols),
      bot.account.last_close_date,
      bot.last_decision?.session_date,
      bot.pending_orders.length,
    ],
    queryFn: () => botApi.plan(bot.id),
    staleTime: 5 * 60_000,
    retry: false,
  })
  const soon = bot.pending_orders.filter((o) => o.side === 'BUY')
  if (!plan) return null
  return (
    <section className="block plan">
      <div className="block-head">
        <h2>다음에 할 일</h2>
        <span className="sub">{when(plan.as_of)} 종가 기준</span>
      </div>
      {soon.length > 0 && (
        <div className="plan-soon">
          <b>다음 장이 열리면</b>{' '}
          {soon.map((o) => `${o.symbol} ${o.budget ? usd(o.budget) : ''}어치`).join(', ')} 사요. 따라 하려면 장이 열린 뒤 같은 금액으로 사면 돼요.
        </div>
      )}
      <div className="plan-when">
        <span className="date">{when(plan.deposit_date)}</span>
        <span className="muted">넣는 날 · {setAmount(Number(plan.deposit))}</span>
      </div>
      <div className="plan-rows">
        {plan.symbols.map((s) => {
          const a = actionOf(s)
          return (
            <div key={s.symbol} className="plan-row">
              <div className="plan-what">
                <div className="plan-sym">
                  {s.symbol}
                  {plan.symbols.length > 1 && <span className="faint"> · {s.weight}%</span>}
                </div>
                <div className={`plan-act ${a.tone}`}>{a.text}</div>
                <div className="muted small">{a.why}</div>
              </div>
              <Distance s={s} />
            </div>
          )
        })}
      </div>
      <Reserve plan={plan} />
      <p className="faint small">
        실제 계좌에서 따라 하려면 그날 장이 열린 뒤 같은 금액으로 사면 돼요. 가격이 바뀌면 할 일도 바뀌어요 (지금 가격이 그날까지
        이어진다고 본 예정이에요).
      </p>
    </section>
  )
}
