import { useEffect, useRef, useState } from 'react'
import { setThemePref, useTheme, type ThemePref } from '../theme'

/** 로고: 오른쪽 위로 오르는 선 마크 + Quant(굵게) Lab(가늘게, 그라데이션) 워드마크. */
export function Brand() {
  return (
    <a className="brand" href="#dashboard" aria-label="Quant Lab 홈">
      <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id="brand-g" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
            <stop style={{ stopColor: 'var(--brand-from)' }} />
            <stop offset="1" style={{ stopColor: 'var(--brand-to)' }} />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill="url(#brand-g)" />
        <path
          d="M8 21.5l5-5.2 4 3.4 6.6-8"
          fill="none"
          stroke="#fff"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="24" cy="11.4" r="2.5" fill="#fff" />
      </svg>
      <h1 className="wordmark">
        Quant<span className="lab">Lab</span>
      </h1>
    </a>
  )
}

const ICONS = {
  light: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  ),
  dark: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z" />
    </svg>
  ),
  system: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  ),
}

const OPTIONS: { pref: ThemePref; label: string }[] = [
  { pref: 'system', label: '시스템 설정 따르기' },
  { pref: 'light', label: '밝게' },
  { pref: 'dark', label: '어둡게' },
]

/** 헤더의 화면 밝기 메뉴. 아이콘은 지금 적용된 테마를 보여준다. */
export function ThemeMenu() {
  const { pref, theme } = useTheme()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => ref.current?.contains(e.target as Node) || setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  return (
    <div className="theme-menu" ref={ref}>
      <button className="icon-btn" aria-label="화면 밝기" title="화면 밝기" onClick={() => setOpen(!open)}>
        {ICONS[theme]}
      </button>
      {open && (
        <div className="menu" role="menu">
          {OPTIONS.map((o) => (
            <button
              key={o.pref}
              role="menuitemradio"
              aria-checked={o.pref === pref}
              className={o.pref === pref ? 'active' : ''}
              onClick={() => {
                setThemePref(o.pref)
                setOpen(false)
              }}
            >
              {ICONS[o.pref]}
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
