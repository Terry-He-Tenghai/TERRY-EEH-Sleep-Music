"""Small, bounded proxy for the ACE-Step generation API over a local SSH tunnel."""

import io
import json
import logging
import math
import os
import re
import threading
import time
import wave
from urllib.parse import parse_qs, urlsplit
from typing import Literal

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/ace", tags=["ace-step"])
STYLES = {
    "ambient": ("氛围", "soft ambient pads, slow evolving textures, warm and spacious"),
    "piano": ("钢琴", "gentle solo piano, sparse notes, warm soft dynamics"),
    "nature": ("自然", "calm nature soundscape, soft rain and wind, subtle ambient music"),
    "strings": ("弦乐", "gentle sustained strings, soft chamber ensemble, slow and soothing"),
    "electronic": ("电子", "minimal downtempo electronic, soft synthesizers, gentle pulse"),
}
TASK_ID = re.compile(r"^[a-zA-Z0-9_-]{8,100}$")
MIN_GENERATION_INTERVAL_S = 15


class GenerateRequest(BaseModel):
    style: str
    description: str = Field(default="", max_length=300)
    duration: int = Field(default=30, ge=10, le=120)
    reference_track_id: str | None = Field(default=None, pattern=r'^user_[a-f0-9]{32}$')


class ExtractRequest(BaseModel):
    reference_track_id: str = Field(pattern=r'^user_[a-f0-9]{32}$')
    track: Literal['vocals', 'backing_vocals', 'drums', 'bass', 'guitar',
                   'keyboard', 'percussion', 'strings', 'synth', 'fx',
                   'brass', 'woodwinds']


