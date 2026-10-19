import { Search, X } from 'lucide-react'

import SegmentedTabs, { type Segment } from './SegmentedTabs'

/**
 * Search and a filter over a list the page has already loaded. The count on
 * each filter is how many match it before searching, so a lecturer can see
 * at a glance how many are live or still processing.
 */
export default function ListToolbar<K extends string>({
  label,
  query,
  onQuery,
  placeholder,
  filter,
  onFilter,
  filters,
}: {
  label: string
  query: string
  onQuery: (query: string) => void
  placeholder: string
  filter: K
  onFilter: (key: K) => void
  filters: { key: K; label: string; count: number }[]
}) {
  const segments: Segment<K>[] = filters.map(({ key, label: name, count }) => ({
    key,
    label: (
      <>
        {name}
        <span className="tabular-nums opacity-70">{count}</span>
      </>
    ),
  }))

  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <SegmentedTabs
        label={`Show ${label}`}
        segments={segments}
        value={filter}
        onChange={onFilter}
        dense
        className="max-w-full overflow-x-auto [scrollbar-width:none]"
      />
      <label className="relative w-full sm:w-72">
        <span className="sr-only">Search {label}</span>
        <Search
          size={16}
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
        <input
          type="search"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && query) {
              event.preventDefault()
              onQuery('')
            }
          }}
          placeholder={placeholder}
          className="w-full rounded-md border border-input bg-input-background py-2 pl-9 pr-9 text-sm placeholder:text-muted-foreground focus:border-ring focus:outline-none focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-search-cancel-button]:hidden"
        />
        {query && (
          <button
            type="button"
            onClick={() => onQuery('')}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X size={15} aria-hidden />
            <span className="sr-only">Clear search</span>
          </button>
        )}
      </label>
    </div>
  )
}
