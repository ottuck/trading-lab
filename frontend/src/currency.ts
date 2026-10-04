import { useQuery } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'
import { api } from './api'

/** 금액 표시 통화 (W1). 계산·주문은 늘 달러이고, 원화는 오늘 환율로 바꿔 보기만 한다.
    고른 값은 이 브라우저에만 저장한다. 환율을 아직 못 받았으면 달러로 보여준다. */
export type Currency = 'USD' | 'KRW'

const KEY = 'quant-lab:currency'
const listeners = new Set<() => void>()

function readPref(): Currency {
  try {
    return localStorage.getItem(KEY) === 'KRW' ? 'KRW' : 'USD'
  } catch {
    return 'USD'
  }
}

let pref = readPref()
let fx: { rate: number; source: string } | null = null

function emit() {
  listeners.forEach((l) => l())
}

export function setCurrency(next: Currency) {
  pref = next
  try {
    localStorage.setItem(KEY, next)
  } catch {
    // 저장이 막힌 브라우저에서는 이번 방문 동안만 적용한다.
  }
  emit()
}

/** 서버가 준 원/달러 매매기준율. App이 받아 넣는다. */
export function setFx(next: { rate: number; source: string } | null) {
  if (next?.rate === fx?.rate && next?.source === fx?.source) return
  fx = next
  emit()
}

/** 지금 원화로 보여주는 중이면 환율, 아니면 null. format.ts가 금액을 바꿀 때 쓴다. */
export function krwRate(): number | null {
  return pref === 'KRW' && fx ? fx.rate : null
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** [고른 통화, 환율, 출처]. 바뀌면 다시 그려야 하는 곳(App, 차트)에서 쓴다. */
export function useCurrency(): { currency: Currency; rate: number | null; source: string | null } {
  const snap = useSyncExternalStore(subscribe, () => `${pref}|${fx?.rate ?? ''}|${fx?.source ?? ''}`)
  const [c, r, s] = snap.split('|')
  return { currency: c as Currency, rate: r ? Number(r) : null, source: s || null }
}

/** 서버의 원/달러를 받아 금액 표시에 넣는다 (W1). 환율은 한 시간마다 바뀌므로 10분마다 다시 묻는다. */
export function useFxSync() {
  const { data } = useQuery({ queryKey: ['fx'], queryFn: api.fx, refetchInterval: 10 * 60_000 })
  useEffect(() => {
    setFx(data ? { rate: Number(data.rate), source: data.source } : null)
  }, [data])
}
