/**
 * RecordingPlayer — HLS VOD player.
 *
 * Architecture:
 *   • Receives a ready .m3u8 URL — no VOD stream creation, no polling.
 *   • Seeks via video.currentTime = (seekToMs - windowStartMs) / 1000.
 *     No new HTTP requests; hls.js downloads only the needed MP4 chunk.
 *   • <video> is always mounted so HLS can buffer ahead.
 *   • Skeleton shown until the first 'playing' event fires.
 *   • Buffer stalls detected via native events + Hls.ErrorDetails.BUFFER_STALLED_ERROR.
 *   • MANIFEST_LOADED (fires before MANIFEST_PARSED) triggers autoplay sooner.
 */
import {
  useCallback, useEffect, useRef, useState,
} from 'react'
import Hls from 'hls.js'
import {
  Play, Pause, SkipBack, SkipForward, AlertCircle, RefreshCw,
} from 'lucide-react'
import { clsx } from 'clsx'

// ── Props ─────────────────────────────────────────────────────────────────────
export interface RecordingPlayerProps {
  /** URL da playlist .m3u8 — passada pelo pai; sem criação de stream aqui. */
  hlsUrl: string
  /**
   * Epoch ms do início da janela. Usado para calcular o offset de seek:
   *   video.currentTime = (seekToMs - windowStartMs) / 1000
   */
  windowStartMs: number
  /**
   * Quando muda, o player busca para esse instante dentro da janela atual.
   * Ignorado se o instante estiver fora da janela.
   */
  seekToMs?: number
  className?: string
  onReady?: () => void
  onError?: (error: string) => void
  /** Reporta a posição atual como epoch ms (útil para sincronizar a timeline). */
  onTimeUpdate?: (currentMs: number) => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtTime(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

// ── Component ─────────────────────────────────────────────────────────────────
export function RecordingPlayer({
  hlsUrl,
  windowStartMs,
  seekToMs,
  className,
  onReady,
  onError,
  onTimeUpdate,
}: RecordingPlayerProps) {
  const videoRef     = useRef<HTMLVideoElement>(null)
  const hlsRef       = useRef<Hls | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [hasPlayed, setHasPlayed] = useState(false)
  const [playing,   setPlaying  ] = useState(false)
  const [buffering, setBuffering] = useState(false)
  const [error,     setError    ] = useState<string | null>(null)
  const [curSec,    setCurSec   ] = useState(0)
  const [durSec,    setDurSec   ] = useState(0)

  // Keep latest callbacks in refs to avoid stale closures in event handlers
  const onReadyRef      = useRef(onReady)
  const onErrorRef      = useRef(onError)
  const onTimeUpdateRef = useRef(onTimeUpdate)
  useEffect(() => { onReadyRef.current = onReady },       [onReady])
  useEffect(() => { onErrorRef.current = onError },       [onError])
  useEffect(() => { onTimeUpdateRef.current = onTimeUpdate }, [onTimeUpdate])

  // ── HLS init / teardown ───────────────────────────────────────────────────
  useEffect(() => {
    if (!hlsUrl) return

    const video = videoRef.current
    if (!video) return

    // Reset state on new URL
    setHasPlayed(false)
    setPlaying(false)
    setBuffering(false)
    setError(null)
    setCurSec(0)
    setDurSec(0)

    // Tear down previous instance
    if (hlsRef.current) {
      hlsRef.current.destroy()
      hlsRef.current = null
    }

    if (Hls.isSupported()) {
      const hls = new Hls({
        lowLatencyMode:       false,
        maxBufferLength:       30,
        maxMaxBufferLength:    60,
        startLevel:            -1,
        capLevelToPlayerSize:  true,
        maxBufferSize:         60 * 1024 * 1024,
        // Enables MP4 segment demuxing (segments are MP4, not TS)
        progressive:           true,
      })

      hlsRef.current = hls
      hls.loadSource(hlsUrl)
      hls.attachMedia(video)

      // MANIFEST_LOADED fires before level details are fully parsed — fastest trigger
      hls.on(Hls.Events.MANIFEST_LOADED, () => {
        video.play().catch(() => {
          // Autoplay blocked; user will press play manually
        })
      })

      hls.on(Hls.Events.ERROR, (_, data) => {
        // Buffer stall — show spinner, hls.js will self-recover
        if (data.details === Hls.ErrorDetails.BUFFER_STALLED_ERROR) {
          setBuffering(true)
          return
        }
        if (data.fatal) {
          const msg = `Erro HLS: ${data.details}`
          setError(msg)
          onErrorRef.current?.(msg)
        }
      })
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari native HLS
      video.src = hlsUrl
      video.addEventListener('loadedmetadata', () => {
        video.play().catch(() => {})
      }, { once: true })
    } else {
      const msg = 'Seu navegador não suporta HLS'
      setError(msg)
      onErrorRef.current?.(msg)
    }

    return () => {
      hlsRef.current?.destroy()
      hlsRef.current = null
    }
  }, [hlsUrl]) // only re-run when URL changes

  // ── Native video events ────────────────────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const onPlaying = () => {
      setPlaying(true)
      setBuffering(false)
      if (!hasPlayed) {
        setHasPlayed(true)
        onReadyRef.current?.()
      }
    }
    const onPause          = () => setPlaying(false)
    const onWaiting        = () => setBuffering(true)
    const onStalled        = () => setBuffering(true)
    const onCanPlay        = () => setBuffering(false)
    const onCanPlayThrough = () => setBuffering(false)
    const onLoadedMeta     = () => setDurSec(video.duration)

    const onTimeUpdate = () => {
      setCurSec(video.currentTime)
      onTimeUpdateRef.current?.(windowStartMs + video.currentTime * 1000)
    }

    video.addEventListener('playing',         onPlaying)
    video.addEventListener('pause',           onPause)
    video.addEventListener('waiting',         onWaiting)
    video.addEventListener('stalled',         onStalled)
    video.addEventListener('canplay',         onCanPlay)
    video.addEventListener('canplaythrough',  onCanPlayThrough)
    video.addEventListener('loadedmetadata',  onLoadedMeta)
    video.addEventListener('timeupdate',      onTimeUpdate)

    return () => {
      video.removeEventListener('playing',         onPlaying)
      video.removeEventListener('pause',           onPause)
      video.removeEventListener('waiting',         onWaiting)
      video.removeEventListener('stalled',         onStalled)
      video.removeEventListener('canplay',         onCanPlay)
      video.removeEventListener('canplaythrough',  onCanPlayThrough)
      video.removeEventListener('loadedmetadata',  onLoadedMeta)
      video.removeEventListener('timeupdate',      onTimeUpdate)
    }
  // hasPlayed intentionally NOT in deps — we want it only for first-play logic
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowStartMs])

  // ── Seek when seekToMs changes ────────────────────────────────────────────
  // This is the core improvement: seek = offset calc, zero new HTTP requests.
  useEffect(() => {
    if (seekToMs === undefined) return
    const video = videoRef.current
    if (!video) return

    const offset = (seekToMs - windowStartMs) / 1000
    if (offset < 0 || (durSec > 0 && offset > durSec)) return  // out of window

    video.currentTime = offset
    if (video.paused) {
      video.play().catch(() => {})
    }
  }, [seekToMs, windowStartMs, durSec])

  // ── Controls ──────────────────────────────────────────────────────────────
  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    v.paused ? v.play().catch(() => {}) : v.pause()
  }, [])

  const seekBy = useCallback((delta: number) => {
    const v = videoRef.current
    if (!v || !durSec) return
    v.currentTime = Math.max(0, Math.min(durSec, v.currentTime + delta))
  }, [durSec])

  // ── Derived ──────────────────────────────────────────────────────────────
  const showSkeleton  = !hasPlayed && !error
  const showError     = !!error
  const showBuffering = hasPlayed && buffering

  const progress = durSec > 0 ? (curSec / durSec) * 100 : 0

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      className={clsx('relative overflow-hidden group', className)}
      style={{ background: '#0a0a0a', borderRadius: 8 }}
    >
      {/* ── Video — always in DOM ─────────────────────────────────────────
          Keeping it mounted lets hls.js start buffering immediately;
          opacity: 0 hides the flicker before the first frame.           */}
      <video
        ref={videoRef}
        className="w-full h-full object-contain"
        playsInline
        style={{
          display:    'block',
          opacity:    hasPlayed ? 1 : 0,
          transition: 'opacity 0.2s ease',
        }}
      />

      {/* ── Skeleton — visible before first play ──────────────────────── */}
      {showSkeleton && (
        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-3"
          style={{ background: '#0a0a0a' }}
        >
          <div style={spinnerStyle} />
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.28)', letterSpacing: '0.03em' }}>
            Carregando…
          </p>
        </div>
      )}

      {/* ── Error state ───────────────────────────────────────────────── */}
      {showError && (
        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-3"
          style={{ background: '#0a0a0a' }}
        >
          <AlertCircle size={26} style={{ color: 'rgba(239,68,68,0.60)' }} />
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)', maxWidth: '72%', textAlign: 'center' }}>
            {error}
          </p>
          <button
            onClick={() => {
              setError(null)
              // Re-trigger HLS init by temporarily clearing URL via key trick
              // Parent will unmount/remount or update hlsUrl to retry
            }}
            style={retryBtnStyle}
          >
            <RefreshCw size={11} />
            Tentar novamente
          </button>
        </div>
      )}

      {/* ── Buffer stall spinner ──────────────────────────────────────── */}
      {showBuffering && (
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
          style={{ background: 'rgba(0,0,0,0.35)' }}
        >
          <div style={spinnerStyle} />
        </div>
      )}

      {/* ── Playback controls — appear on hover once video started ──── */}
      {hasPlayed && (
        <div
          className="absolute bottom-0 left-0 right-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200"
          style={{
            padding:    '28px 14px 10px',
            background: 'linear-gradient(to top, rgba(0,0,0,0.82), transparent)',
          }}
        >
          {/* Seek bar */}
          <div
            className="w-full mb-2.5 relative cursor-pointer"
            style={{ height: 3 }}
            onClick={(e) => {
              const v = videoRef.current
              if (!v || !durSec) return
              const rect = e.currentTarget.getBoundingClientRect()
              const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
              v.currentTime = frac * durSec
            }}
          >
            {/* Track */}
            <div
              className="absolute inset-0 rounded-full"
              style={{ background: 'rgba(255,255,255,0.18)' }}
            />
            {/* Filled */}
            <div
              className="absolute left-0 top-0 bottom-0 rounded-full"
              style={{ width: `${progress}%`, background: '#3b82f6' }}
            />
            {/* Thumb */}
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full bg-white"
              style={{ left: `${progress}%`, boxShadow: '0 0 4px rgba(0,0,0,0.6)' }}
            />
          </div>

          {/* Buttons + time */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button onClick={() => seekBy(-10)} style={ctrlBtn} title="−10s">
              <SkipBack size={14} />
            </button>
            <button onClick={togglePlay} style={{ ...ctrlBtn, width: 26, height: 26 }}>
              {playing ? <Pause size={15} /> : <Play size={15} />}
            </button>
            <button onClick={() => seekBy(10)} style={ctrlBtn} title="+10s">
              <SkipForward size={14} />
            </button>

            <span style={{ marginLeft: 4, fontSize: 11, fontFamily: 'monospace', color: 'rgba(255,255,255,0.60)' }}>
              {fmtTime(curSec)} / {fmtTime(durSec)}
            </span>
          </div>
        </div>
      )}

      {/* Inline keyframes — avoids a separate CSS file */}
      <style>{`
        @keyframes _nvr_spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}

// ── Style constants ────────────────────────────────────────────────────────────
const spinnerStyle: React.CSSProperties = {
  width:       28,
  height:      28,
  borderRadius: '50%',
  border:      '2px solid rgba(255,255,255,0.08)',
  borderTopColor: 'rgba(59,130,246,0.70)',
  animation:   '_nvr_spin 0.9s linear infinite',
  flexShrink:  0,
}

const ctrlBtn: React.CSSProperties = {
  display:        'flex',
  alignItems:     'center',
  justifyContent: 'center',
  width:           22,
  height:          22,
  background:     'transparent',
  border:         'none',
  color:          'rgba(255,255,255,0.78)',
  cursor:         'pointer',
  padding:         0,
  borderRadius:    4,
  flexShrink:      0,
}

const retryBtnStyle: React.CSSProperties = {
  display:     'flex',
  alignItems:  'center',
  gap:          6,
  padding:     '5px 14px',
  background:  'rgba(59,130,246,0.14)',
  border:      '1px solid rgba(59,130,246,0.32)',
  borderRadius: 6,
  color:       '#60a5fa',
  fontSize:    11,
  cursor:      'pointer',
}
