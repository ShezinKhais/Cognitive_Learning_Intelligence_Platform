import { useEffect, useRef } from 'react'
import { Link } from 'react-router'

import { Wordmark } from '../components/brand/ClipMark'
import { buttonStyles } from '../components/ui/button'
import Illustration from '../components/ui/Illustration'
import { useDocumentTitle } from '../components/ui/useDocumentTitle'

export default function NotFoundPage() {
  const heading = useRef<HTMLHeadingElement>(null)
  useDocumentTitle('Page not found')

  useEffect(() => {
    heading.current?.focus()
  }, [])

  return (
    <main className="min-h-screen bg-background px-4 py-10 sm:py-16">
      <div className="mx-auto w-full max-w-lg">
        <div className="mb-10">
          <Wordmark />
        </div>

        <Illustration
          name="not-found"
          className="h-40 w-56 max-w-full"
        />

        <h1
          ref={heading}
          tabIndex={-1}
          className="mt-8 text-[1.75rem] font-bold leading-tight"
        >
          Page not found
        </h1>

        <p className="mt-2 text-muted-foreground">
          We couldn&apos;t find that page.
          The link may be incorrect or the page may have moved.
        </p>

        <div className="mt-6 flex flex-wrap gap-2">
          <Link to="/" className={buttonStyles()}>
            My home page
          </Link>

          <Link
            to="/login"
            className={buttonStyles({ intent: 'secondary' })}
          >
            Sign in
          </Link>
        </div>
      </div>
    </main>
  )
}
