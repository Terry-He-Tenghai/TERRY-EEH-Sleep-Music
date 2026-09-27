"""Read-only, local music catalog. Include ``router`` in the main FastAPI app.

The manifest is an operator-managed trust boundary, never an upload target.
No network calls, generation, directory scans, or EEG-driven playback occur here.
"""
from collections import Counter
from datetime import date
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MUSIC_DIR = Path(__file__).resolve().parent / "music"
AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".flac": "audio/flac"}
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
router = APIRouter(prefix="/api/music", tags=["music"])


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewed_by: str = Field(default="", max_length=200)
    reviewed_at: date | None = None
    notes: str = Field(default="", max_length=2000)
    copyright_checked: bool = False
    audio_checked: bool = False


class Track(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    file: str = Field(min_length=1, max_length=500)
    styles: list[Literal['ambient', 'piano', 'nature', 'strings', 'electronic']] = Field(default_factory=list, max_length=5)
    purpose: str = Field(default="", max_length=2000)
    source: str = Field(default="", max_length=500)
    license: str = Field(default="", max_length=2000)
    review: Review = Field(default_factory=Review)

    def is_approved(self) -> bool:
        return bool(self.review.status == "approved" and self.review.reviewed_by.strip()
                    and self.review.reviewed_at and self.review.copyright_checked
                    and self.review.audio_checked and self.license.strip())


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    tracks: list[Track] = Field(max_length=1000)


def _local_file(name: str) -> Path | None:
    """Reject traversal, absolute paths and all symlinks, including the root."""
    try:
        relative = Path(name)
        if (not name or "\\" in name or "\x00" in name or relative.is_absolute()
                or ".." in relative.parts or ":" in name or MUSIC_DIR.is_symlink()):
            return None
        root = MUSIC_DIR.resolve()
        current = MUSIC_DIR
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return None
        resolved = current.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        return resolved
    except (OSError, ValueError, RuntimeError):
        return None


def _read_manifest() -> tuple[list[Track], str]:
    path = _local_file("manifest.json")
    if path is None:
        return [], "missing"
    try:
        if path.stat().st_size > 1_000_000:
            return [], "invalid"
        manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"), strict=True)
        counts = Counter(track.id for track in manifest.tracks)
        if any(count > 1 for count in counts.values()):
            return [], "invalid"
        return manifest.tracks, "ready"
    except (OSError, UnicodeError, ValidationError, ValueError):
        return [], "invalid"


def _audio_path(track: Track) -> Path | None:
    # Catalog playback does not require review; retain local file safety checks.
    path = _local_file(track.file)
    if path is None or path.suffix.lower() not in AUDIO_TYPES:
        return None
    return path


@router.get("")
def list_music(response: Response):
    response.headers["Cache-Control"] = "no-store"
    tracks, status = _read_manifest()
    public = []
    for track in tracks:
        item = track.model_dump(mode="json", exclude={"file"})
        item["available"] = _audio_path(track) is not None
        item["audio_url"] = f"/api/music/{track.id}/audio" if item["available"] else None
        public.append(item)
    return {"status": status, "tracks": public, "control_mode": "manual",
            "message": "本地音乐仅手动播放；不保证助眠或治疗效果。"}


@router.get("/{track_id}/audio")
def get_music_audio(track_id: str):
    # The client supplies only an opaque ID, never a filename.
    if not re.fullmatch(ID_PATTERN, track_id):
        raise HTTPException(404, "音频不可用")
    tracks, _ = _read_manifest()
    track = next((item for item in tracks if item.id == track_id), None)
    if track is None:
        from music_choices import uploaded
        track = uploaded(track_id)
    path = _audio_path(track) if track else None
    if path is None:
        raise HTTPException(404, "音频不可用")
    return FileResponse(path, media_type=AUDIO_TYPES[path.suffix.lower()],
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
