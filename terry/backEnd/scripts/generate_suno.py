"""Explicit, operator-run AISAASGO task submission and candidate download."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://aisaasgo.org/v1"
TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
MAX_BYTES = 100 * 1024 * 1024


class ProviderError(RuntimeError):
    """Contains HTTP status and a bounded, redacted provider message."""


def safe_error(response, key):
    try:
        body = response.json()
    except ValueError:
        return "Non-JSON response omitted"
    error = body.get("error", body.get("message", "No error message")) if isinstance(body, dict) else "Unexpected error format"
    if isinstance(error, dict):
        error = error.get("message", error.get("code", "Unspecified error"))
    if not isinstance(error, (str, int)):
        return "Structured error omitted"
    text = str(error)
    if key:
        text = text.replace(key, "[REDACTED]")
    text = re.sub(r"https?://\S+", "[URL REDACTED]", text)
    text = re.sub(r"(?i)Bearer\s+\S+|sk[_-][A-Za-z0-9_-]+", "[REDACTED]", text)
    return " ".join(text.split())[:500]


def create_body(args, prompt):
    model = getattr(args, "model", "suno-v5.5")
    if model not in {"suno-v5", "suno-v5.5"}:
        raise ValueError("Unsupported Suno model")
    custom = getattr(args, "custom_mode", False)
    style = getattr(args, "style", None)
    title = getattr(args, "title", None)
    negative = getattr(args, "negative_tags", None)
    duration = getattr(args, "duration", None)
    if custom and (not style or not style.strip() or not title or not title.strip()):
        raise ValueError("Custom mode requires nonempty --style and --title")
    if not custom and any(value is not None for value in (style, title, negative, duration)):
        raise ValueError("--style, --title, --negative-tags and --duration require --custom-mode")
    if duration is not None and (type(duration) is not int or duration <= 0):
        raise ValueError("--duration must be a positive integer in seconds")
    if duration is not None and model != "suno-v5.5":
        raise ValueError("--duration is only supported for suno-v5.5 custom mode")
    body = {"model": model, "prompt": prompt, "custom_mode": custom, "instrumental": True}
    if custom:
        body.update(style=style.strip(), title=title.strip())
        if negative:
            body["negative_tags"] = negative
        if duration is not None:
            body["duration"] = duration
    return body


def api_request(method, path, key, payload=None):
    if "\r" in key or "\n" in key:
        raise ValueError("Credential must not contain newlines")
    # Never retry POST automatically: the provider may already have billed it.
    try:
        response = requests.request(method, API + path, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                                    json=payload, timeout=(10, 120), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise ProviderError(f"API HTTP {response.status_code}: {safe_error(response, key)}; no automatic retry")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("object expected")
        return data
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"API failure ({type(exc).__name__}); no automatic resubmission. Check provider task history before retrying.") from None


def check_id(task_id):
    if not TASK_ID.fullmatch(task_id):
        raise ValueError("Invalid task ID")
    return task_id


def save_task(directory, data):
    # Persist only fields needed for resuming; never credentials or arbitrary response fields.
    directory.mkdir(parents=True, exist_ok=True)
    record = {key: data[key] for key in ("id", "model", "status", "progress", "results") if key in data}
    temp = directory / "task.json.tmp"
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(directory / "task.json")


def download_audio(url, directory, index):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "img.aisaasgo.org"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Untrusted result URL; only https://img.aisaasgo.org is allowed")
    suffix = Path(parsed.path).suffix.lower()
    if suffix == ".mpeg":
        # Provider returns MPEG audio as .mpeg; store with an audio extension.
        suffix = ".mp3"
    if suffix not in {".mp3", ".wav", ".ogg", ".m4a", ".flac"}:
        raise ValueError("Result URL has an unsupported audio extension; inspect manually")
    target = directory / f"candidate-{index}{suffix}"
    if target.exists():
        raise FileExistsError("Candidate already exists; refusing to overwrite")
    partial = target.with_suffix(target.suffix + ".part")
    created_partial = False
    try:
        # A separate request deliberately carries NO API Authorization header.
        with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=False) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Audio HTTP {response.status_code}; redirects are not followed")
            size = 0
            with partial.open("xb") as handle:
                created_partial = True
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise RuntimeError("Audio exceeds 100 MiB limit")
                    handle.write(chunk)
            if size == 0:
                raise RuntimeError("Empty audio response")
        partial.replace(target)
    except Exception:
        if created_partial:
            partial.unlink(missing_ok=True)
        raise
    return target


def run(args, key):
    if args.action == "submit":
        prompt = args.prompt_file.read_text(encoding="utf-8").strip()
        if not prompt or len(prompt) > 20000:
            raise ValueError("Prompt must contain 1–20000 characters")
        body = create_body(args, prompt)
        receipt_dir = ROOT / "music" / "submissions"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt = receipt_dir / f"{uuid.uuid4().hex}.json"
        record = {"model": body["model"], "started_at_unix": time.time(), "status": "submission_started"}
        receipt.write_text(json.dumps(record, indent=2), encoding="utf-8")
        try:
            data = api_request("POST", "/audios/generations", key, body)
        except ProviderError as exc:
            record.update(status="submission_uncertain", safe_error=str(exc))
            receipt.write_text(json.dumps(record, indent=2), encoding="utf-8")
            raise
        task_id = check_id(data.get("id", ""))
        # Display ID before disk writes so an operator can recover if storage fails.
        print(f"Task: {task_id}", flush=True)
        record.update(status="task_received", task_id=task_id)
        receipt.write_text(json.dumps(record, indent=2), encoding="utf-8")
        directory = ROOT / "music" / "candidates" / task_id
        save_task(directory, data)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        (directory / "prompt_source.txt").write_text(args.prompt_file.name, encoding="utf-8")
        print("Submitted once. Use fetch with this task ID to resume; do not resubmit to poll.")
        return
    task_id = check_id(args.task_id)
    directory = ROOT / "music" / "candidates" / task_id
    deadline = time.monotonic() + args.wait_seconds
    while True:
        data = api_request("GET", f"/tasks/{task_id}", key)
        if data.get("id") != task_id:
            raise ValueError("Provider returned a mismatching task ID")
        save_task(directory, data)
        status = data.get("status")
        print(f"Task {task_id}: {status}")
        if status == "completed":
            results = data.get("results")
            if not isinstance(results, list) or not results or not all(isinstance(url, str) for url in results):
                raise ValueError("Expected a nonempty list of result URLs")
            for index, url in enumerate(results):
                print(f"Downloaded: {download_audio(url, directory, index).relative_to(ROOT)}")
            print("Candidates only: listen, verify format and license, then add pending manifest records for review.")
            return
        if status in {"failed", "cancelled", "canceled", "error"}:
            raise RuntimeError("Generation failed or was cancelled; no resubmission performed")
        if status not in {"pending", "processing", "running", "queued", "in_progress"}:
            raise ValueError("Unknown task status; inspect provider documentation")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("Still pending. Run fetch again with the same task ID.")
            return
        time.sleep(min(10, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    submit = actions.add_parser("submit", help="Submit ONE billable generation request")
    submit.add_argument("--prompt-file", type=Path, required=True)
    submit.add_argument("--model", choices=["suno-v5", "suno-v5.5"], default="suno-v5.5")
    submit.add_argument("--custom-mode", action="store_true")
    submit.add_argument("--style")
    submit.add_argument("--title")
    submit.add_argument("--negative-tags")
    submit.add_argument("--duration", type=int, help="Custom-mode target duration in seconds (provider limits apply)")
    fetch = actions.add_parser("fetch", help="Poll existing task and download candidates, without submitting")
    fetch.add_argument("task_id")
    fetch.add_argument("--wait-seconds", type=int, choices=range(0, 1801), default=0, metavar="0..1800")
    args = parser.parse_args()
    # Load the small env helper without importing the EEG package __init__,
    # which unnecessarily initializes MNE/Numba for this standalone API tool.
    import importlib.util
    spec = importlib.util.spec_from_file_location('suno_local_config', ROOT / 'src/anphy_sleep/config.py')
    config_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_module)
    config_module.load_local_env(ROOT)
    key = os.environ.get("AISAASGO_API_KEY", "").strip()
    if not key:
        parser.exit(2, "Set AISAASGO_API_KEY in the environment; never put the key in a prompt or command argument.\n")
    try:
        run(args, key)
    except ProviderError as exc:
        parser.exit(1, f"{exc}\n")
    except (RuntimeError, ValueError, OSError, requests.RequestException) as exc:
        # Avoid printing exception URLs (signed URLs may contain credentials).
        parser.exit(1, f"Operation failed ({type(exc).__name__}). Saved task records can be used to resume; check local paths and provider status.\n")


if __name__ == "__main__":
    main()
