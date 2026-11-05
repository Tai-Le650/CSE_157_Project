import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type ThemeSetting = 'light' | 'dark' | 'system'
type Resolved = 'light' | 'dark'

interface ThemeContextValue {
  theme: ThemeSetting
  resolvedTheme: Resolved
  setLocalTheme: (theme: ThemeSetting) => void
}

const STORAGE_KEY = 'gesture-to-pc.theme'
const ThemeContext = createContext<ThemeContextValue | null>(null)

function readStored(): ThemeSetting {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    return 'light'
  }
  return 'light'
}

function prefersDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function ThemeProvider({ serverTheme, children }: { serverTheme?: ThemeSetting | null; children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeSetting>(() => serverTheme ?? readStored())
  const [systemDark, setSystemDark] = useState<boolean>(prefersDark)

  useEffect(() => {
    if (serverTheme) setTheme(serverTheme)
  }, [serverTheme])

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    query.addEventListener('change', listener)
    return () => query.removeEventListener('change', listener)
  }, [])

  const resolvedTheme: Resolved = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme
  if (typeof document !== 'undefined') document.documentElement.classList.toggle('dark', resolvedTheme === 'dark')

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      return
    }
  }, [resolvedTheme, theme])

  const value = useMemo(() => ({ theme, resolvedTheme, setLocalTheme: setTheme }), [theme, resolvedTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext) ?? { theme: 'light', resolvedTheme: 'light', setLocalTheme: () => undefined }
}
