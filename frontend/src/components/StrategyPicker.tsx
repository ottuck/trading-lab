import type { StrategyInfo } from '../api'

/** 전략 카드 4개 (별명·설명·위험·거래 빈도). 시험해 보기와 봇 설정에서 같이 쓴다. */
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
