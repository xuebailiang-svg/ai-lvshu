<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <div class="logo">🎮</div>
        <h1>电竞馆智能选址系统</h1>
        <p>Esports Site Intelligence Platform</p>
      </div>
      <el-form :model="form" :rules="rules" ref="formRef">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            size="large"
            clearable
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            @click="handleLogin"
            class="login-btn"
          >
            {{ loading ? '登录中...' : '登 录' }}
          </el-button>
        </el-form-item>
      </el-form>
      <div class="login-footer">
        <span>初始管理员密码由安装程序生成，请查看安装完成提示</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref()
const loading = ref(false)

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return
    loading.value = true
    try {
      await authStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push('/')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
}
.login-box {
  width: 420px;
  padding: 48px 40px;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5);
}
.login-header {
  text-align: center;
  margin-bottom: 36px;
}
.logo {
  font-size: 48px;
  margin-bottom: 12px;
}
.login-header h1 {
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 8px;
}
.login-header p {
  color: rgba(255, 255, 255, 0.4);
  font-size: 13px;
  margin: 0;
}
.login-btn {
  width: 100%;
  height: 46px;
  font-size: 16px;
  background: linear-gradient(90deg, #6c63ff, #48c6ef);
  border: none;
  border-radius: 8px;
}
.login-footer {
  text-align: center;
  margin-top: 16px;
  color: rgba(255, 255, 255, 0.3);
  font-size: 12px;
}
</style>
