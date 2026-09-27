#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any


API_URL = "https://api.osf.io/v2/nodes/r26fh/files/osfstorage/"


def list_files() -> list[dict[str, Any]]:
    files = []
    url: str | None = API_URL
    while url:
        with urllib.request.urlopen(url) as response:
            payload = json.load(response)
        files.extend(payload["data"])
        url = payload["links"]["next"]
    return files


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(file_info: dict[str, Any], destination: Path) -> Path:
    attributes = file_info["attributes"]
    output = destination / attributes["name"]
    expected_size = int(attributes["size"])
    expected_md5 = attributes["extra"]["hashes"]["md5"]
    if output.exists() and output.stat().st_size == expected_size:
        if _md5(output) == expected_md5:
            print(f"verified: {output}")
            return output

    partial = output.with_suffix(output.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    request = urllib.request.Request(file_info["links"]["download"], headers=headers)
    with urllib.request.urlopen(request) as response:
        mode = "ab" if existing and response.status == 206 else "wb"
        with partial.open(mode) as handle:
            while chunk := response.read(8 * 1024 * 1024):
                handle.write(chunk)
                completed = handle.tell()
                print(
                    f"\r{attributes['name']}: {completed / expected_size:6.2%}",
                    end="",
                    flush=True,
                )
    print()
    if partial.stat().st_size != expected_size:
        raise IOError(
            f"Incomplete download for {attributes['name']}: "
            f"{partial.stat().st_size} != {expected_size}"
        )
    if _md5(partial) != expected_md5:
        raise IOError(f"Checksum mismatch for {attributes['name']}")
    partial.replace(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Download public ANPHY-Sleep files")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--subject", help="Subject ID, e.g. EPCTL11")
    selection.add_argument("--all", action="store_true", help="Download all 29 subjects")
    selection.add_argument("--list", action="store_true", help="List available subjects")
    parser.add_argument("--output", default="data/raw")
    args = parser.parse_args()

    files = list_files()
    subjects = [
        item
        for item in files
        if re.fullmatch(r"EPCTL\d+(?:-\d+)?\.zip", item["attributes"]["name"], re.I)
    ]
    subjects.sort(key=lambda item: item["attributes"]["name"])
    if args.list:
        for item in subjects:
            size_gb = item["attributes"]["size"] / 1024**3
            print(f"{item['attributes']['name']}\t{size_gb:.2f} GiB")
        return

    if args.subject:
        wanted = args.subject.upper()
        subjects = [
            item
            for item in subjects
            if item["attributes"]["name"].upper().startswith(wanted)
        ]
        if not subjects:
            raise SystemExit(f"Subject not found: {args.subject}")

    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    for item in subjects:
        download(item, destination)


if __name__ == "__main__":
    main()
