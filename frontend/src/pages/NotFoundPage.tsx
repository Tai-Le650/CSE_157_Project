import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { Empty } from '@/components/common/Bits'

export function NotFoundPage() {
  return (
    <Empty
      title="Page not found"
      description="That address is not part of Gesture-to-PC."
      action={
        <Button asChild>
          <Link to="/">Back to the dashboard</Link>
        </Button>
      }
    />
  )
}
