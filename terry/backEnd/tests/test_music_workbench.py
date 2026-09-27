"""ASGI route tests without HTTP-client, MIDI-parser or audio dependencies."""
import asyncio
import importlib.util
import json
from pathlib import Path
import struct
from urllib.parse import urlencode

from fastapi import FastAPI
import pytest

from anphy_sleep.music_engine.midi import generate_midi_plan

spec = importlib.util.spec_from_file_location("music_workbench_test_module", Path(__file__).parents[1] / "music_workbench.py")
music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(music)


def request(endpoint="plan", method="GET", **params):
    app = FastAPI()
    app.include_router(music.router)
    messages = []
    path = f"/api/music-workbench/{endpoint}"

    async def run():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                   "http_version": "1.1", "method": method, "scheme": "http", "path": path,
                   "raw_path": path.encode(), "query_string": urlencode(params).encode(), "root_path": "",
                   "headers": [], "client": ("127.0.0.1", 1234), "server": ("test", 80)}, receive, send)

    asyncio.run(run())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def get_plan(**params):
    status, headers, body = request(**params)
    assert status == 200
    assert headers[b"cache-control"] == b"no-store"
    return json.loads(body)


def test_defaults_and_determinism():
    plan = get_plan()
    assert plan == get_plan(state="M1", seed=42, bars=4, variation="auto", transpose=0)
    assert (plan["bpm"], plan["beats_per_bar"], plan["phrase_beats"], plan["total_beats"]) == (60, 4, 16, 16)
    assert plan["resolved_variation"] == "complete"
    assert set(plan["notes"][0]) == {"start_beat", "duration_beats", "midi_note", "velocity", "voice", "phrase"}
    assert plan["notes"] != get_plan(seed=43)["notes"]
    assert get_plan(seed=2147483647)["seed"] == 2147483647


@pytest.mark.parametrize("state", ["M1", "M2", "M3"])
@pytest.mark.parametrize("variation", ["auto", "complete", "reduced", "extended", "octave"])
def test_states_and_variations_match_generator(state, variation):
    plan = get_plan(state=state, variation=variation)
    original = generate_midi_plan(state, 42, 4, None if variation == "auto" else variation)
    assert len(original) == len(plan["notes"])
    for expected, note in zip(original, plan["notes"]):
        assert note["midi_note"] == expected.midi_note
        assert note["start_beat"] == expected.start_beat
        assert note["duration_beats"] == min(expected.duration_beats, 16 - expected.start_beat)
        assert note["phrase"] == expected.phrase
        assert 0 < note["duration_beats"] and note["start_beat"] + note["duration_beats"] <= 16
        assert 1 <= note["velocity"] <= 127
    assert plan["midi_quality"]["note_count"] == len(original)
    assert plan["midi_quality"]["out_of_scale"] == 0
    if state == "M3":
        assert plan["notes"] == []
        assert plan["gains"]["pad"] > 0 and plan["gains"]["texture"] > 0
        assert plan["gains"]["melody"] == 0


@pytest.mark.parametrize("state,master", [("M1", .80), ("M2", .68), ("M3", .52)])
def test_gain_and_waveform_contract(state, master):
    plan = get_plan(state=state)
    assert set(plan["gains"]) == {"pad", "melody", "bass", "texture"}
    assert all(0 <= gain <= 1 for gain in plan["gains"].values())
    assert plan["waveform"]["master_gain"] == master
    assert set(plan["waveform"]) == {"master_gain", "brightness", "reverb_send", "stereo_width", "fade_seconds"}


@pytest.mark.parametrize("transpose", range(-12, 13))
def test_all_semitone_transpositions_and_quality(transpose):
    base = get_plan()
    plan = get_plan(transpose=transpose)
    assert [n["midi_note"] for n in plan["notes"]] == [n["midi_note"] + transpose for n in base["notes"]]
    assert all(0 <= n["midi_note"] <= 127 for n in plan["notes"])
    quality = plan["midi_quality"]
    scale = {(n + transpose) % 12 for n in (0, 2, 4, 5, 7, 9, 11)}
    assert quality["scope"] == "transposed_plan"
    assert quality["scale_pitch_classes"] == sorted(scale)
    assert quality["out_of_scale"] == sum(n["midi_note"] % 12 not in scale for n in plan["notes"] if n["voice"] == "melody") == 0
    assert quality["out_of_range"] == sum(not 48 <= n["midi_note"] <= 96 for n in plan["notes"] if n["voice"] == "melody")
    assert quality["passes"] == (quality["out_of_range"] == 0)


