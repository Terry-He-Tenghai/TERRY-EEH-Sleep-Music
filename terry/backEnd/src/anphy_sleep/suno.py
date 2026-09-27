from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import requests

from .music_policy import MUSIC_PIPELINES, MusicMode


class SunoApiError(RuntimeError):
    pass


SUCCESS_STATUSES = {"SUCCESS"}
FAILED_STATUSES = {
    "CREATE_TASK_FAILED",
    "GENERATE_AUDIO_FAILED",
    "CALLBACK_EXCEPTION",
    "SENSITIVE_WORD_ERROR",
}


@dataclass(frozen=True)
class SunoGenerationRequest:
    style: str
    title: str
    callback_url: str
    duration_seconds: int | None = None
    negative_tags: str | None = None
    model: str = "V5_5"
    style_weight: float = 0.8
    weirdness_constraint: float = 0.2

    def validate(self) -> None:
        if self.model not in {
            "V4",
            "V4_5",
            "V4_5PLUS",
            "V4_5ALL",
            "V5",
            "V5_5",
        }:
            raise ValueError(f"Unsupported Suno model: {self.model}")
        if not self.style or not self.title:
            raise ValueError("Instrumental custom mode requires style and title")
        style_limit = 200 if self.model == "V4" else 1_000
        title_limit = 80 if self.model in {"V4", "V4_5ALL"} else 100
        if len(self.style) > style_limit:
            raise ValueError(f"style exceeds {style_limit} characters")
        if len(self.title) > title_limit:
            raise ValueError(f"title exceeds {title_limit} characters")
        if not self.callback_url.startswith(("https://", "http://")):
            raise ValueError("callback_url must be an HTTP(S) URL")
        if self.duration_seconds is not None:
            if self.model != "V5_5":
                raise ValueError("duration is only supported by V5_5")
            if not 10 <= self.duration_seconds <= 360:
                raise ValueError("duration must be between 10 and 360 seconds")
        for name, value in [
            ("style_weight", self.style_weight),
            ("weirdness_constraint", self.weirdness_constraint),
        ]:
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    def to_payload(self) -> dict[str, object]:
        self.validate()
        payload: dict[str, object] = {
            "customMode": True,
            "instrumental": True,
            "model": self.model,
            "callBackUrl": self.callback_url,
            "style": self.style,
            "title": self.title,
            "styleWeight": self.style_weight,
            "weirdnessConstraint": self.weirdness_constraint,
        }
        if self.duration_seconds is not None:
            payload["duration"] = self.duration_seconds
        if self.negative_tags:
            payload["negativeTags"] = self.negative_tags
        return payload


