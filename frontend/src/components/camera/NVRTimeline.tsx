/**
 * NVRTimeline v5 — clean, fluid, professional.
 *
 * Design goals:
 *  ✦ Single slim control bar — date pill, time display, step buttons, live badge
 *  ✦ Full-width scrubber rail with smooth segment visualization
 *  ✦ Thin day-overview strip (no separate minimap panel)
 *  ✦ Scroll to zoom, drag to pan
 *  ✦ Animated playhead with crisp time tooltip
 *  ✦ Zero clutter — keyboard hint only on focus
 */
import {
  useCallback, useEffect, useMemo, useRef, useState, memo,
} from 'react'
import { ChevronLeft, ChevronRight, Radio } from 'lucide-react'
import type { RecordingSegment } from '@/types'

// ─── Constants ────────────────────────────────────────────────────────────────

const ZOOM_STEPS_MS = [
  1  * 60_000,        // 1m
  5  * 60_000,        // 5m
  15 * 60_000,        // 15m
  30 * 60_000,        // 30m
  60 * 60_000,        // 1h
  2  * 3_600_000,     // 2h ← default
  4  * 3_600_000,     // 4h
  8  * 3_600_000,     // 8h
  12 * 3_600_000,     // 12h
  24 * 3_600_000,     // 24h
] as const

const DAY_MS        = 24 * 3_600_000
const SEEK_DEBOUNCE = 120

// Heights
const OVERVIEW_H = 5   // thin day-overview strip
const RULER_H    = 20  // ruler with labels
const RAIL_H     = 44  // main scrubber rail

// ─── Palette ──────────────────────────────────────────────────────────────────

const C = {
  bg:             '#08080F',
  railBg:         '#0D0D18',
  railBorder:     'rgba(255,255,255,0.04)',
  overviewBg:     '#06060D',
  tickMajor:      'rgba(255,255,255,0.10)',
  tickMinor:      'rgba(255,255,255,0.04)',
  label:          '#374151',
  labelHour:      '#4B5563',

  // Segments — soft indigo fill
  seg:            'rgba(99,102,241,0.28)',
  segTop:         'rgba(139,148,255,0.45)',
  segActive:      'rgba(99,102,241,0.55)',
  segActiveTop:   'rgba(165,180,252,0.80)',

  // Playhead
  ph:             '#FFFFFF',
  phGlow:         'rgba(255,255,255,0.12)',
  phPill:         'rgba(8,8,15,0.96)',
  phPillBd:       'rgba(255,255,255,0.14)',

  // Overview dot
  ovSeg:          'rgba(99,102,241,0.55)',
  ovPh:           'rgba(255,255,255,0.70)',
  ovWindow:       'rgba(255,255,255,0.05)',
  ovWindowBd:     'rgba(255,255,255,0.15)',

  hover:          'rgba(255,255,255,0.06)',
} as const

