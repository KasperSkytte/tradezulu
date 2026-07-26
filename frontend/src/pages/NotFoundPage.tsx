import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { Card, EmptyState } from '../components/ui'

export function NotFoundPage() {
  return (
    <Card>
      <EmptyState
        icon={<Compass size={38} strokeWidth={1.4} />}
        title="Nothing here"
        description="That page does not exist."
        action={
          <Link to="/" className="tz-btn tz-btn-primary">
            Back to the dashboard
          </Link>
        }
      />
    </Card>
  )
}