class SunoClient:
    """Minimal authenticated client for the documented generation endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.sunoapi.org",
        timeout_seconds: float = 30.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("SUNO_API_KEY")
        if not self.api_key:
            raise ValueError("Set SUNO_API_KEY; never store it in config or source")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _parse_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") != 200:
            raise SunoApiError(
                f"Suno API error {payload.get('code')}: {payload.get('msg')}"
            )
        return payload

    def _send(self, request: Request) -> dict[str, Any]:
        opener = self.opener or urlopen
        try:
            with opener(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SunoApiError(
                f"Suno HTTP {error.code}: {detail}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise SunoApiError(f"Suno request failed: {error}") from error
        return self._parse_payload(payload)

    def _request(
        self,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.opener is not None:
            data = (
                json.dumps(json_body).encode("utf-8")
                if json_body is not None
                else None
            )
            request = Request(
                url,
                data=data,
                method=method,
                headers=self._headers(json_body=json_body is not None),
            )
            return self._send(request)
        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(json_body=json_body is not None),
                json=json_body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as error:
            detail = error.response.text if error.response is not None else str(error)
            status = error.response.status_code if error.response is not None else "?"
            raise SunoApiError(f"Suno HTTP {status}: {detail}") from error
        except requests.RequestException as error:
            raise SunoApiError(f"Suno request failed: {error}") from error
        return self._parse_payload(payload)

    def generate(self, generation: SunoGenerationRequest) -> str:
        payload = self._request(
            "POST",
            f"{self.base_url}/api/v1/generate",
            json_body=generation.to_payload(),
        )
        task_id = payload.get("data", {}).get("taskId")
        if not task_id:
            raise SunoApiError("Suno response did not include data.taskId")
        return str(task_id)

    def get_record_info(self, task_id: str) -> dict[str, Any]:
        query = urlencode({"taskId": task_id})
        return self._request(
            "GET",
            f"{self.base_url}/api/v1/generate/record-info?{query}",
        )

    def wait_for_completion(
        self,
        task_id: str,
        interval_seconds: float = 30.0,
        timeout_seconds: float = 360.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() <= deadline:
            last = self.get_record_info(task_id)
            status = str((last.get("data") or {}).get("status") or "")
            if status in FAILED_STATUSES:
                message = (last.get("data") or {}).get("errorMessage") or status
                raise SunoApiError(f"Suno task {task_id} failed: {message}")
            if status in SUCCESS_STATUSES:
                return last
            sleeper(interval_seconds)
        raise SunoApiError(
            f"Suno task {task_id} timed out after {timeout_seconds:.0f}s"
        )


@dataclass
class CachedTrack:
    url: str
    title: str | None = None
    track_id: str | None = None
    approved: bool = False


class TrackRepository:
    """Thread-safe persistent mapping from control modes to generated tracks."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.data: dict[str, Any] = {
            "schema_version": "1.0",
            "tasks": {},
            "modes": {},
            "callback_events": [],
        }
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)

    def _save(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def register_task(self, mode: MusicMode, task_id: str) -> None:
        with self.lock:
            self.data["tasks"][task_id] = {
                "mode": mode.value,
                "status": "submitted",
            }
            mode_data = self.data["modes"].setdefault(
                mode.value,
                {"tasks": [], "tracks": []},
            )
            if task_id not in mode_data["tasks"]:
                mode_data["tasks"].append(task_id)
            self._save()

    def mark_task_failed(self, task_id: str, error: str) -> None:
        with self.lock:
            task = self.data["tasks"].setdefault(task_id, {})
            task.update({"status": "failed", "error": error})
            self._save()

    def record_generation_error(self, mode: MusicMode, error: str) -> None:
        with self.lock:
            self.data.setdefault("generation_errors", []).append(
                {"mode": mode.value, "error": error}
            )
            self._save()

    @staticmethod
    def _first_value(payload: object, names: set[str]) -> str | None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key.lower() in names and isinstance(value, (str, int)):
                    return str(value)
            for value in payload.values():
                found = TrackRepository._first_value(value, names)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = TrackRepository._first_value(value, names)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _extract_tracks(payload: object) -> list[CachedTrack]:
        tracks: list[CachedTrack] = []
        audio_keys = {
            "audiourl",
            "audio_url",
            "streamaudiourl",
            "stream_audio_url",
            "sourceaudiourl",
            "source_audio_url",
            "sourcestreamaudiourl",
            "source_stream_audio_url",
            "stream_url",
        }
        if isinstance(payload, dict):
            url = next(
                (
                    value
                    for key, value in payload.items()
                    if key.lower() in audio_keys
                    and isinstance(value, str)
                    and value.startswith(("https://", "http://"))
                ),
                None,
            )
            if url is not None:
                tracks.append(
                    CachedTrack(
                        url=url,
                        title=TrackRepository._first_value(
                            payload,
                            {"title"},
                        ),
                        track_id=TrackRepository._first_value(
                            payload,
                            {"id", "audioid", "audio_id"},
                        ),
                    )
                )
            for value in payload.values():
                tracks.extend(TrackRepository._extract_tracks(value))
        elif isinstance(payload, list):
            for value in payload:
                tracks.extend(TrackRepository._extract_tracks(value))
        unique = {}
        for track in tracks:
            unique[track.url] = track
        return list(unique.values())

    def ingest_callback(self, payload: dict[str, Any]) -> int:
        task_id = self._first_value(payload, {"taskid", "task_id"})
        if task_id is None:
            raise ValueError("Callback payload does not contain a taskId")
        with self.lock:
            task = self.data["tasks"].get(task_id)
            if task is None:
                raise ValueError(f"Unknown Suno taskId: {task_id}")
            callback_type = self._first_value(
                payload,
                {"callbacktype", "callback_type", "stage", "type"},
            )
            task["status"] = callback_type or "callback_received"
            tracks = self._extract_tracks(payload)
            mode = str(task["mode"])
            mode_data = self.data["modes"].setdefault(
                mode,
                {"tasks": [task_id], "tracks": []},
            )
            existing_urls = {
                item["url"] for item in mode_data.get("tracks", [])
            }
            added = 0
            for track in tracks:
                if track.url not in existing_urls:
                    mode_data["tracks"].append(asdict(track))
                    existing_urls.add(track.url)
                    added += 1
            self.data["callback_events"].append(payload)
            self.data["callback_events"] = self.data["callback_events"][-100:]
            self._save()
            return added

    def approve(self, mode: MusicMode, index: int) -> CachedTrack:
        with self.lock:
            tracks = self.data["modes"][mode.value]["tracks"]
            tracks[index]["approved"] = True
            self._save()
            return CachedTrack(**tracks[index])

    def select(
        self,
        mode: MusicMode,
        approved_only: bool = True,
    ) -> CachedTrack | None:
        with self.lock:
            mode_data = self.data["modes"].get(mode.value, {})
            for item in mode_data.get("tracks", []):
                track = CachedTrack(**item)
                if track.approved or not approved_only:
                    return track
        return None

    def task_exists(self, mode: MusicMode) -> bool:
        with self.lock:
            return bool(
                self.data["modes"].get(mode.value, {}).get("tasks", [])
            )


class SunoCallbackServer:
    """Small callback receiver; use a secret path because signatures are unspecified."""

    def __init__(
        self,
        repository: TrackRepository,
        host: str,
        port: int,
        secret: str,
    ) -> None:
        if not secret:
            raise ValueError("Callback secret cannot be empty")
        expected_path = f"/suno/callback/{secret}"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != expected_path:
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 1_000_000:
                        self.send_error(413, "invalid callback body size")
                        return
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    added = repository.ingest_callback(payload)
                    response = json.dumps(
                        {"ok": True, "tracks_added": added}
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                except (ValueError, json.JSONDecodeError) as error:
                    self.send_error(400, str(error))

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer((host, port), Handler)

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


def generation_request_for_mode(
    mode: MusicMode,
    callback_url: str,
    model: str = "V5_5",
) -> SunoGenerationRequest:
    pipeline = MUSIC_PIPELINES[mode]
    if not pipeline.generate_with_suno:
        raise ValueError(f"{mode.value} intentionally does not use Suno")
    return SunoGenerationRequest(
        style=pipeline.style,
        title=pipeline.title,
        callback_url=callback_url,
        duration_seconds=pipeline.duration_seconds,
        negative_tags=pipeline.negative_tags,
        model=model,
    )
