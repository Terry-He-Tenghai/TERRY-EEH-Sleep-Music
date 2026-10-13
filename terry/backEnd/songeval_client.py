"""SongEval's native five-dimensional 1-5 scores, separate from legacy rubrics."""
import json
import math
import os
from urllib.request import Request, urlopen

KEYS = ('coherence', 'musicality', 'memorability', 'structure_clarity', 'vocal_naturalness')


def empty(status='unavailable', reason='SongEval has not been requested'):
    return {'status': status, 'reason': reason, 'model': 'SongEval', 'score_range': [1, 5],
            'scores': {key: None for key in KEYS}}


def evaluate(path):
    url = os.environ.get('SONGEVAL_API_URL', 'http://127.0.0.1:8002').rstrip('/')
    try:
        request = Request(url + '/evaluate', data=path.read_bytes(), method='POST',
                          headers={'Content-Type': 'audio/wav'})
        with urlopen(request, timeout=1800) as response:
            value = json.load(response)
        if value.get('status') != 'completed' or value.get('audio_analyzed') is not True or value.get('model') != 'SongEval' or value.get('score_range') != [1, 5]:
            raise ValueError('Unexpected SongEval schema')
        seconds = value.get('analyzed_audio_seconds')
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Missing analyzed audio duration')
        for key in ('model_version', 'method', 'coverage_scope'):
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError('Missing SongEval provenance')
        for key in KEYS:
            score = (value.get('scores') or {}).get(key)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 1 <= score <= 5:
                raise ValueError('Invalid native SongEval score')
        value.update(status='completed', reason=None)
        return value
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return empty('failed', f'SongEval request failed: {type(exc).__name__}: {exc}')
