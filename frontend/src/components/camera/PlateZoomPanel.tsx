import { useEffect, useState } from 'react'

interface PlateZoomPanelProps {
  blobUrl: string
  /** [x1, y1, x2, y2] em pixels, relativo à resolução original da imagem. */
  bbox: [number, number, number, number]
  className?: string
}

const PANEL_W = 260
const PANEL_H = 160

/** Recorte ampliado da região da placa, sobreposto na imagem completa do evento.
 *  Usa a mesma blob URL já carregada (sem 2º fetch) e faz o "zoom" via
 *  crop CSS (img absoluta escalada dentro de um container overflow:hidden) —
 *  sem canvas, sem recodificar a imagem. */
export function PlateZoomPanel({ blobUrl, bbox, className }: PlateZoomPanelProps) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    setNatural(null)
    const img = new Image()
    img.onload = () => setNatural({ w: img.naturalWidth, h: img.naturalHeight })
    img.src = blobUrl
    return () => { img.onload = null }
  }, [blobUrl])

  if (!natural) return null

  const [x1, y1, x2, y2] = bbox
  const boxW = Math.max(1, x2 - x1)
  const boxH = Math.max(1, y2 - y1)

  // Margem ao redor da placa pra dar contexto (o pára-choque/carro em volta),
  // sem perder o zoom — proporcional ao tamanho da própria placa detectada.
  const padX = boxW * 0.5
  const padY = boxH * 1.5
  const cropX1 = Math.max(0, x1 - padX)
  const cropY1 = Math.max(0, y1 - padY)
  const cropX2 = Math.min(natural.w, x2 + padX)
  const cropY2 = Math.min(natural.h, y2 + padY)
  const cropW = Math.max(1, cropX2 - cropX1)
  const cropH = Math.max(1, cropY2 - cropY1)

  const scale = Math.min(PANEL_W / cropW, PANEL_H / cropH)

  return (
    <div
      className={className}
      style={{
        width: PANEL_W,
        height: PANEL_H,
        overflow: 'hidden',
        position: 'relative',
        background: '#000',
        borderRadius: 10,
        border: '1px solid rgba(255,255,255,0.15)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
      }}
    >
      <img
        src={blobUrl}
        alt="Zoom da placa"
        style={{
          position: 'absolute',
          left: -cropX1 * scale,
          top: -cropY1 * scale,
          width: natural.w * scale,
          height: natural.h * scale,
          maxWidth: 'none',
        }}
      />
    </div>
  )
}
