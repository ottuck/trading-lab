// 전략 이름 표시와 파라미터 문자열 변환 (백테스트·봇 설정 화면 공용)

export const STRATEGY_LABEL: Record<string, string> = {
  sma_cross: '골든크로스',
  trend_filter: 'Faber 200일선',
  rsi2: 'Connors RSI(2)',
  donchian: '터틀 돌파',
}

export function paramsText(p: Record<string, number>): string {
  return Object.entries(p)
    .map(([k, v]) => `${k}=${v}`)
    .join(',')
}

export function parseParams(text: string): Record<string, number> {
  return Object.fromEntries(
    text
      .split(',')
      .map((s) => s.split('=').map((x) => x.trim()))
      .filter(([k, v]) => k && v)
      .map(([k, v]) => [k, Number(v)]),
  )
}
