// 질문으로 나 만들기 (N3): 쉬운 질문의 답을 "나처럼 모으기"(dip_saver) 규칙 값으로 바꾼다.
// 판단은 언제나 규칙 함수가 한다. 여기서는 값만 채운다 (project.md 1절 "AI의 역할은 질문 → 규칙 값까지").
import type { SymbolWeight } from './api'

export type Answers = {
  symbols: SymbolWeight[]
  deposit: number
  day: number
  hot: number // 0이면 고점에도 쉬지 않음
  dip: number
}

export type Option = { value: number; label: string; sub?: string }

export const DEPOSITS: Option[] = [
  { value: 500, label: '$500' },
  { value: 1000, label: '$1,000' },
  { value: 1350, label: '$1,350', sub: '월 20만 엔 안팎' },
  { value: 2000, label: '$2,000' },
  { value: 3000, label: '$3,000' },
]

export const DAYS: Option[] = [
  { value: 10, label: '10일' },
  { value: 15, label: '15일' },
  { value: 21, label: '21일' },
  { value: 25, label: '25일' },
  { value: 28, label: '말일 무렵', sub: '28일' },
]

export const HOT: Option[] = [
  { value: 0, label: '신경 안 쓰고 그냥 사요', sub: '오를 때도 매달 똑같이 사요' },
  { value: 20, label: '아주 많이 올랐을 때만 쉬어요', sub: '200일 평균보다 20% 넘게 오르면 그달은 쉬어요' },
  { value: 15, label: '꽤 올랐으면 쉬어요', sub: '200일 평균보다 15% 넘게 오르면 그달은 쉬어요' },
  { value: 10, label: '조금만 올라도 쉬고 기다려요', sub: '200일 평균보다 10% 넘게 오르면 그달은 쉬어요' },
]

export const DIP: Option[] = [
  { value: 10, label: '조금만 떨어져도 바로 사요', sub: '1년 최고가보다 10% 넘게 떨어지면' },
  { value: 15, label: '꽤 떨어지면 사요', sub: '1년 최고가보다 15% 넘게 떨어지면' },
  { value: 20, label: '크게 떨어졌을 때만 사요', sub: '1년 최고가보다 20% 넘게 떨어지면' },
]

export const START: Answers = { symbols: [], deposit: 1350, day: 25, hot: 15, dip: 10 }

/** 답 → dip_saver 파라미터 (high·sma는 고정) */
export function toParams(a: Answers): Record<string, number> {
  return { deposit: a.deposit, day: a.day, dip: a.dip, hot: a.hot, high: 252, sma: 200 }
}

const usd = (n: number) => `$${n.toLocaleString('en-US')}`

/** 답을 쉬운 말 몇 문장으로 */
export function describe(a: Answers): string[] {
  const day = a.day >= 28 ? '말일 무렵' : `${a.day}일`
  // 종목 이름 뒤 조사는 받침에 따라 달라지므로 받침과 상관없는 말(%로, 에)만 붙인다.
  const target =
    a.symbols.length > 1
      ? `${a.symbols.map((s) => `${s.symbol} ${s.weight}%`).join(' · ')}로 나눠 사요`
      : `모두 ${a.symbols[0]?.symbol ?? ''}에 써요`
  return [
    `매달 ${day}에 ${usd(a.deposit)}씩 넣어 ${target}.`,
    a.hot
      ? `200일 평균보다 ${a.hot}% 넘게 오르면 그달은 사지 않고 현금으로 모아 둬요.`
      : '많이 올라도 쉬지 않고 매달 똑같이 사요.',
    a.hot
      ? `1년 최고가보다 ${a.dip}% 넘게 떨어지면 모아 둔 돈까지 다 사요.`
      : `1년 최고가보다 ${a.dip}% 넘게 떨어지면 남은 현금을 바로 다 사요.`,
    '산 주식은 팔지 않고 계속 모아요.',
  ]
}
