import { PageBody, PageHeader, Panel, Tag } from '../components/ui/primitives'
import type { PlannedFeature } from './plannedFeatures'

export default function PlannedFeaturePage({ feature }: { feature: PlannedFeature }) {
  return (
    <>
      <PageHeader title={feature.title} description={feature.summary}>
        <div className="mt-3">
          <Tag>Planned</Tag>
        </div>
      </PageHeader>
      <PageBody>
        <div className="grid gap-6 md:grid-cols-2">
          <Panel title="What this will do">
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
