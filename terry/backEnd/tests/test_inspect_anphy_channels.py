"""Tests for header-only ANPHY electrode inspection."""

import io
import zipfile
from pathlib import Path

from scripts.inspect_anphy_channels import (
    canonical_name,
    discover,
    inspect_source,
    read_edf_labels,
    summarize,
)


def edf_header(labels):
    count = len(labels)
    header = bytearray(b" " * 256)
    header[:8] = b"0       "
    header[184:192] = f"{256 + count * 256:<8}".encode("ascii")
    header[252:256] = f"{count:<4}".encode("ascii")
    return bytes(header) + b"".join(f"{label:<16}".encode("ascii") for label in labels)


def test_old_names_map_to_cap_sites_but_bipolar_signals_do_not():
    labels = read_edf_labels(io.BytesIO(edf_header(["T5-Ref", "T6", "T3", "T4", "F4-", "P7-O1"])))
    matches = summarize(labels)
    assert matches["P7"] == [(1, "T5-Ref")]
    assert matches["P8"] == [(2, "T6")]
    assert matches["T7"] == [(3, "T3")]
    assert matches["T8"] == [(4, "T4")]
    assert canonical_name("F4-") == "F4"
    assert canonical_name("P7-O1") == "P7-O1"


def test_prefers_extracted_edf_and_reads_zip_when_unextracted(tmp_path: Path):
    edf = tmp_path / "EPCTL01" / "record.edf"
    edf.parent.mkdir()
    edf.write_bytes(edf_header(["T5", "T6"]))
    with zipfile.ZipFile(tmp_path / "EPCTL01(1).zip", "w") as bundle:
        bundle.writestr("EPCTL01/other.edf", edf_header(["NOT_THE_SOURCE"]))
    with zipfile.ZipFile(tmp_path / "EPCTL02.zip", "w") as bundle:
        bundle.writestr("nested/EPCTL02.edf", edf_header(["T5-Ref", "T6-Ref"]))
    sources = discover(tmp_path)
    assert sorted(sources) == ["EPCTL01", "EPCTL02"]
    assert sources["EPCTL01"][0] == "edf"
    assert inspect_source(sources["EPCTL01"]) == ["T5", "T6"]
    assert sources["EPCTL02"][0] == "zip"
    assert inspect_source(sources["EPCTL02"]) == ["T5-Ref", "T6-Ref"]
