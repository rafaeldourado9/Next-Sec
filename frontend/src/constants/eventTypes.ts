/**
 * Mapeamento centralizado de tipos técnicos de evento para labels em português.
 * Usado em toda a UI para exibir nomes legíveis de eventos.
 */
export const EVENT_TYPE_LABELS: Record<string, string> = {
  // Intrusão
  'analytics.intrusion.crossed': 'Cerca virtual',
  'analytics.intrusion.started': 'Intrusão detectada',
  'analytics.intrusion.cleared': 'Intrusão encerrada',
  'intrusion.started': 'Intrusão detectada',
  'intrusion.cleared': 'Intrusão encerrada',
  'intrusion': 'Intrusão',

  // Permanência suspeita (loitering)
  'analytics.loitering.started': 'Permanência suspeita',
  'analytics.loitering.cleared': 'Permanência encerrada',
  'loitering.started': 'Permanência suspeita',
  'loitering.cleared': 'Permanência encerrada',

  // Contagem de pessoas
  'analytics.people.count': 'Contagem de pessoas',
  'analytics.people_count': 'Contagem de pessoas',
  'people_count': 'Contagem de pessoas',

  // Contagem de veículos
  'analytics.vehicle.count': 'Contagem de veículos',
  'analytics.vehicle_count': 'Contagem de veículos',
  'vehicle_count': 'Contagem de veículos',

  // Permanência de veículo (dwell)
  'analytics.vehicle.dwell': 'Permanência de veículo',
  'analytics.vehicle_dwell': 'Permanência de veículo',
  'vehicle_dwell': 'Permanência de veículo',

  // LPR/ALPR (reconhecimento de placas)
  'alpr_detected': 'LPR/ALPR',
  'analytics.lpr': 'Leitura de placa',
  'lpr': 'Leitura de placa',

  // Fabricantes
  'hikvision_motion': 'Motion (Hikvision)',
  'intelbras_event': 'Evento Intelbras',
  'camera_event': 'Evento de câmera',

  // Incêndio/Fumaça
  'analytics.fire_smoke': 'Incêndio/Fumaça',
  'fire_smoke': 'Incêndio/Fumaça',

  // EPIs
  'analytics.ppe_detection': 'Detecção de EPI',
  'ppe_detection': 'Detecção de EPI',

  // Moto/Capacete
  'analytics.biker_detection': 'Moto sem capacete',
  'biker_detection': 'Moto sem capacete',

  // Cavalo/Carroça
  'analytics.horse_cart': 'Cavalo/Carroça',
  'horse_cart': 'Cavalo/Carroça',
}

/**
 * Retorna o label em português para um tipo de evento.
 * Se não houver mapeamento, retorna o próprio tipo técnico.
 */
export function getEventTypeLabel(raw: string): string {
  return EVENT_TYPE_LABELS[raw] ?? raw
}

/**
 * Retorna a cor do badge para um tipo de evento.
 * Baseado na severidade implícita do tipo.
 */
export function getEventTypeColor(raw: string): { bg: string; text: string; border: string } {
  const lower = raw.toLowerCase()

  // Eventos críticos (intrusão, incêndio) → vermelho
  if (lower.includes('intrusion') && lower.includes('started')) {
    return { bg: 'rgba(239,68,68,0.12)', text: '#f87171', border: 'rgba(239,68,68,0.3)' }
  }
  if (lower.includes('intrusion') && lower.includes('cleared')) {
    return { bg: 'rgba(34,197,94,0.12)', text: '#4ade80', border: 'rgba(34,197,94,0.3)' }
  }
  if (lower.includes('fire') || lower.includes('smoke')) {
    return { bg: 'rgba(239,68,68,0.12)', text: '#f87171', border: 'rgba(239,68,68,0.3)' }
  }

  // Eventos de encerramento/clear → verde/neutro
  if (lower.includes('cleared') || lower.includes('ended')) {
    return { bg: 'rgba(34,197,94,0.12)', text: '#4ade80', border: 'rgba(34,197,94,0.3)' }
  }

  // Eventos de início/started → amarelo/atenção
  if (lower.includes('started')) {
    return { bg: 'rgba(245,158,11,0.12)', text: '#fbbf24', border: 'rgba(245,158,11,0.3)' }
  }

  // Loitering → amarelo
  if (lower.includes('loitering')) {
    return { bg: 'rgba(245,158,11,0.12)', text: '#fbbf24', border: 'rgba(245,158,11,0.3)' }
  }

  // LPR/ALPR → azul
  if (lower.includes('alpr') || lower.includes('lpr')) {
    return { bg: 'rgba(59,130,246,0.12)', text: '#93c5fd', border: 'rgba(59,130,246,0.3)' }
  }

  // Contagem → roxo
  if (lower.includes('count')) {
    return { bg: 'rgba(168,85,247,0.12)', text: '#c084fc', border: 'rgba(168,85,247,0.3)' }
  }

  // Dwell/permanência → laranja
  if (lower.includes('dwell')) {
    return { bg: 'rgba(249,115,22,0.12)', text: '#fb923c', border: 'rgba(249,115,22,0.3)' }
  }

  // Motion → ciano
  if (lower.includes('motion')) {
    return { bg: 'rgba(6,182,212,0.12)', text: '#22d3ee', border: 'rgba(6,182,212,0.3)' }
  }

  // Default → azul neutro
  return { bg: 'rgba(59,130,246,0.1)', text: 'rgba(147,197,253,0.8)', border: 'rgba(59,130,246,0.2)' }
}

/**
 * Retorna se o evento é do tipo "cleared/encerrado".
 */
export function isClearedEvent(raw: string): boolean {
  const lower = raw.toLowerCase()
  return lower.includes('.cleared') || lower.includes('_cleared') || lower.endsWith('.cleared')
}

/**
 * Retorna se o evento é do tipo intrusion (started ou cleared).
 */
export function isIntrusionEvent(raw: string): boolean {
  const lower = raw.toLowerCase()
  return lower.includes('intrusion')
}
