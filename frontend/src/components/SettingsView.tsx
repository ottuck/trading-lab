import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, botApi, liveApi, notifyApi, type Bot, type NotifyScope, type SymbolWeight, type BrokerAccount } from '../api'
import { useLive } from '../live'
import { useDemo } from '../demo'
import { LiveOrderList } from './Live'
import { ago, dollars, money, shares, won } from '../format'
import { closeNewBot, selectBot, startMeEdit, startNewBot, useNewBotSeed, useSelectedBot, type NewBotSeed } from '../selectedBot'
import { isAiBot, isMeBot, sameParams, useStrategies } from '../strategies'
import { answersOf, describe } from '../me'
import { toConfig, toDraft, type Draft } from '../botConfig'
import { useDismiss } from '../useDismiss'
import { StrategyFields, TradeFields } from './BotConfigFields'
import { activeOf, basketLabel, suggestName } from '../basket'
import { sourceLabel } from '../source'
import { BasketPicker, SymbolPicker } from './SymbolPicker'

/* Vercel식 설정: 왼쪽에 섹션 제목·설명, 오른쪽에 입력. 섹션은 가는 선으로 나누고 저장은 맨 아래 하나,
   되돌릴 수 없는 동작은 맨 아래 빨간 테두리 영역에 따로 둔다. */

function Section({ title, desc, children }: { title: string; desc?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="set-section">
      <div className="set-label">
        <h2>{title}</h2>
        {desc && <p>{desc}</p>}
      </div>
      <div className="set-body">{children}</div>
    </section>
  )
}

/** 제목 자리의 봇 바꾸기 메뉴: "qqq-sma 설정 ▾" */
function Switcher({ bots, current, creating }: { bots: Bot[]; current?: Bot; creating: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useDismiss(open, () => setOpen(false), ref)
  return (
    <div className="switcher" ref={ref}>
      <button className="switcher-btn" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)} disabled={!bots.length}>
        {creating ? '새 봇 만들기' : `${current?.name} 설정`}
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="menu" role="menu">
          {bots.map((b) => (
            <button
              key={b.id}
              role="menuitemradio"
              aria-checked={!creating && b.id === current?.id}
              className={!creating && b.id === current?.id ? 'active' : ''}
              onClick={() => {
                setOpen(false)
                closeNewBot()
                selectBot(b.id)
              }}
            >
              {b.name}
              <span className="faint small">{b.symbol}</span>
            </button>
          ))}
          <hr />
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              startNewBot()
            }}
          >
            + 새 봇 만들기
          </button>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              location.hash = 'me'
            }}
          >
            나 카피하기
          </button>
        </div>
      )}
    </div>
  )
}

function History({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['history', botId], queryFn: () => api.activity(botId, 'config_change') })
  if (!data?.length) return null
  return (
    <Section title="바꾼 기록" desc="설정을 언제 어떻게 바꿨는지 남겨 둬요.">
      <div className="set-log">
        {data.map((a) => (
          <div key={a.id} className="log-item">
            <span className="pip" />
            <div>
              <div className="title">{a.title}</div>
              {a.body && <div className="body">{a.body}</div>}
            </div>
            <time dateTime={a.at}>{ago(a.at)}</time>
          </div>
        ))}
      </div>
    </Section>
  )
}

