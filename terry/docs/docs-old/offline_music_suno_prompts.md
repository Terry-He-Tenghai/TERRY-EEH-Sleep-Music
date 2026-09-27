# Suno 离线素材英文提示词与中文用途

## 使用前提

这些提示词用于操作者在 Suno 平台中人工探索素材，再下载、审核后放入本地库；网页没有调用 Suno，没有上传脑电或音频。选择平台提供的 Instrumental（纯器乐）选项；若存在 Lyrics 输入框，保持为空，不把这份说明当成歌词。不同版本字段、时长和功能会变化，应以实际界面为准。

提示词只是生成目标，不能保证无语言、无突变、确切节奏、时长、声学参数或疗效。听起来像合唱的 pad 也可能含人声，必须逐秒试听。避免指定在世音乐人、歌曲模仿或声纹复刻。下载权限不等于再分发权限：逐条核对当前套餐、生成时条款、来源样本、研究展示/公开演示/商业用途，保存证据后才批准。

Suno 的分轨功能、可用性与质量取决于平台版本/套餐，**不能保证得到独立、干净、同步、可无缝叠加的分轨**。以下提示词产物默认是一条混合音频，不是分轨工程；后处理声源分离也可能引入伪影。后续需要分轨时，优先自行合成或委托创作，独立导出、统一起点/采样率/长度，重新听审。

## 通用约束（可附加到每条 Style / Description）

English prompt:

Create an original instrumental soundscape for a quiet, low-volume listening session. No vocals, no speech, no whispers, no humming, no chanting, no choir, no spoken numbers, and no language-like fragments. Use soft attacks, long releases, restrained high frequencies, a stable tonal center, and very slow continuous changes. Keep the perceived loudness steady. No sudden entrances or exits, no dramatic crescendos, no drops, no builds, no risers, no stingers, no alarms, no sharp transients, no distortion, and no abrupt ending. Avoid recognizable melodies and attention-grabbing hooks. Begin gently and finish with a long natural fade. This is background music, not a medical treatment, hypnosis track, or brainwave entrainment claim. Deliver a complete stereo mix, not a promise of isolated stems.

中文用途：统一约束所有候选素材，减少注意力捕获与惊扰；并不保证实际生成遵从。出现人声、突变或不舒适段落应重新生成/编辑，未复审前不能入库。

## A. Warm sustained pad — 柔和持续音色基底

English prompt:

Original minimalist ambient instrumental, warm rounded analog-style pads and a soft low-mid harmonic bed. A stable D-centered consonant harmony, no dramatic chord changes, no prominent lead melody. Let one or two sustained layers evolve almost imperceptibly over many seconds with gentle filter movement and long overlapping releases. Free-time and beatless: no drums, no ticking pulse, no rhythmic gating, no arpeggio, and no pulsing bass. Keep the low end light and controlled, never sub-bass heavy; keep the upper register smooth rather than shimmering or piercing. A close, calm stereo image with diffuse reverb, no sudden panning. Aim for several minutes of consistent texture if the interface supports it, with a very gradual entrance and a long quiet tail. Entirely instrumental, no voice-like synthesizer, no choir, no words. No climactic section, no loudness jump, no cinematic impact, no abrupt finish.

中文用途：作为最简整曲候选，在手动模式评估个体对持续和声音色的接受程度。D 调只是创作一致性要求，不意味着特定调性有助眠疗效；实际音高需检查。文件 ID 建议 `warm-pad-01`。

## B. Sparse felt piano — 稀疏柔音钢琴

English prompt:

Original very sparse felt-piano ambient instrumental over a barely audible warm sustained pad. Use isolated soft notes and simple open consonant intervals, with long rests and natural decays. Suggest a slow relaxed pace around 45 to 55 BPM only as a compositional reference; avoid a strict audible metronome or repetitive driving rhythm. Stay in a narrow middle register, with no bright high notes, no booming low octaves, no fast runs, no virtuoso phrases, and no memorable song hook. Keep piano attacks exceptionally soft, with no pedal clicks or mechanical noises. Harmonic movement should be rare, gradual, and emotionally neutral rather than sad, suspenseful, or triumphant. No drums, no bass drops, no strings swelling into a climax. No singing, speech, whispers, humming, or choir. Gentle opening, consistent low-intensity arrangement throughout, long decaying ending without a final accented chord.

