import { useCallback, useEffect } from 'react'
import { OctagonX, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useAppState } from '@/hooks/useAppState'
import { api, errorMessage } from '@/services/api'
import { wsClient } from '@/services/ws'

export function useEmergencyStop() {
  return useCallback(async () => {
    const viaSocket = wsClient.emergencyStop()
    try {
      await api.control.emergencyStop('ui_button')
      toast.error('Emergency Stop: PC control disarmed and pending actions cleared')
    } catch (err) {
      if (!viaSocket) toast.error(`Emergency Stop could not reach the backend: ${errorMessage(err)}`)
    }
  }, [])
}

export function EmergencyStopButton() {
  const { control } = useAppState()
  const stop = useEmergencyStop()

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && event.shiftKey) {
        event.preventDefault()
        void stop()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stop])

  if (control?.estop_latched) {
    return (
      <div className="flex items-center gap-2">
        <span className="hidden rounded-md bg-destructive/10 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-destructive md:inline">E-stop latched</span>
        <Button size="sm" variant="outline" onClick={() => void api.control.reset().then(() => toast.success('Emergency Stop reset. PC control stays disarmed until you arm it again.'))}>
          <RotateCcw /> Reset
        </Button>
      </div>
    )
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button size="sm" className="bg-destructive font-semibold text-white shadow-sm hover:bg-destructive/90" onClick={() => void stop()} aria-label="Emergency Stop">
          <OctagonX /> Emergency Stop
        </Button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">
        Disarms PC control instantly and clears pending actions. In this tab: Shift+Esc. While armed, the system-wide hotkey {control?.global_hotkey.spec ?? 'ctrl+alt+backspace'} also works.
      </TooltipContent>
    </Tooltip>
  )
}
