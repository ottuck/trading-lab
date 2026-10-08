import { useState } from 'react'
import type { StrategyInfo } from '../api'
import { applyPreset, presetOf } from '../strategies'
import { MAX_DEPOSIT } from '../format'
import { AmountInput } from './AmountInput'

type Props = { info: StrategyInfo; params: Record<string, number>; onChange: (p: Record<string, number>) => void; custom?: boolean }

/** 프리셋(반응 속도·매달 넣는 돈)과 따로 고르는 규칙(고점에 쉬기 등). 설정·새 봇·시험해 보기 공용.
    매달 넣는 돈은 프리셋 말고 직접 입력할 수도 있다. 전략을 바꾸면 입력칸을 새로 시작한다. */
export function PresetFields(props: Props) {
  return <Fields key={props.info.name} {...props} />
}

function Fields({ info, params, onChange, custom }: Props) {
  const current = presetOf(info, params)
  const hasDeposit = 'deposit' in info.default_params
  // 직접 입력 중인 글자 (비우는 중에도 그대로 보이게). 없으면 프리셋이 아닐 때만 지금 금액을 보여준다
  const [typed, setTyped] = useState<string | null>(null)
  const depositText = typed ?? (current ? '' : String(params.deposit ?? ''))
  // 예전 봇은 나중에 생긴 규칙 값이 없으므로 기본값으로 본다.
  const valueOf = (key: string) => params[key] ?? info.default_params[key]
  const choices = info.choices.filter((c) => !c.requires || valueOf(c.requires))
  return (
    <>
      {info.presets.length > 1 && (
        <div className="controls">
          <span className="label">{info.preset_label}</span>
          {info.presets.map((p) => (
            <button
              key={p.key}
              className={`seg ${current?.key === p.key ? 'active' : ''}`}
              onClick={() => {
                setTyped(null)
                onChange(applyPreset(info, params, p.params))
              }}
            >
              {p.label}
            </button>
          ))}
          {hasDeposit && (
            <AmountInput
              value={depositText}
              placeholder="직접 입력"
              label={`${info.preset_label} 직접 입력`}
              max={MAX_DEPOSIT}
              onChange={(v) => {
                setTyped(v)
                if (Number(v) > 0 && Number(v) <= MAX_DEPOSIT) onChange({ ...params, deposit: Number(v) })
              }}
            />
          )}
          {custom && !current && !hasDeposit && <span className="faint small">직접 설정한 값 사용 중</span>}
        </div>
      )}
      {choices.map((c) => (
        <div key={c.key} className="controls" title={c.hint}>
          <span className="label">{c.label}</span>
          {c.options.map((o) => (
            <button
              key={o.value}
              className={`seg ${valueOf(c.key) === o.value ? 'active' : ''}`}
              aria-pressed={valueOf(c.key) === o.value}
              onClick={() => onChange({ ...params, [c.key]: o.value })}
            >
              {o.label}
            </button>
          ))}
        </div>
      ))}
      {choices.length > 0 && <div className="faint small">{choices.map((c) => c.hint).join(' ')}</div>}
    </>
  )
}
