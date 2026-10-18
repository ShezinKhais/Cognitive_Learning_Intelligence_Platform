import { motion } from 'motion/react'
import { useNavigate } from 'react-router'

import { clearAccessToken } from '../api'
import { Wordmark } from '../components/brand/ClipMark'
import { buttonStyles } from '../components/ui/button'
import Illustration from '../components/ui/Illustration'

export default function AccessDeniedPage() {
  const navigate = useNavigate()

  async function signInWithAnotherAccount(): Promise<void> {
    // The cookie has to be gone first, or the sign-in page signs this
    // account straight back in.
    await clearAccessToken()
    navigate('/login', { replace: true })
  }

  return (
    <main className="min-h-screen bg-background px-4 py-10 sm:py-16">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="mx-auto w-full max-w-lg"
      >
        <div className="mb-10">
          <Wordmark />
        </div>
        <Illustration name="access-denied" className="h-40 w-56" />
        <h1 className="mt-8 text-[1.75rem] font-bold leading-tight">This page is for another role</h1>
        <p className="mt-2 text-muted-foreground">
          Each workspace opens only for the role it is for. Go back to your own home page, or sign in with an account
          that has access.
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <button type="button" onClick={() => navigate('/', { replace: true })} className={buttonStyles()}>
            My home page
          </button>
          <button type="button" onClick={signInWithAnotherAccount} className={buttonStyles({ intent: 'secondary' })}>
            Sign in with another account
          </button>
        </div>
      </motion.div>
    </main>
  )
}
