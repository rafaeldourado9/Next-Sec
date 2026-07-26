/**
 * DayProgressTimeline — barra de progresso contínua do dia inteiro.
 *
 * Substitui a visualização por blocos de segmento (NVRTimeline). Aqui o dia
 * é uma janela linear `[windowStartMs, windowEndMs]`; o playhead avança com o
 * tempo do player e o usuário pode clicar/arrastar em qualquer posição ou
 * usar os controles finos (±1s, ±5s, ±30s, ±1min, ±5min).
 *
 * Zonas grises sob a barra marcam "gaps" — períodos sem gravação dentro da
 * janela (ex.: câmera offline). O playhead atravessa esses gaps normalmente;
 * quem decide o comportamento é o MediaMTX (pula para o próximo fMP4).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, Rewind, FastForward, StepBack, StepForward } from 'lucide-react'

export interface DayInterval {
  id: string
  started_at: string
  ended_at: string
  duration_seconds: number
}

export interface DayProgressTimelineProps {
  /** Início da janela (epoch ms). */
  windowStartMs: number
  /** Fim da janela (epoch ms). */
  windowEndMs: number
  /** Posição atual do playhead (epoch ms). */
  currentMs: number
  /** Chamado quando o usuário solicita um seek (epoch ms). */
  onSeek: (targetMs: number) => void
  /** Playing? Para alternar o botão play/pause. */
  playing: boolean
  /** Toggle play/pause. */
  onTogglePlay: () => void
  /** Intervalos gravados dentro da janela — tudo fora deles é gap. */
  intervals: DayInterval[]
  /** Eventos pontuais para marcar como losango. */
  events?: Array<{ id: string; occurredAtMs: number; label?: string }>
  className?: string
}

