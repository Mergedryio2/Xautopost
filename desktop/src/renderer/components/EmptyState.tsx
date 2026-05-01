import type { ReactNode } from 'react'
import { Mascot, type MascotMood } from './Mascot'

export function EmptyState({
  mood = 'sleep',
  title,
  description,
  action,
  size = 'normal',
}: {
  mood?: MascotMood
  title: string
  description?: ReactNode
  action?: ReactNode
  size?: 'normal' | 'small' | 'large'
}) {
  const mascotSize = size === 'large' ? 120 : size === 'small' ? 64 : 96
  return (
    <div className={`empty-state empty-${size}`}>
      <Mascot mood={mood} size={mascotSize} />
      <p className="empty-title">{title}</p>
      {description && <p className="empty-desc">{description}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  )
}
