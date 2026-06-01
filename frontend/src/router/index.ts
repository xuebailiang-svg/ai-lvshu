import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/data'
      },
      {
        path: 'data',
        name: 'Data',
        component: () => import('@/views/DataView.vue'),
        meta: { title: '历史数据管理' }
      },
      {
        path: 'analysis',
        name: 'Analysis',
        component: () => import('@/views/AnalysisView.vue'),
        meta: { title: '历史数据分析' }
      },
      {
        path: 'model',
        name: 'Model',
        component: () => import('@/views/ModelView.vue'),
        meta: { title: '评分模型 / 权重确认' }
      },
      {
        path: 'map',
        name: 'Map',
        component: () => import('@/views/MapView.vue'),
        meta: { title: '新地址评估' }
      },
      {
        path: 'compare',
        name: 'Compare',
        component: () => import('@/views/CompareView.vue'),
        meta: { title: '多地址对比' }
      },
      {
        path: 'evaluate',
        redirect: '/map'
      },
      {
        path: 'feedback-quality',
        name: 'FeedbackQuality',
        component: () => import('@/views/FeedbackQualityView.vue'),
        meta: { title: '评估反馈 / 数据质量' }
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '系统配置', requiresSuperuser: true }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth !== false && !authStore.isLoggedIn) {
    next('/login')
  } else if (to.meta.requiresSuperuser && !authStore.isSuperuser) {
    next('/')
  } else if (to.path === '/login' && authStore.isLoggedIn) {
    next('/')
  } else {
    next()
  }
})

export default router
