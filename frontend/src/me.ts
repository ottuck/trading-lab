// 나 카피하기 (N3, 질문으로 나 만들기): 쉬운 질문의 답을 "나처럼 투자"(dip_saver) 규칙 값으로 바꾼다.
// 판단은 언제나 규칙 함수가 한다. 여기서는 값만 채운다 (project.md 1절 "AI의 역할은 질문 → 규칙 값까지").
import type { Bot, SymbolWeight } from './api'

export type Answers = {
  symbols: SymbolWeight[]
  regular: number // 1: 매달 산다, 0: 떨어졌을 때만 산다
  deposit: number // 투자에 쓰는 돈의 한 달 평균 (매달 사지 않아도)
  day: number // 0이면 정해진 날 없음 (말일 무렵으로 계산)
  hot: number // 0이면 고점에도 쉬지 않음
  dip: number
}

export type Step = 'symbols' | 'style' | 'deposit' | 'day' | 'hot' | 'dip'

/** 답에 따라 묻는 질문. 떨어졌을 때만 사면 넣는 날·고점 질문은 의미가 없어 건너뛴다. */
export function stepsOf(a: Answers): Step[] {
  return a.regular ? ['symbols', 'style', 'deposit', 'day', 'hot', 'dip'] : ['symbols', 'style', 'deposit', 'dip']
}

export const STYLES: Option[] = [
  { value: 1, label: '매달 꾸준히 사요', sub: '월급날처럼 정해진 때에 넣은 만큼 사요' },
  { value: 0, label: '떨어졌을 때만 몰아서 사요', sub: '평소엔 모아 두고 크게 떨어지면 한꺼번에 사요' },
]

export type Option = { value: number; label: string; sub?: string }

// 달러로 딱 떨어지는 금액. 그 밖의 금액은 직접 입력한다 (원화는 환율 따라 바뀌어 기준으로 쓰지 않는다)
export const DEPOSITS: Option[] = [
  { value: 300, label: '$300' },
  { value: 500, label: '$500' },
  { value: 1000, label: '$1,000' },
  { value: 1500, label: '$1,500' },
  { value: 2000, label: '$2,000' },
  { value: 3000, label: '$3,000' },
]

export const DAYS: Option[] = [
  { value: 10, label: '10일' },
  { value: 15, label: '15일' },
  { value: 21, label: '21일' },
  { value: 25, label: '25일' },
  { value: 28, label: '말일 무렵', sub: '28일' },
  { value: 0, label: '정해진 날 없어요', sub: '매달 말일 무렵에 넣는 것으로 계산해요' },
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

/** 평행세계에서 고른 값처럼 선택지에 없는 지금 값도 고른 채로 보여준다 (예: -5%에 바로 사는 나). */
export function withCurrent(options: Option[], value: number): Option[] {
  if (options.some((o) => o.value === value)) return options
  const sub = options === DIP ? `1년 최고가보다 ${value}% 넘게 떨어지면` : `200일 평균보다 ${value}% 넘게 오르면 그달은 쉬어요`
  return [...options, { value, label: '지금 규칙 그대로', sub }]
}

export const START: Answers = { symbols: [], regular: 1, deposit: 1000, day: 25, hot: 15, dip: 10 }

/** 이미 있는 나 카피 봇의 규칙 → 답 (다시 카피하기) */
export function answersOf(bot: Bot): Answers {
  const p = bot.params
  return {
    symbols: bot.symbols.filter((s) => s.weight > 0),
    regular: p.regular ?? 1,
    deposit: p.deposit ?? START.deposit,
    day: p.day ?? START.day,
    hot: p.hot ?? START.hot,
    dip: p.dip ?? START.dip,
  }
}

/** 답 → dip_saver 파라미터 (high·sma는 고정) */
export function toParams(a: Answers): Record<string, number> {
  return { deposit: a.deposit, day: a.day || 28, dip: a.dip, hot: a.hot, high: 252, sma: 200, regular: a.regular }
}

const usd = (n: number) => `$${n.toLocaleString('en-US')}`

/** 답을 쉬운 말 몇 문장으로 */
export function describe(a: Answers): string[] {
  const when = a.day === 0 ? '매달 한 번' : a.day >= 28 ? '매달 말일 무렵에' : `매달 ${a.day}일에`
  // 종목 이름 뒤 조사는 받침에 따라 달라지므로 받침과 상관없는 말(%로, 에)만 붙인다.
  const target =
    a.symbols.length > 1
      ? `${a.symbols.map((s) => `${s.symbol} ${s.weight}%`).join(' · ')}로 나눠 사요`
      : `모두 ${a.symbols[0]?.symbol ?? ''}에 써요`
  if (!a.regular)
    return [
      `투자에 쓰는 돈을 한 달 평균 ${usd(a.deposit)}씩 모아 두기만 하고, 평소엔 사지 않아요.`,
      `1년 최고가보다 ${a.dip}% 넘게 떨어지면 모아 둔 돈을 한꺼번에 ${
        a.symbols.length > 1 ? target : `${a.symbols[0]?.symbol ?? ''}에 써요`
      }.`,
      '산 주식은 팔지 않고 계속 모아요.',
    ]
  return [
    `${when} ${usd(a.deposit)}씩 넣어 ${target}.`,
    a.hot
      ? `200일 평균보다 ${a.hot}% 넘게 오르면 그달은 사지 않고 현금으로 모아 둬요.`
      : '많이 올라도 쉬지 않고 매달 똑같이 사요.',
    a.hot
      ? `1년 최고가보다 ${a.dip}% 넘게 떨어지면 모아 둔 돈까지 다 사요.`
      : `1년 최고가보다 ${a.dip}% 넘게 떨어지면 남은 현금을 바로 다 사요.`,
    '산 주식은 팔지 않고 계속 모아요.',
  ]
}
