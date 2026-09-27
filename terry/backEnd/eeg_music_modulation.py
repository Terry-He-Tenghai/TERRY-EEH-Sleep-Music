"""Experimental Web-only continuous EEG-to-music mapping, not a sleep metric."""
from __future__ import annotations

import math


class EegMusicModulator:
    def __init__(self):
        self.level = None
        self.time = None

    def apply(self, state, music_state: str, seed: int):
        from dataclasses import asdict
        from anphy_sleep.music_engine.midi import generate_midi_plan

        p = state.aasm_state_probabilities
        # Probabilities and baseline-normalized features have already passed
        # the Web adapter's quality/baseline checks. This score is a control
        # variable, never a calibrated arousal or clinical measurement.
        probability_drive = p['W'] + .45 * p['N1']
        features = state.interpretable_features
        beta = features.get('frontal_beta_z')
        theta = features.get('central_theta_z')
        feature_drive = None
        if beta is not None and theta is not None and math.isfinite(beta) and math.isfinite(theta):
            feature_drive = .5 + .5 * math.tanh((beta - theta) / 3)
        target = probability_drive if feature_drive is None else .8 * probability_drive + .2 * feature_drive
        t = float(state.window_end_s)
        if self.level is None or t < self.time:
            self.level = target
        else:
            alpha = 1 - math.exp(-max(0, t - self.time) / 20)
            self.level += alpha * (target - self.level)
        self.time = t
        level = max(0., min(1., self.level))
        # Increase contrast around the midpoint without fabricating variation
        # when EEG input is unchanged; retain the existing 20-second smoothing.
        level = .5 + .5 * math.tanh(2.4 * (level - .5)) / math.tanh(1.2)
        # Five coarse density bands avoid reselecting notes on tiny changes.
        density = min(4, int(level * 5))
        strides = [4, 3, 2, 1, 1]
        stride = strides[density]
        phrase_index = max(0, int(t // 16))
        notes = [asdict(note) for note in generate_midi_plan(
            music_state, seed=seed, variation='complete', phrase_index=phrase_index
        )]
        melody = [n for n in notes if n['voice'] == 'melody'][::stride]
        duration = .3 + 3.7 * (1 - level)
        # Octave-only changes preserve the pitch classes of the existing motif.
        octave_shift = -12 if density <= 1 else 0
        for index, note in enumerate(melody):
            next_start = melody[index + 1]['start_beat'] if index + 1 < len(melody) else 16
            note['duration_beats'] = min(duration, max(.1, next_start - note['start_beat'] - .05), 16 - note['start_beat'])
            accent = 6 if note['start_beat'] % 2 == 0 else 0
            note['velocity'] = round(40 + 32 * level) + accent
            note['midi_note'] += octave_shift
        notes = [n for n in notes if n['voice'] != 'melody'] + melody
        # A sustained, audible synthesized layer, unlike symbolic pad notes
        # (the browser deliberately does not synthesize pad).
        chords = ((60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62))
        harmony = []
        for bar in range(4):
            chord = chords[(bar + phrase_index) % len(chords)]
            pitches = (chord[0],) if music_state == 'M3' else chord[:2]
            for pitch in pitches:
                harmony.append({'start_beat': float(bar * 4), 'duration_beats': 4.5,
                                'midi_note': pitch, 'velocity': 30 if music_state == 'M3' else round(38 + 14 * level),
                                'voice': 'texture', 'phrase': bar // 2})
        notes += harmony
        # M3 retains a quiet sustained layer, but still omits melody and bass.
        gains = {'master': .18, 'pad': .34 - .12 * level,
                 'melody': 0 if music_state == 'M3' else .34 + .42 * level,
                 'bass': 0 if music_state == 'M3' else .18 + .18 * level,
                 'texture': .16 if music_state == 'M3' else .28 + .18 * level}
        waveform = {'master_gain': .67, 'brightness': .08 + .67 * level,
                    'reverb_send': .35 - .25 * level, 'stereo_width': .25 + .5 * level}
        return notes, gains, waveform, {
            'experimental': True, 'mapping': 'continuous_arrangement_v4',
            'arrangement_phrase': phrase_index, 'development_cycle_seconds': 384,
            'variation_source': 'deterministic_composition_clock_not_eeg',
            'harmony_notes': len(harmony), 'harmony_gain': gains['texture'], 'harmony_duration_beats': 4.5,
            'octave_shift': octave_shift, 'oscillator': 'triangle',
            'probability_drive': probability_drive, 'feature_drive': feature_drive,
            'control_level': level, 'smoothing_seconds': 20,
            'density_band': density, 'melody_notes': len(melody),
            'target_duration_beats': duration, 'brightness': waveform['brightness'],
            'master_gain': gains['master'], 'melody_gain': gains['melody'], 'pad_gain': gains['pad'],
        }