class AutomaticMusic:
    """One generation worker per acquisition session; never blocks the EEG thread."""

    def __init__(self):
        self.lock = threading.RLock()
        self.session = 0
        self.style = None
        self.wanted = None
        self.current = None
        self.cached = {}
        self.last_submit = 0.0
        self.state = {"status": "stopped", "audio_url": None, "music_state": None, "error": None}
        self.worker = None
        self.live_valid_until = None
        self.n2_count = 0
        self.sleep_paused = False
        self.last_live_sequence = None
        self.reference_track_id = None
        self.demo_scripted = False

    def _expire_live(self):
        if self.live_valid_until is not None and time.monotonic() > self.live_valid_until:
            self.state = {**self.state, 'status': 'paused', 'audio_url': None}
            if self.worker is None or not self.worker.is_alive():
                self.wanted = None
            self.live_valid_until = None

    def start(self, session, style, reference_track_id=None):
        with self.lock:
            self.session = session
            self.style = style
            self.reference_track_id = reference_track_id
            self.demo_scripted = False
            self.live_valid_until = None
            self.n2_count = 0
            self.sleep_paused = False
            self.last_live_sequence = None
            self.wanted = None
            self.current = None
            self.cached = {}
            self.last_submit = 0.0
            self.state = {"status": "waiting", "audio_url": None, "music_state": None, "error": None}

    def stop(self):
        with self.lock:
            self.session += 1
            self.style = None
            self.reference_track_id = None
            self.demo_scripted = False
            self.live_valid_until = None
            self.n2_count = 0
            self.sleep_paused = False
            self.last_live_sequence = None
            self.wanted = None
            self.cached = {}
            self.state = {"status": "stopped", "audio_url": None, "music_state": None, "error": None}

    def status(self):
        with self.lock:
            self._expire_live()
            return {"session_id": self.session, **self.state, "wanted_music_state": self.wanted}

    def consider(self, event):
        with self.lock:
            if not self.style or event.get("session_id") != self.session:
                return
            model_permission = (event.get('classification_confirmed') is True
                                or (event.get('state') or {}).get('baseline_ready') is True)
            if event.get('source') == 'LIVE':
                probabilities = event.get('probabilities') or {}
                emitted = event.get('emitted_at_s')
                numeric = lambda value: isinstance(value, (float, int)) and math.isfinite(value)
                model_permission = (
                    event.get('inference_mode') == 'waveform_cnn'
                    and event.get('probability_origin') == 'trained_waveform_cnn_experimental'
                    and event.get('classification_confirmed') is True
                    and event.get('signal_quality') == 1.0
                    and numeric(emitted) and 0 <= time.time() - emitted <= 15
                    and all(numeric(probabilities.get(key)) and 0 <= probabilities[key] <= 1 for key in ('W', 'N1', 'N2'))
                    and abs(sum(probabilities.get(key, 0) for key in ('W', 'N1', 'N2')) - 1) <= .001)
            scripted = (event.get('source') == 'DEMO' and event.get('demo_scripted') is True
                        and event.get('inference_mode') == 'demo_scripted'
                        and event.get('probability_origin') == 'scripted_not_model'
                        and event.get('playback_mode') == 'demo_scripted'
                        and (event.get('state') or {}).get('status') == 'demo_scripted')
            valid = (event.get('status') == 'ready'
                     and (scripted or (event.get('playback_mode') == 'adaptive'
                                       and (event.get('state') or {}).get('status') == 'ok'
                                       and model_permission and event.get('source') in ('LIVE', 'DEMO')))
                     and event.get('target_music_state') in ('M1', 'M2', 'M3'))
            if not valid:
                self.n2_count = 0
                self.live_valid_until = None
                self.state = {**self.state, "status": "sleep_paused" if self.sleep_paused else "paused", "audio_url": None}
                if self.worker is None or not self.worker.is_alive():
                    self.wanted = None
                return
            if event.get('source') == 'LIVE':
                sequence = event.get('sequence')
                if sequence is not None and sequence == self.last_live_sequence:
                    return
                self.last_live_sequence = sequence
                stage = (event.get('waveform_model') or {}).get('stage')
                if stage not in ('W', 'N1', 'N2'):
                    stage = max(('W', 'N1', 'N2'), key=lambda key: probabilities[key])
                if stage == 'N2':
                    self.n2_count += 1
                    if self.n2_count >= 2:
                        self.sleep_paused = True
                else:
                    self.n2_count = 0
                    self.sleep_paused = False
                if self.sleep_paused:
                    self.live_valid_until = None
                    self.wanted = None
                    self.state = {**self.state, "status": "sleep_paused", "audio_url": None}
                    return
            self.live_valid_until = (time.monotonic() + max(0, 15 - (time.time() - emitted))
                                     if event.get('source') == 'LIVE' else None)
            target = event.get("target_music_state")
            if target not in ("M1", "M2", "M3"):
                return
            self.wanted = target
            self.demo_scripted = scripted
            if self.state["status"] in ("paused", "sleep_paused"):
                self.state["status"] = "waiting"
            if target in self.cached:
                self.current = target
                self.state = {"status": "ready", "audio_url": self.cached[target],
                              "music_state": target, "error": None}
                return
            # A new target can arrive while an old track is playing. Keep the
            # currently audible track until generation completes and switches.
            if self.state.get('audio_url') and self.state.get('music_state') != target:
                self.state['status'] = 'ready'
            track = event.get("selected_track") or {}
            if not self.state.get("audio_url") and not scripted and event.get("track_status") == "available" and track.get("url", "").startswith("/api/music/"):
                self.state = {"status": "ready", "audio_url": track["url"],
                              "music_state": target, "error": None}
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, args=(self.session,), daemon=True, name="ace-automatic")
                self.worker.start()

    def _run(self, session):
        while True:
            with self.lock:
                self._expire_live()
                if session != self.session or not self.style or not self.wanted:
                    return
                target = self.wanted
                if target == self.current:
                    return
                if self.state['status'] in ('paused', 'sleep_paused'):
                    return
                if time.monotonic() - self.last_submit < MIN_GENERATION_INTERVAL_S:
                    self.state = {**self.state, "status": "ready" if self.state.get("audio_url") else "cooldown"}
                    return
                self.last_submit = time.monotonic()
                self.state = {**self.state, "status": "ready" if self.state.get("audio_url") else "generating", "error": None}
                style = self.style
                reference_track_id = self.reference_track_id
                demo_scripted = self.demo_scripted
            descriptions = {
                "M1": "Awake relaxation: clear, warm piano melody in the foreground, gently pulsing soft pads, steady slow tempo and recognizable phrases.",
                "M2": "Falling asleep: sparse felt-piano notes with long pauses, sustained strings underneath, slower free-flowing pulse and fewer melodic changes.",
                "M3": "Light sleep: nearly beatless sustained ambient drones and airy soft pads; no lead piano, no distinct melody, no percussion, minimal changes and very quiet dynamics.",
            }
            try:
                task_id = generate(GenerateRequest(style=style, description=descriptions[target],
                                                    duration=30 if demo_scripted and not reference_track_id else 120,
                                                    reference_track_id=reference_track_id))["task_id"]
                deadline = time.monotonic() + (1800 if reference_track_id else 300)
                while time.monotonic() < deadline:
                    with self.lock:
                        self._expire_live()
                        if session != self.session or not self.style:
                            return
                    outcome = generation(task_id)
                    if outcome["status"] == "completed":
                        with self.lock:
                            self._expire_live()
                            if session == self.session:
                                self.cached[target] = outcome["audio_url"]
                            if (session == self.session and (self.wanted == target or demo_scripted and not self.state.get('audio_url'))
                                    and self.state["status"] not in ('paused', 'sleep_paused')):
                                self.current = target
                                self.state = {"status": "ready", "audio_url": outcome["audio_url"],
                                              "music_state": target, "error": None}
                                return
                            if session != self.session or self.state["status"] in ('paused', 'sleep_paused'):
                                return
                        break
                    if outcome["status"] == "failed":
                        raise RuntimeError(outcome["error"])
                    time.sleep(3)
                if outcome["status"] == "completed":
                    continue
                raise RuntimeError("ACE-Step 生成超时")
            except (HTTPException, RuntimeError) as exc:
                with self.lock:
                    if session == self.session and self.state["status"] not in ('paused', 'sleep_paused'):
                        self.state = {**self.state, "status": "ready" if self.state.get("audio_url") else "error", "error": str(exc)[:300]}
                return


