// 표시용 변환. 계산은 백엔드가 하고 화면은 숫자를 보기 좋게만 바꾼다.

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export function money(value: string | null | undefined): string {
  return value == null ? '—' : usd.format(Number(value))
}

export function signedMoney(value: string | null | undefined): string {
  if (value == null) return '—'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${usd.format(n)}`
}

export function percent(value: string | null | undefined): string {
  if (value == null) return '—'
  const n = Number(value) * 100
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

/** 가격·수익 부호에 따른 색 클래스 (오르면 빨강, 내리면 파랑). */
export function tone(value: string | null | undefined): string {
  if (value == null) return ''
  const n = Number(value)
  return n > 0 ? 'rise' : n < 0 ? 'fall' : ''
}

// 시각은 모두 KST로 보여준다 (DB는 UTC).
const kst = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function kstTime(iso: string | null | undefined): string {
  return iso ? `${kst.format(new Date(iso))} KST` : '—'
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return ''
  const sec = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 0) {
    const m = Math.round(-sec / 60)
    return m < 60 ? `${m}분 후` : `${Math.round(m / 60)}시간 후`
  }
  if (sec < 60) return `${sec}초 전`
  const m = Math.round(sec / 60)
  return m < 60 ? `${m}분 전` : m < 60 * 24 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`
}

/** 이미 지난 시각인지 (예: 예정된 판단 시각이 지났는지). */
export function isPast(iso: string | null | undefined): boolean {
  return !!iso && new Date(iso).getTime() <= Date.now()
}

/** 주식 수량. 소수점은 6자리까지 (토스 소수점 거래), 끝자리 0은 지운다. 예: '0.962140' → '0.96214' */
export function shares(value: string | number | null | undefined, digits = 6): string {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-US', { maximumFractionDigits: digits })
}
