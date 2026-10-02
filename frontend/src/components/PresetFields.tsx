import type { StrategyInfo } from '../api'
import { applyPreset, presetOf } from '../strategies'

type Props = { info: StrategyInfo; params: Record<string, number>; onChange: (p: Record<string, number>) => void; custom?: boolean }

/** 프리셋(반응 속도·매달 넣는 돈)과 따로 고르는 규칙(고점에 쉬기 등). 설정·새 봇·시험해 보기 공용. */
export function PresetFields({ info, params, onChange, custom }: Props) {
  const current = presetOf(info, params)
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
              onClick={() => onChange(applyPreset(info, params, p.params))}
            >
              {p.label}
            </button>
          ))}
          {custom && !current && <span className="faint small">직접 설정한 값 사용 중</span>}
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
