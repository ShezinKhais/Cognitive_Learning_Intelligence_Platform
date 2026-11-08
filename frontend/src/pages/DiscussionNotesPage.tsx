import { useParams } from 'react-router'
import { PageBody, PageHeader } from '../components/ui/primitives'
import DiscussionPanel from '../features/discussion/DiscussionPanel'

export default function DiscussionNotesPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  return <>
    <PageHeader title="Session discussion minutes" description="Publish and correct the teaching points students can catch up on during and after class." />
    <PageBody>{sessionId && <DiscussionPanel key={sessionId} sessionId={sessionId} publisher />}</PageBody>
  </>
}
