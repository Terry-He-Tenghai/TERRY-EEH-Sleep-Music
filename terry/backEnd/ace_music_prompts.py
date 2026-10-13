"""Stage-specific arrangements sharing a harmonic frame for gentle transitions."""

import json
from pathlib import Path
from typing import Literal

HarmonyMode = Literal['major', 'natural_minor', 'harmonic_minor', 'melodic_minor']
ChordProgression = Literal['gentle', 'pop', 'descending', 'turnaround']
MusicGenre = Literal['classical', 'jazz', 'folk']
HARMONY_OPTIONS = json.loads((Path(__file__).resolve().parent.parent / 'music_harmony.json').read_text())

STAGE_NAMES = {"M1": "W / awake relaxation", "M2": "N1 / sleep onset", "M3": "N2 / light sleep"}

COMMON_FRAME = (
    "Meter and tempo: 4/4, exactly 60 BPM throughout; keep the quarter-note grid even "
    "when the pulse is only implied. No tempo ramps, meter changes, swing or double-time sections. "
)


def harmonic_frame(harmony_mode='major', chord_progression='gentle'):
    mode = HARMONY_OPTIONS[harmony_mode]
    progression = mode['progressions'][chord_progression]
    return COMMON_FRAME + (
        f"Mode and key: {mode['instruction']} Scale: {mode['scale']}. "
        f"Melody palette: {mode['melody']}; use chord-aware notes, no modulation or sudden register jumps. "
        f"Harmony: repeat {progression['chords']} ({progression['roman']}), "
        "one chord per two bars, an eight-bar cycle. Use close, smooth voice leading, "
        "hold shared chord tones where available, soft root notes and restrained bass. "
        f"Cadence: {progression['cadence']}; soften leading-tone resolution, "
        "no accented dominant build-up, deceptive cadence or dramatic final chord. "
        f"Open over a quiet {mode['tonic']} tonic for the first two bars; finish with a sustained "
        "tonic chord after gently completing the selected cycle, with a smooth tail. "
        "Keep the opening compatible with the previous track's tonic ending. "
    )

REFERENCE_FRAME = (
    "Meter and tempo: retain the reference accompaniment's original meter, beat grid and tempo "
    "across all stages, with no new tempo ramps, swing or double-time feel. "
    "Mode and key: retain its tonic, mode and tuning; do not force C major or 60 BPM on this cover. "
    "Harmony: retain its chord sequence and harmonic rhythm, use shared chord tones and smooth "
    "voice leading, reduce dissonant extensions where possible without reharmonizing the song. "
    "Cadence: soften existing resolutions, avoid new dominant build-ups or emphatic final chords; "
    "use a quiet tonic opening and ending when compatible with the source harmony. "
)

