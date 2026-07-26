import { api } from './api'

export interface Contact {
  id: string
  tenant_id: string
  camera_id: string | null
  phone_number: string
  name: string
  is_active: boolean
  created_at: string
}

interface CreateContactData {
  phone_number: string
  name: string
  camera_id?: string | null
}

interface UpdateContactData {
  name?: string
  is_active?: boolean
}

export const contactsService = {
  async list(camera_id?: string): Promise<Contact[]> {
    const res = await api.get<Contact[]>('/contacts', { params: camera_id ? { camera_id } : undefined })
    return res.data
  },

  async create(data: CreateContactData): Promise<Contact> {
    const res = await api.post<Contact>('/contacts', data)
    return res.data
  },

  async update(id: string, data: UpdateContactData): Promise<Contact> {
    const res = await api.patch<Contact>(`/contacts/${id}`, data)
    return res.data
  },

  async del(id: string): Promise<void> {
    await api.delete(`/contacts/${id}`)
  },
}
