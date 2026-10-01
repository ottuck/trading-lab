import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { backtestApi, botApi, type Bot, type BotConfig } from '../api'
import { kstTime } from '../format'
import { paramsText, parseParams, STRATEGY_LABEL } from '../strategies'

type Draft = {
  strategy: string
  params: string
  commission: string // %
  slippage: string // bp
  maxPosition: string
  maxOrder: string
}

function toDraft(bot?: Bot): Draft {
  return {
    strategy: bot?.strategy ?? 'sma_cross',
    params: bot ? paramsText(bot.params) : 'fast=50,slow=200',
    commission: bot ? String(Number(bot.commission_rate) * 100) : '0.1',
    slippage: bot?.slippage_bps ?? '5',
    maxPosition: bot?.risk.max_position_value ?? '',
    maxOrder: bot?.risk.max_order_value ?? '',
  }
}

function toConfig(d: Draft): BotConfig {
  return {
    strategy: d.strategy,
    params: parseParams(d.params),
    commission_rate: String(Number(d.commission) / 100),
    slippage_bps: d.slippage,
    max_position_value: d.maxPosition || null,
    max_order_value: d.maxOrder || null,
  }
}

function ConfigFields({ draft, onChange }: { draft: Draft; onChange: (d: Draft) => void }) {
  const { data: strategies } = useQuery({ queryKey: ['strategies'], queryFn: backtestApi.strategies, refetchInterval: false })
  const set = (patch: Partial<Draft>) => onChange({ ...draft, ...patch })
  const pick = (name: string) => {
    const s = strategies?.find((x) => x.name === name)
    set({ strategy: name, params: s ? paramsText(s.default_params) : draft.params })
  }
  return (
    <>
      <label>
        전략
        <select value={draft.strategy} onChange={(e) => pick(e.target.value)}>
          {(strategies ?? []).map((s) => (
            <option key={s.name} value={s.name}>
              {STRATEGY_LABEL[s.name] ?? s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        파라미터
        <input value={draft.params} onChange={(e) => set({ params: e.target.value })} size={22} />
      </label>
      <label>
        수수료 %
        <input value={draft.commission} onChange={(e) => set({ commission: e.target.value })} size={5} />
      </label>
      <label>
        슬리피지 bp
        <input value={draft.slippage} onChange={(e) => set({ slippage: e.target.value })} size={4} />
      </label>
      <label>
        최대 보유 금액 $
        <input value={draft.maxPosition} placeholder="제한 없음" onChange={(e) => set({ maxPosition: e.target.value })} size={9} />
      </label>
      <label>
        1회 주문 한도 $
        <input value={draft.maxOrder} placeholder="제한 없음" onChange={(e) => set({ maxOrder: e.target.value })} size={9} />
      </label>
    </>
  )
}

function History({ botId }: { botId: number }) {
  const { data } = useQuery({ queryKey: ['history', botId], queryFn: () => botApi.history(botId) })
  if (!data?.length) return null
  return (
    <>
      <h3>변경 이력</h3>
      <table>
        <tbody>
          {data.map((e) => (
            <tr key={e.id}>
              <td className="nowrap">{kstTime(e.at)}</td>
              <td>{e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function BotSettings({ bot }: { bot: Bot }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(() => toDraft(bot))
  const save = useMutation({
    mutationFn: () => botApi.updateConfig(bot.id, toConfig(draft)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['bots'] })
      void qc.invalidateQueries({ queryKey: ['history', bot.id] })
    },
  })
  const running = bot.state === 'RUNNING'
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          {bot.name} <span className="muted">· {bot.symbol}</span>
        </h2>
        <span className="muted small">초기 현금 ${Number(bot.account.initial_cash).toLocaleString()} (생성 후 변경 불가)</span>
      </div>
      {running && <p className="notice">실행 중에는 설정을 바꿀 수 없습니다. 대시보드에서 일시정지한 뒤 변경하세요.</p>}
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <ConfigFields draft={draft} onChange={setDraft} />
        <button type="submit" className="primary" disabled={running || save.isPending}>
          저장
        </button>
        {save.isSuccess && <span className="up small">저장했습니다. 다음 판단부터 적용됩니다.</span>}
        {save.error && <span className="down small">{save.error.message}</span>}
      </form>
      <History botId={bot.id} />
    </section>
  )
}

function NewBot() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('QQQ')
  const [cash, setCash] = useState('10000')
  const [draft, setDraft] = useState(() => toDraft())
  const create = useMutation({
    mutationFn: () => botApi.create({ ...toConfig(draft), name, symbol, initial_cash: cash }),
    onSuccess: () => {
      setName('')
      void qc.invalidateQueries({ queryKey: ['bots'] })
    },
  })
  return (
    <section className="panel">
      <h2>새 봇</h2>
      <p className="muted small">중지 상태로 만들어집니다. 대시보드에서 시작하세요. 토스가 지원하는 미국 종목이어야 합니다.</p>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
      >
        <label>
          이름
          <input value={name} onChange={(e) => setName(e.target.value)} size={12} required />
        </label>
        <label>
          종목
          <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} size={6} required />
        </label>
        <label>
          초기 현금 $
          <input value={cash} onChange={(e) => setCash(e.target.value)} size={8} />
        </label>
        <ConfigFields draft={draft} onChange={setDraft} />
        <button type="submit" className="primary" disabled={create.isPending}>
          만들기
        </button>
        {create.error && <span className="down small">{create.error.message}</span>}
      </form>
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