/** 만든 뒤 종목·비율 바꾸기. 모으기 전략에서 뺀 종목을 들고 있으면 팔지 않고 들고만 있는다. */
function SymbolsField({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const { byName } = useStrategies()
  const accumulates = !!byName[bot.strategy]?.accumulates
  const [basket, setBasket] = useState(() => activeOf(bot.symbols))
  const save = useMutation({
    mutationFn: () => botApi.updateSymbols(bot.id, basket),
    onSuccess: (b) => {
      setBasket(activeOf(b.symbols))
      void qc.invalidateQueries({ queryKey: ['bots'] })
      void qc.invalidateQueries({ queryKey: ['history', bot.id] })
    },
  })
  const held = bot.account.positions.filter((p) => Number(p.qty) > 0).map((p) => p.symbol)
  const picked = basket.map((b) => b.symbol)
  const dropped = held.filter((s) => !picked.includes(s))
  const total = basket.reduce((sum, b) => sum + b.weight, 0)
  const now = activeOf(bot.symbols)
  const changed = basket.length !== now.length || basket.some((b, i) => b.symbol !== now[i]?.symbol || b.weight !== now[i]?.weight)
  const locked = !accumulates && dropped.length > 0
  return (
    <Section
      title={accumulates ? '종목과 비율' : '종목'}
      desc={accumulates ? '다음 입금부터 이 비율대로 나눠 사요. 바꾼 기록은 아래에 남아요.' : '사고팔 종목을 바꿔요. 들고 있는 동안에는 바꿀 수 없어요.'}
    >
      {accumulates ? (
        <BasketPicker value={basket} onChange={setBasket} />
      ) : (
        <SymbolPicker label="" value={basket[0]?.symbol ?? bot.symbol} onChange={(symbol) => setBasket([{ symbol, weight: 100 }])} />
      )}
      {changed && dropped.length > 0 && (
        <div className="notice">
          {locked
            ? `지금 ${dropped.join(', ')}를 들고 있어요. 이 전략은 판 뒤에 종목을 바꿀 수 있어요.`
            : `${dropped.join(', ')}는 팔지 않아요. 지금 들고 있는 만큼 그대로 두고 더 사지 않아요.`}
        </div>
      )}
      <div className="controls">
        <button disabled={!changed || locked || total !== 100 || save.isPending} onClick={() => save.mutate()}>
          종목 저장
        </button>
        {save.isSuccess && !changed && <span className="ok small">바꿨어요. 다음 판단부터 적용돼요.</span>}
        {save.error && <span className="bad small">{save.error.message}</span>}
      </div>
    </Section>
  )
}

function NameField({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const [name, setName] = useState(bot.name)
  const rename = useMutation({
    mutationFn: () => botApi.rename(bot.id, name.trim()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      void qc.invalidateQueries({ queryKey: ['history', bot.id] })
    },
  })
  const changed = name.trim() !== bot.name
  return (
    <Section title="이름" desc="봇 목록과 기록에 보이는 이름이에요.">
      <div className="controls">
        <input id="bot-name" value={name} onChange={(e) => setName(e.target.value)} size={18} aria-label="봇 이름" />
        <button disabled={!changed || !name.trim() || rename.isPending} onClick={() => rename.mutate()}>
          이름 바꾸기
        </button>
        {rename.isSuccess && !changed && <span className="ok small">바꿨어요.</span>}
        {rename.error && <span className="bad small">{rename.error.message}</span>}
      </div>
    </Section>
  )
}

function DangerZone({ bot, others }: { bot: Bot; others: Bot[] }) {
  const qc = useQueryClient()
  const reset = useMutation({
    mutationFn: () => botApi.reset(bot.id),
    onSuccess: () => void qc.invalidateQueries(),
  })
  const remove = useMutation({
    mutationFn: () => botApi.remove(bot.id),
    onSuccess: () => {
      if (others[0]) selectBot(others[0].id)
      void qc.invalidateQueries()
    },
  })
  const error = reset.error ?? remove.error
  const confirmReset = () =>
    window.confirm(
      `${bot.name}의 모의 잔고를 ${money(bot.account.initial_cash)}로 되돌리고 판단·거래 기록을 모두 지울까요?\n` +
        '설정과 실행 상태는 그대로예요. 되돌릴 수 없어요.',
    )
  // 따로 상자로 묶지 않고 다른 설정과 같은 줄로 둔다. 되돌릴 수 없음은 누를 때 확인 메시지로 알린다.
  return (
    <>
      <Section
        title="처음부터 다시 시작"
        desc={`모의 잔고를 시작 금액 ${money(bot.account.initial_cash)}로 되돌리고 판단·거래 기록을 지워요. 설정은 그대로예요.`}
      >
        <div className="controls">
          <button disabled={reset.isPending} onClick={() => confirmReset() && reset.mutate()}>
            다시 시작
          </button>
        </div>
      </Section>
      <Section title="봇 삭제" desc="이 봇과 모든 기록을 지워요.">
        <div className="controls">
          <button
            className="danger"
            disabled={remove.isPending}
            onClick={() => window.confirm(`${bot.name}의 모든 기록을 지울까요? 되돌릴 수 없어요.`) && remove.mutate()}
          >
            봇 삭제
          </button>
          {error && <span className="bad small">{error.message}</span>}
        </div>
      </Section>
    </>
  )
}

const ORDER_STATUS: Record<string, string> = {
  PENDING: '기다리는 중',
  PARTIAL_FILLED: '일부 체결',
  FILLED: '체결',
  CANCELED: '취소',
  REJECTED: '거절',
}

function amountOf(value: string | null, currency: string) {
  return currency === 'KRW' ? won(value) : dollars(value)
}

function orderTitle(o: BrokerAccount['orders'][number]) {
  const verb = o.side === 'BUY' ? '샀어요' : '팔았어요'
  const done = Number(o.qty) > 0
  return `${o.symbol} ${o.amount ? amountOf(o.amount, o.currency) + ' ' : ''}${done ? verb : o.side === 'BUY' ? '사기 주문' : '팔기 주문'}`
}

/** 실제 증권사 계좌 (실거래 R1). Worker가 한 시간마다 읽은 값을 보여주기만 하고 주문은 내지 않는다. */
function BrokerAccountSection() {
  const { data } = useQuery({ queryKey: ['broker-account'], queryFn: api.brokerAccount, refetchInterval: 60_000 })
  if (!data) return null
  const name = data.source ? sourceLabel(data.source) : '증권사'
  const failing = !!data.error_at && (!data.fetched_at || data.error_at > data.fetched_at)
  return (
    <Section title={`${name} 계좌`} desc={`실제 ${name} 계좌를 한 시간마다 읽어 와요. 실제 주문은 봇 설정의 "실제로 따라 사기"에서 켜요.`}>
      {failing && (
        <div className="notice">
          {ago(data.error_at)}에 계좌를 읽지 못했어요.{' '}
          {data.error === 'access'
            ? '연결 권한을 확인해 주세요. 집 인터넷 주소가 바뀌었다면 증권사 Open API의 허용 IP를 다시 등록해야 해요.'
            : '잠시 연결이 안 됐어요. 한 시간 뒤에 다시 읽어요.'}
        </div>
      )}
      {data.fetched_at && (
        <>
          <div>
            <div className="faint small">주문에 쓸 수 있는 돈</div>
            <div>
              달러 {dollars(data.cash_usd)} <span className="muted">· 원화 {won(data.cash_krw)}</span>
            </div>
          </div>
          <div>
            <div className="faint small">들고 있는 주식</div>
            {data.holdings.length ? (
              data.holdings.map((h) => (
                <div key={h.symbol}>
                  {h.symbol} {shares(h.qty)}주 <span className="muted">· {amountOf(h.value, h.currency)}</span>
                </div>
              ))
            ) : (
              <div className="muted">없어요</div>
            )}
          </div>
          <div className="set-log">
            <div className="faint small">최근 30일 주문</div>
            {data.orders.length ? (
              data.orders.slice(0, 5).map((o) => (
                <div key={o.ordered_at + o.symbol} className="log-item">
                  <span className="pip" />
                  <div>
                    <div className="title">{orderTitle(o)}</div>
                    <div className="body">{ORDER_STATUS[o.status] ?? o.status}</div>
                  </div>
                  <time dateTime={o.ordered_at}>{ago(o.ordered_at)}</time>
                </div>
              ))
            ) : (
              <div className="muted">없어요</div>
            )}
          </div>
          <div className="faint small">{ago(data.fetched_at)}에 읽었어요</div>
        </>
      )}
    </Section>
  )
}

const RATIO_OF: Record<string, string> = { '0.01': '1/100', '0.1': '1/10' }

/** 실제로 따라 사기 (실거래 R2): 나 카피 봇의 모의 매수를 비율만큼 줄여 실제 계좌에서 산다. */
function LiveSection({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const { data: live } = useLive()
  const { byName } = useStrategies()
  const [unsupported, setUnsupported] = useState(false)
  const setRatio = useMutation({
    mutationFn: (ratio: string | null) => botApi.setLive(bot.id, ratio),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      void qc.invalidateQueries({ queryKey: ['live'] })
      void qc.invalidateQueries({ queryKey: ['history', bot.id] })
    },
  })
  if (!live) return null
  // 모으기 봇은 매달 사기만, 사고팔기 봇은 사고팔기를 따라 한다
  const trading = !byName[bot.strategy]?.accumulates
  const current = bot.live_ratio == null ? null : (RATIO_OF[String(Number(bot.live_ratio))] ?? bot.live_ratio)
  const pick = (ratio: string | null) => {
    setUnsupported(false)
    if (ratio === current) return
    const what = trading
      ? `모의로 살 때 봇 현금의 ${ratio}만큼 사고, 모의로 팔 때 실제로 산 만큼 모두 팔아요.`
      : `모의 매수의 ${ratio} 금액을 같은 날 같은 종목으로 사요.`
    const ok =
      !ratio ||
      window.confirm(
        `${what} 실제 ${sourceLabel(live.trader)} 계좌의 돈이 움직여요.\n` +
          `처음 ${live.auto_after}번은 앱에서 승인해야 나가고, 그다음부터 자동이에요. 켤까요?`,
      )
    if (ok) setRatio.mutate(ratio)
  }
  const mine = live.orders.filter((o) => o.bot_id === bot.id)
  const left = Math.max(0, live.auto_after - bot.live_streak)
  const limits = trading
    ? `한도: 사는 주문 1건 ${dollars(live.per_trade)}.`
    : `한도: 주문 1건 ${dollars(live.per_order)}, 한 달 ${dollars(live.per_month)}.`
  return (
    <Section
      title={trading ? '실제로 따라 하기' : '실제로 따라 사기'}
      desc={
        trading
          ? `모의로 살 때 봇 현금의 1/100만큼 실제 계좌에서 사고, 모의로 팔 때 이 봇이 실제로 산 만큼 모두 팔아요. 레버리지는 QLD·TQQQ만 해요. ${limits}`
          : `모의 매수를 1/100 금액으로 실제 계좌에서 같은 날 같은 종목을 사요. 파는 주문은 내지 않아요. ${limits}`
      }
    >
      {!live.trader && (
        <div className="notice">서버의 실거래 스위치가 꺼져 있어요. 켜기 전에는 실제 주문이 나가지 않아요.</div>
      )}
      <div className="controls">
        <button className={`seg ${current === null ? 'active' : ''}`} disabled={setRatio.isPending} onClick={() => pick(null)}>
          끄기
        </button>
        {live.ratios.map((r) => (
          <button key={r} className={`seg ${current === r ? 'active' : ''}`} disabled={setRatio.isPending || !live.trader} onClick={() => pick(r)}>
            {r}
          </button>
        ))}
        <button className="seg unsupported" aria-disabled="true" onClick={() => setUnsupported(true)}>
          1/10
        </button>
        {setRatio.error && <span className="bad small">{setRatio.error.message}</span>}
      </div>
      {unsupported && (
        <div className="notice">
          <b>1/10은 지원하지 않아요.</b> 실제 돈은 1/100로만 따라 해요. 1/10이면{' '}
          {trading ? '한 번에 $1,000 안팎(약 135만원)을 사고팔게 되고' : '한 달 약 $68(약 9만원)이 나가고'}, 지금 안전장치의 한도(
          {trading ? `1건 ${dollars(live.per_trade)}` : `1건 ${dollars(live.per_order)}, 한 달 ${dollars(live.per_month)}`})도 훨씬 넘어요.
          이 앱의 실제 계좌는 같은 판단이 진짜 돈으로도 그대로 움직이는지 작은 금액으로 확인하는 곳이라 비율은 키우지 않기로 했어요.
        </div>
      )}
      {current && (
        <div className="faint small">
          {left > 0
            ? `처음 ${live.auto_after}번은 홈에서 승인해야 나가요 (앞으로 ${left}번). 문제가 생기면 다시 승인부터 해요.`
            : '자동으로 내요. 한도를 넘거나 문제가 생기면 다시 승인을 받아요.'}
        </div>
      )}
      {mine.length > 0 && (
        <div className="set-log">
          <div className="faint small">이 봇이 낸 실제 주문</div>
          <LiveOrderList orders={mine} />
        </div>
      )}
    </Section>
  )
}

/** 비상 중지: 모든 봇의 실제 주문을 멈춘다. 이미 보낸 주문은 체결을 계속 확인한다. */
function HaltSection() {
  const qc = useQueryClient()
  const { data: live } = useLive()
  const halt = useMutation({
    mutationFn: (halted: boolean) => liveApi.halt(halted),
    onSuccess: (data) => qc.setQueryData(['live'], data),
  })
  if (!live?.trader) return null
  return (
    <Section title="실제 주문" desc="모든 봇의 실제 주문을 한 번에 멈추거나 다시 시작해요. 이미 보낸 주문은 체결을 계속 확인해요.">
      <div className="controls">
        {live.halted ? (
          <button disabled={halt.isPending} onClick={() => halt.mutate(false)}>
            다시 시작
          </button>
        ) : (
          <button
            className="danger"
            disabled={halt.isPending}
            onClick={() => window.confirm('모든 봇의 실제 주문을 멈출까요?') && halt.mutate(true)}
          >
            모두 멈추기
          </button>
        )}
        <span className={live.halted ? 'bad small' : 'faint small'}>
          {live.halted ? '멈춤 중 · 새 실제 주문을 보내지 않아요' : '실제 주문을 내고 있어요'}
        </span>
      </div>
      {live.shortfall.length > 0 ? (
        <div className="notice">
          실제 계좌에 봇이 산 것보다 적게 있어요:{' '}
          {live.shortfall.map((s) => `${s.symbol} ${shares(s.held)}주 (봇이 산 ${shares(s.bought)}주)`).join(', ')}. 직접
          파셨다면 괜찮아요. 맞을 때까지 실제 주문은 매번 승인을 받아요.
        </div>
      ) : (
        live.checked_at && <div className="faint small">{ago(live.checked_at)} 실제 계좌와 맞춰 봤어요 · 봇 기록과 맞아요</div>
      )}
    </Section>
  )
}

/** 텔레그램 알림: 켜기·받을 알림 고르기·테스트. 봇 토큰은 서버 비밀값에만 있다. */
function NotifySection() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['notify'], queryFn: notifyApi.get })
  const save = useMutation({
    mutationFn: (next: { enabled: boolean; scope: NotifyScope }) => notifyApi.update(next.enabled, next.scope),
    onSuccess: (n) => qc.setQueryData(['notify'], n),
  })
  const test = useMutation({ mutationFn: notifyApi.test })
  if (!data) return null
  if (!data.available)
    return (
      <Section title="텔레그램 알림" desc="승인 요청과 체결을 폰으로 받아요.">
        <div className="notice">서버에 텔레그램 봇 정보가 없어요. 봇 토큰과 채팅 ID를 넣으면 여기서 켤 수 있어요.</div>
      </Section>
    )
  const scope = data.scope as NotifyScope
  return (
    <Section title="텔레그램 알림" desc="승인 요청과 체결을 폰으로 받아요.">
      <div className="controls">
        <button className={`seg ${!data.enabled ? 'active' : ''}`} disabled={save.isPending} onClick={() => save.mutate({ enabled: false, scope })}>
          끄기
        </button>
        <button
          className={`seg ${data.enabled && scope === 'live' ? 'active' : ''}`}
          disabled={save.isPending}
          onClick={() => save.mutate({ enabled: true, scope: 'live' })}
        >
          실제 주문만
        </button>
        <button
          className={`seg ${data.enabled && scope === 'all' ? 'active' : ''}`}
          disabled={save.isPending}
          onClick={() => save.mutate({ enabled: true, scope: 'all' })}
        >
          모의 투자 소식까지
        </button>
      </div>
      <div className="faint small">
        {!data.enabled
          ? '알림을 보내지 않아요. 소식은 앱의 기록에서 볼 수 있어요.'
          : scope === 'live'
            ? '실제로 살까요? 승인 요청, 체결, 실제 주문 문제, 봇이 멈춘 문제만 보내요.'
            : '모의 매수·매도와 주간 정리까지 보내요.'}
      </div>
      <div className="controls">
        <button disabled={test.isPending} onClick={() => test.mutate()}>
          테스트 메시지 보내기
        </button>
        {test.isSuccess && <span className="ok small">보냈어요. 1분 안에 도착해요.</span>}
        {(test.error ?? save.error) && <span className="bad small">{(test.error ?? save.error)?.message}</span>}
      </div>
    </Section>
  )
}

