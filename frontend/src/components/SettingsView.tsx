import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, botApi, type Bot, type SymbolWeight } from '../api'
import { ago, money, shares } from '../format'
import { closeNewBot, selectBot, startNewBot, useNewBotSeed, useSelectedBot, type NewBotSeed } from '../selectedBot'
import { sameParams, useStrategies } from '../strategies'
import { toConfig, toDraft, type Draft } from '../botConfig'
import { useDismiss } from '../useDismiss'
import { StrategyFields, TradeFields } from './BotConfigFields'
import { activeOf, basketLabel, suggestName } from '../basket'
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
            질문으로 나 만들기
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
    <Section title="이름" desc="봇 목록과 텔레그램 알림에 보이는 이름이에요.">
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
  return (
    <div className="danger-box">
      <div className="danger-row">
        <div>
          <div className="title">처음부터 다시 시작</div>
          <p>모의 잔고를 시작 금액 {money(bot.account.initial_cash)}로 되돌리고 판단·거래 기록을 지워요. 설정은 그대로예요.</p>
        </div>
        <button disabled={reset.isPending} onClick={() => confirmReset() && reset.mutate()}>
          다시 시작
        </button>
      </div>
      <div className="danger-row">
        <div>
          <div className="title">봇 삭제</div>
          <p>이 봇과 모든 기록을 지워요. 되돌릴 수 없어요.</p>
        </div>
        <button
          className="danger"
          disabled={remove.isPending}
          onClick={() => window.confirm(`${bot.name} 봇과 모든 기록을 지울까요? 되돌릴 수 없어요.`) && remove.mutate()}
        >
          봇 삭제
        </button>
      </div>
      {error && <div className="danger-row bad small">{error.message}</div>}
    </div>
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
  return (
    <>
      <Section title="전략" desc="언제 사고팔지 정해요. 돌아가는 중에도 바꿀 수 있고, 다음 판단부터 적용돼요.">
        <StrategyFields draft={draft} onChange={setDraft} />
        {changing && Number(bot.account.qty) > 0 && (
          <div className="notice">
            지금 {bot.symbol} {shares(bot.account.qty)}주를 들고 있어요. 저장하면 다음 판단부터 새 전략으로 봐요. 새 전략이 &quot;팔
            때&quot;라고 보면 그다음 장이 열릴 때 바로 팔아요.
          </div>
        )}
      </Section>
      <Section title="체결과 투자 금액" desc="모의 체결을 얼마나 보수적으로 볼지, 한 번에 얼마까지 넣을지 정해요.">
        <TradeFields draft={draft} onChange={setDraft} />
      </Section>
      <div className="save-bar">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          저장
        </button>
        {save.isSuccess && <span className="ok small">저장했어요. 다음 판단부터 적용돼요.</span>}
        {save.error && <span className="bad small">{save.error.message}</span>}
      </div>
      <SymbolsField key={bot.symbols.map((s) => `${s.symbol}${s.weight}`).join()} bot={bot} />
      <NameField key={bot.name} bot={bot} />
      <History botId={bot.id} />
      <h2 className="danger-title">되돌릴 수 없는 동작</h2>
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
  return (
    <div className="settings">
      <div className="settings-head">
        <Switcher bots={bots} current={selected} creating={creating} />
        <p className="muted small">
          {creating
            ? seed?.strategy
              ? '시험해 본 전략과 종목으로 채워 뒀어요.'
              : '새 모의 투자 봇을 만들어요.'
            : `${basketLabel(selected.symbols, selected.symbol)} · ${byName[selected.strategy]?.nickname ?? selected.strategy} · 시작 금액 ${money(selected.account.initial_cash)}`}
        </p>
      </div>
      {creating ? (
        <NewBotForm key={JSON.stringify(seed)} seed={seed ?? {}} taken={bots.map((b) => b.name)} />
      ) : (
        <BotSettings key={selected.id} bot={selected} others={bots.filter((b) => b.id !== selected.id)} />
      )}
    </div>
  )
}
