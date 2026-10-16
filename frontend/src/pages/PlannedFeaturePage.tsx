import { lazy, Suspense } from 'react'

import { PageBody, PageHeader, Panel, Tag } from '../components/ui/primitives'
import type { PlannedFeature } from './plannedFeatures'

const DEMOS = {
  groups: lazy(() => import('../features/demos/BreakoutDemo')),
  engagement: lazy(() => import('../features/demos/EngagementDemo')),
  progress: lazy(() => import('../features/demos/ProgressDemo')),
  governance: lazy(() => import('../features/demos/GovernanceDemo')),
}

export default function PlannedFeaturePage({ feature }: { feature: PlannedFeature }) {
  const Demo = DEMOS[feature.demo]
  return (
    <>
      <PageHeader title={feature.title} description={feature.summary}>
        <div className="mt-3">
          <Tag>Planned</Tag>
        </div>
      </PageHeader>
      <PageBody>
        <Suspense fallback={<p role="status" className="text-muted-foreground">Loading the demo…</p>}>
          <Demo />
        </Suspense>
        <div className="mt-8 grid gap-6 md:grid-cols-2">
          <Panel title="When it is built">
            <List items={feature.will} />
          </Panel>
          <Panel title="What works today">
            <List items={feature.today} />
          </Panel>
        </div>
        <p className="mt-6 text-sm text-muted-foreground">Built by {feature.owner}.</p>
      </PageBody>
    </>
  )
}

function List({ items }: { items: readonly string[] }) {
  return (
    <ul className="space-y-2.5">
      {items.map((item) => (
        <li key={item} className="flex gap-3">
          <span aria-hidden className="mt-2.5 h-px w-3 shrink-0 bg-muted-foreground" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}
