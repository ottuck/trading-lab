import { useQuery } from '@tanstack/react-query'
import { backtestApi, type StrategyInfo } from './api'

// 전략 소개(별명·설명·프리셋)는 백엔드 카탈로그 하나에서 가져온다.
export function useStrategies() {
  const { data } = useQuery({ queryKey: ['strategies'], queryFn: backtestApi.strategies, staleTime: Infinity })
  const byName: Record<string, StrategyInfo> = Object.fromEntries((data ?? []).map((s) => [s.name, s]))
  return { list: data ?? [], byName }
}

export function strategyTitle(info: StrategyInfo | undefined, fallback: string) {
  return info ? `${info.emoji} ${info.nickname}` : fallback
}

/** 현재 파라미터가 어느 프리셋인지. 없으면 null(직접 설정). */
export function presetOf(info: StrategyInfo | undefined, params: Record<string, number>) {
  return info?.presets.find((p) => JSON.stringify(p.params) === JSON.stringify(params)) ?? null
}

export const SLIPPAGE_CHOICES = [
  { bps: '10', label: '보수적으로', hint: '0.1% 불리하게' },
  { bps: '5', label: '보통 (추천)', hint: '0.05% 불리하게' },
  { bps: '0', label: '이상적으로', hint: '본 가격 그대로' },
]
