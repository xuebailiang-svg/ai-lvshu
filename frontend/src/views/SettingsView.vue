<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="大模型配置" name="llm">
        <el-alert title="配置大模型接口，支持 API 模式（OpenAI/阿里云百炼等）和本地模式（Ollama）" type="info" :closable="false" style="margin-bottom: 16px" />
        <el-empty description="系统配置面板（阶段1后期完善）">
          <template #image><div style="font-size: 48px">🤖</div></template>
        </el-empty>
      </el-tab-pane>
      <el-tab-pane label="向量模型配置" name="embedding">
        <el-empty description="向量模型配置（阶段1后期完善）">
          <template #image><div style="font-size: 48px">🔢</div></template>
        </el-empty>
      </el-tab-pane>
      <el-tab-pane label="重排模型配置" name="reranker">
        <el-empty description="重排模型配置（阶段1后期完善）">
          <template #image><div style="font-size: 48px">🔀</div></template>
        </el-empty>
      </el-tab-pane>
      <el-tab-pane label="地图 API 配置" name="map">
        <el-empty description="高德/美团 API 配置（阶段3完善）">
          <template #image><div style="font-size: 48px">🗺️</div></template>
        </el-empty>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const activeTab = ref('llm')
</script>
