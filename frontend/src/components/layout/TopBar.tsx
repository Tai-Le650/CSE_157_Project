import { Link, NavLink } from 'react-router'
import { FlaskConical, Menu, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { StatusDot } from '@/components/common/StatusBadge'
import { useAppState } from '@/hooks/useAppState'
import { useTheme } from '@/hooks/useTheme'
import { api } from '@/services/api'
import { num } from '@/lib/format'
import { cn } from '@/lib/utils'
import { EmergencyStopButton } from './EmergencyStop'
import { NAV } from './Sidebar'

const MODE_LABELS: { key: 'monitoring' | 'recording' | 'recognition' | 'pc_control' | 'demo'; label: string; active: string }[] = [
  { key: 'monitoring', label: 'Monitoring', active: 'border-success/40 bg-success/10 text-success' },
  { key: 'recording', label: 'Recording', active: 'border-destructive/40 bg-destructive/10 text-destructive' },
  { key: 'recognition', label: 'Recognition', active: 'border-primary/40 bg-primary/10 text-primary' },
  { key: 'pc_control', label: 'PC Control', active: 'border-destructive/60 bg-destructive text-white' },
  { key: 'demo', label: 'Demo', active: 'border-violet-400/50 bg-violet-500/10 text-violet-700 dark:text-violet-300' },
]

export function ModeChips() {
  const { status } = useAppState()
  const modes = status?.modes
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Current modes">
      {MODE_LABELS.map(({ key, label, active }) => {
        const on = Boolean(modes?.[key])
        return (
          <span key={key} className={cn('rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors', on ? active : 'border-border text-muted-foreground/60')} aria-pressed={on}>
            {key === 'recording' && on ? '● ' : ''}
            {label}
          </span>
        )
      })}
    </div>
  )
}

function SensorPills() {
  const { sensors } = useAppState()
  if (!sensors.length) {
    return (
      <Link to="/sensors" className="text-xs text-muted-foreground hover:text-foreground">
        No sensors connected
      </Link>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {sensors.map((s) => (
        <Tooltip key={s.sensor_id}>
          <TooltipTrigger asChild>
            <Link to="/sensors" className="flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-0.5 text-xs hover:bg-muted">
              <StatusDot status={s.status} />
              <span className="font-medium">{s.sensor_id}</span>
              {s.hand !== 'unassigned' ? <span className="text-muted-foreground">{s.hand === 'left' ? 'L' : 'R'}</span> : null}
              <span className="tabular text-muted-foreground">{s.rates.device_hz ? `${num(s.rates.device_hz, 0)} Hz` : '—'}</span>
              {s.simulated ? <FlaskConical className="size-3 text-violet-500" /> : null}
            </Link>
          </TooltipTrigger>
          <TooltipContent>
            {s.sensor_id} on {s.port}: {s.status}. Rate measured from device timestamps{s.simulated ? ' (simulated sensor)' : ''}.
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  )
}

export function TopBar() {
  const { resolvedTheme, setLocalTheme } = useTheme()
  const { status } = useAppState()
  const toggleTheme = () => {
    const next = resolvedTheme === 'dark' ? 'light' : 'dark'
    setLocalTheme(next)
    void api.settings.patch({ theme: next }).catch(() => undefined)
  }
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/85 backdrop-blur">
      <div className="flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 lg:px-6">
        <div className="lg:hidden">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open navigation">
                <Menu />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {NAV.map(({ to, label, icon: Icon }) => (
                <DropdownMenuItem key={to} asChild>
                  <NavLink to={to} end={to === '/'}>
                    <Icon /> {label}
                  </NavLink>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <SensorPills />
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <span className="hidden text-xs text-muted-foreground xl:inline">Mode: <b className="text-foreground">{status?.primary_mode ?? '—'}</b></span>
          <ModeChips />
          <Button variant="ghost" size="icon-sm" onClick={toggleTheme} aria-label="Toggle dark mode">
            {resolvedTheme === 'dark' ? <Sun /> : <Moon />}
          </Button>
          <EmergencyStopButton />
        </div>
      </div>
    </header>
  )
}