中文用途：与持续音色比较“少量离散音符”的舒适度与注意力影响，不用于按 EEG 频率强制节拍同步。生成速度不一定准确，不写入未经测量的 BPM 数值。文件 ID 建议 `felt-piano-01`。

## C. Soft air texture — 平稳空气质感

English prompt:

Create an original, very gentle ambient texture made from soft filtered air-like noise and a faint warm tonal bed. The air should sound smooth and continuous, not hissy, crackling, windy, or stormy. No realistic environmental events: no birds, insects, footsteps, doors, traffic, thunder, sudden water splashes, or human presence. Avoid prominent high-frequency fizz and low-frequency rumble. Use extremely slow timbral evolution without noticeable cycles, pumping, tremolo, or periodic amplitude modulation. No melody, no percussion, no beat, no dramatic harmony, no stereo motion that draws attention. Keep the texture even and unobtrusive with a soft onset and a long fade to silence. No vocals or language-like sounds of any kind. Do not claim calibrated pink noise, a therapeutic frequency, or brainwave synchronization; this is simply an artistic noise-like stereo ambience.

中文用途：作为弱旋律、平稳纹理候选。AI 生成的噪声不等于经过频谱校准的粉红噪声；若研究需要可复现噪声，应使用离线程序合成并测量。文件 ID 建议 `soft-air-01`。

## D. Gentle acoustic resonance — 柔和拨弦余音

English prompt:

Original quiet acoustic ambient instrumental with a few very softly plucked nylon-string tones and long rounded resonances, supported by a restrained warm pad. Remove the impression of sharp picking, string squeaks, fret noise, and finger taps. Use sparse sustained consonant intervals with plenty of space, no strumming pattern, no rhythmic groove, no fast ornamentation, no lead melody, and no recognizable tune. Keep the emotional tone neutral and settled. Avoid brittle treble, heavy bass, metallic bells, chimes, gongs, and sudden resonant peaks. The arrangement should remain almost unchanged, with only tiny gradual variations in color. No percussion or dramatic transition; no vocals, whispers, humming, speech, choir, or breath sounds. Start softly, maintain a stable restrained perceived level, and end in a slow natural fade rather than an accented final note.

中文用途：为不喜欢电子音色的用户提供人工试听备选；拨弦瞬态难以仅靠提示词去除，尤其需要检查起音与共振峰。文件 ID 建议 `acoustic-soft-01`。

## E. Consistent harmonic variant — 同类低密度对照

English prompt:

Create an original alternative to a warm beatless ambient pad, using the same restrained sound palette throughout: one soft sustained midrange layer and one barely audible diffuse background layer. Keep a stable consonant tonal center and very low event density. Do not add new instruments halfway through. No melody, arpeggios, drums, bass pulse, vocal texture, or rhythmic modulation. Maintain a consistent tonal brightness and perceived loudness, with very gradual changes only. Make the entire piece suitable for quiet background listening, with a gentle entrance and a long release. No sudden transitions, no climax, no silence followed by a loud return, no hard cut at the end. Deliver one stereo mix. Do not imitate a named artist or existing recording, and do not promise compatibility as a synchronized stem with another generation.

中文用途：准备同类多版本素材，人工挑选一致性较高的版本；分别生成的音轨不保证和声、相位、时长或节拍一致，不能未经检查叠加。文件 ID 建议 `warm-pad-02`。

## 审核与后处理记录

每条保留：提示词、平台/版本、日期、生成 ID、实际时长、导出格式、原始文件、后处理版本、授权凭证、审核人、全曲听审结论。技术检查包括削波/异常峰值、可闻语言、静音后骤响、淡入淡出、持续低频、刺耳高频、左右声道异常，以及相邻曲目响度差异。音频响度和峰值应使用工具实测，不把提示词里的形容词当测量结果。

需要循环时在编辑器中选择平稳区域、制作并听审交叉淡化接缝；提示词不能保证采样级无缝循环。当前网页不自动循环、不自动切曲。人工后处理并不自动获得版权许可，最终导出版本仍应重新审查。

通过审核后，按 `offline_music_library.md` 登记 `manifest.json`。后续闭环优先验证信号质量、时间同步、个体基线、控制平滑和人工退出，再开展有适当伦理与对照设计的效果研究。现阶段只交付素材准备流程与手动播放器。
