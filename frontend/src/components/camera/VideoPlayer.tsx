import { useCallback, useEffect, useRef, useState } from 'react'
import Hls from 'hls.js'
import { Maximize2, Volume2, VolumeX, Play, Pause, Loader2, WifiOff } from 'lucide-react'
import { clsx } from 'clsx'

interface VideoPlayerProps {
  src?: string
  name?: string
  autoPlay?: boolean
  muted?: boolean
  className?: string
  offline?: boolean
  onError?: () => void
  // Otimizações de banda para mosaico
  bandwidthConfig?: {
    maxBufferLength: number
    maxMaxBufferLength: number
    startLevel: number
    capLevelToPlayerSize: boolean
  }
}

export function VideoPlayer({
  src, name, autoPlay = true, muted: initialMuted = true, className, offline = false, onError, bandwidthConfig,
}: VideoPlayerProps) {
  const videoRef      = useRef<HTMLVideoElement>(null)
  const hlsRef        = useRef<Hls | null>(null)
  const containerRef  = useRef<HTMLDivElement>(null)
  const isMountedRef  = useRef(false)
  const playAbortRef  = useRef<AbortController | null>(null)

  const [playing, setPlaying]         = useState(false)
  const [muted, setMuted]             = useState(initialMuted)
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState(false)
  const [showControls, setShowControls] = useState(false)

  // Wrapper seguro para play com verificação de mount
  const safePlay = useCallback(async (video: HTMLVideoElement) => {
    // Cancelar play anterior se existir
    if (playAbortRef.current) {
      playAbortRef.current.abort()
    }
    
    const controller = new AbortController()
    playAbortRef.current = controller
    
    try {
      await video.play()
      if (!controller.signal.aborted) {
        setPlaying(true)
        setLoading(false)
      }
    } catch (err) {
      if (!controller.signal.aborted && isMountedRef.current) {
        // AbortError é esperado durante cleanup - ignorar
        if ((err as Error).name !== 'AbortError') {
          setError(true)
          onError?.()
        }
      }
    } finally {
      if (playAbortRef.current === controller) {
        playAbortRef.current = null
      }
    }
  }, [onError])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      // Cancelar qualquer play pendente
      if (playAbortRef.current) {
        playAbortRef.current.abort()
      }
    }
  }, [])

  useEffect(() => {
    const video = videoRef.current
    // Se não há src ou está offline (fora do viewport), não carrega
    if (!video || !src || offline) {
      setLoading(false)
      if (!src || offline) {
        setError(true)
        // Limpa source anterior se estiver offline
        if (hlsRef.current) {
          hlsRef.current.destroy()
          hlsRef.current = null
        }
        if (video && video.src) {
          video.removeAttribute('src')
          video.load()
        }
      }
      return
    }

    setLoading(true)
    setError(false)

    // Cleanup do HLS anterior
    if (hlsRef.current) {
      hlsRef.current.destroy()
      hlsRef.current = null
    }

    if (Hls.isSupported() && src.includes('.m3u8')) {
      const hls = new Hls({
        lowLatencyMode: !bandwidthConfig, // Desabilita para mosaicos densos
        maxBufferLength: bandwidthConfig?.maxBufferLength ?? 10,
        maxMaxBufferLength: bandwidthConfig?.maxMaxBufferLength ?? 30,
        startLevel: bandwidthConfig?.startLevel ?? -1,
        capLevelToPlayerSize: bandwidthConfig?.capLevelToPlayerSize ?? true,
        // Otimizações para múltiplos streams
        maxBufferSize: bandwidthConfig ? 1024 * 1024 : 60 * 1024 * 1024, // 1MB vs 60MB
        liveDurationInfinity: true,
        testBandwidth: !bandwidthConfig, // Testa banda apenas para 1x1
      })
      hlsRef.current = hls
      hls.loadSource(src)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        if (autoPlay && isMountedRef.current) {
          safePlay(video)
        } else if (!autoPlay) {
          // Se autoPlay está desabilitado, só marca como pronto
          setLoading(false)
        }
      })
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal && isMountedRef.current) { 
          setError(true)
          onError?.() 
        }
      })
    } else if (video.canPlayType('application/vnd.apple.mpegurl') || !src.includes('.m3u8')) {
      video.src = src
      video.load() // Recarregar source
      if (autoPlay && isMountedRef.current) {
        safePlay(video)
      }
    } else {
      setError(true)
      onError?.()
    }

    return () => {
      // Destruir HLS
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
      // Cancelar play pendente
      if (playAbortRef.current) {
        playAbortRef.current.abort()
      }
      // Limpar source apenas se ainda montado
      if (isMountedRef.current) {
        video.pause()
        video.removeAttribute('src')
        video.load()
      }
    }
  }, [src, autoPlay, onError, offline, safePlay])

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v || loading) return // Não permitir toggle durante loading
    
    // Cancelar qualquer play automático pendente
    if (playAbortRef.current) {
      playAbortRef.current.abort()
    }
    
    try {
      if (v.paused) {
        safePlay(v)
      } else {
        v.pause()
        setPlaying(false)
      }
    } catch {
      // Ignorar erros de pause/play
    }
  }, [loading, safePlay])

  const toggleMute = () => {
    const v = videoRef.current
    if (!v) return
    v.muted = !v.muted
    setMuted(v.muted)
  }

  const toggleFullscreen = () => {
    if (!containerRef.current) return
    document.fullscreenElement
      ? document.exitFullscreen()
      : containerRef.current.requestFullscreen()
  }

  return (
    <div
      ref={containerRef}
      className={clsx('relative bg-black rounded-lg overflow-hidden group select-none', className)}
      onMouseEnter={() => setShowControls(true)}
      onMouseLeave={() => setShowControls(false)}
    >
      <video
        ref={videoRef}
        className="w-full h-full object-cover"
        muted={muted}
        playsInline
        onPlaying={() => { setLoading(false); setPlaying(true) }}
        onPause={() => setPlaying(false)}
        onWaiting={() => setLoading(true)}
        onError={() => { setError(true); onError?.() }}
      />

      {loading && !error && src && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60">
          <Loader2 size={32} className="animate-spin text-white/70" />
        </div>
      )}

      {error && offline && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-2">
          <WifiOff size={28} className="text-zinc-500" />
          <p className="text-xs text-zinc-500">Câmera offline</p>
        </div>
      )}

      {error && !offline && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-2">
          <WifiOff size={28} className="text-zinc-500" />
          <p className="text-xs text-zinc-500">Sem sinal</p>
        </div>
      )}

      {!src && !error && !offline && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
          <WifiOff size={28} className="text-zinc-600" />
          <p className="text-xs text-zinc-600">Câmera não configurada</p>
        </div>
      )}

      {name && (
        <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm text-white text-xs px-2 py-0.5 rounded-md font-medium">
          {name}
        </div>
      )}

      <div className={clsx(
        'absolute bottom-0 left-0 right-0 flex items-center gap-2 px-3 py-2 bg-gradient-to-t from-black/80 to-transparent transition-opacity duration-150',
        showControls ? 'opacity-100' : 'opacity-0',
      )}>
        <button onClick={togglePlay} className="text-white hover:text-zinc-300 transition-colors">
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button onClick={toggleMute} className="text-white hover:text-zinc-300 transition-colors">
          {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>
        <div className="flex-1" />
        <button onClick={toggleFullscreen} className="text-white hover:text-zinc-300 transition-colors">
          <Maximize2 size={16} />
        </button>
      </div>
    </div>
  )
}
