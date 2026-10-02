import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, botApi, type Bot } from '../api'
import { ago, money } from '../format'
import { closeNewBot, selectBot, startNewBot, useNewBotSeed, useSelectedBot, type NewBotSeed } from '../selectedBot'
import { strategyTitle, useStrategies } from '../strategies'
import { toConfig, toDraft, type Draft } from '../botConfig'
import { ConfigFields } from './BotConfigFields'
import { SymbolPicker } from './SymbolPicker'

function History({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['history', botId], queryFn: () => api.activity(botId, 'config_change') })
  if (!data?.length) return null
  return (
    <>
      <h3>바꾼 기록</h3>
      <ul className="activity">
        {data.map((a) => (
          <li key={a.id}>
            <span className="icon">{a.icon}</span>
            <div>
              <div className="title">{a.title}</div>
              {a.body && <div className="muted small body">{a.body}</div>}
              <div className="faint small">{ago(a.at)}</div>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}

function sameStrategy(d: Draft, bot: Bot) {
  return d.strategy === bot.strategy && JSON.stringify(d.params) === JSON.stringify(bot.params)
}

function NameEditor({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(bot.name)
  const rename = useMutation({
    mutationFn: () => botApi.rename(bot.id, name),
    onSuccess: () => {
      setEditing(false)
      void qc.invalidateQueries({ queryKey: ['bots'] })
      void qc.invalidateQueries({ queryKey: ['history', bot.id] })
    },
  })
  if (!editing) {
    return (
      <div className="name-row">
        <h2>{bot.name}</h2>
        <button className="link" onClick={() => setEditing(true)}>
          이름 바꾸기
        </button>
      </div>
    )
  }
  return (
    <div className="name-row">
      <input value={name} onChange={(e) => setName(e.target.value)} size={14} autoFocus />
      <button className="primary" disabled={rename.isPending || !name.trim()} onClick={() => rename.mutate()}>
        저장
      </button>
      <button
        className="ghost"
        onClick={() => {
          setName(bot.name)
          setEditing(false)
        }}
      >
        취소
      </button>
      {rename.error && <span className="bad small">{rename.error.message}</span>}
    </div>
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
    <div className="danger-zone">
      <h3>봇 관리</h3>
      <div className="controls">
        <button disabled={reset.isPending} onClick={() => confirmReset() && reset.mutate()}>
          처음부터 다시 시작
        </button>
        <button
          className="danger"
          disabled={remove.isPending}
          onClick={() => window.confirm(`${bot.name} 봇과 모든 기록을 지울까요? 되돌릴 수 없어요.`) && remove.mutate()}
        >
          봇 삭제
        </button>
        {error && <span className="bad small">{error.message}</span>}
      </div>
    </div>
  )
}

function BotSettings({ bot, others }: { bot: Bot; others: Bot[] }) {
  const qc = useQueryClient()
  const { byName } = useStrategies()
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
    <section className="card stack">
      <div className="panel-head">
        <NameEditor key={bot.name} bot={bot} />
        <span className="muted small">
          {bot.symbol} · {strategyTitle(byName[bot.strategy], bot.strategy)} · 시작 금액 {money(bot.account.initial_cash)}
        </span>
      </div>
      <ConfigFields draft={draft} onChange={setDraft} />
      {changing && bot.account.qty > 0 && (
        <div className="notice">
          지금 {bot.symbol} {bot.account.qty}주를 들고 있어요. 저장하면 다음 판단부터 새 전략으로 봐요. 새 전략이 &quot;팔
          때&quot;라고 보면 그다음 장이 열릴 때 바로 팔아요.
        </div>
      )}
      <div className="controls">
        <button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          저장
        </button>
        {save.isSuccess && <span className="ok small">저장했어요. 다음 판단부터 적용돼요.</span>}
        {save.error && <span className="bad small">{save.error.message}</span>}
        {save.isIdle && <span className="faint small">돌아가는 중에도 바꿀 수 있어요. 다음 판단부터 적용돼요.</span>}
      </div>
      <History botId={bot.id} />
      <DangerZone bot={bot} others={others} />
    </section>
  )
}

const SHORT: Record<string, string> = { sma_cross: 'sma', trend_filter: '200', rsi2: 'rsi', donchian: 'high' }

function suggestName(symbol: string, strategy: string, taken: string[]) {
  const base = `${symbol.toLowerCase()}-${SHORT[strategy] ?? strategy}`
  let name = base
  for (let i = 2; taken.includes(name); i++) name = `${base}-${i}`
  return name
}

function NewBotForm({ seed, taken }: { seed: NewBotSeed; taken: string[] }) {
  const qc = useQueryClient()
  const [symbol, setSymbol] = useState(seed.symbol ?? 'QQQ')
  const [draft, setDraft] = useState(() =>
    toDraft(seed.strategy ? { strategy: seed.strategy, params: seed.params ?? {} } : undefined),
  )
  // 이름은 직접 고치기 전까지 종목·전략에 맞춰 자동으로 제안한다.
  const [customName, setCustomName] = useState<string | null>(null)
  const name = customName ?? suggestName(symbol, draft.strategy, taken)
  const [cash, setCash] = useState('10000')
  const [startNow, setStartNow] = useState(true)
  const create = useMutation({
    mutationFn: async () => {
      const bot = await botApi.create({ ...toConfig(draft), name, symbol, initial_cash: cash })
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
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        새 봇 만들기 {seed.strategy && <span className="sub">시험해 본 전략과 종목으로 채워 뒀어요</span>}
      </div>
      <div className="form">
        <label>
          이름
          <input value={name} onChange={(e) => setCustomName(e.target.value)} size={14} />
        </label>
        <label>
          시작 금액 $
          <input value={cash} inputMode="numeric" onChange={(e) => setCash(e.target.value.replace(/[^0-9]/g, ''))} size={8} />
        </label>
      </div>
      <SymbolPicker label="종목" value={symbol} onChange={setSymbol} />
      <ConfigFields draft={draft} onChange={setDraft} />
      <label className="toggle">
        <input type="checkbox" checked={startNow} onChange={(e) => setStartNow(e.target.checked)} />
        만들면 바로 모의 투자 시작
      </label>
      <div className="controls">
        <button className="primary" disabled={create.isPending || !name.trim() || !cash} onClick={() => create.mutate()}>
          {startNow ? '만들고 시작하기' : '만들기'}
        </button>
        {taken.length > 0 && (
          <button className="ghost" onClick={closeNewBot}>
            취소
          </button>
        )}
        {create.error && <span className="bad small">{create.error.message}</span>}
      </div>
    </section>
  )
}

/** 설정: 홈에서 고른 봇 하나를 바꾼다. 위쪽에서 다른 봇을 고르거나 새 봇을 만든다. */
export function SettingsView({ bots }: { bots: Bot[] }) {
  const seed = useNewBotSeed()
  const selected = useSelectedBot(bots)
  const creating = seed !== null || !bots.length
  return (
    <>
      <div className="controls bot-chips">
        {bots.map((b) => (
          <button
            key={b.id}
            className={`seg ${!creating && b.id === selected?.id ? 'active' : ''}`}
            onClick={() => {
              closeNewBot()
              selectBot(b.id)
            }}
          >
            {b.name} <span className="chip-sub">{b.symbol}</span>
          </button>
        ))}
        <button className={`seg ${creating ? 'active' : ''}`} onClick={() => startNewBot()}>
          + 새 봇
        </button>
      </div>
      {creating ? (
        <NewBotForm key={JSON.stringify(seed)} seed={seed ?? {}} taken={bots.map((b) => b.name)} />
      ) : (
        selected && <BotSettings key={selected.id} bot={selected} others={bots.filter((b) => b.id !== selected.id)} />
      )}
    </>
  )
}
