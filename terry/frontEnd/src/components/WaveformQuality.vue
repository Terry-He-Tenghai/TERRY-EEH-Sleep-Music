<script setup>
import { computed } from 'vue'
import { modelChannelInfo, waveformDiagnostics } from '../audio/modelChannels.js'
const props = defineProps({ event: Object, count: { type: Number, default: 16 } })
const channels = computed(() => modelChannelInfo(props.event, props.count))
const diagnostics = computed(() => waveformDiagnostics(props.event))
</script>

<template>
  <div class="waveform-quality" aria-label="模型电极与质量检查">
    <p>分类电极（{{ channels.selected.length }} 路）：{{ channels.selected.join('、') }}</p>
    <p>质量检查电极（{{ channels.quality.length }} 路）：{{ channels.quality.join('、') }}。2 / 4 / 6 路模型只校验所选电极；旧 8 / 16 路模型保持全部 16 路质量检查约定。首个质量合格且分数达标的分类可触发生成；质量异常时已有音乐继续播放。</p>
    <p v-if="event?.waveform_model?.buffer_retained" role="status">窗口数据已保留，每 6 秒滚动复检；质量合格前不输出新的分类。</p>
    <p v-if="diagnostics.qualityReason" role="status">质量原因：{{ diagnostics.qualityReason }}</p>
    <p v-if="diagnostics.qualityReason?.includes('high_amplitude')" role="status">请检查异常电极与参考电极接触，减少额部眨眼、面部肌肉活动和导线晃动；30 秒峰峰值超过 500 µV 时不会输出新分类。显示滤波不改变此判定。</p>
    <p v-if="diagnostics.resetReason" role="status">窗口重置原因：{{ diagnostics.resetReason }}</p>
    <ul v-if="diagnostics.details.length"><li v-for="(detail, index) in diagnostics.details" :key="index">{{ detail }}</li></ul>
  </div>
</template>

<style scoped>
p, li { font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
</style>
