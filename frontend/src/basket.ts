// 여러 종목 봇의 종목·비율 도우미 (비율 합 100, 최대 10개).
import type { SymbolWeight } from './api'

export const MAX_SYMBOLS = 10

/** 비율을 똑같이 나눈다 (합 100, 나머지는 앞 종목부터 1%씩). */
export function evenSplit(symbols: string[]): SymbolWeight[] {
  const base = Math.floor(100 / symbols.length)
  return symbols.map((symbol, i) => ({ symbol, weight: base + (i < 100 - base * symbols.length ? 1 : 0) }))
}

/** 'VOO 50% · QQQ 50%' (종목이 하나면 'VOO') */
export function basketLabel(symbols: SymbolWeight[] | null | undefined, fallback: string): string {
  if (!symbols || symbols.length <= 1) return symbols?.[0]?.symbol ?? fallback
  return symbols.map((s) => `${s.symbol} ${s.weight}%`).join(' · ')
}
