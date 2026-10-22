import { useSyncExternalStore } from 'react'
import type { SymbolWeight } from './api'

/** 홈과 봇 화면이 같이 쓰는 "지금 보고 있는 봇". 이 브라우저에만 기억한다. */
const KEY = 'trading-lab:bot'
const listeners = new Set<() => void>()

function read(): number | null {
  try {
    return Number(localStorage.getItem(KEY)) || null
  } catch {
    return null
  }
}

/** 봇 화면 주소 #bot/3 (봇 설정 #bot/3/settings, 매매일지 #journal/3) → 3. 주소가 봇을 가리키면 그 봇을 고른다 (뒤로 가기·링크). */
function fromHash(): number | null {
  const m = /^#(?:bot|journal)\/(\d+)(?:\/settings)?$/.exec(location.hash)
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

/** 봇 하나의 설정으로 이동 (#bot/3/settings). 앱 전체 설정(계좌·알림)은 설정 탭에 있다. */
export function openBotSettings(id: number) {
  selectBot(id)
  location.hash = `bot/${id}/settings`
}

/** 봇의 매매일지로 이동 (#journal/3). */
export function openJournal(id: number) {
  selectBot(id)
  location.hash = `journal/${id}`
}

/** 처음부터 다시 시작·봇 삭제 확인창에 붙이는 말: 그 전 매매일지는 보관한다 (서버 journal_archives). */
export const JOURNAL_KEPT = {
  reset: '지금까지의 매매일지는 보관해 두어 매매일지 화면에서 다시 볼 수 있어요.',
  delete: '매매일지는 보관해 두어 매매일지 화면의 "지운 봇의 일지"에서 볼 수 있어요.',
}

/** 보관한 매매일지 (처음부터 다시 시작하기 전·지운 봇) 한 권 (#journal/archive/7). */
export function openArchive(id: number) {
  location.hash = `journal/archive/${id}`
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

/** "새 봇 만들기" 화면(#new) 요청. 시험해 보기 결과에서 오면 종목·전략이 미리 채워진다. */
export type NewBotSeed = { symbol?: string; symbols?: SymbolWeight[]; strategy?: string; params?: Record<string, number>; cash?: string }
let seed: NewBotSeed | null = null
const seedListeners = new Set<() => void>()

export function startNewBot(next: NewBotSeed = {}) {
  seed = next
  seedListeners.forEach((l) => l())
  location.hash = 'new'
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

/** 나 카피하기를 첫 질문부터 연다 (홈 시작 화면이 이미 소개했다). 나 카피하기 화면이 한 번 읽는다. */
export let meSkipIntro = false

export function startMeQuestions() {
  meSkipIntro = true
  location.hash = 'me'
}

export function clearMeSkipIntro() {
  meSkipIntro = false
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