STAGE_ARRANGEMENTS = {
    "M1": (
        "Arrangement for W: relaxed but clearly recognizable music, low energy, not an energetic wake-up track. "
        "Rhythm: mostly quarter and half notes, occasional paired eighth notes, no busy subdivisions. "
        "Groove: lightly imply beats 1 and 3 with soft sustained roots or gentle instrument attacks; "
        "no backbeat, kick/snare pattern, syncopated accents or driving bass. "
        "Melody: an audible four- to six-note motif from the selected melody palette, stepwise or small thirds, "
        "within one octave in the middle register; two-bar question and two-bar answer, "
        "with one bar of breathing space between phrases. Repeat with a small ending variation. "
        "Keep the melody above the accompaniment without sharp attacks. "
        "Voicing: three- or four-note chords, one soft bass root per chord, moderate spacing. "
        "Timbre and waveform envelope: rounded attacks, gentle natural decay, stable sustain "
        "and smooth release; quiet p dynamics, restrained upper harmonics and no clipping. "
        "Maintain an audible foreground motif and a steady background, without a chorus or build-up. "
    ),
    "M2": (
        "Arrangement for N1: noticeably sparser and more floating than W, while keeping the same "
        "underlying beat grid, key and chord cycle. Do not slow the actual tempo. "
        "Rhythm: half and whole notes with two- to four-beat rests, sustained accompaniment. "
        "Groove: half-time perceived motion, one soft onset per two beats at most; "
        "remove beat accents and percussion, no swing or rhythmic pumping. "
        "Melody: a new two- or three-note descending or gently arching motif using shared "
        "selected-mode chord tones, within a fifth; one brief phrase every four bars, "
        "different contour and spacing from W, no dense arpeggios or recognizable hook. "
        "Voicing: two- or three-note chord shells, retain common tones across chord changes, "
        "keep the bass soft and in the same register as W. "
        "Timbre and waveform envelope: softer, darker attacks, longer release and overlap, "
        "reduce bright overtones and transient peaks, pp dynamics with steady perceived loudness. "
        "Make the reduced note density and longer resonance clearly audible without an abrupt "
        "change of instrument family or a sudden loudness drop. "
    ),
    "M3": (
        "Arrangement for N2: a distinct, nearly beatless resting texture, retaining the same "
        "underlying tempo, meter, tonic and harmonic timeline as N1, not a new unrelated drone key. "
        "Rhythm: whole notes tied across bars, no drums or articulated beat; the beat grid is latent. "
        "Groove: no rhythmic bass, pulsing gate, tremolo or amplitude pumping. "
        "Melody: no foreground tune; at most a two-note chord-tone response once per eight-bar "
        "cycle, within a third, integrated into the sustained texture. "
        "Voicing: sustain the tonic/common-tone bed, softly blend each chord's third or sixth "
        "on the existing chord boundaries; preserve the harmonic cycle with minimal movement. "
        "Timbre and waveform envelope: very soft onset, long smooth release, subdued high "
        "harmonics, pp to ppp dynamics, no metallic shimmer, sharp pluck or sudden spectral change. "
        "Compared with N1, make long sustained resonance and the absence of melodic phrases "
        "audible; preserve the selected style's instrument identity even without a lead melody. "
    ),
}

STYLE_ARRANGEMENTS = {
    "ambient": (
        "Style identity: ambient, warm sustained synthesizer pads and unhurried layered textures; "
        "no piano lead, string ensemble, drum kit or nature recording. Render any stage motif "
        "as a soft rounded synth voice. Waveform: sine-dominant fundamental with a low-pass-filtered "
        "triangle layer, no raw sawtooth or square-wave brightness; pad attack 1-3 seconds, "
        "release 3-6 seconds. Gradually reduce moving layers from W to N1 to N2; N2 remains ambient. "
    ),
    "piano": (
        "Style identity: gentle solo piano throughout all stages, felted hammers, intimate warm "
        "middle-register acoustic tone; no synth pads, string backing, drums or nature recording. "
        "Use left-hand chord shells and right-hand stage-specific motifs, no virtuoso runs. "
        "Waveform: natural piano harmonic partials and decaying struck-string resonance, not a "
        "synthetic oscillator; softened hammer transient, light sustain pedal, no mechanical clicks. "
        "W has a clear gentle melody; N1 uses isolated soft notes; N2 uses very widely spaced "
        "piano chord resonance and pedal tails, not a replacement synth drone. "
    ),
    "nature": (
        "Style identity: a continuous quiet nature soundscape with a subordinate warm tonal bed. "
        "Nature sounds: smooth light rain and distant soft wind, the same environment across stages, "
        "well below the musical foreground in W, more exposed as notes thin in N1 and N2. "
        "No thunder, close splashes, bird calls, insects, voices, footsteps or abrupt gusts. "
        "Waveform: softly filtered broadband rain noise with no sharp high-frequency bursts, "
        "plus a low-level sine/triangle tonal bed following the stage harmony and motifs. "
        "Keep the rain level stable; do not raise environmental noise to create the stage contrast. "
    ),
    "strings": (
        "Style identity: soft chamber strings throughout, muted violin/viola and gentle cello, "
        "legato bowing, no piano, synthesizer lead, percussion or nature recording. "
        "W has a restrained viola melody; N1 has short sparse legato responses; "
        "N2 sustains quiet string chord tones without a solo line. "
        "Waveform: natural bowed-string harmonic spectrum, softened upper partials, "
        "slow bow onset and smooth release; minimal vibrato, no tremolo, pizzicato, "
        "scraping bow noise, dramatic orchestral swell or abrupt bow change. "
    ),
    "electronic": (
        "Style identity: minimal downtempo electronic, rounded soft synth lead, restrained "
        "synth bass and smooth electronic pads, not piano or orchestral music. "
        "W has a quiet tonal quarter/half-note pulse, N1 has sparse half-time tonal motion, "
        "N2 has sustained synth tones with the pulse removed but the same latent tempo. "
        "Waveform: sine bass and low-pass-filtered triangle lead/pads, slow envelopes, "
        "restrained harmonics; no harsh saw/square waves, resonant filter sweeps, "
        "kick/snare/hi-hats, sidechain pumping, distortion, drops or nature recording. "
    ),
}


