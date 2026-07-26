import { useState, type ReactNode } from 'react'
import { clsx } from 'clsx'

type Placement = 'top' | 'bottom' | 'left' | 'right'

interface TooltipProps {
  children: ReactNode
  content: string
  placement?: Placement
}

const PLACEMENT_STYLES: Record<Placement, string> = {
  top:    'bottom-full left-1/2 -translate-x-1/2 mb-2',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
  left:   'right-full top-1/2 -translate-y-1/2 mr-2',
  right:  'left-full top-1/2 -translate-y-1/2 ml-2',
}

export function Tooltip({ children, content, placement = 'top' }: TooltipProps) {
  const [visible, setVisible] = useState(false)

  if (!content) return <>{children}</>

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      <span
        role="tooltip"
        className={clsx(
          'pointer-events-none absolute z-50 whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium text-white transition-all duration-150',
          PLACEMENT_STYLES[placement],
          visible ? 'opacity-100 scale-100' : 'opacity-0 scale-95',
        )}
        style={{ background: 'var(--elevated)', border: '1px solid var(--border)' }}
      >
        {content}
      </span>
    </span>
  )
}
