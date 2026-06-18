import request from './index'

export const authApi = {
  login(username: string, password: string) {
    const formData = new FormData()
    formData.append('username', username)
    formData.append('password', password)
    return request.post('/auth/login', formData) as Promise<{
      access_token: string
      token_type: string
      user: any
    }>
  },
  getMe() {
    return request.get('/auth/me')
  },
  listUsers() {
    return request.get('/auth/users')
  },
  createUser(data: {
    username: string
    password: string
    full_name?: string
    email?: string
    is_superuser?: boolean
    is_active?: boolean
  }) {
    return request.post('/auth/users', data)
  },
  updateUser(userId: number, data: {
    full_name?: string
    email?: string
    is_superuser?: boolean
    is_active?: boolean
  }) {
    return request.put(`/auth/users/${userId}`, data)
  },
  resetPassword(userId: number, password: string) {
    return request.post(`/auth/users/${userId}/reset-password`, { password })
  },
  changePassword(old_password: string, new_password: string) {
    return request.put('/auth/me/password', { old_password, new_password })
  }
}