// ─── Helpers ──────────────────────────────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, '0')
function hhmmss(ms: number) {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
function hhmm(ms: number) {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function zoomLabel(ms: number) {
  if (ms <   60_000) return `${ms / 1_000}s`
  if (ms < 3_600_000) return `${ms / 60_000}m`
  if (ms <    DAY_MS) return `${ms / 3_600_000}h`
  return '24h'
}
function parseTimeStr(str: string, dayStartMs: number): number | null {
  const m = str.trim().match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!m) return null
  const h = parseInt(m[1], 10)
  const mn = parseInt(m[2], 10)
  const s = m[3] ? parseInt(m[3], 10) : 0
  if (h > 23 || mn > 59 || s > 59) return null
  return dayStartMs + (h * 3600 + mn * 60 + s) * 1000
}
function getTickConfig(viewMs: number): { tick: number; label: number; fmt: 'hhmm' | 'hhmmss' } {
  if (viewMs <=  1 * 60_000)    return { tick: 10_000,       label: 30_000,        fmt: 'hhmmss' }
  if (viewMs <=  5 * 60_000)    return { tick: 30_000,       label: 60_000,        fmt: 'hhmmss' }
  if (viewMs <= 15 * 60_000)    return { tick: 60_000,       label: 5 * 60_000,    fmt: 'hhmm'  }
  if (viewMs <= 30 * 60_000)    return { tick: 5 * 60_000,   label: 10 * 60_000,   fmt: 'hhmm'  }
  if (viewMs <=     3_600_000)  return { tick: 5 * 60_000,   label: 15 * 60_000,   fmt: 'hhmm'  }
  if (viewMs <=  2 * 3_600_000) return { tick: 10 * 60_000,  label: 30 * 60_000,   fmt: 'hhmm'  }
  if (viewMs <=  4 * 3_600_000) return { tick: 30 * 60_000,  label: 3_600_000,     fmt: 'hhmm'  }
  if (viewMs <=  8 * 3_600_000) return { tick: 3_600_000,    label: 2 * 3_600_000, fmt: 'hhmm'  }
  return                               { tick: 2*3_600_000,  label: 4 * 3_600_000, fmt: 'hhmm'  }
}

// ─── SegBlock ─────────────────────────────────────────────────────────────────

const SegBlock = memo(function SegBlock({
  seg, leftPct, widthPct, isActive, onSeek,
}: {
  seg: RecordingSegment
  leftPct: number
  widthPct: number
  isActive: boolean
  onSeek: (ms: number) => void
}) {
  const s0 = new Date(seg.started_at).getTime()
  const gradient = isActive
    ? `linear-gradient(to bottom, ${C.segActiveTop} 0%, ${C.segActive} 100%)`
    : `linear-gradient(to bottom, ${C.segTop} 0%, ${C.seg} 100%)`

  return (
    <div
      title={`${hhmm(s0)} — ${hhmm(new Date(seg.ended_at).getTime())}`}
      style={{
        position:     'absolute',
        left:         `${leftPct}%`,
        width:        `${Math.max(0.2, widthPct)}%`,
        top:           7,
        bottom:        7,
        borderRadius:  3,
        background:    gradient,
        boxShadow:     isActive ? '0 0 12px rgba(99,102,241,0.22)' : undefined,
        cursor:       'pointer',
        transition:   'background 0.12s, box-shadow 0.12s',
        zIndex:        isActive ? 2 : 1,
      }}
      onClick={(e) => { e.stopPropagation(); onSeek(s0) }}
    />
  )
})

// ─── TimeInput ────────────────────────────────────────────────────────────────

function TimeInput({
  playheadMs, dayStartMs, onSeek,
}: {
  playheadMs: number
  dayStartMs: number
  onSeek: (ms: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft  ] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const currentStr = hhmmss(playheadMs)

  function commit(value: string) {
    const ms = parseTimeStr(value, dayStartMs)
    if (ms !== null) onSeek(ms)
    setEditing(false)
  }

  function startEdit() {
    setDraft(currentStr)
    setEditing(true)
    requestAnimationFrame(() => inputRef.current?.select())
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => commit(draft)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(draft) }
          if (e.key === 'Escape') setEditing(false)
        }}
        autoFocus
        placeholder="HH:MM:SS"
        style={{
          fontFamily:    'ui-monospace, "JetBrains Mono", monospace',
          fontSize:       13,
          fontWeight:     700,
          letterSpacing: '0.06em',
          color:         '#F9FAFB',
          background:    'rgba(99,102,241,0.18)',
          border:        '1px solid rgba(99,102,241,0.50)',
          borderRadius:   6,
          padding:       '0 10px',
          height:         30,
          width:          90,
          textAlign:     'center',
          outline:       'none',
        }}
      />
    )
  }

  return (
    <button
      onClick={startEdit}
      title="Clique para digitar horário (HH:MM:SS)"
      style={{
        fontFamily:    'ui-monospace, "JetBrains Mono", monospace',
        fontSize:       13,
        fontWeight:     700,
        letterSpacing: '0.06em',
        color:         '#E5E7EB',
        background:    'rgba(255,255,255,0.06)',
        border:        '1px solid rgba(255,255,255,0.09)',
        borderRadius:   6,
        padding:       '0 10px',
        height:         30,
        cursor:        'text',
        whiteSpace:    'nowrap',
        transition:    'background 0.12s, border-color 0.12s',
      }}
      onMouseEnter={(e) => {
        const b = e.currentTarget as HTMLButtonElement
        b.style.background   = 'rgba(255,255,255,0.09)'
        b.style.borderColor  = 'rgba(255,255,255,0.16)'
      }}
      onMouseLeave={(e) => {
        const b = e.currentTarget as HTMLButtonElement
        b.style.background   = 'rgba(255,255,255,0.06)'
        b.style.borderColor  = 'rgba(255,255,255,0.09)'
      }}
    >
      {currentStr}
    </button>
  )
}



