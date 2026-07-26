import { api } from './api'

export interface LgpdStatus {
  tenant_id: string
  policies_configured: number
  compliance_level: string
  face_recognition_requires_consent: boolean
  anonymization_enabled: boolean
  audit_trail_enabled: boolean
}

export interface ConsentRecord {
  data_type: string
  action: string
  created_at: string
}

export interface RetentionPolicy {
  data_type: string
  retention_days: number
  anonymize_instead_of_delete: boolean
  auto_enabled: boolean
}

export const lgpdService = {
  async getStatus(): Promise<LgpdStatus> {
    const { data } = await api.get('/lgpd/status')
    return data
  },

  async getRetentionPolicies(): Promise<{ policies: RetentionPolicy[]; defaults: Record<string, number> }> {
    const { data } = await api.get('/lgpd/retention-policies')
    return data
  },

  async setRetentionPolicy(dataType: string, retentionDays: number): Promise<void> {
    await api.post('/lgpd/retention-policies', {
      data_type: dataType,
      retention_days: retentionDays,
    })
  },

  async grantConsent(dataType: string, consentText?: string): Promise<void> {
    await api.post('/lgpd/consent', { data_type: dataType, consent_text: consentText })
  },

  async withdrawConsent(dataType: string): Promise<void> {
    await api.post('/lgpd/consent/withdraw', { data_type: dataType })
  },

  async getConsentLog(): Promise<{ items: ConsentRecord[]; total: number }> {
    const { data } = await api.get('/lgpd/consent-log')
    return data
  },

  async generateRipd(): Promise<Record<string, unknown>> {
    const { data } = await api.post('/lgpd/generate-ripd')
    return data
  },

  async requestDataExport(requestType: string, notes?: string): Promise<void> {
    await api.post('/lgpd/data-request', { request_type: requestType, notes })
  },

  async anonymizeEvents(eventType: 'alpr' | 'face', eventIds?: string[]): Promise<{ total_processed: number; results: { event_id: string; anonymized: boolean }[] }> {
    const { data } = await api.post('/lgpd/anonymize/events', {
      event_type: eventType,
      event_ids: eventIds,
    })
    return data
  },
}
