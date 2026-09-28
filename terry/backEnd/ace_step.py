"""Small, bounded proxy for the ACE-Step generation API over a local SSH tunnel."""

import json
import os
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

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


class GenerateRequest(BaseModel):
    style: str
    description: str = Field(default="", max_length=300)
    duration: int = Field(default=30, ge=10, le=120)


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

    def start(self, session, style):
        with self.lock:
            self.session = session
            self.style = style
            self.wanted = None
            self.current = None
            self.cached = {}
            self.last_submit = 0.0
            self.state = {"status": "waiting", "audio_url": None, "music_state": None, "error": None}

    def stop(self):
        with self.lock:
            self.session += 1
            self.style = None
            self.wanted = None
            self.cached = {}
            self.state = {"status": "stopped", "audio_url": None, "music_state": None, "error": None}

    def status(self):
        with self.lock:
            return {"session_id": self.session, **self.state}

    def consider(self, event):
        with self.lock:
            if not self.style or event.get("session_id") != self.session:
                return
            valid = (event.get("status") == "ready" and event.get("playback_mode") == "adaptive"
                     and (event.get("state") or {}).get("status") == "ok"
                     and (event.get("classification_confirmed") is True or
                          (event.get("state") or {}).get("baseline_ready") is True or
                          (event.get("source") == "LIVE" and event.get("probability_origin") == "eeg_spectral_heuristic_unvalidated"
                           and (event.get("channel_repair") or {}).get("valid_channels")))
                     and event.get("source") in ("LIVE", "DEMO"))
            if not valid:
                self.state = {**self.state, "status": "paused", "audio_url": None}
                self.wanted = None
                return
            target = event.get("target_music_state")
            if target not in ("M1", "M2", "M3"):
                return
            self.wanted = target
            if self.state["status"] == "paused":
                self.state["status"] = "waiting"
            if target in self.cached:
                self.current = target
                self.state = {"status": "ready", "audio_url": self.cached[target],
                              "music_state": target, "error": None}
                return
            track = event.get("selected_track") or {}
            if not self.state.get("audio_url") and event.get("track_status") == "available" and track.get("url", "").startswith("/api/music/"):
                self.state = {"status": "ready", "audio_url": track["url"],
                              "music_state": target, "error": None}
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, args=(self.session,), daemon=True, name="ace-automatic")
                self.worker.start()

    def _run(self, session):
        while True:
            with self.lock:
                if session != self.session or not self.style or not self.wanted:
                    return
                target = self.wanted
                if target == self.current:
                    return
                if time.monotonic() - self.last_submit < 60:
                    self.state = {**self.state, "status": "ready" if self.state.get("audio_url") else "cooldown"}
                    return
                self.last_submit = time.monotonic()
                self.state = {**self.state, "status": "ready" if self.state.get("audio_url") else "generating", "error": None}
                style = self.style
            descriptions = {"M1": "awake and settling, gentle grounding, very low energy",
                            "M2": "sleep onset transition, slower and softer, sparse melody",
                            "M3": "stable light sleep, minimal texture, no percussion, very quiet"}
            try:
                task_id = generate(GenerateRequest(style=style, description=descriptions[target], duration=120))["task_id"]
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    with self.lock:
                        if session != self.session or self.state["status"] == "paused":
                            return
                    outcome = generation(task_id)
                    if outcome["status"] == "completed":
                        with self.lock:
                            if session == self.session:
                                self.cached[target] = outcome["audio_url"]
                            if session == self.session and self.wanted == target and self.state["status"] != "paused":
                                self.current = target
                                self.state = {"status": "ready", "audio_url": outcome["audio_url"],
                                              "music_state": target, "error": None}
                                return
                            if session != self.session or self.state["status"] == "paused":
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
                    if session == self.session and self.state["status"] != "paused":
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
    data = post("/release_task", {"prompt": prompt, "lyrics": "[Instrumental]", "audio_duration": request.duration,
                                   "thinking": False, "audio_format": "wav", "batch_size": 1})
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise HTTPException(502, "ACE-Step 未返回有效任务 ID")
    return {"task_id": task_id, "status": "queued"}


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
