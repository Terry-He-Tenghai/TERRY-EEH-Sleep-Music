#!/usr/bin/env python3
"""Download and verify BOAS PSG EDFs; keep labels from the metadata checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path


API = "https://openneuro.org/crn/graphql"
CHANNELS = {"PSG_F3", "PSG_F4", "PSG_C3", "PSG_C4", "PSG_O1", "PSG_O2"}
EDF = re.compile(r"^(sub-\d+)/eeg/\1_task-Sleep_acq-psg_eeg\.edf$")
KEY = re.compile(r"SHA256E-s(\d+)--([0-9a-f]{64})\.edf")


def manifest() -> dict[str, dict]:
    query = '{ dataset(id: "ds005555") { latestSnapshot { files(recursive: true) { filename size urls } } } }'
    request = urllib.request.Request(
        API, data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return {
        item["filename"]: item
        for item in payload["data"]["dataset"]["latestSnapshot"]["files"]
        if EDF.fullmatch(item["filename"])
    }


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def download(item: dict, checkout: Path, output: Path) -> None:
    filename = item["filename"]
    source = checkout / filename
    if not source.is_symlink():
        raise RuntimeError(f"Expected annex link: {source}")
    key = KEY.search(source.readlink().name)
    if not key or int(key.group(1)) != item["size"]:
        raise RuntimeError(f"Annex key / API size mismatch: {filename}")
    size, sha = int(key.group(1)), key.group(2)
    target = output / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == size and digest(target) == sha:
        print(f"verified {filename}", flush=True)
        return

    partial = target.with_suffix(".edf.part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        raise RuntimeError(f"Partial file exceeds expected size: {partial}")
    if offset < size:
        request = urllib.request.Request(item["urls"][0], headers={"Range": f"bytes={offset}-"} if offset else {})
        with urllib.request.urlopen(request, timeout=60) as response:
            if offset and response.status != 206:
                raise RuntimeError(f"Server did not honor resume for {filename}")
            with partial.open("ab" if offset else "wb") as stream:
                while block := response.read(8 * 1024 * 1024):
                    stream.write(block)
    if partial.stat().st_size != size or digest(partial) != sha:
        raise RuntimeError(f"Size or SHA-256 mismatch: {partial}")
    partial.replace(target)
    print(f"verified {filename}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path("data/raw/ds005555"))
    parser.add_argument("--output", type=Path, default=Path("data/raw/boas-psg"))
    parser.add_argument("--subject", help="One subject, e.g. sub-1; omit for all nights")
    args = parser.parse_args()
    files = manifest()
    selected = sorted(files, key=lambda name: int(EDF.fullmatch(name).group(1).split("-")[1]))
    if args.subject:
        selected = [name for name in selected if EDF.fullmatch(name).group(1) == args.subject]
    if not selected:
        parser.error("No matching subjects")
    for name in selected:
        subject = EDF.fullmatch(name).group(1)
        channels = args.checkout / subject / "eeg" / f"{subject}_task-Sleep_acq-psg_channels.tsv"
        events = args.checkout / subject / "eeg" / f"{subject}_task-Sleep_acq-psg_events.tsv"
        if not CHANNELS.issubset({line.split("\t")[0] for line in channels.read_text().splitlines()}):
            print(f"skip {subject}: missing required EEG channels", flush=True)
            continue
        if "stage_hum" not in events.read_text():
            print(f"skip {subject}: no human labels", flush=True)
            continue
        download(files[name], args.checkout, args.output)
    print("Labels and channel metadata are in the --checkout directory.")


if __name__ == "__main__":
    main()
