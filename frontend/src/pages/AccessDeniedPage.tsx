import { motion } from 'motion/react'
import { Lock } from 'lucide-react'
import { useNavigate } from 'react-router'

import { clearAccessToken } from '../api'
import { Wordmark } from '../components/brand/ClipMark'
import { buttonStyles } from '../components/ui/button'

export default function AccessDeniedPage() {
  const navigate = useNavigate()

  function signInWithAnotherAccount(): void {
    clearAccessToken()
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
        <span className="grid h-11 w-11 place-items-center rounded-full bg-accent text-accent-foreground">
          <Lock size={20} aria-hidden />
        </span>
        <h1 className="mt-5 text-[1.75rem] font-bold leading-tight">This page is for another role</h1>
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
