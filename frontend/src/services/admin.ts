import { api } from './api'

export interface AdminTenant {
  id: string
  name: string
  slug: string
  cnpj: string | null
  is_active: boolean
  cameras_count: number
  created_at: string | null
  latest_invoice: {
    id: string
    total: number
    status: string
    period_start: string
  } | null
}

export interface PricingPlan {
  id: string
  name: string
  camera_price: number
  storage_price_per_gb: number
  analytics_prices: Record<string, number>
  is_active: boolean
  created_at: string | null
}

export interface AdminInvoice {
  id: string
  tenant_id: string
  period_start: string
  period_end: string
  line_items: { description: string; quantity: number; unit_price: number; total: number }[]
  subtotal: number
  tax: number
  total: number
  status: 'draft' | 'pending' | 'paid' | 'overdue' | 'cancelled'
  due_date: string | null
  paid_at: string | null
}

export interface GmvSummary {
  month: string
  gmv_current: number
  gmv_previous: number
  variation_pct: number
  pending_invoices: number
  overdue_invoices: number
}

export interface TenantUsage {
  tenant_id: string
  tenant_name: string
  cameras_active: number
  cameras_online: number
  storage_gb: number
  analytics_map: Record<string, number>
}

export interface OnboardClientResult {
  tenant: { id: string; name: string; slug: string }
  gestor_email: string
  gestor_default_password: string
  license_key: string
  agent: {
    id: string
    name: string
    api_key: string
    wg_private_key: string
    wg_public_key_hub: string
    wg_endpoint: string
    wg_tunnel_ip: string
    wg_allowed_ips: string
  }
}

export const adminService = {
  // ── Tenants ────────────────────────────────────────────────────────────────

  async listTenants(page = 1, pageSize = 20): Promise<{ total: number; items: AdminTenant[] }> {
    const { data } = await api.get('/admin/tenants', { params: { page, page_size: pageSize } })
    return data
  },

  async createTenant(body: {
    name: string; slug: string; gestor_email: string
    gestor_password: string; cnpj?: string; pricing_plan_id?: string
  }): Promise<{ id: string; name: string; slug: string }> {
    const { data } = await api.post('/admin/tenants', body)
    return data
  },

  // Onboarding de cliente Nível 1 (Docker dedicado) — cria tenant + gestor
  // (senha padrão, troca obrigatória) + licença já ativa + agent com túnel
  // WireGuard, tudo numa chamada só (ver Sprint 7 / docs/DEPLOY_EDGE.md).
  async onboardClient(body: {
    name: string; slug: string; gestor_email: string
    gestor_name?: string; cnpj?: string; max_cameras?: number
  }): Promise<OnboardClientResult> {
    const { data } = await api.post('/admin/onboard-client', body)
    return data
  },

  async getTenant(id: string): Promise<any> {
    const { data } = await api.get(`/admin/tenants/${id}`)
    return data
  },

  async updateTenant(id: string, body: Partial<AdminTenant>): Promise<any> {
    const { data } = await api.put(`/admin/tenants/${id}`, body)
    return data
  },

  async suspendTenant(id: string): Promise<void> {
    await api.post(`/admin/tenants/${id}/suspend`)
  },

  async reactivateTenant(id: string): Promise<void> {
    await api.post(`/admin/tenants/${id}/reactivate`)
  },

  async deleteTenant(id: string): Promise<void> {
    await api.delete(`/admin/tenants/${id}`)
  },

  async impersonateTenant(id: string): Promise<{ access_token: string; tenant_name: string; expires_in: number }> {
    const { data } = await api.post(`/admin/tenants/${id}/impersonate`)
    return data
  },

  // ── GMV Billing ────────────────────────────────────────────────────────────

  async getGmvSummary(): Promise<GmvSummary> {
    const { data } = await api.get('/admin/billing/gmv/summary')
    return data
  },

  async getGmvTrend(): Promise<{ trend: { month: string; gmv: number }[] }> {
    const { data } = await api.get('/admin/billing/gmv/trend')
    return data
  },

  async getGmvBreakdown(): Promise<any> {
    const { data } = await api.get('/admin/billing/gmv/breakdown')
    return data
  },

  async listAllInvoices(params?: { tenant_id?: string; status?: string; page?: number }): Promise<{ total: number; items: AdminInvoice[] }> {
    const { data } = await api.get('/admin/billing/invoices', { params })
    return data
  },

  async recordPayment(invoiceId: string, body: { method: string; amount?: number; reference?: string; notes?: string }): Promise<any> {
    const { data } = await api.post(`/admin/billing/invoices/${invoiceId}/pay`, body)
    return data
  },

  async getAllTenantsUsage(): Promise<{ tenants: TenantUsage[]; as_of: string }> {
    const { data } = await api.get('/admin/billing/usage')
    return data
  },

  // ── Pricing Plans ──────────────────────────────────────────────────────────

  async listPricingPlans(): Promise<{ items: PricingPlan[] }> {
    const { data } = await api.get('/admin/pricing/plans')
    return data
  },

  async createPricingPlan(body: Partial<PricingPlan>): Promise<PricingPlan> {
    const { data } = await api.post('/admin/pricing/plans', body)
    return data
  },

  async updatePricingPlan(id: string, body: Partial<PricingPlan>): Promise<PricingPlan> {
    const { data } = await api.put(`/admin/pricing/plans/${id}`, body)
    return data
  },

  async togglePricingPlan(id: string, isActive: boolean): Promise<void> {
    await api.patch(`/admin/pricing/plans/${id}`, { is_active: isActive })
  },
}