GENRE_ARRANGEMENTS = {
    'classical': (
        'Genre identity: restrained classical instrumental music; balanced question-and-answer '
        'phrases, lyrical legato and modest motivic variation, smoothly connected chord voices. '
        'No virtuosic runs, dramatic orchestral swells or emphatic concert ending. '
    ),
    'jazz': (
        'Genre identity: quiet jazz ballad; relaxed lyrical phrasing and warm, softly voiced '
        'chord shells with gentle inner-voice movement. Use only chord-compatible extensions '
        'within the chosen scale; no forced ii-V reharmonization, chromatic substitutions, '
        'swing, walking bass, drum groove or accented syncopation. '
    ),
    'folk': (
        'Genre identity: gentle instrumental folk; simple songlike stepwise motifs, intimate '
        'phrasing and softly repeating accompaniment with breathing space. Translate the '
        'folk character into the selected instruments; do not mandate guitar, vocals, '
        'percussive strumming, stomps or claps. '
    ),
}


def genre_prompt(genre):
    if genre is None:
        return ''
    return GENRE_ARRANGEMENTS[genre] + (
        'Genre is an arrangement influence, not an instrument replacement. Preserve the selected '
        'instrument family and waveform character, tempo, meter, tonic, mode, chord roots, '
        'harmonic rhythm and cadence; for reference covers preserve the source musical frame. '
        'Stage-specific note density and dynamics take priority: recognizable motifs in W, '
        'sparse responses in N1, sustained resonance without a foreground tune in N2. '
        'Keep this genre identity consistent across stages, with no new nature sounds unless '
        'the nature style is selected. No vocals, abrupt transients or energetic builds. '
    )


def stage_prompt(style, music_state, *, reference=False, previous_music_state=None,
                 harmony_mode='major', chord_progression='gentle'):
    frame = REFERENCE_FRAME if reference else harmonic_frame(harmony_mode, chord_progression)
    transition = (
        "Transition compatibility: treat all three stages as different arrangements in one musical family. "
        "Keep the same tonal center, instrument family, bass register and harmony; introduce the new "
        "stage's motif and note density gently over the opening two bars. Make the new arrangement "
        "clearly different through phrasing, articulation and sustained-versus-articulated texture, "
        "not by a key jump, tempo change, new sound environment or loudness jump. "
        "Mix: steady low perceived loudness across stages, no sudden peaks, hard panning, "
        "stereo phase tricks or strong sub-bass; smooth reverb tails and loop-compatible edges. "
        "No vocals, speech, binaural-beat claims or asserted brainwave entrainment. "
    )
    if previous_music_state in STAGE_NAMES and previous_music_state != music_state:
        transition += f"This track follows {STAGE_NAMES[previous_music_state]}; preserve its musical frame. "
    return (
        f"Target stage: {STAGE_NAMES[music_state]}. "
        + frame + STAGE_ARRANGEMENTS[music_state] + STYLE_ARRANGEMENTS[style] + transition
    )
