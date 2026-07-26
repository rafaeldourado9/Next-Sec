/** Schema de configuração por plugin — drive do formulário dinâmico de ROI. */

export interface FieldDef {
  key: string
  label: string
  type: 'number' | 'text'
  min?: number
  max?: number
  step?: number
  default: number | string
}

export const PLUGIN_CONFIG_SCHEMA: Record<string, FieldDef[]> = {
  intrusion: [
    { key: 'min_confidence', label: 'Confiança mínima', type: 'number', min: 0.1, max: 1, step: 0.05, default: 0.5 },
    { key: 'cooldown_seconds', label: 'Cooldown (s)', type: 'number', min: 0, max: 3600, step: 1, default: 30 },
  ],
  people_count: [
    { key: 'min_confidence', label: 'Confiança mínima', type: 'number', min: 0.1, max: 1, step: 0.05, default: 0.5 },
    { key: 'interval_seconds', label: 'Intervalo emissão (s)', type: 'number', min: 5, max: 3600, step: 1, default: 60 },
    { key: 'emit_threshold', label: 'Limiar (contagem)', type: 'number', min: 0, max: 1000, step: 1, default: 0 },
  ],
  vehicle_count: [
    { key: 'min_confidence', label: 'Confiança mínima', type: 'number', min: 0.1, max: 1, step: 0.05, default: 0.5 },
    { key: 'interval_seconds', label: 'Intervalo emissão (s)', type: 'number', min: 5, max: 3600, step: 1, default: 60 },
    { key: 'emit_threshold', label: 'Limiar (contagem)', type: 'number', min: 0, max: 1000, step: 1, default: 0 },
  ],
  lpr: [
    { key: 'min_plate_confidence', label: 'Confiança detecção placa', type: 'number', min: 0.1, max: 1, step: 0.05, default: 0.7 },
    { key: 'min_ocr_confidence', label: 'Confiança OCR', type: 'number', min: 0.1, max: 1, step: 0.05, default: 0.6 },
    { key: 'dedup_ttl_seconds', label: 'Dedup TTL (s)', type: 'number', min: 5, max: 600, step: 1, default: 60 },
  ],
  fire_smoke: [],
  ppe_detection: [],
  biker_detection: [],
  horse_cart: [],
}

/** Plugins que exigem polígono obrigatório para funcionar. */
export const POLYGON_REQUIRED: Record<string, boolean> = {
  intrusion: true,
  people_count: true,
  vehicle_count: true,
  lpr: true,
  fire_smoke: false,
  ppe_detection: false,
  biker_detection: false,
  horse_cart: false,
}
