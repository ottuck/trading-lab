import type { StrategyInfo } from '../api'
import { applyPreset, presetOf } from '../strategies'

type Props = { info: StrategyInfo; params: Record<string, number>; onChange: (p: Record<string, number>) => void; custom?: boolean }

/** 프리셋(반응 속도·매달 넣는 돈)과 따로 고르는 규칙(고점에 쉬기 등). 설정·새 봇·시험해 보기 공용. */
export function PresetFields({ info, params, onChange, custom }: Props) {
  const current = presetOf(info, params)
  return (
    <>
      {info.presets.length > 1 && (
        <div className="controls">
          <span className="label">{info.preset_label}</span>
          {info.presets.map((p) => (
            <button
              key={p.key}
              className={`seg ${current?.key === p.key ? 'active' : ''}`}
              onClick={() => onChange(applyPreset(info, params, p.params))}
            >
              {p.label}
            </button>
          ))}
          {custom && !current && <span className="faint small">직접 설정한 값 사용 중</span>}
        </div>
      )}
      {info.choices.map((c) => (
        <div key={c.key} className="controls" title={c.hint}>
          <span className="label">{c.label}</span>
          {c.options.map((o) => (
            <button
              key={o.value}
              className={`seg ${params[c.key] === o.value ? 'active' : ''}`}
              aria-pressed={params[c.key] === o.value}
              onClick={() => onChange({ ...params, [c.key]: o.value })}
            >
              {o.label}
            </button>
          ))}
        </div>
      ))}
      {info.choices.length > 0 && (
        <div className="faint small">{info.choices.map((c) => c.hint).join(' ')}</div>
      )}
    </>
  )
}
