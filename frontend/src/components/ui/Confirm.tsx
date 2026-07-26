import { Modal } from './Modal'
import { Spinner } from './Spinner'

interface ConfirmProps {
  open: boolean
  message: string
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
}

export function Confirm({ open, message, onConfirm, onCancel, loading }: ConfirmProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title="Confirmar"
      size="sm"
      footer={
        <>
          <button className="btn btn-ghost" onClick={onCancel} disabled={loading}>
            Cancelar
          </button>
          <button className="btn btn-danger" onClick={onConfirm} disabled={loading}>
            {loading ? <Spinner size="sm" /> : 'Confirmar'}
          </button>
        </>
      }
    >
      <p className="text-sm text-t2">{message}</p>
    </Modal>
  )
}
