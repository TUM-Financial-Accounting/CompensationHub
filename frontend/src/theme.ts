import { useEffect, useState } from 'react'

export type Theme = 'system' | 'light' | 'dark'

const systemDark = matchMedia('(prefers-color-scheme: dark)')

function stored(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch {
    return 'system'
  }
}

/** The chosen colour theme, kept on `<html data-theme>` (index.html sets it before the first paint)
 *  and in the Safari bar colour; 'system' follows the device setting live. */
export function useTheme() {
  const [theme, setTheme] = useState(stored)

  useEffect(() => {
    const apply = () => {
      const root = document.documentElement
      root.dataset.theme = theme === 'system' ? (systemDark.matches ? 'dark' : 'light') : theme
      const bg = getComputedStyle(root).getPropertyValue('--bg').trim()
      document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute('content', bg))
    }
    apply()
    try {
      if (theme === 'system') localStorage.removeItem('theme')
      else localStorage.setItem('theme', theme)
    } catch {
      // private mode or blocked storage: the choice lasts for this visit
    }
    systemDark.addEventListener('change', apply)
    return () => systemDark.removeEventListener('change', apply)
  }, [theme])

  return [theme, setTheme] as const
}
