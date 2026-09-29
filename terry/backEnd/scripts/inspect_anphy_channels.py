"""Inspect ANPHY EDF channel headers without loading overnight EEG samples.

Usage:
    python scripts/inspect_anphy_channels.py --dataset "E:\\project\\test\\terry\\dataset"
    python scripts/inspect_anphy_channels.py --dataset "E:\\project\\test\\terry\\dataset" --all-channels
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


CAP_ORDER = (
    "Fp1", "Fp2", "C3", "C4", "P7", "P8", "O1", "O2",
    "F7", "F8", "F3", "F4", "T7", "T8", "P3", "P4",
)
ALIASES = {"T3": "T7", "T4": "T8", "T5": "P7", "T6": "P8"}
SUBJECT_PATTERN = re.compile(r"EPCTL\d+", re.IGNORECASE)


def canonical_name(label: str) -> str:
    """Normalize only known reference suffixes and historical electrode aliases.

    A bipolar label such as P7-O1 is deliberately NOT interpreted as P7.
    """
    name = re.sub(r"^(?:EEG|POLY)\s*", "", label.strip(), flags=re.IGNORECASE)
    name = re.sub(r"[-_\s]*(?:REF|AVG|LE|A1|A2|M1|M2)$", "", name, flags=re.IGNORECASE)
    name = name.rstrip("-_ ").upper()
    return ALIASES.get(name, name)


def read_edf_labels(stream) -> list[str]:
    """Read only the fixed EDF header and its 16-byte-per-signal label field."""
    header = stream.read(256)
    if len(header) != 256 or header[:8] != b"0       ":
        raise ValueError("not a complete EDF header (unexpected version)")
    try:
        count = int(header[252:256].decode("ascii").strip())
        header_bytes = int(header[184:192].decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid EDF signal count or header length") from exc
    if not 1 <= count <= 4096 or header_bytes < 256 + 256 * count:
        raise ValueError(f"invalid EDF header size or signal count: {count}")
    labels = stream.read(16 * count)
    if len(labels) != 16 * count:
        raise ValueError("incomplete EDF channel labels")
    return [labels[i:i + 16].decode("latin-1").strip() for i in range(0, len(labels), 16)]


def subject_id(path: Path | str) -> str | None:
    match = SUBJECT_PATTERN.search(str(path))
    return match.group().upper() if match else None


def discover(dataset: Path) -> dict[str, tuple[str, Path, str | None]]:
    """One source per subject: extracted EDF preferred over archive; no extraction."""
    sources: dict[str, tuple[str, Path, str | None]] = {}
    for path in sorted(dataset.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".edf":
            continue
        sid = subject_id(path.relative_to(dataset))
        if sid:
            sources.setdefault(sid, ("edf", path, None))
    for archive in sorted(dataset.rglob("*")):
        if not archive.is_file() or archive.suffix.lower() != ".zip":
            continue
        sid = subject_id(archive.relative_to(dataset))
        if not sid or sid in sources:
            continue
        with zipfile.ZipFile(archive) as bundle:
            members = [item.filename for item in bundle.infolist()
                       if not item.is_dir() and item.filename.lower().endswith(".edf")]
        if len(members) != 1:
            raise ValueError(f"{archive}: expected exactly one EDF, found {len(members)}")
        sources[sid] = ("zip", archive, members[0])
    return dict(sorted(sources.items()))


def inspect_source(source: tuple[str, Path, str | None]) -> list[str]:
    kind, path, member = source
    if kind == "edf":
        with path.open("rb") as stream:
            return read_edf_labels(stream)
    assert member is not None
    with zipfile.ZipFile(path) as bundle, bundle.open(member) as stream:
        return read_edf_labels(stream)


def summarize(labels: list[str]) -> dict[str, list[tuple[int, str]]]:
    matches: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for number, label in enumerate(labels, start=1):
        matches[canonical_name(label)].append((number, label))
    return dict(matches)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="ANPHY dataset root (EDF, ZIP, or both)")
    parser.add_argument("--all-channels", action="store_true", help="Print every raw EDF signal label")
    args = parser.parse_args(argv)
    if not args.dataset.is_dir():
        parser.error(f"dataset directory does not exist: {args.dataset}")
    try:
        sources = discover(args.dataset)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        return 2
    if not sources:
        print("No EPCTL EDF recordings (extracted or inside ZIP) found.", file=sys.stderr)
        return 2

    complete = 0
    failed = 0
    for sid, source in sources.items():
        kind, path, _ = source
        try:
            labels = inspect_source(source)
            matches = summarize(labels)
            available = [name for name in CAP_ORDER if len(matches.get(name.upper(), [])) == 1]
            missing = [name for name in CAP_ORDER if name.upper() not in matches]
            duplicates = [name for name in CAP_ORDER if len(matches.get(name.upper(), [])) > 1]
            ok = not missing and not duplicates
            complete += ok
            print(f"{sid} [{kind}] {path}: {len(labels)} EDF signals; cap {len(available)}/16; "
                  f"P7={matches.get('P7', [])}; P8={matches.get('P8', [])}")
            if missing or duplicates:
                print(f"  missing={missing}; ambiguous={duplicates}")
            if args.all_channels:
                print("  EDF labels (number: raw -> canonical):")
                for number, label in enumerate(labels, start=1):
                    print(f"    {number:>3}: {label!r} -> {canonical_name(label)}")
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
            failed += 1
            print(f"{sid} [{kind}] ERROR: {exc}", file=sys.stderr)
    print(f"Subjects={len(sources)}; complete 16-channel headers={complete}; read errors={failed}")
    print("Header presence does not establish full-night signal quality, reference compatibility, or valid annotations.")
    return 0 if complete == len(sources) and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
