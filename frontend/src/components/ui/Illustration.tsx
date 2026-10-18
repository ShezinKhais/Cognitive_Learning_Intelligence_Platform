import { motion } from 'motion/react'

import accessDenied from '../../assets/illustrations/access-denied.svg?raw'
import addFiles from '../../assets/illustrations/add-files.svg?raw'
import fileMissing from '../../assets/illustrations/file-missing.svg?raw'
import lecture from '../../assets/illustrations/lecture.svg?raw'
import loadFailed from '../../assets/illustrations/load-failed.svg?raw'
import notFound from '../../assets/illustrations/not-found.svg?raw'
import notifications from '../../assets/illustrations/notifications.svg?raw'
import offline from '../../assets/illustrations/offline.svg?raw'
import pageCrash from '../../assets/illustrations/page-crash.svg?raw'
import reportWarning from '../../assets/illustrations/report-warning.svg?raw'
import serverDown from '../../assets/illustrations/server-down.svg?raw'
import serverError from '../../assets/illustrations/server-error.svg?raw'
import { cn } from './cn'

/*
 * Illustrations from unDraw (undraw.co, free licence), recoloured to the
 * theme tokens so they follow light, dark and high contrast. Inlined rather
 * than loaded as images, since an <img> cannot read CSS variables. The files
 * are ours and hold no scripts or links, so inlining them is safe.
 */
const ART = {
  'access-denied': accessDenied,
  'add-files': addFiles,
  'file-missing': fileMissing,
  lecture,
  'load-failed': loadFailed,
  'not-found': notFound,
  notifications,
  offline,
  'page-crash': pageCrash,
  'report-warning': reportWarning,
  'server-down': serverDown,
  'server-error': serverError,
} as const

export type IllustrationName = keyof typeof ART

/** A drawing that settles in as its page appears. Decorative: screen readers skip it. */
export default function Illustration({ name, className }: { name: IllustrationName; className?: string }) {
  return (
    <motion.div
      aria-hidden
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className={cn('[&>svg]:h-full [&>svg]:w-full', className)}
      dangerouslySetInnerHTML={{ __html: ART[name] }}
    />
  )
}
