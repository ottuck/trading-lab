import type { Bot, BotConfig } from './api'

// 봇 설정 입력칸의 상태와 API 형식 사이 변환 (설정 화면·새 봇 만들기 공용)
export type Draft = {
  strategy: string
  params: Record<string, number>
  slippage: string
  maxPosition: string // 빈 값이면 제한 없음
}

export function toDraft(bot?: Pick<Bot, 'strategy' | 'params'> & Partial<Bot>): Draft {
  return {
    strategy: bot?.strategy ?? 'sma_cross',
    params: bot?.params ?? { fast: 50, slow: 200 },
    slippage: bot?.slippage_bps ? String(Number(bot.slippage_bps)) : '5',
    maxPosition: bot?.risk?.max_position_value ?? '',
  }
}

export function toConfig(d: Draft, bot?: Bot): BotConfig {
  return {
    strategy: d.strategy,
    params: d.params,
    commission_rate: bot?.commission_rate ?? '0.001', // 토스증권 요율 고정 (화면에서 바꾸지 않음)
    slippage_bps: d.slippage,
    max_position_value: d.maxPosition || null,
    max_order_value: bot?.risk?.max_order_value ?? null,
  }
}
