"""Optional local audio-model adapter; never substitute signal heuristics for listening."""
import json
import math
import os
import shlex
import subprocess

SCORES = ('pleasantness', 'coherence', 'transition_naturalness')


def unavailable(reason, status='unavailable'):
    return dict(status=status, scope='AI estimate; exploratory, not participant ratings',
                model=None, model_version=None, method=None, reason=reason,
                scores={key: None for key in SCORES})


def evaluate_music(path):
    command = os.getenv('MUSIC_AUDIO_EVALUATOR_COMMAND', '').strip()
    if not command:
        return unavailable('No audio-capable evaluator configured (MUSIC_AUDIO_EVALUATOR_COMMAND).')
    try:
        # The adapter receives the actual WAV, not a generation prompt. No shell expansion.
        result = subprocess.run([*shlex.split(command), str(path.resolve())],
                                capture_output=True, text=True, timeout=120, check=True)
        value = json.loads(result.stdout)
        for key in ('model', 'model_version', 'method'):
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError(f'Missing evaluator provenance: {key}')
        if value.get('audio_analyzed') is not True:
            raise ValueError('Evaluator must confirm audio_analyzed=true')
        scores = value.get('scores', {})
        for key in SCORES:
            score = scores.get(key)
            if (isinstance(score, bool) or not isinstance(score, (int, float))
                    or not math.isfinite(score) or not 1 <= score <= 7):
                raise ValueError(f'Invalid 1-7 score: {key}')
        return dict(status='completed', scope='AI estimate; exploratory, not participant ratings',
                    model=value['model'], model_version=value['model_version'], method=value['method'],
                    reason=None, scores={key: scores[key] for key in SCORES},
                    audio_analyzed=True)
    except subprocess.TimeoutExpired:
        return unavailable('Audio evaluator exceeded 120-second timeout.', 'failed')
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError, AttributeError) as exc:
        return unavailable(f'Audio evaluator failed: {type(exc).__name__}', 'failed')
