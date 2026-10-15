import { useQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { liveApi, type Bot, type LiveOrder } from './api'
import { useDemo } from './demo'

/* 실제로 따라 사기 (실거래 R2) 조회와 표시 문구. 데모에는 실거래가 없어 묻지 않는다. */

export function useLive() {
  const demo = useDemo()
  return useQuery({ queryKey: ['live'], queryFn: liveApi.get, refetchInterval: 30_000, enabled: !demo })
}

/** 봇을 지우거나 다시 시작해도 실제 계좌의 주식은 그대로다. 실제로 산 기록이 있는 봇에만 알린다. */
export function realKeepNote(bot: Bot, action: 'reset' | 'delete'): string {
  if (bot.live_ratio == null && !bot.has_real_fills) return ''
  if (action === 'delete') {
    const live = bot.live_ratio != null ? ' 실제로 따라 하기도 함께 끝나요.' : ''
    return `\n\n이 봇이 이미 실제 계좌에서 산 주식은 지워도 그대로 남아요 (자동으로 팔리지 않아요). 팔려면 증권사 앱에서 직접 팔아야 해요.${live}`
  }
  // 다시 시작하면 첫 판단의 매수도 새 모의 주문이라, 따라 하는 중이면 실제로도 새로 산다
  const again =
    bot.live_ratio != null ? '\n실제로 따라 하는 중이라, 다시 시작한 뒤 첫 판단의 매수도 실제 계좌에서 새로 사요 (시작 금액의 1/100 안팎).' : ''
  return `\n\n이 봇이 이미 실제 계좌에서 산 주식은 그대로 남아요.${again}`
}

const STATE: Record<LiveOrder['state'], string> = {
  WAITING_APPROVAL: '승인 기다림',
  APPROVED: '장이 열리면 사요',
  SENDING: '보내는 중',
  SENT: '체결 기다림',
  FILLED: '샀어요',
  CANCELED: '취소됐어요',
  REJECTED: '거절됐어요',
  SKIPPED: '넘겼어요',
  UNKNOWN: '확인 필요',
}

const REASON: Record<string, string> = {
  declined: '이번엔 안 사기로 함',
  halted: '멈춰 둔 동안',
  missed: '주문 시간을 놓침',
  no_session: '장이 열리지 않음',
  leveraged: 'QLD·TQQQ 말고는 레버리지 안 함',
  too_small: '금액이 너무 작음',
  carried: '$1이 넘으면 함께 사요',
  no_funds: '달러가 모자라 넘김',
  account_limit: '이번 달 계좌 전체 한도를 넘음',
  confirmed_not_placed: '증권사 내역을 확인해 미접수로 정리함',
  nothing_held: '실제로 산 주식이 없음',
  outside_hours: '주문 시간이 아님',
  insufficient_funds: '계좌에 돈이 부족함',
  prerequisite: '증권사 앱에서 사전 확인 필요',
  restricted: '주문 제한',
  other: '증권사가 받지 않음',
}

const tradeDay = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', weekday: 'short', timeZone: 'UTC' })

/** "10월 2일 (금)" — 미국 거래일. 한국 시간으로는 그날 밤에 산다. */
export function dayLabel(iso: string) {
  return tradeDay.format(new Date(`${iso}T00:00:00Z`))
}

export function liveStatus(o: LiveOrder) {
  const reason = o.reason ? REASON[o.reason] ?? o.reason : ''
  const state = o.reason === 'carried' ? (o.carried_into ? '다음 주문에 더함' : '작아서 모아 둠') : STATE[o.state]
  return [state, o.carried_into ? '' : reason].filter(Boolean).join(' · ')
}

// 홈 잔액 카드의 "금액 가리기". 이 브라우저에만 기억한다.
const HIDE_KEY = 'trading-lab:hide-balance'
const hideListeners = new Set<() => void>()
let hidden = (() => {
  try {
    return localStorage.getItem(HIDE_KEY) === '1'
  } catch {
    return false
  }
})()

export function toggleBalanceHidden() {
  hidden = !hidden
  try {
    localStorage.setItem(HIDE_KEY, hidden ? '1' : '0')
  } catch {
    // 저장이 막힌 브라우저에서는 이번 방문 동안만 적용한다.
  }
  hideListeners.forEach((l) => l())
}

export function useBalanceHidden(): boolean {
  return useSyncExternalStore(
    (l) => {
      hideListeners.add(l)
      return () => hideListeners.delete(l)
    },
    () => hidden,
  )
}
