import { useEffect } from 'react'

let holders = 0

/** Freezes page scroll (`html.locked`) while an overlay is open; overlays may stack. */
export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return
    holders++
    document.documentElement.classList.add('locked')
    return () => {
      if (--holders === 0) document.documentElement.classList.remove('locked')
    }
  }, [active])
}
