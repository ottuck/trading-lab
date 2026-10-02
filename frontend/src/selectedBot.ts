import { useSyncExternalStore } from 'react'

/** 홈과 설정이 같이 쓰는 "지금 보고 있는 봇". 이 브라우저에만 기억한다. */
const KEY = 'quant-lab:bot'
const listeners = new Set<() => void>()

function read(): number | null {
  try {
    return Number(localStorage.getItem(KEY)) || null
  } catch {
    return null
  }
}

let selected = read()

export function selectBot(id: number) {
  selected = id
  try {
    localStorage.setItem(KEY, String(id))
  } catch {
    // 저장이 막힌 브라우저에서는 이번 방문 동안만 기억한다.
  }
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** 고른 봇. 없거나 지워졌으면 첫 번째 봇. */
export function useSelectedBot<T extends { id: number }>(bots: T[]): T {
  const id = useSyncExternalStore(subscribe, () => selected)
  return bots.find((b) => b.id === id) ?? bots[0]
}
