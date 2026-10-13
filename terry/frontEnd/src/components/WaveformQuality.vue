<script setup>
import { computed } from 'vue'
import { text as t } from '../i18n.js'
import { modelChannelInfo, waveformDiagnostics } from '../audio/modelChannels.js'
const props = defineProps({ event: Object, count: { type: Number, default: 16 } })
const channels = computed(() => modelChannelInfo(props.event, props.count))
const diagnostics = computed(() => waveformDiagnostics(props.event))
</script>

<template>
  <div class="waveform-quality" :aria-label="t('模型电极与质量检查', 'Model electrodes and signal quality')">
    <p>{{ t('分类电极', 'Classification electrodes') }} ({{ channels.selected.length }}): {{ channels.selected.join(', ') }}</p>
    <p>{{ t('质量检查电极', 'Quality-check electrodes') }} ({{ channels.quality.length }}): {{ channels.quality.join(', ') }}. {{ t('2 / 4 / 6 路模型只校验所选电极；旧 8 / 16 路模型保持全部 16 路质量检查约定。首个质量合格且分数达标的分类可触发生成；质量异常时已有音乐继续播放。', 'Models with 2 / 4 / 6 channels check selected electrodes; legacy 8 / 16-channel models check all 16 electrodes. Generation requires acceptable quality and model scores; existing music continues during quality rejection.') }}</p>
    <p v-if="event?.waveform_model?.buffer_retained" role="status">{{ t('窗口数据已保留，每 6 秒滚动复检；质量合格前不输出新的分类。', 'Window retained and rechecked every 6 seconds; no new classification until quality passes.') }}</p>
    <p v-if="diagnostics.qualityReason" role="status">{{ t('质量原因：', 'Quality reason: ') }}{{ diagnostics.qualityReason }}</p>
    <p v-if="diagnostics.qualityReason?.includes('high_amplitude')" role="status">{{ t('请检查异常电极与参考电极接触，减少额部眨眼、面部肌肉活动和导线晃动；30 秒峰峰值超过 500 µV 时不会输出新分类。显示滤波不改变此判定。', 'Check electrode and reference contact; reduce blinking, facial movement and cable motion. A 30-second peak-to-peak amplitude above 500 µV blocks new classification. Display filtering does not change this check.') }}</p>
    <p v-if="diagnostics.resetReason" role="status">{{ t('窗口重置原因：', 'Window reset reason: ') }}{{ diagnostics.resetReason }}</p>
    <ul v-if="diagnostics.details.length"><li v-for="(detail, index) in diagnostics.details" :key="index">{{ detail }}</li></ul>
  </div>
</template>

<style scoped>
p, li { font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
</style>
