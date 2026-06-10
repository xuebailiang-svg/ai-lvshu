<template>
  <el-container class="main-layout">
    <!-- 侧边栏 -->
    <el-aside width="220px" class="sidebar">
      <div class="sidebar-logo">
        <span class="logo-icon">🎮</span>
        <span class="logo-text">电竞选址</span>
      </div>
      <el-menu
        :default-active="$route.path"
        router
        background-color="#1a1a2e"
        text-color="rgba(255,255,255,0.65)"
        active-text-color="#6c63ff"
        class="sidebar-menu"
      >
        <el-menu-item index="/data">
          <el-icon><Upload /></el-icon>
          <span>历史数据管理</span>
        </el-menu-item>
        <el-menu-item index="/analysis">
          <el-icon><DataAnalysis /></el-icon>
          <span>历史数据分析</span>
        </el-menu-item>
        <el-menu-item index="/model">
          <el-icon><Histogram /></el-icon>
          <span>评分模型 / 权重确认</span>
        </el-menu-item>
        <el-menu-item index="/map">
          <el-icon><Location /></el-icon>
          <span>新地址评估</span>
        </el-menu-item>
        <el-menu-item index="/compare">
          <el-icon><Histogram /></el-icon>
          <span>多地址对比</span>
        </el-menu-item>
        <el-menu-item index="/competitors">
          <el-icon><OfficeBuilding /></el-icon>
          <span>竞品档案</span>
        </el-menu-item>
        <el-menu-item index="/feedback-quality">
          <el-icon><Histogram /></el-icon>
          <span>评估反馈 / 数据质量</span>
        </el-menu-item>
        <el-menu-item v-if="authStore.isSuperuser" index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统配置</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <el-dropdown @command="handleCommand">
          <div class="user-info">
            <el-avatar size="small" :style="{ background: '#6c63ff' }">
              {{ authStore.user?.username?.charAt(0).toUpperCase() }}
            </el-avatar>
            <span class="username">{{ authStore.user?.full_name || authStore.user?.username }}</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <el-header class="main-header">
        <span class="page-title">{{ $route.meta.title || '电竞馆智能选址系统' }}</span>
      </el-header>
      <el-main class="main-content">
        <!-- KeepAlive 缓存核心页面，切换路由时不销毁组件实例，任务状态完整保留 -->
        <router-view v-slot="{ Component }">
          <keep-alive :include="['MapView', 'CompareView', 'AnalysisView', 'ModelView', 'CompetitorView', 'FeedbackQualityView']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Location, DataAnalysis, Upload, Setting, Histogram, OfficeBuilding } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

async function handleCommand(cmd: string) {
  if (cmd === 'logout') {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
    authStore.logout()
    ElMessage.success('已退出登录')
    router.push('/login')
  }
}
</script>

<style scoped>
.main-layout { height: 100vh; }
.sidebar {
  background: #1a1a2e;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255,255,255,0.05);
}
.sidebar-logo {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.logo-icon { font-size: 24px; margin-right: 10px; }
.logo-text { color: #fff; font-size: 16px; font-weight: 700; }
.sidebar-menu { border: none; flex: 1; }
.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid rgba(255,255,255,0.05);
}
.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.username { color: rgba(255,255,255,0.65); font-size: 14px; }
.main-header {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 24px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.page-title { font-size: 18px; font-weight: 600; color: #1a1a2e; }
.main-content { background: #f5f7fa; padding: 24px; }
</style>
