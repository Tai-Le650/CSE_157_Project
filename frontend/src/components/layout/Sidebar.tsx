import { NavLink } from 'react-router'
import { Activity, BrainCircuit, Cable, CircleDot, Database, Hand, Keyboard, LayoutDashboard, Mic, Radar, Settings } from 'lucide-react'
import { useAppState } from '@/hooks/useAppState'
import { cn } from '@/lib/utils'

export const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/sensors', label: 'Sensor Connections', icon: Cable },
  { to: '/live', label: 'Live Sensor Data', icon: Activity },
  { to: '/recorder', label: 'Gesture Recorder', icon: CircleDot },
  { to: '/datasets', label: 'Dataset Manager', icon: Database },
  { to: '/training', label: 'Model Training', icon: BrainCircuit },
  { to: '/recognition', label: 'Live Recognition', icon: Radar },
  { to: '/mappings', label: 'Command Mapping', icon: Keyboard },
  { to: '/sound', label: 'Sound Activation', icon: Mic },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const { status, connection } = useAppState()
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:flex">
      <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
        <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
          <Hand className="size-5" />
        </div>
        <div className="leading-tight">
          <div className="font-semibold tracking-tight">Gesture-to-PC</div>
          <div className="text-xs text-muted-foreground">CSE 157 · UC Merced</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="space-y-1 border-t border-sidebar-border px-5 py-4 text-xs text-muted-foreground">
        <div className="flex items-center justify-between">
          <span>Backend</span>
          <span className={cn('font-medium', connection === 'open' ? 'text-success' : 'text-warning-foreground dark:text-warning')}>{connection === 'open' ? 'connected' : connection}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Mode</span>
          <span className="font-medium">{status?.workspace === 'demo' ? 'Demo' : 'Real hardware'}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Version</span>
          <span className="font-medium">{status?.version ?? '—'}</span>
        </div>
      </div>
    </aside>
  )
}
