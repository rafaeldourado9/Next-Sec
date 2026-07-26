import { useState, useCallback, useRef } from 'react'

interface ConfirmState {
  open: boolean
  message: string
  resolve: ((value: boolean) => void) | null
}

export function useConfirm() {
  const [state, setState] = useState<ConfirmState>({
    open: false,
    message: '',
    resolve: null,
  })
  const resolveRef = useRef<((value: boolean) => void) | null>(null)

  const confirm = useCallback((message: string): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve
      setState({ open: true, message, resolve })
    })
  }, [])

  const onConfirm = useCallback(() => {
    resolveRef.current?.(true)
    setState({ open: false, message: '', resolve: null })
  }, [])

  const onCancel = useCallback(() => {
    resolveRef.current?.(false)
    setState({ open: false, message: '', resolve: null })
  }, [])

  return {
    confirm,
    confirmState: { open: state.open, message: state.message },
    onConfirm,
    onCancel,
  }
}
