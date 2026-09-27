"""Deterministic composition tests; no hardware or clinical efficacy claims."""
from types import SimpleNamespace

from eeg_music_modulation import EegMusicModulator
from anphy_sleep.music_engine.midi import generate_midi_plan, quality_report


def state(t=320, wake=.8, n1=.15):
    return SimpleNamespace(window_end_s=t, aasm_state_probabilities={
        'W': wake, 'N1': n1, 'N2': 1-wake-n1}, interpretable_features={})


def test_phrase_development_is_reproducible_and_bounded():
    plans = [generate_midi_plan(phrase_index=i) for i in range(24)]
    assert plans == [generate_midi_plan(phrase_index=i) for i in range(24)]
    assert len({tuple(plan) for plan in plans}) > 8
    assert plans[0] == generate_midi_plan(phrase_index=24)
    for notes in plans:
        report = quality_report(notes)
        assert report.passes and report.large_intervals == 0
        assert len([n for n in notes if n.voice == 'bass']) == 8
        assert all(0 <= n.start_beat < 16 for n in notes)


def test_texture_matches_generated_harmony_each_phrase():
    for index in range(24):
        notes, gains, waveform, metadata = EegMusicModulator().apply(state(index*16), 'M1', 42)
        for bar in range(4):
            pad = {n['midi_note'] for n in notes if n['voice'] == 'pad' and n['start_beat'] == bar*4}
            texture = {n['midi_note'] for n in notes if n['voice'] == 'texture' and n['start_beat'] == bar*4}
            assert texture <= pad
        assert metadata['mapping'] == 'continuous_arrangement_v4'
        assert gains['master'] == .18
        assert all(0 <= value <= 1 for value in gains.values())


def test_m3_retains_continuous_harmony_without_melody_or_bass():
    notes, gains, _, _ = EegMusicModulator().apply(state(wake=.05, n1=.1), 'M3', 42)
    assert {n['voice'] for n in notes} == {'texture'}
    assert gains['melody'] == gains['bass'] == 0
    assert [n['start_beat'] for n in notes] == [0, 4, 8, 12]
    assert all(n['duration_beats'] == 4.5 for n in notes)


def test_density_response_and_smoothing():
    quiet = EegMusicModulator().apply(state(wake=.01, n1=.01), 'M2', 42)
    awake = EegMusicModulator().apply(state(wake=.97, n1=.01), 'M1', 42)
    assert quiet[3]['melody_notes'] < awake[3]['melody_notes']
    mod = EegMusicModulator()
    initial = mod.apply(state(320, .01, .01), 'M2', 42)[3]['control_level']
    next_level = mod.apply(state(323, .97, .01), 'M2', 42)[3]['control_level']
    assert initial < next_level < awake[3]['control_level']
