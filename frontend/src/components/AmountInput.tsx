import { useState } from 'react'
import { useCurrency } from '../currency'
import { manwon } from '../format'

type Props = {
  value: string
  onChange: (digits: string) => void
  placeholder?: string
  id?: string
  label?: string
  size?: number
}

/** 달러 금액 입력칸. 숫자만 받고, 한글·문자를 치면 왜 안 써지는지 바로 알려준다. */
export function AmountInput({ value, onChange, placeholder = '예: 5000', id, label, size = 8 }: Props) {
  const [warn, setWarn] = useState(false)
  const { currency, rate } = useCurrency()
  // 원화로 볼 때는 달러로 정한 금액이 대략 얼마인지 옆에 보여준다 (기준은 달러)
  const approx = currency === 'KRW' && rate && Number(value) > 0 ? `약 ${manwon(Number(value) * rate)}` : null
  return (
    <>
      <span className="dollar">
        $
        <input
          id={id}
          inputMode="numeric"
          placeholder={placeholder}
          aria-label={label}
          value={value}
          onChange={(e) => {
            const digits = e.target.value.replace(/[^0-9]/g, '')
            setWarn(digits !== e.target.value)
            onChange(digits)
          }}
          onBlur={() => setWarn(false)}
          size={size}
        />
      </span>
      {approx && !warn && <span className="faint small">{approx}</span>}
      {warn && (
        <span className="input-warn small" role="status">
          숫자만 입력할 수 있어요
        </span>
      )}
    </>
  )
}
