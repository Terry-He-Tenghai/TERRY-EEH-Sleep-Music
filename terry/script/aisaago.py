#!/usr/bin/env python3
"""创建 AI SaaS Go 媒体任务、轮询状态并下载结果。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://aisaasgo.org/v1"
TERMINAL = {"completed", "failed"}


class ApiError(RuntimeError):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        message = payload.get("error", payload) if isinstance(payload, dict) else payload
        super().__init__(f"HTTP {status}：{message}")


def request_json(method: str, path: str, key: str, body: dict[str, Any] | None = None, retries: int = 0) -> dict[str, Any]:
    base = os.getenv("AISAASGO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method), timeout=120) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            raw = error.read().decode(errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            if method == "GET" and (error.code == 429 or error.code >= 500) and attempt < retries:
                time.sleep(min(2**attempt, 20))
                continue
            raise ApiError(error.code, payload) from error
        except urllib.error.URLError as error:
            if method == "GET" and attempt < retries:
                time.sleep(min(2**attempt, 20))
                continue
            raise RuntimeError(f"网络错误：{error.reason}") from error
    raise RuntimeError("请求失败")


def poll_task(task_id: str, key: str, interval: float, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = request_json("GET", f"/tasks/{urllib.parse.quote(task_id, safe='')}", key, retries=4)
        status = task.get("status")
        progress = task.get("progress", 0)
        print(f"状态 {status}，进度 {progress}%", file=sys.stderr)
        if status in TERMINAL:
            return task
        time.sleep(interval)
    raise TimeoutError(f"任务 {task_id} 在 {timeout:g} 秒内未完成")


def download_results(task: dict[str, Any], output_dir: pathlib.Path) -> list[pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[pathlib.Path] = []
    for index, url in enumerate(task.get("results") or [], 1):
        parsed = urllib.parse.urlparse(url)
        suffix = pathlib.Path(parsed.path).suffix
        if not suffix:
            with urllib.request.urlopen(url, timeout=120) as probe:
                suffix = mimetypes.guess_extension(probe.headers.get_content_type()) or ".bin"
        destination = output_dir / f"{task.get('model', 'media')}-{task.get('id', 'task')}-{index}{suffix}"
        with urllib.request.urlopen(url, timeout=300) as source, destination.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
        saved.append(destination)
    return saved


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--output-dir", type=pathlib.Path, default=pathlib.Path("aisaasgo-output"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("models", help="查看可用模型")

    image = sub.add_parser("image", help="生成图片")
    add_common(image)
    image.add_argument("--model", choices=["gpt-image-2", "mona-lisa-1", "mj-v8.1", "mj-v7"], default="gpt-image-2")
    image.add_argument("--size", default="1:1")
    image.add_argument("--resolution", choices=["1K", "2K", "4K"], default="1K")
    image.add_argument("--quality", default="standard")
    image.add_argument("--n", type=int, default=1)
    image.add_argument("--speed", choices=["draft", "fast", "turbo"], default="fast")
    image.add_argument("--image-url", action="append", default=[])
    image.add_argument("--mask-url")

    video = sub.add_parser("video", help="生成视频")
    add_common(video)
    video.add_argument("--model", choices=["seedance-2-mini", "seedance-2", "seedance-2.5"], default="seedance-2-mini")
    video.add_argument("--duration", type=int, default=5)
    video.add_argument("--quality", choices=["480p", "720p", "1080p", "4k"], default="720p")
    video.add_argument("--aspect-ratio", choices=["adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"], default="adaptive")
    video.add_argument("--no-audio", action="store_true")
    video.add_argument("--relaxed-filter", action="store_true")
    video.add_argument("--web-search", action="store_true")
    video.add_argument("--output-format", choices=["mp4", "mov"], default="mp4")

    audio = sub.add_parser("audio", help="生成音乐或音频")
    add_common(audio)
    audio.add_argument("--model", choices=["suno-v4", "suno-v4.5", "suno-v4.5all", "suno-v4.5plus", "suno-v5", "suno-v5.5", "seed-audio-1.0"], default="suno-v5.5")
    audio.add_argument("--custom-mode", action="store_true")
    audio.add_argument("--instrumental", action="store_true")
    audio.add_argument("--style")
    audio.add_argument("--title")
    audio.add_argument("--negative-tags")
    audio.add_argument("--vocal-gender", choices=["m", "f"])
    audio.add_argument("--duration", type=int)
    audio.add_argument("--format", choices=["wav", "mp3", "pcm", "ogg_opus"], default="mp3")
    audio.add_argument("--sample-rate", type=int, choices=[8000, 16000, 24000, 32000, 44100, 48000], default=24000)
    audio.add_argument("--speech-rate", type=float, default=1)
    audio.add_argument("--loudness-rate", type=float, default=1)
    audio.add_argument("--pitch-rate", type=int, default=0)
    return parser


def create_body(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.command == "image":
        allowed_quality = {"gpt-image-2": {"standard", "high"}, "mona-lisa-1": {"low", "medium", "high"}, "mj-v8.1": {"standard", "hd"}, "mj-v7": {"standard"}}
        if args.quality not in allowed_quality[args.model]:
            raise ValueError(f"{args.model} 的质量必须是 {sorted(allowed_quality[args.model])} 之一")
        if args.model.startswith("mj-") and args.n != 1:
            raise ValueError("Midjourney 模型要求 --n 1")
        body: dict[str, Any] = {"model": args.model, "prompt": args.prompt}
        if args.model.startswith("mj-"):
            prompt = args.prompt if "--ar " in args.prompt else f"{args.prompt} --ar {args.size}"
            body.update(prompt=prompt, quality=args.quality, model_params={"speed": args.speed})
        else:
            body.update(size=args.size, resolution=args.resolution, quality=args.quality, n=args.n)
            if args.image_url:
                body["image_urls"] = args.image_url
            if args.mask_url:
                body["mask_url"] = args.mask_url
        return "/images/generations", body
    if args.command == "video":
        limits = {"seedance-2-mini": (15, {"480p", "720p"}), "seedance-2": (30, {"480p", "720p", "1080p", "4k"}), "seedance-2.5": (30, {"480p", "720p", "1080p"})}
        maximum, qualities = limits[args.model]
        if not 4 <= args.duration <= maximum:
            raise ValueError(f"{args.model} 的时长必须在 4 到 {maximum} 秒之间")
        if args.quality not in qualities:
            raise ValueError(f"{args.model} 的质量必须是 {sorted(qualities)} 之一")
        if args.web_search and args.model == "seedance-2-mini":
            raise ValueError("seedance-2-mini 不支持 --web-search")
        if args.web_search and args.relaxed_filter:
            raise ValueError("--web-search 不能与 --relaxed-filter 同时使用")
        body = {"model": args.model, "prompt": args.prompt, "duration": args.duration, "quality": args.quality, "aspect_ratio": args.aspect_ratio, "generate_audio": not args.no_audio, "content_filter": not args.relaxed_filter}
        if args.web_search:
            body["model_params"] = {"web_search": True}
        if args.model == "seedance-2.5":
            body["output_format"] = args.output_format
        return "/videos/generations", body
    if args.model.startswith("suno-"):
        body = {"model": args.model, "prompt": args.prompt, "custom_mode": args.custom_mode, "instrumental": args.instrumental}
        if args.custom_mode:
            if not args.style or not args.title:
                raise ValueError("Suno 自定义模式要求 --style 和 --title")
            body.update(style=args.style, title=args.title)
            if args.negative_tags:
                body["negative_tags"] = args.negative_tags
            if args.vocal_gender:
                body["vocal_gender"] = args.vocal_gender
            if args.duration is not None:
                if args.model != "suno-v5.5":
                    raise ValueError("只有 suno-v5.5 自定义模式支持 --duration")
                body["duration"] = args.duration
    else:
        if not .5 <= args.speech_rate <= 2 or not .5 <= args.loudness_rate <= 2 or not -12 <= args.pitch_rate <= 12:
            raise ValueError("Seed Audio 要求语速和音量在 0.5–2 之间，音高在 -12–12 之间")
        body = {"model": args.model, "prompt": args.prompt, "format": args.format, "sample_rate": args.sample_rate, "speech_rate": args.speech_rate, "loudness_rate": args.loudness_rate, "pitch_rate": args.pitch_rate}
    return "/audios/generations", body


def main() -> int:
    args = build_parser().parse_args()
    key = os.getenv("AISAASGO_API_KEY")
    if not key:
        print("必须设置 AISAASGO_API_KEY", file=sys.stderr)
        return 2
    try:
        if args.command == "models":
            print(json.dumps(request_json("GET", "/models", key, retries=4), ensure_ascii=False, indent=2))
            return 0
        path, body = create_body(args)
        task = request_json("POST", path, key, body)
        print(json.dumps(task, ensure_ascii=False, indent=2))
        if args.no_wait:
            return 0
        task = poll_task(task["id"], key, args.poll_interval, args.timeout)
        print(json.dumps(task, ensure_ascii=False, indent=2))
        if task.get("status") == "failed":
            return 1
        for saved in download_results(task, args.output_dir):
            print(saved.resolve())
        return 0
    except (ApiError, RuntimeError, TimeoutError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
