import { useQuery } from '@tanstack/react-query'
import { backtestApi, type StrategyInfo } from './api'

// 전략 소개(별명·설명·프리셋)는 백엔드 카탈로그 하나에서 가져온다.
export function useStrategies() {
  const { data } = useQuery({ queryKey: ['strategies'], queryFn: backtestApi.strategies, staleTime: Infinity })
  const byName: Record<string, StrategyInfo> = Object.fromEntries((data ?? []).map((s) => [s.name, s]))
  // AI 봇은 시험해 보기(과거 백테스트)가 없고 따로 만든다: 전략 고르기 목록에서는 뺀다
  return { list: (data ?? []).filter((s) => !s.ai), byName }
}

export function strategyTitle(info: StrategyInfo | undefined, fallback: string) {
  return info ? info.nickname : fallback
}

/** 파라미터가 같은지. DB(JSONB)는 키 순서를 바꿔 저장하므로 문자열이 아니라 키별로 비교한다. */
export function sameParams(a: Record<string, number>, b: Record<string, number>) {
  return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => a[k] === b[k])
}

/** 프리셋을 고른다. 따로 고른 규칙(choices)은 그대로 둔다. */
export function applyPreset(info: StrategyInfo, params: Record<string, number>, preset: Record<string, number>) {
  const kept = Object.fromEntries(info.choices.filter((c) => c.key in params).map((c) => [c.key, params[c.key]]))
  return { ...preset, ...kept }
}

/** 현재 파라미터가 어느 프리셋인지 (따로 고른 규칙은 빼고 본다). 없으면 null(직접 설정). */
export function presetOf(info: StrategyInfo | undefined, params: Record<string, number>) {
  return info?.presets.find((p) => sameParams(applyPreset(info, params, p.params), params)) ?? null
}

export const SLIPPAGE_CHOICES = [
  { bps: '10', label: '보수적으로', hint: '0.1% 불리하게' },
  { bps: '5', label: '보통 (추천)', hint: '0.05% 불리하게' },
  { bps: '0', label: '이상적으로', hint: '본 가격 그대로' },
]

/** 나 카피 봇 (나처럼 투자). 있으면 홈 첫 화면이 "나 vs 매달 그냥 사기"와 평행세계의 나가 된다. */
export const isMeBot = (b: { strategy: string }) => b.strategy === 'dip_saver'

/** AI 봇 (마일스톤 4): 고른 종목 안에서 AI가 매일 비중을 정한다 (시장분석·캔들분석). */
export const isAiBot = (b: { strategy: string }) => b.strategy === 'ai_judge' || b.strategy === 'ai_candle'

/** 캔들분석 AI 봇: 뉴스 없이 종목 이름·날짜를 가린 가격 차트만 보고 판단한다. */
export const isCandleBot = (b: { strategy: string }) => b.strategy === 'ai_candle'

/** AI 봇 종류 (전략마다 하나씩 만들 수 있다). */
export const AI_KINDS = {
  ai_judge: { name: '시장분석 AI 봇', short: '시장분석', desc: '뉴스·금리를 조사해 비중을 정해요', cost: '$0.1' },
  ai_candle: { name: '캔들분석 AI 봇', short: '캔들분석', desc: '가격 차트만 보고 비중을 정해요', cost: '$0.07' },
} as const
export type AiKind = keyof typeof AI_KINDS
