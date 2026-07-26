import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { clsx } from 'clsx'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: React.ReactNode
  children: React.ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full'
  footer?: React.ReactNode
  disableBackdropClose?: boolean
}

const SIZES = {
  sm:   'max-w-sm',
  md:   'max-w-md',
  lg:   'max-w-lg',
  xl:   'max-w-2xl',
  full: 'max-w-5xl',
}

export function Modal({ open, onClose, title, children, size = 'md', footer, disableBackdropClose }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    if (open) document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)' }}
      onClick={(e) => { if (!disableBackdropClose && e.target === overlayRef.current) onClose() }}
    >
      <div
        className={clsx('w-full card flex flex-col max-h-[90vh] animate-slide-in', SIZES[size])}
        style={{ background: 'var(--surface)' }}
      >
        {title && (
          <div
            className="flex items-center justify-between px-5 py-4 border-b shrink-0"
            style={{ borderColor: 'var(--border)' }}
          >
            <h2 className="text-sm font-semibold text-t1">{title}</h2>
            <button onClick={onClose} className="btn btn-ghost w-7 h-7 p-0 rounded-md">
              <X size={16} />
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer && (
          <div
            className="flex items-center justify-end gap-2 px-5 py-4 border-t shrink-0"
            style={{ borderColor: 'var(--border)' }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
