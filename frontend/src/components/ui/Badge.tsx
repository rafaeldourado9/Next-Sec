import { clsx } from 'clsx'

type Variant = 'default' | 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps {
  variant?: Variant
  children: React.ReactNode
  className?: string
  dot?: boolean
}

const STYLES: Record<Variant, string> = {
  default: 'bg-elevated text-t2',
  success: 'text-green-400',
  warning: 'text-yellow-400',
  danger:  'text-red-400',
  info:    'text-blue-400',
}

const BG: Record<Variant, string> = {
  default: '',
  success: 'bg-green-500/10',
  warning: 'bg-yellow-500/10',
  danger:  'bg-red-500/10',
  info:    'bg-blue-500/10',
}

export function Badge({ variant = 'default', children, className, dot }: BadgeProps) {
  return (
    <span className={clsx('badge', STYLES[variant], BG[variant], className)}>
      {dot && (
        <span className={clsx('w-1.5 h-1.5 rounded-full', {
          'bg-green-500':  variant === 'success',
          'bg-yellow-500': variant === 'warning',
          'bg-red-500':    variant === 'danger',
          'bg-blue-500':   variant === 'info',
          'bg-zinc-500':   variant === 'default',
        })} />
      )}
      {children}
    </span>
  )
}