/** 설정 맨 위: 봇과 상관없이 하나인 것 (실제 계좌, 알림, 비상 중지). */
function AccountAndNotify() {
  return (
    <>
      <div className="settings-head">
        <h1 className="settings-title">계좌와 알림</h1>
        <p className="muted small">봇과 상관없이 하나예요.</p>
      </div>
      <BrokerAccountSection />
      <NotifySection />
      <HaltSection />
    </>
  )
}

function sameStrategy(d: Draft, bot: Bot) {
  return d.strategy === bot.strategy && sameParams(d.params, bot.params)
}

function BotSettings({ bot, others }: { bot: Bot; others: Bot[] }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(() => toDraft(bot))
  const save = useMutation({
    mutationFn: () => botApi.updateConfig(bot.id, toConfig(draft, bot)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      void qc.invalidateQueries({ queryKey: ['history', bot.id] })
    },
  })
  const changing = !sameStrategy(draft, bot)
  const saved = toDraft(bot)
  const dirty = changing || draft.slippage !== saved.slippage || draft.maxPosition !== saved.maxPosition
  const ai = isAiBot(bot)
  return (
    <>
      {ai ? (
        <Section title="AI에게 맡기기" desc="고른 종목 안에서 무엇을 얼마나 들고 있을지 AI가 매일 장이 끝난 뒤 정해요.">
          <ul className="me-summary">
            <li>
              매달 {bot.params.day}일 ${bot.params.deposit?.toLocaleString('en-US')}를 넣어요
            </li>
            <li>관심 종목 {bot.symbols.length}개({bot.symbols.map((s) => s.symbol).join(' · ')}) 안에서만 사고팔아요</li>
            <li>목표 비중과 지금 비중이 자산의 2%보다 덜 차이 나면 그대로 둬요</li>
            <li>AI 비용이 한 달 상한을 넘으면 그달은 판단하지 않고 그대로 둬요</li>
          </ul>
        </Section>
      ) : isMeBot(bot) ? (
        <Section title="내 규칙" desc="나 카피하기로 정한 규칙이에요. 바꾸면 다음 판단부터 적용되고, 지금까지의 기록은 그대로예요.">
          <ul className="me-summary">
            {describe(answersOf(bot)).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <div className="controls">
            <button onClick={() => startMeEdit(bot.id)}>질문 다시 하기</button>
            <span className="faint small">또는 아래에서 바로 고칠 수 있어요</span>
          </div>
          <StrategyFields draft={draft} onChange={setDraft} />
        </Section>
      ) : (
      <Section title="전략" desc="언제 사고팔지 정해요. 돌아가는 중에도 바꿀 수 있고, 다음 판단부터 적용돼요.">
        <StrategyFields draft={draft} onChange={setDraft} />
        {changing && Number(bot.account.qty) > 0 && (
          <div className="notice">
            지금 {bot.symbol} {shares(bot.account.qty)}주를 들고 있어요. 저장하면 다음 판단부터 새 전략으로 봐요. 새 전략이 &quot;팔
            때&quot;라고 보면 그다음 장이 열릴 때 바로 팔아요.
          </div>
        )}
      </Section>
      )}
      <Section title="체결과 투자 금액" desc="모의 체결을 얼마나 보수적으로 볼지, 한 번에 얼마까지 넣을지 정해요.">
        <TradeFields draft={draft} onChange={setDraft} />
        {/* 저장은 이 섹션(과 위의 전략·규칙)에 속한다: 섹션 밖에 혼자 두지 않는다 */}
        <div className="set-actions">
          <button className="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            저장
          </button>
          {dirty && !ai && <span className="faint small">위의 {isMeBot(bot) ? '내 규칙' : '전략'}도 함께 저장돼요.</span>}
          {!dirty && save.isSuccess && <span className="ok small">저장했어요. 다음 판단부터 적용돼요.</span>}
          {save.error && <span className="bad small">{save.error.message}</span>}
        </div>
      </Section>
      {!ai && <SymbolsField key={bot.symbols.map((s) => `${s.symbol}${s.weight}`).join()} bot={bot} />}
      {ai ? (
        <Section title="실제로 따라 하기" desc="AI 봇은 아직 실제 돈으로 따라 하지 않아요.">
          <p className="muted small">모의로 먼저 지켜보며 나 카피 봇과 비교한 뒤 정해요.</p>
        </Section>
      ) : (
        <LiveSection bot={bot} />
      )}
      <NameField key={bot.name} bot={bot} />
      <History botId={bot.id} />
      <DangerZone bot={bot} others={others} />
    </>
  )
}

function NewBotForm({ seed, taken }: { seed: NewBotSeed; taken: string[] }) {
  const qc = useQueryClient()
  // 종목과 비율. 모으기 전략은 여러 종목(최대 10개), 그 밖의 전략은 첫 종목 하나만 쓴다.
  const [basket, setBasket] = useState<SymbolWeight[]>(seed.symbols ?? [{ symbol: seed.symbol ?? 'QQQ', weight: 100 }])
  const [draft, setDraft] = useState(() =>
    toDraft(seed.strategy ? { strategy: seed.strategy, params: seed.params ?? {} } : undefined),
  )
  const { byName } = useStrategies()
  const accumulates = !!byName[draft.strategy]?.accumulates
  const chosen = accumulates ? basket : basket.slice(0, 1)
  const total = chosen.reduce((sum, b) => sum + b.weight, 0)
  // 이름은 직접 고치기 전까지 종목·전략에 맞춰 자동으로 제안한다.
  const [customName, setCustomName] = useState<string | null>(null)
  const name = customName ?? suggestName(chosen.map((b) => b.symbol), draft.strategy, taken)
  // 시작 금액은 직접 고치기 전까지 전략에 맞춘다 (모으기 전략은 한 달 입금액).
  const [customCash, setCustomCash] = useState<string | null>(null)
  const cash = customCash ?? (accumulates ? String(draft.params.deposit ?? 675) : '10000')
  const [startNow, setStartNow] = useState(true)
  const create = useMutation({
    mutationFn: async () => {
      const bot = await botApi.create({
        ...toConfig(draft),
        name,
        symbol: chosen[0].symbol,
        symbols: chosen.length > 1 ? chosen : undefined,
        initial_cash: cash,
      })
      if (startNow) await api.command(bot.id, 'START')
      return bot
    },
    onSuccess: (bot) => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      // 만든 봇을 홈에서 바로 보여준다.
      selectBot(bot.id)
      closeNewBot()
      location.hash = 'dashboard'
    },
  })
  return (
    <>
      <Section title="전략" desc="언제 사고팔지 정해요. 나중에 설정에서 바꿀 수 있어요.">
        <StrategyFields draft={draft} onChange={setDraft} />
      </Section>
      {accumulates ? (
        <Section title="종목과 비율" desc="매달 넣는 돈을 이 비율대로 나눠 사요. 현금은 함께 써요.">
          <BasketPicker value={basket} onChange={setBasket} />
        </Section>
      ) : (
        <Section title="종목" desc="이 봇이 사고팔 미국 주식이나 ETF예요.">
          <SymbolPicker label="" value={basket[0].symbol} onChange={(symbol) => setBasket([{ symbol, weight: 100 }])} />
        </Section>
      )}
      <Section title="체결과 투자 금액" desc="모의 체결을 얼마나 보수적으로 볼지, 한 번에 얼마까지 넣을지 정해요.">
        <TradeFields draft={draft} onChange={setDraft} />
      </Section>
      <Section title="이름과 시작 금액" desc="모의 투자는 실제 계좌와 무관해요. 시작 금액은 나중에 바꿀 수 없어요.">
        <div className="form" style={{ margin: 0 }}>
          <label>
            이름
            <input id="new-bot-name" value={name} onChange={(e) => setCustomName(e.target.value)} size={16} />
          </label>
          <label>
            시작 금액 ($)
            <input
              id="new-bot-cash"
              value={cash}
              inputMode="numeric"
              onChange={(e) => setCustomCash(e.target.value.replace(/[^0-9]/g, ''))}
              size={8}
            />
          </label>
        </div>
      </Section>
      <div className="save-bar">
        <label className="toggle">
          <input id="start-now" type="checkbox" checked={startNow} onChange={(e) => setStartNow(e.target.checked)} />
          만들면 바로 모의 투자 시작
        </label>
        <button
          className="primary"
          disabled={create.isPending || !name.trim() || !cash || (chosen.length > 1 && total !== 100)}
          onClick={() => create.mutate()}
        >
          {startNow ? '만들고 시작하기' : '만들기'}
        </button>
        {taken.length > 0 && (
          <button className="ghost" onClick={closeNewBot}>
            취소
          </button>
        )}
        {create.error && <span className="bad small">{create.error.message}</span>}
      </div>
    </>
  )
}

