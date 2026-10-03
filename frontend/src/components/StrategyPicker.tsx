import type { StrategyInfo } from '../api'
import { StrategyGlyph } from './StrategyGlyph'

/** 전략 카드 (규칙 그림·별명·설명·위험·거래 빈도). 봇 설정과 새 봇 만들기에서 쓴다. */
export function StrategyPicker({
  list,
  value,
  onChange,
}: {
  list: StrategyInfo[]
  value: string
  onChange: (name: string) => void
}) {
  return (
    <div className="pick-grid">
      {list.map((s) => (
        <button key={s.name} className={`pick ${s.name === value ? 'active' : ''}`} onClick={() => onChange(s.name)}>
          <StrategyGlyph name={s.name} />
          <div className="pick-title">
            {s.nickname}
          </div>
          <div className="pick-desc">{s.summary}</div>
          <div className="pick-meta">
            위험 {s.risk} · 거래 {s.trades}
          </div>
        </button>
      ))}
    </div>
  )
}
