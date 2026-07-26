/**
 * TimelineCanvas — canvas-based interactive timeline.
 *
 * Diferenças em relação ao DayProgressTimeline (DOM):
 *   - Canvas rendering: mais performático, sem reflow/relayout
 *   - Zoom via scroll wheel (Ctrl+scroll ou pinch trackpad)
 *   - Pan via drag (arrasta a janela de visualização)
 *   - Auto-follow: mantém o playhead visível enquanto o vídeo roda
 *   - Clique em qualquer ponto → seek (distingue de drag por distância < 5px)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, Rewind, FastForward, StepBack, StepForward, LocateFixed } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DayInterval {
  id: string
  started_at: string
  ended_at: string
  duration_seconds: number
}

export interface TimelineCanvasProps {
  /** Limite esquerdo da janela de dados (epoch ms). */
  windowStartMs: number
  /** Limite direito da janela de dados (epoch ms). */
  windowEndMs: number
  /** Posição atual do playhead (epoch ms). */
  currentMs: number
  /** Chamado quando o usuário faz seek. */
  onSeek: (ms: number) => void
  playing: boolean
  onTogglePlay: () => void
  intervals: DayInterval[]
  events?: Array<{ id: string; occurredAtMs: number; label?: string }>
  /** Ativa modo de seleção de clip. Primeiro clique = início, segundo = fim. */
  clipMode?: boolean
  /** Chamado quando o usuário confirma um intervalo de clip. */
  onClipSelect?: (startMs: number, endMs: number) => void
  /** Chamado quando o usuário define o ponto de início (primeiro clique). */
  onClipAnchorSet?: () => void
  className?: string
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtClock(ms: number): string {
  const d = new Date(ms)
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((v) => String(v).padStart(2, '0'))
    .join(':')
}

function parseClock(txt: string, dayStartMs: number): number | null {
  const m = txt.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!m) return null
  const h = Number(m[1]), mi = Number(m[2]), se = Number(m[3] ?? '0')
  if (h > 23 || mi > 59 || se > 59) return null
  const base = new Date(dayStartMs)
  base.setHours(h, mi, se, 0)
  return base.getTime()
}

function getTickInterval(rangeMs: number): number {
  if (rangeMs > 12 * 3600_000) return 2 * 3600_000
  if (rangeMs > 2 * 3600_000)  return 3600_000
  if (rangeMs > 30 * 60_000)   return 30 * 60_000
  if (rangeMs > 10 * 60_000)   return 10 * 60_000
  if (rangeMs > 2 * 60_000)    return 60_000
  return 30_000
}

function timeToX(t: number, w: number, start: number, end: number): number {
  return ((t - start) / (end - start)) * w
}

function xToTime(x: number, w: number, start: number, end: number): number {
  return start + (x / w) * (end - start)
}

// ── Component ──────────────────────────────────────────────────────────────────

