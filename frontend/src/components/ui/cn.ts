import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Join class names, letting a later Tailwind class override an earlier one. */
export function cn(...values: ClassValue[]): string {
  return twMerge(clsx(values))
}
