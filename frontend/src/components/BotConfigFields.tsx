import { badLimit, type Draft } from '../botConfig'
import { SLIPPAGE_CHOICES, useStrategies } from '../strategies'
import { Term } from './Help'
import { AmountInput } from './AmountInput'
import { PresetFields } from './PresetFields'
import { StrategyPicker } from './StrategyPicker'

type Props = { draft: Draft; onChange: (d: Draft) => void }

/** 전략 카드와 반응 속도. 설정 화면과 새 봇 만들기에서 같이 쓴다. */
export function StrategyFields({ draft, onChange }: Props) {
  const { list, byName } = useStrategies()
  const info = byName[draft.strategy]
  // 나 카피 봇은 전략을 바꾸지 않고 내 규칙만 고친다. 다른 봇은 유명 전략 중에서 고른다.
  return (
    <div className="stack">
      {!info?.accumulates && (
        <StrategyPicker
          list={list.filter((s) => !s.accumulates)}
          value={draft.strategy}
          onChange={(name) => onChange({ ...draft, strategy: name, params: byName[name]?.default_params ?? {} })}
        />
      )}
      {info && <PresetFields info={info} params={draft.params} onChange={(params) => onChange({ ...draft, params })} custom />}
    </div>
  )
}

/** 체결 가격 가정과 최대 투자 금액. 모으기 봇은 최대 금액에 닿으면 매달 사기가 멈추므로 칸을 숨긴다
    (예전에 정해 둔 값이 있으면 지울 수 있게 보여준다). */
export function TradeFields({ draft, onChange, accumulates }: Props & { accumulates?: boolean }) {
  const set = (patch: Partial<Draft>) => onChange({ ...draft, ...patch })
  const showLimit = !accumulates || draft.maxPosition !== ''
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
      {showLimit && (
        <div className="controls">
          <span className="label">
            <Term k="최대 투자 금액" />
          </span>
          <button className={`seg ${!draft.maxPosition ? 'active' : ''}`} onClick={() => set({ maxPosition: '' })}>
            가진 현금 전부
          </button>
          <AmountInput value={draft.maxPosition} onChange={(maxPosition) => set({ maxPosition })} label="최대 투자 금액 직접 입력" />
          {badLimit(draft) && <span className="bad small">$1 이상으로 정해 주세요. 없애려면 [가진 현금 전부]</span>}
          {accumulates && <span className="faint small">이 금액에 닿으면 매달 사기를 멈춰요</span>}
        </div>
      )}
      <div className="faint small">
        <Term k="수수료">수수료</Term>는 토스증권 요율(0.1%)이 자동으로 적용돼요.
      </div>
    </div>
  )
}