export function TimelineCanvas({
  windowStartMs,
  windowEndMs,
  currentMs,
  onSeek,
  playing,
  onTogglePlay,
  intervals,
  events = [],
  clipMode = false,
  onClipSelect,
  onClipAnchorSet,
  className,
}: TimelineCanvasProps) {
  const canvasRef    = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // ── View window (pode ser zoom/pan independente dos dados) ─────────────────
  const [view, setView] = useState({ start: windowStartMs, end: windowEndMs })

  // Reinicia a janela quando os dados mudam (troca de câmera/data)
  useEffect(() => {
    setView({ start: windowStartMs, end: windowEndMs })
    setAutoFollow(true)
  }, [windowStartMs, windowEndMs])

  // ── Auto-follow ────────────────────────────────────────────────────────────
  const [autoFollow, setAutoFollow] = useState(true)

  useEffect(() => {
    if (!autoFollow) return
    const range = view.end - view.start
    const margin = range * 0.15
    if (currentMs < view.start + margin || currentMs > view.end - margin) {
      setView({ start: currentMs - range / 2, end: currentMs + range / 2 })
    }
  // view changes would cause infinite loop — intentionally omit
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentMs, autoFollow])

  // ── Clip selection state ───────────────────────────────────────────────────
  const [clipAnchor, setClipAnchor] = useState<number | null>(null)
  const [clipHover,  setClipHover ] = useState<number | null>(null)

  // Reset clip state when mode is toggled off
  useEffect(() => {
    if (!clipMode) { setClipAnchor(null); setClipHover(null) }
  }, [clipMode])

  // ── Drag / pan state ───────────────────────────────────────────────────────
  const dragging      = useRef(false)
  const dragStartX    = useRef(0)
  const dragStartView = useRef({ start: 0, end: 0 })
  const [hoverMs, setHoverMs] = useState<number | null>(null)

  // ── Clock input ────────────────────────────────────────────────────────────
  const [inputValue, setInputValue] = useState('')
  const [editing, setEditing] = useState(false)

  const dayStartMs = useMemo(() => {
    const d = new Date(windowStartMs)
    d.setHours(0, 0, 0, 0)
    return d.getTime()
  }, [windowStartMs])

  useEffect(() => {
    if (!editing) setInputValue(fmtClock(currentMs))
  }, [currentMs, editing])

  const submitInput = () => {
    const parsed = parseClock(inputValue.trim(), dayStartMs)
    if (parsed !== null) {
      const clamped = Math.min(windowEndMs, Math.max(windowStartMs, parsed))
      onSeek(clamped)
    } else {
      setInputValue(fmtClock(currentMs))
    }
    setEditing(false)
  }

  // ── Step ───────────────────────────────────────────────────────────────────
  const step = useCallback((deltaMs: number) => {
    const next = Math.min(windowEndMs, Math.max(windowStartMs, currentMs + deltaMs))
    onSeek(next)
  }, [currentMs, windowStartMs, windowEndMs, onSeek])

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        step(e.shiftKey ? -30_000 : e.altKey ? -1_000 : -5_000)
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        step(e.shiftKey ? 30_000 : e.altKey ? 1_000 : 5_000)
      } else if (e.key === ' ') {
        e.preventDefault()
        onTogglePlay()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, onTogglePlay])

  // ── Canvas draw ────────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const dpr  = window.devicePixelRatio || 1
    const rect = container.getBoundingClientRect()
    if (rect.width === 0) return

    const W = rect.width
    const H = 64

    canvas.width  = W * dpr
    canvas.height = H * dpr
    canvas.style.width  = `${W}px`
    canvas.style.height = `${H}px`

    const ctx = canvas.getContext('2d', { willReadFrequently: false })
    if (!ctx) return

    ctx.save()
    ctx.scale(dpr, dpr)

    // Fundo
    ctx.fillStyle = 'rgba(255,255,255,0.03)'
    ctx.fillRect(0, 0, W, H)

    const trackH = 8
    const trackY = H / 2 - trackH / 2

    // Trilho base
    ctx.fillStyle = 'rgba(255,255,255,0.06)'
    ctx.beginPath()
    ctx.roundRect(0, trackY, W, trackH, 4)
    ctx.fill()

    // Ticks + labels
    const tickInterval = getTickInterval(view.end - view.start)
    const firstTick = Math.ceil(view.start / tickInterval) * tickInterval

    ctx.font = '500 9px ui-sans-serif, system-ui, sans-serif'
    ctx.textAlign = 'center'

    for (let t = firstTick; t < view.end; t += tickInterval) {
      const x = timeToX(t, W, view.start, view.end)
      if (x < 0 || x > W) continue

      ctx.fillStyle = 'rgba(255,255,255,0.12)'
      ctx.fillRect(x - 0.5, trackY - 5, 1, 5)

      const d = new Date(t)
      const label = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
      ctx.fillStyle = 'rgba(255,255,255,0.35)'
      ctx.fillText(label, x, trackY - 8)
    }

    // Segmentos gravados
    for (const iv of intervals) {
      const s = new Date(iv.started_at).getTime()
      const e = new Date(iv.ended_at).getTime()
      if (e < view.start || s > view.end) continue
      const x1 = Math.max(0, timeToX(s, W, view.start, view.end))
      const x2 = Math.min(W, timeToX(e, W, view.start, view.end))
      const w  = Math.max(2, x2 - x1)
      ctx.fillStyle = '#3b82f6'
      ctx.beginPath()
      ctx.roundRect(x1, trackY, w, trackH, 3)
      ctx.fill()
    }

    // Evento markers (losango)
    for (const ev of events) {
      const x = timeToX(ev.occurredAtMs, W, view.start, view.end)
      if (x < 0 || x > W) continue
      ctx.fillStyle = '#f59e0b'
      ctx.save()
      ctx.translate(x, trackY + trackH / 2)
      ctx.rotate(Math.PI / 4)
      ctx.fillRect(-4, -4, 8, 8)
      ctx.restore()
    }

    // Clip selection overlay (roxo)
    if (clipMode && clipAnchor !== null) {
      const refMs  = clipHover ?? currentMs
      const startX = Math.max(0, timeToX(Math.min(clipAnchor, refMs), W, view.start, view.end))
      const endX   = Math.min(W, timeToX(Math.max(clipAnchor, refMs), W, view.start, view.end))
      ctx.fillStyle = 'rgba(168,85,247,0.18)'
      ctx.fillRect(startX, 0, endX - startX, H)
      ctx.strokeStyle = '#a855f7'
      ctx.lineWidth = 1.5
      ctx.strokeRect(startX, 0, endX - startX, H)
      // handles
      ;[startX, endX].forEach((hx) => {
        ctx.fillStyle = '#a855f7'
        ctx.fillRect(hx - 1, 0, 2, H)
      })
    }

    // Hover indicator
    if (hoverMs !== null && !clipMode) {
      const hx = timeToX(hoverMs, W, view.start, view.end)
      ctx.fillStyle = 'rgba(255,255,255,0.15)'
      ctx.fillRect(hx - 0.5, trackY - 2, 1, trackH + 4)
    }

    // Playhead
    const px = timeToX(currentMs, W, view.start, view.end)
    if (px >= 0 && px <= W) {
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(px - 1, trackY - 4, 2, trackH + 8)

      ctx.fillStyle = '#60a5fa'
      ctx.beginPath()
      ctx.arc(px, trackY + trackH / 2, 6, 0, Math.PI * 2)
      ctx.fill()

      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 2
      ctx.stroke()
    }

    ctx.restore()
  }, [intervals, events, view, currentMs, hoverMs, clipMode, clipAnchor, clipHover])

  // ── Mouse events ───────────────────────────────────────────────────────────
  const getMouseMs = (clientX: number) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return 0
    return xToTime(clientX - rect.left, rect.width, view.start, view.end)
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    if (clipMode) return
    dragging.current  = true
    dragStartX.current = e.clientX
    dragStartView.current = { ...view }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    const ms = getMouseMs(e.clientX)
    setHoverMs(ms)
    if (clipMode) { setClipHover(ms); return }

    if (!dragging.current) return
    const dx = e.clientX - dragStartX.current
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    const range = dragStartView.current.end - dragStartView.current.start
    const deltaMs = -(dx / rect.width) * range
    setAutoFollow(false)
    setView({
      start: dragStartView.current.start + deltaMs,
      end:   dragStartView.current.end   + deltaMs,
    })
  }

  const handleMouseUp = (e: React.MouseEvent) => {
    if (clipMode) {
      const ms = Math.min(windowEndMs, Math.max(windowStartMs, getMouseMs(e.clientX)))
      if (clipAnchor === null) {
        setClipAnchor(ms)
        onClipAnchorSet?.()
      } else {
        const startMs = Math.min(clipAnchor, ms)
        const endMs   = Math.max(clipAnchor, ms)
        onClipSelect?.(startMs, endMs)
        setClipAnchor(null)
        setClipHover(null)
      }
      return
    }
    const didPan = Math.abs(e.clientX - dragStartX.current) > 5
    dragging.current = false
    if (!didPan) {
      const ms = getMouseMs(e.clientX)
      onSeek(Math.min(windowEndMs, Math.max(windowStartMs, ms)))
    }
  }

  const handleMouseLeave = () => {
    dragging.current = false
    setHoverMs(null)
    if (clipMode) setClipHover(null)
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return

    const range  = view.end - view.start
    const factor = e.deltaY > 0 ? 1.25 : 0.8
    const newRange = Math.min(24 * 3600_000, Math.max(60_000, range * factor))

    const mouseX  = e.clientX - rect.left
    const mouseMs = xToTime(mouseX, rect.width, view.start, view.end)
    const ratio   = mouseX / rect.width

    setAutoFollow(false)
    setView({
      start: mouseMs - newRange * ratio,
      end:   mouseMs + newRange * (1 - ratio),
    })
  }

  // ── Reset view ─────────────────────────────────────────────────────────────
  const resetView = () => {
    setView({ start: windowStartMs, end: windowEndMs })
    setAutoFollow(true)
  }

  // ── Hover tooltip (DOM overlay sobre o canvas) ─────────────────────────────
  const hoverPct = hoverMs !== null
    ? ((hoverMs - view.start) / (view.end - view.start)) * 100
    : null

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div
      className={className}
      style={{
        background: '#0d0d0f',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 10,
        padding: '14px 16px',
        color: 'rgba(255,255,255,0.9)',
        fontFamily: 'ui-sans-serif, system-ui, sans-serif',
        userSelect: 'none',
      }}
    >
      {/* Controls row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <button onClick={onTogglePlay} style={playBtnStyle} title={playing ? 'Pausar (Space)' : 'Reproduzir (Space)'}>
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <StepBtn onClick={() => step(-300_000)} title="−5 min">−5m</StepBtn>
          <StepBtn onClick={() => step(-60_000)}  title="−1 min">−1m</StepBtn>
          <StepBtn onClick={() => step(-5_000)}   title="−5 s (←)"><Rewind size={11} /></StepBtn>
          <StepBtn onClick={() => step(-1_000)}   title="−1 s (Alt+←)"><StepBack size={11} /></StepBtn>
          <StepBtn onClick={() => step(1_000)}    title="+1 s (Alt+→)"><StepForward size={11} /></StepBtn>
          <StepBtn onClick={() => step(5_000)}    title="+5 s (→)"><FastForward size={11} /></StepBtn>
          <StepBtn onClick={() => step(60_000)}   title="+1 min">+1m</StepBtn>
          <StepBtn onClick={() => step(300_000)}  title="+5 min">+5m</StepBtn>
        </div>

        <input
          value={inputValue}
          onFocus={() => setEditing(true)}
          onChange={(e) => setInputValue(e.target.value)}
          onBlur={submitInput}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur()
            if (e.key === 'Escape') {
              setInputValue(fmtClock(currentMs))
              setEditing(false)
              ;(e.currentTarget as HTMLInputElement).blur()
            }
          }}
          placeholder="HH:MM:SS"
          style={clockInputStyle}
        />

        <button
          onClick={resetView}
          title={autoFollow ? 'Auto-follow ativo' : 'Resetar view / ativar auto-follow'}
          style={{
            ...stepBtnStyle,
            color: autoFollow ? '#60a5fa' : 'rgba(255,255,255,0.5)',
            borderColor: autoFollow ? 'rgba(96,165,250,0.4)' : 'rgba(255,255,255,0.08)',
            background: autoFollow ? 'rgba(59,130,246,0.12)' : 'rgba(255,255,255,0.04)',
          }}
        >
          <LocateFixed size={11} />
        </button>

        <div style={{ marginLeft: 'auto', fontSize: 11, fontFamily: 'monospace', color: 'rgba(255,255,255,0.35)' }}>
          {fmtClock(view.start)} → {fmtClock(view.end)}
        </div>
      </div>

      {/* Canvas container */}
      <div
        ref={containerRef}
        style={{ position: 'relative', borderRadius: 6, overflow: 'hidden', cursor: clipMode ? (clipAnchor !== null ? 'col-resize' : 'crosshair') : 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onWheel={handleWheel}
      >
        <canvas ref={canvasRef} style={{ display: 'block' }} />

        {/* Hover tooltip */}
        {hoverPct !== null && hoverMs !== null && (
          <div
            style={{
              position: 'absolute',
              bottom: 'calc(100% + 4px)',
              left: `${hoverPct}%`,
              transform: 'translateX(-50%)',
              background: 'rgba(0,0,0,0.85)',
              border: '1px solid rgba(255,255,255,0.12)',
              padding: '2px 7px',
              borderRadius: 4,
              fontSize: 10,
              fontFamily: 'monospace',
              color: 'rgba(255,255,255,0.85)',
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
            }}
          >
            {fmtClock(hoverMs)}
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 8, fontSize: 10, color: 'rgba(255,255,255,0.35)' }}>
        <LegendDot color="#3b82f6" label="Gravado" />
        <LegendDot color="rgba(255,255,255,0.08)" label="Sem gravação" />
        {events.length > 0 && <LegendDot color="#f59e0b" label="Evento" />}
        <div style={{ marginLeft: 'auto', fontFamily: 'monospace' }}>
          Scroll: zoom · Drag: pan · ← −5s · Shift+← −30s · Espaço play
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StepBtn({ children, onClick, title }: { children: React.ReactNode; onClick: () => void; title: string }) {
  return (
    <button onClick={onClick} title={title} style={stepBtnStyle}>{children}</button>
  )
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
      <span>{label}</span>
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────────

const playBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 28,
  height: 28,
  borderRadius: 6,
  background: 'rgba(59,130,246,0.18)',
  border: '1px solid rgba(59,130,246,0.35)',
  color: '#60a5fa',
  cursor: 'pointer',
  flexShrink: 0,
}

const stepBtnStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: 24,
  height: 22,
  padding: '0 6px',
  borderRadius: 4,
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid rgba(255,255,255,0.08)',
  color: 'rgba(255,255,255,0.75)',
  fontSize: 10,
  cursor: 'pointer',
  fontFamily: 'monospace',
}

const clockInputStyle: React.CSSProperties = {
  width: 88,
  height: 24,
  padding: '0 8px',
  borderRadius: 4,
  background: 'rgba(255,255,255,0.05)',
  border: '1px solid rgba(255,255,255,0.1)',
  color: 'rgba(255,255,255,0.92)',
  fontFamily: 'monospace',
  fontSize: 12,
  textAlign: 'center',
  outline: 'none',
}
