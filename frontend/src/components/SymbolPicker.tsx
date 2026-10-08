import type { SymbolWeight } from '../api'
import { evenSplit, MAX_SYMBOLS } from '../basket'
import { FALLBACK, leverageOf, useInstruments } from '../instruments'
import { Term } from './Help'

/** 여러 종목과 비율 고르기 (모으기 전략). 최대 10개, 비율 합 100. 고르거나 빼면 똑같이 다시 나눈다. */
export function BasketPicker({ value, onChange }: { value: SymbolWeight[]; onChange: (v: SymbolWeight[]) => void }) {
  const { data } = useInstruments()
  const symbols = data?.map((i) => i.symbol) ?? FALLBACK
  const picked = value.map((v) => v.symbol)
  const total = value.reduce((sum, v) => sum + v.weight, 0)
  const toggle = (s: string) => {
    if (picked.includes(s)) {
      if (picked.length > 1) onChange(evenSplit(picked.filter((p) => p !== s)))
    } else if (picked.length < MAX_SYMBOLS) {
      onChange(evenSplit([...picked, s]))
    }
  }
  const setWeight = (s: string, weight: number) => onChange(value.map((v) => (v.symbol === s ? { ...v, weight } : v)))
  const leveraged = picked.map((s) => [s, leverageOf(data, s)] as const).filter(([, x]) => x > 1)
  return (
    <div className="stack">
      <div className="controls">
        {symbols.map((s) => {
          const x = leverageOf(data, s)
          return (
            <button
              key={s}
              className={`seg ${picked.includes(s) ? 'active' : ''}`}
              aria-pressed={picked.includes(s)}
              disabled={!picked.includes(s) && picked.length >= MAX_SYMBOLS}
              onClick={() => toggle(s)}
            >
              {s}
              {x > 1 && <span className="lev">{x}배</span>}
            </button>
          )
        })}
      </div>
      <div className="faint small">평소 가장 많이 사는 종목부터 골라 주세요. 보통 2~5개면 충분해요 (최대 {MAX_SYMBOLS}개).</div>
      {value.length > 1 && (
        <div className="weights">
          {value.map((v) => (
            <label key={v.symbol} className="weight">
              <span>{v.symbol}</span>
              <input
                id={`weight-${v.symbol}`}
                type="number"
                inputMode="numeric"
                min={1}
                max={99}
                step={5}
                value={v.weight}
                onChange={(e) => setWeight(v.symbol, Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
              />
              <span className="faint">%</span>
            </label>
          ))}
          <span className={`small ${total === 100 ? 'faint' : 'bad'}`}>합계 {total}%</span>
          <button className="link" onClick={() => onChange(evenSplit(picked))}>
            똑같이 나누기
          </button>
        </div>
      )}
      {leveraged.map(([s, x]) => (
        <LeverageNotice key={s} symbol={s} factor={x} />
      ))}
    </div>
  )
}

export function LeverageNotice({ symbol, factor }: { symbol: string; factor: number }) {
  return (
    <div className="notice">
      <Term k="레버리지 ETF">
        <b>{symbol}</b>는 {factor}배로 움직이는 상품이에요.
      </Term>{' '}
      기초 지수가 하루 1% 오르면 약 {factor}% 오르고, 1% 내리면 약 {factor}% 내려요. 오르내림이 반복되면
      시간이 갈수록 손해가 쌓일 수 있어요.
    </div>
  )
}