automatic = AutomaticMusic()


@router.get("/automatic/status")
def automatic_status():
    return automatic.status()


def base_url():
    url = os.getenv("ACE_STEP_URL", "http://127.0.0.1:8001").rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.path or parts.query:
        raise HTTPException(503, "ACE-Step 地址配置无效")
    return url


def headers():
    token = os.getenv("ACE_STEP_API_KEY", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def post(path, payload):
    try:
        response = requests.post(base_url() + path, json=payload, headers=headers(), timeout=(5, 20))
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 200 or body.get("error"):
            raise HTTPException(502, "ACE-Step 拒绝请求")
        return body["data"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "ACE-Step 不可用，请检查服务和 SSH 隧道") from exc


def cover_audio(track_id: str) -> bytes:
    from music_choices import uploaded
    from music_library import _audio_path
    track = uploaded(track_id)
    path = _audio_path(track) if track else None
    if path is None:
        raise HTTPException(422, "上传音频不存在，请重新上传")
    try:
        with wave.open(str(path), 'rb') as source:
            rate = source.getframerate()
            duration = source.getnframes() / rate
            if not 10 <= duration <= 600:
                raise HTTPException(422, 'ACE-Step 音频改写和声部提取支持10–600秒原始音频；不会截短上传文件')
            with io.BytesIO() as output:
                with wave.open(output, 'wb') as target:
                    target.setparams(source.getparams())
                    target.writeframes(source.readframes(source.getnframes()))
                return output.getvalue()
    except (OSError, wave.Error, EOFError) as exc:
        raise HTTPException(422, "上传音频无法读取") from exc


def separate_accompaniment(audio_bytes):
    url = os.getenv('AUDIO_SEPARATOR_URL', 'http://127.0.0.1:8002').rstrip('/')
    try:
        response = requests.post(url + '/separate', data=audio_bytes,
                                 headers={'Content-Type': 'audio/wav'}, timeout=(5, 1800))
        response.raise_for_status()
        with wave.open(io.BytesIO(response.content), 'rb') as audio:
            if audio.getnframes() == 0 or audio.getnframes() / audio.getframerate() > 600.1:
                raise ValueError('Invalid accompaniment duration')
        return response.content
    except (requests.RequestException, ValueError, wave.Error, EOFError) as exc:
        raise HTTPException(502, '伴奏分离失败，请检查分离服务和 8002 SSH 隧道；未提交原始人声音频') from exc


def post_cover(payload, audio_bytes):
    try:
        response = requests.post(base_url() + '/release_task', data={key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in payload.items()},
                                 files={'ctx_audio': ('source.wav', audio_bytes, 'audio/wav')},
                                 headers=headers(), timeout=(120, 1800))
        response.raise_for_status()
        body = response.json()
        if body.get('code') != 200 or body.get('error'):
            raise HTTPException(502, "ACE-Step 拒绝音频改写请求")
        return body['data']
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logging.getLogger(__name__).exception('ACE-Step audio submission failed')
        if isinstance(exc, requests.Timeout):
            detail = 'ACE-Step 音频改写提交超时；任务可能已提交，请勿连续重复提交'
        elif isinstance(exc, requests.ConnectionError):
            detail = 'ACE-Step 连接中断，请重新连接8001 SSH隧道'
        elif isinstance(exc, requests.HTTPError):
            detail = f'ACE-Step 音频改写服务返回HTTP {exc.response.status_code}'
        else:
            detail = 'ACE-Step 音频改写响应格式异常'
        raise HTTPException(502, detail) from exc


def result(task_id):
    if not TASK_ID.fullmatch(task_id):
        raise HTTPException(422, "任务 ID 无效")
    items = post("/query_result", {"task_id_list": [task_id]})
    if not isinstance(items, list) or len(items) != 1 or items[0].get("task_id") != task_id:
        raise HTTPException(502, "ACE-Step 任务响应无效")
    item = items[0]
    try:
        audio = json.loads(item.get("result", "[]"))
        first = audio[0] if isinstance(audio, list) and audio else {}
    except (ValueError, TypeError):
        first = {}
    return item, first


@router.get("/styles")
def styles():
    return [{"id": key, "label": value[0]} for key, value in STYLES.items()]


@router.get("/health")
def health():
    try:
        response = requests.get(base_url() + "/health", headers=headers(), timeout=(3, 5))
        response.raise_for_status()
        data = response.json()
        return {"available": data.get("code") == 200, "models_initialized": data.get("data", {}).get("models_initialized", False)}
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(503, "ACE-Step 不可用，请检查服务和 SSH 隧道") from exc


@router.post("/generations", status_code=202)
def generate(request: GenerateRequest):
    if request.style not in STYLES:
        raise HTTPException(422, "不支持的音乐风格")
    description = request.description.strip()
    prompt = f"Instrumental {STYLES[request.style][1]}; no vocals, no abrupt transients, even volume."
    if description:
        prompt += f" {description}"
    payload = {"prompt": prompt, "lyrics": "[Instrumental]", "audio_duration": request.duration,
               "thinking": False, "audio_format": "wav", "batch_size": 1}
    if request.reference_track_id:
        source_audio = cover_audio(request.reference_track_id)
        with wave.open(io.BytesIO(source_audio), 'rb') as audio:
            payload['audio_duration'] = audio.getnframes() / audio.getframerate()
        payload.update(task_type='cover', audio_cover_strength=0.55, cover_noise_strength=0.35)
        data = post_cover(payload, separate_accompaniment(source_audio))
    else:
        data = post("/release_task", payload)
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise HTTPException(502, "ACE-Step 未返回有效任务 ID")
    return {"task_id": task_id, "status": "queued"}


@router.post('/extractions', status_code=202)
def extract(request: ExtractRequest):
    audio_bytes = cover_audio(request.reference_track_id)
    with wave.open(io.BytesIO(audio_bytes), 'rb') as audio:
        duration = audio.getnframes() / audio.getframerate()
    if duration < 10:
        raise HTTPException(422, '官方声部提取需要至少10秒音频')
    data = post_cover({
        'model': 'acestep-v15-base', 'task_type': 'extract',
        'track_name': request.track,
        'instruction': f'Extract the {request.track.upper()} track from the audio:',
        'audio_duration': duration, 'thinking': False,
        'inference_steps': 32, 'guidance_scale': 7.0,
        'audio_format': 'wav', 'batch_size': 1,
    }, audio_bytes)
    task_id = data.get('task_id') if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise HTTPException(502, 'ACE-Step 未返回有效声部提取任务 ID')
    return {'task_id': task_id, 'status': 'queued', 'track': request.track}


@router.get("/generations/{task_id}")
def generation(task_id: str):
    item, first = result(task_id)
    status = item.get("status")
    state = "completed" if status == 1 and first.get("file") else "failed" if status in (1, 2) else "processing"
    return {"task_id": task_id, "status": state,
            "progress": first.get("progress") if state == "processing" else None,
            "error": str(first.get("error") or item.get("progress_text") or "生成失败，未收到音频文件")[:300] if state == "failed" else None,
            "audio_url": f"/api/ace/generations/{task_id}/audio" if state == "completed" else None}


@router.get("/generations/{task_id}/audio")
def audio(task_id: str, request: Request):
    item, first = result(task_id)
    path = first.get("file")
    if item.get("status") != 1 or not isinstance(path, str) or not path:
        raise HTTPException(404, "生成音频尚不可用")
    parsed = urlsplit(path)
    paths = parse_qs(parsed.query).get("path", [])
    if parsed.path != "/v1/audio" or parsed.scheme or parsed.netloc or len(paths) != 1 or not paths[0].lower().endswith((".wav", ".mp3")):
        raise HTTPException(502, "ACE-Step 返回的音频路径无效")
    range_header = request.headers.get("range")
    if range_header and not re.fullmatch(r"bytes=\d+-\d*", range_header):
        raise HTTPException(416, "不支持的音频范围")
    try:
        upstream = requests.get(base_url() + "/v1/audio", params={"path": paths[0]}, headers=headers(),
                                stream=True, timeout=(5, 30))
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(502, "无法读取 ACE-Step 音频") from exc

    size = int(upstream.headers.get("content-length", "0"))
    start, end = 0, size - 1
    if range_header:
        start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
        start = int(start_text)
        end = min(int(end_text) if end_text else size - 1, size - 1)
        if not size or start >= size or end < start:
            upstream.close()
            raise HTTPException(416, "音频范围超出文件长度", headers={"Content-Range": f"bytes */{size}"})

    def chunks():
        try:
            offset = 0
            for chunk in upstream.iter_content(chunk_size=65536):
                boundary = offset + len(chunk)
                if boundary > start and offset <= end:
                    yield chunk[max(0, start - offset):min(len(chunk), end + 1 - offset)]
                offset = boundary
                if offset > end:
                    break
        finally:
            upstream.close()

    media_type = "audio/wav" if paths[0].lower().endswith(".wav") else "audio/mpeg"
    forwarded = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)} if size else {}
    if range_header:
        forwarded["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(chunks(), status_code=206 if range_header else 200, media_type=media_type,
                             headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **forwarded})
