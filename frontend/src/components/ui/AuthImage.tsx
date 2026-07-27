import { Camera } from 'lucide-react'
import { useAuthImage } from '@/hooks/useAuthImage'

export function AuthImage({ src, alt, className, style, onClick }: {
  src: string
  alt?: string
  className?: string
  style?: React.CSSProperties
  onClick?: (e: React.MouseEvent) => void
}) {
  const { blobUrl, error } = useAuthImage(src)

  if (error || !blobUrl) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-1 ${className ?? ''}`}
        style={style}
      >
        <Camera size={16} style={{ color: 'rgba(255,255,255,0.12)' }} />
        <span className="text-[8px] text-t3/40">Sem imagem</span>
      </div>
    )
  }

  return (
    <img src={blobUrl} alt={alt} className={className} style={style} onClick={onClick} />
  )
}
