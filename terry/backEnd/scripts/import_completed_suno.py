"""Import a completed provider task; never submits, approves, or overwrites work."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from generate_suno import ROOT, check_id, download_audio, save_task

# prompt-file prefix -> (id prefix, human title, purpose, prompt section)
CATEGORIES = {
    "l1-pad": ("pad", "Warm Low-Information Sleep Pad", "L1 / Pad 基础铺底候选", "第3节"),
    "l4-texture": ("texture", "Filtered Brown Texture for Sleep", "L4 / Texture 环境纹理候选", "第4节"),
    "m2-transition": ("m2", "Sparse Pre-Sleep Transition", "M2 过渡参考候选", "第5节"),
    "m3-minimal": ("m3", "Minimal Deep Sleep Drone", "M3 极简参考候选", "第6节"),
}


def category_for(directory):
    source = directory / "prompt_source.txt"
    name = source.read_text(encoding="utf-8").strip() if source.is_file() else ""
    prompt = directory / "prompt.txt"
    prompt_text = prompt.read_text(encoding="utf-8").strip() if prompt.is_file() else ""
    for prefix, details in CATEGORIES.items():
        if name.startswith(prefix):
            return details
        candidate = ROOT / "music" / "prompts" / f"{prefix}-v1.txt"
        # Tasks submitted before source tracking are matched by prompt content.
        if prompt_text and candidate.is_file() and candidate.read_text(encoding="utf-8").strip() == prompt_text:
            return details
    return ("candidate", "Unclassified Audio Candidate", "未分类候选素材", "未指定")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_file", type=Path)
    args = parser.parse_args()
    task = json.loads(args.task_file.read_text(encoding="utf-8"))
    task_id = check_id(task["id"])
    if task.get("status") != "completed" or not isinstance(task.get("results"), list) or not task["results"]:
        raise ValueError("Expected a completed task with audio result URLs")
    directory = ROOT / "music" / "candidates" / task_id
    save_task(directory, task)
    prefix, title, purpose, section = category_for(directory)

    import soundfile as sf

    records = []
    for index, url in enumerate(task["results"]):
        suffix = Path(urlparse(url).path).suffix.lower()
        suffix = ".mp3" if suffix == ".mpeg" else suffix
        existing = directory / f"candidate-{index}{suffix}"
        # Resume safely: a prior import may have downloaded before inspection failed.
        path = existing if existing.is_file() and not existing.is_symlink() else download_audio(url, directory, index)
        info = sf.info(path)
        records.append({"file": str(path.relative_to(ROOT / "music")),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "sample_rate_hz": info.samplerate, "channels": info.channels,
                        "duration_s": info.duration, "format": info.format, "subtype": info.subtype,
                        "review_status": "pending"})

    (directory / "technical_report.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    manifest_path = ROOT / "music" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"version": 1, "tracks": []}
    known = {track["id"] for track in manifest["tracks"]}
    known_files = {track["file"] for track in manifest["tracks"]}
    for index, record in enumerate(records):
        if record["file"] in known_files:
            print(f"Skipped existing manifest entry: {record['file']}")
            continue
        track_id = f"{prefix}-{task_id}-{index}"
        if track_id in known:
            raise ValueError("Duplicate track ID; refusing to overwrite a review record")
        manifest["tracks"].append({
            "id": track_id, "title": f"{title} — Candidate {index + 1}", "file": record["file"],
            "purpose": f"{purpose}；非助眠疗效证明",
            "source": f"AISAASGO API; {task.get('model')}; task {task_id}; docs/SUNO_AUDIO_PROMPTS.md {section}",
            "license": "", "review": {"status": "pending", "reviewed_by": "", "reviewed_at": None,
            "copyright_checked": False, "audio_checked": False,
            "notes": "已下载并读取音频格式/时长及SHA-256；尚未全曲听审或核查授权。"}})
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(manifest_path)
    for record in records:
        print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
