import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Notice } from '@/components/common/Bits'
import { useAppState } from '@/hooks/useAppState'
import { api, ApiError, errorMessage } from '@/services/api'
import type { MappingProfile } from '@/types/api'

export function ArmDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { clientId, control, settings, recognition } = useAppState()
  const [profiles, setProfiles] = useState<MappingProfile[]>([])
  const [reasons, setReasons] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setReasons([])
    void api.mappings.profiles().then(setProfiles).catch(() => setProfiles([]))
  }, [open])

  const active = profiles.find((p) => p.profile_id === settings?.active_profile_id)
  const enabled = active?.mappings.filter((m) => m.enabled) ?? []
  const simulated = control?.simulated_actions ?? false

  const arm = async () => {
    if (!clientId) {
      setReasons(['This tab is not connected to the backend.'])
      return
    }
    setBusy(true)
    try {
      await api.control.arm(clientId)
      toast.warning(simulated ? 'PC control armed — actions are simulated (Demo Mode)' : 'PC control ARMED — real keyboard and mouse input enabled')
      onOpenChange(false)
    } catch (err) {
      setReasons(err instanceof ApiError && err.reasons.length ? err.reasons : [errorMessage(err)])
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ShieldAlert className="size-5 text-destructive" /> Arm PC control?</DialogTitle>
          <DialogDescription>
            {simulated
              ? 'Demo Mode: recognised gestures are logged as simulated actions. Nothing is sent to Windows.'
              : 'Recognised gestures will press keys, click and scroll in whichever window has focus. Keep this tab open: it sends the heartbeat that keeps control armed.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div>
            <div className="mb-1 font-medium">Active profile: {active?.name ?? 'none'}</div>
            {enabled.length ? (
              <ul className="space-y-1 rounded-lg border border-border/70 p-3">
                {enabled.map((m) => (
                  <li key={m.mapping_id} className="flex justify-between gap-3">
                    <span className="font-mono">{m.label_id}</span>
                    <span>{m.description}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">No enabled mappings — arming will be refused.</p>
            )}
          </div>
          <p className="text-muted-foreground">
            Recognition: {recognition?.running ? `${recognition.model?.name} on ${recognition.sensor_id}` : 'not running'} · Idle never triggers an action · Cooldown {settings?.inference.cooldown_s ?? '—'} s.
          </p>
          <p className="text-muted-foreground">Stop instantly with the red Emergency Stop button, Shift+Esc in this tab, or {control?.global_hotkey.spec} anywhere while armed. Moving the mouse into a screen corner also stops PyAutoGUI.</p>
          {reasons.length ? (
            <Notice tone="danger" title="Arming was refused">
              <ul className="mt-1 list-disc space-y-0.5 pl-4">{reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </Notice>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button className="bg-destructive text-white hover:bg-destructive/90" disabled={busy} onClick={() => void arm()}>
            {simulated ? 'Arm (simulated)' : 'Arm real PC control'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
