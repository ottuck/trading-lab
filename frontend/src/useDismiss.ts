import { useEffect } from 'react'

/** 바깥을 누르거나 Esc를 누르면 닫히는 메뉴·서랍. ref가 없으면 Esc로만 닫는다. */
export function useDismiss(open: boolean, close: () => void, ref?: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    const onDown = (e: MouseEvent) => ref?.current && !ref.current.contains(e.target as Node) && close()
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open, close, ref])
}
