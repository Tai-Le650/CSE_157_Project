import { Outlet } from 'react-router'
import { FlaskConical, ShieldAlert, WifiOff } from 'lucide-react'
import { useAppState } from '@/hooks/useAppState'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

function Banners() {
  const { connection, status, control, loaded } = useAppState()
  return (
    <>
      {connection !== 'open' ? (
        <div className="flex items-center gap-2 border-b border-warning/40 bg-warning/15 px-6 py-2 text-sm">
          <WifiOff className="size-4" />
          {loaded ? 'Connection to the backend was lost — reconnecting. Live data and controls are paused.' : 'Connecting to the Gesture-to-PC backend at 127.0.0.1…'}
          <span className="text-muted-foreground">Start it with <code className="font-mono">.\.venv\Scripts\python.exe backend\run.py</code></span>
        </div>
      ) : null}
      {status?.workspace === 'demo' ? (
        <div className="flex items-center gap-2 border-b border-violet-400/30 bg-violet-500/10 px-6 py-2 text-sm text-violet-900 dark:text-violet-200">
          <FlaskConical className="size-4" />
          <b>Demo Mode</b> — sensors, signals and gestures are simulated, and every keyboard/mouse action is simulated. Nothing is sent to the operating system.
        </div>
      ) : null}
      {control?.armed && !control.simulated_actions ? (
        <div className="flex items-center gap-2 border-b border-destructive/50 bg-destructive px-6 py-2 text-sm font-medium text-white">
          <ShieldAlert className="size-4" />
          PC control is ARMED — recognised gestures press real keys and click the mouse in the focused window. Shift+Esc or {control.global_hotkey.spec} stops immediately.
        </div>
      ) : null}
    </>
  )
}

export function AppShell() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <Banners />
        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
