import { api } from './api'
import type { User, UserRole } from '@/types'

interface CreateUserData {
  email: string
  password: string
  full_name: string
  role?: string
}

interface UpdateUserData {
  role?: UserRole
  is_active?: boolean
  password?: string
}

export const usersService = {
  async list(): Promise<User[]> {
    const res = await api.get<User[]>('/users')
    return res.data
  },

  async me(): Promise<User> {
    const res = await api.get<User>('/users/me')
    return res.data
  },

  async create(data: CreateUserData): Promise<User> {
    const res = await api.post<User>('/users', data)
    return res.data
  },

  async update(id: string, data: UpdateUserData): Promise<User> {
    const res = await api.patch<User>(`/users/${id}`, data)
    return res.data
  },
}
