import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { camerasService } from '@/services/cameras'
import { VideoPlayer } from './VideoPlayer'
import { RecordingTimeline } from './RecordingTimeline'
import type { VmsEvent } from '@/types'

interface RecordingPlayerProps {
  cameraId: string
  cameraName?: string
  events?: VmsEvent[]
}

const WINDOW_HOURS = 24
// Cada seek pede um trecho de N minutos a partir do ponto clicado — pedir o
// dia inteiro de uma vez sobrecarregaria o MediaMTX à toa; a maior parte do
// tempo o usuário só quer ver alguns minutos a partir de onde clicou.
const SEGMENT_MINUTES = 30

/** Junta o scrubber de cobertura (RecordingTimeline) com o player em modo
 *  VOD — clicar na timeline pede uma nova playback-url assinada pro trecho
 *  e troca o src do player (mesmo padrão de troca de src já usado pro live). */
export function RecordingPlayer({ cameraId, cameraName, events }: RecordingPlayerProps) {
  const [windowEnd] = useState(() => new Date())
  const [windowStart] = useState(() => new Date(Date.now() - WINDOW_HOURS * 3600_000))
  const [selected, setSelected] = useState<Date | null>(null)
  const [playbackUrl, setPlaybackUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  const seekTo = useCallback(async (t: Date) => {
    setSelected(t)
    setLoading(true)
    setError(false)
    try {
      const end = new Date(Math.min(t.getTime() + SEGMENT_MINUTES * 60_000, Date.now()))
      const res = await camerasService.recordingsPlaybackUrl(cameraId, t.toISOString(), end.toISOString())
      setPlaybackUrl(res.playback_url)
    } catch {
      setError(true)
      setPlaybackUrl(null)
    } finally {
      setLoading(false)
    }
  }, [cameraId])

  // Seleciona automaticamente o início da janela visível na primeira carga.
  useEffect(() => {
    seekTo(windowStart)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-3">
      <div className="relative bg-black rounded-lg overflow-hidden" style={{ aspectRatio: '16/9' }}>
        {playbackUrl && !error ? (
          <VideoPlayer
            src={playbackUrl}
            name={cameraName}
            mode="vod"
            autoPlay
            muted
            className="w-full h-full"
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-t3">
            {loading ? (
              <Loader2 size={24} className="animate-spin" />
            ) : (
              <span className="text-xs">
                {error ? 'Sem gravação disponível nesse trecho' : 'Selecione um horário na timeline'}
              </span>
            )}
          </div>
        )}
      </div>

      <RecordingTimeline
        cameraId={cameraId}
        windowStart={windowStart}
        windowEnd={windowEnd}
        events={events}
        selected={selected}
        onSeek={seekTo}
      />
    </div>
  )
}
