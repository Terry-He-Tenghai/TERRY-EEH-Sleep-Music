# Suno 音频提示词库

## 1. 用途与边界

Suno 在本项目中只负责离线生成候选素材，不参与实时脑电控制。正式实验应在试听、技术检查和人工审核后，冻结本地音频文件；现场运行不依赖网络或实时生成。

本项目的自主贡献由本地音乐引擎完成：四层增益、M1/M2/M3 状态、乐句边界调度、确定性 MIDI 动机和波形参数控制。Suno 生成的是基础铺底或环境纹理，不应被描述为脑电特征与乐器之间已经得到验证的科学对应关系。

`sunoapi.org` 可能是第三方接口服务。使用前应核实服务商身份、费用、授权范围、音乐许可、隐私政策和数据保留条款。

## 2. 统一生成设置

- 使用自定义模式（Custom）。
- 开启纯音乐（Instrumental），关闭人声和歌词。
- 优先使用 `V5_5`，长度建议 180 秒；微觉醒修复素材可单独制作 15 秒版本。
- 速度稳定，优先 52–60 BPM；不使用明显的高潮、鼓点、突然转调或强烈音量变化。
- 生成后记录版本、日期、提示词、参数、来源页面、文件哈希和审核结论。
- 一次生成多首候选时，只保留能够无明显断裂循环、无突发瞬态、无可辨识人声的版本。

## 3. 基础铺底：L1 / Pad

### 标题

`Warm Low-Information Sleep Pad`

### Style 提示词

```text
60 BPM instrumental sleep ambient, warm soft evolving pads, very low melodic complexity, stable tonal center, consonant harmony, slow attack, long sustain, low spectral brightness, low dynamic range, gentle breathing-like amplitude movement, predictable texture, no climax, seamless loop-friendly arrangement, spacious but intimate
```

### Negative Tags

```text
vocals, lyrics, spoken words, drums, percussion, cymbals, arpeggios, catchy hook, bright lead, sharp transient, sudden volume change, dramatic build, drop, modulation, dissonance, syncopation, horror, tension, rain sounds, notification sounds
```

## 4. 环境纹理：L4 / Texture

### 标题

`Filtered Brown Texture for Sleep`

### Style 提示词

```text
near-beatless instrumental ambient texture, soft filtered brown-noise-like bed, deep warm low-mid frequencies, extremely slow movement, very low information density, subtle wide stereo atmosphere, no foreground melody, no rhythm, no climax, stable volume, seamless loop-friendly soundscape
```

### Negative Tags

```text
vocals, lyrics, melody, piano lead, drums, percussion, pulse, beat, bass drop, bright high frequencies, hiss, crackle, alarm, riser, impact, sudden change, cinematic tension, dramatic reverb swell
```

## 5. 过渡素材：M2 参考

### 标题

`Sparse Pre-Sleep Transition`

### Style 提示词

```text
54 BPM instrumental pre-sleep ambient, sparse soft piano tones with warm pads, stable consonant harmony, limited note density, mostly stepwise motion, low brightness, gentle long reverb, slow predictable changes, no climax, calm transition from wakefulness toward sleep, loop-friendly structure
```

### Negative Tags

```text
vocals, lyrics, drums, percussion, syncopation, busy melody, catchy hook, bright piano, high-register notes, sudden chord change, modulation, crescendo, drop, sharp attack, dramatic orchestration
```

## 6. 极简素材：M3 参考

### 标题

`Minimal Deep Sleep Drone`

### Style 提示词

```text
40 BPM implied pulse but nearly beatless, instrumental deep sleep drone, soft low-register sustained tones, filtered brown texture, extremely low spectral brightness, almost no melody, minimal harmonic movement, very low dynamic range, long smooth reverb tail, no climax, stable and unobtrusive
```

### Negative Tags

```text
vocals, lyrics, melody, rhythm, percussion, drums, pulse accents, bright timbre, high notes, novelty, tension, dissonance, sudden transition, riser, impact, loud transient, dramatic ending
```

## 7. 微觉醒修复素材

建议优先使用本地固定音频，而不是每次重新生成。若必须使用 Suno：

### 标题

`Soft Sleep Recovery Cue`

### Style 提示词

```text
15-second instrumental sleep recovery cue, very soft warm filtered noise texture, no melody, no rhythm, ultra-low dynamic range, familiar and non-intrusive, slow fade in, slow fade out, no attention-grabbing event, consistent with a quiet sleep environment
```

### Negative Tags

```text
vocals, lyrics, melody, rhythm, percussion, transient, chime, bell, high frequency, volume jump, alarm, notification, surprise, bright sound, dramatic effect
```

## 8. 人工审核清单

每个候选音轨进入缓存前后都应检查：

1. 是否确实没有人声、歌词或可辨识的说话声。
2. 开头和结尾是否能通过交叉淡化连接，没有明显咔哒声或断裂。
3. 是否存在鼓点、铃声、撞击、上升音效或突然的高频能量。
4. 峰值是否低于削波阈值，整体响度是否适合长时间聆听。
5. 是否存在突然转调、强烈高潮、明显不协和或过度重复疲劳。
6. 是否适合作为铺底或纹理，而不是把完整歌曲误当作可独立控制的分轨。
7. 是否保存了来源、生成时间、参数、文件 SHA-256 和审核人/审核日期。

推荐在 `music/source/` 保存原始下载文件，在 `music/frozen/` 保存经过固定采样率、声道、响度和裁剪处理的实验素材。未经审核的文件不能自动播放。

## 9. 素材登记模板

```yaml
asset_id: pad_v1_candidate_01
role: pad
source: suno
model: V5_5
generated_at: YYYY-MM-DDThh:mm:ss+08:00
prompt_file: docs/SUNO_AUDIO_PROMPTS.md
prompt_section: "3. 基础铺底：L1 / Pad"
source_url: ""
original_filename: ""
frozen_filename: music/frozen/base_music_v1.wav
sha256: ""
sample_rate_hz: 22050
channels: 2
loudness_target: "待测"
review_status: pending
review_notes: ""
```

提示词属于素材生成记录，不是干预疗效证据。最终实验报告应区分“音频素材来源”和“音乐控制算法贡献”。
