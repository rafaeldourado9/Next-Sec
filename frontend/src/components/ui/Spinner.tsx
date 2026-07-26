import { clsx } from 'clsx'

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZES = { sm: 'w-4 h-4', md: 'w-6 h-6', lg: 'w-10 h-10' }

export function Spinner({ size = 'md', className }: SpinnerProps) {
  return (
    <div
      className={clsx('animate-spin rounded-full border-2 border-t-transparent', SIZES[size], className)}
      style={{ borderColor: 'var(--accent)', borderTopColor: 'transparent' }}
    />
  )
}

export function PageSpinner() {
  return (
    <div className="flex-1 flex items-center justify-center py-16">
      <Spinner size="lg" />
    </div>
  )
}
