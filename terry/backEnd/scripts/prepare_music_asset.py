"""Prepare pending local music or freeze a hash-bound human-reviewed version."""
import argparse
import json
from pathlib import Path

from anphy_sleep.music_engine.assets import freeze, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("prepare", help="Inspect and standardize; never approve")
    pending.add_argument("source", type=Path)
    pending.add_argument("destination", type=Path)
    pending.add_argument("--provenance", required=True)
    pending.add_argument("--duration", type=float, default=60.)
    pending.add_argument("--sample-rate", type=int, default=48000)
    pending.add_argument("--target-rms-dbfs", type=float, default=-24.)
    pending.add_argument("--peak-dbfs", type=float, default=-3.)
    approved = commands.add_parser("freeze", help="Requires completed review.json for the exact WAV")
    approved.add_argument("prepared", type=Path)
    approved.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        report = prepare(args.source, args.destination, provenance=args.provenance,
                         duration_s=args.duration, sample_rate=args.sample_rate,
                         target_rms_dbfs=args.target_rms_dbfs, peak_dbfs=args.peak_dbfs)
    else:
        report = freeze(args.prepared, args.destination)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
