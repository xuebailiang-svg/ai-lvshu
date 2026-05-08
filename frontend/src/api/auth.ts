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
  }
}
