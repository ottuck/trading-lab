import { useSyncExternalStore } from 'react'
import type { SymbolWeight } from './api'

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

/** 봇 화면 주소 #bot/3 → 3. 주소가 봇을 가리키면 그 봇을 고른다 (뒤로 가기·링크). */
function fromHash(): number | null {
  const m = /^#bot\/(\d+)$/.exec(location.hash)
  return m ? Number(m[1]) : null
}

let selected = fromHash() ?? read()

export function selectBot(id: number) {
  selected = id
  try {
    localStorage.setItem(KEY, String(id))
  } catch {
    // 저장이 막힌 브라우저에서는 이번 방문 동안만 기억한다.
  }
  listeners.forEach((l) => l())
}

window.addEventListener('hashchange', () => {
  const id = fromHash()
  if (id && id !== selected) selectBot(id)
})

/** 봇 하나 자세히 보기로 이동 (#bot/3). */
export function openBot(id: number) {
  selectBot(id)
  location.hash = `bot/${id}`
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** 고른 봇. 없거나 지워졌으면 나 카피 봇(나처럼 투자), 그것도 없으면 첫 번째 봇. */
export function useSelectedBot<T extends { id: number; strategy: string }>(bots: T[]): T {
  const id = useSyncExternalStore(subscribe, () => selected)
  return bots.find((b) => b.id === id) ?? bots.find((b) => b.strategy === 'dip_saver') ?? bots[0]
}

/** "새 봇 만들기" 요청. 시험해 보기 결과에서 오면 종목·전략이 미리 채워진다. */
export type NewBotSeed = { symbol?: string; symbols?: SymbolWeight[]; strategy?: string; params?: Record<string, number> }
let seed: NewBotSeed | null = null
const seedListeners = new Set<() => void>()

export function startNewBot(next: NewBotSeed = {}) {
  seed = next
  seedListeners.forEach((l) => l())
  location.hash = 'settings'
}

export function closeNewBot() {
  seed = null
  seedListeners.forEach((l) => l())
}

export function useNewBotSeed(): NewBotSeed | null {
  return useSyncExternalStore(
    (l) => {
      seedListeners.add(l)
      return () => seedListeners.delete(l)
    },
    () => seed,
  )
}

/** 화면 이동 (#dashboard, #backtest, #settings, #me). 봇 화면은 openBot. */
export function goTo(page: string) {
  location.hash = page
}

/** 나 카피하기(#me)를 기존 나 카피 봇의 규칙 바꾸기로 연다. #me를 떠나면 풀린다. */
let meEdit: number | null = null
const meEditListeners = new Set<() => void>()

export function startMeEdit(botId: number) {
  meEdit = botId
  meEditListeners.forEach((l) => l())
  location.hash = 'me'
}

export function endMeEdit() {
  meEdit = null
  meEditListeners.forEach((l) => l())
}

export function useMeEdit(): number | null {
  return useSyncExternalStore(
    (l) => {
      meEditListeners.add(l)
      return () => meEditListeners.delete(l)
    },
    () => meEdit,
  )
}
