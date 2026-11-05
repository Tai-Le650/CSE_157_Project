import { isRouteErrorResponse, useRouteError } from 'react-router'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Notice } from '@/components/common/Bits'

export function ErrorPage() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : String(error)
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-8">
      <h1 className="text-xl font-semibold">This page hit an error</h1>
      <Notice tone="danger" title={message}>
        Acquisition, recording and PC-control safety run in the backend and are not affected by this page error. Use the Emergency Stop in another tab if needed.
      </Notice>
      <div className="flex gap-2">
        <Button onClick={() => window.location.reload()}><RefreshCw /> Reload</Button>
        <Button variant="outline" onClick={() => window.location.assign('/')}>Go to the dashboard</Button>
      </div>
    </div>
  )
}