// ─── StepBtn ──────────────────────────────────────────────────────────────────

function StepBtn({ label, title, onClick }: { label: string; title: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        height:        26,
        padding:       '0 7px',
        fontSize:       11,
        fontWeight:     500,
        fontFamily:    'ui-monospace, monospace',
        color:         '#3F3F46',
        background:    'transparent',
        border:        '1px solid rgba(255,255,255,0.05)',
        borderRadius:   5,
        cursor:        'pointer',
        whiteSpace:    'nowrap',
        transition:    'color 0.1s, border-color 0.1s',
        flexShrink:     0,
      }}
      onMouseEnter={(e) => {
        const b = e.currentTarget as HTMLButtonElement
        b.style.color       = '#9CA3AF'
        b.style.borderColor = 'rgba(255,255,255,0.13)'
      }}
      onMouseLeave={(e) => {
        const b = e.currentTarget as HTMLButtonElement
        b.style.color       = '#3F3F46'
        b.style.borderColor = 'rgba(255,255,255,0.05)'
      }}
    >
      {label}
    </button>
  )
}

// ─── Props ────────────────────────────────────────────────────────────────────

export interface NVRTimelineProps {
  segments:       RecordingSegment[]
  currentSegId?:  string | null
  playheadMs:     number
  selectedDate:   string
  isLoading?:     boolean
  onSeek:         (ms: number) => void
  onDateChange?:  (d: string) => void
  onRangeChange?: (start: Date, end: Date) => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export function NVRTimeline({
  segments,
  currentSegId,
  playheadMs,
  selectedDate,
  isLoading = false,
  onSeek,
  onDateChange,
  onRangeChange,
}: NVRTimelineProps) {

  const railRef    = useRef<HTMLDivElement>(null)
  const overviewRef= useRef<HTMLDivElement>(null)
  const wrapRef    = useRef<HTMLDivElement>(null)

  const today   = new Date().toISOString().split('T')[0]
  const isToday = selectedDate === today

  const dayStart = useMemo(
    () => new Date(selectedDate + 'T00:00:00').getTime(),
    [selectedDate],
  )

  // ── View state ──────────────────────────────────────────────────────────────
  const [viewMs,     setViewMs    ] = useState<number>(ZOOM_STEPS_MS[5])
  const [viewStart,  setViewStart ] = useState<number>(() => playheadMs - ZOOM_STEPS_MS[5] / 2)
  const [autoFollow, setAutoFollow] = useState(true)

  // ── Hover ───────────────────────────────────────────────────────────────────
  const [hoverMs,  setHoverMs ] = useState<number | null>(null)
  const [hoverPct, setHoverPct] = useState<number | null>(null)

  // ── Drag ────────────────────────────────────────────────────────────────────
  const drag = useRef({ active: false, startX: 0, startView: 0, moved: false })

  // ── Seek debounce ───────────────────────────────────────────────────────────
  const seekTimer   = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingSeek = useRef<number | null>(null)

  const fireSeek = useCallback((ms: number) => {
    if (seekTimer.current) clearTimeout(seekTimer.current)
    pendingSeek.current = null
    onSeek(ms)
  }, [onSeek])

  const debouncedSeek = useCallback((ms: number) => {
    pendingSeek.current = ms
    if (seekTimer.current) clearTimeout(seekTimer.current)
    seekTimer.current = setTimeout(() => {
      if (pendingSeek.current !== null) {
        onSeek(pendingSeek.current)
        pendingSeek.current = null
      }
    }, SEEK_DEBOUNCE)
  }, [onSeek])

  // ── Clamp ───────────────────────────────────────────────────────────────────
  const clamp = useCallback((v: number, vm = viewMs) => {
    const dayEnd = dayStart + DAY_MS
    return Math.max(dayStart - vm * 0.05, Math.min(dayEnd - vm * 0.95, v))
  }, [dayStart, viewMs])

  // ── Stable ref for wheel handler ────────────────────────────────────────────
  const live = useRef({ viewStart, viewMs, dayStart })
  useEffect(() => { live.current = { viewStart, viewMs, dayStart } }, [viewStart, viewMs, dayStart])

  // ── Notify range change ─────────────────────────────────────────────────────
  const onRangeRef = useRef(onRangeChange)
  useEffect(() => { onRangeRef.current = onRangeChange }, [onRangeChange])
  useEffect(() => {
    onRangeRef.current?.(new Date(viewStart), new Date(viewStart + viewMs))
  }, [viewStart, viewMs])

  // ── Auto-follow playhead ────────────────────────────────────────────────────
  useEffect(() => {
    if (!autoFollow) return
    setViewStart(clamp(playheadMs - viewMs / 2))
  }, [playheadMs, viewMs, autoFollow, clamp])

  // ── Reset on date change ────────────────────────────────────────────────────
  useEffect(() => {
    const vm = ZOOM_STEPS_MS[5]
    setViewMs(vm)
    setViewStart(dayStart)
    setAutoFollow(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDate, dayStart])

  // ── Derived ─────────────────────────────────────────────────────────────────
  const viewEnd = viewStart + viewMs

  const toViewPct = useCallback(
    (ms: number) => ((ms - viewStart) / viewMs) * 100,
    [viewStart, viewMs],
  )
  const toDayPct = useCallback(
    (ms: number) => ((ms - dayStart) / DAY_MS) * 100,
    [dayStart],
  )

  const visibleSegs = useMemo(() =>
    segments.filter((s) => {
      const s0 = new Date(s.started_at).getTime()
      const s1 = new Date(s.ended_at).getTime()
      return s1 >= viewStart && s0 <= viewEnd
    }),
    [segments, viewStart, viewEnd],
  )

  const ticks = useMemo(() => {
    const { tick, label: labelInt, fmt } = getTickConfig(viewMs)
    const first = Math.ceil(viewStart / tick) * tick
    const items: Array<{ ms: number; pct: number; major: boolean; label: string | null }> = []
    for (let t = first; t <= viewEnd; t += tick) {
      const isMajor = t % labelInt === 0
      items.push({
        ms: t, pct: toViewPct(t), major: isMajor,
        label: isMajor ? (fmt === 'hhmmss' ? hhmmss(t) : hhmm(t)) : null,
      })
    }
    return items
  }, [viewStart, viewEnd, viewMs, toViewPct])

  const phPct     = toViewPct(playheadMs)
  const phVisible = phPct >= -0.5 && phPct <= 100.5
  const phLabelPct = `${Math.max(3, Math.min(96, phPct))}%`
  const tipPct     = hoverPct !== null ? `${Math.max(3, Math.min(96, hoverPct))}%` : '0'

  const mmViewLeft = Math.max(0, Math.min(99, toDayPct(viewStart)))
  const mmViewW    = Math.min(100 - mmViewLeft, (viewMs / DAY_MS) * 100)
  const mmPhPct    = Math.max(0, Math.min(100, toDayPct(playheadMs)))

  // ── Wheel zoom ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const el = railRef.current
    if (!el) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      const { viewStart: vs, viewMs: vm, dayStart: ds } = live.current
      const rect   = el.getBoundingClientRect()
      const frac   = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      const anchor = vs + frac * vm
      const dir    = e.deltaY > 0 ? 1 : -1
      const idx    = ZOOM_STEPS_MS.indexOf(vm as typeof ZOOM_STEPS_MS[number])
      const newIdx = Math.max(0, Math.min(ZOOM_STEPS_MS.length - 1, idx + dir))
      const newVm  = ZOOM_STEPS_MS[newIdx]
      const dayEnd = ds + DAY_MS
      const newStart = Math.max(
        ds - newVm * 0.05,
        Math.min(dayEnd - newVm * 0.95, anchor - frac * newVm),
      )
      setViewMs(newVm)
      setViewStart(newStart)
      setAutoFollow(false)
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  // ── Pointer helpers ─────────────────────────────────────────────────────────
  const pctFromEvent = useCallback((clientX: number) => {
    const rect = railRef.current?.getBoundingClientRect()
    if (!rect) return 0
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  }, [])

  const msFromEvent = useCallback(
    (clientX: number) => viewStart + pctFromEvent(clientX) * viewMs,
    [viewStart, viewMs, pctFromEvent],
  )

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { active: true, startX: e.clientX, startView: viewStart, moved: false }
    e.currentTarget.style.cursor = 'grabbing'
    setAutoFollow(false)
    e.preventDefault()
  }, [viewStart])

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const pct = pctFromEvent(e.clientX) * 100
    const ms  = viewStart + (pct / 100) * viewMs
    setHoverPct(pct)
    setHoverMs(Math.max(viewStart, Math.min(viewEnd, ms)))