function fmtClock(ms: number): string {
  const d = new Date(ms)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
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

export function DayProgressTimeline({
  windowStartMs,
  windowEndMs,
  currentMs,
  onSeek,
  playing,
  onTogglePlay,
  intervals,
  events = [],
  className,
}: DayProgressTimelineProps) {
  const barRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [hoverMs, setHoverMs] = useState<number | null>(null)
  const [inputValue, setInputValue] = useState('')

  const totalMs = Math.max(1, windowEndMs - windowStartMs)
  const pct = Math.min(100, Math.max(0, ((currentMs - windowStartMs) / totalMs) * 100))

  // Dia de referência (para parser de input HH:MM:SS)
  const dayStartMs = useMemo(() => {
    const d = new Date(windowStartMs)
    d.setHours(0, 0, 0, 0)
    return d.getTime()
  }, [windowStartMs])

  // Converte X do mouse → epoch ms dentro da janela
  const xToMs = useCallback((clientX: number): number => {
    const el = barRef.current
    if (!el) return currentMs
    const rect = el.getBoundingClientRect()
    const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return windowStartMs + frac * totalMs
  }, [windowStartMs, totalMs, currentMs])

  // Drag global
  useEffect(() => {
    if (!dragging) return
    const onMove = (e: MouseEvent) => {
      const ms = xToMs(e.clientX)
      onSeek(ms)
    }
    const onUp = () => setDragging(false)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [dragging, xToMs, onSeek])

  // Sincroniza input quando currentMs muda e usuário não está editando
  const [editing, setEditing] = useState(false)
  useEffect(() => {
    if (!editing) setInputValue(fmtClock(currentMs))
  }, [currentMs, editing])

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        const delta = e.shiftKey ? -30_000 : e.altKey ? -1_000 : -5_000
        onSeek(Math.max(windowStartMs, currentMs + delta))
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        const delta = e.shiftKey ? 30_000 : e.altKey ? 1_000 : 5_000
        onSeek(Math.min(windowEndMs, currentMs + delta))
      } else if (e.key === ' ') {
        e.preventDefault()
        onTogglePlay()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [currentMs, windowStartMs, windowEndMs, onSeek, onTogglePlay])

  // Step buttons
  const step = useCallback((deltaMs: number) => {
    const next = Math.min(windowEndMs, Math.max(windowStartMs, currentMs + deltaMs))
    onSeek(next)
  }, [currentMs, windowStartMs, windowEndMs, onSeek])

  // Ticks (uma marca por hora dentro da janela)
  const hourTicks = useMemo(() => {
    const out: Array<{ pct: number; label: string }> = []
    const start = new Date(windowStartMs)
    start.setMinutes(0, 0, 0)
    if (start.getTime() < windowStartMs) start.setHours(start.getHours() + 1)
    for (let t = start.getTime(); t <= windowEndMs; t += 3600_000) {
      const p = ((t - windowStartMs) / totalMs) * 100
      if (p >= 0 && p <= 100) {
        const d = new Date(t)
        out.push({ pct: p, label: String(d.getHours()).padStart(2, '0') + 'h' })
      }
    }
    return out
  }, [windowStartMs, windowEndMs, totalMs])

  // Zonas gravadas (inverso: usa gap como cinza). Pré-calcula zonas dos intervals.
  const recordedZones = useMemo(() => {
    return intervals.map((iv) => {
      const start = new Date(iv.started_at).getTime()
      const end = new Date(iv.ended_at).getTime()
      const a = Math.max(windowStartMs, start)
      const b = Math.min(windowEndMs, end)
      if (b <= a) return null
      return {
        id: iv.id,
        left: ((a - windowStartMs) / totalMs) * 100,
        width: ((b - a) / totalMs) * 100,
      }
    }).filter(Boolean) as Array<{ id: string; left: number; width: number }>
  }, [intervals, windowStartMs, windowEndMs, totalMs])

  const handleBarMouseDown = (e: React.MouseEvent) => {
    const ms = xToMs(e.clientX)
    onSeek(ms)
    setDragging(true)
  }
  const handleBarMouseMove = (e: React.MouseEvent) => {
    setHoverMs(xToMs(e.clientX))
  }
  const handleBarMouseLeave = () => setHoverMs(null)

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
      }}
    >
      {/* Header: relógio + botão play + controles finos + janela */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 10 }}>
        <button onClick={onTogglePlay} style={playBtn} title={playing ? 'Pausar (Space)' : 'Reproduzir (Space)'}>
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <StepBtn onClick={() => step(-300_000)} title="−5 min (Shift+←×10)">−5m</StepBtn>
          <StepBtn onClick={() => step(-60_000)} title="−1 min">−1m</StepBtn>
          <StepBtn onClick={() => step(-5_000)} title="−5 s (←)"><Rewind size={11} /></StepBtn>
          <StepBtn onClick={() => step(-1_000)} title="−1 s (Alt+←)"><StepBack size={11} /></StepBtn>
          <StepBtn onClick={() => step(1_000)} title="+1 s (Alt+→)"><StepForward size={11} /></StepBtn>
          <StepBtn onClick={() => step(5_000)} title="+5 s (→)"><FastForward size={11} /></StepBtn>
          <StepBtn onClick={() => step(60_000)} title="+1 min">+1m</StepBtn>
          <StepBtn onClick={() => step(300_000)} title="+5 min (Shift+→×10)">+5m</StepBtn>
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
          style={clockInput}
        />

        <div style={{ marginLeft: 'auto', fontSize: 11, fontFamily: 'monospace', color: 'rgba(255,255,255,0.45)' }}>
          {fmtClock(windowStartMs)} → {fmtClock(windowEndMs)}
        </div>
      </div>

      {/* Barra */}
      <div
        ref={barRef}
        onMouseDown={handleBarMouseDown}
        onMouseMove={handleBarMouseMove}
        onMouseLeave={handleBarMouseLeave}
        style={{
          position: 'relative',
          height: 42,
          borderRadius: 8,
          background: 'rgba(255,255,255,0.04)',
          cursor: 'pointer',
          userSelect: 'none',
          overflow: 'hidden',
        }}
      >
        {/* Base track (toda a janela = cinza escuro = "sem gravação") */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: 'repeating-linear-gradient(45deg, rgba(255,255,255,0.02) 0 6px, rgba(255,255,255,0.035) 6px 12px)',
        }} />

        {/* Zonas gravadas (azul claro ao fundo, sempre) */}
        {recordedZones.map((z) => (
          <div
            key={z.id}
            style={{
              position: 'absolute',
              top: 4,
              bottom: 4,
              left: `${z.left}%`,
              width: `${Math.max(z.width, 0.08)}%`,
              background: 'rgba(59,130,246,0.22)',
              borderRadius: 3,
              pointerEvents: 'none',
            }}
          />
        ))}

        {/* Fill até o playhead (gradiente azul forte) */}
        <div
          style={{
            position: 'absolute',
            top: 4,
            bottom: 4,
            left: 0,
            width: `${pct}%`,
            background: 'linear-gradient(90deg, rgba(59,130,246,0.55), rgba(99,102,241,0.78))',
            borderRadius: 3,
            pointerEvents: 'none',
            boxShadow: '0 0 18px rgba(59,130,246,0.22) inset',
          }}
        />

        {/* Ticks de hora */}
        {hourTicks.map((t) => (
          <div
            key={t.label + t.pct}
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: `${t.pct}%`,
              width: 1,
              background: 'rgba(255,255,255,0.08)',
              pointerEvents: 'none',
            }}
          >
            <div style={{
              position: 'absolute',
              top: -14,
              transform: 'translateX(-50%)',
              fontSize: 9,
              color: 'rgba(255,255,255,0.32)',
              fontFamily: 'monospace',
            }}>
              {t.label}
            </div>
          </div>
        ))}

        {/* Event markers (losangos) */}
        {events.map((ev) => {
          const p = ((ev.occurredAtMs - windowStartMs) / totalMs) * 100
          if (p < 0 || p > 100) return null
          return (
            <div
              key={ev.id}
              title={ev.label ?? fmtClock(ev.occurredAtMs)}
              style={{
                position: 'absolute',
                top: 6,
                left: `${p}%`,
                width: 8,
                height: 8,
                transform: 'translateX(-50%) rotate(45deg)',
                background: '#f59e0b',
                border: '1px solid rgba(0,0,0,0.5)',
                pointerEvents: 'none',
              }}
            />
          )
        })}

        {/* Playhead */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${pct}%`,
            width: 2,
            background: '#fff',
            transform: 'translateX(-1px)',
            boxShadow: '0 0 6px rgba(255,255,255,0.5)',
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: -3,
            left: `${pct}%`,
            width: 10,
            height: 10,
            transform: 'translateX(-50%) rotate(45deg)',
            background: '#fff',
            boxShadow: '0 0 4px rgba(0,0,0,0.5)',
            pointerEvents: 'none',
          }}
        />

        {/* Hover tooltip */}
        {hoverMs !== null && !dragging && (
          <div
            style={{
              position: 'absolute',
              bottom: 'calc(100% + 4px)',
              left: `${((hoverMs - windowStartMs) / totalMs) * 100}%`,
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

      {/* Legenda */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 10, fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>
        <LegendDot color="rgba(59,130,246,0.55)" label="Gravado" />
        <LegendDot color="rgba(255,255,255,0.08)" label="Sem gravação" />
        {events.length > 0 && <LegendDot color="#f59e0b" label="Evento" />}
        <div style={{ marginLeft: 'auto', fontFamily: 'monospace' }}>
          ← −5s · Shift+← −30s · Alt+← −1s · Espaço play
        </div>
      </div>
    </div>
  )
}

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

const playBtn: React.CSSProperties = {
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

const clockInput: React.CSSProperties = {
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