@pytest.mark.parametrize("endpoint", ["plan", "midi"])
@pytest.mark.parametrize("params", [
    {"state": "M4"}, {"state": "m1"}, {"state": ""}, {"state": "M1\r\nInjected:yes"},
    {"variation": "random"}, {"variation": ""}, {"bars": 0}, {"bars": 5}, {"bars": 8},
    {"bars": 1000000}, {"bars": 4.5}, {"transpose": -13}, {"transpose": 13},
    {"transpose": 1.5}, {"transpose": "nan"}, {"seed": -1}, {"seed": 2147483648},
    {"seed": "abc"}, {"seed": 1.5},
])
def test_invalid_inputs(endpoint, params):
    assert request(endpoint, **params)[0] == 422


def parse_midi(payload):
    """Parse this writer's type-0 events to independently check export timing."""
    assert payload[:4] == b"MThd"
    assert struct.unpack(">IHHH", payload[4:14]) == (6, 0, 1, 480)
    assert payload[14:18] == b"MTrk"
    assert struct.unpack(">I", payload[18:22])[0] == len(payload) - 22
    i, tick = 22, 0
    events, tempos = [], []
    while i < len(payload):
        delta = 0
        while True:
            byte = payload[i]
            i += 1
            delta = (delta << 7) | (byte & 127)
            if byte < 128:
                break
        tick += delta
        status = payload[i]
        i += 1
        if status == 255:
            kind, size = payload[i:i + 2]
            i += 2
            data = payload[i:i + size]
            i += size
            if kind == 81:
                tempos.append(int.from_bytes(data, "big"))
            elif kind == 47:
                assert size == 0 and i == len(payload)
        else:
            assert status in (0x80, 0x90)
            events.append((tick, status, payload[i], payload[i + 1]))
            i += 2
    assert tempos == [1000000]
    return events


@pytest.mark.parametrize("state", ["M1", "M2", "M3"])
@pytest.mark.parametrize("variation", ["auto", "complete", "reduced", "extended", "octave"])
@pytest.mark.parametrize("transpose", [-12, 1, 12])
def test_midi_export_matches_plan(state, variation, transpose):
    params = dict(state=state, variation=variation, transpose=transpose)
    plan = get_plan(**params)
    status, headers, payload = request("midi", **params)
    assert status == 200
    assert headers[b"content-type"] == b"audio/midi"
    assert headers[b"content-length"] == str(len(payload)).encode()
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"access-control-expose-headers"] == b"Content-Disposition"
    assert headers[b"content-disposition"] == (f'attachment; filename="terry-{state}-seed42-4bars-{plan["resolved_variation"]}-transpose{transpose}.mid"').encode()
    assert payload == request("midi", **params)[2]
    expected = []
    for note in plan["notes"]:
        expected.extend([(round(note["start_beat"] * 480), 0x90, note["midi_note"], note["velocity"]),
                         (round((note["start_beat"] + note["duration_beats"]) * 480), 0x80, note["midi_note"], 0)])
    assert sorted(parse_midi(payload)) == sorted(expected)


def test_temporary_export_is_deleted(monkeypatch):
    original = music.write_midi_file
    paths = []

    def capture(*args, **kwargs):
        path = original(*args, **kwargs)
        paths.append(path)
        return path

    monkeypatch.setattr(music, "write_midi_file", capture)
    assert request("midi")[0] == 200
    assert paths and all(not path.exists() and not path.parent.exists() for path in paths)


def test_export_failure_cleans_temporary_directory(monkeypatch):
    paths = []

    def fail(notes, path, **kwargs):
        paths.append(path)
        path.write_bytes(b"partial")
        raise RuntimeError("writer failed")

    monkeypatch.setattr(music, "write_midi_file", fail)
    with pytest.raises(RuntimeError, match="writer failed"):
        request("midi")
    assert paths and all(not path.parent.exists() for path in paths)


def test_unsafe_generated_pitch_fails_closed(monkeypatch):
    from dataclasses import replace
    original = generate_midi_plan()
    monkeypatch.setattr(music, "generate_midi_plan", lambda *args: [replace(original[0], midi_note=127)])
    assert request(transpose=12)[0] == 422
    assert request("midi", transpose=12)[0] == 422


@pytest.mark.parametrize("endpoint", ["plan", "midi"])
def test_read_only(endpoint):
    assert request(endpoint, method="POST")[0] == 405
