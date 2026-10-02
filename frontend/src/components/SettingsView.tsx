import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, botApi, type Bot, type BotConfig } from '../api'
import { ago, money } from '../format'
import { presetOf, SLIPPAGE_CHOICES, strategyTitle, useStrategies } from '../strategies'
import { StrategyPicker } from './BacktestView'
import { Term } from './Help'
import { SymbolPicker } from './SymbolPicker'

type Draft = {
  strategy: string
  params: Record<string, number>
  slippage: string
  maxPosition: string // 빈 값이면 제한 없음
}

function toDraft(bot?: Bot): Draft {
  return {
    strategy: bot?.strategy ?? 'sma_cross',
    params: bot?.params ?? { fast: 50, slow: 200 },
    slippage: bot ? String(Number(bot.slippage_bps)) : '5',
    maxPosition: bot?.risk.max_position_value ?? '',
  }
}

function toConfig(d: Draft, bot?: Bot): BotConfig {
  return {
    strategy: d.strategy,
    params: d.params,
    commission_rate: bot?.commission_rate ?? '0.001', // 토스증권 요율 고정 (화면에서 바꾸지 않음)
    slippage_bps: d.slippage,
    max_position_value: d.maxPosition || null,
    max_order_value: bot?.risk.max_order_value ?? null,
  }
}

function ConfigFields({ draft, onChange }: { draft: Draft; onChange: (d: Draft) => void }) {
  const { list, byName } = useStrategies()
  const info = byName[draft.strategy]
  const current = presetOf(info, draft.params)
  const set = (patch: Partial<Draft>) => onChange({ ...draft, ...patch })
  return (
    <div className="stack">
      <div>
        <div className="label" style={{ marginBottom: 6 }}>
          어떤 전략으로 할까요?
        </div>
        <StrategyPicker
          list={list}
          value={draft.strategy}
          onChange={(name) => set({ strategy: name, params: byName[name]?.default_params ?? {} })}
        />
      </div>
      {info && info.presets.length > 1 && (
        <div className="controls">
          <span className="label">반응 속도</span>
          {info.presets.map((p) => (
            <button key={p.key} className={`seg ${current?.key === p.key ? 'active' : ''}`} onClick={() => set({ params: p.params })}>
              {p.label}
            </button>
          ))}
          {!current && <span className="faint small">직접 설정한 값 사용 중</span>}
        </div>
      )}
      <div className="controls">
        <span className="label">
          <Term k="체결 가격 가정" />
        </span>
        {SLIPPAGE_CHOICES.map((c) => (
          <button key={c.bps} className={`seg ${c.bps === draft.slippage ? 'active' : ''}`} onClick={() => set({ slippage: c.bps })} title={c.hint}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="controls">
        <span className="label">
          <Term k="최대 투자 금액" />
        </span>
        <button className={`seg ${!draft.maxPosition ? 'active' : ''}`} onClick={() => set({ maxPosition: '' })}>
          가진 현금 전부
        </button>
        <span className="dollar">
          $
          <input
            inputMode="numeric"
            placeholder="직접 입력"
            value={draft.maxPosition}
            onChange={(e) => set({ maxPosition: e.target.value.replace(/[^0-9]/g, '') })}
            size={8}
          />
        </span>
      </div>
      <div className="faint small">
        <Term k="수수료">수수료</Term>는 토스증권 요율(0.1%)이 자동으로 적용돼요.
      </div>
    </div>
  )
}

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

function BotSettings({ bot }: { bot: Bot }) {
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
  const running = bot.state === 'RUNNING'
  return (
    <section className="card stack">
      <div className="panel-head">
        <div className="card-title" style={{ marginBottom: 0 }}>
          {bot.name} <span className="sub">{bot.symbol} · {strategyTitle(byName[bot.strategy], bot.strategy)}</span>
        </div>
        <span className="muted small">시작 금액 {money(bot.account.initial_cash)}</span>
      </div>
      {running && <div className="notice">돌아가는 중에는 바꿀 수 없어요. 홈의 ⋯ 메뉴에서 [잠시 멈춤]을 누른 뒤 바꿔 주세요.</div>}
      <fieldset disabled={running} className="plain">
        <ConfigFields draft={draft} onChange={setDraft} />
      </fieldset>
      <div className="controls">
        <button className="primary" disabled={running || save.isPending} onClick={() => save.mutate()}>
          저장
        </button>
        {save.isSuccess && <span className="ok small">저장했어요. 다음 판단부터 적용돼요.</span>}
        {save.error && <span className="bad small">{save.error.message}</span>}
      </div>
      <History botId={bot.id} />
    </section>
  )
}

function NewBot() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('VOO')
  const [cash, setCash] = useState('10000')
  const [draft, setDraft] = useState(() => toDraft())
  const create = useMutation({
    mutationFn: () => botApi.create({ ...toConfig(draft), name, symbol, initial_cash: cash }),
    onSuccess: () => {
      setName('')
      setOpen(false)
      void qc.invalidateQueries({ queryKey: ['bots'] })
    },
  })
  if (!open) {
    return (
      <button className="link" onClick={() => setOpen(true)}>
        + 봇 하나 더 만들기
      </button>
    )
  }
  return (
    <section className="card stack">
      <div className="card-title" style={{ marginBottom: 0 }}>
        새 봇 만들기
      </div>
      <div className="form">
        <label>
          이름
          <input value={name} onChange={(e) => setName(e.target.value)} size={12} placeholder="예: voo-봇" />
        </label>
        <label>
          시작 금액 $
          <input value={cash} inputMode="numeric" onChange={(e) => setCash(e.target.value.replace(/[^0-9]/g, ''))} size={8} />
        </label>
      </div>
      <SymbolPicker label="종목" value={symbol} onChange={setSymbol} />
      <ConfigFields draft={draft} onChange={setDraft} />
      <div className="controls">
        <button className="primary" disabled={create.isPending || !name} onClick={() => create.mutate()}>
          만들기
        </button>
        <button className="ghost" onClick={() => setOpen(false)}>
          취소
        </button>
        {create.error && <span className="bad small">{create.error.message}</span>}
      </div>
    </section>
  )
}

export function SettingsView({ bots }: { bots: Bot[] }) {
  return (
    <>
      {bots.map((b) => (
        <BotSettings key={`${b.id}-${b.state}`} bot={b} />
      ))}
      <NewBot />
    </>
  )
}
