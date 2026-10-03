// 여러 종목 봇의 종목·비율 도우미 (비율 합 100, 최대 10개).
import type { SymbolWeight } from './api'

export const MAX_SYMBOLS = 10

/** 비율을 똑같이 나눈다 (합 100, 나머지는 앞 종목부터 1%씩). */
export function evenSplit(symbols: string[]): SymbolWeight[] {
  const base = Math.floor(100 / symbols.length)
  return symbols.map((symbol, i) => ({ symbol, weight: base + (i < 100 - base * symbols.length ? 1 : 0) }))
}

/** 사는 종목만 (비율 0은 종목을 바꾸며 뺐지만 들고만 있는 종목). */
export function activeOf(symbols: SymbolWeight[]): SymbolWeight[] {
  return symbols.filter((s) => s.weight > 0)
}

/** 'VOO 50% · QQQ 50%' (종목이 하나면 'VOO'). 들고만 있는 종목은 빼고 보여준다. */
export function basketLabel(all: SymbolWeight[] | null | undefined, fallback: string): string {
  const symbols = all && activeOf(all)
  if (!symbols || symbols.length <= 1) return symbols?.[0]?.symbol ?? fallback
  return symbols.map((s) => `${s.symbol} ${s.weight}%`).join(' · ')
}

/** 봇 이름 제안: 나 카피 봇은 '도플갱어 봇', 그 밖은 'QQQ 봇' (겹치면 '도플갱어 봇 2') */
export function suggestName(symbols: string[], strategy: string, taken: string[]) {
  const base = strategy === 'dip_saver' ? '도플갱어 봇' : `${symbols[0] ?? ''} 봇`
  let name = base
  for (let i = 2; taken.includes(name); i++) name = `${base} ${i}`
  return name
}
