/** A draft split of a class into breakout rooms, before it is sent. */
export type Draft = Record<string, string | null>

export function roomLabels(count: number): string[] {
  return Array.from({ length: count }, (_, index) => `Room ${index + 1}`)
}

/** Deal the students into count rooms, as evenly as possible, in a random
 * order so the same friends do not always end up together. */
export function splitEvenly(userIds: readonly string[], count: number, random: () => number = Math.random): Draft {
  const order = [...userIds]
  for (let index = order.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(random() * (index + 1))
    ;[order[index], order[swap]] = [order[swap], order[index]]
  }
  const labels = roomLabels(Math.max(1, count))
  return Object.fromEntries(order.map((id, index) => [id, labels[index % labels.length]]))
}

/** The draft as the PUT body: every room that has someone in it, in label order. */
export function planBody(draft: Draft): { rooms: { label: string; user_ids: string[] }[] } {
  const rooms = new Map<string, string[]>()
  for (const [userId, label] of Object.entries(draft)) {
    if (label) rooms.set(label, [...(rooms.get(label) ?? []), userId])
  }
  return {
    rooms: [...rooms.entries()]
      .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
      .map(([label, user_ids]) => ({ label, user_ids })),
  }
}
