import type { Draft } from '../botConfig'
import { SLIPPAGE_CHOICES, useStrategies } from '../strategies'
import { Term } from './Help'
import { PresetFields } from './PresetFields'
import { StrategyPicker } from './StrategyPicker'

type Props = { draft: Draft; onChange: (d: Draft) => void }

/** 전략 카드와 반응 속도. 설정 화면과 새 봇 만들기에서 같이 쓴다. */
export function StrategyFields({ draft, onChange }: Props) {
  const { list, byName } = useStrategies()
  const info = byName[draft.strategy]
  return (
    <div className="stack">
      <StrategyPicker
        list={list}
        value={draft.strategy}
        onChange={(name) => onChange({ ...draft, strategy: name, params: byName[name]?.default_params ?? {} })}
      />
      {info && <PresetFields info={info} params={draft.params} onChange={(params) => onChange({ ...draft, params })} custom />}
    </div>
  )
}

/** 체결 가격 가정과 최대 투자 금액. */
export function TradeFields({ draft, onChange }: Props) {
  const set = (patch: Partial<Draft>) => onChange({ ...draft, ...patch })
  return (
    <div className="stack">
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
