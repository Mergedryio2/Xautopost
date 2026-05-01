import { Modal } from './Modal'

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'ตกลง',
  cancelLabel = 'ยกเลิก',
  tone = 'default',
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal open={open} onClose={onCancel} title={title}>
      <div className="modal-form">
        <p className="confirm-message">{message}</p>
        <div className="form-actions">
          {cancelLabel && (
            <button type="button" className="btn-ghost" onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
          <button
            type="button"
            className={tone === 'danger' ? 'btn-primary btn-danger-solid' : 'btn-primary'}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
