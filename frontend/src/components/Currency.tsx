import { setCurrency, useCurrency } from '../currency'

const fmt = (rate: number) => Math.round(rate).toLocaleString('ko-KR')

/** 머리말의 $ / ₩ 바꾸기. 환율을 아직 못 받았으면 보이지 않는다. */
export function CurrencyToggle() {
  const { currency, rate } = useCurrency()
  if (!rate) return null
  const krw = currency === 'KRW'
  const label = krw ? '달러로 보기' : `원화로 보기 (1달러 ${fmt(rate)}원)`
  return (
    <button className="icon-btn currency-btn" aria-label={label} title={label} onClick={() => setCurrency(krw ? 'USD' : 'KRW')}>
      {krw ? '₩' : '$'}
    </button>
  )
}

/** 원화로 볼 때 큰 금액 아래에 작게: "오늘 환율 1,380원으로 바꾼 값이에요" */
export function FxNote() {
  const { currency, rate, source } = useCurrency()
  if (currency !== 'KRW' || !rate) return null
  return (
    <div className="fx-note faint small">
      {source === 'demo' ? '예시 환율' : '오늘 환율'} {fmt(rate)}원으로 바꾼 값이에요
    </div>
  )
}
