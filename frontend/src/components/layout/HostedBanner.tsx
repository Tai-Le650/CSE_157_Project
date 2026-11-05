import { useEffect } from 'react'
import { Globe } from 'lucide-react'
import { toast } from 'sonner'
import { useHosted } from '@/hooks/useSessionInfo'
import { onSessionReplaced } from '@/services/api'

function minutes(value: number): string {
  if (value % 60 === 0) return value === 60 ? '1 hour' : `${value / 60} hours`
  return `${value} minutes`
}

export function HostedBanner() {
  const { limits } = useHosted()

  useEffect(
    () =>
      onSessionReplaced(() => {
        toast.info('Your demo sandbox expired, so a fresh one was started. Reloading…')
        window.setTimeout(() => window.location.reload(), 1500)
      }),
    [],
  )

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-sky-400/30 bg-sky-500/10 px-6 py-2 text-sm text-sky-950 dark:text-sky-100" role="note" aria-label="Online demo">
      <Globe className="size-4 shrink-0" />
      <span>
        <b>Online demo</b> — sensors, gestures and every keyboard/mouse action are simulated. Your sandbox is private and resets after {minutes(limits?.idle_minutes ?? 10)} without an open tab ({minutes(limits?.max_age_minutes ?? 60)} at most).
      </span>
      {limits?.project_url ? (
        <a className="font-medium underline underline-offset-2" href={limits.project_url} target="_blank" rel="noreferrer">
          Use a real XIAO board: run it on your own PC
        </a>
      ) : (
        <span className="text-muted-foreground">To use a real XIAO board, run Gesture-to-PC on your own PC.</span>
      )}
    </div>
  )
}
