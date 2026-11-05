"""Generate cases/ and manifest.json from the specification."""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from harness.lnkbuild import LnkSpec, build, to_filetime   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "cases"
TS_FIELDS = ("creation_time", "access_time", "write_time")
EPOCH = _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc)


def ft(d: _dt.datetime) -> int:
    return to_filetime(d)


# (id, filetime value or None for "leave as built", what it represents, expectation)
TIMESTAMP_CASES = [
    ("T0", None,
     "ordinary modern timestamps, three distinct values",
     "return each field's own value"),
    ("T1", 0,
     "unset, not recorded",
     "report absent, or the 1601 epoch; never a current date"),
    ("T2", 0xFFFFFFFFFFFFFFFF,
     "beyond the representable range (year 60056)",
     "signal an error"),
    ("T3", ft(_dt.datetime(1950, 6, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)),
     "a valid, legitimate pre-epoch date",
     "return 1950-06-01 12:00:00Z"),
    ("T4", ft(_dt.datetime(1969, 12, 31, 23, 59, 59, tzinfo=_dt.timezone.utc)),
     "one second before the Unix epoch",
     "return 1969-12-31 23:59:59Z"),
    ("T5", ft(_dt.datetime(1971, 1, 1, 0, 0, 1, tzinfo=_dt.timezone.utc)),
     "a year after the Unix epoch",
     "return 1971-01-01 00:00:01Z"),
    ("T6", 1,
     "one tick past the FILETIME epoch",
     "return the 1601 epoch, distinguishable from T1"),

    ("T7", ft(_dt.datetime(1970, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)),
     "the Unix epoch exactly",
     "return 1970-01-01 00:00:00Z"),
    ("T8", ft(_dt.datetime(1970, 1, 1, 0, 0, 1, tzinfo=_dt.timezone.utc)),
     "one second after the Unix epoch",
     "return 1970-01-01 00:00:01Z"),
    ("T9", ft(_dt.datetime(1970, 1, 2, 0, 0, 0, tzinfo=_dt.timezone.utc)),
     "one day after the Unix epoch, clear of any local offset",
     "return 1970-01-02 00:00:00Z"),

    # T10 and T11 narrow the Unix-epoch boundary from one second to one tick.
    ("T10", 116444735999999999,
     "one FILETIME tick before the Unix epoch",
     "return 1969-12-31 23:59:59.9999999Z"),
    ("T11", 116444736000000001,
     "one FILETIME tick after the Unix epoch",
     "return 1970-01-01 00:00:00.0000001Z"),

    # The aware form of fromtimestamp fails below t = -43200 on Windows, not
    # below t = 0. T12 and T13 bracket that boundary to the second, the way
    # T7 and T4 bracket the naive one.
    ("T12", 116444304000000000,
     "t = -43200 exactly, the aware-conversion boundary",
     "return 1969-12-31 12:00:00Z"),
    ("T13", 116444303990000000,
     "t = -43201, one second below the aware boundary",
     "return 1969-12-31 11:59:59Z"),

    ("T14", 0x7FFFFFFFFFFFFFFF,
     "maximum signed 64-bit, distinguishing overflow from unsigned-max",
     "signal an error, or return year 30828"),
    ("T15", ft(_dt.datetime(1899, 12, 30, 0, 0, 0, tzinfo=_dt.timezone.utc)),
     "the OLE automation epoch, a second pre-1970 date from another period",
     "return 1899-12-30 00:00:00Z"),
    ("T16", ft(_dt.datetime(1601, 1, 2, 0, 0, 0, tzinfo=_dt.timezone.utc)),
     "a real date one day after the FILETIME epoch, not a sentinel",
     "return 1601-01-02 00:00:00Z"),
]

ICON_CASES = [("I0", 0), ("I1", -1), ("I2", -7)]

TARGET_IDLIST = bytes.fromhex(
    "14001f50e04fd020ea3a6910a2d808002b30309d19002f433a5c00000000000000000000"
    "00000000000000000050003100000000000000000010005573657273003c0009000400ef"
    "be00000000000000002e0000000000000000000000000000000000000000000000000000"
    "00000055007300650072007300000014005600310000000000000000001000616e616c79"
    "737400400009000400efbe00000000000000002e00000000000000000000000000000000"
    "0000000000000000000000000061006e0061006c00790073007400000016005c00310000"
    "000000000000001000446f63756d656e747300440009000400efbe00000000000000002e"
    "000000000000000000000000000000000000000000000000000000000044006f00630075"
    "006d0065006e007400730000001800560032000000000000000000000071332e646f6378"
    "00400009000400efbe00000000000000002e000000000000000000000000000000000000"
    "0000000000000000000000710033002e0064006f0063007800000016000000"
)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    manifest = {"generated": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "cases": {}}

    base_spec = LnkSpec(sample_id="base", id_list=TARGET_IDLIST)
    base_data, gt = build(base_spec)

    offsets = {n: gt.by_name(n).offset for n in TS_FIELDS}
    icon_off = gt.by_name("icon_index").offset
    print(f"offsets: {offsets}  icon_index=0x{icon_off:02x}")

    for cid, value, represents, expectation in TIMESTAMP_CASES:
        b = bytearray(base_data)
        expected = {}
        for name in TS_FIELDS:
            if value is None:
                v = to_filetime(getattr(base_spec, name))
            else:
                v = value
                struct.pack_into("<Q", b, offsets[name], v)
            try:
                decoded = (EPOCH + _dt.timedelta(microseconds=v // 10)
                           ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                decoded = None
            expected[name] = {"filetime": v, "decoded_utc": decoded,
                              "unix": v / 10_000_000 - 11_644_473_600}
        path = OUT / f"{cid}.lnk"
        path.write_bytes(bytes(b))
        manifest["cases"][cid] = {
            "file": path.name, "kind": "timestamp", "represents": represents,
            "expectation": expectation, "expected_fields": expected,
            "icon_index": base_spec.icon_index,
        }
        print(f"  {cid}  {path.name:<10} {represents}")

    base_expected = {}
    for name in TS_FIELDS:
        v = to_filetime(getattr(base_spec, name))
        base_expected[name] = {
            "filetime": v,
            "decoded_utc": (EPOCH + _dt.timedelta(microseconds=v // 10)
                            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unix": v / 10_000_000 - 11_644_473_600,
        }

    for cid, iv in ICON_CASES:
        b = bytearray(base_data)
        struct.pack_into("<i", b, icon_off, iv)
        path = OUT / f"{cid}.lnk"
        path.write_bytes(bytes(b))
        manifest["cases"][cid] = {
            "file": path.name, "kind": "icon_index",
            "represents": f"IconIndex = {iv} (signed 32-bit per MS-SHLLINK)",
            "expectation": f"return {iv}",
            "expected_icon_index": iv,
            "misread_if_unsigned": struct.unpack("<I", struct.pack("<i", iv))[0],
            "expected_fields": base_expected,
        }
        print(f"  {cid}  {path.name:<10} IconIndex = {iv}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n{len(manifest['cases'])} cases written to {OUT}")


if __name__ == "__main__":
    main()
