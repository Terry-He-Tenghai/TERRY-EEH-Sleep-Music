<script setup>
import { computed } from 'vue'
import { text as t } from '../i18n.js'
import harmonyOptions from '../../../music_harmony.json'

defineProps({ disabled: { type: Boolean, default: false } })
const mode = defineModel('mode', { default: 'major' })
const progression = defineModel('progression', { default: 'gentle' })
const progressions = computed(() => harmonyOptions[mode.value].progressions)
</script>

<template>
  <label class="harmony-field">{{ t('调式', 'Mode') }}
    <select v-model="mode" :disabled="disabled">
      <option v-for="(item, id) in harmonyOptions" :key="id" :value="id">{{ t(item.label, item.label_en) }} · {{ item.tonic }}</option>
    </select>
  </label>
  <label class="harmony-field harmony-progression">{{ t('和弦进行', 'Chord Progression') }}
    <select v-model="progression" :disabled="disabled">
      <option v-for="(item, id) in progressions" :key="id" :value="id">{{ item.roman }} · {{ item.chords }}</option>
    </select>
  </label>
</template>

<style scoped>
.harmony-field { display: grid; gap: 6px; min-width: 0; font-size: 13px; }
.harmony-progression { flex: 1 1 260px; }
select { width: 100%; min-width: 0; max-width: 100%; }
</style>
