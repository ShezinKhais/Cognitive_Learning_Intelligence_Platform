/** Made-up names and numbers for the demos. Deterministic, so a demo looks
 * the same on every visit and in screenshots. */

export const SAMPLE_STUDENTS = [
  'Amira K.', 'Ben T.', 'Chen L.', 'Dana R.', 'Elif S.', 'Farah M.', 'Gabriel O.', 'Hana Y.',
  'Isaac P.', 'Jia W.', 'Karim A.', 'Lena V.', 'Mateo G.', 'Noor H.', 'Omar F.', 'Priya N.',
  'Quinn D.', 'Rania B.', 'Sami E.', 'Tara C.', 'Umar J.', 'Vera I.', 'Wen Z.', 'Yusuf Q.',
] as const

/** A small seeded random number source (mulberry32). */
export function seeded(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Students split into groups of about `size`, shuffled by `seed`. The last
 * group is never left with one person: they join the group before. */
export function formGroups<T>(people: readonly T[], size: number, seed: number): T[][] {
  const random = seeded(seed)
  const shuffled = [...people]
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1))
    ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  const groups: T[][] = []
  for (let i = 0; i < shuffled.length; i += size) groups.push(shuffled.slice(i, i + size))
  if (groups.length > 1 && groups[groups.length - 1].length === 1) {
    groups[groups.length - 2].push(...groups.pop()!)
  }
  return groups
}

export const SAMPLE_TERM = [
  { week: 1, title: 'Introduction', engaged: 82, right: 71 },
  { week: 2, title: 'Threat models', engaged: 78, right: 64 },
  { week: 3, title: 'Authentication', engaged: 80, right: 69 },
  { week: 4, title: 'Access control', engaged: 71, right: 52 },
  { week: 5, title: 'Cryptography I', engaged: 66, right: 47 },
  { week: 6, title: 'Cryptography II', engaged: 70, right: 58 },
  { week: 7, title: 'Secure sessions', engaged: 76, right: 66 },
  { week: 8, title: 'Web attacks', engaged: 84, right: 73 },
  { week: 9, title: 'Privacy by design', engaged: 79, right: 70 },
  { week: 10, title: 'Incident response', engaged: 81, right: 75 },
] as const