/** 설정: 홈에서 고른 봇 하나를 바꾼다. 제목의 메뉴로 다른 봇을 고르거나 새 봇을 만든다. */
export function SettingsView({ bots }: { bots: Bot[] }) {
  const seed = useNewBotSeed()
  const selected = useSelectedBot(bots)
  const { byName } = useStrategies()
  const creating = seed !== null || !bots.length
  const demo = useDemo()
  return (
    <div className="settings">
      {/* 데모: 실제 계좌·알림이 없고, 봇 설정은 무엇을 고를 수 있는지 보기만 한다 (바꾸기 요청은 서버가 막는다) */}
      {!demo && <AccountAndNotify />}
      <div className="settings-head bots-head">
        <Switcher bots={bots} current={selected} creating={creating} />
        <p className="muted small">
          {creating
            ? seed?.strategy
              ? '시험해 본 전략과 종목으로 채워 뒀어요.'
              : '새 모의 투자 봇을 만들어요.'
            : `${isAiBot(selected) ? `관심 종목 ${selected.symbols.length}개` : basketLabel(selected.symbols, selected.symbol)} · ${byName[selected.strategy]?.nickname ?? selected.strategy} · 시작 금액 ${money(selected.account.initial_cash)}`}
        </p>
      </div>
      {demo && <div className="notice">데모에서는 설정을 바꿀 수 없어요. 어떤 것을 고를 수 있는지만 보여 드려요.</div>}
      <fieldset className="set-lock" disabled={demo}>
        {creating ? (
          <NewBotForm key={JSON.stringify(seed)} seed={seed ?? {}} taken={bots.map((b) => b.name)} />
        ) : (
          <BotSettings key={selected.id} bot={selected} others={bots.filter((b) => b.id !== selected.id)} />
        )}
      </fieldset>
    </div>
  )
}
