import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from 'vue/compiler-sfc'

const options = JSON.parse(readFileSync(new URL('../../../music_harmony.json', import.meta.url), 'utf8'))

test('all four modes have matching progression ids and four explicit chords', () => {
  assert.deepEqual(Object.keys(options), ['major', 'natural_minor', 'harmonic_minor', 'melodic_minor'])
  for (const mode of Object.values(options)) {
    assert.deepEqual(Object.keys(mode.progressions), ['gentle', 'pop', 'descending', 'turnaround'])
    for (const progression of Object.values(mode.progressions)) {
      assert.equal(progression.chords.split(' - ').length, 4)
      assert.equal(progression.roman.split(' - ').length, 4)
    }
  }
  assert.equal(options.harmonic_minor.progressions.turnaround.chords, 'Am - Dm - E - Am')
  assert.equal(options.natural_minor.progressions.turnaround.chords, 'Am - Dm - Em - Am')
  assert.equal(options.melodic_minor.progressions.pop.chords, 'Am - D - E - Am')
})

test('harmony controls and manual generator compile and both workflows submit selections', () => {
  for (const filename of ['HarmonyControls.vue', 'GenreControl.vue', 'AceMusicPanel.vue']) {
    const source = readFileSync(new URL(filename, import.meta.url), 'utf8')
    const { descriptor } = parse(source)
    compileScript(descriptor, { id: filename })
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id: filename }).errors, [])
  }
  for (const filename of ['../App.vue', 'AceMusicPanel.vue']) {
    const source = readFileSync(new URL(filename, import.meta.url), 'utf8')
    assert.match(source, /harmony_mode:/)
    assert.match(source, /chord_progression:/)
    assert.match(source, /v-model:mode=/)
    assert.match(source, /v-model:progression=/)
    assert.match(source, /music_genre:/)
    assert.match(source, /<GenreControl/)
  }
})

test('optional genres include a blank default and only the three supported genres', () => {
  const source = readFileSync(new URL('GenreControl.vue', import.meta.url), 'utf8')
  assert.match(source, /defineModel\(\{ default: '' \}\)/)
  assert.deepEqual([...source.matchAll(/<option value="([^"]*)"/g)].map(match => match[1]),
    ['', 'classical', 'jazz', 'folk'])
  assert.match(source, /:disabled="disabled"/)
})