    if (!drag.current.active) return
    const dx = e.clientX - drag.current.startX
    if (Math.abs(dx) > 4) drag.current.moved = true

    if (drag.current.moved) {
      const rect = railRef.current?.getBoundingClientRect()
      if (!rect) return
      setViewStart(clamp(drag.current.startView - dx * (viewMs / rect.width)))
    } else {
      debouncedSeek(ms)
    }
  }, [viewStart, viewEnd, viewMs, pctFromEvent, clamp, debouncedSeek])

  const handlePointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current.active) return
    drag.current.active = false
    e.currentTarget.style.cursor = 'crosshair'
    if (!drag.current.moved) fireSeek(msFromEvent(e.clientX))
  }, [msFromEvent, fireSeek])

  const handlePointerLeave = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    setHoverMs(null); setHoverPct(null)
    if (drag.current.active) {
      drag.current.active = false
      e.currentTarget.style.cursor = 'crosshair'
    }
  }, [])

  // ── Overview click ──────────────────────────────────────────────────────────
  const handleOverviewClick = useCallback((e: React.MouseEvent) => {
    const rect = overviewRef.current?.getBoundingClientRect()
    if (!rect) return
    const frac    = (e.clientX - rect.left) / rect.width
    const clickMs = dayStart + frac * DAY_MS
    setViewStart(clamp(clickMs - viewMs / 2))
    setAutoFollow(false)
  }, [dayStart, viewMs, clamp])

  // ── Step seek & keyboard ────────────────────────────────────────────────────
  const stepSeek = useCallback((deltaMs: number) => {
    const next = Math.max(dayStart, Math.min(dayStart + DAY_MS - 1, playheadMs + deltaMs))
    fireSeek(next)
    setAutoFollow(false)
  }, [playheadMs, dayStart, fireSeek])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return
      e.preventDefault()
      const dir   = e.key === 'ArrowRight' ? 1 : -1
      const delta = e.ctrlKey ? 5 * 60_000 : e.shiftKey ? 30_000 : 5_000
      stepSeek(dir * delta)
    }
    el.addEventListener('keydown', handler)
    return () => el.removeEventListener('keydown', handler)
  }, [stepSeek])

  // ── Date nav ────────────────────────────────────────────────────────────────
  const shiftDay = useCallback((delta: number) => {
    if (!onDateChange) return
    const d = new Date(selectedDate + 'T12:00:00')
    d.setDate(d.getDate() + delta)
    onDateChange(d.toISOString().split('T')[0])
  }, [selectedDate, onDateChange])

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <div
      ref={wrapRef}
      className="select-none"
      tabIndex={0}
      style={{ outline: 'none' }}
    >
      {/* ═══ CONTROL BAR ════════════════════════════════════════════════════ */}
      <div
        style={{
          display:    'flex',
          alignItems: 'center',
          gap:         8,
          marginBottom: 10,
          flexWrap:   'wrap',
        }}
      >
        {/* Date nav pill */}
        {onDateChange && (
          <div
            style={{
              display:     'flex',
              alignItems:  'center',
              background:  'rgba(255,255,255,0.04)',
              border:      '1px solid rgba(255,255,255,0.07)',
              borderRadius: 8,
              overflow:    'hidden',
            }}
          >
            <button
              onClick={() => shiftDay(-1)}
              title="Dia anterior"
              style={navBtnStyle}
            >
              <ChevronLeft size={13} />
            </button>
            <div style={navDividerStyle} />
            <label
              style={{
                padding: '0 12px', height: 30, lineHeight: '30px',
                color: '#9CA3AF', fontSize: 12, fontWeight: 500,
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}
              title="Escolher data"
            >
              {isToday ? 'Hoje' : selectedDate}
              <input
                type="date"
                className="sr-only"
                value={selectedDate}
                max={today}
                onChange={(e) => e.target.value && onDateChange(e.target.value)}
              />
            </label>
            <div style={navDividerStyle} />
            <button
              onClick={() => shiftDay(1)}
              disabled={selectedDate >= today}
              title="Próximo dia"
              style={navBtnStyle}
              className="disabled:opacity-30"
            >
              <ChevronRight size={13} />
            </button>
          </div>
        )}

        {/* Separator */}
        <div style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.05)', flexShrink: 0 }} />

        {/* Time display */}
        <TimeInput
          playheadMs={playheadMs}
          dayStartMs={dayStart}
          onSeek={(ms) => { fireSeek(ms); setAutoFollow(false) }}
        />

        {/* Step buttons */}
        <StepBtn label="−1m"  title="Recuar 1 minuto"    onClick={() => stepSeek(-60_000)} />
        <StepBtn label="−10s" title="Recuar 10 segundos"  onClick={() => stepSeek(-10_000)} />
        <StepBtn label="+10s" title="Avançar 10 segundos" onClick={() => stepSeek(+10_000)} />
        <StepBtn label="+1m"  title="Avançar 1 minuto"    onClick={() => stepSeek(+60_000)} />

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Zoom indicator */}
        <div
          style={{
            display:    'flex',
            alignItems: 'center',
            gap:         4,
            height:     26,
            padding:    '0 8px',
            background: 'rgba(255,255,255,0.03)',
            border:     '1px solid rgba(255,255,255,0.05)',
            borderRadius: 5,
            color:      '#27272A',
            fontSize:    10,
            userSelect: 'none',
          }}
          title="Scroll do mouse para zoom"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ opacity: 0.4 }}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35M11 8v6M8 11h6"/></svg>
          <span style={{ fontFamily: 'ui-monospace, monospace', fontWeight: 500 }}>
            {zoomLabel(viewMs)}
          </span>
        </div>

        {/* Live / follow button */}
        {isToday ? (
          <button
            style={{
              display:    'flex',
              alignItems: 'center',
              gap:         5,
              height:     30,
              padding:    '0 12px',
              borderRadius: 7,
              background: autoFollow ? 'rgba(239,68,68,0.12)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${autoFollow ? 'rgba(239,68,68,0.30)' : 'rgba(255,255,255,0.07)'}`,
              color: autoFollow ? '#FCA5A5' : '#4B5563',
              fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onClick={() => { setAutoFollow(true); fireSeek(Date.now()) }}
          >
            <Radio size={9} className={autoFollow ? 'animate-pulse' : ''} />
            AO VIVO
          </button>
        ) : (
          <button
            style={{
              height: 30, padding: '0 12px', borderRadius: 7,
              background: autoFollow ? 'rgba(99,102,241,0.12)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${autoFollow ? 'rgba(99,102,241,0.30)' : 'rgba(255,255,255,0.07)'}`,
              color: autoFollow ? '#A5B4FC' : '#4B5563',
              fontSize: 10, fontWeight: 700, cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onClick={() => setAutoFollow((v) => !v)}
          >
            {autoFollow ? '● seguindo' : '○ fixo'}
          </button>
        )}
      </div>

      {/* ═══ DAY OVERVIEW STRIP ═════════════════════════════════════════════ */}
      <div
        ref={overviewRef}
        onClick={handleOverviewClick}
        title="Clique para ir a esse horário do dia"
        style={{
          position:     'relative',
          height:        OVERVIEW_H,
          background:    C.overviewBg,
          borderRadius:  3,
          overflow:     'hidden',
          cursor:       'pointer',
          marginBottom:  6,
        }}
      >
        {/* Segment blocks in the overview */}
        {segments.map((seg) => {
          const s0 = new Date(seg.started_at).getTime()
          const s1 = new Date(seg.ended_at).getTime()
          return (
            <div
              key={seg.id}
              style={{
                position: 'absolute',
                left:     `${toDayPct(s0)}%`,
                width:    `${Math.max(0.3, ((s1 - s0) / DAY_MS) * 100)}%`,
                top: 0, bottom: 0,
                background: C.ovSeg,
                borderRadius: 2,
              }}
            />
          )
        })}

        {/* Viewport window indicator */}
        <div
          style={{
            position:  'absolute',
            left:      `${mmViewLeft}%`,
            width:     `${mmViewW}%`,
            top: 0, bottom: 0,
            background: C.ovWindow,
            border:     `1px solid ${C.ovWindowBd}`,
            borderRadius: 2,
            boxSizing:  'border-box',
            pointerEvents: 'none',
          }}
        />

        {/* Playhead dot in overview */}
        <div
          style={{
            position: 'absolute',
            left:     `${mmPhPct}%`,
            top: 0, bottom: 0,
            width: 1.5,
            background: C.ovPh,
            pointerEvents: 'none',
          }}
        />
      </div>

      {/* ═══ TIMELINE RAIL ══════════════════════════════════════════════════ */}
      <div style={{ position: 'relative' }}>

        {/* Ruler */}
        <div
          style={{
            position: 'relative',
            height: RULER_H,
            pointerEvents: 'none',
            overflow: 'visible',
          }}
        >
          {ticks.map((tick) => (
            <div key={tick.ms}>
              <div
                style={{
                  position:  'absolute',
                  left:      `${tick.pct}%`,
                  bottom:     0,
                  width:      1,
                  height:    tick.major ? 8 : 3,
                  background: tick.major ? C.tickMajor : C.tickMinor,
                  transform: 'translateX(-50%)',
                }}
              />
              {tick.label && (
                <div
                  style={{
                    position:  'absolute',
                    left:      `${tick.pct}%`,
                    top:        3,
                    transform: 'translateX(-50%)',
                    fontSize:   10,
                    fontFamily: 'ui-monospace, "JetBrains Mono", monospace',
                    fontWeight: tick.ms % 3_600_000 === 0 ? 600 : 400,
                    color:      tick.ms % 3_600_000 === 0 ? C.labelHour : C.label,
                    whiteSpace: 'nowrap',
                    lineHeight: 1,
                  }}
                >
                  {tick.label}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Rail */}
        <div
          ref={railRef}
          style={{
            position: 'relative',
            height:    RAIL_H,
            background: C.railBg,
            border:    `1px solid ${C.railBorder}`,
            borderRadius: 8,
            overflow:  'hidden',
            cursor:   'crosshair',
            userSelect: 'none',
            touchAction: 'none',
          }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerLeave}
        >
          {/* Shimmer while loading */}
          {isLoading && (
            <div
              className="animate-pulse"
              style={{
                position: 'absolute', inset: 0,
                background: 'rgba(255,255,255,0.015)',
              }}
            />
          )}

          {/* Subtle tick grid inside rail */}
          {ticks.filter(t => t.major).map((tick) => (
            <div
              key={`rg-${tick.ms}`}
              style={{
                position: 'absolute',
                left:     `${tick.pct}%`,
                top: 0, bottom: 0,
                width: 1,
                background: 'rgba(255,255,255,0.03)',
                pointerEvents: 'none',
              }}
            />
          ))}

          {/* Segment blocks */}
          {!isLoading && visibleSegs.map((seg) => {
            const s0 = new Date(seg.started_at).getTime()
            const s1 = new Date(seg.ended_at).getTime()
            return (
              <SegBlock
                key={seg.id}
                seg={seg}
                leftPct={toViewPct(s0)}
                widthPct={((s1 - s0) / viewMs) * 100}
                isActive={seg.id === currentSegId}
                onSeek={fireSeek}
              />
            )
          })}

          {/* Hover highlight */}
          {hoverPct !== null && (
            <div
              style={{
                position: 'absolute',
                left: `${hoverPct}%`,
                top: 0, bottom: 0,
                width: 1,
                background: C.hover,
                pointerEvents: 'none',
                zIndex: 4,
              }}
            />
          )}

          {/* Playhead line */}
          {phVisible && (
            <div
              style={{
                position: 'absolute',
                left:     `${phPct}%`,
                top: 0, bottom: 0,
                width: 1.5,
                transform: 'translateX(-50%)',
                background: C.ph,
                boxShadow: `0 0 6px ${C.phGlow}`,
                pointerEvents: 'none',
                zIndex: 5,
              }}
            />
          )}

          {/* Playhead diamond handle */}
          {phVisible && (
            <div
              style={{
                position:  'absolute',
                left:      `${phPct}%`,
                top:       '50%',
                transform: 'translate(-50%, -50%) rotate(45deg)',
                width: 7, height: 7,
                background: C.ph,
                boxShadow: `0 0 8px ${C.phGlow}`,
                pointerEvents: 'none',
                zIndex: 6,
              }}
            />
          )}

          {/* Empty state */}
          {segments.length === 0 && !isLoading && (
            <div
              style={{
                position:  'absolute', inset: 0,
                display:   'flex', alignItems: 'center', justifyContent: 'center',
                fontSize:  11, color: '#1F1F2E',
                pointerEvents: 'none', letterSpacing: '0.02em',
              }}
            >
              Sem gravações nesta data
            </div>
          )}
        </div>

        {/* Hover tooltip */}
        {hoverMs !== null && hoverPct !== null && (
          <div
            style={{
              position:   'absolute',
              left:        tipPct,
              top:        -(RULER_H - 2),
              transform:  'translateX(-50%)',
              background:  C.phPill,
              border:     `1px solid ${C.phPillBd}`,
              color:      '#D1D5DB',
              fontSize:    10,
              fontFamily: 'ui-monospace, monospace',
              fontWeight:  500,
              padding:    '2px 8px',
              borderRadius: 4,
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
              boxShadow:  '0 4px 16px rgba(0,0,0,0.5)',
              zIndex:      10,
            }}
          >
            {hhmmss(hoverMs)}
          </div>
        )}

        {/* Playhead time pill */}
        {phVisible && (
          <div
            style={{
              position:   'absolute',
              left:        phLabelPct,
              top:        -(RULER_H - 0),
              transform:  'translateX(-50%)',
              background:  C.phPill,
              border:     `1px solid ${C.phPillBd}`,
              color:      '#F9FAFB',
              fontSize:    10,
              fontFamily: 'ui-monospace, monospace',
              fontWeight:  700,
              padding:    '2px 8px',
              borderRadius: 4,
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
              letterSpacing: '0.04em',
              boxShadow:   '0 2px 12px rgba(0,0,0,0.60)',
              zIndex:       10,
            }}
          >
            {hhmmss(playheadMs)}
          </div>
        )}
      </div>

      {/* Keyboard hint — subtle, right-aligned */}
      <div
        style={{
          marginTop:    5,
          fontSize:     9,
          color:       '#1C1C28',
          letterSpacing: '0.02em',
          textAlign:   'right',
          userSelect:  'none',
        }}
      >
        ←/→ ±5s · Shift ±30s · Ctrl ±5min · scroll = zoom
      </div>
    </div>
  )
}

// ─── Style constants ───────────────────────────────────────────────────────────

const navBtnStyle: React.CSSProperties = {
  display:        'flex',
  alignItems:     'center',
  justifyContent: 'center',
  width:           30,
  height:          30,
  background:     'transparent',
  border:         'none',
  color:          '#374151',
  cursor:         'pointer',
  flexShrink:      0,
  transition:     'color 0.12s',
}

const navDividerStyle: React.CSSProperties = {
  width:      1,
  height:     16,
  background: 'rgba(255,255,255,0.06)',
  flexShrink:  0,
}
