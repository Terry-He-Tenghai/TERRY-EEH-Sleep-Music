<script setup>
import { text as t } from '../i18n.js'

defineProps({ disabled: Boolean })
const genre = defineModel({ default: '' })
</script>

<template>
  <label class="music-setup__field">
    {{ t('音乐流派（可选）', 'Music Genre (optional)') }}
    <select v-model="genre" :disabled="disabled">
      <option value="">{{ t('不选（原有方式）', 'None (original generation)') }}</option>
      <option value="classical">{{ t('古典', 'Classical') }}</option>
      <option value="jazz">{{ t('爵士', 'Jazz') }}</option>
      <option value="folk">{{ t('民谣', 'Folk') }}</option>
    </select>
  </label>
</template>
