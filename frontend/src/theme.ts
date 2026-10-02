import { useSyncExternalStore } from 'react'

/** 화면 테마. 기본은 시스템 설정을 따르고, 고른 값은 이 브라우저에만 저장한다. */
export type ThemePref = 'system' | 'light' | 'dark'
export type Theme = 'light' | 'dark'

const KEY = 'quant-lab:theme'
const media = window.matchMedia('(prefers-color-scheme: dark)')
const listeners = new Set<() => void>()

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

let pref = readPref()

function resolved(): Theme {
  return pref === 'system' ? (media.matches ? 'dark' : 'light') : pref
}

function apply() {
  const theme = resolved()
  document.documentElement.dataset.theme = theme
  // 모바일 브라우저 주소창 색도 배경에 맞춘다.
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0a0d14' : '#f2f4f6')
  listeners.forEach((l) => l())
}

media.addEventListener('change', () => pref === 'system' && apply())
apply()

export function setThemePref(next: ThemePref) {
  pref = next
  try {
    if (next === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, next)
  } catch {
    // 저장이 막힌 브라우저에서는 이번 방문 동안만 적용한다.
  }
  apply()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 현재 테마의 색 토큰 값. 차트처럼 CSS를 직접 못 쓰는 곳에서 쓴다. */
export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** [고른 값, 실제 적용된 테마]. 차트처럼 색을 직접 읽는 곳은 theme이 바뀌면 다시 그린다. */
export function useTheme(): { pref: ThemePref; theme: Theme } {
  const snap = useSyncExternalStore(subscribe, () => `${pref}:${resolved()}`)
  const [p, t] = snap.split(':') as [ThemePref, Theme]
  return { pref: p, theme: t }
}
