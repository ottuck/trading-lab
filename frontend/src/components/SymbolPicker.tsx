import { FALLBACK, leverageOf, useInstruments } from '../instruments'
import { Term } from './Help'

/** 관심 종목 버튼. 레버리지 ETF는 "3배" 표시와 주의 문구를 함께 보여준다. */
export function SymbolPicker({ label, value, onChange }: { label: string; value: string; onChange: (s: string) => void }) {
  const { data } = useInstruments()
  const symbols = data?.map((i) => i.symbol) ?? FALLBACK
  const lev = leverageOf(data, value)
  return (
    <>
      <div className="controls">
        <span className="label">{label}</span>
        {symbols.map((s) => {
          const x = leverageOf(data, s)
          return (
            <button key={s} className={`seg ${s === value ? 'active' : ''}`} onClick={() => onChange(s)}>
              {s}
              {x > 1 && <span className="lev">{x}배</span>}
            </button>
          )
        })}
      </div>
      {lev > 1 && <LeverageNotice symbol={value} factor={lev} />}
    </>
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
