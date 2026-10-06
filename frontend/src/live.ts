import { useQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { liveApi, type LiveOrder } from './api'
import { useDemo } from './demo'

/* 실제로 따라 사기 (실거래 R2) 조회와 표시 문구. 데모에는 실거래가 없어 묻지 않는다. */

export function useLive() {
  const demo = useDemo()
  return useQuery({ queryKey: ['live'], queryFn: liveApi.get, refetchInterval: 30_000, enabled: !demo })
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
const HIDE_KEY = 'quant-lab:hide-balance'
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
