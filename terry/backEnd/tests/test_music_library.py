"""Offline music API integration tests; no hardware or HTTP client dependency."""
import asyncio
import importlib.util
import json
from pathlib import Path

from fastapi import FastAPI
import pytest

spec = importlib.util.spec_from_file_location("music_library_test_module", Path(__file__).parents[1] / "music_library.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "music"
    root.mkdir()
    monkeypatch.setattr(music, "MUSIC_DIR", root)
    return root


def entry(**changes):
    data = {"id": "calm-01", "title": "Calm", "file": "calm.mp3", "license": "Reviewed local use permission",
            "review": {"status": "approved", "reviewed_by": "Tester", "reviewed_at": "2026-09-12",
                       "copyright_checked": True, "audio_checked": True}}
    data.update(changes)
    return data


def manifest(root, entries):
    (root / "manifest.json").write_text(json.dumps({"version": 1, "tracks": entries}), encoding="utf-8")


def request(path="/api/music", headers=(), method="GET"):
    app = FastAPI()
    app.include_router(music.router)
    messages = []

    async def run():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                   "http_version": "1.1", "method": method, "scheme": "http", "path": path,
                   "raw_path": path.encode(), "query_string": b"", "root_path": "",
                   "headers": list(headers), "client": ("127.0.0.1", 1234), "server": ("test", 80)}, receive, send)

    asyncio.run(run())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def test_missing_library_is_empty(library):
    status, _, body = request()
    assert status == 200
    assert json.loads(body)["tracks"] == []
    assert json.loads(body)["status"] == "missing"


def test_catalog_and_audio_range(library):
    manifest(library, [entry()])
    (library / "calm.mp3").write_bytes(b"0123456789")
    status, headers, body = request()
    catalog = json.loads(body)
    assert status == 200 and headers[b"cache-control"] == b"no-store"
    assert catalog["control_mode"] == "manual"
    assert catalog["tracks"][0]["available"] is True
    assert "file" not in catalog["tracks"][0]
    status, headers, body = request("/api/music/calm-01/audio")
    assert status == 200 and body == b"0123456789"
    assert headers[b"content-type"] == b"audio/mpeg"
    status, headers, body = request("/api/music/calm-01/audio", [(b"range", b"bytes=2-5")])
    assert status == 206 and body == b"2345"


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_review_status_does_not_gate_playback(library, status):
    track = entry()
    track["review"]["status"] = status
    manifest(library, [track])
    (library / "calm.mp3").write_bytes(b"audio")
    assert json.loads(request()[2])["tracks"][0]["available"] is True
    assert request("/api/music/calm-01/audio")[0] == 200


@pytest.mark.parametrize("field,value", [("copyright_checked", False), ("audio_checked", False), ("reviewed_by", ""), ("reviewed_at", None)])
def test_incomplete_review_allows_playback(library, field, value):
    track = entry()
    track["review"][field] = value
    manifest(library, [track])
    (library / "calm.mp3").write_bytes(b"audio")
    assert request("/api/music/calm-01/audio")[0] == 200


def test_no_review_or_license_required(library):
    manifest(library, [{"id": "calm-01", "title": "Calm", "file": "calm.mp3"}])
    (library / "calm.mp3").write_bytes(b"audio")
    assert json.loads(request()[2])["tracks"][0]["available"] is True
    assert request("/api/music/calm-01/audio")[0] == 200


@pytest.mark.parametrize("filename", ["../secret.mp3", "/tmp/secret.mp3", "..\\secret.mp3", "https://example.org/audio.mp3", "nested/../../secret.mp3", "page.html"])
def test_unsafe_paths_denied(library, filename):
    (library.parent / "secret.mp3").write_bytes(b"secret")
    (library / "page.html").write_text("secret")
    manifest(library, [entry(file=filename)])
    assert request("/api/music/calm-01/audio")[0] == 404


def test_symlink_escape_denied(library, symlink_or_skip):
    outside = library.parent / "secret.mp3"
    outside.write_bytes(b"secret")
    symlink_or_skip(library / "calm.mp3", outside)
    manifest(library, [entry()])
    assert request("/api/music/calm-01/audio")[0] == 404


def test_symlink_manifest_denied(library, symlink_or_skip):
    outside = library.parent / "secret.json"
    outside.write_text(json.dumps({"version": 1, "tracks": [entry()]}))
    symlink_or_skip(library / "manifest.json", outside)
    assert json.loads(request()[2])["tracks"] == []


@pytest.mark.parametrize("content", ["{", '{"version": 2, "tracks": []}', '{"version": 1, "tracks": [{"id": "bad"}]}'])
def test_invalid_manifest_fails_closed(library, content):
    (library / "manifest.json").write_text(content)
    assert json.loads(request()[2])["status"] == "invalid"
    assert request("/api/music/calm-01/audio")[0] == 404


def test_duplicate_ids_fail_closed(library):
    manifest(library, [entry(), entry()])
    assert json.loads(request()[2])["status"] == "invalid"


def test_deleted_file_denied_regardless_of_review(library):
    manifest(library, [entry()])
    audio = library / "calm.mp3"
    audio.write_bytes(b"audio")
    assert request("/api/music/calm-01/audio")[0] == 200
    manifest(library, [entry(review={"status": "rejected"})])
    assert request("/api/music/calm-01/audio")[0] == 200
    manifest(library, [entry()])
    audio.unlink()
    assert request("/api/music/calm-01/audio")[0] == 404


def test_unknown_id_and_upload_denied(library):
    assert request("/api/music/unknown/audio")[0] == 404
    assert request("/api/music", method="POST")[0] == 405
